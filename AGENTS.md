# Oasis rulebook

Rules for anyone (human or AI agent) working in this repository. Rule 1 overrides everything else.

## 1. Paid model calls: never without explicit permission

Amazon Nova Pro on Amazon Bedrock is billed separately. **Do not make any live model call unless the owner has explicitly
approved that specific run in the current conversation.** Approval for one run does not cover the next one.

- The local `.env` sets `OASIS_LLM=bedrock` and `oasis/config.py` loads it. So **any** command that imports `oasis` can call
  Bedrock unless offline is forced. Prefix every command with `OASIS_LLM=offline` (PowerShell: `$env:OASIS_LLM="offline"`).
- Never run without approval:
  - `eval.planning --llm bedrock`, `eval.planning_v3 --format ...`, `eval.planning_experiment ...`
  - `eval.runner` without `--llm offline` (its default comes from `.env`, so it is **bedrock**), or with `--extract llm` / `--llm-risk`
  - `eval.record_demo_fixture`
  - `tests/test_llm_live.py` or `tests/test_live_extract.py` with live credentials
  - the server (`uvicorn oasis.api.main:app`) without `OASIS_LLM=offline`
  - any script that uses `boto3` / `bedrock-runtime`, `OASIS_ML_RISK`/`OASIS_LLM_RISK` with a live model, or a smoke test that "just checks the key"
- Safe without asking: the test suite (conftest forces offline and blocks the network), `scripts/start_judge.*` (they set
  offline), `--report` / `--report-only` modes (they rebuild reports from saved rows), and offline benchmarks.
- When a live run is approved: state the command, the token cap (`--cap` / `--token-cap` / `--per-plan-cap`) and the expected
  number of plans **before** running it; always pass a cap; report the tokens actually spent afterwards.
- Never edit `.env`, print its contents or echo AWS credentials.

## 2. Commands (offline)

```bash
# tests (no network; expect "1126 passed, 2 skipped" — update the README if the count changes)
OASIS_DB=:memory: OASIS_LLM=offline PYTHONPATH=. .venv/Scripts/python -m pytest -q
# server
OASIS_LLM=offline PYTHONPATH=. .venv/Scripts/python -m uvicorn oasis.api.main:app --port 8000
# offline benchmarks
OASIS_LLM=offline PYTHONPATH=. .venv/Scripts/python -m eval.runner --llm offline
OASIS_LLM=offline PYTHONPATH=. .venv/Scripts/python -m eval.flightpath_bench
OASIS_LLM=offline PYTHONPATH=. .venv/Scripts/python -m eval.netting_bench
OASIS_LLM=offline PYTHONPATH=. .venv/Scripts/python -m eval.tasks_bench   # chat task benchmark (forces offline itself)
# UI rebuild (frontend/dist is committed; rebuild after any change in frontend/src)
cd frontend && npm ci && npm run build
```

## 3. Security invariants (do not weaken)

- The AI model only proposes and explains. It never approves a payment, holds a credential, changes a verification status or
  writes to the audit log. Its risk score may only escalate a decision.
- Money goes only to the registry account, never to an account read from a document.
- The executor enforces the signed intent exactly (signature, exact match, nonce, expiry, policy re-check). Do not add a bypass,
  "debug" flag or shortcut around `oasis/trust/executor.py`, `policy.py` or `intents.py`.
- Every state-changing endpoint uses a role dependency (`STUDENT`, `PARENT`, `STUDENT_PARENT`, ...). Endpoints marked PUBLIC
  must stay read-only and need no secrets.
- Approvals need a device-key signature over the exact draft hash; a role string grants nothing.
- A security change needs a test in `tests/` and an entry in `docs/security-evidence-matrix.md`.

## 4. Honesty and documentation

- Simulated data stays labelled MOCK in the UI and docs. Never present a sandbox result, credential or compliance mapping as
  real, licensed, audited or a credit score.
- Every number in the README or docs must come from a file in `eval/reports/` and keep its caveat.
- When a fact changes (provider, test count, live-run status), update **every** doc that states it. Search first, for example
  `grep -rn -i "groq\|not yet been run" README.md docs/`. Groq was removed; Bedrock (Nova Pro) is the only live provider.
- Keep English as the default language; Chinese, Tamil and Hindi text is machine-drafted and stays marked as such.

## 5. Code conventions

- Python 3.10+, FastAPI backend in `oasis/`, React + Vite UI in `frontend/src/`, benchmarks in `eval/`, tests in `tests/`.
- Match the surrounding style: short docstrings explaining *why*, deterministic code paths, seeded randomness.
- Tests must stay hermetic: no network, no writes outside temp dirs.
- New UI strings go in both `frontend/src/i18n/en.js` and `zh.js`.
- New corridor values go in `oasis/trust/rules/*.yaml` with source, date and status.

## 6. Git

- Never commit `.env`, `data/`, keys or `node_modules/`.
- Commit or push only when asked. Run the offline test suite before committing.
