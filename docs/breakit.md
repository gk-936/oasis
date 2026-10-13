# Break-it live challenge

A judge (or student) pastes any fraud attempt in the **Break it** tab. The text goes through the normal intake, verification and policy pipeline in a private sandbox ledger (MOCK, no real money). The verdict shows blocked or not, the policy rule (R01-R17) and the why-card that fired.

**Attacker generator.** `Generate 8 attacker variants` runs deterministic, offline template/mutation variants (swapped account, amount, look-alike payee, urgency pressure, prompt injection) against the same defender and shows a scoreboard: blocked/total, CNY saved, CNY lost. No LLM is used; the same `start` always yields the same attacks.

Endpoints (student and judge sessions; shared red-team rate limit): `POST /api/breakit/attack {text}` and `POST /api/breakit/generate {n<=12, start}`. Code: the BREAK-IT block in `oasis/api/main.py`, `frontend/src/tabs/BreakIt.jsx`, `tests/test_breakit.py`.
