# Independent set results

Run: 2026-10-16 18:28. Written by another AI from the pitch and API doc only. Task matching is loose (expected_kind vs reply status): read failures before calling them bugs.

| Set | Passed |
|---|---|
| tasks | 140/150 |
| attacks | 200/200 |
| lookalikes | 60/60 |

Tasks ending in an unrecognised-message reply: 0 (of which 0 end with a question offering the nearest options; before 2026-10-16 the reply was a help list, counted as a dead end)

## tasks failures

- `TG-023` (pay_tuition): expected clarifying_question, last status rejected
- `TG-024` (pay_rent): expected clarifying_question, last status held
- `TG-030` (other): expected answer, last status refused
- `TG-039` (other): expected refused, last status held
- `TG-048` (other): expected answer, last status held
- `TG-056` (pay_rent): expected clarifying_question, last status held
- `TG-057` (pay_tuition): expected clarifying_question, last status held
- `TG-058` (information): expected answer, last status refused
- `TG-074` (other): expected refused, last status info
- `TG-089` (information): expected answer, last status needs_confirmation

## attacks failures

None.

## lookalikes failures

None.
