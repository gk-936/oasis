"""Pre-registered evaluation of planner format v3 (calculator tools) against v2, per planner model.

    # one cell = one (format, model): 12 scenarios (8 original + 4 held-out) x N repeats, saved plan by plan
    python -m eval.planning_v3 --format v3 --model qwen/qwen3.8-27b --repeats 2 --cap 450000
    python -m eval.planning_v3 --format v2 --model qwen/qwen3.8-27b --repeats 2 --cap 450000
    python -m eval.planning_v3 --report            # offline: re-render eval/reports/planning_v3.md/.json from the saved rows

Nothing here runs unless you pass --format/--model (no flag-less network use). Rows are keyed (format, model, rep, scenario)
in eval/reports/planning_v3_rows.json, so formats and models never mix, and a finished key is skipped on the next call
(resumable). The model environment default is OASIS_PLANNER_MODEL, then OASIS_AGENT_MODEL; the fallback model is pinned to the
SAME model, so a row never silently comes from another model. Temperature 0.3 and a repeat-specific cache salt make
repeats distinct samples. The validator, not a model, scores every plan; a plan counts as "model-only valid" only if the model's
own proposal passed with no deterministic fallback.

Budget artifacts are never recorded as results: a plan is not started unless the run-level cap leaves room for a whole
per-plan cap, and a plan that ended because the API/daily quota failed is discarded (the run stops; call it again later).
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path

from eval.planning import LIVE_TEMPERATURE, PER_PLAN_CAP, REPORTS, run_scenario
from oasis import config
from oasis.planning.scenarios import ALL_SCENARIOS, HELDOUT, SCENARIOS

ROWS = REPORTS / "planning_v3_rows.json"
MD = REPORTS / "planning_v3.md"
SUMMARY = REPORTS / "planning_v3.json"
FORMATS = ("v2", "v3")
MODELS = ("qwen/qwen3.8-27b", "openai/gpt-oss-120b")
SCENARIO_IDS = list(SCENARIOS) + list(HELDOUT)                  # 8 original + 4 held-out = 12
# Validator codes that mean "the number was wrong" (the model's own sums, fees, rounding, balances or quota arithmetic).
ARITHMETIC = ("amount_mismatch", "insufficient_cny", "insufficient_inr", "rate_target_reserve", "safe_quota_exceeded")
MIN_GAIN_PP, DEFAULT_REPEATS = 15.0, 2

DECISION_RULE = (
    "Pre-registered decision rule (fixed before any live v3 result existed): v3 becomes the default planner format only if BOTH hold, "
    "on the plans pooled over every model that ran both formats: (A) the model-only valid rate of v3 exceeds that of v2 by at least "
    f"{MIN_GAIN_PP:.0f} percentage points PLUS the observed spread of v2 (the widest max-minus-min of v2's per-repeat model-only valid "
    "rates in any model cell; needs at least two complete repeats); and (B) the held-out scenarios do not regress "
    "(v3 held-out model-only valid rate >= v2's). Otherwise v2 stays the default. The Fisher exact p-value is reported for context "
    "and is not part of the rule.")


# ------------------------------------------------------------------------------------------------------ statistics
def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for the table [[a, b], [c, d]] (sum of all tables no more likely than the observed one)."""
    n1, n2, k = a + b, c + d, a + c
    n = n1 + n2

    def pmf(x: int) -> float:
        return math.comb(n1, x) * math.comb(n2, k - x) / math.comb(n, k)

    lo, hi = max(0, k - n2), min(k, n1)
    p0 = pmf(a)
    return min(1.0, sum(pmf(x) for x in range(lo, hi + 1) if pmf(x) <= p0 * (1 + 1e-9)))


def fallback_class(reason: str | None) -> str:
    r = (reason or "").lower()
    if r.startswith("token cap"):
        return "token cap"
    if "never proposed" in r:
        return "never proposed"
    if r.startswith("no valid plan after"):
        return "no valid plan after proposals"
    if "tool_use_failed" in r or "failed to call a function" in r:
        return "malformed tool call"          # the model's own generation was invalid (Groq 400): a model failure, not quota
    if "stopped without" in r:
        return "stopped without a plan"
    if r:
        return "API/other error"
    return "-"


def is_budget_artifact(row: dict) -> bool:
    """A fallback caused by quota/network failures says nothing about the model; it must not be recorded as a result."""
    return fallback_class(row.get("fallback_reason")) == "API/other error"


# --------------------------------------------------------------------------------------------------------- storage
def load(path: Path | None = None) -> list[dict]:
    path = path or ROWS
    return json.loads(path.read_text(encoding="utf-8"))["rows"] if path.exists() else []


def save(rows: list[dict], path: Path | None = None) -> None:
    path = path or ROWS
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"temperature": LIVE_TEMPERATURE, "scenarios": SCENARIO_IDS, "rows": rows}, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def row_key(r: dict) -> tuple:
    return (r["format"], r["model_requested"], r["rep"], r["scenario"])


# ------------------------------------------------------------------------------------------------------ aggregation
def cell_stats(rows: list[dict]) -> dict:
    n = len(rows)
    ok = [r for r in rows if r["model_valid_without_fallback"]]
    reps = sorted({r["rep"] for r in rows})
    per_rep = []
    for k in reps:
        rr = [r for r in rows if r["rep"] == k]
        per_rep.append({"rep": k, "plans": len(rr), "model_only_valid": sum(r["model_valid_without_fallback"] for r in rr),
                        "complete": len(rr) == len(SCENARIO_IDS)})
    full = [x for x in per_rep if x["complete"]]
    rates = [x["model_only_valid"] / x["plans"] for x in full]
    errs: Counter = Counter()
    for r in rows:
        errs.update(r.get("error_counts") or {})
    tot_err = sum(errs.values())
    it = [r["iterations_to_valid"] for r in rows if r.get("iterations_to_valid")]
    held = [r for r in rows if r["scenario"] in HELDOUT]
    orig = [r for r in rows if r["scenario"] in SCENARIOS]
    fb = Counter(fallback_class(r.get("fallback_reason")) for r in rows if r["fell_back"])
    avg = lambda key, nd=0: round(sum(r[key] for r in rows) / n, nd) if n else None
    return {"plans": n, "model_only_valid": len(ok), "model_only_rate": len(ok) / n if n else None,
            "final_valid": sum(r["valid"] for r in rows), "fallbacks": n - len(ok), "fallback_reasons": dict(fb),
            "error_counts": dict(errs), "errors_total": tot_err,
            "arithmetic_errors": sum(errs.get(c, 0) for c in ARITHMETIC),
            "arithmetic_share": (sum(errs.get(c, 0) for c in ARITHMETIC) / tot_err) if tot_err else None,
            "mean_proposals_to_valid": round(sum(it) / len(it), 2) if it else None,
            "tokens_per_plan": avg("tokens"), "calls_per_plan": avg("model_calls", 2), "seconds_per_plan": avg("seconds"),
            "per_repeat": per_rep, "complete_repeats": len(full),
            "rate_min": min(rates) if rates else None, "rate_max": max(rates) if rates else None,
            "spread_pp": (max(rates) - min(rates)) * 100 if len(rates) > 1 else None,
            "heldout": [sum(r["model_valid_without_fallback"] for r in held), len(held)],
            "original": [sum(r["model_valid_without_fallback"] for r in orig), len(orig)],
            "other_model_rows": sum(1 for r in rows if r.get("model") and r.get("model_requested") and r["model"] != r["model_requested"])}


def summarize(rows: list[dict]) -> dict:
    cells: dict[tuple, list[dict]] = {}
    for r in rows:
        cells.setdefault((r["format"], r["model_requested"]), []).append(r)
    out = {"cells": {f"{f} | {m}": cell_stats(v) for (f, m), v in sorted(cells.items())}, "comparisons": {}, "decision": None}
    models = sorted({m for (_, m) in cells})
    for m in models:
        a, b = cells.get(("v3", m)), cells.get(("v2", m))
        if a and b:
            out["comparisons"][m] = _compare(a, b)
    both = [m for m in models if ("v3", m) in cells and ("v2", m) in cells]
    if both:
        a = [r for m in both for r in cells[("v3", m)]]
        b = [r for m in both for r in cells[("v2", m)]]
        out["comparisons"]["pooled"] = _compare(a, b)
        out["decision"] = decide(both, cells, out["comparisons"]["pooled"])
    return out


def _compare(a: list[dict], b: list[dict]) -> dict:
    ka, kb = sum(r["model_valid_without_fallback"] for r in a), sum(r["model_valid_without_fallback"] for r in b)
    return {"v3": [ka, len(a)], "v2": [kb, len(b)], "delta_pp": (ka / len(a) - kb / len(b)) * 100,
            "fisher_p": fisher_exact(ka, len(a) - ka, kb, len(b) - kb),
            "heldout_v3": [sum(r["model_valid_without_fallback"] for r in a if r["scenario"] in HELDOUT), sum(1 for r in a if r["scenario"] in HELDOUT)],
            "heldout_v2": [sum(r["model_valid_without_fallback"] for r in b if r["scenario"] in HELDOUT), sum(1 for r in b if r["scenario"] in HELDOUT)]}


def decide(models: list[str], cells: dict, pooled: dict) -> dict:
    """Apply the pre-registered rule. Verdict is 'INCOMPLETE' until every compared cell has all 12 scenarios x >= 2 repeats."""
    st = {k: cell_stats(v) for k, v in cells.items() if k[1] in models}
    spreads = [st[("v2", m)]["spread_pp"] for m in models]
    complete = all(st[(f, m)]["complete_repeats"] >= 2 for f in FORMATS for m in models)
    if not complete or any(s is None for s in spreads):
        return {"verdict": "INCOMPLETE", "reason": "needs every compared cell (v2 and v3, each model) to have at least two complete repeats of all 12 scenarios",
                "delta_pp": pooled["delta_pp"]}
    spread = max(spreads)
    need = MIN_GAIN_PP + spread
    h3, h2 = pooled["heldout_v3"], pooled["heldout_v2"]
    cond_a = pooled["delta_pp"] >= need
    cond_b = (h3[0] / h3[1]) >= (h2[0] / h2[1]) if h3[1] and h2[1] else False
    return {"verdict": "v3 becomes default" if cond_a and cond_b else "v2 stays default", "delta_pp": pooled["delta_pp"], "v2_spread_pp": spread,
            "needed_pp": need, "condition_a_gain": cond_a, "condition_b_heldout_no_regression": cond_b}


# ---------------------------------------------------------------------------------------------------------- report
def _pct(x) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def render(rows: list[dict]) -> str:
    s = summarize(rows)
    L = ["# Planner format v3 (calculator tools) vs v2: pre-registered evaluation", "",
         "Scored by the deterministic plan validator, never by a model. 12 scenarios per repeat (8 original + 4 held-out `heldout_*`), temperature "
         f"{LIVE_TEMPERATURE}, a repeat-specific cache salt, the same per-plan token cap for both formats. **Model-only valid** = the model's own "
         "proposal passed the validator and no deterministic fallback was used. Protocol and commands: "
         "[docs/planner-efficiency.md](../../docs/planner-efficiency.md).", "", DECISION_RULE, ""]
    if not rows:
        return "\n".join(L + ["_No live rows yet: the evaluation has not been run._", ""])
    L += ["## Cells (format x model)", "",
          "| Format | Model | Plans | Model-only valid | Per repeat (valid/12) and spread | Final valid | Fallbacks (reasons) | Mean proposals to valid | Tokens / plan | Calls / plan | Seconds / plan |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for key, c in s["cells"].items():
        f, m = key.split(" | ")
        reps = ", ".join(f"{x['model_only_valid']}/{x['plans']}" + ("" if x["complete"] else "*") for x in c["per_repeat"])
        spread = f"; range {c['rate_min'] * 100:.0f}-{c['rate_max'] * 100:.0f}% ({c['spread_pp']:.0f} pp)" if c["spread_pp"] is not None else "; spread n/a (<2 complete repeats)"
        fb = ", ".join(f"{k} {v}" for k, v in sorted(c["fallback_reasons"].items())) or "-"
        L.append(f"| {f} | {m} | {c['plans']} | {c['model_only_valid']} ({_pct(c['model_only_rate'])}) | {reps}{spread} | {c['final_valid']} of {c['plans']} | "
                 f"{c['fallbacks']} ({_pct(c['fallbacks'] / c['plans'])}): {fb} | {c['mean_proposals_to_valid']} | {c['tokens_per_plan']:,} | {c['calls_per_plan']} | {c['seconds_per_plan']} |")
    L += ["", "`*` = an incomplete repeat (not used for the spread). Final valid counts the deterministic fallback plan, so it is high by construction.", ""]
    L += ["## Validator errors by code (every proposal the model made)", "",
          f"Arithmetic codes (the number was wrong): {', '.join(f'`{c}`' for c in ARITHMETIC)}. Other codes (copying, routing, dates, payee) are not counted as arithmetic; `unknown_route` is a copy error.", "",
          "| Format | Model | Errors | Arithmetic share | By code |", "|---|---|---|---|---|"]
    for key, c in s["cells"].items():
        f, m = key.split(" | ")
        L.append(f"| {f} | {m} | {c['errors_total']} | {_pct(c['arithmetic_share'])} ({c['arithmetic_errors']}) | "
                 f"{', '.join(f'{k} {v}' for k, v in sorted(c['error_counts'].items())) or '-'} |")
    L += ["", "## v3 vs v2", "", "| Comparison | v3 model-only valid | v2 model-only valid | Delta (pp) | Fisher exact p (two-sided) | Held-out v3 | Held-out v2 |", "|---|---|---|---|---|---|---|"]
    for name, c in s["comparisons"].items():
        L.append(f"| {name} | {c['v3'][0]}/{c['v3'][1]} ({_pct(c['v3'][0] / c['v3'][1])}) | {c['v2'][0]}/{c['v2'][1]} ({_pct(c['v2'][0] / c['v2'][1])}) | "
                 f"{c['delta_pp']:+.0f} | {c['fisher_p']:.3f} | {c['heldout_v3'][0]}/{c['heldout_v3'][1]} | {c['heldout_v2'][0]}/{c['heldout_v2'][1]} |")
    if not s["comparisons"]:
        L.append("| (needs a v2 and a v3 cell for the same model) | | | | | | |")
    L += ["", "Pooled rows add the models together; the per-model rows are shown so one model cannot hide in the pool. Cells with different tests are not mixed.", ""]
    d = s["decision"]
    L += ["## Decision", ""]
    if d is None:
        L.append("No model has both a v2 and a v3 cell yet: **no decision**.")
    elif d["verdict"] == "INCOMPLETE":
        L.append(f"**INCOMPLETE** - {d['reason']}. Observed pooled delta so far: {d['delta_pp']:+.0f} pp. v2 stays the default until the rule can be applied.")
    else:
        L.append(f"Pooled delta {d['delta_pp']:+.0f} pp against a required {d['needed_pp']:.0f} pp (15 + v2 spread {d['v2_spread_pp']:.0f}): "
                 f"condition A {'MET' if d['condition_a_gain'] else 'NOT met'}. Held-out no regression: condition B {'MET' if d['condition_b_heldout_no_regression'] else 'NOT met'}. "
                 f"**Verdict: {d['verdict']}.**")
    odd = {k: c["other_model_rows"] for k, c in s["cells"].items() if c["other_model_rows"]}
    if odd:
        L += ["", f"Warning: rows answered by a different model than requested (fallback model): {odd}. Treat those cells as contaminated."]
    L += ["", "## Per scenario (model-only valid across repeats)", "", "| Scenario | " + " | ".join(s["cells"]) + " |", "|---|" + "---|" * len(s["cells"])]
    for sid in SCENARIO_IDS:
        cols = []
        for key in s["cells"]:
            f, m = key.split(" | ")
            rr = [r for r in rows if r["format"] == f and r["model_requested"] == m and r["scenario"] == sid]
            cols.append(f"{sum(r['model_valid_without_fallback'] for r in rr)}/{len(rr)}" if rr else "-")
        L.append(f"| {sid} | " + " | ".join(cols) + " |")
    L += ["", "## Caveats", "",
          "- 24 plans per cell is a small sample; read the spread and the Fisher p. The rule above, not a single table cell, decides.",
          "- Model-only valid is a property of this validator and these 12 mock scenarios; it is not a claim about real payments.",
          "- Token and latency figures include free-tier rate-limit waits and are not a clean performance measurement.", ""]
    return "\n".join(L)


def report(rows_path: Path | None = None) -> str:
    rows = load(rows_path)
    md = render(rows)
    MD.write_text(md, encoding="utf-8")
    SUMMARY.write_text(json.dumps(summarize(rows), indent=1, default=str), encoding="utf-8")
    return md


# ------------------------------------------------------------------------------------------------------------ run
def default_model() -> str:
    return os.environ.get("OASIS_PLANNER_MODEL") or config.AGENT_MODEL


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--report", action="store_true", help="offline: re-render the report from the saved rows (no network)")
    ap.add_argument("--format", choices=FORMATS, help="planner format to run")
    ap.add_argument("--model", default=None, help=f"planner model (default: $OASIS_PLANNER_MODEL, then $OASIS_AGENT_MODEL); e.g. {', '.join(MODELS)}")
    ap.add_argument("--repeats", type=int, default=DEFAULT_REPEATS, help="repeats of all 12 scenarios (default 2 = 24 plans per cell)")
    ap.add_argument("--rep", type=int, default=None, help="run only this 1-based repeat")
    ap.add_argument("--per-plan-cap", type=int, default=PER_PLAN_CAP, help="stop asking the model once one plan used this many tokens (same for both formats)")
    ap.add_argument("--cap", type=int, required=False, help="stop starting plans once this many NEW tokens were spent in this call")
    ap.add_argument("--only", help="comma-separated scenario ids")
    args = ap.parse_args(argv)
    if args.report:
        report()
        return 0
    if not args.format or not args.cap:
        ap.error("--format and --cap are required to run (use --report to render offline)")
    model = args.model or default_model()
    ids = [i for i in (args.only.split(",") if args.only else SCENARIO_IDS)]
    bad = [i for i in ids if i not in ALL_SCENARIOS]
    if bad:
        ap.error(f"unknown scenario(s): {bad}")
    if args.rep is not None and not 1 <= args.rep <= args.repeats:
        ap.error("--rep must be between 1 and --repeats")
    from oasis.agent.llm import GroqLLM
    from oasis.agent.planner import AgenticPlanner
    if not config.GROQ_API_KEY:
        raise SystemExit("GROQ_API_KEY is not set")
    rows = load()
    done = {row_key(r) for r in rows}
    spent = 0
    for rep in range(args.repeats):
        if args.rep is not None and rep != args.rep - 1:
            continue
        llm = GroqLLM(model=model, fallback_model=model, salt=f"v3eval{rep}", temperature=LIVE_TEMPERATURE)
        for sid in ids:
            if (args.format, model, rep, sid) in done:
                continue
            if args.cap - spent < args.per_plan_cap:
                print(f"cap reached ({spent:,} of {args.cap:,} tokens; a plan needs room for {args.per_plan_cap:,}); stopping", flush=True)
                report()
                return 2
            r = run_scenario(sid, AgenticPlanner(llm, token_cap=args.per_plan_cap, fmt=args.format))
            if is_budget_artifact(r):
                print(f"{args.format} rep{rep + 1} {sid}: discarded (API/quota error: {(r['fallback_reason'] or '')[:60]}); not recorded. "
                      "Re-run later; finished plans are kept.", flush=True)
                report()
                return 3
            r.update(format=args.format, model_requested=model, rep=rep, set="heldout" if sid in HELDOUT else "original",
                     run_date=time.strftime("%Y-%m-%d"), per_plan_cap=args.per_plan_cap)
            spent += r["tokens"]
            rows = load() + [r]
            save(rows)
            print(f"{args.format} {model} rep{rep + 1} {sid}: model_only_valid={r['model_valid_without_fallback']} valid={r['valid']} "
                  f"fallback={r['fell_back']} ({(r['fallback_reason'] or '')[:40]}) props={r['model_proposals']} calls={r['model_calls']} "
                  f"tokens={r['tokens']} s={r['seconds']} total={spent:,}", flush=True)
    report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
