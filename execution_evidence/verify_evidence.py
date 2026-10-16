"""Re-check the numbers in the Execution Evidence report from the raw operation log. Standard library only; no network.

    python verify_evidence.py

Checks: (1) every audit chain is linked (each entry's previous hash is the hash before it, starting from zeros);
(2) money paid to attacker accounts per case and configuration, recomputed from the ledger transfers in the log;
(3) those figures equal the totals in evidence_results.json; (4) the executor tests moved no extra money.
"""
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ZERO = "0" * 64
log = [json.loads(x) for x in (HERE / "operation_log.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
results = json.loads((HERE / "evidence_results.json").read_text(encoding="utf-8"))
ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    ok &= cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


# 1. chain linkage, per case and configuration
chains, lost = defaultdict(list), defaultdict(float)
for r in log:
    if r["case"].startswith("executor_"):
        continue
    key = (r["case"], r["config"])
    chains[key] += r["audit_entries"]
    for t in r["ledger_transfers"]:
        if t["to_is_attacker"]:
            lost[key] += t["amount"]
broken = []
for key, entries in chains.items():
    prev = ZERO
    for e in entries:
        if e["prev"] != prev:
            broken.append((key, e["i"]))
        prev = e["hash"]
check("audit chains are linked", not broken, f"{len(chains)} chains, {sum(map(len, chains.values()))} entries")

# 2 and 3. money paid to attacker accounts
for cfg in ("UNPROTECTED", "PROTECTED"):
    mine = round(sum(v for (c, k), v in lost.items() if k == cfg and not c.startswith(("P7", "P8"))), 2)
    stated = results["summary"]["money_lost_cny"][cfg]
    check(f"money paid to attacker accounts, {cfg.lower()}", abs(mine - stated) < 0.005, f"log {mine:,.2f}, report {stated:,.2f}")

# 4. executor tests
ex = [r for r in log if r["case"].startswith("executor_")]
extra = round(sum(r["extra_money_moved"] for r in ex), 2)
refused = sum(1 for r in ex if r["case"] != "executor_control" and r["outcome"]["blocked"])
check("executor tests moved no extra money", extra == 0, f"{refused} of {len(ex) - 1} tampered payments refused")
check("honest control payment executed", next(r for r in ex if r["case"] == "executor_control")["outcome"]["status"] == "executed")
print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
raise SystemExit(0 if ok else 1)
