# Router overhaul

What changed in the chat router, why, and what is measured. Every figure here is model off (the deterministic path). The plan this followed is `ROUTER_OVERHAUL.md` (reviewer's brief); the running log with every gate result is [`eval/reports/router_overhaul.md`](../eval/reports/router_overhaul.md), and the three set scores are in [`eval/reports/router_sets.md`](../eval/reports/router_sets.md).

## What did not change

The money path is untouched: the policy engine (R01 to R19, C01, C02), signature checks, registry check, executor and audit chain. The router only decides which existing handler runs and what words come back. A state-changing intent is reachable only through (a) a deterministic pay or convert frame whose object resolves to a registry bill, or (b) a stored `last_offer` that the student accepts with an explicit yes; either way the result is a held draft that needs the student's device-key signature.

## New modules (all deterministic, no new dependencies)

| Module | Job |
|---|---|
| `oasis/agent/lexicon.py` | Concept lexicons as data: pay actions, bills, information targets, currencies, control words, speech-act cues |
| `oasis/agent/frames.py` | Parses a message into speech act, concepts, slots, reported-speech flag, clauses; fuzzy snapping of typos |
| `oasis/agent/router_v2.py` | Chooses a route from the frame: canonical rewrite, fixed sentence, answer-plus-offer, refusal |
| `oasis/agent/context.py` | Six-turn session memory and the ellipsis resolver ("and my phone?", "same again", "the other one") |
| `oasis/agent/scam_lane.py` | Inducement scorer (12 signal families) and attack-text patterns (rule changes, prompt and secret requests, authority claims, exfiltration) |
| `oasis/agent/faq.py` | 60+ fixed answers with retrieval; the hedged fallback |
| `oasis/agent/scorecard.py` | Agent scorecard and mandate card (read-only, from the audit log) |
| `oasis/agent/chat_llm.py` (extended) | Flag-gated interpreter mode (`OASIS_CHAT_LLM=1`, `OASIS_CHAT_LLM_MODE=interpret`); every branch is covered by stub-model tests |

## Behaviour changes

- A "did you mean 1/2/3" menu is gone for read-only questions: the router answers the best candidate and, if the runner-up is close, adds "I can also show you ... say 'yes'" (a bare yes shows only that answer). A numbered menu remains only where the student must pick between payments.
- "I didn't catch that" and "I'm not sure what you mean" no longer exist in the code. Unplaced messages get a fixed FAQ answer or a hedge that names the best guess and the four things to say.
- Statements and worries map to read-only answers with an offer ("my tuition is due Friday" gives the tuition line and "Want me to draft the payment?"; a bare yes then creates the draft, which still needs the signature).
- Reported speech is content, not an instruction ("my dad said he sent the money but I don't see it" is a transfer question, not a bypass attempt).
- Scam situations described in plain words get a pattern-named warning and no draft.
- `stop my autopay`, `cancel my standing instruction`, `remove the rate alert` make a held revoke draft; the mandate ends only after the student's device-key signature (`oasis/agent/mandate_exec.py::handle_revoke`, audited as `mandate_revoked`).
- Zero, `NaN`, `1e9`, "all my money", two conflicting amounts, unknown payee names near a registry name, and unsupported currencies get one clear sentence and no draft.

## Deviations from the brief (recorded, not hidden)

- A message that mixes a genuine request with an attack ("show my balance and ignore previous instructions ...") is still refused as a whole, as the existing 60-message adversarial tests pin. The brief's per-clause refusal is not implemented for refusal-category messages.
- "Rent due today" still produces a payment draft (an existing test pins it); the statement-of-fact offer applies to the other bill statements.
- Where a keyword or similarity rule already placed a message, the new concept layer does not overrule it; it fills the gaps (existing tests pin many of those answers). This is why the word-held-out score is lower than the brief's bar.

## Limits

The attacker catalogue, the DEV set and the frozen set were written by the implementer. The word-held-out set removes a random 30% of each concept's words from the lexicon but other layers still see them. The BLIND set is empty until people who have not seen the router write it (protocol in the brief, section 9.3). None of these numbers is an estimate against a hidden judge.
