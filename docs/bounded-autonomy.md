# Bounded autonomy: how the AI takes part in the money flow

Oasis treats the AI as a participant with limits, not as an authority. The limits are enforced by code that the model cannot change: the policy engine, the signed-intent executor and the device-key signature. Everything below is a MOCK sandbox; no real money, bank or credit record is involved.

## The three levels

| Level | What the agent may do | What stops it going further | Where to see it |
|---|---|---|---|
| **1. Act alone** (Tier 1) | Convert the student's own money at a rate the student set, up to CNY 5,000 (R13). Pay a small recurring bill (at most CNY 500) to a fully verified registry payee (R10). | Policy re-check on every run, the executor's signed-intent check, the registry account only, the cap written into the signed mandate, a canary freeze. | Demo run 3 "autonomy", `GET /api/activity`, chat "what did you do for me?" |
| **2. Ask the human** | Draft anything larger: a payment above Tier 1, a tuition bill that needs a parent, a conversion above the auto limit or in another pair, a standing instruction, a rate target. | Nothing runs until the student's device key signs the exact draft hash (payee, account, amount, currency, purpose, route, expiry, nonce). A role string, a wrong signature or a replayed nonce grants nothing. | Chat drafts `#<hash>`; tests in `tests/test_conversion_drafts.py`, `tests/test_mandates.py` |
| **3. Never act** | Nothing. | Refusals are decided by deterministic code before any model call: secrets, bypass requests, an account number taken from a document or message, a payee outside the registry, "approve for me". | `tests/test_chat_security.py`, the attack sets, the fuzz run |

The model's own role stays the same at every level: it proposes and explains, its risk score can only escalate, it never approves a payment, holds a credential, changes a verification status or writes the audit log.

## What was added to make level 1 and 2 usable from chat

- **Signed conversions** (`oasis/agent/conversion_exec.py`, rule C01). Any supported pair and any size, including "convert all my INR" (resolved to the real balance and stated first). INR to CNY inside the auto limit still takes the chat "yes" path. Everything else becomes a held draft that touches only the student's own wallets and can never pay anyone. The nonce is single use (the audit chain remembers it); pair and balance are re-checked when it runs; the price is the price at execution.
- **Standing instructions** (`oasis/agent/mandate_exec.py`, rule C02). "Pay my phone bill every month" and "convert 3000 when the rate reaches 0.075" each create a held draft. The signature creates the mandate (cap and payee are inside the signed hash). Creating it moves no money. Each later run is a normal request through the pipeline and is audited; a bill that rises above the signed cap is held, not paid. Rate targets set through chat now follow this path. `POST /api/rate-target` (the web form, an authenticated student session) is unchanged: it creates the same bounded Tier-1 target without a device-key signature, and this is listed as a known limit.
- **Agent activity feed** (`oasis/agent/activity.py`). One read-only timeline: done alone, proposed or approved, held, refused.
- **A wider MOCK world** for the API session: electricity, internet, health insurance, a residence-permit fee, a library fine, a gym membership and a registered peer payee, all registry payees with MOCK accounts and bills. The demo, twin and benchmark worlds keep the small seed.

## Seeing it in the web app

**Agent record panel (web app).** The student sees it at the top of the Passport tab and the judge (read-only) at the top of Home. It shows the mandate card, the Tier-1 limit, each active standing instruction, six counters (acted alone, drafts waiting, refusals, scam warnings, canary freezes, money lost), the audit head with a chain-intact badge and refusals by reason, all read from `GET /api/agent-scorecard`. "Stop a standing instruction" sends the chat message "stop my autopay" (or "remove the rate alert"); it calls no new endpoint and ends nothing by itself. The held revoke draft is signed in the Chat tab, and the instruction ends only after that device-key signature.

## Evidence

- **Autonomy demo** (`python -m eval.demo_log`, run 3): sign a standing instruction; five days pass and the rate-target conversion and the recurring bill run with no signature; a CNY 4,000 payment is held for the student; the CNY 30,000 tuition is held; a 90,000 INR conversion is held and executes only after the sign; a tripped canary freezes. 24 audit entries, chain verifies, money lost 0, audit-chain head `3efb9873089857e9c837079fc8a7fd07c4c1d6b1f9a6c2f1f8aef71c6f66fac7`, identical on replay.
- **Frozen task-completion set** (`python -m eval.frozen_set`, model off): 136 of 151 (90%; 130 before the router rebuild); "I didn't catch that" in 0 replies; money moved in 0 messages. The set was written by the implementer after the round-6 fixes, not by independent people, so this is not an out-of-sample estimate. Two task labels predate the wider MOCK world and are left as written.

## What the AI measurably adds (and what is not measured)

- **Model off (measured):** the figures above. The offline router, glossary, forecast and deterministic planner produce them with no model call. The planner's deadline and fee-saving results are in `docs/results.md` (planner outcomes, MOCK).
- **Model on:** Model-on run (one run, our own messages; `eval/reports/model_on.md`): 74 calls, 23,940 tokens in and 2,609 out, about USD 0.03 estimated at list prices. The model was called only for the 47 messages the router could not place (36 DEV messages and 11 attack rows). Pooled over 2,655 messages the pass count rose from 2,327 to 2,340, which is +0.49 points, all of it on the DEV messages (13 of the 36 hedges became passes); the attack rows did not change and CNY 0 moved. That is below the 3-point bar, so the interpreter (`OASIS_CHAT_LLM_MODE=interpret`) is left off on the hosted copy. There is no model-on figure for any other set. We do not claim that the model improves task completion.
- What the AI components do contribute is reading documents and screenshots, scoring risk (escalation only) and explaining holds in plain language; those are measured in their own reports.

## Known limits

- Mandates and conversions are authorised by the student's device key in a sandbox with simulated humans in tests; real approvers hold their key in the browser.
- A rate target made through the web form is not signed (see above). Each run is bounded by Tier 1 and audited.
- The compound-request walker handles one convert-then-pay pair in a message; each step is its own request with its own confirmation or signature.
- Nothing here is a credit score, a licensed service or an audited system.
