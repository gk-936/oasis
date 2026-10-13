"""Accepting and running an agentic plan. A plan is only a proposal until the student accepts it, and executing it
changes nothing about the trust model:

- every `pay` step is turned into an ordinary payment request built from the Passport and the verified-payee registry
  (never from model text) and runs through the SAME pipeline: verification ramp, corridor check, policy engine, signed
  hybrid intent, anchor, executor. Payments above the Tier-1 limit therefore wait for the student (and parent when
  policy says so); a frozen or rejected payment is reported, not forced.
- every `convert` step moves the student's own money between her own accounts, so it is decided by
  `policy.decide_conversion` (canary tripped -> freeze; above the auto limit -> student approval, which accepting the
  plan supplies: accepting is an authenticated student action on the student's own money). A parent-remitted conversion
  additionally needs the parent's consent, which must be a SIGNATURE by the parent's registered device key over the exact
  conversion step (`conversion_draft`); a "parent" string, or a student claiming it, grants nothing.
- the plan is re-validated at acceptance and at execution, against the Passport as it is then.
"""
from __future__ import annotations
from datetime import date

from ..planning import fxplan
from ..planning.fxplan import validate_fx_plan
from ..planning.validator import validate_plan
from ..trust.crypto import canonical, sha256_hex
from ..trust.policy import decide_conversion
from .pipeline import OasisAgent, Request


def get_plan(world, plan_id: str) -> dict | None:
    return next((p for p in world.plans if p["id"] == plan_id), None)


def step_statuses(world, plan: dict) -> list[dict]:
    """Derived live: pay steps are done when the obligation is paid; convert steps when recorded as executed."""
    out = []
    done = {e["step"]: e for e in plan.get("executed", [])}
    for i, s in enumerate(plan["steps"]):
        if s["action"] == "pay":
            ob = world.passport.obligation(s["obligation_id"])
            st = "done" if ob and ob.status == "paid" else ("blocked" if ob and ob.status == "frozen" else "scheduled")
        else:
            st = "done" if i in done and done[i].get("status") == "done" else done.get(i, {}).get("status", "scheduled")
        out.append({"step": i, "status": st, **({"note": done[i]["note"]} if i in done and done[i].get("note") else {})})
    return out


def accept_plan(agent: OasisAgent, plan_id: str) -> dict:
    w = agent.w
    plan = get_plan(w, plan_id)
    if plan is None:
        return {"error": "no such plan"}
    if plan["status"] not in ("proposed", "accepted"):
        return {"error": f"plan is {plan['status']}; only a valid proposal can be accepted"}
    v = (validate_fx_plan if plan.get("kind") == "fx" else validate_plan)(w, plan["steps"])
    if not v.ok:
        plan["status"] = "invalid"
        return {"error": "the plan no longer validates against the current Passport", "errors": v.errors}
    plan["status"] = "accepted"
    plan["accepted_at"] = w.now_iso()
    w.audit.append("plan_accepted", {"plan_id": plan_id, "by": "student", "steps": len(plan["steps"])})
    return {"plan_id": plan_id, "status": "accepted"}


def _bill_text(world, ob) -> str:
    rec = world.passport.recipients[ob.payee_id]
    return (f"Payment from an accepted plan (agent-initiated; details from the Passport and registry)\nPayee: {rec.name}\n"
            f"Payee ID: {rec.id}\nAccount: {rec.account_ref}\nAmount: CNY {ob.remaining:,.0f}\nPurpose: {ob.type}\nDue: {ob.due}")


def conversion_draft(plan_id: str, i: int, s: dict) -> dict:
    """What a parent signs to consent to one parent-remitted conversion step."""
    if "corridor" in s:     # a foreign-currency plan step (INR only can be parent-remitted)
        d = {"kind": "plan_conversion", "plan_id": plan_id, "step": i, "date": s["date"], "send_inr": float(s["send"]),
             "route_id": s["route_id"], "corridor": s["corridor"], "remitter": s.get("remitter", "student")}
    else:
        d = {"kind": "plan_conversion", "plan_id": plan_id, "step": i, "date": s["date"], "send_inr": float(s["send_inr"]),
             "route_id": s["route_id"], "remitter": s.get("remitter", "student")}
    d["canonical"] = canonical({k: v for k, v in d.items()}).decode()
    d["draft_hash"] = sha256_hex(d["canonical"])
    return d


def parent_consents_needed(plan: dict) -> list[dict]:
    return [conversion_draft(plan["id"], i, s) for i, s in enumerate(plan["steps"])
            if s["action"] == "convert" and s.get("remitter") == "parent"]


def record_parent_consent(agent: OasisAgent, plan_id: str, step: int, signature: str) -> dict:
    """The parent's signed consent for one conversion step. Verified against the parent's registered device key."""
    w = agent.w
    plan = get_plan(w, plan_id)
    if plan is None:
        return {"error": "no such plan"}
    need = {d["step"]: d for d in parent_consents_needed(plan)}
    if step not in need:
        return {"error": "that step does not need the parent's consent"}
    dh = need[step]["draft_hash"]
    if w.approvers.verify("parent", dh, signature) is None:
        w.audit.append("approval_rejected", {"role": "parent", "draft_hash": dh, "reason": "consent signature invalid"})
        return {"error": "consent signature does not verify for this conversion"}
    rec = w.approvers.make_record("parent", signature, w.now_iso())
    plan.setdefault("consents", {})[str(step)] = rec
    w.audit.append("plan_consent", {"plan_id": plan_id, "step": step, "draft_hash": dh, "key_id": rec["key_id"]})
    return {"plan_id": plan_id, "step": step, "key_id": rec["key_id"]}


def sim_parent_consent(agent: OasisAgent, plan_id: str) -> int:
    """Harness helper: the SIMULATED parent's device signs every conversion step that needs consent."""
    w = agent.w
    plan = get_plan(w, plan_id)
    n = 0
    for d in parent_consents_needed(plan):
        res = record_parent_consent(agent, plan_id, d["step"], w.sim_devices.sign("parent", d["draft_hash"]))
        n += "error" not in res
    return n


def _consent_ok(w, plan: dict, i: int, s: dict) -> bool:
    rec = (plan.get("consents") or {}).get(str(i))
    return bool(rec) and w.approvers.verify_record(rec, conversion_draft(plan["id"], i, s)["draft_hash"])


def execute_due(agent: OasisAgent, plan_id: str, approver=None) -> dict:
    """Run every step dated today or earlier that is not done yet. Later steps stay scheduled."""
    w = agent.w
    plan = get_plan(w, plan_id)
    if plan is None:
        return {"error": "no such plan"}
    if plan["status"] not in ("accepted", "executing"):
        return {"error": "accept the plan first (nothing runs from a proposal)"}
    ran: list[dict] = []
    held: list[tuple[Request, object]] = []
    done_steps = {e["step"] for e in plan["executed"] if e.get("status") == "done"}
    order = sorted(range(len(plan["steps"])), key=lambda i: (plan["steps"][i]["date"], 0 if plan["steps"][i]["action"] == "convert" else 1, i))
    for i in order:
        s = plan["steps"][i]
        if date.fromisoformat(s["date"]) > w.today or i in done_steps:
            continue
        fxp = plan.get("kind") == "fx"
        if s["action"] == "convert":
            res = (_run_fx_convert if fxp else _run_convert)(agent, plan, i, s)
        else:
            res = (_run_fx_pay if fxp else _run_pay)(agent, plan, i, s, approver, held)
        if res:
            ran.append(res)
    plan["status"] = "done" if all(x["status"] == "done" for x in step_statuses(w, plan)) else "executing"
    w.audit.append("plan_executed_due", {"plan_id": plan_id, "ran": [{"step": r["step"], "status": r["status"]} for r in ran]})
    return {"plan_id": plan_id, "today": w.today.isoformat(), "ran": ran, "plan_status": plan["status"],
            "steps": step_statuses(w, plan), "held": held}


def _record(plan: dict, i: int, status: str, note: str = "") -> dict:
    plan["executed"] = [e for e in plan["executed"] if e["step"] != i] + [{"step": i, "status": status, "note": note}]
    return {"step": i, "status": status, "note": note}


def _run_convert(agent, plan, i, s) -> dict:
    w = agent.w
    if s.get("remitter") == "parent" and not _consent_ok(w, plan, i, s):
        return _record(plan, i, "awaiting_parent_consent", "A parent-remitted conversion needs the parent's signed consent.")
    from ..mock.rates import ROUTES, delivered_amount
    route = next(r for r in ROUTES if r.id == s["route_id"])
    cny = delivered_amount(s["send_inr"], route, w.rates.mid(w.day_index))
    d = decide_conversion(w.passport, cny, w.canaries.hits if w.canaries else [], ("student",))     # accepting the plan = student approval
    if d.action != "allow":
        return _record(plan, i, "blocked", f"{d.rule}: {'; '.join(d.reasons)}")
    conv = w.convert_step(s["send_inr"], s["route_id"], s.get("remitter", "student"))
    if "error" in conv:
        return _record(plan, i, "blocked", conv["error"])
    out = _record(plan, i, "done", f"{conv['route']}: INR {conv['sent_inr']:,.0f} -> CNY {conv['delivered_cny']:,.2f} ({d.rule})")
    return out


def _run_pay(agent, plan, i, s, approver, held) -> dict | None:
    w = agent.w
    ob = w.passport.obligation(s["obligation_id"])
    if ob is None or ob.status == "paid":
        return _record(plan, i, "done", "already paid")
    if ob.status == "frozen":
        return _record(plan, i, "blocked", "obligation is frozen; approve the recovery plan first")
    req = Request(_bill_text(w, ob), source="plan")
    out = agent.handle(req, approver)
    if out.status == "paid":
        return _record(plan, i, "done", f"paid CNY {ob.amount:,.0f}; proof {out.proof_id}")
    if out.status == "held":
        held.append((req, out))
        need = ", ".join((out.decision or {}).get("required_approvals") or []) or "approval"
        return _record(plan, i, "awaiting_approval", f"waiting for {need}")
    return _record(plan, i, "blocked", f"{out.status}: {(out.card or {}).get('rule', '')}")


# ------------------------------------------------------------------------------------ foreign-currency plan steps
def _run_fx_convert(agent, plan, i, s) -> dict:
    """One conversion of an accepted FX plan into the student's own USD / EUR account. Never pays a third party."""
    from ..corridors import core as cor
    from ..mock import fx
    from ..trust import corridor as legacy
    w = agent.w
    rem = s.get("remitter", "student")
    if rem == "parent" and not _consent_ok(w, plan, i, s):
        return _record(plan, i, "awaiting_parent_consent", "A parent-remitted conversion needs the parent's signed consent.")
    try:
        c = cor.corridor(s["corridor"])
    except cor.CorridorError:
        return _record(plan, i, "blocked", "unknown corridor")
    table = fx.table_for(w.rates, w.day_index)
    route = next((r for r in cor.routes_for(s["corridor"], table) if r.id == s["route_id"]), None)
    if route is None:
        return _record(plan, i, "blocked", "unknown route")
    if c["src"] == "INR":       # LRS is re-checked now, against the Passport as it is today
        lrs = legacy.load_rules()["rules"]["lrs_annual_limit_usd"]["value"] * table["INR"]
        if w.passport.remitted_inr_fy.get(rem, 0.0) + float(s["send"]) > lrs + 0.005:
            return _record(plan, i, "blocked", "lrs_exceeded: this remitter's limit for the financial year would be exceeded")
    counts = fxplan.uses_safe_quota(w, plan["steps"])
    if c["src"] == "CNY" and counts:       # the SAFE annual quota is re-checked now against cumulative use
        y = str(w.today.year)
        cap = legacy.load_rules()["rules"]["safe_quota_usd"]["value"]
        if w.passport.cn_outbound_usd.get(y, 0.0) + float(s["send"]) / table["CNY"] > cap + 0.005:
            return _record(plan, i, "blocked", "annual_limit_exceeded: the SAFE annual quota would be exceeded")
    mid = fx.mid(c["src"], c["dst"], table)
    cny = cor.delivered(float(s["send"]), route, mid) * fx.mid(c["dst"], "CNY", table)
    d = decide_conversion(w.passport, cny, w.canaries.hits if w.canaries else [], ("student",))     # accepting the plan = student approval
    if d.action != "allow":
        return _record(plan, i, "blocked", f"{d.rule}: {'; '.join(d.reasons)}")
    conv = w.convert_fx_step(s["corridor"], s["route_id"], float(s["send"]), rem, counts_against_quota=counts)
    if "error" in conv:
        return _record(plan, i, "blocked", conv["error"])
    return _record(plan, i, "done", f"{conv['route']}: {conv['from']} {conv['sent']:,.0f} -> {conv['to']} {conv['delivered']:,.2f} ({d.rule}; {conv['price_status']} price)")


def _run_fx_pay(agent, plan, i, s, approver, held) -> dict | None:
    w = agent.w
    ob = w.passport.obligation(s["obligation_id"])
    if ob is None or ob.status == "paid":
        return _record(plan, i, "done", "already paid")
    if ob.status == "frozen":
        return _record(plan, i, "blocked", "obligation is frozen; approve the recovery plan first")
    req = Request("", source="plan", fx={"obligation_id": ob.id})
    out = agent.handle(req, approver)
    if out.status == "paid":
        return _record(plan, i, "done", f"paid {ob.currency} {ob.amount:,.2f}; proof {out.proof_id}")
    if out.status == "held":
        held.append((req, out))
        need = ", ".join((out.decision or {}).get("required_approvals") or []) or "approval"
        return _record(plan, i, "awaiting_approval", f"waiting for {need}")
    return _record(plan, i, "blocked", f"{out.status}: {(out.card or {}).get('rule', '')}")
