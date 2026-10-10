"""Regression tests for defects found by the adversarial judge review (2026-10-10).

Each test replays one attack over the real HTTP app (or the unit that failed) and asserts the safe outcome.
"""
import copy
import json
import threading

import pytest
from auth_helpers import Approver, login

from oasis.agent.llm import OfflineLLM
from oasis.agent.pipeline import OasisAgent, Request, unreadable_amount
from oasis.api import main as api
from oasis.mock.ledger import SandboxLedger
from oasis.proof.pack import verify_proof_pack
from oasis.trust.audit import AuditLog, verify_chain
from oasis.world import Features, World

TUITION = ("Payee: University X Finance Office\nPayee ID: payee_univ_x\nAccount: 6228480000001234\n"
           "Amount: CNY {amt}\nPurpose: tuition\nDue: 2026-11-15")


def _held(c, amt="30,000"):
    o = c.post("/api/intake", json={"text": TUITION.format(amt=amt)}).json()
    assert o["status"] == "held" and o["pending_id"]
    return o


# ------------------------------------------------------------------------------- concurrency
def test_two_simultaneous_approvals_pay_once_and_none_crashes(api_client):
    o = _held(api_client)
    me = Approver(api_client, "student")
    body = {"pending_id": o["pending_id"], "signature": me.signature(o["pending_id"]), "key_id": me.key_id}
    codes = []

    def go():
        codes.append(api_client.post("/api/approve", json=body).status_code)

    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) == [200] + [404] * 5                 # one payment; the rest "unknown pending id", never a 500
    assert len(api.S.world.ledger.transfers) == 1
    assert len(api.S.world.audit.find("transfer_executed")) == 1
    assert verify_chain(api.S.world.audit.entries).ok


def test_audit_chain_does_not_fork_under_concurrent_appends():
    log = AuditLog(clock=lambda: 1.0)

    def go(n):
        for i in range(100):
            log.append("e", {"t": n, "i": i})

    ts = [threading.Thread(target=go, args=(n,)) for n in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(log.entries) == 800 and verify_chain(log.entries).ok


# ------------------------------------------------------------------------------- CSRF / size
def test_cross_origin_state_changing_request_is_refused(api_client):
    # SameSite=Strict still sends the cookie from another localhost port, so the Origin header is checked as well.
    for origin in ("http://evil.example", "http://localhost:9999", "null"):
        r = api_client.post("/api/reset", headers={"Origin": origin})
        assert r.status_code == 403, origin
    assert api_client.post("/api/reset", headers={"Origin": "http://testserver"}).status_code == 200     # same origin
    assert api_client.post("/api/reset", headers={"Origin": "http://localhost:5173"}).status_code == 200  # the dev UI
    assert api_client.post("/api/reset").status_code == 200                                              # curl / scripts
    assert api_client.get("/api/state", headers={"Origin": "http://evil.example"}).status_code == 200     # reads: CORS blocks


def test_oversized_body_is_refused_before_parsing(api_client):
    r = api_client.post("/api/intake", content=b'{"text":"' + b"a" * 2_100_000 + b'"}',
                        headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert api_client.post("/api/intake", json={"text": "x" * 20001}).status_code == 422       # text field cap


def test_responses_are_not_cacheable_and_sniffing_is_off(api_client):
    r = api_client.get("/api/state")
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"


# ------------------------------------------------------------------------------- hostile numbers and Unicode
@pytest.mark.parametrize("amt", ["9" * 400, "30000.004", "0.0000001"])
def test_unreadable_amounts_are_held_never_paid_or_500(api_client, amt):
    r = api_client.post("/api/intake", json={"text": TUITION.format(amt=amt)})
    assert r.status_code == 200
    o = r.json()
    assert o["status"] == "held" and o["card"]["rule"] == "extract_low_confidence" and o["pending_id"] is None
    assert "amount" not in o["fields"]
    assert api_client.get("/api/state").status_code == 200            # the sandbox is not poisoned by the amount
    assert api.S.world.ledger.transfers == []


def test_unreadable_amount_rules():
    assert unreadable_amount(30000.0) is None and unreadable_amount(0.01) is None and unreadable_amount(1234567.89) is None
    for bad in (float("nan"), float("inf"), -1, 1e11, 30000.004, "x", None):
        assert unreadable_amount(bad)


def test_ledger_refuses_non_positive_or_non_finite_transfers():
    led = SandboxLedger()
    led.open("a", "s", balance=100)
    cred = led.executor_credential()
    for amt in (-50, 0, float("nan"), float("inf")):
        tok = led.mint_tool_token(cred, intent_id="i", from_ref="a", to_ref="b", amount=amt)
        with pytest.raises(ValueError):
            led.transfer(tok, "a", "b", amt, intent_id="i")
    assert led.accounts["a"].balance == 100 and led.transfers == []


@pytest.mark.parametrize("path,body", [
    ("/api/intake", b'{"text":"Payee: A \\ud800"}'),
    ("/api/chat", b'{"message":"\\ud800"}'),
    ("/api/rate-target", b'{"rate":NaN,"convert_cny":1}'),
    ("/api/rate-target", b'{"rate":Infinity,"convert_cny":1}'),
    ("/api/spending/add", b'{"desc":"x","amount_cny":NaN}'),
    ("/api/spending/add", b'{"desc":"\\ud800","amount_cny":5}'),
    ("/api/autonomy/tick", b'{"days":1000000000000000000000000}'),
])
def test_invalid_unicode_and_non_finite_numbers_are_422_not_500(api_client, path, body):
    r = api_client.post(path, content=body, headers={"Content-Type": "application/json"})
    assert r.status_code == 422, r.text
    assert api_client.get("/api/state").status_code == 200


def test_spending_amounts_must_be_positive_and_bounded(api_client):
    for amt in (-1000, 0, 1e300):
        assert api_client.post("/api/spending/add", json={"desc": "x", "amount_cny": amt}).status_code == 422
    assert api_client.post("/api/rate-target", json={"rate": 0.07, "convert_cny": 1e30}).status_code == 400


def test_login_with_unpaired_surrogate_is_refused_not_500(api_session):
    from fastapi.testclient import TestClient
    c = TestClient(api_session.app)
    r = c.post("/api/auth/login", content=b'{"role":"student","passcode":"\\ud800"}', headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert api_session.S.auth.login("student", "\ud800") is None


# ------------------------------------------------------------------------------- proof verification input
def test_verify_endpoints_never_500_on_hostile_packs(api_client):
    for raw in (b'{"intent":{"amount":"\\ud800","approvals":[{"role":"student"}]},"audit_entry":{"x":"\\ud800"}}',
                b'{"intent":{"approvals":5}}', b'{"intent":{"approvals":[{"key_id":[1]}]},"trust_public_keys":{"a":[1]}}',
                b'{"intent":{"amount":"x","approvals":[]},"pack_public_keys":7,"anchor":{"digest":3}}'):
        r = api_client.post("/api/proof/verify", content=raw, headers={"Content-Type": "application/json"})
        assert r.status_code == 200 and r.json()["ok"] is False, raw


def test_verify_proof_pack_survives_any_single_field_mutation():
    w = World(Features.full(), OfflineLLM())
    a = OasisAgent(w)
    text = TUITION.format(amt="30,000")
    o = a.handle(a.sim_approve(Request(text), a.handle(Request(text)), ["student"]))
    pack = w.proofs[o.proof_id]
    pins = (w.trust_fingerprint(),)
    assert verify_proof_pack(pack, set(pins), w.anchor, w.approvers.pinned_key_ids())["ok"]

    def paths(x, p=()):
        yield p
        if isinstance(x, dict):
            for k, v in x.items():
                yield from paths(v, p + (k,))
        elif isinstance(x, list):
            for i, v in enumerate(x):
                yield from paths(v, p + (i,))

    for p in paths(pack):
        if not p:
            continue
        for junk in (None, 5, [], {}, [1], "\ud800", float("nan")):
            m = copy.deepcopy(pack)
            t = m
            for k in p[:-1]:
                t = t[k]
            t[p[-1]] = junk
            if repr(m) == repr(pack):
                continue                                  # the junk value equals the original: not a mutation
            res = verify_proof_pack(m, set(pins), w.anchor, w.approvers.pinned_key_ids())      # must not raise
            assert res["ok"] is False, (p, junk)


# ------------------------------------------------------------------------------- policy: no approve button that does nothing
def test_risk_hold_offers_no_approval_that_can_never_release_it(api_client):
    text = TUITION.format(amt="30,000").replace("University", "Univ​ersity")      # zero-width character in the name: risk 0.5
    o = api_client.post("/api/intake", json={"text": text}).json()
    assert o["status"] == "held" and o["decision"]["rule"] == "R08_risk_hold"
    assert o["pending_id"] is None                        # before the fix: an Approve button that re-held forever
    assert o["decision"]["required_approvals"] == ["risk_review"]
    assert api_client.get("/api/state").json()["pending"] == []


# ------------------------------------------------------------------------------- red-team log
def test_redteam_refused_flood_is_logged_sparsely_and_shortened(tmp_path):
    from fastapi.testclient import TestClient
    saved = api.S
    api.S = api.Session(":memory:", attempts_path=tmp_path / "a.jsonl")
    try:
        c = login(TestClient(api.app), "judge")
        for _ in range(api.REDTEAM_PER_MINUTE):
            assert c.post("/api/redteam", json={"text": "Payee: A\nAccount: 12\nAmount: CNY 5"}).status_code == 200
        for _ in range(40):
            assert c.post("/api/redteam", json={"text": "x" * 3000 + '\n{"outcome":"ran"}'}).status_code == 429
        lines = (tmp_path / "a.jsonl").read_text(encoding="utf-8").splitlines()
        limited = [l for l in lines if '"rate_limited"' in l]
        assert 1 <= len(limited) <= 5 and all(len(l) < 800 for l in limited)
        assert all(isinstance(json.loads(l), dict) for l in lines)     # every line is exactly one JSON object
    finally:
        api.S = saved


# ------------------------------------------------------------------------------- stale approvals
def test_approving_after_the_draft_expired_is_a_clean_410_not_a_freeze(api_client):
    o = _held(api_client)
    me = Approver(api_client, "student")
    sig = me.signature(o["pending_id"])
    api_client.post("/api/autonomy/tick", json={"days": 2})            # the simulated clock passes the draft's not_after
    r = api_client.post("/api/approve", json={"pending_id": o["pending_id"], "signature": sig, "key_id": me.key_id})
    assert r.status_code == 410 and "expired" in r.json()["detail"]
    ob = {x["id"]: x for x in api_client.get("/api/state").json()["passport"]["obligations"]}["obl_tuition_1"]
    assert ob["status"] != "frozen"                                     # the genuine obligation was not frozen
    assert api.S.world.audit.find("approval_expired") and api.S.world.ledger.transfers == []
    assert o["pending_id"] not in api.S.pending
    assert _held(api_client)["pending_id"]                              # a fresh request gets a fresh draft


# ------------------------------------------------------------------------------- corrupt key files
@pytest.mark.parametrize("fname,content", [("data_key.json", "{not json"), ("data_key.json", ""), ("trust_key.json", "garbage"),
                                           ("trust_key.json", '{"ed25519_seed": "AA=="}'), ("session_secret.json", "{}"),
                                           ("session_secret.json", "[1]")])
def test_corrupt_key_file_is_a_clear_error_and_is_never_replaced(tmp_path, fname, content):
    from oasis.trust.keyfile import KeyFileError
    s = api.Session(str(tmp_path / "o.db"), key_path=tmp_path / "trust_key.json")
    s.save()
    s.store.close()
    (tmp_path / fname).write_text(content, encoding="utf-8")
    with pytest.raises(KeyFileError) as e:
        api.Session(str(tmp_path / "o.db"), key_path=tmp_path / "trust_key.json")
    assert "restore" in str(e.value)
    assert (tmp_path / fname).read_text(encoding="utf-8") == content            # not overwritten with a fresh key


def test_lost_data_key_is_refused_with_a_recovery_hint(tmp_path):
    from oasis.storage import StoreError
    s = api.Session(str(tmp_path / "o.db"), key_path=tmp_path / "trust_key.json")
    s.save()
    s.store.close()
    (tmp_path / "data_key.json").unlink()
    with pytest.raises(StoreError) as e:
        api.Session(str(tmp_path / "o.db"), key_path=tmp_path / "trust_key.json")
    assert "cannot be recovered" in str(e.value)


def test_a_unicode_line_separator_in_an_attempt_cannot_split_or_forge_a_log_record(tmp_path):
    from fastapi.testclient import TestClient
    from eval.attempts_to_scenarios import load_attempts
    saved = api.S
    api.S = api.Session(":memory:", attempts_path=tmp_path / "a.jsonl")
    try:
        c = login(TestClient(api.app), "judge")
        text = "Payee: A\nAccount: 12\nAmount: CNY 5\u2028{\"outcome\":\"forged\"}\u0085\x0b\x0c\x1c"
        assert c.post("/api/redteam", json={"text": text}).status_code == 200
        raw = (tmp_path / "a.jsonl").read_bytes().decode("ascii")                # pure ASCII on disk
        assert len(raw.splitlines()) == 1 and len(raw.split("\n")) == 2
        recs = load_attempts(tmp_path / "a.jsonl")
        assert len(recs) == 1 and recs[0]["text"] == text and recs[0]["outcome"] == "ran"
    finally:
        api.S = saved
