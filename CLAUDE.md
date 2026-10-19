# Oasis rulebook

Rule 1 overrides everything else.

## 1. Paid model calls: never without explicit permission

Amazon Nova Pro on Bedrock is billed. **No live model call unless the owner approved that specific run in this conversation.** One approval never covers the next run.

- `.env` sets `OASIS_LLM=bedrock` and `oasis/config.py` loads it, so any command importing `oasis` can call Bedrock. Prefix every command with `OASIS_LLM=offline` (PowerShell: `$env:OASIS_LLM="offline"`).
- Never run without approval: `eval.planning --llm bedrock`, `eval.planning_v3`, `eval.planning_experiment`; `eval.runner` without `--llm offline` or with `--extract llm` / `--llm-risk`; `eval.chat_llm_bench --live`; `eval.chat_live_final --live`; `eval.vision_live_final --live`; `eval.record_demo_fixture`; `tests/test_llm_live.py`, `tests/test_live_extract.py` with live credentials; the server without `OASIS_LLM=offline`; any script using `boto3` / `bedrock-runtime` or a live risk model.
- Safe: the test suite (forced offline), `scripts/start_judge.*`, `--report` / `--report-only`, dry runs, offline benchmarks.
- Approved live run: state the command, token cap and expected calls first; always pass a cap; report tokens actually spent.
- Never edit `.env`, print it or echo AWS credentials.

## 2. Commands (offline)

```bash
# tests: expect "2731 passed, 2 skipped" (update the README if the count changes)
OASIS_DB=:memory: OASIS_LLM=offline PYTHONPATH=. .venv/Scripts/python -m pytest -q
OASIS_LLM=offline PYTHONPATH=. .venv/Scripts/python -m uvicorn oasis.api.main:app --port 8000
OASIS_LLM=offline PYTHONPATH=. .venv/Scripts/python -m eval.runner --llm offline   # also eval.flightpath_bench, eval.netting_bench, eval.tasks_bench
cd frontend && npm ci && npm run build   # frontend/dist is committed; rebuild after frontend/src changes
bash scripts/router_gates.sh <outdir>   # all router gates offline: pytest, eval.runner, eval.fuzz_bench, verify_evidence, eval.frozen_set (about 30 min)
OASIS_LLM=offline PYTHONPATH=. .venv/Scripts/python -m eval.router_sets   # DEV and WORD-HELD-OUT scores (model off); -m eval.attack_catalogue_run for rows A1-A20
```

## 3. Security invariants (do not weaken)

- The model only proposes and explains. It never approves a payment, holds a credential, changes a verification status or writes the audit log. Its risk score may only escalate.
- Money goes only to the registry account, never to an account read from a document.
- The executor enforces the signed intent exactly (signature, exact match, nonce, expiry, policy re-check). No bypass or debug flag around `oasis/trust/executor.py`, `policy.py`, `intents.py`.
- Every state-changing endpoint has a role dependency; PUBLIC endpoints stay read-only and need no secrets.
- Approvals need a device-key signature over the exact draft hash; a role string grants nothing.
- A security change needs a test in `tests/` and an entry in `docs/security-evidence-matrix.md`.

## 4. Honesty and documentation

- Simulated data stays labelled MOCK. Never present a sandbox result, credential or compliance mapping as real, licensed, audited or a credit score.
- Every number in the README or docs comes from a file in `eval/reports/` and keeps its caveat.
- When a fact changes (provider, test count, live-run status), update every doc that states it; grep first. Bedrock (Nova Pro) is the only live provider.
- English is the default language; Chinese text is machine-translated and stays marked; Tamil and Hindi text was checked by the team.

## 5. Conventions and git

- Python 3.10+, FastAPI in `oasis/`, React + Vite in `frontend/src/`, benchmarks in `eval/`, tests in `tests/`. Match surrounding style; deterministic code, seeded randomness; hermetic tests (no network, no writes outside temp dirs).
- Router vocabulary lives in `oasis/agent/lexicon.py` (data, not regexes); add a word only with a test, and never tune on the WORD-HELD-OUT or BLIND sets. Write regexes with the Edit tool or a raw string: a `\b` inside a normal Python string becomes a backspace character.
- New UI strings in both `frontend/src/i18n/en.js` and `zh.js`. New corridor values in `oasis/trust/rules/*.yaml` with source, date and status.
- Never commit `.env`, `data/`, keys or `node_modules/`. Commit or push only when asked, after the offline test suite passes.
