# Payment flow: student pays in INR, university receives CNY

All money here is a MOCK sandbox ledger. Nothing is real, licensed or audited.

## What the student sees

The student holds an INR balance and pays the university directly from it. There is no separate top-up or currency-exchange step.

1. The student sends an invoice (for example "University X, CNY 30,000, tuition").
2. Oasis checks the payee against the registry, runs the policy and corridor rules, and shows a payment card with the INR cost.
3. The student approves once with their device key. The signature covers the exact draft.
4. The INR balance goes down and the university's registry account receives the CNY.

## What happens underneath

Both steps run inside the one approval.

1. The needed INR is converted to CNY at the mock rate (fees included).
2. The executor pays the CNY from the student's account to the registry account, using a single-use token bound to that exact transfer.

Money goes only to the registry account, never to an account read from the invoice.

## Example from an offline test run

| | INR balance | University account (CNY) |
|---|---|---|
| Before | 500,000.00 | 0 |
| After approving a 30,000 CNY invoice | 67,823.10 | 30,000.00 |

A leftover of about 0.01 CNY stays in the student's CNY account. This is a mock figure from `OASIS_LLM=offline`, not a real quote.

## Cases where nothing is deducted

- Unverified or unknown payee
- Duplicate invoice (held until the student chooses "pay again")
- Missing or invalid approval signature
- Insufficient INR balance

## Resetting between runs

`POST /api/reset` restores the starting balances, so every judge starts from the same state.
