# Fuzz results (chat, offline)

Run: 2026-10-19 19:58 | seed 7 | LLM: offline-deterministic

**Caveat.** Our own generator on our own corpus, offline deterministic router, MOCK data. It finds crashes and formatting blind spots, not new attack ideas, and says nothing about a live model.

| Check | Result |
|---|---|
| Corpus messages mutated | 1593 |
| Mutated messages sent | 7588 |
| Hard invariant breaches (mutation) | 0 |
| Soft findings (mutation) | 0 |
| Random walks / steps / signed drafts | 300 / 1662 / 86 |
| Walk invariant breaches | 0 |

## Mutations used

typo (699), upper (745), lower (643), spacing (819), fullwidth (749), zero_width (801), filler_pre (790), filler_post (778), quoted (769), punct (795)

## Hard breaches (mutation)

None.

## Soft findings (for a human to read)

None.

## Walk breaches

None.
