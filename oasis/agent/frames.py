"""Frame parser (ROUTER_OVERHAUL.md section 3): a message becomes a speech act, concepts and slots. Pure, deterministic, no I/O.
It never decides anything; router_v2.py reads the frame and picks a route."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from . import lexicon as L

_ZW = re.compile(r"[​-‏‪-‮⁠﻿]")
_SPACE = re.compile(r"\s+")
_TYPO = {"tution": "tuition", "tuiton": "tuition", "tuision": "tuition", "tutition": "tuition", "recieve": "receive", "mony": "money", "moeny": "money",
         "blance": "balance", "balnce": "balance", "cheepest": "cheapest", "cheapst": "cheapest", "paymnt": "payment", "payement": "payment", "depsoit": "deposit",
         "deposite": "deposit", "wher": "where", "wat": "what", "tmrw": "tomorrow", "pls": "please", "plz": "please", "u": "you", "ur": "your", "bils": "bills",
         "hostle": "hostel", "acommodation": "accommodation", "accomodation": "accommodation", "lanlord": "landlord", "landlrod": "landlord"}
_VOCAB: set[str] | None = None


def _vocab() -> set[str]:
    """Single Latin words of 6+ letters from the bill and info lexicons: the only words fuzzy snapping may land on."""
    global _VOCAB
    if _VOCAB is None:
        ws: set[str] = set()
        for _, words in list(L.BILLS.values()) + list(L.INFO.values()):
            for w in words:
                ws.update(x for x in re.findall(r"[a-z]+", w) if len(x) >= 6)
        _VOCAB = ws
    return _VOCAB


def clean(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = _ZW.sub("", t).replace("’", "'").replace("‘", "'").lower()
    t = "".join(ch if (ch.isprintable() or ch in "\n\t") else " " for ch in t)
    return _SPACE.sub(" ", t).strip()[:2000]


def snap(t: str) -> str:
    """Typo map, then edit-distance-1 snapping (2 for 9+ letters) of unknown 6+ letter words to a lexicon word."""
    voc = _vocab()
    out = []
    for w in t.split(" "):
        core = re.sub(r"^[^\w]+|[^\w]+$", "", w)
        low = _TYPO.get(core, core)
        if low != core:
            w = w.replace(core, low)
        elif len(core) >= 6 and core.isascii() and core.isalpha() and core not in voc:
            lim = 2 if len(core) >= 9 else 1
            best = [v for v in voc if abs(len(v) - len(core)) <= lim and not v.startswith(core) and not core.startswith(v) and L.edit1(core, v, lim)]
            if len(best) == 1:
                w = w.replace(core, best[0])
        out.append(w)
    return " ".join(out)


_NUM = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(k|l|lakhs?|lacs?|crores?|thousand|万)?(?![\w])", re.I)
_ZERO = re.compile(r"(?<![\w.])0+(?:\.0+)?\s*(?:yuan|cny|rmb|inr|rupees?|usd|dollars?|元|块)?(?![\w.]*[1-9])", re.I)
_ABOUT = re.compile(r"\b(?:about|around|approx(?:imately)?|roughly|ish|or so|nearly|almost)\b", re.I)
_NAME2 = re.compile(r"\b([A-Z][A-Za-z0-9.'-]*(?: [A-Z][A-Za-z0-9.'-]*){1,2})\b")


@dataclass
class Frame:
    text: str
    raw: str
    act: str = "other"                                  # question | command | need | fact | worry | other
    pay: bool = False
    bills: list[str] = field(default_factory=list)
    no_payee: list[str] = field(default_factory=list)
    info: dict[str, int] = field(default_factory=dict)
    info_q: bool = False                                         # starts like an information question (how, what, when ...): never a pay order
    info_len: dict[str, int] = field(default_factory=dict)       # words in the longest phrase that matched, per concept
    amounts: list[float] = field(default_factory=list)
    zero_amount: bool = False
    approx: bool = False
    currencies: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    reported: bool = False
    order: bool = False                                           # reads as an order or a stated need to pay (pay verb first, "I need to pay", Hinglish "bhej do", Chinese 交/付), not a mention
    addressed: bool = False
    nopay: bool = False
    convert: bool = False
    rate_target: bool = False
    revoke: bool = False
    wait_convert: bool = False
    names: list[str] = field(default_factory=list)
    clauses: list[str] = field(default_factory=list)

    @property
    def best_info(self) -> str | None:
        return max(self.info, key=lambda k: self.info[k]) if self.info else None


def _count(t: str, words) -> int:
    return len(L.phrase_rx(tuple(words)).findall(t))


def parse(text: str) -> Frame:
    raw = (text or "")[:2000]
    t = snap(clean(raw))
    f = Frame(text=t, raw=raw)
    f.reported = L.has(t, L.REPORTED_CUES)
    f.addressed = L.has(t, L.ADDRESSED_CUES)
    f.nopay = L.has(t, L.NOPAY)
    f.revoke = L.has(t, L.REVOKE)
    f.convert = L.has(t, L.CONVERT_VERBS) or bool(re.search(r"\b(?:buy|change|switch|get)\b.{0,25}\b(?:usd|eur|gbp|aud|cny|inr|dollars?|euros?|pounds?|yuan|rupees?)\b", t))
    f.rate_target = L.has(t, L.RATE_TARGET_WORDS)
    f.wait_convert = bool(re.search(r"\bwait (?:until|for|till)\b", t)) and f.convert
    pay_words = L.has(t, L.PAY_ACTIONS) or L.has(t, L.PAY_DESIRE)
    spec: dict[str, int] = {}
    for name, (_canon, words) in L.BILLS.items():
        hits = L.phrase_rx(tuple(words)).findall(t)
        if hits:
            spec[name] = max(len(h) for h in hits)
    f.bills = sorted(spec, key=lambda k: -spec[k])                 # the bill whose matched phrase is longest (the most specific) comes first
    for name, words in L.NO_PAYEE.items():
        if L.has(t, words):
            f.no_payee.append(name)
    for intent, (_canon, words) in L.INFO.items():
        hits = L.phrase_rx(tuple(words)).findall(t)
        if hits:
            f.info[intent] = len(hits)
            f.info_len[intent] = max((len(h.split()) if h.isascii() else max(len(h) // 2, 1)) for h in hits)
    pay_words = pay_words or bool(re.search(r"\b(?:get|have)\s+(?:my|the)\b.{1,40}\bpaid\b|\b(?:do|make|process|finish|complete)\s+(?:the|my)\b.{0,25}\bpayment\b", t))
    f.pay = bool(pay_words) and not L.has(t, ("pay attention",))
    f.order = f.pay and is_order(raw)
    for code, words in L.CURRENCIES.items():
        if L.has(t, words) and code not in f.currencies:
            f.currencies.append(code)
    for code, words in L.UNSUPPORTED_CURRENCIES.items():
        if L.has(t, words) and code not in f.unsupported:
            f.unsupported.append(code)
    for m in _NUM.finditer(t):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        mult = (m.group(2) or "").lower()
        v *= {"k": 1e3, "thousand": 1e3, "l": 1e5, "万": 1e4}.get(mult, 1e5 if mult.startswith(("lakh", "lac")) else 1e7 if mult.startswith("crore") else 1)
        f.amounts.append(v)
    f.zero_amount = bool(f.amounts) and all(a == 0 for a in f.amounts) or bool(re.search(r"\b(?:zero|nil)\b\s*(?:yuan|cny|rmb|inr|rupees?)?", t) and f.pay)
    f.approx = bool(_ABOUT.search(t)) and bool(f.amounts)
    f.names = [n for n in _NAME2.findall(raw)]
    f.clauses = [c.strip() for c in re.split(r"(?:\s+and then\s+|\s+then\s+|\s+and also\s+|\s+also\s+|\s+after that\s+|\s+afterwards\s+|\s+plus\s+|\s+as well as\s+|;|，|然后|并且)", t) if c.strip()][:4]
    starts_q = t.split(" ", 1)[0] in L.QUESTION_STARTS if t else False
    tq = snap(clean(core(raw))) or t                          # judged on the request itself, without openers like 'can you tell me,' or a rambling lead-in
    f.info_q = (tq.split(" ", 1)[0] in ("how", "what", "when", "where", "why", "which", "who", "is", "are", "does", "did", "will", "was", "has", "have", "had", "what's", "whats", "where's", "how's")
                or bool(re.match(r"(?:can|could|should|do|would|may|am|shall) (?:i|we|you|it|my)\b", tq))
                or bool(re.search(r"\b(?:what is|what's|how much|how many|when is|which)\b[^.]*[?？]\s*$", tq))
                or (bool(re.search(r"多少|吗|么|哪|几|没交|没付|有没有|是否|了没|计划|规划|确认|证明|凭证|回执|收据|进度|状态|完成|成功|[?？]", tq)) and not re.search(r"(?:可以|行|好|能)吗", tq))) if tq else False
    question = starts_q or t.endswith(("?", "？")) or L.has(t, L.QUESTION_CUES)
    if L.has(t, L.WORRY_CUES):
        f.act = "worry"
    elif L.has(t, L.NEED_CUES) and (f.pay or f.bills):
        f.act = "need"
    elif question:
        f.act = "question"
    elif L.has(t, L.FACT_CUES) and not f.pay:
        f.act = "fact"
    elif f.pay or t.split(" ", 1)[0] in ("please", "kindly", "pls", "just"):
        f.act = "command"
    return f


_ADDR_SPLIT = re.compile(r"[,;:]\s*")


def strip_reported(text: str) -> str:
    """The sentence without its 'he said' / 'my dad said' reporting frame (S1b): the narrated clause is routed as content."""
    t = clean(text)
    for cue in sorted(L.REPORTED_CUES, key=len, reverse=True):
        t = re.sub(rf"(?<![a-z]){re.escape(cue)}(?: that)?\b[, ]*", " ", t)
    return _SPACE.sub(" ", t).strip()


_SPLIT_RX = re.compile(r"(?:,?\s+and then\s+|,?\s+then\s+|,?\s+and also\s+|,?\s+also\s+|,?\s+after that\s+|,?\s+afterwards\s+|,?\s+plus\s+|\s+as well as\s+|\s*;\s*|然后|并且)", re.I)
_AND_RX = re.compile(r"\s+and\s+", re.I)


def split_clauses(message: str) -> list[str]:
    """Up to 4 clauses. ' and ' splits only when both sides carry their own request (a pay verb or an information target)."""
    out: list[str] = []
    for seg in _SPLIT_RX.split(message.strip()):
        pieces = _AND_RX.split(seg)
        if len(pieces) > 1:
            ok = all(_has_request(p) for p in pieces)
            out.extend(pieces if ok else [seg])
        else:
            out.append(seg)
    return [p.strip(" ,.") for p in out if p and p.strip(" ,.")][:4]


def _has_request(p: str) -> bool:
    f = parse(p)
    return bool(f.pay or f.info or f.revoke or f.convert)


_LEAD = re.compile(r"^(?:(?:hi|hey|hello|yo|so|ok so|ok|um+|just|please|pls|kindly|oasis|hey bot|bot|bhai|quick question|excuse me|can you|could you|would you mind|would you|i was wondering if you could|i'd like you to|i would like you to|help me|hi there|hello there|could you kindly help me|kindly help me|please help me|i need you to|i want you to|tell me)[,:!.\s-]+)+", re.I)
_TAIL = re.compile(r"(?:[,\s]+(?:please|pls|thanks a lot|thanks|thank you so much|thank you|asap|today|now|yaar|if possible|for this (?:semester|month|term)|this semester|this month))+[\s?.!]*$", re.I)
_RAMBLE = re.compile(r"^.{0,120}?\b(?:anyway|anyhow)\b[,\s]+", re.I)


def core(message: str) -> str:
    """The request without its social wrapping: leading openers and trailing closers removed. Used only to give the concept layer a second look."""
    t = _SPACE.sub(" ", unicodedata.normalize("NFKC", message or "")).strip()
    t = _RAMBLE.sub("", t)
    t = _LEAD.sub("", t)
    t = _TAIL.sub("", t)
    return t.strip(" ,.:;-*\"'") or message


_ORDER_VERBS = re.compile(r"^(?:pay|settle|clear|send|remit|wire|transfer|cover|handle|fund|sort|finish|process|do|make|get|take care of|deal with|top up|recharge|reload|push|release|proceed with|go ahead and)\b")
_DESIRE = re.compile(r"\b(?:i|we)(?:'d| would)? (?:need|want|have|must|should|like|got|gotta|wanna|ought)(?: to| 2)? (?:pay|settle|clear|send|remit|cover|get|handle|fund|top up)\b|\b(?:time|ready|going|about|let's|lets|help me|gotta|wanna) (?:to )?(?:pay|settle|clear)\b|\bit's time to pay\b|\bpay\b[^.?!]{0,30}\b(?:please|pls)\b")
_ORDER_TAIL = re.compile(r"\b(?:bhej(?:o| do| dena)|bharo|bhar do|chukao|chuka do|de do|dedo|pay karo|pay kar do|kar do)\b|交|缴|付|汇款|转账|充值|结清|还清|结算")


def is_order(message: str) -> bool:
    c = clean(core(message))
    if re.search(r"\bplan\b|记录|发给|给.{0,6}看|证明|计划|规划|确认|回执|收据", c):
        return False                                          # a request to send or show a record, a plan or a receipt, not an order to pay
    return bool(_ORDER_VERBS.match(c) or _DESIRE.search(c) or _ORDER_TAIL.search(c))
