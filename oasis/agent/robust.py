"""Robustness layers for wording the keyword router has not seen (offline, deterministic, pure Python, no dependencies).

Runs only AFTER the keyword router (`nlu.classify`, whose security checks come first and are unchanged) returned `unknown`, in this order:
  1. normalise   NFKC, lower-case, typo map, currency synonyms, number forms (50k, 1.5L, 5万, 五千, fifty thousand) -> digits
  2. slots       amounts, currencies, registry payee, bill type, date, question; a few slot rules (amount + two currencies + question = quote)
  3. similarity  char n-gram TF-IDF cosine against `intent_examples.TRAIN`; accepted only above a threshold tuned by leave-one-out on that train set
  4. clarify     otherwise the top candidates are offered as numbered options (chat.py keeps them in the awaiting state)

Safety: steps 2 and 3 can only pick ANSWER-ONLY intents (`ANSWER_ONLY`). They never create, approve, cancel or change a payment draft, never set a
rate target, and a "convert" or "cancel" guess is only ever a quote or a hint. A payment still needs the deterministic keyword match; the only
state-changing kinds that can come out of this module are those `nlu.classify` itself returns on the normalised text (step 1 re-runs it).
"""
from __future__ import annotations
import math
import os
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from . import nl_extract, nlu
from .nlu import ChatIntent

ANSWER_ONLY = ("obligations", "balance", "routes", "runway", "quota", "credit", "status", "transfer_issue", "fx_bill", "parent_request",
               "share_record", "help", "convert", "rate_target", "cancel", "explain", "rate", "spending", "proof", "plan")

# similarity thresholds, tuned by leave-one-out on intent_examples.TRAIN only (eval/router_tune.py)
ACCEPT = 0.17          # minimum score of the best intent (mean cosine of its 5 nearest examples)
MARGIN = 0.08          # the best intent must beat the runner-up by this much, else the message is ambiguous
FLOOR = 0.08           # an intent below this is not offered as an option


# Pairs the matcher (and the keyword rules) mix up. When the top two candidates are one of these pairs the message is never answered on a guess:
# both options are offered. Taken from the train-set errors (eval/router_tune.py --pairs) plus the pairs named in the brief.
CONFUSABLE = frozenset(frozenset(p) for p in (
    ("status", "transfer_issue"), ("status", "explain"), ("transfer_issue", "explain"), ("credit", "share_record"), ("credit", "proof"), ("proof", "share_record"),
    ("routes", "convert"), ("routes", "rate"), ("convert", "rate"), ("rate", "rate_target"), ("balance", "runway"), ("balance", "obligations"),
    ("balance", "spending"), ("obligations", "spending"), ("obligations", "status"), ("obligations", "plan"), ("runway", "plan"), ("parent_request", "plan"),
    ("credit", "help")))
CONFUSE_MARGIN = 9.0   # a confusable top-2 pair is always clarified when their gap is below this (9.0 = always)


def confusable(a: str, b: str) -> bool:
    return frozenset((a, b)) in CONFUSABLE


def enabled() -> bool:
    return os.environ.get("OASIS_ROUTER_ROBUST", "1").strip() != "0"


# ------------------------------------------------------------------ 1. normalisation
_TYPOS = {"tution": "tuition", "tuiton": "tuition", "tuision": "tuition", "tuitoin": "tuition", "recieve": "receive", "recieved": "received", "recive": "receive",
          "rnt": "rent", "rentt": "rent", "mony": "money", "moeny": "money", "cheepest": "cheapest", "cheapst": "cheapest", "blance": "balance", "balnce": "balance",
          "balence": "balance", "convrt": "convert", "cancl": "cancel", "cancle": "cancel", "cancell": "cancel", "paymnt": "payment", "payement": "payment",
          "wat": "what", "wen": "when", "hw": "how", "wher": "where", "u": "you", "ur": "your", "pls": "please", "plz": "please", "thru": "through",
          "abt": "about", "tmrw": "tomorrow", "rupes": "rupees", "rupess": "rupees", "yaun": "yuan", "yuaan": "yuan", "depsoit": "deposit", "deposite": "deposit",
          "fess": "fees", "bils": "bills", "paymnts": "payments", "transfr": "transfer", "tranfer": "transfer", "remitence": "remittance", "exchnge": "exchange",
          "arrvied": "arrived", "arived": "arrived", "recieving": "receiving", "wallt": "wallet", "walet": "wallet", "invoce": "invoice", "invioce": "invoice",
          "whats": "what is", "hows": "how is", "wheres": "where is", "dont": "do not", "cant": "can not", "isnt": "is not", "didnt": "did not", "wont": "will not"}
_CURRENCY = (("inr", r"₹|\brs\.?(?=\s*\d|\b)|\brupees?\b|\brupaye\b|\brupiya\b|卢比|印度卢比"), ("cny", r"¥|￥|\byuan\b|\brmb\b|\brenminbi\b|人民币|(?<=[\d万千百])\s*元|(?<=[成换])元|(?<=\d)\s*块"),
             ("usd", r"\$|\bdollars?\b|\bbucks\b|美元|美金"), ("eur", r"€|\beuros?\b|欧元"), ("gbp", r"£|\bpounds?\b|英镑"), ("aud", r"\baussie dollars?\b|澳元"))
_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
_BIG = {"hundred": 100, "thousand": 1000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000, "crore": 10_000_000, "crores": 10_000_000, "million": 1_000_000}
_WORDNUM = re.compile(r"\b(?:(?:a|an|" + "|".join(list(_UNITS) + list(_TENS)) + r")(?:[ -]+(?:and[ ]+)?)?)*(?:" + "|".join(_BIG) + r")\b"
                      r"(?:[ -]+(?:and[ ]+)?(?:(?:" + "|".join(list(_UNITS) + list(_TENS)) + r")[ -]*)+)?", re.I)
_ZH_RUN = re.compile(r"([零〇一二两三四五六七八九十百千万]{2,})(?=\s*(?:元|块|卢比|人民币|美元|欧元|rmb|inr|cny|usd))", re.I)


def _words_value(seq: str) -> int | None:
    total = cur = 0
    seen = False
    for w in re.split(r"[ -]+", seq.strip().lower()):
        if w in ("a", "an", "and", ""):
            cur = cur or (1 if w in ("a", "an") else 0)
        elif w in _UNITS:
            cur += _UNITS[w]
            seen = True
        elif w in _TENS:
            cur += _TENS[w]
            seen = True
        elif w == "hundred":
            cur = max(cur, 1) * 100
            seen = True
        elif w in _BIG:
            total += max(cur, 1) * _BIG[w]
            cur = 0
            seen = True
        else:
            return None
    return total + cur if seen else None


def _numbers(t: str) -> str:
    """'50k' '1.5L' '2 lakh' '5万' '五千元' 'fifty thousand' -> plain digits."""
    t = re.sub(r"\b\d{1,2}(?:,\d{2})+,\d{3}\b", lambda m: m.group(0).replace(",", ""), t)       # Indian grouping: 1,00,000
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?)\b", lambda m: f"{round(float(m.group(1)) * (10_000_000 if m.group(2)[0] == 'c' else 100_000))}", t)
    t = _WORDNUM.sub(lambda m: (lambda v: f" {v} " if v else m.group(0))(_words_value(m.group(0))), t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*(?:lakhs?|lacs?|l)\b", lambda m: f"{round(float(m.group(1)) * 100_000)}", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*(?:m|mn|million)\b", lambda m: f"{round(float(m.group(1)) * 1_000_000)}", t)
    t = re.sub(r"(?<![\w.])(\d+(?:\.\d+)?)\s*k\b", lambda m: f"{round(float(m.group(1)) * 1000)}", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*万", lambda m: f"{round(float(m.group(1)) * 10_000)}", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*千", lambda m: f"{round(float(m.group(1)) * 1000)}", t)
    return _ZH_RUN.sub(lambda m: f" {nl_extract.zh_numeral(m.group(1)) or m.group(1)} ".replace(".0 ", " "), t)


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").casefold()
    t = _numbers(t)
    for code, rx in _CURRENCY:
        t = re.sub(rx, f" {code} ", t, flags=re.I)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)
    t = re.sub(r"[^\w\s.一-鿿]", " ", t)
    words = [_TYPOS.get(w, w) for w in t.split()]
    return re.sub(r"\s+", " ", " ".join(words)).strip()


# ------------------------------------------------------------------ 2. slots and slot rules
_CUR = ("inr", "cny", "usd", "eur", "gbp", "aud")
_AMT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.]*\d)\s*(inr|cny|usd|eur|gbp|aud)?|(inr|cny|usd|eur|gbp|aud)\s*(\d+(?:\.\d+)?)")
_BILL = (("rent", r"\brent\b|房租|租金|kiraya"), ("tuition", r"\btuition\b|\bfees?\b|学费|学杂费"), ("deposit", r"\bdeposit\b|押金"),
         ("phone", r"\bphone\b|\bmobile\b|话费|手机费"), ("living", r"\bliving\b|生活费|\ballowance\b"))
_WH = re.compile(r"\b(?:what|which|when|where|why|how|who)\b|^(?:is|are|do|does|did|can|could|will|would|should|any)\b|[?？]|吗|什么|多少|哪|怎么|如何|为什么|能不能|是不是|有没有|是否|几")
_DATE = re.compile(r"\b(?:today|tomorrow|tonight|next (?:week|month)|this (?:week|month|term|semester)|by (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|\d{1,2}(?:st|nd|rd|th))\b|今天|明天|下周|下个月|这个月|本月|号")
_SHORT = re.compile(r"\b(?:less|short|smaller|lower|only (?:got|received|credited|part|some|half)|(?:got|received|credited|gets) only|not (?:the )?(?:full|all)|missing)\b|少收|少了|只收到|不够|差了|只到了")
_RECV = re.compile(r"\b(?:received|receive|got|get|gets|credited|arrived|arrive|reached|came|landed)\b|收到|到账|到了|入账")
_FOREIGN = re.compile(r"\b(?:usd|eur|gbp|aud)\b")
_BILLWORD = re.compile(r"\b(?:bills?|invoices?|fees?|charges?|tuition|rent|deposit|subscription|registration)\b|账单|发票|费用|学费|房租|押金")
_DUEWORD = re.compile(r"\b(?:due|owe|owed|owing|outstanding|pending|unpaid|overdue|left to pay|remaining|upcoming|coming up|deadline)\b|欠|待付|没付|没交|未付|未交|到期|逾期|截止")
_LASTWORD = re.compile(r"\b(?:last|lasts|enough|run out|running out|stretch|survive|cover|afford|sufficient|short before)\b|撑|够用|够不够|用完|花完|坚持")
_MONEYWORD = re.compile(r"\b(?:money|funds?|savings|cash|balance|budget)\b|钱|资金|存款|预算|生活费")
# a message with none of these words (and no currency) is chit-chat or noise: it never gets an options menu
_DOMAIN = re.compile(r"\b(?:bills?|pay\w*|paid|money|funds?|cash|rent|tuition|fees?|deposit|balance|wallet|account|transfers?|send|sent|remit\w*|convert\w*|exchange|rates?|inr|cny|usd|eur|gbp|yuan|rupees?|"
                     r"rmb|dollars?|euros?|invoices?|receipts?|proof|landlord|university|school|parents?|mom|dad|loan|credit|record|history|limit|quota|lrs|tcs|spend\w*|expenses?|budget|plan|"
                     r"routes?|cheap\w*|owe|due|draft|approve|sign\w*|cancel|refund|status|afford|broke|savings|semester|term)\b|钱|付|账单|汇|款|费|租|学费|余额|转账|兑|换|信用|额度|汇率|父母|爸妈|签|取消|退|预算|计划")
# an explicit request to make a draft / pay, in English, Hinglish or Chinese: similarity never overrides or replaces it with an answer
_MAKE = re.compile(r"\b(?:draft|prepare|prep|set up|bana do|banao|kar do|karo|de do|bhar\w*|dena|dedo|top ?up|recharge)\b|草稿|起草|准备|办理|处理|帮我(?:付|交|缴)")
_PAYIMP = re.compile(r"\b(?:pay|send|transfer|wire|settle)\b|^(?:请|帮我)?(?:付|交|缴|转)")


@dataclass
class Slots:
    amounts: list = field(default_factory=list)       # [(value, currency or None)]
    currencies: list = field(default_factory=list)    # in order, no repeats
    bill: str | None = None
    payee: str | None = None
    date: str | None = None
    question: bool = False


def extract(text: str, norm: str | None = None, payees=()) -> Slots:
    n = norm if norm is not None else normalise(text)
    s = Slots()
    for m in _AMT.finditer(n):
        v, c = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        if len(v.split(".")[0]) <= 9 and float(v) > 0:         # 10+ digits is an account number, not an amount
            s.amounts.append((float(v), c))
    s.currencies = list(dict.fromkeys(re.findall(r"\b(inr|cny|usd|eur|gbp|aud)\b", n)))
    s.bill = next((k for k, rx in _BILL if re.search(rx, n)), None)
    r = nl_extract.registry_payee(text or "", payees) if payees else None
    s.payee = r.id if r else None
    d = _DATE.search(n)
    s.date = d.group(0) if d else None
    s.question = bool(_WH.search(n) or "?" in (text or "") or "？" in (text or ""))
    return s


def rules(n: str, s: Slots) -> list[tuple[str, dict, float]]:
    """Slot-based inference: (label, slots, score). Answer-only labels only."""
    out = []
    amt = next((a for a in s.amounts if a[1] in (None, "inr", "cny")), None) or (s.amounts[0] if s.amounts else None)
    if amt and len(s.currencies) >= 2 and s.question and not _PAYIMP.search(n):
        out.append(("routes", {"amount": amt[0], "currency": (amt[1] or s.currencies[0]).upper(), "quote": True}, 0.9))
    if _SHORT.search(n) and _RECV.search(n) and (s.amounts or s.payee or re.search(r"\b(?:university|landlord|school|college|payee|they|he|she)\b|学校|房东|对方", n)):
        out.append(("transfer_issue", {"wording": n}, 0.9))
    if _FOREIGN.search(n) and _BILLWORD.search(n):
        out.append(("fx_bill", {"wording": n, "pay_in": bool(_PAYIMP.search(n) and s.bill)}, 0.88))
    if s.bill and _DUEWORD.search(n) and s.question and not _PAYIMP.search(n) and not s.amounts:
        out.append(("obligations", {}, 0.86))
    if _LASTWORD.search(n) and _MONEYWORD.search(n) and s.question and not _PAYIMP.search(n):
        out.append(("runway", {}, 0.84))
    return out


# ------------------------------------------------------------------ 3. similarity (char n-gram TF-IDF, cosine)
def _shape(n: str) -> str:
    return re.sub(r"\d+(?:\.\d+)?", "0", n)


def _grams(s: str) -> dict[str, int]:
    s = f" {s} "
    g: dict[str, int] = defaultdict(int)
    for k in (1, 2, 3):
        for i in range(len(s) - k + 1):
            g[s[i:i + k]] += 1
    return g


class Index:
    def __init__(self, examples: dict[str, list[str]]):
        self.docs: list[tuple[str, dict[str, float]]] = []
        raw = [(lab, _grams(_shape(normalise(t)))) for lab, ts in examples.items() for t in ts]
        seen: dict[str, set] = defaultdict(set)         # class-level idf: an n-gram that occurs in few intents is a strong cue (tuned on the train set)
        for lab, g in raw:
            for k in g:
                seen[k].add(lab)
        n = len(examples)
        self.idf = {k: math.log(n / len(v)) + 1 for k, v in seen.items()}
        self.post: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for i, (lab, g) in enumerate(raw):
            v = self._vec(g)
            self.docs.append((lab, v))
            for k, w in v.items():
                self.post[k].append((i, w))

    def _vec(self, g: dict[str, int]) -> dict[str, float]:
        v = {k: (1 + math.log(c)) * self.idf[k] for k, c in g.items() if k in self.idf}
        z = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {k: x / z for k, x in v.items()}

    def scores(self, text: str, skip: int | None = None) -> list[tuple[str, float]]:
        """Per intent: the mean cosine of its 5 nearest examples, highest first."""
        q = self._vec(_grams(_shape(normalise(text))))
        acc: dict[int, float] = defaultdict(float)
        for k, w in q.items():
            for i, x in self.post.get(k, ()):
                acc[i] += w * x
        best: dict[str, list[float]] = defaultdict(list)
        for i, c in acc.items():
            if i != skip:
                best[self.docs[i][0]].append(c)
        out = []
        for lab, cs in best.items():
            cs.sort(reverse=True)
            out.append((lab, sum(cs[:5]) / 5))
        return sorted(out, key=lambda x: -x[1])


_INDEX: Index | None = None


def index() -> Index:
    global _INDEX
    if _INDEX is None:
        from .intent_examples import TRAIN
        _INDEX = Index(TRAIN)
    return _INDEX


def similar(text: str) -> list[tuple[str, float]]:
    return index().scores(text)


def decide(ranked: list[tuple[str, float]], accept: float | None = None, margin: float | None = None) -> str | None:
    accept, margin = ACCEPT if accept is None else accept, MARGIN if margin is None else margin
    if not ranked or ranked[0][1] < accept:
        return None
    if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < margin:
        return None
    if len(ranked) > 1 and confusable(ranked[0][0], ranked[1][0]) and ranked[0][1] - ranked[1][1] < CONFUSE_MARGIN:
        return None                                              # a confusable pair: ask, do not guess
    return ranked[0][0]


# ------------------------------------------------------------------ labels -> ChatIntent (answer-only)
def to_intent(label: str, text: str, norm: str, s: Slots, ui: str, extra: dict | None = None, confidence: float = 0.6) -> ChatIntent:
    lang = nlu.detect_lang(text, ui)
    a = next((x for x in s.amounts if x[1] in (None, "inr", "cny")), None)
    sl: dict = dict(extra or {})
    if label == "routes":
        sl.setdefault("amount", a[0] if a else None)
        sl.setdefault("currency", ((a[1] or "inr").upper()) if a else None)
        if a and len(s.currencies) >= 2:
            sl.setdefault("quote", True)
        return ChatIntent(nlu.ROUTES, sl, confidence, lang)
    if label == "convert":
        sl.update({"amount": a[0] if a else None, "currency": ((a[1] or "inr").upper()) if a else None, "quote_only": True})
        return ChatIntent(nlu.CONVERT, sl, confidence, lang)
    if label == "rate_target":
        return ChatIntent(nlu.RATE_TARGET, {"incomplete": True, "rate": None}, confidence, lang)      # instructions only: no target is ever set from a guess
    if label == "cancel":
        return ChatIntent(nlu.HELP, {"cancel_hint": True}, confidence, lang)                           # a hint, never a cancel
    if label == "credit":
        sl["growth"] = bool(nlu._CREDIT_GROWTH.search(norm))
        return ChatIntent(nlu.CREDIT, sl, confidence, lang)
    if label in ("transfer_issue", "fx_bill", "parent_request"):
        sl.setdefault("wording", norm)
        if label == "fx_bill":
            sl.setdefault("pay_in", bool(_PAYIMP.search(norm) and s.bill))
        return ChatIntent(label, sl, confidence, lang)
    return ChatIntent(label, sl, confidence, lang)


def label_of(it: ChatIntent) -> str:
    """The intent label of a ChatIntent, as used by the example sets."""
    if it.kind == nlu.HELP and it.slots.get("cancel_hint"):
        return "cancel"
    if it.kind == nlu.CANCEL:
        return "cancel"
    return it.kind


@dataclass
class Result:
    status: str                                   # "intent" | "clarify" | "none"
    intent: ChatIntent | None = None
    source: str = ""                              # "normalised" | "slots" | "similarity"
    confidence: float = 0.0
    candidates: list = field(default_factory=list)   # [(label, score, ChatIntent)] best first, answer-only


def resolve(text: str, ui: str = "en", payees=()) -> Result:
    """Layers 1 to 4 for a message the keyword router left `unknown`."""
    norm = normalise(text)
    if not norm:
        return Result("none")
    if norm != nlu.normalise(text):                     # layer 1 may have fixed typos, numbers or currencies: give the deterministic router another go
        it = nlu.classify(norm, ui)
        if it.kind != nlu.UNKNOWN and it.kind not in nlu.REFUSALS:       # a refusal is decided on the raw text only: stripping quotes must never create one
            return Result("intent", it, "normalised", it.confidence)
    s = extract(text, norm, payees)
    cands: list[tuple[str, float, ChatIntent]] = []
    hits = rules(norm, s)
    if hits:
        lab, sl, sc = hits[0]
        return Result("intent", to_intent(lab, text, norm, s, ui, sl, sc), "slots", sc)
    if _MAKE.search(norm) and not s.question:                  # a payment-like order the keyword router could not place: ask (chat's own reply), never answer a guess
        return Result("none", None, "slots")
    ranked = similar(text)
    if ranked and ranked[0][0] == "other":                  # chit-chat or nonsense: no intent, no menu (the chat layer's own "I didn't catch that" answers)
        return Result("none", None, "similarity", ranked[0][1])
    top = decide(ranked)
    if top == "other":
        return Result("none", None, "similarity", ranked[0][1])
    if top:
        sc = dict(ranked)[top]
        return Result("intent", to_intent(top, text, norm, s, ui, None, sc), "similarity", sc)
    pool = ranked[:2] if len(ranked) > 1 and confusable(ranked[0][0], ranked[1][0]) else ranked[:3]       # a confusable pair is offered as exactly those two
    for lab, sc in pool:
        if sc >= FLOOR and lab not in ("cancel", "other") and (_DOMAIN.search(norm) or s.currencies):
            cands.append((lab, sc, to_intent(lab, text, norm, s, ui, None, sc)))
    return Result("clarify" if cands else "none", None, "similarity", ranked[0][1] if ranked else 0.0, cands)


# kinds the similarity/slot evidence may overturn: only the two payment-ish labels the keyword rules guess from a few words. Keyword answers stand.
# The override target is always an answer-only intent, so this can only turn a payment-ish guess into an answer, never the reverse.
_CONTEST = (nlu.PAY_OBLIGATION, nlu.CORRECT)
_WANT_PAY = re.compile(r"\bi(?:'d| would)? (?:need|want|have|like) to pay\b|\blet'?s pay\b|\bi (?:need|want) (?:to )?(?:send|settle)\b")
ARB_ACCEPT = 9.0       # to put a keyword ANSWER in doubt (offer both options). 9.0 = off: lowering it cuts wrong answers but breaks deterministic behaviour pinned by tests (see docs/router-changes.md)
ARB_MARGIN = 0.12
PAY_ACCEPT = 0.17      # to turn a payment-ish keyword guess (no explicit "pay ...") into an answer: that direction is the safe one, so the bar is lower
PAY_MARGIN = 0.08


def arbitrate(text: str, ui: str, payees, kw: ChatIntent) -> Result | None:
    """A keyword result that confident evidence disagrees with: a Result holding an answer-only intent, or a clarification, or None (the keyword result stands).
    A question without an explicit "pay ..." is never turned into a payment draft: the best answer-only intent is used, else the candidates are offered."""
    if kw.slots.get("labelled"):
        return None
    if kw.kind not in _CONTEST:
        return _doubt(text, ui, payees, kw)
    norm = normalise(text)
    if kw.kind == nlu.CORRECT and (kw.slots.get("amount") or kw.slots.get("wants_account")):
        return None                                     # "make it 2600" next to a draft is a real correction
    asks = text.strip().endswith(("?", "？")) and not nlu._PAY_CUE.search(norm)          # "tuition still owing?": a bare bill name that ends in a question mark
    if kw.kind == nlu.PAY_OBLIGATION and ((kw.confidence < 0.8 and not asks) or nlu._PAY_IMPERATIVE.search(norm) or nlu._PAY_IMPERATIVE.search(nlu.normalise(text)) or nlu._PAY_IMPERATIVE.search(nlu.fix_typos(nlu.strip_filler(nlu.normalise(text)))) or nlu._HINGLISH_PAY.search(norm) or _MAKE.search(norm) or _WANT_PAY.search(norm)):
        return None                                     # an explicit "pay ..." request, or a bare bill name ("phone bill pls", "do the usual payment"), stays as the router read it
    s = extract(text, norm, payees)
    mine = label_of(kw)
    hits = rules(norm, s)
    if hits:
        lab, sl, sc = hits[0]
        return Result("intent", to_intent(lab, text, norm, s, ui, sl, sc), "arbitrated", sc) if lab != mine else None
    ranked = similar(text)
    if (kw.kind == nlu.PAY_OBLIGATION and ranked and ranked[0][0] == "other" and ranked[0][1] >= FLOOR
            and not s.bill and not s.amounts and not s.payee and not _DOMAIN.search(norm)):
        return Result("none", None, "arbitrated", ranked[0][1])        # "play some music" read as "pay": chit-chat is not a payment request
    soft = kw.kind in (nlu.PAY_OBLIGATION, nlu.CORRECT)
    top = decide(ranked, PAY_ACCEPT if soft else ARB_ACCEPT, PAY_MARGIN if soft else ARB_MARGIN)
    if top and top != mine and top not in ("cancel", "other"):
        sc = dict(ranked)[top]
        return Result("intent", to_intent(top, text, norm, s, ui, None, sc), "arbitrated", sc)
    if kw.kind == nlu.PAY_OBLIGATION and s.question and not s.amounts and not s.payee and not kw.slots.get("amount") and not kw.slots.get("fraction"):   # a question is not a payment request
        top = decide(ranked, 0.05, 0.0)
        if top and top not in ("cancel", "other"):
            sc = dict(ranked)[top]
            return Result("intent", to_intent(top, text, norm, s, ui, None, sc), "arbitrated", sc)
        cands = [(lab, sc, to_intent(lab, text, norm, s, ui, None, sc)) for lab, sc in ranked[:3] if sc >= FLOOR and lab not in ("cancel", "other")]
        if cands:
            return Result("clarify", None, "arbitrated", ranked[0][1], cands)
    return None


def _doubt(text: str, ui: str, payees, kw: ChatIntent) -> Result | None:
    """A keyword ANSWER the similarity evidence disagrees with: offer both as numbered options instead of trusting either. The keyword answer stands
    when the evidence is weak, and an explicit keyword parse (a rate target with numbers, a cancel, a refusal) is never second-guessed."""
    mine = label_of(kw)
    if mine not in ANSWER_ONLY or mine == "cancel" or (kw.kind == nlu.RATE_TARGET and not kw.slots.get("incomplete")) or (kw.kind == nlu.HELP and kw.slots):
        return None
    if kw.kind in nlu.TOPIC_KINDS or kw.kind in (nlu.CONVERT, nlu.RATE):
        return None                                     # specific keyword rules (transfer issue, foreign bill, parent request, quota, share record, convert, rate): they stand
    norm = normalise(text)
    ranked = [r for r in similar(text) if r[0] != "other"]
    if not ranked or ranked[0][0] == mine or ranked[0][1] < ARB_ACCEPT:
        return None
    top = ranked[0][0]
    if not (confusable(mine, top) or (len(ranked) < 2 or ranked[0][1] - ranked[1][1] >= ARB_MARGIN)):
        return None
    s = extract(text, norm, payees)
    return Result("clarify", None, "arbitrated", ranked[0][1],
                  [(mine, 0.6, kw), (top, ranked[0][1], to_intent(top, text, norm, s, ui, None, ranked[0][1]))])


def route(text: str, ui: str = "en", payees=()) -> tuple[str, str, float]:
    """(label, source, confidence) the whole offline router gives a message: keyword router, then layers 1 to 4. Label 'clarify' or 'unknown' when none."""
    it = nlu.classify(text, ui)
    if not enabled():
        return label_of(it), "router", it.confidence
    if it.kind != nlu.UNKNOWN:
        alt = arbitrate(text, ui, payees, it)
        if alt is not None:
            return {"intent": label_of(alt.intent) if alt.intent else "", "clarify": "clarify", "none": "unknown"}[alt.status], "arbitrated", alt.confidence
        return label_of(it), "router", it.confidence
    r = resolve(text, ui, payees)
    if r.status == "intent":
        return label_of(r.intent), r.source, r.confidence
    return ("clarify" if r.status == "clarify" else "unknown"), r.source or "router", r.confidence
