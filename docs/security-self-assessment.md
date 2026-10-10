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
| R15 | hold | the document demands a currency other than CNY (needs a corrected CNY invoice; no approval overrides it) |
| R16 | hold | out-of-band verification required: a document asks to change an approver or approval limit, to refund or reverse, to pay an authority not in the Passport, or (unstructured) to change a payee's bank details; nothing is actioned (raised by the pipeline before any payment logic) |
| R05 | hold | recipient not yet verified (the verification ramp must finish; no approval can override it) |
| R06 | hold | corridor rule hold (LRS, purpose mismatch, split payments; splits that dodge parent approval need the parent) |
| R07 | hold | amount above the recipient's ramp limit (needs explicit student approval) |
| R08 | hold | risk score ≥ 0.5 (no approval releases it: confirm out of band and re-submit) |
| R09 | (sets approvers) | family-support transfer above INR 50,000 requires student **and** parent (appears as R11 until both approve) |
| R10 | allow (tier 1) | recurring payment up to CNY 500 to a Verified_Full recipient (not family support) |
| R13/R14 | allow (tier 1) / hold | conversion into the student's own balance at a student-set rate target: within the auto limit / above it (needs the student) |
| R11/R12 | hold / allow | tier 2: required approvals missing / present |

## Executor checks (before any transfer)
The executor checks five things. New: every approval inside the intent must be an Ed25519 signature by that role's registered device key over this exact payment (see below), and only roles whose signature verified are passed to the policy engine. The original four: the hybrid signature is valid (Ed25519 **and** ML-DSA-65 must both verify), the payload matches the intent exactly (payee, account, amount, currency, route), the intent hasn't expired and its nonce hasn't been used, and the policy decision, re-evaluated at execution time, is `allow`. Any failure freezes the payment. The payment credential is a per-execution tool token (short-lived, single-use, bound to the intent and transfer), not a static string.

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
- **Persistence** is encrypted at rest (AES-256-GCM, see "Hardening added 2026-10-10"). The data key and the trust signing key are still PLAINTEXT key files under `data/keys/` protected only by OS permissions (and optionally wrapped with `OASIS_KEY_PASSPHRASE`); a process or user that can read them can decrypt the database. Real deployments need a key vault/HSM.
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
- **Authentication is demo-grade.** Roles are protected by per-role passcodes (public demo defaults unless `OASIS_PASS_*` is set; `OASIS_REQUIRE_CUSTOM_PASSCODES=1` refuses them), exchanged for signed 1-hour HttpOnly session cookies. There are no per-user accounts, no MFA, no password hashing store, and no CSRF token beyond SameSite=Strict + JSON bodies. TLS is not terminated by this app.
- **Risk scoring is a heuristic scorer, plus an optional LLM scorer in live mode that can only escalate** (max of the two; its failure falls back to the heuristic and is recorded). It is untrusted input to the policy engine like every other model output.
- **The risk scorer's recall on poisoned tool output is 0/6** by nature (the document is genuine); only intent binding stops those.
- **Route comparison is information, not licensed financial advice**; the UI shows a disclosure. The spending forecast starts cold (budget and labelled reference costs) until enough transactions exist.
- **LLM variability** affects live results; hence the repeat and spread options and the caveats above.
- **WeIdentity is not integrated** (the SDK was last released in 2023); the registry is WeIdentity-style demo credentials, and anchoring is a local simulation by default. FISCO BCOS anchoring is real but local (4 nodes on one host, `OASIS_ANCHOR=fisco`, tx hashes in `docs/fisco-bcos.md`), so it shows the integration, not decentralised trust.
- **Novelty is incremental:** two-sided payment-agent evaluation already exists; the contribution is resolving legitimate changes and the real corridor.
- **A local `.env` holds the Groq key.** It is git-ignored; never commit it and rotate the key if it leaks. `.env.example` contains no key.
- **Regulatory figures** are researched secondary-source values. The education purpose code is unconfirmed.
- **Screenshots** may contain third parties' personal data. The vision path keeps only extracted text and does not store the image.


## Honest limits

- **Some 100% results are partly by construction.** The same team wrote the attacks and the defences. The simulated student declines using the risk evidence the system itself produced. Legitimate account changes succeed because the scenarios pre-register the new account in the registry. A 100% block rate on this suite is therefore not a claim about unseen attackers, and a 100% completion rate is not a claim about real landlords and universities.
- **Approvals are signed, but the humans are still simulated in the benchmark.** In the API, an approval is an Ed25519 signature from the approver's browser-held device key. The device key is generated at first login and registered by whoever holds the role's passcode (trust on first use; a later login can rotate it). A phished passcode therefore lets an attacker register their own key. The benchmark and scripted demo use in-process simulated device keys.
- **Live planning is weak so far.** In the latest live run (qwen/qwen3.8-27b with openai/gpt-oss-120b as fallback; `eval/reports/planning.md`, 2026-10-10) all 8 scenarios ended with a valid plan, but only 4 of 8 without falling back to the deterministic planner (the other 4 hit the per-plan token cap), using 100,235 tokens and 42 model calls; proposals to the first valid plan averaged 2.75 (max 4). The deterministic planner is valid on 8 of 8 with 1.5 proposals. One run, no repeats.
- **The AI risk scorer is escalate-only and optional.** The default scorer is heuristic; the LLM scorer exists only in live mode and has not yet been run on the full live benchmark, so its contribution is unmeasured.

- **Adversarial judge review (2026-10-10), by design or too large to fix here.**
  - *Duplicate invoice after payment.* Re-submitting an already-paid invoice is not paid automatically (the recipient's ramp limit holds it at R07 for explicit student approval), but nothing says "you already paid this". A student who signs that approval pays twice. There is no payment idempotency key outside the signed intent's nonce.
  - *Device-key takeover is trust-on-first-use.* Whoever holds a role's passcode can register a new Ed25519 key for that role, which retires the old one (and invalidates drafts the old key was about to sign). Passcodes are shared per role. Real deployment needs per-user accounts plus an out-of-band step (or WebAuthn) to enrol a device.
  - *The login throttle is per client address.* Ten wrong passcodes lock that address out for a minute, including the legitimate user behind it (a cheap denial of service against the login). The limiter is in memory and resets on restart.
  - *Time is simulated.* Draft expiry (`not_after`) and the executor check use the sandbox's simulated clock, not the wall clock. A pending approval therefore does not expire by itself as real days pass, only when the simulated clock moves past it (then it is retired with HTTP 410, see below). Session tokens do use the wall clock.
  - *Floating-point money.* Amounts are Python floats. Input is limited to finite, non-negative values with at most two decimals and at most CNY 10^10, and ledger balances are rounded to whole fen after each transfer, but there is no `Decimal` ledger, so very long histories could still accumulate sub-fen error elsewhere (rates, savings).
  - *Corridor limits use one hard-coded USD/INR of 88.0* (`corridor.USD_INR`), independent of the INR/CNY rate source, so LRS and SAFE headroom is approximate if the real USD/INR moves. Units are consistent inside each check (INR for LRS/TCS, USD converted to INR for SAFE, CNY for payments).
  - *A judge can read the student's data.* The judge role is read-only for state, audit and plans by design (so a reviewer can inspect the system); it cannot call any state-changing student endpoint and the red-team console runs on its own sandbox ledger.
  - *The scripted demo's keys are public and seeded.* While a demo world is active the server pins its fingerprint, so a pack forged with the public demo seeds would verify during the demo. `GET /api/trust/fingerprint` reports `demo_keys: true` then. Do not treat verification during a demo as authenticity.
  - *Interactive API docs (`/docs`, `/openapi.json`) are public* and list every endpoint. They contain no secrets.
  - *Only one request runs at a time.* Requests are serialised to protect the single-writer sandbox state (audit chain, ledger, nonces, pending approvals); a slow live-model call blocks the others. Fine for a demo, not a scaling design.
  - *Amount notation.* `1e5` is read as `1` (the parser reads digits only), which shows in the draft the student signs; it is never read as 100,000.

## Judge review 2026-10-10: defects found and fixed

Found by attacking the running API over HTTP; each has a regression test in `tests/test_judge_attacks.py`.

| Finding | Severity | Fix |
|---|---|---|
| Two simultaneous approvals of one pending payment gave 500s (and a race window on the replay check); audit appends were not atomic | High | Requests run one at a time; `AuditLog.append` takes a lock; the loser gets 404 |
| Amounts of NaN/infinity/400 digits, or with fractions of a fen (`30000.004`), reached the pipeline; infinity poisoned the audit log and made `/api/state` return 500 until a reset | High | `unreadable_amount`: such amounts are dropped and the request is held as a low-confidence extraction; the ledger refuses non-positive or non-finite transfers and keeps balances on whole fen |
| Unpaired surrogate or NaN in any JSON field gave 500 (and a 422 echoing the input also crashed) | Medium | Strict request models (422), no echo of input in validation errors, text length caps, spending/rate-target bounds |
| Cross-origin POSTs: SameSite=Strict still sends the cookie from another page on `localhost` (any port) | Medium | Origin check on every state-changing request (same host or the dev UI only); 2 MB body cap; `Cache-Control: no-store` and `nosniff` on API responses |
| R08 risk hold offered an Approve that could never release it (each signed approval re-held with a new pending id, forever) | Medium | R08 now names `risk_review` instead of an approver, so no approval is offered; the card says to confirm out of band and re-submit |
| Approving a payment after its draft expired froze the genuine obligation and showed an attack-style card | Medium | Expired drafts are retired with HTTP 410 and an `approval_expired` audit entry; the obligation is untouched |
| Proof verification could raise (500) on malformed packs (wrong types, surrogates) | Medium | `verify_proof_pack` never raises: any unreadable pack fails with `malformed` and `ok: false` |
| A U+2028 in a red-team attempt split its log record when read with `splitlines()` (silent loss of the attempt); a flood of refused attempts was logged in full without limit | Medium | Attempts are written ASCII-only and read by `
`; refused attempts are shortened and logged at most 5 per minute; the file stops growing at 50 MB |
| Intake text of ~200 KB took 12 s to parse (quadratic field regexes) while holding every other request | Medium | 20,000-character cap on intake and chat text (the regexes are not changed) |
| Corrupt or empty key files gave raw `JSONDecodeError`/`KeyError`; a lost data key gave a bare "wrong key" | Low | `KeyFileError` / recovery hint: clear message, the file is never overwritten with a fresh key |

Checked and held: no or forged or tampered or expired or revoked session token (401); parent/judge on student endpoints and student on the judge console (403); role-string or foreign-role signatures; signature replay on another draft or after a changed amount; unregistered or rotated device key; register-for-another-role (the session role decides); forged, stripped or mixed-key proof packs; login brute force (429 after 10); CORS limited to the two dev origins; no stack traces, tokens, passcodes or key material in responses, audit entries or proofs; tampered database rows and wrong data key refused. `pip-audit` of `requirements.txt`: no known vulnerabilities (the venv's own `setuptools` 65.5.0 build tool has advisories; it is not a runtime dependency). `npm audit --omit=dev`: 0 vulnerabilities.

## Out of scope
Compromise of the host machine or signing keys; compromise of the registry itself; real banking integration; production key management (vault/HSM); denial of service; the correctness of regulatory figures beyond the stated research.

## Standard protections (deployment)
Implemented in this repository: encryption at rest, role-based access, signed approvals, short-lived tool tokens, secrets from a git-ignored key file or environment. Planned for deployment, not implemented: TLS in transit (hybrid X25519MLKEM768: PQ-TLS is now tested with Caddy 2.11.7 (go1.26.8) and an OpenSSL 3.5.9 client, which negotiated X25519MLKEM768 (`eval/reports/pqtls.md`); caveats: classical certificate, one local machine, browsers not tested; the app itself still serves plain HTTP unless the Caddy proxy in `docs/pq-tls.md` is run, and the dev machine's Python links OpenSSL 1.1.1t, which lacks ML-KEM) and a secrets vault/HSM (keys are local files; the Groq key is read from the environment or an untracked `.env`).
## Hardening added 2026-10-10

| Control | What it does | Where |
|---|---|---|
| Roles (least privilege) | `student` (intake, chat, plans, approve as student, demo, reset), `parent` (approve as parent, sign plan-conversion consent, own pending list and own proofs), `judge` (red-team console, read-only views). 401 without a session, 403 for the wrong role. Public: health, trust fingerprint, proof verification, login. The scripted demo is a student action because it replaces the persisted sandbox. | `oasis/api/auth.py`, `oasis/api/main.py` |
| Session tokens | HMAC-SHA256 signed, 1 hour, jti revocable on logout, HttpOnly + SameSite=Strict cookie (Bearer header also accepted), constant-time passcode compare, failed-login rate limit (10/min/client). | `oasis/api/auth.py` |
| Signed approvals | An approval is an Ed25519 signature over `oasis-approval-v1\|role\|draft_hash`, where the draft hash covers payee, account, amount, currency, purpose, route, not_after and nonce. The role string alone grants nothing; the policy engine only ever sees roles whose signature verified against the role's registered key; the executor re-verifies; approvals are stored in the signed intent and proof pack and `verify_proof_pack` re-checks them against pinned approver key ids. A changed amount, a different payment, a forged or missing signature, an unregistered or retired device key are all refused. | `oasis/trust/approvals.py`, `executor.py`, `proof/pack.py` |
| Where approver private keys live | In the approver's browser (Ed25519 via the MIT `@noble/curves` library; generated at first login, stored in localStorage wrapped with the passcode by PBKDF2 and AES-GCM). The server holds only public keys. Chosen over server-held keys because a stolen database or a compromised server then cannot forge an approval, and over WebCrypto Ed25519 because that is missing from older browsers. | `frontend/src/crypto.js` |
| Encryption at rest | Every payload column (Passport, audit entries, proofs, cards, ledger, pending, approver keys) is AES-256-GCM encrypted with row-bound associated data; the SQLite file reveals no payee names, accounts or amounts (tested by grepping the file). The audit hash chain is verified after decrypt on restart. An old plaintext database is migrated once; a plaintext row inside an encrypted database, a wrong key or a moved/altered row is refused. | `oasis/storage.py`, `oasis/trust/keyfile.py` |
| Short-lived tool tokens | The executor holds only an issuer secret that can mint but not pay. Each execution mints a token that expires in 30 s, works once and is bound to the intent id, accounts, amount and currency; replays, expiry and mismatches are refused. It is never logged or returned. The unprotected baseline keeps a static credential on purpose, as the thing being measured. | `oasis/mock/ledger.py`, `executor.py` |
| Red-team console | Judge only; its own sandbox world (own ledger, registry, simulated approvers) that can never touch the student's ledger; 20 attempts/min per client (429), 4,000-byte text and 400-byte tool-output limits (413); every attempt, including refused ones, appended to `data/redteam_attempts.jsonl` (git-ignored). | `oasis/api/main.py` |

### Remaining limits of this hardening
- Key files (`data/keys/data_key.json`, `trust_key.json`, `session_secret.json`) are plaintext unless `OASIS_KEY_PASSPHRASE` is set, and on Windows `chmod 0600` does not restrict access; rely on the account's folder permissions or disk encryption. With the passphrase set, it must be present in the server environment at every start, so it protects a copied key file, not a live server.
- Table names, row ids (for example `int_0001`) and row counts are not encrypted.
- Device-key registration is trust on first use, and the browser key is readable by script running in the page (XSS) while unlocked; there is no hardware-backed key (WebAuthn would be the next step).
- Passcodes are shared per role, not per person; the demo defaults are public.
- Conversions between the student's own accounts (rate targets, plan conversions) are authorised by the authenticated student session, not by a per-action signature; only parent-remitted conversions need a signed parent consent.
- The in-memory rate limiter and token store reset on restart and are per process.
