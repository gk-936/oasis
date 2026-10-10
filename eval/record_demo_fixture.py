"""Record the live-demo fixture: real qwen/qwen3.8-27b responses for both scripted demo runs, written to
`eval/fixtures/demo_cache/` so the Demo tab's "live-replay" mode can replay them later with no network.

    PYTHONPATH=. python -m eval.record_demo_fixture [--max-tokens 25000] [--min-remaining 40000] [--force]

This is the ONLY place the demo uses the network. It refuses to start if recording would leave fewer than
`--min-remaining` tokens of the free-tier daily allowance (200k) according to data/llm_cache/usage.json, and it stops
itself after `--max-tokens` new tokens. Responses already in the fixture cost nothing, so re-running only fills gaps.
The fixture files hold the model name, the response text and the recording date: no prompts, keys or organisation ids
(the script checks that before it finishes).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import time

from oasis import config
from oasis.agent.llm import QuotaExhausted, UsageLedger
from oasis.agent.replay import FIXTURE_DIR, DemoLiveLLM, fixture_info
from oasis.demo import DemoRunner, new_demo_world

FREE_TIER_DAILY_TOKENS = 200_000
SECRET_RE = re.compile(r"(gsk_\w+|org_\w+|Bearer\s+\S+|api[_-]?key)", re.I)


def tokens_used_today() -> int:
    return UsageLedger(config.DATA_DIR / "llm_cache" / "usage.json").day()["tokens"]


def scan_for_secrets() -> list[str]:
    return [f.name for f in FIXTURE_DIR.glob("*.json") if f.name != "usage.json" and SECRET_RE.search(f.read_text(encoding="utf-8"))]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-tokens", type=int, default=25_000)
    ap.add_argument("--min-remaining", type=int, default=40_000,
                    help="refuse to record if fewer than this many daily tokens would remain afterwards")
    ap.add_argument("--force", action="store_true", help="skip the remaining-budget check")
    a = ap.parse_args(argv)
    if not config.GROQ_API_KEY:
        print("GROQ_API_KEY is not set (see .env.example). Nothing was recorded and no network call was made.", file=sys.stderr)
        return 1
    used = tokens_used_today()
    left_after = FREE_TIER_DAILY_TOKENS - used - a.max_tokens
    if left_after < a.min_remaining and not a.force:
        print(f"Refusing to record: {used} tokens used today; a {a.max_tokens}-token recording would leave {left_after} "
              f"(< {a.min_remaining}). Try again after the daily reset, or pass --force.", file=sys.stderr)
        return 2
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    llm = DemoLiveLLM(record=True, token_cap=a.max_tokens)
    start, partial = tokens_used_today(), False
    try:
        for run in DemoRunner.RUNS:
            DemoRunner(run, new_demo_world(mode="live", llm=llm)).run_all()
    except QuotaExhausted as e:
        partial = True
        print(f"Stopped early: {e}. What was recorded is kept; re-run later to fill the gaps.", file=sys.stderr)
    bad = scan_for_secrets()
    if bad:
        for name in bad:
            (FIXTURE_DIR / name).unlink()
        print(f"Removed {len(bad)} fixture file(s) that looked like they held a secret; investigate before recording again.", file=sys.stderr)
        return 3
    info = fixture_info()
    manifest = {"recorded": time.strftime("%Y-%m-%d"), "model": config.AGENT_MODEL, "fallback_model": config.FALLBACK_MODEL,
                "entries": info["entries"], "tokens_spent_this_run": tokens_used_today() - start, "partial": partial,
                "note": "Recorded responses for the Demo tab's live-replay mode. Contains model name, response text and date only."}
    (FIXTURE_DIR / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps(manifest, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
