# Router thresholds: trade-off table (offline)

Train = leave-one-out over the 1694 train phrases (what the thresholds are chosen on). Held-out = the 326 phrases the matcher never reads (reported, never selected on).
Percentages of the set. 'none' = no intent claimed (correct for chit-chat). Targets that were asked for: wrong <= 5% and right + clarified >= 85% on held-out.

| Setting | train right | train wrong | train clarified | train none | held-out right | held-out wrong | held-out clarified | held-out none |
|---|---|---|---|---|---|---|---|---|
| no pair rule, answer at 0.12 | 1322 (78%) | 188 (11%) | 126 (7%) | 58 (3%) | 278 (85%) | 11 (3%) | 25 (8%) | 12 (4%) |
| pair rule on, answer at 0.12 | 1187 (70%) | 172 (10%) | 242 (14%) | 93 (5%) | 253 (78%) | 9 (3%) | 42 (13%) | 22 (7%) |
| **shipped:** pair rule on, answer at 0.17 | 1150 (68%) | 162 (10%) | 271 (16%) | 111 (7%) | 248 (76%) | 7 (2%) | 48 (15%) | 23 (7%) |
| pair rule on, answer at 0.22 | 1127 (67%) | 162 (10%) | 287 (17%) | 118 (7%) | 248 (76%) | 7 (2%) | 48 (15%) | 23 (7%) |
| pair rule on, answer at 0.27 | 1089 (64%) | 162 (10%) | 312 (18%) | 131 (8%) | 239 (73%) | 7 (2%) | 53 (16%) | 27 (8%) |
| pair rule on, answer at 0.32 | 1067 (63%) | 160 (9%) | 329 (19%) | 138 (8%) | 232 (71%) | 6 (2%) | 60 (18%) | 28 (9%) |
| + keyword answers in doubt at 0.25 / 0.12 | 1095 (65%) | 138 (8%) | 343 (20%) | 118 (7%) | 240 (74%) | 7 (2%) | 56 (17%) | 23 (7%) |
| + keyword answers in doubt at 0.17 / 0.12 | 1095 (65%) | 134 (8%) | 347 (20%) | 118 (7%) | 240 (74%) | 7 (2%) | 56 (17%) | 23 (7%) |
| + keyword answers in doubt at 0.0 (any disagreement) | 1073 (63%) | 105 (6%) | 398 (23%) | 118 (7%) | 233 (71%) | 7 (2%) | 63 (19%) | 23 (7%) |
