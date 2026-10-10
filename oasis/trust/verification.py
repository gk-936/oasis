"""Step 3 - verification ramp. "Investigate, don't block": a changed account is re-verified, not refused.

Unverified -> RegistryChecked -> TestPaid -> Verified_Low -> Verified_Full.
Details supplied by the requester (including those on an invoice) are treated as forgeable;
only the independent registry can confirm an account.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from ..mock.registry import VerifiedPayeeRegistry
from ..passport.models import Level, Passport, Recipient, Verification

LOW_LIMIT_CNY = 5000.0
FULL_LIMIT_CNY = 50000.0
PROMOTE_AFTER = 2
# Simulated minutes each stage costs (used for the "time to resolve" metric).
STAGE_MINUTES = {"registry_check": 5, "test_payment": 30, "limit_set": 1}


@dataclass
class VerifyOutcome:
    level: Level
    reasons: list[str] = field(default_factory=list)
    needs_test_payment: bool = False
    sim_minutes: int = 0
    account_changed: bool = False
    payee_id: str | None = None


class Verifier:
    def __init__(self, registry: VerifiedPayeeRegistry):
        self.registry = registry

    def assess(self, passport: Passport, *, payee_id: str | None, name: str, account_ref: str,
               payee_type: str = "") -> VerifyOutcome:
        """Resolve a claimed recipient. Mutates the Passport recipient record on state changes."""
        known = passport.recipients.get(payee_id) if payee_id else None
        out = VerifyOutcome(Level.UNVERIFIED, payee_id=payee_id)

        cred = self.registry.lookup(payee_id) if payee_id else None
        if cred is None:
            cred = self.registry.lookup_by_name(name)
        out.sim_minutes += STAGE_MINUTES["registry_check"]

        if cred is None:
            out.level = Level.UNVERIFIED
            out.reasons.append("No registry credential for this identity (name/ID unknown to the registry).")
            return out

        out.payee_id = cred.payee_id
        if payee_id and cred.payee_id != payee_id:
            out.level = Level.REJECTED
            out.reasons.append("Registry identity does not match the claimed payee ID.")
            return out

        if cred.account_ref != account_ref:
            out.level = Level.REJECTED
            out.reasons.append("Registry contradicts the account on the request - details on the request are "
                               "treated as forgeable.")
            # The request is rejected; the genuine recipient's record is left untouched (no denial of service).
            return out

        # Registry confirms the account. A changed account resets the recipient: re-verified, not blocked.
        known = known or passport.recipients.get(cred.payee_id)
        if known and known.account_ref != account_ref:
            out.account_changed = True
            out.reasons.append("Account details changed - recipient reset to unverified and re-verified.")
            known.verification = Verification()
        rec = known or Recipient(
            id=cred.payee_id, name=cred.name, payee_type=cred.payee_type, account_ref=cred.account_ref)
        rec.account_ref = cred.account_ref
        if rec.verification.level in (Level.UNVERIFIED, Level.REJECTED):
            rec.verification = Verification(method="registry_credential", level=Level.REGISTRY_CHECKED,
                                            notes=["registry credential signature valid, account matches"])
        passport.recipients[rec.id] = rec
        out.level = rec.verification.level
        out.needs_test_payment = rec.verification.level == Level.REGISTRY_CHECKED
        if out.needs_test_payment:
            out.sim_minutes += STAGE_MINUTES["test_payment"]
            out.reasons.append("Registry confirms the account; a small test payment is required before limits open.")
        return out

    def confirm_test_payment(self, passport: Passport, payee_id: str, today: str = "2026-10-10") -> VerifyOutcome:
        rec = passport.recipients[payee_id]
        out = VerifyOutcome(rec.verification.level, sim_minutes=STAGE_MINUTES["limit_set"], payee_id=payee_id)
        if rec.verification.level != Level.REGISTRY_CHECKED:
            out.reasons.append("Test payment ignored: recipient is not at registry_checked.")
            return out
        rec.verification.level = Level.VERIFIED_LOW
        rec.verification.limit_cny = LOW_LIMIT_CNY
        rec.verification.verified_at = today
        rec.verification.notes.append("test payment confirmed; low limit set")
        out.level = Level.VERIFIED_LOW
        out.reasons.append(f"Test payment confirmed - low limit CNY {LOW_LIMIT_CNY:,.0f} set.")
        return out

    @staticmethod
    def record_success(passport: Passport, payee_id: str) -> None:
        """Limits rise only after successful, uneventful payments."""
        rec = passport.recipients.get(payee_id)
        if not rec:
            return
        v = rec.verification
        v.successful_payments += 1
        if v.level == Level.VERIFIED_LOW and v.successful_payments >= PROMOTE_AFTER:
            v.level = Level.VERIFIED_FULL
            v.limit_cny = FULL_LIMIT_CNY
            v.notes.append("promoted after successful payments")

    @staticmethod
    def seed_verified(passport: Passport, recipient: Recipient, level: Level = Level.VERIFIED_FULL,
                      limit: float = FULL_LIMIT_CNY) -> None:
        recipient.verification = Verification(method="registry_credential", level=level, limit_cny=limit,
                                              verified_at="2026-10-01", successful_payments=PROMOTE_AFTER)
        passport.recipients[recipient.id] = recipient
