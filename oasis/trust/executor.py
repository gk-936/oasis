"""Step 5 - intent-enforcing executor. The only component holding the (sandbox) payment credential."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable

from ..mock.ledger import SandboxLedger, Transfer
from .approvals import ApproverRegistry
from .audit import AuditLog
from .canaries import Canaries
from .crypto import HybridSigner
from .intents import check_intent, verified_approval_roles
from .policy import Decision


@runtime_checkable
class PaymentRail(Protocol):
    """The only three things the executor asks of a payment rail. `SandboxLedger` is the MOCK implementation. A real rail
    (a licensed partner's API) would have to supply the same three calls, keep the same guarantees (a token bound to one
    intent and one exact transfer, single use, short life; a currency that must match both accounts) and be the only thing
    that can move money. See docs/path-to-production.md."""
    def executor_credential(self) -> str: ...
    def mint_tool_token(self, issuer: str, *, intent_id: str, from_ref: str, to_ref: str, amount: float,
                        currency: str = "CNY", ttl_s: float = ...) -> str: ...
    def transfer(self, credential: str, from_ref: str, to_ref: str, amount: float, currency: str = "CNY",
                 memo: str = "", intent_id: str | None = None) -> Transfer: ...


@dataclass
class ExecResult:
    status: str                      # executed | refused | frozen | held
    reasons: list[str] = field(default_factory=list)
    transfer: Transfer | None = None
    decision: Decision | None = None

    @property
    def ok(self) -> bool:
        return self.status == "executed"


class Executor:
    def __init__(self, ledger: PaymentRail, signer: HybridSigner, audit: AuditLog,
                 canaries: Canaries | None, now_iso: Callable[[], str], approvers=None):
        self._ledger = ledger
        self._cred = ledger.executor_credential()
        self._signer = signer
        self._audit = audit
        self._canaries = canaries
        self._now = now_iso
        self._approvers = approvers if approvers is not None else ApproverRegistry()   # empty: no approval can verify
        self.used_nonces: set[str] = set()

    def execute(self, intent: dict, payload: dict, decide: Callable[[tuple[str, ...]], Decision],
                from_ref: str) -> ExecResult:
        """`decide(verified_roles)` re-evaluates policy NOW. The roles passed in are only those whose approval signature
        verified against the registered device key: a role string alone never reaches the policy engine."""
        # Checks 1-3: signature, exact match, expiry, replay, approval signatures.
        chk = check_intent(self._signer, intent, payload, self._now(), self.used_nonces, self._approvers)
        if not chk.ok:
            self._audit.append("executor_refused", {"intent_id": intent.get("intent_id"), "reasons": chk.reasons,
                                                    "payload": payload})
            return ExecResult("frozen", chk.reasons)
        # Canary check on the payload that is about to move money.
        if self._canaries:
            hits = self._canaries.scan(payload, "executor_payload")
            if hits:
                self._audit.append("canary_tripped", {"intent_id": intent["intent_id"],
                                                      "hits": [h.__dict__ for h in hits]})
                return ExecResult("frozen", [f"canary tripped: {h.kind}" for h in hits])
        # Check 4: policy decision, re-evaluated now.
        verified, _ = verified_approval_roles(self._approvers, intent)
        d = decide(tuple(sorted(verified)))
        self._audit.append("policy_decision", {"intent_id": intent["intent_id"], **d.to_dict()})
        if d.action == "freeze":
            return ExecResult("frozen", d.reasons, decision=d)
        if d.action == "hold":
            return ExecResult("held", d.reasons, decision=d)
        # The payment credential is minted per execution: short-lived, single-use, bound to this intent and transfer.
        token = self._ledger.mint_tool_token(self._cred, intent_id=intent["intent_id"], from_ref=from_ref,
                                             to_ref=payload["account_ref"], amount=payload["amount"],
                                             currency=payload["currency"])
        t = self._ledger.transfer(token, from_ref, payload["account_ref"], payload["amount"],
                                  payload["currency"], memo=intent["purpose"], intent_id=intent["intent_id"])
        self.used_nonces.add(intent["nonce"])
        self._audit.append("transfer_executed", {"intent_id": intent["intent_id"], "tx": t.id,
                                                 "to": payload["account_ref"], "amount": payload["amount"]})
        return ExecResult("executed", ["matches signed intent; policy allow"], t, d)
