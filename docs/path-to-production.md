# Path to production: what would have to change to move real money

Oasis today cannot complete a real cross-border transfer. Every balance, rail, registry identity and most route prices are simulated (see [real-vs-simulated.md](real-vs-simulated.md)). This page says exactly where a real payment partner would plug in, what stays as it is, and what Oasis could not do without one. It is a design note, not something that has been built or tested against a real provider.

## The seam: `PaymentRail`

The executor (`oasis/trust/executor.py`) is the only component that moves money, and it asks the payment layer for exactly three things, written down as the `PaymentRail` protocol in that file:

| Call | What the executor uses it for | What a real rail must guarantee |
|---|---|---|
| `executor_credential()` | the executor's own secret | it can only **mint** authorisations, never pay by itself |
| `mint_tool_token(issuer, intent_id, from_ref, to_ref, amount, currency)` | one authorisation per execution | bound to one signed intent and one exact transfer, single use, expires in seconds |
| `transfer(token, from_ref, to_ref, amount, currency, memo, intent_id)` | the payment itself | refuses an unknown, used, expired or mismatched token; refuses a currency that does not match both accounts |

`SandboxLedger` (`oasis/mock/ledger.py`, 117 lines) is the MOCK implementation. A test (`tests/test_trust.py::test_executor_needs_only_the_three_call_payment_rail_seam`) runs the executor against a rail that has only those three calls, so the claim "the executor needs nothing else from the ledger" is checked, not just stated. The in-sandbox baseline (an agent that holds its own credential) uses the ledger directly on purpose and is not part of the protected path.

## What stays the same

Registry check, policy rules R01 to R19, signed hybrid intents, device-key approvals, the audit hash chain, proof packs and the exact-match enforcement all sit **before** the rail and do not depend on it. The security argument (the model never pays, money goes only to the registry account) is unchanged by the swap.

## What would have to be built or bought

1. **A licensed counterparty.** Moving customer money is a regulated activity (in India an authorised dealer bank under FEMA/LRS; in China SAFE-supervised banks). Oasis holds no licence and does not claim one. A bank or regulated payment provider would execute the transfer; Oasis would be the planning, verification and evidence layer in front of it.
2. **A real rail adapter** implementing the three calls above on the partner's API, with the partner's own idempotency key carrying our intent id.
3. **Real payee verification.** The registry is made of WeIdentity-style demo credentials. In production the verified account would come from the university or landlord through the partner's account-validation service or a signed statement, not a demo file.
4. **KYC and sanctions at the partner.** Oasis screens names against four public list snapshots as evidence for review; a regulated partner has to run its own screening and customer due diligence.
5. **Asynchronous settlement.** The sandbox transfer is instant and exact. Real transfers pend, arrive short after intermediary deductions or fail. FlightPath already models that journey (pre-transfer checks, delay and short-credit detection, no blind resend), but its deduction model is our own, so it would have to be tuned on real transfers.
6. **Real balances and reconciliation.** In the sandbox the ledger *is* the source of truth for balances (the wallet, the Passport and the Twin read it directly in `oasis/world.py`). With a real rail, balances come from the partner and the Passport must reconcile to them. This part is **not** behind the seam today and is the largest piece of rework.
7. **Real route prices.** Replace MOCK spreads with partner quotes; the method is in [corridor-research.md](corridor-research.md).
8. **Operations and security.** Per-person accounts and MFA, key management in an HSM or vault, TLS everywhere, multi-worker state, monitoring, an independent security audit and legal review. The demo-grade items are listed in the README's known limitations.

## What this does and does not show

It shows that the trust-critical part (authorising exactly one signed payment) is separated from the money-moving part by a three-call interface with a test. It does not show that a real provider integration works, that a provider would accept this flow, or that the result would be compliant. The first realistic step is a pilot with a regulated partner's sandbox API; until then Oasis remains a simulation.
