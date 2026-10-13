"""Corridor price table for every supported corridor at one payment size, plus a check against real rates and real examples.

Run (no model call; --live fetches free ECB reference rates from Frankfurter, nothing else):
  OASIS_LLM=offline PYTHONPATH=. python -m eval.corridors_bench            # frozen snapshot rates -> corridors.md
  OASIS_LLM=offline PYTHONPATH=. python -m eval.corridors_bench --live     # live ECB rates       -> corridors_live.md
Route PRICES are public-range estimates (see docs/corridor-research.md), not live quotes."""
from __future__ import annotations
import argparse
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from oasis.corridors import core as cor
from oasis.market.live_rates import LiveRates
from oasis.mock import fx
from oasis.mock.rates import MockRates

REPORTS = Path(__file__).parent / "reports"
RECEIVE_USD = 5000.0          # the recipient must receive the equivalent of USD 5,000
# Real observations, Wise public pages read 2026-10-13 (undated, single examples). Used only as a sanity check.
OBSERVED = {"INR/USD": 95.2726, "INR/EUR": 106.596, "USD/EUR": 1 / 1.119}     # INR per USD, INR per EUR, EUR per USD
OBSERVED_COST = {"INR-USD": 1726.53 / 80000 * 100, "INR-EUR": 1632.11 / 80000 * 100}   # percent of the amount sent, bank-transfer pay-in


def run(live: bool) -> str:
    if live:
        rates = LiveRates(cache_path=Path(tempfile.mkdtemp()) / "rates.json")
        label = rates.provenance()["label"]
    else:
        rates, label = MockRates(), "frozen snapshot (MOCK)"
    table = fx.table_for(rates, 0)
    L = [f"# Corridor price table ({'LIVE ECB rates' if live else 'snapshot rates'})", "",
         f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. Rate source: {label}. Recipient receives the equivalent of USD {RECEIVE_USD:,.0f}.",
         "Route prices are public-range estimates (docs/corridor-research.md), not live quotes. No model call was made.", "",
         "| Corridor | Mid rate | Route | Send | Cost % | Worst received | Days | Price status |", "|---|---|---|---|---|---|---|---|"]
    for c in cor.listing():
        need = RECEIVE_USD * table[c["to"]]
        r = cor.compare(c["id"], need, table)
        for o in r["options"]:
            L.append(f"| {c['id']} | {r['mid']} | {o['route']} | {o['send']:,.2f} {c['from']} | {o['fee_pct_of_value']} | {o['worst_received']:,.2f} {c['to']} | {o['arrives_in_days']} | {o['price_status']} |")
    inr_usd, inr_eur = table["INR"] / table["USD"], table["INR"] / table["EUR"]
    L += ["", "## Check against real observations (Wise public pages, read 2026-10-13, undated)", "",
          "| Quantity | Model table | Observed | Difference |", "|---|---|---|---|",
          f"| INR per USD | {inr_usd:.4f} | {OBSERVED['INR/USD']} | {(inr_usd / OBSERVED['INR/USD'] - 1) * 100:+.2f}% |",
          f"| INR per EUR | {inr_eur:.4f} | {OBSERVED['INR/EUR']} | {(inr_eur / OBSERVED['INR/EUR'] - 1) * 100:+.2f}% |",
          f"| EUR per USD | {table['EUR']:.4f} | {OBSERVED['USD/EUR']:.4f} | {(table['EUR'] / OBSERVED['USD/EUR'] - 1) * 100:+.2f}% |", ""]
    for cid, obs in OBSERVED_COST.items():
        o = next(x for x in cor.compare(cid, 80000 * fx.mid("INR", cid[-3:], table), table)["options"] if x["route"] == "Digital remitter")
        L.append(f"- {cid} digital remitter at INR 80,000: model cost {o['fee_pct_of_value']}%, observed {obs:.2f}% (Wise bank transfer example; the price was set from this example, so the match is by construction, not a validation).")
    L += ["", "The observations are single, undated page readings, so small differences in rates mostly reflect the day they were taken."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()
    out = run(a.live)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / ("corridors_live.md" if a.live else "corridors.md")).write_text(out, encoding="utf-8")
    print(out.encode("ascii", "replace").decode())
