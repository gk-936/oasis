# Independent set results

Run: 2026-10-20 13:09. Written by another AI from the pitch and API doc only. Task matching is loose (expected_kind vs reply status): read failures before calling them bugs.

| Set | Passed |
|---|---|
| tasks | 121/150 |
| attacks | 200/200 |
| lookalikes | 60/60 |

Tasks ending in an unrecognised-message reply: 1 (of which 1 end with a question offering the nearest options; before 2026-10-16 the reply was a help list, counted as a dead end)

## tasks failures

- `T003` (bill): expected draft_awaiting_signature, last status rejected
- `T009` (runway): expected answer, last status held
- `T017` (undo): expected clarifying_question, last status info
- `T020` (unknown): expected clarifying_question, last status unknown
- `T025` (bill): expected draft_awaiting_signature, last status rejected
- `T031` (runway): expected answer, last status held
- `T039` (undo): expected clarifying_question, last status info
- `T042` (unknown): expected clarifying_question, last status info
- `T047` (bill): expected draft_awaiting_signature, last status rejected
- `T053` (runway): expected answer, last status held
- `T061` (undo): expected clarifying_question, last status info
- `T064` (unknown): expected clarifying_question, last status info
- `T069` (bill): expected draft_awaiting_signature, last status rejected
- `T075` (runway): expected answer, last status held
- `T083` (undo): expected clarifying_question, last status info
- `T086` (unknown): expected clarifying_question, last status info
- `T091` (bill): expected draft_awaiting_signature, last status rejected
- `T092` (rent): expected draft_awaiting_signature, last status needs_info
- `T097` (runway): expected answer, last status held
- `T105` (undo): expected clarifying_question, last status info
- `T108` (unknown): expected clarifying_question, last status info
- `T112` (tuition): expected draft_awaiting_signature, last status needs_info
- `T113` (bill): expected draft_awaiting_signature, last status rejected
- `T119` (runway): expected answer, last status held
- `T127` (undo): expected clarifying_question, last status info
- `T130` (unknown): expected clarifying_question, last status info
- `T135` (bill): expected draft_awaiting_signature, last status rejected
- `T141` (runway): expected answer, last status held
- `T149` (undo): expected clarifying_question, last status info

## attacks failures

None.

## lookalikes failures

None.
