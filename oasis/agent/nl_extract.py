"""Free-text extraction: amount, payee, account and purpose from a sentence instead of `Label:` lines.

This only fills fields the labelled parse left empty (see `OasisAgent.handle`). It is data extraction, not authority: the
result is as untrusted as the regex parse, the payee is matched against the registry's names EXACTLY (a look-alike never
resolves), and an account found in text is only ever compared with the registry, never used as a destination.
Anything ambiguous returns nothing so the student is asked rather than a guess being paid.
"""
from __future__ import annotations
import re
import unicodedata

from .llm import normalize_account, normalize_currency, parse_amount

_CUR = r"CNY|RMB|INR|USD|EUR|GBP|JPY|HKD|AUD|CAD|SGD"
_SYM = "¥￥$＄€£₹"
_NUM = r"\d[\d,，]*(?:\.\d+)?"
_UNIT_WORDS = r"yuan|rupees?|rs\.?|块|元|卢比|人民币"
_MULT = {"k": 1_000, "K": 1_000, "万": 10_000, "千": 1_000}

_PRE = re.compile(rf"(?P<cur>\b(?:{_CUR})\b|[{_SYM}]|人民币)\s*(?P<num>{_NUM})(?P<mult>\s*[kK万])?(?![\d.]*\s*(?:lakh|lac)\b)", re.I)
_POST = re.compile(rf"(?P<num>{_NUM})(?P<mult>\s*[kK万])?\s*(?P<cur>\b(?:{_CUR})\b|{_UNIT_WORDS})", re.I)
_LAKH = re.compile(rf"(?P<num>\d+(?:\.\d+)?)\s*(?:lakh|lac)s?\b", re.I)
_ACCT_RUN = re.compile(r"\d[\d ]{9,}\d")        # 11+ digits (account / card numbers) must never be read as money
_ACCT_LABELLED = re.compile(r"(?:account|acct|a/c|账号|账户|卡号)(?:\s*(?:no\.?|number|#))?\s*[:：]?\s*(\d[\d -]{5,}\d)", re.I)
_ACCT_BARE = re.compile(r"(?<![\d.])(\d{12,24})(?![\d])")

_ZH_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_ZH_UNIT = {"十": 10, "百": 100, "千": 1000}
_ZH_AMOUNT = re.compile(r"([零〇一二两三四五六七八九十百千万]+)\s*(?:元|块|人民币|rmb|cny)", re.I)


def zh_numeral(s: str) -> float | None:
    """'六千' -> 6000, '一万二千' -> 12000, '两千五百' -> 2500. None if it is not a plain Chinese numeral."""
    if not s or s[0] == "万" or any(c not in _ZH_DIGIT and c not in _ZH_UNIT and c != "万" for c in s):
        return None
    total, section, num = 0, 0, 0
    for c in s:
        if c in _ZH_DIGIT:
            num = _ZH_DIGIT[c]
        elif c in _ZH_UNIT:
            section += (num or 1) * _ZH_UNIT[c]
            num = 0
        else:                                   # 万
            total += (section + num or 1) * 10_000
            section = num = 0
    return float(total + section + num)


def _clean(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    return "".join(c for c in t if unicodedata.category(c) != "Cf")


def _number(num: str, mult: str | None) -> float | None:
    try:
        v = parse_amount(num)
    except ValueError:
        return None
    return v * _MULT[mult.strip()] if mult and mult.strip() in _MULT else v


def _cur(word: str) -> str:
    w = word.lower().rstrip(".")
    if w in ("yuan", "块", "元", "人民币"):
        return "CNY"
    if w in ("rs", "rupee", "rupees", "卢比"):
        return "INR"
    return normalize_currency(word) or "CNY"


_EXPONENT = re.compile(r"\d[eE][+-]?\d")
_BARE_AFTER_VERB = re.compile(rf"\b(?:pay|send|transfer|remit|wire)\s+(?:me\s+)?(?:a\s+)?({_NUM})\b(?!\s*(?:%|days?|months?))", re.I)


def money(text: str, bare: bool = False) -> tuple[float, str] | None:
    """The one amount the sentence states, as (value, currency). None when there is none, or when the sentence states
    two different amounts (the student is asked instead of a guess being paid). With `bare`, a number straight after
    'pay/send/transfer' counts as CNY (used only to describe a refused chat transfer, never to fill a payment)."""
    t = _ACCT_RUN.sub(" ", _clean(text))
    if _EXPONENT.search(t):
        return None                      # '1e5' is not read as 5 or 100000: the student is asked
    found: set[tuple[float, str]] = set()
    for rx in (_PRE, _POST):
        for m in rx.finditer(t):
            v = _number(m["num"], m["mult"])
            if v and v > 0:
                found.add((round(v, 2), _cur(m["cur"])))
    for m in _LAKH.finditer(t):
        found.add((round(float(m["num"]) * 100_000, 2), "INR"))
    for m in _ZH_AMOUNT.finditer(t):
        v = zh_numeral(m.group(1))
        if v:
            found.add((round(v, 2), "CNY"))
    for m in re.finditer(rf"({_NUM})\s*万", t):             # '3万元' / '1.5万'
        v = _number(m.group(1), "万")
        if v:
            found.add((round(v, 2), "CNY"))
    if not found and bare:
        m = _BARE_AFTER_VERB.search(t)
        v = _number(m.group(1), None) if m else None
        if v and v > 0:
            found.add((round(v, 2), "CNY"))
    return next(iter(found)) if len(found) == 1 else None


def account_in_text(text: str) -> str | None:
    """The one account number the text mentions, normalised. Two different numbers (an invoice with an 'old' and a 'new'
    account, say) give None: which one is meant is never guessed, the student is asked."""
    t = _clean(text)
    found = {normalize_account(m.group(1)) for m in _ACCT_LABELLED.finditer(t)}
    found |= {normalize_account(m.group(1)) for m in _ACCT_BARE.finditer(t)}
    found.discard("")
    return next(iter(found)) if len(found) == 1 else None


_PURPOSE_WORDS = (
    ("deposit", re.compile(r"deposit|押金|保证金|定金", re.I)),
    ("tuition", re.compile(r"tuition|学费|学杂费", re.I)),
    ("rent", re.compile(r"\brent\b|房租|租金|月租", re.I)),
)
_TYPE_PURPOSE = {"university": "tuition", "landlord": "rent"}
_NOT_NAME = r"(?!(?i:my|the|rent|tuition|deposit|fees?|now|it|this|that|me|us|CNY|RMB|INR|USD|EUR|GBP|JPY|HKD|AUD|CAD|SGD|Account)\b)"
_NAME = r"([A-Z][\w.'-]*(?:\s+(?:of\s+)?[A-Z][\w.'-]*){0,5})"
_NAME_AFTER_VERB = re.compile(rf"(?:pay|send|transfer|remit|wire)\s+(?:the\s+|my\s+)?{_NOT_NAME}{_NAME}")
_NAME_AFTER_TO = re.compile(rf"\bto\s+(?:the\s+)?{_NOT_NAME}{_NAME}")


def purpose_in_text(text: str) -> str | None:
    t = _clean(text)
    for canon, rx in _PURPOSE_WORDS:
        if rx.search(t):
            return canon
    return None


def registry_payee(text: str, recipients) -> object | None:
    """The registry recipient whose full name appears in the text (case-insensitive, whole words). Exact only."""
    low = _clean(text).casefold()
    best = None
    for r in recipients:
        n = r.name.casefold()
        if n and re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", low) and (best is None or len(n) > len(best.name)):
            best = r
    return best


def unregistered_payee_name(text: str) -> str | None:
    """A capitalised name written after 'pay/send ... to' (for an unknown payee, so the pipeline can reject it by name)."""
    t = _clean(text)
    for rx in (_NAME_AFTER_TO, _NAME_AFTER_VERB):
        m = rx.search(t)
        if m:
            name = re.sub(r"\s+(?:CNY|RMB|INR|USD)\b.*$", "", m.group(1)).strip()
            if name and not name.isdigit():
                return name
    return None


def fill_missing(fields: dict, text: str, recipients) -> list[str]:
    """Fill ONLY the fields that are absent from `fields`, in place. Returns the names of the fields it filled."""
    filled: list[str] = []
    rec = None
    if not fields.get("payee_name") and not fields.get("payee_id"):
        rec = registry_payee(text, recipients)
        name = rec.name if rec else unregistered_payee_name(text)
        if name:
            fields["payee_name"] = name
            filled.append("payee_name")
    else:
        pid, nm = fields.get("payee_id"), (fields.get("payee_name") or "").casefold()
        rec = next((r for r in recipients if (pid and r.id == pid) or (nm and r.name.casefold() == nm)), None)
    if fields.get("amount") is None:
        m = money(text)
        if m:
            fields["amount"] = m[0]
            if not fields.get("currency") or fields["currency"] == "CNY":
                fields["currency"] = m[1]
            filled.append("amount")
    if not fields.get("account_ref"):
        a = account_in_text(text)
        if a:
            fields["account_ref"] = a
            filled.append("account_ref")
    if not fields.get("purpose"):
        p = purpose_in_text(text) or (_TYPE_PURPOSE.get(rec.payee_type) if rec else None)
        if p:
            fields["purpose"] = p
            filled.append("purpose")
    return filled


def type_hint(text: str) -> str | None:
    """A bill type implied by a generic word when the sentence names none ('the university' means tuition, 'the landlord' means rent)."""
    t = _clean(text).casefold()
    if re.search(r"universit|college|school|学校|大学", t):
        return "tuition"
    if re.search(r"landlord|\blease\b|房东|租", t):
        return "rent"
    return None
