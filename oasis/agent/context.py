"""Session memory and the ellipsis resolver (ROUTER_OVERHAUL.md section 5.4). Pure functions over the dialog dict; nothing here can move money.
Context expires after 6 turns or on reset (the dialog is recreated on reset)."""
from __future__ import annotations

import re

from . import frames, lexicon as L

TTL = 6
KEY = "ctx2"
_ELLIPSIS = re.compile(r"^(?:and|what about|how about|also|and what about)\s+(?:my |the |your )?(?P<obj>[^?.!]{2,30}?)\s*[?.!]*$", re.I)
_OTHER = re.compile(r"^(?:and )?(?:the )?(?:other|next|another) (?:one|bill)\s*[?.!]*$|^what about the other one\s*[?.!]*$", re.I)
_AGAIN = re.compile(r"^(?:same again|again|once more|one more( time)?|same|do it again|the same|like before|as before)\s*[?.!]*$", re.I)
_SAME_BUT = re.compile(r"^(?:same|the same|again) but (?P<n>[\d,.]+k?)\s*[?.!]*$", re.I)
_AND_NUM = re.compile(r"^(?:and|what about|how about|or|no,?|actually,?|make it)\s+(?:make it\s+)?(?P<n>\d[\d,]*(?:\.\d+)?k?)\s*[?.!]*$", re.I)
_PAY_IT = re.compile(r"^(?:ok(?:ay)?,? |yes,? |please |pls )*pay (?:it|him|her|them|that|this)(?: now| please| pls)?\s*[?.!]*$", re.I)
_WHY = re.compile(r"^(?:why|why\??|how come|really|how so|why is that|why not)\s*[?.!]*$", re.I)
_PICK = re.compile(r"^(?:option |number |#)?([1-3])\s*[.)]?$|^the (first|second|third)(?: one)?\s*[?.!]*$", re.I)


def get(d: dict) -> dict:
    return d.setdefault(KEY, {"turn": 0})


def tick(d: dict) -> None:
    c = get(d)
    c["turn"] = c.get("turn", 0) + 1


def fresh(d: dict) -> dict | None:
    """The stored context, or None once it is older than TTL turns."""
    c = get(d)
    if "set_at" not in c or c["turn"] - c["set_at"] > TTL:
        return None
    return c


def remember(d: dict, kind: str, canon: str | None, bill: str | None, amount: float | None = None) -> None:
    c = get(d)
    keep = kind in ("confirm", "faq", "unknown")
    c.update({"last_kind": c.get("last_kind") if keep else kind, "last_canon": c.get("last_canon") if keep else canon,
              "last_bill": c.get("last_bill") if keep else (bill or c.get("last_bill")), "last_amount": amount, "set_at": c.get("turn", 0)})


def resolve(d: dict, message: str, f: frames.Frame, open_bills: list[str]) -> tuple[str, str] | None:
    """(action, text): 'rewrite' with a canonical sentence, or 'say' with a fixed reply. None when the message is not an ellipsis or the context is gone."""
    t = f.text
    m_pick = _PICK.match(t)
    if m_pick and not d.get("awaiting"):
        return "say", "There is nothing to pick. What would you like to do?"
    c = fresh(d)
    if c is None:
        return None
    last, bill = c.get("last_kind"), c.get("last_bill")
    if _OTHER.match(t) and bill and open_bills:
        rest = [b for b in open_bills if b != bill]
        nxt = rest[0] if rest else None
        if nxt is None:
            return "say", "There is no other open bill."
        return "rewrite", _again(last, nxt)
    m = _ELLIPSIS.match(t)
    if m and last:
        obj = m.group("obj").strip()
        tmp = frames.parse(obj)
        if tmp.bills:
            return "rewrite", _again(last, tmp.bills[0])
    if _PAY_IT.match(t) and bill and bill in L.BILLS:
        return "rewrite", f"pay my {L.BILLS[bill][0]}"                          # "what do I owe", "and the rent?", "pay it": the bill the last answer was about
    m = _AND_NUM.match(t)
    if m and c.get("last_canon") and last in ("convert", "pay_obligation", "routes") and re.search(r"\d", c["last_canon"]):
        n = m.group("n").replace(",", "")
        return "rewrite", re.sub(r"\d[\d,.]*k?", n, c["last_canon"], count=1)
    m = _SAME_BUT.match(t)
    if m and c.get("last_canon"):
        n = m.group("n").replace(",", "")
        return "rewrite", re.sub(r"\d[\d.]*k?", n, c["last_canon"], count=1) if re.search(r"\d", c["last_canon"]) else f"{c['last_canon']} {n}"
    if _AGAIN.match(t) and c.get("last_canon"):
        return "rewrite", c["last_canon"]
    if _WHY.match(t) and last in ("pay_obligation", "refused", "held", "bypass", "secrets", "convert", "explain"):
        return "rewrite", "why was it held"
    return None


def _again(last: str | None, bill: str) -> str:
    """The last intent repeated for a new bill. A pay stays a pay frame for a registry bill (the draft still needs the signature)."""
    canon = L.BILLS[bill][0]
    if last == "pay_obligation":
        return f"pay my {canon}"
    return f"how much do i owe on my {canon}"
