# Task-completion benchmark (chat)

Run: 2026-10-14 20:42 | LLM: offline-deterministic | 85 scripted tasks

**Caveat.** Our own scripted tasks, written by the same team that built Oasis, run against the offline keyword router on MOCK data. It shows the chat paths work end to end and that attacks fail; it is not an independent benchmark and says nothing about a live model.

| Metric | Value |
|---|---|
| Task success rate | 1.000 (85/85) |
| Mean user turns per task | 1.42 |
| Mean user turns per completed payment task | 1.08 |
| Tasks where a follow-up question was asked | 10 (correct end state in 10) |
| False refusals on legitimate tasks | 0 |
| Money lost (CNY, sandbox) | 0 |

## By category

| Category | Passed |
|---|---|
| pay_obligation | 6/6 |
| follow_up | 6/6 |
| natural_invoice | 7/7 |
| parent_cosign | 1/1 |
| information | 10/10 |
| convert | 3/3 |
| correct_cancel | 4/4 |
| chinese | 5/5 |
| security | 21/21 |
| paraphrase | 10/10 |
| safety_net | 12/12 |

## Failures

None.

A payment task ends when the script signs the draft with a device key (the same signature the browser makes). A held draft awaiting a human signature is the correct end state when no signer is present.
