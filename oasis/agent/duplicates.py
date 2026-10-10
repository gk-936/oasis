"""Duplicate-payment detection (rule R17).

Re-submitting an invoice that was already paid must never silently pay it again. A request is a suspected duplicate
when, for the same payee, ONE of these holds:

  1. it carries the same invoice reference as a payment already made;
  2. it is the identical document (same text, whitespace and case folded) as a payment made within DOC_WINDOW_DAYS days;
  3. it matches an obligation that is already fully paid (same payee, same purpose, same amount, same due date if the
     document states one) and no open obligation matches it.

An instalment against an open obligation is NOT a duplicate: a payment recorded against the same obligation never
counts for rules 1 and 2. Scheduled recurring bills are the agent's own, obligation-keyed payments and are not checked.
The check only ever adds a hold; it can never release one.
"""
from __future__ import annotations
import hashlib
import re

DOC_WINDOW_DAYS = 30

_REF_RE = re.compile(r"(?:Invoice\s*(?:No\.?|Number|Num|#|Ref(?:erence)?)|Inv\s*(?:No\.?|#)|Reference(?:\s*(?:No\.?|Number))?|"
                     r"Ref(?:\.|\s*No\.?|\s*#)|发票号码?|发票编号)\s*[:：#]?\s*([A-Za-z0-9][A-Za-z0-9._/\-]{2,39})", re.I)


def invoice_ref(text: str) -> str | None:
    """The invoice reference the document states (normalised: upper case), or None."""
    m = _REF_RE.search(text or "")
    return m.group(1).upper().rstrip(".-/") if m else None


def doc_hash(text: str) -> str:
    """Hash of the document with whitespace and case folded, so a re-sent copy of the same invoice matches."""
    norm = re.sub(r"\s+", " ", (text or "")).strip().casefold()
    return hashlib.sha256(norm.encode("utf-8", "surrogatepass")).hexdigest()


def find_duplicate(world, *, text: str, fields: dict, payee_id: str | None, ob, amount: float,
                   purpose: str, recurring: bool) -> dict | None:
    """Return {"kind","date","proof_id","amount","obligation_id","why"} for the earlier payment, or None."""
    if recurring or not payee_id:
        return None
    ref, dh = invoice_ref(text), doc_hash(text)
    now = world.now.timestamp()
    for h in reversed(world.history):
        if h.get("payee_id") != payee_id:
            continue
        if ob is not None and h.get("obligation_id") == ob.id:
            continue                                   # an instalment of the same open obligation
        kind = None
        if ref and h.get("invoice_ref") == ref:
            kind = "invoice_ref"
        elif h.get("doc_hash") == dh and now - h["ts"] <= DOC_WINDOW_DAYS * 86400:
            kind = "same_document"
        if kind:
            return _info(kind, h.get("date"), h.get("proof_id"), h["amount_cny"], h.get("obligation_id"), ref)
    if ob is None:
        due = fields.get("due")
        for o in world.passport.obligations:
            if (o.status == "paid" and o.payee_id == payee_id and o.type == purpose and abs(o.amount - amount) < 0.5
                    and (not due or o.due == due)):
                h = next((x for x in reversed(world.history) if x.get("obligation_id") == o.id), {})
                return _info("paid_obligation", h.get("date"), h.get("proof_id"), o.amount, o.id, ref)
    return None


def _info(kind: str, when, proof_id, amount, obligation_id, ref) -> dict:
    how = {"invoice_ref": f"it has the same invoice reference ({ref})",
           "same_document": "it is the same document",
           "paid_obligation": "it matches an obligation that is already paid"}[kind]
    proof_s = f", proof {proof_id}" if proof_id else ""
    return {"kind": kind, "date": when, "proof_id": proof_id, "amount": amount, "obligation_id": obligation_id,
            "invoice_ref": ref,
            "why": f"You already paid this on {when or 'an earlier date'}{proof_s}: {how}."}
