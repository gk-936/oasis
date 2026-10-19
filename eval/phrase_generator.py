"""Phrase generator and the DEV / WORD-HELD-OUT / BLIND split (ROUTER_OVERHAUL.md section 9). Deterministic, offline, no model.

    message = [opener] + [speech-act frame] + [object phrase] + [slot phrase] + [closer] + [noise transform]

DEV          generated from the lexicon words the router has (70% of each concept); the router was tuned on these. May be tuned on.
WORD-HELD-OUT  generated ONLY from the withheld 30% of each concept's words; while this set runs, those words are removed from the router's lexicon
               (lexicon.WITHHELD). Not tuned on: if a failure is fixed by adding the withheld word, the word moves to DEV and a fresh 30% is drawn (new seed).
BLIND        tests/data/blind/*.json written by people who have not seen the router; read-only, hash logged, never tuned on. Empty until teammates return it.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import random
import re

from oasis.agent import lexicon as L

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEED_SPLIT = 20261019            # fixed and recorded in the report; draw a new one only after a withheld word moves to DEV

OPENERS = ["", "", "", "hi ", "hey ", "hello ", "so ", "ok so ", "quick question: ", "excuse me, ", "please ", "pls ", "um ", "hey bot ", "Oasis, ", "can you ",
           "could you ", "would you mind ", "I was wondering if you could ", "I'd like you to ", "just ", "yo "]
CLOSERS = ["", "", "", " please", " thanks", " asap", " today", " now", " for this semester", " for this month", " if possible", "?"]
PAY_FRAMES = ["pay {o}", "please pay {o}", "I need to pay {o}", "I want to pay {o}", "settle {o}", "take care of {o}", "clear {o}", "time to pay {o}", "help me pay {o}",
              "go ahead and pay {o}", "I have to pay {o}", "get {o} paid", "do {o} payment", "I'd like to pay {o}", "let's pay {o}"]
HI_PAY = ["{o} bhej do", "{o} pay karo", "mera {o} bharo", "{o} chuka do", "{o} de do"]
ZH_PAY = ["交{o}", "帮我付{o}", "我要交{o}", "支付{o}", "缴{o}"]
# nouns that need a frame to be a sentence; everything else in INFO is already a phrase or question
NOUN_FRAMES = {"balance": ["what is my {w}", "show my {w}", "check my {w}", "{w}?"], "limit": ["what is the {w}", "my {w}"], "limits": ["what are the {w}"],
               "quota": ["what is the {w}"], "rate": ["what is the {w} today", "{w}?"], "proof": ["show me {w}", "i need {w}"], "receipt": ["show me the {w}"],
               "bills": ["show my {w}", "what are my {w}"], "unpaid": ["anything {w}?", "what is {w}"], "outstanding": ["what is {w}"], "dues": ["what are my {w}"],
               "deadlines": ["what are my {w}"], "funds": ["how are my {w}"], "wallets": ["show my {w}"], "holdings": ["show my {w}"], "credit": ["tell me about {w}"]}

BILLS_PAYABLE = ("tuition", "rent", "deposit", "phone")                  # the four bill types the MOCK world holds
INFO_SCORED = {"balance": {"balance"}, "obligations": {"obligations"}, "rate": {"rate", "convert"}, "routes": {"routes"}, "runway": {"runway"},
               "spending": {"spending"}, "status": {"status", "where", "proof"}, "transfer_issue": {"transfer_issue", "status"}, "quota": {"quota"},
               "parent_request": {"parent_request"}, "credit": {"credit", "share_record"}, "share_record": {"share_record", "credit"}, "proof": {"proof", "status"},
               "plan": {"plan", "obligations"}, "help": {"help", "faq"}}

_SAFE_INFO = {                                                           # info phrases that are unambiguous enough to score (a shared word like "stuck" is not)
    "status": None, "transfer_issue": None}


def split_words(words: tuple[str, ...], rng: random.Random) -> tuple[list[str], list[str]]:
    """(kept, withheld): a random 30% of a concept's words are withheld from the router."""
    ws = sorted(set(words))
    rng.shuffle(ws)
    k = max(1, round(0.3 * len(ws)))
    return sorted(ws[k:]), sorted(ws[:k])


def concept_split(seed: int = SEED_SPLIT) -> dict[str, dict[str, list[str]]]:
    rng = random.Random(seed)
    out: dict[str, dict[str, list[str]]] = {"bills": {}, "info": {}}
    for name, (_c, words) in sorted(L.BILLS.items()):
        out["bills"][name] = dict(zip(("kept", "withheld"), split_words(words, rng)))
    for name, (_c, words) in sorted(L.INFO.items()):
        out["info"][name] = dict(zip(("kept", "withheld"), split_words(words, rng)))
    return out


# ------------------------------------------------------------------ noise transforms (the 28 of the surface probe)
def _typo(s: str, rng: random.Random) -> str:
    w = s.split()
    i = rng.randrange(len(w))
    x = w[i]
    if len(x) > 3:
        k = rng.randrange(1, len(x) - 1)
        x = x[:k] + x[k + 1] + x[k] + x[k + 2:]
    w[i] = x
    return " ".join(w)


NOISE = {
    "none": lambda s, r: s, "upper": lambda s, r: s.upper(), "title": lambda s, r: s.title(), "q": lambda s, r: s.rstrip("?") + "?", "bang": lambda s, r: s + "!!!",
    "politeness": lambda s, r: "Hi there, could you kindly help me: " + s + ". Thanks a lot!",
    "ramble": lambda s, r: "so I just got to the dorm and I'm a bit stressed, anyway " + s + " because my mom keeps asking",
    "typo": _typo, "typo2": lambda s, r: _typo(_typo(s, r), r), "emoji": lambda s, r: "\U0001F4B8 " + s + " \U0001F64F", "dots": lambda s, r: s + "....",
    "double_space": lambda s, r: s.replace(" ", "  "), "lead_so": lambda s, r: "so, " + s, "hinglish": lambda s, r: "bhai " + s + " yaar",
    "txtspeak": lambda s, r: re.sub(r"\byou\b", "u", re.sub(r"\bplease\b", "pls", s)), "nopunct": lambda s, r: s.lower().rstrip("?."),
    "quotes": lambda s, r: '"' + s + '"', "trailing": lambda s, r: s + " for this semester", "urgent": lambda s, r: "URGENT!! " + s + " asap",
    "newline": lambda s, r: s.replace(" ", "\n", 1), "md": lambda s, r: "**" + s + "**", "oasis": lambda s, r: "Oasis, " + s,
}
NOISE_NAMES = sorted(NOISE)


def make(rng: random.Random, kind: str, concept: str, word: str, lang: str) -> str:
    """One surface message for a concept word."""
    op = rng.choice(OPENERS)
    cl = rng.choice(CLOSERS)
    if kind == "pay":
        pool = ZH_PAY if re.search(r"[一-鿿]", word) and rng.random() < .7 else HI_PAY if lang == "hi" else PAY_FRAMES
        art = "" if word.startswith(("the ", "my ")) or re.search(r"[一-鿿]", word) else rng.choice(["my ", "the "])
        core = rng.choice(pool).format(o=art + word)
        if not re.search(r"[一-鿿]", core):
            core = op + core
    else:
        f = NOUN_FRAMES.get(word)
        core = op + (rng.choice(f).format(w=word) if f else word)
    s = core + (cl if not re.search(r"[一-鿿]", core) else "")
    s = s.strip()
    names = [n for n in NOISE_NAMES if not (re.search(r"[一-鿿]", s) and n in ("typo", "typo2", "title", "txtspeak"))]
    return NOISE[rng.choice(names)](s, rng)


def generate(n: int, seed: int, held_out: bool, split: dict | None = None) -> list[dict]:
    """n messages with expected class and accepted intents. held_out=True draws words only from the withheld 30%."""
    split = split or concept_split()
    rng = random.Random(seed + (1 if held_out else 0))
    items, seen = [], set()
    key = "withheld" if held_out else "kept"
    tries = 0
    while len(items) < n and tries < n * 30:
        tries += 1
        if rng.random() < 0.38:
            b = rng.choice(BILLS_PAYABLE)
            ws = split["bills"]["phone" if b == "phone" else b][key]
            if not ws:
                continue
            w = rng.choice(ws)
            lang = "zh" if re.search(r"[一-鿿]", w) else ("hi" if w in ("kiraya", "bijli ka bill") or rng.random() < .1 else "en")
            if b == "phone" and w in ("recharge", "mobile", "sim", "airtime"):
                pass
            msg = make(rng, "pay", b, w, lang)
            exp = {"class": "draft", "intents": ["pay_obligation"], "bill": b}
            kind = "pay"
        else:
            c = rng.choice(sorted(INFO_SCORED))
            ws = split["info"][c][key]
            if not ws:
                continue
            w = rng.choice(ws)
            msg = make(rng, "info", c, w, "zh" if re.search(r"[一-鿿]", w) else "en")
            exp = {"class": "answer", "intents": sorted(INFO_SCORED[c]), "concept": c}
            kind = "info"
        if msg in seen:
            continue
        seen.add(msg)
        items.append({"id": f"{'HO' if held_out else 'DEV'}-{len(items):05d}", "message": msg, "kind": kind, "set": "held_out" if held_out else "dev", **exp})
    return items


def withheld_words(split: dict | None = None) -> dict[str, dict[str, list[str]]]:
    split = split or concept_split()
    return {"bills": {k: v["withheld"] for k, v in split["bills"].items()}, "info": {k: v["withheld"] for k, v in split["info"].items()}}


def blind_items() -> tuple[list[dict], str]:
    """The BLIND set (read-only) and its sha256. Files: tests/data/blind/*.json, each {"items": [{"message","class","intents"}]}."""
    d = ROOT / "tests" / "data" / "blind"
    items, h = [], hashlib.sha256()
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        raw = p.read_bytes()
        h.update(raw)
        for i, it in enumerate(json.loads(raw.decode("utf-8")).get("items", [])):
            items.append({"id": f"BLIND-{p.stem}-{i:03d}", "message": it["message"], "class": it["class"], "intents": it.get("intents", []), "set": "blind", "kind": it.get("kind", "?")})
    return items, h.hexdigest()[:16]
