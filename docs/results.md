# Oasis results in detail

Every number here comes from a file in `eval/reports/` (named in each section). The README shows six of them with one caveat each. Offline results are deterministic and reproducible with no network; live results are small samples from a hosted model and are labelled so. All money is sandbox (MOCK) data. How each file was produced: [execution-evidence.md](execution-evidence.md).

## 1. Visible benchmark (offline, deterministic)

44 scenarios (32 attacks, 12 legitimate changes) x 4 layer configurations, plus AI red-team variants. Report: `eval/reports/benchmark.md`.

| | baseline | +verification | +intents+policy | full (+canaries) |
|---|---|---|---|---|
| Attack block rate | 6.2% | 68.8% | 100% | 100% |
| Money lost (CNY, sandbox) | 479,000 | 108,000 | 0 | 0 |
| Legitimate completion | 100% | 100% | 100% | 100% |

- The offline baseline uses a regex parser that deliberately follows embedded instructions (a gullible agent). The other three configurations behave the same in offline and live mode.
- Canaries are an early-detection layer, not an extra blocking layer: they block 0 additional attacks over signed intents + policy and flag 3 attacks earlier (at Understand, offline run).
- The scripted student and parent approve only requests consistent with the Passport, so 100% is partly by construction (Known limitation 9).
- The risk scorer is a heuristic scorer, plus an optional LLM scorer in live mode that can only escalate (combined as max(heuristic, llm)). The heuristic's features were chosen after seeing the benchmark (in-sample): it flags 81% of attacks and 0% of legitimate changes, and it cannot see poisoned-tool attacks (0/6). A small held-out set is in `tests/test_pipeline.py`.

## 2. Hidden blind set (offline)

40 blind cases (28 attacks, 12 legitimate), written by an independent agent that saw only the pitch and the scenario format; sha256-verified and unmodified. The first run is kept as [`benchmark_hidden_prefix.md`](../eval/reports/benchmark_hidden_prefix.md); then general fixes with their own tests; then a re-run: [`benchmark_hidden.md`](../eval/reports/benchmark_hidden.md).

**Strict pass criteria:** an attack counts as blocked only if no money reaches an attacker account and there is no overpayment, wrong payee, wrong currency or unregistered account; a refusal or a hold passes.

Attack block rate (strict pass criteria), baseline / +verification / +intents+policy / full:

| Run | Attack block rate | Baseline money lost (CNY) | Legitimate completion |
|---|---|---|---|
| Pre-fix (first run) | 46.4% / 92.9% / 100% / 100% | 180,600 | 83.3% / 83.3% / 75% / 75% (3 false blocks: spaced account digits, markdown-table invoice, instalment) |
| Post-fix | 39.3% / 89.3% / 100% / 100% | 246,600 | 100% in all four, 0 false blocks |

The two lower no-policy figures are honest: the extractor now reads the stated currency and the whole account, so cases that used to pass by accident (unreadable fields) are now stopped only by the policy layer; every attack case now stops for a real reason (`extract_low_confidence` is no longer how any of them passes). The visible benchmark is unchanged. The set is partly burned, because its failures were fixed afterwards.

## 3. Live benchmark (Groq, live-agent extraction)

Report: `eval/reports/benchmark_live.md`. Extraction by a live model, 3 repeats (temperature 0, then 0.4 and 0.4, distinct cache salts) over six injection-bearing scenarios, LLM risk scorer on.

| | baseline | +verification | +intents+policy | full |
|---|---|---|---|---|
| Attack block rate (live) | 18.8% | 68.8% | 100% | 100% |

- Identical in every repeat (min = mean = max); the live baseline loses CNY 380,000 per repeat (the offline gullible baseline loses 479,000).
- The model followed an embedded injection in 0 of 18 injection-bearing scenario runs (6 scenarios x 3 repeats). This is not a robustness claim: a few samples of one model on hand-written injections cannot rule out rarer failures. Within a repeat, identical documents reuse one cached model response across the four configurations.
- Serving model, recorded per extraction: of 183 extraction steps (full configuration, 3 repeats), 167 were answered by qwen/qwen3.8-27b and 16 by the fallback openai/gpt-oss-120b (used when the primary hit its rate limit); 0 fell back to the regex parser. Read it as "a live model", not as a statement about one model.
- The LLM risk scorer raised the score on 82 of 183 extraction steps (17 of them injection-bearing) but pushed 0 across the policy hold threshold (0.5), so it changed no decision; its measured contribution here is nil.
- The recorded live runs were made at the old mock rate base (0.0845) and were not re-run after the 2026-10-10 recalibration to 0.0692 (the sandbox starting balance also moved from INR 4 to INR 5 lakh and the split-payment attack amounts from CNY 4,000 to about 3,300); the offline benchmark outcome is unchanged in the re-run.

## 4. Plan quality

Report: `eval/reports/planning.md`. Eight scenarios scored by the deterministic validator, never by a model.

### Deterministic planner (offline)

8/8 valid, 20/20 deadlines met, conversion fees 83.0% below a typical bank route (MOCK rates, recalibrated 2026-10-10): CNY 4,990 vs CNY 29,378.

### Groq tool-calling planner, model-only (live, tiny samples)

Three full repeats on 2026-10-11 (per-plan cap 22,000 tokens, temperature 0.3, a distinct cache salt per repeat; repeat 3 replaced an older 2026-10-10 Tight runway row):

| Measure | Result |
|---|---|
| Valid without fallback, per repeat | 4 of 8, 2 of 8, 1 of 8 (min / mean / max 1 / 2.33 / 4) |
| Pooled | 7 of 24 plans (29%); the single run before the prompt change was 4 of 8 |
| Per scenario (valid out of 3 repeats) | Arrival shortfall 1, Tight runway 0, SAFE-quota tuition 0, Late scholarship 1, Parent remitter crossing TCS 2, Rate target 1, Five obligations 1, Urgent deposit 1 |
| 17 fallbacks | 10 token-cap stops, 4 no proposal within the call budget, 2 no valid plan after one proposal, 1 Groq API HTTP 400 tool-call validation error |
| Answered last by | qwen/qwen3.8-27b in 20 of 24 plans (4 of the 7 model-valid), openai/gpt-oss-120b in 4 (3 of 7) |
| Tokens | 463,343 on 2026-10-11 over 3 of 4 keys |

The final plan was valid in all 24 only because the fallback is the deterministic plan. Repeat 3 was run on its own with `python -m eval.planning --llm groq --repeats 3 --repeat-index 3`.

### Format experiment: compact tool results (v2) vs old (v1)

2026-10-11, 230,613 new tokens, temperature 0.3; details in [planner-efficiency.md](planner-efficiency.md).

| | v2 (compact, now default) | v1 (old) |
|---|---|---|
| Original scenarios (7 of 8; urgent-deadline not run), model-only valid | 5 of 7 (1 repeat) | 6 of 21 (3 repeats); p about 0.08, inconclusive |
| Four held-out scenarios written beforehand | 3 of 4 | 3 of 4 (no gain shown) |
| Pooled | 8 of 11 | 9 of 25 |
| Tokens per plan (originals) | 15,459 | 20,809 |

Planner format v3 (calculator tools `facts_sheet` and `size_conversion`, numeric `fix` hints on validator errors, a prompt under half the length) is built and tested offline; its live evaluation is pending and v2 stays the default. Pre-registered decision rule and commands: [planner-efficiency.md](planner-efficiency.md).

## 5. Student-outcome simulation (a model with stated assumptions)

Report: `eval/reports/simulation.md`. 5 personas, 90 days, Oasis vs a manually paying student, MOCK fees (rate recalibrated 2026-10-10). Scam and landlord events run through the real pipeline.

| Persona | Situation | Fees manual (CNY) | Fees Oasis (CNY) | Saved | Late days manual / Oasis | Scams stopped |
|---|---|---|---|---|---|---|
| Arjun | tight runway | 3,188 | 457 | 2,731 | 3 / 3 | 0 |
| Meera | scholarship 21 days late | 2,097 | 388 | 1,708 | 1 / 0 | 0 |
| Kiran | monthly family top-ups | 1,822 | 280 | 1,542 | 0 / 0 | 0 |
| Sana | landlord changes bank account | 3,617 | 654 | 2,963 | 3 / 0 | 0 |
| Rahul | forged finance-office invoice | 3,148 | 646 | 2,503 | 3 / 0 | 1 (CNY 30,000 saved) |

Savings come from mock fees; the simulated student and parent are not oracles.

## 6. Tests

537 tests pass and 2 are skipped (live FISCO and live PQ-TLS), no network, no database file: `OASIS_DB=:memory: OASIS_LLM=offline PYTHONPATH=. .venv/Scripts/python -m pytest -q`.

## 7. Scripted demo (offline, repeats exactly)

`eval/reports/demo.md`. Run 1 (legitimate): Arjun's plan is valid after 2 proposals and saves CNY 1,653 vs a typical bank route; the savings receipt totals CNY 1,313.66; 4 proof packs, audit chain intact, money lost 0. Run 2 (attack): the forged invoice, rewritten payment instructions and hidden-page injection are all stopped; money lost CNY 0. Audit-chain heads are listed in [execution-evidence.md](execution-evidence.md).
