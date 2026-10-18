# Router robustness layers: before and after (offline, no model call)

Before = keyword router alone; after = keyword router + normalisation, slot rules, similarity fallback, arbitration and clarification (`agent/robust.py`).
**Honest labels:** held-out 3 (120 phrases) was written before the round-5 changes and never used for tuning: it is the honest figure (out-of-sample for the matcher, written by the team that wrote the router). Held-out 1 and 2 are no longer out-of-sample: their failures were used to fix keyword rules. Every other set below was used for earlier router fixes, so those figures are not first-run figures. 'Right' means the label equals the one written with the message.

| Message set (paraphrases) | n | correct before > after | wrong before > after | unknown before > after | clarified after | money moved | drafts created before > after |
|---|---|---|---|---|---|---|---|
| messages (first set) | 22 | 1 > 9 | 0 > 1 | 21 > 1 | 11 | 0 | 0 > 0 |
| fresh | 40 | 30 > 32 | 4 > 3 | 6 > 1 | 4 | 0 | 2 > 2 |
| held-out (chat labeller) | 20 | 0 > 4 | 0 > 2 | 20 > 3 | 11 | 0 | 0 > 0 |
| scale | 73 | 2 > 18 | 0 > 3 | 71 > 14 | 38 | 0 | 0 > 0 |
| router held-out 1 (326; tuned: drove the round-4 fixes) | 326 | 221 > 252 | 2 > 6 | 103 > 22 | 46 | 0 | 0 > 0 |
| router held-out 2 (200; tuned: drove the round-5 rule classes) | 200 | 131 > 158 | 9 > 6 | 60 > 8 | 28 | 0 | 3 > 0 |
| router held-out 3 (120; written first, never tuned on: the honest row) | 120 | 88 > 99 | 4 > 4 | 28 > 3 | 14 | 0 | 0 > 0 |
| **sum of the five rows other than held-out 2 and 3** | 481 | 254 > 315 | 6 > 15 | 221 > 41 | 110 | | |

| Outside-written scenario set | n | met every expectation before > after | scenarios where money moved or was lost |
|---|---|---|---|
| Codex scenarios (80) | 80 | 70 > 74 | 0 > 0 (money moved 0) |
| Codex round 2 (250) | 250 | 132 > 146 | 0 > 0 (money moved 0) |

| Independent set | tasks before > after | attacks passed before > after | look-alikes passed before > after |
|---|---|---|---|
| set 1 | 116/120 > 116/120 | 150/150 > 150/150 | 50/50 > 50/50 |
| set 2 | 133/150 > 133/150 | 200/200 > 200/200 | 60/60 > 60/60 |
| set 3 (ChatGPT) | 96/120 > 101/120 | 150/150 > 150/150 | 50/50 > 50/50 |
| set A | 149/150 > 149/150 | 0/0 > 0/0 | 60/60 > 60/60 |
| set C (Codex) | 129/150 > 128/150 | 200/200 > 200/200 | 57/60 > 57/60 |
| set G (Gemini) | 140/150 > 141/150 | 200/200 > 200/200 | 60/60 > 60/60 |

Reply latency over 862 chat turns through the API test client (router + handler + save): median 7.1 ms, p95 18.9 ms, max 100.3 ms. The matcher alone takes about 1 ms per message.
