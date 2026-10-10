# What is real and what is simulated

| Real (working code in this repository) | Simulated (labelled MOCK in the UI and docs) |
|---|---|
| Six-step pipeline, Student Financial Passport | Exchange rates (deterministic sine around 0.0845 CNY/INR), route fees, delivery times, reliability |
| Deterministic policy engine and permission tiers (`oasis/trust/policy.py`) | Payment rails and bank transfers (`SandboxLedger`) |
| Hybrid Ed25519 + ML-DSA-65 signed intents, intent-enforcing executor | Wallet / QR foreign-card fees (3% over CNY 200 + 1% card bank fee, from researched figures) and imported wallet spending |
| Verification ramp (registry check → test payment → low limit → full limit) | Verified-payee registry: WeIdentity-*style* demo credentials, not real institutions, not the WeIdentity SDK |
| Canary tripwires (early detection) and freeze → recovery plan → ask | Sandbox balances; parent account |
| Corridor rules engine with data file `inr_cny.yaml` (values researched, marked unconfirmed where applicable) | Simulated humans in the benchmark (student / parent approvers) |
| SHA-256 hash-chained audit log and verifier | Simulated clock and "minutes to resolve" |
| Proof packs and an independent verifier | Outcome simulation is a **model** with stated assumptions (`eval/simulator.py`) |
| Tier-1 autonomy: student rate targets and recurring bills to Verified_Full recipients, under the policy engine | Rates that targets are checked against (mock path) |
| Spending categorisation and the cold-start → own-pattern forecast | Reference costs and the transactions it learns from in the demo (mock wallet data) |
| SQLite persistence of Passport, audit log, proofs, why-cards | Anchoring runs on `LocalAnchorChain`, a local hash-linked simulation, **not** FISCO BCOS |
| Scripted, repeatable demo (fixed seed, offline) | Demo signing keys are seeded and public; real keys are ephemeral per process |
| Agentic planner: tool protocol, deterministic plan validator (SAFE per calendar year, LRS, TCS, deadlines, funds), offline planner, Groq native tool calling with recorded fallback (fake-client tests; live run on 3 of 8 scenarios, 2026-10-10) | Rates, routes and fees the plans are quoted against; the registry's verified contact channels |
| Optional SM2/SM3 signer (`gmssl` 3.2.2): sign/verify, tamper and cross-key rejection, standard test vector reproduced (not constant-time, unaudited; interoperability untested) | |
| Benchmark runner, baseline (same pipeline with layers off), red-team console | |
| Offline deterministic parser / risk scorer / explainer (the no-network path); Groq adapter with fallback, backoff and cache (fake-client tests plus live smoke test and benchmark runs on 2026-10-10; live-agent extraction mode results are one repeat, n=6 injections) | Model behaviour beyond those runs is unverified |

Not built: FISCO BCOS integration (only an adapter stub that raises `NotImplementedError`; the "chain" in proof packs is a local simulation), real banking integration, hybrid post-quantum TLS (deployment concern, not in this code), a local offline language model or OCR (the deterministic parser is the offline path), encryption of the SQLite file at rest.

No result is a production claim. Corridor figures are "as of October 2026" and each still needs its official confirmation step (see `oasis/trust/rules/inr_cny.yaml`).
