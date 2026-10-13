"""Paying an obligation owed in USD or EUR, through the same trust components as a CNY payment.

What is shared with the CNY pipeline (nothing here weakens it): the verified-payee registry (the account is the REGISTRY's, never
one read from a document), the verification level, the draft the student signs with their registered device key (role strings
grant nothing), the signed hybrid intent, the intent-enforcing executor (signature, exact match including the currency, nonce,
expiry, policy re-check), the single-use tool token bound to the currency, the hash-chained audit log, the anchor and the proof pack.

What differs: the request carries no document text. It is built from the Passport and the registry only (`Request.fx`), so
there is nothing for an injection to rewrite; the policy is `decide_fx` (never automatic, always the student's signature); the
ledger moves value between the student's USD / EUR account and the payee's account of the same currency (a transfer whose
currency does not match an account is refused by the ledger).
"""
from __future__ import annotations

from types import SimpleNamespace

from ..mock import fx
from ..passport.models import Level
from ..trust.approvals import make_draft
from ..trust.policy import FxPolicyInput, decide_fx
from ..world import FX_ACCTS

ROUTE_ID = "route_fx_settlement"


def handle_fx(agent, req, approver=None):
    from .pipeline import APPROVABLE, Outcome
    w, p = agent.w, agent.w.passport
    t0 = w.sim_minutes
    out = Outcome("held")
    ob = p.obligation(str((req.fx or {}).get("obligation_id")))
    if ob is None or ob.currency not in FX_ACCTS or ob.status == "paid" or ob.remaining <= 0:
        out.status = "rejected"
        out.card = agent._card(out, "?", 0.0, "rejected", "fx_bad_obligation",
                               ["This is not an open obligation owed in USD or EUR."])
        return out
    if ob.status == "frozen":
        out.status = "held"
        out.card = agent._card(out, ob.payee_id, ob.remaining, "held", "fx_frozen", ["The obligation is frozen after a security stop; approve the recovery first."])
        return out
    cur, amount = ob.currency, ob.remaining
    rec = p.recipients.get(ob.payee_id)
    cred = w.registry.lookup(ob.payee_id)
    out.fields = {"payee_id": ob.payee_id, "payee_name": rec.name if rec else ob.payee_id, "amount": amount, "currency": cur,
                  "purpose": ob.type, "account_ref": cred.account_ref if cred else None}
    out.label = "matches_known"
    out.risk = {"score": 0.0, "evidence": ["Built from the Passport and the registry; there is no document to score."]}
    if rec is None or cred is None or cred.account_ref != rec.account_ref:
        return agent._finish_stop(out, ob, out.fields, ["The registry does not confirm this recipient's account."],
                                  "R03_rejected_recipient", "rejected", t0, amount)
    vo = w.verifier.assess(p, payee_id=ob.payee_id, name=rec.name, account_ref=cred.account_ref)
    out.verification = {"level": vo.level.value, "reasons": vo.reasons, "account_changed": vo.account_changed}
    w.audit.append("verify", {"payee_id": vo.payee_id, **out.verification})
    if vo.level == Level.REJECTED:
        return agent._finish_stop(out, ob, out.fields, vo.reasons, "R03_rejected_recipient", "rejected", t0, amount)
    if vo.level == Level.UNVERIFIED or vo.needs_test_payment:
        return agent._finish_stop(out, ob, out.fields, vo.reasons + ["A CNY test payment cannot verify a foreign-currency account; verify the recipient first."],
                                  "R05_unverified", "needs_verification", t0, amount)
    rec = p.recipients[vo.payee_id]
    account_ref = rec.account_ref                       # only the registry-confirmed account is ever used
    proposal = {"payee_id": rec.id, "account_ref": account_ref, "amount": amount, "currency": cur, "route_id": ROUTE_ID}
    if w.canaries:
        hits = w.canaries.scan({"fields": proposal}, "fx_payment")
        if hits:
            out.canary_hits = [h.__dict__ for h in hits]
            w.audit.append("canary_tripped", {"stage": "fx_payment", "hits": out.canary_hits})
            return agent._finish_freeze(out, ob, out.fields, ["canary tripwire fired"], "R01_canary", t0, amount)
    table = fx.table_for(w.rates, w.day_index)
    amount_cny = round(amount * fx.mid(cur, "CNY", table), 2)
    paid_cny = sum(h["amount_cny"] for h in w.history if h["payee_id"] == rec.id)
    draft = make_draft(**proposal, purpose=ob.type,
                       not_after=(req.draft or {}).get("not_after") or w.now.replace(hour=23, minute=59).isoformat(),
                       nonce=(req.draft or {}).get("nonce") or w.builder.new_nonce())
    out.draft, dh = draft, draft["draft_hash"]
    signed = agent._verified_approvals(req, dh, out)
    approvals = set(signed)
    hits = w.canaries.hits if w.canaries else []

    def policy(appr):
        return decide_fx(FxPolicyInput(p, rec, rec.id, ob.type, amount, cur, amount_cny, list(hits), tuple(appr), paid_cny))

    d = policy(approvals)
    out.trace.append(f"Commit: policy {d.action} ({d.rule}) {d.reasons}")
    while d.action == "hold" and approver and set(d.required_approvals) <= APPROVABLE:
        roles, minutes = approver.review({"fields": out.fields, "obligation": ob, "decision": d, "risk": SimpleNamespace(score=0.0, evidence=[]),
                                          "mismatch": False, "followed_injection": False, "label": out.label, "remitter": "student",
                                          "purpose": ob.type, "instalment": False, "amount": amount, "required": list(d.required_approvals)})
        w.advance(minutes)
        for r in roles - approvals:
            agent._sim_sign(r, dh, signed)
        new = set(signed) - approvals
        if not new:
            break
        approvals |= new
        d = policy(approvals)
        out.trace.append(f"Commit: approvals {sorted(approvals)} -> {d.action} ({d.rule})")
    out.decision = d.to_dict()
    if d.action == "freeze":
        return agent._finish_freeze(out, ob, out.fields, d.reasons, d.rule, t0, amount)
    if d.action == "hold":
        out.status, out.detected = "held", True
        out.card = agent._card(out, out.fields["payee_name"], amount, "held", d.rule, d.reasons,
                               f"Needs approval from: {', '.join(d.required_approvals) or 'verification'}")
        out.sim_minutes = w.sim_minutes - t0
        return out
    intent = w.builder.build(student_id=p.student.id, purpose=ob.type, tier=d.tier, obligation_id=ob.id, not_after=draft["not_after"],
                             nonce=draft["nonce"], approvals=[signed[r] for r in sorted(approvals)], **proposal)
    out.intent = {k: v for k, v in intent.items() if k != "signatures"} | {"signature_algorithms": sorted(intent["signatures"])}
    w.audit.append("intent_signed", {"intent_id": intent["intent_id"], "intent_hash": w.builder.intent_hash(intent)})
    w.anchor_block = w.anchor.anchor(w.builder.intent_hash(intent))
    from ..mock.ledger import InsufficientFunds
    try:
        res = w.executor.execute(intent, dict(proposal), policy, FX_ACCTS[cur])
    except InsufficientFunds as e:
        return agent._finish_stop(out, ob, out.fields, [str(e)], "insufficient_funds", "held", t0, amount)
    except ValueError as e:                              # e.g. the ledger's currency check
        return agent._finish_stop(out, ob, out.fields, [str(e)], "ledger_refused", "held", t0, amount)
    out.trace.append(f"Execute: {res.status} {res.reasons}")
    if res.status == "frozen":
        return agent._finish_freeze(out, ob, out.fields, res.reasons, "executor_intent_check", t0, amount)
    if res.status == "held":
        out.status, out.detected = "held", True
        out.card = agent._card(out, out.fields["payee_name"], amount, "held", res.decision.rule, res.reasons)
        out.sim_minutes = w.sim_minutes - t0
        return out
    return _finish_paid(agent, out, ob, rec, amount, cur, amount_cny, res.transfer, intent, d, t0)


def _finish_paid(agent, out, ob, rec, amount, cur, amount_cny, transfer, intent, d, t0):
    from ..proof.pack import build_proof_pack
    w, p = agent.w, agent.w.passport
    w.sync_balances()
    out.status, out.paid_cny = "paid", amount_cny
    out.transfer = transfer.__dict__
    out.sim_minutes = w.sim_minutes - t0
    w.history.append({"payee_id": rec.id, "amount_cny": amount_cny, "amount_inr": agent._inr(amount_cny), "ts": w.now.timestamp(),
                      "date": w.today.isoformat(), "purpose": ob.type, "obligation_id": ob.id, "proof_id": intent["intent_id"],
                      "currency": cur, "amount": amount, "doc_hash": None, "invoice_ref": None})
    ob.amount_paid, ob.status = ob.amount, "paid"
    w.verifier.record_success(p, rec.id)
    ih = w.builder.intent_hash(intent)
    entry = w.audit.find("transfer_executed", intent_id=intent["intent_id"])[-1]
    anchor = w.anchor.verify(ih)
    ab = w.anchor_block
    if anchor and ab and ab.get("digest") == ih and "tx_hash" not in anchor:
        anchor = {**anchor, "tx_hash": ab["tx_hash"]}
    pack = build_proof_pack(signer=w.signer, intent=intent, verification=out.verification or {}, costs={}, audit_entry=entry,
                            anchor=anchor, trust_public_keys=w.signer.public_keys(), decision=d.to_dict())
    w.proofs[intent["intent_id"]] = pack
    p.reputation["proofs"].append(intent["intent_id"])
    out.proof_id = intent["intent_id"]
    out.trace.append(f"Prove: paid {cur} {amount:,.2f}; proof pack {out.proof_id}")
    return out


# ------------------------------------------------------------------------------------------------ sandbox demo bill
DEMO_PAYEES = {
    "us": ("payee_us_univ", "State University of Example (US, MOCK)", "US-UNIV-USD-0001", "USD"),
    "eu": ("payee_eu_univ", "Example Universitaet (EU, MOCK)", "EU-UNIV-EUR-0001", "EUR"),
}
DEMO_MAX = 100_000.0


def add_demo_obligation(world, kind: str, amount: float, days: int) -> dict:
    """Sandbox convenience: add a tuition bill owed in USD or EUR to one of two FIXED MOCK universities. The payee and its account
    come from this table only (never from the caller), and are issued by the MOCK registry, so the 'money goes only to the registry
    account' rule is unchanged. Raises ValueError for anything else."""
    from datetime import timedelta
    from ..passport.models import Obligation, Recipient
    from ..trust.verification import Verifier
    if kind not in DEMO_PAYEES:
        raise ValueError(f"kind must be one of {sorted(DEMO_PAYEES)}")
    if not (isinstance(amount, (int, float)) and 0 < amount <= DEMO_MAX) or not (0 <= int(days) <= 365):
        raise ValueError(f"amount must be between 0 and {DEMO_MAX:,.0f} and days between 0 and 365")
    pid, name, acct, cur = DEMO_PAYEES[kind]
    w, p = world, world.passport
    if w.registry.lookup(pid) is None:
        w.registry.issue(pid, name, "university", acct)
        w.registry.set_contact(pid, "the finance office's official portal inbox", "finance@example-university.example.edu")
    if acct not in w.ledger.accounts:
        w.ledger.open(acct, name, currency=cur)
    if pid not in p.recipients:
        Verifier.seed_verified(p, Recipient(id=pid, name=name, payee_type="university", account_ref=acct))
    n = 1 + sum(1 for o in p.obligations if o.id.startswith("obl_fx_"))
    ob = Obligation(id=f"obl_fx_{n}", type="tuition", payee_id=pid, amount=round(float(amount), 2), currency=cur,
                    due=(w.today + timedelta(days=int(days))).isoformat(), label=f"{cur} tuition (MOCK)")
    p.obligations.append(ob)
    w.audit.append("fx_obligation_added", {"obligation_id": ob.id, "payee_id": pid, "currency": cur, "amount": ob.amount})
    return ob.model_dump()
