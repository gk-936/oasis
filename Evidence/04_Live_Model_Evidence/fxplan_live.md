# Foreign-currency planner, live (Amazon Nova Pro on Bedrock)

MOCK world on the frozen rate snapshot; route prices are public-range estimates. The deterministic validator judges every proposal. Small sample: a handful of plans on mock data is not a robustness claim.

| Scenario | Rep | Planner / model | Model-only valid | Valid | Fallback | Proposals | Model calls | Tokens | Seconds | Corridors | Tools called |
|---|---|---|---|---|---|---|---|---|---|---|---|
| USD 5,000 tuition, funded from INR | 1 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 5,285 | 7.3 | INR-USD | fx_facts > fx_size_conversion |
| EUR 3,000 tuition, funded from INR | 1 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 3,869 | 7.0 | INR-EUR | fx_facts > fx_size_conversion |
| USD 4,000 tuition, student holds CNY | 1 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 3,992 | 5.0 | CNY-USD | fx_facts > fx_size_conversion |
| USD 8,000 tuition, student INR is short | 1 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 3 | 6 | 12,940 | 15.5 | INR-USD | fx_facts > fx_size_conversion > fx_size_conversion |
| USD 2,000, already held in USD | 1 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 2 | 1,857 | 2.3 | - | fx_facts |
| USD 5,000 due in 2 days | 1 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 4,108 | 6.4 | INR-USD | fx_facts > fx_size_conversion |
| USD 300,000 (above the LRS limit) | 1 | deterministic (fallback) / us.amazon.nova-pro-v1:0 | False | False | True (no valid plan after 3 proposal(s)) | 4 | 8 | 19,449 | 19.9 | INR-USD | fx_facts > fx_size_conversion > fx_size_conversion > fx_size_conversion > fx_size_conversion > fx_facts > fx_size_conversion |
| USD 4,000 tuition, student holds EUR | 1 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 4,075 | 5.2 | EUR-USD | fx_facts > fx_size_conversion |
| EUR 3,000 tuition, student holds CNY | 1 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 3,768 | 5.0 | CNY-EUR | fx_facts > fx_size_conversion |
| USD 5,000 tuition, funded from INR | 2 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 5,465 | 8.6 | INR-USD | fx_facts > fx_size_conversion |
| EUR 3,000 tuition, funded from INR | 2 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 3,944 | 5.7 | INR-EUR | fx_facts > fx_size_conversion |
| USD 4,000 tuition, student holds CNY | 2 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 4,082 | 5.8 | CNY-USD | fx_facts > fx_size_conversion |
| USD 8,000 tuition, student INR is short | 2 | deterministic (fallback) / us.amazon.nova-pro-v1:0 | False | True | True (no valid plan after 2 proposal(s)) | 4 | 8 | 23,645 | 20.6 | INR-USD | fx_facts > fx_size_conversion > fx_facts > fx_size_conversion > fx_size_conversion > fx_facts > fx_size_conversion > fx_size_conversion > fx_facts > fx_size_conversion > fx_size_conversion |
| USD 2,000, already held in USD | 2 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 2 | 1,881 | 2.3 | - | fx_facts |
| USD 5,000 due in 2 days | 2 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 4,286 | 6.9 | INR-USD | fx_facts > fx_size_conversion |
| USD 300,000 (above the LRS limit) | 2 | deterministic (fallback) / us.amazon.nova-pro-v1:0 | False | False | True (no valid plan after 4 proposal(s)) | 5 | 7 | 16,293 | 15.8 | INR-USD | fx_facts > fx_size_conversion > fx_facts > fx_size_conversion |
| USD 4,000 tuition, student holds EUR | 2 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 4,307 | 6.5 | EUR-USD | fx_facts > fx_size_conversion |
| EUR 3,000 tuition, student holds CNY | 2 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 4,081 | 6.8 | CNY-EUR | fx_facts > fx_size_conversion |
| USD 5,000 tuition, funded from INR | 3 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 5,213 | 6.9 | INR-USD | fx_facts > fx_size_conversion |
| EUR 3,000 tuition, funded from INR | 3 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 3,790 | 5.6 | INR-EUR | fx_facts > fx_size_conversion |
| USD 4,000 tuition, student holds CNY | 3 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 3,994 | 4.5 | CNY-USD | fx_facts > fx_size_conversion |
| USD 8,000 tuition, student INR is short | 3 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 3 | 6 | 12,605 | 12.5 | INR-USD | fx_facts > fx_size_conversion > fx_size_conversion |
| USD 2,000, already held in USD | 3 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 2 | 1,856 | 2.6 | - | fx_facts |
| USD 5,000 due in 2 days | 3 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 4,241 | 5.8 | INR-USD | fx_facts > fx_size_conversion |
| USD 300,000 (above the LRS limit) | 3 | deterministic (fallback) / us.amazon.nova-pro-v1:0 | False | False | True (the model stopped without a valid plan) | 4 | 8 | 19,225 | 18.1 | INR-USD | fx_facts > fx_size_conversion > fx_size_conversion > fx_facts > fx_size_conversion |
| USD 4,000 tuition, student holds EUR | 3 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 4,212 | 5.6 | EUR-USD | fx_facts > fx_size_conversion |
| EUR 3,000 tuition, student holds CNY | 3 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 1 | 3 | 3,902 | 7.5 | CNY-EUR | fx_facts > fx_size_conversion |
| USD 8,000 tuition, student INR is short | 4 | deterministic (fallback) / us.amazon.nova-pro-v1:0 | False | True | True (no valid plan after 3 proposal(s)) | 5 | 8 | 21,945 | 20.9 | INR-USD | fx_facts > fx_size_conversion > fx_size_conversion > fx_size_conversion > fx_size_conversion > fx_facts > fx_size_conversion > fx_size_conversion |
| USD 8,000 tuition, student INR is short | 5 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 2 | 5 | 11,855 | 15.6 | INR-USD | fx_facts > fx_size_conversion > fx_size_conversion > fx_size_conversion > fx_size_conversion |
| USD 8,000 tuition, student INR is short | 6 | bedrock-fx-tools / us.amazon.nova-pro-v1:0 | True | True | False (-) | 3 | 6 | 13,536 | 18.2 | INR-USD | fx_facts > fx_size_conversion > fx_size_conversion |

**Plans: 30** (27 that should be plannable, 3 that should be refused). Tokens spent in total: 233,701. Run date: 2026-10-13.

- Plannable scenarios: the model's own plan was valid without the fallback in **25 of 27**; a valid plan was delivered (model or deterministic fallback) in **27 of 27**.
- Refusal scenario (a payment above the India LRS limit): **3 of 3** correctly ended with no valid plan, so no plan that breaks the limit was produced. The model spent 16-19k tokens trying each time; the deterministic fallback also (correctly) found none.

| Corridor | Plans | Model-only valid | Valid delivered |
|---|---|---|---|
| CNY-EUR | 3 | 3 | 3 |
| CNY-USD | 3 | 3 | 3 |
| EUR-USD | 3 | 3 | 3 |
| INR-EUR | 3 | 3 | 3 |
| INR-USD | 12 | 10 | 12 |
