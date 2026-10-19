# Image invoice intake: what changed

Offline only. No Bedrock call was made, and nothing under `oasis/trust/*` was touched. Nothing is committed.

## What the pipeline does now (`oasis/agent/vision.py`, called from `VisionExtractor.to_text` in `oasis/agent/llm.py`)

1. **Two-level quality gate** (Pillow only). *Hard* (clearly unusable): short side under 200px or long side under 320px, blur (variance of the Laplacian after a 3x3 median, border cropped, on an 800px copy) under 10, mean brightness under 30 or over 254.5, contrast (grey-level std) under 5. A hard failure raises `VisionHold` (kind `quality`) with no model call and a why-card asking for a clearer photo or pasted text. *Borderline* (soft): under 480x320, blur under 100, brightness under 45 or over 252, contrast under 8. A borderline photo goes to the model, the two-pass check is forced even if `OASIS_VISION_PASSES=1`, and it is held only on disagreement or a validation failure (the hold names that the photo was borderline). Undecodable files and images over 40 megapixels are hard-held.
   - Fixed a bug in the first blur metric: Pillow's 3x3 kernel leaves the border pixels unfiltered, which put a constant floor under the variance, so heavy blur read as about 95 instead of about 1. The border is now cropped and a median filter runs first so speckle and phone noise do not count as sharpness.
2. **Preprocessing**: EXIF auto-orient, deskew (within 10 degrees), upscale to a 1400px long side, autocontrast, mild unsharp mask. Neither image is stored.
3. **Closed-list payee**: the prompt lists each registry payee as `id | English name | Chinese name/aliases`; the model returns one `payee_id` or `none`. Any `Payee:` name it adds is ignored and the text for the pipeline takes the name from the registry. Chinese aliases for every MOCK payee are in `oasis/mock/registry.py` (`ALIASES`, beside the signed credential; signatures unchanged). They are machine-drafted and unreviewed.
4. **Bilingual prompt for every image**: English and Chinese instructions and field labels (`Payee ID (收款方编号)` and so on), the same for every image; language is no longer chosen from hints. The reply parser accepts English or Chinese labels.
5. **Validators**: `payee_id` in the registry; account 12 to 19 digits (or a registry account reference); amount positive, at most 1,000,000; due date between 60 days ago and 2 years ahead; purpose from `tuition, rent, deposit, living, family_support` (Chinese labels mapped). A failure is a `VisionHold` (kind `validation`) naming the field.
   - **Amount**: if the payee has an open obligation, an amount over 2x the largest one fails (validation). If the payee has **no** open obligation (for example the student's own account), the 2x rule is not applied; the amount is held for the student's confirmation (kind `confirmation`, rule `vision_confirmation`) with a why-card saying it is not tied to any open obligation.
6. **Two passes** (`OASIS_VISION_PASSES=2` default; `1` reads once, except borderline photos): reworded second prompt; a difference in `payee_id`, amount or account holds (kind `disagreement`).
7. `POST /api/intake/image` returns a held outcome with `card` and a `vision` object (kind, doubtful fields, measured quality) on any hold; Telegram and email attachments hold the same way. Accepted images still go through the normal pipeline (registry-account rule, signed approvals).
8. **Live-run rows**: every live vision call (`OASIS_LLM=bedrock`) appends the raw model reply per image (SHA-256 prefix) and pass, and each final outcome, to `eval/reports/vision_live_final_rows.json` (`OASIS_VISION_ROWS` overrides the path, `0` turns it off). Offline and test runs write nothing. The rows hold the model's text for the invoice, never the image. **Privacy note:** in real (not MOCK) use that text contains the student's invoice fields; keep the file out of any shared location or set `OASIS_VISION_ROWS=0`.
9. **`execution_evidence/verify_evidence.py` check 6** recomputes the vision figures from those rows: every accepted image has valid, in-list, agreeing readings in its raw replies; none whose passes disagree or ran away was accepted; every model-read image has an outcome; hold counts by kind. It prints `SKIP` until a live vision run has been saved (the stdlib re-implementation covers the payee list, runaway values and the three agreement fields, not the date, purpose or amount-plausibility rules). `eval/participant_logs.py` copies the rows file into `execution_evidence/live_reports/` when it exists. The two copies of the verifier (`execution_evidence/`, `Evidence/02_Execution_Logs/`) are identical.

## Gate results, reported separately (`eval/vision_gate_bench.py`)

| Set | Readable | Readable hard-held | Readable borderline | Unusable controls | Controls hard-held |
|---|---|---|---|---|---|
| Tuning: `eval/vision` (40 images, thresholds set on these, so a fit) | 32 | 0 | 0 | 8 | 8 |
| **Held-out: `eval/vision_heldout` (30 images, never used to set thresholds)** | 24 | **0** | 0 | 6 | 6 |

Held-out images: 24 JPEG photos with Georgia, Calibri, Cambria, Candara, Tahoma, Segoe UI, Comic Sans, Courier New, Bahnschrift, Microsoft JhengHei and Yu Gothic, a ruled-table layout, perspective tilt, shadows, paper texture, phone-like noise, JPEG quality 40 to 85, mild dimming and blur; plus 6 controls (2 tiny, 2 very dark, 2 very blurry). Reports: `eval/reports/vision_gate.md`, `eval/reports/vision_heldout_gate.md`; rebuild with `python -m eval.vision.generate` and `python -m eval.vision_heldout.generate` (Windows fonts).

Caveats: the held-out set is synthetic and written by the same team, so it is only "held out" from the threshold tuning; no held-out image was borderline (the lowest sharpness among readable ones was 103.6, just above the soft limit of 100), so the borderline path is covered by unit tests, not by this set; a scripted oracle stands in for the model, so these figures say nothing about how well Nova Pro reads the images. No live run was made.

## Replay of the two failed live responses (`tests/test_vision_hardening.py`)

The raw rows were not saved (that is what item 8 fixes); both replies are reconstructed from `eval/reports/vision_live.md`.

- Chinese invoice, invented payee 赵凯旋 and purpose 测试: payee name ignored; purpose fails the closed list; held on `purpose`. With a valid purpose it is corrected to the registry name.
- Blurry image, invented payee and a payee ID of thousands of zeros: hard-held before the model; if the gate is bypassed the runaway ID is rejected, and a shorter bogus ID fails the registry check.

## Docker

`Pillow>=10` is in `requirements.txt`, and the Dockerfile's builder stage installs `requirements.txt` minus pytest, so Pillow is installed (manylinux wheels exist for python:3.12-slim; no system libraries needed). **No docker build was run:** the Docker CLI is installed but the daemon is not running on this machine.

## Not done / limits

- No live check of the bilingual closed-list prompt on Nova Pro; it needs an approved live run (the rows file will record it).
- 90/180 degree rotation is handled only when the file carries EXIF orientation.
- Plausible-but-wrong values that pass the validators are limited by the two-pass check, the registry-only payment rule and the student's confirmation.
- README/docs test counts and the PDFs were not updated.

## Checks

| Check | Result |
|---|---|
| `tests/test_chat_llm_bench.py` | 7 passed. Added an autouse `OASIS_ROUTER_ROBUST=0` fixture (as in `tests/test_chat_llm.py`); no assertion was changed. See the note below. |
| Vision tests (`tests/test_vision_hardening.py`) | 65 passed |
| Full suite (`OASIS_DB=:memory: OASIS_LLM=offline PYTHONPATH=. python -m pytest -q`) | 2731 passed, 2 skipped, 0 failed |
| `execution_evidence/verify_evidence.py` | ALL CHECKS PASSED (vision check skipped: no live rows yet) |
| `python -m eval.runner --llm offline` | attack block rate 1.0, money lost 0 (the timestamp-only change to `eval/reports/benchmark.*` was reverted) |

Note on the bench tests: when I first ran them, the fixture alone did not fix them, because the working-tree keyword router (`oasis/agent/nlu.py`) already placed "can I last until december without trouble", "remind me what's outstanding" and "how many months of coverage do I have" with the robust layer off (the committed `nlu.py` returned `unknown` for all three). By the final run they passed; `eval/chat_llm_bench.py` and `docs/security-self-assessment.md` show edits I did not make, so something else in the tree changed in between. I did not investigate which change made the difference.
