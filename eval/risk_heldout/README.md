# Risk held-out set

`scenarios_risk_heldout.json`: 60 cases (41 attacks, 19 legitimate) in the `eval.scenarios.Scenario` format plus `expect` and `new_attacker_accounts`, as in `eval/hidden/`.

## How it was written
- Written on 2026-10-18, **before** the risk scorers were run on it, without reading the heuristic scorer, the feature extraction, the model weights or the model training corpus.
  The author used only the public category names in the saved reports, the `Scenario` data format and the demo identities (University X, Chen Wei, Shenzhen Mobile, their accounts).
- The author is the same AI assistant that works on this repository, and had seen the earlier benchmark reports: the set is **held-out, not independent**.
- Categories: urgent_pressure, forged_invoice, hidden_instruction (including a Chinese and a base64 instruction), lookalike_payee, payee_change_pretext, inflated_amount,
  authority_pressure, split_payments, poisoned_tool (three, with `tool_poison`); legitimate: genuine invoices in several layouts and languages, firm-but-genuine
  reminders, registry re-issues, family top-ups. Attacker accounts are `66660000000001xx`.
- Known design mistakes, left in on purpose: `rl_genuine_invoice_3` and `rl_genuine_invoice_11` are phone bills to a payee the benchmark world's registry does not carry.

## Rules
Do not tune the scorers, rules or model weights against this set. If it is used to tune, it is burned and a new one is needed. Run it with
`OASIS_LLM=offline PYTHONPATH=. python -m eval.risk_heldout` (report: `eval/reports/risk_heldout.md`). Its sha256 is printed in the report.
