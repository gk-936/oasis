# Plan-quality evaluation (agentic planning)

Eight planning scenarios on MOCK data (`oasis/planning/scenarios.py`), scored by the deterministic plan validator (`oasis/planning/validator.py`), never by a model. A plan is *valid* when every obligation is funded and paid in its exact amount, to its own payee, on or before its due date; CNY arrives before it is spent; the student's INR never goes negative; the SAFE quota is respected per calendar year; the LRS limit holds; and INR needed by pending rate targets stays unconverted. TCS and LRS findings are surfaced as warnings. Fees are measured against the same INR sent through the typical bank route. Rates are quoted at today's mock rate; nothing is predicted.

## Offline (deterministic planner, no network)

Planner: `deterministic`; run 2026-10-10.

| Metric | Result |
|---|---|
| Scenarios run | 8 of 8 |
| Valid-plan rate (final plan) | 100% |
| Valid without fallback | 8 of 8 |
| Fallbacks to the deterministic plan | 0 |
| Proposals to first valid plan (mean / max) | 1.5 / 2 |
| Deadlines met | 20 of 20 |
| Conversion fees vs typical bank | CNY 5,138 vs CNY 29,867 (82.8% lower) |
| Tokens / model calls | 0 / 0 |

| Scenario | Valid | Proposals to valid | Fallback | Deadlines | Fees (CNY) vs bank | TCS (INR) | First validator errors | Warnings |
|---|---|---|---|---|---|---|---|---|
| Arrival shortfall (the demo student) | yes | 2 | no | 3/3 | 390 vs 2,093 | 0 | insufficient_inr | low_runway, parent_remitter |
| Tight runway | yes | 1 | no | 3/3 | 322 vs 1,885 | 0 | - | low_runway |
| SAFE-quota tuition | yes | 1 | no | 1/1 | 2,548 vs 16,391 | 74,238 | - | safe_quota_near, tcs |
| Late scholarship | yes | 2 | no | 2/2 | 354 vs 1,853 | 0 | insufficient_inr | late_income_ignored, low_runway, parent_remitter |
| Parent remitter crossing TCS | yes | 2 | no | 1/1 | 296 vs 1,613 | 5,093 | insufficient_inr | low_runway, parent_remitter, tcs |
| Rate target to protect | yes | 2 | no | 3/3 | 390 vs 2,093 | 0 | rate_target_reserve | parent_remitter |
| Five obligations | yes | 1 | no | 5/5 | 382 vs 2,285 | 0 | - | - |
| Urgent deposit | yes | 1 | no | 2/2 | 457 vs 1,652 | 0 | - | - |

- The deterministic planner drafts a student-funded plan first and asks the family only when the validator reports a shortfall; that is why scenarios with a shortfall need two proposals.

## Live (Groq native tool calling)

Planner: `groq-tools`; model `qwen/qwen3.8-27b`, fallback `openai/gpt-oss-120b`; run 2026-10-10.

| Metric | Result |
|---|---|
| Scenarios run | 3 of 8 |
| Valid-plan rate (final plan) | 100% |
| Valid without fallback | 1 of 3 |
| Fallbacks to the deterministic plan | 2 |
| Proposals to first valid plan (mean / max) | 3.0 / 3 |
| Deadlines met | 5 of 5 |
| Conversion fees vs typical bank | CNY 3,438 vs CNY 20,516 (83.2% lower) |
| Tokens / model calls | 22,633 / 16 |

| Scenario | Valid | Proposals to valid | Fallback | Deadlines | Fees (CNY) vs bank | TCS (INR) | First validator errors | Warnings |
|---|---|---|---|---|---|---|---|---|
| Arrival shortfall (the demo student) | yes | 3 | no | 3/3 | 594 vs 2,511 | 0 | insufficient_cny | low_runway, parent_remitter |
| SAFE-quota tuition | yes | - | yes: token cap reached (15144) | 1/1 | 2,548 vs 16,391 | 74,238 | insufficient_cny | safe_quota_near, tcs |
| Parent remitter crossing TCS | yes | - | yes: token cap reached (7489) | 1/1 | 296 vs 1,613 | 5,093 | insufficient_inr | low_runway, parent_remitter, tcs |

- Tokens spent by this run: 22,633 (cap 22,000); Groq daily ledger before: 76,343, after: 98,976.
- Total Groq tokens spent on live planning today (incl. earlier debugging runs whose responses are now cached): 61,561 (ledger 37,415 -> 98,976).
- Live calls 9, cache hits 7, model fallbacks 2.
- 2 fallback(s) (SAFE-quota tuition; Parent remitter crossing TCS) were triggered by the per-plan token cap protecting the free-tier budget, not by a model that gave up: those plans were still being revised. The reported plan is then the deterministic one.
- Not run live (token budget): Tight runway, Late scholarship, Rate target to protect, Five obligations, Urgent deposit.
- Observed live behaviour (earlier debugging runs included): qwen/qwen3.8-27b once emitted garbled argument keys in a propose_plan call (the validator rejected it) and hit its 7,000 input-tokens-per-minute limit, after which the adapter retried or used openai/gpt-oss-120b, which answered with the plan as plain JSON text; that text is parsed as a propose_plan call and validated like any other. Typical errors the validator caught: CNY a few yuan short because the model rounded INR down, INR above the student's balance, and wrong payment amounts.

## Caveats

- Eight hand-written scenarios, one run each; a pass here shows the planner and validator agree on these cases, not general optimality.
- The validator checks feasibility and the stated rules; it does not search for the globally cheapest plan. 'Fees vs bank' compares with the typical bank route only.
- Corridor figures (SAFE quota, LRS, TCS) are researched, not officially confirmed; the SAFE quota is modelled as USD 50,000 equivalent per calendar year at a mock USD/INR of 88.
- Offline results are deterministic. A live result is one sample from one model at temperature 0 and is cached; it is not a robustness claim.
