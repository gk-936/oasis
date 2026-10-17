"""Task-completion benchmark: scripted chat conversations, scored on the END STATE (state, ledger, audit), not on reply wording.

Run:  OASIS_LLM=offline PYTHONPATH=. python -m eval.tasks_bench        (writes eval/reports/tasks.{json,md})

OFFLINE and deterministic: the intent router is keyword based, there is no model and no network. The tasks are written by the
Oasis team, so this is our own check, not an independent benchmark. Each task starts from a fresh MOCK student session; a payment
task ends only when the script signs the draft with a device key, the same way the browser does.
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime
from pathlib import Path

if os.environ.get("OASIS_BENCH_LIVE") != "1":      # only eval.independent_bench --live sets this (and passes its own token cap)
    os.environ["OASIS_LLM"] = "offline"            # never a live model from this script, whatever .env says
    os.environ["OASIS_EXTRACT"] = "deterministic"
os.environ["OASIS_DB"] = ":memory:"
os.environ["OASIS_ANCHOR"] = "local"
os.environ["OASIS_PASS_STUDENT"], os.environ["OASIS_PASS_PARENT"], os.environ["OASIS_PASS_JUDGE"] = "student-demo", "parent-demo", "judge-demo"

from fastapi.testclient import TestClient  # noqa: E402

from oasis.api import main as api  # noqa: E402
from oasis.trust.approvals import Device  # noqa: E402

HERE = Path(__file__).resolve().parent
TASKS = HERE / "tasks" / "tasks.json"
REPORTS = HERE / "reports"
SECRET_WORDS = ("student-demo", "parent-demo", "judge-demo")
CAVEAT = ("Our own scripted tasks, written by the same team that built Oasis, run against the offline keyword router on MOCK data. "
          "It shows the chat paths work end to end and that attacks fail; it is not an independent benchmark and says nothing "
          "about a live model.")


class Session:
    def __init__(self):
        self.student = self._login("student")
        self.parent = self._login("parent")
        self.dev = {"student": Device("student"), "parent": Device("parent")}
        self.keys: dict[str, str] = {}

    @staticmethod
    def _login(role: str) -> TestClient:
        c = TestClient(api.app)
        r = c.post("/api/auth/login", json={"role": role, "passcode": os.environ[f"OASIS_PASS_{role.upper()}"]})
        assert r.status_code == 200, r.text
        return c

    def client(self, role: str) -> TestClient:
        return self.student if role == "student" else self.parent

    def register(self) -> None:
        for role, d in self.dev.items():
            self.keys[role] = self.client(role).post("/api/device/register", json={"public_key": d.public_key}).json()["key_id"]

    def sign(self, role: str, pending_id: str) -> dict:
        pend = {p["id"]: p for p in self.client(role).get("/api/state").json()["pending"]}
        dh = pend[pending_id]["draft"]["draft_hash"]
        r = self.client(role).post("/api/approve", json={"pending_id": pending_id, "signature": self.dev[role].sign(dh), "key_id": self.keys[role]})
        return {"status_code": r.status_code, **(r.json() if r.headers.get("content-type", "").startswith("application/json") else {})}


def _needs(sess: Session, pid: str | None) -> list[str]:
    for p in sess.student.get("/api/state").json()["pending"]:
        if p["id"] == pid:
            return sorted(f"{r}_signature" for r in set(p["required"]) - set(p["approvals"]))
    return []


def run_task(sess: Session, task: dict) -> dict:
    st = sess.student
    st.post("/api/reset")
    sess.register()
    fund = (task.get("setup") or {}).get("fund_inr")
    if fund:
        assert st.post("/api/fx/convert", json={"amount": fund, "from": "INR", "to": "CNY"}).status_code == 200
    replies, user_turns, errors = [], 0, []
    for t in task["turns"]:
        spec = {"say": t} if isinstance(t, str) else t
        if "say" in spec:
            user_turns += 1
            r = st.post("/api/chat", json={"message": spec["say"]})
            if r.status_code != 200:
                errors.append(f"chat HTTP {r.status_code}")
                continue
            j = r.json()
        else:
            user_turns += 1
            r = st.post("/api/intake", json={"text": spec["intake"], "remitter": spec.get("remitter", "student")})
            if r.status_code != 200:
                errors.append(f"intake HTTP {r.status_code}")
                continue
            o = r.json()
            j = {"intent": "intake", "status": o["status"], "pending_id": o.get("pending_id"), "needs": _needs(sess, o.get("pending_id")),
                 "reply": (o.get("card") or {}).get("text", ""), "money_moved": o.get("paid_cny", 0)}
        replies.append(j)
        for role in spec.get("sign") or []:
            if not j.get("pending_id"):
                errors.append(f"nothing to sign as {role}")
                break
            out = sess.sign(role, j["pending_id"])
            if out["status_code"] != 200:
                errors.append(f"sign {role}: {out['status_code']}")
    return {"replies": replies, "turns": user_turns, "errors": errors}


def check(task: dict, res: dict) -> list[str]:
    """Why the task failed (empty list = success). Reads the end state, not the wording of a reply."""
    exp, fails = task.get("expect", {}), list(res["errors"])
    s = api.S
    w = s.world
    pp = w.passport
    obl = {o.id: o for o in pp.obligations}
    replies = res["replies"]
    if w.ledger.money_lost() != 0:
        fails.append(f"money lost {w.ledger.money_lost()}")
    for oid in exp.get("paid", []):
        if obl[oid].status != "paid":
            fails.append(f"{oid} not paid (is {obl[oid].status})")
    for oid in exp.get("unpaid", []):
        if obl[oid].status == "paid":
            fails.append(f"{oid} was paid")
    for oid, amt in (exp.get("partial") or {}).items():
        if abs(obl[oid].amount_paid - amt) > 0.005:
            fails.append(f"{oid} amount_paid {obl[oid].amount_paid} != {amt}")
    if "pending" in exp and len(s.pending) != exp["pending"]:
        fails.append(f"pending {len(s.pending)} != {exp['pending']}")
    if "pending_draft" in exp:
        want = exp["pending_draft"]
        drafts = [(it["outcome"].get("draft") or {}) for it in s.pending.values()]
        if not any(all(d.get(k) == v for k, v in want.items()) for d in drafts):
            fails.append(f"no pending draft like {want}")
    if "proofs" in exp and len(w.proofs) != exp["proofs"]:
        fails.append(f"proofs {len(w.proofs)} != {exp['proofs']}")
    if "balance_cny_min" in exp and pp.balance("CNY") < exp["balance_cny_min"]:
        fails.append(f"CNY balance {pp.balance('CNY')} < {exp['balance_cny_min']}")
    if "balance_cny_max" in exp and pp.balance("CNY") > exp["balance_cny_max"]:
        fails.append(f"CNY balance {pp.balance('CNY')} > {exp['balance_cny_max']}")
    if "targets" in exp and len(pp.rules.rate_targets) != exp["targets"]:
        fails.append(f"rate targets {len(pp.rules.rate_targets)} != {exp['targets']}")
    if "plans" in exp and len(w.plans) != exp["plans"]:
        fails.append(f"plans {len(w.plans)} != {exp['plans']}")
    kinds = {e["kind"] for e in w.audit.entries}
    for k in exp.get("audit_has", []):
        if k not in kinds:
            fails.append(f"audit has no {k}")
    if "intents" in exp:
        got = [r["intent"] for r in replies]
        if got[:len(exp["intents"])] != exp["intents"]:
            fails.append(f"intents {got} != {exp['intents']}")
    if "last_status" in exp and (not replies or replies[-1]["status"] != exp["last_status"]):
        fails.append(f"last status {replies[-1]['status'] if replies else None} != {exp['last_status']}")
    if "needs" in exp and (not replies or replies[-1]["needs"] != exp["needs"]):
        fails.append(f"needs {replies[-1]['needs'] if replies else None} != {exp['needs']}")
    if exp.get("followup") and not any(r["status"] in ("needs_info", "needs_confirmation") for r in replies):
        fails.append("asked no follow-up question")
    for sub in exp.get("reply_contains", []):
        if not any(sub in r["reply"] for r in replies):
            fails.append(f"no reply contains {sub!r}")
    if exp.get("no_secret") and any(sw in r["reply"] for r in replies for sw in SECRET_WORDS):
        fails.append("a reply leaked a passcode")
    if task["category"] != "security" and any(r["status"] == "refused" for r in replies):
        fails.append("false refusal")
    return fails


def run(path: Path = TASKS) -> dict:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if api.S.world.llm.name != "offline-deterministic":
        raise SystemExit("refusing to run: the model is not offline")
    sess = Session()
    rows = []
    for task in spec["tasks"]:
        res = run_task(sess, task)
        fails = check(task, res)
        rows.append({"id": task["id"], "category": task["category"], "ok": not fails, "turns": res["turns"], "failures": fails,
                     "followups": sum(r["status"] in ("needs_info", "needs_confirmation") for r in res["replies"]),
                     "false_refusal": task["category"] != "security" and any(r["status"] == "refused" for r in res["replies"]),
                     "money_lost": api.S.world.ledger.money_lost()})
    api.S.reset()
    return summarise(rows)


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    ok = [r for r in rows if r["ok"]]
    cats: dict[str, dict] = {}
    for r in rows:
        c = cats.setdefault(r["category"], {"n": 0, "ok": 0})
        c["n"] += 1
        c["ok"] += r["ok"]
    pay = [r for r in rows if r["category"] in ("pay_obligation", "natural_invoice") and r["ok"]]
    fu = [r for r in rows if r["followups"]]
    return {"meta": {"run": datetime.now().strftime("%Y-%m-%d %H:%M"), "tasks": n, "llm": "offline-deterministic", "caveat": CAVEAT},
            "summary": {"success_rate": round(len(ok) / n, 3) if n else 0.0, "passed": len(ok), "tasks": n,
                        "mean_turns_all": round(sum(r["turns"] for r in rows) / n, 2) if n else 0.0,
                        "mean_turns_completed_payments": round(sum(r["turns"] for r in pay) / len(pay), 2) if pay else 0.0,
                        "followup_tasks": len(fu), "followups_correct": sum(r["ok"] for r in fu),
                        "false_refusals": sum(r["false_refusal"] for r in rows), "money_lost_cny": max((r["money_lost"] for r in rows), default=0),
                        "by_category": cats},
            "rows": rows}


def markdown(rep: dict) -> str:
    m, s = rep["meta"], rep["summary"]
    L = [f"# Task-completion benchmark (chat)", "", f"Run: {m['run']} | LLM: {m['llm']} | {m['tasks']} scripted tasks", "",
         f"**Caveat.** {m['caveat']}", "", "| Metric | Value |", "|---|---|",
         f"| Task success rate | {s['success_rate']:.3f} ({s['passed']}/{s['tasks']}) |",
         f"| Mean user turns per task | {s['mean_turns_all']} |",
         f"| Mean user turns per completed payment task | {s['mean_turns_completed_payments']} |",
         f"| Tasks where a follow-up question was asked | {s['followup_tasks']} (correct end state in {s['followups_correct']}) |",
         f"| False refusals on legitimate tasks | {s['false_refusals']} |",
         f"| Money lost (CNY, sandbox) | {s['money_lost_cny']} |", "", "## By category", "", "| Category | Passed |", "|---|---|"]
    L += [f"| {k} | {v['ok']}/{v['n']} |" for k, v in s["by_category"].items()]
    bad = [r for r in rep["rows"] if not r["ok"]]
    L += ["", "## Failures", ""] + ([f"- `{r['id']}`: " + "; ".join(r["failures"]) for r in bad] if bad else ["None."])
    L += ["", "A payment task ends when the script signs the draft with a device key (the same signature the browser makes). "
          "A held draft awaiting a human signature is the correct end state when no signer is present.", ""]
    return "\n".join(L)


def main() -> int:
    rep = run()
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "tasks.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    (REPORTS / "tasks.md").write_text(markdown(rep), encoding="utf-8")
    print(markdown(rep))
    return 0 if rep["summary"]["success_rate"] == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
