# Payment Evidence Passport

One signed bundle proving: this payment (tuition or rent) was paid to this registry-verified payee, and it arrived.
Code: `oasis/proof/evidence_passport.py`. Tests: `tests/test_evidence_passport.py`. UI: the "Evidence" tab (student) and the public `/?evidence=<code>` page.

## What is inside

| Part | Source | Re-checked by the verifier |
|---|---|---|
| Signed intent, approvals, audit entry, anchor | existing proof pack | `verify_proof_pack` (hybrid signature, approval signatures, entry hash) |
| Registry payee | registry credential (MOCK issuer) | credential signature, binding to the intent's payee and account, issuer key pinned |
| Reconciliation: credited / short / delayed | FlightPath `reconcile` on the embedded journey | recomputed from the journey, must equal the stated finding and status |
| Audit-chain inclusion | hash-linked entries from the payment's entry to the chain head | each link and hash recomputed; first entry equals the pack's entry and is the `transfer_executed` for this intent; optionally the head is on the server's own chain |

The whole body is signed with the server key (Ed25519 + ML-DSA-65, same signer as the Trust Pass) and carries a `passport_hash`.

## Endpoints (one block in `oasis/api/main.py`)

- `GET /api/evidence-passport/payments` (student): payments a passport can be issued for.
- `POST /api/evidence-passport/issue` (student): `{intent_id, outcome: credited|short|delayed, credited_cny?}`.
- `POST /api/evidence-passport/share` (student): only a passport that verifies is stored; returns a QR code id.
- `GET /api/evidence-passport/check/{code}` (public): re-verifies now. The code only locates the passport.
- `POST /api/evidence-passport/verify` (public): verify a pasted passport. No secrets, no state change.

## Trust model

`ok` needs every offline check AND the server key, the proof-pack keys and the registry issuer key to match pins held by the server. A forger who re-signs with fresh keys passes `signature` but fails the pins. With no pins supplied the verifier never reports `ok`.

## Limits (MOCK)

- The payment rail is simulated. The reconciliation outcome is chosen at issue time (credited, short, delayed) and driven through the FlightPath state machine; no real bank confirmed receipt.
- The registry, clock and money are simulated. This is not a bank statement.
- Share codes live in the same store as Trust Pass shares (bounded, lost if the session is reset).
- The audit segment is capped at 500 entries after the payment.
