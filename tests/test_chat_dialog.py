"""Multi-turn chat: slot filling, confirm, correct, cancel, undo, payee mismatch, and the full pay-and-sign cycle."""
import pytest

from tests.auth_helpers import Approver, new_client


@pytest.fixture()
def st():
    c = new_client("student")
    c.post("/api/reset")
    return c


def say(c, m, **h):
    r = c.post("/api/chat", json={"message": m}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def pending(c):
    return {p["id"]: p for p in c.get("/api/state").json()["pending"]}


def test_pay_my_rent_prepares_a_draft_to_the_registered_landlord_and_asks_for_the_signature(st):
    j = say(st, "Pay my rent")
    assert j["intent"] == "pay_obligation" and j["status"] == "held" and j["needs"] == ["student_signature"]
    dr = pending(st)[j["pending_id"]]["draft"]
    assert dr["payee_id"] == "payee_landlord_chen" and dr["account_ref"] == "6222021111110001" and dr["amount"] == 6000
    assert j["draft_hash"] == dr["draft_hash"] and j["money_moved"] == 0
    assert "Chen Wei" in j["reply"] and "****0001" in j["reply"] and "sign" in j["reply"].lower()


def test_full_cycle_chat_draft_then_device_signature_pays_the_registry_account(st):
    assert st.post("/api/fx/convert", json={"amount": 100000, "from": "INR", "to": "CNY"}).status_code == 200
    j = say(st, "pay my rent")
    ap = Approver(st, "student")
    r = ap.approve(j["pending_id"])
    assert r.status_code == 200 and r.json()["status"] == "paid"
    state = st.get("/api/state").json()
    assert state["ledger_money_lost"] == 0 and r.json()["proof_id"] in state["proofs"]
    assert [o["status"] for o in state["passport"]["obligations"] if o["id"] == "obl_rent_1"] == ["paid"]
    st2 = say(st, "did my payment go through?")
    assert st2["intent"] == "status" and "1 bill(s) paid" in st2["reply"]
    assert say(st, "show me the proof")["proof_id"] == r.json()["proof_id"]


def test_repeating_the_same_request_gives_one_draft_not_two(st):
    a, b = say(st, "pay my rent"), say(st, "pay my rent")
    assert a["pending_id"] == b["pending_id"] and len(pending(st)) == 1 and "already" in b["reply"]


def test_ambiguous_request_asks_a_question_then_the_answer_drafts(st):
    q = say(st, "pay Chen Wei")
    assert q["status"] == "needs_info" and q["needs"] == ["info:obligation"] and "rent" in q["reply"] and "deposit" in q["reply"]
    assert not pending(st)
    j = say(st, "the deposit")
    assert j["status"] == "held" and pending(st)[j["pending_id"]]["draft"]["purpose"] == "deposit"


def test_bare_pay_lists_the_open_bills_and_a_number_answers(st):
    q = say(st, "pay")
    assert q["needs"] == ["info:obligation"] and "1)" in q["reply"]
    assert say(st, "1")["status"] == "held"


def test_generic_words_and_currency_mismatch(st):
    assert pending(st) == {} and pending(st) == {}
    j = say(st, "pay the university")
    assert j["status"] == "held" and pending(st)[j["pending_id"]]["draft"]["purpose"] == "tuition"
    q = say(st, "pay 6000 USD rent")
    assert q["status"] == "needs_info" and "USD" in q["reply"] and "CNY" in q["reply"]


def test_an_unknown_name_with_no_matching_bill_lists_who_can_be_paid(st):
    j = say(st, "send 5000 to Alice")
    assert j["status"] == "rejected" and "not a registered payee" in j["reply"] and "Chen Wei" in j["reply"]
    assert not pending(st) and st.get("/api/state").json()["ledger_money_lost"] == 0


def test_unregistered_payee_gets_an_explanation_and_the_registered_one_only_after_yes(st):
    j = say(st, "Please pay Shenzhen University tuition of CNY 26000")
    assert j["status"] == "needs_confirmation" and not pending(st)
    assert "not a registered payee" in j["reply"] and "University X Finance Office" in j["reply"] and "30,000" in j["reply"]
    d = say(st, "yes")
    assert d["status"] == "held" and pending(st)[d["pending_id"]]["draft"]["amount"] == 30000
    assert "chat_unregistered_payee" in [e["kind"] for e in st.get("/api/state").json()["security_feed"]]


def test_unregistered_payee_then_no_pays_nothing(st):
    say(st, "Please pay Shenzhen University tuition of CNY 26000")
    assert say(st, "no")["status"] == "cancelled" and not pending(st)


def test_chat_never_drafts_more_than_the_bill(st):
    for m in ("pay my rent 90000", "pay my tuition CNY 50000", "交房租 九万元"):
        j = say(st, m)
        assert j["status"] == "rejected" and j["refusal"] == "overpayment" and not pending(st) and j["money_moved"] == 0
    assert "chat_refused" in [e["kind"] for e in st.get("/api/state").json()["security_feed"]]


def test_amount_different_from_the_bill_asks_before_drafting(st):
    q = say(st, "pay my tuition 20000")
    assert q["status"] == "needs_confirmation" and not pending(st) and "part payment" in q["reply"]
    j = say(st, "yes")
    assert pending(st)[j["pending_id"]]["draft"]["amount"] == 20000


def test_correction_makes_a_new_draft_and_the_old_signature_no_longer_works(st):
    st.post("/api/fx/convert", json={"amount": 100000, "from": "INR", "to": "CNY"})
    a = say(st, "pay my rent")
    ap = Approver(st, "student")
    old_sig = ap.signature(a["pending_id"])
    b = say(st, "Actually the amount was wrong, it should be 2600")
    assert b["intent"] == "correct" and b["pending_id"] != a["pending_id"] and b["draft_hash"] != a["draft_hash"]
    assert pending(st)[b["pending_id"]]["draft"]["amount"] == 2600 and a["pending_id"] not in pending(st)
    assert st.post("/api/approve", json={"pending_id": a["pending_id"], "signature": old_sig, "key_id": ap.key_id}).status_code == 404
    assert st.post("/api/approve", json={"pending_id": b["pending_id"], "signature": old_sig, "key_id": ap.key_id}).status_code == 403
    assert ap.approve(b["pending_id"]).json()["status"] == "paid"
    assert "declined" in [e["kind"] for e in st.get("/api/state").json()["security_feed"]]


def test_correction_without_a_draft_or_without_an_amount_asks(st):
    assert "no draft" in say(st, "make it 5000")["reply"].lower()
    say(st, "pay my rent")
    assert say(st, "the amount is wrong")["needs"] == ["info:amount"]


def test_cancel_withdraws_the_draft_and_a_second_cancel_says_nothing_is_pending(st):
    a = say(st, "pay my rent")
    c = say(st, "Cancel that payment")
    assert c["status"] == "cancelled" and c["pending_id"] == a["pending_id"] and not pending(st)
    assert "no payment waiting" in say(st, "cancel")["reply"]


def test_undo_before_and_after_payment(st):
    assert "nothing" in say(st, "undo")["reply"].lower()
    st.post("/api/fx/convert", json={"amount": 100000, "from": "INR", "to": "CNY"})
    j = say(st, "pay my rent")
    assert "hasn't been sent" in say(st, "undo that")["reply"]
    Approver(st, "student").approve(j["pending_id"])
    assert "can't be reversed" in say(st, "undo the payment")["reply"]


def test_confirm_with_nothing_pending_does_nothing(st):
    j = say(st, "yes")
    assert j["status"] == "info" and j["money_moved"] == 0


def test_convert_quotes_then_converts_only_after_yes(st):
    q = say(st, "convert 20000 INR to CNY")
    assert q["status"] == "needs_confirmation" and st.get("/api/state").json()["passport"]["balances"][1]["amount"] == 0
    assert say(st, "yes")["status"] == "done"
    assert st.get("/api/state").json()["passport"]["balances"][1]["amount"] > 1000


def test_a_big_conversion_is_not_done_from_chat(st):
    q = say(st, "convert 200000 INR to CNY")
    assert q["status"] == "info" and "auto limit" in q["reply"]
    assert say(st, "yes")["money_moved"] == 0 and st.get("/api/state").json()["passport"]["balances"][1]["amount"] == 0


def test_a_non_answer_drops_the_question_and_is_handled_normally(st):
    say(st, "pay Chen Wei")
    j = say(st, "how much money do I have?")
    assert j["intent"] == "balance"


def test_an_account_number_given_as_the_answer_is_refused(st):
    say(st, "pay Chen Wei")
    j = say(st, "pay account 6666000000000002")
    assert j["money_moved"] == 0 and "6666000000000002" not in j["reply"]
    assert not pending(st)


def test_rate_target_still_works_and_reports_its_fields(st):
    j = say(st, "convert 1500 when the rate reaches 0.0700")
    assert j["intent"] == "rate_target" and j["status"] == "done" and j["target"]["rate"] == 0.07


def test_chinese_flow_replies_in_chinese_without_a_language_header(st):
    j = say(st, "交房租")
    assert j["status"] == "held" and "草稿已就绪" in j["reply"]
    assert "已取消" in say(st, "取消")["reply"]
    assert "您有" in say(st, "你好，我还有多少钱？")["reply"]
