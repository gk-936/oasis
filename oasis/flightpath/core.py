"""FlightPath: predict -> simulate -> verify -> monitor -> reconcile -> recover. All rail behaviour here is MOCK.

Nothing in this module moves money. Recovery only *advises*; any new payment still goes through the normal
policy engine, recipient verification and student approval (oasis/trust)."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date

from ..mock.rates import ROUTES, MockRates, Route, delivered_amount
from ..planning.routes import inr_needed

# MOCK intermediary deductions (CNY) a route may take on the way, as (expected, worst case). Shown as a range, never a guarantee.
# The expected value is half the worst case: the simulator draws the real deduction uniformly in [0, worst].
DEDUCTIONS = {"route_bank_swift": (90.0, 180.0), "route_inr_cny_1": (20.0, 40.0),
              "route_inr_cny_2": (30.0, 60.0), "route_inr_cny_3": (5.0, 10.0)}
GRACE_DAYS = 1
SHORT_TOLERANCE_CNY = 1.0

STAGES = ("prepared", "checks_complete", "submitted", "processing", "credited", "delayed", "rejected")
TRANSITIONS = {
    "prepared": {"checks_complete", "rejected"},
    "checks_complete": {"submitted"},
    "submitted": {"processing", "rejected"},
    "processing": {"credited", "delayed", "rejected"},
    "delayed": {"credited", "rejected"},
    "credited": set(), "rejected": set(),
}


# ---------------------------------------------------------------- 1. predict
@dataclass
class Warning_:
    code: str
    severity: str          # "block" | "warn"
    message: str
    fix: str


def precheck(*, payee_verified: bool, details_match: bool, docs_complete: bool, route: Route,
             today: date, due: date | None) -> list[Warning_]:
    """Preventable failure signs from information we already hold. It cannot promise success."""
    w = []
    if not payee_verified:
        w.append(Warning_("payee_unverified", "block", "Recipient is not in the verified registry.", "Verify the recipient first."))
    if not details_match:
        w.append(Warning_("details_mismatch", "block", "Beneficiary name/account does not match the invoice.", "Correct the recipient details."))
    if not docs_complete:
        w.append(Warning_("docs_missing", "warn", "Supporting documents are incomplete; the receiving bank may hold the transfer.", "Upload the missing document before sending."))
    if due is not None:
        slack = (due - today).days - route.days
        if slack < 0:
            w.append(Warning_("misses_deadline", "block", f"{route.name} takes {route.days}d but only {(due - today).days}d remain.", "Choose a faster route or ask for an extension."))
        elif slack < GRACE_DAYS + 1:
            w.append(Warning_("tight_deadline", "warn", f"Only {slack}d of slack on {route.name}.", "Send now or pick a faster route."))
    return w


# ---------------------------------------------------------------- 2. plan on the recipient amount
@dataclass
class RouteOption:
    route: Route
    send_inr: float
    recipient_expected_cny: float
    recipient_worst_cny: float
    fee_inr: float
    arrives_in_days: int
    reliability: float
    meets_target: bool          # even in the worst case
    on_time: bool


def compare_routes(rates: MockRates, required_cny: float, today: date, due: date | None = None, day_index: int = 0) -> list[RouteOption]:
    """For each route: the INR to send so the recipient gets `required_cny` even after the worst expected deduction."""
    mid = rates.mid(day_index)
    out = []
    for r in ROUTES:
        exp, worst = DEDUCTIONS.get(r.id, (0.0, 0.0))
        send = inr_needed(rates, r, required_cny + worst, day_index)
        got = delivered_amount(send, r, mid)
        out.append(RouteOption(r, send, round(got - exp, 2), round(got - worst, 2), round(send - required_cny / mid, 2),
                               r.days, r.reliability, got - worst >= required_cny - 0.01,
                               due is None or (due - today).days >= r.days))
    # on time first, then cheapest to the sender for a guaranteed-sufficient amount, then reliability
    return sorted(out, key=lambda o: (not o.on_time, o.send_inr, -o.reliability))


# ---------------------------------------------------------------- 3. simulate / monitor
@dataclass
class Journey:
    id: str
    route_id: str
    send_inr: float
    required_cny: float
    due_day: int | None = None
    stage: str = "prepared"
    submitted_day: int | None = None
    credited_cny: float | None = None
    refund_confirmed: bool = False
    history: list[dict] = field(default_factory=list)


class TransitionError(ValueError):
    pass


def advance(j: Journey, stage: str, day: int, **info) -> Journey:
    if stage not in TRANSITIONS.get(j.stage, set()):
        raise TransitionError(f"{j.stage} -> {stage} is not a valid step")
    j.history.append({"day": day, "from": j.stage, "to": stage, **info})
    j.stage = stage
    if stage == "submitted":
        j.submitted_day = day
    if stage == "credited":
        j.credited_cny = info.get("credited_cny")
    return j


# ---------------------------------------------------------------- 4. reconcile
@dataclass
class Finding:
    code: str            # delayed | shortfall | rejected | unconfirmed | ok
    detail: str
    shortfall_cny: float = 0.0


def _route(j: Journey) -> Route:
    return next(r for r in ROUTES if r.id == j.route_id)


def reconcile(j: Journey, today_day: int) -> Finding:
    """Compare what was expected with the evidence we actually have."""
    if j.stage == "rejected":
        return Finding("rejected", "The transfer was rejected.")
    if j.stage == "credited":
        short = round(j.required_cny - (j.credited_cny or 0.0), 2)
        if short > SHORT_TOLERANCE_CNY:
            return Finding("shortfall", f"Recipient got {j.credited_cny:.2f} CNY, {short:.2f} CNY less than required.", short)
        return Finding("ok", "Recipient confirmation matches the required amount.")
    if j.submitted_day is None:
        return Finding("ok", "Not submitted yet.")
    elapsed = today_day - j.submitted_day
    if elapsed > _route(j).days + GRACE_DAYS:
        return Finding("delayed", f"{elapsed}d since submission; this route normally takes {_route(j).days}d.")
    if j.stage == "delayed":
        return Finding("delayed", "Provider reported a delay.")
    return Finding("ok", "Within the expected window.")


# ---------------------------------------------------------------- 5. recover safely
@dataclass
class Advice:
    action: str            # wait | request_docs | support_case | investigate_shortfall | plan_alternative | none
    reason: str
    resend_allowed: bool = False
    needs_approval: bool = True


def can_resend(j: Journey) -> bool:
    """A second payment is only conceivable once the first is definitely dead AND the money is back."""
    return j.stage == "rejected" and j.refund_confirmed


def advise(j: Journey, f: Finding) -> Advice:
    """Next safe step. Never auto-pays; a new payment always re-enters verification, policy and approval."""
    if f.code == "ok":
        return Advice("none", f.detail, needs_approval=False)
    if f.code == "delayed":
        return Advice("support_case", "Original transfer is unresolved. Do not send again; ask the provider for its status.")
    if f.code == "shortfall":
        return Advice("investigate_shortfall", f"Ask the provider for the deduction breakdown; a top-up of {f.shortfall_cny:.2f} CNY "
                      "is a new payment and needs approval.")
    if f.code == "rejected":
        if can_resend(j):
            return Advice("plan_alternative", "Rejected and refunded: plan a new payment on another route.", resend_allowed=True)
        return Advice("request_docs", "Rejected, but the refund is not confirmed. Fix the cause and wait for the refund before any new payment.")
    return Advice("wait", f.detail)


def audit_event(audit, j: Journey, f: Finding, a: Advice) -> None:
    """Record the verdict in the tamper-evident chain (no-op when no audit log is supplied)."""
    if audit is not None:
        audit.append("flightpath", {"journey": j.id, "stage": j.stage, "finding": f.code, "action": a.action,
                                    "resend_allowed": a.resend_allowed})


# ---------------------------------------------------------------- 6. sandbox events and persistence
def journey_to_dict(j: Journey) -> dict:
    return {**j.__dict__, "history": list(j.history)}


def journey_from_dict(d: dict) -> Journey:
    return Journey(**d)


SIM_EVENTS = ("credit", "delay", "reject", "short_credit")


def simulate_event(j: Journey, event: str, day: int, short_cny: float = 25.0) -> Journey:
    """MOCK rail event layered on a journey (the sandbox ledger itself is instant). Walks the legal states, never skips one."""
    if event not in SIM_EVENTS:
        raise TransitionError(f"unknown event {event!r}")
    if j.stage == "prepared":
        advance(j, "checks_complete", day)
    if j.stage == "checks_complete":
        advance(j, "submitted", day)
    if j.stage == "submitted":
        advance(j, "processing", day)
    if event == "delay":
        advance(j, "delayed", day, note="simulated provider delay")
    elif event == "reject":
        advance(j, "rejected", day, note="simulated rejection")
    else:
        got = j.required_cny if event == "credit" else round(j.required_cny - short_cny, 2)
        advance(j, "credited", day, credited_cny=got, note=f"simulated {event}")
    return j
