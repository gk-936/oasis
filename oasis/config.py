"""Runtime configuration. Models are env-overridable."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ["OASIS_DATA_DIR"]) if os.environ.get("OASIS_DATA_DIR") else ROOT / "data"   # /data in the container
RULES_DIR = Path(__file__).resolve().parent / "trust" / "rules"


def _load_dotenv(path: Path) -> None:
    """Tiny .env reader (no dependency). Real environment variables always win."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip("'\"")
            if v:                       # a blank "KEY=" line means "not set" (an empty AWS_* variable would break credential lookup)
                os.environ.setdefault(k.strip(), v)
    except OSError:
        pass


_load_dotenv(ROOT / ".env")

# LLM provider: "offline" (deterministic, no network) or "bedrock" (Amazon Nova Pro on Amazon Bedrock).
LLM_PROVIDER = os.getenv("OASIS_LLM", "offline")
# Extraction mode: "deterministic" (default; regex is the floor, the model only fills gaps) or "llm" (live agent:
# the model's JSON is primary, the regex parse is only a per-field fallback).
EXTRACT_MODE = os.getenv("OASIS_EXTRACT", "deterministic")
# Optional LLM risk scorer (live mode only, i.e. OASIS_EXTRACT=llm): combined as max(heuristic, llm), escalate-only.
LLM_RISK = os.getenv("OASIS_LLM_RISK", "0") == "1"


# Amazon Bedrock (OASIS_LLM=bedrock): Amazon Nova Pro. The model id is the Bedrock id / inference profile enabled in YOUR account.
BEDROCK_MODEL = os.getenv("OASIS_BEDROCK_MODEL", "us.amazon.nova-pro-v1:0")
BEDROCK_REGION = os.getenv("OASIS_BEDROCK_REGION") or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
AGENT_MODEL = BEDROCK_MODEL                                                  # the model every live LLM job uses
REDTEAM_MODEL = AGENT_MODEL
FALLBACK_MODEL = os.getenv("OASIS_BEDROCK_FALLBACK_MODEL", AGENT_MODEL)      # default: no silent downgrade to a weaker model
# Client-side guard rails: calls per minute, and a daily token cap as a spend guard (about $1 at $0.10 in / $0.50 out per 1M).
BEDROCK_RPM = float(os.getenv("OASIS_BEDROCK_RPM", "120"))
BEDROCK_DAILY_TOKEN_BUDGET = int(os.getenv("OASIS_BEDROCK_DAILY_TOKENS", "2000000"))
# lifetime budget (0 = none): once the ledger in the data volume has counted this many tokens over ALL days, the model is never called again
# and every AI feature uses its deterministic result. A call that starts just under the limit can overshoot it by that one call.
BEDROCK_TOTAL_TOKEN_BUDGET = int(os.getenv("OASIS_BEDROCK_TOTAL_TOKENS", "0"))
BEDROCK_MAX_RETRIES = int(os.getenv("OASIS_BEDROCK_MAX_RETRIES", "4"))
# per-call network limits: one hung model call must not hold the single worker (every judge waits) for minutes
BEDROCK_TIMEOUT = float(os.getenv("OASIS_BEDROCK_TIMEOUT", "45"))
BEDROCK_CONNECT_TIMEOUT = float(os.getenv("OASIS_BEDROCK_CONNECT_TIMEOUT", "8"))

# Persistence for the API session: a SQLite file, or ":memory:" / "" for in-memory only.
DB_PATH = os.getenv("OASIS_DB") or str(DATA_DIR / "oasis.db")

RULESET_VERSION = "2026.10.2"
