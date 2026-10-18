# Offline chat router: current numbers (router frozen after this round)

All figures are offline (no model call). Nothing under `oasis/trust/*` was touched. Shipped settings: answer threshold `ACCEPT` 0.17, margin 0.08, confusable-pair rule on, keyword-answer doubt off. `OASIS_ROUTER_ROBUST=0` switches the new layers off.

## Checks

| Check | Result |
|---|---|
| Full suite (`OASIS_DB=:memory: OASIS_LLM=offline PYTHONPATH=. python -m pytest -q`) | 1979 passed, 2 skipped |
| `execution_evidence/verify_evidence.py` | ALL CHECKS PASSED |
| `python -m eval.runner --llm offline` | attack block rate 1.0, money lost 0 |
| Money moved on every message set, outside set and independent set | 0 |
| Payment drafts created from any phrase of the three held-out sets (646 phrases) | 0 |

## Held-out results

| Set | n | right | wrong | clarified | no intent | right + clarified |
|---|---|---|---|---|---|---|
| **Held-out 3** (written before this round, never used for tuning: the honest figure) | 120 | 99 (82.5%) | 4 (3.3%) | 14 (11.7%) | 3 (2.5%) | 113 (94.2%) |
| Held-out 2 (its failures drove this round's rule classes: tuned) | 200 | 158 (79.0%) | 6 (3.0%) | 28 (14.0%) | 8 (4.0%) | 186 (93.0%) |
| Held-out 1 (its failures drove the previous round's fixes: tuned) | 326 | 252 (77.3%) | 6 (1.8%) | 46 (14.1%) | 22 (6.7%) | 298 (91.4%) |

All three sets are out-of-sample for the matcher (it never reads them) and written by the team that wrote the router. Goal was wrong <= 5% and right + clarified >= 85%: met on the honest set (3.3% and 94.2%).

Held-out 3, before this round's fixes (counts only, taken before any change): right 86 (71.7%), wrong 17 (14.2%), clarified 11, no intent 6.

## Held-out 3: the 4 wrong answers (not fixed: the router is frozen)

| Message | True | Got | Layer |
|---|---|---|---|
| am I going to make it financially to graduation | runway | correct | keyword rule (_CORRECT) |
| I don't want to go through with the payment, cancel | cancel | nopay | keyword rule (_NOPAY) |
| show my payment history | spending | share_record | keyword rule (_SHARE_RECORD) |
| what fees do I owe the university right now | obligations | routes | keyword rule (_ROUTES) |

## Before and after (keyword router alone, with this round's keyword fixes, versus the full router)

| Message set (paraphrases) | n | correct | wrong | unknown | clarified after | drafts created |
|---|---|---|---|---|---|---|
| messages (first set) | 22 | 1 > 9 | 0 > 1 | 21 > 1 | 11 | 0 > 0 |
| fresh | 40 | 30 > 32 | 4 > 3 | 6 > 1 | 4 | 2 > 2 |
| held-out (chat labeller) | 20 | 0 > 4 | 0 > 2 | 20 > 3 | 11 | 0 > 0 |
| scale | 73 | 2 > 18 | 0 > 3 | 71 > 14 | 38 | 0 > 0 |
| held-out 1 | 326 | 221 > 252 | 2 > 6 | 103 > 22 | 46 | 0 > 0 |
| **sum of those five rows** | 481 | 254 > 315 | 6 > 15 | 221 > 41 | 110 | |
| held-out 2 | 200 | 131 > 158 | 9 > 6 | 60 > 8 | 28 | 3 > 0 |
| held-out 3 | 120 | 88 > 99 | 4 > 4 | 28 > 3 | 14 | 0 > 0 |

The message-set rows (other than the held-outs) were used for earlier router fixes, so they are not first-run figures.

| Outside-written set | n | met every expectation (before > after) | money moved or lost |
|---|---|---|---|
| Codex scenarios | 80 | 70 > 74 | 0 |
| Codex round 2 | 250 | 126 > 140 | 0 |

| Independent set | tasks | attacks passed | look-alikes passed |
|---|---|---|---|
| set 1 | 116/120 > 116/120 | 150/150 > 150/150 | 50/50 > 50/50 |
| set 2 | 133/150 > 133/150 | 200/200 > 200/200 | 60/60 > 60/60 |
| set 3 (ChatGPT) | 96/120 > 101/120 | 150/150 > 150/150 | 50/50 > 50/50 |
| set A | 149/150 > 149/150 | 0/0 > 0/0 | 60/60 > 60/60 |
| set C (Codex) | 129/150 > 128/150 | 200/200 > 200/200 | 57/60 > 57/60 |
| set G (Gemini) | 140/150 > 141/150 | 200/200 > 200/200 | 60/60 > 60/60 |

Attacks and look-alikes do not regress on any set. Set C loses one task against the keyword router alone; every other set is level or better.

## Train examples and rule classes

- `oasis/agent/intent_examples.py`: 1861 train phrases, English and Chinese (obligations 108, balance 89, routes 98, runway 102, quota 98, credit 86, status 105, transfer_issue 106, fx_bill 100, parent_request 88, share_record 80, help 90, convert 74, rate_target 98, cancel 71, explain 86, rate 68, spending 64, proof 74, plan 73, other 103). This round added 167 phrases (about 15 per affected intent); 4 candidates were dropped for similarity above 0.9 to a held-out phrase or as duplicates.
- Rule classes fixed with general rules, not by copying phrases: (a) a question or request for information is never a payment (bare `给` no longer counts as a payment verb; `哪个/哪些/吗/么/呢/什么/怎么/是否/推荐/告诉我/回单/凭证/收据` and "has ... finished", "do you handle" keep it from becoming a draft); (b) pending / unpaid / outstanding / 没结清 / 还有哪些 without a sent transfer asks for the bills; (c) enough / carry me / survive / till <month> / 够不够 / 撑到 is runway; (d) notify / alert / tell me when / once / 提醒 / 通知 with a rate is a rate alert; (e) hasn't received / not arrived / been days / 还没到账 is a transfer problem; (f) ceiling / limit on money sent, 要不要扣税 / 交税 is a quota question.
- Safety: every refusal is unchanged. The only secrets-word exemption is the earlier narrow one (Chinese 凭证 right after a payment word). One guard fix: a typo'd imperative such as "paay the depsoit" stays a payment request.
- Benchmark integrity: three messages in the labeller benchmark ("can I last until december without trouble", "remind me what's outstanding", "how many months of coverage do I have") are now placed correctly by the keyword rules, so `eval/chat_llm_bench.py` excludes them from its "router cannot place it" check (list `PLACED_BY_LATER_RULES`); their recorded live rows stay as labeller results.

## Tests

`tests/test_router_robust.py` guards the achieved levels with slack. Held-out 3: wrong <= 5.5%, right + clarified >= 92%, right >= 80.5%. Held-out 2: wrong <= 5%, right + clarified >= 91%, right >= 77%. Held-out 1: wrong <= 4%, right + clarified >= 89%, right >= 75%. `test_no_held_out_phrase_creates_a_payment_draft` runs all 646 held-out phrases end to end (no draft, money moved 0). The 60 task-plus-attack messages are all refused or rejected.

## Latency

The matcher takes about 1 ms. A full chat turn through the API test client over 862 turns: median 9.5 ms, p95 30.2 ms, max 60.5 ms (latest `eval.router_robust_eval` run; timings vary with machine load).

## Files

- New this round: `tests/data/router_heldout3.json`. Changed: `oasis/agent/nlu.py`, `oasis/agent/robust.py`, `oasis/agent/intent_examples.py`, `eval/router_robust_eval.py`, `eval/chat_llm_bench.py`, `tests/test_router_robust.py`.

## Docs and PDFs still to update (on hold)

Test count is now 1979 passed, 2 skipped. Places that state a test count, the old router figures or the old outside-set figures: `CLAUDE.md`, `AGENTS.md`, `README.md` (badge and test line), `features.md`, `docs/full-overview.md`, `docs/security-evidence-matrix.md`, `docs/results.md`, `docs/execution-evidence.md`, `Evidence/README.md`, `Evidence/test_suite_result.txt`, `Evidence/06_Security_and_Design_Notes/`, the `eval/chat_llm/messages_scale.json` note, and the builders `eval/build_techdoc_pdf.py`, `eval/build_security_pdf.py`, `eval/build_evidence_pdf.py`, `eval/build_evidence_folder.py`. The three PDFs (in `docs/`, `Evidence/01_Submission_Documents/` and `execution_evidence/`) need a rebuild afterwards.
