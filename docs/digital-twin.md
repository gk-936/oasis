# Financial Digital Twin (MOCK / simulation)

`oasis/twin/core.py`, `GET /api/twin?seed=7&paths=600`, Twin tab (student, judge). Pure stdlib, offline, about 0.2 s.

It simulates the rest of the semester from the Passport (open obligations, expected top-ups, balances, spending burn).
Each of N paths draws: an INR->CNY geometric random walk, whether the parent top-up is late, and per payment whether the
FlightPath rail delays or short-credits it. Output: probability each deadline is met, a p10/p50/p90 balance fan chart,
and mitigations (convert rupees now, pay 3 days earlier, use the fastest route, ask a parent for a top-up sized to the gap).
Each mitigation's gain is measured by re-running the same random paths (common random numbers), so differences are not noise.

## Assumptions (stated, not measured)
- FX volatility 0.3 percent per day, zero drift. This is an assumption; Oasis never predicts rates.
- 35 percent chance a top-up is late (1 to 14 days); 5 percent chance a transfer is credited short (2 days to fix);
  rail delay probability is 1 minus the MOCK route reliability.
- Grace of 1 day after the due date, as in FlightPath.

## Limits
A simulation of MOCK data, not a forecast or advice. Same seed gives identical output. If the student simply lacks
the money, probabilities are near zero and only a top-up helps; the twin says so rather than hiding it.
