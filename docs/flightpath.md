# FlightPath: payment-journey reliability (simulated)

Security stops the wrong payment. FlightPath covers the right payment that still fails: delayed, rejected or short-credited.
Code: `oasis/flightpath/core.py`. Benchmark: `python -m eval.flightpath_bench` -> `eval/reports/flightpath.{json,md}`.

| Step | What it does |
|---|---|
| Predict | `precheck`: unverified payee, detail mismatch, missing documents, deadline slack |
| Plan | `compare_routes`: ranks by the amount the **recipient** gets, with a worst-case deduction margin, not the sender fee |
| Simulate | `Journey` state machine: prepared > checks_complete > submitted > processing > credited / delayed / rejected |
| Reconcile | `reconcile`: flags delay (past route time + grace) and short-credit versus the required amount |
| Recover | `advise`: wait / support case / investigate shortfall. **Never resends** while the first transfer is unresolved; a new payment needs a rejection **and** a confirmed refund, then re-enters policy and approval |

API (advisory, moves no money): `POST /api/flightpath/compare`, `GET /api/flightpath/benchmark`, `POST /api/flightpath/precheck`, `GET|POST /api/flightpath/journeys`, `POST .../journeys/{id}/simulate` (MOCK delay / reject / short credit), `POST .../refund`, `GET .../advice`. Journeys persist and each verdict is written to the audit chain. UI: the FlightPath tab.

## Limits
- Rails, deductions and delays are MOCK. Results are simulation results, not validated against real transfers.
- The baseline is a deliberately naive strategy (cheapest route on paper, no pre-checks, retry on delay). The benchmark's deduction model is my own: real deductions are drawn uniformly in [0, worst case] and FlightPath's expected value is set to half the worst case. That consistency is by construction, so the amount-error figure (4.43 vs 4.9 CNY) shows the mechanism works, not accuracy on real rails.
- Everything on the original roadmap is now built: see [digital-twin.md](digital-twin.md) and [evidence-passport.md](evidence-passport.md).
