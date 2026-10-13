"""Credit growth guidance: a plan, evidence-backed opportunities and a what-if simulator over the Trust Pass record.

Read-only: nothing here signs, issues, pays or writes to the audit log. It only reads the claims the Trust Pass already
computes from verified payments (`trust_pass.compute_claims`) and shows how they would change.

Honesty limits (see CAVEATS):
- Only payments Oasis executed to a registry-verified payee count. External payments (cash, cards, outside transfers) are
  listed as not verified, never counted.
- It never advises paying anything early or extra to lift a metric; only real, existing obligations are mentioned.
- It is not a credit score and does not predict any landlord's, bank's or lender's decision.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import trust_pass as tp

MAX_MONTHS = 24
MAX_LATE = 6
CAVEATS = (
    "SANDBOX guidance: the payments, payees and dates are simulated.",
    "It is not a credit score and does not predict whether any landlord, bank or lender will agree.",
    "Only payments Oasis executed to a registry-verified payee are counted. External payments are not verified.",
    "Never make an extra or early payment just to raise a number; only real obligations belong in the record.",
)
EXTERNAL_UNVERIFIED = ("cash_or_card_payments", "transfers_outside_oasis", "payments_to_unverified_payees",
                       "loan_or_card_repayments_elsewhere")

# (id, claim-derived progress key, target). Progress keys come from `_progress`.
MILESTONES = (
    ("first_payment", "payments", 1),
    ("three_payments", "payments", 3),
    ("six_payments", "payments", 6),
    ("streak_4", "streak", 4),
    ("history_3m", "months", 3),
    ("history_6m", "months", 6),
    ("rent_and_tuition", "types", 2),
    ("on_time_100", "clean", 1),
)

# What each opportunity needs, in terms of the Trust Pass claims. `pay_type` limits the evidence to one obligation type.
OPPORTUNITIES = {
    "lower_deposit": {"claims": ["rent_on_time"], "pay_type": "rent", "min": 1, "audience": "Landlord"},
    "no_guarantor": {"claims": ["tuition_on_time"], "pay_type": "tuition", "min": 1, "audience": "Landlord or university"},
    "student_card": {"claims": ["on_time_all", "no_late"], "pay_type": None, "min": 3, "audience": "Bank"},
    "home_bank": {"claims": ["history_months", "no_late"], "pay_type": None, "min": 6, "audience": "Bank"},
}


def _progress(c: dict) -> dict:
    a = c["on_time_all"]
    types = sum(1 for k in ("rent_on_time", "tuition_on_time") if c[k]["of"] >= 1)
    return {"payments": a["of"], "streak": c["on_time_streak"]["count"], "months": c["history_months"]["months"],
            "types": types, "clean": 1 if c["no_late"]["value"] else 0}


def plan(world) -> dict:
    """Milestones toward a stronger record, what is verified vs not, and the real obligations that will extend it."""
    c = tp.compute_claims(tp._entries(world), world.today.isoformat())
    prog = _progress(c)
    ms = [{"id": mid, "current": min(prog[key], target), "target": target, "met": prog[key] >= target}
          for mid, key, target in MILESTONES]
    upcoming = [{"id": o.id, "type": o.type, "due": o.due, "amount": o.amount, "currency": o.currency}
                for o in world.passport.obligations if o.status in ("pending", "planned", "partially_paid")]
    upcoming.sort(key=lambda o: o["due"])
    return {"verified": {"payments": prog["payments"], "on_time": c["on_time_all"]["on_time"],
                         "months": prog["months"], "streak": prog["streak"]},
            "milestones": ms, "next": next((m["id"] for m in ms if not m["met"]), None),
            "upcoming_obligations": upcoming[:5], "not_verified": list(EXTERNAL_UNVERIFIED), "caveats": list(CAVEATS)}


def opportunities(world) -> dict:
    """For each ask: what the student wants, the evidence they hold, what is missing and a payload for /trust-pass/issue."""
    c = tp.compute_claims(tp._entries(world), world.today.isoformat())
    th = tp.threshold_options(c)
    out = []
    for oid, spec in OPPORTUNITIES.items():
        missing = []
        a, pay = c["on_time_all"], spec["pay_type"]
        r = c[f"{pay}_on_time"] if pay else a
        if pay and r["of"] < spec["min"]:
            missing.append({"code": "need_payment_type", "type": pay, "have": r["of"], "need": spec["min"]})
        if pay and r["of"] and r["on_time"] < r["of"]:
            missing.append({"code": "late_payment_present", "type": pay})
        if not pay and oid == "student_card":
            if a["of"] < spec["min"]:
                missing.append({"code": "need_payments", "have": a["of"], "need": spec["min"]})
            if a["of"] and not c["no_late"]["value"]:
                missing.append({"code": "late_payment_present", "type": "any"})
        if oid == "home_bank":
            if c["history_months"]["months"] < spec["min"]:
                missing.append({"code": "need_months", "have": c["history_months"]["months"], "need": spec["min"]})
            if a["of"] and not c["no_late"]["value"]:
                missing.append({"code": "late_payment_present", "type": "any"})
        picks = {k: next((o["at_least"] for o in reversed(v) if o["met"]), None) for k, v in th.items()}
        thresholds = {k: v for k, v in picks.items() if v is not None} if oid in ("student_card", "home_bank") else {}
        claims = list(spec["claims"]) + [k for k in thresholds if k not in spec["claims"]]
        ready = not missing
        out.append({"id": oid, "ready": ready, "missing": missing, "evidence_claims": spec["claims"],
                    "package": {"claims": claims, "thresholds": thresholds, "audience": spec["audience"]} if ready else None,
                    "next": "issue_package" if ready else "build_record", "note": "better_supported_not_guaranteed"})
    return {"opportunities": out, "caveats": list(CAVEATS)}


def _hypothetical(base: date, i: int, *, late: bool) -> dict:
    due = base + timedelta(days=30 * i)
    paid = due + timedelta(days=5) if late else due
    return {"obligation_type": "rent", "payee_type": "landlord", "paid_date": paid.isoformat(), "due_date": due.isoformat(),
            "on_time": not late, "amount_cny": 0.0, "payee_level": "verified", "hypothetical": True}


def _snapshot(c: dict) -> dict:
    lv = max(i for i, (need, _) in enumerate(tp.LADDER) if c["on_time_streak"]["count"] >= need)
    return {"claims": {k: v for k, v in c.items()}, "asks": tp.suggested_asks(c), "ladder_level": lv,
            "thresholds_met": {k: [o["at_least"] for o in v if o["met"]] for k, v in tp.threshold_options(c).items()}}


def simulate(world, on_time_months: int = 0, late_payments: int = 0, starter_product: bool = False,
             budget_safe: bool = True) -> dict:
    """What-if over Oasis's OWN metrics. Hypothetical rent payments are appended after today, on-time ones first, then late ones.
    Starter-product repayments happen outside Oasis, so they change nothing here; they only add warnings."""
    if not (0 <= on_time_months <= MAX_MONTHS and 0 <= late_payments <= MAX_LATE):
        raise ValueError(f"on_time_months must be 0-{MAX_MONTHS} and late_payments 0-{MAX_LATE}")
    today = world.today
    base = tp._entries(world)
    extra = [_hypothetical(today, i + 1, late=False) for i in range(on_time_months)]
    extra += [_hypothetical(today, on_time_months + i + 1, late=True) for i in range(late_payments)]
    after_c = tp.compute_claims(base + extra, (today + timedelta(days=30 * (len(extra)))).isoformat())
    before = _snapshot(tp.compute_claims(base, today.isoformat()))
    after = _snapshot(after_c)
    notes = []
    if starter_product:
        notes.append("external_repayments_not_verified")
    if starter_product and not budget_safe:
        notes.append("unsafe_budget_missed_payment_risk")
        if before["claims"]["on_time_streak"]["count"] or on_time_months:
            notes.append("a_missed_payment_resets_streak_and_no_late")
    if late_payments:
        notes.append("late_payment_breaks_streak_and_no_late")
    return {"hypothetical": True, "scenario": {"on_time_months": on_time_months, "late_payments": late_payments,
                                              "starter_product": starter_product, "budget_safe": budget_safe},
            "before": before, "after": after,
            "gained_asks": [a for a in after["asks"] if a not in before["asks"]],
            "lost_asks": [a for a in before["asks"] if a not in after["asks"]],
            "notes": notes, "caveats": list(CAVEATS)}
