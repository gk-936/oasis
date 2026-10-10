"""FastAPI backend.  Run:  uvicorn oasis.api.main:app --reload   (from the repo root, PYTHONPATH=.)

State is held in a `Session`. If `OASIS_DB` is a file path (default data/oasis.db) the session is persisted to
SQLite and restored on start; `OASIS_DB=:memory:` keeps everything in memory. The red-team world is a separate,
never-persisted sandbox.
"""
from __future__ import annotations
import json
import re
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import config
from ..agent.i18n import LANGS
from ..agent.llm import GroqLLM, VisionExtractor, VisionUnavailable, explain_template, make_llm
from ..agent.parent import parent_view
from ..agent.pipeline import OasisAgent, Request
from ..agent import plan_exec
from ..agent.planner import AgenticPlanner, DeterministicPlanner, build_record, make_planner
from ..agent.replay import MODES, fixture_info
from ..demo import DemoRunner, new_demo_world
from ..planning import spending
from ..planning.scenarios import SCENARIOS, build_scenario_world
from ..planning.forecast import monthly_burn, runway_months, triggers
from ..planning.routes import last_mile, quote_routes, rank
from ..proof.pack import verify_proof_pack
from ..storage import SqliteStore
from ..chain.anchor import LocalAnchorChain
from ..trust.audit import verify_chain
from ..trust.keystore import fingerprint, load_or_create_signer
from ..world import Features, World

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "eval" / "reports"
MOCK_NOTE = ("MOCK: rates, fees, payment rails, registry identities, wallet spending and balances are simulated "
             "sandbox data. Anchoring uses a local simulated chain, not FISCO BCOS.")

app = FastAPI(title="Oasis API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


class Session:
    """One student's sandbox (plus a separate red-team sandbox), optionally backed by SQLite."""

    def __init__(self, db_path: str | None = None, key_path=None):
        self.db_path = config.DB_PATH if db_path is None else db_path
        self.store = None if self.db_path in ("", ":memory:") else SqliteStore(self.db_path)
        # A persistent session (SQLite file) also gets persistent trust keys, so proof packs verify after a restart and
        # the published fingerprint stays stable. An in-memory session (tests) gets fresh in-memory keys.
        self.signer = load_or_create_signer(key_path) if (self.store or key_path) else None
        self.pending: dict[str, dict] = {}   # pending_id -> {"request","approvals","required","outcome"}
        self.demo: DemoRunner | None = None
        self.redteam_log: list[dict] = []
        self.chat: list[dict] = []
        snap = self.store.load() if self.store else None
        self._build(snap)

    def _build(self, snap: dict | None = None, world: World | None = None) -> None:
        self.world = world or World(Features.full(), make_llm(), store=self.store, autonomy=True, signer=self.signer)
        if snap:
            self.world.restore(snap)
            self.pending = {k: {"request": Request(**v["request"]), "approvals": set(v["approvals"]),
                                "required": v["required"], "outcome": v["outcome"]}
                            for k, v in snap["kv"].get("pending", {}).items()}
        self.agent = OasisAgent(self.world)
        self.redteam_world = World(Features.full(), make_llm(), signer=self.signer)   # separate sandbox ledger for judges
        self.redteam_agent = OasisAgent(self.redteam_world)

    def reset(self) -> None:
        if self.store:
            self.store.clear()
        self.pending, self.demo, self.redteam_log, self.chat = {}, None, [], []
        self._build()
        self.save()

    def start_demo(self, run: str, mode: str = "offline") -> DemoRunner:
        if self.store:
            self.store.clear()
        self.pending, self.redteam_log, self.chat = {}, [], []
        w = new_demo_world(self.store, mode)
        self.demo = DemoRunner(run, w)
        self._build(world=w)
        self.demo.agent = self.agent
        self.save()
        return self.demo

    def trusted_fingerprints(self) -> set[str]:
        """Key fingerprints this server vouches for: its own signing keys. The scripted demo's keys are public (seeded),
        so they are trusted only while the demo world is the active world."""
        return {self.world.trust_fingerprint(), self.redteam_world.trust_fingerprint()}

    def anchor_chains(self, ids: tuple[str, ...] | None = None) -> list:
        return [w.anchor for w in (self.world, self.redteam_world) if isinstance(w.anchor, LocalAnchorChain)]

    def save(self) -> None:
        if not self.store:
            return
        snap = self.world.snapshot()
        snap["kv"]["pending"] = {k: {"request": {"text": v["request"].text, "source": v["request"].source,
                                                 "purpose_hint": v["request"].purpose_hint,
                                                 "remitter": v["request"].remitter, "recurring": v["request"].recurring,
                                                 "tool_poison": v["request"].tool_poison,
                                                 "approvals": list(v["request"].approvals)},
                                     "approvals": sorted(v["approvals"]), "required": v["required"],
                                     "outcome": jsonable_encoder(v["outcome"])}
                                 for k, v in self.pending.items()}
        self.store.save(snap)


S = Session()


def _out(o) -> dict:
    return jsonable_encoder(o.to_dict())


def _store_pending(req: Request, outcome: dict) -> str | None:
    d = outcome.get("decision") or {}
    req_roles = set(d.get("required_approvals") or [])
    if outcome["status"] != "held" or not req_roles or not req_roles <= {"student", "parent"}:
        return None
    pid = f"pend_{len(S.pending)+1:03d}"
    while pid in S.pending:
        pid += "x"
    S.pending[pid] = {"request": req, "approvals": set(req.approvals), "required": sorted(req_roles), "outcome": outcome}
    return pid


# ------------------------------------------------------------------ models
class IntakeIn(BaseModel):
    text: str
    remitter: str = "student"
    source: str = "invoice"


class ChatIn(BaseModel):
    message: str


class ApproveIn(BaseModel):
    pending_id: str
    role: str            # student | parent
    approve: bool = True


class RedTeamIn(BaseModel):
    text: str
    tool_poison: dict | None = None


class DemoIn(BaseModel):
    run: str = "legit"   # legit | attack
    mode: str = "offline"   # offline | live (live = recorded model responses replayed from the fixture; no network)


class RateTargetIn(BaseModel):
    rate: float
    convert_cny: float


class TargetIdIn(BaseModel):
    target_id: str


class TickIn(BaseModel):
    days: int = 1


class SpendSimIn(BaseModel):
    days: int = 21


class SpendAddIn(BaseModel):
    desc: str
    amount_cny: float


class RecoveryIn(BaseModel):
    obligation: str | None = None


class PlanIn(BaseModel):
    goal: str = ""
    scenario: str | None = None      # plan on a throwaway MOCK world from oasis/planning/scenarios.py instead of the session
    live: bool = False               # use the live tool-calling model when one is configured (otherwise deterministic, offline)


class PlanExecIn(BaseModel):
    approvals: list[str] = []        # e.g. ["parent"]: the parent's consent for a parent-remitted conversion


# ------------------------------------------------------------------ state
@app.get("/api/state")
def state():
    w = S.world
    p = w.passport
    quotes = rank(quote_routes(w.rates, 100000, w.today, None, w.day_index))
    burn, basis = monthly_burn(p)
    decoys = w.canaries.decoy_payees if w.canaries else set()
    sp = spending.summarize(p)
    return jsonable_encoder({
        "mock_note": MOCK_NOTE,
        "llm": w.llm.name, "agent_model": config.AGENT_MODEL if w.llm.name == "groq" else None,
        "fallback_model": config.FALLBACK_MODEL if w.llm.name == "groq" else None,
        "persistence": {"enabled": S.store is not None, "path": S.db_path if S.store else None},
        "demo": {"active": S.demo is not None, "run": S.demo.run if S.demo else None, "mode": S.demo.mode if S.demo else None},
        "now": w.now_iso(),
        "passport": {**p.model_dump(), "recipients": {k: v.model_dump() for k, v in p.recipients.items() if k not in decoys}},
        "rate_mid": w.rates.mid(w.day_index),
        "routes": [{"id": q.route.id, "name": q.route.name, "delivered_cny_per_100k_inr": q.delivered_cny,
                    "days": q.arrives_in_days, "reliability": q.route.reliability, "cost_vs_mid_pct": q.cost_vs_mid_pct,
                    "typical_bank": q.route.typical_bank} for q in quotes],
        "last_mile_rent_6000": last_mile(6000),
        "runway_months": runway_months(p, w.rates, w.day_index), "burn": {"monthly_cny": burn, "basis": basis},
        "spending": sp,
        "autonomy": {"rate_now": w.rates.mid(w.day_index), "targets": p.rules.rate_targets,
                     "tier1_auto_convert_cny": p.rules.tier1_auto_convert_cny,
                     "tier1_auto_pay_cny": p.rules.tier1_auto_limit_cny,
                     "recurring": [o.model_dump() for o in p.obligations if o.recurring and o.status in ("pending", "planned")],
                     "log": p.autonomy_log[-20:]},
        "triggers": [t.__dict__ for t in triggers(p, w.rates, w.today, w.day_index)],
        "cards": w.cards[-20:],
        "proofs": list(w.proofs),
        "pending": [{"id": k, "required": v["required"], "approvals": sorted(v["approvals"]),
                     "fields": v["outcome"]["fields"], "card": v["outcome"].get("card")} for k, v in S.pending.items()],
        "security_feed": [{"i": e["i"], "kind": e["kind"], "ts": e["ts"]} for e in w.audit.entries[-30:]],
        "ledger_money_lost": w.ledger.money_lost(),
        "canaries_tripped": bool(w.canaries and w.canaries.tripped),
    })


@app.post("/api/reset")
def reset():
    S.reset()
    return {"ok": True}


# ------------------------------------------------------------------ pipeline
@app.post("/api/intake")
def intake(body: IntakeIn):
    req = Request(body.text, source=body.source, remitter=body.remitter)
    o = _out(S.agent.handle(req))
    o["pending_id"] = _store_pending(req, o)
    S.save()
    return o


@app.post("/api/intake/image")
async def intake_image(file: UploadFile = File(...), remitter: str = "student"):
    """Image intake via the Groq agent model. If the image cannot be read the result is a low-confidence hold
    asking the student to paste the text or confirm the fields; nothing is guessed."""
    data = await file.read()
    try:
        llm = S.world.llm if isinstance(S.world.llm, GroqLLM) else None
        text = VisionExtractor(llm).to_text(data, file.content_type or "image/png")   # image is not stored
    except VisionUnavailable as e:
        req = Request("", source="screenshot", remitter=remitter)
        o = _out(S.agent.handle(req))
        o["message"] = str(e)
        S.save()
        return o
    return intake(IntakeIn(text=text, remitter=remitter, source="screenshot"))


@app.post("/api/approve")
def approve(body: ApproveIn):
    item = S.pending.get(body.pending_id)
    if not item:
        raise HTTPException(404, "unknown pending id")
    if not body.approve:
        S.world.audit.append("declined", {"pending_id": body.pending_id, "role": body.role})
        S.pending.pop(body.pending_id)
        S.save()
        return {"status": "declined"}
    item["approvals"].add(body.role)
    S.world.audit.append("approval", {"pending_id": body.pending_id, "role": body.role})
    missing = set(item["required"]) - item["approvals"]
    if missing:
        S.save()
        return {"status": "waiting", "missing": sorted(missing)}
    req = item["request"]
    req.approvals = tuple(sorted(item["approvals"]))
    o = _out(S.agent.handle(req))
    S.pending.pop(body.pending_id)
    o["pending_id"] = _store_pending(req, o)
    S.save()
    return o


@app.post("/api/recovery/approve")
def recovery_approve(body: RecoveryIn):
    """The 'ask' step after a freeze: the student approves the recovery plan. Nothing is paid here."""
    res = S.agent.approve_recovery(body.obligation)
    S.save()
    return res


@app.get("/api/parent/pending")
def parent_pending(lang: str | None = None):
    p = S.world.passport
    parent = next((a for a in p.approvers if a.role == "parent"), None)
    if lang and lang not in LANGS:
        raise HTTPException(400, f"unsupported language {lang!r}; use one of {sorted(LANGS)}")
    out = []
    for k, v in S.pending.items():
        if "parent" in v["required"]:
            view = parent_view(S.world, v["outcome"]["fields"], lang)
            out.append({"id": k, **view, "approvals": sorted(v["approvals"]), "required": v["required"]})
    return {"parent": parent.model_dump() if parent else None, "language": lang or (parent.language if parent else "en"),
            "available_languages": LANGS, "pending": out}


INVOICE_HINT = re.compile(r"(Payee|Account|Amount|收款人|账号|金额)\s*[:：]", re.I)
TARGET_RE = re.compile(r"convert\s+(?:cny\s*|¥|rmb\s*)?([\d,]+(?:\.\d+)?)[^.\n]*?(?:rate|inr)[^\d]{0,30}?(0\.\d+)", re.I)


@app.post("/api/chat")
def chat(body: ChatIn):
    S.chat.append({"role": "student", "text": body.message})
    if INVOICE_HINT.search(body.message):
        res = intake(IntakeIn(text=body.message))
        reply = (f"I checked it. Status: {res['status']}." +
                 (f" {res['card']['text']}" if res.get("card") else "") +
                 (f" Proof pack {res['proof_id']} is ready." if res.get("proof_id") else ""))
        S.chat.append({"role": "oasis", "text": reply, "outcome": res})
        return {"reply": reply, "outcome": res}
    m = TARGET_RE.search(body.message)
    if m:
        amount, rate = float(m.group(1).replace(",", "")), float(m.group(2))
        t = S.agent.set_rate_target(rate, amount)
        S.save()
        lim = S.world.passport.rules.tier1_auto_convert_cny
        reply = (f"Rate target set: I will watch INR to CNY and, when it reaches {rate:.4f}, convert CNY {amount:,.0f} "
                 + ("on my own (within your Tier-1 limit)." if amount <= lim else f"after you approve it (above your CNY {lim:,.0f} auto limit).")
                 + " I do not predict rates; I only act on your target.")
        S.chat.append({"role": "oasis", "text": reply, "target": t})
        return {"reply": reply, "target": t}
    w = S.world
    p = w.passport
    tr = triggers(p, w.rates, w.today, w.day_index)
    pend = [o for o in p.obligations if o.status != "paid"]
    best = rank(quote_routes(w.rates, 100000, w.today, None, w.day_index))[0]
    reply = (f"You have INR {p.balance('INR'):,.0f} and CNY {p.balance('CNY'):,.0f}. "
             f"Upcoming: " + "; ".join(f"{o.type} CNY {o.amount:,.0f} due {o.due}" for o in pend) + ". "
             f"Runway after obligations: {runway_months(p, w.rates, w.day_index):.1f} months. "
             f"Cheapest on-time route right now: {best.route.name}. "
             + (" Alerts: " + " ".join(t.message for t in tr) if tr else " No alerts.") +
             " Forward me any invoice or message and I'll check it before anything is paid. "
             "You can also say: 'convert 2000 when the rate reaches 0.0855'.")
    S.chat.append({"role": "oasis", "text": reply})
    return {"reply": reply}


# ------------------------------------------------------------------ agentic planning (spec step 2)
def _plan_view(world, rec: dict) -> dict:
    return jsonable_encoder({**rec, "step_status": plan_exec.step_statuses(world, rec)})


@app.get("/api/plan/scenarios")
def plan_scenarios():
    return [{"id": s.id, "title": s.title, "description": s.description, "goal": s.goal, "tests": s.tests} for s in SCENARIOS.values()]


@app.post("/api/plan")
def plan_create(body: PlanIn):
    """The agent builds a plan by calling read-only tools and revising from the validator's errors. It is a PROPOSAL:
    nothing is paid or converted until the student accepts it, and executing it goes through the normal pipeline."""
    live = body.live and isinstance(S.world.llm, GroqLLM)
    if body.scenario:
        if body.scenario not in SCENARIOS:
            raise HTTPException(400, f"unknown scenario {body.scenario!r}; use one of {sorted(SCENARIOS)}")
        w = build_scenario_world(body.scenario, S.world.llm if live else None)
        planner = AgenticPlanner(S.world.llm) if live else DeterministicPlanner()
        rec = build_record(w, planner.plan(w, body.goal or SCENARIOS[body.scenario].goal), body.goal or SCENARIOS[body.scenario].goal)
        rec["scenario"] = body.scenario
        return _plan_view(w, rec)          # scenario worlds are throwaway: not stored, not executable
    planner = AgenticPlanner(S.world.llm) if live else DeterministicPlanner()
    rec = build_record(S.world, planner.plan(S.world, body.goal), body.goal)
    S.save()
    return _plan_view(S.world, rec)


@app.get("/api/plans")
def plans_list():
    return [_plan_view(S.world, r) for r in S.world.plans]


@app.get("/api/plan/{plan_id}")
def plan_get(plan_id: str):
    rec = plan_exec.get_plan(S.world, plan_id)
    if rec is None:
        raise HTTPException(404, "no such plan")
    return _plan_view(S.world, rec)


@app.post("/api/plan/{plan_id}/accept")
def plan_accept(plan_id: str):
    res = plan_exec.accept_plan(S.agent, plan_id)
    if "error" in res and res.get("errors") is None and res["error"] == "no such plan":
        raise HTTPException(404, res["error"])
    S.save()
    return jsonable_encoder(res)


@app.post("/api/plan/{plan_id}/execute")
def plan_execute(plan_id: str, body: PlanExecIn | None = None):
    """Run the accepted plan's steps that are due today. Payments go through the full pipeline; anything that needs
    approval is registered as a pending approval for the student (and parent) exactly like a normal intake."""
    res = plan_exec.execute_due(S.agent, plan_id, tuple((body.approvals if body else []) or []))
    if "error" in res:
        raise HTTPException(409, res["error"])
    pend = []
    for req, held in res.pop("held"):
        pend.append(_store_pending(req, _out(held)))
    res["pending_ids"] = [p for p in pend if p]
    S.save()
    return jsonable_encoder(res)


# ------------------------------------------------------------------ Tier-1 autonomy + spending
@app.post("/api/rate-target")
def rate_target(body: RateTargetIn):
    if body.rate <= 0 or body.convert_cny <= 0:
        raise HTTPException(400, "rate and convert_cny must be positive")
    t = S.agent.set_rate_target(body.rate, body.convert_cny)
    S.save()
    return t


@app.post("/api/rate-target/approve")
def rate_target_approve(body: TargetIdIn):
    res = S.agent.approve_rate_target(body.target_id)
    S.save()
    return jsonable_encoder(res)


@app.post("/api/autonomy/tick")
def autonomy_tick(body: TickIn):
    """Advance the simulated clock and let the agent do its Tier-1 work (rate targets, recurring bills)."""
    days = max(1, min(int(body.days), 60))
    acts = S.agent.run_days(days)
    out = []
    for a in acts:
        req, held = a.pop("held_request", None), a.pop("held_outcome", None)
        if req is not None and held is not None:
            a["pending_id"] = _store_pending(req, _out(held))
        out.append(a)
    S.save()
    return jsonable_encoder({"days": days, "now": S.world.now_iso(), "actions": out})


@app.post("/api/spending/simulate")
def spending_simulate(body: SpendSimIn):
    """Import MOCK wallet spending so the forecast can switch from cold start to the student's own pattern."""
    p = S.world.passport
    start = (max(date.fromisoformat(t["date"]) for t in p.transactions) + timedelta(days=1)
             if p.transactions else S.world.today - timedelta(days=max(1, min(body.days, 90))))
    spending.simulate_spending(p, start, max(1, min(body.days, 90)))
    S.world.audit.append("spending_imported", {"source": "mock", "days": body.days, "transactions": len(p.transactions)})
    S.save()
    return spending.summarize(p)


@app.post("/api/spending/add")
def spending_add(body: SpendAddIn):
    tx = spending.add_transaction(S.world.passport, S.world.today, body.desc, body.amount_cny, "manual")
    S.save()
    return {"transaction": tx, "summary": spending.summarize(S.world.passport)}


# ------------------------------------------------------------------ red team (separate sandbox)
@app.post("/api/redteam")
def redteam(body: RedTeamIn):
    from eval.approver import SimulatedHumans
    w = S.redteam_world
    before = w.ledger.money_lost()
    o = _out(S.redteam_agent.handle(Request(body.text, tool_poison=body.tool_poison), SimulatedHumans()))
    o["money_lost_this_attempt"] = round(w.ledger.money_lost() - before, 2)
    S.redteam_log.append({"text": body.text[:500], "status": o["status"], "lost": o["money_lost_this_attempt"]})
    return o


@app.get("/api/redteam/log")
def redteam_log():
    return {"attempts": S.redteam_log, "total_lost": S.redteam_world.ledger.money_lost()}


# ------------------------------------------------------------------ proof + audit
@app.get("/api/proof/{intent_id}")
def proof(intent_id: str):
    pk = S.world.proofs.get(intent_id) or S.redteam_world.proofs.get(intent_id)
    if not pk:
        raise HTTPException(404, "no such proof pack")
    return pk


def _verify_pinned(pack: dict) -> dict:
    """Verify against THIS server's pinned key fingerprint and its (simulated) chain; any other keys fail key_pinned."""
    best = None
    for chain in S.anchor_chains() or [None]:
        res = verify_proof_pack(pack, S.trusted_fingerprints(), chain)
        if best is None or (res["ok"] and not best["ok"]):
            best = res
    res = best
    res["pinned_fingerprint"] = S.world.trust_fingerprint()
    return res


@app.get("/api/trust/fingerprint")
def trust_fingerprint():
    """The fingerprint (sha256 over the canonical public keys) that verifiers must pin. Public keys only."""
    w = S.world
    return {"fingerprint": w.trust_fingerprint(), "key_id": w.signer.key_id, "public_keys": w.signer.public_keys(),
            "algorithms": sorted(w.signer.public_keys()), "persistent": S.signer is not None and not w.deterministic,
            "demo_keys": bool(w.deterministic),
            "note": "Pin this fingerprint out of band. A proof pack embeds its own public keys, so a pack signed with any "
                    "other keys fails the key_pinned check. Demo keys are seeded and public: never trust them for real use."}


@app.get("/api/proof/{intent_id}/verify")
def proof_verify(intent_id: str):
    return _verify_pinned(proof(intent_id))


@app.post("/api/proof/verify")
def proof_verify_upload(pack: dict):
    return _verify_pinned(pack)


@app.get("/api/audit")
def audit():
    return {"entries": S.world.audit.entries}


@app.get("/api/audit/verify")
def audit_verify():
    r = verify_chain(S.world.audit.entries)
    return {**r.__dict__, "ok": r.ok, "head": S.world.audit.head()}


# ------------------------------------------------------------------ evaluation + demo
@app.get("/api/benchmark")
def benchmark():
    out = {}
    for name in ("benchmark", "simulation", "planning"):
        f = REPORTS / f"{name}.json"
        out[name] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
        md = REPORTS / f"{name}.md"
        out[f"{name}_md"] = md.read_text(encoding="utf-8") if md.exists() else None
    if out["benchmark"]:
        out["benchmark"].pop("results", None)
    if out["planning"]:       # keep the payload small: summaries only (the markdown report has the per-scenario table)
        out["planning"] = {k: {"summary": v["summary"], "date": v["date"], "planner": v["planner"], "model": v.get("model")}
                           for k, v in out["planning"].items() if isinstance(v, dict)}
    return out


@app.post("/api/demo/start")
def demo_start(body: DemoIn):
    """Reset to the scripted demo world (fixed seed, fixed MOCK data) and return the step list. `mode` "offline" (default)
    uses the offline LLM; "live" replays recorded qwen/qwen3.8-27b responses from the fixture (no network)."""
    if body.run not in DemoRunner.RUNS:
        raise HTTPException(400, f"run must be one of {DemoRunner.RUNS}")
    if body.mode not in MODES:
        raise HTTPException(400, f"mode must be one of {MODES}")
    d = S.start_demo(body.run, body.mode)
    return jsonable_encoder({"run": d.run, "steps": d.titles, "total": len(d.titles), "done": d.done,
                             "llm": S.world.llm.name, "seed": 7, "mode": d.mode,
                             "model": config.AGENT_MODEL if d.mode == "live" else None,
                             "fixture": fixture_info() if d.mode == "live" else None})


@app.post("/api/demo/next")
def demo_next():
    if not S.demo:
        raise HTTPException(409, "no demo running; POST /api/demo/start first")
    res = S.demo.next()
    S.save()
    return jsonable_encoder(res)


@app.get("/api/demo/state")
def demo_state():
    if not S.demo:
        return {"active": False}
    return jsonable_encoder({"active": True, "run": S.demo.run, "mode": S.demo.mode, "index": S.demo.index, "total": len(S.demo.titles),
                             "done": S.demo.done, "steps": S.demo.titles, "results": S.demo.results})


@app.post("/api/demo/run")
def demo_run(body: DemoIn):
    """Play a whole scripted demo run in one call (same result every time, no network)."""
    demo_start(body)
    res = S.demo.run_all()
    S.save()
    return jsonable_encoder(res)


@app.post("/api/demo/reset")
def demo_reset():
    """Back to a clean (non-demo) sandbox; also wipes the SQLite state."""
    S.reset()
    return {"ok": True}


@app.get("/api/explain/savings")
def savings():
    convs = [e["data"] for e in S.world.audit.entries if e["kind"] == "conversion"]
    tot = round(sum(c["saved_cny"] for c in convs), 2)
    return {"conversions": convs, "total_saved_cny": tot,
            "text": explain_template("savings", {"saved_cny": tot, "saved_pct": convs[-1]["saved_pct"] if convs else 0})}


DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
