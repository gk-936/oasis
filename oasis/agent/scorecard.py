"""Agent scorecard and mandate card (ROUTER_OVERHAUL.md section 11). Read-only: every number comes from the audit log, the passport or the pending list;
nothing here changes state, and the model is not involved."""
from __future__ import annotations

import collections


def build(S) -> dict:
    w = S.world
    p = w.passport
    entries = list(w.audit.entries)
    kinds = collections.Counter(e["kind"] for e in entries)
    refusals = collections.Counter(e["data"].get("category", "other") for e in entries if e["kind"] == "chat_refused")
    rejected = sum(1 for e in entries if e["kind"] == "policy_decision" and (e["data"].get("action") or e["data"].get("decision", {}).get("action")) in ("block", "reject", "rejected"))
    held_audit = sum(1 for e in entries if e["kind"] == "policy_decision" and (e["data"].get("action") or e["data"].get("decision", {}).get("action")) == "hold")
    active = [m for m in p.rules.mandates if m.get("active")]
    from ..trust.audit import verify_chain
    ok = verify_chain(entries).ok
    return {
        "acted_alone_tier1": kinds.get("autonomous_action", 0),
        "drafts_waiting_for_you": len(S.pending),
        "drafts_held_total": held_audit,
        "refusals_by_reason": dict(refusals),
        "scam_warnings": refusals.get("scam", 0),
        "rejected_by_policy": rejected,
        "canary_freezes": kinds.get("canary_tripped", 0),
        "approvals_rejected": kinds.get("approval_rejected", 0),
        "money_lost_cny": float(w.ledger.money_lost()),
        "audit_head": w.audit.head(),
        "audit_chain_ok": bool(ok),
        "audit_entries": len(entries),
        "caps": {"tier1_auto_limit_cny": float(p.rules.tier1_auto_limit_cny),
                 "mandates": [{"id": m["id"], "kind": m.get("kind"), "cap_cny": m.get("cap_cny"), "every_days": m.get("every_days"), "created": m.get("created"),
                               "expires": "until you revoke it"} for m in active]},
        "source": "audit log, passport and pending drafts; read-only",
    }


def summary(S, lang: str = "en") -> str:
    c = build(S)
    refused = sum(c["refusals_by_reason"].values())
    t = (f"Here is my record this session, all read from the audit log: I acted alone {c['acted_alone_tier1']} time(s) inside your Tier-1 limit of CNY {c['caps']['tier1_auto_limit_cny']:,.0f}; "
         f"{c['drafts_waiting_for_you']} draft(s) are waiting for your signature; I refused {refused} request(s) ({c['scam_warnings']} scam warning(s)); "
         f"{c['canary_freezes']} canary freeze(s); money lost CNY {c['money_lost_cny']:,.0f}. Audit chain {'intact' if c['audit_chain_ok'] else 'BROKEN'}, head {str(c['audit_head'])[:12]}.")
    return t


def mandate_card(S) -> str:
    p = S.world.passport
    cap = float(p.rules.tier1_auto_limit_cny)
    active = [m for m in p.rules.mandates if m.get("active")]
    base = (f"My mandate: I may pay registered bills up to CNY {cap:,.0f} each, only after you signed the standing instruction, and I stop at the first anomaly. "
            "Everything else waits for your device-key signature. You can end any standing instruction by saying 'stop my autopay' (it ends only after you sign), and every action is in the audit log.")
    if not active:
        return base + " Right now you have no active standing instruction."
    rows = "; ".join(f"{m['id']} ({m.get('kind', 'mandate').replace('_', ' ')}, up to CNY {float(m.get('cap_cny') or 0):,.0f}, until you revoke it)" for m in active)
    return base + f" Active now: {rows}."
