# Execution evidence (sandbox logs and reports)

Everything below ran on the simulated sandbox (MOCK rates, rails, registry and balances). Nothing was sent to a real bank or blockchain. There are no on-chain transaction hashes: anchoring is a local hash-linked simulation (`LocalAnchorChain`), not FISCO BCOS. The audit-chain head hash in the demo log plays the equivalent role for tamper evidence.

| Evidence | Files (in `eval/reports/`) | What it shows | Produced by |
|---|---|---|---|
| Offline benchmark (deterministic extraction) | `benchmark.md`, `benchmark.json` | 4 configurations x (32 attacks + 12 legitimate changes) + 4 AI red-team variants: block rate, money lost, detection, legit completion, false blocks, canary early detections, risk-scorer accuracy | `python -m eval.runner` |
| Live benchmark (Groq, live-agent extraction) | `benchmark_live.md`, `benchmark_live.json` | Same suite with qwen/qwen3.8-27b as the primary extractor (served by the fallback model where noted in the report), 9 AI red-team variants, per-field extraction provenance, "model followed injection" counts, deterministic reference table. One repeat, 2026-10-10 | `python -m eval.runner --llm groq --extract llm --repeats 1` |
| Planning evaluation | `planning.md`, `planning.json` | 8 planning scenarios scored by the deterministic validator: offline 8/8 valid; live run on 3 of 8 (token budget) with fallbacks recorded | `python -m eval.planning` (live section: `--llm groq --token-cap 60000`) |
| Student-outcome simulation | `simulation.md`, `simulation.json` | 5 personas over 90 days, Oasis vs a manually paying student; scam and landlord events run through the real pipeline. A model with stated assumptions | `python -m eval.simulator` |
| Scripted demo log | `demo.md`, `demo.json` | Both demo runs, step headlines, money lost, chain verification and the audit-chain head hash, replayed twice to show identical heads | `python -m eval.demo_log` |

Audit-chain heads for the seeded demo (offline model, seed 7, seeded DEMO keys, simulated clock), reproduced on every run:

- Run 1 (legit): `cc1c6367ea2b396a7338d2f977d28440be42b3498b24159363e5d186acacad2d` (29 entries, money lost 0)
- Run 2 (attack): `d0a0a83e6d64f8e9a609a4a6d8d1519d8a2e8569a883d61941e2088326bd96f2` (money lost 0)

If the code or ruleset changes, these hashes change; regenerate with `python -m eval.demo_log` and read `demo.md`. The API exposes the same data live: `GET /api/audit`, `GET /api/audit/verify`, `GET /api/proof/{intent_id}/verify`, `POST /api/demo/run`.

## Regenerating

```bash
# from the repository root, with the venv active (all offline unless stated)
PYTHONPATH=. python -m eval.runner                     # benchmark.md/.json
PYTHONPATH=. python -m eval.simulator                  # simulation.md/.json
PYTHONPATH=. python -m eval.planning                   # planning.md/.json (offline section)
PYTHONPATH=. python -m eval.demo_log                   # demo.md/.json
OASIS_DB=:memory: OASIS_LLM=offline PYTHONPATH=. python -m pytest -q    # 142 tests
```

Live results need `GROQ_API_KEY` in `.env` and a Groq free-tier budget (about 200k tokens/day). The runner is resumable (checkpoints in `data/bench_cache/`, git-ignored) and stops cleanly with exit code 2 when the daily budget is spent. Responses are cached in `data/llm_cache/` (git-ignored), so the committed live reports are the evidence of the 2026-10-10 runs; a fresh clone re-queries the model and, because models drift and may be retired, will not reproduce them exactly. Offline reports are deterministic and regenerate identically (apart from the run timestamp).

## Caveats

- Live benchmark: one repeat, temperature 0, six injection-bearing scenarios. Not a robustness claim.
- Live planning: three of eight scenarios, one run; two of three fell back to the deterministic plan because of the per-plan token cap.
- Simulated humans approve or decline according to the Passport; they are not oracles. Savings are driven by mock fees.
