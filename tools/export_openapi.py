"""Write docs/openapi.json from the FastAPI app, offline (no server, no network, no model).

    OASIS_LLM=offline OASIS_DB=:memory: PYTHONPATH=. python tools/export_openapi.py

/docs and /openapi.json are switched off on a judge-mode server (correct for security), so this static copy is the API reference.
tests/test_openapi_export.py fails if the file is out of date.
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OASIS_LLM", "offline")
os.environ.setdefault("OASIS_DB", ":memory:")

OUT = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"


def build() -> str:
    from oasis.api.main import app
    return json.dumps(app.openapi(), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    sys.exit(0)
