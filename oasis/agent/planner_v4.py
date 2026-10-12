"""Planner format v4 ('constrained JSON', exploratory): one JSON object, generated under schema-constrained decoding.

The model receives the system prompt, the deterministic facts sheet (`oasis/planning/calc.py::facts_sheet`) and a compact
route table, and must answer with ONE JSON object whose shape is fixed by a JSON schema (Ollama's `format`): a short
`calculation` note, the `steps` (convert / pay) and a short `rationale`. The shape can never be malformed; whether the plan
is CORRECT is decided only by the existing deterministic validator. On errors the model is shown the validator's errors
with their `fix` hints (the v3 presentation) and may revise, at most `MAX_REVISIONS` times.

Honesty rules (tested): the harness never applies a fix, never edits a step and never computes an INR amount. There is no
`size_conversion` tool; the route table gives the model the numbers (days, fixed fee, marginal CNY per INR) to do its own
arithmetic. The deterministic fallback is the same as for the tool-calling planner and is recorded as a fallback.
"""
from __future__ import annotations
import json
import time

from ..mock.rates import ROUTES
from ..planning import calc
from ..planning.tools import PlanningToolbox, compact, present
from ..planning.validator import required_obligations

MAX_REVISIONS = 3
MAX_PROPOSALS = 1 + MAX_REVISIONS
MAX_OUTPUT_TOKENS = 1800

SYSTEM_V4 = (
    "You are Oasis's planning agent for a student paying fees in China. You only PROPOSE a plan; you never move money. "
    "Answer with ONE JSON object: calculation (short working), steps, rationale.\n"
    "Rules:\n"
    "1. Pay every obligation in 'obligations' exactly once: a pay step with its obligation_id, payee_id and amount_cny copied exactly, "
    "on a date that is today or later and not after its due date.\n"
    "2. CNY comes from the CNY balance and from conversions. A conversion (convert step) sent on date D by route R arrives on D + days(R) "
    "and the CNY must be in the account on the pay date, so pay on or after the arrival date and convert early enough (D + days <= pay date).\n"
    "3. Size each conversion yourself: send_inr = ceil(fixed_fee_inr + (target_cny + 1) / cny_per_inr) with the route's own numbers "
    "(the +1 is headroom for rounding). target_cny is the CNY still missing (obligations total minus the CNY balance, cny_shortfall). "
    "Never send more INR than this formula gives. Prefer the cheapest route (highest cny_per_inr) that still arrives in time, and as few conversions as possible. "
    "Do not use the 'bank' route unless nothing else arrives in time.\n"
    "4. The student's INR balance cannot go negative, and rate_target_reserve_inr must stay unconverted: the student's convert steps may send at most "
    "student_spendable_inr IN TOTAL. If the formula needs more INR than that, the student sends student_spendable_inr and a separate convert step with "
    "remitter 'parent' sends the rest (the parent's consent is needed).\n"
    "5. At most the SAFE quota may be converted per calendar year (safe.left_by_year, all remitters together): convert the rest on January 1 of the "
    "next year or later, still arriving before the payment it funds.\n"
    "6. If a validator error comes back, fix every error (apply each 'fix' if it is correct), change nothing else and return the COMPLETE corrected plan.\n"
    "Worked example with made-up numbers (not your task): short 10,000 CNY, route X has fixed_fee_inr 500 and cny_per_inr 0.07, so send_inr = ceil(500 + 10001/0.07) = "
    "143,371. student_spendable_inr is 100,000, so the student sends 100,000 and the parent sends the remaining 43,371 in a second convert step; then pay after arrival.")


def route_table(world) -> list[dict]:
    """Per-route numbers the model needs for its own arithmetic (no INR amounts for any particular plan)."""
    mid = world.rates.mid(world.day_index)
    return [{"id": r.id, "days": r.days, "fixed_fee_inr": r.fixed_fee_inr,
             "cny_per_inr": round(mid * (1 - r.rate_spread) * (1 - r.pct_fee), 6), **({"bank": True} if r.typical_bank else {})}
            for r in ROUTES]


def build_schema(world) -> dict:
    """JSON schema for the answer. Ids are enums taken from the world (so a hallucinated id cannot be generated); amounts, dates,
    routes, remitters and ordering are free for the model to choose."""
    need = required_obligations(world.passport)
    date_s = {"type": "string", "pattern": r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$"}
    convert = {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["convert"]}, "date": date_s,
        "route_id": {"type": "string", "enum": [r.id for r in ROUTES]},
        "remitter": {"type": "string", "enum": ["student", "parent"]}, "send_inr": {"type": "integer"}},
        "required": ["action", "date", "route_id", "remitter", "send_inr"]}
    pay = {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["pay"]}, "date": date_s,
        "obligation_id": {"type": "string", "enum": [o.id for o in need]},
        "payee_id": {"type": "string", "enum": sorted({o.payee_id for o in need})}, "amount_cny": {"type": "number"}},
        "required": ["action", "date", "obligation_id", "payee_id", "amount_cny"]}
    return {"type": "object", "properties": {
        "calculation": {"type": "string", "maxLength": 700},
        "steps": {"type": "array", "minItems": 1, "maxItems": 14, "items": {"anyOf": [convert, pay]}},
        "rationale": {"type": "string", "maxLength": 300}},
        "required": ["calculation", "steps", "rationale"]}


# facts_sheet fields that already contain an INR amount sized by the harness; v4 must not hand the model a ready-made answer.
SIZED_BY_HARNESS = ("inr_needed_est", "inr_short_est")


def facts(world) -> dict:
    return {k: v for k, v in calc.facts_sheet(world).items() if k not in SIZED_BY_HARNESS}


def user_message(world, goal: str = "") -> str:
    return (f"Today is {world.today.isoformat()}. Plan how to pay everything due" + (f". Student's goal: {goal}" if goal else ".")
            + "\nFACTS: " + compact(facts(world), 6000) + "\nROUTES: " + compact(route_table(world), 2000))


class ConstrainedPlanner:
    """Planner format v4. `llm` is an `OllamaLLM` (anything with `generate_json(messages, schema, seed=...)`)."""
    name = "ollama-constrained"

    def __init__(self, llm, token_cap: int | None = None, fmt: str = "v4", seed: int | None = None):
        self.llm, self.fmt, self.token_cap = llm, fmt, token_cap
        self.seed = getattr(llm, "seed", 0) if seed is None else seed
        self.system = SYSTEM_V4
        self.last_info: dict = {}

    def _ask(self, msgs, schema, seed, trace) -> dict:
        n_err = len(getattr(self.llm, "errors", []))
        try:
            return self.llm.generate_json(msgs, schema, seed=seed, max_tokens=MAX_OUTPUT_TOKENS)
        finally:
            for er in getattr(self.llm, "errors", [])[n_err:]:
                trace.append({"type": "model_error", **er})

    def plan(self, world, goal: str = ""):
        from .planner import DeterministicPlanner, PlanResult
        tb = PlanningToolbox(world, MAX_PROPOSALS, "v3")      # "v3" only switches on the `fix` hints in the verdict shown to the model
        schema = build_schema(world)
        msgs = [{"role": "system", "content": self.system}, {"role": "user", "content": user_message(world, goal)}]
        tokens = calls = 0
        model, reason = None, None
        t0 = time.monotonic()
        try:
            while calls < MAX_PROPOSALS and not tb.valid_proposal:
                if self.token_cap and tokens >= self.token_cap:
                    reason = f"token cap reached ({tokens})"
                    break
                resp = self._ask(msgs, schema, self.seed + calls, tb.trace)
                calls += 1
                tokens += resp.get("tokens", 0)
                model = resp.get("model") or model
                obj = resp.get("json")
                if not obj or not isinstance(obj.get("steps"), list):
                    tb.trace.append({"type": "model_note", "text": "unparseable or truncated JSON (done_reason=%s)" % (resp.get("stats") or {}).get("done_reason")})
                    msgs += [{"role": "assistant", "content": resp.get("content", "")[:1500]},
                             {"role": "user", "content": "That answer was cut off. Return the complete plan again as one JSON object, with a shorter calculation."}]
                    continue
                tb.trace.append({"type": "model_note", "text": ("calculation: " + str(obj.get("calculation", "")))[:600]})
                res = tb.call("propose_plan", {"steps": obj["steps"], "rationale": str(obj.get("rationale", ""))[:300]})
                if res.get("valid"):
                    break
                msgs += [{"role": "assistant", "content": resp["content"]},
                         {"role": "user", "content": "The validator rejected this plan: " + compact(present("propose_plan", res, "v3"), 5000)
                          + "\nReturn the complete corrected plan as one JSON object."}]
        except Exception as e:  # noqa: BLE001 - Ollama not running, model missing, timeout: the deterministic plan is the floor
            reason = f"{type(e).__name__}: {str(e)[:200]}"
        self.last_info = {"seconds_llm": round(time.monotonic() - t0, 2)}
        if tb.valid_proposal:
            vp = tb.valid_proposal
            return PlanResult(vp["steps"], True, vp["validation"], vp["rationale"] or "", self.name, model, len(tb.proposals),
                              trace=tb.trace, tokens=tokens, model_calls=calls)
        reason = reason or (f"no valid plan after {len(tb.proposals)} proposal(s)" if tb.proposals else "the model never proposed a plan")
        fb = DeterministicPlanner().plan(world, goal)
        trace = tb.trace + [{"type": "fallback", "reason": reason, "message": "The live model did not produce a valid plan; "
                                                                                "using the deterministic planner's plan."}] + fb.trace
        return PlanResult(fb.steps, fb.valid, fb.validation, fb.rationale, "deterministic (fallback)", model,
                          len(tb.proposals) + fb.iterations, fell_back=True, fallback_reason=reason, trace=trace,
                          tokens=tokens, model_calls=calls)

    def sample(self, world, goal: str = "", seed: int = 0) -> dict:
        """ONE independent first proposal (no revision) for generate-and-verify. Returns the validator's verdict on it."""
        tb = PlanningToolbox(world, 1, "v3")
        msgs = [{"role": "system", "content": self.system}, {"role": "user", "content": user_message(world, goal)}]
        t0 = time.monotonic()
        resp = self.llm.generate_json(msgs, build_schema(world), seed=seed, max_tokens=MAX_OUTPUT_TOKENS)
        obj = resp.get("json")
        out = {"tokens": resp.get("tokens", 0), "seconds": round(time.monotonic() - t0, 2), "valid": False, "errors": {}, "parsed": bool(obj and isinstance(obj.get("steps"), list))}
        if out["parsed"]:
            tb.call("propose_plan", {"steps": obj["steps"], "rationale": str(obj.get("rationale", ""))[:300]})
            v = tb.proposals[0]["validation"]
            out["valid"] = bool(v["valid"])
            for e in v["errors"]:
                out["errors"][e["code"]] = out["errors"].get(e["code"], 0) + 1
        return out
