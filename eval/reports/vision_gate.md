# Image-intake quality gate, two levels: eval/vision (40 tuning images)

Generated MOCK invoices; no model was called. `hold` = clearly unusable (no model call), `borderline` = goes to the model with the two-pass check forced, `pass` = normal. The thresholds were set on THESE images, so the figures below are a fit, not a held-out result.

- Readable invoices: 32; **hard-held: 0**; borderline (sent to the model): 0
- Unusable controls: 8; hard-held: 8; sent to the model: 0
- Scripted oracle (returns each image's printed fields, not a model) accepted by the full chain: 32
- Thresholds (hard, soft): {"hard_resolution": [320, 200], "soft_resolution": [480, 320], "blur": [10.0, 100.0], "brightness": [30.0, 45.0, 252.0, 254.5], "contrast": [5.0, 8.0]}

| image | expected | verdict | size | blur | brightness | contrast | chain |
|---|---|---|---|---|---|---|---|
| clean_en_1 | pass | pass | 900x560 | 642.9 | 242.1 | 34.9 | accepted |
| clean_en_2 | pass | pass | 900x560 | 583.8 | 242.7 | 33.4 | accepted |
| clean_en_3 | pass | pass | 900x560 | 602.8 | 242.5 | 33.9 | accepted |
| clean_en_4 | pass | pass | 900x560 | 641.6 | 242.1 | 34.9 | accepted |
| clean_en_5 | pass | pass | 900x560 | 583.6 | 242.7 | 33.4 | accepted |
| clean_zh_1 | pass | pass | 900x560 | 661.1 | 241.9 | 35.0 | accepted |
| clean_zh_2 | pass | pass | 900x560 | 618.6 | 242.4 | 33.8 | accepted |
| clean_zh_3 | pass | pass | 900x560 | 625.9 | 242.3 | 34.0 | accepted |
| clean_zh_4 | pass | pass | 900x560 | 660.4 | 241.9 | 35.0 | accepted |
| clean_zh_5 | pass | pass | 900x560 | 618.1 | 242.4 | 33.8 | accepted |
| mixed_1 | pass | pass | 1000x560 | 856.6 | 239.7 | 39.7 | accepted |
| mixed_2 | pass | pass | 1000x560 | 737.3 | 240.8 | 37.3 | accepted |
| mixed_3 | pass | pass | 1000x560 | 756.2 | 240.6 | 37.7 | accepted |
| mixed_4 | pass | pass | 1000x560 | 854.6 | 239.7 | 39.7 | accepted |
| skewed_1 | pass | pass | 930x608 | 582.8 | 242.5 | 33.2 | accepted |
| skewed_2 | pass | pass | 938x622 | 513.6 | 243.2 | 31.4 | accepted |
| skewed_3 | pass | pass | 954x652 | 506.4 | 243.4 | 30.8 | accepted |
| skewed_4 | pass | pass | 962x666 | 522.8 | 243.2 | 31.3 | accepted |
| rotated_1 | pass | pass | 900x560 | 642.8 | 242.1 | 34.9 | accepted |
| rotated_2 | pass | pass | 900x560 | 583.8 | 242.7 | 33.4 | accepted |
| rotated_3 | pass | pass | 900x560 | 602.6 | 242.5 | 33.9 | accepted |
| blurry_1_1 | pass | pass | 900x560 | 138.7 | 242.2 | 27.3 | accepted |
| blurry_1_2 | pass | pass | 900x560 | 125.0 | 242.7 | 26.3 | accepted |
| blurry_2_1 | hold | hold | 900x560 | 7.3 | 242.2 | 21.4 | model not called |
| blurry_2_2 | hold | hold | 900x560 | 6.9 | 242.7 | 20.6 | model not called |
| blurry_3_1 | hold | hold | 900x560 | 0.8 | 242.2 | 17.9 | model not called |
| blurry_3_2 | hold | hold | 900x560 | 0.7 | 242.7 | 17.2 | model not called |
| low_light_1 | pass | pass | 900x560 | 132.0 | 84.6 | 12.3 | accepted |
| low_light_2 | hold | hold | 900x560 | 13.9 | 28.3 | 4.0 | model not called |
| low_res_1 | hold | hold | 300x187 | 178.4 | 241.7 | 30.0 | model not called |
| low_res_2 | hold | hold | 260x162 | 97.0 | 242.3 | 27.5 | model not called |
| low_res_3 | hold | hold | 220x137 | 52.9 | 242.1 | 26.3 | model not called |
| handwritten_1 | pass | pass | 900x560 | 437.7 | 244.5 | 26.4 | accepted |
| handwritten_2 | pass | pass | 900x560 | 396.3 | 244.8 | 25.4 | accepted |
| injected_1 | pass | pass | 900x560 | 729.0 | 241.3 | 36.3 | accepted |
| injected_2 | pass | pass | 900x560 | 695.4 | 241.6 | 35.3 | accepted |
| injected_3 | pass | pass | 900x560 | 718.2 | 241.5 | 35.8 | accepted |
| injected_4 | pass | pass | 900x560 | 751.6 | 241.1 | 36.6 | accepted |
| wrong_account_1 | pass | pass | 900x560 | 649.4 | 242.1 | 35.0 | accepted |
| wrong_account_2 | pass | pass | 900x560 | 607.0 | 242.5 | 33.9 | accepted |
