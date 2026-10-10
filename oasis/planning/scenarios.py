"""Planning scenarios: fixed MOCK worlds used by the plan-quality evaluation and the UI's "try a scenario" picker.

Each builder starts from the scripted demo world (seed 7, offline LLM, deterministic keys; today is 2026-10-12) and
changes the Passport. The planner is judged by the deterministic validator, never by a model.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable

from ..agent.llm import OfflineLLM
from ..passport.models import Obligation
from ..world import Features, World


@dataclass(frozen=True)
class PlanScenario:
    id: str
    title: str
    description: str
    goal: str
    tests: str                      # what a good plan has to get right
    build: Callable[[World], None]


def _obs(w: World, *items) -> None:
    w.passport.obligations = [Obligation(id=i, type=t, payee_id=p, amount=a, due=d) for i, t, p, a, d in items]


UNIV, LAND = "payee_univ_x", "payee_landlord_chen"


def _demo(w: World) -> None:      # default demo Passport: INR 5 lakh against ~INR 6.07 lakh of obligations
    pass


def _tight(w: World) -> None:
    w.passport.set_balance("INR", 617000)          # only ~1.6% above what the best route needs


def _safe(w: World) -> None:
    w.passport.set_balance("INR", 6_400_000)
    _obs(w, ("obl_tuition_1", "tuition", UNIV, 400000, "2027-01-20"))


def _late_scholarship(w: World) -> None:
    w.passport.set_balance("INR", 366000)
    w.passport.expected_income = [{"label": "Scholarship stipend", "amount_cny": 20000, "expected": "2026-10-01", "received": False}]
    _obs(w, ("obl_rent_1", "rent", LAND, 6000, "2026-11-01"), ("obl_tuition_1", "tuition", UNIV, 30000, "2026-11-15"))


def _parent_tcs(w: World) -> None:
    w.passport.set_balance("INR", 50000)
    w.passport.remitted_inr_fy["parent"] = 950000.0
    _obs(w, ("obl_tuition_1", "tuition", UNIV, 30000, "2026-11-15"))


def _rate_target(w: World) -> None:
    w.passport.set_balance("INR", 635000)
    w.passport.rules.rate_targets.append({"id": "rt_01", "pair": "INR-CNY", "rate": 0.0700, "convert_cny": 20000,
                                          "status": "watching", "created": "2026-10-12"})


def _multi(w: World) -> None:
    w.passport.set_balance("INR", 980000)
    _obs(w, ("obl_hostel_1", "tuition", UNIV, 4000, "2026-10-20"), ("obl_deposit_1", "deposit", LAND, 6000, "2026-10-25"),
         ("obl_rent_1", "rent", LAND, 6000, "2026-11-01"), ("obl_tuition_1", "tuition", UNIV, 30000, "2026-11-15"),
         ("obl_rent_2", "rent", LAND, 6000, "2026-12-01"))


def _urgent(w: World) -> None:
    w.passport.set_balance("INR", 600000)
    _obs(w, ("obl_deposit_1", "deposit", LAND, 6000, "2026-10-14"), ("obl_tuition_1", "tuition", UNIV, 30000, "2026-11-15"))


SCENARIOS: dict[str, PlanScenario] = {s.id: s for s in [
    PlanScenario("shortfall", "Arrival shortfall (the demo student)",
                 "INR 5 lakh against deposit, rent and tuition worth about INR 6.07 lakh.", "Pay everything due.",
                 "Notice the INR shortfall and propose a parent-remitted conversion instead of leaving tuition unfunded.", _demo),
    PlanScenario("tight_runway", "Tight runway", "INR 6.17 lakh against INR 6.07 lakh of obligations on the best route.",
                 "Pay everything due and keep as much as possible.",
                 "Pick the cheapest on-time route; a costly route (or a split) would leave tuition short.", _tight),
    PlanScenario("safe_quota_tuition", "SAFE-quota tuition", "A CNY 400,000 programme fee due 2027-01-20 with INR 64 lakh in the account.",
                 "Pay the tuition.", "Convert at most the SAFE quota in 2026 and the rest from 1 January, in time for the due date.", _safe),
    PlanScenario("late_scholarship", "Late scholarship", "A CNY 20,000 stipend was due 2026-10-01 and has not arrived; INR 3.66 lakh in the account.",
                 "Pay rent and tuition.", "Do not count on the missing stipend; fund the gap another way.", _late_scholarship),
    PlanScenario("parent_tcs", "Parent remitter crossing TCS", "The student has INR 50,000; the parent has already sent INR 9.5 lakh this year.",
                 "Pay the tuition.", "Use the parent as remitter and surface the TCS that crossing INR 10 lakh would trigger.", _parent_tcs),
    PlanScenario("rate_target", "Rate target to protect", "INR 6.35 lakh; a pending target converts CNY 20,000 when the rate reaches 0.0700.",
                 "Pay everything due without disturbing my rate target.", "Keep the INR the rate target needs unconverted.", _rate_target),
    PlanScenario("multiple_obligations", "Five obligations", "Hostel fee, deposit, two rents and tuition across ten weeks; INR 9.8 lakh.",
                 "Pay everything due at the lowest cost.", "Batch conversions so fixed fees are paid as few times as possible.", _multi),
    PlanScenario("urgent_deadline", "Urgent deposit", "A CNY 6,000 deposit is due in two days, tuition in five weeks.",
                 "Pay the deposit on time and then the tuition.", "A 3-day route cannot fund a payment due in 2 days: pick a faster route for that part.", _urgent),
]}


def build_scenario_world(scenario_id: str, llm=None) -> World:
    s = SCENARIOS[scenario_id]
    w = World(Features.full(), llm or OfflineLLM(susceptible=True), seed=7, deterministic=True, autonomy=False)
    s.build(w)
    w.sync_balances()
    return w
