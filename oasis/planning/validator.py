"""Deterministic plan validator (spec step 2, "agentic planning").

The LLM can only PROPOSE a plan. This module checks every proposal against the Passport, the corridor rules and
the mock route table, and returns concrete errors the model can act on. It moves no money and never trusts the
proposal: every number it reports is recomputed here.

Plan steps (JSON objects):
  convert  {"action":"convert","date":"YYYY-MM-DD","send_inr":N,"route_id":"route_...","remitter":"student"|"parent"}
  pay      {"action":"pay","date":"YYYY-MM-DD","obligation_id":"obl_...","payee_id":"payee_...","amount_cny":N}

Rules (each failure is an error with a code and a hint; warnings never block):
  bad_step / bad_date / date_in_past         malformed or backdated step
  unknown_obligation / already_paid / obligation_frozen / duplicate_payment
  unknown_payee / payee_mismatch / amount_mismatch
  late_payment                               paid after the due date
  obligation_unfunded                        a required obligation has no pay step
  unknown_route / bad_amount
  insufficient_inr                           the student's INR would go negative
  insufficient_cny / route_too_slow          CNY not in the account on the pay date (or arrives too late)
  safe_quota_exceeded                        conversions in one calendar year above the SAFE facilitation quota
  lrs_exceeded                               remitter's LRS limit for the financial year
  rate_target_reserve                        INR a student-set rate target needs is no longer unconverted
Warnings: tcs, tcs_near, safe_quota_near, small_conversion, route_not_cheapest, low_runway, late_income_ignored,
approval_expected, parent_remitter.

Rates are quoted at today's mock mid-market rate for the whole horizon. That is a quote, not a forecast: the agent
does not predict exchange rates.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..mock.rates import ROUTES, Route, delivered_amount
from ..trust import corridor

CNY_TOL = 0.5
ROUTE_BY_ID = {r.id: r for r in ROUTES}
BANK = next(r for r in ROUTES if r.typical_bank)
MIN_CONVERSION_CNY = 500.0
REMITTERS = ("student", "parent")


@dataclass
class Issue:
    code: str
    message: str
    step: int | None = None
    hint: str = ""
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {"code": self.code, "message": self.message}
        if self.step is not None:
            d["step"] = self.step
        if self.hint:
            d["hint"] = self.hint
        if self.data:
            d["data"] = self.data
        return d


@dataclass
class Validation:
    ok: bool
    errors: list[dict]
    warnings: list[dict]
    metrics: dict
    schedule: list[dict]

    def to_dict(self) -> dict:
        return {"valid": self.ok, "errors": self.errors, "warnings": self.warnings, "metrics": self.metrics,
                "schedule": self.schedule}


def safe_quota_inr() -> float:
    return corridor.load_rules()["rules"]["safe_quota_usd"]["value"] * corridor.USD_INR


def lrs_limit_inr() -> float:
    return corridor.load_rules()["rules"]["lrs_annual_limit_usd"]["value"] * corridor.USD_INR


def required_obligations(passport) -> list:
    """Obligations a plan must fund: pending/planned and not recurring (recurring bills are paid by Tier-1 autonomy)."""
    return sorted((o for o in passport.obligations if o.status in ("pending", "planned") and not o.recurring),
                  key=lambda o: o.due)


def _tcs(already: float, amount: float, rules: dict, loan_funded: bool) -> float:
    if loan_funded:
        return 0.0
    t = rules["rules"]["tcs_threshold_inr"]
    over = max(0.0, already + amount - t["value"]) - max(0.0, already - t["value"])
    return round(over * t["rate_above"], 2)


def _parse_date(v) -> date | None:
    try:
        return date.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None


def validate_plan(world, steps) -> Validation:
    p = world.passport
    today = world.today
    mid = world.rates.mid(world.day_index)
    rules = corridor.load_rules()
    r_ = rules["rules"]
    quota, lrs = safe_quota_inr(), lrs_limit_inr()
    loan = p.funding_source == "education_loan"
    errors: list[Issue] = []
    warns: list[Issue] = []

    if not isinstance(steps, list) or not steps:
        errors.append(Issue("bad_step", "A plan needs a non-empty list of steps."))
        return Validation(False, [e.to_dict() for e in errors], [], {}, [])

    # ---- 1. parse and check each step on its own ----------------------------------------------------
    parsed: list[dict] = []
    paid_ids: dict[str, int] = {}
    for i, s in enumerate(steps):
        if not isinstance(s, dict) or s.get("action") not in ("convert", "pay"):
            errors.append(Issue("bad_step", "Each step must be an object with action 'convert' or 'pay'.", i))
            continue
        d = _parse_date(s.get("date"))
        if d is None:
            errors.append(Issue("bad_date", f"Step date {s.get('date')!r} is not a YYYY-MM-DD date.", i))
            continue
        if d < today:
            errors.append(Issue("date_in_past", f"Step is dated {d}, before today ({today}).", i,
                                f"Use {today} or later."))
            continue
        if s["action"] == "convert":
            try:
                send = float(s.get("send_inr"))
            except (TypeError, ValueError):
                send = 0.0
            route = ROUTE_BY_ID.get(s.get("route_id"))
            remitter = s.get("remitter") or "student"
            if route is None:
                errors.append(Issue("unknown_route", f"Unknown route {s.get('route_id')!r}.", i,
                                    "Use a route_id from get_routes: " + ", ".join(ROUTE_BY_ID)))
                continue
            if send <= 0 or send != send:
                errors.append(Issue("bad_amount", "send_inr must be a positive number.", i))
                continue
            if remitter not in REMITTERS:
                errors.append(Issue("bad_step", f"remitter must be one of {REMITTERS}.", i))
                continue
            parsed.append({"i": i, "action": "convert", "date": d, "send_inr": round(send, 2), "route": route,
                           "remitter": remitter})
        else:
            ob = p.obligation(str(s.get("obligation_id")))
            if ob is None:
                errors.append(Issue("unknown_obligation", f"No obligation {s.get('obligation_id')!r} in the Passport.", i,
                                    "Use ids from list_obligations."))
                continue
            if ob.status == "paid":
                errors.append(Issue("already_paid", f"{ob.id} is already paid.", i))
                continue
            if ob.status == "frozen":
                errors.append(Issue("obligation_frozen", f"{ob.id} is frozen after a security stop; the student must "
                                                         f"approve the recovery plan first.", i))
                continue
            if ob.id in paid_ids:
                errors.append(Issue("duplicate_payment", f"{ob.id} is paid twice (steps {paid_ids[ob.id]} and {i}).", i))
                continue
            paid_ids[ob.id] = i
            pid = s.get("payee_id")
            known = pid in p.recipients or world.registry.lookup(str(pid)) is not None
            if not known:
                errors.append(Issue("unknown_payee", f"Payee {pid!r} is not in the Passport or the verified registry.", i,
                                    f"{ob.id} is payable to {ob.payee_id}."))
                continue
            if pid != ob.payee_id:
                errors.append(Issue("payee_mismatch", f"{ob.id} is owed to {ob.payee_id}, not {pid}.", i,
                                    f"Set payee_id to {ob.payee_id}."))
                continue
            try:
                amt = float(s.get("amount_cny"))
            except (TypeError, ValueError):
                amt = -1.0
            if abs(amt - ob.amount) > CNY_TOL:
                errors.append(Issue("amount_mismatch", f"{ob.id} is CNY {ob.amount:,.2f}; the step pays CNY {amt:,.2f}.", i,
                                    f"Set amount_cny to {ob.amount}."))
                continue
            if d > date.fromisoformat(ob.due):
                errors.append(Issue("late_payment", f"{ob.id} is due {ob.due}; the step pays on {d}.", i,
                                    f"Pay on or before {ob.due}."))
                continue
            parsed.append({"i": i, "action": "pay", "date": d, "ob": ob, "amount": ob.amount})

    # ---- 2. every required obligation must be paid ---------------------------------------------------
    for ob in required_obligations(p):
        if ob.id not in paid_ids:
            errors.append(Issue("obligation_unfunded", f"{ob.id} ({ob.type}, CNY {ob.amount:,.0f}, due {ob.due}) has no pay step.",
                                None, f"Add a pay step for {ob.id} on or before {ob.due}."))
    for ob in p.obligations:
        if ob.status == "frozen" and ob.id not in paid_ids:
            warns.append(Issue("frozen_excluded", f"{ob.id} is frozen and is not part of this plan until recovery is approved."))

    # ---- 3. chronological cash simulation -------------------------------------------------------------
    inr = p.balance("INR")
    cny = p.balance("CNY")
    used_by = {r: p.remitted_inr_fy.get(r, 0.0) for r in REMITTERS}
    year_used = {y: v for y, v in p.safe_used_inr.items()}
    converts: list[dict] = []        # processed conversions with arrival date
    sched: list[dict] = []
    pay_ok: dict[int, bool] = {}
    total_send = total_deliv = total_bank = tcs_total = 0.0
    sim_inr_after = inr
    events = sorted(parsed, key=lambda e: (e["date"], 0 if e["action"] == "convert" else 1, e["i"]))
    pay_dates = sorted(e["date"] for e in events if e["action"] == "pay")
    for e in events:
        i = e["i"]
        if e["action"] == "convert":
            route: Route = e["route"]
            send, rem, d = e["send_inr"], e["remitter"], e["date"]
            deliv = round(delivered_amount(send, route, mid), 2)
            arrival = d + timedelta(days=route.days)
            if rem == "student":
                if send > sim_inr_after + 0.005:
                    errors.append(Issue("insufficient_inr", f"Step {i}: the student has INR {sim_inr_after:,.0f} on {d}; "
                                        f"the conversion sends INR {send:,.0f}.", i,
                                        f"Short by INR {send - sim_inr_after:,.0f}. Reduce it or fund the shortfall with a "
                                        f"parent-remitted conversion (remitter 'parent', needs the parent's consent).",
                                        {"short_inr": round(send - sim_inr_after, 2)}))
                sim_inr_after -= send
            y = str(d.year)
            before = year_used.get(y, 0.0)
            if before + send > quota + 0.005:
                room = max(0.0, quota - before)
                errors.append(Issue(
                    "safe_quota_exceeded",
                    f"Step {i}: conversions dated in {y} would total INR {before + send:,.0f}, above the SAFE facilitation "
                    f"quota of INR {quota:,.0f} (USD 50,000 equivalent).", i,
                    f"Convert at most INR {room:,.0f} in {y} (that includes INR {before:,.0f} already used) and "
                    f"schedule the rest on or after {int(y) + 1}-01-01, early enough to arrive before the payment date.",
                    {"year": y, "quota_inr": round(quota, 2), "used_before_inr": round(before, 2), "max_send_inr": round(room, 2)}))
            elif (before + send) / quota >= 0.8:
                warns.append(Issue("safe_quota_near", f"Conversions in {y} reach {100 * (before + send) / quota:.0f}% of the SAFE quota.", i))
            year_used[y] = before + send
            if used_by[rem] + send > lrs + 0.005:
                errors.append(Issue("lrs_exceeded", f"Step {i}: the {rem} remitter's LRS limit (INR {lrs:,.0f}) would be exceeded this "
                                    f"financial year.", i, "Use the other remitter or reduce the amount.",
                                    {"used_inr": round(used_by[rem], 2), "limit_inr": round(lrs, 2)}))
            tcs = _tcs(used_by[rem], send, rules, loan)
            if tcs > 0:
                tcs_total += tcs
                warns.append(Issue("tcs", f"Step {i}: TCS of INR {tcs:,.0f} would be collected from the {rem} remitter "
                                   f"(2% above INR 10 lakh; recoverable as a tax credit, not a fee).", i, "", {"tcs_inr": tcs, "remitter": rem}))
            elif not loan and used_by[rem] + send > 0.8 * r_["tcs_threshold_inr"]["value"]:
                warns.append(Issue("tcs_near", f"Step {i}: the {rem} remitter is approaching the INR 10 lakh TCS threshold.", i))
            used_by[rem] += send
            if rem == "parent":
                warns.append(Issue("parent_remitter", f"Step {i}: INR {send:,.0f} would be sent by the parent; it needs the "
                                   f"parent's consent and counts against the parent's LRS/TCS.", i))
            if deliv < MIN_CONVERSION_CNY:
                warns.append(Issue("small_conversion", f"Step {i}: CNY {deliv:,.0f} delivered is below the CNY {MIN_CONVERSION_CNY:,.0f} "
                                   f"minimum worth converting (fixed fees dominate).", i))
            total_send += send
            total_deliv += deliv
            total_bank += delivered_amount(send, BANK, mid)
            converts.append({**e, "arrival": arrival, "delivered": deliv})
            sched.append({"step": i, "date": d.isoformat(), "action": "convert", "send_inr": send, "route": route.name,
                          "route_id": route.id, "remitter": rem, "delivered_cny": deliv, "arrives": arrival.isoformat()})
        else:
            ob, d = e["ob"], e["date"]
            avail = cny_available(cny, converts, d, events, e)
            if avail + CNY_TOL < ob.amount:
                late = [c for c in converts if c["arrival"] > d]
                late_sum = sum(c["delivered"] for c in late)
                if late and avail + late_sum + CNY_TOL >= ob.amount:
                    errors.append(Issue("route_too_slow", f"Step {i}: CNY {ob.amount:,.0f} is paid on {d} but the conversion that "
                                        f"funds it arrives on {min(c['arrival'] for c in late)}, after the payment date.", i,
                                        "Convert earlier or use a faster route (check days in get_routes).",
                                        {"available_cny": round(avail, 2)}))
                else:
                    errors.append(Issue("insufficient_cny", f"Step {i}: only CNY {avail:,.0f} will be in the student's account on {d}; "
                                        f"{ob.id} needs CNY {ob.amount:,.0f}.", i,
                                        f"Short by CNY {ob.amount - avail:,.0f}: add or enlarge a conversion arriving on or before {d}.",
                                        {"short_cny": round(ob.amount - avail, 2)}))
                pay_ok[i] = False
            else:
                pay_ok[i] = True
            sched.append({"step": i, "date": d.isoformat(), "action": "pay", "obligation_id": ob.id, "payee_id": ob.payee_id,
                          "amount_cny": ob.amount, "due": ob.due})
            if ob.amount > p.rules.tier1_auto_limit_cny:
                warns.append(Issue("approval_expected", f"Step {i}: paying CNY {ob.amount:,.0f} is above the Tier-1 limit; it will "
                                   f"wait for the student's approval and passes verification, signed intent, policy and executor "
                                   f"like any payment.", i))

    # ---- 4. rate-target reserve ---------------------------------------------------------------------------
    reserve = sum(t["convert_cny"] / t["rate"] for t in p.rules.rate_targets
                  if t.get("status") in ("watching", "awaiting_approval") and t.get("rate"))
    if reserve and sim_inr_after + 0.005 < reserve:
        errors.append(Issue("rate_target_reserve", f"The student's pending rate target(s) need about INR {reserve:,.0f} to stay "
                            f"unconverted; the plan leaves INR {sim_inr_after:,.0f}.", None,
                            f"Keep at least INR {reserve:,.0f} unconverted (or fund the difference from the parent).",
                            {"reserve_inr": round(reserve, 2), "left_inr": round(sim_inr_after, 2)}))

    # ---- 5. route quality (warnings) -----------------------------------------------------------------------
    for c in converts:
        later = [d for d in pay_dates if d >= c["date"]]
        deadline = later[0] if later else None
        cand = [r for r in ROUTES if deadline is None or c["date"] + timedelta(days=r.days) <= deadline]
        if cand:
            best = max(cand, key=lambda r: delivered_amount(c["send_inr"], r, mid))
            diff = delivered_amount(c["send_inr"], best, mid) - c["delivered"]
            if diff > 0.001 * c["delivered"] and diff > 5:
                warns.append(Issue("route_not_cheapest", f"Step {c['i']}: {best.name} would deliver CNY {diff:,.0f} more and still arrive on time.",
                                   c["i"], "", {"better_route_id": best.id, "extra_cny": round(diff, 2)}))
    for inc in p.expected_income:
        if not inc.get("received") and _parse_date(inc.get("expected")) and _parse_date(inc["expected"]) < today:
            warns.append(Issue("late_income_ignored", f"{inc['label']} (CNY {inc['amount_cny']:,.0f}) was expected on {inc['expected']} "
                               f"and has not arrived; the plan does not count on it."))

    # ---- 6. metrics --------------------------------------------------------------------------------------------
    final_cny = cny + total_deliv - sum(e["ob"].amount for e in events if e["action"] == "pay")
    burn = max(float(p.student.monthly_budget_cny), 1.0)
    runway = (max(final_cny, 0) + max(sim_inr_after, 0) * mid) / burn
    if runway < p.rules.runway_alert_months and not errors:
        warns.append(Issue("low_runway", f"After the plan the student has about {runway:.1f} months of budget left "
                           f"(alert below {p.rules.runway_alert_months:g})."))
    req = required_obligations(p)
    met = sum(1 for o in req if o.id in paid_ids and pay_ok.get(paid_ids[o.id], False))
    cost_mid = total_send * mid
    metrics = {
        "conversions": len(converts), "total_send_inr": round(total_send, 2), "delivered_cny": round(total_deliv, 2),
        "bank_delivered_cny": round(total_bank, 2), "saved_vs_bank_cny": round(total_deliv - total_bank, 2),
        "fees_cny": round(cost_mid - total_deliv, 2), "bank_fees_cny": round(cost_mid - total_bank, 2),
        "tcs_inr": round(tcs_total, 2), "obligations": len(req), "deadlines_met": met,
        "final_inr": round(sim_inr_after, 2), "final_cny": round(final_cny, 2), "runway_months_after": round(runway, 2),
        "rate_basis": f"today's mock mid-market rate {mid:.6f} (a quote, not a forecast)",
    }
    sched.sort(key=lambda s: (s["date"], 0 if s["action"] == "convert" else 1, s["step"]))
    return Validation(not errors, [e.to_dict() for e in errors], [w.to_dict() for w in warns], metrics, sched)


def cny_available(start_cny: float, converts: list[dict], on: date, events: list[dict], this: dict) -> float:
    """CNY in the student's account on `on`: opening balance + conversions arrived by then - payments made earlier."""
    arrived = sum(c["delivered"] for c in converts if c["arrival"] <= on)
    spent = sum(e["amount"] for e in events if e["action"] == "pay" and e is not this and
                (e["date"], e["i"]) < (this["date"], this["i"]))
    return start_cny + arrived - spent
