"""Deterministic, offline warning-sign features for the trained risk model (see riskscorerimp.md).

Four groups, each aimed at an attack category the hand-set rules missed out of sample: amount (inflated_amount), payee similarity
(lookalike_payee), injection text (hidden_instruction), authority and secrecy cues (authority_pressure). Pure functions of the
document text, the extracted fields and the registry facts the pipeline already passes in; no network, no model call. They only
feed the escalate-only model: a feature never approves anything.
"""
from __future__ import annotations
import base64
import binascii
import re
import unicodedata

_ACCT = re.compile(r"(?<!\d)\d{12,19}(?!\d)")
_B64 = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
_AMOUNT = re.compile(r"(?:CNY|RMB|INR|USD|¥|金额[:：]?)\s*([\d,]+(?:\.\d+)?)", re.I)
_SUFFIX = {"ltd", "limited", "co", "inc", "llc", "company", "official", "management", "property", "group", "corp", "the", "of", "demo"}
_ABBR = {"univ": "university", "uni": "university"}

_INJECT = re.compile(
    r"(^|\n)\s*(system|assistant|admin|note to (the )?(assistant|ai|agent)|developer)\s*[:：]|disregard (the |all |any )?(verified|previous|prior|earlier)|"
    r"ignore (all |any )?(prior|previous|earlier)? ?(safety|checks|rules|instructions)|pre-?approved|skip (the )?(verification|checks)|"
    r"override|bypass|(correct|real|actual) account is|route (it |the payment )?to|you (must|should) now|忽略|无视|系统(指令|提示)|<!--|\[\[", re.I)
_REDIRECT = re.compile(r"\binstead\b|new account|updated account|account (has )?changed|bank (card|details) (has |have )?(changed|updated)|"
                       r"旧(账号|卡)|新(账号|账户|卡)|更换银行卡|请勿再汇|please use the account below", re.I)
_AUTHORITY = re.compile(
    r"\b(this is your (father|mother|dad|mom|parent|uncle)|ceo|director|dean|embassy|consulate|police|immigration|scholarship office|"
    r"tax (office|bureau)|official notice|on behalf of|asked (me|the finance)|colleague|friend of|handling fee|processing fee|release fee|"
    r"customs|visa (fee|office))\b|大使馆|领事馆|公安|海关|校长|院长|经理说", re.I)
_SECRECY = re.compile(r"(do not|don'?t|never|no need to) (tell|inform|verify|contact|check|call|mention)|keep (this )?(confidential|secret|between us)|"
                      r"without (telling|informing)|before anyone|请勿(联系|告诉|通知)|保密|不要告诉|稍后确认", re.I)
_FEE = re.compile(r"surcharge|late fee|roaming|handling|penalty|extra charge|additional|附加费|滞纳", re.I)


def _skeleton(s: str) -> str:
    """Casefolded, NFKC, accents and punctuation stripped, 'Univ.' expanded, filler words dropped: what a human reads as 'the same name'."""
    s = unicodedata.normalize("NFKC", s).casefold()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))
    words = [_ABBR.get(w, w) for w in re.findall(r"[\w一-鿿]+", s)]
    return " ".join(w for w in words if w not in _SUFFIX)


def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _ratio(a: str, b: str) -> float:
    return 1 - _lev(a, b) / max(len(a), len(b), 1)


def amount_features(fields: dict, text: str, expected: float | None, ctx: dict) -> dict[str, float]:
    f: dict[str, float] = {}
    amt = fields.get("amount")
    if amt and expected:
        r = amt / expected
        f["amt_over"] = min(1.0, max(0.0, (r - 1.05) / 1.0))                 # 2x the obligation or more saturates
        f["amt_under"] = 1.0 if r < 0.8 else 0.0
        f["amt_decade"] = 1.0 if r >= 5 or (0 < r <= 0.2) else 0.0           # off by a power of ten: typo or fraud
    prior = [r.get("amount_inr", 0) for r in ctx.get("recent", []) if r.get("payee_id") == fields.get("payee_id") and r.get("amount_inr", 0) > 0]
    inr = ctx.get("amount_inr")
    if inr and len(prior) >= 2:
        mu = sum(prior) / len(prior)
        sd = (sum((p - mu) ** 2 for p in prior) / len(prior)) ** 0.5 or mu * 0.1 or 1.0
        f["amt_z"] = max(0.0, min(1.0, ((inr - mu) / sd - 2) / 4))
    if amt and amt >= 1000 and amt % 10000 == 0 and expected and amt != expected:
        f["amt_round_off"] = 1.0
    if any(re.fullmatch(r"\d{1,3}(,\d{1,3})*,\d{2}", m) for m in re.findall(r"(?<![\d,])\d{1,3}(?:,\d{1,3})*,\d{1,2}(?![\d,])", text)):
        f["amt_malformed"] = 1.0                                              # '300,00': thousands separators in the wrong place
    if _FEE.search(text) and expected and amt and amt != expected:
        f["amt_fee_words"] = 1.0
    return f


def payee_features(fields: dict, known_names: list[str]) -> dict[str, float]:
    name = fields.get("payee_name") or ""
    if not name or not known_names:
        return {}
    sk = _skeleton(name)
    best, kind = 0.0, 0.0
    for k in known_names:
        if name == k:
            return {}
        ks = _skeleton(k)
        if not ks or not sk:
            continue
        r = _ratio(sk, ks)
        toks, kt = set(sk.split()), set(ks.split())
        overlap = len(toks & kt) / max(1, len(toks | kt))
        sub = 1.0 if (sk in ks or ks in sk) and min(len(sk), len(ks)) >= 2 else 0.0
        cjk = bool(re.search(r"[一-鿿]", name)) and r >= 0.5 and sk != ks      # one changed character in a short Chinese name
        s = max(r if r >= 0.75 else 0.0, overlap if overlap >= 0.5 else 0.0, 0.85 * sub, 0.9 if cjk else 0.0)
        if s > best:
            best, kind = s, (1.0 if sk == ks else 0.0)
    if best <= 0:
        return {}
    f = {"pay_near": best}
    if kind:
        f["pay_same_skeleton"] = 1.0                                          # differs only by case, accents, filler words or abbreviation
    return f


def injection_features(text: str) -> dict[str, float]:
    f: dict[str, float] = {}
    if _INJECT.search(text):
        f["inj_lexicon"] = 1.0
    for m in _B64.findall(text):
        try:
            dec = base64.b64decode(m + "=" * (-len(m) % 4), validate=True).decode("ascii")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if dec.isprintable() and re.search(r"[a-z]{3}", dec, re.I):
            f["inj_base64"] = 1.0
            break
    if _REDIRECT.search(text):
        f["inj_redirect"] = 1.0
    return f


def authority_features(text: str) -> dict[str, float]:
    f: dict[str, float] = {}
    if _AUTHORITY.search(text):
        f["auth_cue"] = 1.0
    if _SECRECY.search(text):
        f["auth_secrecy"] = 1.0
    return f


def account_features(fields: dict, text: str, known_accounts: dict[str, str], ctx: dict) -> dict[str, float]:
    """Account numbers in the text that no registry or history entry vouches for (a payee asked to be paid somewhere unknown)."""
    vouched = set(known_accounts.values())
    if ctx.get("registry_account"):
        vouched.add(ctx["registry_account"])
    found = {re.sub(r"\D", "", m) for m in _ACCT.findall(text)}
    unknown = {a for a in found if a not in vouched}
    f: dict[str, float] = {}
    if unknown:
        f["acct_unvouched"] = min(1.0, len(unknown) / 2)
    if len(found) >= 2:
        f["acct_multiple"] = 1.0
    return f


def extra_features(fields: dict, text: str, known_names: list[str], known_accounts: dict[str, str], expected: float | None, ctx: dict) -> dict[str, float]:
    f: dict[str, float] = {}
    for part in (amount_features(fields, text, expected, ctx), payee_features(fields, known_names), injection_features(text),
                 authority_features(text), account_features(fields, text, known_accounts, ctx)):
        f.update(part)
    return f
