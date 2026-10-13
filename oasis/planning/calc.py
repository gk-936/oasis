"""Calculators for the v3 planner protocol: `size_conversion` and `facts_sheet`.

Both are pure functions of the World (Passport, rates, corridor rules): no side effects, no money moves, nothing is
stored. They exist so the model never has to do INR, fee or rounding arithmetic in its head; the model still decides
WHAT to convert, on which route and date, and writes the plan itself. The validator stays the only judge.
"""
from __future__ import annotations
import math
from collections import defaultdict
from datetime import date, timedelta

from ..mock.rates import ROUTES, delivered_amount
from ..trust import corridor
from .routes import inr_needed
from .validator import ROUTE_BY_ID, REMITTERS, _tcs, lrs_limit_inr, required_obligations, safe_quota_inr

# size_conversion adds this much CNY on top of the requested target before rounding the INR up to a whole rupee. It covers
# the 2-decimal rounding of the delivered amount and the validator's CNY comparison; it costs about INR 14 per conversion.
HEADROOM_CNY = 1.0


def size_send_inr(rates_mid: float, route, target_cny: float) -> int:
    """Smallest whole-rupee send_inr whose delivered CNY (rounded to 2 decimals, as the validator does) is at least
    target_cny + HEADROOM_CNY. Exact inverse of routes.delivered_amount."""
    need = float(target_cny) + HEADROOM_CNY
    per_inr = rates_mid * (1 - route.rate_spread) * (1 - route.pct_fee)
    send = max(1, math.ceil(route.fixed_fee_inr + need / per_inr))
    while round(delivered_amount(send, route, rates_mid), 2) < need:      # float guard; normally 0 iterations
        send += 1
    return send


def size_conversion(world, target_cny, route_id, convert_date, remitter: str = "student", due: str | None = None) -> dict:
    p = world.passport
    route = ROUTE_BY_ID.get(route_id)
    if route is None:
        return {"error": f"unknown route {route_id!r}", "route_ids": list(ROUTE_BY_ID)}
    target = float(target_cny)
    if not target > 0:
        return {"error": "target_cny must be positive"}
    if remitter not in REMITTERS:
        return {"error": f"remitter must be one of {list(REMITTERS)}"}
    d = date.fromisoformat(str(convert_date))
    if d < world.today:
        return {"error": f"convert_date {d} is before today ({world.today})"}
    mid = world.rates.mid(world.day_index)
    send = size_send_inr(mid, route, target)
    delivered = round(delivered_amount(send, route, mid), 2)
    arrives = d + timedelta(days=route.days)
    out = {"route_id": route.id, "remitter": remitter, "send_inr": send, "delivered_cny": delivered, "headroom_cny": HEADROOM_CNY,
           "arrives_on": arrives.isoformat(), "effective_rate": round(delivered / send, 6)}
    if due:
        dd = date.fromisoformat(str(due))
        out["on_time"] = arrives <= dd
        out["latest_convert_date"] = (dd - timedelta(days=route.days)).isoformat()
    ok = [r for r in ROUTES if not r.typical_bank and (not due or d + timedelta(days=r.days) <= date.fromisoformat(str(due)))]
    if ok:
        best = min(ok, key=lambda r: size_send_inr(mid, r, target))
        bs = size_send_inr(mid, best, target)
        if best.id != route.id and bs < send:
            out["cheaper_route"] = {"route_id": best.id, "send_inr": bs, "saves_inr": send - bs, "arrives_on": (d + timedelta(days=best.days)).isoformat()}
    spendable = max(0.0, p.balance("INR") - _reserve_inr(p))
    if remitter == "student" and send > spendable + 0.005:      # over what the student may spend: hand back the exact split
        part = math.floor(spendable)
        rest = max(0.0, target - round(delivered_amount(part, route, mid), 2)) if part > route.fixed_fee_inr + 1 else target
        out["split"] = {"student_send_inr": part if part > route.fixed_fee_inr + 1 else 0, "parent_send_inr": size_send_inr(mid, route, rest),
                        "why": f"the student can spend at most INR {spendable:,.0f} (rate-target reserve kept); use these two convert steps instead of one"}
    y = str(d.year)
    room = max(0.0, safe_quota_inr() - p.safe_used_inr.get(y, 0.0))
    out["safe"] = {"year": y, "room_inr": round(room), "fits": send <= room + 0.005}
    if not out["safe"]["fits"]:
        out["safe"]["stage_rest_on"] = f"{int(y) + 1}-01-01"
        now = math.floor(room)
        if now > route.fixed_fee_inr + 1:
            left = max(0.0, target - round(delivered_amount(now, route, mid), 2))
            out["safe"]["split"] = {"this_year_send_inr": now, "next_year_send_inr": size_send_inr(mid, route, left), "next_year_date": out["safe"]["stage_rest_on"]}
    rules = corridor.load_rules()
    used = p.remitted_inr_fy.get(remitter, 0.0)
    tr = corridor.tcs_rate(p, "tuition", rules)
    out["tcs_inr"] = _tcs(used, send, rules, p.funding_source == "education_loan", tr["rate"])
    out["lrs_ok"] = used + send <= lrs_limit_inr() + 0.005
    return out


def _reserve_inr(p) -> float:
    return sum(t["convert_cny"] / t["rate"] for t in p.rules.rate_targets if t.get("status") in ("watching", "awaiting_approval") and t.get("rate"))


def facts_sheet(world) -> dict:
    """Compact deterministic numbers for planning. No advice, no prose."""
    p, today = world.passport, world.today
    mid = world.rates.mid(world.day_index)
    rules = corridor.load_rules()
    need = required_obligations(p)
    by_month: dict[str, float] = defaultdict(float)
    by_year: dict[str, float] = defaultdict(float)
    for o in need:
        by_month[o.due[:7]] += o.remaining
        by_year[o.due[:4]] += o.remaining
    inr, cny = p.balance("INR"), p.balance("CNY")
    reserve = _reserve_inr(p)
    total = sum(o.remaining for o in need)
    short_cny = max(0.0, total - cny)
    spendable = max(0.0, inr - reserve)
    est = None
    if short_cny > 0:
        est = min(inr_needed(world.rates, r, short_cny + HEADROOM_CNY, world.day_index) for r in ROUTES if not r.typical_bank)
    quota = safe_quota_inr()
    last_year = max([today.year] + [int(o.due[:4]) for o in need])
    tr = corridor.tcs_rate(p, "tuition", rules)
    lrs, thr = lrs_limit_inr(), tr["threshold_inr"]
    remitter = lambda who: {"remitted_inr_fy": round(p.remitted_inr_fy.get(who, 0.0)), "lrs_left_inr": round(max(0.0, lrs - p.remitted_inr_fy.get(who, 0.0))),
                            "tcs_free_left_inr": round(max(0.0, thr - p.remitted_inr_fy.get(who, 0.0)))}
    sugg = None
    if short_cny > 0 and need:
        avail = (min(date.fromisoformat(o.due) for o in need) - today).days - 2        # arrive 2 days before the earliest due date
        pool = [r for r in ROUTES if not r.typical_bank and r.days <= avail]
        if pool:
            r = min(pool, key=lambda r: size_send_inr(mid, r, short_cny))
            sugg = {"route_id": r.id, "convert_date": today.isoformat(), "target_cny": round(short_cny, 2),
                    "note": "ONE conversion funds every obligation; call size_conversion with these values for the exact send_inr and any split"}
    return {
        "suggested_conversion": sugg,
        "today": today.isoformat(), "mid_cny_per_inr": mid,
        "obligations": [{"id": o.id, "payee_id": o.payee_id, "amount_cny": o.remaining, "due": o.due} for o in need],
        "cny_needed": {"total": round(total, 2), "by_month": {k: round(v, 2) for k, v in sorted(by_month.items())},
                       "by_year": {k: round(v, 2) for k, v in sorted(by_year.items())}},
        "balances": {"INR": inr, "CNY": cny}, "rate_target_reserve_inr": round(reserve, 2), "student_spendable_inr": round(spendable, 2),
        "cny_shortfall": round(short_cny, 2), "inr_needed_est": None if est is None else round(est), "inr_short_est": None if est is None else round(max(0.0, est - spendable)),
        "safe": {"quota_inr": round(quota), "left_by_year": {str(y): round(max(0.0, quota - p.safe_used_inr.get(str(y), 0.0))) for y in range(today.year, last_year + 1)},
                 "new_year_starts": f"{today.year + 1}-01-01"},
        "student": remitter("student"), "parent": {**remitter("parent"), "consent_needed": True, "tcs_rate": tr["rate"]},
        "routes": [{"id": r.id, "days": r.days, "fixed_fee_inr": r.fixed_fee_inr, "pct_fee": r.pct_fee, "spread": r.rate_spread,
                    **({"bank": True} if r.typical_bank else {})} for r in ROUTES],
    }
