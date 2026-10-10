"""Live demo mode: a real model (Groq qwen/qwen3.8-27b) made repeatable by REPLAYING recorded responses.

The Demo tab's "live-replay" mode runs the same scripted scenarios as the offline demo, but extraction (the model's JSON is
primary), the optional AI risk scorer and the planner (native tool calling) are real model calls whose answers were
recorded once into a small committed fixture (`eval/fixtures/demo_cache/*.json`: model name, response text, recording
date; no prompts, keys or organisation ids) and are read back from it with NO network. If a response is missing from
the fixture, that step falls back to the offline parser / heuristic scorer / deterministic planner and says so.

Record (the only time this module touches the network; needs GROQ_API_KEY and spends free-tier tokens):

    PYTHONPATH=. python -m eval.record_demo_fixture
"""
from __future__ import annotations
import time
from pathlib import Path
from types import SimpleNamespace

from .. import config
from .llm import Extraction, GroqLLM, OfflineLLM, QuotaExhausted, UsageLedger, explain_template

FIXTURE_DIR = config.ROOT / "eval" / "fixtures" / "demo_cache"
MODES = ("offline", "live")
OFFLINE_LABEL = "offline parser (deterministic rules, no AI model)"


class ReplayMiss(RuntimeError):
    """The fixture holds no recorded response for this request."""


class _ReplayOnlyClient:
    """Stands in for the Groq client in replay mode: any call that was not served from the fixture is a miss. It cannot
    reach the network, so replay needs neither a key nor a connection."""

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    @staticmethod
    def _create(**_kw):
        raise ReplayMiss("no recorded response for this request")


def short_model(model: str | None) -> str:
    return (model or "?").split("/")[-1]


def family(model: str | None) -> str:
    m = (model or "").casefold()
    return "Qwen" if "qwen" in m else "GPT-OSS" if "gpt-oss" in m else "Model"


class DemoLiveLLM(GroqLLM):
    """GroqLLM over a fixture directory. Replay (default) never touches the network; `record=True` uses the real client and
    writes new responses into the fixture directory (counted against the shared daily-token ledger)."""
    name = "groq-demo-replay"

    def __init__(self, fixture_dir: Path | None = None, record: bool = False, token_cap: int | None = None, **kw):
        self.record = record
        self.fixture_dir = Path(fixture_dir) if fixture_dir else FIXTURE_DIR
        kw.setdefault("extract_mode", "llm")
        kw.setdefault("llm_risk", True)
        if not record:
            kw.update(client=_ReplayOnlyClient(), rpm=0)
        super().__init__(cache_dir=self.fixture_dir, **kw)
        if record:
            # new responses must count against the SAME daily ledger as every other live call
            self.usage = UsageLedger(config.DATA_DIR / "llm_cache" / "usage.json")
        self.token_cap = token_cap
        self._start_tokens = self.usage.day()["tokens"]
        self.events: list[dict] = []

    # -- provenance ------------------------------------------------------------------------------------
    def _logged(self, kind: str, fn):
        if self.record and self.token_cap is not None and self.usage.day()["tokens"] - self._start_tokens >= self.token_cap:
            raise QuotaExhausted(f"recording token cap reached ({self.token_cap})")
        before = self.cache_hits
        try:
            out = fn()
        except QuotaExhausted:
            raise
        except Exception:
            self.events.append({"kind": kind, "source": "missing", "model": None, "recorded": None})
            raise
        replayed = self.cache_hits > before
        self.events.append({"kind": kind, "source": "replayed" if replayed else "live", "model": self.last_model,
                            "recorded": self.last_recorded if replayed else time.strftime("%Y-%m-%d")})
        return out

    def _chat(self, system, user, *a, **k):
        kind = ("extract" if system == self.EXTRACT_SYSTEM else "risk" if system == self.RISK_SYSTEM else "other")
        return self._logged(kind, lambda: super(DemoLiveLLM, self)._chat(system, user, *a, **k))

    def chat_tools(self, *a, **k):
        return self._logged("plan", lambda: super(DemoLiveLLM, self).chat_tools(*a, **k))

    # -- behaviour ---------------------------------------------------------------------------------------
    def extract(self, text: str, tool_context: dict | None = None) -> Extraction:
        ext = super().extract(text, tool_context)
        if ext.call_failed:       # nothing recorded (or the call failed): the offline parser, and the step says so
            return OfflineLLM.extract(self, text, tool_context)
        return ext

    def explain(self, kind: str, ctx: dict, language: str = "en") -> str:
        return explain_template(kind, ctx, language)       # explanations stay templated: fewer recorded calls, same facts

    def draft_recovery(self, ctx: dict) -> str | None:
        return None

    # -- what to show on screen --------------------------------------------------------------------------
    def drain_events(self) -> list[dict]:
        ev, self.events = self.events, []
        return ev


KIND_NAMES = {"extract": "Extraction", "risk": "Risk score", "plan": "Plan", "other": "Text"}
MISS_NAMES = {"extract": "offline parser", "risk": "heuristic scorer", "plan": "deterministic planner", "other": "template"}


def ai_summary(mode: str, events: list[dict]) -> dict:
    """The on-screen provenance of one demo step: which mode and which model produced each part."""
    if mode != "live":
        return {"mode": "offline", "label": OFFLINE_LABEL, "items": [], "replay_misses": 0}
    groups: dict[tuple, int] = {}
    for e in events:
        groups[(e["kind"], e["source"], e.get("model"), e.get("recorded"))] = \
            groups.get((e["kind"], e["source"], e.get("model"), e.get("recorded")), 0) + 1
    items = []
    for (kind, source, model, rec), n in groups.items():
        name = KIND_NAMES.get(kind, kind)
        if source == "missing":
            label = f"{MISS_NAMES.get(kind, 'offline')} (no recorded response; offline fallback)"
        else:
            how = f"replayed from recorded response {rec}" if source == "replayed" else "live call, just recorded"
            label = f"{family(model)} {short_model(model)} — {how}"
        items.append({"kind": kind, "source": source, "model": model, "recorded": rec, "calls": n,
                      "label": f"{name}: {label}" + (f" ({n} calls)" if n > 1 else "")})
    misses = sum(i["calls"] for i in items if i["source"] == "missing")
    if not items:
        label = "no model call in this step (deterministic code only)"
    else:
        label = "; ".join(i["label"] for i in items)
    return {"mode": "live", "label": label, "items": items, "replay_misses": misses}


def fixture_info(fixture_dir: Path | None = None) -> dict:
    """What the committed fixture holds (read from the files; nothing is guessed)."""
    import json
    d = Path(fixture_dir) if fixture_dir else FIXTURE_DIR
    models, dates, n = set(), set(), 0
    for f in sorted(d.glob("*.json")) if d.exists() else []:
        if f.name in ("MANIFEST.json", "usage.json"):
            continue
        try:
            e = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        n += 1
        models.add(e.get("model"))
        dates.add(e.get("recorded"))
    return {"entries": n, "models": sorted(m for m in models if m), "recorded": sorted(x for x in dates if x),
            "path": str(d.relative_to(config.ROOT)) if d.is_relative_to(config.ROOT) else str(d)}
