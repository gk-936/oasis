# Peer netting (MOCK, simulation only)

Idea: Indian students paying INR to CNY and Chinese students or families paying CNY to INR are opposite flows. In a pool, the matched volume can settle at the mid-rate with no FX spread and no bank leg. Only the unmatched residual goes through the normal cheapest on-time route (`oasis/planning/routes.py`).

## What is implemented
- `oasis/netting/core.py`: a deterministic greedy matcher (earliest deadline first, ties by id) and `net()`, which computes the saving versus routing every payment alone.
- Eligibility: a payment enters the pool only if its payee is verified, it has passed policy and approval upstream, and it has at least 2 days to its deadline (a pooled match settles after the next netting cycle). Everything else is routed alone. Netting never bypasses recipient verification, policy or approval.
- Value is conserved: matched CNY on the INR side equals matched CNY on the CNY side; each payment's matched plus residual equals its amount.
- A pool of one has no counterparty, so the saving is exactly 0.
- `eval/netting_bench.py` writes `eval/reports/netting.{json,md}`; `POST /api/netting/simulate` and `GET /api/netting/benchmark`; UI tab "Netting" (student, judge).

## Honest limits
- The cohorts are seeded and synthetic. Real demand is thinner and lopsided; unmatched volume is always routed normally.
- The CNY to INR leg cost is assumed equal to the mirror INR to CNY route (MOCK assumption).
- Real netting requires a licensed counterparty (a payment institution holding both currencies) and regulatory approval in both countries (for example RBI/FEMA and PBoC/SAFE rules). Nothing here moves money.
