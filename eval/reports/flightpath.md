# FlightPath benchmark (SIMULATION (mock rails))

400 seeded transfers, seed 11. Not validated against real rails.

| Metric | Baseline | FlightPath |
|---|---|---|
| Recipient short-credited | 0.9 | 0.0 |
| Duplicate payments | 62 | 0 |
| Preventable issues flagged | 0/119 | 119/119 |
| Recipient-amount error (CNY, MAE) | 4.9 | 4.43 |

False-alarm rate on legitimate transfers: 0.0.
Slow-but-successful transfers (a retry would duplicate): 62.
