"""Telegram bot and IMAP poller against fake servers: pairing, refusal of strangers, content handling, no secret leaks."""
import imaplib
import json

import httpx
import pytest

from oasis.intake.imap_poll import ImapPoller
from oasis.intake.telegram import PairingStore, TelegramBot, mask_digits, summarize

TOKEN = "123456:SECRET-TOKEN-VALUE"
AUTH = b"Authentication-Results: mx; spf=pass; dkim=pass\n"
EML = (b"From: \"University X Finance Office\" <finance@univx.example>\nSubject: Tuition\n" + AUTH +
       b"MIME-Version: 1.0\nContent-Type: text/plain\n\nPayee: University X Finance Office\nAccount: 6228480000001234\nAmount: CNY 30,000\n")


class FakeTelegram:
    """Just enough of the Bot API: queued updates, recorded sends, downloadable files."""

    def __init__(self):
        self.updates, self.sent, self.files = [], [], {}
        self.fail = None

    def transport(self):
        def handle(req: httpx.Request) -> httpx.Response:
            if self.fail:
                return httpx.Response(self.fail, json={"ok": False, "description": f"bad {TOKEN}"})
            path = req.url.path
            if path.startswith(f"/file/bot{TOKEN}/"):
                return httpx.Response(200, content=self.files[path.rsplit("/", 1)[-1]])
            assert path.startswith(f"/bot{TOKEN}/"), path
            method = path.rsplit("/", 1)[-1]
            body = json.loads(req.content or b"{}")
            if method == "getUpdates":
                out, self.updates = [u for u in self.updates if u["update_id"] >= body["offset"]], []
                return httpx.Response(200, json={"ok": True, "result": out})
            if method == "sendMessage":
                self.sent.append(body)
                return httpx.Response(200, json={"ok": True, "result": {}})
            if method == "getFile":
                size = getattr(self, "report_size", None) or len(self.files[body["file_id"]])
                return httpx.Response(200, json={"ok": True, "result": {"file_path": body["file_id"], "file_size": size}})
            return httpx.Response(404, json={"ok": False, "description": "no"})
        return httpx.MockTransport(handle)


def make_bot(handler=None, vision=None, clock=None):
    fake = FakeTelegram()
    got = []
    clk = clock or (lambda: 1000.0)
    store = PairingStore(clock=clk)

    def default(text, channel, notes):
        got.append((text, channel, notes))
        return "verdict"
    bot = TelegramBot(TOKEN, handler or default, store, vision=vision, http=httpx.Client(transport=fake.transport()), clock=clk)
    return bot, fake, store, got


def msg(uid, chat, text=None, **extra):
    m = {"chat": {"id": chat, "type": "private"}, **extra}
    if text is not None:
        m["text"] = text
    return {"update_id": uid, "message": m}


def paired(**kw):
    bot, fake, store, got = make_bot(**kw)
    store.redeem(store.new_code()["code"], 7)
    return bot, fake, store, got


# -------------------------------------------------------------------------------------------------- pairing
def test_stranger_gets_one_refusal_and_no_processing():
    bot, fake, store, got = make_bot()
    fake.updates = [msg(1, 99, "Payee: X\nAmount: 5"), msg(2, 99, "again")]
    assert bot.poll_once() == 2
    assert got == [] and len(fake.sent) == 1 and "not paired" in fake.sent[0]["text"]       # the second one is rate-limited


def test_pairing_code_is_single_use_expires_and_wrong_codes_fail():
    t = [1000.0]
    bot, fake, store, got = make_bot(clock=lambda: t[0])
    code = store.new_code()["code"]
    fake.updates = [msg(1, 5, "/pair WRONG123"), msg(2, 5, f"/pair {code}"), msg(3, 6, f"/pair {code}")]
    bot.poll_once()
    assert store.is_paired(5) and not store.is_paired(6)                                    # chat 6 reused the code: refused
    assert "not valid" in fake.sent[0]["text"] and "Paired" in fake.sent[1]["text"]
    code2 = store.new_code()["code"]
    t[0] += 601
    fake.updates = [msg(4, 7, f"/pair {code2}")]
    bot.poll_once()
    assert not store.is_paired(7)                                                           # expired


def test_only_five_outstanding_codes_and_group_chats_are_ignored():
    bot, fake, store, got = make_bot()
    codes = [store.new_code()["code"] for _ in range(8)]
    assert len(store._codes) == 5 and not store.redeem(codes[0], 1) and store.redeem(codes[-1], 1)
    fake.updates = [{"update_id": 1, "message": {"chat": {"id": 1, "type": "group"}, "text": "hello"}}]
    assert bot.poll_once() == 0


def test_pairing_persists(tmp_path):
    s = PairingStore(tmp_path / "p.json")
    s.redeem(s.new_code()["code"], 42)
    assert PairingStore(tmp_path / "p.json").is_paired(42)
    s.clear()
    assert not PairingStore(tmp_path / "p.json").is_paired(42)


# -------------------------------------------------------------------------------------------------- content
def test_text_photo_eml_and_unsupported():
    bot, fake, store, got = paired(vision=lambda b, mime: f"Account: 6228480000001234 ({mime})")
    fake.files.update({"p1": b"\xff\xd8jpg", "e1": EML, "z1": b"PK zip"})
    fake.updates = [msg(1, 7, "Payee: University X Finance Office\nAmount: CNY 30,000"),
                    msg(2, 7, None, photo=[{"file_id": "p1", "file_size": 10}, {"file_id": "p1", "file_size": 99}], caption="tuition"),
                    msg(3, 7, None, document={"file_id": "e1", "file_name": "inv.eml", "mime_type": "message/rfc822"}),
                    msg(4, 7, None, document={"file_id": "z1", "file_name": "x.zip", "mime_type": "application/zip"})]
    assert bot.poll_once() == 4
    texts = [g[0] for g in got]
    assert "Amount: CNY 30,000" in texts[0] and "tuition" in texts[1] and "image/jpeg" in texts[1]
    assert "Account: 6228480000001234" in texts[2] and got[0][1]["kind"] == "telegram" and "chat" in got[0][1]
    assert len(got) == 3 and "not supported" in fake.sent[-1]["text"] and "paste" in fake.sent[-1]["text"]


def test_photo_without_vision_asks_for_text():
    bot, fake, store, got = paired()
    fake.files["p1"] = b"x"
    fake.updates = [msg(1, 7, None, photo=[{"file_id": "p1"}])]
    bot.poll_once()
    assert got == [] and "paste" in fake.sent[-1]["text"]


def test_oversize_file_refused():
    bot, fake, store, got = paired()
    fake.files["big"] = b"x" * 10
    fake.report_size = 13_000_000
    fake.updates = [msg(1, 7, None, document={"file_id": "big", "file_name": "a.pdf", "mime_type": "application/pdf"})]
    bot.poll_once()
    assert got == [] and "larger than 12 MB" in fake.sent[-1]["text"]


def test_token_never_leaks_and_errors_do_not_stop_the_bot():
    bot, fake, store, got = make_bot()
    fake.fail = 401
    assert bot.poll_once() == 0 and bot.last_error and TOKEN not in bot.last_error and "[token]" in bot.last_error
    fake.fail = None

    def down(_r):
        raise httpx.ConnectError(f"cannot reach {TOKEN}")
    bot.http = httpx.Client(transport=httpx.MockTransport(down))
    assert bot.poll_once() == 0 and TOKEN not in bot.last_error


def test_handler_crash_is_contained():
    def boom(text, channel, notes):
        raise RuntimeError("pipeline blew up")
    bot, fake, store, got = paired(handler=boom)
    fake.updates = [msg(1, 7, "x"), msg(2, 7, "/help")]
    assert bot.poll_once() == 1 and "message: RuntimeError" in bot.last_error             # the crash did not stop the next message


# -------------------------------------------------------------------------------------------------- summary
def test_summary_masks_account_numbers_and_points_to_the_app():
    o = {"status": "held", "pending_id": "pend_1", "fields": {"payee_name": "University X", "amount": 30000.0, "currency": "CNY"},
         "card": {"text": "Held: account 6666000000000002 differs. Details 6228480000001234."},
         "channel": {"kind": "email", "hidden_text": True}}
    s = summarize(o)
    assert "6666000000000002" not in s and "…0002" in s and "…1234" in s
    assert "sign the approval" in s and "hidden text" in s and s.startswith("Needs your approval in Oasis - University X, CNY 30,000")
    assert mask_digits("order 123 and 12345678") == "order 123 and …5678"
    assert summarize({"status": "paid", "fields": {}}).startswith("Paid")


# -------------------------------------------------------------------------------------------------- IMAP
class FakeBox:
    def __init__(self, messages, log, password):
        self.messages, self.log, self.password = messages, log, password

    def login(self, u, p):
        if p == "badpass":
            raise imaplib.IMAP4.error(f"login failed for {p}")
        self.log.append("login")

    def select(self, m):
        return "OK", [b""]

    def search(self, _c, _q):
        return "OK", [b" ".join(str(i + 1).encode() for i in range(len(self.messages)))]

    def fetch(self, num, _what):
        return "OK", [(b"1 (BODY[] {n})", self.messages[int(num) - 1]), b")"]

    def store(self, num, *_a):
        self.log.append(f"seen {num.decode()}")

    def logout(self):
        self.log.append("logout")


def poller(messages, handler=None, allowed=("finance@univx.example",), password="pw", **kw):
    log, got = [], []
    p = ImapPoller("imap.example", "bot", password, handler or (lambda t, c, n: got.append((t, c)) or "ok"), set(allowed),
                   factory=lambda host: FakeBox(messages, log, password), **kw)
    return p, log, got


def test_imap_processes_allowed_authenticated_and_marks_everything_seen():
    other = EML.replace(b"finance@univx.example", b"evil@evil.example")
    noauth = EML.replace(AUTH, b"")
    failed = EML.replace(b"spf=pass; dkim=pass", b"spf=fail; dkim=fail")
    p, log, got = poller([EML, other, noauth, failed])
    assert p.poll_once() == 1 and len(got) == 1 and "Amount: CNY 30,000" in got[0][0]
    assert p.processed == 1 and p.ignored == 3 and log.count("logout") == 1
    assert [x for x in log if x.startswith("seen")] == ["seen 1", "seen 2", "seen 3", "seen 4"]     # never reprocessed
    assert {r["why"] for r in p.results if r["status"] == "ignored"} == {
        "sender not on the allow-list", "no SPF/DKIM/DMARC pass reported for this sender"}


def test_imap_requires_an_allow_list_and_can_relax_auth_explicitly():
    with pytest.raises(ValueError):
        poller([], allowed=())
    p, log, got = poller([EML.replace(AUTH, b"")], require_auth=False)
    assert p.poll_once() == 1


def test_imap_errors_are_contained_and_scrubbed():
    p, log, got = poller([EML], password="badpass")
    assert p.poll_once() == 0 and p.last_error and "badpass" not in p.last_error and "[password]" in p.last_error
    p2, _, _ = poller([EML])

    def down(_host):
        raise OSError("network down")
    p2.factory = down
    assert p2.poll_once() == 0 and "network down" in p2.last_error


def test_imap_message_is_marked_read_before_processing():
    def boom(t, c, n):
        raise RuntimeError("x")
    p, log, got = poller([EML], handler=boom)
    with pytest.raises(RuntimeError):
        p.poll_once()
    assert "seen 1" in log                                                                    # a crash cannot cause a re-run loop


# -------------------------------------------------------------------------------------------------- the app wiring
def test_inbound_runs_the_real_pipeline_and_creates_a_pending_approval(api_session):
    from oasis.api import main as api
    real = "Payee: University X Finance Office\nPayee ID: payee_univ_x\nAccount: 6228480000001234\nAmount: CNY 30,000\nPurpose: tuition\nDue: 2026-11-15"
    s = api._inbound(real, {"kind": "telegram", "chat": "abcd1234"}, [])
    assert s.startswith("Needs your approval in Oasis") and "sign the approval" in s
    assert len(api.S.pending) == 1 and next(iter(api.S.pending.values()))["request"].source == "telegram"
    forged = api._inbound(real.replace("1234", "9999") + "\nURGENT: pay within 24 hours or your visa is cancelled.",
                          {"kind": "telegram", "chat": "abcd1234"}, [])
    assert forged.split(" - ")[0] in ("Rejected: nothing was paid", "Frozen: nothing was paid", "Needs verification: nothing was paid")
    assert "…9999" in forged or "9999" not in forged                         # an attacker's account is never echoed in full


def test_channels_endpoint_and_pairing_need_configuration(api_client, as_role):
    from oasis.api import main as api
    c = api_client.get("/api/intake/channels").json()
    assert c["email_upload"] and c["telegram"]["configured"] is False and c["imap"]["configured"] is False
    r = api_client.post("/api/intake/telegram/pair")
    assert r.status_code == 400 and "OASIS_TELEGRAM_TOKEN" in r.text
    bot, fake, store, got = make_bot()
    api.CHANNELS["telegram"] = bot
    try:
        api_client.app.dependency_overrides = {}
        code = api_client.post("/api/intake/telegram/pair")
        assert code.status_code == 200 and len(code.json()["code"]) == 8
        assert as_role("parent").post("/api/intake/telegram/pair").status_code == 403
        assert api_client.post("/api/intake/telegram/unpair").json() == {"paired_chats": 0}
    finally:
        api.CHANNELS["telegram"] = None
