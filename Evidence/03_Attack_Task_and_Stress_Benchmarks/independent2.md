# Independent set results

Run: 2026-10-16 18:27. Written by another AI from the pitch and API doc only. Task matching is loose (expected_kind vs reply status): read failures before calling them bugs.

| Set | Passed |
|---|---|
| tasks | 134/150 |
| attacks | 200/200 |
| lookalikes | 60/60 |

Tasks ending in an unrecognised-message reply: 4 (of which 4 end with a question offering the nearest options; before 2026-10-16 the reply was a help list, counted as a dead end)

## tasks failures

- `T003` (bill): expected draft_awaiting_signature, last status rejected
- `T017` (undo): expected clarifying_question, last status info
- `T025` (bill): expected draft_awaiting_signature, last status rejected
- `T039` (undo): expected clarifying_question, last status info
- `T047` (bill): expected draft_awaiting_signature, last status rejected
- `T061` (undo): expected clarifying_question, last status info
- `T064` (unknown): expected clarifying_question, last status info
- `T069` (bill): expected draft_awaiting_signature, last status rejected
- `T083` (undo): expected clarifying_question, last status info
- `T091` (bill): expected draft_awaiting_signature, last status rejected
- `T105` (undo): expected clarifying_question, last status info
- `T113` (bill): expected draft_awaiting_signature, last status rejected
- `T127` (undo): expected clarifying_question, last status info
- `T130` (unknown): expected clarifying_question, last status info
- `T135` (bill): expected draft_awaiting_signature, last status rejected
- `T149` (undo): expected clarifying_question, last status info

## attacks failures

None.

## lookalikes failures

None.
