# Oasis: complete feature list

Every feature found in the code, the 102 API routes, the UI and the docs, with one line on what it is. All money, fees, rails, registry identities and balances are simulated sandbox data (MOCK). "Live mode" means `OASIS_LLM=bedrock` (Amazon Nova Pro on Bedrock); without it a deterministic offline version runs. Written 2026-10-18 from the repository as committed.

## 1. Core payment pipeline

1. **Six-step flow** (`oasis/agent/pipeline.py`): Understand, Plan, Verify, Commit, Execute and watch, Prove. Every payment goes through the same steps.
2. **Independent payee registry** (`oasis/mock/registry.py`): WeIdentity-style demo credentials, signed by an issuer, binding a payee to a receiving account. The paid account always comes from here, never from a document.
3. **Verification ramp** (`oasis/trust/verification.py`): registry check, test payment, low limit, full limit. A changed account is re-verified instead of refused.
4. **Policy engine, rules R01 to R19** (`oasis/trust/policy.py`): canary, hard limit, rejected recipient, risk freeze, unverified payee, corridor, recipient limit, risk hold, Tier-1 auto, approval required, approved, rate-target, conversion approval, currency mismatch, out-of-band verification (R16), duplicate payment (R17), foreign-currency approval and approved (R18, R19).
5. **Permission tiers and per-recipient limits**: what the agent may do alone (Tier 1) versus what needs the student, and the parent for larger amounts.
6. **Hybrid signed intents** (`oasis/trust/intents.py`, `crypto.py`): each payment is signed with Ed25519 plus ML-DSA-65 (post-quantum).
7. **Intent-enforcing executor** (`oasis/trust/executor.py`): pays only what was signed: signature, exact match, nonce, expiry and a policy re-check.
8. **Single-use tool tokens** (`oasis/mock/ledger.py`): the executor mints a short-lived token bound to one transfer; it holds no long-lived payment credential.
9. **Mock sandbox ledger and rails** (`oasis/mock/ledger.py`): the simulated bank layer, with currency checks and money-lost accounting.
10. **Canary tripwires** (`oasis/trust/canaries.py`): decoy credentials, payees and document fields that only a compromised flow would touch; touching one freezes the flow.
11. **Freeze and recovery** (`oasis/agent/recovery.py`): after a freeze the agent drafts a message to the legitimate payee via the registry's verified channel only, checked for leaked details, with a template fallback.
12. **Hash-chained audit log** (`oasis/trust/audit.py`): SHA-256 chain with a verifier; tampering is detectable.
13. **Proof packs** (`oasis/proof/pack.py`): a signed bundle of intent, approvals and audit evidence with an independent verifier and a "try tampering" check.
14. **Pinned key fingerprint** (`oasis/trust/keystore.py`): verifiers pin the server's key fingerprint, so a pack re-signed with fresh keys fails.
15. **Why-cards**: a plain-language explanation of each decision, with a "not established" line and a next step.
16. **Duplicate-payment detection** (`oasis/agent/duplicates.py`, R17): re-submitting an already paid invoice is held, not paid again.
17. **Request-type classification** (`oasis/agent/request_types.py`): documents that ask to change approvers, contacts or stored recipients go to out-of-band verification (R16), never half-understood as a payment.
18. **Corridor rules engine** (`oasis/trust/corridor.py`, `rules/inr_cny.yaml`): India outbound rules (LRS, TCS, SAFE quota), each value with source, date and status.
19. **Sanctions screening** (`oasis/screening.py`): matches payee names against OFAC, UN, UK OFSI and EU list snapshots; evidence for review, never an automatic block or clearance.
20. **Card and IFSC format checks**: basic validity checks on bank identifiers.
21. **Optional trained risk model** (`oasis/agent/ml_risk.py`): a small model that can only raise the risk score (`OASIS_ML_RISK=1`).
22. **Payment-sequence anomaly flags** (`sequence_flags` in `oasis/agent/llm.py`): a burst of payments, a third payment to one payee in 24 hours, or an amount over 3x earlier payments raises the risk score.
23. **Parent co-approval** (`oasis/agent/parent.py`): larger payments need a parent signature, with the request shown in English, Tamil, Hindi or Chinese.
24. **Browser-held device keys** (`frontend/src/crypto.js`): the student and parent keys stay in the browser, protected by a passphrase, and sign the exact draft hash.
25. **Pay-again** (`/api/pay-again`): resubmit a held or failed payment through the same checks.
26. **Recovery approval** (`/api/recovery/approve`): the student approves the safe replacement plan after a freeze.

## 2. Planning and money

27. **Student Financial Passport** (`oasis/passport/models.py`): the student's profile, balances, obligations, payees and history.
28. **Spending categorisation** (`oasis/planning/spending.py`): keyword categorisation of transactions, with simulate and add endpoints.
29. **Forecast** (`oasis/planning/forecast.py`): cold-start budget to own-pattern forecast with named triggers; it never predicts exchange rates.
30. **Shortfall and runway warnings**: tells the student before money runs short.
31. **SAFE quota and Indian TCS awareness**: warns about annual limits and tax collected at source, including when a parent sends money.
32. **Agentic planner** (`oasis/agent/planner.py`, `oasis/planning/tools.py`): a model proposes a payment plan using read-only calculator and registry tools; formats v1, v2 and v3.
33. **Plan validator and fix hints** (`oasis/planning/validator.py`, `fixes.py`, `calc.py`): deterministic checks of amounts, quotas, deadlines and funds, with numeric hints for corrections.
34. **Deterministic fallback planner**: used when the model fails or is out of budget.
35. **Plan trade-offs and questions**: sets the chosen route against alternatives and asks for missing facts instead of guessing.
36. **Plan accept, consent and execute** (`oasis/agent/plan_exec.py`): a plan is only a proposal until accepted; each payment step then runs through the normal pipeline.
37. **Plan scenarios** (`oasis/planning/scenarios.py`): eight evaluation scenarios plus held-out ones.
38. **Route comparison** (`oasis/planning/routes.py`): ranks routes by what the recipient receives, not by the fee shown.
39. **Six-currency wallet and converter** (`oasis/passport/currency.py`): INR, CNY, USD, EUR, GBP and AUD balances with quote and convert.
40. **60-day coverage check**: whether the yuan on hand covers what is due.
41. **Tier-1 autonomy** (`oasis/agent/autonomy.py`): rate-target conversions and small recurring bills to fully verified payees.
42. **Savings receipt**: what the plan saved versus a typical bank route.
43. **Five extra corridors** (`oasis/corridors/core.py`, `rules/corridors.yaml`): CNY to USD, INR to USD, EUR to USD, INR to EUR and CNY to EUR, with foreign-currency plans (`oasis/planning/fxplan.py`) and payments (`oasis/agent/fx_exec.py`).
44. **Corridor compare and check endpoints**: read-only comparison on the amount the recipient must receive, plus rule checks.
45. **Live ECB rates** (`oasis/market/live_rates.py`): real reference rates, cached an hour, with a labelled STALE or MOCK fallback.
46. **Mock wallet and QR payments** (`oasis/mock/wallet.py`): foreign-card fee simulation for Alipay and WeChat-style spending.

## 3. FlightPath, Digital Twin, netting

47. **FlightPath** (`oasis/flightpath/core.py`): follows a transfer after it is sent: pre-transfer checks, journey state machine, delay and short-credit detection, refund handling, and never a blind resend.
48. **FlightPath consequences**: links a delay to the bill's deadline and compares waiting, asking the provider, a top-up or a new route.
49. **FlightPath benchmark**: simulated comparison against a baseline (duplicates, flagged issues).
50. **Financial Digital Twin** (`oasis/twin/core.py`): a seeded Monte Carlo of the rest of the semester with per-deadline probabilities, a fan chart and mitigations.
51. **Peer netting simulation** (`oasis/netting/core.py`): matches opposite INR and CNY flows at mid-rate; simulation and benchmark only.

## 4. Credentials and proof

52. **Trust Pass** (`oasis/proof/trust_pass.py`): a student-held credential built from verified payments, with salted commitments, selective disclosure, audience binding and expiry.
53. **Zero-knowledge threshold proofs** (`oasis/proof/zk.py`): prove "at least X% on time" without revealing the counts.
54. **W3C Verifiable Credential export** (`oasis/proof/vc_export.py`): export and verify a Trust Pass as a standard credential.
55. **QR share and login-free verifier**: a landlord's phone re-verifies every signature at a public page.
56. **Earned-autonomy ladder**: a track record raises the co-approval limit, but only the parent can accept it.
57. **Credit growth** (`oasis/proof/credit_growth.py`): milestone plan, per-ask evidence and a what-if simulator, read-only and never suggesting extra payments.
58. **Payment reliability record** (`oasis/proof/reliability.py`): create, view and verify a record of on-time payments.
59. **Evidence Passport** (`oasis/proof/evidence_passport.py`): one signed, QR-verifiable bundle proving a payment reached a registry-verified payee.
60. **Savings explanation endpoint**: explains the savings receipt in plain words.

## 5. AI-model features (live mode only)

61. **Invoice extraction**: the model reads payee, account, amount and due date; the deterministic parse is the fallback.
62. **Vision intake** (`VisionExtractor`): reads invoice photos and screenshots into text.
63. **AI risk scorer**: scores warning signs and can only raise a score; malformed answers keep their score.
64. **Payment planner**: model tool calling, always re-checked by the validator.
65. **Chat labeller** (`oasis/agent/chat_llm.py`): labels messages the router cannot place; it can never sign or pay, and a payment label only drafts a whole open bill.
66. **Explanation rewrites**: rewords template explanations; discarded if a number changes, is added or the text is not plain.
67. **FlightPath wording**: rewrites the deadline-consequence text in the user's language, with the same guard.
68. **Recovery draft**: drafts the message to a legitimate payee, checked for leaked details.
69. **Red-team variant generator**: writes fake invoices for benchmarks only; not part of the product.
70. **Live-replay demo** (`oasis/agent/replay.py`): runs the demo with recorded model answers, with no network.

## 6. Chat and intake

71. **Intent router** (`oasis/agent/nlu.py`): keyword and regex router for English, Chinese and Hinglish; no model needed.
72. **Chat intents** (`oasis/agent/chat.py`): balance, obligations, rate, routes, runway, plan, status, explain, proof, credit, help, pay, correct, cancel, estimate, convert, FAQ, and polite declines for reminders and standing orders.
73. **Refusals by category**: bypass, secrets, registry edits and similar requests are refused and audited by category.
74. **Multi-turn drafts**: change the amount, part payments, "pay half", and follow-up questions on a waiting draft.
75. **Pasted text intake** (`/api/intake`): invoices pasted into chat or the intake box.
76. **Image intake** (`/api/intake/image`): photos and screenshots, including Chinese text.
77. **Email intake** (`oasis/intake/mail.py`, `/api/intake/email`): `.eml` files, with sender-authentication, Reply-To and hidden-text evidence.
78. **Telegram and mailbox channels** (`oasis/intake/telegram.py`, `imap_poll.py`): optional bot and IMAP watcher with pairing endpoints; tested against fake servers only.
79. **Intake channels status**: shows which channels are configured.

## 7. Evaluation and judging tools

80. **Red-team console** (`/api/redteam`): a judge enters an attack, gets the verdict and rule; attempts are logged per sandbox.
81. **Break-it challenge** (`/api/breakit/*`): paste any fraud attempt and watch it run through the real pipeline, with an offline attacker generator and scoreboard.
82. **Break-it executor attacks** (`oasis/trust/breakit_exec.py`): tamper with, replay or forge a signed payment and hand it to the real executor.
83. **Numbers tab and benchmark endpoint**: shows the committed benchmark metrics.
84. **Scripted demo** (`oasis/demo.py`): two reproducible runs, Arjun's semester and the attack story.
85. **Benchmark runner with baseline** (`eval/runner.py`): the same pipeline with layers turned off for comparison.
86. **Evaluation suites** (`eval/`): chat tasks, outside-written independent sets, fuzz, mega stress tests, planning, corridors, netting, FlightPath, AI-contribution and chat-labeller sets.
87. **Live evaluation guards**: `--live` with a hard token cap, a not-reliable flag if the cap is hit, and a cap on the config module.
88. **Local token meter** (outside the repo): counts input and output tokens and cost per run.
89. **Per-judge sandboxes**: each judge login gets its own ledger, registry and attempt log, up to 20 at once.

## 8. Access, security and hosting

90. **Roles**: student, parent and judge, each with its own tabs and endpoints.
91. **Passcode login and sessions**: HttpOnly, SameSite=Strict cookies, 30-minute sessions in judge mode.
92. **Optional passkey** (`oasis/api/passkeys.py`): WebAuthn second factor.
93. **Rate limits** (`oasis/api/ratelimit.py`): per-client limits on logins and the red-team console.
94. **Judge mode**: API docs off, tighter limits, and refusal to start without custom passcodes.
95. **Security headers and Origin check**: CSP, HSTS, frame and referrer headers, exact-origin CSRF check and an allow list.
96. **Encrypted persistence** (`oasis/storage.py`): SQLite payloads encrypted with AES-256-GCM.
97. **Key files** (`oasis/trust/keyfile.py`): created on first use, git-ignored, optionally wrapped with a passphrase.
98. **Token budgets** (`oasis/config.py`): a daily limit and a lifetime limit (`OASIS_BEDROCK_TOTAL_TOKENS`) after which the model is never called again.
99. **Model call limits**: per-call connect and read timeouts, and a retry limit, so one hung call cannot freeze the server.
100. **Operational endpoints**: health, `/auth/me`, logout, language change, reset sandbox and device-key registration.
101. **Docker image and compose file**: non-root, read-only filesystem, healthcheck, single worker.
102. **Caddy HTTPS profile**: Let's Encrypt certificate and HTTP redirect (run end to end on the Azure VM).
103. **FISCO BCOS anchoring** (`tools/fisco/`): optional 4-node local chain for anchoring hashes, with a local simulated anchor by default (`oasis/chain/anchor.py`).
104. **Post-quantum TLS recipe** (`tools/caddy/`): hybrid key exchange tested with an OpenSSL client only.
105. **Judge start scripts** (`scripts/`): one command for Windows or bash, offline by default, `--live` with your own key.

## 9. Interface

106. **Landing page and 3D globe**: public front page with a how-it-works and limits section.
107. **Login gate and role home**: role selection, home cards and a feature drawer in the header.
108. **Tabs**: Home, FlightPath, Chat, Passport, Demo, Parent, Twin, Netting, Proof, Evidence Passport, Red team, Break it, Numbers, Help and Settings, plus corridor, credit growth, foreign-currency plan and Trust Pass panels.
109. **Two languages**: English and Simplified Chinese interface; the choice is saved in the Passport.
110. **Dark mode styles** (`frontend/src/dark.css`): dark theme support.
111. **PDF export**: reports can be downloaded as PDF from the UI.
112. **Help page and Settings**: usage help per role, and settings for language, device key, sandbox reset and session.
113. **MOCK labels**: simulated data is labelled throughout the UI.

## 10. Developer and documentation extras

114. **OpenAPI export and agent API doc**: `tools/export_openapi.py`, `docs/openapi.json` and `docs/agent-api.md` for scripted testing.
115. **Scripted client** (`tools/oasis_client.py`): login, key registration and signing in one call.
116. **Reference-data fetchers** (`tools/fetch_reference.py`, `fetch_extra_sanctions.py`): rebuild the sanctions snapshots.
117. **Test suite**: about 926 test functions (1606 cases), offline and hermetic.
118. **Documentation set**: judge guide, technical documentation, security self-assessment, evidence matrix, compliance mapping, results, real-vs-simulated, path to production and more in `docs/`.
119. **Progress ledger and rulebook**: `newaddition.md` records every change and result; `CLAUDE.md` holds the working rules (no paid model call without approval, security invariants).
