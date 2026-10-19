"""The six-step pipeline: understand -> plan -> verify -> commit -> execute and watch -> prove.

The LLM (steps 1-2 and explanations) proposes. Verification, policy, the signed intent and the executor
decide what money moves. Features can be switched off layer by layer so the benchmark can measure each layer;
with every layer off this is the unprotected baseline agent (same LLM, same tools).
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Protocol

from .. import config
from ..mock.ledger import InsufficientFunds
from .duplicates import doc_hash, find_duplicate, invoice_ref
from . import i18n, nl_extract
from .llm import diverges_from_genuine
from .request_types import LABELS, classify_request, needs_out_of_band
from ..passport.models import Level, Obligation, Recipient
from ..proof.pack import build_proof_pack
from ..trust import corridor
from ..trust.approvals import make_draft
from ..trust.crypto import canonical, sha256_hex
from ..trust.intents import strip_sigs
from ..trust.policy import Decision, PolicyInput, decide
from ..world import STUDENT_ACCT, World

PARENT_ACCT = "acct_parent"
APPROVABLE = {"student", "parent"}
STUDENT_LATENCY_MIN = 10
PARENT_LATENCY_MIN = 60


MAX_AMOUNT_CNY = 1e10     # no real payment is this large; anything above is an unreadable or hostile number


def unreadable_amount(raw) -> str | None:
    """Why `raw` cannot be a payment amount (None = it can). Money is CNY with at most 2 decimals (fen): NaN, infinity,
    a negative or absurd figure, or a sub-fen fraction such as 30000.004 is never rounded or guessed into a payment."""
    try:
        a = float(raw)
    except (TypeError, ValueError, OverflowError):
        return "the amount is not a number"
    if not math.isfinite(a):
        return "the amount is not a finite number"
    if a < 0 or a > MAX_AMOUNT_CNY:
        return "the amount is outside any plausible payment range"
    if abs(a * 100 - round(a * 100)) > 1e-6 * max(1.0, a):
        return "the amount has fractions of a fen (more than 2 decimals)"
    return None


class ApprovalProvider(Protocol):
    def review(self, ctx: dict) -> tuple[set[str], int]:
        """Return (roles that approve, simulated minutes taken). Called only for approvable holds."""


@dataclass
class Request:
    text: str
    source: str = "invoice"          # invoice | chat | screenshot
    purpose_hint: str | None = None
    remitter: str = "student"        # student | parent
    recurring: bool = False
    tool_poison: dict | None = None  # poisoned tool output that rewrites payment instructions at execute time
    approvals: tuple[str, ...] = ()  # DEPRECATED role strings: carry no authority and are ignored (audited if present)
    signed_approvals: tuple[dict, ...] = ()   # Ed25519 approvals over the draft hash (trust/approvals.py); only these count
    draft: dict | None = None        # {"nonce","not_after"} fixed when the payment was first held, so approvers sign one draft
    pay_again: bool = False          # the student explicitly confirmed paying a suspected duplicate a second time (R17)
    genuine: dict | None = None      # benchmark only: the document's genuine (pre-injection) fields, from the scenario
    channel: dict | None = None      # real inbound channel provenance (email headers, sender); risk evidence only
    conversion: dict | None = None   # {"src","dst","amount"}: an own-balance conversion on a signed draft (agent/conversion_exec.py)
    mandate: dict | None = None      # {"obligation_id"}: a standing instruction for a recurring bill, on a signed draft (agent/mandate_exec.py)
    fx: dict | None = None           # {"obligation_id"}: a foreign-currency payment built from the Passport + registry (agent/fx_exec.py)


@dataclass
class Outcome:
    status: str                      # paid | held | frozen | rejected | needs_verification
    label: str = ""                  # matches_known | new_or_changed | stop
    fields: dict = field(default_factory=dict)
    risk: dict = field(default_factory=dict)
    verification: dict | None = None
    decision: dict | None = None
    corridor: dict | None = None
    intent: dict | None = None
    transfer: dict | None = None
    card: dict | None = None
    proof_id: str | None = None
    sim_minutes: int = 0
    trace: list[str] = field(default_factory=list)
    canary_hits: list[dict] = field(default_factory=list)
    paid_cny: float = 0.0
    savings: dict | None = None
    recovery: dict | None = None
    detected: bool = False           # an alert/hold/freeze/rejection fired (attack detection)
    followed_injection: bool = False  # analysis-only ground truth
    draft: dict | None = None        # the exact payment draft approvers sign (fields + canonical string + draft_hash)
    rejected_approvals: list = field(default_factory=list)   # approvals that were presented but did not verify
    duplicate: dict | None = None    # the earlier payment this request repeats (R17): date, proof id, why
    extraction: dict | None = None   # live-agent mode: per-field sources and whether the model followed an injection

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class OasisAgent:
    def __init__(self, world: World):
        self.w = world
        self._suspicious_text = ""     # the request being handled; used only to CHECK recovery drafts, never to write them

    # ---------------------------------------------------------------- helpers
    def _known(self) -> tuple[list[str], dict[str, str]]:
        decoys = self.w.canaries.decoy_payees if self.w.canaries else set()
        recs = [r for r in self.w.passport.recipients.values() if r.id not in decoys]
        return [r.name for r in recs], {r.id: r.account_ref for r in recs}

    def _match_obligation(self, fields: dict) -> Obligation | None:
        p = self.w.passport
        pid, name = fields.get("payee_id"), (fields.get("payee_name") or "").casefold()
        for o in p.obligations:
            if o.status in ("paid",):
                continue
            rec = p.recipients.get(o.payee_id)
            if (pid and o.payee_id == pid) or (rec and name and rec.name.casefold() == name):
                if not fields.get("purpose") or o.type == fields["purpose"]:
                    return o
        return None

    def _card(self, out: Outcome, payee: str, amount: float, action: str, rule: str, reasons: list[str],
              nxt: str | None = None) -> dict:
        ctx = {"payee": payee, "amount": amount, "action": action, "rule": rule, "reasons": reasons}
        if nxt:
            ctx["next"] = nxt
        card = {"id": f"card_{len(self.w.cards)+1:03d}", "title": "Why was I stopped?" if action != "held"
                else "Waiting for approval", "text": self.w.llm.explain("why_stopped", ctx),
                "rule": rule, "action": action, "payee": payee, "amount": amount, "reasons": reasons}
        self.w.cards.append(card)
        self.w.audit.append("why_card", card)          # the audit entry is a copy: the guidance below is for display and never changes its hash
        card["uncertainty"] = i18n.card_uncertainty(rule, reasons)
        card["next_step"] = i18n.card_next_step(action, nxt)
        return card

    def _recovery(self, ob: Obligation | None) -> dict | None:
        """Autonomous recovery (spec step 5): see `recovery.build_recovery`. Uses the registry's verified channel only."""
        from .recovery import build_recovery
        return build_recovery(self.w, ob, self._suspicious_text)

    def _risk_ctx(self, fields: dict, amount: float) -> dict:
        """Read-only context for the risk scorer. The score is an input to policy, never the decision."""
        w = self.w
        cred = w.registry.lookup(fields["payee_id"]) if fields.get("payee_id") else None
        if cred is None and fields.get("payee_name"):
            cred = w.registry.lookup_by_name(fields["payee_name"])
        now = w.now.timestamp()
        from ..screening import sanctions        # public OFAC snapshot; evidence only (see screening.py)
        hits = sanctions().screen(fields.get("payee_name") or "") if fields.get("payee_name") else []
        return {"sanctions_hits": hits, "registry_known": cred is not None, "registry_account": cred.account_ref if cred else None,
                "amount_inr": self._inr(amount) if amount else 0.0,
                "approval_threshold_inr": w.passport.rules.parent_coapproval_above_inr,
                "recent": [{"payee_id": h["payee_id"], "amount_inr": h["amount_inr"],
                            "hours_ago": (now - h["ts"]) / 3600} for h in w.history]}

    def _inr(self, cny: float) -> float:
        return round(cny / self.w.rates.mid(self.w.day_index), 2)

    def _pay_direct(self, from_ref: str, to_ref: str, amount: float, memo: str):
        """Unprotected path: the agent itself holds the payment credential."""
        return self.w.ledger.transfer(self.w.ledger.executor_credential(), from_ref, to_ref, amount, "CNY", memo)

    def _policy_input(self, *, rec: Recipient | None, payee_id: str, purpose: str, amount: float,
                      cor, risk: float, hits, approvals, recurring: bool, remitter: str, currency: str = "CNY",
                      instalment: bool = False, remaining: float | None = None, duplicate: dict | None = None,
                      pay_again: bool = False) -> PolicyInput:
        paid = sum(h["amount_cny"] for h in self.w.history if h["payee_id"] == payee_id)
        return PolicyInput(self.w.passport, rec, payee_id, purpose, amount, self._inr(amount), cor, list(hits),
                           risk, tuple(approvals), recurring, remitter, paid, currency, instalment, remaining,
                           duplicate, pay_again)

    # --------------------------------------------------------------- test payment
    def _test_payment(self, rec: Recipient, out: Outcome) -> bool:
        w = self.w
        w.convert(1.0, None)
        payload = {"payee_id": rec.id, "account_ref": rec.account_ref, "amount": 1.0, "currency": "CNY",
                   "route_id": "route_test"}
        w.advance(30)
        if w.features.intents_policy:
            intent = w.builder.build(student_id=w.passport.student.id, purpose="verification_test", tier=1,
                                     not_after=(w.now.replace(hour=23, minute=59)).isoformat(), approvals=[],
                                     **payload)
            pi = lambda appr: decide(self._policy_input(rec=rec, payee_id=rec.id, purpose="verification_test", amount=1.0,
                                                   cor=corridor.CorridorResult(), risk=0.0, hits=[], approvals=(),
                                                   recurring=False, remitter="student"))
            res = w.executor.execute(intent, payload, pi, STUDENT_ACCT)
            ok = res.ok
        else:
            self._pay_direct(STUDENT_ACCT, rec.account_ref, 1.0, "verification_test")
            ok = True
        w.sync_balances()
        if ok:
            vo = w.verifier.confirm_test_payment(w.passport, rec.id, w.today.isoformat())
            w.audit.append("verification_ramp", {"payee_id": rec.id, "level": vo.level.value})
            out.trace.append(f"Verify: test payment confirmed -> {vo.level.value}")
        return ok

    # ------------------------------------------------------------ signed approvals
    def _verified_approvals(self, req: Request, dhash: str, out: Outcome) -> dict[str, dict]:
        """Keep only approvals whose signature verifies, for THIS draft, against the role's registered device key."""
        w, signed = self.w, {}
        for rec in req.signed_approvals:
            role = rec.get("role") if isinstance(rec, dict) else None
            if role in APPROVABLE and w.approvers.verify_record(rec, dhash):
                signed[role] = w.approvers.make_record(role, rec["signature"], rec.get("at") or w.now_iso())
            else:
                out.rejected_approvals.append({"role": role, "reason": "signature does not verify for this exact payment"})
                w.audit.append("approval_rejected", {"role": role, "draft_hash": dhash,
                                                     "reason": "signature does not verify for this exact payment"})
        if req.approvals:
            w.audit.append("unsigned_approval_ignored", {"roles": sorted(req.approvals), "draft_hash": dhash})
        return signed

    def _sim_sign(self, role: str, dhash: str, signed: dict[str, dict]) -> None:
        """A SIMULATED human approves: their in-process device key signs the draft (sandbox worlds only)."""
        w = self.w
        if w.sim_devices is None or role not in APPROVABLE:
            return
        sig = w.sim_devices.sign(role, dhash)
        if w.approvers.verify(role, dhash, sig):
            signed[role] = w.approvers.make_record(role, sig, w.now_iso())

    def sim_approve(self, req: Request, out: Outcome, roles) -> Request:
        """Harness/test helper: have the simulated devices of `roles` sign the held outcome's draft and attach the
        signatures to `req`, ready to be handled again. Not available on a world without sim devices."""
        d = out.draft
        signed = {r["role"]: r for r in req.signed_approvals}
        for role in roles:
            self._sim_sign(role, d["draft_hash"], signed)
        req.draft = {"nonce": d["nonce"], "not_after": d["not_after"]}
        req.signed_approvals = tuple(signed.values())
        return req

    # ---------------------------------------------------------------- main flow
    def handle(self, req: Request, approver: ApprovalProvider | None = None) -> Outcome:
        if req.mandate is not None:
            from .mandate_exec import handle_mandate
            return handle_mandate(self, req, approver)
        if req.conversion is not None:
            from .conversion_exec import handle_conversion
            return handle_conversion(self, req, approver)
        if req.fx is not None:
            from .fx_exec import handle_fx
            return handle_fx(self, req, approver)
        w, p, f_ = self.w, self.w.passport, self.w.features
        t0 = w.sim_minutes
        self._suspicious_text = req.text
        out = Outcome("held")
        names, accounts = self._known()

        # 1. UNDERSTAND (untrusted extraction)
        tool_ctx = w.canaries.tool_context() if w.canaries else {}
        ext = w.llm.extract(req.text, tool_ctx)
        fields = dict(ext.fields)
        decoys = w.canaries.decoy_payees if w.canaries else set()
        labelled = dict(fields)           # what the document stated in labelled form, before any sentence-level fill
        filled = nl_extract.fill_missing(fields, req.text, [r for r in p.recipients.values() if r.id not in decoys])
        bad_amount = unreadable_amount(fields["amount"]) if fields.get("amount") is not None else None
        if bad_amount:
            fields.pop("amount")          # never pay, round or audit an amount that is not valid money; ask the student instead
        out.fields, out.followed_injection = fields, ext.followed_injection
        if ext.mode == "llm":
            # Honest live-mode ground truth: compare what the model returned with the scenario's genuine fields.
            # (The model is never asked whether it followed an injection, and defences never read this.)
            mdl = ext.model_fields is not None and req.genuine is not None and diverges_from_genuine(ext.model_fields, req.genuine)
            if req.genuine is not None:
                out.followed_injection = mdl or diverges_from_genuine(fields, req.genuine)
            out.extraction = {"mode": "llm", "sources": dict(ext.sources), "call_failed": ext.call_failed,
                              "model_followed": bool(mdl), "ground_truth": req.genuine is not None,
                              "served_model": ext.served_model, "from_cache": ext.from_cache}
        out.trace.append(f"Understand: extracted payee={fields.get('payee_name')!r} amount={fields.get('amount')} "
                         f"purpose={fields.get('purpose')} (untrusted)")
        if filled:
            out.trace.append(f"Understand: read {', '.join(filled)} from the sentence (no labelled line; still untrusted)")
        if bad_amount:
            out.trace.append(f"Understand: amount rejected - {bad_amount}")
        if w.canaries:
            hits = w.canaries.scan({"fields": fields, "tool_calls": ext.used_tokens}, "understand")
            if hits:
                out.canary_hits = [h.__dict__ for h in hits]
                w.audit.append("canary_tripped", {"stage": "understand", "hits": out.canary_hits})
        purpose = fields.get("purpose") or req.purpose_hint or "living"
        fields["purpose"] = purpose
        amount = float(fields.get("amount") or 0)
        ob = self._match_obligation(fields)
        # An instalment is a deliberate part payment of what is still owed (never more than that, never a different payee).
        instalment = ob is not None and 0.5 < amount < ob.remaining - 0.5
        out.label = "stop" if out.canary_hits else ("matches_known" if ob and abs(ob.remaining - amount) < 0.5
                                                    else "new_or_changed")
        rctx = self._risk_ctx(fields, amount)
        if req.channel:
            rctx["channel"] = req.channel
        risk = w.llm.risk(fields, req.text, names, accounts, (amount if instalment else ob.remaining) if ob else None, rctx)
        out.risk = {"score": risk.score, "evidence": risk.evidence}
        if risk.components is not None:
            out.risk["components"] = risk.components
        out.trace.append(f"Understand: label={out.label}; risk={risk.score:.2f} {risk.evidence}")
        w.audit.append("understand", {"label": out.label, "fields": fields, "risk": out.risk})

        if out.canary_hits and f_.canaries:
            return self._finish_freeze(out, ob, fields, ["canary tripwire fired during understanding"],
                                       "R01_canary", t0, amount)
        # "structured" means the document itself carried payee, account and amount as labelled fields; a sentence we read
        # them from is not, so a message announcing new bank details still goes to out-of-band verification (R16).
        structured = (float(labelled.get("amount") or 0) > 0 and bool(labelled.get("account_ref"))
                      and bool(labelled.get("payee_name") or labelled.get("payee_id")))
        kind = classify_request(req.text)
        if f_.intents_policy and needs_out_of_band(kind, structured):
            return self._finish_out_of_band(out, ob, fields, kind, t0, amount)
        if amount <= 0 or not fields.get("account_ref"):
            out.status = "held"
            out.trace.append("Understand: low-confidence extraction - asking the student to confirm fields")
            out.card = self._card(out, fields.get("payee_name", "?"), amount, "held", "extract_low_confidence",
                                  ["Required payment fields could not be read confidently."] + ([f"Amount rejected: {bad_amount}."] if bad_amount else []), "Please confirm the details.")
            out.detected = True
            out.sim_minutes = w.sim_minutes - t0
            return out

        # 3. VERIFY
        payee_id, account_ref, rec = fields.get("payee_id"), fields["account_ref"], None
        if f_.verification:
            vo = w.verifier.assess(p, payee_id=payee_id, name=fields.get("payee_name", ""), account_ref=account_ref)
            w.advance(vo.sim_minutes - (30 if vo.needs_test_payment else 0))
            out.verification = {"level": vo.level.value, "reasons": vo.reasons, "account_changed": vo.account_changed}
            out.trace.append(f"Verify: {vo.level.value} {vo.reasons}")
            w.audit.append("verify", {"payee_id": vo.payee_id, **out.verification})
            if vo.level == Level.REJECTED:
                return self._finish_stop(out, ob, fields, vo.reasons, "R03_rejected_recipient", "rejected", t0, amount)
            if vo.level == Level.UNVERIFIED:
                return self._finish_stop(out, ob, fields, vo.reasons, "R05_unverified", "needs_verification", t0, amount)
            payee_id = vo.payee_id
            rec = p.recipients[payee_id]
            if vo.needs_test_payment and not self._test_payment(rec, out):
                return self._finish_stop(out, ob, fields, ["verification test payment did not complete"],
                                         "R05_unverified", "held", t0, amount)
            account_ref = rec.account_ref        # only the registry-confirmed account is ever used
            out.verification["level"] = rec.verification.level.value
        else:
            payee_id = payee_id or "payee_unknown"
            rec = p.recipients.get(payee_id)

        remitter = req.remitter
        from_ref = PARENT_ACCT if purpose == "family_support" else STUDENT_ACCT
        proposal = {"payee_id": payee_id, "account_ref": account_ref, "amount": amount, "currency": "CNY",
                    "route_id": w.planned_route_id(__import__("datetime").date.fromisoformat(ob.due) if ob else None)}
        # Poisoned tool output rewrites the instructions the (gullible) agent receives at execute time.
        exec_payload = dict(proposal)
        if req.tool_poison and w.llm.susceptible:
            exec_payload.update(req.tool_poison)
            out.followed_injection = True

        # 4. COMMIT + 5. EXECUTE
        if not f_.intents_policy:
            return self._execute_direct(out, ob, exec_payload, from_ref, purpose, remitter, t0, req)

        cor = corridor.check(p, payee_type=rec.payee_type if rec else "", purpose=purpose, amount_cny=amount,
                             amount_inr=self._inr(amount), remitter=remitter, history=w.history,
                             payee_id=payee_id, now_ts=w.now.timestamp(), year=w.today.year)
        out.corridor = cor.to_dict()
        hits = w.canaries.hits if w.canaries else []
        draft = make_draft(**proposal, purpose=purpose,
                           not_after=(req.draft or {}).get("not_after") or w.now.replace(hour=23, minute=59).isoformat(),
                           nonce=(req.draft or {}).get("nonce") or w.builder.new_nonce())
        out.draft, dh = draft, draft["draft_hash"]
        signed = self._verified_approvals(req, dh, out)       # role -> approval record; ONLY verified signatures count
        approvals = set(signed)
        mismatch = ob is not None and not instalment and abs(ob.remaining - amount) > 0.5
        currency = (fields.get("currency") or "CNY").upper()

        dup = find_duplicate(w, text=req.text, fields=fields, payee_id=payee_id, ob=ob, amount=amount, purpose=purpose,
                             recurring=req.recurring)
        out.duplicate = dup
        if dup:
            out.trace.append(f"Commit: possible duplicate payment - {dup['why']}")

        def policy(appr):
            return decide(self._policy_input(rec=rec, payee_id=payee_id, purpose=purpose, amount=amount, cor=cor,
                                             risk=risk.score, hits=hits, approvals=appr, recurring=req.recurring,
                                             remitter=remitter, currency=currency, instalment=instalment,
                                             remaining=ob.remaining if ob else None, duplicate=dup,
                                             pay_again=req.pay_again))
        d = policy(approvals)
        out.trace.append(f"Commit: policy {d.action} ({d.rule}) {d.reasons}")
        while d.action == "hold" and approver and set(d.required_approvals) <= APPROVABLE:
            roles, minutes = approver.review({"fields": fields, "obligation": ob, "decision": d, "risk": risk,
                                              "mismatch": mismatch, "followed_injection": ext.followed_injection,
                                              "label": out.label, "remitter": remitter, "purpose": purpose, "instalment": instalment,
                                              "amount": amount, "required": list(d.required_approvals)})
            w.advance(minutes)
            for r in roles - approvals:
                self._sim_sign(r, dh, signed)                 # simulated humans only; a real world has no sim devices
            new = set(signed) - approvals
            if not new:
                break
            approvals |= new
            d = policy(approvals)
            out.trace.append(f"Commit: approvals {sorted(approvals)} -> {d.action} ({d.rule})")
        out.decision = d.to_dict()
        if d.action == "freeze":
            return self._finish_freeze(out, ob, fields, d.reasons, d.rule, t0, amount)
        if d.action == "hold":
            out.status, out.detected = "held", True
            out.card = self._card(out, fields.get("payee_name", payee_id), amount, "held", d.rule, d.reasons,
                                  f"Needs approval from: {', '.join(d.required_approvals) or 'verification'}")
            out.sim_minutes = w.sim_minutes - t0
            return out

        if from_ref == STUDENT_ACCT:
            conv = w.convert(amount, ob and __import__("datetime").date.fromisoformat(ob.due))
            if conv and "error" not in conv:
                out.savings = conv
        intent = w.builder.build(student_id=p.student.id, purpose=purpose, tier=d.tier, obligation_id=ob.id if ob else None,
                                 not_after=draft["not_after"], nonce=draft["nonce"],
                                 approvals=[signed[r] for r in sorted(approvals)], **proposal)
        out.intent = {k: v for k, v in intent.items() if k != "signatures"} | {"signature_algorithms": sorted(intent["signatures"])}
        w.audit.append("intent_signed", {"intent_id": intent["intent_id"], "intent_hash": w.builder.intent_hash(intent)})
        w.anchor_block = w.anchor.anchor(w.builder.intent_hash(intent))
        try:
            res = w.executor.execute(intent, exec_payload, policy, from_ref)
        except InsufficientFunds as e:
            return self._finish_stop(out, ob, fields, [str(e)], "insufficient_funds", "held", t0, amount)
        out.trace.append(f"Execute: {res.status} {res.reasons}")
        if res.status == "frozen":
            return self._finish_freeze(out, ob, fields, res.reasons, "executor_intent_check", t0, amount)
        if res.status == "held":
            out.status, out.detected = "held", True
            out.card = self._card(out, fields.get("payee_name", payee_id), amount, "held", res.decision.rule, res.reasons)
            out.sim_minutes = w.sim_minutes - t0
            return out
        return self._finish_paid(out, ob, rec, payee_id, amount, purpose, remitter, res.transfer, intent, d, t0, req)

    # ------------------------------------------------------------ unprotected execution
    def _execute_direct(self, out, ob, payload, from_ref, purpose, remitter, t0, req=None) -> Outcome:
        w = self.w
        amount = payload["amount"]
        if from_ref == STUDENT_ACCT:
            conv = w.convert(amount, None)
            if conv and "error" not in conv:
                out.savings = conv
        try:
            t = self._pay_direct(from_ref, payload["account_ref"], amount, purpose)
        except InsufficientFunds as e:
            out.status = "held"
            out.trace.append(f"Execute: {e}")
            out.sim_minutes = w.sim_minutes - t0
            return out
        out.trace.append(f"Execute (agent holds credentials): paid {amount} to {payload['account_ref']}")
        rec = w.passport.recipients.get(payload["payee_id"])
        return self._finish_paid(out, ob, rec, payload["payee_id"], amount, purpose, remitter, t, None, None, t0, req)

    # ------------------------------------------------------------------ finishers
    def _finish_paid(self, out, ob, rec, payee_id, amount, purpose, remitter, transfer, intent, d, t0, req=None) -> Outcome:
        w, p = self.w, self.w.passport
        w.sync_balances()
        out.status, out.paid_cny = "paid", amount
        out.transfer = transfer.__dict__
        out.sim_minutes = w.sim_minutes - t0
        w.history.append({"payee_id": payee_id, "amount_cny": amount, "amount_inr": self._inr(amount), "ts": w.now.timestamp(),
                          "date": w.today.isoformat(), "purpose": purpose, "obligation_id": ob.id if ob else None,
                          "proof_id": intent["intent_id"] if intent is not None else None,
                          "doc_hash": doc_hash(req.text) if req is not None else None,
                          "invoice_ref": invoice_ref(req.text) if req is not None else None})
        p.remitted_inr_fy[remitter] = p.remitted_inr_fy.get(remitter, 0.0) + self._inr(amount)
        if ob:
            if abs(ob.remaining - amount) < 0.5:
                ob.amount_paid, ob.status = ob.amount, "paid"
            elif 0 < amount < ob.remaining:
                ob.amount_paid = round(ob.amount_paid + amount, 2)
                ob.status = "partially_paid"
        if rec:
            w.verifier.record_success(p, payee_id)
        p.reputation["verified_on_time_payments"] += 1 if (ob and rec) else 0
        if intent is not None:
            ih = w.builder.intent_hash(intent)
            entry = w.audit.find("transfer_executed", intent_id=intent["intent_id"])[-1]
            anchor = w.anchor.verify(ih)
            ab = w.anchor_block
            if anchor and ab and ab.get("digest") == ih and "tx_hash" not in anchor:
                anchor = {**anchor, "tx_hash": ab["tx_hash"]}      # FISCO verify() reads the contract; the tx hash comes from anchor()
            pack = build_proof_pack(signer=w.signer, intent=intent,
                                    verification=out.verification or {}, costs=out.savings or {},
                                    audit_entry=entry, anchor=anchor,
                                    trust_public_keys=w.signer.public_keys(), decision=d.to_dict() if d else None)
            w.proofs[intent["intent_id"]] = pack
            p.reputation["proofs"].append(intent["intent_id"])
            out.proof_id = intent["intent_id"]
        out.trace.append(f"Prove: paid CNY {amount:,.2f}" + (f"; proof pack {out.proof_id}" if out.proof_id else ""))
        return out

    def _finish_stop(self, out, ob, fields, reasons, rule, status, t0, amount) -> Outcome:
        w = self.w
        out.status, out.detected = status, True
        out.card = self._card(out, fields.get("payee_name", "?"), amount, status, rule, reasons)
        out.recovery = self._recovery(ob)
        if ob and status in ("rejected",):
            ob.status = ob.open_status
        w.audit.append("stopped", {"rule": rule, "status": status, "reasons": reasons})
        out.sim_minutes = w.sim_minutes - t0
        return out

    def _finish_out_of_band(self, out, ob, fields, kind, t0, amount) -> Outcome:
        """R16: the document asks for something Oasis never does from a document (change who approves, change where a
        payee is paid, refund/reverse, pay an authority that is not in the Passport). Nothing is actioned and no payment
        is attempted; the student is told to confirm through a channel the document did not supply."""
        w = self.w
        what = LABELS.get(kind, kind)
        reasons = [f"This looks like {what}.",
                   "A document or message cannot change approvers, approval limits or a payee's bank details, and Oasis does not "
                   "act on refund or reversal requests found in a document. Nothing in it was actioned."]
        out.status, out.detected = "held", True
        out.trace.append(f"Understand: request type {kind} - requires out-of-band verification")
        out.card = self._card(out, fields.get("payee_name", "?"), amount, "held", "R16_out_of_band_verification", reasons,
                              "Confirm it yourself through the registry-verified contact (not any contact in the document); "
                              "then re-submit the genuine invoice.")
        out.decision = {"action": "hold", "tier": 2, "rule": "R16_out_of_band_verification", "reasons": reasons,
                        "required_approvals": ["out_of_band_verification"], "ruleset": config.RULESET_VERSION}
        w.audit.append("out_of_band_required", {"request_type": kind, "amount": amount})
        out.sim_minutes = w.sim_minutes - t0
        return out

    def _finish_freeze(self, out, ob, fields, reasons, rule, t0, amount) -> Outcome:
        w = self.w
        out.status, out.detected = "frozen", True
        if ob:
            ob.status = "frozen"
        out.card = self._card(out, fields.get("payee_name", "?"), amount, "frozen", rule, reasons)
        out.recovery = self._recovery(ob)
        w.audit.append("freeze", {"rule": rule, "reasons": reasons, "obligation": ob.id if ob else None})
        out.sim_minutes = w.sim_minutes - t0
        return out

    def unfreeze_after_review(self, obligation_id: str) -> None:
        ob = self.w.passport.obligation(obligation_id)
        if ob and ob.status == "frozen":
            ob.status = ob.open_status
            self.w.audit.append("unfreeze", {"obligation": obligation_id, "by": "student"})

    def approve_recovery(self, obligation_id: str | None) -> dict:
        """The student approves the recovery plan after a freeze (the 'ask' step): the obligation goes back to
        pending and the tripped canaries are cleared, so the genuine payment can be re-run through the pipeline.
        Both actions are logged. Nothing is paid here."""
        w = self.w
        if obligation_id:
            self.unfreeze_after_review(obligation_id)
        cleared = len(w.canaries.hits) if w.canaries else 0
        if w.canaries:
            w.canaries.reset()
        w.audit.append("recovery_approved", {"obligation": obligation_id, "canaries_cleared": cleared, "by": "student"})
        return {"obligation": obligation_id, "canaries_cleared": cleared}

    # --------------------------------------------------------------- Tier-1 autonomy (see autonomy.py)
    def set_rate_target(self, rate: float, convert_cny: float) -> dict:
        from .autonomy import set_rate_target
        return set_rate_target(self, rate, convert_cny)

    def approve_rate_target(self, target_id: str) -> dict:
        from .autonomy import approve_rate_target
        return approve_rate_target(self, target_id)

    def autonomy_tick(self) -> list[dict]:
        from .autonomy import autonomy_tick
        return autonomy_tick(self)

    def run_days(self, days: int) -> list[dict]:
        from .autonomy import run_days
        return run_days(self, days)
