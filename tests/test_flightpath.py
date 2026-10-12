from datetime import date, timedelta

import pytest

from eval.flightpath_bench import run
from oasis.flightpath import core as fp
from oasis.mock.rates import MockRates

TODAY = date(2026, 10, 12)


def _journey(route="route_inr_cny_2", required=10000.0):
    j = fp.Journey("j1", route, 150000.0, required)
    fp.advance(j, "checks_complete", 0)
    fp.advance(j, "submitted", 0)
    fp.advance(j, "processing", 1)
    return j


def test_invalid_transition_rejected():
    with pytest.raises(fp.TransitionError):
        fp.advance(fp.Journey("x", "route_inr_cny_2", 1, 1), "credited", 0)


def test_routes_ranked_on_recipient_amount_with_margin():
    opts = fp.compare_routes(MockRates(), 20000, TODAY, TODAY + timedelta(days=5))
    assert all(o.meets_target for o in opts)
    assert all(o.recipient_worst_cny >= 20000 - 0.01 for o in opts)


def test_late_route_ranked_last():
    opts = fp.compare_routes(MockRates(), 20000, TODAY, TODAY + timedelta(days=1))
    assert opts[0].on_time and not opts[-1].on_time


def test_precheck_flags_preventable_issues():
    r = fp.ROUTES[0]
    codes = {w.code for w in fp.precheck(payee_verified=True, details_match=False, docs_complete=False,
                                         route=r, today=TODAY, due=TODAY + timedelta(days=1))}
    assert {"details_mismatch", "docs_missing", "misses_deadline"} <= codes


def test_delay_never_allows_resend():
    j = _journey()
    f = fp.reconcile(j, 10)
    a = fp.advise(j, f)
    assert f.code == "delayed" and a.action == "support_case" and not a.resend_allowed


def test_shortfall_detected():
    j = _journey()
    fp.advance(j, "credited", 2, credited_cny=9900.0)
    f = fp.reconcile(j, 2)
    assert f.code == "shortfall" and f.shortfall_cny == 100.0
    assert fp.advise(j, f).needs_approval


def test_resend_only_after_rejection_and_refund():
    j = _journey()
    fp.advance(j, "rejected", 2)
    assert not fp.can_resend(j) and not fp.advise(j, fp.reconcile(j, 2)).resend_allowed
    j.refund_confirmed = True
    a = fp.advise(j, fp.reconcile(j, 2))
    assert fp.can_resend(j) and a.resend_allowed and a.needs_approval


def test_benchmark_beats_baseline_and_is_deterministic():
    r = run(200, 3)
    assert r == run(200, 3)
    assert r["flightpath"]["duplicate_payments"] == 0
    assert r["flightpath"]["recipient_short_rate"] <= r["baseline"]["recipient_short_rate"]


def test_api_compare(api_client):
    r = api_client.post("/api/flightpath/compare", json={"required_cny": 20000, "due_in_days": 5})
    assert r.status_code == 200
    opts = r.json()["options"]
    assert len(opts) == 4 and all(o["meets_target"] for o in opts)
