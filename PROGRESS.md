# Oasis — Progress Ledger

Submission deadline: **20 Oct 2026, 23:59 Beijing (21:29 IST)**. Update this file at the end of every work session.

Status key: ✅ done · 🟡 partial / stub · ⬜ not started · ❌ blocked

## Tech stack (as built)

| Layer | Choice | Status | Notes |
|---|---|---|---|
| Language / runtime | Python 3.10 venv (`.venv`) | ✅ | Run with `PYTHONPATH=.` |
| Backend API | FastAPI + Uvicorn | ✅ | `oasis/api/main.py`; also serves built frontend |
| Data model | Pydantic v2 (Student Financial Passport) | ✅ | |
| Persistence | SQLite (stdlib) for Passport, audit, proofs, why-cards (+ledger, pending, clock) | ✅ | `oasis/storage.py`; API default `data/oasis.db`; tests/benchmark in-memory; keys not stored; file unencrypted |
| Policy engine | Pure Python, deterministic, versioned rules (R01–R14) | ✅ | `oasis/trust/policy.py`, ruleset 2026.10.2 |
| Corridor rules | YAML data + Python checker | ✅ | figures still need official confirmation |
| Signatures | Ed25519 (PyNaCl) + ML-DSA-65 (`cryptography`, FIPS 204), hybrid | ✅ | liboqs not needed |
| SM2 signer (optional) | `SM2Signer` on `gmssl` 3.2.2 (GB/T 32918 + SM3); `sm2_hybrid_signer` | ✅ | Standard Fp-256 test vector reproduced exactly (`tests/test_sm2.py`; vector values entered from memory, the exact match authenticates them). Pure Python, not constant-time, unaudited; interop with other SM2 libraries untested. Default scheme stays Ed25519 + ML-DSA-65 |
| Audit log | SHA-256 hash chain + verifier | ✅ | entries now deep-copied on append |
| Anchoring | Local simulated chain (clearly labelled) | 🟡 | FISCO BCOS adapter is a stub; decision: stay with the labelled simulation |
| Payee registry | WeIdentity-style hybrid-signed credentials (mock) | ✅ | Demo identities |
| Agentic planner (`oasis/agent/planner.py`, `planning/tools.py`, `planning/validator.py`) | 7 JSON-schema tools (6 read-only + proposal-only `propose_plan`), validator rules, 4-proposal loop, offline `DeterministicPlanner`, `AgenticPlanner` over `GroqLLM.chat_tools` (cache, rate limit, budget, model fallback shared with the adapter), fallback recorded | 🟡 | Fake-client tests plus live run on 3 of 8 scenarios (1 valid without fallback; 2 hit the per-plan token cap and fell back). qwen3.8-27b is limited to 7,000 input tokens/minute and once emitted garbled tool-call arguments; gpt-oss-120b sometimes answers with the plan as text (parsed and validated). Live behaviour beyond that is unverified |
| Agent LLM | Groq `qwen/qwen3.8-27b` (preview) with automatic fallback to `openai/gpt-oss-120b` | 🟡 | Rate limit, 429 backoff, daily budget, disk cache, fallback on 404/daily limit: fake-client tests plus live smoke test 2026-10-10 (extract, explain incl. Tamil, JSON mode, fallback on a dead model id all verified against the real API) |
| Red-team LLM | Groq `openai/gpt-oss-120b` | 🟡 | Live call works; prompt now carries the scenario context and variants are filtered (must have Account/Amount lines) else templates; offline uses fixed templates |
| Vision | Groq agent model (same key, cache, limiter); failure -> low-confidence hold | 🟡 | Verified live once on a generated invoice PNG (all fields read correctly); more image types untested; SiliconFlow removed |
| Live-agent extraction (`OASIS_EXTRACT=llm`, `--extract llm`) | Model JSON is primary; regex only as per-field fallback; `followed_injection` computed from scenario ground truth | 🟡 | Fake-client tests + one live benchmark run (repeats 1). Default demo/tests/offline benchmark unchanged (deterministic) |
| Purpose normaliser | Deterministic mapping of free text (English/Chinese) to tuition/rent/deposit/living/family_support, applied to regex and LLM output | ✅ | Unknown purposes are kept as-is, never guessed |
| Offline path | Deterministic regex extractor + heuristic risk scorer + templated explainer | ✅ | Deliberately follows injections (models a gullible agent). Local model (Qwen3-4B) and PaddleOCR dropped |
| Frontend | React 18 + Vite | ✅ | All 7 tabs browser-checked 2026-10-10 (Playwright), favicon added, MOCK labels. Agentic plan panel (plan, schedule, tool-call trace, validator feedback, why-this-plan, accept/run) in the Passport tab and demo Run 1. Re-checked at 375px and 1280px after adding it: no horizontal page scroll on any tab, 16px side gutter; fixed grid and Numbers-table overflow |
| Tests | pytest | ✅ | 142 passing (2026-10-10; includes the planning/recovery and SM2 tests) |
| TLS (hybrid ML-KEM) | — | ⬜ | Not implemented; documented |

## Pipeline steps

| Step | Status | Notes |
|---|---|---|
| 1 Understand | ✅ | Text intake; image intake via Groq (one live PNG check) |
| 2 Plan | ✅ | Routes, savings, triggers, spending categorisation + cold-start -> own-pattern forecast, rate targets. **Agentic planning** (tool-calling planner proposes, deterministic validator checks, bounded revise loop; offline planner + Groq native tool calling with recorded fallback; plan execution via the normal pipeline): offline 8/8 scenarios valid, live run only 3/8 (token budget) |
| 3 Verify | ✅ | Ramp + test payment + limits; registry-aware risk score |
| 4 Commit | ✅ | Signed intents, tiers, parent co-approval (Tamil/Hindi/English) |
| 5 Execute & watch | ✅ | Executor checks, canaries (early detection), freeze + recovery plan + student approval; recovery message drafted for the registry's verified channel only (live-model draft validated against the suspicious request, else template) |
| 6 Prove | ✅ | Proof packs, why-cards, savings, reputation |
| Tier-1 autonomy | ✅ | Rate-target conversions (R13), recurring bills to Verified_Full (R10), visible in the UI |

## Evaluation

| Item | Status | Result / note |
|---|---|---|
| Benchmark (32 attacks, 12 legit, 4 configs) | ✅ offline | baseline 6.2% blocked / CNY 479,000 lost; +verification 68.8% / 108,000; +intents+policy 100% / 0; full 100% / 0; legit completion 100% in all; false-block 0% |
| Canaries | ✅ reframed | Early detection: 0 extra blocks over signed intents, 3 attacks flagged earlier |
| Risk scorer | ✅ | Flags 81% of attacks (26/32), 0% of legit (0/12); accuracy 86%, precision 1.0, recall 0.81; first-step-only 69% (was 44%); poisoned tool 0/6 by nature; in-sample |
| Benchmark with real LLM, deterministic extraction (`--llm groq --repeats N`) | 🟡 | One run 2026-10-10: identical to offline by construction (regex is the floor, model only fills gaps), so it says nothing about model behaviour; shows only that the live model does not break the pipeline |
| Benchmark, live-agent extraction (`--llm groq --extract llm`) | 🟡 | One run (repeats 1, qwen/qwen3.8-27b, 9 AI red-team variants), report `eval/reports/benchmark_live.md`: the model followed 0 of 6 hidden injections; 0 of 61 steps fell back to regex; baseline loses CNY 380,000 vs 479,000 deterministic (model resisted the injections the regex agent follows); other three configs identical to deterministic. n=6 injections, one repeat, temperature 0: not a robustness claim. repeats 3 not run |
| AI red-team variants | 🟡 | Templates offline (4); 9 variants in the live run |
| Plan-quality evaluation (`python -m eval.planning`, `eval/reports/planning.md/.json`) | ✅ offline / 🟡 live | Offline (deterministic planner): 8/8 valid, mean 1.5 proposals to valid (max 2), 20/20 deadlines met, conversion fees CNY 5,138 vs 29,867 via a typical bank route (-82.8%, MOCK rates). Live (Groq, 1 run, scenarios shortfall / SAFE-quota tuition / parent TCS only): final plans 3/3 valid but 1/3 without fallback (shortfall: valid on proposal 3); the other two were stopped by the per-plan token cap and the deterministic plan was reported. Live spend 2026-10-10: 61.6k tokens including debugging runs (ledger 37.4k -> 99.0k). 5 scenarios not run live. One run, temperature 0: not a robustness claim |
| 5-persona 90-day simulation | ✅ | Savings driven by mock fees — label as such |
| Live red-team console | ✅ | Separate sandbox ledger |
| Scripted demo (spec section 19) | ✅ | Step-by-step API + Demo tab; repeatable (same audit head); no network. Run 1 step 1 now includes the agent's plan (tool-call trace, one validator revision, why-this-plan) |

## Submission deliverables

| # | Deliverable | Status |
|---|---|---|
| 1 | Technical documentation | ✅ `docs/technical-documentation.md` (architecture, algorithms, R01-R14, security design, data model, 33-endpoint API list, evaluation method), final pass 2026-10-10 |
| 2 | Presentation deck (≤10 min) | ⬜ |
| 3 | Demo video (≤5 min) | ⬜ |
| 4 | Source code (GitHub, README, tests) | 🟡 README, MIT `LICENSE`, `.gitignore` and licence table ready; no git repo yet (first commit to a private repo still to do) |
| 5 | Security self-assessment | ✅ `docs/security-self-assessment.md` (tiers, threat model, known risks incl. live findings, out of scope), final pass 2026-10-10 |
| 6 | Execution evidence (sandbox logs) | ✅ `docs/execution-evidence.md` + `eval/reports/` (offline and live benchmark, planning, simulation, demo log with audit heads). No on-chain hashes (anchoring is simulated) |

## Open decisions

- [x] Canaries: kept, reframed everywhere as an early-detection layer (not an extra blocking layer).
- [x] Offline local model (Qwen3-4B) and PaddleOCR: dropped; the deterministic parser is the no-network path.
- [x] Persistence: SQLite added; in-memory stays the default for tests/benchmark.
- [x] FISCO BCOS: stay with the clearly labelled local simulation; adapter stub documented honestly.
- [x] Models: Groq `qwen/qwen3.8-27b` + fallback `openai/gpt-oss-120b`; vision on Groq (SiliconFlow removed).
- [ ] Hero university and its real tuition payment method
- [ ] Native-speaker review of the Tamil and Hindi wording
- [x] Live Groq benchmark repeats 1, fallback and image intake verified against the real API (repeats 3 still optional)
- [x] `.env` has no SILICONFLOW line any more (checked 2026-10-10); it still carries a stale `OASIS_VISION_MODEL` comment/line that nothing reads. `.env` is git-ignored and holds the only real key
- [ ] The two source `.md` files in `D:\china_hackathon` still say CanaryPay (intentionally untouched)

## Log

| Date | Work done |
|---|---|
| 2026-10-10 | Verified Groq model IDs/limits; scaffolded Oasis; built trust layer, pipeline, eval, API, frontend, docs; 24 tests pass; offline benchmark run |
| 2026-10-10 | Groq adapter hardened (fallback, 429 backoff, rate limit, daily budget); Groq vision replaces SiliconFlow; resumable benchmark with spread; SQLite persistence + reset; scripted demo mode (both runs, repeatable); Tier-1 autonomy (rate targets, recurring bills); registry-aware risk scorer (44% -> 81% attack flag rate, 0% legit); Tamil/Hindi parent view; spending categorisation + forecast switch; canaries reframed; UI rebuilt and all tabs checked in a browser; docs updated; 63 tests pass |
| 2026-10-10 | Live Groq session: smoke test (extract benign/injected/Chinese, why_stopped, Tamil parent text, red-team, PNG intake) all parsed; fallback to gpt-oss-120b verified with a dead model id and the dead model skipped afterwards; red-team prompt fixed (it produced off-topic GBP invoices) and variants now validated; full live benchmark done, matches offline; ~36k tokens / 96 requests used today; 64 tests pass |
| 2026-10-10 | Live-agent extraction mode (model primary, regex per-field fallback, honest followed_injection from scenario ground truth), purpose normaliser (English/Chinese), mode-keyed checkpoints, `benchmark_live.md` with provenance and deterministic reference; live run repeats 1 (~1.4k new tokens, nearly all responses cached from the earlier run; ~37.4k of 200k used today); offline `benchmark.md` regenerated; 97 tests pass |
| 2026-10-10 | Agentic planning and autonomous recovery: tool protocol + deterministic plan validator (SAFE per calendar year, LRS/TCS, deadlines, funds, rate-target reserve), offline `DeterministicPlanner`, Groq `AgenticPlanner` via `chat_tools` with recorded fallback, plan accept/execute through the normal pipeline, registry contact channels and validated recovery drafts; API `/api/plan*`; Passport-tab plan panel and demo Run 1 integration; `eval/planning.py` (8 scenarios: offline 8/8 valid; live 3 scenarios, 61.6k tokens); responsive fixes; 142 tests pass |
| 2026-10-10 | Final documentation pass: README rewritten (pitch, mermaid architecture, quick start, results with caveats, AI-as-participant, deployment, licences); technical documentation gained policy table, data model, security design, full API list; SM2 no longer described as a stub; security self-assessment updated with live findings; `docs/execution-evidence.md` and `eval/demo_log.py` (+ `eval/reports/demo.*`) added; MIT `LICENSE`; `.gitignore` hardened (frontend/dist deliberately committed); unused `openai` removed from requirements.txt; secret scan clean except the git-ignored `.env`; 142 tests pass |
