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
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import math
import os
import re
from collections import OrderedDict
import secrets
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request as HttpRequest, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field, model_validator

from .. import config
from ..agent import localize as loc
from ..agent.i18n import LANGS, UI_LANGS, lang_from_accept, ui_lang
from ..agent.zh_messages import route_zh
from ..agent.llm import GroqLLM, VisionExtractor, VisionUnavailable, explain_template, make_llm
from ..agent.parent import parent_view
from ..agent.pipeline import OasisAgent, Request
from ..agent import plan_exec
from ..agent.planner import AgenticPlanner, DeterministicPlanner, build_record, make_planner
from ..agent.replay import MODES, fixture_info
from ..demo import DemoRunner, new_demo_world
from ..market import provenance
from ..planning import spending
from ..flightpath import core as fpath
from ..planning.scenarios import SCENARIOS, build_scenario_world
from ..planning.forecast import monthly_burn, runway_months, triggers
from ..planning.routes import last_mile, quote_routes, rank
from ..mock.fx import FxError, quote as fx_quote, table_for
from ..passport import currency as currency_mod
from ..passport.currency import currency_view
from ..proof import trust_pass as tp
from ..proof.pack import verify_proof_pack
from ..proof.reliability import build_reliability_record, eligible_payments, verify_reliability_record
from ..intake.telegram import PairingStore, summarize as chat_summary
from ..screening import screen_payee
from ..storage import SqliteStore
from ..chain.anchor import Anchor, LocalAnchorChain
from ..trust.approvals import ApproverRegistry
from ..trust import corridor
from ..trust.audit import verify_chain
from ..trust.keyfile import default_session_secret_path, load_or_create_secret
from ..trust.keystore import fingerprint, load_or_create_signer
from ..world import Features, World
from .auth import COOKIE, ROLES, Auth, Principal, judge_mode
from .passkeys import PasskeyError, PasskeyService
from .ratelimit import RateLimiter

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "eval" / "reports"
MOCK_NOTE = ("MOCK: rates, fees, payment rails, registry identities, wallet spending and balances are simulated "
             "sandbox data. Anchoring uses a local simulated chain unless OASIS_ANCHOR=fisco, which uses a real FISCO BCOS chain running locally (4 nodes, one host).")

REDTEAM_MAX_TEXT = 4000          # bytes of attack text per attempt
REDTEAM_MAX_POISON = 400         # bytes of poisoned-tool-output JSON per attempt
REDTEAM_PER_MINUTE = 20          # attempts per client per minute
LOGIN_FAILS_PER_MINUTE = 10
REDTEAM_MAX_WORLDS = 20          # red-team sandboxes kept at once (one per judge session); least recently used is evicted
JUDGE_REDTEAM_PER_MINUTE = 10    # OASIS_JUDGE_MODE=1: tighter limits
JUDGE_LOGIN_FAILS_PER_MINUTE = 5
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect")

@asynccontextmanager
async def _lifespan(_app):
    start_channels()                     # Telegram / IMAP threads, only for the channels configured in the environment
    yield
    CHANNELS["stop"].set()


app = FastAPI(title="Oasis API", version="0.3.0", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
MAX_BODY = 2_000_000             # bytes of JSON per request
MAX_UPLOAD = 12_000_000          # bytes for the image upload
_STATE_LOCK = threading.Lock()   # a thread lock (not asyncio): it also serialises requests served from different event loops


def _env_origins() -> set[str]:
    """OASIS_ALLOWED_ORIGINS: extra exact origins (comma-separated, e.g. https://oasis.example.com) for a public deployment."""
    return {o.strip().rstrip("/") for o in os.environ.get("OASIS_ALLOWED_ORIGINS", "").split(",") if o.strip()}


def _origin_allowed(origin: str, request: HttpRequest) -> bool:
    """Same-host check for the Origin header. Behind a TLS-terminating proxy that rewrites Host, the public host is also
    accepted from X-Forwarded-Host, but ONLY when OASIS_TRUST_FORWARDED_HOST=1 (the operator says a proxy sets it) or from
    the exact-origin allow-list OASIS_ALLOWED_ORIGINS. Unset, behaviour is the plain same-host check."""
    host = origin.split("://", 1)[-1]
    if host == request.headers.get("host") or origin.rstrip("/") in _env_origins():
        return True
    if os.environ.get("OASIS_TRUST_FORWARDED_HOST") == "1":
        fwd = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
        return bool(fwd) and host == fwd
    return False


def _cookie_secure(request: HttpRequest) -> bool:
    """Secure flag for the session cookie: always when OASIS_COOKIE_SECURE=1; otherwise when the request arrived over https
    (behind a proxy that is the scheme uvicorn derives from X-Forwarded-Proto for trusted proxies only: --forwarded-allow-ips).
    Plain http://localhost keeps a non-Secure cookie."""
    return os.environ.get("OASIS_COOKIE_SECURE") == "1" or request.url.scheme == "https"


@app.middleware("http")
async def guard(request: HttpRequest, call_next):
    """Cross-cutting protections for every request.

    - CSRF: SameSite=Strict treats http://localhost:ANY_PORT as same-site, so another page on localhost could still send a
      cookie-carrying POST. A state-changing request whose Origin is neither this host nor the dev UI origin is refused.
    - Size: bodies above MAX_BODY (MAX_UPLOAD for the image upload) are refused before parsing.
    - Serialisation: the sandbox is single-writer state (audit chain, ledger, nonces, pending approvals). Requests run one at
      a time, so two simultaneous approvals can never both pass the replay check and the audit chain cannot fork.
    """
    path = request.url.path
    if judge_mode() and (path in DOCS_PATHS or path.startswith("/docs/")):      # interactive API docs off in judge mode
        return JSONResponse({"detail": "not found"}, status_code=404)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and origin != "null" and origin not in CORS_ORIGINS and not _origin_allowed(origin, request):
            return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
        if origin == "null":
            return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
        try:
            n = int(request.headers.get("content-length") or 0)
        except ValueError:
            n = MAX_UPLOAD + 1
        if n > (MAX_UPLOAD if path in ("/api/intake/image", "/api/intake/email") else MAX_BODY):
            return JSONResponse({"detail": "request body too large"}, status_code=413)
    if path == "/api/health" or not path.startswith("/api/"):
        return await call_next(request)
    while not _STATE_LOCK.acquire(blocking=False):       # polling keeps the worker threads free for the handler that holds it
        await asyncio.sleep(0.002)
    try:
        response = await call_next(request)
    finally:
        _STATE_LOCK.release()
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


@app.middleware("http")
async def security_headers(request: HttpRequest, call_next):
    """Browser-side protections on EVERY response, including the static UI and early refusals (registered after `guard`, so it
    wraps it). CSP/framing: the UI is same-origin only and cannot be embedded; the interactive API docs (off in judge mode)
    load a CDN script, so they are exempt from the CSP. HSTS only over https (it is meaningless, and harmful to cache, over
    plain http on localhost)."""
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if request.url.path not in DOCS_PATHS and not request.url.path.startswith("/docs/"):
        h.setdefault("Content-Security-Policy", CSP)
    if request.url.scheme == "https" or os.environ.get("OASIS_COOKIE_SECURE") == "1":
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


_ROLE_ERR = re.compile(r"role may not do this", re.I)
_SIG_ERR = re.compile(r"signature|signed approval", re.I)


def _error_code(detail) -> str | None:
    """A language-neutral tag for the errors the UI treats specially (it must not parse translated wording)."""
    if not isinstance(detail, str):
        return None
    if _ROLE_ERR.search(detail):
        return "role_not_allowed"
    if "cross-origin" in detail:
        return "cross_origin"
    if _SIG_ERR.search(detail):
        return "approval_rejected"
    return None


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: HttpRequest, exc: StarletteHTTPException):
    """Same body as FastAPI's default ({"detail": ...}), with the text in the caller's language and, where the UI needs it, a
    language-neutral `code`. Status codes and headers are untouched."""
    body = {"detail": loc.tr_error(exc.detail, _ui_lang(request))}
    code = _error_code(exc.detail)
    if code:
        body["code"] = code
    return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))


_PYDANTIC_ZH = {"Field required": "此字段必填", "Input should be a valid string": "应为有效的文本",
                "Input should be a valid boolean": "应为有效的布尔值", "Input should be a valid integer": "应为有效的整数",
                "Input should be a valid number": "应为有效的数字", "Input should be a valid dictionary": "应为有效的对象",
                "Input should be a valid list": "应为有效的列表"}


def _pydantic_zh(msg: str) -> str:
    if msg in _PYDANTIC_ZH:
        return _PYDANTIC_ZH[msg]
    m = re.fullmatch(r"String should have at most (\d+) characters?", msg)
    if m:
        return f"文本最多 {m.group(1)} 个字符"
    m = re.fullmatch(r"Input should be greater than (.+)", msg)
    if m:
        return f"应大于 {m.group(1)}"
    return msg


@app.exception_handler(RequestValidationError)
async def _validation_error(request: HttpRequest, exc: RequestValidationError):
    """422 without echoing the offending input: it may hold NaN or an unpaired surrogate, which cannot be rendered as JSON
    (that used to turn a validation error into a 500), and echoing request text back helps nobody."""
    zh = _ui_lang(request) == "zh"
    errs = [{"loc": [str(x) for x in e.get("loc", ())], "type": e.get("type"),
             "msg": _pydantic_zh(str(e.get("msg"))) if zh else str(e.get("msg"))} for e in exc.errors()]
    return JSONResponse({"detail": errs}, status_code=422)


class RedTeamBox:
    """One judge session's red-team sandbox: its own World (ledger, audit chain, registry, simulated approvers), agent and log."""

    def __init__(self, signer):
        self.world = World(Features.full(), make_llm(), signer=signer, rates_mode="mock")
        self.agent = OasisAgent(self.world)
        self.log: list[dict] = []


class Session:
    """One student's sandbox (plus per-judge red-team sandboxes), optionally backed by SQLite."""

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
        pk_dir = kdir or (Path(self.db_path).parent if self.store else config.DATA_DIR)      # beside the database / keys, so a fresh sandbox starts with none
        self.passkeys = PasskeyService(pk_dir / "passkeys.json" if persistent else None)
        self.tg_store = PairingStore(pk_dir / "telegram_pairing.json" if persistent else None)
        self.approvers = ApproverRegistry()      # public keys of the real approvers' devices; private keys stay in browsers
        self.attempts_path = Path(attempts_path or os.environ.get("OASIS_ATTEMPTS_FILE") or config.DATA_DIR / "redteam_attempts.jsonl")
        jm = judge_mode()
        self.redteam_per_minute = JUDGE_REDTEAM_PER_MINUTE if jm else REDTEAM_PER_MINUTE
        self.redteam_max_worlds = int(os.environ.get("OASIS_REDTEAM_MAX_WORLDS") or REDTEAM_MAX_WORLDS)
        self.redteam_limiter = RateLimiter(self.redteam_per_minute, 60.0)
        self.login_limiter = RateLimiter(JUDGE_LOGIN_FAILS_PER_MINUTE if jm else LOGIN_FAILS_PER_MINUTE, 60.0)
        self.redteam_log_limiter = RateLimiter(5, 60.0)
        self.pending: dict[str, dict] = {}   # pending_id -> {"request","signed","required","outcome"}
        self.demo: DemoRunner | None = None
        self.redteam_boxes: OrderedDict[str, RedTeamBox] = OrderedDict()     # judge session id -> sandbox (LRU, bounded)
        self.chat: list[dict] = []
        self.reliability_last = None
        self.trust_shares: dict[str, dict] = {}   # QR code -> shared Trust Pass presentation
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
            self.trust_shares = dict(snap["kv"].get("trust_shares", {}))
        self.agent = OasisAgent(self.world)
        self.redteam_boxes = OrderedDict()                 # every judge's sandbox starts fresh with the student's reset
        self._rt_default = RedTeamBox(self.signer)          # fallback world (no judge session); never persisted

    @property
    def redteam_world(self) -> World:
        return self._rt_default.world

    def redteam_box(self, key: str) -> RedTeamBox:
        """The calling judge session's own sandbox, created on first use. At most `redteam_max_worlds` are kept; the least
        recently used one is evicted (its attempts stay in the attempts file, its world and proofs are dropped)."""
        box = self.redteam_boxes.get(key)
        if box is None:
            box = self.redteam_boxes[key] = RedTeamBox(self.signer)
            while len(self.redteam_boxes) > self.redteam_max_worlds:
                self.redteam_boxes.popitem(last=False)
        else:
            self.redteam_boxes.move_to_end(key)
        return box

    def redteam_worlds(self) -> list[World]:
        return [self._rt_default.world] + [b.world for b in self.redteam_boxes.values()]

    def reset(self) -> None:
        if self.store:
            self.store.clear()
        self.pending, self.demo, self.chat = {}, None, []
        self.reliability_last = None
        self.trust_shares = {}
        lang = self.world.passport.student.language
        self._build()
        self.world.passport.student.language = lang         # the interface language is the student's, not part of the sandbox
        self.save()

    def start_demo(self, run: str, mode: str = "offline") -> DemoRunner:
        if self.store:
            self.store.clear()
        self.pending, self.chat = {}, []
        lang = self.world.passport.student.language
        w = new_demo_world(self.store, mode)      # its own registry with seeded SIMULATED approver devices
        w.passport.student.language = lang
        self.demo = DemoRunner(run, w)
        self._build(world=w)
        self.demo.agent = self.agent
        self.save()
        return self.demo

    def trusted_fingerprints(self) -> set[str]:
        """Key fingerprints this server vouches for: its own signing keys. The scripted demo's keys are public (seeded),
        so they are trusted only while the demo world is the active world."""
        return {self.world.trust_fingerprint()} | {w.trust_fingerprint() for w in self.redteam_worlds()}

    def pinned_approver_keys(self) -> set[str]:
        """Approver device-key ids this server vouches for (registered real devices + the sandbox worlds' simulated ones)."""
        keys = self.approvers.pinned_key_ids() | self.world.approvers.pinned_key_ids()
        for w in self.redteam_worlds():
            keys |= w.approvers.pinned_key_ids()
        return keys

    def anchor_chains(self, ids: tuple[str, ...] | None = None) -> list:
        return [w.anchor for w in [self.world, *self.redteam_worlds()] if isinstance(w.anchor, Anchor)]

    def save(self) -> None:
        if not self.store:
            return
        snap = self.world.snapshot()
        snap["kv"]["approvers"] = self.approvers.public_view()
        snap["kv"]["trust_shares"] = self.trust_shares
        snap["kv"]["pending"] = {k: {"request": _request_to(v["request"]), "signed": v["signed"],
                                     "required": v["required"], "outcome": jsonable_encoder(v["outcome"])}
                                 for k, v in self.pending.items()}
        self.store.save(snap)


def _request_to(r: Request) -> dict:
    return {"text": r.text, "source": r.source, "purpose_hint": r.purpose_hint, "remitter": r.remitter,
            "recurring": r.recurring, "tool_poison": r.tool_poison, "draft": r.draft, "pay_again": r.pay_again,
            "signed_approvals": list(r.signed_approvals), "channel": r.channel}


def _request_from(d: dict) -> Request:
    return Request(d["text"], source=d["source"], purpose_hint=d.get("purpose_hint"), remitter=d["remitter"],
                   recurring=d.get("recurring", False), tool_poison=d.get("tool_poison"), draft=d.get("draft"),
                   pay_again=bool(d.get("pay_again", False)), signed_approvals=tuple(d.get("signed_approvals", [])),
                   channel=d.get("channel"))


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


def _ui_lang(request: HttpRequest) -> str:
    """The language of this response: `?lang=` > the `X-Oasis-Lang` header the UI sends > the logged-in student's saved language
    (Passport) > Accept-Language > English. Only the whitelisted UI codes (en, zh) are ever honoured; anything else is ignored."""
    for cand in (request.query_params.get("lang"), request.headers.get("x-oasis-lang")):
        c = ui_lang(cand)
        if c:
            return c
    try:
        if _principal(request) is not None:
            c = ui_lang(S.world.passport.student.language)
            if c:
                return c
    except Exception:  # noqa: BLE001 - language resolution must never break a request
        pass
    return lang_from_accept(request.headers.get("accept-language")) or "en"


UI = Depends(_ui_lang)


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
            "duplicate": v["outcome"].get("duplicate"), "pay_again": bool(v["request"].pay_again),
            "draft": {kk: d.get(kk) for kk in ("payee_id", "account_ref", "amount", "currency", "purpose", "route_id",
                                                "not_after", "nonce", "canonical", "draft_hash")} if d else None}


DUP_CONFIRM = "duplicate_confirmation"     # R17 hold: not an approver role, so /api/approve can never release it


def _store_pending(req: Request, outcome: dict) -> str | None:
    d = outcome.get("decision") or {}
    req_roles = set(d.get("required_approvals") or [])
    dup_hold = d.get("rule") == "R17_duplicate_payment" and req_roles == {DUP_CONFIRM}
    if outcome["status"] != "held" or not req_roles or not (req_roles <= {"student", "parent"} or dup_hold) or not outcome.get("draft"):
        return None
    pid = f"pend_{secrets.token_hex(4)}"     # unique, never reused: a stale button can never hit a newer payment
    dr = outcome["draft"]
    req.draft = {"nonce": dr["nonce"], "not_after": dr["not_after"]}     # approvers sign THIS draft; the re-run reuses it
    S.pending[pid] = {"request": req, "signed": {a["role"]: a for a in req.signed_approvals}, "required": sorted(req_roles),
                      "outcome": outcome}
    return pid


# ------------------------------------------------------------------ models
def _check_clean(v, path="body"):
    """Reject what breaks canonical JSON, hashing, the encrypted store or the JSON response: lone surrogates, NaN, infinity."""
    if isinstance(v, str):
        try:
            v.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError(f"{path}: text contains an unpaired surrogate (invalid Unicode)")
    elif isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError(f"{path}: NaN and infinity are not allowed")
    elif isinstance(v, dict):
        for k, x in v.items():
            _check_clean(k, path)
            _check_clean(x, f"{path}.{k}")
    elif isinstance(v, (list, tuple)):
        for x in v:
            _check_clean(x, path)


class Strict(BaseModel):
    """Base of every request body: invalid Unicode and non-finite numbers are a 422, never a 500 or poisoned state."""
    @model_validator(mode="after")
    def _clean(self):
        _check_clean(self.__dict__)
        return self


class IntakeIn(Strict):
    text: str = Field(max_length=20000)    # an invoice is a page, not a book; the field parsers are not linear on adversarial text
    remitter: str = "student"
    source: str = "invoice"


class ChatIn(Strict):
    message: str = Field(max_length=20000)


class ApproveIn(Strict):
    pending_id: str
    approve: bool = True
    signature: str | None = None    # base64 Ed25519 signature over approval_message(role, draft_hash); required to approve
    key_id: str | None = None       # the device key that signed (checked against the role's active key)


class LoginIn(Strict):
    role: str
    passcode: str


class PasskeyFinishIn(Strict):
    challenge_id: str = Field(max_length=64)
    credential: dict                # the WebAuthn credential JSON from navigator.credentials.create()/get()


class ScreenIn(Strict):
    name: str = Field(max_length=200)
    account: str | None = Field(default=None, max_length=64)
    ifsc: str | None = Field(default=None, max_length=16)


@app.post("/api/screen")
def screen(body: ScreenIn, p: Principal = Depends(ANY)):
    """Public-data checks on a payee (OFAC snapshot, card Luhn/length, IFSC shape). Evidence only; not a compliance clearance."""
    return screen_payee(body.name, body.account, body.ifsc)


class DeviceIn(Strict):
    public_key: str                 # base64 Ed25519 public key; the private key never leaves the browser


class ConsentIn(Strict):
    step: int
    signature: str


class RedTeamIn(Strict):
    text: str
    tool_poison: dict | None = None


class DemoIn(Strict):
    run: str = "legit"   # legit | attack
    mode: str = "offline"   # offline | live (live = recorded model responses replayed from the fixture; no network)


class RateTargetIn(Strict):
    rate: float
    convert_cny: float


class TargetIdIn(Strict):
    target_id: str


class TickIn(Strict):
    days: int = Field(default=1, ge=-10**6, le=10**6)


class SpendSimIn(Strict):
    days: int = Field(default=21, ge=-10**6, le=10**6)


class SpendAddIn(Strict):
    desc: str = Field(max_length=200)
    amount_cny: float = Field(gt=0, le=1e7)


class RecoveryIn(Strict):
    obligation: str | None = None


class PlanIn(Strict):
    goal: str = Field(default="", max_length=2000)
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
    if S.passkeys.must_use(p.role):          # second factor: no cookie until the passkey assertion verifies
        return S.passkeys.login_begin(p.role, _rp(request)[0], token, p)
    _set_session_cookie(response, request, token)
    out = {"role": p.role, "expires_at": datetime.fromtimestamp(p.exp, timezone.utc).isoformat(timespec="seconds")}
    if return_token:           # for scripts/CLI that cannot keep a cookie jar; the browser UI never asks for it
        out["token"] = token
    return out


def _rp(request: HttpRequest) -> tuple[str, str]:
    """WebAuthn relying-party id and origin: OASIS_WEBAUTHN_RP_ID / OASIS_WEBAUTHN_ORIGIN when set (public deployment behind a
    proxy), otherwise derived from the Host header of this request."""
    host = request.headers.get("host", "localhost")
    rp_id = os.environ.get("OASIS_WEBAUTHN_RP_ID") or host.rsplit(":", 1)[0].strip("[]")
    return rp_id, os.environ.get("OASIS_WEBAUTHN_ORIGIN") or f"{request.url.scheme}://{host}"


def _set_session_cookie(response: Response, request: HttpRequest, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=S.auth.ttl_s, httponly=True, samesite="strict",
                        secure=_cookie_secure(request), path="/")


@app.get("/api/auth/passkey/status")
def passkey_status(p: Principal = Depends(ANY)):
    return {"registered": S.passkeys.count(p.role), "required_at_login": S.passkeys.must_use(p.role)}


@app.post("/api/auth/passkey/register/begin")
def passkey_register_begin(request: HttpRequest, p: Principal = Depends(ANY)):
    try:
        return S.passkeys.register_begin(p.role, _rp(request)[0])
    except PasskeyError as e:
        raise HTTPException(400, str(e))


@app.post("/api/auth/passkey/register/finish")
def passkey_register_finish(body: PasskeyFinishIn, request: HttpRequest, p: Principal = Depends(ANY)):
    rp_id, origin = _rp(request)
    try:
        out = S.passkeys.register_finish(p.role, body.challenge_id, body.credential, rp_id, origin)
    except PasskeyError as e:
        raise HTTPException(400, str(e))
    S.world.audit.append("passkey_registered", {"role": p.role, "count": out["count"]})
    return out


@app.post("/api/auth/passkey/login/finish")
def passkey_login_finish(body: PasskeyFinishIn, request: HttpRequest, response: Response, return_token: bool = False):
    key = f"login:{_client(request)}"
    if S.login_limiter.blocked(key):
        raise HTTPException(429, "too many failed logins; wait a minute", headers={"Retry-After": str(S.login_limiter.retry_after(key))})
    rp_id, origin = _rp(request)
    try:
        token, p = S.passkeys.login_finish(body.challenge_id, body.credential, rp_id, origin)
    except PasskeyError as e:
        S.login_limiter.record(key)
        raise HTTPException(401, str(e))
    _set_session_cookie(response, request, token)
    out = {"role": p.role, "expires_at": datetime.fromtimestamp(p.exp, timezone.utc).isoformat(timespec="seconds")}
    if return_token:
        out["token"] = token
    return out


@app.post("/api/auth/logout")
def logout(response: Response, p: Principal = Depends(ANY)):
    S.auth.revoke(p.jti)
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(request: HttpRequest):
    """Who am I? 200 {"role": null} when logged out (a probe, not an error); the role and device key otherwise."""
    p = _principal(request)
    if p is None:
        return {"role": None}
    out = {"role": p.role, "expires_at": datetime.fromtimestamp(p.exp, timezone.utc).isoformat(timespec="seconds")}
    if p.role in ("student", "parent"):
        k = S.approvers.active(p.role)
        out["device_key"] = {"key_id": k["key_id"], "public_key": k["public_key"]} if k else None
    if p.role == "student":
        out["language"] = ui_lang(S.world.passport.student.language) or "en"
    return out


class LanguageIn(Strict):
    language: str = Field(max_length=16)


@app.post("/api/student/language")
def set_language(body: LanguageIn, p: Principal = Depends(STUDENT)):
    """Save the student's interface language in the Passport (student.language). Only the whitelisted UI codes are accepted
    (`en`, `zh`; a region tag such as zh-CN is normalised); anything else is a 400 and changes nothing."""
    code = ui_lang(body.language)
    if code is None:
        raise HTTPException(400, f"unsupported language {body.language!r}; use one of {sorted(UI_LANGS)}")
    S.world.passport.student.language = code
    S.world.audit.append("language_set", {"language": code})
    S.save()
    return {"language": code, "supported": list(UI_LANGS)}


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


@app.get("/api/corridor/rules")
def corridor_rules(p: Principal = Depends(ANY)):
    """Every corridor rule with its value, precise source, retrieval date, confidence and status (confirmed-primary |
    researched-secondary | unconfirmed). Read-only view of the YAML data file; any logged-in role may read it."""
    return {**corridor.rules_public(), "note": MOCK_NOTE}


@app.get("/api/approvers")
def approvers(p: Principal = Depends(ANY)):
    return {"keys": [{k: v for k, v in rec.items()} for rec in S.approvers.public_view()]}


# ------------------------------------------------------------------ state
@app.get("/api/state")
def state(p: Principal = Depends(VIEWERS), ui: str = UI):
    w = S.world
    if p.role == "parent":      # least privilege: the parent sees only what concerns them
        return loc.localize_state(jsonable_encoder({
            "mock_note": MOCK_NOTE, "role": "parent", "now": w.now_iso(),
            "persistence": {"enabled": S.store is not None, "path": None},
            "proofs": _parent_proofs(),
            "pending": [_pending_view(k, v) for k, v in S.pending.items() if "parent" in v["required"]]}), ui)
    p_ = w.passport
    quotes = rank(quote_routes(w.rates, 100000, w.today, None, w.day_index))
    burn, basis = monthly_burn(p_)
    decoys = w.canaries.decoy_payees if w.canaries else set()
    sp = spending.summarize(p_)
    return loc.localize_state(jsonable_encoder({
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
        "currency_view": currency_view(p_, w.rates.mid(w.day_index), provenance(w.rates, w.day_index), w.today,
                                       w.rates.usd_crosses(w.day_index)),
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
    }), ui)


@app.post("/api/reset")
def reset(p: Principal = Depends(STUDENT)):
    S.reset()
    return {"ok": True}


# ------------------------------------------------------------------ pipeline
def _intake(body: IntakeIn) -> dict:
    return _run_intake(Request(body.text, source=body.source, remitter=body.remitter))


def _run_intake(req: Request, notes: list[str] | None = None) -> dict:
    """Shared by the paste box, image, email and Telegram intake: one pipeline, one pending-approval store."""
    o = _out(S.agent.handle(req))
    o["pending_id"] = _store_pending(req, o)
    if req.channel:
        o["channel"] = req.channel
    if notes:
        o["intake_notes"] = notes
    S.save()
    return o


def _vision_reader():
    llm = S.world.llm if isinstance(S.world.llm, GroqLLM) else None
    try:
        v = VisionExtractor(llm)
    except VisionUnavailable:
        return None
    return v.to_text


# ------------------------------------------------------------------ real inbound channels (Telegram bot, IMAP mailbox)
CHANNELS: dict = {"telegram": None, "imap": None, "stop": threading.Event(), "threads": []}


def _inbound(text: str, channel: dict, notes: list) -> str:
    """Called from the channel threads: same pipeline, same single-writer lock as an HTTP request. Returns a chat summary."""
    with _STATE_LOCK:
        o = _run_intake(Request(text, source=channel["kind"], remitter="student", channel=channel), notes)
        lang = ui_lang(S.world.passport.student.language) or "en"
    return chat_summary(loc.localize_outcome(o, lang))


def start_channels() -> None:
    """Start the Telegram bot / IMAP poller threads for the channels that are configured in the environment. Idempotent."""
    from ..intake.imap_poll import ImapPoller
    from ..intake.telegram import TelegramBot
    if CHANNELS["threads"]:
        return
    stop = CHANNELS["stop"]
    stop.clear()
    vision = _vision_reader()
    tok = os.environ.get("OASIS_TELEGRAM_TOKEN")
    if tok:
        CHANNELS["telegram"] = bot = TelegramBot(tok, _inbound, S.tg_store, vision=vision)

        def run_bot():
            while not stop.is_set():
                if bot.poll_once(timeout=20) == 0 and bot.last_error:
                    stop.wait(5)
        CHANNELS["threads"].append(threading.Thread(target=run_bot, name="oasis-telegram", daemon=True))
    host = os.environ.get("OASIS_IMAP_HOST")
    if host:
        allowed = {a for a in os.environ.get("OASIS_IMAP_ALLOWED_SENDERS", "").split(",") if a.strip()}
        CHANNELS["imap"] = poller = ImapPoller(host, os.environ.get("OASIS_IMAP_USER", ""), os.environ.get("OASIS_IMAP_PASSWORD", ""),
                                              _inbound, allowed, vision=vision,
                                              require_auth=os.environ.get("OASIS_IMAP_REQUIRE_AUTH", "1") != "0")
        every = max(15, int(os.environ.get("OASIS_IMAP_INTERVAL_S", "60")))

        def run_imap():
            while not stop.is_set():
                poller.poll_once()
                stop.wait(every)
        CHANNELS["threads"].append(threading.Thread(target=run_imap, name="oasis-imap", daemon=True))
    for t in CHANNELS["threads"]:
        t.start()


@app.get("/api/intake/channels")
def intake_channels(p: Principal = Depends(STUDENT)):
    """Which real channels are on (never any secret): the email upload is always available; Telegram and IMAP need env config."""
    bot, imap = CHANNELS["telegram"], CHANNELS["imap"]
    return {"email_upload": True,
            "telegram": {"configured": bot is not None, "paired_chats": S.tg_store.count(),
                         "processed": bot.processed if bot else 0, "last_error": bot.last_error if bot else None},
            "imap": {"configured": imap is not None, "allowed_senders": sorted(imap.allowed) if imap else [],
                     "require_auth": imap.require_auth if imap else None, "processed": imap.processed if imap else 0,
                     "ignored": imap.ignored if imap else 0, "last_error": imap.last_error if imap else None,
                     "recent": imap.results[-5:] if imap else []}}


@app.post("/api/intake/telegram/pair")
def telegram_pair(p: Principal = Depends(STUDENT)):
    if CHANNELS["telegram"] is None:
        raise HTTPException(400, "Telegram is not configured on this server (set OASIS_TELEGRAM_TOKEN)")
    S.world.audit.append("telegram_pair_code_issued", {})
    return S.tg_store.new_code()


@app.post("/api/intake/telegram/unpair")
def telegram_unpair(p: Principal = Depends(STUDENT)):
    S.tg_store.clear()
    S.world.audit.append("telegram_unpaired", {})
    return {"paired_chats": 0}


@app.post("/api/intake/email")
async def intake_email(file: UploadFile = File(...), remitter: str = "student", p: Principal = Depends(STUDENT), ui: str = UI):
    """A real email as a .eml file (in a mail client: Save as / Download message). Same pipeline as the paste box; the
    sender's authentication results, a diverging Reply-To and hidden text become risk evidence, never authority."""
    from ..intake.mail import MAX_RAW, parse_eml
    data = await file.read(MAX_RAW + 1)
    try:
        pm = parse_eml(data, vision=_vision_reader())
    except ValueError as e:
        raise HTTPException(413 if "large" in str(e) else 400, str(e))
    return loc.localize_outcome(_run_intake(Request(pm.text, source="email", remitter=remitter, channel=pm.channel), pm.notes), ui)


@app.post("/api/intake")
def intake(body: IntakeIn, p: Principal = Depends(STUDENT), ui: str = UI):
    return loc.localize_outcome(_intake(body), ui)


@app.post("/api/intake/image")
async def intake_image(file: UploadFile = File(...), remitter: str = "student", p: Principal = Depends(STUDENT), ui: str = UI):
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
        return loc.localize_outcome(o, ui)
    return loc.localize_outcome(_intake(IntakeIn(text=text, remitter=remitter, source="screenshot")), ui)


@app.post("/api/approve")
def approve(body: ApproveIn, p: Principal = Depends(STUDENT_PARENT), ui: str = UI):
    """Approve (or decline) a held payment AS THE ROLE OF THE SESSION. Approving needs a signature, made with that
    role's registered device key, over the pending payment's exact draft hash. The role string grants nothing."""
    role = p.role
    item = S.pending.get(body.pending_id)
    if not item:
        raise HTTPException(404, "unknown pending id")
    dismiss_dup = (not body.approve) and role == "student" and DUP_CONFIRM in item["required"]
    if role not in item["required"] and not dismiss_dup:
        if DUP_CONFIRM in item["required"]:
            raise HTTPException(403, "this looks like a duplicate of a payment you already made: choose Pay again to "
                                     "start a deliberate second payment; it cannot be approved directly")
        raise HTTPException(403, f"this payment does not need the {role}'s approval")
    na = (item["outcome"].get("draft") or {}).get("not_after")
    if body.approve and na and datetime.fromisoformat(S.world.now_iso()) > datetime.fromisoformat(na):
        # The signed draft has an expiry. Running it now would make the executor freeze the genuine obligation and show a
        # "Why was I stopped?" card for what is only a stale approval, so retire it cleanly and ask for a fresh request.
        S.world.audit.append("approval_expired", {"pending_id": body.pending_id, "role": role, "not_after": na})
        S.pending.pop(body.pending_id)
        S.save()
        raise HTTPException(410, f"this payment draft expired at {na}; submit the invoice again to get a fresh one to approve")
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
    return loc.localize_outcome(o, ui)


class PayAgainIn(Strict):
    pending_id: str


@app.post("/api/pay-again")
def pay_again(body: PayAgainIn, p: Principal = Depends(STUDENT), ui: str = UI):
    """The student's explicit "pay again" for a suspected duplicate (R17). It re-runs the held request with `pay_again`
    set and a FRESH draft: the result is an ordinary held payment, with the duplicate warning attached, that must still
    be signed with the student's device key. Nothing is paid here."""
    item = S.pending.get(body.pending_id)
    if not item:
        raise HTTPException(404, "unknown pending id")
    if DUP_CONFIRM not in item["required"]:
        raise HTTPException(409, "this item is not a suspected duplicate")
    req = item["request"]
    req.pay_again, req.draft, req.signed_approvals = True, None, ()
    S.world.audit.append("pay_again_requested", {"pending_id": body.pending_id, "duplicate": item["outcome"].get("duplicate")})
    o = _out(S.agent.handle(req))
    S.pending.pop(body.pending_id)
    o["pending_id"] = _store_pending(req, o)
    S.save()
    return loc.localize_outcome(o, ui)


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
TARGET_RE_ZH = re.compile(r"(?:汇率|rate)[^\d]{0,12}(0\.\d+)[^\d]{0,12}(?:兑换|换成|转换)\s*(?:¥|CNY|RMB|人民币)?\s*([\d,]+(?:\.\d+)?)"
                          r"|(?:兑换|换成|转换)\s*(?:¥|CNY|RMB|人民币)?\s*([\d,]+(?:\.\d+)?)[^\d]{0,24}?(?:汇率|rate)[^\d]{0,12}(0\.\d+)", re.I)
TARGET_RE = re.compile(r"convert\s+(?:cny\s*|¥|rmb\s*)?([\d,]+(?:\.\d+)?)[^.\n]*?(?:rate|inr)[^\d]{0,30}?(0\.\d+)", re.I)


_STATUS_ZH = {"paid": "已支付", "held": "已暂缓，等待批准", "frozen": "已冻结", "rejected": "已拒绝", "needs_verification": "需要验证"}
_OBL_ZH = {"tuition": "学费", "rent": "房租", "deposit": "押金", "living": "生活费", "family_support": "家庭资助"}


@app.post("/api/chat")
def chat(body: ChatIn, p: Principal = Depends(STUDENT), ui: str = UI):
    zh = ui == "zh"
    S.chat.append({"role": "student", "text": body.message})
    if INVOICE_HINT.search(body.message):
        res = loc.localize_outcome(_intake(IntakeIn(text=body.message)), ui)
        if zh:
            reply = (f"我已检查完毕。状态：{_STATUS_ZH.get(res['status'], res['status'])}。" +
                     (f" {res['card']['text']}" if res.get("card") else "") +
                     (f" 证明包 {res['proof_id']} 已就绪。" if res.get("proof_id") else ""))
        else:
            reply = (f"I checked it. Status: {res['status']}." +
                     (f" {res['card']['text']}" if res.get("card") else "") +
                     (f" Proof pack {res['proof_id']} is ready." if res.get("proof_id") else ""))
        S.chat.append({"role": "oasis", "text": reply, "outcome": res})
        return {"reply": reply, "outcome": res}
    m = TARGET_RE.search(body.message)
    mz = None if m else TARGET_RE_ZH.search(body.message)
    if mz:
        m = (mz.group(2), mz.group(1)) if mz.group(1) else (mz.group(3), mz.group(4))
    if m:
        amount, rate = ((float(m[0].replace(",", "")), float(m[1])) if isinstance(m, tuple)
                        else (float(m.group(1).replace(",", "")), float(m.group(2))))
        t = S.agent.set_rate_target(rate, amount)
        S.save()
        lim = S.world.passport.rules.tier1_auto_convert_cny
        if zh:
            reply = (f"已设定汇率目标：我会关注 INR 对 CNY 的汇率，当它达到 {rate:.4f} 时，" +
                     (f"自行兑换 ¥{amount:,.0f}（在您的 1 级自动额度之内）。" if amount <= lim
                      else f"在您批准之后兑换 ¥{amount:,.0f}（超过 ¥{lim:,.0f} 的自动额度）。") +
                     " 我不会预测汇率，只会按您设定的目标行动。")
        else:
            reply = (f"Rate target set: I will watch INR to CNY and, when it reaches {rate:.4f}, convert CNY {amount:,.0f} "
                     + ("on my own (within your Tier-1 limit)." if amount <= lim else f"after you approve it (above your CNY {lim:,.0f} auto limit).")
                     + " I do not predict rates; I only act on your target.")
        S.chat.append({"role": "oasis", "text": reply, "target": t})
        return {"reply": reply, "target": t}
    w = S.world
    pp = w.passport
    tr_ = triggers(pp, w.rates, w.today, w.day_index)
    pend = [o for o in pp.obligations if o.status != "paid"]
    best = rank(quote_routes(w.rates, 100000, w.today, None, w.day_index))[0]
    if zh:
        alerts = loc.localize_triggers([t.__dict__ for t in tr_], ui)
        reply = (f"您有 ₹{pp.balance('INR'):,.0f} 和 ¥{pp.balance('CNY'):,.0f}。"
                 f"即将到期：" + "；".join(f"{_OBL_ZH.get(o.type, o.type)} ¥{o.amount:,.0f}，到期日 {o.due}" for o in pend) + "。"
                 f"付清应付款项后的资金可维持：{runway_months(pp, w.rates, w.day_index):.1f} 个月。"
                 f"当前最便宜且能按时到账的路线：{route_zh(best.route.name)}。"
                 + ("提醒：" + " ".join(a["message"] for a in alerts) if alerts else "目前没有提醒。") +
                 " 把任何发票或消息转发给我，我会在付款之前先检查。"
                 "您也可以这样说：“convert 2000 when the rate reaches 0.0700”（汇率达到 0.0700 时兑换 2000）。")
    else:
        reply = (f"You have INR {pp.balance('INR'):,.0f} and CNY {pp.balance('CNY'):,.0f}. "
                 f"Upcoming: " + "; ".join(f"{o.type} CNY {o.amount:,.0f} due {o.due}" for o in pend) + ". "
                 f"Runway after obligations: {runway_months(pp, w.rates, w.day_index):.1f} months. "
                 f"Cheapest on-time route right now: {best.route.name}. "
                 + (" Alerts: " + " ".join(t.message for t in tr_) if tr_ else " No alerts.") +
                 " Forward me any invoice or message and I'll check it before anything is paid. "
                 "You can also say: 'convert 2000 when the rate reaches 0.0700'.")
    S.chat.append({"role": "oasis", "text": reply})
    return {"reply": reply}


# ------------------------------------------------------------------ agentic planning (spec step 2)
def _plan_view(world, rec: dict, ui: str = "en") -> dict:
    consents = [{**d, "signed_by": ((rec.get("consents") or {}).get(str(d["step"])) or {}).get("key_id")}
                for d in plan_exec.parent_consents_needed(rec)] if rec.get("id") else []
    return loc.localize_plan(jsonable_encoder({**rec, "step_status": plan_exec.step_statuses(world, rec), "parent_consents": consents}), ui)


@app.get("/api/plan/scenarios")
def plan_scenarios(p: Principal = Depends(STUDENT_JUDGE), ui: str = UI):
    return loc.localize_scenarios([{"id": s.id, "title": s.title, "description": s.description, "goal": s.goal, "tests": s.tests}
                                   for s in SCENARIOS.values()], ui)


@app.post("/api/plan")
def plan_create(body: PlanIn, p: Principal = Depends(STUDENT), ui: str = UI):
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
        return _plan_view(w, rec, ui)          # scenario worlds are throwaway: not stored, not executable
    planner = AgenticPlanner(S.world.llm) if live else DeterministicPlanner()
    rec = build_record(S.world, planner.plan(S.world, body.goal), body.goal)
    S.save()
    return _plan_view(S.world, rec, ui)


@app.get("/api/plans")
def plans_list(p: Principal = Depends(STUDENT_JUDGE), ui: str = UI):
    return [_plan_view(S.world, r, ui) for r in S.world.plans]


@app.get("/api/plan/{plan_id}")
def plan_get(plan_id: str, p: Principal = Depends(STUDENT_JUDGE), ui: str = UI):
    rec = plan_exec.get_plan(S.world, plan_id)
    if rec is None:
        raise HTTPException(404, "no such plan")
    return _plan_view(S.world, rec, ui)


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
    if body.rate >= 10 or body.convert_cny > 1e7:
        raise HTTPException(400, "rate must be below 10 and convert_cny at most 10,000,000")
    t = S.agent.set_rate_target(body.rate, body.convert_cny)
    S.save()
    return t


@app.post("/api/rate-target/approve")
def rate_target_approve(body: TargetIdIn, p: Principal = Depends(STUDENT)):
    res = S.agent.approve_rate_target(body.target_id)
    S.save()
    return jsonable_encoder(res)


@app.post("/api/autonomy/tick")
def autonomy_tick(body: TickIn, p: Principal = Depends(STUDENT), ui: str = UI):
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
    return jsonable_encoder({"days": days, "now": S.world.now_iso(), "actions": loc.localize_actions(out, ui)})


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
ATTEMPTS_MAX_BYTES = 50_000_000      # stop appending (never block the console) once the attempts file is this big


def _log_attempt(rec: dict) -> None:
    """Append one red-team attempt to the attempts store (data/redteam_attempts.jsonl, git-ignored). Failure to write
    never blocks the console. One JSON object per line (json.dumps escapes newlines, so an attempt text cannot forge a
    second record); the file is size-capped so a flood of refused attempts cannot fill the disk."""
    try:
        if S.attempts_path.exists() and S.attempts_path.stat().st_size > ATTEMPTS_MAX_BYTES:
            return
        S.attempts_path.parent.mkdir(parents=True, exist_ok=True)
        with S.attempts_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True, ensure_ascii=True, default=str) + "\n")   # ASCII on disk: U+2028 / U+0085 cannot split a record
    except OSError:
        pass


@app.post("/api/redteam")
def redteam(body: RedTeamIn, request: HttpRequest, p: Principal = Depends(JUDGE), ui: str = UI):
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
        if S.redteam_log_limiter.allow(client):       # a flood of refused attempts is logged at 5/min, shortened
            _log_attempt({**base, "text": body.text[:200], "text_sha256": hashlib.sha256(body.text.encode()).hexdigest(),
                          "tool_poison": None, "outcome": "rate_limited"})
        raise HTTPException(429, f"rate limit: at most {S.redteam_per_minute} attempts per minute",
                            headers={"Retry-After": str(S.redteam_limiter.retry_after(client))})
    box = S.redteam_box(p.jti)          # this judge session's own sandbox world
    w = box.world
    before = w.ledger.money_lost()
    o = _out(box.agent.handle(Request(body.text, tool_poison=body.tool_poison), SimulatedHumans()))
    o["money_lost_this_attempt"] = round(w.ledger.money_lost() - before, 2)
    d = o.get("decision") or {}
    entry = {"text": body.text[:500], "status": o["status"], "lost": o["money_lost_this_attempt"]}
    box.log.append(entry)
    del box.log[:-200]
    _log_attempt({**base, "text": body.text, "tool_poison": body.tool_poison, "outcome": "ran", "status": o["status"],
                  "label": o.get("label"), "rule": d.get("rule") or (o.get("card") or {}).get("rule"),
                  "risk_score": (o.get("risk") or {}).get("score"), "detected": o.get("detected"),
                  "canary_kinds": [h.get("kind") for h in o.get("canary_hits") or []],
                  "followed_injection": o.get("followed_injection"), "money_lost": o["money_lost_this_attempt"]})
    return loc.localize_outcome(o, ui)


@app.get("/api/redteam/log")
def redteam_log(p: Principal = Depends(JUDGE)):
    box = S.redteam_box(p.jti)
    return {"attempts": box.log, "total_lost": box.world.ledger.money_lost(),
            "limits": {"per_minute": S.redteam_per_minute, "max_text_bytes": REDTEAM_MAX_TEXT,
                       "max_worlds": S.redteam_max_worlds},
            "isolation": "your attempts and your sandbox ledger are private to this login session"}


# ------------------------------------------------------------------ proof + audit
def _parent_proofs() -> list[str]:
    """Least privilege: the parent sees only the proof packs of payments they co-approved."""
    return [i for i, pk in S.world.proofs.items()
            if any(a.get("role") == "parent" for a in (pk.get("intent") or {}).get("approvals") or [])]


@app.get("/api/proof/{intent_id}")
def proof(intent_id: str, p: Principal = Depends(VIEWERS)):
    if p.role == "parent" and intent_id not in _parent_proofs():
        raise HTTPException(403, "the parent can open only the proof packs of payments they approved")
    return _proof(intent_id, p)


def _proof(intent_id: str, p: Principal | None = None) -> dict:
    """A judge session looks in its own red-team sandbox first (intent ids repeat across sandboxes), then the shared lookup."""
    own = S.redteam_boxes.get(p.jti) if p is not None and p.role == "judge" else None
    pk = (own.world.proofs.get(intent_id) if own else None) or S.world.proofs.get(intent_id) or next((w.proofs[intent_id] for w in S.redteam_worlds() if intent_id in w.proofs), None)
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
def proof_verify(intent_id: str, request: HttpRequest):
    """PUBLIC and harmless: returns only check results for a pack that already exists."""
    return _verify_pinned(_proof(intent_id, _principal(request)))


@app.post("/api/proof/verify")
def proof_verify_upload(pack: dict):
    """PUBLIC: verifies an uploaded pack against the pinned keys. Needs no secrets and changes no state."""
    return _verify_pinned(pack)


class ReliabilityIn(Strict):
    include_name: bool = False       # default: pseudonymous id only
    share_amounts: bool = False      # default: amount bands, not exact amounts


@app.post("/api/reliability/record")
def reliability_create(body: ReliabilityIn, p: Principal = Depends(STUDENT)):
    """Student only. Signs a payment-reliability record of the payments that completed the full pipeline with a verified
    proof pack. It is not a credit score."""
    rec = build_reliability_record(S.world, include_name=body.include_name, share_amounts=body.share_amounts)
    S.reliability_last = rec
    return rec


@app.get("/api/reliability/mine")
def reliability_mine(p: Principal = Depends(STUDENT)):
    return {"record": S.reliability_last, "eligible_payments": len(eligible_payments(S.world))}


@app.post("/api/reliability/verify")
def reliability_verify(record: dict):
    """PUBLIC: verifies a record against THIS server's pinned fingerprint and its proof packs. Needs no secrets, changes no state."""
    res = verify_reliability_record(record, S.trusted_fingerprints(), lambda pid: S.world.proofs.get(pid) if isinstance(pid, str) else None,
                                    pack_verifier=lambda pk: bool(_verify_pinned(pk).get("ok")))
    res["pinned_fingerprint"] = S.world.trust_fingerprint()
    return res


# ------------------------------------------------------------------ multi-currency wallet (MOCK pricing)
class FxIn(Strict):
    amount: float
    src: str = Field(alias="from", max_length=3)
    dst: str = Field(alias="to", max_length=3)


@app.post("/api/fx/quote")
def fx_quote_ep(body: FxIn, p: Principal = Depends(STUDENT)):
    try:
        return fx_quote(body.amount, body.src, body.dst, table_for(S.world.rates, S.world.day_index)).to_dict()
    except FxError as e:
        raise HTTPException(400, str(e))


@app.post("/api/fx/convert")
def fx_convert(body: FxIn, p: Principal = Depends(STUDENT)):
    """Student only: moves money between the student's OWN sandbox balances, so it never pays anyone. Audited."""
    try:
        rec = currency_mod.convert(S.world, body.amount, body.src, body.dst)
    except FxError as e:
        raise HTTPException(400, str(e))
    S.save()
    return rec


# ------------------------------------------------------------------ Trust Pass (portable payment reputation)
class TrustIssueIn(Strict):
    claims: list[str] = Field(max_length=len(tp.CLAIMS))
    thresholds: dict[str, int] = Field(default_factory=dict, max_length=len(tp.THRESHOLDS))
    audience: str | None = Field(default=None, max_length=tp.MAX_AUDIENCE)


class TrustShareIn(Strict):
    presentation: dict


def _tp_verify(pres) -> dict:
    res = tp.verify_presentation(pres, S.trusted_fingerprints(), S.world.today.isoformat(),
                                 lambda pid: S.world.proofs.get(pid) if isinstance(pid, str) else None,
                                 pack_verifier=lambda pk: bool(_verify_pinned(pk).get("ok")))
    res["pinned_fingerprint"] = S.world.trust_fingerprint()
    return res


@app.get("/api/trust-pass/claims")
def trust_claims(p: Principal = Depends(STUDENT)):
    w = S.world
    c = tp.compute_claims(tp._entries(w), w.today.isoformat())
    return {"claims": [{"id": k, "value": v, "statement": tp.statement(k, v)} for k, v in c.items()],
            "thresholds": tp.threshold_options(c), "suggested_asks": tp.suggested_asks(c), "ladder": tp.ladder(w),
            "valid_days": tp.VALID_DAYS}


@app.post("/api/trust-pass/issue")
def trust_issue(body: TrustIssueIn, p: Principal = Depends(STUDENT)):
    """Student only. Returns the holder copy; the salts in `disclosures` are what lets the student reveal payments later."""
    try:
        holder = tp.issue(S.world, body.claims, body.audience, body.thresholds)
    except ValueError as e:
        raise HTTPException(400, str(e))
    S.save()
    return holder


class TrustZkIn(Strict):
    credential: dict
    openings: dict                  # the holder's private counts and blinding factors, from the issue response
    kind: str = Field(max_length=8)
    k: int = Field(ge=1, le=100000)


@app.post("/api/trust-pass/zk-prove")
def trust_zk_prove(body: TrustZkIn, p: Principal = Depends(STUDENT)):
    """Student only: one zero-knowledge threshold claim ('at least 94% on time', 'at least 5 payments') for a credential the
    student holds. Refused (400) if the record does not meet it. The counts never leave the student's own request."""
    try:
        return tp.zk_prove(body.credential, body.openings, body.kind, body.k)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/trust-pass/share")
def trust_share(body: TrustShareIn, p: Principal = Depends(STUDENT)):
    """Student only. Stores a presentation that verifies against this server, under a short code for a QR."""
    res = _tp_verify(body.presentation)
    if not res["ok"]:
        raise HTTPException(400, "only a presentation that verifies against this server can be shared")
    code = tp.share(S.trust_shares, body.presentation, S.world.today.isoformat())
    S.save()
    return {"code": code, "valid_until": body.presentation["credential"]["valid_until"]}


@app.get("/api/trust-pass/check/{code}")
def trust_check(code: str):
    """PUBLIC (what the QR opens): re-verifies the shared presentation now. The code only locates it."""
    hit = S.trust_shares.get(code) if len(code) <= 32 else None
    if hit is None:
        raise HTTPException(404, "unknown or expired code")
    return _tp_verify(hit["presentation"])


@app.post("/api/trust-pass/verify")
def trust_verify(pres: dict):
    """PUBLIC: verifies a pasted Trust Pass presentation against THIS server's pinned key and simulated clock."""
    return _tp_verify(pres)


@app.get("/api/trust-pass/ladder")
def trust_ladder(p: Principal = Depends(STUDENT_PARENT)):
    return tp.ladder(S.world)


@app.post("/api/trust-pass/ladder/accept")
def trust_ladder_accept(p: Principal = Depends(PARENT)):
    """Parent only: accepting the earned threshold is the parent's decision; the student cannot raise it."""
    try:
        r = tp.accept_ladder(S.world)
    except ValueError as e:
        raise HTTPException(400, str(e))
    S.save()
    return r


@app.get("/api/audit")
def audit(p: Principal = Depends(STUDENT_JUDGE)):
    return {"entries": S.world.audit.entries}


@app.get("/api/audit/verify")
def audit_verify(p: Principal = Depends(VIEWERS)):
    r = verify_chain(S.world.audit.entries)
    return {**r.__dict__, "ok": r.ok, "head": S.world.audit.head()}


# ------------------------------------------------------------------ FlightPath (advisory; moves no money)
class FlightPathIn(BaseModel):
    required_cny: float = Field(gt=0)
    due_in_days: int | None = None


@app.post("/api/flightpath/compare")
def flightpath_compare(body: FlightPathIn, p: Principal = Depends(STUDENT_JUDGE)):
    today = S.world.today
    due = today + timedelta(days=body.due_in_days) if body.due_in_days is not None else None
    return {"label": "MOCK rates and deductions", "options": jsonable_encoder(
        [{**o.__dict__, "route": o.route.name, "route_id": o.route.id} for o in fpath.compare_routes(S.world.rates, body.required_cny, today, due)])}


@app.get("/api/flightpath/benchmark")
def flightpath_benchmark(p: Principal = Depends(STUDENT_JUDGE)):
    f = REPORTS / "flightpath.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


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
                           for k, v in out["planning"].items() if isinstance(v, dict) and "summary" in v}   # e.g. "experiment" has no summary
    return out


# The scripted demo REPLACES the persisted sandbox with its own fixed world (and wipes the stored state), so it is a
# STUDENT action; judges see the same scripted runs through the read-only demo/state view. The demo world has its own
# simulated approver devices: its "humans" are in-process, exactly like the benchmark's.
@app.post("/api/demo/start")
def demo_start(body: DemoIn, p: Principal = Depends(STUDENT), ui: str = UI):
    """Reset to the scripted demo world (fixed seed, fixed MOCK data) and return the step list. `mode` "offline" (default)
    uses the offline LLM; "live" replays recorded qwen/qwen3.8-27b responses from the fixture (no network)."""
    return loc.localize_demo_info(_demo_start(body), ui)


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
def demo_next(p: Principal = Depends(STUDENT), ui: str = UI):
    if not S.demo:
        raise HTTPException(409, "no demo running; POST /api/demo/start first")
    res = S.demo.next()
    S.save()
    return loc.localize_demo_step(jsonable_encoder(res), ui)


@app.get("/api/demo/state")
def demo_state(p: Principal = Depends(STUDENT_JUDGE), ui: str = UI):
    if not S.demo:
        return {"active": False}
    return loc.localize_demo_info(jsonable_encoder({
        "active": True, "run": S.demo.run, "mode": S.demo.mode, "index": S.demo.index, "total": len(S.demo.titles),
        "done": S.demo.done, "steps": S.demo.titles, "results": [loc.localize_demo_step(r, ui) for r in S.demo.results]}), ui)


@app.post("/api/demo/run")
def demo_run(body: DemoIn, p: Principal = Depends(STUDENT), ui: str = UI):
    """Play a whole scripted demo run in one call (same result every time, no network)."""
    _demo_start(body)
    res = S.demo.run_all()
    S.save()
    return loc.localize_demo_step(jsonable_encoder(res), ui)


@app.post("/api/demo/reset")
def demo_reset(p: Principal = Depends(STUDENT)):
    """Back to a clean (non-demo) sandbox; also wipes the SQLite state."""
    S.reset()
    return {"ok": True}


@app.get("/api/explain/savings")
def savings(p: Principal = Depends(STUDENT_JUDGE), ui: str = UI):
    convs = [e["data"] for e in S.world.audit.entries if e["kind"] == "conversion"]
    tot = round(sum(c["saved_cny"] for c in convs), 2)
    return {"conversions": convs, "total_saved_cny": tot,
            "text": explain_template("savings", {"saved_cny": tot, "saved_pct": convs[-1]["saved_pct"] if convs else 0}, ui)}


DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
