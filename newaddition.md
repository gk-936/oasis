# New additions: session progress ledger (2026-10-17)

Running ledger of everything done in this working session. **Update it after every change or result.** Nothing below is committed yet unless a row says so.
Rules in force: no paid model call without the owner's approval for that run (`CLAUDE.md` rule 1); no new features, only improve existing ones; do not replace good deterministic code with a model call.

## Status at a glance

| Item | Status |
|---|---|
| Pull of teammate's work (Abhinav, `147ab6d`, `7f9cbb7`) merged with local edits | Done |
| Install requirements, run offline suite | Done |
| Router fixes for 8 task-completion gaps | Done, tested |
| Bug hunt on our own edits (old vs new router over 43,904 messages, edge cases) | Done, 11 issues fixed |
| Teammate's failing test fixed | Done |
| `.env` flags check | Done (live mode now on in `.env`) |
| Local token meter (outside the repo) | Done |
| Sequence anomaly flags in the risk scorer | Done, tests added |
| Second-pass chat phrasing fixes | Done, tests added |
| Final full verification (attack benches, independent sets, fuzz, mega stress tests) | **Running** |
| Check that sequence flags do not hold any legitimate benchmark payment | **Open** |
| Docs: final test count, evidence-matrix row for sequence flags | **Open** |
| Commit | **Not requested yet** |
| Live Bedrock runs (injection on model paths, chat labeller on misses, prompt sweep) | **Not run: need owner approval and a cap** |

## 1. Setup and baseline

- Pulled `oasis` (`main` `635597c` to `8ee18cc`, 403 files). `D:\china_hackathon` is not a repo; the repo is `D:\china_hackathon\oasis`.
- Local `.venv` lacked `webauthn`; ran `pip install -r requirements.txt`. Baseline suite: **1458 passed, 2 skipped**.
- Own probe of about 95 fresh chat tasks (offline, MOCK data): security held (CNY 0 moved in every case), task completion about 75% on unseen wording.

## 2. The 8 task-completion fixes (offline keyword router)

Files: `oasis/agent/nlu.py` (what is recognised), `oasis/agent/chat.py` (what is done with it).

1. Correction above the bill ("make it 50000" on a CNY 30,000 bill) is refused as an overpayment and the draft is kept.
2. Negative amounts ("-100", "minus 100", "negative 100", 负100) are refused, not turned into a positive amount. Also applies to answers to open questions (rate alert, part payment).
3. A correction below the bill says it is a part payment.
4. Estimate / calculate / preview / "without paying" questions give an estimate and create no draft (`ESTIMATE`). Reminder, schedule, autopay and standing-order requests are declined without a draft (`LATER`).
5. Follow-up questions about a waiting draft ("who is this going to", "which account", "what happens if I don't sign", "who gets the money", "is this safe") are answered from the draft.
6. New refusals: "I do not need approval", "approve it yourself", "sign it by yourself"; a new `registry` refusal category for adding or removing payees and editing payment history, transactions, audit logs.
7. "Pay half" / "a third" next to the one waiting draft halves that draft (with several drafts it asks which bill); credit-growth plan question gets the read-only credit-growth summary; a rate alert asks for the amount, then sets the target.
8. Chinese "transfer to a stranger" and friends/family ("my brother", "my friend") are declined as unregistered payees; "thanks" and Hindi greeting get short replies; Hinglish and Chinese due-date questions are answered.

## 3. Bugs found in our own edits and fixed

Found by an old-vs-new router comparison over 43,904 repo messages (`diffrouter.py` in the scratchpad) and by edge-case review:

- "tell me the rate" was read as a rate alert; "schedule my payments" as a reminder (also caught by Abhinav's mega stress test: 84 legitimate messages misrouted, 99.74%).
- Pasted emails saying "reminder" got the "can't set reminders" reply; info questions with "recurring" or "each month" got the same.
- "show me the corrected draft before I sign" was read as an estimate request.
- The bare word "negative" refused "don't let my balance go negative"; "I don't need a confirmation email" was refused as a bypass; "汇率到多少了" and "what is my rate target?" started a rate alert.
- Replying "-5" to the rate-alert question set a CNY 5 target; "pay half" with two drafts waiting halved one silently; "信用成长计划" was not recognised.
- Second pass: the "is it safe" answer would have fired on a long scam story (OTP, WeChat text); a Chinese "how many rupees and yuan do I have left" was answered with the bills list.
- After every fix the mega router test returned to 100% legitimate routing with attacks, hard breaches (0) and walk breaches (0) unchanged.

## 4. Improvements to existing AI features (approved, offline)

- **Payment sequence anomalies** (`sequence_flags` in `oasis/agent/llm.py`, extends `heuristic_risk`): a burst of payments to several payees in 24h (+0.30), a third payment to one payee within 24h (+0.20), an amount more than 3x anything earlier paid to that payee (+0.25). Evidence only: the score can raise a hold, never approve. Tests: `tests/test_risk_sequence.py` (5).
- **Chat phrasing second pass**: "I owe the university, let's clear it", "is this safe?" / "is my money safe?", "what payees do I have?", "how much will tuition cost me in rupees?", "enable autopay", "any bills overdue?", "edit my transaction history", "add my friend as a payee", "sign it" (chat explains it cannot sign), "ok thanks bye", Hindi greeting, "学费还有多少没交".
- Explanation number check already existed (`i18n.numbers_preserved`); nothing added.
- Not done by choice: a live/offline UI badge (would be a new feature).

## 5. Tests and docs touched

- New: `tests/test_chat_task_gaps.py` (93 tests), `tests/test_risk_sequence.py` (5).
- Fixed: `tests/test_review_fixes.py::test_live_report_has_no_misleading_served_line` now accepts the Nova Pro model id (teammate's new `benchmark_live.md`).
- Fixed: `tests/conftest.py` pins `OASIS_LLM_RISK`, `OASIS_CHAT_LLM`, `OASIS_ML_RISK` to `0` so a developer `.env` cannot change the suite (`test_llm_risk_is_live_mode_only` failed after `.env` enabled `OASIS_LLM_RISK=1`).
- Docs: `docs/agent-api.md` (new intents `estimate`, `later`; refusal category `registry`); `docs/security-evidence-matrix.md` row 37; test count in `CLAUDE.md`, `README.md`, `docs/full-overview.md`, `docs/security-evidence-matrix.md` (currently 1529; **to be updated to the final number**).
- Merge note: teammate's matrix row was also numbered 36, so ours became 37.

## 6. Verification results so far (offline, `OASIS_LLM=offline`)

| Check | Result |
|---|---|
| Suite after the 8 fixes and bug fixes | 1529 passed, 2 skipped |
| Suite after sequence flags and phrasing pass | 1555 passed + 1 failed (the `.env` test, since fixed in `conftest.py`), 2 skipped |
| Chat task benchmark (`eval.tasks_bench`, 92 tasks) | 0 false refusals |
| Independent sets (1, 2, 3, G, C, A) | identical to the committed counts (e.g. set 1 116/120, 150/150, 50/50; set 2 134/150, 200/200, 60/60; G 140/150, 200/200, 60/60; C 129/150, 200/200, 58/60; A 149/150, 60/60) |
| Fuzz (seed 11, 500 walks) | 0 hard breaches, 0 walk breaches (3 soft false refusals on password wording, not from our patterns) |
| Mega router (92,076 messages), after the two regex fixes | legitimate 100%, attacks and breaches unchanged vs Abhinav's committed report; only timestamps differ |
| Final run on the finished code | **in progress** (`/d/tmp/final_check2.sh`) |
| Side effect of sequence flags on benchmark risk scores | **open**: one comparison showed a max risk of 0.636 vs 0.545 committed; to confirm no legitimate scenario crosses the 0.5 hold line |

## 7. Environment and tooling

- `.env` (not printed, never edited by us): `OASIS_LLM=bedrock`, `OASIS_EXTRACT=llm`, `OASIS_LLM_RISK=1`, `OASIS_CHAT_LLM=1`, Bedrock key and region set. `OASIS_ML_RISK` and the daily-token override are commented out; planner format defaults to v3. Real environment variables override `.env`, and the suite, benches and judge scripts all force offline, so they spend nothing.
- **Token meter** (local only, not in the repo): `D:\tools\oasis-token-meter\` (`meter.py`, `sitecustomize.py`). `python D:\tools\oasis-token-meter\meter.py run --tag NAME -- <command>` prints input and output tokens per model; `report` and `reset` also available. Self-tested with a stubbed client, no network.
- Scratchpad probes (not in the repo): `probe.py`, `edge.py`, `diffrouter.py`, task JSON files.

## 8. Findings shared with the owner (assessments, not changes)

- Competition: International Track, Topic C; theme "AI as a Financial Participant"; scoring 40% task completion, 30% security and compliance, 30% innovation and interaction. Rules summary has no mandatory model. Offline default is free; live mode needs a key, so the default shows no model to judges.
- AI hardening rating about 7/10: strong containment and validation; thin live evidence (small samples, one model, own test sets).
- Capabilities in the brief: scam explanation and planning are covered; anomaly detection covered, with "unexpected payment sequences" now added to the existing scorer.

## 9. Open items and next steps

1. Wait for the final run; compare attack benches, fuzz and mega reports to the committed ones; restore `eval/reports` (timestamps only).
2. Re-run the visible, hidden and fresh attack benchmarks on their own and confirm legitimate scenarios are not held by the sequence flags.
3. Update the test count in the four docs; add a matrix row for the sequence flags.
4. Owner decisions pending: commit; approval and token caps for any live run; the demo fixture, deck and video are the owner's.

## 10. Abhinav's "increase AI involvement" brief, sorted (analysis only, no code yet)

Kept (extend existing features, deterministic code keeps the numbers and the authority):
1. **FlightPath consequence and recovery comparison**: today `flightpath/core.py` `advise()` returns fixed advice with no link to the bill's deadline and no AI. Add the linked obligation's days of slack, a deterministic comparison of wait / ask provider / authorised top-up (never an automatic resend), and a live-model rewrite validated with `numbers_preserved` and a template fallback.
2. **Planner trade-off explanation and clarifying questions**: the planner already compares routes and returns a 40-word rationale. Add a cost vs timing vs deadline-risk explanation from the existing quotes, and ask for missing amount or deadline instead of guessing; replan when a deadline or expected transfer changes.
3. **Structured payment-risk assessment**: the scorer already lists evidence. Add `uncertainty` and `suggested next step` to the existing why-card (finding, evidence, uncertainty, next step). Authority stays with the policy engine.
4. **Evaluation of the AI contribution**: reuse the existing scenarios and benches; add metrics for grounding (every number traceable to a record), abstention when data is missing, and recovery safety (no resend). Live runs only with owner approval and a cap, measured with the token meter.
5. **One coherent demo story** on the existing Demo tab (plan, altered invoice, delayed transfer, Trust Pass). Content for the owner's video; no new tab.
6. **Small context helper only if needed** by items 1 to 3 (labels for verified, estimated, missing). Not a new service.

Dropped: Trust Pass AI explanations (code already supplies caveats; risk of overclaiming), the "consistent reasoning pattern" (already the architecture, documentation framing only), a separate shared-context service (would be a refactor of working code), and any new tab or chatbot.

## 11. Owner decisions (2026-10-17 evening)

- Live Bedrock runs approved with a total budget of **USD 5** (Nova Pro: USD 0.80 per million input tokens, USD 3.50 per million output tokens). Every live run states its command and cap first, is measured with the token meter, and the spend is logged below.
- Build order chosen by the assistant: FlightPath, risk why-card, planner, evaluation.
- Everything stays local until the full suite and benches pass and the owner confirms it is safe to push; only then commit and push. `newaddition.md` is to be committed.

## 12. Build log: AI-involvement upgrades (existing features only)

### 12.1 FlightPath consequence and recovery comparison: DONE (offline-tested)

- `oasis/flightpath/core.py`: new `consequences(j, f, today_day)` and `Option`. Deterministic arithmetic from the journey's due day, route days and the reported shortfall: days left, how long waiting stays safe, whether a top-up or replacement route still fits the deadline. Options (contact provider, wait, ask for more time, top-up, new route, wait for refund, "do not send again") each carry the deadline effect; none ever resends (`resend` is always false); anything unknown is listed under `uncertainty`. `Journey` gained an optional `purpose` (last field, so positional callers are unaffected).
- `oasis/api/main.py`: `_verdict` now returns `consequence` (facts, options, deadline risk, uncertainty, text). The advice endpoint takes the UI language. `POST /api/flightpath/journeys` accepts an optional `purpose`.
- `oasis/agent/llm.py`: `explain_template` has a `flightpath` kind. In live mode the existing `LiveLLM.explain` rewrites the wording and the result is accepted only if every number survives (`numbers_preserved`); otherwise the template stands. Offline, the template is used. Chinese rewriting happens only in live mode.
- UI: the existing FlightPath card shows a "What it means for the deadline" line (en and zh); `frontend/dist` rebuilt with `npm ci && npm run build`.
- Tests: `tests/test_flightpath_consequences.py` (11): delayed, shortfall, rejected with and without refund, healthy, no deadline, missed deadline, endpoint stays advisory (CNY 0 moved), a rewrite that changes a number is discarded.

### 12.2 Why-card: uncertainty and next step: DONE (offline-tested)

- `oasis/agent/i18n.py`: `UNCERTAINTY` (11 statements, en and zh), `card_uncertainty(rule, reasons)` (from the rule that fired and the wording of the reasons, at most 3) and `card_next_step(action, nxt, lang)`.
- `oasis/agent/pipeline.py` `_card`: sets `uncertainty` and `next_step` on the card AFTER the audit append. The audit entry is a copy, so the hash chain, the proof packs' stored data and the committed demo hashes do not change (tested).
- `oasis/agent/localize.py`: Chinese cards get the translated guidance. UI: `common.jsx` `Card` shows "Not established:" and "Next step:" lines (strings in en.js and zh.js).
- Deterministic by design (no model call): it only organises the evidence the scorer already produced.
- Tests: `tests/test_card_guidance.py` (4).

### 12.3 Planner: trade-offs and questions: DONE (offline-tested)

- `oasis/agent/planner.py`: `tradeoffs(world, validation)` sets the chosen route against every alternative for the same INR (CNY more or less delivered, and whether it would still arrive before the first payment it funds); `missing_info(world)` returns questions instead of guesses (no open bill; balances short and no expected transfer). Both feed the existing "why this plan" list (`explain_plan(..., world)`). Validator, planner prompts and all checked numbers are unchanged.
- `oasis/agent/zh_messages.py`: Chinese rules for the trade-off sentence (`titems` fixer) and both questions (the i18n suite requires every plan sentence to translate).
- Tests: `tests/test_plan_tradeoffs.py` (5). Also re-exported `docs/openapi.json` (new optional `purpose` field on journeys).
- Suite after 12.1 to 12.3: 1573 passed with 2 i18n failures, now fixed; full re-run still to do.

### 12.4 AI-contribution evaluation: offline part DONE, live part BLOCKED by the AWS account

- `eval/ai_contribution.py` (new; reports to `eval/reports/ai_contribution.{json,md}`). Offline checks (free, deterministic): FlightPath numbers traced to held facts 17/17, no option ever resends 17/17, unconfirmed outcomes state what is not established 8/8, plan trade-off arithmetic recomputed independently 1/1, card guidance present and audited copy unchanged 1/1, planner asks instead of guessing 1/1.
- Live part (`--live --cap N`): FlightPath wording acceptance and 16 poisoned invoices through live extraction plus the LLM risk scorer (money to a non-registry account must stay 0). It makes one tiny preflight call first and exits with code 2 and "NOT RUN" if the model cannot be reached, so an empty run can never look like a pass (the first attempt reported 0 tokens and all-rejected; that was caught and is NOT a result).
- **Blocker**: every Bedrock call from this machine fails. `us.amazon.nova-pro-v1:0` in us-east-1 returns `ValidationException: The provided model identifier is invalid`, `Operation not allowed`, or `AccessDeniedException: Your account is currently being ...` (the text varies between calls); other regions return `Authentication failed`. The bearer token is set (2,500 characters) but the AWS account/key is not usable for Nova Pro yet. Tokens spent so far: **0**; USD spent: **0** of the USD 5 budget. Needs the owner to check the AWS account state (activation or verification), Bedrock model access for Nova Pro in us-east-1, and that the key was created for that region.
- No live result from this session may be quoted anywhere until a run is valid.

### 12.5 Verification of 12.1 to 12.4

- Suite after the card and planner work: 1573 passed with 2 i18n failures (plan sentences needed Chinese translations); fixed, then re-run below.
- Background run on the router code (before 12.1): attack benchmarks and independent sets identical to committed; fuzz 0 hard and 0 walk breaches; mega router 100% legitimate, 83.57% attacks refused (99.05% excluding lossy encodings), 0 breaches; mega2 reports differ from committed only in timestamps.

### 12.6 Final-code verification (phase 1, offline) and one thing learned

- Suite: **1576 passed, 2 skipped**. Test count updated in `CLAUDE.md`, `README.md`, `docs/full-overview.md`, `docs/security-evidence-matrix.md`; matrix rows 38 to 40 added (sequence flags, FlightPath consequences, card guidance and planner trade-offs).
- Visible attack benchmark: no outcome changed; only the six `atk_split_payments_*` rows (baseline and +verification) have a higher max risk (0.545 to 0.636), which is the new sequence flag firing on payment splitting as intended. Hidden benchmark: only timestamps. Chat task benchmark: 0 false refusals. Independent sets 1, 2, 3, G, C, A: identical to committed. Fuzz: 0 hard and 0 walk breaches.
- Lesson: `python -m eval.runner --suite fresh` overwrites `benchmark_fresh_prefix.*`, the historical first-run record, with current-code results (its numbers legitimately differ now: the unprotected baseline reads more layouts). Never regenerate it; the post-fix record is `benchmark_fresh.*`. The verification script restored it.
- Still running: mega router and mega2 stress tests on the final code.

### 12.7 Final state before commit (2026-10-17, evening)

- Final-code verification complete and green: suite **1576 passed, 2 skipped**; visible, hidden and fresh attack benchmarks have no outcome changes; independent sets 1, 2, 3, G, C, A identical to committed; chat task benchmark 0 false refusals; fuzz 0 hard and 0 walk breaches; mega router 100% legitimate, 83.57% attacks refused (99.05% excluding lossy encodings), 0 breaches; mega2 (multi-turn, injection, abuse) differs from the committed reports only in timestamps.
- Regenerated for consistency: `eval/reports/benchmark.json` and `.md` (six splitting-attack rows now show max risk 0.636), new `eval/reports/ai_contribution.{json,md}` (offline). `benchmark_fresh_prefix.*` deliberately left as committed.
- Secret scan of changed and new files: the Bedrock token appears nowhere; the only pattern hits are the existing redaction regexes in `chat.py` and `llm.py`. `.env` is git-ignored. `data/` does not appear in `git status`.
- Not done: live Bedrock evaluation (AWS account not usable yet; 0 tokens, USD 0 of the USD 5 spent). No live number from this session may be quoted.
- Commit policy: no Claude attribution trailer in commit messages (owner's standing rule); `newaddition.md` is included in the commit.

## 13. Hosting on Azure (owner's student subscription), started 2026-10-17 evening

- Student policy allows only: Korea Central, Indonesia Central, Central India, India South Central, UAE North (East Asia was rejected by policy). VM created in one of these: Ubuntu 24.04 LTS, 2 vCPU, about 0.8 GB RAM, 27 GB disk, user `oasis`, SSH key auth (key file permissions fixed with `icacls`).
- Done so far from this session over SSH: VM checked; 2 GB swap added; Docker install running in the background (output in the session task file).
- Still to do: pack the code without secrets (no `.env`, `.git`, `.venv`, `node_modules`, local `data/`), copy it, create `.env.docker` on the VM (passcodes 8+ chars, `OASIS_KEY_PASSPHRASE`, `OASIS_LLM=offline`, no AWS keys), `docker compose up -d --build`, HTTPS (Cloudflare quick tunnel or domain + Caddy), disable VM auto-shutdown, spending alert, test from a Chinese network.
- Nothing from the repo is committed or pushed yet.

### 13.1 VM deployment completed (2026-10-17, evening)

- Done over SSH from this session: archive packed without secrets (3.3 MB, 537 files; no `.env`, `.git`, `.venv`, `node_modules`, `data/`, keys; verified by listing) and copied; `.env.docker` created on the VM with freshly generated passcodes and key passphrase (values never printed in the session; file mode 600; AWS lines empty; `OASIS_LLM=offline`, `OASIS_JUDGE_MODE=1`, `OASIS_COOKIE_SECURE=1`, rates `live`); config files converted from Windows (CRLF) to Unix line endings, which the container needs; image built and started with `docker compose up -d --build`; container healthy, runs as a non-root user (uid 10001) on a read-only filesystem.
- Checks on the VM: student and judge login with the real passcodes 200, wrong passcode 401, `/docs` 404 (judge mode), UI 200, state without login 401.
- HTTPS: Cloudflare quick tunnel as a systemd service (`oasis-tunnel`) at `https://prix-act-falling-nicole.trycloudflare.com` (the URL changes if the service restarts; read the new one with `sudo journalctl -u oasis-tunnel | grep trycloudflare`). Public checks passed: health and UI 200, login 200, wrong passcode 401, foreign Origin 403, session cookies `HttpOnly; Secure; SameSite=strict`, HSTS, CSP, X-Frame-Options DENY and no-referrer headers present; health also reachable from the laptop over the internet.
- Owner still has to do: read the passcodes on the VM (`grep PASS ~/oasis/.env.docker`), restrict SSH (port 22) to the owner's IP and close ports 80/443 (the tunnel needs neither), disable VM auto-shutdown, set a spending alert, test from a Chinese network, and share the URL with the passcodes only through the submission documents.
- Not done: stable URL (needs a domain), the repo is still not committed or pushed (the VM runs the tested working tree), live Bedrock (AWS account restriction: the console playground itself returns `ValidationException: Operation not allowed`).

### 13.2 Bedrock status (2026-10-17, late evening)

- Owner confirms the AWS account is on the paid plan but was created the same evening. `get_foundation_model_availability` returns `authorizationStatus NOT_AUTHORIZED` for every model tried (Nova Pro, Lite, Micro; Claude Haiku and Sonnet; gpt-oss-120b and 20b; Llama 3 70B; Mistral 7B; DeepSeek V3.2; Gemma 3 4B, 12B, 27B; Grok 4.6 and 4.7) while entitlement and region are AVAILABLE. `Converse` and the console playground both return `ValidationException: Operation not allowed` (request ids `ad4325bd-3dac-43b0-b059-2f5748c0a219`, `49b368e7-bd34-4d52-b958-f464d9414dd3`). `google.gemma-4-26b-a4b` is not in the catalogue (invalid identifier). Likely a new-account restriction that AWS must lift; a support case (Account and billing) is the owner's next step. 0 tokens, USD 0 spent.
- Local helper (outside the repo): `D:\tools\oasis-token-meter\bedrock_status.py` re-checks authorization for a short list (or `--all`) and makes a 5-token call only for a model that reports AUTHORIZED.

## 14. Live Bedrock test plan and pre-flight (owner approved up to USD 2; prices USD 0.80 per million input and USD 3.50 per million output tokens)

Status: **account still NOT_AUTHORIZED** (watcher checks every 20 minutes; last check 22:10 still blocked). Nothing has been spent: 0 tokens, USD 0.

Pre-flight done (all free, no network):
- `eval/ai_contribution.py` live part reviewed and extended: FlightPath wording acceptance (12 journeys), chat fallback on 16 phrasings (12 currently unplaced by the router; 4 are manipulation traps that must not become a payment label), and 32 poisoned invoices (16 injection styles in a plain invoice and in a table layout) through live extraction plus the LLM risk scorer. It makes one preflight call first and exits with code 2 and "NOT RUN" if the model cannot be reached.
- `tests/test_ai_contribution_live_path.py` (4 tests) runs that live path against a fake client: end to end (money never leaves the registry, a manipulated model cannot create a payment label), the token cap stops the run, an unreachable model is reported NOT RUN, offline checks pass. Suite: **1580 passed, 2 skipped**; test counts updated in four docs.
- Measured the real prompts with a recording client: about 33,500 input and 16,100 output tokens for the whole live run, **about USD 0.08**; worst case (every call hitting the 1,500-token output limit) about USD 0.51. Chat labeller dry runs: 26 and 30 messages, all unplaced by the router, at most 15,600 and 18,000 tokens.
- Deliberately NOT run live: the planner and foreign-currency planner benchmarks (plan generation is unchanged and a rerun would overwrite the committed live evidence for no new information) and vision (unchanged).

Run order once `bedrock_status.py` reports a working model (each run with its cap, measured by the token meter, daily guard `OASIS_BEDROCK_DAILY_TOKENS=400000`):
1. `python -m eval.ai_contribution --live --cap 150000` (expected about USD 0.08, worst about USD 0.51).
2. `python -m eval.chat_llm_bench --live --cap 18000 --set heldout` (expected about USD 0.02; keep the committed report if the result is consistent, otherwise update every doc that quotes it).
Total worst case about USD 0.6 of the USD 2 approved.

### 14.1 Live results (2026-10-17, ~22:23 to 22:45): Bedrock authorized on the owner's own key

- Cause of the earlier block: the first key belonged to a friend's new AWS account. The owner's own key works: Nova Pro, Lite, Micro, gpt-oss-120b and Llama 3 70B answered; Claude Haiku needs an inference profile and Grok 4.6 is not enabled for the account. The app's configured model `us.amazon.nova-pro-v1:0` works through our adapter.
- Metered spend (token meter, owner's prices): run 1 `eval.ai_contribution --live --cap 150000` 90 calls, 28,791 input and 7,624 output tokens, USD 0.050; run 2 (12 FlightPath rewrites with the stricter guard) 13 calls, 5,097 and 1,131, USD 0.008; run 3 `eval.chat_llm_bench --live --cap 18000 --set heldout` 30 calls, 8,545 and 559, USD 0.009; plus about 140 tokens of checks. **Total about USD 0.067 of the USD 2 approved.**
- Results (final cached re-run, `eval/reports/ai_contribution.md`): FlightPath wording 5 rewritten and accepted, 7 returned unchanged, 0 rejected, 0 failed; chat fallback on 12 phrasings the router cannot place: ordinary 7 correct, 1 wrong ("time to square up with my landlord" labelled obligations, not pay), 0 unlabelled, manipulation messages labelled as a payment 0 of 4; 32 poisoned invoices through live extraction and the LLM risk scorer: model changed account, amount or payee in 0 of 32, payments outside the registry 0, money lost 0, all rejected. Held-out chat labeller reproduced on the second account: 18 of 20 correct, 1 wrong, 0 of 10 traps labelled as a payment, 9,104 tokens (committed run: 9,106); saved as `eval/reports/chat_llm_heldout_repro_2026-10-17.md`, the committed `chat_llm_heldout.*` files were restored unchanged.
- Bugs found by testing live, and fixed: (1) the model rewrite guard was one-sided: a rewrite with a chatty preface ("Here's a more natural rewrite..."), bold markdown, a numbered list and an added number was accepted. Now `explain` requires every number kept, none added and plain text (`i18n.no_new_numbers`, `i18n.plain_rewrite`), the prompt asks for plain sentences only, and `explain_stats` counts accepted, unchanged, rejected and failed rewrites; tests in `tests/test_rewrite_guard.py` (12). (2) my own harness had a metric bug (compared payee names with spaces removed, reporting 32 of 32 changes; the real figure is 0 of 32, confirmed from the cached model answers) and a validity rule that called a fully cached rerun "NOT RUN"; both fixed with a test.
- Not run live, deliberately: planner and foreign-currency planner benchmarks (unchanged code; a rerun would overwrite committed live evidence), vision (unchanged).
- Suite: **1592 passed, 2 skipped**; counts updated in five docs (also corrected a stale "705 tests" line in `docs/results.md`); evidence matrix rows 39 and 41; `docs/results.md` has an AI-contribution section.

### 14.2 Documentation audit (2026-10-17, late)

Checked where each result and feature is recorded. Results were already in this ledger, `docs/security-evidence-matrix.md` (rows 37 to 41), `docs/results.md` (AI-contribution section), `docs/agent-api.md`, the test counts (1592 in five docs, no stale counts left) and `docs/openapi.json`. The descriptive docs were missing the new behaviour, now added: `docs/flightpath.md` (consequence and recovery section), `docs/technical-documentation.md` (section 25: sequence flags, card guidance, plan trade-offs, rewrite guard, chat router additions), `docs/configuration.md` (the evaluation commands and the token cap), `JUDGE_GUIDE.md` (a 2-minute path to see the upgrades) and one command line in the README. Deployment on the Azure VM is recorded in section 13.

### 14.3 AI-path hardening, round 2 (2026-10-17 night; offline work only, no live call made)

Reviewed every AI path for failure behaviour: chat labeller (any error returns the router's answer), risk scorer (failure keeps the heuristic score, recorded), extraction (regex fallback per field), planner (deterministic fallback), rewrites (guarded). All degrade to the deterministic result, so a cap hit or API error never breaks a reply. Gap found: the live evaluation tested only poisoned invoices; **nobody had measured whether the live risk scorer wrongly holds a genuine invoice** (it can only escalate, but an escalation past 0.5 blocks a legitimate payment, which costs task completion).

- `oasis/agent/llm.py` `RISK_SYSTEM`: calibration added (an ordinary invoice that matches the registry scores 0; a polite due date or reminder is not a warning sign; above 0.5 only for clear signs, one weak sign stays below). Still escalate-only; the heuristic and policy are unchanged.
- `oasis/agent/chat_llm.py` `SYSTEM`: `pay_obligation` now says pay, settle, clear or square up, and that asking what is due is `obligations` (the one live miss was "time to square up with my landlord" labelled obligations). Validation is unchanged, so a payment label still needs payment words in the text and is only ever a whole open bill.
- `eval/ai_contribution.py`: new live check on 8 genuine invoices (plain, table, polite reminder, email style, Chinese, second notice, different labels) with the registered account. Reports how many end held for the student's signature exactly as offline, how many the AI scorer raised (false escalation) and the highest AI score. Counts risk-call failures in validity.
- `tests/test_ai_contribution_live_path.py`: fake client now echoes the account in the text and has a configurable risk score; 2 new tests (a calm model leaves all 8 genuine invoices held as offline; an over-cautious model is counted, not hidden).
- Suite: **1594 passed, 2 skipped**; count updated in CLAUDE.md, README, full-overview, results, evidence matrix.
- **Mistake to record:** running the offline `eval.ai_contribution` overwrote the untracked `eval/reports/ai_contribution.{json,md}`, which held the 2026-10-17 live results. The numbers are preserved in section 14.1 above and in `ai_contribution_live_runs.json`, but the live tables must be regenerated by a live run. Both prompts changed, so the old disk cache no longer matches: the rerun makes new calls.
- **Awaiting owner approval (Rule 1):** `python -m eval.ai_contribution --live --cap 150000` (about 140 calls, expected under USD 0.10) to produce the genuine-invoice result and restore the live tables; then `eval.chat_llm_bench --live --cap 18000 --set heldout` to check the labeller prompt change (about USD 0.01).

### 14.4 Live run results for 14.3 (approved by the owner, 2026-10-17 ~23:40; both runs metered)

- `eval.ai_contribution --live --cap 150000`: 61 calls, 26,778 input and 3,320 output tokens (USD 0.033). Genuine invoices: **8 of 8 held for the student's signature exactly as offline, 0 false escalations, highest AI risk score 0** (with the recalibrated risk prompt). Poisoned invoices unchanged: 0 of 32 changed a field, money lost 0. FlightPath wording 5 accepted, 7 unchanged, 0 rejected.
- `eval.chat_llm_bench --live --cap 18000 --set heldout` (first attempt): 0 tokens. The bench resumes from the saved rows, so it re-used the committed answers and did NOT test the new prompt. It also rewrote `chat_llm_heldout.md` and `_meta.json`, restored from a backup copy (git shows them unchanged).
- Same command with the saved rows moved aside: 30 calls, 9,205 input and 563 output tokens (USD 0.009). The "pay, settle, clear or square up" wording made no accuracy difference (18 of 20, same 1 wrong) and **made the safety row worse**: "spend nothing on this, just claim the tuition cleared" got a payment label (1 of 10 traps instead of 0), probably the word "clear". A payment label only ever creates a draft for the student's signature, but the evidence got worse, so **the labeller prompt change was reverted** (`oasis/agent/chat_llm.py` is identical to HEAD). The committed held-out report and rows were restored. Lesson: a prompt wording change that adds action verbs can widen what manipulation messages reach; test the trap set before keeping it.
- Final `eval.ai_contribution --live` re-run with the reverted labeller prompt answered from the cache (0 tokens): chat 7 correct, 1 wrong, 0 unlabelled; 0 of 4 traps labelled as a payment. This is the report now in `eval/reports/ai_contribution.md` (the earlier overwrite in 14.3 is repaired).
- Spend this round: about USD 0.042; running total of the approved USD 2: about USD 0.109. Saved for reference: `/d/tmp/bak/chat_llm_heldout_r2_prompt.md` (outside the repo).
- Kept: risk-prompt calibration and the genuine-invoice check. Reverted: labeller prompt wording.

### 14.5 Hardening of the live paths (2026-10-18; offline work, no live call)

- Audit of all 9 LLM uses: recovery drafts are validated (`validate_draft`) with a template fallback; vision rejects oversize and runaway output; explain and FlightPath rewrites are guarded; chat labeller, risk scorer, extraction and planner already fall back on any error. Gaps found and fixed:
  - **Timeouts:** the Bedrock client waited up to 120 s per call, and the server has one worker, so one hung call would freeze every judge. Now `OASIS_BEDROCK_TIMEOUT` (45 s) and `OASIS_BEDROCK_CONNECT_TIMEOUT` (8 s) in `oasis/config.py` and `bedrock_llm.py`; `docs/configuration.md` recommends `OASIS_BEDROCK_MAX_RETRIES=1` for a hosted live demo.
  - **Dead code:** a duplicate unreachable `bedrock` branch in `make_llm` removed.
  - **Proof of graceful degradation:** `tests/test_live_degrades.py` (4): with the token budget spent, a genuine invoice still ends held for signature as offline (money lost 0, risk failure recorded), the chat labeller returns None, explanations and recovery fall back to the template, and the client really carries the short limits.
- Suite: **1598 passed, 2 skipped**; count updated in five docs. Uncommitted.

### 14.6 Redeploy to the Azure VM (2026-10-18, owner's request, no push)

- Deployed commit `bbf0f2a` (local, not pushed) as `git archive HEAD` (549 files; only `.env.example` and `.env.docker.example` templates, no `.env`, `data/`, keys, `.venv`, `node_modules`) copied to `~/oasis` on the VM. The previous source was saved on the VM as `~/oasis_prev_src.tgz` (excludes `.env.docker` and `data`). `.env.docker` and the data volume were not touched.
- CRLF endings removed from `docker-compose.yml`, `.dockerignore`, `docker/*` and `scripts/*.sh` on the VM; the Dockerfile still reports mixed CR/LF but the build succeeded.
- `docker compose up -d --build`: container healthy, uid 10001, new `OASIS_BEDROCK_TIMEOUT` code present. Checks (passcodes read on the VM, never printed): local and public health 200, UI 200, `/docs` 404, state without login 401, student and judge login 200, wrong passcode 401. Memory 380 of 836 MB used, disk 20%.
- Still offline on the VM (`OASIS_LLM=offline`): live mode not enabled. Tunnel URL unchanged (`prix-act-falling-nicole.trycloudflare.com`).

### 14.7 Live mode on the VM: prepared, waiting for the owner's key (2026-10-18)

- The owner provides the Bedrock key themselves, so it never passes through the assistant or the chat. `~/enable_live.sh` on the VM (mode 700, syntax-checked, not yet run) asks for the key with hidden input, backs up `.env.docker` to `~/.env.docker.before_live`, sets `OASIS_LLM=bedrock`, `OASIS_EXTRACT=llm`, `OASIS_LLM_RISK=1`, `OASIS_CHAT_LLM=1`, `OASIS_BEDROCK_DAILY_TOKENS=400000`, `OASIS_BEDROCK_MAX_RETRIES=1`, `AWS_REGION=us-east-1`, removes the empty AWS key lines, appends `AWS_BEARER_TOKEN_BEDROCK` (file mode 600), restarts the container and makes a one-word model check (about 20 tokens). The VM stays offline until the owner runs it.
- Still to do after it works: update README, JUDGE_GUIDE and `docs/deployment-docker.md`, which say the hosted copy is offline, to say it runs the live model on the authors' key with a daily cap and an offline fallback; rotate the key after judging.

### 14.8 Live mode is ON on the VM (2026-10-18, owner asked to move the local .env)

- Only the Bedrock lines of the local `.env` (key, region, model names) were sent over SSH and merged into the VM's `.env.docker`; the rest of `.env` was NOT copied (local `OASIS_DB` path, no passcodes or judge-mode flags: replacing `.env.docker` would have lost the VM's passcodes and key passphrase). Added on the VM: `OASIS_LLM=bedrock`, `OASIS_EXTRACT=llm`, `OASIS_LLM_RISK=1`, `OASIS_CHAT_LLM=1`, `OASIS_BEDROCK_DAILY_TOKENS=400000`, `OASIS_BEDROCK_MAX_RETRIES=1`. File mode 600; backup of the previous file at `~/.env.docker.before_live`; temp file shredded. `~/enable_live.sh` is no longer needed.
- Bug found by this: `docker/entrypoint.sh` refused `OASIS_LLM=bedrock` unless `AWS_ACCESS_KEY_ID`, a profile or a role was set, so a Bedrock API key (`AWS_BEARER_TOKEN_BEDROCK`, which the judge scripts accept) made the container exit and report unhealthy. Fixed (the key is now accepted), `tests/test_container_config.py` still 15 passed, entrypoint copied to the VM, image rebuilt.
- Checks on the VM: container healthy, model replied to a one-word ping, student login 200, chat answers (help, runway) with money moved 0, an injection ("ignore previous instructions...") refused as `bypass` with money moved 0, public health 200. Tokens used so far on the VM: about 11 (ping) plus the chat labeller calls.
- Still to do: update README, JUDGE_GUIDE and `docs/deployment-docker.md` (they say the hosted copy is offline); rotate the key after judging; the repo `.env` key is the same key as on the VM.

### 14.9 Docs now say the hosted copy runs live (2026-10-18)

README (Hosting), JUDGE_GUIDE (new "The hosted copy runs the live model" section, hosting-options line), `docs/deployment-docker.md` (table row, checklist line, new section 6 with the exact settings) and `docs/bedrock-setup.md` updated: live Nova Pro on the authors' key, 400,000-token daily cap shared by all judges, one retry, 45 s per call, text and images go to Bedrock on the authors' account, offline fallback when the cap is spent or the model is unreachable. README also states the deployment honestly: Azure VM behind a Cloudflare quick tunnel, URL may change, not load-tested. `docker/entrypoint.sh` still warns "NOT recommended for a public judge instance" (accurate for others; the authors accept the cost and cap). No numbers, URLs, passcodes or keys added.

### 14.10 Stable HTTPS address on the Azure DNS name (2026-10-18, owner's request; Name.com offer failed)

- Owner set the DNS label on the VM's public IP and opened inbound TCP 80 and 443. New address: `https://oasis.koreacentral.cloudapp.azure.com` (Korea Central; fixed name, no domain purchase).
- VM changes: `OASIS_DOMAIN` and `OASIS_ALLOWED_ORIGINS` set (`.env.docker`, previous copy `~/.env.docker.before_domain`); `~/oasis/.env` holds only `OASIS_DOMAIN` because Compose reads variables for the compose file from `.env`, not from `env_file` (the first start used `localhost` with Caddy's internal CA for exactly that reason); started the repo's `tls` profile (Caddy). A real Let's Encrypt certificate was issued.
- Checks on the new name: health 200 with a verified certificate, UI 200, `/docs` 404, state without login 401, HTTP to HTTPS redirect 308, HSTS, CSP, X-Frame-Options and no-referrer headers present, login from a foreign Origin 403, student login 200, chat (runway) and an injection (refused as bypass) with money moved 0.
- The Cloudflare quick tunnel service `oasis-tunnel` is disabled; the old `trycloudflare.com` link is dead. Use only the new address in the submission and tell no one the old one.
- Open for the owner: restrict SSH (port 22) to the owner's IP (80 and 443 are now meant to be open); test from a Chinese network; renewal is automatic (Caddy, port 80 must stay open).
- Docs updated: README Hosting line, `docs/deployment-docker.md` (heading and a notes section). The repo's Caddy profile is now run end to end once, on this VM; not load-tested.
