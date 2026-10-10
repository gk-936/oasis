"""Live-rates wiring: worlds stay mock by default and when deterministic; the API exposes provenance; the mock is
calibrated to the real INR->CNY level."""
import pytest

from oasis.market import LiveRates
from oasis.mock.rates import MockRates
from oasis.world import World


def test_mock_base_is_calibrated_to_the_real_level():
    assert MockRates.BASE == pytest.approx(0.0692)
    assert all(0.068 < MockRates().mid(d) < 0.0705 for d in range(-30, 400))


def test_world_defaults_to_mock_and_deterministic_forces_mock(monkeypatch):
    monkeypatch.delenv("OASIS_RATES", raising=False)
    assert type(World().rates) is MockRates
    monkeypatch.setenv("OASIS_RATES", "live")
    assert isinstance(World(rates_mode=None).rates, LiveRates)
    assert type(World(deterministic=True).rates) is MockRates
    assert type(World(rates_mode="mock").rates) is MockRates


def test_api_state_carries_rate_provenance(api_client):
    s = api_client.get("/api/state").json()
    r = s["rates"]
    assert r["mode"] == "mock" and r["source"] == "MOCK" and "MOCK" in r["label"] and "MOCK" in r["spreads_and_fees"]
    assert r["rate"] == pytest.approx(s["rate_mid"])


def test_planning_get_rates_is_labelled_mock_offline():
    from oasis.planning.scenarios import build_scenario_world
    from oasis.planning.tools import PlanningToolbox
    out = PlanningToolbox(build_scenario_world("shortfall")).call("get_rates", {})
    assert out["rates"]["mode"] == "mock" and "mock" in out["note"] and "spreads and fees are mock" in out["note"]
