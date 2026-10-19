"""A conversion between the student's OWN balances that needs the student's device-key signature (any supported pair, any size).

Why a signed draft: chat used to refuse everything beyond the Tier-1 auto limit ("use the Convert screen"). Now the request becomes a held draft
exactly like a payment: the draft binds the pair, the amount, a nonce and an expiry; only a signature by the student's registered device key over
that exact draft hash releases it; the nonce is single-use (the audit chain remembers it); balance and pair are re-checked when it runs.

What does not change: nothing here can pay anyone. The only accounts touched are the student's own wallets (`passport.currency.convert`), the
request carries no document text, and a role string grants nothing. Tier-1 conversions (INR->CNY inside the auto limit, rate targets) keep their own
path and are audited as before.
"""
from __future__ import annotations

import math

from ..mock import fx
from ..passport import currency as currency_mod
from ..trust.approvals import make_draft

OWN = "own_balance"
ROUTE = "own_balance_fx"
RULE = "C01_conversion_needs_signature"


def _draft(w, src: str, dst: str, amount: float, req) -> dict:
    return make_draft(payee_id=OWN, account_ref=f"own:{src}>{dst}", amount=amount, currency=src, purpose=f"convert_to_{dst.lower()}", route_id=ROUTE,
                      not_after=(req.draft or {}).get("not_after") or w.now.replace(hour=23, minute=59).isoformat(),
                      nonce=(req.draft or {}).get("nonce") or w.builder.new_nonce())


def handle_conversion(agent, req, approver=None):
    from .pipeline import Outcome
    w, p = agent.w, agent.w.passport
    t0 = w.sim_minutes
    out = Outcome("held")
    c = req.conversion or {}
    try:
        src, dst, amount = str(c["src"]).upper(), str(c["dst"]).upper(), float(c["amount"])
        if not math.isfinite(amount) or amount <= 0 or src == dst or src not in fx.CURRENCIES or dst not in fx.CURRENCIES:
            raise fx.FxError("choose two different supported currencies and a positive amount")
        q = fx.quote(amount, src, dst, fx.table_for(w.rates, w.day_index))
        if q.amount > p.balance(src) + 0.005:
            raise fx.FxError(f"not enough {src}: you hold {fx.SYMBOLS[src]}{p.balance(src):,.2f}")
    except (KeyError, ValueError, TypeError, fx.FxError) as e:
        out.status = "rejected"
        out.fields = {"payee_id": OWN, "payee_name": "your own wallets", "amount": c.get("amount"), "currency": c.get("src")}
        out.card = agent._card(out, "your own wallets", float(c.get("amount") or 0) if str(c.get("amount", "")).replace(".", "", 1).isdigit() else 0.0,
                               "rejected", "conversion_invalid", [str(e)])
        return out
    out.fields = {"payee_id": OWN, "payee_name": "your own wallets", "amount": amount, "currency": src, "purpose": f"convert_to_{dst.lower()}",
                  "account_ref": f"own:{src}>{dst}", "to_currency": dst, "expected_received": q.received}
    out.label = "matches_known"
    out.risk = {"score": 0.0, "evidence": ["Built from the Passport only; there is no document to score, and no third party is paid."]}
    draft = _draft(w, src, dst, amount, req)
    out.draft, dh = draft, draft["draft_hash"]
    signed = agent._verified_approvals(req, dh, out)
    out.decision = {"action": "allow" if "student" in signed else "hold", "rule": RULE, "tier": 2, "required_approvals": ["student"],
                    "reasons": ["Converting between your own balances above the Tier-1 limit, or in another pair, needs your device-key signature on this exact draft."],
                    "ruleset": "conversion-v1"}
    if "student" not in signed:
        out.status, out.detected = "held", True
        out.card = agent._card(out, "your own wallets", amount, "held", RULE, out.decision["reasons"], "Needs approval from: student")
        out.sim_minutes = w.sim_minutes - t0
        return out
    if w.audit.find("conversion_executed", nonce=draft["nonce"]):                      # single use
        out.status = "rejected"
        out.card = agent._card(out, "your own wallets", amount, "rejected", "conversion_replay", ["This signed conversion was already executed; a nonce is used once."])
        return out
    if draft["not_after"] and w.now_iso() > draft["not_after"]:
        out.status = "rejected"
        out.card = agent._card(out, "your own wallets", amount, "rejected", "conversion_expired", ["The signed draft has expired."])
        return out
    try:
        rec = currency_mod.convert(w, amount, src, dst)                                  # re-checks pair and balance at execution time
    except fx.FxError as e:
        out.status = "held"
        out.card = agent._card(out, "your own wallets", amount, "held", "conversion_refused", [str(e)])
        return out
    w.audit.append("conversion_executed", {"draft_hash": dh, "nonce": draft["nonce"], "from": src, "to": dst, "amount": amount,
                                           "received": rec["received"], "approval_key_id": signed["student"]["key_id"]})
    out.status, out.paid_cny = "paid", 0.0
    out.fields["received"] = rec["received"]
    out.trace.append(f"Converted {amount:,.2f} {src} to {rec['received']:,.2f} {dst} between your own balances on a signed draft")
    out.sim_minutes = w.sim_minutes - t0
    return out
