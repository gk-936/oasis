# Oasis: technical documentation

## 1. Architecture

```
Frontend (React 18) ── FastAPI (oasis/api/main.py)
                          │
                    OasisAgent (oasis/agent/pipeline.py)
   1 Understand ── LLM extraction (untrusted) + canary scan (early detection) + risk score (registry-aware, an input only)
   2 Plan       ── route ranking, conversion, forecast triggers, corridor costs
   3 Verify     ── Verifier (registry credential → test payment → limits)
   4 Commit     ── corridor check → policy engine → approvals → signed intent → anchor
   5 Execute    ── Executor: signature + exact match + nonce/expiry + policy re-check → sandbox ledger
   6 Prove      ── proof pack, audit chain, savings receipt, reputation, "Why was I stopped?" card
```

`World` (`oasis/world.py`) wires one student's Passport, mock layer and trust modules together. `Features` switches layers on and off: `baseline` (all off; the agent holds the credential and pays what it extracted), `+verification`, `+intents+policy`, and `full` (adds canaries). The baseline is the same pipeline with the same LLM and tools.

## 2. Core algorithms

**Route scoring.** `delivered = (send − fixed_fee) × mid × (1 − spread) × (1 − pct_fee)`. Routes that would miss the due date are excluded. The rest are ranked by delivered amount, then speed, then reliability. Savings are reported against the typical bank route. The amount to send is found by binary search on the same formula. Conversions are at least CNY 500 because fixed fees make tiny conversions wasteful.

**Agentic planning** (`oasis/agent/planner.py`, `oasis/planning/tools.py`, `oasis/planning/validator.py`). The planner is a tool-using agent whose only outputs are proposals. Tools (JSON-schema function tools): `read_passport`, `list_obligations`, `get_rates`, `get_routes(send_inr, due)`, `check_corridor(amount_inr, purpose, remitter)`, `forecast_runway` (all read-only) and `propose_plan(steps, rationale)` (proposal only). No tool moves money, signs, or edits the Passport (`tests/test_planning.py::test_tools_are_read_only_or_proposal_only`). A plan is a list of `convert` steps (date, INR, route, remitter student or parent) and `pay` steps (date, obligation, payee, CNY). `validate_plan` simulates the plan chronologically and returns errors with hints: unknown obligation, payee or route; wrong payee or amount; late payment; unfunded or duplicated obligation; INR going negative; CNY not yet arrived when spent (route too slow); SAFE quota exceeded (USD 50,000 equivalent per calendar year, counted over all conversions, which is why a very large tuition is split across December and January); LRS exceeded; INR needed by a pending rate target no longer unconverted; frozen obligations. Warnings never block: TCS with the amount (per remitter, cumulative), approaching TCS or SAFE limits, parent-remitted conversions (need the parent's consent), conversions that fall below CNY 500, a cheaper route that would also arrive on time, low runway after the plan, income that has not arrived (never counted), and that payments above the Tier-1 limit will wait for the student. Rates are quoted at today's mock rate for the whole horizon: a quote, not a forecast. The loop allows 4 proposals; the validator's errors go back to the model as tool results. `DeterministicPlanner` (offline) uses the same tools: it drafts a student-funded plan staged by calendar-year SAFE room, and revises from the validator's errors (for example, a shortfall adds a parent-remitted conversion). `AgenticPlanner` (Groq) calls `GroqLLM.chat_tools`, which has native tool calling with the adapter's cache, rate limiter, 429 backoff, daily budget and model fallback (a plan written as plain JSON text is parsed as a `propose_plan` call and validated the same way). If the model cannot produce a valid plan inside the loop, hits its token cap, or the API fails, the deterministic plan is used and `fell_back` / `fallback_reason` are recorded in the plan and the trace. A plan is stored as a proposal. `plan_exec.accept_plan` re-validates and records the student's acceptance; `execute_due` then runs the steps due today: every `pay` step becomes an ordinary request built from the Passport and registry and goes through the full pipeline (so it waits for approval above the Tier-1 limit), and every `convert` step is decided by `decide_conversion` (a parent-remitted one also needs the parent's consent). Later steps stay scheduled.

**Forecast triggers.** These are shortfall (within 21 days), rate move (±1% over 7 days), low runway, late income and student-set rate targets. The agent never predicts rates. Burn rate starts from the student's budget plus labelled reference costs (cold start). Transactions are categorised by keyword rules (`oasis/planning/spending.py`); once there are at least 14 days and 15 transactions the forecast switches to the student's own per-category daily average x 30 with a damped, clamped trend, and the dashboard shows which basis is in use and a backtest error (forecast the last 7 days from the earlier data). Wallet spending in the demo is imported mock data.

**Verification ramp (state machine).** `UNVERIFIED -> REGISTRY_CHECKED -> (CNY 1 test payment) -> VERIFIED_LOW (limit CNY 5,000) -> VERIFIED_FULL (after 2 successful payments)`; any contradiction by the registry gives `REJECTED` without touching the genuine record. The registry is looked up by payee ID, falling back to an exact name match. If the account on the request differs from the credential, the request is REJECTED and the genuine record is untouched. A match with a changed account resets the recipient to unverified, then REGISTRY_CHECKED, then a CNY 1 test payment, then VERIFIED_LOW (CNY 5,000 limit), then VERIFIED_FULL after 2 successful payments. Only the registry-confirmed account is ever used for payment; the account on the request is not.

**Policy engine** (`oasis/trust/policy.py`, ruleset 2026.10.2, rules evaluated in this fixed order; the first match decides; every decision records its rule ID):

| Rule | Decision (tier) | Condition |
|---|---|---|
| R01 | freeze (3) | a canary fired |
| R02 | freeze (3) | amount above the hard limit (CNY 200,000 default) |
| R03 | freeze (3) | the registry contradicts the recipient |
| R04 | freeze (3) | risk score >= 0.85 (escalation only) |
| R04b / R04c | allow (1) / freeze (3) | verification test payment: up to CNY 10 and only to a registry-confirmed recipient / otherwise |
| R15 | hold (2) | the document demands a currency other than CNY; Oasis settles CNY only and never pays it as if it were CNY (needs a corrected CNY invoice, no approval overrides it); evaluated before R05 |
| R05 | hold (2) | recipient not yet verified; the ramp must finish, no approval overrides it |
| R17 | hold (2) | duplicate payment: the same invoice reference, the identical document (30-day window) or an already-paid obligation was paid before (`oasis/agent/duplicates.py`). The why-card says "You already paid this on <date>, proof <id>". No approver is offered (`duplicate_confirmation`), so `/api/approve` refuses it; the student's explicit `POST /api/pay-again` starts a fresh draft that still needs the student's signature and carries the warning; instalments against an open obligation are not duplicates; evaluated after R05, before R06 |
| R06 | hold (2) | corridor hold (LRS, purpose mismatch, split payments; splits that dodge parent approval need the parent) |
| R07 | hold (2) | amount above the recipient's ramp limit (explicit student approval) |
| R08 | hold (2) | risk score >= 0.5 (no approval releases it) |
| R09 | (sets approvers) | family-support transfer above INR 50,000 requires student and parent; shows up as R11 until both approve |
| R10 | allow (1) | recurring payment up to the Tier-1 limit (CNY 500) to a Verified_Full recipient, not family support |
| R11 | hold (2) | required approvals missing; a part payment (instalment, below the obligation's remaining amount) is never automatic and always lands here for the student |
| R12 | allow (2) | all required approvals present, recipient verified, within limits |
| R13 | allow (1) | conversion into the student's own balance at a student-set rate target, within the auto limit (CNY 5,000) |
| R14 | allow (2) / hold (2) | conversion above the auto limit: approved by the student / waiting for the student |

R16 (`out_of_band_verification`, raised by the pipeline in `oasis/agent/pipeline.py` before any payment logic, classified by `oasis/agent/request_types.py`) holds, tier 2, with a why-card and no approval path, a document that asks for something Oasis never does from a document: change who approves or an approval limit (always), a refund or reversal, a payment demand from an authority that is not in the Passport, or a message (not a structured invoice) announcing new bank details. Nothing is actioned and no payment is attempted; the student confirms through a registry-verified contact. A structured invoice with new bank details still goes through the verification ramp (re-verified against the registry, not blocked).

Tiers: 1 = the agent may act alone within bounds, 2 = needs explicit human approval, 3 = never (freeze).

**Signed intents.** The canonical JSON is the intent minus its signatures, with sorted keys and no whitespace. It is signed with Ed25519 and ML-DSA-65, and both must verify. Each intent carries a nonce, a `not_after` timestamp and the approvals with their timestamps. The SHA-256 hash of the intent is anchored.

**Crypto-agility.** All signing goes through the `Signer` interface (`Ed25519Signer`, `MLDSA65Signer`, `SM2Signer`). The default `HybridSigner` is Ed25519 + ML-DSA-65 and both must verify. `SM2Signer` (GB/T 32918 with SM3, default ID `1234567812345678`) is implemented and optional, on the `gmssl` 3.2.2 package; `sm2_hybrid_signer` builds a hybrid that includes it. The implementation reproduces the standard Fp-256 SM2 test vector (`tests/test_sm2.py`; the vector values were entered from memory, and the exact match authenticates them). It is pure Python, not constant-time and unaudited, so it is a crypto-agility demonstration, not production key handling; interoperability with other SM2 libraries is untested. Signatures are keyed by algorithm name, so an algorithm can be swapped (for example, to a future ICCS NGCC standard) without touching callers. ML-DSA-65 signatures are about 3.3 KB, so only hashes are anchored.

**Canaries.** There are three decoys: a fake bank token in the agent's tool context, a decoy payee record in the Passport, and a decoy account number. Extracted fields, tool calls and the executor payload are all scanned, and any hit freezes the payment. In the benchmark canaries are an early-detection layer, not an extra blocking layer: 0 additional attacks blocked over signed intents + policy; 3 flagged earlier, at Understand, before verification or execution.

**Extraction normalisation and layouts.** `regex_fields` reads `Key: value` lines, markdown/ASCII tables, `Key - value` / `Key = value` and bold keys (`canonical_text`), and records the stated currency. The account number is normalised for comparison (`normalize_account`: NFKC so full-width digits become ASCII, zero-width and other format characters removed, spaces and dashes stripped; letters that merely look like Latin or digits are never folded) and compared exactly with the registry per payee, so normalisation cannot turn an attacker's number into a registered one. The raw text still goes to the risk scorer, which flags hidden or look-alike characters in the account line as evidence. The same normalisation is applied to what a live model returns.

**Instalments.** An `Obligation` tracks `amount_paid` (`remaining`, status `partially_paid` then `paid`). A payment to the registered payee below the remaining amount is an explicit instalment: never Tier-1 automatic, always R11 for the student; the simulated student approves it because it is consistent with the Passport. A payment above the remaining amount is a mismatch and stays a hold.

**Audit chain.** Each entry stores `hash = SHA-256(canonical{i, ts, kind, data, prev})`. `verify_chain` recomputes the chain and reports the first broken link.

**Proof pack.** A proof pack contains the intent, intent hash, verification state, costs, policy decision, audit entry and anchor block, plus the trust public keys. It is hybrid-signed. `verify_proof_pack(pack, trusted_fingerprints, chain)` needs no secrets but needs a pinned key fingerprint: the keys in the pack prove nothing by themselves, so `key_pinned` must be true (fingerprint = sha256 of the canonical public keys, `GET /api/trust/fingerprint`), and with a chain the anchor block must exist with the intent hash as digest on an intact chain (`anchor_on_chain`; null = not checked). Trust keys persist in `data/keys/trust_key.json` (git-ignored, `OASIS_TRUST_KEY`); the scripted demo uses seeded public keys.

**Corridor rules** (`oasis/trust/rules/inr_cny.yaml`, data rather than code):

| Rule | Value | Action |
|---|---|---|
| LRS | USD 250k per remitter per financial year | hold |
| TCS | per purpose, from `tcs_by_purpose` in the YAML: education 2% above INR 10 lakh, education-loan nil, other purposes (rent, deposit, living, family support) 20% above INR 10 lakh; all three are secondary-sourced and the message says "UNCONFIRMED/secondary-sourced" | warn, with the amount |
| Education purpose code | S0305 (unconfirmed) | shown |
| Rule sources | every rule has `source`, `retrieved`, `confidence`, `status` (confirmed-primary / researched-secondary / unconfirmed) | `GET /api/corridor/rules`; Passport tab card |
| SAFE quota | USD 50k per person per calendar year, cumulative (`safe_used_inr`), the same arithmetic as the plan validator | warn and stage |
| Wallet foreign-card fee | 3% over CNY 200 | added to route cost |
| Split payments | 2 or more payments to the same payee within 72 hours, each just under an approval threshold | hold |

**Risk scorer.** `heuristic_risk` (offline) scores urgency language, instructions addressed to the assistant, lookalike and partly matching payee names, an account the independent registry contradicts (a changed account the registry confirms is not flagged), unknown payees, amount mismatch, and amounts just under an approval threshold repeated to the same payee. Its score can only escalate a decision (hold at 0.5, freeze at 0.85). With a live model the same interface is used, and the score is still only an input.

**Autonomous recovery** (`oasis/agent/recovery.py`). After a freeze or rejection the agent builds the recovery plan from the registry's verified channel for the legitimate payee (`registry.contact`, MOCK) and the Passport obligation only. With a live model, `GroqLLM.draft_recovery` writes the message; the model is never shown the suspicious request. `validate_draft` then rejects any draft that contains an account number, phone number, email, link or handle found in the suspicious request, any contact other than the registry's own, or any long digit string; a rejected draft is replaced by the template and the rejection is shown. Offline always uses the template. Nothing is sent: the student approves first.

**Tier-1 autonomy** (`oasis/agent/autonomy.py`, rules R10 and R13 in `policy.py`). A student sets a rate target ("convert CNY 2,000 if the rate reaches 0.0700"); the agent watches the mock rate, never predicts it, and `decide_conversion` allows a conversion up to the student's auto limit (CNY 5,000), holds a larger one for the student, and freezes if a canary tripped. Recurring bills (a mock mobile plan) are paid through the full pipeline, taking the recipient's account from the Passport, and are automatic only for a Verified_Full recipient within the CNY 500 Tier-1 limit (R10); otherwise they are held. Every action is in the Passport's autonomy log and the audit chain.

**Persistence** (`oasis/storage.py`). SQLite via the standard library. The audit log is written entry by entry; the Passport, ledger, proofs, cards, pending approvals, clock and registry facts are saved as a snapshot after each state-changing request, and restored on start. Keys are not stored.

**Scripted demo** (`oasis/demo.py`). Fixed seed, fixed mock data, offline model, seeded demo keys/nonces and the simulated clock, so each run reproduces the same audit-chain head. Run 2 catches the forged invoice at Verify (the registry contradicts the account); the step-5 intent-mismatch catch is shown by the second attack (rewritten payment instructions).

**Parent view.** Explanations in English, Tamil and Hindi are templated (`oasis/agent/i18n.py`); a live model may rewrite them, but the rewrite is accepted only if every number survives unchanged. The wording has not been reviewed by a native speaker.

**Groq adapter.** Primary `qwen/qwen3.8-27b`, automatic fallback to `openai/gpt-oss-120b` on retired-model/404 or daily-limit errors (a gone model is skipped for the rest of the process), client-side rate limit, backoff honouring `retry-after` on 429, a daily token/request budget kept on disk, a response cache, `<think>` stripping. Image intake uses the primary model only (the fallback has no vision); failure becomes a low-confidence hold. Covered by tests with a fake client and exercised against the live API (smoke test and benchmark runs, 2026-10-10).

**Two extraction modes.** (1) *Deterministic* (default for the demo, tests and offline benchmark): a regex parse is the floor; the offline parser deliberately follows embedded instructions to model a gullible agent; a Groq model, if present, only fills fields the regex left empty. A live run in this mode is therefore numerically identical to the offline run and does not test the model. (2) *Live agent* (`OASIS_EXTRACT=llm`, `eval.runner --llm groq --extract llm`): the model's JSON is the primary extraction. The regex parse (which does not follow instructions) is used only when the call fails or is unparseable (all fields), or per field when payee_name / account_ref / amount is missing; `Extraction.sources` records `model` / `regex` / `none` per field. The model is never asked whether it followed an injection: the benchmark derives the document's genuine fields from the scenario text before the embedded instruction and marks the model as having followed it if its account, amount or payee id differ. The risk scorer, verification, policy, intents and executor are identical in both modes. In both modes a deterministic normaliser maps free-text purposes (including Chinese: 学费, 房租, 押金, 生活费) to tuition / rent / deposit / living / family_support; unknown purposes are kept unchanged.

## 3. Data model

The **Student Financial Passport** (`oasis/passport/models.py`, Pydantic v2) holds: `student` (id, name, home/host currency INR/CNY, language, monthly budget); `balances` per currency; `obligations` (id, type tuition/rent/deposit/living/family_support, payee_id, amount, currency, due date, status pending/planned/paid/frozen, recurrence); `recipients` (id, name, type, account reference, and a `Verification` of method, level, limit, successful payments, notes); `rules` (Tier-1 auto limit, parent co-approval threshold INR 50,000, hard limit, runway alert, rate targets); `approvers` (role, name, language); `remitted_inr_fy` (per remitter, for LRS/TCS); `safe_used_inr` (per calendar year, for the SAFE quota); `funding_source` (self / education loan); `expected_income`; `transactions` (categorised wallet spending); `autonomy_log` (Tier-1 actions); and `reputation` (on-time verified payments, proof references). Verification levels: UNVERIFIED, REGISTRY_CHECKED, VERIFIED_LOW, VERIFIED_FULL, REJECTED.

Other persisted objects: **payment intent** (payee, account, amount, currency, route, nonce, `not_after`, approvals, signatures per algorithm), **audit entry** (`i, ts, kind, data, prev, hash`), **proof pack**, **why-card** (plain-language reason a payment was stopped), **plan** (steps, rationale, tool-call trace, validator feedback, fallback flag, per-step status), and **ledger** entries (sandbox). SQLite persistence is in `oasis/storage.py` (audit log per entry; the rest as a snapshot per state-changing request).

## 4. Security design

- **Trust boundary.** Documents, screenshots, web pages, tool output and every LLM output are untrusted. The policy engine, intent builder/signer, executor, verification ramp, registry interface and audit log are deterministic code. Only the `Executor` holds the (sandbox) payment credential.
- **Signed intents bind approval to execution.** The executor pays only if both signatures verify, the payload equals the intent exactly (payee, account, amount, currency, route), the intent is unexpired and its nonce unused, and the policy, re-evaluated at execution time, still says `allow`. Any failure freezes the payment. This is what stops poisoned-tool rewrites and replays.
- **Registry, not request, is the source of the account.** The account on a request is treated as forgeable; the registry-confirmed account is the only one paid.
- **Escalate-only AI.** Risk scoring is a heuristic scorer, plus an optional LLM scorer in live mode (`OASIS_LLM_RISK=1` with `OASIS_EXTRACT=llm`) that can only escalate: the two are combined as max(heuristic, llm), a failed LLM call falls back to the heuristic and is recorded, and responses are cached. The risk score can raise a decision to hold (0.5) or freeze (0.85), never lower it. LLM text for the parent view must keep every number unchanged or it is discarded. Recovery drafts are validated against the suspicious request.
- **Tamper evidence.** Hash-chained audit log, hybrid-signed proof packs verifiable without secrets, intent hashes anchored (a labelled local simulation by default; a 4-node local test chain (real FISCO BCOS 3.17.1) with `OASIS_ANCHOR=fisco`, see `fisco-bcos.md`).
- **Crypto-agility and post-quantum.** Hybrid Ed25519 + ML-DSA-65 by default; optional SM2/SM3. TLS with hybrid ML-KEM is tested with Caddy 2.11.7 and an OpenSSL 3.5.9 client (X25519MLKEM768 negotiated, classical-only client refused; `eval/reports/pqtls.md`, `pq-tls.md`); the certificate is classical, it is one machine, browsers were not tested, and the app itself still serves plain HTTP unless the proxy is run.
- **Access control.** Roles student/parent/judge with HMAC-signed 1-hour session tokens in HttpOnly SameSite=Strict cookies (`oasis/api/auth.py`); every endpoint declares its allowed roles (401/403).
- **Signed approvals.** An approval is an Ed25519 signature over `oasis-approval-v1|role|draft_hash` (draft = payee, account, amount, currency, purpose, route, not_after, nonce). Private keys are generated in the approver's browser (`frontend/src/crypto.js`); the server's `ApproverRegistry` holds public keys. The pipeline, policy engine input and executor accept only roles with a verified signature; the intent stores the approval records; `verify_proof_pack(..., approver_key_ids)` re-checks them offline. Sandbox worlds (benchmark, demo, red team, tests) use in-process simulated device keys (`SimDevices`).
- **Encryption at rest.** `oasis/storage.py` AES-256-GCM per payload column with row-bound associated data; data key in `data/keys/data_key.json` (`OASIS_DATA_KEY`), optional scrypt passphrase wrapping (`OASIS_KEY_PASSPHRASE`, `oasis/trust/keyfile.py`); plaintext DBs are migrated once, wrong keys and injected plaintext rows refused.
- **Tool tokens.** `SandboxLedger.mint_tool_token` issues a 30 s, single-use token bound to intent id, accounts, amount and currency; the executor mints one per execution and the agent never sees it.
- **Red-team console.** Judge only, separate world, 20 attempts/min/client, size limits, every attempt appended to `data/redteam_attempts.jsonl`.
- Threat model, permission tiers and known risks: `security-self-assessment.md`.

## 5. Evaluation
- `eval/planning.py`: eight planning scenarios (shortfall, tight runway, SAFE-quota tuition, late scholarship, parent remitter crossing TCS, rate target, five obligations, urgent deposit) scored by the validator: valid-plan rate, proposals to first valid plan, fallbacks, deadlines met, conversion fees against the same INR through a typical bank route. Offline: 8 of 8 valid, 1.5 proposals on average, 20 of 20 deadlines, fees 82.8% lower than the bank route (MOCK rates). Live (Groq tool calling, 2026-10-11, small samples): 24 plans over three repeats gave 7 valid without fallback (29%), and a later compact-tool-result experiment plus four held-out scenarios is in `docs/planner-efficiency.md`; see `eval/reports/planning.md`. The final plan is always valid because a fallback is the deterministic plan, so the model-only rate is the number to read.
- `eval/scenarios.py`: 32 attacks in 6 categories and 12 legitimate changes in 3 categories, published as data.
- `eval/approver.py`: simulated student and parent. They aren't oracles and never see the scenario label.
- `eval/runner.py`: runs every scenario in a fresh world for each of the four configurations. It reports attack block rate, money lost, detection rate, canary early detections and extra blocks, legitimate completion rate, false-block rate, minutes to resolve and risk-scorer accuracy (flag rates, precision, recall, per category). `--llm groq --repeats N` is resumable (checkpoint in `data/bench_cache/`, keyed by provider, model, ruleset and extraction mode so live-agent and deterministic runs never mix), rate-limited, and reports min / mean / max across repeats. With `--extract llm` it writes `benchmark_live.md/json` (model-followed-injection counts, per-field extraction provenance, and a deterministic reference table on the same scenarios); the default run writes `benchmark.md/json`. Caveats of the live result: 3 repeats (temperature 0, 0.4, 0.4), six injection-bearing scenarios, and within a repeat identical documents reuse one cached model response across the four configurations. AI red-team variants are reported separately.
- `eval/simulator.py`: 5 personas over 90 days, Oasis against a manually paying student, under the assumptions stated in the file. Scam and legitimate-change events run through the real pipeline.
- Pre-set targets, enforced in `tests/test_pipeline.py`: zero money lost on the attack suite in the full configuration, and every legitimate change completes.

## 6. API

Generated from `oasis/api/main.py` (FastAPI; interactive docs at `/docs`). If `frontend/dist` exists it is mounted at `/`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health`, `/api/auth/config` | public: liveness; login screen config (never a passcode) |
| POST | `/api/auth/login`, `/api/auth/logout`; GET `/api/auth/me` | role + passcode -> session cookie; revoke; who am I (200 `{"role": null}` when logged out, so the UI probe is not an error) |
| POST | `/api/device/register` | student/parent registers the public half of their Ed25519 device key |
| GET | `/api/corridor/rules` | any role: every corridor rule with value, source, retrieved date, confidence and status (confirmed-primary / researched-secondary / unconfirmed) |
| GET | `/api/approvers` | registered approver public keys (any role) |
| POST | `/api/plan/{plan_id}/consent` | parent only: signed consent to a parent-remitted conversion step |
| GET | `/api/state` | student/judge: Passport, routes, forecast triggers, why-cards, pending items (with signable drafts), security feed; parent: only their pending items and proofs |
| POST | `/api/reset` | clean sandbox; wipes SQLite state |
| POST | `/api/intake` | run the six-step pipeline on pasted document text |
| POST | `/api/intake/image` | same, for an invoice photo or screenshot (Groq vision; unreadable becomes a hold) |
| POST | `/api/approve` | student or parent (the SESSION role) approves with a `signature` over the pending draft hash, or declines; no signature or a bad one is 403 |
| POST | `/api/pay-again` | student only: turn a suspected-duplicate hold (R17) into a fresh, signable draft that carries the duplicate warning; pays nothing by itself |
| POST | `/api/recovery/approve` | the 'ask' step after a freeze: approve the drafted recovery |
| GET | `/api/parent/pending` | parent's view with explanation and facts (`?lang=en|hi|ta`) |
| POST | `/api/chat` | plan summary, or invoice intake when the message looks like an invoice |
| GET | `/api/plan/scenarios` | the eight planning scenarios (MOCK) |
| POST | `/api/plan` | the agent proposes a plan (`goal`; `scenario` for a throwaway MOCK world; `live` to use the tool-calling model when configured) |
| GET | `/api/plans` | plans with tool-call trace, validator feedback, why-this-plan |
| GET | `/api/plan/{plan_id}` | one plan with live step status |
| POST | `/api/plan/{plan_id}/accept` | student accepts (re-validated) |
| POST | `/api/plan/{plan_id}/execute` | run the steps due today through the normal pipeline (a parent-remitted conversion waits for the parent's signed consent) |
| POST | `/api/rate-target` | student sets a rate target |
| POST | `/api/rate-target/approve` | student approves a conversion above the auto limit |
| POST | `/api/autonomy/tick` | the agent's Tier-1 work (rate targets, recurring bills) |
| POST | `/api/spending/simulate` | import mock wallet spending |
| POST | `/api/spending/add` | add and categorise a transaction |
| POST | `/api/redteam` | judge only: red-team console (a separate sandbox world per judge session, never persisted, at most 20 kept; 20/min (10 in judge mode), 4,000 bytes, 429/413) |
| GET | `/api/redteam/log` | red-team attempts and outcomes |
| GET | `/api/proof/{intent_id}` | proof pack |
| GET | `/api/proof/{intent_id}/verify` | independent checks of that pack, pinned to this server's key fingerprint and chain |
| POST | `/api/reliability/record` | student: options `include_name` (default false) and `share_amounts` (default false); signs a payment-reliability record of the payments that completed the full pipeline with a verified proof pack (section 15) |
| GET | `/api/reliability/mine` | student: the last record created and how many payments are eligible now |
| POST | `/api/reliability/verify` | public, like proof verification: checks a pasted record against this server's pinned fingerprint and its proof packs; bounded input, never a 500 |
| POST | `/api/proof/verify` | verify a pasted proof pack against this server's pinned fingerprint (a pack signed by other keys fails `key_pinned`) |
| GET | `/api/trust/fingerprint` | the trust-key fingerprint to pin, the public keys, and whether they are persistent or demo keys |
| GET | `/api/audit` | audit chain |
| GET | `/api/audit/verify` | recompute the chain; first broken link if any |
| GET | `/api/benchmark` | benchmark and simulation reports |
| POST | `/api/demo/start` | start a scripted run (`{"run": "legit" or "attack", "mode": "offline" or "live"}`; live replays recorded model responses from `eval/fixtures/demo_cache/`, no network, with a per-step mode/model label) |
| POST | `/api/demo/next` | play the next step |
| GET | `/api/demo/state` | current demo state |
| POST | `/api/demo/run` | play a whole run in one call |
| POST | `/api/demo/reset` | reset the demo |
| GET | `/api/explain/savings` | conversions and total saved versus a typical bank route |


## 7. Repository layout

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

## 8. Agentic planning (spec step 2) and autonomous recovery (step 5)

The agent builds a payment plan by calling read-only tools (`read_passport`, `list_obligations`, `get_rates`, `get_routes`, `check_corridor`, `forecast_runway`) and the proposal-only `propose_plan`. A deterministic validator (`oasis/planning/validator.py`) checks every proposal (each obligation paid in its exact amount, to its own payee, by its due date; CNY arrives before it is spent; the student's INR never negative; SAFE quota per calendar year, so a large tuition is split across two conversions; LRS; INR kept for rate targets; TCS/LRS warnings surfaced) and returns concrete errors so the planner revises (at most 4 proposals). The model can only propose; accepting a plan still sends every payment through verification, signed intents, policy and the executor. Offline a deterministic planner speaks the same protocol; with a Groq key `AgenticPlanner` uses native tool calling and falls back to the deterministic plan (recorded) if it cannot produce a valid one. UI: Passport tab, "Agentic plan" (also shown in demo Run 1). API: `POST /api/plan`, `GET /api/plans`, `POST /api/plan/{id}/accept|execute`. After a freeze the agent drafts the message to the legitimate recipient using only the registry's verified channel; the draft is rejected if it contains any account number or contact from the suspicious request. Results: `eval/reports/planning.md`, summarised in [results.md](results.md).

## 9. What the AI does and never does

What the AI does: reads documents and screenshots (including Chinese text), extracts payment fields, scores risk (a heuristic scorer, plus an optional LLM scorer in live mode that can only escalate), builds and revises a payment plan by calling read-only tools, explains decisions in plain language (and in Tamil/Hindi for a parent), compares routes, watches student-set rate targets, and drafts a recovery message to the legitimate recipient's registry-verified channel.

What the AI never does: hold the payment credential, approve a payment, change a recipient's verification status, edit the audit log, sign an intent, choose a payee account (only the registry-confirmed account is paid), predict exchange rates, or contact anyone on its own. Extraction is untrusted, the risk score can only escalate a decision, a plan is only a proposal that still passes verification, policy, signing and the executor, and recovery drafts are rejected if they contain any account or contact from the suspicious request. Safety never depends on the LLM. Much of the work in the product (route comparison, forecasting, validation, verification, signing, enforcement, execution, audit) is deterministic code; unaided model planning is currently weak (see [results.md](results.md) section 4).

## 10. Scripted demo (works offline, repeats exactly)

Open the **Demo** tab (or call `POST /api/demo/start {"run": "legit"|"attack"}`, then `POST /api/demo/next` per step, or `POST /api/demo/run` for the whole run). The demo uses a fixed seed, fixed mock data, seeded **demo-only** signing keys and a simulated clock, so each run produces the same statuses, amounts and the same audit-chain head hash every time (`tests/test_features.py` and `tests/test_review_fixes.py` check this). It never uses the network. A toggle in the Demo tab (`"mode": "offline"|"live"` in the API) chooses who reads, scores and plans:

- **Offline** (default): the deterministic parser, scorer and planner, no AI model. Each step is labelled "offline parser".
- **Live-replay**: qwen/qwen3.8-27b reads the documents (live-agent extraction), adds an escalate-only AI risk score and plans with native tool calling. Its answers were recorded once into the committed fixture `eval/fixtures/demo_cache/` (model name, response text and date only) and are replayed from it, so the demo repeats exactly with no network. Each step shows its mode and model, for example "Qwen qwen3.8-27b - replayed from recorded response 2026-10-10". If a response is missing from the fixture, that call falls back to the offline parser, heuristic scorer or deterministic planner and the step says so. **Status of the fixture: not recorded yet** (the free-tier daily token allowance was spent before the recording could run), so live-replay currently shows the labelled offline fallback on every step. Record it with `PYTHONPATH=. python -m eval.record_demo_fixture` (about 25k tokens; it refuses when fewer than 40k of the daily 200k would remain).

- Run 1 (legitimate): Passport and forecast, agent plan with validator revision, tuition paid with a signed intent, parent co-approves a top-up (shown in Tamil/Hindi/English), landlord's genuine account change completes through the verification ramp, Tier-1 autonomy (rate target + recurring bill), proof packs and savings receipt.
- Run 2 (attack): the forged invoice is caught at step 3 (Verify: the registry contradicts the account) and stopped with a why-card; payment instructions rewritten at execution (the second attack) are stopped at step 5 by the executor's intent check; hidden page injection reaches a canary, freeze and recovery plan, the student approves the recovery and the genuine payment completes.

**Recording the demo:** set `OASIS_KEY_PASSPHRASE` before recording (for example `export OASIS_KEY_PASSPHRASE=...` before starting uvicorn) so the key files under `data/keys/` are passphrase-wrapped and plaintext keys are never shown on screen; use custom `OASIS_PASS_*` passcodes too, and start from a clean sandbox (`POST /api/reset`).

`POST /api/reset` (or `/api/demo/reset`, or the "Reset sandbox" button) returns to a clean sandbox and wipes the SQLite state.

## 11. Login, roles and signed approvals (detail)

Every API endpoint except `/api/health`, `/api/trust/fingerprint`, proof verification and login needs a session. Set `OASIS_PASS_STUDENT` / `OASIS_PASS_PARENT` / `OASIS_PASS_JUDGE` in `.env` for anything real (`OASIS_REQUIRE_CUSTOM_PASSCODES=1` refuses the defaults). `OASIS_JUDGE_MODE=1` (set by the judge start scripts) refuses the default passcodes unless `OASIS_ALLOW_DEMO_PASSCODES=1`, switches off `/docs`, and tightens limits (10 red-team attempts per minute, 5 failed logins per minute, 30-minute sessions). Each judge login gets its own red-team sandbox world (at most 20 kept, least recently used evicted). Wrong role gives 403, no session 401. The scripted demo is a student action because it replaces the persisted sandbox.

**Signed approvals.** On first login a student or parent gets an Ed25519 device key made in the browser (private half never leaves it, wrapped with the passcode). Approving a payment signs its exact draft (payee, account, amount, currency, purpose, route, expiry, nonce); the policy engine and executor accept a role's approval only if that signature verifies against the role's registered public key, and the proof pack shows "signed by parent device key ab12...". To try the two-person flow, open two browsers: student (Chat tab, "Simulate a family top-up request", approve) then parent (Parent tab, approve).

**Security features:** role-based access, signed approvals, encryption at rest, short-lived single-use executor tokens, a rate-limited and size-limited judge console whose every attempt is logged to `data/redteam_attempts.jsonl` (git-ignored).

## 12. Verifying a proof pack

A proof pack embeds the public keys that signed it, so a pack alone proves nothing: anyone could change the amount, sign with fresh keys and embed those. `verify_proof_pack(pack, trusted_fingerprints=..., chain=...)` therefore only reports `ok` when the fingerprint of the embedded keys (sha256 over the canonical public keys) is one you pinned. The API pins its own: `GET /api/trust/fingerprint` (shown at the top of the Proof tab), and `/api/proof/.../verify` and `POST /api/proof/verify` check against it. Approvals inside the pack are Ed25519 signatures over the exact payment and must come from pinned approver device keys (`approvals_signed`, `approver_keys_pinned`). With a chain available the verifier also checks that the anchor block exists with the intent hash as digest and the chain is intact; standalone verification reports the anchor as "not checked" (and `ok` stays false without a pinned fingerprint).

- Fingerprint of the scripted demo's public keys: `396bbb6e7a75c14fa88bf26bdbee0218a5aefdb48ca3ef9a0f9ff2de3dffdbdf` (anyone can forge with these keys, so never pin them outside the demo).
- A real server's fingerprint is created on first start and printed by the endpoint; pin it out of band.

## 13. What is real and what is simulated (summary)

Real: the six-step pipeline, policy engine, hybrid signed intents and intent-enforcing executor, verification ramp, canaries, corridor rules engine, hash-chained audit log, proof packs and verifier, plan validator, the benchmark harness and the Groq adapter. Simulated (labelled MOCK): route spreads and fees (the INR→CNY mid-market rate is a mock snapshot of the real level by default, and the real ECB reference rate with `OASIS_RATES=live`, shown with a live / STALE / MOCK badge; Oasis never predicts rates; see [live-rates.md](live-rates.md)), routes, payment rails and balances, the payee registry (WeIdentity-style demo credentials), wallet spending, humans in the benchmark, the clock, and anchoring by default (a local hash-linked simulation; FISCO BCOS is a 4-node local test chain: real v3.17.1 Air, 4 nodes on one host (WSL2), the `OasisAnchor` contract anchors only sha256 intent digests, and real transaction hashes are in [fisco-bcos.md](fisco-bcos.md). It is opt-in (`OASIS_ANCHOR=fisco`); the default, the tests, the benchmark and the scripted demo use the labelled local simulation). Post-quantum TLS: PQ-TLS is tested: Caddy 2.11.7 (go1.26.8) terminating TLS 1.3 with only `x25519mlkem768`, an OpenSSL 3.5.9 client negotiated X25519MLKEM768 and a classical-only client was refused (`eval/reports/pqtls.md`). Caveats: the certificate is classical (ECDSA from Caddy's internal CA), the test is local on one machine, and browsers were not tested. Full table: [real-vs-simulated.md](real-vs-simulated.md).

## 14. Deployment

- **Single process (demo/evaluation):** `python -m uvicorn oasis.api.main:app --host 0.0.0.0 --port 8000` serves API and UI. State is SQLite at `data/oasis.db` (`OASIS_DB` to move it, `:memory:` for none).
- **No Node needed to run:** `frontend/dist` is committed (about 190 KB) and served by the API; rebuild it with `npm run build` after UI changes.
- **Not production-ready, by design (see Known limitations):** the build serves plain HTTP by default. Payload columns in the SQLite file are AES-256-GCM encrypted, but table names, row ids and counts are in clear, and the data key and trust signing key under `data/keys/` are plaintext files unless `OASIS_KEY_PASSPHRASE` is set (then scrypt+AES-GCM wrapped). The API requires a role login (student, parent, judge) and payment approvals are signed by browser-held device keys, but the passcodes are shared demo-grade secrets (public defaults unless `OASIS_PASS_*` is set), with no per-person accounts or MFA. A real deployment still needs TLS (hybrid X25519MLKEM768 at a reverse proxy; PQ-TLS is tested as described in section 13; recipe in [pq-tls.md](pq-tls.md)), a key vault or HSM, per-person accounts with MFA, and a full independent audit. See [security-self-assessment.md](security-self-assessment.md).

## 15. Payment reliability record (credit building, honestly)

Code: `oasis/proof/reliability.py`; API in section 6; UI: Passport tab, card "Payment reliability record". Tests: `tests/test_reliability.py`.

**What it is.** A signed list of the payments that completed through the full Oasis pipeline with a verified proof pack: obligation type, payee type, paid date, due date, an `on_time` flag (paid date <= due date, both from the SIMULATED clock), the proof pack id and intent hash, the anchor reference if any, and either an amount band (default) or the exact amount (student opt-in). The student appears as a pseudonymous id (`stu_` plus a hash of the student id and the key fingerprint); the name is included only if the student ticks "Include my name". The record carries its caveats ("payment-reliability record from a SANDBOX; not a credit score; not accepted by any credit bureau"), the trust public keys and their fingerprint, a `record_hash` and a hybrid signature (Ed25519 + ML-DSA-65) over the canonical body. Integral floats are normalised to integers before hashing, so a record re-saved by a browser or another JSON tool still verifies.

**Who is listed.** Only history entries whose proof pack exists, verifies against this server's keys, and matches the obligation, payee, currency and amount. Unpaid, held, frozen, rejected and duplicate (R17) payments never produce such an entry. A tampered or missing proof pack removes the payment from the next record.

**Verifying.** `verify_reliability_record(record, trusted_fingerprints, proof_lookup=None)` never raises and returns per-check results: `signature`, `fingerprint_matches`, `key_pinned` (None means no fingerprint was supplied, and then `ok` is False), `record_hash`, `summary_consistent`, `on_time_consistent`, `unique_proofs` and `proofs_checked`. With a proof lookup each listed proof must exist, verify, and match its entry (intent hash, amount or band, paid date from the audit entry, anchor reference). Without one, `proofs_checked` is None: the entries were not cross-checked. A record re-signed with fresh keys fails the pin; an entry edited and re-signed by the real key still fails the proof cross-check.

**Limits.** It is not a credit score and no bureau, bank or regulator accepts it (README Known limitation 19). The due date is not inside the proof pack. The record is signed by one sandbox server and is only as trustworthy as the fingerprint a checker pinned out of band. Privacy design (opt-in name and amounts) is in [compliance-mapping.md](compliance-mapping.md), row 10.

## 16. Currencies: INR and CNY only

The Passport tab card "Balances by currency" shows holdings in INR and CNY, the total in each currency at the current mid rate (with the live or MOCK rate badge), the exposure split in percent, and the existing conversion-timing hints and rate targets. It is computed by `oasis/passport/currency.py::currency_view` and returned in `GET /api/state` as `currency_view` (unit-tested in `tests/test_reliability.py`). The valuation uses the mid rate, so a real conversion would return less after route spread and fees.

Only the INR to CNY corridor is supported (README Known limitation 20). There is no wallet in any other currency. Supporting another corridor would need: a rules file next to `oasis/trust/rules/inr_cny.yaml` (per-currency limits, tax and quota rules with sources), the corridor-rules loader pointed at it, and route spreads and fees for that pair in the mock layer (`oasis/mock/rates.py` routes and `oasis/market/`), plus a payee registry for that country. None of this exists today.
