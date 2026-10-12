# Local models (Ollama) as the planner: exploratory evaluation

**Exploratory and separate.** Not part of the pre-registered v3-vs-v2 verdict (`eval/reports/planning_v3.md`). Local models only (nothing leaves the machine), temperature 0.3, repeat-specific seeds, 12 scenarios (8 original + 4 held-out `heldout_*`) x 2 repeats. Scored by the deterministic validator. **Model-only valid** = the model's own proposal passed within its budget (v4: 1 + 3 revisions; v2: 4 proposals / 8 calls) and no deterministic fallback was used; **pass@1** = the first proposal was valid. **Generate-and-verify** (v4 only) = up to 3 independent first proposals, the first the validator accepts; it uses the validator as a filter and is NOT the model-only number. Reference (Groq, other protocol): gpt-oss-120b v3: 14/24 (58%), Groq, model-only valid.

## Cells

| Model | Format | Plans | Model-only valid | pass@1 | Original / held-out model-only | Generate-and-verify (up to 3) | Final valid (incl. fallback) | Fallbacks (reasons) | Mean proposals to valid | Tokens / plan | Seconds / plan | GPU share |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| phi4-mini | v4, exploratory (constrained JSON) | 24 | 7/24 (29%) | 1/24 (4%) | 6/16 / 1/8 | 2/24 (8%); held-out 1/8; +21.4 s/plan | 24 of 24 | 17: no valid plan after proposals 17 | 2.57 | 9,922.0 | 39.7 | 100% |
| qwen3.5:4b | v4, exploratory (constrained JSON) | 24 | 19/24 (79%) | 4/24 (17%) | 13/16 / 6/8 | 9/24 (38%); held-out 4/8; +29.5 s/plan | 24 of 24 | 5: no valid plan after proposals 5 | 2.37 | 8,253.0 | 55.7 | 100% |

Final valid counts the deterministic fallback plan, so it is high by construction. Seconds include model load on the first plan of a cell.

## Validator errors by code (every proposal the model made; generate-and-verify extra samples excluded)

| Model | Format | Errors | Arithmetic share | By code |
|---|---|---|---|---|
| phi4-mini | v4 | 180 | 80% (144) | bad_amount 2, duplicate_payment 20, insufficient_cny 84, insufficient_inr 38, obligation_unfunded 2, rate_target_reserve 5, route_too_slow 12, safe_quota_exceeded 17 |
| qwen3.5:4b | v4 | 61 | 85% (52) | bad_amount 2, insufficient_cny 35, insufficient_inr 9, obligation_unfunded 4, rate_target_reserve 3, route_too_slow 3, safe_quota_exceeded 5 |

Arithmetic codes: `amount_mismatch`, `insufficient_cny`, `insufficient_inr`, `rate_target_reserve`, `safe_quota_exceeded`.

## Per scenario (model-only valid across repeats)

| Scenario | phi4-mini | v4 | qwen3.5:4b | v4 |
|---|---|---|
| shortfall | 2/2 | 2/2 |
| tight_runway | 1/2 | 2/2 |
| safe_quota_tuition | 0/2 | 1/2 |
| late_scholarship | 2/2 | 1/2 |
| parent_tcs | 0/2 | 2/2 |
| rate_target | 0/2 | 1/2 |
| multiple_obligations | 0/2 | 2/2 |
| urgent_deadline | 1/2 | 2/2 |
| heldout_shared_landlord | 1/2 | 2/2 |
| heldout_year_boundary | 0/2 | 1/2 |
| heldout_scholarship_target | 0/2 | 1/2 |
| heldout_deposit_rent_tuition | 0/2 | 2/2 |

## Memory and context

- phi4-mini | v4: largest prompt 5978 tokens, calls whose prompt reached num_ctx (silent truncation risk): 0; GPU share of the loaded model: 100%.
- qwen3.5:4b | v4: largest prompt 4200 tokens, calls whose prompt reached num_ctx (silent truncation risk): 0; GPU share of the loaded model: 100%.

## Caveats

- 24 plans per cell is a small sample; differences of a few plans are noise.
- Model-only valid is a property of this validator and these 12 mock scenarios, not of real payments.
- v4 shows the model the validator's `fix` hints on revisions and a route table; v2 does not. The formats differ in more than the output channel, so this is not a clean format comparison.
