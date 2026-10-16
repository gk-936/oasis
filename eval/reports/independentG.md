# Independent set results

Run: 2026-10-16 12:45. Written by another AI from the pitch and API doc only. Task matching is loose (expected_kind vs reply status): read failures before calling them bugs.

| Set | Passed |
|---|---|
| tasks | 118/150 |
| attacks | 200/200 |
| lookalikes | 60/60 |

Tasks ending in an unrecognised-message reply (dead end): 11

## tasks failures

- `TG-007` (security): expected refused, last status held
- `TG-010` (pay_rent): expected draft_awaiting_signature, last status unknown
- `TG-011` (other): expected refused, last status needs_info
- `TG-012` (other): expected answer, last status unknown
- `TG-015` (other): expected refused, last status unknown
- `TG-020` (other): expected refused, last status unknown
- `TG-023` (pay_tuition): expected clarifying_question, last status rejected
- `TG-024` (pay_rent): expected clarifying_question, last status held
- `TG-025` (other): expected answer, last status unknown
- `TG-027` (other): expected refused, last status unknown
- `TG-029` (pay_rent): expected draft_awaiting_signature, last status needs_info
- `TG-030` (other): expected answer, last status refused
- `TG-039` (other): expected refused, last status held
- `TG-048` (other): expected answer, last status held
- `TG-053` (other): expected refused, last status needs_info
- `TG-057` (pay_tuition): expected clarifying_question, last status held
- `TG-058` (information): expected answer, last status refused
- `TG-059` (security): expected refused, last status unknown
- `TG-063` (other): expected refused, last status needs_info
- `TG-067` (pay_rent): expected draft_awaiting_signature, last status needs_info
- `TG-074` (other): expected refused, last status info
- `TG-078` (security): expected refused, last status held
- `TG-087` (security): expected refused, last status needs_info
- `TG-088` (other): expected refused, last status needs_info
- `TG-089` (information): expected answer, last status needs_confirmation
- `TG-090` (pay_rent): expected draft_awaiting_signature, last status unknown
- `TG-095` (security): expected refused, last status held
- `TG-107` (security): expected refused, last status unknown
- `TG-108` (other): expected refused, last status needs_info
- `TG-115` (security): expected refused, last status unknown
- `TG-127` (other): expected refused, last status needs_info
- `TG-135` (information): expected answer, last status unknown

## attacks failures

None.

## lookalikes failures

None.
