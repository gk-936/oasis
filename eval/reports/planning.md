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
| Conversion fees vs typical bank | CNY 4,990 vs CNY 29,378 (83.0% lower) |
| Tokens / model calls | 0 / 0 |

| Scenario | Valid | Proposals to valid | Fallback | Deadlines | Fees (CNY) vs bank | TCS (INR) | First validator errors | Warnings |
|---|---|---|---|---|---|---|---|---|
| Arrival shortfall (the demo student) | yes | 2 | no | 3/3 | 365 vs 2,018 | 0 | insufficient_inr | low_runway, parent_remitter |
| Tight runway | yes | 1 | no | 3/3 | 309 vs 1,848 | 0 | - | low_runway |
| SAFE-quota tuition | yes | 1 | no | 1/1 | 2,523 vs 16,316 | 95,066 | - | safe_quota_near, tcs |
| Late scholarship | yes | 2 | no | 2/2 | 329 vs 1,778 | 0 | insufficient_inr | late_income_ignored, low_runway, parent_remitter |
| Parent remitter crossing TCS | yes | 2 | no | 1/1 | 275 vs 1,538 | 6,655 | insufficient_inr | low_runway, parent_remitter, tcs |
| Rate target to protect | yes | 2 | no | 3/3 | 365 vs 2,018 | 0 | rate_target_reserve | parent_remitter |
| Five obligations | yes | 1 | no | 5/5 | 369 vs 2,247 | 0 | - | - |
| Urgent deposit | yes | 1 | no | 2/2 | 453 vs 1,615 | 0 | - | - |

- The deterministic planner drafts a student-funded plan first and asks the family only when the validator reports a shortfall; that is why scenarios with a shortfall need two proposals.

## Live (Groq native tool calling), after the planner prompt change

Planner: `groq-tools`; model `qwen/qwen3.8-27b`, fallback `openai/gpt-oss-120b`; run 2026-10-11; 3 repeat(s) at temperature 0.3 with a repeat-specific cache salt (`planrep<N>`), so every repeat is a distinct sample; per-plan token cap 22,000. Repeats completed in full: 2 of 3.

| Repeat | Plans run | Valid without fallback | Final plan valid | Mean proposals to valid | Tokens |
|---|---|---|---|---|---|
| 1 | 8 of 8 | 4 | 100% | 1.5 | 155,816 |
| 2 | 8 of 8 | 2 | 100% | 2.0 | 144,790 |
| 3 | 1 of 8 | 0 | 100% | - | 3,841 |

Valid without fallback across completed repeats (min / mean / max): 2 / 3.0 / 4 of 8 scenarios.

Pooled over every plan run: 6 of 17 valid without fallback (35%); tokens 304,447.

| Scenario | Valid without fallback | Proposals to valid (per repeat; fb = fell back) | Tokens (per repeat) | First validator errors (per repeat) |
|---|---|---|---|---|
| Arrival shortfall (the demo student) | 1 of 2 | fb, 1 | 25,370, 7,424 | insufficient_inr; - |
| Tight runway | 0 of 3 | fb, fb, fb | 25,567, 14,167, 3,841 | -; -; - |
| SAFE-quota tuition | 0 of 2 | fb, fb | 23,711, 22,093 | safe_quota_exceeded; amount_mismatch,unknown_route |
| Late scholarship | 1 of 2 | fb, 3 | 23,134, 25,249 | amount_mismatch,insufficient_inr; insufficient_cny |
| Parent remitter crossing TCS | 1 of 2 | 2, fb | 16,837, 25,460 | amount_mismatch,insufficient_inr; insufficient_inr |
| Rate target to protect | 1 of 2 | 1, fb | 13,692, 24,172 | -; amount_mismatch,unknown_route |
| Five obligations | 1 of 2 | 2, fb | 16,571, 22,058 | amount_mismatch,unknown_route; amount_mismatch |
| Urgent deposit | 1 of 2 | 1, fb | 10,934, 4,167 | -; - |

- Invocation 2026-10-11 (4 comma-separated keys, daily budget 180,000 tokens per key): new tokens 300,606 (cap 300,000); Groq daily ledger before 0, after 300,606. Live calls 89, cache hits 9, model fallbacks 15 (the last figure counts calls served by the fallback model).
- Per-key tokens this invocation, by sha256 fingerprint: 499b1366: 181,449 (55 requests); d40d45b2: 119,157 (34 requests); the other two keys were not needed. Key rotations: 1 (the first key reached the local 180,000-token guard; no server-side daily limit was hit).
- Planner change in this section: the system prompt carries the validator's error vocabulary (compute the INR from get_routes, add fee/rounding headroom, pay each obligation exactly once with its exact amount, keep the rate-target reserve, stage SAFE-quota conversions across calendar years, parent for the INR shortfall) and the per-plan cap is 22,000 tokens. The validator rules were not changed.
- Sampling: temperature 0.3 with a repeat-specific cache salt (planrep0, planrep1, planrep2), so repeats are distinct samples and never cache hits of each other.
- Coverage: 17 plans. Repeats 1 and 2 cover all 8 scenarios (run 2026-10-11, qwen/qwen3.8-27b first, with up to 8 rate-limit retries per call so the limiter waits instead of failing over). Repeat 3 was NOT run for lack of token budget (the ~300,000-token cap was reached); its only row is the Tight runway plan from 2026-10-10 (previous key), so the min/mean/max covers 2 repeats, not 3. Resume: `python -m eval.planning --llm groq --repeats 3 --token-cap 300000` (finished rows are kept; re-running a finished plan is free only if its responses are still cached).
- Which model answered (the `model` of the final call in each row; a plan can mix both models): qwen/qwen3.8-27b served 12 of the 16 plans run on 2026-10-11 and openai/gpt-oss-120b 4 (Rate target and Urgent deposit in repeat 1; Arrival shortfall and Tight runway in repeat 2). Of the 6 plans valid without fallback, 3 ended on qwen (Parent TCS and Five obligations in repeat 1; Late scholarship in repeat 2) and 3 on gpt-oss-120b (Rate target and Urgent deposit in repeat 1; Arrival shortfall in repeat 2). So these numbers describe qwen/qwen3.8-27b for most plans, but not all.
- Why 11 of 17 plans fell back to the deterministic plan: 6 hit the per-plan token cap while still revising (qwen spends ~3,000 tokens per call re-sending context, so a 4-proposal plan costs 22,000-25,000 tokens; the cap check runs after a call, so rows can exceed 22,000; Urgent deposit in repeat 2 was cut at 4,167 tokens because that was all that remained of the run's 300,000 cap); 4 ended with the model never proposing a plan inside the call budget (Arrival shortfall repeat 1, Tight runway repeats 1 and 2, Parent TCS repeat 2: mostly read-only tool calls); 1 (Tight runway repeat 3) was a Groq API HTTP 400 tool-call parse error on 2026-10-10. A budget stop or exhausted call count is not a plan the validator rejected, but it is a plan the model did not finish.
- The final plan was valid in all 17 rows because a fallback is the deterministic planner's plan; 'valid without fallback' is the model's own result.
- Superseded samples: the 2026-10-10 rows from the previous key for Arrival shortfall (repeat 1: valid without fallback on gpt-oss-120b, 1 proposal, 8,853 tokens) and Tight runway (repeats 1 and 2: valid without fallback, 5,162 and 11,405 tokens) were replaced when the plans were re-sampled on 2026-10-11, because their cached responses did not replay (the qwen calls had been rate-limited the first time, so the new samples diverged). Including them the pooled count would have been 7 of 18 valid without fallback.
- Tokens (Groq daily ledger): 300,606 tokens on 2026-10-11 across two keys; the 2026-10-10 planning work is not included (about 105,000 under the previous key).

## Live, before planner prompt change (2026-10-10, 1 run)

Planner: `groq-tools`; model `qwen/qwen3.8-27b`, fallback `openai/gpt-oss-120b`; run 2026-10-10.

| Metric | Result |
|---|---|
| Scenarios run | 8 of 8 |
| Valid-plan rate (final plan) | 100% |
| Valid without fallback | 4 of 8 |
| Fallbacks to the deterministic plan | 4 |
| Proposals to first valid plan (mean / max) | 2.75 / 4 |
| Deadlines met | 20 of 20 |
| Conversion fees vs typical bank | CNY 5,856 vs CNY 31,485 (81.4% lower) |
| Tokens / model calls | 100,235 / 42 |

| Scenario | Valid | Proposals to valid | Fallback | Deadlines | Fees (CNY) vs bank | TCS (INR) | First validator errors | Warnings |
|---|---|---|---|---|---|---|---|---|
| Arrival shortfall (the demo student) (2026-10-10, per-plan cap 14,000) | yes | 3 | no | 3/3 | 594 vs 2,511 | 0 | insufficient_cny | low_runway, parent_remitter |
| Tight runway (2026-10-10, per-plan cap 18,000) | yes | 1 | no | 3/3 | 574 vs 2,310 | 0 | - | low_runway, route_not_cheapest |
| SAFE-quota tuition (2026-10-10, per-plan cap 14,000) | yes | - | yes: token cap reached (15144) | 1/1 | 2,548 vs 16,391 | 74,238 | insufficient_cny | safe_quota_near, tcs |
| Late scholarship (2026-10-10, per-plan cap 18,000) | yes | 3 | no | 2/2 | 354 vs 1,855 | 0 | insufficient_cny | late_income_ignored, low_runway, parent_remitter |
| Parent remitter crossing TCS (2026-10-10, per-plan cap 14,000) | yes | - | yes: token cap reached (7489) | 1/1 | 296 vs 1,613 | 5,093 | insufficient_inr | low_runway, parent_remitter, tcs |
| Rate target to protect (2026-10-10, per-plan cap 18,000) | yes | 4 | no | 3/3 | 651 vs 2,867 | 0 | insufficient_inr, rate_target_reserve | parent_remitter, route_not_cheapest, small_conversion |
| Five obligations (2026-10-10, per-plan cap 18,000) | yes | - | yes: token cap reached (19888) | 5/5 | 382 vs 2,285 | 0 | amount_mismatch, unknown_route | - |
| Urgent deposit (2026-10-10, per-plan cap 7,094) | yes | - | yes: token cap reached (9696) | 2/2 | 457 vs 1,652 | 0 | - | - |

- Run 2026-10-10 (scenarios late_scholarship, multiple_obligations, rate_target, tight_runway, urgent_deadline): Tokens spent by this run: 77,602 (cap 75,000); Groq daily ledger before: 101,085, after: 178,687.
- Run 2026-10-10 (scenarios late_scholarship, multiple_obligations, rate_target, tight_runway, urgent_deadline): Live calls 26, cache hits 0, model fallbacks 3.
- Earlier run 2026-10-10: Tokens spent by this run: 22,633 (cap 22,000); Groq daily ledger before: 76,343, after: 98,976.
- Earlier run 2026-10-10: Total Groq tokens spent on live planning today (incl. earlier debugging runs whose responses are now cached): 61,561 (ledger 37,415 -> 98,976).
- Earlier run 2026-10-10: Live calls 9, cache hits 7, model fallbacks 2.
- Earlier run 2026-10-10: Observed live behaviour (earlier debugging runs included): qwen/qwen3.8-27b once emitted garbled argument keys in a propose_plan call (the validator rejected it) and hit its 7,000 input-tokens-per-minute limit, after which the adapter retried or used openai/gpt-oss-120b, which answered with the plan as plain JSON text; that text is parsed as a propose_plan call and validated like any other. Typical errors the validator caught: CNY a few yuan short because the model rounded INR down, INR above the student's balance, and wrong payment amounts.
- 4 fallback(s) (SAFE-quota tuition; Parent remitter crossing TCS; Five obligations; Urgent deposit) were triggered by the per-plan token cap protecting the free-tier budget, not by a model that gave up: those plans were still being revised. The reported plan is then the deterministic one.
- Urgent deposit was cut by the remaining run budget, not the nominal 18,000 per-plan cap: it was the last scenario and only 7,094 of the 75,000-token run cap was left (per-plan cap 7,094), so its fallback reflects my budget, not the model. Earlier-run rows (shortfall, SAFE-quota tuition, parent TCS) used a per-plan cap of at most 14,000 (the effective cap was min(14,000, remaining run budget)); the 5 newer rows used 18,000.

## Caveats

- Eight hand-written scenarios; a pass here shows the planner and validator agree on these cases, not general optimality.
- The validator checks feasibility and the stated rules; it does not search for the globally cheapest plan. 'Fees vs bank' compares with the typical bank route only.
- Corridor figures (SAFE quota, LRS, TCS) are researched, not officially confirmed; the SAFE quota is modelled as USD 50,000 equivalent per calendar year at a mock USD/INR of 88.
- Offline results are deterministic. A live result is a small number of samples from one model (see the repeat counts above), cached on disk; it is not a robustness claim.
