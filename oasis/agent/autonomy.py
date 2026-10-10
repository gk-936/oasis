"""Tier-1 autonomy: what the agent may do on its own, still under deterministic policy.

1. Student-set rate targets: "convert CNY 5,000 if INR->CNY reaches 0.0700". The agent watches the (mock) rate;
   it never predicts it. When the target is reached `policy.decide_conversion` decides: a small conversion into
   the student's own CNY balance is Tier 1 (allow); a larger one needs the student; a tripped canary freezes it.
2. Small recurring bills to Verified_Full recipients (e.g. a mobile plan): paid through the SAME six-step
   pipeline as any other payment, with the recipient's account taken from the Passport (never from a document).
   The policy engine allows it automatically only if the recipient is Verified_Full and the amount is within
   the Tier-1 limit (rule R10); otherwise it holds for approval.

Every autonomous action is written to the Passport's autonomy log and the hash-chained audit log.
"""
from __future__ import annotations
from datetime import date, timedelta

from ..passport.models import Level, Obligation
from ..trust.policy import decide_conversion
from .pipeline import OasisAgent, Request


def _log(agent: OasisAgent, kind: str, **data) -> dict:
    w = agent.w
    entry = {"day": w.today.isoformat(), "kind": kind, **data}
    w.passport.autonomy_log.append(entry)
    w.audit.append("autonomous_action", entry)
    return entry


def set_rate_target(agent: OasisAgent, rate: float, convert_cny: float, pair: str = "INR-CNY") -> dict:
    w = agent.w
    t = {"id": f"rt_{len(w.passport.rules.rate_targets) + 1:02d}", "pair": pair, "rate": float(rate),
         "convert_cny": float(convert_cny), "status": "watching", "created": w.today.isoformat()}
    w.passport.rules.rate_targets.append(t)
    w.audit.append("rate_target_set", t)
    return t


def _convert_for_target(agent: OasisAgent, t: dict, decision, rate: float) -> dict:
    w = agent.w
    conv = w.convert(w.passport.balance("CNY") + t["convert_cny"])
    if conv is None or "error" in conv:
        t["status"] = "blocked"
        return _log(agent, "rate_target_blocked", target=t["id"], reason=(conv or {}).get("error", "nothing to convert"))
    t["status"], t["executed"] = "done", w.today.isoformat()
    return _log(agent, "rate_target_conversion", target=t["id"], rate=rate, target_rate=t["rate"], rule=decision.rule,
                tier=decision.tier, convert_cny=t["convert_cny"], delivered_cny=conv["delivered_cny"],
                sent_inr=conv["sent_inr"], route=conv["route"], saved_cny=conv["saved_cny"])


def approve_rate_target(agent: OasisAgent, target_id: str) -> dict:
    w = agent.w
    t = next((x for x in w.passport.rules.rate_targets if x["id"] == target_id), None)
    if not t or t["status"] != "awaiting_approval":
        return {"error": "no such target awaiting approval"}
    d = decide_conversion(w.passport, t["convert_cny"], w.canaries.hits if w.canaries else [], ("student",))
    if d.action != "allow":
        return {"error": d.reasons}
    return _convert_for_target(agent, t, d, w.rates.mid(w.day_index))


def _check_rate_targets(agent: OasisAgent) -> list[dict]:
    w, acts = agent.w, []
    rate = w.rates.mid(w.day_index)
    for t in w.passport.rules.rate_targets:
        if t.get("status") != "watching" or rate < t["rate"]:
            continue
        d = decide_conversion(w.passport, t["convert_cny"], w.canaries.hits if w.canaries else [])
        if d.action == "allow":
            acts.append(_convert_for_target(agent, t, d, rate))
        elif d.action == "hold":
            t["status"] = "awaiting_approval"
            acts.append(_log(agent, "rate_target_needs_approval", target=t["id"], rate=rate, rule=d.rule, reasons=d.reasons))
        else:
            t["status"] = "blocked"
            acts.append(_log(agent, "rate_target_blocked", target=t["id"], rule=d.rule, reasons=d.reasons))
    return acts


def _pay_recurring(agent: OasisAgent, ob: Obligation) -> dict | None:
    w, p = agent.w, agent.w.passport
    rec = p.recipients.get(ob.payee_id)
    if rec is None or rec.verification.level != Level.VERIFIED_FULL:
        return None     # only fully verified recipients are eligible for autonomous payment
    text = (f"Recurring bill (agent-initiated from the Passport)\nPayee: {rec.name}\nPayee ID: {rec.id}\n"
            f"Account: {rec.account_ref}\nAmount: CNY {ob.amount:,.0f}\nPurpose: {ob.type}\nDue: {ob.due}")
    req = Request(text, source="recurring", recurring=True)
    out = agent.handle(req)       # no approver: Tier 1 passes by itself, anything else is held
    if out.status == "paid":
        base = ob.id.split("#")[0]
        n = sum(1 for o in p.obligations if o.id.split("#")[0] == base)
        p.obligations.append(ob.model_copy(update={"id": f"{base}#{n}", "status": "pending",
                                                   "due": (date.fromisoformat(ob.due) + timedelta(days=ob.every_days)).isoformat()}))
        return _log(agent, "recurring_bill_paid", obligation=ob.id, label=ob.label or ob.type, amount_cny=ob.amount,
                    rule=(out.decision or {}).get("rule"), tier=(out.decision or {}).get("tier"), proof_id=out.proof_id,
                    next_due=p.obligations[-1].due)
    ob.status = "planned"          # held: stop retrying every day; the student decides
    entry = dict(_log(agent, "recurring_bill_held", obligation=ob.id, status=out.status,
                      rule=(out.decision or {}).get("rule") or (out.card or {}).get("rule"),
                      reasons=(out.card or {}).get("reasons") or (out.decision or {}).get("reasons")))
    entry["held_request"], entry["held_outcome"] = req, out     # for the API to register a pending approval
    return entry


def _check_recurring(agent: OasisAgent) -> list[dict]:
    w, acts = agent.w, []
    for ob in list(w.passport.obligations):
        if ob.recurring and ob.status == "pending" and date.fromisoformat(ob.due) <= w.today:
            a = _pay_recurring(agent, ob)
            if a:
                acts.append(a)
    return acts


def autonomy_tick(agent: OasisAgent) -> list[dict]:
    return _check_rate_targets(agent) + _check_recurring(agent)


def run_days(agent: OasisAgent, days: int) -> list[dict]:
    acts: list[dict] = []
    for _ in range(max(0, int(days))):
        agent.w.advance(days=1)
        acts += autonomy_tick(agent)
    return acts
