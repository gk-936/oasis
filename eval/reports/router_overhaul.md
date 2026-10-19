# Router overhaul log

All figures are model off: the deterministic path (`OASIS_LLM=offline`, `OASIS_CHAT_LLM=0`). Plan: `ROUTER_OVERHAUL.md`; design summary: `docs/router-overhaul.md`; set scores: `eval/reports/router_sets.md`.

## Baseline (build 813fa78, before Phase 1)

| Measure | Result |
|---|---|
| Noise probe (`eval/probes/router_probe_noise.py`, 12 requests x 29 transforms) | 343/348 (98.6%) |
| Paraphrase probe (`router_probe_paraphrase.py`) | 47/78 (60%) |
| Attack probe (`router_probe_attacks.py`, 50 strings) | money moved 0 |
| Full suite | 2299 passed, 2 skipped |
| Frozen set (`eval.frozen_set`) | 130/151 |
| Fuzz | the committed report said 0 hard breaches; a fresh run of this same build reports 13 (own-wallet conversion drafts flagged by the checker as "outside the registry"). The checker was corrected to exempt `own:` and `revoke:` drafts, which pay no one |

## Phase 1 (policy fix, FAQ, hedge)
- Replaced the numbered clarify menu with answer-the-best-candidate plus a one-line offer (`last_offer`; a bare yes shows only that answer). Added `oasis/agent/faq.py` (60+ answers, retrieval, hedge). Removed the two generic fallback strings from the code (a test greps for them).
- Paraphrase probe 47 -> 62/78; noise 343/348 (no change). Seven existing tests encoded the old menu and were rewritten.

## Phases 2 to 4 (frames, context, compound, scam lane, catalogue)
- Added `lexicon.py`, `frames.py`, `router_v2.py`, `context.py`, `scam_lane.py`, the revoke path (`mandate_exec.handle_revoke`), the reported-speech guard, the compound splitter and the attacker catalogue (205 items; rows A12 and A15 are tested at API level and in `tests/test_router_model.py`).
- The first full gate run after these phases failed 59 existing tests because the new layer overrode correct keyword answers. The layer was narrowed (a pay rewrite only for a real order, the existing similarity layer answers first, negation and question guards). The next full run passed except two catalogue expectations I had written too strictly; those were corrected.
- Deviation recorded: a message that mixes a real request with an attack is still refused as a whole (60 existing adversarial tests pin it).

## Phases 5 to 7 (sets, model path, scorecard)
- `eval/phrase_generator.py`, `eval/router_sets.py`: DEV (tuned on), WORD-HELD-OUT (30% of each concept's words removed from the lexicon while it runs, seed 20261019), BLIND loader (empty).
- `chat_llm.interpret` (flag-gated, stub-tested, 400-call cap), `scorecard.py` + `GET /api/agent-scorecard`, mandate card.

## Final gates (same code, run together)

| Gate | Result |
|---|---|
| `pytest -q` (offline, in-memory DB) | 2628 passed, 2 skipped |
| Attack benchmark (`eval.runner --llm offline`) | money lost CNY 0 (full pipeline row) |
| Fuzz (`eval.fuzz_bench`) | 0 hard breaches, 0 walk breaches |
| `execution_evidence/verify_evidence.py` | all checks passed |
| `eval.frozen_set` | 136/151 (130/151 before) |
| `tests/data/router_heldout.json` gate | passes (inside the suite) |

## Final measurements

| Measure | Baseline | Final | Note |
|---|---|---|---|
| Noise probe | 343/348 | 344/348 | |
| Paraphrase probe | 47/78 (60%) | 75/78 (96%) | measured one build earlier; the items overlap what was tuned on |
| Attack probe | money moved 0 | money moved 0 | |
| Attacker catalogue | n/a | 205/205 | written and tuned by the implementer |
| DEV (2,400 generated) | n/a | 86.9% | tuned on; bar was 95% (not met) |
| WORD-HELD-OUT (1,600 generated) | n/a | 58.9% | not tuned on; bar was 85% (not met) |
| BLIND | n/a | not run | no independent messages exist yet; bar was 80% |
| Frozen set | 130/151 | 136/151 (90%) | |
| Menu rate on answer/draft messages | n/a | 1.5% DEV, 4.0% held-out | bar 3% (DEV met, held-out not) |
| "I didn't catch" replies | 2 (frozen) | 0 | |
| Money moved | 0 | 0 | every set, probe, catalogue item and benchmark |

Numbers that fell: none against the baseline. The noise probe dipped to 340/348 midway (a "stressed ... anyway" lead-in was read as a worry), fixed and re-measured at 344/348.

Bars not met, stated plainly: DEV 86.9% (bar 95%), WORD-HELD-OUT 58.9% (bar 85%), BLIND not run (bar 80%). The held-out gap is mostly vocabulary the router does not know ("data plan", "airtime", "credit card"), where it asks which bill rather than guessing, plus existing tests that pin older answers.

## Not done, on instruction
- The three PDFs were not rebuilt (instruction: not unless asked). They still state 2299 tests and the earlier router description. `eval/build_*_pdf.py` hold the old count too.
- Model-on figures are a separate measurement (the interpreter is built and covered by stub tests); every figure in this log is model off.
- Phase 9 (freeze): the submission cut-off and its time zone are not in the material; confirm with the organisers, then run all gates once on the exact zip from a clean extraction.
