"""Peer-netting benchmark on SEEDED SYNTHETIC cohorts. MOCK: not real demand, not a licensed counterparty.

Run: PYTHONPATH=. python -m eval.netting_bench   (writes eval/reports/netting.{json,md})"""
from __future__ import annotations
import json
import random
from pathlib import Path

from oasis.netting.core import Payment, net

REPORTS = Path(__file__).parent / "reports"
SIZES = [1, 2, 10, 50, 200, 1000]
SEED = 11


def cohort(n: int, seed: int = SEED) -> list[Payment]:
    rng = random.Random(seed * 100003 + n)
    out = []
    for i in range(n):
        d = "INR_CNY" if rng.random() < 0.65 else "CNY_INR"   # more Indians paying into China than the reverse
        out.append(Payment(f"p{i:04d}", d, round(rng.uniform(1500, 30000), 2), rng.choice([1, 3, 5, 7, 10, 14]),
                           payee_verified=rng.random() > 0.05, approved=rng.random() > 0.03))
    return out


def run() -> dict:
    rows = []
    for n in SIZES:
        r = net(cohort(n))
        rows.append({"pool_size": n, "total_volume_cny": r["total_volume_cny"], "matched_volume_cny": r["matched_volume_cny"],
                     "matched_pct": round(r["matched_volume_cny"] / r["total_volume_cny"] * 100, 1),
                     "cost_alone_cny": r["cost_alone_cny"], "cost_netted_cny": r["cost_netted_cny"],
                     "saving_cny": r["saving_cny"], "saving_pct": r["saving_pct"]})
    return {"label": "MOCK: seeded synthetic cohorts", "seed": SEED, "rows": rows,
            "caveats": ["Synthetic demand; real pools are thinner and lopsided.",
                        "CNY->INR cost assumed equal to the mirror INR->CNY route (MOCK).",
                        "Real netting needs a licensed counterparty and regulatory approval; nothing here moves money.",
                        "Only payee-verified, approved payments with >=2 days to deadline enter the pool."]}


def to_markdown(r: dict) -> str:
    t = "\n".join(f"| {x['pool_size']} | {x['total_volume_cny']:,.0f} | {x['matched_pct']}% | {x['cost_alone_cny']:,.0f} | "
                  f"{x['cost_netted_cny']:,.0f} | {x['saving_cny']:,.0f} | {x['saving_pct']}% |" for x in r["rows"])
    c = "\n".join(f"- {x}" for x in r["caveats"])
    return (f"# Peer netting benchmark ({r['label']})\n\nSeed {r['seed']}. Cost = CNY lost versus mid-rate.\n\n"
            f"| Pool size | Volume CNY | Matched | Cost alone | Cost netted | Saving CNY | Saving |\n|---|---|---|---|---|---|---|\n{t}\n\n{c}\n")


def main() -> None:
    r = run()
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "netting.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
    (REPORTS / "netting.md").write_text(to_markdown(r), encoding="utf-8")
    print(to_markdown(r))


if __name__ == "__main__":
    main()
