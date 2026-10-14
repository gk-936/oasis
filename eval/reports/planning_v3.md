# Planner format v3 (calculator tools) vs v2: pre-registered evaluation

> Rows for the qwen and gpt-oss models are a historical run on the Groq provider, which has since been removed; Amazon Nova Pro on Bedrock is now the only live provider.

Scored by the deterministic plan validator, never by a model. 12 scenarios per repeat (8 original + 4 held-out `heldout_*`), temperature 0.3, a repeat-specific cache salt, the same per-plan token cap for both formats. **Model-only valid** = the model's own proposal passed the validator and no deterministic fallback was used. Protocol and commands: [docs/planner-efficiency.md](../../docs/planner-efficiency.md).

Pre-registered decision rule (fixed before any live v3 result existed): v3 becomes the default planner format only if BOTH hold, on the plans pooled over every model that ran both formats: (A) the model-only valid rate of v3 exceeds that of v2 by at least 15 percentage points PLUS the observed spread of v2 (the widest max-minus-min of v2's per-repeat model-only valid rates in any model cell; needs at least two complete repeats); and (B) the held-out scenarios do not regress (v3 held-out model-only valid rate >= v2's). Otherwise v2 stays the default. The Fisher exact p-value is reported for context and is not part of the rule.

## Cells (format x model)

| Format | Model | Plans | Model-only valid | Per repeat (valid/12) and spread | Final valid | Fallbacks (reasons) | Mean proposals to valid | Tokens / plan | Calls / plan | Seconds / plan |
|---|---|---|---|---|---|---|---|---|---|---|
| v2 | openai/gpt-oss-120b | 2 | 1 (50%) | 1/2*; spread n/a (<2 complete repeats) | 2 of 2 | 1 (50%): malformed tool call 1 | 1.0 | 4,898.0 | 3.5 | 22.0 |
| v2 | qwen/qwen3.8-27b | 24 | 4 (17%) | 2/12, 2/12; range 17-17% (0 pp) | 24 of 24 | 20 (83%): malformed tool call 15, never proposed 1, no valid plan after proposals 4 | 3.5 | 10,787.0 | 4.25 | 91.0 |
| v3 | openai/gpt-oss-120b | 24 | 14 (58%) | 8/12, 6/12; range 50-67% (17 pp) | 24 of 24 | 10 (42%): malformed tool call 1, never proposed 4, no valid plan after proposals 4, stopped without a plan 1 | 1.07 | 10,349.0 | 6.25 | 57.0 |
| v3 | qwen/qwen3.8-27b | 24 | 4 (17%) | 2/12, 2/12; range 17-17% (0 pp) | 24 of 24 | 20 (83%): malformed tool call 20 | 2.25 | 3,493.0 | 2.67 | 41.0 |

`*` = an incomplete repeat (not used for the spread). Final valid counts the deterministic fallback plan, so it is high by construction.

## Validator errors by code (every proposal the model made)

Arithmetic codes (the number was wrong): `amount_mismatch`, `insufficient_cny`, `insufficient_inr`, `rate_target_reserve`, `safe_quota_exceeded`. Other codes (copying, routing, dates, payee) are not counted as arithmetic; `unknown_route` is a copy error.

| Format | Model | Errors | Arithmetic share | By code |
|---|---|---|---|---|
| v2 | openai/gpt-oss-120b | 0 | - (0) | - |
| v2 | qwen/qwen3.8-27b | 43 | 100% (43) | amount_mismatch 22, insufficient_cny 14, insufficient_inr 5, rate_target_reserve 2 |
| v3 | openai/gpt-oss-120b | 9 | 100% (9) | insufficient_cny 3, insufficient_inr 5, safe_quota_exceeded 1 |
| v3 | qwen/qwen3.8-27b | 10 | 80% (8) | amount_mismatch 4, insufficient_cny 1, insufficient_inr 3, unknown_route 2 |

## v3 vs v2

| Comparison | v3 model-only valid | v2 model-only valid | Delta (pp) | Fisher exact p (two-sided) | Held-out v3 | Held-out v2 |
|---|---|---|---|---|---|---|
| openai/gpt-oss-120b | 14/24 (58%) | 1/2 (50%) | +8 | 1.000 | 4/8 | 0/0 |
| qwen/qwen3.8-27b | 4/24 (17%) | 4/24 (17%) | +0 | 1.000 | 1/8 | 1/8 |
| pooled | 18/48 (38%) | 5/26 (19%) | +18 | 0.123 | 5/16 | 1/8 |

Pooled rows add the models together; the per-model rows are shown so one model cannot hide in the pool. Cells with different tests are not mixed.

## Decision

**INCOMPLETE** - needs every compared cell (v2 and v3, each model) to have at least two complete repeats of all 12 scenarios. Observed pooled delta so far: +18 pp. v2 stays the default until the rule can be applied.

## Per scenario (model-only valid across repeats)

| Scenario | v2 | openai/gpt-oss-120b | v2 | qwen/qwen3.8-27b | v3 | openai/gpt-oss-120b | v3 | qwen/qwen3.8-27b |
|---|---|---|---|---|
| shortfall | 0/1 | 0/2 | 1/2 | 2/2 |
| tight_runway | 1/1 | 0/2 | 2/2 | 0/2 |
| safe_quota_tuition | - | 0/2 | 0/2 | 0/2 |
| late_scholarship | - | 0/2 | 1/2 | 0/2 |
| parent_tcs | - | 0/2 | 2/2 | 1/2 |
| rate_target | - | 0/2 | 0/2 | 0/2 |
| multiple_obligations | - | 2/2 | 2/2 | 0/2 |
| urgent_deadline | - | 1/2 | 2/2 | 0/2 |
| heldout_shared_landlord | - | 1/2 | 2/2 | 1/2 |
| heldout_year_boundary | - | 0/2 | 0/2 | 0/2 |
| heldout_scholarship_target | - | 0/2 | 1/2 | 0/2 |
| heldout_deposit_rent_tuition | - | 0/2 | 1/2 | 0/2 |

## Caveats

- 24 plans per cell is a small sample; read the spread and the Fisher p. The rule above, not a single table cell, decides.
- Model-only valid is a property of this validator and these 12 mock scenarios; it is not a claim about real payments.
- Token and latency figures include free-tier rate-limit waits and are not a clean performance measurement.
