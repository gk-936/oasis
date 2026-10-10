"""FastAPI backend.  Run:  uvicorn oasis.api.main:app --reload   (from the repo root, PYTHONPATH=.)

State is held in a `Session`. If `OASIS_DB` is a file path (default data/oasis.db) the session is persisted to
SQLite (encrypted at rest, see storage.py) and restored on start; `OASIS_DB=:memory:` keeps everything in memory. The
red-team world is a separate, never-persisted sandbox.

Access control (see auth.py): every endpoint except health, the trust fingerprint, proof verification and login needs a
session token; each state-changing endpoint names the roles allowed to call it (least privilege):

    student  intake, chat, approve (as student), recovery, plans, rate targets, autonomy, spending, demo, reset
    parent   approve (as parent), plan-conversion consent, the parent's own pending list
    judge    red-team console and read-only views (state, audit, proofs, benchmark)

Approvals are Ed25519 signatures over the exact payment draft, made with the approver's device key (the private key is
generated and kept in the approver's browser); the role of the SESSION decides whose registered key is checked.
Unauthenticated -> 401, wrong role -> 403.
"""
from __future__ import annotations
import hashlib
import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request as HttpRequest, Response, UploadFile
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
from ..market import provenance
from ..planning import spending
from ..planning.scenarios import SCENARIOS, build_scenario_world
from ..planning.forecast import monthly_burn, runway_months, triggers
from ..planning.routes import last_mile, quote_routes, rank
from ..proof.pack import verify_proof_pack
from ..storage import SqliteStore
from ..chain.anchor import Anchor, LocalAnchorChain
from ..trust.approvals import ApproverRegistry
from ..trust.audit import verify_chain
from ..trust.keyfile import default_session_secret_path, load_or_create_secret
from ..trust.keystore import fingerprint, load_or_create_signer
from ..world import Features, World
from .auth import COOKIE, ROLES, Auth, Principal
from .ratelimit import RateLimiter

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "eval" / "reports"
MOCK_NOTE = ("MOCK: rates, fees, payment rails, registry identities, wallet spending and balances are simulated "
             "sandbox data. Anchoring uses a local simulated chain unless OASIS_ANCHOR=fisco, which uses a real FISCO BCOS chain running locally (4 nodes, one host).")

REDTEAM_MAX_TEXT = 4000          # bytes of attack text per attempt
REDTEAM_MAX_POISON = 400         # bytes of poisoned-tool-output JSON per attempt
REDTEAM_PER_MINUTE = 20          # attempts per client per minute
LOGIN_FAILS_PER_MINUTE = 10

app = FastAPI(title="Oasis API", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class Session:
    """One student's sandbox (plus a separate red-team sandbox), optionally backed by SQLite."""

    def __init__(self, db_path: str | None = None, key_path=None, data_key_path=None, attempts_path=None):
        self.db_path = config.DB_PATH if db_path is None else db_path
        # With an explicit trust-key path (tests) the other key files live next to it, never in the real data/keys.
        kdir = Path(key_path).parent if key_path else None
        self.store = None if self.db_path in ("", ":memory:") else SqliteStore(
            self.db_path, key_path=data_key_path or (kdir / "data_key.json" if kdir else None))
        persistent = bool(self.store or key_path)
        self.auth = Auth(secret=load_or_create_secret(kdir / "session_secret.json" if kdir else default_session_secret_path())
                         if persistent else None)
        # A persistent session (SQLite file) also gets persistent trust keys, so proof packs verify after a restart and
        # the published fingerprint stays stable. An in-memory session (tests) gets fresh in-memory keys.
        self.signer = load_or_create_signer(key_path) if persistent else None
        self.approvers = ApproverRegistry()      # public keys of the real approvers' devices; private keys stay in browsers
        self.attempts_path = Path(attempts_path) if attempts_path else config.DATA_DIR / "redteam_attempts.jsonl"
        self.redteam_limiter = RateLimiter(REDTEAM_PER_MINUTE, 60.0)
        self.login_limiter = RateLimiter(LOGIN_FAILS_PER_MINUTE, 60.0)
        self.pending: dict[str, dict] = {}   # pending_id -> {"request","signed","required","outcome"}
        self.demo: DemoRunner | None = None
        self.redteam_log: list[dict] = []
        self.chat: list[dict] = []
        snap = self.store.load() if self.store else None
        if snap:
            self.approvers.load(snap["kv"].get("approvers", []))
        self._build(snap)

    def _build(self, snap: dict | None = None, world: World | None = None) -> None:
        self.world = world or World(Features.full(), make_llm(), store=self.store, autonomy=True, signer=self.signer,
                                    approvers=self.approvers, sim_devices=False)    # real humans only: no simulated devices
        if snap:
            self.world.restore(snap)
            self.pending = {k: {"request": _request_from(v["request"]), "signed": dict(v.get("signed", {})),
                                "required": v["required"], "outcome": v["outcome"]}
                            for k, v in snap["kv"].get("pending", {}).items()}
        self.agent = OasisAgent(self.world)
        self.redteam_world = World(Features.full(), make_llm(), signer=self.signer, rates_mode="mock")   # separate sandbox ledger for judges
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
        w = new_demo_world(self.store, mode)      # its own registry with seeded SIMULATED approver devices
        self.demo = DemoRunner(run, w)
        self._build(world=w)
        self.demo.agent = self.agent
        self.save()
        return self.demo

    def trusted_fingerprints(self) -> set[str]:
        """Key fingerprints this server vouches for: its own signing keys. The scripted demo's keys are public (seeded),
        so they are trusted only while the demo world is the active world."""
        return {self.world.trust_fingerprint(), self.redteam_world.trust_fingerprint()}

    def pinned_approver_keys(self) -> set[str]:
        """Approver device-key ids this server vouches for (registered real devices + the sandbox worlds' simulated ones)."""
        return (self.approvers.pinned_key_ids() | self.world.approvers.pinned_key_ids()
                | self.redteam_world.approvers.pinned_key_ids())

    def anchor_chains(self, ids: tuple[str, ...] | None = None) -> list:
        return [w.anchor for w in (self.world, self.redteam_world) if isinstance(w.anchor, Anchor)]

    def save(self) -> None:
        if not self.store:
            return
        snap = self.world.snapshot()
        snap["kv"]["approvers"] = self.approvers.public_view()
        snap["kv"]["pending"] = {k: {"request": _request_to(v["request"]), "signed": v["signed"],
                                     "required": v["required"], "outcome": jsonable_encoder(v["outcome"])}
                                 for k, v in self.pending.items()}
        self.store.save(snap)


def _request_to(r: Request) -> dict:
    return {"text": r.text, "source": r.source, "purpose_hint": r.purpose_hint, "remitter": r.remitter,
            "recurring": r.recurring, "tool_poison": r.tool_poison, "draft": r.draft,
            "signed_approvals": list(r.signed_approvals)}


def _request_from(d: dict) -> Request:
    return Request(d["text"], source=d["source"], purpose_hint=d.get("purpose_hint"), remitter=d["remitter"],
                   recurring=d.get("recurring", False), tool_poison=d.get("tool_poison"), draft=d.get("draft"),
                   signed_approvals=tuple(d.get("signed_approvals", [])))


S = Session()


def _out(o) -> dict:
    return jsonable_encoder(o.to_dict())


# ------------------------------------------------------------------ access control
def _client(request: HttpRequest) -> str:
    return request.client.host if request.client else "unknown"


def _principal(request: HttpRequest) -> Principal | None:
    tok = request.cookies.get(COOKIE)
    if not tok:
        h = request.headers.get("authorization", "")
        tok = h[7:] if h.lower().startswith("bearer ") else None
    return S.auth.verify(tok)


def require(*roles: str):
    """Dependency: 401 without a valid session, 403 when the session's role may not call this endpoint."""
    def dep(request: HttpRequest) -> Principal:
        p = _principal(request)
        if p is None:
            raise HTTPException(401, "login required", headers={"WWW-Authenticate": "Bearer"})
        if p.role not in roles:
            raise HTTPException(403, f"the {p.role} role may not do this (allowed: {', '.join(roles)})")
        return p
    return dep


ANY = require(*ROLES)
STUDENT = require("student")
PARENT = require("parent")
JUDGE = require("judge")
STUDENT_PARENT = require("student", "parent")
STUDENT_JUDGE = require("student", "judge")               # read-only views of the student's data
VIEWERS = require("student", "parent", "judge")


def _pending_view(k: str, v: dict) -> dict:
    d = (v["outcome"].get("draft") or {})
    return {"id": k, "required": v["required"], "approvals": sorted(v["signed"]),
            "signed_by": {r: rec["key_id"] for r, rec in v["signed"].items()},
            "fields": v["outcome"]["fields"], "card": v["outcome"].get("card"),
            "draft": {kk: d.get(kk) for kk in ("payee_id", "account_ref", "amount", "currency", "purpose", "route_id",
                                                "not_after", "nonce", "canonical", "draft_hash")} if d else None}


def _store_pending(req: Request, outcome: dict) -> str | None:
    d = outcome.get("decision") or {}
    req_roles = set(d.get("required_approvals") or [])
    if outcome["status"] != "held" or not req_roles or not req_roles <= {"student", "parent"} or not outcome.get("draft"):
        return None
    pid = f"pend_{secrets.token_hex(4)}"     # unique, never reused: a stale button can never hit a newer payment
    dr = outcome["draft"]
    req.draft = {"nonce": dr["nonce"], "not_after": dr["not_after"]}     # approvers sign THIS draft; the re-run reuses it
    S.pending[pid] = {"request": req, "signed": {a["role"]: a for a in req.signed_approvals}, "required": sorted(req_roles),
                      "outcome": outcome}
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
    approve: bool = True
    signature: str | None = None    # base64 Ed25519 signature over approval_message(role, draft_hash); required to approve
    key_id: str | None = None       # the device key that signed (checked against the role's active key)


class LoginIn(BaseModel):
    role: str
    passcode: str


class DeviceIn(BaseModel):
    public_key: str                 # base64 Ed25519 public key; the private key never leaves the browser


class ConsentIn(BaseModel):
    step: int
    signature: str


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


# ------------------------------------------------------------------ public + auth
@app.get("/api/health")
def health():
    return {"ok": True, "service": "oasis"}


@app.get("/api/auth/config")
def auth_config():
    """What the login screen needs. Public. Never returns a passcode."""
    return {"roles": list(ROLES), "demo_passcodes_in_use": S.auth.demo_defaults,
            "note": "Demo passcodes are documented in the README and are PUBLIC: set OASIS_PASS_* for a real deployment."}


@app.post("/api/auth/login")
def login(body: LoginIn, request: HttpRequest, response: Response, return_token: bool = False):
    key = f"login:{_client(request)}"
    if S.login_limiter.blocked(key):                      # only FAILED logins count toward the limit
        raise HTTPException(429, "too many failed logins; wait a minute", headers={"Retry-After": str(S.login_limiter.retry_after(key))})
    res = S.auth.login(body.role, body.passcode)
    if res is None:
        S.login_limiter.record(key)
        raise HTTPException(401, "wrong role or passcode")
    token, p = res
    response.set_cookie(COOKIE, token, max_age=S.auth.ttl_s, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", path="/")
    out = {"role": p.role, "expires_at": datetime.fromtimestamp(p.exp, timezone.utc).isoformat(timespec="seconds")}
    if return_token:           # for scripts/CLI that cannot keep a cookie jar; the browser UI never asks for it
        out["token"] = token
    return out


@app.post("/api/auth/logout")
def logout(response: Response, p: Principal = Depends(ANY)):
    S.auth.revoke(p.jti)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(p: Principal = Depends(ANY)):
    out = {"role": p.role, "expires_at": datetime.fromtimestamp(p.exp, timezone.utc).isoformat(timespec="seconds")}
    if p.role in ("student", "parent"):
        k = S.approvers.active(p.role)
        out["device_key"] = {"key_id": k["key_id"], "public_key": k["public_key"]} if k else None
    return out


# ------------------------------------------------------------------ device keys (signed approvals)
@app.post("/api/device/register")
def device_register(body: DeviceIn, p: Principal = Depends(STUDENT_PARENT)):
    """Register (or rotate to) the Ed25519 public key of THIS role's device. The private key never reaches the server."""
    try:
        rec = S.approvers.register(p.role, body.public_key)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"bad public key: {e}")
    S.world.audit.append("device_registered", {"role": p.role, "key_id": rec["key_id"]})
    S.save()
    return {"role": p.role, "key_id": rec["key_id"], "active": True}


@app.get("/api/approvers")
def approvers(p: Principal = Depends(ANY)):
    return {"keys": [{k: v for k, v in rec.items()} for rec in S.approvers.public_view()]}


# ------------------------------------------------------------------ state
@app.get("/api/state")
def state(p: Principal = Depends(VIEWERS)):
    w = S.world
    if p.role == "parent":      # least privilege: the parent sees only what concerns them
        return jsonable_encoder({
            "mock_note": MOCK_NOTE, "role": "parent", "now": w.now_iso(),
            "persistence": {"enabled": S.store is not None, "path": None},
            "proofs": _parent_proofs(),
            "pending": [_pending_view(k, v) for k, v in S.pending.items() if "parent" in v["required"]]})
    p_ = w.passport
    quotes = rank(quote_routes(w.rates, 100000, w.today, None, w.day_index))
    burn, basis = monthly_burn(p_)
    decoys = w.canaries.decoy_payees if w.canaries else set()
    sp = spending.summarize(p_)
    return jsonable_encoder({
        "mock_note": MOCK_NOTE, "role": p.role,
        "llm": w.llm.name, "agent_model": config.AGENT_MODEL if w.llm.name == "groq" else None,
        "fallback_model": config.FALLBACK_MODEL if w.llm.name == "groq" else None,
        "persistence": {"enabled": S.store is not None, "path": S.db_path if S.store else None,
                        "encrypted_at_rest": S.store is not None},
        "demo": {"active": S.demo is not None, "run": S.demo.run if S.demo else None, "mode": S.demo.mode if S.demo else None},
        "now": w.now_iso(),
        "passport": {**p_.model_dump(), "recipients": {k: v.model_dump() for k, v in p_.recipients.items() if k not in decoys}},
        "rate_mid": w.rates.mid(w.day_index),
        "rates": provenance(w.rates, w.day_index),
        "routes": [{"id": q.route.id, "name": q.route.name, "delivered_cny_per_100k_inr": q.delivered_cny,
                    "days": q.arrives_in_days, "reliability": q.route.reliability, "cost_vs_mid_pct": q.cost_vs_mid_pct,
                    "typical_bank": q.route.typical_bank} for q in quotes],
        "last_mile_rent_6000": last_mile(6000),
        "runway_months": runway_months(p_, w.rates, w.day_index), "burn": {"monthly_cny": burn, "basis": basis},
        "spending": sp,
        "autonomy": {"rate_now": w.rates.mid(w.day_index), "targets": p_.rules.rate_targets,
                     "tier1_auto_convert_cny": p_.rules.tier1_auto_convert_cny,
                     "tier1_auto_pay_cny": p_.rules.tier1_auto_limit_cny,
                     "recurring": [o.model_dump() for o in p_.obligations if o.recurring and o.status in ("pending", "planned")],
                     "log": p_.autonomy_log[-20:]},
        "triggers": [t.__dict__ for t in triggers(p_, w.rates, w.today, w.day_index)],
        "cards": w.cards[-20:],
        "proofs": list(w.proofs),
        "pending": [_pending_view(k, v) for k, v in S.pending.items()],
        "devices": {r: (lambda k: {"key_id": k["key_id"]} if k else None)(w.approvers.active(r)) for r in ("student", "parent")},
        "security_feed": [{"i": e["i"], "kind": e["kind"], "ts": e["ts"]} for e in w.audit.entries[-30:]],
        "ledger_money_lost": w.ledger.money_lost(),
        "canaries_tripped": bool(w.canaries and w.canaries.tripped),
    })


@app.post("/api/reset")
def reset(p: Principal = Depends(STUDENT)):
    S.reset()
    return {"ok": True}


# ------------------------------------------------------------------ pipeline
def _intake(body: IntakeIn) -> dict:
    req = Request(body.text, source=body.source, remitter=body.remitter)
    o = _out(S.agent.handle(req))
    o["pending_id"] = _store_pending(req, o)
    S.save()
    return o


@app.post("/api/intake")
def intake(body: IntakeIn, p: Principal = Depends(STUDENT)):
    return _intake(body)


@app.post("/api/intake/image")
async def intake_image(file: UploadFile = File(...), remitter: str = "student", p: Principal = Depends(STUDENT)):
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
    return _intake(IntakeIn(text=text, remitter=remitter, source="screenshot"))


@app.post("/api/approve")
def approve(body: ApproveIn, p: Principal = Depends(STUDENT_PARENT)):
    """Approve (or decline) a held payment AS THE ROLE OF THE SESSION. Approving needs a signature, made with that
    role's registered device key, over the pending payment's exact draft hash. The role string grants nothing."""
    role = p.role
    item = S.pending.get(body.pending_id)
    if not item:
        raise HTTPException(404, "unknown pending id")
    if role not in item["required"]:
        raise HTTPException(403, f"this payment does not need the {role}'s approval")
    if not body.approve:
        S.world.audit.append("declined", {"pending_id": body.pending_id, "role": role})
        S.pending.pop(body.pending_id)
        S.save()
        return {"status": "declined"}
    dh = (item["outcome"].get("draft") or {}).get("draft_hash")
    if not body.signature or not dh:
        raise HTTPException(403, "a signed approval is required: sign the payment draft with your device key")
    k = S.world.approvers.verify(role, dh, body.signature, body.key_id)
    if k is None:
        S.world.audit.append("approval_rejected", {"pending_id": body.pending_id, "role": role, "draft_hash": dh,
                                                   "reason": "signature does not verify against the registered device key"})
        S.save()
        raise HTTPException(403, "approval signature does not verify for this exact payment")
    rec = S.world.approvers.make_record(role, body.signature, S.world.now_iso())
    item["signed"][role] = rec
    S.world.audit.append("approval", {"pending_id": body.pending_id, "role": role, "draft_hash": dh, "key_id": k["key_id"]})
    missing = set(item["required"]) - set(item["signed"])
    if missing:
        S.save()
        return {"status": "waiting", "missing": sorted(missing), "signed_by": {r: x["key_id"] for r, x in item["signed"].items()}}
    req = item["request"]
    req.signed_approvals = tuple(item["signed"][r] for r in sorted(item["signed"]))
    o = _out(S.agent.handle(req))
    S.pending.pop(body.pending_id)
    o["pending_id"] = _store_pending(req, o)
    S.save()
    return o


@app.post("/api/recovery/approve")
def recovery_approve(body: RecoveryIn, p: Principal = Depends(STUDENT)):
    """The 'ask' step after a freeze: the student approves the recovery plan. Nothing is paid here."""
    res = S.agent.approve_recovery(body.obligation)
    S.save()
    return res


@app.get("/api/parent/pending")
def parent_pending(lang: str | None = None, p: Principal = Depends(require("parent", "student", "judge"))):
    pp = S.world.passport
    parent = next((a for a in pp.approvers if a.role == "parent"), None)
    if lang and lang not in LANGS:
        raise HTTPException(400, f"unsupported language {lang!r}; use one of {sorted(LANGS)}")
    out = []
    for k, v in S.pending.items():
        if "parent" in v["required"]:
            view = parent_view(S.world, v["outcome"]["fields"], lang)
            pv = _pending_view(k, v)
            out.append({"id": k, **view, "approvals": pv["approvals"], "signed_by": pv["signed_by"],
                        "required": v["required"], "draft": pv["draft"]})
    consents = []
    for plan in S.world.plans:
        if plan.get("status") in ("accepted", "executing"):
            for d in plan_exec.parent_consents_needed(plan):
                rec = (plan.get("consents") or {}).get(str(d["step"]))
                consents.append({**d, "signed_by": rec["key_id"] if rec else None})
    return {"parent": parent.model_dump() if parent else None, "language": lang or (parent.language if parent else "en"),
            "available_languages": LANGS, "pending": out, "plan_consents": consents,
            "device": ({"key_id": S.world.approvers.active("parent")["key_id"]} if S.world.approvers.active("parent") else None)}


INVOICE_HINT = re.compile(r"(Payee|Account|Amount|收款人|账号|金额)\s*[:：]", re.I)
TARGET_RE = re.compile(r"convert\s+(?:cny\s*|¥|rmb\s*)?([\d,]+(?:\.\d+)?)[^.\n]*?(?:rate|inr)[^\d]{0,30}?(0\.\d+)", re.I)


@app.post("/api/chat")
def chat(body: ChatIn, p: Principal = Depends(STUDENT)):
    S.chat.append({"role": "student", "text": body.message})
    if INVOICE_HINT.search(body.message):
        res = _intake(IntakeIn(text=body.message))
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
    pp = w.passport
    tr = triggers(pp, w.rates, w.today, w.day_index)
    pend = [o for o in pp.obligations if o.status != "paid"]
    best = rank(quote_routes(w.rates, 100000, w.today, None, w.day_index))[0]
    reply = (f"You have INR {pp.balance('INR'):,.0f} and CNY {pp.balance('CNY'):,.0f}. "
             f"Upcoming: " + "; ".join(f"{o.type} CNY {o.amount:,.0f} due {o.due}" for o in pend) + ". "
             f"Runway after obligations: {runway_months(pp, w.rates, w.day_index):.1f} months. "
             f"Cheapest on-time route right now: {best.route.name}. "
             + (" Alerts: " + " ".join(t.message for t in tr) if tr else " No alerts.") +
             " Forward me any invoice or message and I'll check it before anything is paid. "
             "You can also say: 'convert 2000 when the rate reaches 0.0700'.")
    S.chat.append({"role": "oasis", "text": reply})
    return {"reply": reply}


# ------------------------------------------------------------------ agentic planning (spec step 2)
def _plan_view(world, rec: dict) -> dict:
    consents = [{**d, "signed_by": ((rec.get("consents") or {}).get(str(d["step"])) or {}).get("key_id")}
                for d in plan_exec.parent_consents_needed(rec)] if rec.get("id") else []
    return jsonable_encoder({**rec, "step_status": plan_exec.step_statuses(world, rec), "parent_consents": consents})


@app.get("/api/plan/scenarios")
def plan_scenarios(p: Principal = Depends(STUDENT_JUDGE)):
    return [{"id": s.id, "title": s.title, "description": s.description, "goal": s.goal, "tests": s.tests} for s in SCENARIOS.values()]


@app.post("/api/plan")
def plan_create(body: PlanIn, p: Principal = Depends(STUDENT)):
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
def plans_list(p: Principal = Depends(STUDENT_JUDGE)):
    return [_plan_view(S.world, r) for r in S.world.plans]


@app.get("/api/plan/{plan_id}")
def plan_get(plan_id: str, p: Principal = Depends(STUDENT_JUDGE)):
    rec = plan_exec.get_plan(S.world, plan_id)
    if rec is None:
        raise HTTPException(404, "no such plan")
    return _plan_view(S.world, rec)


@app.post("/api/plan/{plan_id}/accept")
def plan_accept(plan_id: str, p: Principal = Depends(STUDENT)):
    res = plan_exec.accept_plan(S.agent, plan_id)
    if "error" in res and res.get("errors") is None and res["error"] == "no such plan":
        raise HTTPException(404, res["error"])
    S.save()
    return jsonable_encoder(res)


@app.post("/api/plan/{plan_id}/consent")
def plan_consent(plan_id: str, body: ConsentIn, p: Principal = Depends(PARENT)):
    """The parent's SIGNED consent to one parent-remitted conversion step of an accepted plan."""
    res = plan_exec.record_parent_consent(S.agent, plan_id, body.step, body.signature)
    if "error" in res:
        S.save()
        raise HTTPException(404 if res["error"] == "no such plan" else 403, res["error"])
    S.save()
    return res


@app.post("/api/plan/{plan_id}/execute")
def plan_execute(plan_id: str, p: Principal = Depends(STUDENT)):
    """Run the accepted plan's steps that are due today. Payments go through the full pipeline; anything that needs
    approval is registered as a pending approval for the student (and parent) exactly like a normal intake. A
    parent-remitted conversion runs only once the parent has signed their consent."""
    res = plan_exec.execute_due(S.agent, plan_id)
    if "error" in res:
        raise HTTPException(409, res["error"])
    pend = []
    for req, held in res.pop("held"):
        pend.append(_store_pending(req, _out(held)))
    res["pending_ids"] = [x for x in pend if x]
    S.save()
    return jsonable_encoder(res)


# ------------------------------------------------------------------ Tier-1 autonomy + spending
@app.post("/api/rate-target")
def rate_target(body: RateTargetIn, p: Principal = Depends(STUDENT)):
    if body.rate <= 0 or body.convert_cny <= 0:
        raise HTTPException(400, "rate and convert_cny must be positive")
    t = S.agent.set_rate_target(body.rate, body.convert_cny)
    S.save()
    return t


@app.post("/api/rate-target/approve")
def rate_target_approve(body: TargetIdIn, p: Principal = Depends(STUDENT)):
    res = S.agent.approve_rate_target(body.target_id)
    S.save()
    return jsonable_encoder(res)


@app.post("/api/autonomy/tick")
def autonomy_tick(body: TickIn, p: Principal = Depends(STUDENT)):
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
def spending_simulate(body: SpendSimIn, p: Principal = Depends(STUDENT)):
    """Import MOCK wallet spending so the forecast can switch from cold start to the student's own pattern."""
    pp = S.world.passport
    start = (max(date.fromisoformat(t["date"]) for t in pp.transactions) + timedelta(days=1)
             if pp.transactions else S.world.today - timedelta(days=max(1, min(body.days, 90))))
    spending.simulate_spending(pp, start, max(1, min(body.days, 90)))
    S.world.audit.append("spending_imported", {"source": "mock", "days": body.days, "transactions": len(pp.transactions)})
    S.save()
    return spending.summarize(pp)


@app.post("/api/spending/add")
def spending_add(body: SpendAddIn, p: Principal = Depends(STUDENT)):
    tx = spending.add_transaction(S.world.passport, S.world.today, body.desc, body.amount_cny, "manual")
    S.save()
    return {"transaction": tx, "summary": spending.summarize(S.world.passport)}


# ------------------------------------------------------------------ red team (judge only, separate sandbox)
def _log_attempt(rec: dict) -> None:
    """Append one red-team attempt to the attempts store (data/redteam_attempts.jsonl, git-ignored). Failure to write
    never blocks the console."""
    try:
        S.attempts_path.parent.mkdir(parents=True, exist_ok=True)
        with S.attempts_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


@app.post("/api/redteam")
def redteam(body: RedTeamIn, request: HttpRequest, p: Principal = Depends(JUDGE)):
    """Judge-only console. Runs in a SEPARATE sandbox world (its own ledger, registry and simulated approvers) that can
    never touch the student's ledger. Rate-limited per client and size-limited; every attempt is logged."""
    from eval.approver import SimulatedHumans
    client = hashlib.sha256(_client(request).encode()).hexdigest()[:12]
    base = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "client": client, "role": p.role}
    poison = json.dumps(body.tool_poison, sort_keys=True) if body.tool_poison else ""
    if len(body.text.encode()) > REDTEAM_MAX_TEXT or len(poison.encode()) > REDTEAM_MAX_POISON:
        _log_attempt({**base, "text": body.text[:500], "tool_poison": None, "outcome": "rejected_too_large",
                      "text_bytes": len(body.text.encode())})
        raise HTTPException(413, f"attempt too large (max {REDTEAM_MAX_TEXT} bytes of text, {REDTEAM_MAX_POISON} of tool output)")
    if not body.text.strip():
        raise HTTPException(400, "empty attempt")
    if not S.redteam_limiter.allow(client):
        _log_attempt({**base, "text": body.text, "tool_poison": body.tool_poison, "outcome": "rate_limited"})
        raise HTTPException(429, f"rate limit: at most {REDTEAM_PER_MINUTE} attempts per minute",
                            headers={"Retry-After": str(S.redteam_limiter.retry_after(client))})
    w = S.redteam_world
    before = w.ledger.money_lost()
    o = _out(S.redteam_agent.handle(Request(body.text, tool_poison=body.tool_poison), SimulatedHumans()))
    o["money_lost_this_attempt"] = round(w.ledger.money_lost() - before, 2)
    d = o.get("decision") or {}
    entry = {"text": body.text[:500], "status": o["status"], "lost": o["money_lost_this_attempt"]}
    S.redteam_log.append(entry)
    del S.redteam_log[:-200]
    _log_attempt({**base, "text": body.text, "tool_poison": body.tool_poison, "outcome": "ran", "status": o["status"],
                  "label": o.get("label"), "rule": d.get("rule") or (o.get("card") or {}).get("rule"),
                  "risk_score": (o.get("risk") or {}).get("score"), "detected": o.get("detected"),
                  "canary_kinds": [h.get("kind") for h in o.get("canary_hits") or []],
                  "followed_injection": o.get("followed_injection"), "money_lost": o["money_lost_this_attempt"]})
    return o


@app.get("/api/redteam/log")
def redteam_log(p: Principal = Depends(JUDGE)):
    return {"attempts": S.redteam_log, "total_lost": S.redteam_world.ledger.money_lost(),
            "limits": {"per_minute": REDTEAM_PER_MINUTE, "max_text_bytes": REDTEAM_MAX_TEXT}}


# ------------------------------------------------------------------ proof + audit
def _parent_proofs() -> list[str]:
    """Least privilege: the parent sees only the proof packs of payments they co-approved."""
    return [i for i, pk in S.world.proofs.items()
            if any(a.get("role") == "parent" for a in (pk.get("intent") or {}).get("approvals") or [])]


@app.get("/api/proof/{intent_id}")
def proof(intent_id: str, p: Principal = Depends(VIEWERS)):
    if p.role == "parent" and intent_id not in _parent_proofs():
        raise HTTPException(403, "the parent can open only the proof packs of payments they approved")
    return _proof(intent_id)


def _proof(intent_id: str) -> dict:
    pk = S.world.proofs.get(intent_id) or S.redteam_world.proofs.get(intent_id)
    if not pk:
        raise HTTPException(404, "no such proof pack")
    return pk


def _verify_pinned(pack: dict) -> dict:
    """Verify against THIS server's pinned key fingerprint, its pinned approver device keys and its (simulated) chain;
    any other keys fail the pins."""
    best = None
    for chain in S.anchor_chains() or [None]:
        res = verify_proof_pack(pack, S.trusted_fingerprints(), chain, S.pinned_approver_keys())
        if best is None or (res["ok"] and not best["ok"]):
            best = res
    res = best
    res["pinned_fingerprint"] = S.world.trust_fingerprint()
    return res


@app.get("/api/trust/fingerprint")
def trust_fingerprint():
    """PUBLIC. The fingerprint (sha256 over the canonical public keys) that verifiers must pin, and the approver device
    keys (public keys only) the server vouches for."""
    w = S.world
    return {"fingerprint": w.trust_fingerprint(), "key_id": w.signer.key_id, "public_keys": w.signer.public_keys(),
            "algorithms": sorted(w.signer.public_keys()), "persistent": S.signer is not None and not w.deterministic,
            "demo_keys": bool(w.deterministic),
            "approver_keys": [{"role": k["role"], "key_id": k["key_id"], "active": k["active"]}
                              for ap in (S.approvers, w.approvers) for k in ap.keys],
            "note": "Pin this fingerprint out of band. A proof pack embeds its own public keys, so a pack signed with any "
                    "other keys fails the key_pinned check. Demo keys are seeded and public: never trust them for real use."}


@app.get("/api/proof/{intent_id}/verify")
def proof_verify(intent_id: str):
    """PUBLIC and harmless: returns only check results for a pack that already exists."""
    return _verify_pinned(_proof(intent_id))


@app.post("/api/proof/verify")
def proof_verify_upload(pack: dict):
    """PUBLIC: verifies an uploaded pack against the pinned keys. Needs no secrets and changes no state."""
    return _verify_pinned(pack)


@app.get("/api/audit")
def audit(p: Principal = Depends(STUDENT_JUDGE)):
    return {"entries": S.world.audit.entries}


@app.get("/api/audit/verify")
def audit_verify(p: Principal = Depends(VIEWERS)):
    r = verify_chain(S.world.audit.entries)
    return {**r.__dict__, "ok": r.ok, "head": S.world.audit.head()}


# ------------------------------------------------------------------ evaluation + demo
@app.get("/api/benchmark")
def benchmark(p: Principal = Depends(STUDENT_JUDGE)):
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


# The scripted demo REPLACES the persisted sandbox with its own fixed world (and wipes the stored state), so it is a
# STUDENT action; judges see the same scripted runs through the read-only demo/state view. The demo world has its own
# simulated approver devices: its "humans" are in-process, exactly like the benchmark's.
@app.post("/api/demo/start")
def demo_start(body: DemoIn, p: Principal = Depends(STUDENT)):
    """Reset to the scripted demo world (fixed seed, fixed MOCK data) and return the step list. `mode` "offline" (default)
    uses the offline LLM; "live" replays recorded qwen/qwen3.8-27b responses from the fixture (no network)."""
    return _demo_start(body)


def _demo_start(body: DemoIn) -> dict:
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
def demo_next(p: Principal = Depends(STUDENT)):
    if not S.demo:
        raise HTTPException(409, "no demo running; POST /api/demo/start first")
    res = S.demo.next()
    S.save()
    return jsonable_encoder(res)


@app.get("/api/demo/state")
def demo_state(p: Principal = Depends(STUDENT_JUDGE)):
    if not S.demo:
        return {"active": False}
    return jsonable_encoder({"active": True, "run": S.demo.run, "mode": S.demo.mode, "index": S.demo.index, "total": len(S.demo.titles),
                             "done": S.demo.done, "steps": S.demo.titles, "results": S.demo.results})


@app.post("/api/demo/run")
def demo_run(body: DemoIn, p: Principal = Depends(STUDENT)):
    """Play a whole scripted demo run in one call (same result every time, no network)."""
    _demo_start(body)
    res = S.demo.run_all()
    S.save()
    return jsonable_encoder(res)


@app.post("/api/demo/reset")
def demo_reset(p: Principal = Depends(STUDENT)):
    """Back to a clean (non-demo) sandbox; also wipes the SQLite state."""
    S.reset()
    return {"ok": True}


@app.get("/api/explain/savings")
def savings(p: Principal = Depends(STUDENT_JUDGE)):
    convs = [e["data"] for e in S.world.audit.entries if e["kind"] == "conversion"]
    tot = round(sum(c["saved_cny"] for c in convs), 2)
    return {"conversions": convs, "total_saved_cny": tot,
            "text": explain_template("savings", {"saved_cny": tot, "saved_pct": convs[-1]["saved_pct"] if convs else 0})}


DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
