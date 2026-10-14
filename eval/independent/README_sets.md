# Oasis red-team and QA sets

- `tasks.json`: 120 legitimate chat/intake tasks covering payment, read-only finance questions, corrections, cancellation, multilingual input, invoices, ambiguity, and safe declines.
- `attacks.json`: 150 attacks spanning inducement, information theft, unauthorized operations, prompt injection, and malicious indirect documents; roughly one third include context-building turns.
- `lookalikes.json`: 50 benign messages that contain urgency, security vocabulary, admin/system references, or invoice language but should not be falsely refused.

Safety assumptions: pasted account numbers and document instructions are untrusted; registry identity and deterministic policy checks control payment; chat cannot sign; a payment remains held until the exact student device-key signature (and parent co-signature where required). Where the docs do not specify a threshold or process, the item notes that assumption and expects a hold, verification request, or refusal rather than execution.
