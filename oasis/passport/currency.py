"""Multi-currency view and sandbox wallet conversions.

Holdings in INR (home), CNY (host) and the common tuition / scholarship currencies USD, EUR, GBP and AUD, each valued in
CNY and INR at the mid rate. The INR->CNY mid is the world's rate (mock snapshot, or live ECB with OASIS_RATES=live); the
other crosses are live from the same
provider response when OASIS_RATES=live, else the snapshot in oasis/mock/fx.py. The view is a valuation aid, not a quote: a real conversion pays a spread and
fees, which `convert` applies (MOCK wallet pricing). The CNY balance lives in the sandbox ledger, so a conversion into or
out of CNY moves the ledger account and the Passport is re-synced from it.
"""
from __future__ import annotations

from datetime import timedelta

from ..mock import fx

SUPPORTED = fx.CURRENCIES
COVERAGE_DAYS = 60


def currency_view(passport, rate_cny_per_inr: float, rates: dict | None = None, today=None,
                  crosses: dict | None = None) -> dict:
    rate = float(rate_cny_per_inr)
    table = fx.per_usd(rate, crosses=crosses) if rate > 0 else None
    holdings = []
    for cur in SUPPORTED:
        amt = round(passport.balance(cur), 2)
        if table:
            v_cny = amt * fx.mid(cur, "CNY", table)
            v_inr = amt * fx.mid(cur, "INR", table)
        else:
            v_cny = amt if cur == "CNY" else 0.0
            v_inr = amt if cur == "INR" else 0.0
        holdings.append({"currency": cur, "symbol": fx.SYMBOLS[cur], "amount": amt,
                         "value_cny": round(v_cny, 2), "value_inr": round(v_inr, 2)})
    total_cny = round(sum(h["value_cny"] for h in holdings), 2)
    total_inr = round(sum(h["value_inr"] for h in holdings), 2)
    exposure = {h["currency"]: (round(100 * h["value_cny"] / total_cny, 1) if total_cny > 0 else 0.0) for h in holdings}
    out = {
        "supported": list(SUPPORTED),
        "holdings": holdings,
        "rate_cny_per_inr": rate,
        "cny_per_unit": {c: round(fx.mid(c, "CNY", table), 6) for c in SUPPORTED} if table else None,
        "rate_source": (rates or {}).get("source"), "rate_label": (rates or {}).get("label"),
        "total_cny": total_cny, "total_inr": total_inr,
        "exposure_pct": exposure,
        "crosses_live": bool(crosses),
        "note": "Valued at the mid rate; a real conversion pays a spread and fees.",
    }
    if today is not None:
        out["coverage"] = coverage(passport, today)
    return out


def coverage(passport, today) -> dict:
    """Do the CNY funds on hand cover the CNY obligations due in the next COVERAGE_DAYS days?"""
    horizon = (today + timedelta(days=COVERAGE_DAYS)).isoformat()      # overdue obligations count too
    due = round(sum(o.amount for o in passport.obligations
                    if o.status in ("pending", "planned") and o.due <= horizon), 2)
    cny = round(passport.balance("CNY"), 2)
    return {"days": COVERAGE_DAYS, "due_cny": due, "cny_on_hand": cny, "shortfall_cny": round(max(0.0, due - cny), 2)}


def convert(world, amount, src: str, dst: str) -> dict:
    """Convert between the student's own sandbox balances at the MOCK wallet price. Raises fx.FxError on refusal."""
    from ..world import STUDENT_ACCT
    table = fx.table_for(world.rates, world.day_index)
    q = fx.quote(amount, src, dst, table)
    p = world.passport
    if q.amount > p.balance(src) + 0.005:
        raise fx.FxError(f"not enough {src}: you hold {fx.SYMBOLS[src]}{p.balance(src):,.2f}")
    acct = world.ledger.accounts[STUDENT_ACCT]
    for cur, delta in ((src, -q.amount), (dst, q.received)):
        if cur == "CNY":
            acct.balance = round(acct.balance + delta, 2)
        else:
            p.set_balance(cur, round(p.balance(cur) + delta, 2))
    world.sync_balances()
    rec = {"day": world.today.isoformat(), **q.to_dict()}
    world.audit.append("fx_conversion", {k: rec[k] for k in ("day", "from", "to", "amount", "rate", "fee", "received")})
    return rec
