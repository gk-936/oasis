"""Generic corridors (CNY-USD, INR-USD, EUR-USD, INR-EUR, CNY-EUR) and parity with the original INR-CNY engine. Hermetic."""
from datetime import date

import pytest

from oasis.corridors import core as cor
from oasis.mock import fx
from oasis.mock.rates import MockRates, ROUTES, delivered_amount
from oasis.planning.routes import inr_needed

TABLE = fx.per_usd(MockRates().mid(0))
NEW = ["CNY-USD", "INR-USD", "EUR-USD", "INR-EUR", "CNY-EUR"]


def test_all_corridors_listed():
    ids = {c["id"] for c in cor.listing()}
    assert ids == {"INR-CNY", *NEW}


def test_inr_cny_matches_the_original_engine():
    rates = MockRates()
    mid = rates.mid(0)
    for r_old, r_new in zip(ROUTES, cor.routes_for("INR-CNY", TABLE)):
        assert cor.delivered(100000, r_new, mid) == pytest.approx(delivered_amount(100000, r_old, mid), abs=0.01)
        # closed-form inverse agrees with the original binary search when there is no extra deduction
        flat = cor.Route(r_new.id, r_new.name, r_new.typical_bank, r_new.fixed_fee_src, r_new.pct_fee, r_new.spread, r_new.days, r_new.reliability, "mock", 0.0)
        assert cor.send_needed(30000, flat, mid) == pytest.approx(inr_needed(rates, r_old, 30000), abs=0.02)


@pytest.mark.parametrize("cid", NEW)
def test_inverse_is_exact_and_worst_case_met(cid):
    res = cor.compare(cid, 5000, TABLE)
    assert len(res["options"]) == 3 and res["best"]
    for o in res["options"]:
        assert o["meets_target"] and o["worst_received"] >= 5000 - 0.01
        assert o["send"] > 0 and o["expected_received"] >= o["worst_received"]
    assert res["saving_vs_bank"]["saved_src"] > 0                     # the cheapest route beats the typical bank


def test_deadline_filters_routes():
    res = cor.compare("INR-USD", 1000, TABLE, due_in_days=1)
    assert [o["on_time"] for o in res["options"]][0] is True
    assert all(not o["on_time"] for o in res["options"] if o["arrives_in_days"] > 1)


def test_forward_quote_roundtrip():
    res = cor.compare("EUR-USD", 2000, TABLE)
    o = res["options"][0]
    fwd = {r["route_id"]: r for r in cor.quote_send("EUR-USD", o["send"], TABLE)["routes"]}
    assert fwd[o["route_id"]]["worst_delivered"] == pytest.approx(2000, abs=0.05)


def test_cross_rates_are_consistent():
    # triangular consistency of the table: INR->EUR * EUR->USD == INR->USD
    assert fx.mid("INR", "EUR", TABLE) * fx.mid("EUR", "USD", TABLE) == pytest.approx(fx.mid("INR", "USD", TABLE))


def test_checks_use_sourced_rules():
    big = cor.check("INR-USD", 30_000_000, "tuition", TABLE)                 # about USD 340k
    rules = {f["rule"]: f for f in big["findings"]}
    assert rules["lrs_annual_limit"]["severity"] == "hold" and rules["lrs_annual_limit"]["status"] == "confirmed-primary"
    assert rules["tcs"]["severity"] == "warn" and rules["tcs"]["source"]
    cn = cor.check("CNY-USD", 500_000, "tuition", TABLE)
    assert any(f["rule"] == "safe_annual_quota" for f in cn["findings"])
    eu = cor.check("EUR-USD", 1000, "tuition", TABLE)
    assert eu["findings"][0]["status"] == "researched-secondary"
    assert any(f["status"] == "unconfirmed" for f in cor.check("INR-EUR", 1000, "tuition", TABLE)["findings"])   # EUR inbound row


def test_bad_input_refused():
    for bad in (0, -5, float("nan"), "x", 1e12):
        with pytest.raises(cor.CorridorError):
            cor.compare("INR-USD", bad, TABLE)
    with pytest.raises(cor.CorridorError):
        cor.compare("INR-JPY", 100, TABLE)


def test_api_read_only_and_roles(api_client, as_role):
    assert api_client.get("/api/corridors").status_code == 200
    r = api_client.post("/api/corridors/compare", json={"corridor": "CNY-EUR", "required": 3000})
    assert r.status_code == 200 and r.json()["options"]
    assert api_client.post("/api/corridors/compare", json={"corridor": "XXX-YYY", "required": 3000}).status_code == 400
    assert api_client.post("/api/corridors/compare", json={"corridor": "CNY-EUR", "required": -1}).status_code == 422
    assert api_client.post("/api/corridors/check", json={"corridor": "INR-EUR", "amount": 50000}).status_code == 200
    assert as_role("parent").post("/api/corridors/compare", json={"corridor": "INR-EUR", "required": 100}).status_code == 200
    from fastapi.testclient import TestClient
    from oasis.api import main as api
    assert TestClient(api.app).post("/api/corridors/compare", json={"corridor": "INR-EUR", "required": 100}).status_code == 401


def test_researched_rules_carry_source_and_status():
    for cid in NEW:
        for f in cor.check(cid, 1000, "tuition", TABLE)["findings"]:
            assert f["status"] in ("confirmed-primary", "researched-secondary", "unconfirmed") and f["source"] and f["retrieved"]
    ids = {f["rule"] for f in cor.check("CNY-USD", 1000, "tuition", TABLE)["findings"]}
    assert {"safe_anti_splitting", "us_incoming_wire_fee"} <= ids
    assert "payer_payee_data" in {f["rule"] for f in cor.check("EUR-USD", 1000, "tuition", TABLE)["findings"]}


def test_prices_are_flagged_mock_until_sourced_and_calibration_helper():
    st = {o["route"]: o["price_status"] for o in cor.compare("EUR-USD", 1000, TABLE)["options"]}
    assert set(st.values()) <= {"sourced", "estimated", "assumed"} and "mock" not in st.values()
    assert st["Digital remitter"] == "sourced" and st["Education payment specialist"] == "assumed"
    assert all(o["price_source"] for o in cor.compare("INR-EUR", 1000, TABLE)["options"])
    assert all(o["price_status"] == "mock" for o in cor.compare("INR-CNY", 1000, TABLE)["options"])
    r = cor.implied_costs(100000, 0.0113, 1000.0, fixed_fee_src=500)
    assert 0 < r["variable_cost_pct"] < r["total_cost_pct"] < 100
    with pytest.raises(cor.CorridorError):
        cor.implied_costs(100, 1.0, 90, fixed_fee_src=200)


def test_realistic_price_levels():
    # the typical bank costs a few percent on a mid-size payment; a digital remitter between about 0.3% and 2.5%
    for cid in NEW:
        o = {x["route"]: x for x in cor.compare(cid, 10000, TABLE)["options"]}
        bank, dig = o["Typical bank SWIFT transfer"], o["Digital remitter"]
        assert 2.0 < bank["fee_pct_of_value"] < 6.0, (cid, bank["fee_pct_of_value"])
        assert 0.3 < dig["fee_pct_of_value"] < 2.5, (cid, dig["fee_pct_of_value"])
        assert bank["worst_received"] <= bank["expected_received"]
