"""Build `oasis/reference/sanctions_extra.json.gz` from the public UN, UK and EU consolidated sanctions lists.

    python tools/fetch_extra_sanctions.py                       # downloads (network) and writes the file
    python tools/fetch_extra_sanctions.py --from-dir DIR        # parses files already downloaded into DIR (un.xml, uk.csv, eu.csv, eu.xml)

Sources (public, no key): UN Security Council consolidated list (scsanctions.un.org), UK OFSI consolidated list (ConList.csv),
EU consolidated financial sanctions file (webgate.ec.europa.eu, public token). Only individuals and entities are kept. Every entry
records its list. The file is a snapshot with the retrieval date, never a live feed, and a clean result is not a compliance clearance.
Downloaded files are untrusted data: this script only parses them (no eval, no XML entity expansion beyond the standard library's)."""
from __future__ import annotations
import argparse
import csv
import gzip
import io
import json
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "oasis" / "reference" / "sanctions_extra.json.gz"
URLS = {"UN": "https://scsanctions.un.org/resources/xml/en/consolidated.xml",
        "UK": "https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.csv",
        "EU": "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw"}
FILES = {"UN": "un.xml", "UK": "uk.csv", "EU": "eu.csv"}


def _join(*parts) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


def parse_un(raw: bytes) -> list[dict]:
    root = ET.fromstring(raw)
    out = []
    for kind, tag in (("individual", "INDIVIDUAL"), ("entity", "ENTITY")):
        for e in root.iter(tag):
            g = lambda t: (e.findtext(t) or "").strip()          # noqa: E731
            name = _join(g("FIRST_NAME"), g("SECOND_NAME"), g("THIRD_NAME"), g("FOURTH_NAME"))
            if not name:
                continue
            aliases = [(a.findtext("ALIAS_NAME") or "").strip() for a in e.iter(f"{tag}_ALIAS")]
            out.append({"uid": f"UN-{g('DATAID')}", "name": name, "type": kind, "program": g("UN_LIST_TYPE") or "UN", "list": "UN",
                        "aliases": sorted({a for a in aliases if a and a != name})})
    return out


def parse_uk(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    header_at = next(i for i, r in enumerate(rows) if r and r[0].strip() == "Name 6")
    head = rows[header_at]
    ix = {h: i for i, h in enumerate(head)}
    entries: dict[str, dict] = {}
    for r in rows[header_at + 1:]:
        if len(r) < len(head):
            continue
        gtype = r[ix["Group Type"]].strip().lower()
        if gtype not in ("individual", "entity"):
            continue                                             # ships and other groups are dropped, as for OFAC
        name = _join(*(r[ix[f"Name {n}"]] for n in (1, 2, 3, 4, 5, 6)))
        if not name:
            continue
        gid = r[ix["Group ID"]].strip()
        e = entries.setdefault(gid, {"uid": f"UK-{gid}", "name": name, "type": gtype, "program": r[ix["Regime"]].strip() or "UK", "list": "UK", "aliases": []})
        alias_type = r[ix["Alias Type"]].strip().lower()
        if alias_type == "primary name" and e["name"] != name:
            e["aliases"].append(e["name"])
            e["name"] = name
        elif name != e["name"] and name not in e["aliases"]:
            e["aliases"].append(name)
    return list(entries.values())


def parse_eu_csv(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8-sig", errors="replace")
    rd = csv.DictReader(io.StringIO(text), delimiter=";")
    entries: dict[str, dict] = {}
    for r in rd:
        whole = (r.get("NameAlias_WholeName") or "").strip()
        eid = (r.get("Entity_LogicalId") or "").strip()
        if not whole or not eid:
            continue
        typ = "individual" if (r.get("Entity_SubjectType_ClassificationCode") or "").strip().upper() == "P" else "entity"
        e = entries.setdefault(eid, {"uid": f"EU-{eid}", "name": whole, "type": typ, "program": (r.get("Entity_Regulation_Programme") or "EU").strip() or "EU",
                                     "list": "EU", "aliases": []})
        if whole != e["name"] and whole not in e["aliases"]:
            e["aliases"].append(whole)
    return list(entries.values())


PARSERS = {"UN": parse_un, "UK": parse_uk, "EU": parse_eu_csv}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "oasis-reference-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from-dir", help="parse files already downloaded (un.xml, uk.csv, eu.csv)")
    ap.add_argument("--lists", default="UN,UK,EU")
    a = ap.parse_args(argv)
    entries, meta = [], {}
    for name in a.lists.split(","):
        try:
            raw = (Path(a.from_dir) / FILES[name]).read_bytes() if a.from_dir else fetch(URLS[name])
            got = PARSERS[name](raw)
        except (OSError, ValueError, ET.ParseError, StopIteration) as e:
            print(f"{name}: skipped ({type(e).__name__}: {str(e)[:80]})", file=sys.stderr)
            continue
        entries += got
        meta[name] = {"count": len(got), "url": URLS[name]}
        print(f"{name}: {len(got)} entries")
    if not entries:
        print("nothing parsed; the existing file is left unchanged", file=sys.stderr)
        return 1
    doc = {"source": "UN Security Council, UK OFSI and EU consolidated sanctions lists (public)", "retrieved": time.strftime("%Y-%m-%d"),
           "count": len(entries), "lists": meta, "entries": entries}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(entries)} entries -> {OUT} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
