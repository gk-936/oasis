"""Autonomous recovery (spec step 5): after a freeze the agent drafts a message to the LEGITIMATE recipient.

The draft is addressed only through the channel the verified-payee registry lists for that payee. The model is never
shown the suspicious request, and the draft is checked afterwards: it must contain no account number, phone number,
email address or link taken from the suspicious request, and no contact detail at all other than the registry's own.
A draft that fails is discarded and the template is used. Sending is out of scope here: the student approves first.
"""
from __future__ import annotations
import re

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
LONG_DIGITS_RE = re.compile(r"\d[\d \-]{5,}\d")        # account-like or phone-like digit groups (spaces / hyphens allowed)
HANDLE_RE = re.compile(r"(?<!\w)@\w{3,}")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def contact_tokens(text: str) -> set[str]:
    """Account numbers, phone numbers, emails, links and handles found in untrusted text (normalised)."""
    toks: set[str] = set()
    for m in EMAIL_RE.findall(text) + URL_RE.findall(text) + HANDLE_RE.findall(text):
        toks.add(m.casefold().rstrip(".,;)"))
    for m in LONG_DIGITS_RE.findall(text):
        d = _digits(m)
        if len(d) >= 6 and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", m.strip()):
            toks.add(d)
    for m in re.findall(r"\d{6,}", text):
        toks.add(m)
    return toks


def validate_draft(draft: str, suspicious_text: str, allowed: list[str] | None = None) -> list[str]:
    """Problems with a recovery draft (empty list = acceptable). `allowed` are the registry's own contact strings."""
    problems: list[str] = []
    allowed_n = {a.casefold() for a in (allowed or [])} | {_digits(a) for a in (allowed or []) if len(_digits(a)) >= 6}
    low, dd = draft.casefold(), _digits(draft)
    for tok in sorted(contact_tokens(suspicious_text) - allowed_n):
        t = tok.casefold()
        if (t in low) or (t.isdigit() and t in dd):
            problems.append(f"contains a detail from the suspicious request ({tok[:4]}...{tok[-2:]})" if t.isdigit()
                            else f"contains a contact from the suspicious request ({tok})")
    for m in EMAIL_RE.findall(draft) + URL_RE.findall(draft) + HANDLE_RE.findall(draft):
        if m.casefold().rstrip(".,;)") not in allowed_n:
            problems.append(f"contains a contact that is not the registry's verified one ({m})")
    for m in re.findall(r"\d[\d -]{6,}\d", draft):
        if _digits(m) not in allowed_n and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", m.strip()):
            problems.append("contains a long number that could be an account or phone number")
    if re.search(r"\d{8,}", draft):
        problems.append("contains a long digit string")
    return sorted(set(problems))


def template_draft(name: str, ob_type: str, amount: float, due: str, channel: str) -> str:
    return (f"Hello {name}, we received a payment request for {ob_type} (CNY {amount:,.0f}, due {due}) with changed details. "
            f"Nothing has been paid. Please confirm your current receiving account to us through {channel}.")


def build_recovery(world, ob, suspicious_text: str = "") -> dict | None:
    """The recovery plan shown to the student after a freeze. Facts come from the registry and the Passport only."""
    if not ob:
        return None
    cred = world.registry.lookup(ob.payee_id)
    name = cred.name if cred else ob.payee_id
    contact = world.registry.contact(ob.payee_id)
    channel = contact["channel"] if contact else "the registry-listed channel"
    allowed = [contact["address"]] if contact else []
    ctx = {"recipient": name, "recipient_type": cred.payee_type if cred else "payee", "obligation_type": ob.type,
           "amount_cny": ob.amount, "due": ob.due, "verified_channel": channel}
    tmpl = template_draft(name, ob.type, ob.amount, ob.due, channel)
    draft, source, rejected = tmpl, "template", []
    out = world.llm.draft_recovery(ctx)          # offline LLM: None -> template
    if out:
        rejected = validate_draft(out, suspicious_text, allowed)
        if not rejected:
            draft, source = out, f"llm ({getattr(world.llm, 'last_model', None) or world.llm.name})"
    check = validate_draft(draft, suspicious_text, allowed)
    return {"steps": ["freeze payment", "identify what changed", f"re-verify {name} through the registry's verified channel",
                      "replan the safest route", "ask the student to approve the new plan"],
            "verified_channel": f"{channel} (from the registry; never details from the suspicious request)",
            "channel": {"payee_id": ob.payee_id, "channel": channel, "address": contact["address"] if contact else None,
                        "source": "verified-payee registry"},
            "draft_message": draft, "draft_source": source, "draft_checks": {"ok": not check, "problems": check},
            "llm_draft_rejected": rejected,
            "safe_plan": {"obligation": ob.id, "pay_to_account": cred.account_ref if cred else None, "requires": "student approval"}}
