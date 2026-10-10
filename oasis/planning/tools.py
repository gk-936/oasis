"""The planner's tool protocol (JSON-schema function tools) and the toolbox that serves them.

Every tool is read-only or proposal-only. The model can look at the Passport, the rates, the routes and the corridor
rules, and it can PROPOSE a plan; `propose_plan` runs the deterministic validator and returns its verdict. No tool
moves money, signs anything or changes a Passport. Executing an accepted plan is a separate step that goes through
verification, signed intents, policy and the executor (`oasis/agent/plan_exec.py`).
"""
from __future__ import annotations
import json
from datetime import date

from ..market import provenance
from ..mock.rates import ROUTES, delivered_amount
from ..trust import corridor
from . import forecast
from .routes import quote_routes
from .validator import (BANK, lrs_limit_inr, required_obligations, safe_quota_inr, validate_plan)

READ_TOOLS = ("read_passport", "list_obligations", "get_rates", "get_routes", "check_corridor", "forecast_runway")

_DATE = {"type": "string", "description": "ISO date YYYY-MM-DD"}
def _fn(name, description, properties=None, required=None):
    params = {"type": "object", "properties": properties or {}}
    if required:
        params["required"] = required
    return {"type": "function", "function": {"name": name, "description": description, "parameters": params}}


TOOL_SPECS = [
    _fn("read_passport", "Read-only. Balances (INR, CNY), SAFE quota used per year, INR sent per remitter this financial year, "
                         "rate targets, income not yet arrived."),
    _fn("list_obligations", "Read-only. Obligations with id, payee_id, exact amount_cny, due date and plan_must_fund."),
    _fn("get_rates", "Read-only. Today's INR to CNY mid-market rate (real ECB reference rate when OASIS_RATES=live, otherwise a mock; see the note and 'rates' fields) and each route's fees (route spreads and fees are always mock). A quote, not a forecast."),
    _fn("get_routes", "Read-only. For send_inr: CNY delivered per route, days, on_time for the due date, saving vs the bank route.",
        {"send_inr": {"type": "number"}, "due": {"type": "string", "description": "YYYY-MM-DD, optional"}}, ["send_inr"]),
    _fn("check_corridor", "Read-only. LRS, TCS and SAFE-quota findings for converting amount_inr.",
        {"amount_inr": {"type": "number"}, "purpose": {"type": "string"}, "remitter": {"type": "string", "description": "student or parent"}},
        ["amount_inr", "purpose"]),
    _fn("forecast_runway", "Read-only. Months of money left after obligations, monthly burn, active triggers."),
    _fn("propose_plan", "Proposal only, moves no money. Submit the COMPLETE plan; a validator returns valid or concrete errors. Steps: "
                        "convert {action:'convert',date,send_inr,route_id,remitter:'student'|'parent'} and pay "
                        "{action:'pay',date,obligation_id,payee_id,amount_cny}. route_id is one of " + ", ".join(r.id for r in ROUTES) + ".",
        {"steps": {"type": "array", "items": {"type": "object", "properties": {
            "action": {"type": "string"}, "date": {"type": "string"}, "send_inr": {"type": "number"}, "route_id": {"type": "string"},
            "remitter": {"type": "string"}, "obligation_id": {"type": "string"}, "payee_id": {"type": "string"},
            "amount_cny": {"type": "number"}}, "required": ["action", "date"]}},
         "rationale": {"type": "string", "description": "At most 40 words: why this plan"}}, ["steps", "rationale"]),
]


class PlanningToolbox:
    """Serves the tools against one World. Keeps the proposals and validator verdicts for the trace."""

    def __init__(self, world, max_iterations: int = 4):
        self.w = world
        self.max_iterations = max_iterations
        self.trace: list[dict] = []
        self.proposals: list[dict] = []         # [{steps, rationale, validation}]
        self.valid_proposal: dict | None = None

    # -- dispatch ---------------------------------------------------------------------------------
    def call(self, name: str, args: dict | None = None) -> dict:
        args = args if isinstance(args, dict) else {}
        fn = getattr(self, f"tool_{name}", None) if name in [t["function"]["name"] for t in TOOL_SPECS] else None
        if fn is None:
            res = {"error": f"unknown tool {name!r}", "tools": [t["function"]["name"] for t in TOOL_SPECS]}
        else:
            try:
                res = fn(**args)
            except TypeError as e:
                res = {"error": f"bad arguments for {name}: {e}"}
            except Exception as e:  # noqa: BLE001 - a tool error is data for the model, never a crash
                res = {"error": f"{name} failed: {e}"}
        if name != "propose_plan":
            self.trace.append({"type": "tool_call", "tool": name, "args": args, "result": res})
        return res

    # -- read tools -------------------------------------------------------------------------------
    def tool_read_passport(self) -> dict:
        w, p = self.w, self.w.passport
        return {"today": w.today.isoformat(), "student": p.student.name,
                "balances": {b.currency: b.amount for b in p.balances}, "funding_source": p.funding_source,
                "monthly_budget_cny": p.student.monthly_budget_cny, "remitted_inr_fy": p.remitted_inr_fy,
                "safe_used_inr_by_year": p.safe_used_inr, "safe_quota_inr_per_year": round(safe_quota_inr(), 2),
                "lrs_limit_inr_per_remitter": round(lrs_limit_inr(), 2),
                "tier1_auto_limit_cny": p.rules.tier1_auto_limit_cny,
                "rate_targets": [t for t in p.rules.rate_targets if t.get("status") in ("watching", "awaiting_approval")],
                "income_not_arrived": [i for i in p.expected_income if not i.get("received")],
                "approvers": [a.role for a in p.approvers]}

    def tool_list_obligations(self) -> dict:
        p = self.w.passport
        need = {o.id for o in required_obligations(p)}
        return {"obligations": [{"id": o.id, "type": o.type, "payee_id": o.payee_id, "amount_cny": o.amount, "due": o.due,
                                 "status": o.status, "recurring": o.recurring, "plan_must_fund": o.id in need}
                                for o in p.obligations if o.status != "paid"]}

    def tool_get_rates(self) -> dict:
        w = self.w
        mid = w.rates.mid(w.day_index)
        prov = provenance(w.rates, w.day_index)
        return {"as_of": w.today.isoformat(), "mid_cny_per_inr": mid,
                "note": (f"{'live' if prov['mode'] == 'live' else 'mock'} mid-market quote at today's rate for the whole horizon; "
                         "route spreads and fees are mock; Oasis does not predict rates"),
                "rates": prov,
                "routes": [{"id": r.id, "name": r.name, "fixed_fee_inr": r.fixed_fee_inr, "pct_fee": r.pct_fee,
                            "spread": r.rate_spread, "days": r.days, "reliability": r.reliability,
                            "typical_bank": r.typical_bank} for r in ROUTES]}

    def tool_get_routes(self, send_inr: float, due: str | None = None) -> dict:
        w = self.w
        send = float(send_inr)
        if send <= 0:
            return {"error": "send_inr must be positive"}
        d = date.fromisoformat(due) if due else None
        qs = quote_routes(w.rates, send, w.today, d, w.day_index)
        bank = next(q for q in qs if q.route.typical_bank)
        return {"send_inr": send, "due": due, "routes": sorted(
            ({"route_id": q.route.id, "name": q.route.name, "delivered_cny": q.delivered_cny, "days": q.arrives_in_days,
              "on_time": q.on_time, "vs_bank_cny": round(q.delivered_cny - bank.delivered_cny, 2),
              "typical_bank": q.route.typical_bank} for q in qs), key=lambda r: -r["delivered_cny"])}

    def tool_check_corridor(self, amount_inr: float, purpose: str, remitter: str = "student") -> dict:
        w, p = self.w, self.w.passport
        pt = {"tuition": "university", "rent": "landlord", "deposit": "landlord", "family_support": "family"}.get(purpose, "merchant")
        res = corridor.check(p, payee_type=pt, purpose=purpose, amount_cny=0, amount_inr=float(amount_inr), remitter=remitter)
        y = str(w.today.year)
        return {"remitter": remitter, "findings": [{"rule": f.rule, "severity": f.severity, "message": f.message}
                                                   for f in res.findings if f.rule != "purpose_code"],
                "remitter_inr_this_fy": p.remitted_inr_fy.get(remitter, 0.0),
                "tcs_threshold_inr": corridor.load_rules()["rules"]["tcs_threshold_inr"]["value"],
                "safe_quota_inr_per_year": round(safe_quota_inr(), 2),
                "safe_remaining_inr_this_calendar_year": round(max(0.0, safe_quota_inr() - p.safe_used_inr.get(y, 0.0)), 2),
                "note": "The SAFE quota is counted per calendar year across all conversions; the validator enforces it."}

    def tool_forecast_runway(self) -> dict:
        w, p = self.w, self.w.passport
        burn, basis = forecast.monthly_burn(p)
        return {"runway_months_after_obligations": forecast.runway_months(p, w.rates, w.day_index),
                "monthly_burn_cny": burn, "burn_basis": basis, "runway_alert_months": p.rules.runway_alert_months,
                "triggers": [{"kind": t.kind, "message": t.message} for t in forecast.triggers(p, w.rates, w.today, w.day_index)]}

    # -- proposal-only ----------------------------------------------------------------------------
    def tool_propose_plan(self, steps=None, rationale: str = "") -> dict:
        n = len(self.proposals) + 1
        if n > self.max_iterations:
            res = {"valid": False, "errors": [{"code": "iteration_limit", "message": f"At most {self.max_iterations} proposals are allowed."}],
                   "warnings": [], "metrics": {}, "schedule": []}
            self.trace.append({"type": "proposal", "iteration": n, "steps": steps, "rationale": rationale, "validation": res})
            return {"valid": False, "errors": res["errors"], "iteration": n}
        v = validate_plan(self.w, steps).to_dict()
        prop = {"iteration": n, "steps": steps, "rationale": rationale, "validation": v}
        self.proposals.append(prop)
        self.trace.append({"type": "proposal", **prop})
        if v["valid"] and self.valid_proposal is None:
            self.valid_proposal = prop
        slim = lambda e: {k: e[k] for k in ("code", "message", "hint", "step") if k in e}
        out = {"valid": v["valid"], "iteration": n, "errors": [slim(e) for e in v["errors"]]}
        if v["valid"]:
            seen, ws = set(), []
            for x in v["warnings"]:
                if x["code"] not in seen and x["code"] != "approval_expected":
                    seen.add(x["code"])
                    ws.append({"code": x["code"], "message": x["message"][:160]})
            m = v["metrics"]
            out["warnings"] = ws
            out["summary"] = {k: m[k] for k in ("total_send_inr", "delivered_cny", "saved_vs_bank_cny", "tcs_inr", "deadlines_met", "obligations")}
        else:
            out["instruction"] = "Fix every error; call propose_plan again with the complete corrected plan."
        return out


def compact(res, limit: int = 3500) -> str:
    """Tool result as compact JSON for the model (bounded so a long run cannot blow the token budget)."""
    s = json.dumps(res, separators=(",", ":"), default=str)
    return s if len(s) <= limit else s[:limit] + '..."truncated"'
