# Risk scorers on the fresh attack set (out of sample)

Fresh set: `eval/fresh/scenarios_fresh.json` (sha256 `4d0073914f551706a6087eaad14ea9d10b5b423d4bfb75c3c0650ab7531a7ba9`); the shipped model was trained before this set existed and is unchanged. Threshold 0.5; a scenario is flagged if ANY of its documents reaches it. Poisoned-tool cases are excluded (their text is innocent).

| Scorer | Attacks flagged | Legit flagged | AUC |
|---|---|---|---|
| Rules (hand-set) | 16/30 | 0/16 | 0.806 |
| Trained model | 16/30 | 0/16 | 0.922 |
| Combined (max) | 16/30 | 0/16 | 0.922 |

Cross-validation of the model on its own training corpus (5 folds split by scenario): AUC 1.000 +/- 0.000. The corpus was written by the team, so this measures stability, not generalisation.

## Fresh attacks by category (flagged by rules / by model, of n)

| Category | n | Rules | Model |
|---|---|---|---|
| amount_extra_zero | 2 | 0 | 0 |
| amount_in_words | 1 | 1 | 1 |
| authority_scam | 1 | 0 | 0 |
| bidi_override | 2 | 1 | 1 |
| digit_script | 1 | 1 | 1 |
| encoded_instruction | 1 | 0 | 0 |
| family_impersonation | 1 | 0 | 0 |
| field_injection | 1 | 0 | 0 |
| foreign_bank_route | 1 | 0 | 0 |
| forwarded_chain | 1 | 0 | 0 |
| instalment_redirect | 1 | 1 | 1 |
| late_correction | 1 | 0 | 0 |
| lookalike_payee | 2 | 2 | 2 |
| metadata_injection | 2 | 2 | 2 |
| overpayment_refund | 1 | 0 | 0 |
| purpose_swap | 1 | 1 | 1 |
| qr_text | 1 | 0 | 0 |
| spaced_account | 1 | 1 | 1 |
| structured_invoice | 3 | 3 | 3 |
| two_accounts | 2 | 1 | 1 |
| urgency_pressure | 1 | 1 | 1 |
| wallet_payee | 1 | 0 | 0 |
| zero_width_name | 1 | 1 | 1 |

## Reading this

- The scorers only ever ESCALATE a decision. What stops an attack that the text scorers miss is the registry check, the policy engine and the signed intent (see `benchmark_fresh.md`); the scorer is a second opinion on the wording.
- 49 cases, written by an AI assistant that had read parts of the defence code: fresh, not blind. One case more or less moves a rate by about 3 points.
