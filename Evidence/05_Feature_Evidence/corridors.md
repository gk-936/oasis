# Corridor price table (snapshot rates)

Generated 2026-10-13 07:28 UTC. Rate source: frozen snapshot (MOCK). Recipient receives the equivalent of USD 5,000.
Route prices are public-range estimates (docs/corridor-research.md), not live quotes. No model call was made.

| Corridor | Mid rate | Route | Send | Cost % | Worst received | Days | Price status |
|---|---|---|---|---|---|---|---|
| INR-CNY | 0.069964 | Education payment specialist | 482,079.86 INR | 0.794 | 33,460.50 CNY | 3 | mock |
| INR-CNY | 0.069964 | Digital remitter B (INR→CNY) | 485,162.17 INR | 1.424 | 33,460.50 CNY | 1 | mock |
| INR-CNY | 0.069964 | Digital remitter A (INR→CNY) | 485,513.84 INR | 1.495 | 33,460.50 CNY | 2 | mock |
| INR-CNY | 0.069964 | Typical bank SWIFT transfer | 503,203.79 INR | 4.958 | 33,460.50 CNY | 4 | mock |
| CNY-USD | 0.14943 | Digital remitter | 33,724.51 CNY | 0.783 | 5,000.00 USD | 2 | assumed |
| CNY-USD | 0.14943 | Education payment specialist | 33,730.34 CNY | 0.8 | 5,000.00 USD | 3 | assumed |
| CNY-USD | 0.14943 | Typical bank SWIFT transfer | 35,032.25 CNY | 4.487 | 5,000.00 USD | 3 | estimated |
| INR-USD | 0.010455 | Education payment specialist | 488,013.37 INR | 2.0 | 5,000.00 USD | 3 | assumed |
| INR-USD | 0.010455 | Digital remitter | 488,811.43 INR | 2.16 | 5,000.00 USD | 1 | sourced |
| INR-USD | 0.010455 | Typical bank SWIFT transfer | 500,718.27 INR | 4.487 | 5,000.00 USD | 3 | estimated |
| EUR-USD | 1.1206 | Digital remitter | 4,488.97 EUR | 0.603 | 5,000.00 USD | 1 | sourced |
| EUR-USD | 1.1206 | Education payment specialist | 4,497.88 EUR | 0.8 | 5,000.00 USD | 2 | assumed |
| EUR-USD | 1.1206 | Typical bank SWIFT transfer | 4,671.49 EUR | 4.487 | 5,000.00 USD | 2 | estimated |
| INR-EUR | 0.00933 | Education payment specialist | 488,013.37 INR | 2.0 | 4,461.90 EUR | 3 | assumed |
| INR-EUR | 0.00933 | Digital remitter | 488,212.64 INR | 2.04 | 4,461.90 EUR | 1 | sourced |
| INR-EUR | 0.00933 | Typical bank SWIFT transfer | 500,718.27 INR | 4.487 | 4,461.89 EUR | 3 | estimated |
| CNY-EUR | 0.133348 | Digital remitter | 33,724.51 CNY | 0.783 | 4,461.89 EUR | 2 | assumed |
| CNY-EUR | 0.133348 | Education payment specialist | 33,730.34 CNY | 0.8 | 4,461.89 EUR | 3 | assumed |
| CNY-EUR | 0.133348 | Typical bank SWIFT transfer | 35,032.25 CNY | 4.487 | 4,461.89 EUR | 3 | estimated |

## Check against real observations (Wise public pages, read 2026-10-13, undated)

| Quantity | Model table | Observed | Difference |
|---|---|---|---|
| INR per USD | 95.6506 | 95.2726 | +0.40% |
| INR per EUR | 107.1861 | 106.596 | +0.55% |
| EUR per USD | 0.8924 | 0.8937 | -0.14% |

- INR-USD digital remitter at INR 80,000: model cost 2.16%, observed 2.16% (Wise bank transfer example).
- INR-EUR digital remitter at INR 80,000: model cost 2.04%, observed 2.04% (Wise bank transfer example).

The observations are single, undated page readings, so small differences in rates mostly reflect the day they were taken.
