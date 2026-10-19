# Changes made against MASTER_FIX

Offline suite: **2731 passed, 2 skipped**. Attack benchmark: CNY 0 lost. Fuzz run: 0 hard breaches. `execution_evidence/verify_evidence.py`: ALL CHECKS PASSED.

## Covered

| MASTER_FIX item | What changed | Where |
|---|---|---|
| Section 8 core-four failures | Bank vs remittance app, transfer time, invoice authenticity ("is this invoice real?"), "university account changed" email, "show my landlord", on-time count, "what next", guided start for new students. A low-confidence invoice parse now asks for payee and amount instead of printing "CNY 0 to ?". | `oasis/agent/nlu.py`, `chat.py`, `robust.py`; `tests/test_core_four.py` |
| A1 | Finance summary ("Am I overspending?") | `chat.py` (`_finance_summary`) |
| A2 | Transfer time leads with days per route | `chat.py` (`_transfer_time`) |
| A3 | "What if it arrives short?" gets the FlightPath answer | `nlu.py`, `chat.py` |
| A4 | Instalments: N equal parts, confirmation, then a normal held draft | `nlu.py`, `chat.py` |
| A5 | A person outside the registry ("my mother", "friend Li Wei", "Forward 50000 to my cousin, acct ...") gets guidance; no draft, no account stored | `chat.py` (`_new_payee_reply`) |
| A6 | Conversions of any pair or size, and "convert all", become held drafts released only by the student's device-key signature (rule C01) | `oasis/agent/conversion_exec.py`; `tests/test_conversion_drafts.py` |
| A7 | A bare "yes" binds only to the last conversion quote | `chat.py` (`last_offer`) |
| A8 | Paying an already-paid bill says it is already paid | `chat.py` |
| A9 | Compound requests ("convert ... and pay my rent") walk step by step via "next" | `chat.py` |
| Widen sandbox | MOCK electricity, internet, health insurance, visa fee, library, gym and a registered peer payee, in the API session world only (the demo, twin and benchmark worlds keep the small seed) | `oasis/world.py`, `chat.py`, `oasis/mock/registry.py` |
| C1 | Standing instructions: recurring bill and rate target made through chat are signed drafts (rule C02); a bill above its signed cap is held | `oasis/agent/mandate_exec.py`, `autonomy.py`; `tests/test_mandates.py` |
| C2 | Agent activity feed (chat plus `GET /api/activity`) | `oasis/agent/activity.py`, `oasis/api/main.py` |
| C3 | Third scripted demo run "autonomy"; 24 audit entries, money lost 0, identical chain head on replay (`3efb9873...`); a Run 3 button in the Demo tab | `oasis/demo.py`, `frontend/src/tabs/Demo.jsx`, `frontend/dist` |
| C4 | Stated honestly: model-off figures only, no claim that the model improves completion | `docs/bounded-autonomy.md` |
| C5 | Three-level ladder: act alone, ask the human, never act | `docs/bounded-autonomy.md` |
| Concept questions | Fixed answers for SWIFT, nonce, MOCK, FlightPath, supported currencies, "who made you", "how do I use this" | `oasis/agent/glossary.py` |
| Part D | Test count updated everywhere; evidence-matrix rows 46 to 49; technical documentation, security self-assessment, real-vs-simulated, execution-evidence, results, README and JUDGE_GUIDE updated; the three PDFs and the Evidence folder rebuilt; flaky `test_account_numbers_are_masked_in_every_reply` fixed | `docs/`, `eval/build_*.py`, `Evidence/` |
| Part E | 151-message frozen set, offline: **136 of 151 (90%)** after the router rebuild (130 before); "I didn't catch that" in 0 replies; money moved in 0 messages | `eval/frozen_set.py`, `eval/reports/frozen_set.md` |

## Behaviour changes that updated old tests

- Conversions above the auto limit or in another pair are now held drafts, not "use the Convert screen".
- Electricity, internet, insurance, visa fee, library and gym are registered MOCK payees in the API session world (gas and water are still refused).
- Chat requests for a rate target are held drafts until signed.
- `eval/tasks/tasks.json`: the `rate_target` task now signs; `mc_inr_usd` now ends with one pending draft.

## Skipped or not measured

- **Part B (B1 to B7) and C4 model-on numbers:** Model-on run (one run, our own messages; `eval/reports/model_on.md`): 74 calls, 23,940 tokens in and 2,609 out, about USD 0.03 estimated at list prices. The model was called only for the 47 messages the router could not place (36 DEV messages and 11 attack rows). Pooled over 2,655 messages the pass count rose from 2,327 to 2,340, which is +0.49 points, all of it on the DEV messages (13 of the 36 hedges became passes); the attack rows did not change and CNY 0 moved. That is below the 3-point bar, so the interpreter (`OASIS_CHAT_LLM_MODE=interpret`) is left off on the hosted copy. There is no model-on figure for any other set.
- **Section 8.2 golden flows and 8.4 extra phrasings:** only partly covered.
- **Section 0:** the organisers' task description was not re-checked for a supplied simulated environment.
- **Finance summary in the similarity matcher:** a keyword rule reaches it instead, to avoid disturbing the pinned held-out scores.

## Known limits

- `POST /api/rate-target` (the web form) still creates a bounded Tier-1 target without a device-key signature.
- The frozen set was written by the implementer after the fixes, so it is not an out-of-sample estimate and has no true baseline.
- The new Chinese strings for the Run 3 button are machine-translated and not team-checked.
