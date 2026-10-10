"""Student-outcome simulation: 5 personas x 90 simulated days, Oasis vs a manually paying student.

    python -m eval.simulator

This is a MODEL, not a measurement. Assumptions (stated in the report):
- Manual student converts INR via a typical bank route 7 days before each obligation and once a month for
  living costs, pays rent and living costs by foreign card in Alipay/WeChat Pay, notices a late income only on
  the day money is needed (a family top-up then takes 3 days), and pays any invoice as received.
- Oasis converts with the best on-time route, pays from a local account (no wallet fee), warns 21 days ahead
  (shortfall / late-income triggers) and requests a family top-up early, and runs every invoice through the
  real pipeline (scam and legitimate-change events below use the actual OasisAgent).
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path

from oasis.agent.llm import OfflineLLM
from oasis.agent.pipeline import OasisAgent, Request
from oasis.mock.rates import ROUTES, MockRates, delivered_amount
from oasis.mock.wallet import foreign_card_cost
from oasis.world import Features, World

from .approver import SimulatedHumans
from .scenarios import LL_NEW, rent, tuition

REPORTS = Path(__file__).resolve().parent / "reports"
BANK = next(r for r in ROUTES if r.typical_bank)
DAYS = 90
TOPUP_DAYS = 3
WARN_DAYS = 21


@dataclass
class Persona:
    name: str
    inr: float
    living_cny_month: float
    obligations: list[tuple[int, float, str]]           # (day, CNY, kind)
    incomes: list[tuple[int, int, float]] = field(default_factory=list)  # (expected day, actual day, CNY)
    family_topup_cny: float = 0.0                       # what family can send on request
    events: list[str] = field(default_factory=list)     # forged_invoice | landlord_change
    note: str = ""


PERSONAS = [
    Persona("Arjun", 400000, 2400, [(1, 6000, "deposit"), (1, 3000, "rent"), (20, 15000, "tuition"), (31, 3000, "rent"), (61, 3000, "rent")],
            family_topup_cny=8000, note="tight runway"),
    Persona("Meera", 250000, 2200, [(1, 3000, "rent"), (31, 3000, "rent"), (61, 3000, "rent"), (45, 12000, "tuition")],
            incomes=[(25, 46, 9000)], family_topup_cny=6000, note="scholarship arrives 21 days late"),
    Persona("Kiran", 150000, 2500, [(1, 3500, "rent"), (31, 3500, "rent"), (61, 3500, "rent")],
            incomes=[(28, 28, 4000), (58, 58, 4000), (88, 88, 4000)], family_topup_cny=5000, note="monthly family top-ups"),
    Persona("Sana", 600000, 2600, [(1, 6000, "rent"), (31, 6000, "rent"), (61, 6000, "rent"), (15, 20000, "tuition")],
            family_topup_cny=5000, events=["landlord_change"], note="landlord changes bank account mid-semester"),
    Persona("Rahul", 600000, 2500, [(1, 4000, "rent"), (31, 4000, "rent"), (61, 4000, "rent"), (30, 25000, "tuition")],
            family_topup_cny=5000, events=["forged_invoice"], note="receives a forged finance-office invoice"),
]


def conv_cost(inr: float, route, mid: float) -> float:
    return inr * mid - delivered_amount(inr, route, mid)


def simulate(p: Persona, strategy: str, rates: MockRates) -> dict:
    best = min((r for r in ROUTES if not r.typical_bank), key=lambda r: -delivered_amount(100000, r, rates.mid(0)))
    route = BANK if strategy == "manual" else best
    inr, cny, fees, late, pending = p.inr, 0.0, 0.0, 0, []   # pending: (arrival_day, cny)
    topup_requested = set()
    lead = 7 if strategy == "manual" else max(route.days, 3)

    def convert(day: int, need: float):
        nonlocal inr, fees
        mid = rates.mid(day)
        send = min(inr, need / (mid * (1 - route.rate_spread) * (1 - route.pct_fee)) + route.fixed_fee_inr)
        if send <= route.fixed_fee_inr:
            return
        got = delivered_amount(send, route, mid)
        inr -= send
        fees += conv_cost(send, route, mid)
        pending.append((day + route.days, got))

    obligations = sorted(p.obligations)
    for day in range(-10, DAYS + 1):
        for (a, c) in [x for x in pending if x[0] == day]:
            cny += c
            pending.remove((a, c))
        for exp, act, amt in p.incomes:
            if act == day:
                cny += amt
        # Oasis forecast: shortfall / late-income trigger WARN_DAYS ahead -> early top-up request.
        if strategy == "oasis":
            horizon = [o for o in obligations if day <= o[0] <= day + WARN_DAYS]
            expected = sum(amt for exp, act, amt in p.incomes if day < act and exp > day and exp <= day + WARN_DAYS)
            available = cny + sum(c for _, c in pending) + inr * rates.mid(day) * 0.98 + expected
            late_income = any(exp < day < act for exp, act, _ in p.incomes)
            need = sum(o[1] for o in horizon) + p.living_cny_month * WARN_DAYS / 30
            if (available < need or late_income) and p.family_topup_cny and "early" not in topup_requested:
                topup_requested.add("early")
                pending.append((day + TOPUP_DAYS, p.family_topup_cny))
        # Monthly living conversion.
        if (day + lead) % 30 == 0 and 0 <= day + lead < DAYS:
            convert(day, p.living_cny_month)
        # Pre-obligation conversion.
        for d, amt, _ in obligations:
            if d - lead == day:
                in_flight = sum(c for _, c in pending)
                if strategy == "oasis":  # plan for everything due up to this date, not one bill at a time
                    due = sum(a2 for d2, a2, _ in obligations if day <= d2 <= d)
                    gap = due - max(cny + in_flight - p.living_cny_month / 2, 0)
                else:
                    gap = amt - max(cny + in_flight - p.living_cny_month / 2, 0)
                if gap > 0:
                    convert(day, gap)
        # Pay obligations due today.
        for o in [o for o in obligations if o[0] == day]:
            d, amt, kind = o
            if cny >= amt:
                cny -= amt
                if strategy == "manual" and kind in ("rent", "deposit"):
                    fees += foreign_card_cost(amt)["total_cost"] - amt
            else:
                late += 1
                if p.family_topup_cny and "late" not in topup_requested and "early" not in topup_requested:
                    topup_requested.add("late")
                    pending.append((day + TOPUP_DAYS, p.family_topup_cny))
                if cny + sum(c for _, c in pending) < amt:
                    convert(day, amt - max(cny, 0) - sum(c for _, c in pending))  # react: convert the gap now
                obligations.append((day + 1, amt, kind))  # retry tomorrow; each day late counts once
        # Daily living spend (small payments).
        if day < 0:
            continue
        daily = p.living_cny_month / 30
        cny -= daily
        if strategy == "manual":
            fees += daily * 0.01  # card bank fee; small payments stay under the CNY 200 wallet-fee threshold
    return {"fees_cny": round(fees, 2), "late_payment_days": late, "end_cny": round(cny, 2),
            "end_inr": round(inr, 2), "route": route.name}


def run_event(event: str) -> dict:
    w = World(Features.full(), OfflineLLM(susceptible=True))
    agent, humans = OasisAgent(w), SimulatedHumans()
    if event == "forged_invoice":
        o = agent.handle(Request(tuition("6228480000009999", extra="URGENT: bank details updated.")), humans)
        return {"event": event, "oasis_status": o.status, "manual_assumed": "paid attacker",
                "scam_stopped": o.status in ("rejected", "frozen", "held", "needs_verification") and w.ledger.money_lost() == 0,
                "money_saved_cny": 30000 if w.ledger.money_lost() == 0 else 0}
    w.registry.issue("payee_landlord_chen", "Chen Wei", "landlord", LL_NEW)
    o = agent.handle(Request(rent(LL_NEW)), humans)
    return {"event": event, "oasis_status": o.status, "completed": o.status == "paid", "minutes": o.sim_minutes}


def main() -> dict:
    rates = MockRates(7)
    rows = []
    for p in PERSONAS:
        m, o = simulate(p, "manual", rates), simulate(p, "oasis", rates)
        events = [run_event(e) for e in p.events]
        rows.append({"persona": p.name, "note": p.note, "manual": m, "oasis": o,
                     "fees_saved_cny": round(m["fees_cny"] - o["fees_cny"], 2),
                     "late_days_avoided": m["late_payment_days"] - o["late_payment_days"],
                     "scams_stopped": sum(e.get("scam_stopped", False) for e in events), "events": events})
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "simulation.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    md = ["# Oasis student-outcome simulation (MODEL - see assumptions in eval/simulator.py)", "",
          "| Persona | Situation | Fees manual (CNY) | Fees Oasis (CNY) | Saved | Late-payment days manual | Oasis | Scams stopped |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['persona']} | {r['note']} | {r['manual']['fees_cny']:,.0f} | {r['oasis']['fees_cny']:,.0f} | "
                  f"{r['fees_saved_cny']:,.0f} | {r['manual']['late_payment_days']} | {r['oasis']['late_payment_days']} | "
                  f"{r['scams_stopped']} |")
    md.append("")
    md.append("Event runs use the real pipeline: " + "; ".join(f"{r['persona']}: {e}" for r in rows for e in r["events"]))
    (REPORTS / "simulation.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return {"rows": rows}


if __name__ == "__main__":
    main()
