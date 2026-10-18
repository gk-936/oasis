# Evidence

Every file here backs a claim made in the three submission documents (Technical Documentation, Security Self-Assessment, Execution Evidence).
These are copies of the saved reports and logs in the repository (`eval/reports/`, `execution_evidence/`, `docs/`). All data is simulated (MOCK).
Live-model results are saved report rows from Amazon Nova Pro; Nova calls are not written to the Oasis audit chain, so these files are the record, not a provider-side log.
Rebuild this folder with `PYTHONPATH=. python -m eval.build_evidence_folder`. The earlier Groq-hosted run (`benchmark_live_groq`) is history only and is not included; Groq was removed.

## Folders

| Folder | What it holds |
|---|---|
| `01_Submission_Documents` | The three PDFs |
| `02_Execution_Logs` | The execution-evidence folder: raw operation log, results, offline AI-participant logs, live-report copies, and `verify_evidence.py` (run it from inside the folder; no network) |
| `03_Attack_Task_and_Stress_Benchmarks` | Offline attack, task and stress benchmarks, outside-written sets, authorization sweep |
| `04_Live_Model_Evidence` | Saved live runs of Amazon Nova Pro with token and cost records |
| `05_Feature_Evidence` | FlightPath, netting, corridor and post-quantum TLS records |
| `06_Security_and_Design_Notes` | Evidence matrix, security notes, problem evidence, what is real and simulated |

## Claim to file

| Claim | Where to check it |
|---|---|
| 6 of 6 scam scenarios mitigated, CNY 0 against CNY 126,000 lost, 2 of 2 genuine payments, 10 of 10 tampered payments refused | `02_Execution_Logs/operation_log.jsonl`, `evidence_results.json`, `verify_evidence.py` |
| Audit chains verify, replay to identical heads, tamper is detected | `02_Execution_Logs/evidence_results.json`, `demo_run_log.json` |
| Chat session: one payment, three refusals, CNY 0 lost; FlightPath advice never resends; plan trade-offs | `02_Execution_Logs/participant_logs.json` |
| Layered benchmark: 32 attacks and 12 genuine changes (6.2%, 68.8%, 100%, 100%) | `03_.../benchmark.md`, `benchmark.json` |
| Hidden blind set and fresh set (first-run records kept) | `03_.../benchmark_hidden*`, `benchmark_fresh*`, `benchmark_blind2*` |
| Outside-written sets 1, 2, 3, G, C, A | `03_.../independent*.md` |
| 92,076 chat messages and 29,053 conversations, 0 hard breaches; mutation fuzz | `03_.../mega.md`, `mega2_*.md`, `fuzz.md` |
| Authorization sweep: 94 routes, 752 calls, 0 findings | `03_.../api_sweep.md`, `api_sweep.json` |
| Chat task benchmark, 92 tasks, 0 false refusals | `03_.../tasks.md` |
| Risk scorer out of sample, trained model | `03_.../risk_fresh.md`, `ml_risk.md` |
| 128 poisoned invoices: model changed no field; 40 of 40 genuine invoices held as offline; risk scorer 168 scored | `04_.../ai_contribution.md`, `ai_contribution.json` |
| Planner 56 of 56 valid, 140 of 140 deadlines, 7 repeats | `04_.../planning.md`, `planning.json` |
| Foreign-currency planner | `04_.../fxplan_live.md`, `fxplan_live.json` |
| Chat labeller: 72 of 73 paraphrases, traps 1 of 25 as run and 0 of 25 after a rule added later (post hoc); router alone 52 right, 19 wrong, 73 unknown | `04_.../chat_llm_scale.md`, `chat_llm_scale_rows.json`, `chat_llm_heldout.md` |
| Outside sets through the live path: 550 attacks and 170 look-alikes, 0 breaches | `04_.../independent3_live.md`, `independentG_live.md`, `independentC_live.md` |
| Live extraction and risk benchmark (injections followed 0 of 6) | `04_.../benchmark_live.md`, `benchmark_live.json` |
| Image intake: 4 of 6 correct | `04_.../vision_live.md`, `vision_live/` |
| Tokens, calls and USD of every metered live run | `04_.../ai_contribution_live_runs.json` |
| FlightPath, peer netting, corridor rules | `05_.../flightpath.md`, `netting.md`, `corridors.md` |
| Post-quantum signatures and TLS | `05_.../pqtls.md`, `06_.../pq-tls.md` |
| Test suite: 1766 passed, 2 skipped (offline) | `test_suite_result.txt`; rerun with the command in `CLAUDE.md` |
| Each security claim maps to named tests | `06_.../security-evidence-matrix.md` |
| Informal conversations with 10 people we know: 6 international students (Europe, Southeast Asia) and 4 parents (who, what we asked, limits) | `interviews.md` |
| Known limits, MOCK labelling | `06_.../security-self-assessment.md`, `real-vs-simulated.md`, `problem-evidence.md` |
