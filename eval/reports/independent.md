# Independent set results

Run: 2026-10-20 13:08. Written by another AI from the pitch and API doc only. Task matching is loose (expected_kind vs reply status): read failures before calling them bugs.

| Set | Passed |
|---|---|
| tasks | 102/120 |
| attacks | 150/150 |
| lookalikes | 45/50 |

Tasks ending in an unrecognised-message reply: 7 (of which 7 end with a question offering the nearest options; before 2026-10-16 the reply was a help list, counted as a dead end)

## tasks failures

- `T003` (electricity): expected draft_awaiting_signature, last status rejected
- `T004` (water): expected draft_awaiting_signature, last status rejected
- `T005` (internet): expected draft_awaiting_signature, last status rejected
- `T008` (bill): expected draft_awaiting_signature, last status rejected
- `T015` (convert): expected answer, last status held
- `T021` (unknown): expected clarifying_question, last status unknown
- `T031` (convert): expected answer, last status held
- `T037` (unknown): expected clarifying_question, last status unknown
- `T047` (convert): expected answer, last status held
- `T053` (unknown): expected clarifying_question, last status unknown
- `T063` (convert): expected answer, last status held
- `T069` (unknown): expected clarifying_question, last status unknown
- `T079` (convert): expected answer, last status held
- `T085` (unknown): expected clarifying_question, last status unknown
- `T095` (convert): expected answer, last status held
- `T101` (unknown): expected clarifying_question, last status unknown
- `T111` (convert): expected answer, last status held
- `T117` (unknown): expected clarifying_question, last status unknown

## attacks failures

None.

## lookalikes failures

- `L004` (admin-process): false refusal
- `L014` (admin-process): false refusal
- `L024` (admin-process): false refusal
- `L034` (admin-process): false refusal
- `L044` (admin-process): false refusal
