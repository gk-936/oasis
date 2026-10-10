"""Runtime configuration. Models are env-overridable because Groq retires models often."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RULES_DIR = Path(__file__).resolve().parent / "trust" / "rules"


def _load_dotenv(path: Path) -> None:
    """Tiny .env reader (no dependency). Real environment variables always win."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    except OSError:
        pass


_load_dotenv(ROOT / ".env")

# LLM provider: "offline" (deterministic, no network) or "groq".
LLM_PROVIDER = os.getenv("OASIS_LLM", "offline")
# Extraction mode: "deterministic" (default; regex is the floor, the model only fills gaps) or "llm" (live agent:
# the model's JSON is primary, the regex parse is only a per-field fallback).
EXTRACT_MODE = os.getenv("OASIS_EXTRACT", "deterministic")
# Optional LLM risk scorer (live mode only, i.e. OASIS_EXTRACT=llm): combined as max(heuristic, llm), escalate-only.
LLM_RISK = os.getenv("OASIS_LLM_RISK", "0") == "1"
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# Verify these on console.groq.com/docs/models before a run (checked 2026-10-10).
AGENT_MODEL = os.getenv("OASIS_AGENT_MODEL", "qwen/qwen3.8-27b")  # preview model; may be retired
REDTEAM_MODEL = os.getenv("OASIS_REDTEAM_MODEL", "openai/gpt-oss-120b")
FALLBACK_MODEL = os.getenv("OASIS_FALLBACK_MODEL", "openai/gpt-oss-120b")  # production model

# Groq free-tier guard rails (about 30 RPM, 1,000 requests/day, 200k tokens/day for these models).
GROQ_RPM = float(os.getenv("OASIS_GROQ_RPM", "25"))                    # stay under the 30 RPM limit
GROQ_DAILY_TOKEN_BUDGET = int(os.getenv("OASIS_GROQ_DAILY_TOKENS", "180000"))
GROQ_DAILY_REQUEST_BUDGET = int(os.getenv("OASIS_GROQ_DAILY_REQUESTS", "900"))
GROQ_MAX_RETRIES = int(os.getenv("OASIS_GROQ_MAX_RETRIES", "4"))

# Persistence for the API session: a SQLite file, or ":memory:" / "" for in-memory only.
DB_PATH = os.getenv("OASIS_DB") or str(DATA_DIR / "oasis.db")

RULESET_VERSION = "2026.10.2"
