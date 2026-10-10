"""Step 4 - signed protected intents. The executor refuses anything outside the intent."""
from __future__ import annotations
import random
import secrets
from datetime import datetime
from dataclasses import dataclass, field

from .approvals import draft_hash
from .crypto import HybridSigner, canonical, sha256_hex

MATCH_FIELDS = ("payee_id", "account_ref", "amount", "currency", "route_id")


class IntentBuilder:
    """Holds the signing key. The LLM never touches it."""

    def __init__(self, signer: HybridSigner | None = None, seed: int | None = None):
        self.signer = signer or HybridSigner()
        self._n = 0
        self._rng = random.Random(seed) if seed is not None else None   # seeded nonces for the scripted demo only

    def new_nonce(self) -> str:
        return self._nonce()

    def _nonce(self) -> str:
        return f"{self._rng.getrandbits(96):024x}" if self._rng else secrets.token_hex(12)

    def build(self, *, student_id: str, payee_id: str, account_ref: str, amount: float, currency: str,
              purpose: str, route_id: str, not_after: str, tier: int, approvals: list[dict],
              obligation_id: str | None = None, nonce: str | None = None) -> dict:
        """`approvals` are SIGNED approval records (see trust/approvals.py), each bound to this intent's draft hash.
        `nonce` lets a payment keep the nonce its approvers signed over."""
        self._n += 1
        body = {"intent_id": f"int_{self._n:04d}", "student_id": student_id, "payee_id": payee_id,
                "account_ref": account_ref, "amount": amount, "currency": currency, "purpose": purpose,
                "route_id": route_id, "not_after": not_after, "tier": tier, "approvals": approvals,
                "obligation_id": obligation_id, "nonce": nonce or self._nonce()}
        return {**body, "signatures": self.signer.sign(canonical(body)), "key_id": self.signer.key_id}

    def intent_hash(self, intent: dict) -> str:
        return sha256_hex(canonical(strip_sigs(intent)))


def strip_sigs(intent: dict) -> dict:
    return {k: v for k, v in intent.items() if k not in ("signatures", "key_id")}


@dataclass
class IntentCheck:
    ok: bool
    reasons: list[str] = field(default_factory=list)


def verified_approval_roles(approvers, intent: dict) -> tuple[set[str], list[str]]:
    """Roles whose approval in `intent` carries a valid signature over THIS intent's draft hash, from the role's
    registered device key. Returns (verified roles, reasons for every approval that did not verify)."""
    dh = draft_hash(intent)
    ok: set[str] = set()
    bad: list[str] = []
    for a in intent.get("approvals") or []:
        role = a.get("role") if isinstance(a, dict) else None
        if approvers is not None and role and approvers.verify_record(a, dh):
            ok.add(role)
        else:
            bad.append(f"approval by {role!r} has no valid signature over this payment")
    return ok, bad


def check_intent(signer: HybridSigner, intent: dict, payload: dict, now_iso: str, used_nonces: set[str],
                 approvers=None) -> IntentCheck:
    """Executor pre-flight: signature, exact match, expiry, replay, and (when `approvers` is given) that every approval
    in the intent is a valid signature by that role's registered key over this exact payment."""
    reasons: list[str] = []
    if approvers is not None:
        reasons += verified_approval_roles(approvers, intent)[1]
    if not signer.verify(canonical(strip_sigs(intent)), intent.get("signatures", {})):
        reasons.append("signature invalid")
    for f in MATCH_FIELDS:
        if intent.get(f) != payload.get(f):
            reasons.append(f"{f} differs from signed intent ({payload.get(f)!r} vs {intent.get(f)!r})")
    if datetime.fromisoformat(now_iso) > datetime.fromisoformat(intent["not_after"]):
        reasons.append("intent expired")
    if intent["nonce"] in used_nonces:
        reasons.append("nonce already used (replay)")
    return IntentCheck(not reasons, reasons)
