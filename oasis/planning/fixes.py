"""Numeric `fix` hints for validator errors, shown to the model only in the v3 presentation.

Each fix is derived from the same numbers the validator used (plus `calc.size_send_inr`); it never changes a validator
rule or severity, and nothing here edits a plan: the model reads the fix and writes the corrected plan itself.

Shapes (all keys optional except where noted; step = index in the submitted plan):
  {"step": i, "set": {field: value}}            change fields of step i
  {"add_convert": {date, route_id, send_inr, remitter}}   add this conversion step
  {"add_pay": {date, obligation_id, payee_id, amount_cny}}  add this pay step
  {"remove_step": i}                             delete step i
plus the numbers the fix is based on (short_cny, over_inr, latest_date, max_send_inr, ...).
"""
from __future__ import annotations
import math
from datetime import date, timedelta

from ..mock.rates import ROUTES, delivered_amount
from .calc import size_send_inr
from .validator import ROUTE_BY_ID

NON_BANK = [r for r in ROUTES if not r.typical_bank]


def derive_fixes(world, steps, errors: list[dict]) -> list[dict | None]:
    """One entry per error (None when the code has no derivable correction). Never raises."""
    out: list[dict | None] = []
    for e in errors:
        try:
            out.append(_fix(world, steps if isinstance(steps, list) else [], e))
        except Exception:  # noqa: BLE001 - a fix is advisory; a failure here must never break the validator's answer
            out.append(None)
    return out


def _step(steps, e):
    i = e.get("step")
    return (i, steps[i]) if isinstance(i, int) and 0 <= i < len(steps) and isinstance(steps[i], dict) else (None, None)


def _d(v) -> date:
    return date.fromisoformat(str(v))


def _ob(world, s):
    return world.passport.obligation(str(s.get("obligation_id")))


def _mid(world) -> float:
    return world.rates.mid(world.day_index)


def _next_pay(steps, after: date) -> date | None:
    ds = []
    for s in steps:
        if isinstance(s, dict) and s.get("action") == "pay":
            try:
                d = _d(s.get("date"))
            except (TypeError, ValueError):
                continue
            if d >= after:
                ds.append(d)
    return min(ds) if ds else None


def _shift_to_parent(world, steps, i: int, short: float) -> dict:
    """Take `short` INR off student conversion i and have the parent convert enough to deliver the same CNY."""
    s = steps[i]
    route, d, mid = ROUTE_BY_ID[s["route_id"]], _d(s["date"]), _mid(world)
    send = float(s["send_inr"])
    new_send = math.floor(send - short)
    fix = {"over_inr": round(short, 2)}
    if new_send <= route.fixed_fee_inr + 1:
        return {**fix, "step": i, "set": {"remitter": "parent"}}
    lost = delivered_amount(send, route, mid) - delivered_amount(new_send, route, mid)
    return {**fix, "step": i, "set": {"send_inr": new_send},
            "add_convert": {"date": d.isoformat(), "route_id": route.id, "send_inr": size_send_inr(mid, route, lost), "remitter": "parent"}}


def _fix(world, steps, e: dict) -> dict | None:
    code, data, today, mid = e.get("code"), e.get("data") or {}, world.today, _mid(world)
    i, s = _step(steps, e)
    if code == "amount_mismatch" and s is not None:
        ob = _ob(world, s)
        return {"step": i, "set": {"amount_cny": ob.remaining}} if ob else None
    if code in ("payee_mismatch", "unknown_payee") and s is not None:
        ob = _ob(world, s)
        return {"step": i, "set": {"payee_id": ob.payee_id}} if ob else None
    if code == "late_payment" and s is not None:
        ob = _ob(world, s)
        return {"step": i, "set": {"date": ob.due}, "latest_date": ob.due} if ob else None
    if code == "date_in_past" and s is not None:
        return {"step": i, "set": {"date": today.isoformat()}}
    if code == "duplicate_payment" and s is not None:
        return {"remove_step": i}
    if code == "obligation_unfunded":
        ob = world.passport.obligation(str(e.get("message", "").split(" ", 1)[0]))
        if ob is None:
            return None
        pay = max(today, _d(ob.due) - timedelta(days=2))
        return {"add_pay": {"date": pay.isoformat(), "obligation_id": ob.id, "payee_id": ob.payee_id, "amount_cny": ob.remaining}}
    if code == "unknown_route" and s is not None:
        d, send = _d(s["date"]), float(s.get("send_inr") or 1)
        deadline = _next_pay(steps, d)
        pool = [r for r in NON_BANK if deadline is None or d + timedelta(days=r.days) <= deadline] or sorted(NON_BANK, key=lambda r: r.days)[:1]
        return {"step": i, "set": {"route_id": max(pool, key=lambda r: delivered_amount(send, r, mid)).id}}
    if code == "insufficient_inr" and s is not None and s.get("route_id") in ROUTE_BY_ID:
        return _shift_to_parent(world, steps, i, float(data["short_inr"]))
    if code == "rate_target_reserve":
        short = float(data["reserve_inr"]) - float(data["left_inr"])
        cand = [(str(x.get("date")), k) for k, x in enumerate(steps)
                if isinstance(x, dict) and x.get("action") == "convert" and (x.get("remitter") or "student") == "student" and x.get("route_id") in ROUTE_BY_ID]
        return _shift_to_parent(world, steps, max(cand)[1], short) if cand else None
    if code == "safe_quota_exceeded" and s is not None:
        route, d, y = ROUTE_BY_ID[s["route_id"]], _d(s["date"]), int(data["year"])
        room, send = float(data["max_send_inr"]), float(s["send_inr"])
        jan = date(y + 1, 1, 1)
        rem = s.get("remitter") or "student"
        if room < route.fixed_fee_inr + 1:
            return {"step": i, "set": {"date": jan.isoformat()}, "max_send_inr": round(room), "stage_on": jan.isoformat()}
        new_send = math.floor(room)
        lost = delivered_amount(send, route, mid) - delivered_amount(new_send, route, mid)
        rest = size_send_inr(mid, route, lost)
        return {"step": i, "set": {"send_inr": new_send}, "max_send_inr": round(room), "stage_on": jan.isoformat(),
                "add_convert": {"date": jan.isoformat(), "route_id": route.id, "send_inr": rest, "remitter": rem},
                "arrives_on": (jan + timedelta(days=route.days)).isoformat()}
    if code == "insufficient_cny" and s is not None:
        pay_d, short = _d(s["date"]), float(data["short_cny"])
        ok = [r for r in NON_BANK if today + timedelta(days=r.days) <= pay_d]
        if not ok:
            fastest = min(NON_BANK, key=lambda r: r.days)
            return {"short_cny": round(short, 2), "no_route_arrives_by": pay_d.isoformat(),
                    "earliest_pay_date": (today + timedelta(days=fastest.days)).isoformat()}
        best = min(ok, key=lambda r: size_send_inr(mid, r, short))
        return {"short_cny": round(short, 2),
                "add_convert": {"date": today.isoformat(), "route_id": best.id, "send_inr": size_send_inr(mid, best, short), "remitter": "student"}}
    if code == "route_too_slow" and s is not None:
        pay_d = _d(s["date"])
        late = []
        for k, x in enumerate(steps):
            if isinstance(x, dict) and x.get("action") == "convert" and x.get("route_id") in ROUTE_BY_ID:
                try:
                    cd = _d(x["date"])
                except (TypeError, ValueError):
                    continue
                if cd + timedelta(days=ROUTE_BY_ID[x["route_id"]].days) > pay_d:
                    late.append((cd + timedelta(days=ROUTE_BY_ID[x["route_id"]].days), k, cd, x))
        if not late:
            return None
        _, k, cd, x = max(late)
        route, send = ROUTE_BY_ID[x["route_id"]], float(x.get("send_inr") or 1)
        by = pay_d - timedelta(days=route.days)
        faster = sorted((r for r in NON_BANK if cd + timedelta(days=r.days) <= pay_d), key=lambda r: -delivered_amount(send, r, mid))
        fix: dict = {"step": k, "pay_date": pay_d.isoformat(), "faster_route_ids": [r.id for r in faster]}
        if by >= today:
            fix["convert_by"] = by.isoformat()
            fix["set"] = {"date": by.isoformat()}
        elif faster:
            fix["set"] = {"route_id": faster[0].id}
        return fix
    return None
