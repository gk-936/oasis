"""Chat completes tasks (pre-submission to-do, sections 3-4): every path ends at a draft for the student's device-key signature or an advice-only answer; nothing moves money."""
from tests.auth_helpers import Approver, new_client


def _client():
    c = new_client("student")
    c.post("/api/reset")
    return c


def _say(c, msg):
    return c.post("/api/chat", json={"message": msg}).json()


def test_usd_bill_in_chat_becomes_a_draft_for_signature():
    c = _client()
    j = _say(c, "I need to pay a USD application fee of 100 dollars")
    assert j["intent"] == "fx_bill" and j["status"] == "held" and j["pending_id"] and j["draft_hash"]
    assert "student_signature" in j["needs"] and "MOCK" in j["reply"] and j["money_moved"] == 0
    assert j["pending_id"] in c.get("/api/state").text            # the draft sits in the normal pending store
    assert "sign" in j["reply"].lower()


def test_usd_bill_without_an_amount_asks_for_it():
    j = _say(_client(), "pay my USD application fee")
    assert j["status"] == "needs_info" and j["pending_id"] is None and j["needs"] == ["info:amount"]


def test_existing_foreign_bill_is_drafted_not_duplicated():
    c = _client()
    c.post("/api/fx/demo-obligation", json={"kind": "us", "amount": 250, "days": 20})
    j = _say(c, "pay my USD fee")
    assert j["status"] == "held" and "USD 250.00" in j["reply"] and "sandbox" not in j["reply"]


def test_how_to_questions_about_usd_bills_do_not_draft():
    j = _say(_client(), "how do I pay a USD bill?")
    assert j["pending_id"] is None and j["status"] != "held"


def test_unsigned_chat_fx_draft_moves_nothing_and_signing_goes_through_the_executor():
    c = _client()
    j = _say(c, "pay my USD application fee of 100 dollars")
    before = c.get("/api/state").json()
    assert j["pending_id"] in {p["id"] for p in before["pending"]}
    r = Approver(c, "student").approve(j["pending_id"])
    body = r.json()
    assert r.status_code == 200 and body["status"] in ("paid", "held", "rejected"), body       # signed once: the executor decides (no USD funds: it stops, nothing is paid)
    assert body["status"] != "paid" or body.get("proof_id")


def test_trust_pass_is_issued_in_chat_and_the_link_verifies():
    c = _client()
    j = _say(c, "share my payment record with my landlord")
    assert j["intent"] == "share_record" and j["status"] == "done" and j["share_link"].startswith("/api/trust-pass/check/")
    assert "landlord" in j["reply"] and "not a credit score" in j["reply"] and j["money_moved"] == 0
    chk = c.get(j["share_link"]).json()
    assert chk["ok"] is True


def test_trust_pass_question_stays_advice():
    j = _say(_client(), "how do I share my payment record?")
    assert j["status"] == "info" and "share_link" not in j


def test_where_is_my_transfer_without_a_journey_reports_the_bill_state():
    j = _say(_client(), "where is my tuition transfer?")
    assert j["intent"] == "where" and "tuition" in j["reply"] and "not paid" in j["reply"] and "in transit" in j["reply"]


def test_where_is_my_transfer_with_a_pending_draft_says_it_has_not_left():
    c = _client()
    _say(c, "pay my tuition")
    j = _say(c, "where is my tuition transfer?")
    assert j["intent"] == "where" and "hasn't left" in j["reply"]


def test_where_is_my_transfer_uses_the_flightpath_journey_when_tracked():
    c = _client()
    r = c.post("/api/flightpath/journeys", json={"route_id": "route_inr_cny_3", "send_inr": 100000, "required_cny": 6500, "due_in_days": 10, "purpose": "tuition"})
    assert r.status_code == 200, r.text
    j = _say(c, "where is my tuition transfer?")
    assert j["intent"] == "where" and j["resend_offered"] is False and "jny_0001" in j["reply"]


def test_plan_then_pay_the_deposit_reaches_a_draft_in_one_conversation():
    c = _client()
    p, d = (_say(c, m) for m in ("plan my semester", "pay the deposit"))
    assert p["intent"] == "plan" and "pay the" in p["reply"] and p["money_moved"] == 0
    assert d["status"] == "held" and d["pending_id"] and "deposit" in d["reply"]


def test_checkin_once_per_session_then_yes_continues_into_the_plan():
    c = _client()
    r = c.get("/api/chat/checkin").json()
    assert r["intent"] == "checkin" and "is due in" in r["reply"] and "short" in r["reply"] and "Want a plan?" in r["reply"] and r["shortfall_cny"] > 0
    assert c.get("/api/chat/checkin").json()["reply"] is None
    y = _say(c, "yes")
    assert y["intent"] == "plan" and y["money_moved"] == 0 and y["pending_id"] is None


def test_checkin_then_no_declines_the_plan():
    c = _client()
    c.get("/api/chat/checkin")
    n = _say(c, "no")
    assert n["status"] == "cancelled" and n["money_moved"] == 0


def test_checkin_needs_a_student_session():
    from fastapi.testclient import TestClient
    from oasis.api import main as api
    assert TestClient(api.app).get("/api/chat/checkin").status_code in (401, 403)


SCAM = ("is this a scam? URGENT: Your tuition is overdue. Pay CNY 30000 immediately to account 6222020200112233445 in the name of "
        "Wei Zhang Education Fund. Do not contact the university. Reply now or you will be deported.")


def test_scam_check_gives_a_verdict_and_why_and_moves_nothing():
    c = _client()
    j = _say(c, SCAM)
    assert j["intent"] == "scam_check" and j["verdict"] == "likely_scam" and j["pending_id"] is None and j["money_moved"] == 0
    assert "urgency" in j["reply"] and "registry" in j["reply"] and "CNY 0 moved" in j["reply"] and len(j["evidence"]) >= 2
    assert c.get("/api/state").json()["pending"] == []


def test_scam_check_flags_a_registry_account_mismatch():
    j = _say(_client(), "is this a scam? Hi, Chen Wei here, rent for November CNY 6000, send it to account 6222000000000099 please, thanks")
    assert j["verdict"] in ("likely_scam", "suspicious") and "registry" in j["reply"]


def test_bare_is_this_a_scam_is_still_the_safety_faq():
    assert _say(_client(), "is this a scam?")["intent"] == "faq"


def test_scam_check_does_not_trip_the_canaries_or_freeze_anything():
    c = _client()
    _say(c, SCAM)
    assert _say(c, "pay my rent")["status"] == "held"


def test_hidden_markup_is_measured_against_mid_and_the_cheapest_route():
    j = _say(_client(), "my bank quoted ¥6,550 for ₹1,00,000, is that fair?")
    assert j["intent"] == "markup_check" and j["markup_pct"] > 5 and j["cheapest_cny"] > 6550 and "expensive" in j["reply"] and j["pending_id"] is None


def test_fair_quote_is_called_fair():
    j = _say(_client(), "my bank quoted ¥6,950 for ₹1,00,000, is that fair?")
    assert j["intent"] == "markup_check" and "roughly fair" in j["reply"] and "more than the quote" not in j["reply"]
