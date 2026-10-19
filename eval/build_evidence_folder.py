"""Assemble the Evidence/ folder: copies of the files that back every claim in the three submission documents, plus an index.

Copies only (saved reports, logs, the PDFs, evidence docs). No model call, no network, no secrets (.env and data/ are never read).

    PYTHONPATH=. python -m eval.build_evidence_folder
"""
from __future__ import annotations
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DST = ROOT / "Evidence"
R = ROOT / "eval" / "reports"

GROUPS = {
    "01_Submission_Documents": [ROOT / "docs/Technical_Documentation.pdf", ROOT / "docs/Security_Self_Assessment_Report.pdf",
                                ROOT / "execution_evidence/Execution_Evidence_Report.pdf"],
    "03_Attack_Task_and_Stress_Benchmarks": [R / f"{n}.{x}" for n in (
        "benchmark", "benchmark_hidden", "benchmark_hidden_prefix", "benchmark_fresh", "benchmark_fresh_prefix", "benchmark_blind2", "benchmark_blind2_prefix",
        "benchmark_attempts", "tasks", "independent", "independent2", "independent3", "independentG", "independentC", "independentA",
        "mega", "mega2_abuse", "mega2_inject", "mega2_tasks", "fuzz", "api_sweep", "risk_fresh", "simulation", "demo") for x in ("md", "json") if (R / f"{n}.{x}").exists()] + [R / "ml_risk.md", R / "router_robust.md", R / "outside_scenarios_offline.md", R / "outside_outside_codex_round2.md", R / "outside_firstrun.json"],
    "04_Live_Model_Evidence": [R / f"{n}.{x}" for n in (
        "ai_contribution", "ai_contribution_live_runs", "planning", "fxplan_live", "fxplan", "benchmark_live", "chat_llm", "chat_llm_heldout", "chat_llm_scale",
        "chat_llm_scale_rows", "chat_llm_heldout_rows", "chat_llm_rows", "chat_llm_heldout_repro_2026-10-17", "independent3_live", "independentG_live", "independentC_live",
        "vision_live", "corridors_live") for x in ("md", "json") if (R / f"{n}.{x}").exists()],
    "05_Feature_Evidence": [R / f"{n}.{x}" for n in ("flightpath", "netting", "corridors", "pqtls") for x in ("md", "json") if (R / f"{n}.{x}").exists()],
    "06_Security_and_Design_Notes": [ROOT / "docs" / n for n in ("security-evidence-matrix.md", "security-self-assessment.md", "pq-tls.md", "fisco-bcos.md",
                                                                "real-vs-simulated.md", "problem-evidence.md", "results.md", "execution-evidence.md")],
}

INDEX = """# Evidence

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
| Chat labeller: 72 of 73 paraphrases, traps: 0 of 25 fresh accepted, 1 of 25 original (a held draft); router rebuilt: DEV 86.9%, words withheld from the lexicon 58.9%, frozen 136 of 151, catalogue 205 of 205 (model off) | `04_.../chat_llm_scale.md`, `chat_llm_scale_rows.json`, `chat_llm_heldout.md` |
| Outside sets through the live path: 550 attacks and 170 look-alikes, 0 breaches | `04_.../independent3_live.md`, `independentG_live.md`, `independentC_live.md` |
| Live extraction and risk benchmark (injections followed 0 of 6) | `04_.../benchmark_live.md`, `benchmark_live.json` |
| Image intake: 4 of 6 correct | `04_.../vision_live.md`, `vision_live/` |
| Tokens, calls and USD of every metered live run | `04_.../ai_contribution_live_runs.json` |
| FlightPath, peer netting, corridor rules | `05_.../flightpath.md`, `netting.md`, `corridors.md` |
| Post-quantum signatures and TLS | `05_.../pqtls.md`, `06_.../pq-tls.md` |
| Test suite: 2628 passed, 2 skipped (offline) | `test_suite_result.txt`; rerun with the command in `CLAUDE.md` |
| Each security claim maps to named tests | `06_.../security-evidence-matrix.md` |
| Informal conversations with 10 people we know: 6 international students (Europe, Southeast Asia) and 4 parents (who, what we asked, limits) | `interviews.md` |
| Known limits, MOCK labelling | `06_.../security-self-assessment.md`, `real-vs-simulated.md`, `problem-evidence.md` |
"""


def main() -> None:
    if DST.exists():
        shutil.rmtree(DST)
    n = 0
    for g, files in GROUPS.items():
        (DST / g).mkdir(parents=True)
        for f in files:
            shutil.copyfile(f, DST / g / f.name)
            n += 1
    shutil.copytree(R / "vision_live", DST / "04_Live_Model_Evidence" / "vision_live")
    shutil.copytree(ROOT / "execution_evidence", DST / "02_Execution_Logs", ignore=shutil.ignore_patterns("*.pdf", "__pycache__"))
    shutil.copyfile(ROOT / "docs" / "interviews.md", DST / "interviews.md")
    (DST / "README.md").write_text(INDEX, encoding="utf-8")
    (DST / "test_suite_result.txt").write_text(chr(10).join(["Offline test suite, run (OASIS_DB=:memory: OASIS_LLM=offline, no network):",
                                                          "2628 passed, 2 skipped in 851.81s (0:14:11)",
                                                          "The 2 skipped tests are the live FISCO and live PQ-TLS tests.", ""]), encoding="utf-8")
    print(f"wrote {DST.name}/: {n} files in {len(GROUPS)} groups + execution logs + index")


if __name__ == "__main__":
    main()
