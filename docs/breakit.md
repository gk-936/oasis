# Break-it live challenge

A judge (or student) pastes any fraud attempt in the **Break it** tab. The text goes through the normal intake, verification and policy pipeline in a private sandbox ledger (MOCK, no real money). The verdict shows blocked or not, the policy rule (R01-R17) and the why-card that fired.

**Attacker generator.** `Generate 8 attacker variants` runs deterministic, offline template/mutation variants (swapped account, amount, look-alike payee, urgency pressure, prompt injection) against the same defender and shows a scoreboard: blocked/total, CNY saved, CNY lost. No LLM is used; the same `start` always yields the same attacks.

Endpoints (student and judge sessions; shared red-team rate limit): `POST /api/breakit/attack {text}` and `POST /api/breakit/generate {n<=12, start}`. Code: the BREAK-IT block in `oasis/api/main.py`, `frontend/src/tabs/BreakIt.jsx`, `tests/test_breakit.py`.

**Executor attacks (tamper, replay, forge).** Chat attacks test intake and policy. `GET/POST /api/breakit/executor {attack}` hands the real executor (`oasis/trust/executor.py`) a signed payment in the caller's own sandbox and reports whether it was refused and how much extra money moved. Attacks: `tamper_amount`, `tamper_payee`, `tamper_intent` (edit after signing), `replay` (same nonce), `expired`, `forged_approval` (unregistered key), `role_swap` (student signature relabelled parent), `unsigned`, `no_approval`, plus a `control` (honest signed payment, must execute, so the harness is not simply refusing everything). `POST /api/breakit/executor/all` runs every attack in one request, so it counts once against the red-team rate limit (10 a minute in judge mode; each single attack counts one). Code: `oasis/trust/breakit_exec.py`, `tests/test_breakit.py`.

Limit: the `decide` callable in this harness only allows when the student's device signature verified. It is not the full policy engine (rules R01-R17 are exercised by the chat attacks and the policy tests). Same team wrote the attacks and the defences.
