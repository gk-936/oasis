"""FlightPath explains what a finding means for the deadline and compares safe next steps. Deterministic arithmetic; the model may only
reword it (numbers must survive) and nothing here ever resends a payment. Offline, MOCK rails."""
import pytest

from oasis.flightpath import core as fp

ROUTE = next(r for r in fp.ROUTES if r.days >= 2)


def journey(due_in=None, stage="processing", submitted=0, credited=None, refund=False, purpose="tuition"):
    j = fp.Journey("jny_t", ROUTE.id, 10000.0, 3000.0, None if due_in is None else due_in, stage, submitted, credited, refund, [], purpose)
    return j


def verdict(j, today):
    f = fp.reconcile(j, today)
    return f, fp.consequences(j, f, today)


def test_delayed_transfer_names_the_deadline_and_never_offers_a_resend():
    today = ROUTE.days + fp.GRACE_DAYS + 2
    j = journey(due_in=today + ROUTE.days + 5)
    f, c = verdict(j, today=today)
    assert f.code == "delayed"
    assert c["facts"]["days_left"] == ROUTE.days + 5
    assert "tuition" in c["text"] and "paid twice" in c["text"]
    assert not any(o["resend"] for o in c["options"]) and {"contact_provider", "wait", "no_resend"} <= {o["action"] for o in c["options"]}
    assert c["uncertainty"] and "has not confirmed" in c["uncertainty"][0]


def test_wait_option_says_how_long_waiting_stays_safe():
    today = ROUTE.days + fp.GRACE_DAYS + 1
    j = journey(due_in=today + ROUTE.days + 9)
    _, c = verdict(j, today=today)
    wait = next(o for o in c["options"] if o["action"] == "wait")
    assert f"{c['facts']['days_left'] - ROUTE.days} day" in wait["effect"]


def test_when_a_replacement_could_no_longer_arrive_it_suggests_asking_for_more_time():
    j = journey(due_in=ROUTE.days + fp.GRACE_DAYS + 2)            # deadline lands just after the delay is flagged
    _, c = verdict(j, today=ROUTE.days + fp.GRACE_DAYS + 2)
    assert "extension" in {o["action"] for o in c["options"]} and c["deadline_risk"] in ("tight", "missed")


def test_shortfall_offers_a_top_up_that_needs_approval_and_checks_it_fits_the_deadline():
    j = journey(due_in=30, stage="credited", credited=2900.0)
    f, c = verdict(j, today=5)
    top = next(o for o in c["options"] if o["action"] == "top_up")
    assert f.code == "shortfall" and top["needs_approval"] and "100.00" in top["label"] and "in time" in top["effect"]
    late = fp.consequences(journey(due_in=1, stage="credited", credited=2900.0), f, 0)
    assert "ask for more time" in next(o for o in late["options"] if o["action"] == "top_up")["effect"]


def test_rejected_without_a_confirmed_refund_says_wait_not_resend():
    f, c = verdict(journey(due_in=10, stage="rejected"), today=3)
    assert f.code == "rejected" and [o["action"] for o in c["options"]] == ["wait_for_refund"]
    assert "refund of the rejected transfer is not confirmed" in c["uncertainty"][0]


def test_rejected_and_refunded_plans_a_new_payment_through_approval():
    _, c = verdict(journey(due_in=10, stage="rejected", refund=True), today=3)
    opt = c["options"][0]
    assert opt["action"] == "new_route" and opt["needs_approval"] and opt["resend"] is False


def test_a_healthy_transfer_has_no_options_and_no_alarm():
    f, c = verdict(journey(due_in=10, stage="credited", credited=3000.0), today=4)
    assert f.code == "ok" and c["options"] == [] and c["deadline_risk"] == "none"


def test_no_deadline_recorded_is_stated_not_invented():
    _, c = verdict(journey(due_in=None), today=ROUTE.days + fp.GRACE_DAYS + 2)
    assert c["facts"]["days_left"] is None and "No deadline is recorded" in c["text"]


def test_missed_deadline_is_reported_as_past():
    _, c = verdict(journey(due_in=2), today=ROUTE.days + fp.GRACE_DAYS + 5)
    assert c["deadline_risk"] == "missed" and "deadline passed" in c["text"]


# ---- API and the model rewrite guard -------------------------------------------------------------------------------
def test_advice_endpoint_returns_the_consequence_and_stays_advisory(api_client, api_session):
    r = api_client.post("/api/flightpath/journeys", json={"route_id": ROUTE.id, "required_cny": 3000, "send_inr": 45000, "due_in_days": 12, "purpose": "tuition"})
    assert r.status_code == 200, r.text
    jid = r.json()["journey"]["id"]
    api_client.post(f"/api/flightpath/journeys/{jid}/simulate", json={"event": "delay"})
    v = api_client.get(f"/api/flightpath/journeys/{jid}/advice").json()
    c = v["consequence"]
    assert c["options"] and not any(o["resend"] for o in c["options"]) and "tuition" in c["text"]
    w = api_session.S.world
    assert not w.ledger.transfers and w.ledger.money_lost() == 0


def test_a_model_rewrite_that_changes_a_number_is_discarded(tmp_path):
    from oasis.agent.llm import LiveLLM
    from tests.test_llm_live import FakeClient
    template = "Tuition is due in 8 days. Ask the provider today. Safe for up to 3 days."
    bad = LiveLLM(client=FakeClient(["Tuition is due in 80 days. Ask the provider today. Safe for up to 3 days."]), cache_dir=tmp_path / "a", rpm=0)
    assert bad.explain("flightpath", {"text": template}, "en") == template
    good = LiveLLM(client=FakeClient(["Your tuition is due in 8 days, so ask the provider today; waiting is safe for up to 3 days."]), cache_dir=tmp_path / "b", rpm=0)
    assert "8 days" in good.explain("flightpath", {"text": template}, "en") and good.explain("flightpath", {"text": template}, "en") != template
