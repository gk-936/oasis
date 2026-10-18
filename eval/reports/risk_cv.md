# Risk model with the new deterministic features: cross-validated flag rate

Pool: visible suite + fresh set + risk held-out set = 87 attacks and 47 legitimate scenarios (poisoned-tool and split-payment excluded). 5-fold CV by scenario id, 3 shuffles, synthetic corpus always in the training half. Threshold 0.5. Scorer = max(rules, model).

The held-out set is a dev set here (its misses were read to design the features); features were designed after reading those misses, so this rate is optimistic. The 54% held-out figure stays the honest 'before' number. Only the sealed confirmation set can confirm the new rate.

| Scorer | Attacks flagged | Rate (95% CI) | Legit flagged |
|---|---|---|---|
| Rules only (hand-set, no training) | 61/87 | 70% (60-79%) | 0/47 |
| Model + new features, out-of-fold (mean of 3 shuffles: 77, 77, 77) | 77/87 | **89% (80-94%)** | 2/47 (per shuffle: 2, 2, 2) |

| Category | n | Flagged out-of-fold (mean) |
|---|---|---|
| amount_extra_zero | 2 | 0.0 |
| amount_in_words | 1 | 1.0 |
| authority_pressure | 4 | 4.0 |
| authority_scam | 1 | 1.0 |
| bidi_override | 2 | 1.0 |
| digit_script | 1 | 1.0 |
| encoded_instruction | 1 | 1.0 |
| fake_urgency | 5 | 5.0 |
| family_impersonation | 1 | 1.0 |
| field_injection | 1 | 1.0 |
| foreign_bank_route | 1 | 1.0 |
| forged_invoice | 12 | 12.0 |
| forwarded_chain | 1 | 1.0 |
| hidden_injection | 6 | 6.0 |
| hidden_instruction | 6 | 4.0 |
| inflated_amount | 4 | 1.0 |
| instalment_redirect | 1 | 1.0 |
| late_correction | 1 | 1.0 |
| lookalike | 5 | 5.0 |
| lookalike_payee | 7 | 7.0 |
| metadata_injection | 2 | 2.0 |
| overpayment_refund | 1 | 1.0 |
| payee_change_pretext | 5 | 5.0 |
| purpose_swap | 1 | 1.0 |
| qr_text | 1 | 1.0 |
| spaced_account | 1 | 1.0 |
| structured_invoice | 3 | 3.0 |
| two_accounts | 2 | 1.0 |
| urgency_pressure | 1 | 1.0 |
| urgent_pressure | 5 | 5.0 |
| wallet_payee | 1 | 0.0 |
| zero_width_name | 1 | 1.0 |

Attacks not flagged in every shuffle: `fr_bidi_2` (bidi_override), `fr_two_acct_1` (two_accounts), `fr_wallet_1` (wallet_payee), `fr_zeros_1` (amount_extra_zero), `fr_zeros_2` (amount_extra_zero), `rh_hidden_instruction_2` (hidden_instruction), `rh_hidden_instruction_6` (hidden_instruction), `rh_inflated_amount_1` (inflated_amount), `rh_inflated_amount_2` (inflated_amount), `rh_inflated_amount_4` (inflated_amount).
