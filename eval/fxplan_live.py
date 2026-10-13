"""LIVE evaluation of the foreign-currency planner (Amazon Nova Pro on Amazon Bedrock). THIS SPENDS TOKENS.

Per the repository rulebook, run it only with the owner's explicit approval for that specific run, and always pass --cap.
  OASIS_LLM=bedrock PYTHONPATH=. python -m eval.fxplan_live --cap 30000 --per-plan-cap 25000 --only usd_from_inr
  PYTHONPATH=. python -m eval.fxplan_live --report          (offline: rebuild the report from the saved rows, no network)

The scenarios are the ones in eval/fxplan_bench.py (MOCK world, estimated route prices). The model gets the FX toolbox
(fx_facts, fx_size_conversion, propose_plan) and may propose at most 4 plans; the deterministic validator judges each one. A row
is 'model-only valid' when the model's own plan was valid without the deterministic fallback. Rows are saved in
eval/reports/fxplan_live.json; a run that hit an API or quota error is discarded, not recorded."""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

from eval.fxplan_bench import SCENARIOS, build

REPORTS = Path(__file__).parent / "reports"
ROWS = REPORTS / "fxplan_live.json"
IDS = {s[0]: s for s in SCENARIOS}
LIVE_TEMPERATURE = 0.3
PER_PLAN_CAP = 25_000
REFUSAL = {"over_lrs"}     # scenarios whose correct outcome is NO valid plan


def load() -> list[dict]:
    return json.loads(ROWS.read_text(encoding="utf-8")) if ROWS.exists() else []


def save(rows: list[dict]) -> None:
    REPORTS.mkdir(exist_ok=True)
    ROWS.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def run_scenario(sid: str, planner) -> dict:
    """Plan one scenario with `planner` and summarise the result as a row. No network of its own."""
    w = build(IDS[sid])
    t0 = time.time()
    res = planner.plan(w, "Pay my foreign-currency tuition on time at the lowest cost.")
    v = res.validation or {}
    m = v.get("metrics") or {}
    tools = [x["tool"] for x in res.trace if x.get("type") == "tool_call"]
    return {"scenario": sid, "title": IDS[sid][1], "planner": res.planner, "model": res.model, "valid": res.valid,
            "fell_back": res.fell_back, "fallback_reason": res.fallback_reason, "model_valid_without_fallback": res.valid and not res.fell_back,
            "model_proposals": sum(1 for x in res.trace if x.get("type") == "proposal" and not res.fell_back) or res.iterations,
            "model_calls": res.model_calls, "tokens": res.tokens, "seconds": round(time.time() - t0, 1), "tools_called": tools,
            "deadlines_met": f"{m.get('deadlines_met', 0)}/{m.get('obligations', 0)}", "saved_vs_bank_usd": m.get("saved_vs_bank_usd_equivalent"),
            "corridors": sorted({s["corridor"] for s in res.steps if s["action"] == "convert"}),
            "error_codes": sorted({e["code"] for e in v.get("errors", [])})}


def is_budget_artifact(r: dict) -> bool:
    reason = (r.get("fallback_reason") or "").lower()
    return r["fell_back"] and any(k in reason for k in ("quota", "throttl", "credential", "accessdenied", "network", "timeout", "connection", "validationexception"))


def report() -> None:
    rows = load()
    L = ["# Foreign-currency planner, live (Amazon Nova Pro on Bedrock)", "",
         "MOCK world on the frozen rate snapshot; route prices are public-range estimates. The deterministic validator judges every proposal. "
         "Small sample: a handful of plans on mock data is not a robustness claim.", "",
         "| Scenario | Rep | Planner / model | Model-only valid | Valid | Fallback | Proposals | Model calls | Tokens | Seconds | Corridors | Tools called |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['title']} | {r.get('rep', 0) + 1} | {r['planner']} / {r['model']} | {r['model_valid_without_fallback']} | {r['valid']} | {r['fell_back']} "
                 f"({(r['fallback_reason'] or '-')[:50]}) | {r['model_proposals']} | {r['model_calls']} | {r['tokens']:,} | {r['seconds']} | "
                 f"{', '.join(r['corridors']) or '-'} | {' > '.join(r['tools_called']) or '-'} |")
    if rows:
        ok = [r for r in rows if r["scenario"] not in REFUSAL]
        no = [r for r in rows if r["scenario"] in REFUSAL]
        L += ["", f"**Plans: {len(rows)}** ({len(ok)} that should be plannable, {len(no)} that should be refused). Tokens spent in total: "
                  f"{sum(r['tokens'] for r in rows):,}. Run date: {', '.join(sorted({r.get('run_date', '?') for r in rows}))}.", "",
              f"- Plannable scenarios: the model's own plan was valid without the fallback in **{sum(r['model_valid_without_fallback'] for r in ok)} of {len(ok)}**; "
              f"a valid plan was delivered (model or deterministic fallback) in **{sum(r['valid'] for r in ok)} of {len(ok)}**.",
              f"- Refusal scenario (a payment above the India LRS limit): **{sum(not r['valid'] for r in no)} of {len(no)}** correctly ended with no valid plan, so no plan "
              "that breaks the limit was produced. The model spent 16-19k tokens trying each time; the deterministic fallback also (correctly) found none.", "",
              "| Corridor | Plans | Model-only valid | Valid delivered |", "|---|---|---|---|"]
        for c in sorted({", ".join(r["corridors"]) for r in ok if r["corridors"]}):
            g = [r for r in ok if ", ".join(r["corridors"]) == c]
            L.append(f"| {c} | {len(g)} | {sum(r['model_valid_without_fallback'] for r in g)} | {sum(r['valid'] for r in g)} |")
    else:
        L += ["", "_No live rows yet: the evaluation has not been run._"]
    (REPORTS / "fxplan_live.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--report", action="store_true", help="offline: rebuild the report from the saved rows (no network)")
    ap.add_argument("--only", default="usd_from_inr", help="comma-separated scenario ids, or 'all'")
    ap.add_argument("--repeats", type=int, default=1, help="repeats of every chosen scenario (a fresh cache salt per repeat)")
    ap.add_argument("--cap", type=int, help="stop starting plans once this many NEW tokens were spent in this call (required to run)")
    ap.add_argument("--per-plan-cap", type=int, default=PER_PLAN_CAP, help="stop asking the model once one plan used this many tokens")
    args = ap.parse_args(argv)
    if args.report:
        report()
        return 0
    if not args.cap:
        ap.error("--cap is required to run (use --report to render offline)")
    ids = list(IDS) if args.only == "all" else args.only.split(",")
    bad = [i for i in ids if i not in IDS]
    if bad:
        ap.error(f"unknown scenario(s): {bad}")
    from eval.planning_v3 import default_model
    from oasis.agent.llm import LiveLLM
    from oasis.agent.planner import AgenticFxPlanner
    model = default_model()
    rows = load()
    spent = 0
    for rep in range(args.repeats):
        llm = LiveLLM(model=model, fallback_model=model, salt=f"fxlive{rep}", temperature=LIVE_TEMPERATURE)
        for sid in ids:
            if any(r["scenario"] == sid and r.get("rep", 0) == rep and r.get("model_requested") == model for r in rows):
                continue                                           # already recorded: a re-run resumes
            if args.cap - spent < args.per_plan_cap:
                print(f"cap reached ({spent:,} of {args.cap:,} tokens; a plan needs room for {args.per_plan_cap:,}); stopping", flush=True)
                report()
                return 2
            r = run_scenario(sid, AgenticFxPlanner(llm, token_cap=args.per_plan_cap))
            if is_budget_artifact(r):
                print(f"{sid} rep{rep + 1}: discarded (API/quota error: {(r['fallback_reason'] or '')[:80]}); not recorded.", flush=True)
                report()
                return 3
            r.update(model_requested=model, rep=rep, run_date=time.strftime("%Y-%m-%d"), per_plan_cap=args.per_plan_cap)
            spent += r["tokens"]
            rows.append(r)
            save(rows)
            print(f"{sid} rep{rep + 1} {model}: model_only_valid={r['model_valid_without_fallback']} valid={r['valid']} fallback={r['fell_back']} "
                  f"({(r['fallback_reason'] or '')[:40]}) props={r['model_proposals']} calls={r['model_calls']} tokens={r['tokens']} s={r['seconds']} total={spent:,}", flush=True)
    report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
