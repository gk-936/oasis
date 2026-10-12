"""FlightPath vs the naive baseline on seeded, simulated transfers. SIMULATION results, not real-rail data.

Run: PYTHONPATH=. python -m eval.flightpath_bench   (writes eval/reports/flightpath.{json,md})

Baseline = cheapest-on-paper route, no pre-checks, "submitted means done", retry when it looks late.
FlightPath = compare on recipient amount with a deduction margin, pre-check, reconcile, and never resend while unresolved."""
from __future__ import annotations
import json
import random
from datetime import date, timedelta
from pathlib import Path

from oasis.flightpath import core as fp
from oasis.mock.rates import ROUTES, MockRates, delivered_amount
from oasis.planning.routes import inr_needed

REPORTS = Path(__file__).parent / "reports"
TODAY = date(2026, 10, 12)


def make_scenarios(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        out.append({
            "id": f"s{i:03d}", "required_cny": rng.choice([8000, 15000, 22000, 35000]),
            "due_in": rng.choice([2, 3, 5, 8, 14]),
            "issue": rng.choices([None, "docs_missing", "details_mismatch"], [0.7, 0.2, 0.1])[0],   # preventable
            "slow": rng.random() < 0.2,           # arrives late but arrives
            "rejected": False, "deduct_frac": rng.random(),
        })
        if out[-1]["issue"] == "details_mismatch" or (out[-1]["issue"] == "docs_missing" and rng.random() < 0.6):
            out[-1]["rejected"] = True            # unfixed preventable issues really do fail
    return out


def _truth(s: dict, route) -> dict:
    exp, worst = fp.DEDUCTIONS[route.id]
    return {"deduct": round(worst * s["deduct_frac"], 2), "days": route.days + (3 if s["slow"] else 0)}


def run(n: int = 400, seed: int = 11) -> dict:
    rates, mid = MockRates(), MockRates().mid(0)
    sc = make_scenarios(n, seed)
    b = dict(short=0, dup=0, caught=0, errs=[])
    f = dict(short=0, dup=0, caught=0, short_detected=0, flagged_issue=0, false_alarm=0, legit=0, errs=[])
    n_short_sim = n_issue = n_slow = n_legit = 0
    for s in sc:
        due = TODAY + timedelta(days=s["due_in"])
        # ---------------- baseline
        route = min(ROUTES, key=lambda r: inr_needed(rates, r, s["required_cny"]))
        send = inr_needed(rates, route, s["required_cny"])
        t = _truth(s, route)
        got = delivered_amount(send, route, mid) - t["deduct"]
        if got < s["required_cny"] - fp.SHORT_TOLERANCE_CNY:
            b["short"] += 1
        if s["slow"] and not s["rejected"]:
            b["dup"] += 1                          # retried a payment that was only slow
        b["errs"].append(abs(delivered_amount(send, route, mid) - got))
        # ---------------- FlightPath
        opts = fp.compare_routes(rates, s["required_cny"], TODAY, due)
        o = opts[0]
        t = _truth(s, o.route)
        warns = fp.precheck(payee_verified=True, details_match=s["issue"] != "details_mismatch",
                            docs_complete=s["issue"] != "docs_missing", route=o.route, today=TODAY, due=due)
        issue_flag = any(w.code in ("details_mismatch", "docs_missing") for w in warns)
        got_f = delivered_amount(o.send_inr, o.route, mid) - t["deduct"]
        j = fp.Journey(s["id"], o.route.id, o.send_inr, s["required_cny"])
        fp.advance(j, "checks_complete", 0); fp.advance(j, "submitted", 0); fp.advance(j, "processing", 1)
        late = t["days"] > o.route.days + fp.GRACE_DAYS
        check_day = o.route.days + fp.GRACE_DAYS + 1
        finding = fp.reconcile(j, check_day) if late else None
        if late and finding.code == "delayed":
            adv = fp.advise(j, finding)
            f["dup"] += 1 if adv.resend_allowed else 0       # must stay zero
        if s["rejected"]:
            fp.advance(j, "rejected", 2)
        else:
            fp.advance(j, "credited", t["days"], credited_cny=round(got_f, 2))
            fin = fp.reconcile(j, t["days"])
            if fin.code == "shortfall":
                f["short"] += 1
        f["errs"].append(abs(o.recipient_expected_cny - got_f))
        # tallies
        if s["issue"]:
            n_issue += 1
            f["flagged_issue"] += issue_flag
        else:
            n_legit += 1
            if any(w.severity == "block" for w in warns):
                f["false_alarm"] += 1
        n_slow += s["slow"] and not s["rejected"]
        if delivered_amount(send, route, mid) - _truth(s, route)["deduct"] < s["required_cny"] - fp.SHORT_TOLERANCE_CNY:
            n_short_sim += 1
    mae = lambda e: round(sum(e) / len(e), 2)
    res = {
        "n": n, "seed": seed, "label": "SIMULATION (mock rails)",
        "baseline": {"recipient_short_rate": round(b["short"] / n, 3), "duplicate_payments": b["dup"],
                     "preventable_issues_flagged": "0/%d" % n_issue, "recipient_amount_mae_cny": mae(b["errs"])},
        "flightpath": {"recipient_short_rate": round(f["short"] / n, 3), "duplicate_payments": f["dup"],
                       "preventable_issues_flagged": f"{f['flagged_issue']}/{n_issue}",
                       "recipient_amount_mae_cny": mae(f["errs"]),
                       "false_alarm_rate": round(f["false_alarm"] / max(1, n_legit), 3)},
        "slow_but_fine_transfers": int(n_slow), "baseline_would_short_credit": n_short_sim,
    }
    return res


def to_markdown(r: dict) -> str:
    b, f = r["baseline"], r["flightpath"]
    rows = [("Recipient short-credited", b["recipient_short_rate"], f["recipient_short_rate"]),
            ("Duplicate payments", b["duplicate_payments"], f["duplicate_payments"]),
            ("Preventable issues flagged", b["preventable_issues_flagged"], f["preventable_issues_flagged"]),
            ("Recipient-amount error (CNY, MAE)", b["recipient_amount_mae_cny"], f["recipient_amount_mae_cny"])]
    t = "\n".join(f"| {a} | {x} | {y} |" for a, x, y in rows)
    return (f"# FlightPath benchmark ({r['label']})\n\n{r['n']} seeded transfers, seed {r['seed']}. Not validated against real rails.\n\n"
            f"| Metric | Baseline | FlightPath |\n|---|---|---|\n{t}\n\nFalse-alarm rate on legitimate transfers: {f['false_alarm_rate']}.\n"
            f"Slow-but-successful transfers (a retry would duplicate): {r['slow_but_fine_transfers']}.\n")


def main() -> None:
    r = run()
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "flightpath.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
    (REPORTS / "flightpath.md").write_text(to_markdown(r), encoding="utf-8")
    print(to_markdown(r))


if __name__ == "__main__":
    main()
