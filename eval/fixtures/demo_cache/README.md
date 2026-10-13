Recorded model responses for the Demo tab's live-replay mode (see `oasis/agent/replay.py`).
Each `<hash>.json` holds only the model name, the response text and the recording date: no prompts, keys or
organisation ids. While this directory holds no recordings the live-replay demo falls back to the offline parser and
says so on every step.

Record (spends Bedrock tokens; refuses when the daily token budget would run low):

    PYTHONPATH=. python -m eval.record_demo_fixture
