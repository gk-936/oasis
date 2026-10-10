"""Deterministic policy engine: allow / hold / freeze. Same inputs -> same decision, every rule logged.

The LLM risk score is one input that can only ESCALATE a decision; it never grants one.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from ..config import RULESET_VERSION
from ..passport.models import LEVEL_ORDER, Level, Passport, Recipient
from .corridor import CorridorResult

RISK_HOLD = 0.5
RISK_FREEZE = 0.85
TEST_PAYMENT_MAX_CNY = 10.0


@dataclass
class PolicyInput:
    passport: Passport
    recipient: Recipient | None
    payee_id: str
    purpose: str
    amount_cny: float
    amount_inr: float
    corridor: CorridorResult
    canary_hits: list = field(default_factory=list)
    risk_score: float = 0.0
    approvals: tuple[str, ...] = ()          # roles that approved, e.g. ("student", "parent")
    recurring: bool = False
    remitter: str = "student"
    paid_to_payee_cny: float = 0.0           # already paid to this payee in the current limit window
    currency: str = "CNY"                    # the currency the DOCUMENT demands (the rail only ever settles CNY)
    instalment: bool = False                 # a part payment below the obligation's remaining amount
    remaining_cny: float | None = None       # what is still owed on the matched obligation (instalments only)


@dataclass
class Decision:
    action: str                # allow | hold | freeze
    tier: int                  # 1 automatic, 2 approval required, 3 never
    rule: str
    reasons: list[str]
    required_approvals: list[str] = field(default_factory=list)
    ruleset: str = RULESET_VERSION

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def decide(p: PolicyInput) -> Decision:
    rules = p.passport.rules
    rec = p.recipient
    level = rec.verification.level if rec else Level.UNVERIFIED

    # R01 canary tripwire -> freeze
    if p.canary_hits:
        return Decision("freeze", 3, "R01_canary", [f"Canary tripped: {h.kind} at {h.where}" for h in p.canary_hits])
    # R02 hard limit or rejected recipient -> never (tier 3)
    if p.amount_cny > rules.hard_limit_cny:
        return Decision("freeze", 3, "R02_hard_limit", [f"Amount exceeds the hard limit of CNY {rules.hard_limit_cny:,.0f}."])
    if level == Level.REJECTED:
        return Decision("freeze", 3, "R03_rejected_recipient", ["The registry contradicts this recipient's details."])
    # R04 extreme risk score -> freeze (escalation only)
    if p.risk_score >= RISK_FREEZE:
        return Decision("freeze", 3, "R04_risk_freeze", [f"Risk score {p.risk_score:.2f} is above the freeze threshold."])

    # R04b verification test payment: tiny, only to a registry-confirmed recipient.
    if p.purpose == "verification_test":
        if level == Level.REGISTRY_CHECKED and p.amount_cny <= TEST_PAYMENT_MAX_CNY:
            return Decision("allow", 1, "R04b_test_payment", ["Registry-confirmed recipient; small verification test payment."])
        return Decision("freeze", 3, "R04c_bad_test_payment", ["A test payment is only allowed to a registry-confirmed recipient, up to CNY 10."])

    # R15 the document demands a currency other than CNY: Oasis settles CNY obligations in CNY only and never
    # converts a demand silently (a USD figure read as CNY, or CNY paid against a USD demand, is a different amount).
    if (p.currency or "CNY").upper() != "CNY":
        return Decision("hold", 2, "R15_currency_mismatch",
                        [f"The document demands {p.currency.upper()}, but this obligation is settled in CNY. Oasis will not pay "
                         "a foreign-currency demand as if it were CNY."], ["corrected_cny_invoice"])

    # R05 unverified recipient -> hold for verification
    if LEVEL_ORDER[level] < LEVEL_ORDER[Level.VERIFIED_LOW]:
        return Decision("hold", 2, "R05_unverified", ["Recipient is not verified; the verification ramp must complete first."],
                        ["verification"])
    # R06 corridor holds
    if p.corridor.holds:
        # Splitting a family transfer to dodge parent co-approval needs the parent, not just the student.
        dodges_parent = any(f.rule == "split_payments" and f.data.get("threshold") == rules.parent_coapproval_above_inr
                            for f in p.corridor.holds)
        who = ["parent"] if dodges_parent else ["student"]
        return Decision("hold", 2, "R06_corridor", [f.message for f in p.corridor.holds], who)
    # R07 recipient limit: above the ramp limit needs explicit student approval (tier 2, one-time)
    limit = rec.verification.limit_cny if rec else 0.0
    over_limit = p.paid_to_payee_cny + p.amount_cny > limit
    if over_limit and "student" not in p.approvals:
        return Decision("hold", 2, "R07_recipient_limit",
                        [f"Amount would exceed this recipient's verified limit of CNY {limit:,.0f}."], ["student"])
    # R08 risk hold
    if p.risk_score >= RISK_HOLD:
        # No approval releases a risk hold (a signed approval re-runs the same score and holds again), so no approver is
        # offered: the student confirms through a registry-verified channel and re-submits the genuine request.
        return Decision("hold", 2, "R08_risk_hold",
                        [f"Risk score {p.risk_score:.2f} requires review outside this document: confirm with the payee through "
                         "the registry-verified contact, then re-submit the genuine invoice. An approval cannot release this hold."],
                        ["risk_review"])

    need = ["student"]
    # R09 parent co-approval for large family transfers
    if p.purpose == "family_support" and p.amount_inr > rules.parent_coapproval_above_inr:
        need = ["student", "parent"]
    # R10 tier-1 automatic: small, recurring, fully verified recipient
    tier1 = (not p.instalment and not over_limit and level == Level.VERIFIED_FULL and p.recurring and p.amount_cny <= rules.tier1_auto_limit_cny
             and p.purpose != "family_support")
    if tier1:
        return Decision("allow", 1, "R10_tier1_auto", ["Small recurring payment to a fully verified recipient."])

    missing = [r for r in need if r not in p.approvals]
    if missing:
        why = [f"Approval required from: {', '.join(missing)}."]
        if p.instalment:
            why.insert(0, f"Part payment of CNY {p.amount_cny:,.2f}"
                          + (f" against CNY {p.remaining_cny:,.2f} still owed" if p.remaining_cny is not None else "")
                          + ": an instalment is never automatic.")
        return Decision("hold", 2, "R11_approval_required", why, missing)
    return Decision("allow", 2, "R12_approved", ["All required approvals present; recipient verified; within limits."])


def decide_conversion(passport: Passport, convert_cny: float, canary_hits: list | None = None,
                      approvals: tuple[str, ...] = ()) -> Decision:
    """Tier-1 autonomy for student-set rate targets: a small conversion into the student's own CNY balance.

    Deterministic like every other decision. It never pays a third party, and anything above the student's
    auto-convert limit needs the student.
    """
    rules = passport.rules
    if canary_hits:
        return Decision("freeze", 3, "R01_canary", [f"Canary tripped: {h.kind} at {h.where}" for h in canary_hits])
    if convert_cny > rules.hard_limit_cny:
        return Decision("freeze", 3, "R02_hard_limit", [f"Conversion exceeds the hard limit of CNY {rules.hard_limit_cny:,.0f}."])
    if convert_cny <= rules.tier1_auto_convert_cny:
        return Decision("allow", 1, "R13_tier1_rate_target",
                        [f"Student-set rate target reached; conversion of CNY {convert_cny:,.0f} is within the "
                         f"CNY {rules.tier1_auto_convert_cny:,.0f} auto limit."])
    if "student" in approvals:
        return Decision("allow", 2, "R14_conversion_approved", ["Conversion above the auto limit approved by the student."])
    return Decision("hold", 2, "R14_conversion_approval",
                    [f"Conversion of CNY {convert_cny:,.0f} is above the CNY {rules.tier1_auto_convert_cny:,.0f} auto limit."],
                    ["student"])
