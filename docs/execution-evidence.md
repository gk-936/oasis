# Execution evidence (sandbox logs and reports)

Everything below ran on the simulated sandbox (MOCK rates, rails, registry and balances). Nothing was sent to a real bank or blockchain. The benchmark, demo and simulation reports contain no on-chain transaction hashes: they anchor on the local hash-linked simulation (`LocalAnchorChain`) by design. The real FISCO BCOS transaction hashes (local 4-node chain) are in [`fisco-bcos.md`](fisco-bcos.md) and the post-quantum TLS handshake evidence is `eval/reports/pqtls.md`. The audit-chain head hash in the demo log plays the equivalent role for tamper evidence.

| Evidence | Files (in `eval/reports/`) | What it shows | Produced by |
|---|---|---|---|
| Hidden test set, pre-fix and post-fix | `benchmark_hidden_prefix.md/.json` (first run, kept unchanged), `benchmark_hidden.md/.json` (after the general fixes, with pre/post table and why each case passes) | 40 blind cases, sha256-verified. Attack block rate (strict pass criteria: no money to attacker accounts, no overpayment, wrong payee, wrong currency or unregistered account; a refusal or hold passes): pre-fix 46.4% / 92.9% / 100% / 100%, post-fix 39.3% / 89.3% / 100% / 100% (baseline / +verification / +intents+policy / full); legitimate completion 75% pre-fix, 100% post-fix. Detail: [`results.md`](results.md) | `python -m eval.runner --suite hidden` |
| Post-quantum TLS handshake | `pqtls.md` | Caddy 2.11.7 + OpenSSL 3.5.9 negotiated X25519MLKEM768; classical-only client refused | `tools/caddy/verify-pq.ps1` |
| Offline benchmark (deterministic extraction) | `benchmark.md`, `benchmark.json` | 4 configurations x (32 attacks + 12 legitimate changes) + 4 AI red-team variants: block rate, money lost, detection, legit completion, false blocks, canary early detections, risk-scorer accuracy | `python -m eval.runner` |
| Live benchmark (Groq, live-agent extraction) | `benchmark_live.md`, `benchmark_live.json` | Same suite with a live model extracting (qwen/qwen3.8-27b configured as primary; which model served each extraction was not recorded in this run and is labelled "model not recorded (pre-fix run)"; newer runs record it per extraction), 9 AI red-team variants, per-field extraction provenance, "model followed injection" counts, deterministic reference table. Re-run 2026-10-10 with 3 repeats (temperature 0, 0.4, 0.4; distinct cache salts) and the LLM risk scorer; per-extraction serving model is now recorded (qwen/qwen3.8-27b 167, openai/gpt-oss-120b 16 of 183 steps); the earlier single-repeat run is superseded | `python -m eval.runner --llm groq --extract llm --llm-risk --repeats 3` |
| Planning evaluation | `planning.md`, `planning.json` | 8 planning scenarios scored by the deterministic validator: offline 8/8 valid; live (Amazon Nova Pro on Bedrock, 2026-10-13, 3 repeats = 24 plans, temperature 0.3, per-plan cap 22,000): planner v2 16 of 24 valid without fallback, planner v3 with calculator tools 24 of 24 (0 fallbacks, 23 of 24 on the first proposal, 150,079 tokens, fees CNY 15,087 vs CNY 14,969 deterministic vs CNY 88,307 bank) | `python -m eval.planning` (live: `OASIS_PLANNER_FORMAT=v3 python -m eval.planning --llm bedrock --repeats 3 --token-cap 150000`) |
| Planner format experiment | `planning.md` (last section), `planning_experiment.json`, [`planner-efficiency.md`](planner-efficiency.md) | earlier format experiments (v1 vs v2) were run on Groq models in 2026-10-11 and are kept as history; the current live evidence is the Amazon Nova Pro run above | `python -m eval.planning_experiment` |
| Student-outcome simulation | `simulation.md`, `simulation.json` | 5 personas over 90 days, Oasis vs a manually paying student; scam and landlord events run through the real pipeline. A model with stated assumptions | `python -m eval.simulator` |
| Scripted demo log | `demo.md`, `demo.json` | Both demo runs, step headlines, money lost, chain verification and the audit-chain head hash, replayed twice to show identical heads | `python -m eval.demo_log` |

Audit-chain heads for the seeded demo (offline model, seed 7, seeded DEMO keys, simulated clock), reproduced on every run:

- Run 1 (legit): `38417365ea11d0c3c51b9ad4d555858e860b4e7b491ca6cc29bab7c048d1cf72` (29 entries, money lost 0)
- Run 2 (attack): `64f5aa04bca100693c35d34f1692f4d8987623a433307d72b255a40e38c1a449` (money lost 0)

If the code or ruleset changes, these hashes change; regenerate with `python -m eval.demo_log` and read `demo.md`. The API exposes the same data live: `GET /api/audit`, `GET /api/audit/verify`, `GET /api/proof/{intent_id}/verify`, `POST /api/demo/run`.

## Regenerating

```bash
# from the repository root, with the venv active (all offline unless stated)
PYTHONPATH=. python -m eval.runner --llm offline        # benchmark.md/.json
PYTHONPATH=. python -m eval.runner --suite hidden       # benchmark_hidden.md/.json (offline)
PYTHONPATH=. python -m eval.simulator                  # simulation.md/.json
PYTHONPATH=. python -m eval.planning                   # planning.md/.json (offline section)
PYTHONPATH=. python -m eval.demo_log                   # demo.md/.json
OASIS_DB=:memory: OASIS_LLM=offline PYTHONPATH=. python -m pytest -q    # the whole suite, no network (count: see README)
PYTHONPATH=. python -m eval.runner --llm groq --extract llm --report-only   # rebuild benchmark_live.md from the checkpoint, no model call
```

Live results need `GROQ_API_KEY` in `.env` and a Groq free-tier budget (about 200k tokens/day). The runner is resumable (checkpoints in `data/bench_cache/`, git-ignored) and stops cleanly with exit code 2 when the daily budget is spent. Responses are cached in `data/llm_cache/` (git-ignored), so the committed live reports are the evidence of the 2026-10-10 runs; a fresh clone re-queries the model and, because models drift and may be retired, will not reproduce them exactly. Offline reports are deterministic and regenerate identically (apart from the run timestamp).

## Caveats

- Live benchmark: 3 repeats (temperature 0, 0.4, 0.4), six injection-bearing scenarios; identical outcomes in every repeat (zero spread), the model followed 0 of 18; the LLM risk scorer raised 82 of 183 scores and pushed 0 over the hold threshold. Not a robustness claim.
- Live planning: Amazon Nova Pro on Bedrock, 2026-10-13, 24 plans (3 repeats of 8). v2: 16 of 24 valid without fallback, 391,069 tokens. v3 (calculator tools): 24 of 24, 168,982 tokens. v3 with route, consolidation and SAFE-split calculators (final): 24 of 24, 0 fallbacks, 23 of 24 on the first proposal, 150,079 tokens, 51 of 51 deadlines met, fees CNY 15,087 vs CNY 14,969 (deterministic) vs CNY 88,307 (typical bank). Total Bedrock spend for all runs about 810,000 tokens (about USD 0.7 at USD 0.80 / 3.20 per million input / output tokens). The final plan is always checked by the deterministic validator.
- Live-replay demo fixture (`eval/fixtures/demo_cache/`): not recorded yet; until it is, live-replay shows labelled offline fallbacks. Record with `python -m eval.record_demo_fixture`.
- Simulated humans approve or decline according to the Passport; they are not oracles. Savings are driven by mock fees.
