"""Offline benchmark of the foreign-currency planner on seeded scenarios. MOCK world, estimated route prices, no model call.

Run: OASIS_LLM=offline PYTHONPATH=. python -m eval.fxplan_bench   (writes eval/reports/fxplan.{json,md})"""
from __future__ import annotations
import json
from pathlib import Path

from oasis.agent.llm import OfflineLLM
from oasis.agent.planner import DeterministicFxPlanner
from oasis.passport.models import Obligation, Recipient
from oasis.world import Features, World

REPORTS = Path(__file__).parent / "reports"
# (id, title, obligation currency, amount, INR, CNY, held in the obligation currency, days until due)
SCENARIOS = [
    ("usd_from_inr", "USD 5,000 tuition, funded from INR", "USD", 5000, 700_000, 0, 0, 38),
    ("eur_from_inr", "EUR 3,000 tuition, funded from INR", "EUR", 3000, 400_000, 0, 0, 38),
    ("usd_from_cny", "USD 4,000 tuition, student holds CNY", "USD", 4000, 0, 40_000, 0, 38),
    ("parent_topup", "USD 8,000 tuition, student INR is short", "USD", 8000, 300_000, 0, 0, 40),
    ("already_funded", "USD 2,000, already held in USD", "USD", 2000, 100_000, 0, 2500, 20),
    ("tight_deadline", "USD 5,000 due in 2 days", "USD", 5000, 700_000, 0, 0, 2),
    ("over_lrs", "USD 300,000 (above the LRS limit)", "USD", 300_000, 40_000_000, 0, 0, 45),
    ("usd_from_eur", "USD 4,000 tuition, student holds EUR", "USD", 4000, 0, 0, 0, 38, {"EUR": 6000}),
    ("eur_from_cny", "EUR 3,000 tuition, student holds CNY", "EUR", 3000, 0, 40_000, 0, 38),
]


def build(sc) -> World:
    _, _, cur, amt, inr, cny, held, days = sc[:8]
    w = World(Features.full(), OfflineLLM(susceptible=True), seed=7, deterministic=True)
    p = w.passport
    p.set_balance("INR", inr)
    p.set_balance("CNY", cny)
    if held:
        w.credit_fx(cur, held)
    for c, v in (sc[8] if len(sc) > 8 else {}).items():
        w.credit_fx(c, v)
    p.recipients["payee_foreign_univ"] = Recipient(id="payee_foreign_univ", name="Foreign University", payee_type="university", account_ref="FX-0001")
    due = (w.today.fromordinal(w.today.toordinal() + days)).isoformat()
    p.obligations.append(Obligation(id="obl_fx_tuition", type="tuition", payee_id="payee_foreign_univ", amount=amt, currency=cur, due=due))
    return w


def run() -> dict:
    rows = []
    for sc in SCENARIOS:
        w = build(sc)
        res = DeterministicFxPlanner().plan(w)
        v = res.validation
        convs = [s for s in res.steps if s["action"] == "convert"]
        rows.append({"id": sc[0], "title": sc[1], "valid": res.valid, "iterations": res.iterations,
                     "corridors": sorted({c["corridor"] for c in convs}), "remitters": sorted({c["remitter"] for c in convs}),
                     "deadlines_met": f"{v.get('metrics', {}).get('deadlines_met', 0)}/{v.get('metrics', {}).get('obligations', 0)}",
                     "saved_vs_bank_usd": v.get("metrics", {}).get("saved_vs_bank_usd_equivalent"),
                     "error_codes": sorted({e["code"] for e in v.get("errors", [])}), "price_status": sorted({s["price_status"] for s in v.get("schedule", []) if s["action"] == "convert"})})
    return {"rows": rows, "valid": sum(r["valid"] for r in rows), "total": len(rows)}


def md(d: dict) -> str:
    L = ["# Foreign-currency planner (offline, deterministic)", "",
         "MOCK world on the frozen rate snapshot; route prices are public-range estimates (docs/corridor-research.md). No model call. "
         "These are plans only (nothing is executed here; execution is covered by tests/test_fxplan.py). One scenario is SUPPOSED to be refused: a payment above the LRS limit. An assumed route price must beat a sourced one by more than 0.5% to be chosen.", "",
         "| Scenario | Valid | Corridor | Remitter | Deadlines met | Saved vs bank (USD) | Errors | Price status |", "|---|---|---|---|---|---|---|---|"]
    for r in d["rows"]:
        L.append(f"| {r['title']} | {r['valid']} | {', '.join(r['corridors']) or '-'} | {', '.join(r['remitters']) or '-'} | {r['deadlines_met']} | {r['saved_vs_bank_usd']} | {', '.join(r['error_codes']) or '-'} | {', '.join(r['price_status']) or '-'} |")
    L += ["", f"Valid plans: {d['valid']} of {d['total']}."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    d = run()
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "fxplan.json").write_text(json.dumps(d, indent=2), encoding="utf-8")
    (REPORTS / "fxplan.md").write_text(md(d), encoding="utf-8")
    print(md(d).encode("ascii", "replace").decode())
