# Corridor price table (LIVE ECB rates)

Generated 2026-10-13 07:28 UTC. Rate source: INR→CNY 0.0699 · live · ECB via Frankfurter · as of 2026-10-12 · fetched 07:28 UTC. Recipient receives the equivalent of USD 5,000.
Route prices are public-range estimates (docs/corridor-research.md), not live quotes. No model call was made.

| Corridor | Mid rate | Route | Send | Cost % | Worst received | Days | Price status |
|---|---|---|---|---|---|---|---|
| INR-CNY | 0.06988 | Education payment specialist | 482,707.48 INR | 0.794 | 33,463.91 CNY | 3 | mock |
| INR-CNY | 0.06988 | Digital remitter B (INR→CNY) | 485,794.46 INR | 1.424 | 33,463.91 CNY | 1 | mock |
| INR-CNY | 0.06988 | Digital remitter A (INR→CNY) | 486,146.42 INR | 1.495 | 33,463.91 CNY | 2 | mock |
| INR-CNY | 0.06988 | Typical bank SWIFT transfer | 503,856.49 INR | 4.958 | 33,463.91 CNY | 4 | mock |
| CNY-USD | 0.149415 | Digital remitter | 33,727.94 CNY | 0.783 | 5,000.00 USD | 2 | assumed |
| CNY-USD | 0.149415 | Education payment specialist | 33,733.78 CNY | 0.8 | 5,000.00 USD | 3 | assumed |
| CNY-USD | 0.149415 | Typical bank SWIFT transfer | 35,035.82 CNY | 4.487 | 5,000.00 USD | 3 | estimated |
| INR-USD | 0.010441 | Education payment specialist | 488,649.78 INR | 2.0 | 5,000.00 USD | 3 | assumed |
| INR-USD | 0.010441 | Digital remitter | 489,448.88 INR | 2.16 | 5,000.00 USD | 1 | sourced |
| INR-USD | 0.010441 | Typical bank SWIFT transfer | 501,371.25 INR | 4.487 | 5,000.00 USD | 3 | estimated |
| EUR-USD | 1.1181 | Digital remitter | 4,499.00 EUR | 0.603 | 5,000.00 USD | 1 | sourced |
| EUR-USD | 1.1181 | Education payment specialist | 4,507.93 EUR | 0.8 | 5,000.00 USD | 2 | assumed |
| EUR-USD | 1.1181 | Typical bank SWIFT transfer | 4,681.93 EUR | 4.487 | 5,000.00 USD | 2 | estimated |
| INR-EUR | 0.009338 | Education payment specialist | 488,649.78 INR | 2.0 | 4,471.87 EUR | 3 | assumed |
| INR-EUR | 0.009338 | Digital remitter | 488,849.31 INR | 2.04 | 4,471.87 EUR | 1 | sourced |
| INR-EUR | 0.009338 | Typical bank SWIFT transfer | 501,371.25 INR | 4.487 | 4,471.87 EUR | 3 | estimated |
| CNY-EUR | 0.133633 | Digital remitter | 33,727.94 CNY | 0.783 | 4,471.87 EUR | 2 | assumed |
| CNY-EUR | 0.133633 | Education payment specialist | 33,733.78 CNY | 0.8 | 4,471.87 EUR | 3 | assumed |
| CNY-EUR | 0.133633 | Typical bank SWIFT transfer | 35,035.82 CNY | 4.487 | 4,471.87 EUR | 3 | estimated |

## Check against real observations (Wise public pages, read 2026-10-13, undated)

| Quantity | Model table | Observed | Difference |
|---|---|---|---|
| INR per USD | 95.7754 | 95.2726 | +0.53% |
| INR per EUR | 107.0865 | 106.596 | +0.46% |
| EUR per USD | 0.8944 | 0.8937 | +0.08% |

- INR-USD digital remitter at INR 80,000: model cost 2.16%, observed 2.16% (Wise bank transfer example; the price was set from this example, so the match is by construction, not a validation).
- INR-EUR digital remitter at INR 80,000: model cost 2.04%, observed 2.04% (Wise bank transfer example; the price was set from this example, so the match is by construction, not a validation).

The observations are single, undated page readings, so small differences in rates mostly reflect the day they were taken.
