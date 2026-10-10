# Security self-assessment

## Trust boundaries
- **Untrusted:** every document, message, screenshot, web page and tool output the agent reads, and every LLM output (extraction, risk score, explanations).
- **Trusted:** policy engine, intent builder/signer, executor, verification ramp, registry interface, audit log.
- The LLM never holds the payment credential (only `Executor` has it), never approves a payment, never changes verification status and cannot edit the audit log.

## Permission tiers (implemented in `oasis/trust/policy.py`)
Tiers: 1 = the agent may act alone within bounds, 2 = explicit human approval, 3 = never (freeze). Rules are evaluated in this fixed order (ruleset 2026.10.2, the same table is in the technical documentation). The same inputs always give the same decision, and every decision is logged with its rule ID and ruleset version.

| Rule | Decision | Condition |
|---|---|---|
| R01 | freeze (tier 3) | a canary (early-detection tripwire) fired |
| R02 | freeze (tier 3) | amount above the hard limit |
| R03 | freeze (tier 3) | the registry contradicts the recipient |
| R04 | freeze | risk score ≥ 0.85 (escalation only) |
| R04b/c | allow / freeze | verification test payment: ≤ CNY 10, only to a registry-confirmed recipient |
| R05 | hold | recipient not yet verified (the verification ramp must finish; no approval can override it) |
| R06 | hold | corridor rule hold (LRS, purpose mismatch, split payments; splits that dodge parent approval need the parent) |
| R07 | hold | amount above the recipient's ramp limit (needs explicit student approval) |
| R08 | hold | risk score ≥ 0.5 |
| R09 | (sets approvers) | family-support transfer above INR 50,000 requires student **and** parent (appears as R11 until both approve) |
| R10 | allow (tier 1) | recurring payment up to CNY 500 to a Verified_Full recipient (not family support) |
| R13/R14 | allow (tier 1) / hold | conversion into the student's own balance at a student-set rate target: within the auto limit / above it (needs the student) |
| R11/R12 | hold / allow | tier 2: required approvals missing / present |

## Executor checks (before any transfer)
The executor checks four things: the hybrid signature is valid (Ed25519 **and** ML-DSA-65 must both verify), the payload matches the intent exactly (payee, account, amount, currency, route), the intent hasn't expired and its nonce hasn't been used, and the policy decision, re-evaluated at execution time, is `allow`. Any failure freezes the payment.

## Threat model

| Attack | Primary defence | Backup | Benchmark category |
|---|---|---|---|
| Forged invoice, swapped bank details | registry verification (request details treated as forgeable) | intent mismatch | forged_invoice |
| Hidden prompt injection | LLM cannot approve; verification; policy risk hold | canary tripwire | hidden_injection |
| Lookalike payee names | registry identity match is exact; no fuzzy name resolution | risk evidence | lookalike |
| Fake university urgency | verification ignores urgency | "Why was I stopped?" card | fake_urgency |
| Poisoned tool output | intent binding (executor exact match) | canary scan of the payload | poisoned_tool |
| Payments split to dodge limits | corridor split-pattern flag routes the hold to the parent | policy hold | split_payments |
| Replay of an old approval | nonce + expiry | audit log | unit tests |

A forged request never changes the genuine recipient's record. The request is rejected and the real university or landlord stays verified, so an attacker can't cause a denial of service against legitimate payees.

## Known risks and limitations
- **Canaries are an early-detection layer, not a blocking layer, and only see attacks that touch them.** In the benchmark they block 0 attacks beyond verification + signed intents + policy; they flag 3 attacks earlier (at Understand, before verification or execution) and give a freeze signal. Intents and verification cover everything canaries miss.
- **Verification is only as good as the registry.** A compromised registry defeats step 3, and in this build the registry is a mock.
- **Simulated humans.** The benchmark's student and parent approve only requests consistent with the Passport. A real student might approve a scam, which tier-2 approval can't fully prevent.
- **Offline LLM and thin live evidence.** The default benchmark uses a deterministic "gullible" extractor that follows embedded instructions, a worst-case stand-in. The live-agent run (`--llm groq --extract llm`, qwen/qwen3.8-27b) is one repeat at temperature 0 over six injection-bearing scenarios: the model followed 0 of 6 and the baseline lost CNY 380,000 instead of 479,000. That is not a robustness claim; `--repeats 3` was not run, and the injection count is the same in all four configurations by construction (one cached response per document per repeat).
- **Risk scorer** is heuristic (offline) or LLM-based. It is measured (offline: flags 81% of attacks and 0% of legitimate changes; 69% on the first step only, up from 44%), but the features were chosen after seeing the benchmark, so those rates are in-sample, and it cannot see poisoned tool output (the invoice looks genuine). It only escalates; it never allows.
- **Persistence** stores state in an unencrypted SQLite file; the trust signing keys are a plain git-ignored file (`data/keys/trust_key.json`), generated once so the fingerprint is stable. Real deployments need encryption at rest and a key vault.
- **Proof-pack forgery (found by external review, fixed).** `verify_proof_pack` used to trust the public keys embedded in the pack, so a pack with a changed amount or account signed by fresh keys verified. It now requires the embedded keys' fingerprint to be pinned (`trusted_fingerprints`; the API pins the server's, published at `GET /api/trust/fingerprint`) and, when a chain is available, checks the anchor block and chain integrity. Residual: a verifier that does not pin a fingerprint obtains no authenticity, only consistency; the anchor is a local simulation.
- **Tier-1 autonomy** is bounded (CNY 500 recurring bills to Verified_Full recipients, CNY 5,000 rate-target conversions into the student's own balance), but a compromised host or Passport would let it act within those bounds.
- **Demo keys** are seeded and public so runs reproduce; they are used only in the scripted demo.
- **Image intake** uses the Groq agent model; if the image cannot be read the flow holds and asks for text. Verified live once on a generated invoice PNG (all fields read); other image types are untested.
- **Parent-language text** is templated and not reviewed by native speakers.
- **Legitimate changes cost time.** A landlord's account change takes about 55 simulated minutes (registry check, test payment, approval) against 0 for the unprotected baseline.
- **Post-quantum library maturity.** ML-DSA comes from `cryptography`'s FIPS 204 implementation. The hybrid rule means a flaw in one algorithm alone does not break signatures.
- **SM2/SM3 (optional, crypto-agility demo).** `SM2Signer` (GB/T 32918, SM3 digest, default ID `1234567812345678`) uses the pure-Python `gmssl` 3.2.2 package, which is not constant-time and has not been audited; it is suitable for the demo, not for production key handling. It matches the GB/T 32918.5 / GM/T 0003.5 Fp-256 test vector (checked in `tests/test_sm2.py`; the vector values were entered from memory, and the exact match of the signature is what authenticates them). The default scheme remains Ed25519 + ML-DSA-65; SM2 is used only when a `HybridSigner` is built with it (`sm2_hybrid_signer`). The SM2 round-trip, tamper and cross-key rejection are tested; interoperability with other SM2 implementations (for example GmSSL, Tongsuo) has not been tested.
- **The LLM can propose a bad plan; it cannot execute one.** The deterministic validator checks feasibility and the stated rules, not global optimality. Live evidence: of 3 plan scenarios run on Groq, 1 was valid without falling back; 2 hit the per-plan token cap and the deterministic plan was reported. The tool-calling model once emitted garbled arguments (rejected by the validator).
- **Model availability.** The primary agent model is a Groq preview model that can be retired at short notice; the fallback is automatic and the offline parser is the floor.
- **No API authentication.** The FastAPI app trusts its caller (a single-student sandbox). Real use needs authentication, per-user state and CSRF/CORS review.
- **Risk scoring is a heuristic scorer, plus an optional LLM scorer in live mode that can only escalate** (max of the two; its failure falls back to the heuristic and is recorded). It is untrusted input to the policy engine like every other model output.
- **The risk scorer's recall on poisoned tool output is 0/6** by nature (the document is genuine); only intent binding stops those.
- **Route comparison is information, not licensed financial advice**; the UI shows a disclosure. The spending forecast starts cold (budget and labelled reference costs) until enough transactions exist.
- **LLM variability** affects live results; hence the repeat and spread options and the caveats above.
- **WeIdentity is not integrated** (the SDK was last released in 2023); the registry is WeIdentity-style demo credentials, and anchoring is a local simulation, not FISCO BCOS.
- **Novelty is incremental:** two-sided payment-agent evaluation already exists; the contribution is resolving legitimate changes and the real corridor.
- **A local `.env` holds the Groq key.** It is git-ignored; never commit it and rotate the key if it leaks. `.env.example` contains no key.
- **Regulatory figures** are researched secondary-source values. The education purpose code is unconfirmed.
- **Screenshots** may contain third parties' personal data. The vision path keeps only extracted text and does not store the image.


## Honest limits

- **Some 100% results are partly by construction.** The same team wrote the attacks and the defences. The simulated student declines using the risk evidence the system itself produced. Legitimate account changes succeed because the scenarios pre-register the new account in the registry. A 100% block rate on this suite is therefore not a claim about unseen attackers, and a 100% completion rate is not a claim about real landlords and universities.
- **Approvals are not authenticated.** Roles ("student", "parent") are plain strings in the request; any API caller can approve as the parent. The two-person rule is enforced in the policy engine, not by identity. A real deployment needs authentication and per-user sessions.
- **Live planning is weak so far.** In the latest live run (qwen/qwen3.8-27b with openai/gpt-oss-120b as fallback; `eval/reports/planning.md`, 2026-10-10) all 8 scenarios ended with a valid plan, but only 4 of 8 without falling back to the deterministic planner (the other 4 hit the per-plan token cap), using 100,235 tokens and 42 model calls; proposals to the first valid plan averaged 2.75 (max 4). The deterministic planner is valid on 8 of 8 with 1.5 proposals. One run, no repeats.
- **The AI risk scorer is escalate-only and optional.** The default scorer is heuristic; the LLM scorer exists only in live mode and has not yet been run on the full live benchmark, so its contribution is unmeasured.

## Out of scope
Compromise of the host machine or signing keys; compromise of the registry itself; real banking integration; production key management and encryption at rest; denial of service; the correctness of regulatory figures beyond the stated research.

## Standard protections (deployment)
Planned for deployment, not implemented in this repository: TLS in transit (hybrid X25519MLKEM768 where the stack supports it; the demo build runs plain HTTP and does not exercise it; the dev machine's Python links OpenSSL 1.1.1t, which lacks ML-KEM; see `docs/pq-tls.md` for an untested deployment recipe), encryption at rest, secrets from a vault (the Groq key is read from the environment or an untracked `.env`), least privilege. The SQLite file is not encrypted.
