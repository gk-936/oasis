# Recent attacks (2022 to 2026) replayed against Oasis

Public attack classes against payment flows, what Oasis does about each, and the test that replays it. Tests are in `tests/test_recent_attacks.py` (offline, MOCK money). Same caveat as the rest of the repo: our own tests of our own defences, not an audit.

| Attack class | Public source | Oasis control | Test |
|---|---|---|---|
| Business email compromise: fake "we changed banks" or "account under audit" notice | [FBI IC3 2025 report, via secondary summaries](https://help.illinoisstate.edu/spaces/informationsecurity/pages/320503814/Business+Email+Compromise+BEC); [Abnormal Security 2026](https://abnormal.ai/ja/blog/2026-attack-landscape-report-vec) | Money goes only to the registry account; a changed account is held (R16) | `test_bec_bank_change_pretext_never_pays_the_new_account` (5 pretexts) |
| Hidden instructions aimed at AI agents (1px text, HTML comments, JSON-LD, meta tags, white-on-white, zero-width characters) | [Security Affairs](https://securityaffairs.com/194822/ai/hidden-web-prompts-trick-ai-agents-into-sending-money.html); [Cloud Security Alliance note](https://labs.cloudsecurityalliance.org/research/csa-research-note-indirect-prompt-injection-in-the-wild-2026/) | The model only proposes; executor enforces the signed intent; nothing moves without a device-key signature | `test_hidden_instruction_in_an_invoice_moves_no_money_to_the_attacker` (6 payloads) |
| Race condition / double spend | [Paymenter CVE-2026-55219](https://www.wiz.io/vulnerability-database/cve/cve-2026-55219); Kettle, DEF CON 2023 | Single-use nonce and tool token | `test_parallel_approvals_of_one_draft_pay_exactly_once` (8 parallel requests) |
| Overspend / negative balance | same | Ledger refuses `InsufficientFunds` | `test_payment_larger_than_funds_is_refused_and_balance_never_negative` |
| Look-alike payee names (homoglyphs, "1" for "l") | [Abnormal / BEC summaries above](https://abnormal.ai/ja/blog/2026-attack-landscape-report-vec) | Exact registry names only | `test_lookalike_payee_name_does_not_resolve_to_the_registered_payee` |
| MFA fatigue / push bombing (Uber 2022) | [Kroll, Oct 2023](https://www.kroll.com/en/insights/publications/cyber/mfa-bypass-leads-to-account-compromise) | Approval is a signature over the exact draft, not a tap | `test_repeated_unsigned_approve_requests_never_pay` (25 attempts) |
| Session token theft / replay (adversary-in-the-middle) | Kroll, above | Session revocation on logout | `test_stolen_session_cookie_is_dead_after_logout` |
| Deepfake CFO and urgency pressure (the $25M Hong Kong case) | [Hogan Lovells](https://hoganlovells.com/en/publications/deepfakes-and-financial-fraud-what-next-for-the-uk-financial-sector) | Urgency treated as a fraud signal; no bypass of parent approval | existing: `tests/test_chat_dialog.py::test_emergency_pressure_to_skip_parent_approval_is_refused_and_named_as_a_fraud_signal` |

## Not covered

- SIM swap: Oasis uses device keys, not SMS codes, so there is no SMS factor to swap. No test.
- Confirmation of Payee bypass: no public technique was found; not tested.
- Voice-clone phone confirmation: out of scope for a text and API system.

## Further sources

Bank-change notices in French, Chinese and Hindi plus "ignore the registry" and "verbally approved" pretexts; payee-id-only swap; odd amounts (`1e5`, negative, zero, NaN, huge, three decimals); extra body fields (mass assignment); foreign, junk and oversized pending ids; approve replay after paid; four parallel drafts together exceeding the balance; chat attacks claiming parent authority or a rewritten registry. All move no money outside the registry (23 more tests, 41 in total).
