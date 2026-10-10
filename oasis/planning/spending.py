"""Step 2 - spending categorisation and the cold-start -> own-pattern forecast.

A newly arrived student has no history, so the forecast starts from the student's budget plus labelled
reference costs (MOCK reference data). As transactions accumulate they are categorised by simple keyword
rules and, once there is enough history, the forecast switches to the student's own per-category averages
with a damped trend. The model is deliberately simple and explainable; its backtest error is reported.
"""
from __future__ import annotations
import random
from datetime import date, timedelta

from ..passport.models import Passport

# Labelled reference costs for the cold-start month (Shenzhen, CNY). MOCK reference data.
REFERENCE_COSTS_CNY = {"food": 1500, "transport": 250, "phone_internet": 150, "misc": 400}
CATEGORIES = list(REFERENCE_COSTS_CNY) + ["groceries"]
MIN_DAYS_OWN_PATTERN = 14
MIN_TX_OWN_PATTERN = 15
BACKTEST_MIN_DAYS = 21

KEYWORDS = {
    "food": ["lunch", "dinner", "breakfast", "meituan", "restaurant", "cafe", "coffee", "luckin", "noodle", "canteen", "milk tea"],
    "groceries": ["supermarket", "grocery", "groceries", "market", "dashang", "walmart", "sam's", "vegetable"],
    "transport": ["metro", "subway", "bus", "didi", "taxi", "ride", "bike", "ticket", "train"],
    "phone_internet": ["mobile", "unicom", "telecom", "data plan", "top-up", "topup", "sim", "wifi", "internet"],
}


def categorise(desc: str) -> str:
    low = desc.casefold()
    for cat, words in KEYWORDS.items():
        if any(w in low for w in words):
            return cat
    return "misc"


def add_transaction(passport: Passport, when: date, desc: str, amount_cny: float, source: str = "manual") -> dict:
    tx = {"date": when.isoformat(), "desc": desc, "amount_cny": round(float(amount_cny), 2),
          "category": categorise(desc), "source": source}
    passport.transactions.append(tx)
    return tx


def simulate_spending(passport: Passport, start: date, days: int, seed: int = 11) -> list[dict]:
    """Deterministic MOCK wallet spending, imported as if from the student's wallet. Label it as mock in the UI."""
    rng = random.Random(f"{seed}-{start.isoformat()}")
    out = []
    for i in range(days):
        d = start + timedelta(days=i)
        out.append(add_transaction(passport, d, rng.choice(["Meituan lunch", "Canteen lunch", "Noodle shop lunch"]),
                                   rng.uniform(14, 32), "mock"))
        out.append(add_transaction(passport, d, rng.choice(["Dinner restaurant", "Meituan dinner", "Milk tea and snack"]),
                                   rng.uniform(18, 45), "mock"))
        out.append(add_transaction(passport, d, "Shenzhen Metro", rng.uniform(6, 14), "mock"))
        if d.weekday() == 6:
            out.append(add_transaction(passport, d, "Dashang supermarket groceries", rng.uniform(70, 150), "mock"))
        if d.day == 1 or (i == 3):
            out.append(add_transaction(passport, d, "China Mobile data plan top-up", 50.0, "mock"))
        if rng.random() < 0.18:
            out.append(add_transaction(passport, d, "Stationery and printing", rng.uniform(8, 40), "mock"))
    return out


def _monthly_by_category(txs: list[dict], first: date, last: date) -> dict[str, float]:
    span = max((last - first).days + 1, 1)
    tot: dict[str, float] = {}
    for t in txs:
        tot[t["category"]] = tot.get(t["category"], 0.0) + t["amount_cny"]
    return {c: v / span * 30 for c, v in tot.items()}


def _forecast_total(txs: list[dict], first: date, last: date) -> tuple[dict[str, float], float]:
    """Per-category daily average x 30 with a damped trend (second half vs first half of the window)."""
    base = _monthly_by_category(txs, first, last)
    span = (last - first).days + 1
    mid = first + timedelta(days=span // 2)
    a = sum(t["amount_cny"] for t in txs if date.fromisoformat(t["date"]) < mid)
    b = sum(t["amount_cny"] for t in txs if date.fromisoformat(t["date"]) >= mid)
    ratio = (b / max(span - span // 2, 1)) / (a / max(span // 2, 1)) if a > 0 and b > 0 else 1.0
    factor = 1 + 0.5 * (min(max(ratio, 0.8), 1.2) - 1)   # damped, clamped trend
    return {c: round(v * factor, 2) for c, v in base.items()}, round(factor, 3)


def summarize(passport: Passport) -> dict:
    txs = passport.transactions
    budget = float(max(passport.student.monthly_budget_cny, sum(REFERENCE_COSTS_CNY.values())))
    if not txs:
        days = 0
    else:
        dates = sorted(date.fromisoformat(t["date"]) for t in txs)
        first, last = dates[0], dates[-1]
        days = len({d for d in dates})
    own = bool(txs) and days >= MIN_DAYS_OWN_PATTERN and len(txs) >= MIN_TX_OWN_PATTERN
    out = {"n_transactions": len(txs), "days_of_history": days, "min_days_needed": MIN_DAYS_OWN_PATTERN,
           "reference_costs_cny": REFERENCE_COSTS_CNY, "label": "MOCK reference costs and mock wallet data"}
    if not own:
        out.update(basis="cold_start", monthly_cny=budget,
                   basis_text="student budget + labelled reference costs (cold start)",
                   categories={c: {"monthly_cny": v, "share": round(v / sum(REFERENCE_COSTS_CNY.values()), 3)}
                               for c, v in REFERENCE_COSTS_CNY.items()},
                   forecast_error_pct=None, trend_factor=1.0,
                   note=f"Need {MIN_DAYS_OWN_PATTERN} days / {MIN_TX_OWN_PATTERN} transactions to switch to your own pattern.")
        return out
    cats, factor = _forecast_total(txs, first, last)
    total = round(sum(cats.values()), 2)
    out.update(basis="own_pattern", monthly_cny=total, basis_text="own spending pattern (per-category average + damped trend)",
               categories={c: {"monthly_cny": v, "share": round(v / total, 3) if total else 0} for c, v in sorted(cats.items())},
               trend_factor=factor, forecast_error_pct=None, note="")
    span = (last - first).days + 1
    if span >= BACKTEST_MIN_DAYS:   # backtest: forecast the last 7 days from everything before them
        cut = last - timedelta(days=6)
        train = [t for t in txs if date.fromisoformat(t["date"]) < cut]
        test = sum(t["amount_cny"] for t in txs if date.fromisoformat(t["date"]) >= cut)
        if train and test > 0:
            tf, tfac = _forecast_total(train, first, cut - timedelta(days=1))
            pred = sum(tf.values()) / 30 * 7
            out["forecast_error_pct"] = round(abs(pred - test) / test * 100, 1)
    return out
