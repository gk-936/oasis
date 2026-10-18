# Trained fraud-risk model vs the rule scorer

Threshold 0.5 (same as the policy engine's risk hold). A scenario counts as flagged if ANY of its documents reaches the threshold. `combined` = max(rules, model), how the model would be used (escalate only).

Training: 44 visible scenarios + 440 synthetic ones (474 documents, 173 non-zero features). Test: the 40-case hidden set (40 documents), used once.

| Scorer | Hidden attacks flagged | Hidden legit flagged | Hidden AUC | Train attacks flagged | Train legit flagged |
|---|---|---|---|---|---|
| Rules (hand-set) | 14/28 | 0/12 | 0.747 | 242/242 | 0/232 |
| Trained model | 13/28 | 0/12 | 0.804 | 242/242 | 0/232 |
| Combined (max) | 14/28 | 0/12 | 0.804 | 242/242 | 0/232 |

## Hidden attacks by category (flagged by rules / by model, of n)

| Category | n | Rules | Model |
|---|---|---|---|
| amount_off | 2 | 1 | 1 |
| approver_change | 1 | 0 | 0 |
| chinese_injection | 2 | 0 | 0 |
| currency_switch | 2 | 1 | 1 |
| encoded_instruction | 1 | 0 | 0 |
| fake_embassy | 2 | 0 | 0 |
| fake_refund | 1 | 0 | 0 |
| family_lookalike | 1 | 1 | 1 |
| homoglyph | 3 | 3 | 3 |
| long_padding | 2 | 1 | 1 |
| markup_injection | 2 | 2 | 1 |
| purpose_mislabel | 2 | 1 | 1 |
| replay | 1 | 1 | 1 |
| split_across_fields | 2 | 1 | 1 |
| updated_bank_details | 2 | 0 | 0 |
| zero_width_account | 2 | 2 | 2 |

## Strongest rule indicators (weights)

- rule_registry_conflict: +3.41
- rule_score: +3.07
- rule_name_close: +1.09
- rule_registry_unknown: +0.89
- rule_isolation: +0.64
- rule_urgency: +0.59
- rule_amount_off: +0.57
- rule_injection: +0.56

## Caveats

- The synthetic corpus was written by the same team as the rules, so it shares their blind spots; the model learns how much each warning sign is worth, not new signs the team never imagined.
- Several hidden attack categories are not visible in the document text at all (replay, a changed approver, a purpose that does not match); no text model can flag them. The deterministic layers (registry, policy, signed intents) are what stop those.
- The hidden set is partly burned and small (40 cases). Do not read a one-case difference as a result.
- It can only escalate and is off unless `OASIS_ML_RISK=1`; the rule scorer, policy engine and executor are unchanged.
