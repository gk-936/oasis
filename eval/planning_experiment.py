"""Planner token-efficiency experiment (2026-10-11): old vs new tool-result format, original and held-out scenarios.

    python -m eval.planning_experiment --format v2 --set heldout --rep 0 --cap 60000

Each finished plan is appended to eval/reports/planning_experiment.json straight away (resumable: a finished
(format, set, rep, scenario) is skipped). Same settings as the earlier live runs: temperature 0.3, per-plan cap 22,000,
cache salt planrep<rep>. `--format v1` is the full-result format used on 2026-10-11, `v2` the compact one. The held-out
scenarios (oasis/planning/scenarios.py: HELDOUT) were written before any live result of v2 was seen and are never tuned on.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

from eval.planning import LIVE_TEMPERATURE, PER_PLAN_CAP, run_scenario
from oasis.planning.scenarios import HELDOUT, SCENARIOS

OUT = Path(__file__).resolve().parent / "reports" / "planning_experiment.json"


def load() -> list[dict]:
    return json.loads(OUT.read_text(encoding="utf-8"))["rows"] if OUT.exists() else []


def save(rows: list[dict]) -> None:
    OUT.write_text(json.dumps({"temperature": LIVE_TEMPERATURE, "per_plan_cap": PER_PLAN_CAP, "rows": rows}, indent=1, default=str), encoding="utf-8")


def report() -> None:
    """Merge the experiment rows into eval/reports/planning.json and re-render planning.md (no network)."""
    from eval import planning as P
    jf = P.REPORTS / "planning.json"
    data = json.loads(jf.read_text(encoding="utf-8"))
    ex = json.loads(OUT.read_text(encoding="utf-8"))
    ex.setdefault("notes", NOTES)
    data["experiment"] = P.experiment_summary(data["live"]["results"], ex)
    jf.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    (P.REPORTS / "planning.md").write_text(P.render(data), encoding="utf-8")


NOTES = [
    "Spend: 230,613 new tokens on 2026-10-11 (key fingerprints: ceef6c23 80,651; a1d412ac 149,962; 499b1366 0; d40d45b2 0), 19 plans plus one re-run, under the ~250k cap.",
    "Not run for lack of budget: a second repeat of the new format, and the urgent-deadline scenario in the new format. The old-format comparison for the original scenarios is the three repeats already recorded (24 plans, 2026-10-11, other key state).",
    "One new-format plan (multiple_obligations) was first stopped at 12,362 tokens by the run-level cap, not by the model; that row was discarded as a budget artifact and the plan resumed (its first calls replay from the disk cache, so its tokens are recorded as 12,362 + 4,730 and its seconds cover only the resumed part).",
    "Old-format error counts for the original scenarios exist only for the first proposal; all other groups count every validator error the live model drew.",
    "Fisher exact tests (two-sided, uncorrected): original same scenarios new 5/7 vs old 6/21 gives p about 0.076; pooled new 8/11 vs old 9/25 gives p about 0.070. Neither is conclusive. The held-out result is 3/4 vs 3/4: no measurable difference.",
]


def main(argv=None) -> int:
    if argv is None and "--report" in sys.argv:
        report()
        return 0
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", choices=("v1", "v2"), required=True)
    ap.add_argument("--set", choices=("original", "heldout"), required=True, dest="sset")
    ap.add_argument("--rep", type=int, default=0)
    ap.add_argument("--cap", type=int, required=True, help="stop starting plans once this many NEW tokens were spent in this invocation")
    ap.add_argument("--only")
    args = ap.parse_args(argv)
    from oasis.agent.llm import LiveLLM
    from oasis.agent.planner import AgenticPlanner
    ids = list(HELDOUT if args.sset == "heldout" else SCENARIOS)
    if args.only:
        ids = [i for i in ids if i in args.only.split(",")]
    rows = load()
    done = {(r["format"], r["set"], r["rep"], r["scenario"]) for r in rows}
    llm = LiveLLM(salt=f"planrep{args.rep}", temperature=LIVE_TEMPERATURE)
    spent = 0
    for sid in ids:
        if (args.format, args.sset, args.rep, sid) in done:
            continue
        if spent >= args.cap:
            print("cap reached; stopping", flush=True)
            return 2
        r = run_scenario(sid, AgenticPlanner(llm, token_cap=min(PER_PLAN_CAP, args.cap - spent), fmt=args.format))
        r.update(format=args.format, rep=args.rep, run_date="2026-10-11", per_plan_cap=PER_PLAN_CAP)
        r["set"] = args.sset
        spent += r["tokens"]
        rows = load() + [r]
        save(rows)
        print(f"{args.format} {args.sset} rep{args.rep} {sid}: valid={r['valid']} fallback={r['fell_back']} ({(r['fallback_reason'] or '')[:40]}) "
              f"props={r['model_proposals']} calls={r['model_calls']} tokens={r['tokens']} s={r['seconds']} total={spent:,}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
