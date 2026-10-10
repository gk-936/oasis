"""Step 5 - intent-enforcing executor. The only component holding the (sandbox) payment credential."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

from ..mock.ledger import SandboxLedger, Transfer
from .audit import AuditLog
from .canaries import Canaries
from .crypto import HybridSigner
from .intents import check_intent
from .policy import Decision


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
    def __init__(self, ledger: SandboxLedger, signer: HybridSigner, audit: AuditLog,
                 canaries: Canaries | None, now_iso: Callable[[], str]):
        self._ledger = ledger
        self._cred = ledger.executor_credential()
        self._signer = signer
        self._audit = audit
        self._canaries = canaries
        self._now = now_iso
        self.used_nonces: set[str] = set()

    def execute(self, intent: dict, payload: dict, decide: Callable[[], Decision], from_ref: str) -> ExecResult:
        # Checks 1-3: signature, exact match, expiry, replay.
        chk = check_intent(self._signer, intent, payload, self._now(), self.used_nonces)
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
        d = decide()
        self._audit.append("policy_decision", {"intent_id": intent["intent_id"], **d.to_dict()})
        if d.action == "freeze":
            return ExecResult("frozen", d.reasons, decision=d)
        if d.action == "hold":
            return ExecResult("held", d.reasons, decision=d)
        t = self._ledger.transfer(self._cred, from_ref, payload["account_ref"], payload["amount"],
                                  payload["currency"], memo=intent["purpose"], intent_id=intent["intent_id"])
        self.used_nonces.add(intent["nonce"])
        self._audit.append("transfer_executed", {"intent_id": intent["intent_id"], "tx": t.id,
                                                 "to": payload["account_ref"], "amount": payload["amount"]})
        return ExecResult("executed", ["matches signed intent; policy allow"], t, d)
