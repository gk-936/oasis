"""Exploratory evaluation of LOCAL models (Ollama) as the planner: v4 constrained JSON and the v2 tool-calling format.

    python -m eval.planning_local --model qwen3.5:4b --format v4 --repeats 2     # one cell; resumable, rows saved plan by plan
    python -m eval.planning_local --model qwen3.5:4b --format v2 --repeats 2
    python -m eval.planning_local --report                                        # offline: re-render the report from saved rows

Nothing leaves the machine (loopback Ollama, local models only; "-cloud" models are refused by the adapter). One cell, hence
one model process, runs at a time. Rows are keyed (model, format, rep, scenario) in eval/reports/planning_local_rows.json;
finished keys are skipped on the next call. Before every plan the available RAM is read: below RECYCLE_RAM_MB the model is
unloaded and reloaded (the Ollama runner's memory grows during a run), and the run stops (exit 4) if RAM stays below MIN_FREE_RAM_MB. This is a SEPARATE, exploratory report; it is never mixed into the pre-registered v3-vs-v2 verdict.

Per plan (the validator, never a model, scores everything):
- model-only valid  : the model's own proposal passed within the revision budget, no deterministic fallback
- pass@1            : the FIRST proposal was valid
- generate-and-verify (v4 only): up to 3 independent first proposals at the same temperature (the run's first proposal plus two
  more with different seeds, drawn only when the first was invalid); the first one the validator accepts counts. This uses the
  validator as a filter, so it is reported apart and is not the model-only number.
"""
from __future__ import annotations
import argparse
import ctypes
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from eval.planning import PER_PLAN_CAP, REPORTS, run_scenario
from eval.planning_v3 import ARITHMETIC
from oasis import config
from oasis.planning.validator import required_obligations
from oasis.planning.scenarios import ALL_SCENARIOS, HELDOUT, SCENARIOS, build_scenario_world

ROWS = REPORTS / "planning_local_rows.json"
MD = REPORTS / "planning_local.md"
SUMMARY = REPORTS / "planning_local.json"
MODELS = ("qwen3.5:4b", "qwen2.5:3b", "phi4-mini")
FORMATS = ("v4", "v2")
SCENARIO_IDS = list(SCENARIOS) + list(HELDOUT)
TEMPERATURE = 0.3
MIN_FREE_RAM_MB = 1500
RECYCLE_RAM_MB = 2600           # below this the model is unloaded before the next plan
GV_SAMPLES = 3
BASELINE = "gpt-oss-120b v3: 14/24 (58%), Groq, model-only valid"


def free_ram_mb() -> float:
    class MS(ctypes.Structure):
        _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                    ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("tvv", ctypes.c_ulonglong), ("avv", ctypes.c_ulonglong),
                    ("ext", ctypes.c_ulonglong)]
    m = MS()
    m.l = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ap / 2**20


def load(path: Path | None = None) -> dict:
    path = path or ROWS
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"rows": [], "no_tools": []}


def save(data: dict, path: Path | None = None) -> None:
    path = path or ROWS
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"temperature": TEMPERATURE, "scenarios": SCENARIO_IDS, **data}, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, path)


def row_key(r: dict) -> tuple:
    return (r["model_requested"], r["format"], r["rep"], r["scenario"])


def fallback_class(reason: str | None) -> str:
    r = (reason or "").lower()
    if r.startswith("token cap"):
        return "token cap"
    if "never proposed" in r:
        return "never proposed"
    if r.startswith("no valid plan after"):
        return "no valid plan after proposals"
    if "ollamaunsupported" in r:
        return "no tool support"
    if "stopped without" in r:
        return "stopped without a plan"
    if r:
        return "Ollama error"
    return "-"


def is_infrastructure_failure(row: dict) -> bool:
    """Ollama down / model missing / timeouts say nothing about the model: never record them as results."""
    return fallback_class(row.get("fallback_reason")) == "Ollama error"


def ensure_ram(llm, wait_s: float = 600.0) -> float | None:
    """Host RAM guard, called before every plan. The Ollama runner's private memory grows about 0.5 GB per plan on this machine, so
    below RECYCLE_RAM_MB the model is unloaded (frees about 3-4 GB; the next call reloads it, about 15 s) and the call waits for RAM to
    recover. None = RAM stayed under MIN_FREE_RAM_MB for `wait_s` even without the model: the run must stop."""
    free = free_ram_mb()
    if free >= RECYCLE_RAM_MB:
        return free
    llm.unload()
    llm.recycles = getattr(llm, "recycles", 0) + 1
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(10)
        free = free_ram_mb()
        if free >= RECYCLE_RAM_MB or (free >= MIN_FREE_RAM_MB and time.time() - t0 > 30):
            return free
    return None


# ------------------------------------------------------------------------------------------------------ one plan
def run_plan(llm, planner, sid: str, fmt: str, seed: int) -> dict:
    n0 = len(llm.call_log)
    r = run_scenario(sid, planner)
    calls = llm.call_log[n0:]
    r["pass1"] = bool(r["model_valid_without_fallback"] and r["iterations_to_valid"] == 1)
    r["prompt_tokens"] = sum(c["prompt_tokens"] for c in calls)
    r["output_tokens"] = sum(c["output_tokens"] for c in calls)
    r["max_prompt_tokens"] = max((c["prompt_tokens"] for c in calls), default=0)
    r["truncated_calls"] = sum(c["truncated"] for c in calls)
    r["load_s"] = round(sum(c["load_s"] for c in calls), 2)
    r["gen_s"] = round(sum(c["eval_s"] for c in calls), 2)
    try:
        r["ps"] = llm.ps()
    except Exception:  # noqa: BLE001
        r["ps"] = []
    r["seed"] = seed
    w = build_scenario_world(sid)               # how much CNY the plan delivers beyond what was missing (a cost signal the validator does not score)
    net = max(0.0, sum(o.remaining for o in required_obligations(w.passport)) - w.passport.balance("CNY"))
    r["cny_missing"] = round(net, 2)
    r["overshoot_pct"] = round(100 * ((r.get("delivered_cny") or 0) - net) / net, 1) if net > 0 else None
    if fmt == "v4":                       # generate-and-verify: the run's first proposal is sample 1
        samples = [{"valid": r["pass1"], "seed": seed, "from_main_run": True}]
        if not r["pass1"]:
            for k in range(1, GV_SAMPLES):
                s = planner.sample(build_scenario_world(sid), ALL_SCENARIOS[sid].goal, seed + 1000 * k)
                samples.append({**s, "seed": seed + 1000 * k})
                if s["valid"]:
                    break
        r["gv_valid"] = any(s["valid"] for s in samples)
        r["gv_samples"] = len(samples)
        r["gv_tokens"] = sum(s.get("tokens", 0) for s in samples[1:])
        r["gv_seconds"] = round(sum(s.get("seconds", 0) for s in samples[1:]), 2)
        r["gv_error_counts"] = dict(sum((Counter(s.get("errors", {})) for s in samples[1:]), Counter()))
    return r


# ------------------------------------------------------------------------------------------------------ aggregation
def cell_stats(rows: list[dict]) -> dict:
    n = len(rows)
    fb = Counter(fallback_class(r.get("fallback_reason")) for r in rows if r["fell_back"])
    errs: Counter = Counter()
    for r in rows:
        errs.update(r.get("error_counts") or {})
    tot = sum(errs.values())
    held = [r for r in rows if r["scenario"] in HELDOUT]
    orig = [r for r in rows if r["scenario"] in SCENARIOS]
    it = [r["iterations_to_valid"] for r in rows if r.get("iterations_to_valid")]
    ok = lambda xs, key: sum(1 for r in xs if r.get(key))
    avg = lambda key, nd=0: round(sum(r.get(key, 0) for r in rows) / n, nd) if n else None
    gv = [r for r in rows if "gv_valid" in r]
    ps = [p for r in rows for p in r.get("ps", [])]
    return {"plans": n, "model_only_valid": ok(rows, "model_valid_without_fallback"), "pass1": ok(rows, "pass1"),
            "final_valid": ok(rows, "valid"), "fallbacks": sum(r["fell_back"] for r in rows), "fallback_reasons": dict(fb),
            "error_counts": dict(errs), "errors_total": tot, "arithmetic_errors": sum(errs.get(c, 0) for c in ARITHMETIC),
            "arithmetic_share": (sum(errs.get(c, 0) for c in ARITHMETIC) / tot) if tot else None,
            "mean_proposals_to_valid": round(sum(it) / len(it), 2) if it else None,
            "tokens_per_plan": avg("tokens"), "seconds_per_plan": avg("seconds", 1), "calls_per_plan": avg("model_calls", 2),
            "heldout": [ok(held, "model_valid_without_fallback"), len(held)], "original": [ok(orig, "model_valid_without_fallback"), len(orig)],
            "heldout_pass1": [ok(held, "pass1"), len(held)], "original_pass1": [ok(orig, "pass1"), len(orig)],
            "gv": [ok(gv, "gv_valid"), len(gv)] if gv else None,
            "gv_heldout": [ok([r for r in gv if r["scenario"] in HELDOUT], "gv_valid"), len([r for r in gv if r["scenario"] in HELDOUT])] if gv else None,
            "gv_extra_seconds": round(sum(r.get("gv_seconds", 0) for r in gv) / len(gv), 1) if gv else None,
            "gv_mean_samples": round(sum(r["gv_samples"] for r in gv) / len(gv), 2) if gv else None,
            "truncated_calls": sum(r.get("truncated_calls", 0) for r in rows), "max_prompt_tokens": max((r.get("max_prompt_tokens", 0) for r in rows), default=0),
            "gpu_pct": sorted({p["gpu_pct"] for p in ps if p.get("gpu_pct") is not None}),
            "per_repeat": [{"rep": k, "plans": sum(1 for r in rows if r["rep"] == k), "valid": sum(1 for r in rows if r["rep"] == k and r["model_valid_without_fallback"])}
                           for k in sorted({r["rep"] for r in rows})]}


def summarize(data: dict) -> dict:
    cells: dict[tuple, list[dict]] = {}
    for r in data["rows"]:
        cells.setdefault((r["model_requested"], r["format"]), []).append(r)
    return {"cells": {f"{m} | {f}": cell_stats(v) for (m, f), v in sorted(cells.items())}, "no_tools": data.get("no_tools", [])}


def _pct(a, b=None) -> str:
    if b is None:
        return "-" if a is None else f"{a * 100:.0f}%"
    return f"{a}/{b} ({a * 100 / b:.0f}%)" if b else "-"


def render(data: dict) -> str:
    s = summarize(data)
    fmt_name = {"v4": "v4, exploratory (constrained JSON)", "v2": "v2 (tool calling)"}
    L = ["# Local models (Ollama) as the planner: exploratory evaluation", "",
         "**Exploratory and separate.** Not part of the pre-registered v3-vs-v2 verdict (`eval/reports/planning_v3.md`). Local models only (nothing "
         f"leaves the machine), temperature {TEMPERATURE}, repeat-specific seeds, 12 scenarios (8 original + 4 held-out `heldout_*`) x 2 repeats. "
         "Scored by the deterministic validator. **Model-only valid** = the model's own proposal passed within its budget (v4: 1 + 3 revisions; "
         "v2: 4 proposals / 8 calls) and no deterministic fallback was used; **pass@1** = the first proposal was valid. **Generate-and-verify** "
         "(v4 only) = up to 3 independent first proposals, the first the validator accepts; it uses the validator as a filter and is NOT the model-only number. "
         f"Reference (Groq, other protocol): {BASELINE}.", ""]
    if not data["rows"]:
        return "\n".join(L + ["_No rows yet._", ""])
    L += ["## Cells", "", "| Model | Format | Plans | Model-only valid | pass@1 | Original / held-out model-only | Generate-and-verify (up to 3) | Final valid (incl. fallback) | Fallbacks (reasons) | Mean proposals to valid | Tokens / plan | Seconds / plan | GPU share |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for key, c in s["cells"].items():
        m, f = key.split(" | ")
        fb = ", ".join(f"{k} {v}" for k, v in sorted(c["fallback_reasons"].items())) or "-"
        gv = f"{_pct(*c['gv'])}; held-out {c['gv_heldout'][0]}/{c['gv_heldout'][1]}; +{c['gv_extra_seconds']} s/plan" if c["gv"] else "n/a"
        L.append(f"| {m} | {fmt_name[f]} | {c['plans']} | {_pct(c['model_only_valid'], c['plans'])} | {_pct(c['pass1'], c['plans'])} | "
                 f"{c['original'][0]}/{c['original'][1]} / {c['heldout'][0]}/{c['heldout'][1]} | {gv} | {c['final_valid']} of {c['plans']} | "
                 f"{c['fallbacks']}: {fb} | {c['mean_proposals_to_valid']} | {c['tokens_per_plan']:,} | {c['seconds_per_plan']} | "
                 f"{'/'.join(str(x) + '%' for x in c['gpu_pct']) or '?'} |")
    for m in s["no_tools"]:
        L.append(f"| {m} | {fmt_name['v2']} | 0 | no tool support (Ollama rejected `tools`) | | | | | | | | | |")
    L += ["", "Final valid counts the deterministic fallback plan, so it is high by construction. Seconds include model load on the first plan of a cell.", "",
          "## Validator errors by code (every proposal the model made; generate-and-verify extra samples excluded)", "",
          "| Model | Format | Errors | Arithmetic share | By code |", "|---|---|---|---|---|"]
    for key, c in s["cells"].items():
        m, f = key.split(" | ")
        L.append(f"| {m} | {f} | {c['errors_total']} | {_pct(c['arithmetic_share'])} ({c['arithmetic_errors']}) | {', '.join(f'{k} {v}' for k, v in sorted(c['error_counts'].items())) or '-'} |")
    L += ["", f"Arithmetic codes: {', '.join(f'`{c}`' for c in ARITHMETIC)}.", "", "## Per scenario (model-only valid across repeats)", "",
          "| Scenario | " + " | ".join(s["cells"]) + " |", "|---|" + "---|" * len(s["cells"])]
    for sid in SCENARIO_IDS:
        cols = []
        for key in s["cells"]:
            m, f = key.split(" | ")
            rr = [r for r in data["rows"] if r["model_requested"] == m and r["format"] == f and r["scenario"] == sid]
            cols.append(f"{sum(r['model_valid_without_fallback'] for r in rr)}/{len(rr)}" if rr else "-")
        L.append(f"| {sid} | " + " | ".join(cols) + " |")
    L += ["", "## Memory and context", ""]
    for key, c in s["cells"].items():
        L.append(f"- {key}: largest prompt {c['max_prompt_tokens']} tokens, calls whose prompt reached num_ctx (silent truncation risk): {c['truncated_calls']}; "
                 f"GPU share of the loaded model: {', '.join(str(x) + '%' for x in c['gpu_pct']) or 'unknown'}.")
    L += ["", "## Caveats", "", "- 24 plans per cell is a small sample; differences of a few plans are noise.",
          "- Model-only valid is a property of this validator and these 12 mock scenarios, not of real payments.",
          "- v4 shows the model the validator's `fix` hints on revisions and a route table; v2 does not. The formats differ in more than the output channel, so this is not a clean format comparison.", ""]
    return "\n".join(L)


def report(path: Path | None = None) -> str:
    data = load(path)
    md = render(data)
    MD.write_text(md, encoding="utf-8")
    SUMMARY.write_text(json.dumps(summarize(data), indent=1, default=str), encoding="utf-8")
    return md


# ------------------------------------------------------------------------------------------------------------ run
def main(argv=None) -> int:
    from oasis.agent.ollama_llm import OllamaLLM
    code = 1
    try:
        code = _main(argv)
        return code
    finally:                                # never leave a model loaded behind
        try:
            if "--report" not in (argv if argv is not None else sys.argv):
                OllamaLLM(model="x", use_cache=False).unload(_LAST_MODEL[0]) if _LAST_MODEL else None
        except Exception:  # noqa: BLE001
            pass


_LAST_MODEL: list[str] = []


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--model", choices=MODELS)
    ap.add_argument("--format", choices=FORMATS)
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--rep", type=int, default=None, help="only this 1-based repeat")
    ap.add_argument("--only", help="comma-separated scenario ids")
    ap.add_argument("--no-record", action="store_true", help="development: run and print, do not save rows")
    ap.add_argument("--max-minutes", type=float, default=None, help="stop starting plans after this many minutes (resume later)")
    args = ap.parse_args(argv)
    if args.report:
        report()
        return 0
    if not (args.model and args.format):
        ap.error("--model and --format are required")
    _LAST_MODEL[:] = [args.model]
    ids = args.only.split(",") if args.only else SCENARIO_IDS
    bad = [i for i in ids if i not in ALL_SCENARIOS]
    if bad:
        ap.error(f"unknown scenario(s): {bad}")
    from oasis.agent.ollama_llm import OllamaError, OllamaLLM
    from oasis.agent.planner import AgenticPlanner
    from oasis.agent.planner_v4 import ConstrainedPlanner
    data = load()
    if args.model in data.get("no_tools", []) and args.format == "v2":
        print(f"{args.model}: already recorded as 'no tool support'; nothing to run")
        return 0
    done = {row_key(r) for r in data["rows"]}
    t_start = time.time()
    probe = OllamaLLM(model=args.model, use_cache=False)
    try:
        probe.require_installed()
        for p in probe.ps():                                   # one model process at a time
            if p["name"] and not p["name"].startswith(args.model.split(":")[0] + ":") and p["name"] != args.model:
                print(f"unloading {p['name']} (one model at a time)")
                probe.unload(p["name"])
    except OllamaError as e:
        print(f"Ollama: {e}")
        return 3
    for rep in range(args.repeats):
        if args.rep is not None and rep != args.rep - 1:
            continue
        seed = 1000 * (rep + 1) + 17
        llm = OllamaLLM(model=args.model, temperature=TEMPERATURE, seed=seed, use_cache=False, keep_alive="10m", use_mmap=False)
        planner = ConstrainedPlanner(llm, token_cap=PER_PLAN_CAP, seed=seed) if args.format == "v4" else AgenticPlanner(llm, token_cap=PER_PLAN_CAP, fmt="v2")
        for sid in ids:
            if (args.model, args.format, rep, sid) in done:
                continue
            if args.max_minutes and (time.time() - t_start) / 60 > args.max_minutes:
                print("time budget for this call reached; stopping (resume by calling again)")
                report()
                return 2
            free = ensure_ram(llm)
            if free is None:
                print(f"free RAM stayed below {MIN_FREE_RAM_MB} MB even with the model unloaded: stopping (resume later)")
                report()
                return 4
            r = run_plan(llm, planner, sid, args.format, seed)
            if args.format == "v2" and fallback_class(r.get("fallback_reason")) == "no tool support":
                print(f"{args.model}: Ollama rejected tools -> recorded as no tool support")
                if not args.no_record:
                    data = load()
                    data.setdefault("no_tools", []).append(args.model)
                    save(data)
                    report()
                return 0
            if is_infrastructure_failure(r):
                print(f"{args.format} rep{rep + 1} {sid}: discarded (Ollama error: {(r['fallback_reason'] or '')[:100]}); not recorded")
                report()
                return 3
            r.update(format=args.format, model_requested=args.model, rep=rep, set="heldout" if sid in HELDOUT else "original",
                     run_date=time.strftime("%Y-%m-%d"), free_ram_mb=round(free))
            print(f"{args.model} {args.format} rep{rep + 1} {sid}: model_only_valid={r['model_valid_without_fallback']} pass1={r['pass1']} "
                  f"fallback={r['fell_back']} ({(r['fallback_reason'] or '')[:40]}) props={r['model_proposals']} errs={r['error_counts']} "
                  f"tokens={r['tokens']} s={r['seconds']} gv={r.get('gv_valid')} free_ram={free:.0f}MB", flush=True)
            if not args.no_record:
                data = load()
                data["rows"].append(r)
                save(data)
                done.add(row_key(r))
    probe.unload(args.model)
    if not args.no_record:
        report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
