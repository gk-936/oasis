"""Financial Digital Twin. MOCK / SIMULATION: pure stdlib, seeded, offline. Moves no money, predicts no real rate.

Per simulated path: the INR->CNY mid-rate follows a geometric random walk (assumed daily volatility FX_DAILY_VOL), the
parent's expected top-ups may arrive late, and each payment crosses a FlightPath rail that may delay or short-credit it.
Same seed => identical output. Mitigations are evaluated by re-running the same paths (common random numbers)."""
from __future__ import annotations
import math
import random
from dataclasses import dataclass
from datetime import date

from ..flightpath.core import DEDUCTIONS, GRACE_DAYS
from ..mock.rates import ROUTES, MockRates, delivered_amount
from ..planning.forecast import monthly_burn
from ..passport.currency import obligation_cny
from ..passport.models import Passport

# ASSUMPTIONS (stated, not measured). Changing them changes the answer; the API echoes them back.
FX_DAILY_VOL = 0.003        # 0.3% per day std-dev of the INR->CNY log-rate (about 4.7% over 250 days). An assumption.
TOPUP_LATE_PROB = 0.35      # chance an expected parent top-up arrives late
TOPUP_MAX_LATE_DAYS = 14
SHORT_CREDIT_PROB = 0.05    # chance the rail credits less than required (a top-up then takes SHORT_FIX_DAYS)
SHORT_FIX_DAYS = 2
MAX_DELAY_DAYS = 5
DEFAULT_PATHS = 600
MAX_HORIZON = 150
ASSUMPTIONS = {"fx_daily_vol": FX_DAILY_VOL, "fx_model": "geometric random walk, zero drift",
               "topup_late_prob": TOPUP_LATE_PROB, "topup_max_late_days": TOPUP_MAX_LATE_DAYS,
               "short_credit_prob": SHORT_CREDIT_PROB, "rail_delay_prob": "1 - route reliability (MOCK)",
               "max_rail_delay_days": MAX_DELAY_DAYS}

MITIGATIONS = ("convert_early", "send_early", "faster_route", "parent_topup")


@dataclass(frozen=True)
class Plan:
    convert_early: bool = False   # convert all INR to CNY on day 0 (and on top-up arrival): removes FX risk, pays the spread once
    send_early: int = 0           # extra days of slack before each deadline
    route_id: str | None = None   # force one route for every payment (None: the most reliable default)
    extra_buffer_cny: float = 0.0


def _route(rid):
    return next(r for r in ROUTES if r.id == rid)


def build_inputs(passport: Passport, rates: MockRates, today: date) -> dict:
    """Pull the semester out of the Passport: open obligations, expected top-ups, balances, daily burn."""
    obs = []
    for o in sorted(passport.obligations, key=lambda o: o.due):
        if o.status in ("paid", "frozen") or o.remaining <= 0:
            continue
        due = max((date.fromisoformat(o.due) - today).days, 0)
        obs.append({"id": o.id, "label": o.label or o.type, "type": o.type, "amount_cny": obligation_cny(o, rates, 0), "due_day": due, "due": o.due})
    inc = []
    for i in passport.expected_income:
        if i.get("received"):
            continue
        inc.append({"label": i.get("label", "top-up"), "amount_cny": float(i.get("amount_cny", 0)),
                    "day": max((date.fromisoformat(i["expected"]) - today).days, 0)})
    burn, basis = monthly_burn(passport)
    horizon = min(MAX_HORIZON, max([o["due_day"] for o in obs] + [i["day"] for i in inc] + [30]) + 14)
    return {"obligations": obs, "income": inc, "cny": passport.balance("CNY"), "inr": passport.balance("INR"),
            "burn_per_day": burn / 30.0, "burn_basis": basis, "rate0": rates.mid(0), "horizon": horizon}


def _net(route, rate):
    return rate * (1 - route.rate_spread) * (1 - route.pct_fee)


def simulate(inp: dict, plan: Plan = Plan(), paths: int = DEFAULT_PATHS, seed: int = 7, vol: float = FX_DAILY_VOL) -> dict:
    H, obs, inc = inp["horizon"], inp["obligations"], inp["income"]
    route = _route(plan.route_id or "route_inr_cny_3")
    exp_ded = DEDUCTIONS.get(route.id, (0, 0))[0]
    met = [0] * len(obs)
    all_met = 0
    bal = [[0.0] * paths for _ in range(H + 1)]
    rate0 = inp["rate0"]
    sends = [max(o["due_day"] - route.days - plan.send_early, 0) for o in obs]
    for p in range(paths):
        rng = random.Random(seed * 1_000_003 + p)
        # all randomness is drawn up-front in a fixed order so scenarios share the same world (common random numbers)
        shocks = [rng.gauss(0, 1) for _ in range(H + 1)]
        late = [(rng.random() < TOPUP_LATE_PROB, 1 + int(rng.random() * TOPUP_MAX_LATE_DAYS)) for _ in inc]
        rail = [(rng.random(), 1 + int(rng.random() * MAX_DELAY_DAYS), rng.random()) for _ in obs]
        cny, inr = inp["cny"] + plan.extra_buffer_cny, inp["inr"]
        arrive = [(i["day"] + (dd if l else 0), i["amount_cny"] / rate0) for i, (l, dd) in zip(inc, late)]
        rate, ok_all = rate0, True
        if plan.convert_early:
            cny += delivered_amount(inr, route, rate)
            inr = 0.0
        for d in range(H + 1):
            if d:
                rate *= math.exp(vol * shocks[d] - 0.5 * vol * vol)
            for day, amt_inr in arrive:
                if day == d:
                    if plan.convert_early:
                        cny += delivered_amount(amt_inr, route, rate)
                    else:
                        inr += amt_inr
            burn = inp["burn_per_day"]
            use = min(cny, burn)
            cny -= use
            if burn > use and inr > 0:
                inr = max(inr - (burn - use) / _net(route, rate), 0.0)
            for k, o in enumerate(obs):
                if sends[k] != d:
                    continue
                u_delay, delay_days, u_short = rail[k]
                need = o["amount_cny"] + exp_ded
                funded = cny + (delivered_amount(inr, route, rate) if inr > 0 else 0.0) >= need
                if funded:
                    from_cny = min(cny, need)
                    cny -= from_cny
                    short = need - from_cny
                    if short > 0:
                        inr = max(inr - (short / _net(route, rate) + route.fixed_fee_inr), 0.0)
                delay = delay_days if u_delay > route.reliability else 0
                fix = SHORT_FIX_DAYS if u_short < SHORT_CREDIT_PROB else 0
                if funded and d + route.days + delay + fix <= o["due_day"] + GRACE_DAYS:
                    met[k] += 1
                else:
                    ok_all = False
            bal[d][p] = cny + inr * rate
        all_met += ok_all

    def q(vals, f):
        vals = sorted(vals)
        return vals[min(int(f * len(vals)), len(vals) - 1)]
    fan = [{"day": d, "p10": round(q(bal[d], .1), 2), "p50": round(q(bal[d], .5), 2), "p90": round(q(bal[d], .9), 2)} for d in range(H + 1)]
    return {"p_all_met": round(all_met / paths, 4),
            "deadlines": [{**o, "p_met": round(met[k] / paths, 4), "send_day": sends[k]} for k, o in enumerate(obs)], "fan": fan}


def _sized_topup(inp: dict, start: float, seed: int, target: float = 0.85, step: float = 1000.0, max_steps: int = 40) -> float:
    """Smallest top-up (in 1,000 steps, from `start`) that makes the simulation meet every deadline with probability >= target.
    The simple gap formula ignores daily spending until the last deadline and the conversion spread, so it can recommend an amount
    that still fails; this checks the amount against the same simulation the page shows (fewer paths, same seed: deterministic)."""
    amt = start
    # money cannot fix rail delays or short credits, so the goal is "almost as good as unlimited money", capped at `target`
    ceiling = simulate(inp, Plan(extra_buffer_cny=1e7), 200, seed)["p_all_met"]
    target = min(target, ceiling * 0.97)
    for _ in range(max_steps):
        if simulate(inp, Plan(extra_buffer_cny=amt), 200, seed)["p_all_met"] >= target:
            return amt
        amt += step
    return amt


def run_twin(passport: Passport, rates: MockRates, today: date, seed: int = 7, paths: int = DEFAULT_PATHS, rescue: bool = False) -> dict:
    inp = build_inputs(passport, rates, today)
    if rescue:
        # What-if (MOCK): the family has promised enough to cover the whole gap, arriving in 10 days (and it may arrive late).
        need0 = sum(o["amount_cny"] for o in inp["obligations"]) + inp["burn_per_day"] * 14
        gap0 = max(need0 - inp["cny"] - inp["inr"] * inp["rate0"], 0.0)
        inp["income"] = inp["income"] + [{"label": "What-if family top-up", "amount_cny": _sized_topup(inp, float(math.ceil((gap0 + 1000) / 1000) * 1000), seed), "day": 10}]
    base = simulate(inp, Plan(), paths, seed)
    plans = {"convert_early": Plan(convert_early=True), "send_early": Plan(send_early=3), "faster_route": Plan(route_id="route_inr_cny_2")}
    need = sum(o["amount_cny"] for o in inp["obligations"]) + inp["burn_per_day"] * 14
    gap = max(need - inp["cny"] - inp["inr"] * inp["rate0"], 0.0)
    topup = _sized_topup(inp, float(math.ceil((gap + 1000) / 1000) * 1000), seed)   # covers the shortfall, then grown until the simulation agrees
    plans["parent_topup"] = Plan(extra_buffer_cny=topup)
    options = []
    for m in MITIGATIONS:
        r = simulate(inp, plans[m], paths, seed)
        options.append({"id": m, "topup_cny": topup if m == "parent_topup" else None, "p_all_met": r["p_all_met"], "improvement": round(r["p_all_met"] - base["p_all_met"], 4),
                        "deadlines": [{"id": d["id"], "p_met": d["p_met"]} for d in r["deadlines"]]})
    options.sort(key=lambda o: -o["improvement"])
    best = options[0] if options and options[0]["improvement"] > 0.005 else None
    return {"label": "MOCK / simulation, not a forecast", "seed": seed, "paths": paths, "horizon_days": inp["horizon"],
            "assumptions": ASSUMPTIONS, "start_cny": inp["cny"], "start_inr": inp["inr"], "burn_basis": inp["burn_basis"],
            "rescue": rescue, "baseline": base, "mitigations": options, "recommended": best["id"] if best else None}
