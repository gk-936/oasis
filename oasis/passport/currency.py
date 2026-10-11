"""Multi-currency view: the student's holdings in the two supported currencies, valued both ways at the current rate.

Only INR <-> CNY is supported. The rate is the mid rate in CNY per INR (mock snapshot, or live ECB with OASIS_RATES=live);
it is a valuation aid, not a quote: real conversions pay a route spread and fees. There is no wallet in any other currency.
"""
from __future__ import annotations

SUPPORTED = ("INR", "CNY")


def currency_view(passport, rate_cny_per_inr: float, rates: dict | None = None) -> dict:
    inr = round(passport.balance("INR"), 2)
    cny = round(passport.balance("CNY"), 2)
    rate = float(rate_cny_per_inr)
    cny_value_of_inr = inr * rate
    total_cny = round(cny + cny_value_of_inr, 2)
    total_inr = round(inr + (cny / rate if rate > 0 else 0.0), 2)
    share_inr = round(100 * cny_value_of_inr / total_cny, 1) if total_cny > 0 else 0.0
    return {
        "supported": list(SUPPORTED),
        "holdings": [{"currency": "INR", "amount": inr, "value_cny": round(cny_value_of_inr, 2)},
                     {"currency": "CNY", "amount": cny, "value_cny": cny}],
        "rate_cny_per_inr": rate,
        "rate_source": (rates or {}).get("source"), "rate_label": (rates or {}).get("label"),
        "total_cny": total_cny, "total_inr": total_inr,
        "exposure_pct": {"INR": share_inr, "CNY": round(100 - share_inr, 1) if total_cny > 0 else 0.0},
        "note": "Valued at the mid rate; a real conversion pays the route spread and fees. Only INR and CNY are supported.",
    }
