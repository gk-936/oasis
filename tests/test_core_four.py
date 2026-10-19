"""Core-four phrasings (remittances, tuition, credit building, multi-currency) that used to end in a menu, a generic reply or 'CNY 0 to ?'.
Each must reach the right answer in one turn, and none may move money or create a draft."""
import pytest

from tests.auth_helpers import new_client

CASES = [
    ("is it better to use a bank or a remittance app", "routes", "bank wire"),
    ("bank vs remittance app?", "routes", "bank wire"),
    ("how long will a transfer to China take", "routes", "day(s)"),
    ("how many days does a remittance take to arrive", "routes", "day(s)"),
    ("is this invoice real? it says pay 30000 to account 6222000011112222", "scam_check", "registry"),
    ("is this email authentic? pay 5000 to account 6222000011112222 for your fees", "scam_check", "registry"),
    ("I got an email saying the university's bank account changed", "faq", "registry"),
    ("my landlord says the bank account details changed, is that ok", "faq", "registry"),
    ("can I show my landlord that I pay on time", "share_record", "Trust Pass"),
    ("how many of my payments were on time", "credit", "on time"),
    ("what should I do next to improve my record", "credit", "Next step"),
    ("I'm a new international student, where do I start?", "help", "four things"),
    ("getting started", "help", "four things"),
    ("Am I overspending?", "finance_summary", "Open bills"),
    ("Give me a summary of my finances", "finance_summary", "Balances"),
    ("how am I doing this month?", "finance_summary", "Payment record"),
    ("what if it arrives short?", "transfer_issue", "top-up"),
]


@pytest.fixture()
def st():
    return new_client("student")


@pytest.mark.parametrize("msg,intent,needle", CASES)
def test_core_four_phrasing(st, msg, intent, needle):
    j = st.post("/api/chat", json={"message": msg}).json()
    assert j["intent"] == intent, j["reply"]
    assert needle in j["reply"], j["reply"]
    assert j["status"] in ("info", "done") and j["money_moved"] == 0 and not j["pending_id"]
    assert "CNY 0 to ?" not in j["reply"] and "didn't catch" not in j["reply"]
    assert st.get("/api/state").json()["ledger_money_lost"] == 0


def test_low_confidence_invoice_asks_instead_of_printing_cny_0(st):
    j = st.post("/api/chat", json={"message": "invoice 30000 account 6222000011112222"}).json()
    assert "CNY 0 to ?" not in j["reply"] and j["money_moved"] == 0


def test_instalments_offer_equal_parts_and_a_normal_confirmation(st):
    for msg, n in (("Pay tuition in installments", 2), ("split my tuition into two payments", 2), ("pay my tuition in 3 parts", 3)):
        j = st.post("/api/chat", json={"message": msg}).json()
        assert j["status"] == "needs_confirmation" and f"part 1 of {n}" in j["reply"] and not j["pending_id"], j["reply"]
        assert f"CNY {30000 // n:,}" in j["reply"]


@pytest.mark.parametrize("msg", ["Send 5000 yuan to my mother in India", "I want to send 20000 INR to my friend Li Wei in China",
                                 "Forward 50000 to my cousin, acct 99887766"])
def test_unregistered_person_is_explained_and_never_paid(st, msg):
    j = st.post("/api/chat", json={"message": msg}).json()
    assert j["status"] in ("rejected", "info", "needs_info") and not j["pending_id"] and j["money_moved"] == 0
    assert "99887766" not in j["reply"]
    if "cousin" not in msg:
        assert "registry" in j["reply"] and "plan my semester" in j["reply"]


def test_paying_a_paid_bill_says_so(st):
    from tests.auth_helpers import Approver
    ap = Approver(st, "student")
    d = st.post("/api/chat", json={"message": "pay my rent"}).json()
    assert d["status"] == "held"
    assert ap.approve(d["pending_id"]).status_code == 200
    j = st.post("/api/chat", json={"message": "pay my rent"}).json()
    assert "already paid" in j["reply"] and j["money_moved"] == 0 and not j["pending_id"]


def test_bare_yes_binds_to_the_last_offer_not_an_unrelated_draft(st):
    st.post("/api/chat", json={"message": "pay my rent"})
    q = st.post("/api/chat", json={"message": "how many yuan for 90000 rupees?"}).json()
    assert q["intent"] == "convert" and not q["pending_id"]
    j = st.post("/api/chat", json={"message": "yes"}).json()
    assert "conversion quote" in j["reply"] and j["money_moved"] == 0
    j2 = st.post("/api/chat", json={"message": "yes"}).json()           # the offer is spent: the next "yes" is about the waiting draft
    assert "conversion quote" not in j2["reply"] and j2["money_moved"] == 0


def test_activity_feed_chat_and_endpoint(st):
    st.post("/api/reset")
    j = st.post("/api/chat", json={"message": "what did you do for me?"}).json()
    assert j["intent"] == "activity" and "haven't done anything" in j["reply"]
    st.post("/api/chat", json={"message": "pay my tuition"})
    j = st.post("/api/chat", json={"message": "what did you do for me?"}).json()
    assert "Held for you" in j["reply"] and j["money_moved"] == 0
    r = st.get("/api/activity").json()
    assert set(r) == {"acted_alone", "proposed_or_approved", "held", "refused"} and r["held"]


def test_activity_feed_shows_autonomous_actions(st):
    st.post("/api/autonomy/tick", json={"days": 30})
    r = st.get("/api/activity").json()
    assert r["acted_alone"] or r["held"]


@pytest.mark.parametrize("msg,needle", [("what is a swift code", "SWIFT"), ("what is a nonce", "one-time"), ("what does MOCK mean here", "simulated"),
                                        ("what is FlightPath", "never resends"), ("what currencies do you support", "INR, CNY"),
                                        ("who made you", "Oasis"), ("how do I use this", "plan my semester")])
def test_concept_questions_get_fixed_answers(st, msg, needle):
    j = st.post("/api/chat", json={"message": msg}).json()
    assert needle in j["reply"] and j["money_moved"] == 0 and not j["pending_id"] and j["intent"] != "unknown"


def test_compound_request_walks_steps_one_at_a_time(st):
    a = st.post("/api/chat", json={"message": "convert 20000 INR to CNY and pay my tuition"}).json()
    assert a["intent"] == "convert" and "Next in your list" in a["reply"] and not a["pending_id"]
    st.post("/api/chat", json={"message": "yes"})
    b = st.post("/api/chat", json={"message": "next"}).json()
    assert b["intent"] == "pay_obligation" and b["status"] == "held" and b["money_moved"] == 0
