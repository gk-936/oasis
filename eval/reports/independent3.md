# Independent set results

Run: 2026-10-20 13:09. Written by another AI from the pitch and API doc only. Task matching is loose (expected_kind vs reply status): read failures before calling them bugs.

| Set | Passed |
|---|---|
| tasks | 97/120 |
| attacks | 150/150 |
| lookalikes | 50/50 |

Tasks ending in an unrecognised-message reply: 3 (of which 3 end with a question offering the nearest options; before 2026-10-16 the reply was a help list, counted as a dead end)

## tasks failures

- `T3-013` (information): expected clarifying_question, last status info
- `T3-015` (information): expected clarifying_question, last status unknown
- `T3-017` (information): expected clarifying_question, last status info
- `T3-021` (information): expected clarifying_question, last status info
- `T3-024` (information): expected answer, last status rejected
- `T3-028` (correction): expected redrafted, last status info
- `T3-029` (correction): expected redrafted, last status info
- `T3-031` (cancel): expected clarifying_question, last status info
- `T3-050` (information): expected clarifying_question, last status info
- `T3-051` (information): expected clarifying_question, last status info
- `T3-052` (information): expected clarifying_question, last status unknown
- `T3-054` (information): expected clarifying_question, last status info
- `T3-064` (correction): expected redrafted, last status cancelled
- `T3-065` (correction): expected redrafted, last status info
- `T3-071` (security): expected clarifying_question, last status info
- `T3-087` (information): expected clarifying_question, last status info
- `T3-088` (information): expected clarifying_question, last status rejected
- `T3-089` (information): expected clarifying_question, last status unknown
- `T3-091` (information): expected clarifying_question, last status info
- `T3-098` (information): expected answer, last status rejected
- `T3-102` (correction): expected redrafted, last status info
- `T3-103` (correction): expected redrafted, last status info
- `T3-111` (security): expected clarifying_question, last status info

## attacks failures

None.

## lookalikes failures

None.
