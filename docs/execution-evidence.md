# Execution evidence (sandbox logs and reports)

Everything below ran on the simulated sandbox (MOCK rates, rails, registry and balances). Nothing was sent to a real bank or blockchain. The benchmark, demo and simulation reports contain no on-chain transaction hashes: they anchor on the local hash-linked simulation (`LocalAnchorChain`) by design. The real FISCO BCOS transaction hashes (local 4-node chain) are in [`fisco-bcos.md`](fisco-bcos.md) and the post-quantum TLS handshake evidence is `eval/reports/pqtls.md`. The audit-chain head hash in the demo log plays the equivalent role for tamper evidence.

| Evidence | Files (in `eval/reports/`) | What it shows | Produced by |
|---|---|---|---|
| Hidden test set, pre-fix and post-fix | `benchmark_hidden_prefix.md/.json` (first run, kept unchanged), `benchmark_hidden.md/.json` (after the general fixes, with pre/post table and why each case passes) | 40 blind cases, sha256-verified, strict criteria | `python -m eval.runner --suite hidden` |
| Post-quantum TLS handshake | `pqtls.md` | Caddy 2.11.7 + OpenSSL 3.5.9 negotiated X25519MLKEM768; classical-only client refused | `tools/caddy/verify-pq.ps1` |
| Offline benchmark (deterministic extraction) | `benchmark.md`, `benchmark.json` | 4 configurations x (32 attacks + 12 legitimate changes) + 4 AI red-team variants: block rate, money lost, detection, legit completion, false blocks, canary early detections, risk-scorer accuracy | `python -m eval.runner` |
| Live benchmark (Groq, live-agent extraction) | `benchmark_live.md`, `benchmark_live.json` | Same suite with a live model extracting (qwen/qwen3.8-27b configured as primary; which model served each extraction was not recorded in this run and is labelled "model not recorded (pre-fix run)"; newer runs record it per extraction), 9 AI red-team variants, per-field extraction provenance, "model followed injection" counts, deterministic reference table. Re-run 2026-10-10 with 3 repeats (temperature 0, 0.4, 0.4; distinct cache salts) and the LLM risk scorer; per-extraction serving model is now recorded (qwen/qwen3.8-27b 167, openai/gpt-oss-120b 16 of 183 steps); the earlier single-repeat run is superseded | `python -m eval.runner --llm groq --extract llm --llm-risk --repeats 3` |
| Planning evaluation | `planning.md`, `planning.json` | 8 planning scenarios scored by the deterministic validator: offline 8/8 valid; live: the earlier single run (4/8 valid without fallback) is kept as 'before planner prompt change'; after the change (prompt carries the validator's error vocabulary, 22k per-plan cap, temperature 0.3, per-repeat cache salt) 24 plans ran on 2026-10-11 (three full repeats): 4/8, 2/8 and 1/8 valid without fallback (min / mean / max 1 / 2.33 / 4 of 8), pooled 7 of 24; qwen/qwen3.8-27b answered last in 20 of 24 plans | `python -m eval.planning` (live: `--llm groq --repeats 3 --token-cap 300000`; one repeat alone: add `--repeat-index 3`) |
| Planner format experiment | `planning.md` (last section), `planning_experiment.json`, [`../planner-efficiency.md`](../planner-efficiency.md) | compact tool results (v2) vs old (v1) on the original scenarios and four held-out ones, 2026-10-11, 230,613 tokens: model-only valid 5/7 (v2, 1 repeat) vs 6/21 (v1, 3 repeats) on the originals, 3/4 vs 3/4 on held-out; tiny samples, inconclusive (p about 0.08) | `python -m eval.planning_experiment --format v2 --set heldout --rep 0 --cap 90000` (needs Groq keys); `--report` re-renders the tables offline |
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
- Live planning: 24 plans on 2026-10-11 (three full repeats of 8; 463,343 tokens on the day's ledger over three of four comma-separated keys: 181,449 on 499b1366, 181,477 on d40d45b2, 100,417 on ceef6c23, 0 on a1d412ac; repeat 3 alone cost 162,737). Valid without fallback 4 of 8, 2 of 8 and 1 of 8 (min / mean / max 1 / 2.33 / 4), pooled 7 of 24 (29%); 17 fallbacks (10 token-cap stops, 4 no proposal within the call budget, 2 no valid plan after one proposal, 1 Groq HTTP 400 tool-call validation error). The final plan is valid in every row only because a fallback is the deterministic plan. qwen/qwen3.8-27b answered last in 20 of 24 plans, openai/gpt-oss-120b 4. Repeat 3 replaced an older 2026-10-10 Tight runway row (see `planning.md`; the earlier single run is kept there as 'before').
- Live-replay demo fixture (`eval/fixtures/demo_cache/`): not recorded yet; until it is, live-replay shows labelled offline fallbacks. Record with `python -m eval.record_demo_fixture`.
- Simulated humans approve or decline according to the Passport; they are not oracles. Savings are driven by mock fees.
