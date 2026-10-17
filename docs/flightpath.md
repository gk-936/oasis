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

## What a finding means for the deadline (added 2026-10-17)

`consequences()` in `oasis/flightpath/core.py` turns a finding into advice that names the bill's deadline. It is arithmetic on facts FlightPath already holds (the journey's due day, the route's days, the reported shortfall); it never sends, reverses or approves anything.

- **Delayed:** how many days remain, how long waiting stays safe (days left minus the route's days), or, if a replacement could no longer arrive in time, a suggestion to ask the recipient for more time. It always lists "do not send again yet" and explains that the first transfer may still arrive, so a second payment could pay the same bill twice.
- **Short credit:** the top-up as a new payment that needs approval, and whether it would arrive before the deadline.
- **Rejected:** wait for the refund, or, once the refund is confirmed, plan a new payment on another route through verification and approval.
- **What is not established** (for example "the provider has not confirmed whether the money reached the recipient") is listed explicitly. No option ever has `resend` set.
- `POST /api/flightpath/journeys` accepts an optional `purpose` (tuition, rent, deposit, living) so the text can name the bill; the advice endpoint returns a `consequence` object (facts, options, deadline risk, uncertainty, text) and the FlightPath tab shows it as "What it means for the deadline".
- In live mode a model may reword the text. The reword is kept only if every number survives, none is added and it is plain text (no preface, markdown or list); otherwise the deterministic text is shown. Offline, the deterministic text is always shown.
- Evidence: `tests/test_flightpath_consequences.py`, `eval/reports/ai_contribution.md` (17 of 17 numbers traced to held facts, 17 of 17 with no resend offline; live rewrite results). Mock rails and our own deadline arithmetic: a simulation, not validated against real transfers.
