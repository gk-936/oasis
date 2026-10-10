"""Step 2 - route comparison on the amount that actually arrives."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date

from ..mock.rates import ROUTES, MockRates, Route, delivered_amount
from ..mock.wallet import foreign_card_cost, local_account_cost
from ..passport.models import Passport
from ..trust import corridor


@dataclass
class RouteQuote:
    route: Route
    send_inr: float
    delivered_cny: float
    effective_rate: float
    arrives_in_days: int
    on_time: bool
    cost_vs_mid_pct: float


def quote_routes(rates: MockRates, send_inr: float, today: date, due: date | None = None,
                 day_index: int = 0) -> list[RouteQuote]:
    mid = rates.mid(day_index)
    out = []
    for r in ROUTES:
        d = delivered_amount(send_inr, r, mid)
        on_time = due is None or (due - today).days >= r.days
        out.append(RouteQuote(r, send_inr, round(d, 2), round(d / send_inr, 6), r.days, on_time,
                              round((1 - d / (send_inr * mid)) * 100, 3)))
    return out


def rank(quotes: list[RouteQuote]) -> list[RouteQuote]:
    """Delivered amount, then delivery time, then reliability. Late routes are excluded."""
    ok = [q for q in quotes if q.on_time]
    return sorted(ok, key=lambda q: (-q.delivered_cny, q.arrives_in_days, -q.route.reliability))


def best_route(rates: MockRates, send_inr: float, today: date, due: date | None, day_index: int = 0):
    ranked = rank(quote_routes(rates, send_inr, today, due, day_index))
    bank = next(q for q in quote_routes(rates, send_inr, today, due, day_index) if q.route.typical_bank)
    return (ranked[0] if ranked else None), bank


def savings_vs_bank(best: RouteQuote, bank: RouteQuote) -> dict:
    s = round(best.delivered_cny - bank.delivered_cny, 2)
    return {"route": best.route.name, "delivered_cny": best.delivered_cny,
            "bank_route": bank.route.name, "bank_delivered_cny": bank.delivered_cny,
            "saved_cny": s, "saved_pct": round(s / bank.delivered_cny * 100, 2) if bank.delivered_cny else 0.0}


def inr_needed(rates: MockRates, route: Route, target_cny: float, day_index: int = 0) -> float:
    """Invert the delivered-amount formula (binary search keeps it exact and simple)."""
    lo, hi = 0.0, target_cny / (rates.mid(day_index) * 0.5) + route.fixed_fee_inr * 2
    for _ in range(60):
        mid = (lo + hi) / 2
        if delivered_amount(mid, route, rates.mid(day_index)) < target_cny:
            lo = mid
        else:
            hi = mid
    return round(hi, 2)


def last_mile(amount_cny: float) -> dict:
    """Foreign-card wallet payment vs a local Chinese bank account."""
    card, local = foreign_card_cost(amount_cny), local_account_cost(amount_cny)
    return {"foreign_card": card, "local_account": local,
            "extra_cost_cny": round(card["total_cost"] - local["total_cost"], 2)}


def corridor_notes(passport: Passport, amount_inr: float, purpose: str, remitter: str = "student") -> list[str]:
    res = corridor.check(passport, payee_type={"tuition": "university", "rent": "landlord"}.get(purpose, "family"),
                         purpose=purpose, amount_cny=0, amount_inr=amount_inr, remitter=remitter)
    return [f.message for f in res.findings if f.severity in ("warn", "hold", "info")]
