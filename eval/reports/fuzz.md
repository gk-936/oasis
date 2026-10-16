# Fuzz results (chat, offline)

Run: 2026-10-16 11:58 | seed 7 | LLM: offline-deterministic

**Caveat.** Our own generator on our own corpus, offline keyword router, MOCK data. It finds crashes and formatting blind spots, not new attack ideas, and says nothing about a live model.

| Check | Result |
|---|---|
| Corpus messages mutated | 1362 |
| Mutated messages sent | 6615 |
| Hard invariant breaches (mutation) | 0 |
| Soft findings (mutation) | 0 |
| Random walks / steps / signed drafts | 300 / 1624 / 65 |
| Walk invariant breaches | 0 |

## Mutations used

typo (604), upper (661), lower (592), spacing (703), fullwidth (678), zero_width (662), filler_pre (670), filler_post (702), quoted (673), punct (670)

## Hard breaches (mutation)

None.

## Soft findings (for a human to read)

None.

## Walk breaches

None.
