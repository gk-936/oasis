import time
from dataclasses import replace

from oasis.demo import new_demo_world
from oasis.twin import core as tw


def _world():
    return new_demo_world()


def test_deterministic_and_fast():
    w = _world()
    t0 = time.time()
    a = tw.run_twin(w.passport, w.rates, w.today, seed=3)
    assert time.time() - t0 < 2.5
    assert a == tw.run_twin(w.passport, w.rates, w.today, seed=3)
    assert a["label"].startswith("MOCK") and a["assumptions"]["fx_daily_vol"] == tw.FX_DAILY_VOL
    assert a["baseline"]["deadlines"] and all(0 <= d["p_met"] <= 1 for d in a["baseline"]["deadlines"])
    assert all(f["p10"] <= f["p50"] <= f["p90"] for f in a["baseline"]["fan"])


def test_more_buffer_never_lowers_probability():
    w = _world()
    inp = tw.build_inputs(w.passport, w.rates, w.today)
    ps = [tw.simulate(inp, tw.Plan(extra_buffer_cny=b), 300, 5)["p_all_met"] for b in (0, 20000, 80000, 400000)]
    assert ps == sorted(ps) and ps[-1] > ps[0]


def test_mitigation_improvement_is_a_rerun_difference():
    w = _world()
    r = tw.run_twin(w.passport, w.rates, w.today)
    for m in r["mitigations"]:
        assert abs(m["improvement"] - (m["p_all_met"] - r["baseline"]["p_all_met"])) < 1e-3


def test_rescue_scenario_makes_deadlines_reachable():
    w = _world()
    base = tw.run_twin(w.passport, w.rates, w.today)
    r = tw.run_twin(w.passport, w.rates, w.today, rescue=True)
    assert r["rescue"] is True and base["rescue"] is False
    assert r["baseline"]["p_all_met"] > base["baseline"]["p_all_met"]
