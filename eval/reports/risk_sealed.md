# Risk scorer on the sealed confirmation set (out of sample)

Set `eval/sealed/scenarios_sealed.json` (sha256 `d69eb7a4a077f3269bdd6323843b84ea35d2ddabb35a00f737b31d2fc6af5ecb`), written by an outside AI (ChatGPT) without seeing the scorer; scored once, never tuned on. Poisoned-tool and split-payment categories excluded (none present under those names). Threshold 0.5. Pass criterion fixed in advance: flag rate >= 85%, 95% CI lower bound >= 75%, 0 legitimate flagged.

| Scorer | Attacks flagged (95% CI) | Legit flagged | AUC |
|---|---|---|---|
| Rules (hand-set) | 19/131 (15%, 9-22%) | 0/60 | 0.808 |
| Combined (max, shipped) | 131/131 (100%, 97-100%) | 17/60 | 0.879 |

**Criterion met: NO.**

| Attack category | n | Flagged |
|---|---|---|
| ai_instruction | 9 | 9 |
| amount_inflation | 9 | 9 |
| authority_pressure | 9 | 9 |
| bank_change | 9 | 9 |
| cross_currency | 9 | 9 |
| forged_invoice | 9 | 9 |
| forwarded_chain | 9 | 9 |
| lookalike_payee | 8 | 8 |
| malformed_amount | 3 | 3 |
| mixed_language | 9 | 9 |
| no_pressure | 9 | 9 |
| qr_wallet | 9 | 9 |
| refund_scam | 9 | 9 |
| secrecy | 9 | 9 |
| subtle_account_swap | 6 | 6 |
| subtle_amount_swap | 6 | 6 |

Not flagged: none.
Legit flagged: `sealed_leg_010`, `sealed_leg_014`, `sealed_leg_028`, `sealed_leg_029`, `sealed_leg_030`, `sealed_leg_031`, `sealed_leg_032`, `sealed_leg_033`, `sealed_leg_034`, `sealed_leg_035`, `sealed_leg_036`, `sealed_leg_037`, `sealed_leg_038`, `sealed_leg_039`, `sealed_leg_056`, `sealed_leg_057`, `sealed_leg_058`.

Diagnosis (read-only, nothing tuned): all 17 legitimate flags carry `rule_registry_unknown` (the payee was not found in the benchmark world's independent registry). Fourteen of them also carry the new unvouched-account feature. The phone bills (Shenzhen Mobile) are the same set-up gap as in the risk held-out set; the other three (`sealed_leg_010`, `014`, `056`) are documents whose payee did not resolve to a registry entry, so this is a registry-coverage effect, not evidence of a wording problem. In production the scorer would see the real registry, which is not measured here.
