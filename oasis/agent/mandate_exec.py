"""A signed standing instruction (mandate) for a recurring bill.

The student asks in chat ("pay my phone bill every month"). That produces a HELD draft that binds the registry payee, the registry account,
a per-run cap (never above the Tier-1 limit), the purpose and a nonce/expiry; only a signature by the student's registered device key over that
exact draft hash creates the mandate. Creating it moves no money. Afterwards the autonomy tick may pay that bill on its due date, but every run is a
normal request through the whole pipeline: the registry account is used, policy R10 is re-checked (Verified_Full recipient, amount within the Tier-1
limit), the executor enforces the signed intent, and the run is audited. A bill with a mandate is also held if its amount rises above the signed cap.
"""
from __future__ import annotations

from ..passport.models import Level
from ..trust.approvals import make_draft

ROUTE = "standing_mandate"
RULE = "C02_mandate_needs_signature"


def handle_mandate(agent, req, approver=None):
    from .pipeline import Outcome
    w, p = agent.w, agent.w.passport
    t0 = w.sim_minutes
    out = Outcome("held")
    m = req.mandate or {}
    if m.get("kind") == "rate_target":
        return _handle_rate_target(agent, req, out, t0)
    ob = p.obligation(str(m.get("obligation_id")))
    rec = p.recipients.get(ob.payee_id) if ob else None
    cred = w.registry.lookup(ob.payee_id) if ob else None
    cap = float(p.rules.tier1_auto_limit_cny)
    if (ob is None or rec is None or cred is None or cred.account_ref != rec.account_ref or rec.verification.level != Level.VERIFIED_FULL
            or ob.currency != "CNY" or ob.amount > cap):
        out.status = "rejected"
        out.card = agent._card(out, ob.payee_id if ob else "?", float(ob.amount) if ob else 0.0, "rejected", "mandate_ineligible",
                               [f"A standing instruction needs an open CNY bill of at most CNY {cap:,.0f} to a fully verified registry payee."])
        return out
    out.fields = {"payee_id": rec.id, "payee_name": rec.name, "amount": ob.amount, "currency": "CNY", "purpose": f"mandate:{ob.type}",
                  "account_ref": cred.account_ref, "every_days": ob.every_days or 30, "cap_cny": cap}
    out.label = "matches_known"
    out.risk = {"score": 0.0, "evidence": ["Built from the Passport and the registry; no document text."]}
    draft = make_draft(payee_id=rec.id, account_ref=cred.account_ref, amount=ob.amount, currency="CNY", purpose=f"mandate:{ob.type}", route_id=ROUTE,
                       not_after=(req.draft or {}).get("not_after") or w.now.replace(hour=23, minute=59).isoformat(),
                       nonce=(req.draft or {}).get("nonce") or w.builder.new_nonce())
    out.draft, dh = draft, draft["draft_hash"]
    signed = agent._verified_approvals(req, dh, out)
    out.decision = {"action": "allow" if "student" in signed else "hold", "rule": RULE, "tier": 2, "required_approvals": ["student"], "ruleset": "mandate-v1",
                    "reasons": ["A standing instruction lets the agent pay this bill on its own later, so it needs your device-key signature on this exact draft."]}
    if "student" not in signed:
        out.status, out.detected = "held", True
        out.card = agent._card(out, rec.name, ob.amount, "held", RULE, out.decision["reasons"], "Needs approval from: student")
        out.sim_minutes = w.sim_minutes - t0
        return out
    if w.audit.find("mandate_created", nonce=draft["nonce"]) or w.now_iso() > draft["not_after"]:
        out.status = "rejected"
        out.card = agent._card(out, rec.name, ob.amount, "rejected", "mandate_replay_or_expired", ["This signed mandate was already used or has expired."])
        return out
    mid = f"mandate_{len(p.rules.mandates) + 1}"
    ob.recurring, ob.every_days = True, ob.every_days or 30
    p.rules.mandates.append({"id": mid, "kind": "recurring_bill", "obligation": ob.id.split("#")[0], "payee_id": rec.id, "cap_cny": ob.amount,
                             "every_days": ob.every_days, "draft_hash": dh, "approval_key_id": signed["student"]["key_id"],
                             "created": w.today.isoformat(), "active": True})
    w.audit.append("mandate_created", {"mandate": mid, "nonce": draft["nonce"], "draft_hash": dh, "obligation": ob.id, "payee_id": rec.id,
                                       "cap_cny": ob.amount, "approval_key_id": signed["student"]["key_id"]})
    out.status, out.paid_cny = "paid", 0.0
    out.fields["mandate_id"] = mid
    out.trace.append(f"Mandate {mid}: {ob.type} to {rec.name} up to CNY {ob.amount:,.0f} every {ob.every_days} days, signed with the student's device key")
    out.sim_minutes = w.sim_minutes - t0
    return out


def _handle_rate_target(agent, req, out, t0):
    """A rate target is a standing instruction too: a held draft binding the rate and the amount; only the student's device-key signature sets it."""
    import math
    w, p = agent.w, agent.w.passport
    m = req.mandate
    try:
        rate, cny = float(m["rate"]), float(m["convert_cny"])
        if not (math.isfinite(rate) and math.isfinite(cny)) or not (0 < rate < 10) or not (0 < cny <= 1e7):
            raise ValueError("rate must be between 0 and 10 and the amount between 0 and 10,000,000")
    except (KeyError, TypeError, ValueError) as e:
        out.status = "rejected"
        out.card = agent._card(out, "your own wallets", 0.0, "rejected", "rate_target_invalid", [str(e)])
        return out
    out.fields = {"payee_id": "own_balance", "payee_name": "your own wallets", "amount": cny, "currency": "CNY", "purpose": "rate_target",
                  "account_ref": f"own:INR>CNY@{rate:.4f}", "rate": rate}
    out.label = "matches_known"
    out.risk = {"score": 0.0, "evidence": ["Built from the Passport only; the target converts the student's own balances and pays no one."]}
    draft = make_draft(payee_id="own_balance", account_ref=f"own:INR>CNY@{rate:.4f}", amount=cny, currency="CNY", purpose="rate_target", route_id="standing_rate_target",
                       not_after=(req.draft or {}).get("not_after") or w.now.replace(hour=23, minute=59).isoformat(),
                       nonce=(req.draft or {}).get("nonce") or w.builder.new_nonce())
    out.draft, dh = draft, draft["draft_hash"]
    signed = agent._verified_approvals(req, dh, out)
    out.decision = {"action": "allow" if "student" in signed else "hold", "rule": RULE, "tier": 2, "required_approvals": ["student"], "ruleset": "mandate-v1",
                    "reasons": ["A rate target lets the agent convert your own money on its own later, so it needs your device-key signature on this exact draft."]}
    if "student" not in signed:
        out.status, out.detected = "held", True
        out.card = agent._card(out, "your own wallets", cny, "held", RULE, out.decision["reasons"], "Needs approval from: student")
        out.sim_minutes = w.sim_minutes - t0
        return out
    if w.audit.find("mandate_created", nonce=draft["nonce"]) or w.now_iso() > draft["not_after"]:
        out.status = "rejected"
        out.card = agent._card(out, "your own wallets", cny, "rejected", "mandate_replay_or_expired", ["This signed target was already used or has expired."])
        return out
    t = agent.set_rate_target(rate, cny)
    mid = f"mandate_{len(p.rules.mandates) + 1}"
    p.rules.mandates.append({"id": mid, "kind": "rate_target", "target": t["id"], "rate": rate, "cap_cny": cny, "draft_hash": dh,
                             "approval_key_id": signed["student"]["key_id"], "created": w.today.isoformat(), "active": True})
    w.audit.append("mandate_created", {"mandate": mid, "nonce": draft["nonce"], "draft_hash": dh, "target": t["id"], "rate": rate, "cap_cny": cny,
                                       "approval_key_id": signed["student"]["key_id"]})
    out.status, out.paid_cny = "paid", 0.0
    out.fields["mandate_id"] = mid
    out.trace.append(f"Rate target {t['id']} at {rate:.4f} for CNY {cny:,.0f}, signed with the student's device key")
    out.sim_minutes = w.sim_minutes - t0
    return out
