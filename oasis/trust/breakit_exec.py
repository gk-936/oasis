"""Break-it executor attacks: tamper with, replay or forge a SIGNED payment and hand it to the real executor.

Chat attacks test intake and policy. These test the last gate: whatever an attacker (or a prompt-injected agent) hands the
executor must match what the human signed. Runs only in a judge's sandbox world (MOCK ledger). The `decide` callable here
stands in for the policy engine: it allows only when the student's device signature verified, so a role string alone
grants nothing. Policy rules R01-R17 are exercised by the chat attacks and tests/test_policy*.py."""
from __future__ import annotations
import copy
from datetime import datetime, timedelta

from .approvals import Device, make_draft
from .policy import Decision

AMOUNT = 100.0
ATTACKER_ACCT = "6228480000009999"

ATTACKS = {
    "control":        "Honest payment, correctly signed (control: the harness is not just refusing everything)",
    "tamper_amount":  "Agent asks to move 10x the signed amount",
    "tamper_payee":   "Agent swaps in an attacker account after the human signed",
    "tamper_intent":  "Edit the signed intent's amount and payee, keep the old signature",
    "replay":         "Re-submit an intent that already paid (same nonce)",
    "expired":        "Submit a signed intent after its expiry",
    "forged_approval": "Approval signed by a key that is not the student's registered device",
    "role_swap":      "Student's signature relabelled as the parent's approval",
    "unsigned":       "Intent with the trust signature stripped",
    "pq_stripped":    "PQ signature stripped: valid Ed25519 signature but the ML-DSA-65 signature removed",
    "no_approval":    "Correct intent but no human device signature",
}


def _decide(roles: tuple[str, ...]) -> Decision:
    if "student" in roles:
        return Decision("allow", 2, "BREAKIT_CONTROL", ["student device signature verified"])
    return Decision("hold", 2, "BREAKIT_CONTROL", ["needs the student's device signature"], ["student"])


def _signed_intent(w, *, approve: bool = True, not_after: str | None = None, key=None, role="student"):
    from ..world import STUDENT_ACCT, UNIV_ACCT
    na = not_after or (w.now + timedelta(hours=1)).isoformat()
    proposal = {"payee_id": "payee_univ_x", "account_ref": UNIV_ACCT, "amount": AMOUNT, "currency": "CNY",
                "route_id": w.planned_route_id(None)}
    draft = make_draft(**proposal, purpose="tuition", not_after=na, nonce=w.builder.new_nonce())
    approvals = []
    if approve:
        sig = key.sign(draft["draft_hash"], "student") if key else w.sim_devices.sign("student", draft["draft_hash"])
        approvals = [{**w.approvers.make_record("student", sig, w.now_iso()), "role": role}]
    intent = w.builder.build(student_id=w.passport.student.id, purpose="tuition", tier=2, approvals=approvals,
                             not_after=na, nonce=draft["nonce"], **proposal)
    return intent, dict(proposal), STUDENT_ACCT


def run_attack(w, attack: str) -> dict:
    """Run one named attack against `w.executor` and report whether it was refused and what money moved."""
    if attack not in ATTACKS:
        raise KeyError(attack)
    lost0, n0 = w.ledger.money_lost(), len(w.ledger.transfers)
    ex = w.executor
    from ..world import STUDENT_ACCT
    acct = w.ledger.accounts[STUDENT_ACCT]
    acct.balance = max(acct.balance, AMOUNT * 20)     # sandbox float so the honest control payment can clear
    approve = attack != "no_approval"
    intent, payload, src = _signed_intent(
        w, approve=approve,
        not_after=(w.now - timedelta(minutes=5)).isoformat() if attack == "expired" else None,
        key=Device("student") if attack == "forged_approval" else None,
        role="parent" if attack == "role_swap" else "student")
    if attack == "tamper_amount":
        payload["amount"] = AMOUNT * 10
    elif attack == "tamper_payee":
        payload["account_ref"] = ATTACKER_ACCT
    elif attack == "tamper_intent":
        intent = copy.deepcopy(intent)
        intent["amount"], intent["account_ref"] = AMOUNT * 10, ATTACKER_ACCT
        payload["amount"], payload["account_ref"] = AMOUNT * 10, ATTACKER_ACCT
    elif attack == "unsigned":
        intent = {k: v for k, v in intent.items() if k not in ("signatures", "key_id")}
        intent["signatures"] = {}
    elif attack == "pq_stripped":              # the classical signature stays valid; only the post-quantum one is removed
        intent = copy.deepcopy(intent)
        intent["signatures"] = {k: v for k, v in intent.get("signatures", {}).items() if "ml" not in k.lower() and "dsa" not in k.lower()}
    elif attack == "replay":
        first = ex.execute(intent, payload, _decide, src)
        if not first.ok:
            raise RuntimeError("replay setup: the honest first payment did not execute")
    res = ex.execute(intent, payload, _decide, src)
    moved = round(sum(t.amount for t in w.ledger.transfers[n0:]), 2)
    legit_first = AMOUNT if attack == "replay" else 0.0
    extra = round(moved - legit_first, 2) if attack != "control" else 0.0
    return {"attack": attack, "label": ATTACKS[attack], "status": res.status, "blocked": res.status != "executed",
            "reasons": res.reasons, "money_moved": moved, "extra_money_moved": extra,
            "money_lost": round(w.ledger.money_lost() - lost0, 2), "mock": True}
