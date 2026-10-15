# Fuzz results (chat, offline)

Run: 2026-10-15 18:49 | seed 11 | LLM: offline-deterministic

**Caveat.** Our own generator on our own corpus, offline keyword router, MOCK data. It finds crashes and formatting blind spots, not new attack ideas, and says nothing about a live model.

| Check | Result |
|---|---|
| Corpus messages mutated | 534 |
| Mutated messages sent | 3865 |
| Hard invariant breaches (mutation) | 0 |
| Soft findings (mutation) | 0 |
| Random walks / steps / signed drafts | 500 / 2755 / 85 |
| Walk invariant breaches | 0 |

## Mutations used

typo (300), upper (378), lower (362), spacing (401), fullwidth (403), zero_width (414), filler_pre (398), filler_post (387), quoted (398), punct (424)

## Hard breaches (mutation)

None.

## Soft findings (for a human to read)

None.

## Walk breaches

None.
