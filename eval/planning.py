"""Plan-quality evaluation (spec step 2, "agentic planning"): eight planning scenarios scored by the deterministic validator.

    python -m eval.planning                       # offline: the deterministic planner, no network
    python -m eval.planning --llm groq            # live: Groq native tool calling, capped by --token-cap (default 60,000)

The validator, not a model, scores every plan. Per scenario: was the final plan valid, how many proposals did it take,
did the live model fall back to the deterministic plan, how many obligations were paid by their deadline, and what the
conversions cost against the same INR through a typical bank route. Results go to eval/reports/planning.json and
planning.md (offline and live sections are kept side by side). The API key is never printed or written.
"""
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path

from oasis import config
from oasis.agent.planner import AgenticPlanner, DeterministicPlanner, build_record
from oasis.planning.scenarios import SCENARIOS, build_scenario_world

REPORTS = Path(__file__).resolve().parent / "reports"
DEFAULT_TOKEN_CAP = 60_000
PER_PLAN_CAP = 22_000   # 4 proposals x ~2.5k tokens of tool results + 8 calls re-sending a growing context; 14-18k cut off 4 of 8 plans mid-revision


def run_scenario(sid: str, planner) -> dict:
    s = SCENARIOS[sid]
    w = build_scenario_world(sid)
    t0 = time.time()
    rec = build_record(w, planner.plan(w, s.goal), s.goal)
    v = rec["validation"]
    m = v.get("metrics") or {}
    props = [t for t in rec["trace"] if t["type"] == "proposal"]
    first_valid = next((t["iteration"] for t in props if t["validation"]["valid"]), None)
    model_props = [t for t in props]       # in a fallback the live model's proposals come first in the trace
    return {
        "scenario": sid, "title": s.title, "tests": s.tests, "planner": rec["planner"], "model": rec["model"],
        "valid": rec["valid"], "fell_back": rec["fell_back"], "fallback_reason": rec["fallback_reason"],
        "iterations": rec["iterations"], "iterations_to_valid": first_valid if not rec["fell_back"] else None,
        "model_valid_without_fallback": bool(rec["valid"] and not rec["fell_back"]),
        "deadlines_met": m.get("deadlines_met", 0), "obligations": m.get("obligations", 0),
        "conversions": m.get("conversions", 0), "send_inr": m.get("total_send_inr", 0), "delivered_cny": m.get("delivered_cny", 0),
        "fees_cny": m.get("fees_cny"), "bank_fees_cny": m.get("bank_fees_cny"), "saved_vs_bank_cny": m.get("saved_vs_bank_cny"),
        "tcs_inr": m.get("tcs_inr", 0), "warnings": sorted({x["code"] for x in v.get("warnings", [])} - {"approval_expected"}),
        "first_errors": sorted({e["code"] for e in (props[0]["validation"]["errors"] if props else [])}),
        "proposals": len(model_props), "tokens": rec["tokens"], "model_calls": rec["model_calls"],
        "seconds": round(time.time() - t0, 2), "steps": rec["steps"], "rationale": rec["rationale"][:500],
    }


def summarize(rows: list[dict]) -> dict:
    ran = [r for r in rows if not r.get("skipped")]
    n = len(ran) or 1
    ok = [r for r in ran if r["valid"]]
    iters = [r["iterations_to_valid"] for r in ran if r["iterations_to_valid"]]
    fees, bank = sum(r["fees_cny"] or 0 for r in ok), sum(r["bank_fees_cny"] or 0 for r in ok)
    return {"scenarios_run": len(ran), "valid_plan_rate": round(len(ok) / n, 3), "valid_without_fallback": sum(r["model_valid_without_fallback"] for r in ran),
            "fallbacks": sum(r["fell_back"] for r in ran),
            "mean_iterations_to_valid": round(sum(iters) / len(iters), 2) if iters else None,
            "max_iterations_to_valid": max(iters) if iters else None,
            "deadlines_met": sum(r["deadlines_met"] for r in ran), "deadlines_total": sum(r["obligations"] for r in ran),
            "fees_cny": round(fees, 2), "bank_fees_cny": round(bank, 2),
            "fee_reduction_vs_bank_pct": round((1 - fees / bank) * 100, 1) if bank else None,
            "tokens": sum(r["tokens"] for r in ran), "model_calls": sum(r["model_calls"] for r in ran)}


def render_repeats(d: dict, title: str) -> list[str]:
    ran = [r for r in d["results"] if not r.get("skipped")]
    sp = d.get("spread")
    L = [f"## {title}", "", f"Planner: `{d['planner']}`; model `{d['model']}`, fallback `{d.get('fallback_model')}`; run {d['date']}; "
         f"{d['repeats']} repeat(s) at temperature {d['temperature']} with a repeat-specific cache salt (`planrep<N>`), so every repeat is a distinct "
         f"sample; per-plan token cap {d['per_plan_cap']:,}. Repeats completed in full: {len(d.get('complete_repeats', []))} of {d['repeats']}.", ""]
    L += ["| Repeat | Plans run | Valid without fallback | Final plan valid | Mean proposals to valid | Tokens |", "|---|---|---|---|---|---|"]
    for k, s in enumerate(d["per_repeat"]):
        L.append(f"| {k + 1} | {s['scenarios_run']} of {len(SCENARIOS)} | {s['valid_without_fallback']} | {s['valid_plan_rate']*100:.0f}% | "
                 f"{s['mean_iterations_to_valid'] or '-'} | {s['tokens']:,} |")
    if sp:
        v = sp["valid_without_fallback"]
        L += ["", f"Valid without fallback across completed repeats (min / mean / max): {v['min']} / {v['mean']} / {v['max']} of {len(SCENARIOS)} scenarios.", ""]
    else:
        L += ["", "Fewer than two repeats completed in full, so no min/mean/max across repeats is reported.", ""]
    tot = sum(r["valid"] and not r["fell_back"] for r in ran)
    L += [f"Pooled over every plan run: {tot} of {len(ran)} valid without fallback ({(tot / len(ran) * 100 if ran else 0):.0f}%); "
          f"tokens {sum(r['tokens'] for r in ran):,}.", ""]
    L += ["| Scenario | Valid without fallback | Proposals to valid (per repeat; fb = fell back) | Tokens (per repeat) | First validator errors (per repeat) |", "|---|---|---|---|---|"]
    for sid in SCENARIOS:
        rs = sorted((r for r in ran if r["scenario"] == sid), key=lambda r: r["rep"])
        if not rs:
            L.append(f"| {SCENARIOS[sid].title} | not run | | | |")
            continue
        ok = sum(r["valid"] and not r["fell_back"] for r in rs)
        L.append(f"| {SCENARIOS[sid].title} | {ok} of {len(rs)} | {', '.join(str(r['iterations_to_valid'] or ('fb' if r['fell_back'] else '-')) for r in rs)} | "
                 f"{', '.join(format(r['tokens'], ',') for r in rs)} | {'; '.join(','.join(r['first_errors']) or '-' for r in rs)} |")
    skipped = [r for r in d["results"] if r.get("skipped")]
    if skipped:
        L += ["", f"Not run (token budget): {len(skipped)} plan(s): " + ", ".join(f"{r['title']} (repeat {r['rep'] + 1})" for r in skipped) + "."]
    L.append("")
    for note in d.get("notes", []):
        L.append(f"- {note}")
    L.append("")
    return L


def render(data: dict) -> str:
    L = ["# Plan-quality evaluation (agentic planning)", "",
         "Eight planning scenarios on MOCK data (`oasis/planning/scenarios.py`), scored by the deterministic plan validator "
         "(`oasis/planning/validator.py`), never by a model. A plan is *valid* when every obligation is funded and paid in its exact amount, "
         "to its own payee, on or before its due date; CNY arrives before it is spent; the student's INR never goes negative; the SAFE quota "
         "is respected per calendar year; the LRS limit holds; and INR needed by pending rate targets stays unconverted. "
         "TCS and LRS findings are surfaced as warnings. Fees are measured against the same INR sent through the typical bank route. "
         "Rates are quoted at today's mock rate; nothing is predicted.", ""]
    for key, title in (("offline", "Offline (deterministic planner, no network)"),
                       ("live", "Live (Groq native tool calling), after the planner prompt change"),
                       ("live_before", "Live, before planner prompt change (2026-10-10, 1 run)")):
        d = data.get(key)
        if not d:
            L += [f"## {title}", "", "_Not run._", ""]
            continue
        if d.get("repeats"):
            L += render_repeats(d, title)
            continue
        s = d["summary"]
        L += [f"## {title}", "", f"Planner: `{d['planner']}`" + (f"; model `{d['model']}`, fallback `{d.get('fallback_model')}`" if d.get("model") else "")
              + f"; run {d['date']}.", ""]
        L += ["| Metric | Result |", "|---|---|",
              f"| Scenarios run | {s['scenarios_run']} of {len(SCENARIOS)} |", f"| Valid-plan rate (final plan) | {s['valid_plan_rate']*100:.0f}% |",
              f"| Valid without fallback | {s['valid_without_fallback']} of {s['scenarios_run']} |", f"| Fallbacks to the deterministic plan | {s['fallbacks']} |",
              f"| Proposals to first valid plan (mean / max) | {s['mean_iterations_to_valid']} / {s['max_iterations_to_valid']} |",
              f"| Deadlines met | {s['deadlines_met']} of {s['deadlines_total']} |",
              f"| Conversion fees vs typical bank | CNY {s['fees_cny']:,.0f} vs CNY {s['bank_fees_cny']:,.0f} ({s['fee_reduction_vs_bank_pct']}% lower) |",
              f"| Tokens / model calls | {s['tokens']:,} / {s['model_calls']} |", ""]
        L += ["| Scenario | Valid | Proposals to valid | Fallback | Deadlines | Fees (CNY) vs bank | TCS (INR) | First validator errors | Warnings |", "|---|---|---|---|---|---|---|---|---|"]
        for r in d["results"]:
            if r.get("skipped"):
                L.append(f"| {r['title']} | not run ({r['skipped']}) | | | | | | | |")
                continue
            L.append(f"| {r['title']}{(' (' + r['run_date'] + ', per-plan cap ' + format(r['per_plan_cap'], ',') + ')') if r.get('per_plan_cap') else ''} | {'yes' if r['valid'] else 'NO'} | {r['iterations_to_valid'] or '-'} | {'yes: ' + (r['fallback_reason'] or '')[:60] if r['fell_back'] else 'no'} | "
                     f"{r['deadlines_met']}/{r['obligations']} | {r['fees_cny']:,.0f} vs {r['bank_fees_cny']:,.0f} | {r['tcs_inr']:,.0f} | "
                     f"{', '.join(r['first_errors']) or '-'} | {', '.join(r['warnings']) or '-'} |")
        L.append("")
        for note in d.get("notes", []):
            L.append(f"- {note}")
        L.append("")
    L += ["## Caveats", "",
          "- Eight hand-written scenarios; a pass here shows the planner and validator agree on these cases, not general optimality.",
          "- The validator checks feasibility and the stated rules; it does not search for the globally cheapest plan. 'Fees vs bank' compares with the typical bank route only.",
          "- Corridor figures (SAFE quota, LRS, TCS) are researched, not officially confirmed; the SAFE quota is modelled as USD 50,000 equivalent per calendar year at a mock USD/INR of 88.",
          "- Offline results are deterministic. A live result is a small number of samples from one model (see the repeat counts above), cached on disk; it is not a robustness claim.", ""]
    return "\n".join(L)


def extra_notes(rows: list[dict], ids: list[str]) -> list[str]:
    """Plain-language caveats derived from the rows, so a reader does not mistake a budget stop for a model failure."""
    out = []
    capped = [r["title"] for r in rows if r.get("fell_back") and "token cap" in (r.get("fallback_reason") or "")]
    if capped:
        out.append(f"{len(capped)} fallback(s) ({'; '.join(capped)}) were triggered by the per-plan token cap protecting the free-tier budget, "
                   f"not by a model that gave up: those plans were still being revised. The reported plan is then the deterministic one.")
    missing = [SCENARIOS[i].title for i in SCENARIOS if i not in [r["scenario"] for r in rows if not r.get("skipped")]]
    if missing:
        out.append(f"Not run live (token budget): {', '.join(missing)}.")
    return out


LIVE_TEMPERATURE = 0.3      # repeats are distinct samples: temperature > 0 AND a repeat-specific cache salt (planrep<N>)


def spread_of(per_rep: list[dict]) -> dict:
    out = {}
    for k in ("valid_without_fallback", "valid_plan_rate", "tokens", "mean_iterations_to_valid"):
        vals = [x[k] for x in per_rep if x.get(k) is not None]
        out[k] = {"min": min(vals), "mean": round(sum(vals) / len(vals), 2), "max": max(vals)} if vals else None
    return out


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", default="offline", choices=("offline", "groq"))
    ap.add_argument("--repeats", type=int, default=1, help="live only: N independent samples per scenario (temperature "
                    f"{LIVE_TEMPERATURE}, cache salt planrep<N>, so repeats are distinct and never cache hits of each other)")
    ap.add_argument("--token-cap", type=int, default=DEFAULT_TOKEN_CAP, help="stop starting new live plans once this many NEW tokens were spent")
    ap.add_argument("--per-plan-cap", type=int, default=PER_PLAN_CAP, help="stop asking the model once one plan has used this many tokens")
    ap.add_argument("--only", help="comma-separated scenario ids")
    ap.add_argument("--ledger-baseline", type=int, default=None,
                    help="Groq tokens already used today BEFORE the planning work (cache replays count as 0 new tokens, so the total is taken from the ledger)")
    args = ap.parse_args(argv)
    ids = [i for i in (args.only.split(",") if args.only else SCENARIOS)]
    REPORTS.mkdir(exist_ok=True)
    jf = REPORTS / "planning.json"
    data = json.loads(jf.read_text(encoding="utf-8")) if jf.exists() else {}
    notes: list[str] = []
    today = time.strftime("%Y-%m-%d")
    if args.llm == "groq":
        from oasis.agent.llm import GroqLLM, UsageLedger
        if not config.GROQ_API_KEY:
            raise SystemExit("GROQ_API_KEY is not set")
        prev = data.get("live") or {}
        if prev and not prev.get("repeats"):            # the pre-change single run is kept as its own section
            data["live_before"] = data.pop("live")
            prev = {}
        old_rows = {(r["rep"], r["scenario"]): r for r in prev.get("results", []) if not r.get("skipped")}
        rows: list[dict] = []
        spent = 0

        def flush() -> None:      # keep every finished plan on disk so an interrupted run loses nothing
            allrows = {k: v for k, v in old_rows.items()}
            allrows.update({(r["rep"], r["scenario"]): r for r in rows if not r.get("skipped")})
            merged = sorted(allrows.values(), key=lambda r: (r["rep"], list(SCENARIOS).index(r["scenario"])))
            reps_n = max(args.repeats, prev.get("repeats", 0))
            per = [summarize([r for r in merged if r["rep"] == k]) for k in range(reps_n)]
            comp = [k for k in range(reps_n) if len([r for r in merged if r["rep"] == k]) == len(SCENARIOS)]
            data["live"] = {"date": today, "planner": "groq-tools", "model": llm0.model, "fallback_model": config.FALLBACK_MODEL,
                            "repeats": reps_n, "temperature": LIVE_TEMPERATURE, "per_plan_cap": args.per_plan_cap,
                            "complete_repeats": comp, "summary": summarize(merged), "per_repeat": per,
                            "spread": spread_of([per[k] for k in comp]) if len(comp) > 1 else None,
                            "results": merged, "notes": [n for n in prev.get("notes", []) if n.startswith(("Invocation", "Total Groq"))] + notes + extra_notes(merged, list(SCENARIOS))}
            jf.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")

        llm0 = GroqLLM(salt="planrep0", temperature=LIVE_TEMPERATURE)
        spent0 = llm0.usage.day()["tokens"]
        keys0 = {k: dict(v) for k, v in llm0.usage.day().get("keys", {}).items()}
        calls = hits = fbs = rots = 0
        for rep in range(args.repeats):
            llm = GroqLLM(salt=f"planrep{rep}", temperature=LIVE_TEMPERATURE)
            for sid in ids:
                if spent >= args.token_cap:
                    if (rep, sid) in old_rows:
                        rows.append(old_rows[(rep, sid)])
                    else:
                        rows.append({"scenario": sid, "rep": rep, "title": SCENARIOS[sid].title, "skipped": f"token cap {args.token_cap:,} reached"})
                    continue
                cap = min(args.per_plan_cap, args.token_cap - spent)
                r = run_scenario(sid, AgenticPlanner(llm, token_cap=cap))
                r["rep"], r["run_date"], r["per_plan_cap"] = rep, today, cap
                if r["tokens"] == 0 and (rep, sid) in old_rows:      # pure cache replay of a finished plan: keep its recorded cost
                    r = old_rows[(rep, sid)]
                else:
                    spent += r["tokens"]
                rows.append(r)
                flush()
                print(f"rep{rep} {sid}: valid={r['valid']} fallback={r['fell_back']} proposals={r['proposals']} tokens={r['tokens']} (total {spent:,})", flush=True)
            calls, hits, fbs, rots = calls + llm.calls, hits + llm.cache_hits, fbs + llm.fallbacks, rots + llm.key_rotations
        notes.append(f"Invocation {today}: new tokens {spent:,} (cap {args.token_cap:,}); Groq daily ledger before {spent0:,}, "
                     f"after {UsageLedger(llm0.usage.path).day()['tokens']:,}. Live calls {calls}, cache hits {hits}, model fallbacks {fbs}.")
        fresh = UsageLedger(llm0.usage.path)      # other GroqLLM instances (one per repeat) wrote the file; re-read it
        keys1 = fresh.day().get("keys", {})
        per_key = {k: keys1[k]["tokens"] - keys0.get(k, {}).get("tokens", 0) for k in keys1}
        if len(llm0.fingerprints) > 1 or per_key:
            notes.append(f"Per-key tokens this invocation ({len(llm0.fingerprints)} key(s), by sha256 fingerprint): "
                         + ", ".join(f"{k}: {v:,}" for k, v in sorted(per_key.items())) + f"; key rotations {rots}.")
        if args.ledger_baseline is not None:
            notes.append(f"Total Groq tokens spent on live planning in this session: {UsageLedger(llm0.usage.path).day()['tokens'] - args.ledger_baseline:,}.")
        flush()
    else:
        planner = DeterministicPlanner()
        rows = [run_scenario(sid, planner) for sid in ids]
        notes.append("The deterministic planner drafts a student-funded plan first and asks the family only when the validator reports a shortfall; "
                     "that is why scenarios with a shortfall need two proposals.")
        for r in rows:
            r.setdefault("run_date", today)
        data["offline"] = {"date": today, "planner": "deterministic", "model": None, "fallback_model": None,
                           "summary": summarize(rows), "results": rows, "notes": notes}
    jf.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    (REPORTS / "planning.md").write_text(render(data), encoding="utf-8")
    print(json.dumps(data["live" if args.llm == "groq" else "offline"]["summary"], indent=1))
    return data


if __name__ == "__main__":
    main()
