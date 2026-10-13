# Oasis

**A student finance assistant for cross-border study: it plans the semester's payments, finds the cheaper route, warns before money runs short, and will not pay the wrong person.**
Built for the 2026 Shenzhen FinTechathon, International Track, **Topic C: Cross-border & Student Finance Assistant**. Hero corridor: an Indian student arriving in Shenzhen (INR to CNY).
Oasis keeps a Student Financial Passport and proposes a payment plan with an AI model; deterministic code checks, signs, enforces and records every payment.

> All money, fees, payment rails, registry identities and balances are **simulated sandbox data**, labelled MOCK in the UI. Exchange rates are **real**: the hosted Docker image fetches ECB reference rates server-side (`OASIS_RATES=live`, cached, with a labelled MOCK fallback if the server is offline); local runs and tests default to a mock snapshot so results repeat. See [docs/real-vs-simulated.md](docs/real-vs-simulated.md).

## The pain point we close

**A forged invoice or a "my bank account has changed" message must never be able to redirect a student's tuition or rent.** Governments and universities warn students about exactly this (cited below). In Oasis the account that gets paid always comes from an independent payee registry, never from the document; a changed account triggers re-verification; and every payment is bound to a signed intent the executor enforces exactly. On our benchmark that is 100% of 32 attacks blocked and CNY 0 lost (a forged tuition invoice alone: CNY 30,000 saved), with every legitimate payment completed. Around that core, Oasis covers the rest of Topic C: cheaper remittance routes, deadline-aware tuition and rent plans, multi-currency balances at live rates, and a portable payment reputation (the Trust Pass) built from those same verified payments.

## A student story: Arjun

Arjun lands in Shenzhen with INR 5 lakh. He owes tuition, rent, a deposit and a family-funded top-up, about CNY 42,000 in total, each with a deadline. In the scripted demo (offline, repeats exactly) Oasis does this:

- **Sees the shortfall on day one.** The Passport and forecast show he needs about INR 604,727 and is INR 104,727 short, and warn about low runway, the SAFE annual quota and Indian TCS when a parent sends money.
- **Compares routes and saves fees.** The agent's plan (valid after 2 validator revisions) saves **CNY 1,653 vs a typical bank route**. Across the 8 planning scenarios conversion fees were CNY 4,990 vs 29,378 (83% lower); in the 90-day simulation of 5 personas Oasis saves CNY 1,542 to 2,963 each, Arjun CNY 2,731. All mock fees; see [docs/results.md](docs/results.md).
- **Meets deadlines.** All 20 deadlines across the 8 planning scenarios were met by the deterministic planner, with CNY arriving before it is spent.
- **Pays tuition with a signed intent** to the registry-verified university account, and issues a proof pack he can show anyone.
- **Languages.** The interface and the server's plain-language explanations come in English (default) and Simplified Chinese (picker on the login screen and in the header; a student's choice is saved in the Passport); machine-drafted Chinese, see `docs/i18n-glossary.md`.
- **Gets parent co-approval in Tamil, Hindi, Chinese or English.** A top-up needs the parent's signed approval; the parent sees it in their own language (templated text, not native-reviewed).
- **Handles the landlord's genuine account change** (paid in 45 simulated minutes, nothing wrongly blocked) while a forged invoice is stopped with a plain-language why-card.
- **Builds a payment reputation from day one: the Oasis Trust Pass (credit building, not a credit score).** Most students arrive with no credit file at all, and none travels across the border. From the payments that passed the full checks, Arjun issues a signed Trust Pass he holds himself: he picks claims ("3 of 3 paid on time", "all to registry-verified payees"), or only thresholds ("at least 90% on time") that hide the exact numbers, and chooses which payments, if any, to reveal (salted commitments, selective disclosure). He can also prove **any** threshold in zero knowledge ("at least 94% on time", "at least 5 payments") without revealing the counts and without Oasis pre-signing that number: the signed pass holds commitments to the counts and the proof is bound to this credential and audience; a false claim cannot be proved. He names the verifier ("Landlord, Room 1203", sealed into the signature) and shows a QR code; the landlord's phone opens a login-free page that re-verifies every signature. The pass suggests what it can support asking for (a lower deposit, no guarantor). A clean streak also proposes a higher parent co-approval limit that only the parent can accept. Not a bureau report: it cannot be padded by "paying rent" to a friend, because every payment went to a registry-verified payee. The simpler signed **payment-reliability record** is still there too. The pass can also be exported as a **W3C Verifiable Credential** (`did:key` issuer, Ed25519 proof; partly spec-conformant, see [docs/w3c-vc.md](docs/w3c-vc.md)).
- **Sends the invoice the way it really arrives.** Besides pasting text or a photo, Arjun uploads a real email (.eml) or forwards it to a Telegram bot or a watched mailbox (optional; see [docs/real-inputs.md](docs/real-inputs.md)). Oasis reads the message's own headers: a forged test email (sender authentication failed, Reply-To on another domain, free-mail sender, hidden instruction text) scores risk 0.98 and is rejected at the verify step, while the genuine one scores 0 and waits for his signature. The channel adds evidence, never authority.
- **Screens payees against a public sanctions list.** Payee names are fuzzy-matched against a snapshot of the US OFAC list (17,515 entries); a close match is evidence that sends the payment to review, never an automatic block, and a clean result is not a compliance clearance.
- **Manages money in six currencies at live rates.** INR, CNY, USD, EUR, GBP and AUD balances, each valued in yuan and rupees at real ECB mid rates, with exposure per currency, an in-app converter (wallet fee and saving versus a typical bank shown up front; mock pricing) and a check that the yuan on hand covers everything due in the next 60 days.
- **Acts on his behalf within small limits:** a rate-target conversion and a recurring bill (Tier-1 autonomy), then shows a **savings receipt** (CNY 1,313.66 in the demo) and the Student Financial Passport.

Try it in the Demo tab (Run 1 is this story, Run 2 is the attack story).

## Why this matters

Cited external facts (sources, dates and gaps: [docs/problem-evidence.md](docs/problem-evidence.md); read 2026-10-11, no user research with real students has been done):

- Sending money costs about 6.5% of the amount on average worldwide and banks are the dearest provider type at about 14.6% ([World Bank Remittance Prices Worldwide, Q1 2025](https://remittanceprices.worldbank.org/sites/default/files/rpw_main_report_and_annex_q125_1_0.pdf), read via a summary); we found no cited India-to-China tuition figure.
- Paying in China by foreign card in WeChat Pay carries a 3% fee on each payment of CNY 200 or more ([Beijing government](https://english.beijing.gov.cn/travellinginbeijing/essentials/inboundtourismfacilitationmeasures/202603/t20260326_4566766.html)).
- Shanghai's government warns international students about texts from a "landlord with a new number" asking for rent to a different card ([Shanghai government](https://english.shanghai.gov.cn/en-Editor'sPick-StudyinShanghai/20240828/f7b950613be9462e80a8bd94ca2c38de.html)); a Belgian university warned that fraudsters alter the account number on genuine tuition invoices ([VRT News](https://www.vrt.be/vrtnws/en/2026/10/01/ku-leuven-warns-of-invoice-fraud-with-tuition-fee-payments/), date unresolved).
- The Ministry of External Affairs told the Rajya Sabha in 2023 that about 10,000 Indian students were in higher education in China, adding that students do not register with missions ([Careers360 report](https://news.careers360.com/no-specific-data-indian-students-studying-abroad-china-mbbs-russia-fmge-covid-in-spite-of-constant-efforts-ministry)).

## What the AI does vs what code does

| The AI model (untrusted; proposes and explains) | Deterministic code (decides, enforces, proves) |
|---|---|
| Reads documents and screenshots (incl. Chinese text) and extracts payment fields | Validates every plan: exact amounts, payees, deadlines, quotas, runway |
| Proposes and revises a payment plan by calling read-only tools | Verifies the recipient against an independent registry; applies policy rules R01-R17 |
| Explains decisions in plain language, Tamil and Hindi | Signs intents (Ed25519 + ML-DSA-65), enforces them exactly at execution, keeps the audit chain and proof packs |

**Also in the code, not the AI:** a small trained fraud-risk model (logistic regression, pure Python, optional via `OASIS_ML_RISK=1`, escalate-only, explainable weights). Measured once on the hidden set it ranks documents slightly better than the hand-set rules (AUC 0.80 against 0.75) but flags no extra attack (13 of 28 against 14 of 28), so it is reported as modest, not as a detection gain ([docs/results.md](docs/results.md)).

**Plain statement:** most of the work is deterministic code, not the AI. Unaided model planning is currently weak: live model-only plans were valid in **7 of 24** runs (29%). The final plan is always valid only because a fallback to the deterministic plan takes over. Calculator tools (planner format v3) were evaluated live on 2026-10-12 but the comparison is incomplete (quota ran out), so v2 stays the default. The AI never holds credentials, approves a payment, changes a verification status or edits the audit log.

## Results at a glance

All sandbox data. Full tables and labels: [docs/results.md](docs/results.md).

| Result | Number | Caveat |
|---|---|---|
| Visible benchmark (32 attacks, offline) | 100% blocked, CNY 0 lost (unprotected baseline: 6.2%, CNY 479,000 lost) | Our own attacks; simulated humans, so partly by construction |
| Hidden blind set (28 attacks, offline) | 100% blocked (strict pass criteria; baseline 39.3%) | Written by an independent agent, but partly burned: its failures were fixed afterwards |
| Live model vs injections | Model followed 0 of 18 embedded injections | Tiny sample of one model; not a robustness claim |
| Route savings (simulation) | CNY 1,542 to 2,963 saved per student over 90 days | A model with stated assumptions and mock fees |
| Live planner, model-only | 7 of 24 plans valid (29%) | Final plan valid only via the deterministic fallback |
| Planner v3 vs v2 (live, incomplete) | gpt-oss-120b v3 14 of 24 valid (58%); qwen3.8-27b 4 of 24 (17%) for both | v2 gpt-oss cell has 2 of 24 plans; no verdict, v2 stays default |
| Trained risk model vs rules (hidden set) | AUC 0.804 vs 0.747; attacks flagged 13/28 vs 14/28; legit flagged 0/12 both | Synthetic training data from the same team; hidden set small and partly burned; off by default |
| Tests | 729 pass, 2 skipped (live FISCO, live PQ-TLS) | No network; the skipped two need local services |

## Top limitations

Full list of 24 below.

- **Mock world:** fees, rails, registry and balances are simulated; nothing touches a real bank.
- **Weak unaided AI planning:** 7 of 24 live plans valid; the fallback makes the final plan valid.
- **Benchmarks are partly by construction:** same team wrote attacks and defences; humans are simulated.
- **Demo-grade security setup:** shared passcodes, plaintext keys unless a passphrase is set; passkeys (optional second factor), the zero-knowledge proofs and the email checks are not independently audited.
- **Real channels untested live:** the Telegram bot and mailbox watcher were tested against fake servers; Telegram is blocked in mainland China.
- **Translations are machine-drafted:** Chinese, Tamil and Hindi wording is unreviewed by native speakers; English is the official text.
- **Regulatory figures are researched, not confirmed** by a bank or counsel; not legal advice.

## Quick start

Requires Python 3.10+ and, only to rebuild the UI, Node 18+. No API key is needed (default `OASIS_LLM=offline`).

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows; on macOS/Linux use .venv/bin/python
PYTHONPATH=. .venv/Scripts/python -m uvicorn oasis.api.main:app --port 8000
# open http://localhost:8000 and log in (demo passcodes below); API docs at /docs
# optional UI rebuild: cd frontend && npm ci && npm run build   (a built copy is committed)
# tests: OASIS_DB=:memory: OASIS_LLM=offline PYTHONPATH=. .venv/Scripts/python -m pytest -q     # 738 tests, no network
```

**For a judge:** `scripts\start_judge.ps1` (Windows) or `bash scripts/start_judge.sh` starts everything offline with a fresh sandbox and prints the URL and logins; see [JUDGE_GUIDE.md](JUDGE_GUIDE.md). Benchmark commands, LLM settings and env vars: [docs/configuration.md](docs/configuration.md).

**Hosting (Docker):** `docker compose up -d --build` runs a single-worker container that refuses the public demo passcodes and fetches live ECB exchange rates server-side (judges' browsers never call the rate API; if the server cannot reach it the rate badge says MOCK and everything still works); see [docs/deployment-docker.md](docs/deployment-docker.md) (statically checked and run from a clean venv, not yet built in Docker).

## Login and roles

Demo passcodes (public, from `.env.example`; set `OASIS_PASS_*` for anything real):

| Role | Passcode | May do |
|---|---|---|
| student | `student-demo` | intake, chat, plans, rate targets, signed approvals, the scripted demo, reset |
| parent | `parent-demo` | signed approval of top-ups, sees only their own items |
| judge | `judge-demo` | read-only views and the rate-limited red-team console |

Approvals are signed by browser-held Ed25519 device keys. Details: [docs/technical-documentation.md](docs/technical-documentation.md) section 11.

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

Safety (the part that keeps wrong payments from happening): the registry-confirmed account is the only one paid, each approved payment is bound to a signed intent the executor enforces exactly, canary tripwires flag tampering, and a proof pack anyone can verify ([docs/technical-documentation.md](docs/technical-documentation.md) sections 4 and 12).

## Optional extras (not required for Topic C)

- **FISCO BCOS anchoring:** a 4-node local test chain, opt-in (`OASIS_ANCHOR=fisco`); no on-chain bonus claim ([docs/fisco-bcos.md](docs/fisco-bcos.md)).
- **Post-quantum TLS:** tested with an OpenSSL client only, not browsers ([docs/pq-tls.md](docs/pq-tls.md)).

## Documentation

| Document | Contents |
|---|---|
| [docs/results.md](docs/results.md) | all benchmark, planning, live and simulation tables with precise labels |
| [docs/configuration.md](docs/configuration.md) | LLM configuration, environment variables, persistence, benchmark commands |
| [docs/technical-documentation.md](docs/technical-documentation.md) | architecture, algorithms, security design, API, repository layout, agentic planning, demo, proof-pack verification, deployment |
| [docs/security-self-assessment.md](docs/security-self-assessment.md) | permission tiers, threat model, known risks, out of scope |
| [docs/security-evidence-matrix.md](docs/security-evidence-matrix.md) | each security claim mapped to code, exact test, command, outcome and limits (no audit or certification) |
| [docs/compliance-mapping.md](docs/compliance-mapping.md) | design alignment with LRS/TCS, SAFE, PIPL, DPDP, AML-style monitoring; explicitly NOT compliance |
| [docs/flightpath.md](docs/flightpath.md) | FlightPath: pre-transfer checks, recipient-amount route comparison, simulated transfer lifecycle, delay/short-credit detection, no-blind-resend recovery; simulation benchmark and its limits (core only, no UI tab yet) |
| [docs/real-inputs.md](docs/real-inputs.md) | real invoice intake (email file, Telegram bot, mailbox watcher): setup, safety rules, where each works (Telegram is blocked in mainland China), what was and was not tested live |
| [docs/problem-evidence.md](docs/problem-evidence.md) | cited evidence for the student problem (costs, scams, student numbers), what was not found, and what is only simulated; no user research yet |
| [docs/regulatory-sources.md](docs/regulatory-sources.md) | where each corridor figure came from (retrieved 2026-10-11), what could not be read |
| [JUDGE_GUIDE.md](JUDGE_GUIDE.md) | 5- and 15-minute paths for a judge to try to break Oasis, offline, one command |
| [docs/real-vs-simulated.md](docs/real-vs-simulated.md) | what is working code and what is MOCK |
| [docs/execution-evidence.md](docs/execution-evidence.md) | sandbox logs and reports, how to regenerate them |
| [docs/planner-efficiency.md](docs/planner-efficiency.md) | planner format experiments (v1, v2, v3) |
| [docs/deployment-docker.md](docs/deployment-docker.md) | Docker image, compose (+ optional Caddy TLS), hosting options, hosted-security checklist, backup and reset |
| [docs/pq-tls.md](docs/pq-tls.md) / [docs/fisco-bcos.md](docs/fisco-bcos.md) | post-quantum TLS recipe; FISCO BCOS local-chain anchoring |
| [PROGRESS.md](PROGRESS.md) | build ledger |

## Known limitations

1. **Authentication is demo-grade.** Roles use shared passcodes with no per-person accounts, and approver device keys are trust-on-first-use. An optional passkey (WebAuthn) second factor exists (`OASIS_REQUIRE_PASSKEY=1`, off by default; a role can enrol its first passkey with the passcode alone); it was tested with a software authenticator and a virtual one in Chrome, not a hardware key, and is not independently audited ([security self-assessment][sec]).
2. **Key files are plaintext unless `OASIS_KEY_PASSPHRASE` is set.** Otherwise the keys under `data/keys/` rely on OS permissions only, so set the passphrase before any recorded demo ([hardening][sec-hard]).
3. **FISCO BCOS is a 4-node local test chain** (real FISCO BCOS 3.17.1, all nodes on one host), opt-in via `OASIS_ANCHOR=fisco`. It shows the integration, not decentralised trust, and Oasis does NOT claim the on-chain challenge bonus (that is Topic F; Oasis is Topic C) ([FISCO BCOS notes][fisco]).
4. **PQ-TLS was tested only with an OpenSSL client** (OpenSSL 3.5.9 negotiated X25519MLKEM768 via Caddy). It was not tested in browsers, the certificate is classical, and the app itself still serves plain HTTP ([PQ-TLS evidence][pq]).
5. **Much of the world is mock data.** Route spreads and fees, wallet conversion fees, payment rails and the payee registry are mock; exchange rates are live in the Docker image (`OASIS_RATES=live`, cached, MOCK fallback) and mock by default locally. The scripted Demo tab always uses the mock rate so it repeats exactly ([real vs simulated][rvs]).
6. **There is no API to real banks, and WeIdentity is not integrated.** The registry is made of WeIdentity-style demo credentials, and nothing is ever sent to a real bank ([real vs simulated][rvs]).
7. **Money is stored as floats rounded to whole fen.** Fine for a sandbox; production would use `Decimal`, and corridor checks use one hard-coded USD/INR of 88.0.
8. **Demo Run 2 catches the forged invoice at step 3 (Verify), not step 5.** The step 5 intent-mismatch catch is shown by the rewritten-payment-instructions attack ([technical documentation][tech]).
9. **Humans in the benchmark are simulated, and the same team wrote the attacks and the defences.** The scripted student and parent approve only requests consistent with the Passport, so 100% results are partly by construction; the blind hidden set mitigates this partly but is now partly burned, because its failures were fixed afterwards ([hidden-set report][hidden]).
10. **Live results are small samples.** Live model-only planning was valid in 7 of 24 plans (29%) and the live injection test covered 18 runs (0 followed), so neither is a robustness claim; the final plan is always valid only because the fallback is the deterministic plan ([all live numbers][results]). Planner v3 versus v2 live evaluation (2026-10-12) is INCOMPLETE, so no verdict: the daily token quota on all four keys ran out before the last cell, and only 2 of its 24 plans ran. Model-only valid / final-valid / fallback / tokens per plan: v3 qwen3.8-27b 4 of 24 (17%) / 24 of 24 / 83% (all malformed tool calls) / 3,493; v2 qwen3.8-27b 4 of 24 (17%) / 24 of 24 / 83% / 10,787; v3 gpt-oss-120b 14 of 24 (58%) / 24 of 24 / 42% / 10,349; v2 gpt-oss-120b 1 of 2 plans. Samples are small, v2 stays the default, and final-valid is high only because of the deterministic fallback (docs/planner-efficiency.md).
11. **The risk scorer is heuristic and was tuned on the benchmark itself (in-sample).** The optional LLM scorer can only escalate, and neither scorer can see poisoned tool output (0/6), which only intent binding stops.
12. **Regulatory figures were researched on 2026-10-11, several from secondary sources, and are not confirmed by a bank or counsel.** LRS and the SAFE quota were read on primary pages, TCS and the WeChat Pay fee from secondary ones; confirm each figure with an authorised dealer bank, as this is not legal advice ([regulatory sources][regsrc]).
13. **Rate limiting and tokens are per process.** The login throttle and the session and executor token stores reset on restart and do not work across several workers.
14. **Requests are serialised.** One request runs at a time to protect the single-writer sandbox state, so a slow live-model call blocks the others; time is the simulated clock, not wall time.
15. **The judge role can read the student's data.** It is read-only by design so a reviewer can inspect state, audit and plans, and it cannot call any state-changing student endpoint.
16. **Parser and duplicate-check gaps.** An amount written as `1e5` is read as `1` (visible in the draft the student signs), and duplicates of invoices older than 30 days are caught only through the paid-obligation check.
17. **Tamil, Hindi and Chinese (zh-CN) text is machine-drafted: the parent approval wording and the Chinese interface and server messages have not been reviewed by native speakers.** English is the default and the competition's official language; see `docs/i18n-glossary.md`.
18. **Demo keys are public and seeded.** While a demo world is active the server pins their fingerprint, so a pack forged with the public demo seeds would verify during the demo (`GET /api/trust/fingerprint` reports `demo_keys: true`).
19. **The payment-reliability record is a sandbox statement, not a credit product.** It is signed by this server's key over simulated payments and simulated dates, is not a credit score, and no credit bureau, bank or regulator accepts it. The due date comes from the invoice the student supplied and is not inside the proof pack, so only the server's signature vouches for it. Only payments that went through the full pipeline with a verified proof pack are listed. The same holds for the **Trust Pass**: it is a server-signed sandbox credential, not a credit score; no lender is obliged to accept it; the preset threshold claims are attested by the server, while the optional zero-knowledge threshold proofs (any threshold, counts hidden) are a from-the-textbook construction that is not independently audited and still trust the server for the committed counts; the QR code locates a copy stored on this server, so an independent verifier should also take the JSON file and check the signature against the pinned key; and the payee level shown is the registry level at issue time ([technical documentation][tech], sections 15 and 18).
20. **Remittances and payments cover one corridor, INR to CNY.** The wallet holds and converts six currencies (INR, CNY, USD, EUR, GBP, AUD), but sending money abroad, the corridor rules, routes and obligations are INR to CNY only. Another corridor needs its own rules file (`oasis/trust/rules/*.yaml`) and its own route fees in the mock layer ([technical documentation][tech], section 16).
21. **Sanctions screening is a snapshot of one public list.** It uses the US OFAC SDN list (17,515 entries, retrieved 2026-10-12) with fuzzy matching on Latin-script names; a hit is evidence for review and a clean result is not a compliance clearance, common names give false matches, the card and IFSC checks are format checks only, and the Chinese bank-prefix table is unofficial ([technical documentation][tech], section 21).
22. **The real inbound channels were not tested live.** The email upload was tested in Chrome; the Telegram bot and the IMAP watcher only against fake servers (no bot token or mailbox was available), Telegram is blocked in mainland China without a VPN, and an uploaded email can carry any Authentication-Results header ([real inputs][inputs]).
23. **The trained risk model is modest.** On the hidden set it ranks documents slightly better than the rules (AUC 0.80 against 0.75) but flags no extra attack, its synthetic training data was written by the same team as the rules, and it is off unless `OASIS_ML_RISK=1` ([results][results]).
24. **Nothing is hosted and the container is not built.** Judges run the one-command script locally; the Docker image and the hosted-security checklist were written and checked statically only, and the app has not been load-tested.

[sec]: docs/security-self-assessment.md
[sec-hard]: docs/security-self-assessment.md#hardening-added-2026-10-10
[fisco]: docs/fisco-bcos.md
[pq]: eval/reports/pqtls.md
[rvs]: docs/real-vs-simulated.md
[tech]: docs/technical-documentation.md
[hidden]: eval/reports/benchmark_hidden_prefix.md
[plan]: eval/reports/planning.md
[regsrc]: docs/regulatory-sources.md
[inputs]: docs/real-inputs.md
[results]: docs/results.md

## Licence and third-party components

Oasis is released under the [MIT licence](LICENSE). Dependencies (read from installed package metadata, 2026-10-10); none is copyleft:

| Component | Licence |
|---|---|
| FastAPI, Pydantic, PyYAML, pytest, React 18, React DOM, Vite 5, @vitejs/plugin-react, httptools, watchfiles, qrcode-generator | MIT |
| Starlette, Uvicorn, HTTPX, python-dotenv, websockets | BSD-3-Clause |
| PyNaCl, Groq SDK, python-multipart | Apache-2.0 |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| gmssl (optional SM2/SM3) | BSD |
| py_webauthn (passkeys), pypdf (optional, PDF text) | BSD-3-Clause |
| cbor2 (via py_webauthn) | MIT |
| Frontend build-time transitive packages (`node_modules`) | MIT (55), ISC (5), Apache-2.0 (1), BSD-3-Clause (1), CC-BY-4.0 (1: `caniuse-lite` browser-support data, attribution required, build-time only, not shipped in `dist`) |

Groq models (`qwen/qwen3.8-27b`, `openai/gpt-oss-120b`) are used as a hosted service under Groq's terms and are not redistributed. Licences of every transitive Python package were not exhaustively audited.
