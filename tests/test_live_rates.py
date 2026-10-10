"""LiveRates with a fake transport: no sockets, no real data/ directory."""
import json
from datetime import datetime, timezone

import pytest

from oasis.market.live_rates import LiveRates, cross_rate, make_rates, provenance
from oasis.mock.rates import MockRates

T0 = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc).timestamp()


class Fake:
    def __init__(self, inr=90.0, cny=6.3, fail=False, bodies=None):
        self.calls, self.inr, self.cny, self.fail, self.bodies = [], inr, cny, fail, bodies or {}

    def __call__(self, url):
        self.calls.append(url)
        if self.fail:
            raise OSError("network down")
        for k, v in self.bodies.items():
            if k in url:
                return v
        if "frankfurter" in url:
            when = url.split("/v1/")[1].split("?")[0]
            return json.dumps({"base": "EUR", "date": "2026-10-09" if when == "latest" else when,
                               "rates": {"INR": self.inr, "CNY": self.cny}})
        raise OSError("secondary not stubbed")


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t


def make(tmp_path, fake, clock=None, **kw):
    return LiveRates(cache_path=tmp_path / "rates_cache.json", transport=fake, clock=clock or Clock(), **kw)


def test_cross_rate_maths():
    assert cross_rate(90.0, 6.3) == pytest.approx(0.07)
    with pytest.raises(ValueError):
        cross_rate(0, 6.3)


def test_fresh_fetch_carries_provenance(tmp_path):
    r = make(tmp_path, Fake())
    q = r.quote(0)
    assert q.rate == pytest.approx(0.07) and q.source == "frankfurter" and q.as_of == "2026-10-09"
    assert q.fetched_at.endswith("Z") and not q.stale
    assert "live" in q.label() and "ECB via Frankfurter" in q.label() and "UTC" in q.label()
    assert (tmp_path / "rates_cache.json").exists()
    assert r.provenance()["mode"] == "live"


def test_cache_hit_within_ttl_and_expiry(tmp_path):
    fake, clock = Fake(), Clock()
    r = make(tmp_path, fake, clock)
    r.mid(0); r.mid(0); r.mid(3)                       # future days share the latest quote
    assert len(fake.calls) == 1
    clock.t += 3599
    r.mid(0)
    assert len(fake.calls) == 1
    clock.t += 2
    fake.cny = 6.48
    assert r.mid(0) == pytest.approx(0.072) and len(fake.calls) == 2


def test_cache_persists_across_instances(tmp_path):
    make(tmp_path, Fake()).mid(0)
    fake2 = Fake(fail=True)
    assert make(tmp_path, fake2).mid(0) == pytest.approx(0.07)
    assert fake2.calls == []


def test_network_failure_uses_stale_cache(tmp_path):
    clock = Clock()
    make(tmp_path, Fake(), clock).mid(0)
    clock.t += 7200
    r = make(tmp_path, Fake(fail=True), clock)
    q = r.quote(0)
    assert q.stale and q.rate == pytest.approx(0.07) and q.source == "frankfurter"
    assert "STALE" in q.label()


def test_no_cache_no_network_falls_back_to_labelled_mock(tmp_path):
    r = make(tmp_path, Fake(fail=True))
    q = r.quote(0)
    assert q.source == "MOCK" and r.mid(0) == MockRates(7).mid(0)
    assert "MOCK" in q.label() and r.provenance()["mode"] == "mock"


def test_failure_backoff_avoids_hammering(tmp_path):
    fake = Fake(fail=True)
    r = make(tmp_path, fake)
    for _ in range(5):
        r.mid(0)
    assert len(fake.calls) == 2                         # primary + secondary once, then backoff


def test_malformed_primary_falls_to_secondary_then_mock(tmp_path):
    good = json.dumps({"date": "2026-10-09", "inr": {"cny": 0.0712}})
    r = make(tmp_path, Fake(bodies={"frankfurter": "<html>oops</html>", "jsdelivr": good}))
    q = r.quote(0)
    assert q.source == "fawazahmed0" and q.rate == pytest.approx(0.0712)
    bad = json.dumps({"base": "EUR", "date": "x", "rates": {"INR": 90, "CNY": 900}})   # implausible 10.0
    r2 = LiveRates(cache_path=tmp_path / "c2.json", clock=Clock(),
                   transport=Fake(bodies={"frankfurter": bad, "jsdelivr": "{}"}))
    assert r2.quote(0).source == "MOCK"
    r3 = LiveRates(cache_path=tmp_path / "c3.json", clock=Clock(),
                   transport=Fake(bodies={"frankfurter": json.dumps({"rates": {}}), "jsdelivr": "nope"}))
    assert r3.quote(0).source == "MOCK"


def test_history_uses_dated_endpoint_and_future_is_flat(tmp_path):
    fake = Fake()
    r = make(tmp_path, fake)
    r.mid(-7)
    assert any("/v1/2026-10-03?" in u for u in fake.calls)
    r.mid(-7)
    assert sum("2026-10-03" in u for u in fake.calls) == 1   # history cached permanently
    assert r.mid(30) == r.mid(0) == r.mid(1)                  # never predicted
    assert not any("2026-11" in u for u in fake.calls)


def test_history_failure_never_invents_rates(tmp_path):
    clock = Clock()
    make(tmp_path, Fake(), clock).mid(0)
    r = make(tmp_path, Fake(fail=True), clock)
    assert r.mid(-7) == pytest.approx(0.07)                   # falls back to the live rate, flat


def test_route_interface_unchanged(tmp_path):
    from oasis.mock.rates import ROUTES
    r = make(tmp_path, Fake())
    assert r.route_rate(ROUTES[0], 0) == pytest.approx(0.07 * (1 - ROUTES[0].rate_spread))


def test_factory_and_provenance(tmp_path, monkeypatch):
    monkeypatch.delenv("OASIS_RATES", raising=False)
    assert type(make_rates()) is MockRates
    assert provenance(make_rates())["source"] == "MOCK"
    monkeypatch.setenv("OASIS_RATES", "live")
    assert isinstance(make_rates(cache_path=tmp_path / "x.json", transport=Fake()), LiveRates)
    assert type(make_rates(mode="mock")) is MockRates
