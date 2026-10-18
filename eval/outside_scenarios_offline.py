"""Run an outside-written scenario file (e.g. Codex's scenarios.json) against /api/chat, offline. No model call, no network.

Run: PYTHONPATH=. python -m eval.outside_scenarios_offline <scenarios.json>
The expectations were written by the outside tester before any run; results are first-run and the file is not edited afterwards.
Writes eval/reports/outside_scenarios_offline.md.
"""
from __future__ import annotations
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

for k, v in {"OASIS_DB": ":memory:", "OASIS_LLM": "offline", "OASIS_EXTRACT": "deterministic", "OASIS_ANCHOR": "local",
             "OASIS_PASS_STUDENT": "student-demo", "OASIS_PASS_PARENT": "parent-demo", "OASIS_PASS_JUDGE": "judge-demo"}.items():
    os.environ[k] = v
os.environ.pop("OASIS_KEY_PASSPHRASE", None)

REPORT = Path(__file__).resolve().parent / "reports" / "outside_scenarios_offline.md"


STATUSES = {"refused", "rejected", "info", "held", "needs_info", "needs_confirmation", "done", "cancelled", "frozen", "paid", "needs_verification"}


def repair(sc: dict) -> dict | None:
    """Mechanical repair of one known malformation in the file: the expected status was written as a last 'turn' and the
    explanation was put in expect.final_status_in. Returns the repaired copy, or None if the scenario is not of that shape."""
    e = sc.get("expect", {})
    if isinstance(e.get("final_status_in"), str) and len(sc["turns"]) > 1 and sc["turns"][-1] in STATUSES:
        fixed = json.loads(json.dumps(sc))
        fixed["turns"], fixed["why"] = sc["turns"][:-1], e["final_status_in"]
        fixed["expect"]["final_status_in"] = [sc["turns"][-1]]
        return fixed
    return None


def run_one(sc: dict) -> dict:
    from fastapi.testclient import TestClient
    from oasis.api import main as api
    c = TestClient(api.app)
    c.post("/api/auth/login", json={"role": "student", "passcode": "student-demo"})
    c.post("/api/reset")
    e, moved, replies, statuses = sc["expect"], 0.0, [], []
    for t in sc["turns"]:
        j = c.post("/api/chat", json={"message": t}).json()
        moved += float(j.get("money_moved") or 0)
        replies.append(str(j.get("reply", "")))
        statuses.append(j.get("status"))
    problems = []
    if e.get("final_status_in") and statuses[-1] not in e["final_status_in"]:
        problems.append(f"status {statuses[-1]!r} not in {e['final_status_in']}")
    if moved > float(e.get("money_moved_max", 0)) + 1e-9:
        problems.append(f"moved {moved}")
    if e.get("must_not_pay", True) and "paid" in statuses:
        problems.append("a turn ended paid")
    low = " ".join(replies).lower()
    problems += [f"said {s!r}" for s in e.get("must_not_say", []) if s.lower() in low]
    if e.get("must_say_any") and not any(s.lower() in replies[-1].lower() for s in e["must_say_any"]):
        problems.append("none of must_say_any in last reply")
    lost = c.get("/api/state").json().get("ledger_money_lost", 0)
    if lost:
        problems.append(f"ledger_money_lost {lost}")
    return {"id": sc["id"], "category": sc["category"], "ok": not problems, "problems": problems, "statuses": statuses,
            "money_moved": moved, "unsafe": bool(lost) or moved > float(e.get("money_moved_max", 0)) + 1e-9}


def main(path: str) -> int:
    global REPORT
    if Path(path).stem != "outside_codex_scenarios":        # the first set keeps its report name; later sets get their own
        REPORT = REPORT.with_name(f"outside_{Path(path).stem}.md")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    scenarios, repaired = [], []
    for s in data["scenarios"]:
        r = repair(s) if "--raw" not in sys.argv else None
        scenarios.append(r or s)
        if r:
            repaired.append(s["id"])
    rows = [run_one(s) for s in scenarios]
    by = defaultdict(lambda: [0, 0])
    for r in rows:
        by[r["category"]][0] += r["ok"]
        by[r["category"]][1] += 1
    lines = [f"# Outside-written scenarios, offline (first run)", "",
             f"Written by: {data.get('written_by')} on {data.get('date')}. {len(rows)} scenarios; expectations fixed before the run; no model call.", "",
             (f"{len(repaired)} scenarios had the expected status written as a last turn and the explanation in final_status_in; they were mechanically repaired ({chr(44).join(repaired[:3])}...), the file itself is unchanged. " if repaired else ""), "", f"Passed {sum(r['ok'] for r in rows)} of {len(rows)}; scenarios where money moved beyond the allowance or the ledger lost money: {sum(r['unsafe'] for r in rows)}.", "",
             "| category | passed | total |", "|---|---|---|"] + [f"| {k} | {a} | {b} |" for k, (a, b) in sorted(by.items())]
    fails = [r for r in rows if not r["ok"]]
    lines += ["", "## Failures (as run, not edited)", ""] + [f"- `{r['id']}` ({r['category']}): {'; '.join(r['problems'])}" for r in fails]
    REPORT.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    print(chr(10).join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
