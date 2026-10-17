# Configuration: LLM, environment variables, persistence

## Persistence

The API keeps the Passport, audit log, proofs, why-cards, ledger, pending approvals and clock in SQLite (`data/oasis.db`, override with `OASIS_DB`; `OASIS_DB=:memory:` disables it) so state survives an API restart. Tests and the benchmark are in-memory. The database is **encrypted at rest** (AES-256-GCM on every payload column; an old plaintext DB is migrated on first start). The data key lives in `data/keys/data_key.json` (override `OASIS_DATA_KEY`). The trust signing keys are generated once and kept in a git-ignored file (`data/keys/trust_key.json`, override with `OASIS_TRUST_KEY`). All key files are plaintext protected by OS permissions unless you set `OASIS_KEY_PASSPHRASE` (then they are scrypt+AES-GCM wrapped); see the honest limits in the security self-assessment, so the key fingerprint and old proof packs stay valid across restarts. Tests and the benchmark use in-memory keys; the scripted demo uses seeded public demo keys. The red-team sandbox is never persisted.

## LLM configuration

By default Oasis runs **offline** (`OASIS_LLM=offline`): a deterministic parser, risk scorer and explainer, so demos, tests and benchmarks are reproducible with no network. This is the no-network path; there is no OCR fallback (deliberately dropped). Live mode uses Amazon Nova Pro on Amazon Bedrock (`OASIS_LLM=bedrock`; set-up steps in [bedrock-setup.md](bedrock-setup.md)). AWS credentials come from the standard AWS chain, never from a key in this repo; `.env` (git-ignored) may hold `OASIS_LLM`, `AWS_REGION` and `OASIS_BEDROCK_MODEL`. Real environment variables override `.env`.

| Variable | Default | Notes |
|---|---|---|
| `OASIS_LLM` | `offline` | `bedrock` to use Amazon Nova Pro on Amazon Bedrock for extraction, risk, explanations, red-team variants, image intake and the planner (set up: below) |
| `OASIS_PLANNER_FORMAT` | `v3` | planner format: `v1`, `v2` or `v3` (default; calculator tools, 24 of 24 valid without fallback live vs 16 of 24 for v2) |
| `OASIS_BEDROCK_MODEL` / `AWS_REGION` | `us.amazon.nova-pro-v1:0` / `us-east-1` | **the default id is a best guess, not verified**: copy the exact model id or inference profile from the Bedrock console. `OASIS_BEDROCK_REGION` overrides `AWS_REGION` |
| `OASIS_BEDROCK_FALLBACK_MODEL` | same as the model | optional second model tried if the first errors; default is none, so there is no silent downgrade |
| `OASIS_BEDROCK_RPM` / `_DAILY_TOKENS` | 120 / 2000000 | client-side rate limit and a spend guard (about $1/day at $0.10 in / $0.50 out per 1M tokens) |
| `OASIS_CHAT_LLM` | `0` | `1` lets a live model propose a label for a chat message the keyword router could not place (needs `OASIS_LLM=bedrock` and **your own** AWS/Bedrock access; Oasis ships no key). The proposal is validated against a closed list and cross-checked with the text; security refusals are decided first and a payment still ends as a held draft that only your device-key signature releases. Each call spends tokens (cached; capped by `OASIS_BEDROCK_DAILY_TOKENS`) |
| `OASIS_LLM_RISK` | `0` | `1` adds the LLM risk scorer in live mode (`OASIS_EXTRACT=llm` only); combined as max(heuristic, llm), so it can only escalate |
| `OASIS_TRUST_KEY` | `data/keys/trust_key.json` | where the persistent trust signing keys live (git-ignored) |
| `OASIS_PASS_STUDENT` / `_PARENT` / `_JUDGE` | random per run | role passcodes. None is built in: an unset one is generated and printed once. `OASIS_REQUIRE_CUSTOM_PASSCODES=1` refuses generated ones |
| `OASIS_JUDGE_MODE` | `0` | `1` (set by the judge start scripts) requires all three passcodes to be set, gives every login its own private sandbox (`OASIS_MAX_SANDBOXES`, default 40), switches off `/docs`, tightens limits |
| `OASIS_KEY_PASSPHRASE` | unset | wraps key files with scrypt+AES-GCM |
| `OASIS_RATES` | mock (`live` in the Docker image) | `live` uses real ECB reference rates for INR→CNY and the USD, EUR, GBP and AUD wallet crosses, fetched server-side and cached 1 hour (badge live / STALE / MOCK); the scripted demo always uses the mock; see [live-rates.md](live-rates.md) |
| `OASIS_ANCHOR` | local simulation | `fisco` uses the 4-node local FISCO BCOS test chain |
| `OASIS_DB` | `data/oasis.db` | SQLite location; `:memory:` for none |
| `OASIS_DATA_DIR` | `data/` | base directory for the LLM cache, rate cache and other defaults (`/data` in the Docker image) |
| `OASIS_ML_RISK` | unset | `1` also scores each document with the small trained fraud-risk model (`oasis/agent/ml_risk.py`, weights in `ml_risk_model.json`) and keeps the higher of its score and the rule score, so it can only escalate; the evidence list says which indicators drove it. Retrain and re-measure with `python -m eval.ml_risk_train` (report: `eval/reports/ml_risk.md`) |
| `OASIS_TELEGRAM_TOKEN` | unset | Telegram bot token (from BotFather): turns on the invoice bot. Chats must be paired with a one-time code from the app before anything is processed. See [real-inputs.md](real-inputs.md) |
| `OASIS_IMAP_HOST` / `_USER` / `_PASSWORD` | unset | Mailbox watcher over IMAP (use a dedicated mailbox and an app password). `OASIS_IMAP_ALLOWED_SENDERS` (comma-separated exact addresses) is required; `OASIS_IMAP_REQUIRE_AUTH=0` drops the SPF/DKIM/DMARC-pass requirement (default on); `OASIS_IMAP_INTERVAL_S` (default 60, minimum 15) |
| `OASIS_REQUIRE_PASSKEY` | unset | `1` makes a role that has registered a passkey (WebAuthn: fingerprint, face, phone or security key) prove it after the passcode before a session is issued; a role with no passkey can still log in by passcode to enrol one, so enrol before exposing the server. `OASIS_WEBAUTHN_RP_ID` / `OASIS_WEBAUTHN_ORIGIN` override the values derived from the Host header (needed behind a proxy). Public keys only, in `data/passkeys.json`; verification by py_webauthn, not independently audited |
| `OASIS_COOKIE_SECURE` | unset | `1` forces the `Secure` flag on the session cookie (it is also set automatically for https requests, including `X-Forwarded-Proto: https` from a trusted proxy) |
| `OASIS_ALLOWED_ORIGINS` | unset | extra exact origins (comma-separated, e.g. `https://oasis.example.com`) accepted by the Origin/CSRF check behind a proxy that rewrites `Host` |
| `OASIS_TRUST_FORWARDED_HOST` | unset | `1` also accepts `X-Forwarded-Host` as the public host in the Origin check (the Docker entrypoint sets it when `FORWARDED_ALLOW_IPS` is set) |
| `FORWARDED_ALLOW_IPS`, `PORT` | `127.0.0.1`, `8000` | read by the Docker command: proxy addresses whose `X-Forwarded-*` headers uvicorn believes (per-IP rate limits, https detection), and the listen port. See [deployment-docker.md](deployment-docker.md) |

The adapter (`oasis/agent/llm.py` + `bedrock_llm.py`) rate-limits itself, backs off on throttling (honouring `retry-after`), keeps a daily token budget on disk, caches every response on disk (`data/llm_cache/`; cache hits cost nothing) and can fall back to a second model. If Bedrock is unreachable the offline parser is the floor. Unit tests use a fake client; nothing in this repo has been run against the real Bedrock API yet.

Image intake (`POST /api/intake/image`) sends the picture to the agent model through the same client. The fallback model has no vision, so if the image cannot be read the result is a low-confidence hold asking the student to paste the text or confirm the fields; nothing is guessed. The image is not stored.

## Benchmarks and evaluation commands

```bash
# offline benchmark: 4 configurations x 44 scenarios + AI red-team variants -> eval/reports/benchmark.md/.json
PYTHONPATH=. .venv/Scripts/python -m eval.runner

# live benchmark (needs AWS credentials; resumable, capped by `OASIS_BEDROCK_DAILY_TOKENS`) -> eval/reports/benchmark_live.md/.json
PYTHONPATH=. .venv/Scripts/python -m eval.runner --llm bedrock --extract llm --repeats 1     # raise --repeats N for spread

# plan-quality evaluation of the agentic planner (8 scenarios) -> eval/reports/planning.md/.json
PYTHONPATH=. .venv/Scripts/python -m eval.planning                       # live: --llm bedrock --token-cap 60000

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

## AI-contribution evaluation

```bash
OASIS_LLM=offline PYTHONPATH=. .venv/Scripts/python -m eval.ai_contribution                       # offline checks, free
PYTHONPATH=. .venv/Scripts/python -m eval.ai_contribution --live --cap 150000                      # LIVE: spends Bedrock tokens, needs the owner's approval per run
```

`--cap` is a hard token limit and is required with `--live`. Cached answers cost nothing on a rerun. The live part prints "NOT RUN" and exits with code 2 if the model cannot be reached. Measure real input and output tokens with a metering wrapper if you want a cost figure; the committed report records one metered history. Set `OASIS_BEDROCK_DAILY_TOKENS` as a second guard.
