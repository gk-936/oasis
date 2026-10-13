"""Foreign-currency payment plans: the planner for obligations owed in USD or EUR, over the generic corridors.

The INR -> CNY planner (validator.py, planner.py) is unchanged and ignores obligations that are not in CNY. This module is its
counterpart for an obligation such as "US tuition, USD 5,000". The LLM (or the deterministic planner) can only PROPOSE; this
validator recomputes every number from the Passport, the corridor engine (oasis/corridors) and the sourced rules, so a
model never decides an amount, a fee or a limit.

Plan steps:
  convert  {"action":"convert","date":"YYYY-MM-DD","corridor":"INR-USD","route_id":"route_inr_usd_2","send":N,"remitter":"student"|"parent"}
  pay      {"action":"pay","date":"YYYY-MM-DD","obligation_id":"obl_...","payee_id":"payee_...","amount":N}   (N in the obligation's currency)

This module moves no money. An accepted FX plan is executed by agent/plan_exec.py through the same trust path as a CNY plan: the
registry's account, the student's signature on the exact payment, the signed intent and the executor (agent/fx_exec.py). Route prices are public-range estimates and
each corridor rule carries its source and status (docs/corridor-research.md). Worst-case intermediary deductions are assumed
on every conversion, so a valid plan has margin. Rates are today's quote, never a forecast.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from ..corridors import core as cor
from ..market import provenance
from ..mock import fx
from ..trust import corridor as legacy_corridor
from .validator import Issue, Validation, _lakh, _parse_date, _tcs

AMOUNT_TOL = 0.5            # in the obligation's currency
REMITTERS = ("student", "parent")
PAY_MARGIN_DAYS = 2
ASSUMED_PENALTY = 0.005     # risk adjustment: prefer a price with evidence unless the unsourced one is clearly cheaper
FOREIGN = ("USD", "EUR")    # currencies an obligation may be owed in for an FX plan
SRC_ORDER = ("INR", "CNY", "EUR", "USD")


def foreign_obligations(passport) -> list:
    """Open, non-recurring obligations owed in a currency other than CNY (the CNY planner ignores these)."""
    return sorted((o for o in passport.obligations if o.currency != "CNY" and not o.recurring
                   and o.status in ("pending", "planned", "partially_paid")), key=lambda o: o.due)


def uses_safe_quota(world, steps) -> bool:
    """Does this plan's CNY outflow count against the SAFE USD 50,000 convenience quota? Overseas tuition may be bought outside it
    (SAFE Tianjin bureau, 2025-07-14); any other purpose uses it."""
    for s in steps or []:
        if isinstance(s, dict) and s.get("action") == "pay":
            ob = world.passport.obligation(str(s.get("obligation_id")))
            if ob is not None and ob.type != "tuition":
                return True
    return False


def has_foreign(world) -> bool:
    return bool(foreign_obligations(world.passport))


def _table(world) -> dict[str, float]:
    return fx.table_for(world.rates, world.day_index)


def _rate_basis(world) -> str:
    pv = provenance(world.rates, world.day_index)
    src = f"live ECB reference rates ({pv['source']}, as of {pv['as_of']})" if pv["mode"] == "live" else "the frozen mock snapshot"
    return f"today's {src}; route prices are public-range estimates (a quote, not a forecast)"


def usable_corridors(dst: str) -> list[str]:
    """Corridors that deliver `dst`, home currency first. INR-CNY is excluded: it is the original planner's job."""
    out = [cid for cid in cor.corridor_ids() if cor.corridor(cid)["dst"] == dst]
    return sorted(out, key=lambda c: SRC_ORDER.index(cor.corridor(c)["src"]) if cor.corridor(c)["src"] in SRC_ORDER else 9)


# --------------------------------------------------------------------------------------------------------- validator
def validate_fx_plan(world, steps) -> Validation:
    p = world.passport
    today = world.today
    table = _table(world)
    errors: list[Issue] = []
    warns: list[Issue] = []
    if not isinstance(steps, list) or not steps:
        errors.append(Issue("bad_step", "A plan needs a non-empty list of steps."))
        return Validation(False, [e.to_dict() for e in errors], [], {}, [])

    parsed: list[dict] = []
    paid_ids: dict[str, int] = {}
    for i, s in enumerate(steps):
        if not isinstance(s, dict) or s.get("action") not in ("convert", "pay"):
            errors.append(Issue("bad_step", "Each step must be an object with action 'convert' or 'pay'.", i))
            continue
        d = _parse_date(s.get("date"))
        if d is None:
            errors.append(Issue("bad_date", f"Step date {s.get('date')!r} is not a YYYY-MM-DD date.", i))
            continue
        if d < today:
            errors.append(Issue("date_in_past", f"Step is dated {d}, before today ({today}).", i, f"Use {today} or later."))
            continue
        if s["action"] == "convert":
            cid = s.get("corridor")
            try:
                c = cor.corridor(str(cid))
            except cor.CorridorError:
                errors.append(Issue("unknown_corridor", f"Unknown corridor {cid!r}.", i, "Use one of: " + ", ".join(cor.corridor_ids())))
                continue
            if c.get("engine") == "legacy":
                errors.append(Issue("unknown_corridor", "INR-CNY is planned by the CNY planner, not the foreign-currency planner.", i))
                continue
            route = next((r for r in cor.routes_for(str(cid), table, today) if r.id == s.get("route_id")), None)
            if route is None:
                errors.append(Issue("unknown_route", f"Unknown route {s.get('route_id')!r} for {cid}.", i,
                                    "Use a route_id from fx_facts: " + ", ".join(r.id for r in cor.routes_for(str(cid), table))))
                continue
            try:
                send = float(s.get("send"))
            except (TypeError, ValueError):
                send = 0.0
            if send <= 0 or send != send or send > cor.MAX_AMOUNT:
                errors.append(Issue("bad_amount", "send must be a positive number.", i))
                continue
            rem = s.get("remitter") or "student"
            if rem not in REMITTERS:
                errors.append(Issue("bad_step", f"remitter must be one of {REMITTERS}.", i))
                continue
            if rem == "parent" and c["src"] != "INR":
                errors.append(Issue("bad_step", "Only an INR conversion can be remitted by the parent.", i))
                continue
            parsed.append({"i": i, "action": "convert", "date": d, "cid": str(cid), "c": c, "route": route, "send": round(send, 2), "remitter": rem})
        else:
            ob = p.obligation(str(s.get("obligation_id")))
            if ob is None:
                errors.append(Issue("unknown_obligation", f"No obligation {s.get('obligation_id')!r} in the Passport.", i, "Use ids from fx_facts."))
                continue
            if ob.currency == "CNY":
                errors.append(Issue("not_foreign", f"{ob.id} is owed in CNY; the CNY planner handles it.", i))
                continue
            if ob.status == "paid":
                errors.append(Issue("already_paid", f"{ob.id} is already paid.", i))
                continue
            if ob.status == "frozen":
                errors.append(Issue("obligation_frozen", f"{ob.id} is frozen after a security stop.", i))
                continue
            if ob.id in paid_ids:
                errors.append(Issue("duplicate_payment", f"{ob.id} is paid twice (steps {paid_ids[ob.id]} and {i}).", i))
                continue
            paid_ids[ob.id] = i
            pid = s.get("payee_id")
            if pid not in p.recipients and world.registry.lookup(str(pid)) is None:
                errors.append(Issue("unknown_payee", f"Payee {pid!r} is not in the Passport or the verified registry.", i, f"{ob.id} is payable to {ob.payee_id}."))
                continue
            if pid != ob.payee_id:
                errors.append(Issue("payee_mismatch", f"{ob.id} is owed to {ob.payee_id}, not {pid}.", i, f"Set payee_id to {ob.payee_id}."))
                continue
            try:
                amt = float(s.get("amount"))
            except (TypeError, ValueError):
                amt = -1.0
            if abs(amt - ob.remaining) > AMOUNT_TOL:
                errors.append(Issue("amount_mismatch", f"{ob.id} still has {ob.currency} {ob.remaining:,.2f} to pay; the step pays {amt:,.2f}.", i,
                                    f"Set amount to {ob.remaining}."))
                continue
            if d > date.fromisoformat(ob.due):
                errors.append(Issue("late_payment", f"{ob.id} is due {ob.due}; the step pays on {d}.", i, f"Pay on or before {ob.due}."))
                continue
            parsed.append({"i": i, "action": "pay", "date": d, "ob": ob, "amount": ob.remaining})

    for ob in foreign_obligations(p):
        if ob.id not in paid_ids:
            errors.append(Issue("obligation_unfunded", f"{ob.id} ({ob.type}, {ob.currency} {ob.amount:,.0f}, due {ob.due}) has no pay step.", None,
                                f"Add a pay step for {ob.id} on or before {ob.due}."))

    # chronological cash simulation, one balance per currency; a conversion lands in the receiving currency on arrival at the
    # WORST-CASE delivered amount (after the largest intermediary deduction)
    bal = {c: p.balance(c) for c in fx.CURRENCIES}
    used_by = {r: p.remitted_inr_fy.get(r, 0.0) for r in REMITTERS}
    cn_year: dict[str, float] = {y: float(v) for y, v in p.cn_outbound_usd.items()}     # earlier years' and months' use counts too
    converts: list[dict] = []
    sched: list[dict] = []
    pay_ok: dict[int, bool] = {}
    tot = {"send_usd": 0.0, "delivered_usd": 0.0, "bank_usd": 0.0, "tcs_inr": 0.0}
    rules_in = legacy_corridor.load_rules()
    seen_findings: set[str] = set()
    events = sorted(parsed, key=lambda e: (e["date"], 0 if e["action"] == "convert" else 1, e["i"]))
    quota_applies = any(x["ob"].type != "tuition" for x in parsed if x["action"] == "pay")
    for e in events:
        i = e["i"]
        if e["action"] == "convert":
            c, route, send, rem, d = e["c"], e["route"], e["send"], e["remitter"], e["date"]
            src, dst = c["src"], c["dst"]
            mid = fx.mid(src, dst, table)
            deliv = max(0.0, cor.delivered(send, route, mid) - route.deduction_worst_dst)
            if rem == "student":
                if send > bal[src] + 0.005:
                    errors.append(Issue("insufficient_funds", f"Step {i}: the student has {src} {bal[src]:,.0f} on {d}; the conversion sends {src} {send:,.0f}.", i,
                                        f"Short by {src} {send - bal[src]:,.0f}. Reduce it" + (" or use a parent-remitted conversion (remitter 'parent', needs the parent's consent)." if src == "INR" else "."),
                                        {"short": round(send - bal[src], 2), "currency": src}))
                bal[src] -= send
            usd = send / table[src]
            res = cor.check(e["cid"], send, "tuition", table)
            if src == "INR":
                lrs = legacy_corridor.load_rules()["rules"]["lrs_annual_limit_usd"]["value"] * table["INR"]      # the table's USD/INR, not the fixed 88.0
                if used_by[rem] + send > lrs + 0.005:
                    errors.append(Issue("lrs_exceeded", f"Step {i}: the {rem} remitter's LRS limit (INR {lrs:,.0f}) would be exceeded this financial year.", i,
                                        "Use the other remitter or reduce the amount.", {"used_inr": round(used_by[rem], 2), "limit_inr": round(lrs, 2)}))
                tr = legacy_corridor.tcs_rate(p, "tuition", rules_in)
                tcs = _tcs(used_by[rem], send, rules_in, p.funding_source == "education_loan", tr["rate"])
                if tcs > 0:
                    tot["tcs_inr"] += tcs
                    warns.append(Issue("tcs", f"Step {i}: TCS of INR {tcs:,.0f} would be collected from the {rem} remitter ({tr['rate']:.0%} above "
                                       f"{_lakh(tr['threshold_inr'])}; recoverable as a tax credit, not a fee).{legacy_corridor.tcs_caveat(tr)}", i,
                                       "", {"tcs_inr": tcs, "rate_status": tr["status"]}))
                used_by[rem] += send
            elif src == "CNY" and not quota_applies:
                if "safe_tuition_documents" not in seen_findings:
                    seen_findings.add("safe_tuition_documents")
                    warns.append(Issue("safe_tuition_documents", f"Step {i}: overseas tuition can be bought outside the USD 50,000 SAFE quota with your ID and the "
                                       "admission notice or the school's fee notice; confirm with the bank. [confirmed-primary, SAFE Tianjin bureau, 2025-07-14]", i))
            elif src == "CNY":
                y = str(d.year)
                before = cn_year.get(y, 0.0)
                cap = rules_in["rules"]["safe_quota_usd"]["value"]
                if before + usd > cap + 0.005:
                    errors.append(Issue("annual_limit_exceeded", f"Step {i}: conversions out of CNY dated in {y} would total about USD {before + usd:,.0f}, above the "
                                        f"USD {cap:,.0f} SAFE annual quota.", i, "Stage the rest in the next calendar year or prepare school-fee documents; confirm with the bank.",
                                        {"rule": "safe_annual_quota"}))
                cn_year[y] = before + usd
            if rem == "parent":
                warns.append(Issue("parent_remitter", f"Step {i}: {src} {send:,.0f} would be sent by the parent; it needs the parent's consent and counts against the parent's limits.", i))
            for f in res["findings"]:
                if f["severity"] == "info" and f["rule"] not in seen_findings:
                    seen_findings.add(f["rule"])
                    warns.append(Issue("rule_note", f"{f['message']} [{f['status']}]", i, "", {"rule": f["rule"], "status": f["status"], "source": f["source"]}))
            if route.stale:
                warns.append(Issue("price_stale", f"Step {i}: the {route.name} price is {route.price_age_days} days old (retrieved {route.price_retrieved}); re-check it before relying on it.", i))
            if route.price_status != "sourced":
                warns.append(Issue("price_estimate", f"Step {i}: the {route.name} price is {'an assumed placeholder' if route.price_status == 'assumed' else 'a public-range estimate'}, not a live quote.", i))
            bank = next((r for r in cor.routes_for(e["cid"], table) if r.typical_bank), None)
            if bank:
                tot["bank_usd"] += max(0.0, cor.delivered(send, bank, mid) - bank.deduction_worst_dst) * (table["USD"] / table[dst])
            tot["send_usd"] += usd
            tot["delivered_usd"] += deliv * (table["USD"] / table[dst])
            arrival = d + timedelta(days=route.days)
            converts.append({**e, "arrival": arrival, "delivered": deliv, "dst": dst})
            sched.append({"step": i, "date": d.isoformat(), "action": "convert", "corridor": e["cid"], "send": send, "currency": src,
                          "route": route.name, "route_id": route.id, "remitter": rem, "delivered_worst_case": round(deliv, 2),
                          "delivered_currency": dst, "arrives": arrival.isoformat(), "price_status": route.price_status})
        else:
            ob, d = e["ob"], e["date"]
            cur = ob.currency
            arrived = sum(c["delivered"] for c in converts if c["dst"] == cur and c["arrival"] <= d)
            spent = sum(x["amount"] for x in events if x["action"] == "pay" and x is not e and x["ob"].currency == cur and (x["date"], x["i"]) < (d, i))
            avail = p.balance(cur) + arrived - spent
            if avail + AMOUNT_TOL < ob.remaining:
                late = [c for c in converts if c["dst"] == cur and c["arrival"] > d]
                if late and avail + sum(c["delivered"] for c in late) + AMOUNT_TOL >= ob.remaining:
                    errors.append(Issue("route_too_slow", f"Step {i}: {cur} {ob.remaining:,.0f} is paid on {d} but the conversion that funds it arrives on "
                                        f"{min(c['arrival'] for c in late)}, after the payment date.", i, "Convert earlier or use a faster route (see days in fx_facts)."))
                else:
                    errors.append(Issue("insufficient_dst", f"Step {i}: only {cur} {avail:,.0f} will be in the account on {d}; {ob.id} needs {cur} {ob.remaining:,.0f}.", i,
                                        f"Short by {cur} {ob.remaining - avail:,.0f}: add or enlarge a conversion arriving on or before {d}.",
                                        {"short": round(ob.remaining - avail, 2), "currency": cur}))
                pay_ok[i] = False
            else:
                pay_ok[i] = True
            sched.append({"step": i, "date": d.isoformat(), "action": "pay", "obligation_id": ob.id, "payee_id": ob.payee_id,
                          "amount": ob.remaining, "currency": cur, "due": ob.due})

    for c in converts:
        later = [e["date"] for e in events if e["action"] == "pay" and e["ob"].currency == c["dst"] and e["date"] >= c["date"]]
        deadline = min(later) if later else None
        mid = fx.mid(c["c"]["src"], c["dst"], table)
        cand = [r for r in cor.routes_for(c["cid"], table) if deadline is None or c["date"] + timedelta(days=r.days) <= deadline]
        if cand:
            best = max(cand, key=lambda r: cor.delivered(c["send"], r, mid) - r.deduction_worst_dst)
            gain = (cor.delivered(c["send"], best, mid) - best.deduction_worst_dst) - c["delivered"]
            if gain > 0.002 * max(c["delivered"], 1) and gain > 1:
                warns.append(Issue("route_not_cheapest", f"Step {c['i']}: {best.name} would deliver {c['dst']} {gain:,.0f} more and still arrive on time.", c["i"], "",
                                   {"better_route_id": best.id, "extra": round(gain, 2)}))
    req = foreign_obligations(p)
    met = sum(1 for o in req if o.id in paid_ids and pay_ok.get(paid_ids[o.id], False))
    metrics = {
        "conversions": len(converts), "total_send_usd_equivalent": round(tot["send_usd"], 2),
        "delivered_worst_case_usd_equivalent": round(tot["delivered_usd"], 2),
        "saved_vs_bank_usd_equivalent": round(tot["delivered_usd"] - tot["bank_usd"], 2) if tot["bank_usd"] else 0.0,
        "tcs_inr": round(tot["tcs_inr"], 2), "obligations": len(req), "deadlines_met": met,
        "final_balances": {c: round(v, 2) for c, v in bal.items() if v or c in ("INR", "CNY")}, "rate_basis": _rate_basis(world),
    }
    sched.sort(key=lambda s: (s["date"], 0 if s["action"] == "convert" else 1, s["step"]))
    return Validation(not errors, [e.to_dict() for e in errors], [w.to_dict() for w in warns], metrics, sched)


# ----------------------------------------------------------------------------------------------------------- toolbox
class FxToolbox:
    """Same call/trace/proposal protocol as PlanningToolbox, with three tools: fx_facts, fx_size_conversion, propose_plan."""
    READ = ("fx_facts", "fx_size_conversion")

    def __init__(self, world, max_iterations: int = 4, fmt: str = "v2"):
        self.w = world
        self.fmt = fmt
        self.max_iterations = max_iterations
        self.trace: list[dict] = []
        self.proposals: list[dict] = []
        self.valid_proposal: dict | None = None

    def call(self, name: str, args: dict | None = None) -> dict:
        args = args if isinstance(args, dict) else {}
        fn = getattr(self, f"tool_{name}", None) if name in FX_TOOL_NAMES else None
        if fn is None:
            res = {"error": f"unknown tool {name!r}", "tools": list(FX_TOOL_NAMES)}
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

    def tool_fx_facts(self) -> dict:
        w, p = self.w, self.w.passport
        t = _table(w)
        obs = foreign_obligations(p)
        dsts = sorted({o.currency for o in obs})
        corridors = []
        for dst in dsts:
            for cid in usable_corridors(dst):
                c = cor.corridor(cid)
                corridors.append({"corridor": cid, "from": c["src"], "to": dst, "mid": round(fx.mid(c["src"], dst, t), 6),
                                  "student_balance": round(p.balance(c["src"]), 2),
                                  "routes": [{"route_id": r.id, "name": r.name, "days": r.days, "price_status": r.price_status,
                                              **({"bank": True} if r.typical_bank else {})} for r in cor.routes_for(cid, t)]})
        need = {}
        for o in obs:
            need[o.currency] = need.get(o.currency, 0.0) + o.remaining
        return {"today": w.today.isoformat(), "obligations": [{"id": o.id, "type": o.type, "payee_id": o.payee_id, "amount": o.remaining,
                                                              "currency": o.currency, "due": o.due} for o in obs],
                "balances": {c: round(p.balance(c), 2) for c in fx.CURRENCIES if p.balance(c)},
                "shortfall": {c: round(max(0.0, need[c] - p.balance(c)), 2) for c in need},
                "remitted_inr_fy": p.remitted_inr_fy, "corridors": corridors,
                "note": "Worst-case intermediary deductions are included in size_conversion."}

    def tool_fx_size_conversion(self, target: float, corridor: str, route_id: str, convert_date: str, due: str | None = None) -> dict:
        w = self.w
        t = _table(w)
        c = cor.corridor(corridor)
        route = next((r for r in cor.routes_for(corridor, t) if r.id == route_id), None)
        if route is None:
            return {"error": f"unknown route {route_id!r} for {corridor}"}
        mid = fx.mid(c["src"], c["dst"], t)
        send = math.ceil(cor.send_needed(float(target), route, mid))
        d = date.fromisoformat(convert_date)
        arrival = d + timedelta(days=route.days)
        out = {"corridor": corridor, "route_id": route_id, "send": send, "currency": c["src"], "arrives": arrival.isoformat(),
               "delivered_worst_case": round(max(0.0, cor.delivered(send, route, mid) - route.deduction_worst_dst), 2),
               "price_status": route.price_status}
        if due:
            out["on_time"] = arrival <= date.fromisoformat(due)
        alt = cor.compare(corridor, float(target), t, (date.fromisoformat(due) - d).days if due else None)
        if alt["best"] and alt["best"] != route_id:
            b = next(o for o in alt["options"] if o["route_id"] == alt["best"])
            out["cheaper_route"] = {"route_id": b["route_id"], "send": math.ceil(b["send"])}
        return out

    def tool_propose_plan(self, steps=None, rationale: str = "") -> dict:
        n = len(self.proposals) + 1
        if n > self.max_iterations:
            res = {"valid": False, "errors": [{"code": "iteration_limit", "message": f"At most {self.max_iterations} proposals are allowed."}],
                   "warnings": [], "metrics": {}, "schedule": []}
            self.trace.append({"type": "proposal", "iteration": n, "steps": steps, "rationale": rationale, "validation": res})
            return {"valid": False, "errors": res["errors"], "iteration": n}
        v = validate_fx_plan(self.w, steps).to_dict()
        prop = {"iteration": n, "steps": steps, "rationale": rationale, "validation": v}
        self.proposals.append(prop)
        self.trace.append({"type": "proposal", **prop})
        if v["valid"] and self.valid_proposal is None:
            self.valid_proposal = prop
        slim = lambda e: {k: e[k] for k in ("code", "message", "hint", "step") if k in e}
        out = {"valid": v["valid"], "iteration": n, "errors": [slim(e) for e in v["errors"]]}
        if v["valid"]:
            m = v["metrics"]
            out["warnings"] = [{"code": x["code"], "message": x["message"][:160]} for x in v["warnings"] if x["code"] in ("tcs", "price_estimate")][:3]
            out["summary"] = {k: m[k] for k in ("total_send_usd_equivalent", "delivered_worst_case_usd_equivalent", "tcs_inr", "deadlines_met", "obligations")}
        else:
            out["instruction"] = "Fix every error; call propose_plan again with the complete corrected plan."
        return out


def _fn(name, description, properties=None, required=None):
    params = {"type": "object", "properties": properties or {}}
    if required:
        params["required"] = required
    return {"type": "function", "function": {"name": name, "description": description, "parameters": params}}


FX_TOOL_SPECS = [
    _fn("fx_facts", "Read-only. Foreign-currency obligations (exact amount, currency, payee_id, due), balances, shortfall per currency, "
                    "and the corridors/routes that deliver each currency (route ids, days, price_status)."),
    _fn("fx_size_conversion", "Read-only calculator. Exact whole-unit send for a corridor and route so the recipient gets `target` even after the "
                              "worst-case intermediary deduction; arrival, on_time and a cheaper_route if one exists. Use its send exactly.",
        {"target": {"type": "number"}, "corridor": {"type": "string"}, "route_id": {"type": "string"}, "convert_date": {"type": "string"},
         "due": {"type": "string"}}, ["target", "corridor", "route_id", "convert_date"]),
    _fn("propose_plan", "Proposal only, moves no money. Submit the COMPLETE plan. Steps: convert {action:'convert',date,corridor,route_id,send,remitter:'student'|'parent'} "
                        "and pay {action:'pay',date,obligation_id,payee_id,amount}. amount is in the obligation's own currency.",
        {"steps": {"type": "array", "items": {"type": "object", "properties": {
            "action": {"type": "string"}, "date": {"type": "string"}, "corridor": {"type": "string"}, "route_id": {"type": "string"},
            "send": {"type": "number"}, "remitter": {"type": "string"}, "obligation_id": {"type": "string"}, "payee_id": {"type": "string"},
            "amount": {"type": "number"}}, "required": ["action", "date"]}},
         "rationale": {"type": "string", "description": "At most 40 words: why this plan"}}, ["steps", "rationale"]),
]
FX_TOOL_NAMES = tuple(t["function"]["name"] for t in FX_TOOL_SPECS)

FX_SYSTEM = (
    "You are Oasis's planning agent for a student who owes money in a foreign currency (USD or EUR). You only PROPOSE a plan; you never move money.\n"
    "1. Call fx_facts first. Pay every obligation in it exactly once, copying its id, payee_id and amount exactly, in its own currency, on or before its due date and not before today.\n"
    "2. For every conversion call fx_size_conversion(target, corridor, route_id, convert_date, due) and use its send exactly. Never compute amounts, fees or rounding yourself. target is the foreign amount that conversion must deliver (use shortfall). Use only corridor and route ids from fx_facts.\n"
    "3. Money arrives on convert date + route days and must be in the account on the pay date. Prefer the corridor whose source balance covers the send; the student's balance cannot go negative.\n"
    "4. Propose the complete plan once with propose_plan. If it returns errors, change only what each error says and re-propose the complete plan. Keep every message short.")


# -------------------------------------------------------------------------------------------------- deterministic planner
def draft_fx(world, tb: FxToolbox, facts: dict, cons: dict) -> tuple[list[dict], str]:
    today = date.fromisoformat(facts["today"])
    p = world.passport
    t = _table(world)
    steps: list[dict] = []
    notes: list[str] = []
    arrivals: dict[str, list[tuple[date, float]]] = {}
    by_cur: dict[str, list[dict]] = {}
    for o in facts["obligations"]:
        by_cur.setdefault(o["currency"], []).append(o)
    for cur, obs in by_cur.items():
        obs.sort(key=lambda o: o["due"])
        short = facts["shortfall"].get(cur, 0.0)
        if short <= 0.005:
            continue
        due = date.fromisoformat(obs[0]["due"])
        days = max((due - today).days - 1, 0)
        best = None
        for cid in usable_corridors(cur):
            src = cor.corridor(cid)["src"]
            r = cor.compare(cid, short, t, days)
            # an assumed (unsourced) price must beat a sourced or estimated one by more than ASSUMED_PENALTY to be chosen
            ok = [o for o in r["options"] if o["on_time"] and o["meets_target"]]
            opt = min(ok, key=lambda o: o["send"] * (1 + ASSUMED_PENALTY if o["price_status"] == "assumed" else 1), default=None)
            if opt is None:
                continue
            send = math.ceil(opt["send"])
            enough = send <= p.balance(src) + 0.005
            usd = send / t[src]
            key = (not enough, (src != "INR") if not enough else False, usd)   # short everywhere: the parent can top up INR, nothing else
            if best is None or key < best[0]:
                best = (key, cid, src, opt, send, enough)
        if best is None:
            notes.append(f"No corridor can deliver {cur} {short:,.0f} before {due}; start earlier or ask the university for an extension.")
            continue
        _, cid, src, opt, send, enough = best
        tb.call("fx_size_conversion", {"target": round(short, 2), "corridor": cid, "route_id": opt["route_id"], "convert_date": today.isoformat(), "due": due.isoformat()})
        rem = "student"
        if not enough and src == "INR" and cons.get("use_parent"):
            rem = "parent"
            notes.append(f"The student's {src} balance does not cover {src} {send:,.0f}; the conversion is proposed as a parent remittance, which needs the parent's consent.")
        steps.append({"action": "convert", "date": today.isoformat(), "corridor": cid, "route_id": opt["route_id"], "send": float(send), "remitter": rem})
        arrivals.setdefault(cur, []).append((today + timedelta(days=opt["arrives_in_days"]), short))
        notes.append(f"{cur} {short:,.0f} via {cid} on {opt['route']} ({opt['price_status']} price).")
    for cur, obs in by_cur.items():
        cum = 0.0
        held = facts["balances"].get(cur, 0.0)
        for o in obs:
            cum += o["amount"]
            due = date.fromisoformat(o["due"])
            ready = today if held >= cum else None
            running = held
            for d, c in sorted(arrivals.get(cur, [])):
                running += c
                if ready is None and running >= cum:
                    ready = d
            pay = min(max(today, due - timedelta(days=PAY_MARGIN_DAYS), ready or due), due)
            steps.append({"action": "pay", "date": pay.isoformat(), "obligation_id": o["id"], "payee_id": o["payee_id"], "amount": o["amount"]})
    steps.sort(key=lambda s: (s["date"], 0 if s["action"] == "convert" else 1))
    n_conv = sum(1 for s in steps if s["action"] == "convert")
    return steps, (f"Pay {sum(len(v) for v in by_cur.values())} foreign-currency obligation(s) {PAY_MARGIN_DAYS} days before the due date; "
                   + (f"{n_conv} conversion(s) on the cheapest on-time route. " if n_conv else "the foreign currency already held covers everything. ") + " ".join(notes)).strip()


def repair_fx(cons: dict, errors: list[dict]) -> bool:
    changed = False
    for e in errors:
        if e["code"] == "insufficient_funds" and not cons.get("use_parent"):
            cons["use_parent"] = changed = True
    return changed
