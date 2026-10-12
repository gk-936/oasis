"""Local LLM adapter for Ollama (https://ollama.com): the planner-facing twin of `GroqLLM`, with no API key and no
data leaving the machine.

- `chat_tools(messages, tools)`: native tool calling, same return shape as `GroqLLM.chat_tools`
  ({"content", "tool_calls": [{"id","name","arguments"(dict)}], "model", "tokens", "cached"}).
- `generate_json(messages, schema)`: ONE JSON object under Ollama's schema-constrained decoding (`format` = JSON schema),
  so the text always parses and matches the schema's shape. It guarantees form, never correctness.

It talks to the native `/api/chat` endpoint (not `/v1`) because only that endpoint takes `options.num_ctx`, `keep_alive`,
`think` and returns `eval_count` / `prompt_eval_count` / `total_duration`.

Design notes
- `num_ctx` defaults to 8192. Ollama's own default is small and SILENTLY truncates the prompt; the planner's longest
  context (a v2 tool-calling run after several proposals) is about 6-8k tokens and the v4 prompt is about 1.5-3k. 8192
  keeps the KV cache of a 3-5B model small enough to stay on a 6 GB GPU. `prompt_eval_count` is recorded per call and a
  call whose prompt reaches `num_ctx` is flagged `truncated`.
- Privacy: only loopback hosts are accepted (override: OASIS_OLLAMA_ALLOW_REMOTE=1) and "-cloud" models, which Ollama proxies
  to a third party, are refused. Error text goes through the same redaction as the Groq adapter.
- Cache: on disk, keyed like the Groq one (model, messages, tools or schema, salt, temperature) plus seed and num_ctx.
- Planner interface only: extraction / risk / explanations stay on the deterministic `OfflineLLM` parents.
"""
from __future__ import annotations
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .. import config
from .llm import THINK_RE, OfflineLLM, _redact

LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}


class OllamaError(RuntimeError):
    """Base class: every Ollama failure the planner can see."""


class OllamaUnavailable(OllamaError):
    """Ollama is not running (or not reachable) at the configured URL."""


class OllamaModelMissing(OllamaError):
    """The requested model is not installed locally."""


class OllamaUnsupported(OllamaError):
    """The model does not support the requested feature (for example tools)."""


class OllamaRefused(OllamaError):
    """Refused by the adapter's own privacy guard (non-loopback host, cloud-proxied model)."""


def is_cloud_model(model: str) -> bool:
    return bool(re.search(r"(^|[:\-_/])cloud$", model.lower())) or model.lower().startswith("gemini")


class OllamaLLM(OfflineLLM):
    name = "ollama"

    def __init__(self, model: str | None = None, url: str | None = None, cache_dir: Path | None = None, susceptible: bool = True,
                 salt: str = "", temperature: float = 0.0, seed: int | None = 0, num_ctx: int | None = None,
                 keep_alive: str | int | None = None, timeout: float | None = None, max_retries: int | None = None,
                 use_cache: bool = True, think: bool = False, use_mmap: bool | None = None, opener=None, sleep=time.sleep):
        super().__init__(susceptible)
        self.model = model or config.OLLAMA_MODEL
        self.url = (url or config.OLLAMA_URL).rstrip("/")
        host = (urlparse(self.url).hostname or "").lower()
        if host not in LOOPBACK and not config.OLLAMA_ALLOW_REMOTE:
            raise OllamaRefused(f"OASIS_OLLAMA_URL host {host!r} is not loopback; set OASIS_OLLAMA_ALLOW_REMOTE=1 to allow it "
                                "(the point of this adapter is that nothing leaves the machine)")
        self._check_model(self.model)
        self.salt, self.temperature, self.seed = salt, temperature, seed
        self.num_ctx = config.OLLAMA_NUM_CTX if num_ctx is None else num_ctx
        self.keep_alive = config.OLLAMA_KEEP_ALIVE if keep_alive is None else keep_alive
        self.timeout = config.OLLAMA_TIMEOUT if timeout is None else timeout
        self.max_retries = config.OLLAMA_RETRIES if max_retries is None else max_retries
        self.think = think
        self.use_mmap = config.OLLAMA_USE_MMAP if use_mmap is None else use_mmap     # False: weights are copied, not memory-mapped (see docs)
        self.use_cache = use_cache
        self.cache_dir = cache_dir or (config.DATA_DIR / "llm_cache_ollama")
        if use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._open = opener or urllib.request.urlopen
        self.sleep = sleep
        self.calls = 0
        self.cache_hits = 0
        self.errors: list[dict] = []
        self.call_log: list[dict] = []           # one entry per network call: token counts and timings (seconds)
        self.last_model: str | None = None

    @staticmethod
    def _check_model(model: str) -> None:
        if is_cloud_model(model):
            raise OllamaRefused(f"{model!r} is a cloud-proxied model: Ollama would send the prompt to a third party. Use a local model.")

    # -- transport --------------------------------------------------------------------------------
    def _scrub(self, msg: str) -> str:
        return _redact(str(msg))

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode("utf-8")
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(self.url + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with self._open(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                text = ""
                try:
                    text = json.loads(e.read().decode("utf-8")).get("error", "")
                except Exception:  # noqa: BLE001
                    pass
                low = text.lower()
                if e.code == 404 or ("model" in low and "not found" in low):
                    self._err("model_missing", text)
                    raise OllamaModelMissing(f"model {body.get('model')!r} is not installed in Ollama; "
                                             f"`ollama pull {body.get('model')}` would install it. ({self._scrub(text)[:150]})") from None
                if e.code == 400 and ("does not support" in low or "not support" in low):
                    self._err("unsupported", text)
                    raise OllamaUnsupported(self._scrub(text)[:200]) from None
                if e.code >= 500 and attempt < self.max_retries:
                    self._err("transient", f"HTTP {e.code} {text}")
                    last = e
                    self.sleep(min(2.0 * (2 ** attempt), 20.0))
                    continue
                self._err("other", f"HTTP {e.code} {text}")
                raise OllamaError(f"Ollama HTTP {e.code}: {self._scrub(text)[:200]}") from None
            except (urllib.error.URLError, ConnectionError, OSError) as e:
                reason = getattr(e, "reason", e)
                if isinstance(reason, TimeoutError) or isinstance(e, TimeoutError) or "timed out" in str(reason).lower():
                    self._err("transient", "timeout")
                    last = e
                    if attempt < self.max_retries:
                        self.sleep(min(2.0 * (2 ** attempt), 20.0))
                        continue
                    raise OllamaError(f"Ollama did not answer within {self.timeout:.0f}s after {attempt + 1} attempt(s)") from None
                self._err("unavailable", str(reason))
                raise OllamaUnavailable(f"Ollama is not running at {self.url} (start it with `ollama serve` or the Ollama app). "
                                        f"({self._scrub(str(reason))[:120]})") from None
        raise OllamaError(f"Ollama unavailable: {self._scrub(str(last))[:200]}")

    def _err(self, kind: str, message: str) -> None:
        self.errors.append({"model": self.model, "kind": kind, "message": self._scrub(message)[:300]})

    def _get(self, path: str) -> dict:
        try:
            with self._open(urllib.request.Request(self.url + path), timeout=min(self.timeout, 15)) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, OSError) as e:
            raise OllamaUnavailable(f"Ollama is not running at {self.url} ({self._scrub(str(getattr(e, 'reason', e)))[:120]})") from None

    # -- helpers ----------------------------------------------------------------------------------
    def installed(self) -> list[str]:
        return [m.get("name", "") for m in self._get("/api/tags").get("models", [])]

    def require_installed(self, model: str | None = None) -> None:
        """Clean 'not running' / 'not installed' errors before a long run."""
        model = model or self.model
        names = self.installed()
        if model not in names and f"{model}:latest" not in names:
            raise OllamaModelMissing(f"model {model!r} is not installed in Ollama (installed: {', '.join(sorted(n for n in names if not is_cloud_model(n))) or 'none'})")

    def ps(self) -> list[dict]:
        """Loaded models with their memory split: size_vram / size (the GPU share)."""
        out = []
        for m in self._get("/api/ps").get("models", []):
            size, vram = int(m.get("size", 0)), int(m.get("size_vram", 0))
            out.append({"name": m.get("name"), "size_mb": round(size / 2**20), "vram_mb": round(vram / 2**20),
                        "gpu_pct": round(100 * vram / size) if size else None, "context": m.get("context_length")})
        return out

    def unload(self, model: str | None = None) -> None:
        """keep_alive 0: free the model's memory now."""
        try:
            self._post("/api/generate", {"model": model or self.model, "keep_alive": 0})
        except OllamaError:
            pass

    @staticmethod
    def to_native(messages: list[dict]) -> list[dict]:
        """OpenAI-style planner messages -> Ollama native: tool_call arguments are objects, tool results carry `tool_name`."""
        names: dict[str, str] = {}
        out = []
        for m in messages:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                tcs = []
                for t in m["tool_calls"]:
                    f = t.get("function", {})
                    args = f.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args or "{}")
                        except ValueError:
                            args = {}
                    names[t.get("id", "")] = f.get("name", "")
                    tcs.append({"function": {"name": f.get("name", ""), "arguments": args if isinstance(args, dict) else {}}})
                out.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
            elif m.get("role") == "tool":
                out.append({"role": "tool", "tool_name": names.get(m.get("tool_call_id", ""), ""), "content": m.get("content", "")})
            else:
                out.append({"role": m["role"], "content": m.get("content") or ""})
        return out

    def _body(self, model: str, messages: list[dict], seed: int | None, max_tokens: int, **extra) -> dict:
        opts = {"temperature": self.temperature, "num_ctx": self.num_ctx, "num_predict": max_tokens}
        if seed is not None:
            opts["seed"] = seed
        if self.use_mmap is not None:
            opts["use_mmap"] = self.use_mmap
        body = {"model": model, "messages": self.to_native(messages), "stream": False, "options": opts, "keep_alive": self.keep_alive, **extra}
        if not self.think:
            body["think"] = False
        return body

    def _account(self, r: dict, wall: float) -> dict:
        ns = lambda k: round(int(r.get(k, 0) or 0) / 1e9, 3)
        pe, ev = int(r.get("prompt_eval_count", 0) or 0), int(r.get("eval_count", 0) or 0)
        rec = {"prompt_tokens": pe, "output_tokens": ev, "tokens": pe + ev, "total_s": ns("total_duration") or round(wall, 3),
               "load_s": ns("load_duration"), "eval_s": ns("eval_duration"), "wall_s": round(wall, 3),
               "truncated": pe >= self.num_ctx - 8, "done_reason": r.get("done_reason")}
        self.call_log.append(rec)
        self.calls += 1
        return rec

    def _cache_path(self, kind: str, model: str, messages, spec, seed) -> Path:
        key = hashlib.sha256(json.dumps([kind, model, messages, spec, self.salt, self.temperature, seed, self.num_ctx],
                                        sort_keys=True, default=str).encode()).hexdigest()
        return self.cache_dir / f"{key}.json"

    def _cached(self, path: Path) -> dict | None:
        if self.use_cache and path.exists():
            self.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def _store(self, path: Path, out: dict) -> None:
        if self.use_cache:
            path.write_text(json.dumps({**out, "recorded": time.strftime("%Y-%m-%d")}), encoding="utf-8")

    # -- native tool calling (planner v1-v3) ------------------------------------------------------
    def chat_tools(self, messages: list[dict], tools: list[dict], model: str | None = None, max_tokens: int = 900,
                   seed: int | None = ...) -> dict:
        model = model or self.model
        self._check_model(model)
        seed = self.seed if seed is ... else seed
        path = self._cache_path("tools", model, messages, tools, seed)
        hit = self._cached(path)
        if hit is not None:
            self.last_model = hit.get("model")
            return {**hit, "tokens": 0, "cached": True}
        t0 = time.monotonic()
        r = self._post("/api/chat", self._body(model, messages, seed, max_tokens, tools=tools))
        rec = self._account(r, time.monotonic() - t0)
        msg = r.get("message") or {}
        calls = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            f = tc.get("function", {})
            args = f.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except ValueError:
                    args = {}
            calls.append({"id": tc.get("id") or f"call_{self.calls}_{i}", "name": f.get("name", ""), "arguments": args if isinstance(args, dict) else {}})
        out = {"content": THINK_RE.sub("", msg.get("content") or "").strip(), "tool_calls": calls, "model": r.get("model") or model, "stats": rec}
        self.last_model = out["model"]
        self._store(path, out)
        return {**out, "tokens": rec["tokens"], "cached": False}

    # -- schema-constrained JSON (planner v4) -----------------------------------------------------
    def generate_json(self, messages: list[dict], schema: dict, model: str | None = None, max_tokens: int = 1400,
                      seed: int | None = ...) -> dict:
        """Returns {"content", "json" (parsed dict or None), "model", "tokens", "cached", "stats"}. With `format` = schema,
        decoding can only produce text that matches the schema, but a call cut off by num_predict can still be partial JSON,
        in which case `json` is None and `stats.done_reason` is 'length'."""
        model = model or self.model
        self._check_model(model)
        seed = self.seed if seed is ... else seed
        path = self._cache_path("json", model, messages, schema, seed)
        hit = self._cached(path)
        if hit is not None:
            self.last_model = hit.get("model")
            return {**hit, "tokens": 0, "cached": True}
        t0 = time.monotonic()
        r = self._post("/api/chat", self._body(model, messages, seed, max_tokens, format=schema))
        rec = self._account(r, time.monotonic() - t0)
        text = THINK_RE.sub("", (r.get("message") or {}).get("content") or "").strip()
        try:
            parsed = json.loads(text)
            parsed = parsed if isinstance(parsed, dict) else None
        except ValueError:
            parsed = None
        out = {"content": text, "json": parsed, "model": r.get("model") or model, "stats": rec}
        self.last_model = out["model"]
        self._store(path, out)
        return {**out, "tokens": rec["tokens"], "cached": False}
