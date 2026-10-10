"""Parent approval view: a plain explanation in the parent's language (templated offline, LLM when available)."""
from __future__ import annotations

from . import i18n


def parent_view(world, fields: dict, lang: str | None = None) -> dict:
    """Build what the parent sees for one pending family transfer.

    `fields` are the (untrusted, extracted) request fields; the recipient's verification level is read from the
    Passport, not from the request.
    """
    p = world.passport
    parent = next((a for a in p.approvers if a.role == "parent"), None)
    lang = lang or (parent.language if parent else "en")
    amount_cny = float(fields.get("amount") or 0)
    amount_inr = round(amount_cny / world.rates.mid(world.day_index))
    rec = p.recipients.get(fields.get("payee_id") or "")
    ctx = {"student": p.student.name, "amount_inr": amount_inr, "amount_cny": amount_cny,
           "purpose": fields.get("purpose") or "family_support", "payee": (rec.name if rec else fields.get("payee_name")),
           "verification_level": rec.verification.level.value if rec else None,
           "verification_limit_cny": rec.verification.limit_cny if rec else 0.0,
           "threshold_inr": p.rules.parent_coapproval_above_inr}
    return {"language": lang, "language_name": i18n.LANGS.get(lang, lang), "amount_inr": amount_inr,
            "amount_cny": amount_cny, "explanation": world.llm.explain("parent_approval", ctx, lang),
            "facts": i18n.parent_facts(ctx, lang), "labels": i18n.LABELS.get(lang, i18n.LABELS["en"]),
            "available_languages": i18n.LANGS}
