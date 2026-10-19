"""ROUTER_FIXES_ROUND2.md 2.3: confident-wrong intents on the reviewer's fresh set. DEV fixtures, tuned on. Offline, no model."""
import pytest

from tests.auth_helpers import new_client

# (message, intent, draft expected, text the reply must contain)
ROWS = [
    ("get the mobile bill done", "pay_obligation", True, "Shenzhen Mobile"),
    ("need to clear my phone recharge", "pay_obligation", True, "Shenzhen Mobile"),
    ("clear my mobile top up", "pay_obligation", True, "Shenzhen Mobile"),
    ("I'd better pay the accommodation before the 1st", "pay_obligation", True, "Chen Wei"),
    ("pay the accommodation before the 5th", "pay_obligation", True, "Chen Wei"),
    ("學費付一下", "pay_obligation", True, "University X"),
    ("房租付一下", "pay_obligation", True, "Chen Wei"),
    ("月租帮我交一下", "pay_obligation", True, "Chen Wei"),
    ("wallet total in rupees?", "balance", False, "₹"),
    ("how much do I need to pay in total", "obligations", False, "open bills"),
    ("has the university got my money", "status", False, ""),
    ("who is my landlord", "info", False, "Chen Wei"),
    ("what is my landlord's name", "info", False, "****0001"),
    ("is my bank ripping me off on the rate", "markup_check", False, "markup"),
    ("is the bank overcharging me on the rate", "markup_check", False, "markup"),
    ("how much is the bank charging me in hidden fees", "markup_check", False, "markup"),
    ("what will the university get if I send 100000 rupees", "routes", False, "cheapest"),
    ("what's 1 yuan in rupees", "rate", False, "rate"),
    ("give my landlord proof that I always pay on time", "share_record", False, ""),
    ("make something I can send to my lender", "share_record", False, ""),
    ("I'm a bit short this month", "runway", False, "short"),
    ("I can't afford rent this month", "runway", False, ""),
    ("I need 500 dollars", "fx_bill", False, "500 USD"),
]


@pytest.mark.parametrize("m,intent,draft,text", ROWS, ids=[r[0] for r in ROWS])
def test_round2_wrong_answer_rows(m, intent, draft, text):
    st = new_client("student")
    st.post("/api/reset")
    j = st.post("/api/chat", json={"message": m}).json()
    assert j["intent"] == intent, j["reply"][:200]
    assert bool(j.get("pending_id")) is draft and j["money_moved"] == 0
    assert text in j["reply"]
