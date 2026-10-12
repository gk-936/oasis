# Configuration: LLM, environment variables, persistence

## Persistence

The API keeps the Passport, audit log, proofs, why-cards, ledger, pending approvals and clock in SQLite (`data/oasis.db`, override with `OASIS_DB`; `OASIS_DB=:memory:` disables it) so state survives an API restart. Tests and the benchmark are in-memory. The database is **encrypted at rest** (AES-256-GCM on every payload column; an old plaintext DB is migrated on first start). The data key lives in `data/keys/data_key.json` (override `OASIS_DATA_KEY`). The trust signing keys are generated once and kept in a git-ignored file (`data/keys/trust_key.json`, override with `OASIS_TRUST_KEY`). All key files are plaintext protected by OS permissions unless you set `OASIS_KEY_PASSPHRASE` (then they are scrypt+AES-GCM wrapped); see the honest limits in the security self-assessment, so the key fingerprint and old proof packs stay valid across restarts. Tests and the benchmark use in-memory keys; the scripted demo uses seeded public demo keys. The red-team sandbox is never persisted.

## LLM configuration

By default Oasis runs **offline** (`OASIS_LLM=offline`): a deterministic parser, risk scorer and explainer, so demos, tests and benchmarks are reproducible with no network. This is the no-network path; there is no OCR fallback (deliberately dropped). A local model through Ollama is available as an **exploratory, opt-in planner provider** (`OASIS_LLM=ollama`, below); it is not the default and the other LLM jobs (extraction, explanations) stay deterministic under it. **No key is needed.** To use Groq, copy `.env.example` to `.env` (git-ignored, never commit it) and set `GROQ_API_KEY` (a free key is enough). Real environment variables override `.env`.

| Variable | Default | Notes |
|---|---|---|
| `OASIS_LLM` | `offline` | `groq` to use Groq; `ollama` to use a LOCAL model for the planner only (no key; see the Ollama rows below; extraction, risk and explanations stay on the deterministic parser) |
| `OASIS_PLANNER_FORMAT` | `v2` | planner format: `v1`, `v2` (default), `v3` (calculator tools, evaluation incomplete) or `v4` (schema-constrained JSON, exploratory, Ollama only) |
| `OASIS_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama server. Only loopback hosts are accepted unless `OASIS_OLLAMA_ALLOW_REMOTE=1`, so prompts never leave the machine |
| `OASIS_OLLAMA_MODEL` | `qwen3.5:4b` | an INSTALLED local model (the adapter never pulls one). `-cloud` models and `gemini*` are refused: Ollama proxies them to a third party |
| `OASIS_OLLAMA_NUM_CTX` | `8192` | context window sent with every call. Ollama's own default is smaller and truncates silently; 8192 fits the longest planner prompt and keeps the KV cache of a 3-5B model on a 6 GB GPU |
| `OASIS_OLLAMA_KEEP_ALIVE` / `_TIMEOUT` / `_RETRIES` | `5m` / `300` s / `2` | how long the model stays loaded after a call (`0` unloads at once), request timeout (a cold load of a 4B model takes about 15 s), retries on 5xx and timeouts |
| `GROQ_API_KEY` | - | the only key needed (text and image intake). Accepts a **comma-separated list** (`key1,key2,...`): the adapter keeps one client per key and moves to the next key when one reaches its daily limit (or its local daily budget); per-minute 429s are waited out on the same key. `QuotaExhausted` only when every key is spent. Usage is tracked per key fingerprint (8-char sha256) in `data/llm_cache/usage.json`; key values are never logged |
| `OASIS_AGENT_MODEL` | `qwen/qwen3.8-27b` | Groq **preview** model; accepts images; may be retired at short notice |
| `OASIS_FALLBACK_MODEL` | `openai/gpt-oss-120b` | production model, used automatically if the agent model errors (retired/404, daily limit); no vision |
| `OASIS_REDTEAM_MODEL` | `openai/gpt-oss-120b` | AI red-team generator |
| `OASIS_LLM_RISK` | `0` | `1` adds the LLM risk scorer in live mode (`OASIS_EXTRACT=llm` only); combined as max(heuristic, llm), so it can only escalate |
| `OASIS_TRUST_KEY` | `data/keys/trust_key.json` | where the persistent trust signing keys live (git-ignored) |
| `OASIS_GROQ_RPM` / `_DAILY_TOKENS` / `_DAILY_REQUESTS` | 25 / 180000 / 900 | client-side guard rails under the free tier (about 30 RPM, 1,000 requests/day, 200k tokens/day); the daily budgets apply **per key** |
| `OASIS_PASS_STUDENT` / `_PARENT` / `_JUDGE` | demo passcodes | role passcodes; `OASIS_REQUIRE_CUSTOM_PASSCODES=1` refuses the defaults |
| `OASIS_JUDGE_MODE` | `0` | `1` (set by the judge start scripts) refuses default passcodes unless `OASIS_ALLOW_DEMO_PASSCODES=1`, switches off `/docs`, tightens limits |
| `OASIS_KEY_PASSPHRASE` | unset | wraps key files with scrypt+AES-GCM |
| `OASIS_RATES` | mock (`live` in the Docker image) | `live` uses real ECB reference rates for INR→CNY and the USD, EUR, GBP and AUD wallet crosses, fetched server-side and cached 1 hour (badge live / STALE / MOCK); the scripted demo always uses the mock; see [live-rates.md](live-rates.md) |
| `OASIS_ANCHOR` | local simulation | `fisco` uses the 4-node local FISCO BCOS test chain |
| `OASIS_DB` | `data/oasis.db` | SQLite location; `:memory:` for none |
| `OASIS_DATA_DIR` | `data/` | base directory for the LLM cache, rate cache and other defaults (`/data` in the Docker image) |
| `OASIS_REQUIRE_PASSKEY` | unset | `1` makes a role that has registered a passkey (WebAuthn: fingerprint, face, phone or security key) prove it after the passcode before a session is issued; a role with no passkey can still log in by passcode to enrol one, so enrol before exposing the server. `OASIS_WEBAUTHN_RP_ID` / `OASIS_WEBAUTHN_ORIGIN` override the values derived from the Host header (needed behind a proxy). Public keys only, in `data/passkeys.json`; verification by py_webauthn, not independently audited |
| `OASIS_COOKIE_SECURE` | unset | `1` forces the `Secure` flag on the session cookie (it is also set automatically for https requests, including `X-Forwarded-Proto: https` from a trusted proxy) |
| `OASIS_ALLOWED_ORIGINS` | unset | extra exact origins (comma-separated, e.g. `https://oasis.example.com`) accepted by the Origin/CSRF check behind a proxy that rewrites `Host` |
| `OASIS_TRUST_FORWARDED_HOST` | unset | `1` also accepts `X-Forwarded-Host` as the public host in the Origin check (the Docker entrypoint sets it when `FORWARDED_ALLOW_IPS` is set) |
| `FORWARDED_ALLOW_IPS`, `PORT` | `127.0.0.1`, `8000` | read by the Docker command: proxy addresses whose `X-Forwarded-*` headers uvicorn believes (per-IP rate limits, https detection), and the listen port. See [deployment-docker.md](deployment-docker.md) |

Model IDs were checked against console.groq.com/docs/models on 2026-10-10. `qwen/qwen3-32b` and `qwen/qwen3.6-27b` are retired. The Groq adapter rate-limits itself, backs off on 429 (honouring `retry-after`), keeps a daily budget on disk, caches every response on disk (`data/llm_cache/`; cache hits cost nothing) and falls back to the second model. If Groq is unavailable the offline parser is the floor. Unit tests use a fake client; the adapter, image intake and the benchmark have also been run live (2026-10-10).

Image intake (`POST /api/intake/image`) sends the picture to the agent model through the same client. The fallback model has no vision, so if the image cannot be read the result is a low-confidence hold asking the student to paste the text or confirm the fields; nothing is guessed. The image is not stored.

## Benchmarks and evaluation commands

```bash
# offline benchmark: 4 configurations x 44 scenarios + AI red-team variants -> eval/reports/benchmark.md/.json
PYTHONPATH=. .venv/Scripts/python -m eval.runner

# live benchmark (needs GROQ_API_KEY; resumable, ~200k tokens/day on the free tier) -> eval/reports/benchmark_live.md/.json
PYTHONPATH=. .venv/Scripts/python -m eval.runner --llm groq --extract llm --repeats 1     # raise --repeats N for spread

# plan-quality evaluation of the agentic planner (8 scenarios) -> eval/reports/planning.md/.json
PYTHONPATH=. .venv/Scripts/python -m eval.planning                       # live: --llm groq --token-cap 60000

# 5-persona, 90-day student-outcome simulation (a model with stated assumptions) -> eval/reports/simulation.md/.json
PYTHONPATH=. .venv/Scripts/python -m eval.simulator

# scripted demo log (both runs, replayed twice, audit-chain heads) -> eval/reports/demo.md/.json
PYTHONPATH=. .venv/Scripts/python -m eval.demo_log
```

If a live run exhausts the daily budget it stops cleanly (exit code 2); rerun the same command later and it continues from `data/bench_cache/`. Where each result file comes from: [execution-evidence.md](execution-evidence.md).

Two extraction modes. Default `--extract deterministic`: the regex parse is the floor and the model only fills empty fields, so results equal the offline benchmark and say nothing about model behaviour. `--extract llm` (or `OASIS_EXTRACT=llm` for the API) is the **live agent** mode: the model's JSON extraction is primary and the regex parse is used only, per field, when the call fails, is unparseable or omits payee_name / account_ref / amount. Whether the model followed an embedded injection is computed by comparing its fields with the document's genuine (pre-injection) fields from the scenario, never from the model. The scorer stays deterministic. Live results go to `eval/reports/benchmark_live.md` with a deterministic reference table; checkpoints are keyed by mode.

Free-text purposes ("Tuition fee for Fall 2026 semester", "房租", "deposit (2 months)") are normalised to tuition / rent / deposit / living / family_support by a deterministic mapper applied to both regex and model output. Finished results are checkpointed in `data/bench_cache/`. The report shows min / mean / max across repeats. In deterministic mode the unsafe behaviour of the unprotected baseline is modelled by the regex extractor that follows embedded instructions; in live-agent mode it is whatever the model does. Poisoned-tool scenarios (a simulated rewrite of payment details at execution time) are independent of the model in both modes. Safety layers never depend on the model.

## Interface language

No environment variable is needed. English is the default; the UI language is chosen in the browser (`?lang=zh` or the picker) and saved per student in the Passport. The API honours `?lang=`, the `X-Oasis-Lang` header and `Accept-Language` (`en`, `zh`). See technical documentation section 17.
