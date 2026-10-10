"""What kind of request is this document? Oasis only knows how to do one thing from a document: pay a registry-
verified payee for an obligation. Everything else a document can ask for is classified here so that it is routed to
an out-of-band verification hold (rule R16) instead of being half-understood as a payment.

Classification is deterministic and keyword based; it only ever ADDS a hold, it never grants anything. The pipeline
has no code path that changes an approver, an approval threshold, a notification contact or a stored recipient from a
document, so "never actioned" is structural; this module makes the refusal visible and explainable.
"""
from __future__ import annotations
import re

PAY = "pay_invoice"
CHANGE_APPROVER = "change_approver"
CHANGE_RECIPIENT = "change_recipient_details"
REFUND = "refund"
AUTHORITY = "authority_demand"

_CHANGE_VERB = r"(?:change|update|replace|add|remove|lower|raise|reduce|reset|disable|waive|switch|edit|modify|更改|修改|更换|变更|降低|取消)"
_APPROVER_NOUN = (r"(?:co-?approver|approver|approval (?:threshold|limit|contact|rule|requirement)|"
                  r"(?:guardian|parent|notification|verification|confirmation|security|2fa|otp)\s+(?:contact|e-?mail|phone|number|device)|"
                  r"审批人|批准人|审批额度|审批门槛)")
_APPROVER_RE = re.compile(rf"{_CHANGE_VERB}[^.\n]{{0,60}}?{_APPROVER_NOUN}", re.I)
_RECIPIENT_RE = re.compile(
    r"((?:bank|account|payment|receiving) details? (?:have |has )?(?:been )?(?:changed|updated|moved)|"
    r"(?:changed|new|updated|different) (?:bank )?(?:account|card)|"
    r"(?:old|previous|earlier) (?:bank )?(?:account|card)[^.\n]{0,20}?(?:closed|froze\w*|frozen|cancelled|canceled|blocked|lost)|"
    r"(?:bank|card|account)[^.\n]{0,15}?\b(?:froze|frozen|blocked|closed)\b[^.\n]{0,40}?(?:send|remit|transfer|pay)|"
    r"(?:send|remit|transfer|pay)[^.\n]{0,120}?\binstead\b|"
    r"银行(?:信息|账户|账号)(?:已)?(?:变更|更新|更换)|(?:已)?更换(?:银行)?(?:卡|账号|账户))", re.I)
_REFUND_RE = re.compile(r"\b(?:refund(?!able)|reimburs\w*|chargeback|reversal|(?:reverse|return|send back) (?:the |your )?(?:funds|payment|money))\b|退款|退还", re.I)
_AUTHORITY_ORG = re.compile(r"(?:embassy|consulate|public security|police|immigration|entry-?exit|visa office|"
                            r"tax bureau|公安|大使馆|领事馆|出入境|海关)", re.I)
_AUTHORITY_THREAT = re.compile(r"(?:deport\w*|detain\w*|detention|arrest\w*|guarantee deposit|cancell?ation of (?:your )?visa|"
                               r"visa (?:will be )?cancell?ed|fine|penalt\w+|驱逐|拘留|逮捕|保证金|罚款)", re.I)

LABELS = {
    CHANGE_APPROVER: "a request to change who approves payments or the approval rules",
    CHANGE_RECIPIENT: "a message asking to change where a payee is paid",
    REFUND: "a refund or reversal request",
    AUTHORITY: "a payment demand from an authority that is not an obligation in the Passport",
}


def classify_request(text: str) -> str:
    """One of the type constants above. `pay_invoice` is the default (including odd or unreadable documents)."""
    if _APPROVER_RE.search(text):
        return CHANGE_APPROVER
    if _REFUND_RE.search(text):
        return REFUND
    if _AUTHORITY_ORG.search(text) and _AUTHORITY_THREAT.search(text):
        return AUTHORITY
    if _RECIPIENT_RE.search(text):
        return CHANGE_RECIPIENT
    return PAY


def needs_out_of_band(kind: str, structured: bool) -> bool:
    """Whether the request must be routed to R16 before any payment logic runs.
    Approver changes always (a document can never change the people who approve). Refunds and authority demands are not
    something Oasis does from a document. A recipient-detail message is only held when it is not a structured invoice:
    a structured invoice with new bank details is handled by the registry verification ramp (re-verify, don't block)."""
    if kind == CHANGE_APPROVER:
        return True
    if kind in (REFUND, AUTHORITY):
        return True
    if kind == CHANGE_RECIPIENT:
        return not structured
    return False
