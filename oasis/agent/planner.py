"""Agentic planner (spec step 2): the agent builds the plan by calling tools, checking the result and revising.

Two implementations speak the same tool protocol (`oasis/planning/tools.py`):

- `DeterministicPlanner` (offline, no network): calls the read tools, drafts a plan, submits it with `propose_plan`,
  and revises from the validator's concrete errors. It is the demo/test path and the safety net.
- `AgenticPlanner` (Groq native tool calling): the model chooses the tool calls and the plan; the same toolbox and
  validator answer. If the model cannot produce a valid plan within the loop (or the API fails) the deterministic plan
  is used and the fallback and its reason are recorded.

Either way the result is a PROPOSAL. Nothing here moves money; executing an accepted plan goes through the normal
pipeline (`oasis/agent/plan_exec.py`).
"""
from __future__ import annotations
import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..mock.rates import ROUTES, delivered_amount
from ..planning.routes import inr_needed
from ..planning.tools import TOOL_SPECS, PlanningToolbox, compact
from ..planning.validator import required_obligations, safe_quota_inr, validate_plan

MAX_ITERATIONS = 4          # proposals the validator will judge
MAX_MODEL_CALLS = 8         # chat completions per plan (live)
PAY_MARGIN_DAYS = 2         # pay this many days before the due date when funds allow
NON_BANK = [r for r in ROUTES if not r.typical_bank]


@dataclass
class PlanResult:
    steps: list[dict]
    valid: bool
    validation: dict
    rationale: str
    planner: str
    model: str | None = None
    iterations: int = 0
    fell_back: bool = False
    fallback_reason: str | None = None
    trace: list[dict] = field(default_factory=list)
    tokens: int = 0
    model_calls: int = 0


# ---------------------------------------------------------------------------------------------- deterministic
def _route_choice(send_estimate: float, days_available: int, max_days: int | None, mid: float):
    """Cheapest (most CNY delivered) non-bank route that arrives within `days_available` days."""
    ok = [r for r in NON_BANK if r.days <= days_available and (max_days is None or r.days <= max_days)]
    pool = ok or sorted(NON_BANK, key=lambda r: r.days)[:1]
    return max(pool, key=lambda r: delivered_amount(send_estimate, r, mid))


def _draft(world, tb: PlanningToolbox, pas: dict, obs: dict, cons: dict) -> tuple[list[dict], str]:
    """One draft from what the read tools reported. `cons` carries what earlier validator errors taught the planner."""
    today = date.fromisoformat(pas["today"])
    mid = world.rates.mid(world.day_index)
    need = sorted((o for o in obs["obligations"] if o["plan_must_fund"]), key=lambda o: o["due"])
    cny0 = pas["balances"].get("CNY", 0.0)
    inr0 = pas["balances"].get("INR", 0.0)
    reserve = sum(t["convert_cny"] / t["rate"] for t in pas["rate_targets"])
    quota = pas["safe_quota_inr_per_year"]
    year_used = {y: float(v) for y, v in pas["safe_used_inr_by_year"].items()}
    shortfall = max(0.0, sum(o["amount_cny"] for o in need) - cny0)
    first_due = date.fromisoformat(need[0]["due"]) if need else today
    steps: list[dict] = []
    arrivals: list[tuple[date, float]] = []
    notes: list[str] = []

    remaining, cursor, student_free = shortfall, today, max(0.0, inr0 - reserve)
    guard = 0
    while remaining > 0.5 and guard < 6:
        guard += 1
        # the earliest obligation this conversion has to help fund (cumulative need so far)
        covered, deadline = cny0 + sum(c for _, c in arrivals), first_due
        run = 0.0
        for o in need:
            run += o["amount_cny"]
            if run > covered:
                deadline = date.fromisoformat(o["due"])
                break
        days = (deadline - cursor).days - 1
        est = remaining / (mid * 0.99)
        route = _route_choice(est, days, cons.get("max_route_days"), mid)
        tb.call("get_routes", {"send_inr": round(est), "due": deadline.isoformat()})
        send_full = math.ceil(inr_needed(world.rates, route, remaining + 1.0, world.day_index))
        room = max(0.0, quota - year_used.get(str(cursor.year), 0.0))
        if room < 1:                                    # this calendar year's SAFE quota is used: wait for next January
            cursor = date(cursor.year + 1, 1, 1)
            notes.append(f"SAFE quota for {cursor.year - 1} is used up, so the rest waits for {cursor}.")
            continue
        send = min(send_full, math.floor(room))
        part_cny = delivered_amount(send, route, mid) if send < send_full else remaining
        tb.call("check_corridor", {"amount_inr": send, "purpose": need[0]["type"] if need else "tuition", "remitter": "student"})
        stu = min(send, student_free)
        if send > stu and cons.get("use_parent"):
            route_s = _route_choice(stu, days, cons.get("max_route_days"), mid) if stu > 0 else route
            got_stu = delivered_amount(stu, route_s, mid) if stu > 0 else 0.0
            need_par = max(remaining - got_stu, 1.0) + 1.0
            route_p = _route_choice(need_par / (mid * 0.99), days, cons.get("max_route_days"), mid)
            par = min(math.ceil(inr_needed(world.rates, route_p, need_par, world.day_index)), max(0, math.floor(room) - stu))
            if stu > 0:
                steps.append({"action": "convert", "date": cursor.isoformat(), "send_inr": round(stu, 2), "route_id": route_s.id, "remitter": "student"})
            steps.append({"action": "convert", "date": cursor.isoformat(), "send_inr": float(par), "route_id": route_p.id, "remitter": "parent"})
            part_cny = got_stu + delivered_amount(par, route_p, mid)
            send = stu + par
            send_full = send + 1 if part_cny < remaining - 0.5 else send     # still short: stage the rest
            notes.append(f"The student's own INR (after keeping INR {reserve:,.0f} for rate targets) covers INR {stu:,.0f}; "
                         f"the parent would remit INR {par:,.0f}, which needs the parent's consent.")
            route = route_p
        else:
            steps.append({"action": "convert", "date": cursor.isoformat(), "send_inr": float(send), "route_id": route.id, "remitter": "student"})
        student_free = max(0.0, student_free - stu)
        year_used[str(cursor.year)] = year_used.get(str(cursor.year), 0.0) + send
        arrivals.append((cursor + timedelta(days=route.days), part_cny))
        remaining -= part_cny
        if send < send_full:
            notes.append(f"Staged: INR {send:,.0f} now (the SAFE quota leaves INR {room:,.0f} this calendar year), the rest from January.")
            cursor = date(cursor.year + 1, 1, 1)

    # pay dates: a couple of days before the due date, never before the CNY has arrived
    cum, bal_dates = 0.0, sorted(arrivals)
    for o in need:
        cum += o["amount_cny"]
        due = date.fromisoformat(o["due"])
        ready: date | None = today if cny0 >= cum else None
        running = cny0
        for d, c in bal_dates:
            running += c
            if ready is None and running >= cum:
                ready = d
        pay = min(max(today, due - timedelta(days=PAY_MARGIN_DAYS), ready or due), due)
        steps.append({"action": "pay", "date": pay.isoformat(), "obligation_id": o["id"], "payee_id": o["payee_id"], "amount_cny": o["amount_cny"]})
    steps.sort(key=lambda s: (s["date"], 0 if s["action"] == "convert" else 1))
    n_conv = sum(1 for s in steps if s["action"] == "convert")
    why = (f"Pay {len(need)} obligation(s) {PAY_MARGIN_DAYS} days before each due date; "
           + (f"fund the CNY shortfall of {shortfall:,.0f} with {n_conv} conversion(s) on the cheapest route that arrives in time. "
              if shortfall > 0 else "the CNY already in the account covers everything, so no conversion is needed. ")
           + " ".join(notes))
    return steps, why.strip()


def _repair(cons: dict, errors: list[dict]) -> bool:
    """Teach the draft from validator errors. Returns False when nothing new can be tried."""
    changed = False
    for e in errors:
        c = e["code"]
        if c in ("insufficient_inr", "rate_target_reserve") and not cons.get("use_parent"):
            cons["use_parent"] = changed = True
        elif c in ("route_too_slow",) and cons.get("max_route_days") != 1:
            cons["max_route_days"] = 1
            changed = True
    return changed


class DeterministicPlanner:
    name = "deterministic"

    def plan(self, world, goal: str = "") -> PlanResult:
        tb = PlanningToolbox(world, MAX_ITERATIONS)
        pas, obs = tb.call("read_passport"), tb.call("list_obligations")
        tb.call("get_rates")
        tb.call("forecast_runway")
        cons: dict = {}
        rationale = ""
        for _ in range(MAX_ITERATIONS):
            steps, rationale = _draft(world, tb, pas, obs, cons)
            res = tb.call("propose_plan", {"steps": steps, "rationale": rationale})
            if res.get("valid"):
                break
            if not _repair(cons, res.get("errors", [])):
                break
        final = tb.valid_proposal or (tb.proposals[-1] if tb.proposals else None)
        return PlanResult(final["steps"] if final else [], bool(tb.valid_proposal), final["validation"] if final else {},
                          final["rationale"] if final else rationale, self.name, None, len(tb.proposals), trace=tb.trace)


# ------------------------------------------------------------------------------------------------------- Groq
SYSTEM = (
    "You are Oasis's planning agent for a student paying fees in China. You can only PROPOSE a plan; you never move money. "
    "Call read_passport, list_obligations, get_rates and forecast_runway together in one turn, then get_routes / check_corridor if "
    "useful, then propose_plan. A deterministic validator answers with concrete errors; fix them all and re-propose the COMPLETE plan. "
    "Rules: pay every obligation with plan_must_fund=true once, with its exact amount_cny and its own payee_id, on or before its due "
    "date and not before today. CNY arrives on convert date + route days and must be there before it is spent. The student's INR "
    "balance cannot go negative: send at most the INR balance from the student, and put any extra INR in a separate convert step with "
    "remitter 'parent' (needs the parent's consent). At most the SAFE quota of INR may be converted per calendar year (a large amount "
    "must be split across December and January). Keep INR unconverted for pending rate targets. Prefer the cheapest route that arrives "
    "on time and few conversions. Rates are today's quote, never a prediction. Keep every message short.")


def _plan_from_text(text: str) -> dict | None:
    """Pull a {"steps": [...]} object out of a plain-text reply (a model that did not use the tool-call channel)."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    return d if isinstance(d, dict) and isinstance(d.get("steps"), list) else None


def _tool_message(tc_id: str, res: dict) -> dict:
    return {"role": "tool", "tool_call_id": tc_id, "content": compact(res)}


class AgenticPlanner:
    """Groq native tool calling over the same toolbox. Falls back to the deterministic plan, and says so."""
    name = "groq-tools"

    def __init__(self, llm, max_model_calls: int = MAX_MODEL_CALLS, token_cap: int | None = None):
        self.llm = llm
        self.max_model_calls = max_model_calls
        self.token_cap = token_cap       # stop asking the model once this many tokens were spent on this plan

    def plan(self, world, goal: str = "") -> PlanResult:
        tb = PlanningToolbox(world, MAX_ITERATIONS)
        msgs: list[dict] = [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": f"Today is {world.today.isoformat()}. Plan how to pay everything due"
                                                        + (f". Student's goal: {goal}" if goal else ".")}]
        tokens = calls = 0
        model, reason = None, None
        nudged = False
        try:
            while calls < self.max_model_calls and not tb.valid_proposal and len(tb.proposals) < MAX_ITERATIONS:
                if self.token_cap and tokens >= self.token_cap:
                    reason = f"token cap reached ({tokens})"
                    break
                n_err = len(getattr(self.llm, "errors", []))
                try:
                    resp = self.llm.chat_tools(msgs, TOOL_SPECS)
                finally:
                    for er in getattr(self.llm, "errors", [])[n_err:]:
                        tb.trace.append({"type": "model_error", **er})
                calls += 1
                tokens += resp.get("tokens", 0)
                model = resp.get("model") or model
                if resp.get("content"):
                    tb.trace.append({"type": "model_note", "text": resp["content"][:600]})
                tcs = resp.get("tool_calls") or []
                if not tcs:
                    parsed = _plan_from_text(resp.get("content") or "")
                    if parsed is not None:     # some models answer with the JSON instead of a tool call; it is still only a proposal
                        tcs = [{"id": f"text_{calls}", "name": "propose_plan", "arguments": parsed}]
                        tb.trace.append({"type": "model_note", "text": "The model wrote the plan as text; it was parsed as a propose_plan call."})
                msgs.append({"role": "assistant", "content": resp.get("content") or "",
                             **({"tool_calls": [{"id": t["id"], "type": "function",
                                                 "function": {"name": t["name"], "arguments": json.dumps(t["arguments"])}} for t in tcs]}
                                if tcs else {})})
                if not tcs:
                    if nudged:
                        reason = "the model stopped without a valid plan"
                        break
                    nudged = True
                    msgs.append({"role": "user", "content": "Call propose_plan now with the complete plan."})
                    continue
                for t in tcs:
                    args = t["arguments"]
                    if t["name"] == "propose_plan" and isinstance(args.get("steps"), str):
                        try:
                            args = {**args, "steps": json.loads(args["steps"])}
                        except ValueError:
                            pass
                    msgs.append(_tool_message(t["id"], tb.call(t["name"], args)))
        except Exception as e:  # noqa: BLE001 - QuotaExhausted, auth, network: the deterministic plan is the floor
            reason = f"{type(e).__name__}: {str(e)[:200]}"
        if tb.valid_proposal:
            vp = tb.valid_proposal
            return PlanResult(vp["steps"], True, vp["validation"], vp["rationale"] or "", f"groq-tools", model, len(tb.proposals),
                              trace=tb.trace, tokens=tokens, model_calls=calls)
        reason = reason or (f"no valid plan after {len(tb.proposals)} proposal(s)" if tb.proposals else "the model never proposed a plan")
        fb = DeterministicPlanner().plan(world, goal)
        trace = tb.trace + [{"type": "fallback", "reason": reason, "message": "The live model did not produce a valid plan; "
                                                                                "using the deterministic planner's plan."}] + fb.trace
        return PlanResult(fb.steps, fb.valid, fb.validation, fb.rationale, "deterministic (fallback)", model,
                          len(tb.proposals) + fb.iterations, fell_back=True, fallback_reason=reason, trace=trace,
                          tokens=tokens, model_calls=calls)


def make_planner(llm):
    """Live tool-calling planner when the LLM supports it; otherwise the deterministic one (no network)."""
    if hasattr(llm, "chat_tools") and getattr(llm, "name", "") == "groq":
        return AgenticPlanner(llm)
    return DeterministicPlanner()


# ---------------------------------------------------------------------------------------------- plan record
def explain_plan(validation: dict, steps: list[dict]) -> list[str]:
    """'Why this plan', derived from the validator's own numbers, not from model prose."""
    m, why = validation.get("metrics", {}), []
    convs = [s for s in validation.get("schedule", []) if s["action"] == "convert"]
    pays = [s for s in validation.get("schedule", []) if s["action"] == "pay"]
    why.append(f"{m.get('deadlines_met', 0)} of {m.get('obligations', 0)} obligations are paid on or before their due dates.")
    if convs:
        why.append(f"{len(convs)} conversion(s) send INR {m.get('total_send_inr', 0):,.0f} and deliver CNY {m.get('delivered_cny', 0):,.0f}; "
                   f"that is CNY {m.get('saved_vs_bank_cny', 0):,.0f} more than the same INR through a typical bank route (MOCK rates).")
        why.append("Routes: " + "; ".join(sorted({c['route'] for c in convs})) + ". Every route arrives before the payment it funds.")
    else:
        why.append("No conversion is needed: the CNY already held covers every obligation.")
    if len({c["date"][:4] for c in convs}) > 1:
        why.append("Conversions are split across two calendar years so each year stays inside the SAFE facilitation quota.")
    if any(c["remitter"] == "parent" for c in convs):
        why.append("The student's own INR is not enough, so part is proposed as a parent remittance. It needs the parent's consent and counts against the parent's LRS and TCS.")
    if m.get("tcs_inr"):
        why.append(f"TCS of INR {m['tcs_inr']:,.0f} would be collected; it is an advance tax credit, not a fee.")
    if any(w["code"] == "approval_expected" for w in validation.get("warnings", [])):
        why.append("Payments above the Tier-1 limit wait for the student's approval and pass verification, signed intent, policy and the executor.")
    why.append(f"Rates are today's quote ({m.get('rate_basis', 'mock')}); Oasis does not predict exchange rates.")
    return why


def build_record(world, res: PlanResult, goal: str = "") -> dict:
    """Store a plan as a PROPOSAL (status 'proposed'); nothing is executed."""
    pid = f"plan_{len(world.plans) + 1:03d}"
    rec = {"id": pid, "created": world.now_iso(), "goal": goal, "status": "proposed" if res.valid else "invalid",
           "planner": res.planner, "model": res.model, "valid": res.valid, "iterations": res.iterations,
           "fell_back": res.fell_back, "fallback_reason": res.fallback_reason, "tokens": res.tokens,
           "model_calls": res.model_calls, "steps": res.steps, "rationale": res.rationale,
           "why": explain_plan(res.validation, res.steps) if res.validation else [],
           "validation": res.validation, "trace": res.trace, "executed": []}
    world.plans.append(rec)
    world.audit.append("plan_proposed", {"plan_id": pid, "planner": res.planner, "valid": res.valid, "iterations": res.iterations,
                                         "fell_back": res.fell_back, "steps": len(res.steps),
                                         "delivered_cny": (res.validation.get("metrics") or {}).get("delivered_cny")})
    return rec


def propose(world, planner=None, goal: str = "") -> dict:
    planner = planner or make_planner(world.llm)
    return build_record(world, planner.plan(world, goal), goal)
