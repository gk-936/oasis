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

## Live (Bedrock native tool calling), after the planner prompt change

Planner: `bedrock-tools`; model `us.amazon.nova-pro-v1:0`, fallback `# default: same model (no silent downgrade)`; run 2026-10-18; 7 repeat(s) at temperature 0.3 with a repeat-specific cache salt (`planrep<N>`), so every repeat is a distinct sample; per-plan token cap 22,000. Repeats completed in full: 7 of 7.

| Repeat | Plans run | Valid without fallback | Final plan valid | Mean proposals to valid | Tokens |
|---|---|---|---|---|---|
| 1 | 8 of 8 | 8 | 100% | 1.0 | 47,718 |
| 2 | 8 of 8 | 8 | 100% | 1.0 | 47,753 |
| 3 | 8 of 8 | 8 | 100% | 1.25 | 54,608 |
| 4 | 8 of 8 | 8 | 100% | 1.25 | 57,766 |
| 5 | 8 of 8 | 8 | 100% | 1.38 | 57,947 |
| 6 | 8 of 8 | 8 | 100% | 1.0 | 48,441 |
| 7 | 8 of 8 | 8 | 100% | 1.25 | 54,081 |

Valid without fallback across completed repeats (min / mean / max): 8 / 8.0 / 8 of 8 scenarios.

Pooled over every plan run: 56 of 56 valid without fallback (100%); tokens 368,314.

| Scenario | Valid without fallback | Proposals to valid (per repeat; fb = fell back) | Tokens (per repeat) | First validator errors (per repeat) |
|---|---|---|---|---|
| Arrival shortfall (the demo student) | 7 of 7 | 1, 1, 1, 1, 1, 1, 1 | 6,244, 6,458, 6,219, 6,123, 6,250, 6,132, 6,128 | -; -; -; -; -; -; - |
| Tight runway | 7 of 7 | 1, 1, 1, 1, 1, 1, 1 | 6,120, 6,133, 6,515, 6,274, 6,016, 6,574, 6,051 | -; -; -; -; -; -; - |
| SAFE-quota tuition | 7 of 7 | 1, 1, 1, 2, 1, 1, 1 | 5,957, 5,930, 6,059, 9,092, 5,993, 5,990, 5,955 | -; -; -; safe_quota_exceeded; -; -; - |
| Late scholarship | 7 of 7 | 1, 1, 1, 1, 2, 1, 1 | 6,052, 6,022, 6,080, 6,087, 9,099, 6,089, 6,181 | -; -; -; -; insufficient_inr; -; - |
| Parent remitter crossing TCS | 7 of 7 | 1, 1, 1, 1, 1, 1, 1 | 4,717, 4,619, 4,630, 4,717, 4,724, 4,642, 4,643 | -; -; -; -; -; -; - |
| Rate target to protect | 7 of 7 | 1, 1, 1, 1, 1, 1, 1 | 6,286, 6,276, 6,247, 6,325, 6,865, 6,636, 6,316 | -; -; -; -; -; -; - |
| Five obligations | 7 of 7 | 1, 1, 1, 1, 1, 1, 1 | 6,366, 6,408, 6,410, 6,406, 6,521, 6,426, 6,482 | -; -; -; -; -; -; - |
| Urgent deposit | 7 of 7 | 1, 1, 3, 2, 3, 1, 3 | 5,976, 5,907, 12,448, 12,742, 12,479, 5,952, 12,325 | -; -; route_too_slow; route_too_slow; route_too_slow; -; route_too_slow |

- Invocation 2026-10-11 (repeats 1 and 2; 4 comma-separated keys, daily budget 180,000 tokens per key): new tokens 300,606 (cap 300,000); Groq daily ledger before 0, after 300,606. Live calls 89, cache hits 9, model fallbacks 15 (the last figure counts calls served by the fallback model).
- Invocation 2026-10-11 (repeat 3 only, `--repeats 3 --repeat-index 3 --token-cap 200000`): new tokens 162,737 (cap 200,000); Groq daily ledger before 300,606, after 463,343. Live calls 50, cache hits 4, model fallbacks 11.
- Invocation 2026-10-13: new tokens 146,221 (cap 200,000); daily ledger before 18, after 146,239. Live calls 46, cache hits 1, model fallbacks 0.
- Invocation 2026-10-13: new tokens 244,848 (cap 330,000); daily ledger before 146,239, after 391,087. Live calls 78, cache hits 49, model fallbacks 0.
- Invocation 2026-10-13: new tokens 56,493 (cap 120,000); daily ledger before 391,087, after 447,580. Live calls 21, cache hits 0, model fallbacks 0.
- Invocation 2026-10-13: new tokens 23,942 (cap 30,000); daily ledger before 447,580, after 471,522. Live calls 6, cache hits 0, model fallbacks 0.
- Invocation 2026-10-13: new tokens 16,800 (cap 30,000); daily ledger before 471,522, after 488,322. Live calls 3, cache hits 3, model fallbacks 0.
- Invocation 2026-10-13: new tokens 6,237 (cap 30,000); daily ledger before 488,322, after 494,559. Live calls 3, cache hits 0, model fallbacks 0.
- Invocation 2026-10-13: new tokens 46,125 (cap 120,000); daily ledger before 494,559, after 540,684. Live calls 21, cache hits 4, model fallbacks 0.
- Invocation 2026-10-13: new tokens 116,620 (cap 150,000); daily ledger before 540,684, after 657,304. Live calls 50, cache hits 27, model fallbacks 0.
- Invocation 2026-10-13: new tokens 150,079 (cap 150,000); daily ledger before 657,304, after 807,383. Live calls 71, cache hits 3, model fallbacks 0.
- Invocation 2026-10-18: new tokens 57,766 (cap 70,000); daily ledger before 517,548, after 575,314. Live calls 26, cache hits 1, model fallbacks 0.
- Invocation 2026-10-18: new tokens 57,947 (cap 70,000); daily ledger before 575,314, after 633,261. Live calls 26, cache hits 1, model fallbacks 0.
- Invocation 2026-10-18: new tokens 48,441 (cap 70,000); daily ledger before 633,261, after 681,702. Live calls 23, cache hits 1, model fallbacks 0.
- Invocation 2026-10-18: new tokens 54,081 (cap 70,000); daily ledger before 681,702, after 735,783. Live calls 25, cache hits 1, model fallbacks 0.
- Per-key tokens this invocation (1 key(s), by sha256 fingerprint): aws: 54,081; key rotations 0.

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

## Tool-result format experiment (old `v1` vs compact `v2`), 2026-10-11

Same settings as the earlier live runs: temperature 0.3, per-plan cap 22,000, cache salt `planrep<N>`, validator, scoring and fallback unchanged. Only what the model is shown changed (`oasis/planning/tools.py::present`). Details and caveats: docs/planner-efficiency.md (repository file `docs/planner-efficiency.md`). **Sample sizes are tiny; read the spread and the caveats.**

| Group | Plans | Model-only valid | Final plan valid (with fallback) | Fallbacks (reasons) | Mean proposals to valid | Tokens / plan | Calls / plan | Seconds / plan | Validator errors by code |
|---|---|---|---|---|---|---|---|---|---|
| original, old format, all 8 scenarios x 3 repeats | 24 | 7 (29%) | 24 of 24 | 17: the model never proposed a plan 4, token cap reached 10, no valid plan after 1 proposal(s) 2, RuntimeError 1 | 1.71 | 19,306 | 6.33 | 155 | amount_mismatch 9, insufficient_cny 1, insufficient_inr 6, rate_target_reserve 1, safe_quota_exceeded 1, unknown_route 5 (first proposal only) |
| original, old format, the 7 scenarios that ran under v2 (x 3 repeats) | 21 | 6 (29%) | 21 of 21 | 15: the model never proposed a plan 4, token cap reached 9, no valid plan after 1 proposal(s) 2 | 1.83 | 20,809 | 6.76 | 164 | amount_mismatch 9, insufficient_cny 1, insufficient_inr 6, rate_target_reserve 1, safe_quota_exceeded 1, unknown_route 5 (first proposal only) |
| original, new format, 7 scenarios x 1 repeat | 7 | 5 (71%) | 7 of 7 | 2: the model never proposed a plan 1, no valid plan after 2 proposal(s) 1 | 2.2 | 15,459 | 6.14 | 106 | amount_mismatch 18, duplicate_payment 1, insufficient_cny 2, rate_target_reserve 1, unknown_route 2 (every proposal) |
| held-out, old format, 4 x 1 | 4 | 3 (75%) | 4 of 4 | 1: token cap reached 1 | 1.67 | 13,848 | 4.75 | 115 | insufficient_cny 2 (every proposal) |
| held-out, new format, 4 x 1 | 4 | 3 (75%) | 4 of 4 | 1: the model never proposed a plan 1 | 2.33 | 16,752 | 6.0 | 122 | amount_mismatch 4, insufficient_cny 3 (every proposal) |
| pooled original (same scenarios) + held-out, old format | 25 | 9 (36%) | 25 of 25 | 16: the model never proposed a plan 4, token cap reached 10, no valid plan after 1 proposal(s) 2 | 1.78 | 19,696 | 6.44 | 156 | amount_mismatch 9, insufficient_cny 3, insufficient_inr 6, rate_target_reserve 1, safe_quota_exceeded 1, unknown_route 5 (first proposal only) |
| pooled original + held-out, new format | 11 | 8 (73%) | 11 of 11 | 3: the model never proposed a plan 2, no valid plan after 2 proposal(s) 1 | 2.25 | 15,929 | 6.09 | 112 | amount_mismatch 22, duplicate_payment 1, insufficient_cny 5, rate_target_reserve 1, unknown_route 2 (every proposal) |

Per-repeat model-only valid (valid out of plans): original, old format, all 8 scenarios x 3 repeats: 4/8, 2/8, 1/8; original, old format, the 7 scenarios that ran under v2 (x 3 repeats): 3/7, 2/7, 1/7; original, new format, 7 scenarios x 1 repeat: 5/7; held-out, old format, 4 x 1: 3/4; held-out, new format, 4 x 1: 3/4; pooled original (same scenarios) + held-out, old format: 6/11, 2/7, 1/7; pooled original + held-out, new format: 8/11

- Spend: 230,613 new tokens on 2026-10-11 (key fingerprints: ceef6c23 80,651; a1d412ac 149,962; 499b1366 0; d40d45b2 0), 19 plans plus one re-run, under the ~250k cap.
- Not run for lack of budget: a second repeat of the new format, and the urgent-deadline scenario in the new format. The old-format comparison for the original scenarios is the three repeats already recorded (24 plans, 2026-10-11, other key state).
- One new-format plan (multiple_obligations) was first stopped at 12,362 tokens by the run-level cap, not by the model; that row was discarded as a budget artifact and the plan resumed (its first calls replay from the disk cache, so its tokens are recorded as 12,362 + 4,730 and its seconds cover only the resumed part).
- Old-format error counts for the original scenarios exist only for the first proposal; all other groups count every validator error the live model drew.
- Fisher exact tests (two-sided, uncorrected): original same scenarios new 5/7 vs old 6/21 gives p about 0.076; pooled new 8/11 vs old 9/25 gives p about 0.070. Neither is conclusive. The held-out result is 3/4 vs 3/4: no measurable difference.

## Caveats

- Eight hand-written scenarios; a pass here shows the planner and validator agree on these cases, not general optimality.
- The validator checks feasibility and the stated rules; it does not search for the globally cheapest plan. 'Fees vs bank' compares with the typical bank route only.
- Corridor figures (SAFE quota, LRS, TCS) are researched, not officially confirmed; the SAFE quota is modelled as USD 50,000 equivalent per calendar year at a mock USD/INR of 88.
- Offline results are deterministic. A live result is a small number of samples from one model (see the repeat counts above), cached on disk; it is not a robustness claim.
