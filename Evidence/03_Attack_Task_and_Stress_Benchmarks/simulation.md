# Oasis student-outcome simulation (MODEL - see assumptions in eval/simulator.py)

| Persona | Situation | Fees manual (CNY) | Fees Oasis (CNY) | Saved | Late-payment days manual | Oasis | Scams stopped |
|---|---|---|---|---|---|---|---|
| Arjun | tight runway | 3,188 | 457 | 2,731 | 3 | 3 | 0 |
| Meera | scholarship arrives 21 days late | 2,097 | 388 | 1,708 | 1 | 0 | 0 |
| Kiran | monthly family top-ups | 1,822 | 280 | 1,542 | 0 | 0 | 0 |
| Sana | landlord changes bank account mid-semester | 3,617 | 654 | 2,963 | 3 | 0 | 0 |
| Rahul | receives a forged finance-office invoice | 3,148 | 646 | 2,503 | 3 | 0 | 1 |

Event runs use the real pipeline: Sana: {'event': 'landlord_change', 'oasis_status': 'paid', 'completed': True, 'minutes': 45}; Rahul: {'event': 'forged_invoice', 'oasis_status': 'rejected', 'manual_assumed': 'paid attacker', 'scam_stopped': True, 'money_saved_cny': 30000}
