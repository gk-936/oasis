# Image-intake quality gate, two levels: eval/vision_heldout (30 held-out images)

Generated MOCK invoices; no model was called. `hold` = clearly unusable (no model call), `borderline` = goes to the model with the two-pass check forced, `pass` = normal. These images were generated after the thresholds were fixed and were not used to set them.

- Readable invoices: 24; **hard-held: 0**; borderline (sent to the model): 0
- Unusable controls: 6; hard-held: 6; sent to the model: 0
- Scripted oracle (returns each image's printed fields, not a model) accepted by the full chain: 24
- Thresholds (hard, soft): {"hard_resolution": [320, 200], "soft_resolution": [480, 320], "blur": [10.0, 100.0], "brightness": [30.0, 45.0, 252.0, 254.5], "contrast": [5.0, 8.0]}

| image | expected | verdict | size | blur | brightness | contrast | chain |
|---|---|---|---|---|---|---|---|
| photo_01 | pass | pass | 1100x799 | 559.5 | 209.8 | 34.9 | accepted |
| photo_02 | pass | pass | 1280x949 | 244.9 | 146.0 | 17.0 | accepted |
| photo_03 | pass | pass | 1100x840 | 634.2 | 237.5 | 30.8 | accepted |
| photo_04 | pass | pass | 1100x780 | 408.4 | 195.5 | 32.7 | accepted |
| photo_05 | pass | pass | 1100x700 | 385.0 | 223.2 | 34.3 | accepted |
| photo_06 | pass | pass | 1100x820 | 270.7 | 150.1 | 18.2 | accepted |
| photo_07 | pass | pass | 1600x1006 | 709.0 | 200.2 | 37.9 | accepted |
| photo_08 | pass | pass | 1280x957 | 474.9 | 239.3 | 23.7 | accepted |
| photo_09 | pass | pass | 1100x741 | 873.0 | 232.1 | 36.5 | accepted |
| photo_10 | pass | pass | 1400x870 | 103.6 | 134.5 | 26.7 | accepted |
| photo_11 | pass | pass | 1400x987 | 601.9 | 228.3 | 31.4 | accepted |
| photo_12 | pass | pass | 1600x1056 | 757.8 | 226.7 | 32.0 | accepted |
| photo_13 | pass | pass | 1600x1032 | 541.7 | 186.4 | 45.2 | accepted |
| photo_14 | pass | pass | 1100x816 | 203.1 | 125.5 | 18.5 | accepted |
| photo_15 | pass | pass | 1280x842 | 274.3 | 226.8 | 23.7 | accepted |
| photo_16 | pass | pass | 1280x949 | 604.0 | 194.6 | 38.8 | accepted |
| photo_17 | pass | pass | 1600x1178 | 576.0 | 228.8 | 26.3 | accepted |
| photo_18 | pass | pass | 1100x841 | 220.7 | 132.7 | 16.9 | accepted |
| photo_19 | pass | pass | 1100x794 | 490.2 | 189.6 | 40.2 | accepted |
| photo_20 | pass | pass | 1280x861 | 164.4 | 229.5 | 22.4 | accepted |
| photo_21 | pass | pass | 1280x798 | 906.2 | 225.8 | 36.5 | accepted |
| photo_22 | pass | pass | 1400x994 | 198.8 | 110.8 | 19.8 | accepted |
| photo_23 | pass | pass | 1400x960 | 822.6 | 228.9 | 38.5 | accepted |
| photo_24 | pass | pass | 1100x808 | 680.6 | 228.1 | 29.6 | accepted |
| control_tiny_1 | hold | hold | 200x137 | 31.5 | 238.2 | 21.5 | model not called |
| control_tiny_2 | hold | hold | 220x151 | 42.2 | 238.9 | 21.0 | model not called |
| control_dark_1 | hold | hold | 1400x960 | 3.7 | 15.7 | 2.2 | model not called |
| control_dark_2 | hold | hold | 1400x960 | 5.5 | 20.5 | 2.6 | model not called |
| control_blur_1 | hold | hold | 1400x960 | 2.1 | 238.0 | 12.6 | model not called |
| control_blur_2 | hold | hold | 1400x960 | 1.9 | 238.2 | 11.4 | model not called |
