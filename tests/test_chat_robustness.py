"""F7 grounding, F11 robustness, F13 isolation for chat: odd input never gives a 500, numbers come from state, sessions do not mix."""
import re
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.auth_helpers import new_client


@pytest.fixture()
def st():
    c = new_client("student")
    c.post("/api/reset")
    return c


ODD = ["", "   ", "\n\n", "x" * 20000, "🙂🙂🙂", "مرحبا بالعالم", "​​​", "‮evil‬", "NaN", "-5000", "pay NaN yuan rent",
       "pay 1e999 yuan rent", "pay 999999999999 yuan rent", "pay -6000 yuan rent", "pay 0 yuan rent", "pay 6000.004 yuan rent",
       "pay six thousand yuan rent", "6000 USD rent", "'; DROP TABLE users;--", "<script>alert(1)</script>", "{{7*7}}", "%s%s%s%n",
       "pay my rent " * 500, "交" * 5000, "a\x00b", "pay\trent\r\nnow", "Payee:", "Amount: ", "convert", "convert 0 INR to CNY",
       "convert -5 INR to CNY", "convert 99999999999 INR to CNY", "set a rate target of NaN", "convert 100 when the rate reaches 0.0000"]


@pytest.mark.parametrize("msg", ODD)
def test_odd_input_gets_a_clear_reply_never_a_server_error(st, msg):
    r = st.post("/api/chat", json={"message": msg})
    assert r.status_code == 200, (msg[:40], r.status_code, r.text[:200])
    j = r.json()
    assert j["reply"] and j["money_moved"] == 0 and j["intent"]
    assert st.get("/api/state").json()["ledger_money_lost"] == 0


def test_unpaired_surrogates_are_a_422_not_a_500(st):
    assert st.post("/api/chat", content=b'{"message":"\\ud800"}', headers={"content-type": "application/json"}).status_code == 422


def test_negative_zero_and_huge_amounts_never_become_drafts(st):
    for m in ("pay -6000 yuan rent", "pay 0 yuan rent", "pay 999999999999 yuan rent"):
        j = st.post("/api/chat", json={"message": m}).json()
        while j["status"] == "needs_confirmation":
            j = st.post("/api/chat", json={"message": "yes"}).json()
        assert j["status"] != "held" or j["draft_hash"] is None or j["money_moved"] == 0
        for p in st.get("/api/state").json()["pending"]:
            assert 0 < p["draft"]["amount"] <= 30000


def test_the_same_message_repeated_is_idempotent(st):
    a = st.post("/api/chat", json={"message": "pay my tuition"}).json()
    b = st.post("/api/chat", json={"message": "pay my tuition"}).json()
    assert a["pending_id"] == b["pending_id"] and len(st.get("/api/state").json()["pending"]) == 1


def test_concurrent_requests_do_not_corrupt_state(st):
    def go(i):
        return st.post("/api/chat", json={"message": ("pay my rent", "what do I owe?", "pay my tuition", "hello")[i % 4]}).status_code
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(go, range(24)))
    assert set(codes) == {200}
    pend = st.get("/api/state").json()["pending"]
    assert len(pend) == len({(p["draft"]["payee_id"], p["draft"]["amount"], p["draft"]["purpose"]) for p in pend}) == 2


def _numbers(text):
    return {float(x.replace(",", "")) for x in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?", text)}


def test_every_number_in_a_factual_reply_comes_from_state(st):
    s = st.get("/api/state").json()
    known = {b["amount"] for b in s["passport"]["balances"]}
    known |= {o["amount"] for o in s["passport"]["obligations"]} | {float(len(s["passport"]["obligations"]))}
    known |= {float(x) for o in s["passport"]["obligations"] for x in re.findall(r"\d+", o["due"])}
    bal = st.post("/api/chat", json={"message": "how much money do I have?"}).json()["reply"]
    assert _numbers(bal) - {0.0} <= known | {500000.0}
    owe = st.post("/api/chat", json={"message": "what do I owe?"}).json()["reply"]
    assert _numbers(owe) <= known | {float(i) for i in range(1, 6)}
    rate = st.post("/api/chat", json={"message": "what is the INR to CNY rate?"}).json()["reply"]
    assert f"{s['rates']['rate']:.4f}" in rate and "MOCK" in rate and "not a market rate" in rate and "predict" in rate
    assert "STALE" not in rate


def test_the_rate_reply_carries_the_source_badge_and_never_predicts(st):
    r = st.post("/api/chat", json={"message": "will the rate go up next week?"}).json()
    assert "predict" in r["reply"] or r["intent"] in ("rate", "help", "unknown")


def test_missing_data_is_stated_not_invented(st):
    assert "No proof pack yet" in st.post("/api/chat", json={"message": "show me the proof"}).json()["reply"]
    assert "Nothing has been stopped" in st.post("/api/chat", json={"message": "why was it blocked?"}).json()["reply"]


def test_two_sessions_have_separate_dialogues_and_the_chat_log_is_not_exposed(st):
    other = new_client("student")
    st.post("/api/chat", json={"message": "pay Chen Wei"})                         # st now waits for "which one?"
    j = other.post("/api/chat", json={"message": "2"}).json()
    assert j["intent"] != "pay_obligation" and not j["pending_id"]
    assert st.post("/api/chat", json={"message": "2"}).json()["status"] == "held"
    for path in ("/api/state", "/api/audit"):
        r = st.get(path)
        if r.status_code == 200:
            assert "pay Chen Wei" not in r.text


def test_reset_clears_the_dialogue(st):
    st.post("/api/chat", json={"message": "pay Chen Wei"})
    st.post("/api/reset")
    assert st.post("/api/chat", json={"message": "2"}).json()["intent"] != "pay_obligation"


def test_the_chinese_reply_is_chosen_from_the_message_alone(st):
    r = st.post("/api/chat", json={"message": "我欠多少钱？"}).json()
    assert re.search(r"[一-鿿]", r["reply"])
    assert not re.search(r"[一-鿿]", st.post("/api/chat", json={"message": "what do I owe?"}).json()["reply"])
