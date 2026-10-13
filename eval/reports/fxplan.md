# Foreign-currency planner (offline, deterministic)

MOCK world on the frozen rate snapshot; route prices are public-range estimates (docs/corridor-research.md). No model call. These are plans only (nothing is executed here; execution is covered by tests/test_fxplan.py). One scenario is SUPPOSED to be refused: a payment above the LRS limit. An assumed route price must beat a sourced one by more than 0.5% to be chosen.

| Scenario | Valid | Corridor | Remitter | Deadlines met | Saved vs bank (USD) | Errors | Price status |
|---|---|---|---|---|---|---|---|
| USD 5,000 tuition, funded from INR | True | INR-USD | student | 1/1 | 121.13 | - | sourced |
| EUR 3,000 tuition, funded from INR | True | INR-EUR | student | 1/1 | 116.27 | - | sourced |
| USD 4,000 tuition, student holds CNY | True | CNY-USD | student | 1/1 | 170.55 | - | assumed |
| USD 8,000 tuition, student INR is short | True | INR-USD | parent | 1/1 | 137.53 | - | sourced |
| USD 2,000, already held in USD | True | - | - | 1/1 | 0.0 | - | - |
| USD 5,000 due in 2 days | True | INR-USD | student | 1/1 | 121.13 | - | sourced |
| USD 300,000 (above the LRS limit) | False | INR-USD | student | 1/1 | 1734.22 | lrs_exceeded | sourced |
| USD 4,000 tuition, student holds EUR | True | EUR-USD | student | 1/1 | 177.65 | - | sourced |
| EUR 3,000 tuition, student holds CNY | True | CNY-EUR | student | 1/1 | 158.04 | - | assumed |

Valid plans: 8 of 9.
