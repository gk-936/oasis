"""Step 2 - forecast with named triggers. The agent never predicts exchange rates."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date

from ..mock.rates import MockRates
from ..passport.currency import obligation_cny
from ..passport.models import Passport
from . import spending
from .spending import REFERENCE_COSTS_CNY

WARNING_WINDOW_DAYS = 21


@dataclass
class Trigger:
    kind: str       # shortfall | rate_move | low_runway | late_income | rate_target
    message: str
    data: dict


def cny_equivalent(passport: Passport, rates: MockRates, day_index: int = 0) -> float:
    return passport.balance("CNY") + passport.balance("INR") * rates.mid(day_index)


def monthly_burn(passport: Passport, history_cny: list[float] | None = None) -> tuple[float, str]:
    """Own spending pattern once there is enough history; otherwise the student's budget + labelled reference costs."""
    if history_cny and len(history_cny) >= 3:
        avg = sum(history_cny) / len(history_cny)
        return round(avg, 2), "own spending pattern (per-category average)"
    sm = spending.summarize(passport)
    return float(sm["monthly_cny"]), sm["basis_text"]


def cover_position(passport: Passport, rates: MockRates, day_index: int = 0) -> dict:
    """What the open tuition, rent and deposit bills total against what the balances are worth today (CNY); shortfall is 0 when covered."""
    pending = sum(obligation_cny(o, rates, day_index) for o in passport.obligations if o.status in ("pending", "planned", "partially_paid")
                  and o.type in ("tuition", "rent", "deposit"))
    available = cny_equivalent(passport, rates, day_index)
    return {"bills_cny": round(pending, 2), "available_cny": round(available, 2), "shortfall_cny": round(max(pending - available, 0), 2)}


def runway_months(passport: Passport, rates: MockRates, day_index: int = 0, history_cny=None) -> float:
    """Months the money lasts after pending obligations are covered."""
    pending = sum(obligation_cny(o, rates, day_index) for o in passport.obligations if o.status in ("pending", "planned", "partially_paid")
                  and o.type in ("tuition", "rent", "deposit"))
    free = cny_equivalent(passport, rates, day_index) - pending
    burn, _ = monthly_burn(passport, history_cny)
    return round(max(free, 0) / burn, 2) if burn else float("inf")


def triggers(passport: Passport, rates: MockRates, today: date, day_index: int = 0,
             rate_move_threshold: float = 0.01, history_cny=None) -> list[Trigger]:
    out: list[Trigger] = []
    # Shortfall: obligation due soon and projected balance won't cover it.
    available = cny_equivalent(passport, rates, day_index)
    committed = 0.0
    for o in sorted(passport.obligations, key=lambda o: o.due):
        if o.status not in ("pending", "planned"):
            continue
        committed += obligation_cny(o, rates, day_index, remaining=False)
        days = (date.fromisoformat(o.due) - today).days
        if days <= WARNING_WINDOW_DAYS and committed > available:
            out.append(Trigger("shortfall", f"{o.type} of CNY {o.amount:,.0f} due in {days} days; "
                               f"projected funds cover only CNY {available:,.0f} of CNY {committed:,.0f} committed.",
                               {"obligation": o.id, "gap_cny": round(committed - available, 2)}))
    # Rate move vs the previous day (information to time staged conversions, not a prediction).
    prev, cur = rates.mid(day_index - 7), rates.mid(day_index)
    if abs(cur - prev) / prev >= rate_move_threshold:
        d = "up" if cur > prev else "down"
        out.append(Trigger("rate_move", f"INR→CNY mid-market moved {d} {abs(cur-prev)/prev*100:.2f}% over 7 days.",
                           {"prev": prev, "cur": cur}))
    # Low runway.
    rw = runway_months(passport, rates, day_index, history_cny)
    if rw < passport.rules.runway_alert_months:
        out.append(Trigger("low_runway", f"Only {rw:.1f} months of money left after obligations.", {"months": rw}))
    # Late income.
    for inc in passport.expected_income:
        if not inc.get("received") and date.fromisoformat(inc["expected"]) < today:
            out.append(Trigger("late_income", f"{inc['label']} (CNY {inc['amount_cny']:,.0f}) was expected on "
                               f"{inc['expected']} and has not arrived.", inc))
    # Student-set rate targets (the agent acts on these; it does not predict).
    for t in passport.rules.rate_targets:
        if cur >= t["rate"]:
            out.append(Trigger("rate_target", f"Rate {cur:.4f} reached your target {t['rate']:.4f}: "
                               f"convert CNY {t['convert_cny']:,.0f}.", t))
    return out
