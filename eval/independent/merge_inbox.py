"""Merge the JSON chunks an outside AI wrote (saved in eval/independent/inbox/) into one set, validate it, and report problems.

Run:  python eval/independent/merge_inbox.py G
      reads inbox/G_attacks_*.json, G_lookalikes_*.json, G_tasks_*.json; writes attacksG.json, lookalikesG.json, tasksG.json next to this file
Then: OASIS_LLM=offline PYTHONPATH=. python -m eval.independent_bench G
A chunk may be wrapped in a markdown fence: the first JSON array in the file is used. Duplicate messages are dropped, bad items are listed.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KINDS = {"draft_awaiting_signature", "redrafted", "answer", "clarifying_question", "cancelled", "refused"}
CHANNELS = {"chat", "invoice_text", "email_text"}


def load_chunk(p: Path):
    t = p.read_text(encoding="utf-8")
    m = re.search(r"\[.*\]", t, re.S)
    return json.loads(m.group(0)) if m else []


def check(kind, it):
    if kind == "tasks":
        if not isinstance(it.get("turns"), list) or not it["turns"] or not all(isinstance(x, str) and x.strip() for x in it["turns"]):
            return "turns must be a non-empty list of strings"
        if it.get("expected_kind") not in KINDS:
            return f"expected_kind {it.get('expected_kind')!r} not in {sorted(KINDS)}"
        it.setdefault("expected", it["expected_kind"])
    else:
        if not isinstance(it.get("attack"), str) or not it["attack"].strip():
            return "attack must be a non-empty string"
        if it.setdefault("channel", "chat") not in CHANNELS:
            return f"channel {it['channel']!r} not in {sorted(CHANNELS)}"
        it.setdefault("setup_turns", [])
    it.setdefault("category", "other")
    return None


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "G"
    (HERE / "inbox").mkdir(exist_ok=True)
    for kind in ("attacks", "lookalikes", "tasks"):
        items, seen, bad = [], set(), []
        for f in sorted((HERE / "inbox").glob(f"{tag}_{kind}_*.json")):
            try:
                chunk = load_chunk(f)
            except Exception as e:  # noqa: BLE001
                bad.append(f"{f.name}: not valid JSON ({e})")
                continue
            for it in chunk:
                key = json.dumps(it.get("turns") or it.get("attack"), ensure_ascii=False)
                why = check(kind, it)
                if why:
                    bad.append(f"{f.name} {it.get('id')}: {why}")
                elif key in seen:
                    bad.append(f"{f.name} {it.get('id')}: duplicate message dropped")
                else:
                    seen.add(key)
                    items.append(it)
        for i, it in enumerate(items, 1):
            it["id"] = f"{kind[0].upper()}{tag}-{i:03d}"
        if items:
            (HERE / f"{kind}{tag}.json").write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{kind}: {len(items)} items kept, {len(bad)} problems")
        for b in bad[:20]:
            print("   -", b)


if __name__ == "__main__":
    main()
