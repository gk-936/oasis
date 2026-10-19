# Chat labeller and router, final capped live run (Amazon Nova Pro, MOCK data)

Messages go through the real /api/chat path with the live labeller on (router, robust layers, labeller, validator). One run, one model, our own message sets (the traps and held-out router sets were written by the Oasis team); small samples. The model only proposes a label; payments are drafts that need a device-key signature.

Spend: 32 calls, 12,259 tokens (cap 40,000), USD 0.0098 (cap 0.05)

| Set | n | right | wrong | clarified | no intent | trap got pay label | labeller calls | payment labels given | accepted by validator | drafts | money moved | tokens | USD |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| traps_original25 | 25 | 24 | 0 | 0 | 0 | 1 | 24 | 8 | 1 | 1 | 0.0 | 9,863 | 0.0079 |
| traps_fresh25 | 25 | 23 | 0 | 0 | 0 | 2 | 6 | 1 | 0 | 0 | 0.0 | 2,396 | 0.0019 |
