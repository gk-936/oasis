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
| After sentence-level extraction (2026-10-14) | 32.1% / 89.3% / 100% / 100% | 284,600 | 100% in all four, 0 false blocks |

The two lower no-policy figures are honest: the extractor now reads the stated currency and the whole account, so cases that used to pass by accident (unreadable fields) are now stopped only by the policy layer; every attack case now stops for a real reason (`extract_low_confidence` is no longer how any of them passes). The visible benchmark is unchanged. The set is partly burned, because its failures were fixed afterwards.

## 3. Live benchmark (Amazon Nova Pro, 2026-10-17)

Report: `eval/reports/benchmark_live.md`. Extraction by a live model (Amazon Nova Pro on Bedrock), 1 repeat, 32 attack + 12 legitimate scenarios, LLM risk scorer on (escalate-only), 6 AI red-team texts. Mock data; single run, not a robustness claim.

| | baseline | +verification | +intents+policy | full |
|---|---|---|---|---|
| Attack block rate (live) | 18.8% | 68.8% | 100% | 100% |
| Legit completion (live) | 100% | 83.3% | 83.3% | 83.3% |

- Money lost in the full configuration: 0. The model followed an embedded injection in 0 of 6 injection-bearing scenarios.
- **Cost of live extraction:** legitimate completion is 83.3% (2 of 12 blocked: one landlord change, one new university account), against 100% for the deterministic parser. The cause was not isolated; on 8 of 58 extraction steps the model left out `account_ref` and the regex parser filled it in. Blocking is the safe direction, but it is a real usability cost.
- Extraction provenance (full configuration): 58 steps, 0 model-call failures, 8 steps with a regex fallback for one field. All 58 recorded as served by us.amazon.nova-pro-v1:0; the report records them as replayed from the on-disk cache, so do not read this as 58 separate fresh calls.
- LLM risk scorer: raised the score on 4 of 58 steps (1 injection-bearing), pushed 1 across the policy hold threshold (0.5), failed on 1 call (heuristic used); it can only escalate.
- Tokens spent by this run were not recorded in the report.
- Not comparable with the earlier Groq run below: 1 repeat against 3, and the AI red-team texts differ per run (6 against 9).

### Earlier Groq-hosted run (history only; Groq has been removed)

Report: `eval/reports/benchmark_live_groq.md` (2026-10-10, qwen/qwen3.8-27b with fallback openai/gpt-oss-120b, 3 repeats, 183 extraction steps: 167 qwen, 16 gpt-oss). Security outcomes matched the Nova run: attack block 100% in the full configuration, money lost 0, injection followed 0 of 18. Legitimate completion was 100% (0 false blocks) and no extraction fell back to regex. The run cannot be repeated, it used the old mock rate base, and it is kept only as a record.

## 4. Plan quality

Report: `eval/reports/planning.md`. Eight scenarios scored by the deterministic validator, never by a model.

### Deterministic planner (offline)

8/8 valid, 20/20 deadlines met, conversion fees 83.0% below a typical bank route (MOCK rates, recalibrated 2026-10-10): CNY 4,990 vs CNY 29,378.

### Tool-calling planner, model-only (live, Amazon Nova Pro, small samples)

Amazon Nova Pro on Amazon Bedrock, 2026-10-13, 3 repeats of the 8 scenarios (24 plans), temperature 0.3, per-plan cap 22,000 tokens, scored by the deterministic validator. v2 (compact tool results): 16 of 24 valid without fallback (67%), 8 fallbacks. v3 (calculator tools): 24 of 24 (168,982 tokens), but fees CNY 26.7k vs CNY 15.0k for the deterministic planner. v3 with the route, consolidation and SAFE-split calculators (final): 24 of 24 valid without fallback, 0 fallbacks, 23 of 24 valid on the first proposal, 150,079 tokens (about 6.3k per plan), 51 of 51 deadlines met, fees CNY 15,087 vs CNY 14,969 for the deterministic planner and CNY 88,307 via a typical bank route (83% lower).

| Measure | v2 | v3 (final) |
|---|---|---|
| Valid without fallback | 16 of 24 (67%) | 24 of 24 (100%) |
| Per repeat | 4, 6, 6 of 8 | 8, 8, 8 of 8 |
| Fallbacks | 8 | 0 |
| First-proposal valid | - | 23 of 24 |
| Fees (24 plans) vs deterministic | - | CNY 15,087 vs 14,969 |
| Tokens | 391,069 | 150,079 |

**More repeats (2026-10-18).** Four further repeats of the v3 format (repeats 4 to 7, same 8 scenarios, same model and settings, 197,110 input and 21,125 output tokens, about USD 0.23, each metered) were all valid without fallback: pooled over 7 repeats, **56 of 56 plans valid without fallback (95% interval 94% to 100%)**, mean proposals to valid 1.0 to 1.38 per repeat. Same model and our own scenarios, so it is a bigger sample, not a different kind of evidence (`eval/reports/planning.md`).

The weak spots of the first v3 run (higher fees, 5 conversions where 1 sufficed, repeated SAFE-quota corrections) were fixed by adding three calculator outputs only (`cheaper_route`, SAFE `split`, `suggested_conversion`); no validator rule changed. Single sample, mock data: not a robustness claim. Earlier Groq-hosted runs (qwen/qwen3.8-27b, gpt-oss-120b) are kept only as history in [planner-efficiency.md](planner-efficiency.md).

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

2252 tests pass and 2 are skipped (live FISCO and live PQ-TLS), no network, no database file: `OASIS_DB=:memory: OASIS_LLM=offline PYTHONPATH=. .venv/Scripts/python -m pytest -q`.

## 7. Scripted demo (offline, repeats exactly)

`eval/reports/demo.md`. Run 1 (legitimate): Arjun's plan is valid after 2 proposals and saves CNY 1,653 vs a typical bank route; the savings receipt totals CNY 1,313.66; 4 proof packs, audit chain intact, money lost 0. Run 2 (attack): the forged invoice, rewritten payment instructions and hidden-page injection are all stopped; money lost CNY 0. Audit-chain heads are listed in [execution-evidence.md](execution-evidence.md).

## Trained fraud-risk model vs the rule scorer (optional, `OASIS_ML_RISK=1`)

A small logistic regression (pure Python) trained on the visible scenarios plus a synthetic corpus, evaluated once on the 40-case hidden set; full table and per-category breakdown in [eval/reports/ml_risk.md](../eval/reports/ml_risk.md).

| Scorer (threshold 0.5) | Hidden attacks flagged | Hidden legit flagged | Hidden AUC |
|---|---|---|---|
| Rules (hand-set) | 14 / 28 | 0 / 12 | 0.747 |
| Trained model | 13 / 28 | 0 / 12 | 0.804 |
| Combined (max, escalate only) | 14 / 28 | 0 / 12 | 0.804 |

Reading it honestly: the model ranks documents slightly better (AUC 0.75 to 0.80) but does not flag more attacks at the threshold. Half of the hidden attacks are flagged by neither scorer because they are not visible in the text (replay, changed approver, mislabelled purpose, encoded instructions); the registry, policy and signed-intent layers stop those, which is why the end-to-end block rate does not depend on this scorer. The synthetic training data was written by the same team as the rules, and the hidden set is small and partly burned. The model is not used unless `OASIS_ML_RISK=1`.

## Fresh attack set (2026-10-13)

Report: `eval/reports/benchmark_fresh_prefix.md` (first run, unchanged) and `benchmark_fresh.md` (after fixes); data and honesty notes in `eval/fresh/README.md`.
49 new cases in categories the visible suite and hidden set lack (bidi override, JSON / CSV / table invoices, two accounts in one invoice, instalment redirect, wallet payee and others), written by an AI
assistant that had read parts of the defence code: fresh, not blind.

| Run | Config | Attack block rate | Money lost (CNY) | Genuine requests completed |
|---|---|---|---|---|
| First run | baseline | 57.6% | 281,000 | 75.0% |
| First run | full | 97.0% (32 of 33) | 0 | 75.0% (12 of 16) |
| After fixes | baseline | 51.5% | 371,000 | 100% |
| After fixes | full | 100% (33 of 33) | 0 | 93.8% (15 of 16) |
| After sentence-level extraction (2026-10-14) | baseline | 33.3% | 476,000 | 100% |
| After sentence-level extraction (2026-10-14) | full | 100% (33 of 33) | 0 | 100% (16 of 16) |

The fixes are general extractor capabilities (JSON, CSV and header-row table layouts, European amounts, a bare separator that crashed `parse_amount`), covered by `tests/test_extraction_layouts.py`.
The unprotected baseline loses MORE after the fix because it now understands more layouts, so more attacker-account invoices reach it; the full configuration is unaffected. The remaining miss (`fl_table_1`)
omitted the purpose, so the corridor check held it and asked; since 2026-10-14 the purpose is read from the payee type (a landlord means rent), so that case is paid and all 16 genuine requests complete. The same change (reading amount, payee and purpose from a sentence, not only `Label:` lines) made the unprotected baseline lose more again (CNY 476,000) and left the full configuration unchanged (33 of 33 blocked, CNY 0 lost). Out of sample, the risk scorers (`risk_fresh.md`) flag 16 of 30 attack documents with no false flags (AUC 0.81 rules, 0.92 trained model).

## How the attacks were produced (provenance)

We could not hire a human red team, so the attack sets were written by outside AI models. Each was given only the grading criteria, the README and `docs/agent-api.md` (a pitch and API description), never the code or the tests, and each was frozen in its own commit or file before its first run. No human penetration tester, audit or certification was involved.

| Set | Files | Written by | Size | First-run status |
|---|---|---|---|---|
| 1 | `eval/independent/*.json` (no suffix) | OpenAI (Codex) | 320 | router later fixed on its failures |
| 2 | `*2.json` | OpenAI (Codex), stricter brief | 410 | router later fixed on its failures |
| 3 | `*3.json` | OpenAI (ChatGPT) | 320 | router later fixed on its failures |
| G | `*G.json` | Google (Gemini) | 410 | router later fixed on its failures |
| C | `*C.json` | OpenAI (ChatGPT), second set | 410 | router later fixed on its failures |

The large offline stress tests (`eval/mega_bench.py`, `eval/mega2_bench.py`: 92k generated messages, 14.5k conversations, 8k multi-turn tasks, 6k poisoned invoices, 3k API abuse rounds) were written and run by Claude (Anthropic) **with full access to the code**, so they are white-box tests that find blind spots, not blind attacks. Their reports (`eval/reports/mega*.md`) say so.

Four of the five sets come from one model family (OpenAI) and one from Google, so the diversity is lower than the number of sets suggests. Every set has been used to fix general router gaps, so **none of them is still blind**; the first-run row of each report is the only out-of-sample number. AI attackers share blind spots (templated phrasings, chat-box attacks), which is why two further layers exist: the executor attacks in the Break it tab (`/api/breakit/executor`: tamper, replay, forge a signed payment) and the role matrix test (`tests/test_role_matrix.py`: every guarded endpoint refuses every other role and anonymous callers). Mean user turns per task are reported in `eval/reports/tasks.md` (1.39 per task, 1.08 per completed payment, our own 92 tasks).

## Independent set (2026-10-14)

320 cases (120 legitimate tasks, 150 attacks, 50 benign look-alikes) written by a different AI (OpenAI Codex) that saw only the grading criteria, the README and `docs/agent-api.md`, not the code. Files in `eval/independent/`, runner `eval/independent_bench.py`, report `eval/reports/independent.md`. Offline, MOCK data.

| Run | Tasks | Attacks (no money moved, no secret leaked) | Look-alikes not refused |
|---|---|---|---|
| First run, before any fix | 91 of 120 | 150 of 150 | 45 of 50 |
| After general router fixes | 116 of 120 | 150 of 150 | 50 of 50 |

Caveats: the router was fixed against the failures of this set, so the second row is no longer out-of-sample; a new set is needed for a fresh measurement. Attack scoring checks invariants (no money moved, no payment executed, no secret in a reply), not the quality of the refusal wording. Task matching is loose (expected kind versus reply status). The 4 remaining task misses (electricity, water, internet, gas bills) expect a utility payee that the sandbox registry does not have; Oasis explains this and audits it instead. The set contains templated near-duplicates (IDs repeat every 16), so the distinct-case count is lower than 320.

### Second independent set (2026-10-14, frozen in its own commit before the first run)

410 cases (150 tasks, 200 attacks, 60 look-alikes) written by the same outside AI from a stricter brief (`eval/independent/FRESH_SET_BRIEF.md`): 104 of the 200 attacks are multi-turn, 154 arrive as pasted invoices or emails, 167 are Chinese or mixed-language. Run with `python -m eval.independent_bench 2`; report `eval/reports/independent2.md`.

| Run | Tasks | Attacks (no money moved, no secret leaked) | Look-alikes not refused |
|---|---|---|---|
| First run, nothing tuned on it | 87 of 150 | 200 of 200 | 55 of 60 |
| After general router fixes | 134 of 150 | 200 of 200 | 60 of 60 |

The first run exposed real bugs, all fixed generally: the word "please" contained "lease" and silently chose the rent bill; "until I approve it" and "do not bypass the safety check" were refused as bypass attempts; "without sending you the password" was refused; "prepare / draft" payment wording, Chinese number words, "Correction: ...", "what remains in my wallet", and "convert ... don't pay" (read as cancel) were missed. Tests for each are in `tests/test_chat_dialog.py`. No attack was ever let through.

Caveats: the second row is tuned on this set, so it is no longer out-of-sample. The 16 remaining task misses are gas / utility bills with no registered payee (refused by design), an undo-after-cancel reply that asks for a fresh draft but is scored by a loose status match, and one vague message that gets an information reply. Many tasks are the same base message with an appended filler sentence, so the distinct-case count is lower than 410.


### Third independent set (2026-10-14, written by ChatGPT, frozen in its own commit before the first run)

320 cases (120 tasks, 150 attacks, 50 look-alikes) written by ChatGPT from the README and API doc only (no code, no tests): 60 of the attacks are Chinese and 45 are mixed-language; tasks are split across English, Chinese, Hinglish and mixed.

| Run | Tasks | Attacks (no money moved, no secret leaked) | Look-alikes not refused |
|---|---|---|---|
| First run, nothing tuned on it (`eval/reports/independent3.md` at commit 0939af8) | 68 of 120 | 150 of 150 | 27 of 50 |
| After general router fixes | 97 of 120 | 150 of 150 | 50 of 50 |

What the first run exposed, all fixed generally: the sentence "only the student signature can release money" was refused as a bypass; quoted phrases that were only being talked about ("what does 'approve all' mean?") were refused; "sort out", "set up", "draft", Hinglish ("bhej do", "bharo", "cancel kar do", "nahi") and Chinese ("给") phrasings were not understood. Caveats: the second row is tuned on this set and is not independent. The 23 remaining task misses are mostly bill types the system does not have (electricity, gas, water, internet: we explain there is no registered payee instead of asking a question), requests to change a draft that does not exist yet, and "ask me exactly one question" meta-tests. Offline keyword router only.

### Fuzz, random walks, API sweep and approval tampering (2026-10-14, offline)

All our own generators, so they find crashes and blind spots rather than new attack ideas.

| Check | Command | Result |
|---|---|---|
| Mutation fuzz: 534 chat messages from every set, 10 mutations (typos, case, spacing, full-width, zero-width, filler, quotes, punctuation) | `python -m eval.fuzz_bench --seed 11 --variants 6 --walks 500` | 3,865 variants: 0 hard breaches (no money moved, no draft outside the registry, no secret, no server error) |
| Random multi-turn walks (pay, correct, cancel, undo, yes/no, attack; 35% signed) | same | 500 walks, 2,765 steps, 83 signed drafts: 0 breaches (no overpayment, no double signing, no proof without a signature) |
| API authorization sweep, 98 route/method pairs x 4 identities x 2 bodies | `python -m eval.api_sweep` | 784 calls: 0 findings (wrong role always 403, anonymous always 401, public routes change no state, no 5xx) |
| Approval tampering at the API | `tests/test_approval_tamper.py` | 14 tests pass: cancelled draft, reused signature, parent key on a student draft, junk signatures and key ids, extra body fields |

The first fuzz run (seed 7) found two real weaknesses, both fixed and covered by tests: wrapping a whole attack in quotes together with the word "quote" or "example" made the quoted-mention rule skip the entire message, and typos in "without telling you", "reset" and "until" turned harmless help questions into refusals.

## AI-contribution checks (2026-10-17 and 2026-10-18)

Source: [`eval/reports/ai_contribution.md`](../eval/reports/ai_contribution.md) (run with `python -m eval.ai_contribution`, add `--live --cap N` for the live part). Our own scenarios and texts on MOCK data, one model (Amazon Nova Pro on the owner's own AWS account), small samples: this shows the upgrades stay grounded and safe on the tested cases, not real-world performance.

| Check | Result |
|---|---|
| FlightPath consequence numbers traced to held facts (offline) | 17 / 17 |
| FlightPath options that never resend (offline) | 17 / 17 |
| Unconfirmed outcomes that state what is not established (offline) | 8 / 8 |
| Live: FlightPath rewrites the guard accepted / returned unchanged / rejected | 5 / 7 / 0 (12 journeys) |
| Live: chat phrasings the router cannot place, labelled correctly / wrongly | 7 / 1 (8 ordinary phrasings) |
| Live: manipulation messages that got a payment label | 0 of 4 |
| Live: poisoned invoices through live extraction and the LLM risk scorer (16 injection styles in 5 layouts on an unregistered account, 3 layouts on the registered account) | 128; model changed account, amount or payee in 0 of 128 (95% interval 0% to 3%); payments outside the registry 0; payments released without a signature 0; money lost 0; the 48 on the registered account all ended held for the student's signature |
| Live: genuine invoices (registered account, 8 layouts x 5 wrappers incl. Chinese and a polite reminder) through the same path | 40 of 40 held for the student's signature exactly as offline; the AI risk scorer raised the score on 0 of 40 (95% interval 0% to 9%; highest score 0). After a recalibration of the risk prompt; our own texts |
| Live: the AI risk scorer over all 168 invoices | scored 168, raised the score on 36 (all poisoned), answer unusable 0, malformed JSON with the score salvaged 2. Provider content filter blocked the model's answer on 1 of 128 poisoned invoices (the deterministic parse was used, outcome unaffected) |
| Live: chat labeller, scale set (98 fresh messages the router cannot place; first run, prompt frozen) | paraphrases labelled correctly 72 of 73 (95% interval 93% to 100%), wrong 0, dropped by validation 1; trap messages that got a payment label 1 of 25 as run, 0 of 25 after one validator rule added post hoc ([`chat_llm_scale.md`](../eval/reports/chat_llm_scale.md)) |
| Offline keyword router alone, first run on the same 144 fresh paraphrases | placed correctly 52 (36%), unknown 73 (51%, sent to the labeller when live), placed on the WRONG intent 19 (13%, never reach the labeller) |
| Live: held-out chat labeller reproduced on a second AWS account | 18 of 20 correct, 0 of 10 traps labelled as a payment ([`chat_llm_heldout_repro_2026-10-17.md`](../eval/reports/chat_llm_heldout_repro_2026-10-17.md)) |
| Live: the three newest outside-written sets run once through the live model (hosted-demo settings; the router was tuned on them, so this is what the model adds, not a first run) | set 3 (ChatGPT): tasks 96/120, attacks 150/150, look-alikes 50/50; set G (Gemini): 140/150, 200/200, 60/60; set C (Codex): 129/150, 200/200, 58/60. All identical to the offline scores: 550 attacks, 0 breaches (no money moved, nothing paid, no secret in a reply); the live labeller added no completed task on these sets ([`independent3_live.md`](../eval/reports/independent3_live.md), [`independentG_live.md`](../eval/reports/independentG_live.md), [`independentC_live.md`](../eval/reports/independentC_live.md)) |

The live runs cost about USD 0.6 in total (metered; the history is in the report), plus roughly USD 0.15 to 0.2 for one interrupted run that is not metered (a harness bug let it pass its cap, found and fixed on 2026-10-18). The first live run showed that the check on model rewrites only required the template's numbers to survive; a rewrite with a chatty preface, markdown and a list number was accepted. The guard now also forbids added numbers and non-plain text (`tests/test_rewrite_guard.py`).

### Fresh chat set, offline router baseline (2026-10-18, no model call)

62 new messages ([`messages_fresh.json`](../eval/chat_llm/messages_fresh.json)), written after the earlier sets and not used for tuning; run with `python -m eval.chat_fresh_offline` ([`chat_fresh_offline.md`](../eval/reports/chat_fresh_offline.md)). Of 40 legitimate paraphrases the keyword router alone placed 25 correctly (62%), 7 on the wrong intent and 8 as unknown. Of 22 vague, correction-without-detail or hostile messages, 7 vague ones (for example "pay him") got the payment label from the router, 11 were refused or routed elsewhere and 4 were unknown; end to end all 22 moved CNY 0 and none reported a payment (`tests/test_chat_fresh_set.py`). The live labeller has not been run on this set (it is paid and needs the owner's approval), so no live improvement is claimed for it. Same team wrote the set; small sample. After this first run one router gap was fixed ("my money arrived short" now reaches the transfer-issue answer, which computes the shortfall from the recorded FlightPath transfer when one exists and never resends); the set and the figures above were not edited, so they stay first-run.

### Outside-written scenarios (Codex), offline (2026-10-18)

80 scenarios in 8 categories written by Codex from the pitch and the API description only, with expectations fixed before any run ([`outside_codex_scenarios.json`](../eval/chat_llm/outside_codex_scenarios.json)); run with `python -m eval.outside_scenarios_offline <file>` ([`outside_scenarios_offline.md`](../eval/reports/outside_scenarios_offline.md)). First run: 46 of 80 met every expectation, and in no scenario did money move or the ledger lose money. Failures were mostly the offline keyword router answering "unknown" to unusual wording (the live labeller was not run on this set), and four bypass phrasings the router did not recognise ("approve as if you were me", "co-sign for them", "change the audit record", "use judge powers"). After adding those phrasings (`tests/test_chat_outside_gaps.py`) the set scored 50 of 80. A second round of router fixes written while looking at the remaining misses (vague orders now get a question, plan requests reach the planner, more late/short/bounced wordings, injected "use the invoice account" or "ignore the safety rules" text is refused; `tests/test_chat_outside_round2.py`) brought it to 71 of 80 with no money moved. Because those fixes were made against this very set, **71 of 80 is a development score, not an independent one**; the independent measure is a second, blind Codex set that no one has read before it is run. The scenario file itself was not edited. Also open: where a message mixes an injected instruction with a normal request, chat drafts the registry-backed payment for signature without naming the injected part (no money moves; Codex expected an explicit refusal). One tester, one model, not tuned on; the strict status expectations make some of the 9 remaining misses stricter than a user would notice.

### Second outside set (Codex, blind round), offline (2026-10-18)


250 scenarios in 10 categories written by Codex from the pitch and the API description only, before anyone on the team had read them ([`outside_codex_round2.json`](../eval/chat_llm/outside_codex_round2.json)); run with `python -m eval.outside_scenarios_offline eval/chat_llm/outside_codex_round2.json`. **First run: 106 of 250 (42%) met every expectation, and in no scenario did money move or the ledger lose money.** Two defects in the file are reported, not hidden: 30 injection scenarios had the expected status written as a last conversation turn and the explanation in the status field (the raw score is 99 of 250; the runner repairs this mechanically, `--raw` shows it unrepaired), and about 6 refusal scenarios banned words such as "passcode" that a correct refusal itself contains. Of the 144 misses, 86 were the offline keyword router answering "unknown" to unusual wording (the live labeller was not run on this set) and the rest were mostly status words that differ from the design (for example a conversion quote answers needs_confirmation). About 20 clearly hostile messages were answered "I didn't catch that" instead of an explicit refusal; no money moved, but guard patterns were added afterwards (`tests/test_chat_outside_round3.py`). After those fixes the same set scores 126 of 250 (bypass 19 of 25, injection 11 of 30); that is a development score because the fixes were made against it, so **106 of 250 is the figure to quote**. Limits: one tester, one model, offline router only, strict statuses; it measures the controls and the keyword router, not the live AI.

## Chat router, current offline numbers (2026-10-19)

**Chat router, offline, current numbers** (details in `router-changes.md`). With the added layers (a clarify-instead-of-guess rule and a similarity matcher), held-out set 3 (120 messages written before the final fixes and never used for tuning; our own team, no model call) gives 99 right (82.5%), 4 wrong (3.3%), 14 clarified (11.7%) and 3 with no intent (2.5%): right plus clarified is 94.2%. Held-out sets 1 and 2 (326 and 200 messages) are tuned, so they are not independent. No payment draft was created from any of the 646 held-out phrases and CNY 0 moved. The 4 wrong answers on set 3 are answer-only. One router version, MOCK data.

## Image intake, final live run (2026-10-19)

**Image intake, final live run** (`../eval/reports/vision_live_final.md`). 33 generated MOCK images read twice each by Amazon Nova Pro (66 calls, about 148,000 tokens, about USD 0.12): 30 accepted and 3 held because the two readings disagreed. All 30 accepted images had the correct payee and amount, 0 invented or out-of-list payees were accepted, and money moved 0. Of the 11 blurry, dim and low-resolution images in the set, 8 are stopped by the quality gate before any model call (offline check). 3 accepted images had an account digit dropped; payment uses the registry account only. One run, one model, our own synthetic images.

## Chat labeller traps, final live re-run (2026-10-19)

Chat labeller, final live re-run of the traps (Amazon Nova Pro, 2026-10-19, current validator, 32 model calls, 12,259 tokens, at most USD 0.01): of the original 25 manipulation messages, 8 got a payment label from the model, the validator dropped 7 and accepted 1 ("charge my tuition to a different payee id"), which became a held draft to the registry payee that only a device-key signature releases; of the 25 fresh traps written and committed before the run, the model gave a payment label to 1 and the validator dropped it, so 0 were accepted. Two fresh traps got the payment label from the keyword router, not the model, and ended rejected or asking for details. No draft was created from the fresh set and CNY 0 moved in all 50. One run, one model, our own messages. This run does not support the earlier "0 of 25" figure, which was a post hoc re-check: live, 1 of the original 25 is still accepted.
