"""Download the public OFAC SDN list and write the trimmed, compressed copy the app screens against.

    python tools/fetch_reference.py            # needs network; writes oasis/reference/ofac_sdn.json.gz

Source: US Treasury OFAC, Specially Designated Nationals list (sdn.csv + alt.csv), public domain, no key needed.
Only individuals and entities are kept (vessels and aircraft are dropped: nobody pays one by invoice, and their names, such as a
tanker called ARJUN, collide with ordinary words). The file records when it was retrieved; it is a snapshot, not a live feed.
"""
import csv
import gzip
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://www.treasury.gov/ofac/downloads/"
OUT = Path(__file__).resolve().parents[1] / "oasis" / "reference" / "ofac_sdn.json.gz"


def get(name: str) -> list[list[str]]:
    with urllib.request.urlopen(BASE + name, timeout=90) as r:
        return list(csv.reader(io.StringIO(r.read().decode("latin-1"))))


def main() -> int:
    sdn, alt = get("sdn.csv"), get("alt.csv")
    entries: dict[str, dict] = {}
    for row in sdn:
        if len(row) < 4:
            continue
        uid, name, typ, prog = row[0].strip(), row[1].strip(), row[2].strip().lower(), row[3].strip()
        if typ in ("vessel", "aircraft") or not name:
            continue
        entries[uid] = {"uid": uid, "name": name, "type": "individual" if typ == "individual" else "entity",
                        "program": prog.replace("] [", ", ").strip("-0- ").strip(), "aliases": []}
    for row in alt:
        if len(row) >= 4 and row[0].strip() in entries and row[3].strip() not in ("", "-0-"):
            entries[row[0].strip()]["aliases"].append(row[3].strip())
    doc = {"source": "US Treasury OFAC SDN list (sdn.csv, alt.csv)", "url": BASE, "retrieved": time.strftime("%Y-%m-%d"),
           "count": len(entries), "entries": list(entries.values())}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(entries)} entries -> {OUT} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
