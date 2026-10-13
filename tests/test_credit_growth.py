"""Credit growth plan, opportunities and simulator: read-only guidance over the Trust Pass record. Hermetic."""
import pytest

from oasis.proof import credit_growth as cg
from oasis.proof import trust_pass as tp
from oasis.agent.llm import OfflineLLM
from oasis.world import Features, World
from test_trust_pass import _paid_world


def test_plan_counts_only_verified_payments():
    w = _paid_world()
    p = cg.plan(w)
    assert p["verified"]["payments"] == 2 and p["next"] == "three_payments"
    m = {x["id"]: x for x in p["milestones"]}
    assert m["first_payment"]["met"] and m["rent_and_tuition"]["met"] and not m["six_payments"]["met"]
    assert "cash_or_card_payments" in p["not_verified"]


def test_plan_on_empty_world():
    p = cg.plan(World(Features.full(), OfflineLLM(susceptible=True)))
    assert p["verified"]["payments"] == 0 and p["next"] == "first_payment"


def test_opportunities_ready_and_missing():
    w = _paid_world()
    o = {x["id"]: x for x in cg.opportunities(w)["opportunities"]}
    assert o["lower_deposit"]["ready"] and o["lower_deposit"]["package"]["claims"] == ["rent_on_time"]
    assert not o["student_card"]["ready"] and o["student_card"]["missing"][0]["code"] == "need_payments"
    assert not o["home_bank"]["ready"] and o["home_bank"]["package"] is None
    assert all(x["note"] == "better_supported_not_guaranteed" for x in o.values())


def test_late_payment_removes_opportunities():
    w = _paid_world(late_tuition=True)
    o = {x["id"]: x for x in cg.opportunities(w)["opportunities"]}
    assert not o["no_guarantor"]["ready"] and o["no_guarantor"]["missing"][0]["code"] == "late_payment_present"


def test_simulate_on_time_months_gains_asks_and_ladder():
    w = _paid_world()
    s = cg.simulate(w, on_time_months=6)
    assert s["hypothetical"] and "student_card" in s["gained_asks"] and "home_bank" in s["gained_asks"]
    assert s["after"]["ladder_level"] > s["before"]["ladder_level"]
    assert tp.compute_claims(tp._entries(w), w.today.isoformat())["on_time_all"]["of"] == 2   # nothing was saved


def test_simulate_late_payment_resets_streak():
    s = cg.simulate(_paid_world(), on_time_months=2, late_payments=1)
    assert s["after"]["claims"]["on_time_streak"]["count"] == 0
    assert "student_card" not in s["after"]["asks"]
    assert s["after"]["claims"]["no_late"]["value"] is False and "late_payment_breaks_streak_and_no_late" in s["notes"]


def test_starter_product_changes_nothing_but_warns():
    w = _paid_world()
    s = cg.simulate(w, starter_product=True, budget_safe=False)
    assert s["after"]["claims"] == s["before"]["claims"]
    assert "external_repayments_not_verified" in s["notes"] and "unsafe_budget_missed_payment_risk" in s["notes"]


def test_simulate_rejects_out_of_range():
    with pytest.raises(ValueError):
        cg.simulate(_paid_world(), on_time_months=99)


def test_api_is_student_only_and_writes_nothing(api_client, as_role):
    before = len(api_client.get("/api/trust-pass/claims").json()["claims"])
    assert api_client.get("/api/credit-growth/plan").status_code == 200
    assert api_client.get("/api/credit-growth/opportunities").status_code == 200
    r = api_client.post("/api/credit-growth/simulate", json={"on_time_months": 3})
    assert r.status_code == 200 and r.json()["hypothetical"]
    assert api_client.post("/api/credit-growth/simulate", json={"on_time_months": 99}).status_code == 422
    assert as_role("parent").get("/api/credit-growth/plan").status_code == 403
    assert len(api_client.get("/api/trust-pass/claims").json()["claims"]) == before
