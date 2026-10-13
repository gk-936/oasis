"""Peer netting (MOCK, simulation only). INR->CNY payers are matched against CNY->INR payers in a pool; matched
volume settles at mid-rate with no spread or bank leg, the residual goes through the normal cheapest on-time route.

Netting never bypasses recipient verification, policy or approval: a payment that is not payee-verified AND approved
is not eligible for the pool and is routed alone. Real netting needs a licensed counterparty and regulatory approval;
nothing here moves money. All amounts are in CNY-equivalent at the MOCK mid-rate.
"""
from __future__ import annotations
from dataclasses import dataclass

from ..mock.rates import ROUTES, MockRates
from ..planning.routes import inr_needed

NET_SETTLE_DAYS = 2          # a pooled match settles after the next netting cycle (MOCK)
LABEL = "MOCK: simulated pool; real netting needs a licensed counterparty and regulatory approval"


@dataclass(frozen=True)
class Payment:
    id: str
    direction: str            # "INR_CNY" or "CNY_INR"
    amount_cny: float         # CNY-equivalent value to deliver
    due_in_days: int
    payee_verified: bool = True
    approved: bool = True     # policy + approval already passed upstream


def _alone_cost(rates: MockRates, amt: float, due_days: int) -> float:
    """CNY lost vs mid when routing `amt` alone on the cheapest on-time route (fastest if none is on time).
    CNY->INR is assumed to cost the same as the mirror INR->CNY route (MOCK assumption)."""
    if amt <= 0:
        return 0.0
    mid = rates.mid(0)
    rs = [r for r in ROUTES if r.days <= due_days] or [min(ROUTES, key=lambda r: r.days)]
    return min(inr_needed(rates, r, amt) * mid - amt for r in rs)


def eligible(p: Payment) -> bool:
    return p.payee_verified and p.approved and p.due_in_days >= NET_SETTLE_DAYS and p.amount_cny > 0


def match(pool: list[Payment]) -> list[tuple[str, str, float]]:
    """Deterministic greedy: earliest deadline first, ties by id. Returns (inr_payer, cny_payer, cny_volume)."""
    key = lambda p: (p.due_in_days, p.id)
    a = sorted((p for p in pool if p.direction == "INR_CNY" and eligible(p)), key=key)
    b = sorted((p for p in pool if p.direction == "CNY_INR" and eligible(p)), key=key)
    ra, rb = {p.id: p.amount_cny for p in a}, {p.id: p.amount_cny for p in b}
    out, j = [], 0
    for p in a:
        while ra[p.id] > 1e-9 and j < len(b):
            q = b[j]
            v = min(ra[p.id], rb[q.id])
            if v > 1e-9:
                out.append((p.id, q.id, round(v, 2)))
                ra[p.id] -= v
                rb[q.id] -= v
            if rb[q.id] <= 1e-9:
                j += 1
    return out


def net(pool: list[Payment], rates: MockRates | None = None) -> dict:
    rates = rates or MockRates()
    matches = match(pool)
    matched: dict[str, float] = {}
    for x, y, v in matches:
        matched[x] = matched.get(x, 0.0) + v
        matched[y] = matched.get(y, 0.0) + v
    rows, alone_total, netted_total = [], 0.0, 0.0
    for p in pool:
        m = round(min(matched.get(p.id, 0.0), p.amount_cny), 2)
        resid = round(p.amount_cny - m, 2)
        alone = _alone_cost(rates, p.amount_cny, p.due_in_days)
        netted = _alone_cost(rates, resid, p.due_in_days)
        alone_total += alone
        netted_total += netted
        rows.append({"id": p.id, "direction": p.direction, "amount_cny": p.amount_cny, "matched_cny": m,
                     "residual_cny": resid, "cost_alone_cny": round(alone, 2), "cost_netted_cny": round(netted, 2),
                     "eligible": eligible(p)})
    vol = sum(p.amount_cny for p in pool)
    saving = round(alone_total - netted_total, 2)
    return {"label": LABEL, "payments": rows,
            "matches": [{"inr_payer": x, "cny_payer": y, "cny": v} for x, y, v in matches],
            "matched_volume_cny": round(sum(v for *_, v in matches), 2), "total_volume_cny": round(vol, 2),
            "cost_alone_cny": round(alone_total, 2), "cost_netted_cny": round(netted_total, 2),
            "saving_cny": saving, "saving_pct": round(saving / alone_total * 100, 2) if alone_total else 0.0}
