# Peer netting benchmark (MOCK: seeded synthetic cohorts)

Seed 11. Cost = CNY lost versus mid-rate.

| Pool size | Volume CNY | Matched | Cost alone | Cost netted | Saving CNY | Saving |
|---|---|---|---|---|---|---|
| 1 | 22,957 | 0.0% | 295 | 295 | 0 | 0.0% |
| 2 | 36,505 | 44.2% | 332 | 69 | 263 | 79.33% |
| 10 | 127,694 | 27.1% | 1,353 | 593 | 761 | 56.19% |
| 50 | 844,635 | 22.5% | 8,456 | 4,865 | 3,591 | 42.46% |
| 200 | 3,243,411 | 29.8% | 32,676 | 14,544 | 18,132 | 55.49% |
| 1000 | 15,543,272 | 26.1% | 157,882 | 81,640 | 76,242 | 48.29% |

- Synthetic demand; real pools are thinner and lopsided.
- CNY->INR cost assumed equal to the mirror INR->CNY route (MOCK).
- Real netting needs a licensed counterparty and regulatory approval; nothing here moves money.
- Only payee-verified, approved payments with >=2 days to deadline enter the pool.
