# Planner token efficiency (live tool-calling planner)

Goal: raise the share of live plans that are valid **without** falling back to the deterministic plan (the "model-only valid rate"), without hiding failures. The validator, its rules, the scoring and the fallback were not touched. Results table: `eval/reports/planning.md` (section "Tool-result format experiment"), raw rows: `eval/reports/planning_experiment.json` and `planning.json` (key `experiment`).

## (a) Where the tokens go

Measured on the scenario worlds (`oasis/planning/tools.py`, `oasis/agent/planner.py`) and in the recorded live rows (24 plans, 2026-10-11, old format). Character counts are exact; token figures use about 4 characters per token and are estimates (the Groq tokenizer was not run locally).

| Item | Size | Notes |
|---|---|---|
| System prompt | 2,201 chars (about 550 tokens) | re-sent on every model call |
| Tool schemas (7 tools) | 2,602 chars (about 650 tokens) | re-sent on every model call |
| Fixed overhead per call | about 1,200 tokens | times 6.3 calls per plan on average = about 7,600 of the 19,306 mean tokens per plan (about 39%) |
| First-turn tool results (read_passport, list_obligations, get_rates, forecast_runway, get_routes, check_corridor) | 3,334 to 3,578 chars | `get_rates` alone is 1,151 chars (route table plus provenance block and note); the rest sits in the context for every later call |
| Invalid `propose_plan` result | about 700 chars for 3 errors | each error carries a code, a message with the numbers, a hint and the step |
| A plan proposal (assistant message) | roughly 100 to 150 tokens per step | the whole plan is re-sent on each revision and stays in the context |
| Calls per plan | 6.33 mean (cap 8) | proposals per plan 2.21 mean |
| Tokens per plan | 19,306 mean, cap 22,000 | 10 of 24 plans were stopped by the cap while still revising |
| Latency per plan | 155 s mean | dominated by the free-tier per-minute limits and waits, not generation |

Where the first validator errors came from (old format, first proposal, 24 plans): `amount_mismatch` 9, `insufficient_inr` 6, `unknown_route` 5, `safe_quota_exceeded` 1, `insufficient_cny` 1, `rate_target_reserve` 1. Fallback reasons (17 of 24): token cap 10, the model never proposed within its call budget 4, no valid plan after one proposal 2, API error 1.

## (b) The one change tried: compact tool results (`v2`)

`oasis/planning/tools.py::present` builds the view the model sees; the toolbox, the trace, the UI and the offline `DeterministicPlanner` still use the full results. `PLANNER_FORMAT` / `OASIS_PLANNER_FORMAT=v1` restores the old view (it is kept as a switch, not reverted).

- `read_passport`: dropped student name, funding source, monthly budget, Tier-1 limit and approvers; rate targets reduced to rate and CNY amount; income to label, amount and date.
- `list_obligations`: only the obligations to fund (id, type, payee, exact amount, due date) plus a list of ids that are not part of the plan.
- `get_rates`: id, days, fixed fee, percentage fee and spread per route plus the mid rate (no provenance block, names, reliability or prose note; the typical bank route is flagged).
- `get_routes`, `check_corridor`, `forecast_runway`: dropped echoes of the request, names and notes.
- `propose_plan` errors: code, message, hint and step are kept verbatim (the same codes and text); only the `iteration` and `instruction` fields are dropped.

Size of the first-turn results: 3,334 to 3,578 chars before, 1,621 to 1,779 after (about 50% less, roughly 400 tokens per plan at the point they are first sent, and again on each later call that carries them).

Tests (`tests/test_planning.py`): the compact view keeps every fact the model acts on (ids, exact amounts, payees, due dates, balances, SAFE quota and use per year, LRS, remitted INR, rate-target numbers, expected income, route ids, days, fees, delivered CNY, on-time flag, the bank route flag), `v1` returns the untouched result, and for mutated invalid plans covering 11 validator error codes (amount_mismatch, unknown_route, payee_mismatch, obligation_unfunded, duplicate_payment, late_payment, date_in_past, insufficient_inr, insufficient_cny, bad_step, safe_quota_exceeded) the compact errors are identical to the full ones in code, message, hint and step. `rate_target_reserve` is exercised in the live scenarios but its mutation is not in the test; `lrs_exceeded` and a few rarely seen codes are untested here.

## (c) Evaluation

Same settings as before: temperature 0.3, per-plan cap 22,000, cache salt `planrep<N>`, same validator. Four new held-out scenarios (`oasis/planning/scenarios.py::HELDOUT`, ids prefixed `heldout_`) were written from first principles **before** any live result of `v2` was seen and were never used to tune anything: two obligations to one landlord payee per date (student and a flatmate), a CNY 350,000 tuition due after the SAFE calendar-year boundary with a parent-covered shortfall, a late scholarship plus a rate target, and a deposit plus rent plus tuition on a thin margin. The deterministic planner solves all four (a feasibility check, not tuning).

Budget: 230,613 new tokens (key ceef6c23 80,651; a1d412ac 149,962; 499b1366 and d40d45b2 0 because they were already spent), under the ~250k cap. Therefore only one repeat of the new format was run, and the urgent-deadline scenario was not run in the new format. One plan (multiple_obligations) was cut by the run-level cap rather than by the model; that row was discarded and the plan resumed (its recorded tokens are 12,362 + 4,730; seconds cover only the resumed part).

| Group | Plans | Model-only valid | Mean proposals to valid | Tokens / plan | Calls / plan | Seconds / plan |
|---|---|---|---|---|---|---|
| original, old format (same 7 scenarios, 3 repeats) | 21 | 6 (29%); per repeat 3/7, 2/7, 1/7 | 1.83 | 20,809 | 6.76 | 164 |
| original, new format (7 scenarios, 1 repeat) | 7 | 5 (71%) | 2.2 | 15,459 | 6.14 | 106 |
| held-out, old format (1 repeat) | 4 | 3 (75%) | 1.67 | 13,848 | 4.75 | 115 |
| held-out, new format (1 repeat) | 4 | 3 (75%) | 2.33 | 16,752 | 6.0 | 122 |
| pooled, old | 25 | 9 (36%) | 1.78 | 19,696 | 6.44 | 156 |
| pooled, new | 11 | 8 (73%) | 2.25 | 15,929 | 6.09 | 112 |

The final plan was valid in every case in every group, only because a fallback is the deterministic plan. Fallback reasons, new format: the model never proposed a plan 2 (shortfall, heldout_year_boundary: both need a parent remitter and the model used all 8 calls on tools), no valid plan after 2 proposals 1 (rate_target). Old format held-out: one token-cap stop (heldout_year_boundary, 25,054 tokens). Validator error counts by code are in `eval/reports/planning.md`.

## Result and verdict

- Original scenarios: model-only valid 71% (5/7) against 29% (6/21; per-repeat range 14% to 43%), tokens per plan down 26%. This is above the old spread, but it is one repeat of seven plans: Fisher exact p about 0.08.
- Held-out scenarios: 3/4 under both formats, no measurable difference (and the new format used more calls on average).
- Pooled: 73% against 36% (+37 points, p about 0.07). That meets the "at least +15 points" bar numerically, but with 11 new plans it is not a statistically conclusive result, the old and new runs were made under different API key states and rate-limit conditions, and the held-out set, which is the unbiased check, shows no gain.
- Latency fell (112 s against 156 s per plan) but is confounded by rate-limit waits, so it is not claimed as an effect.
- The failure mode the change did not touch: the model sometimes spends its whole call budget on tools and never proposes (2 of 11 new-format plans, 4 of 24 old).

Decision: `v2` stays the default because it was at least as good on every comparison and cheaper per plan, and it is switchable to `v1`. No second change (schema or output-format compaction) was tried: the stopping rule was one or two changes, the budget was spent, and chasing further gains on these samples would be tuning to noise. Conclusion: the evidence suggests compact results help the original scenarios and does not show a gain on held-out ones. A repeat run on a fresh daily budget (at least 3 repeats of all 12 scenarios per format) is needed before calling it an improvement.

## v3: calculator tools — protocol and pre-registered evaluation

Status (2026-10-11): **built and tested offline; no live result exists.** `v2` stays the default. v3 is selected with `OASIS_PLANNER_FORMAT=v3` (or `AgenticPlanner(llm, fmt="v3")`, or `--format v3` in the evaluation CLI). `v1` and `v2` are byte-for-byte unchanged (snapshot test in `tests/test_planning_v3.py`, fixture `tests/snapshots/planner_v1_v2.json`, taken before the change).

### Why

In the live runs most validator errors were arithmetic (`amount_mismatch` 22 times, `insufficient_cny`, `unknown_route`): the model computed INR amounts, fees and rounding in its head. Plans also hit the token cap (22-25k tokens per 4-proposal plan). Principle: give the model calculators and make errors actionable, while the model still writes the plan. No code repairs a plan, so "model-only valid" stays a pure measurement. The validator rules, severities, scoring and fallback are untouched.

### Protocol

The model is offered three tools (v1/v2 offer seven; the v3 tool schemas are 1,908 characters against 2,748):

| Tool | Fields | Result |
|---|---|---|
| `facts_sheet()` | none | obligations to fund (id, payee_id, exact `amount_cny`, `due`); `cny_needed` total, by month, by year; `balances`; `rate_target_reserve_inr`; `student_spendable_inr`; `cny_shortfall`; `inr_needed_est` and `inr_short_est` (cheapest non-bank route); `safe` (quota, left per calendar year, `new_year_starts`); `student` and `parent` (`remitted_inr_fy`, `lrs_left_inr`, `tcs_free_left_inr`; parent also `consent_needed`, `tcs_rate`); `routes` (id, days, fixed fee, pct fee, spread). Numbers only; 1.1k-1.5k characters in all 12 scenarios (about 300-400 tokens). |
| `size_conversion(target_cny, route_id, convert_date, remitter?, due?)` | `target_cny` number, `route_id`, `convert_date` YYYY-MM-DD, `remitter` student (default) or parent, `due` optional | `send_inr` (smallest whole rupee delivering at least `target_cny` plus CNY 1.00 headroom, which covers 2-decimal rounding), `delivered_cny`, `arrives_on`, `effective_rate`, `on_time` and `latest_convert_date` when `due` is given, `safe` (year, room, fits, stage-rest date), `tcs_inr`, `lrs_ok`. A pure function of the world and the rates. |
| `propose_plan(steps, rationale)` | unchanged | unchanged, except errors may carry `fix` |

Neither new tool changes state or moves money (state-hash test); the toolbox only answers them in v3.

`fix` (v3 presentation only; the error keeps its code, message, hint and step, and the validator itself never emits it; `oasis/planning/fixes.py`):

| Error code | `fix` carries |
|---|---|
| `amount_mismatch` | `set.amount_cny` = the remaining amount |
| `payee_mismatch`, `unknown_payee` | `set.payee_id` = the obligation's payee |
| `late_payment` | `latest_date` and `set.date` |
| `date_in_past` | `set.date` = today |
| `duplicate_payment` | `remove_step` |
| `obligation_unfunded` | `add_pay` with date, id, payee and exact amount |
| `unknown_route` | `set.route_id` = best route that still arrives for the next payment |
| `insufficient_cny` | `short_cny` and `add_convert` (cheapest on-time route; `send_inr` equals what `size_conversion` returns), or the earliest pay date when no route can arrive |
| `insufficient_inr` | `over_inr`, `set.send_inr` reduced to the balance, `add_convert` for the parent that preserves the delivered CNY |
| `rate_target_reserve` | same shape as `insufficient_inr`, for the INR the reserve is short |
| `safe_quota_exceeded` | `max_send_inr`, `stage_on` (next 1 January), `set.send_inr`, `add_convert` for the rest with its `arrives_on`; or `set.date` when no room is left |
| `route_too_slow` | `convert_by` (latest convert date for that route), `faster_route_ids`, `pay_date`, and the `set` that applies |

Codes with no derivable correction (`bad_step`, `bad_date`, `bad_amount`, `lrs_exceeded`, ...) carry no `fix`. The tests apply the fix of each code above to a mutated plan and check that the code's error disappears (other errors may follow; that is the model's loop).

Prompt: `SYSTEM_V3` is 1,089 characters against 2,201 for v2 (49%; the test limit is 60%). It says: call `facts_sheet` first, copy obligations exactly, size every conversion with `size_conversion`, never compute INR, propose once, apply each `fix` and change nothing else. The per-plan cap logic (`token_cap`, 8 calls, 4 proposals) and the deterministic fallback are exactly as before. The offline `DeterministicPlanner` is unchanged and gives identical plans under v1, v2 and v3.

Offline proof that the protocol works: a scripted "model" in the tests (facts_sheet, then `size_conversion`, one proposal, then apply each `fix`) runs through `GroqLLM.chat_tools` with a fake client and produces a model-only valid plan in all 12 scenarios (1 to 3 proposals). This shows the protocol is workable, not that a real model will use it well.

### Pre-registered evaluation

Rule, fixed before any live v3 result: v3 becomes the default only if, pooled over the models that ran both formats, (A) its model-only valid rate beats v2's by at least 15 percentage points plus v2's observed spread (the widest max-minus-min of v2's per-repeat rates in any model cell; needs two complete repeats), and (B) the held-out scenarios do not regress (v3 held-out rate at least v2's). Otherwise v2 stays. The Fisher exact p is reported but is not part of the rule. The report prints the rule, and the verdict is `INCOMPLETE` until every compared cell has two complete repeats.

Design: 12 scenarios (8 original + 4 `heldout_*`) x 2 repeats = 24 plans per format-model cell; four cells for two formats and two models. Temperature 0.3, a repeat-specific cache salt, per-plan cap 22,000 for both formats, and the fallback model pinned to the tested model (no cross-model contamination). Rows are keyed (format, model, repeat, scenario) in `eval/reports/planning_v3_rows.json`, written after every plan, and finished keys are skipped on re-run. A plan is not started unless the run cap leaves room for a whole per-plan cap, and a plan that ended on an API or quota error is discarded, not recorded.

Commands (to run later, when the daily budget is back; each call is resumable):

```
export PYTHONPATH=.
python -m eval.planning_v3 --format v3 --model qwen/qwen3.8-27b    --repeats 2 --cap 450000
python -m eval.planning_v3 --format v2 --model qwen/qwen3.8-27b    --repeats 2 --cap 450000
python -m eval.planning_v3 --format v3 --model openai/gpt-oss-120b --repeats 2 --cap 450000
python -m eval.planning_v3 --format v2 --model openai/gpt-oss-120b --repeats 2 --cap 450000
python -m eval.planning_v3 --report        # offline: re-render eval/reports/planning_v3.md and .json
```

Other options: `--rep N` runs one repeat, `--only id,id` selects scenarios, `--per-plan-cap N` sets the per-plan cap, and `OASIS_PLANNER_MODEL` sets the default model. Exit code 2 means the run cap was reached; 3 means the API or daily quota failed (call again later).

Token budget (an estimate): v3 is aimed at 12-15k tokens per plan, so about 290-360k per v3 cell; v2 measured 15-20k per plan, so about 360-480k per v2 cell; about 1.3-1.7M tokens for all four cells. Budgets are per key: `OASIS_GROQ_DAILY_TOKENS` (default 180000) and `OASIS_GROQ_DAILY_REQUESTS` (default 900) apply to each key in `GROQ_API_KEY` separately (a comma-separated list), so keys times the daily budget decides how many days the run takes; one cell needs roughly 150-200 requests. The v3 token figure is a target, not a measurement.

The report table (format x model) shows: model-only valid rate with per-repeat values and spread, final-valid rate (inflated by the fallback), fallback rate and reasons, validator errors by code, arithmetic-error share (`amount_mismatch`, `insufficient_cny`, `insufficient_inr`, `rate_target_reserve`, `safe_quota_exceeded`), mean proposals to valid, tokens, calls and seconds per plan, the v3-vs-v2 Fisher exact p (per model and pooled), held-out and per-scenario breakdowns, and the decision.
