# Oasis

**A proactive financial agent for international students that plans, pays and protects, and cannot be tricked into paying the wrong person.** Oasis (built for the 2026 Shenzhen FinTechathon, International Track, Topic C: Cross-border & Student Finance Assistant) keeps a Student Financial Passport, plans an INR to CNY payment schedule with a tool-using agent whose proposals a deterministic validator checks, verifies every recipient against an independent registry, binds each approved payment to a hybrid-signed intent (Ed25519 + ML-DSA-65, optional SM2) that the executor enforces exactly, watches for tampering with canary tripwires, and hands back a proof pack anyone can verify. The AI does the work; deterministic guardrails decide what money moves. The hero corridor is INR to CNY: an Indian student arriving in Shenzhen.

> All money, rates, fees, payment rails, registry identities, wallet spending and balances are **simulated sandbox data**, labelled MOCK in the UI. See [docs/real-vs-simulated.md](docs/real-vs-simulated.md).

## Architecture

```mermaid
flowchart LR
  subgraph U["UNTRUSTED: everything the agent reads or writes"]
    D["Documents, screenshots, web pages, tool output"] --> S1["1 Understand<br/>LLM extraction + canary scan + risk score<br/>(inputs only)"]
    S1 --> S2["2 Plan<br/>routes, forecast, agentic planner"]
    S2 -. "proposal" .-> V["Plan validator<br/>(deterministic)"]
    V -. "errors, revise (max 4)" .-> S2
  end
  S2 --> S3
  subgraph T["TRUSTED: deterministic code, no LLM decides here"]
    S3["3 Verify<br/>registry credential, test payment, limits"] --> S4["4 Commit<br/>corridor rules, policy R01-R17,<br/>approvals, signed intent, anchor"]
    S4 --> S5["5 Execute and watch<br/>executor: signature, exact match,<br/>nonce/expiry, policy re-check"]
    S5 --> S6["6 Prove<br/>audit hash chain, proof pack,<br/>why-card, savings receipt"]
  end
  S5 --> L[("Sandbox ledger (MOCK)")]
  S5 -. "canary hit / mismatch" .-> F["Freeze, recovery plan,<br/>student approves"]
```

The LLM never holds the payment credential, never approves a payment, never changes verification status and cannot edit the audit log. Details: [docs/technical-documentation.md](docs/technical-documentation.md).

## Quick start

Requires Python 3.10+ (tested on 3.10) and, only to rebuild the UI, Node 18+.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows; on macOS/Linux use .venv/bin/python

# optional: rebuild the frontend (a built copy is committed in frontend/dist)
cd frontend && npm ci && npm run build && cd ..

# run the API; it also serves the built UI at /
PYTHONPATH=. .venv/Scripts/python -m uvicorn oasis.api.main:app --port 8000
# open http://localhost:8000 and log in (see "Login and roles" below); API docs at /docs
```

Frontend development mode (proxies `/api` to :8000): `cd frontend && npm ci && npm run dev`.

### Configuration (.env)

Copy `.env.example` to `.env` (git-ignored). **No key is needed**: with the default `OASIS_LLM=offline` everything works with no network (deterministic parser, risk scorer and explainer). For live models, set `OASIS_LLM=groq` and `GROQ_API_KEY=...` (a free Groq key is enough). Real environment variables override `.env`. Never commit `.env`.

### Tests, benchmarks, evaluations, demo

```bash
# 394 tests (+2 skipped: live FISCO and live PQ-TLS), no network, no database file
OASIS_DB=:memory: OASIS_LLM=offline PYTHONPATH=. .venv/Scripts/python -m pytest -q

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

If a live run exhausts the daily budget it stops cleanly (exit code 2); rerun the same command later and it continues from `data/bench_cache/`. Where each result file comes from and how it was produced: [docs/execution-evidence.md](docs/execution-evidence.md).

### Scripted demo (works offline, repeats exactly)

Open the **Demo** tab (or call `POST /api/demo/start {"run": "legit"|"attack"}`, then `POST /api/demo/next` per step, or `POST /api/demo/run` for the whole run). The demo uses a fixed seed, fixed mock data, seeded **demo-only** signing keys and a simulated clock, so each run produces the same statuses, amounts and the same audit-chain head hash every time (`tests/test_features.py` and `tests/test_review_fixes.py` check this). It never uses the network. A toggle in the Demo tab (`"mode": "offline"|"live"` in the API) chooses who reads, scores and plans:

- **Offline** (default): the deterministic parser, scorer and planner, no AI model. Each step is labelled "offline parser".
- **Live-replay**: qwen/qwen3.8-27b reads the documents (live-agent extraction), adds an escalate-only AI risk score and plans with native tool calling. Its answers were recorded once into the committed fixture `eval/fixtures/demo_cache/` (model name, response text and date only) and are replayed from it, so the demo repeats exactly with no network. Each step shows its mode and model, for example "Qwen qwen3.8-27b - replayed from recorded response 2026-10-10". If a response is missing from the fixture, that call falls back to the offline parser, heuristic scorer or deterministic planner and the step says so. **Status of the fixture: not recorded yet** (the free-tier daily token allowance was spent before the recording could run), so live-replay currently shows the labelled offline fallback on every step. Record it with `PYTHONPATH=. python -m eval.record_demo_fixture` (about 25k tokens; it refuses when fewer than 40k of the daily 200k would remain).

- Run 1 (legitimate): Passport and forecast, agent plan with validator revision, tuition paid with a signed intent, parent co-approves a top-up (shown in Tamil/Hindi/English), landlord's genuine account change completes through the verification ramp, Tier-1 autonomy (rate target + recurring bill), proof packs and savings receipt.
- Run 2 (attack): the forged invoice is caught at step 3 (Verify: the registry contradicts the account) and stopped with a why-card; payment instructions rewritten at execution (the second attack) are stopped at step 5 by the executor's intent check; hidden page injection reaches a canary, freeze and recovery plan, the student approves the recovery and the genuine payment completes.

**Recording the demo:** set `OASIS_KEY_PASSPHRASE` before recording (for example `export OASIS_KEY_PASSPHRASE=...` before starting uvicorn) so the key files under `data/keys/` are passphrase-wrapped and plaintext keys are never shown on screen; use custom `OASIS_PASS_*` passcodes too, and start from a clean sandbox (`POST /api/reset`).

`POST /api/reset` (or `/api/demo/reset`, or the "Reset sandbox" button) returns to a clean sandbox and wipes the SQLite state.

## Results at a glance

| Result | Configuration | Value | Source |
|---|---|---|---|
| Attack block rate (32 attacks) | baseline / +verification / +intents+policy / full | **offline:** 6.2% / 68.8% / 100% / 100% | `eval/reports/benchmark.md` |
| Money lost (CNY, sandbox) | same | **offline:** 479,000 / 108,000 / 0 / 0 | same |
| Legitimate completion, false blocks (12 changes) | all four | **offline:** 100%, 0% | same |
| Attack block rate, **live agent** (extraction by a live model, 3 repeats, LLM risk scorer on; qwen/qwen3.8-27b primary served 167 of 183 extractions, openai/gpt-oss-120b fallback 16) | same | **live:** 18.8% / 68.8% / 100% / 100% in every repeat (min = mean = max); baseline loses CNY 380,000 per repeat | `eval/reports/benchmark_live.md` |
| **Hidden test set** (40 blind cases: 28 attack, 12 legit; sha256-verified; the file is unmodified; first run kept as [`benchmark_hidden_prefix.md`](eval/reports/benchmark_hidden_prefix.md), then **general fixes** with their own tests, then re-run) | baseline / +verification / +intents+policy / full | **offline, pre-fix:** attacks passed 46.4% / 92.9% / 100% / 100%, baseline loses CNY 180,600, legit completion 83.3% / 83.3% / 75% / 75% (3 false blocks: spaced account digits, markdown-table invoice, instalment). **Post-fix:** 39.3% / 89.3% / 100% / 100%, baseline loses CNY 246,600, legit completion 100% in all four, 0 false blocks; every attack case now stops for a real reason (`extract_low_confidence` is no longer how any of them passes). The two lower no-policy figures are honest: the extractor now reads the stated currency and the whole account, so cases that used to pass by accident (unreadable fields) are now only stopped by the policy layer. The visible benchmark is unchanged | `eval/reports/benchmark_hidden.md` (pre: `benchmark_hidden_prefix.md`) |
| Model followed an embedded injection | all four | **live:** 0 of 18 injection-bearing scenario runs (6 scenarios x 3 repeats); LLM risk scorer raised 82 of 183 scores, 0 crossed the hold threshold | same |
| Plan quality, deterministic planner | 8 scenarios | **offline:** 8/8 valid, 20/20 deadlines, conversion fees 83.0% below a typical bank route (MOCK rates, recalibrated 2026-10-10) | `eval/reports/planning.md` |
| Plan quality, Groq tool-calling planner | after the prompt change; partial (token budget) | **live:** valid without fallback in 3 of 4 plans run (Tight runway 2 of 3, Arrival shortfall 1 of 1; the other 6 scenarios not re-run). Before the change (1 run): final plans 8/8 valid, only 4/8 without fallback; 100,235 tokens | same |
| 90-day simulation (5 personas) | Oasis vs manual | **model:** fees saved CNY 1,542 to 2,963 per persona (mock fees, recalibrated rate) | `eval/reports/simulation.md` |

Honest caveats:

- **Live benchmark: 3 repeats** (temperature 0, then 0.4 and 0.4, distinct cache salts) over **six** injection-bearing scenarios, with the LLM risk scorer on. Every repeat gave identical outcomes (zero spread), so the spread table shows no variance; "the model followed 0 of 18" (6 scenarios x 3 repeats) is still not a robustness claim, because a few samples of one model on hand-written injections cannot rule out rarer failures. Within a repeat, identical documents reuse one cached model response across the four configurations.
- The offline baseline uses a regex parser that deliberately follows embedded instructions (a gullible agent); the live baseline is whatever the model does, which is why it loses less (CNY 380,000 vs 479,000). The other three configurations are identical in both modes.
- **Which model served the live benchmark is now recorded per extraction:** of 183 extraction steps (full configuration, 3 repeats), 167 were answered by qwen/qwen3.8-27b and 16 by the fallback openai/gpt-oss-120b (used when the primary hit its rate limit); 0 steps fell back to the regex parser. Treat the numbers as "a live model (qwen/qwen3.8-27b primary, openai/gpt-oss-120b fallback)", not as a statement about one model.
- **Canaries are an early-detection layer, not an extra blocking layer**: they block 0 additional attacks over signed intents + policy and flag 3 attacks earlier (at Understand, offline run).
- The **risk scorer** is a heuristic scorer, plus an optional LLM scorer in live mode that can only escalate (combined as max(heuristic, llm)). In the live benchmark (3 repeats, LLM scorer on) it raised the score on 82 of 183 extraction steps (17 of them injection-bearing) but pushed 0 across the policy hold threshold (0.5), so it changed no decision; its measured contribution here is nil. The heuristic's features were chosen after seeing the benchmark (in-sample): it flags 81% of attacks and 0% of legitimate changes; it cannot see poisoned-tool attacks (0/6). A small held-out set is in `tests/test_pipeline.py`.
- **Mock rate recalibrated on 2026-10-10:** the mock INR→CNY base moved from 0.0845 to 0.0692 (the real ECB-derived cross rate as of 2026-10-09), the sandbox starting balance from INR 4 to INR 5 lakh and the split-payment attack amounts from CNY 4,000 to ~3,300 to keep their original meaning. The offline benchmark, simulation, planning (offline) and demo reports were regenerated; the benchmark outcome is unchanged. The recorded live-model runs (`benchmark_live.*`, the Groq rows of `planning.*`) were made at the old base and were not re-run (no Groq budget).
- The simulated student and parent are not oracles; real people could approve a scam. Savings come from mock fees. Corridor figures (SAFE, LRS, TCS) are researched, not officially confirmed.

## Login and roles

Every API endpoint except `/api/health`, `/api/trust/fingerprint`, proof verification and login needs a session. The login screen offers three roles; the **demo passcodes** (public, from `.env.example`) are:

| Role | Passcode | May do |
|---|---|---|
| student | `student-demo` | intake, chat, plans, rate targets, approve as student (signed), the scripted demo, reset |
| parent | `parent-demo` | approve as parent (signed), consent to parent-remitted conversions, see only their own pending items and proofs |
| judge | `judge-demo` | red-team console (rate-limited, own sandbox ledger) and read-only views |

Set `OASIS_PASS_STUDENT` / `OASIS_PASS_PARENT` / `OASIS_PASS_JUDGE` in `.env` for anything real (`OASIS_REQUIRE_CUSTOM_PASSCODES=1` refuses the defaults). Wrong role gives 403, no session 401. The scripted demo is a student action because it replaces the persisted sandbox.

**Signed approvals.** On first login a student or parent gets an Ed25519 device key made in the browser (private half never leaves it, wrapped with the passcode). Approving a payment signs its exact draft (payee, account, amount, currency, purpose, route, expiry, nonce); the policy engine and executor accept a role's approval only if that signature verifies against the role's registered public key, and the proof pack shows "signed by parent device key ab12...". To try the two-person flow, open two browsers: student (Chat tab, "Simulate a family top-up request", approve) then parent (Parent tab, approve).

**Security features:** role-based access, signed approvals, encryption at rest, short-lived single-use executor tokens, a rate-limited and size-limited judge console whose every attempt is logged to `data/redteam_attempts.jsonl` (git-ignored).

## Verifying a proof pack

A proof pack embeds the public keys that signed it, so a pack alone proves nothing: anyone could change the amount, sign with fresh keys and embed those. `verify_proof_pack(pack, trusted_fingerprints=..., chain=...)` therefore only reports `ok` when the fingerprint of the embedded keys (sha256 over the canonical public keys) is one you pinned. The API pins its own: `GET /api/trust/fingerprint` (shown at the top of the Proof tab), and `/api/proof/.../verify` and `POST /api/proof/verify` check against it. Approvals inside the pack are Ed25519 signatures over the exact payment and must come from pinned approver device keys (`approvals_signed`, `approver_keys_pinned`). With a chain available the verifier also checks that the anchor block exists with the intent hash as digest and the chain is intact; standalone verification reports the anchor as "not checked" (and `ok` stays false without a pinned fingerprint).

- Fingerprint of the scripted demo's public keys: `396bbb6e7a75c14fa88bf26bdbee0218a5aefdb48ca3ef9a0f9ff2de3dffdbdf` (anyone can forge with these keys, so never pin them outside the demo).
- A real server's fingerprint is created on first start and printed by the endpoint; pin it out of band (for example in this README for your deployment).

## Known limitations

1. **Authentication is demo-grade.** Roles use shared passcodes (one per role, public demo defaults unless `OASIS_PASS_*` is set), with no per-person accounts or MFA, and approver device keys are trust-on-first-use, so whoever holds a role's passcode can register a new key ([security self-assessment][sec]).
2. **Key files are plaintext unless `OASIS_KEY_PASSPHRASE` is set.** The data key and trust signing key under `data/keys/` are only protected by OS permissions otherwise, so set the passphrase before any recorded demo so plaintext keys are never shown ([hardening][sec-hard]).
3. **FISCO BCOS is a 4-node local test chain** (real FISCO BCOS 3.17.1, all nodes on a single host), opt-in via `OASIS_ANCHOR=fisco`; the labelled simulated chain is the default, and it shows the integration, not decentralised trust ([FISCO BCOS notes][fisco]). Oasis does NOT claim the on-chain challenge bonus: that bonus is for Topic F, and Oasis is Topic C.
4. **PQ-TLS was tested only with an OpenSSL client** (OpenSSL 3.5.9 negotiated X25519MLKEM768 via Caddy); it was not tested in browsers, the certificate is classical, and the app itself still serves plain HTTP ([PQ-TLS evidence][pq]).
5. **Much of the world is mock data.** Route spreads and fees, payment rails and the payee registry are mock; exchange rates can be live (`OASIS_RATES=live`) with a mock fallback ([real vs simulated][rvs]).
6. **There is no API to real banks, and WeIdentity is not integrated.** The registry is made of WeIdentity-style demo credentials, and nothing is ever sent to a real bank ([real vs simulated][rvs]).
7. **Money is stored as floats rounded to whole fen.** This is fine for a sandbox only; production would use `Decimal`, and corridor checks use one hard-coded USD/INR of 88.0.
8. **Demo Run 2 catches the forged invoice at step 3 (Verify), not step 5.** The registry contradicts the account at Verify; the step 5 intent-mismatch catch is shown by the rewritten-payment-instructions attack ([technical documentation][tech]).
9. **Humans in the benchmark are simulated, and the same team wrote the attacks and the defences.** The scripted student and parent approve only requests consistent with the Passport, so 100% results are partly by construction; the blind hidden set mitigates this partly and is now partly burned, because its failures were fixed afterwards ([hidden-set report][hidden]).
10. **Live results are small samples.** After the planner-prompt change (per-plan cap raised to 22,000 tokens, temperature 0.3, a distinct cache salt per repeat) the live planner was valid without fallback in 3 of the 4 plans that fit the free-tier token budget (Tight runway 2 of 3, the miss being a Groq API HTTP 400 tool-call parse error rather than a rejected plan; Arrival shortfall 1 of 1); the other six scenarios were not re-run, so there is no min/mean/max across full planning repeats (the earlier single run was 4 of 8), and the model recorded on those plans was the fallback openai/gpt-oss-120b, not qwen/qwen3.8-27b. The live benchmark ran 3 repeats (temperature 0, then 0.4 and 0.4) with the LLM risk scorer over six injection scenarios: outcomes were identical in every repeat (zero spread), the model followed 0 of 18 embedded injections, and 167 of 183 extractions were served by qwen/qwen3.8-27b and 16 by the fallback ([planning report][plan]). The planning repeats resume with `python -m eval.planning --llm groq --repeats 3 --token-cap 85000` after the daily Groq reset.
11. **The risk scorer is heuristic and was tuned on the benchmark itself (in-sample).** An optional LLM scorer in live mode can only escalate, and neither scorer can see poisoned tool output (0/6), which only intent binding stops.
12. **Regulatory figures are researched but not officially confirmed.** The TCS rate for non-education purposes is a marked placeholder, and the education purpose code is unconfirmed (`oasis/trust/rules/inr_cny.yaml`).
13. **Rate limiting and tokens are per process.** The login throttle (per client address, in memory) and the session and executor token stores reset on restart and do not work across several workers, and one address can be locked out for a minute.
14. **Requests are serialised.** One request runs at a time to protect the single-writer sandbox state, so a slow live-model call blocks the others; time is the simulated clock, not wall time.
15. **The judge role can read the student's data.** It is read-only by design so a reviewer can inspect state, audit and plans, and it cannot call any state-changing student endpoint.
16. **Parser and duplicate-check gaps.** An amount written as `1e5` is read as `1` (digits only, visible in the draft the student signs), and duplicates of invoices older than 30 days are caught only through the paid-obligation check.
17. **Tamil and Hindi parent text is templated and has not been reviewed by native speakers.**
18. **Demo keys are public and seeded.** While a demo world is active the server pins their fingerprint, so a pack forged with the public demo seeds would verify during the demo (`GET /api/trust/fingerprint` reports `demo_keys: true`).

[sec]: docs/security-self-assessment.md
[sec-hard]: docs/security-self-assessment.md#hardening-added-2026-10-10
[fisco]: docs/fisco-bcos.md
[pq]: eval/reports/pqtls.md
[rvs]: docs/real-vs-simulated.md
[tech]: docs/technical-documentation.md
[hidden]: eval/reports/benchmark_hidden_prefix.md
[plan]: eval/reports/planning.md

## What is real and what is simulated

Real: the six-step pipeline, policy engine, hybrid signed intents and intent-enforcing executor, verification ramp, canaries, corridor rules engine, hash-chained audit log, proof packs and verifier, plan validator, the benchmark harness and the Groq adapter. Simulated (labelled MOCK): route spreads and fees (the INR→CNY mid-market rate is a mock snapshot of the real level by default, and the real ECB reference rate with `OASIS_RATES=live`, shown with a live / STALE / MOCK badge; Oasis never predicts rates; see [docs/live-rates.md](docs/live-rates.md)), routes, payment rails and balances, the payee registry (WeIdentity-style demo credentials), wallet spending, humans in the benchmark, the clock, and anchoring by default (a local hash-linked simulation; FISCO BCOS is a 4-node local test chain: real v3.17.1 Air, 4 nodes on one host (WSL2), the `OasisAnchor` contract anchors only sha256 intent digests, and real transaction hashes are in [docs/fisco-bcos.md](docs/fisco-bcos.md). It is opt-in (`OASIS_ANCHOR=fisco`); the default, the tests, the benchmark and the scripted demo use the labelled local simulation). Post-quantum TLS: PQ-TLS is tested: Caddy 2.11.7 (go1.26.8) terminating TLS 1.3 with only `x25519mlkem768`, an OpenSSL 3.5.9 client negotiated X25519MLKEM768 and a classical-only client was refused (`eval/reports/pqtls.md`). Caveats: the certificate is classical (ECDSA from Caddy's internal CA), the test is local on one machine, and browsers were not tested. Full table: [docs/real-vs-simulated.md](docs/real-vs-simulated.md).

## AI as a Financial Participant

What the AI does: reads documents and screenshots (including Chinese text), extracts payment fields, scores risk (a heuristic scorer, plus an optional LLM scorer in live mode that can only escalate), builds and revises a payment plan by calling read-only tools, explains decisions in plain language (and in Tamil/Hindi for a parent), compares routes, watches student-set rate targets, and drafts a recovery message to the legitimate recipient's registry-verified channel.

What the AI never does: hold the payment credential, approve a payment, change a recipient's verification status, edit the audit log, sign an intent, choose a payee account (only the registry-confirmed account is paid), predict exchange rates, or contact anyone on its own. Extraction is untrusted, the risk score can only escalate a decision, a plan is only a proposal that still passes verification, policy, signing and the executor, and recovery drafts are rejected if they contain any account or contact from the suspicious request. Safety never depends on the LLM.

## Deployment

- **Single process (demo/evaluation):** the quick start above. `python -m uvicorn oasis.api.main:app --host 0.0.0.0 --port 8000` serves API and UI. State is SQLite at `data/oasis.db` (`OASIS_DB` to move it, `:memory:` for none).
- **No Node needed to run:** `frontend/dist` is committed (about 190 KB) and served by the API; rebuild it with `npm run build` after UI changes.
- **Not production-ready, by design:** the build serves plain HTTP, the SQLite file is unencrypted, the trust signing keys are an unencrypted git-ignored file (`data/keys/trust_key.json`), and the API has no authentication. A real deployment needs TLS (hybrid X25519MLKEM768 at a reverse proxy; PQ-TLS is tested: Caddy 2.11.7 (go1.26.8) terminating TLS 1.3 with only `x25519mlkem768`, an OpenSSL 3.5.9 client negotiated X25519MLKEM768 and a classical-only client was refused (`eval/reports/pqtls.md`). Caveats: the certificate is classical (ECDSA from Caddy's internal CA), the test is local on one machine, and browsers were not tested; recipe in [docs/pq-tls.md](docs/pq-tls.md)), encryption at rest, a key vault and authentication. See [docs/security-self-assessment.md](docs/security-self-assessment.md).

## Documentation

| Document | Contents |
|---|---|
| [docs/technical-documentation.md](docs/technical-documentation.md) | architecture, algorithms, security design, data model, API, evaluation method |
| [docs/security-self-assessment.md](docs/security-self-assessment.md) | permission tiers, threat model, known risks, out of scope |
| [docs/real-vs-simulated.md](docs/real-vs-simulated.md) | what is working code and what is MOCK |
| [docs/execution-evidence.md](docs/execution-evidence.md) | sandbox logs and reports, how to regenerate them |
| [docs/pq-tls.md](docs/pq-tls.md) | post-quantum TLS recipe, tested with an OpenSSL 3.5 client against Caddy (evidence: [eval/reports/pqtls.md](eval/reports/pqtls.md)) |
| [docs/fisco-bcos.md](docs/fisco-bcos.md) | FISCO BCOS anchoring on a 4-node local test chain, real transaction hashes, how to run and verify |
| [PROGRESS.md](PROGRESS.md) | build ledger |

## LLM configuration and persistence

### Persistence

The API keeps the Passport, audit log, proofs, why-cards, ledger, pending approvals and clock in SQLite (`data/oasis.db`, override with `OASIS_DB`; `OASIS_DB=:memory:` disables it) so state survives an API restart. Tests and the benchmark are in-memory. The database is **encrypted at rest** (AES-256-GCM on every payload column; an old plaintext DB is migrated on first start). The data key lives in `data/keys/data_key.json` (override `OASIS_DATA_KEY`). The trust signing keys are generated once and kept in a git-ignored file (`data/keys/trust_key.json`, override with `OASIS_TRUST_KEY`). All key files are plaintext protected by OS permissions unless you set `OASIS_KEY_PASSPHRASE` (then they are scrypt+AES-GCM wrapped); see the honest limits in the security self-assessment, so the key fingerprint and old proof packs stay valid across restarts. Tests and the benchmark use in-memory keys; the scripted demo uses seeded public demo keys. The red-team sandbox is never persisted.

### LLM configuration

By default Oasis runs **offline** (`OASIS_LLM=offline`): a deterministic parser, risk scorer and explainer, so demos, tests and benchmarks are reproducible with no network. This is the no-network path; there is no local-model or OCR fallback (both deliberately dropped). To use Groq, copy `.env.example` to `.env` and set `GROQ_API_KEY`:

| Variable | Default | Notes |
|---|---|---|
| `OASIS_LLM` | `offline` | `groq` to use Groq |
| `GROQ_API_KEY` | - | the only key needed (text and image intake) |
| `OASIS_AGENT_MODEL` | `qwen/qwen3.8-27b` | Groq **preview** model; accepts images; may be retired at short notice |
| `OASIS_FALLBACK_MODEL` | `openai/gpt-oss-120b` | production model, used automatically if the agent model errors (retired/404, daily limit); no vision |
| `OASIS_REDTEAM_MODEL` | `openai/gpt-oss-120b` | AI red-team generator |
| `OASIS_LLM_RISK` | `0` | `1` adds the LLM risk scorer in live mode (`OASIS_EXTRACT=llm` only); combined as max(heuristic, llm), so it can only escalate |
| `OASIS_TRUST_KEY` | `data/keys/trust_key.json` | where the persistent trust signing keys live (git-ignored) |
| `OASIS_GROQ_RPM` / `_DAILY_TOKENS` / `_DAILY_REQUESTS` | 25 / 180000 / 900 | client-side guard rails under the free tier (about 30 RPM, 1,000 requests/day, 200k tokens/day) |

Model IDs were checked against console.groq.com/docs/models on 2026-10-10. `qwen/qwen3-32b` and `qwen/qwen3.6-27b` are retired. The Groq adapter rate-limits itself, backs off on 429 (honouring `retry-after`), keeps a daily budget on disk, caches every response on disk (`data/llm_cache/`; cache hits cost nothing) and falls back to the second model. If Groq is unavailable the offline parser is the floor. Unit tests use a fake client; the adapter, image intake and the benchmark have also been run live (2026-10-10).

Image intake (`POST /api/intake/image`) sends the picture to the agent model through the same client. The fallback model has no vision, so if the image cannot be read the result is a low-confidence hold asking the student to paste the text or confirm the fields; nothing is guessed. The image is not stored.

Benchmark with a real model, resumable and repeated:

```bash
PYTHONPATH=. .venv/Scripts/python -m eval.runner --llm groq --repeats 3
```

Two extraction modes. Default `--extract deterministic`: the regex parse is the floor and the model only fills empty fields, so results equal the offline benchmark and say nothing about model behaviour. `--extract llm` (or `OASIS_EXTRACT=llm` for the API) is the **live agent** mode: the model's JSON extraction is primary and the regex parse is used only, per field, when the call fails, is unparseable or omits payee_name / account_ref / amount. Whether the model followed an embedded injection is computed by comparing its fields with the document's genuine (pre-injection) fields from the scenario, never from the model. The scorer stays deterministic. Live results go to `eval/reports/benchmark_live.md` with a deterministic reference table; checkpoints are keyed by mode.

```bash
PYTHONPATH=. .venv/Scripts/python -m eval.runner --llm groq --extract llm --repeats 1
```

Free-text purposes ("Tuition fee for Fall 2026 semester", "房租", "deposit (2 months)") are normalised to tuition / rent / deposit / living / family_support by a deterministic mapper applied to both regex and model output. Finished results are checkpointed in `data/bench_cache/`. If the daily budget runs out the run stops cleanly (exit code 2); run the same command again later and it continues. The report shows min / mean / max across repeats. In deterministic mode the unsafe behaviour of the unprotected baseline is modelled by the regex extractor that follows embedded instructions; in live-agent mode it is whatever the model does. Poisoned-tool scenarios (a simulated rewrite of payment details at execution time) are independent of the model in both modes. Safety layers never depend on the model.

Safety never depends on the LLM. Extraction is untrusted. The risk score (a heuristic scorer, plus an optional LLM scorer in live mode that can only escalate) can only escalate a decision. Verification, the policy engine, signed intents and the executor are all deterministic code.

## What the layers add (offline benchmark, 32 attacks + 12 legitimate changes)

| | baseline | +verification | +intents+policy | full (+canaries) |
|---|---|---|---|---|
| Attack block rate | 6.2% | 68.8% | 100% | 100% |
| Money lost (CNY, sandbox) | 479,000 | 108,000 | 0 | 0 |
| Legit completion | 100% | 100% | 100% | 100% |

Canaries are an **early-detection layer, not an extra blocking layer**: they block 0 additional attacks over signed intents + policy, and flag 3 attacks earlier (at Understand, before verification or execution). See `eval/reports/benchmark.md` for all figures, including the risk scorer's accuracy.

## Repository layout

```
oasis/
  agent/        llm.py (offline / Groq / vision), i18n.py + parent.py (Tamil/Hindi/English), pipeline.py
                (six steps, layer switches), autonomy.py (Tier-1: rate targets, recurring bills),
                planner.py (agentic tool-calling planner: offline + Groq), plan_exec.py (accept/run a plan through the
                pipeline), recovery.py (autonomous recovery draft + validation)
  passport/     Student Financial Passport data model
  planning/     route comparison, forecast + triggers, spending categorisation (cold start -> own pattern),
                tools.py (planner tool protocol), validator.py (deterministic plan validator), scenarios.py
  trust/        crypto (Signer interface: Ed25519 + ML-DSA-65 hybrid by default; optional SM2/SM3 via gmssl; PQ-TLS tested with an OpenSSL client against Caddy: docs/pq-tls.md), verification ramp, intents,
                policy engine, corridor rules (rules/inr_cny.yaml), executor, canaries, audit chain
  proof/        proof packs + standalone verifier
  chain/        anchoring interface: LocalAnchorChain (simulated, default); FiscoAnchor (4-node local test chain, real FISCO BCOS 3.17.1, OASIS_ANCHOR=fisco)
  mock/         rates/routes, sandbox ledger, payee registry (WeIdentity-style), wallet/QR fees
  storage.py    SQLite persistence
  demo.py       scripted demo runs (fixed seed, offline)
  api/          FastAPI app
  world.py      wires one student's session together
eval/           scenarios, simulated humans, runner (resumable), planning eval, outcome simulator, demo_log, reports/
frontend/       React 18: demo, chat, Passport, parent view, red-team console, proof viewer, numbers
tests/          pytest
docs/           technical documentation, security self-assessment, real-vs-simulated, execution evidence, PQ-TLS recipe
```

## Agentic planning (spec step 2) and autonomous recovery (step 5)

The agent builds a payment plan by calling read-only tools (`read_passport`, `list_obligations`, `get_rates`, `get_routes`, `check_corridor`, `forecast_runway`) and the proposal-only `propose_plan`. A deterministic validator (`oasis/planning/validator.py`) checks every proposal (each obligation paid in its exact amount, to its own payee, by its due date; CNY arrives before it is spent; the student's INR never negative; SAFE quota per calendar year, so a large tuition is split across two conversions; LRS; INR kept for rate targets; TCS/LRS warnings surfaced) and returns concrete errors so the planner revises (at most 4 proposals). The model can only propose; accepting a plan still sends every payment through verification, signed intents, policy and the executor. Offline a deterministic planner speaks the same protocol; with a Groq key `AgenticPlanner` uses native tool calling and falls back to the deterministic plan (recorded) if it cannot produce a valid one. UI: Passport tab, "Agentic plan" (also shown in demo Run 1). API: `POST /api/plan`, `GET /api/plans`, `POST /api/plan/{id}/accept|execute`. After a freeze the agent drafts the message to the legitimate recipient using only the registry's verified channel; the draft is rejected if it contains any account number or contact from the suspicious request. Results: `eval/reports/planning.md`.


## Licence and third-party components

Oasis is released under the [MIT licence](LICENSE). Dependencies and their licences (read from installed package metadata, 2026-10-10); none is copyleft:

| Component | Licence |
|---|---|
| FastAPI, Pydantic, PyYAML, pytest | MIT |
| Starlette, Uvicorn, HTTPX, python-dotenv, websockets | BSD-3-Clause |
| PyNaCl, Groq SDK, python-multipart | Apache-2.0 |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| gmssl (optional SM2/SM3) | BSD |
| httptools, watchfiles (pulled in by `uvicorn[standard]`) | MIT |
| React 18, React DOM, Vite 5, @vitejs/plugin-react | MIT |
| Frontend build-time transitive packages (`node_modules`) | MIT (55), ISC (5), Apache-2.0 (1), BSD-3-Clause (1), CC-BY-4.0 (1: `caniuse-lite` browser-support data, attribution required, build-time only, not shipped in `dist`) |

Groq models (`qwen/qwen3.8-27b`, `openai/gpt-oss-120b`) are used as a hosted service under Groq's terms and are not redistributed. Licences of every transitive Python package were not exhaustively audited beyond the table above.
