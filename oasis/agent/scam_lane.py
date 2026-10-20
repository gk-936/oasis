"""Scam lane and attack-text lane (ROUTER_OVERHAUL.md sections 6 and 7). Deterministic scorers over normalised text; no model, no I/O.
They only ever REFUSE or WARN. They cannot create a draft, change a payee or approve anything; the security lane in nlu.py and the policy engine are untouched."""
from __future__ import annotations

import codecs
import re
import unicodedata
from dataclasses import dataclass, field

from . import lexicon as L

# family -> (strong?, words). A strong family can fire alone; a weak one needs a second family.
FAMILIES: dict[str, tuple[bool, tuple[str, ...]]] = {
    "authority": (False, ("immigration bureau", "immigration office", "immigration department", "embassy", "consulate", "police", "cyber police", "public security", "court", "customs", "immigration", "tax office", "bank security team",
                          "bank security", "fraud department", "bank manager", "government", "recruiter", "lawyer", "customer service", "公安", "警察", "海关", "大使馆", "法院", "银行客服")),
    "threat": (False, ("visa has a problem", "visa problem", "problem with my visa", "account is in a case", "involved in a case", "deportation", "deported", "arrest", "arrested", "jail", "visa cancelled", "visa revoked", "account frozen", "account will be frozen", "account suspended",
                       "legal action", "lawsuit", "penalty", "blacklisted", "遣返", "逮捕", "冻结", "封号")),
    "urgency_secrecy": (False, ("urgently", "right now", "within the hour", "today only", "last chance", "don't tell anyone", "keep this secret", "don't tell your parents",
                                "don't tell the bank", "confidential", "马上", "立刻", "保密")),
    "advance_fee": (True, ("processing fee", "release fee", "clearance fee", "customs fee", "handling fee", "tax to release", "fee to claim", "fee to unlock", "scholarship fee",
                           "scholarship processing", "visa processing", "lottery", "winner", "inheritance", "to release my scholarship", "release my scholarship", "to claim my parcel", "to release it", "to unlock it", "to claim it",
                           "手续费", "解冻费", "奖学金")),
    "guaranteed_returns": (True, ("guaranteed", "risk-free", "risk free", "assured returns", "double your money", "double my money", "double the money", "doubles in a week", "double it in a week", "30% monthly", "10% weekly", "high returns", "investment opportunity",
                                  "trading platform", "signals group", "forex group", "crypto investment", "monthly returns", "稳赚", "高回报", "带单")),
    "safe_account": (True, ("regulatory account", "supervision account", "supervised account", "custody account", "safe account", "secure account", "protected account", "move your money", "move my money", "transfer to a safe", "verification account", "audit account",
                            "安全账户", "核查账户")),
    "credential_remote": (True, ("otp", "one-time password", "one time password", "verification code", "pin", "cvv", "card number", "password", "passcode", "remote access", "anydesk",
                                "teamviewer", "screen share", "install this app", "install an app", "download this app", "apk", "qr code to receive money", "scan this code", "验证码", "密码", "远程")),
    "untraceable": (True, ("gift card", "gift cards", "itunes card", "steam card", "usdt", "tether", "bitcoin", "crypto wallet", "wallet address", "prepaid card", "礼品卡", "虚拟币")),
    "refund_overpay": (True, ("overpaid me", "paid me too much", "return the difference", "return the extra", "i overpaid you", "sent too much", "send back the difference", "refund the difference", "wrong transfer please return", "accidentally sent", "多转了", "退还")),
    "account_change": (True, ("new account", "changed its account", "changed account", "updated bank details", "new bank details", "account has changed", "please use this account instead",
                              "pay to this account instead", "don't use the old account", "changed the account", "账户变更", "新账号")),
    "advance_before_service": (True, ("deposit before viewing", "deposit before i can", "before i can even view", "before viewing", "pay before viewing", "pay to hold the flat",
                                      "pay to reserve without a contract", "no contract yet", "landlord abroad", "key will be mailed", "先付定金", "看房前付款")),
    "stranger_payee": (True, ("qr code a stranger", "qr a stranger", "stranger sent me", "stranger's qr", "stranger's account", "stranger's wallet", "a stranger asked me to pay")),
    "romance_emergency": (True, ("dating app", "met online", "met on an app", "met on a dating", "stuck at the airport", "stuck in the airport", "stuck at an airport", "in hospital", "my friend needs", "family emergency", "send money to a friend i met online", "i met someone online", "紧急汇款")),
}
# phrasings that are not a fixed word list: (family, regex over the normalised text)
_EXTRA = tuple((f, re.compile(r)) for f, r in (
    ("threat", r"\bvisa\b[^.?!]{0,25}\b(?:cancel\w*|revoked|expir\w*|invalid|suspended|terminated|void)\b"),
    ("advance_fee", r"\b(?:scholarship|prize|reward|grant|lottery|winnings?)\b[^.?!]{0,50}\b(?:pay|fee|first|send|wire|transfer)\b|\b(?:pay|send|wire|transfer)\b[^.?!]{0,30}\bfirst\b[^.?!]{0,30}\b(?:scholarship|prize|reward|grant)\b"),
    ("advance_fee", r"\b(?:customs|courier|delivery)\b[^.?!]{0,30}\b(?:held|detained|seized|stuck|blocked)\b[^.?!]{0,50}\b(?:pay|fee|send)\b"),
    ("guaranteed_returns", r"\b(?:double|triple)\b[^.?!]{0,15}\b(?:money|investment|savings)\b|\bguarantee[sd]?\b[^.?!]{0,30}\b(?:profit|returns?|income)\b|\bpromised\b[^.?!]{0,30}\b(?:double|returns?|profit)\b"),
    ("refund_overpay", r"\boverpa(?:id|yment)\b[^.?!]{0,60}\b(?:return|send back|refund|give back)\b|\b(?:return|send back|refund)\b[^.?!]{0,40}\boverpa(?:id|yment)\b"),
    ("romance_emergency", r"\b(?:met|know)\b[^.?!]{0,25}\b(?:on|via|through)\b[^.?!]{0,15}\b(?:app|instagram|facebook|telegram|whatsapp|online)\b[^.?!]{0,60}\b(?:hospital|emergency|ticket|stuck|needs?)\b"),
    ("stranger_payee", r"\bqr(?: code)?\b[^.?!]{0,30}\b(?:stranger|someone i (?:don't|do not) know|unknown)\b|\b(?:stranger|unknown person)\b[^.?!]{0,30}\bqr\b"),
    ("safe_account", r"\b(?:move|transfer|send)\b[^.?!]{0,25}\b(?:money|funds)\b[^.?!]{0,25}\b(?:regulatory|supervised|escrow|verification|audit|check)\b[^.?!]{0,10}\baccount\b"),
))
# words that count only next to another family (false-positive guard)
GUARDED = ("fine", "agent", "officer", "parcel", "prize", "courier")
_PAY_CONTEXT = re.compile(r"\b(?:wants?|needs?|asks? for|asked for) \d|\breturn\b|\b(?:pay|paying|send|sending|transfer|remit|wire|invest|deposit|fee|charge|refund|forward|settle|move|release|top up|buy|purchase|wants? my|asked for my|asking for my|needs? my|give (?:them|him|her) my)\b|付|转|汇|交", re.I)
_ACCT = re.compile(r"(?<!\d)\d{12,19}(?!\d)")
_WALLET = re.compile(r"\b0x[0-9a-fA-F]{6,}\b|\b(?:[13][a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[a-z0-9]{20,})\b|\bT[1-9A-HJ-NP-Za-km-z]{33}\b")
_QUESTION = re.compile(r"\?\s*$|^(?:is|are|how|what|why|should|can|could|do|does)\b", re.I)

PATTERN_TEXT = {
    "advance_fee": ("This looks like an advance-fee scam: you are asked to pay a fee to release or claim something.",
                    "Real universities, scholarship bodies and couriers do not ask for a private transfer to release money or goods."),
    "guaranteed_returns": ("This looks like an investment scam: guaranteed or very high returns are the classic sign.",
                           "No legitimate investment guarantees returns, and a stranger who urges you to transfer now is a red flag."),
    "safe_account": ("This looks like a 'safe account' scam.", "A bank never asks you to move money to a 'safe account'."),
    "credential_remote": ("This looks like a credential or remote-access scam.",
                          "No bank, university or support agent needs your OTP, PIN, password or remote access to your device. Never share them or install an app on request."),
    "untraceable": ("This looks like a scam asking for an untraceable payment (gift cards, crypto or a wallet address).",
                    "Nobody legitimate, including universities, landlords, banks and governments, is paid in gift cards or crypto."),
    "refund_overpay": ("This looks like an overpayment or refund scam.", "Do not send back a 'difference' to a stranger: the original payment is often fake or reversible."),
    "account_change": ("This looks like an invoice-redirect scam: a new or changed account.",
                       "A changed bank account in an email or message is the most common fraud. Confirm by phone with the organisation, then have it added and verified in the registry."),
    "advance_before_service": ("This looks like a rental scam: money is requested before you can view or sign.",
                               "Never pay a deposit before viewing the flat and seeing a contract."),
    "romance_emergency": ("This looks like an emergency or romance scam.", "Do not send money to someone you have only met online or on an urgent unverified story."),
    "stranger_payee": ("This looks like a payment to a stranger's QR code or account.",
                       "I only pay registered payees, so a QR code or account from someone you do not know is refused."),
    "authority_threat": ("This looks like an authority-impersonation scam.",
                         "Real embassies, police and courts never ask for money transfers to avoid arrest or deportation."),
}


@dataclass
class Assessment:
    score: int
    families: list[str] = field(default_factory=list)
    pattern: str = ""
    pay_context: bool = False
    accounts: list[str] = field(default_factory=list)
    wallet: bool = False
    fire: bool = False
    question: bool = False


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = re.sub("[​-‏‪-‮⁠-⁤﻿­]", "", t)         # zero-width, bidi and soft-hyphen characters never hide a word
    t = t.replace("’", "'").lower().replace("_", " ")
    return re.sub(r"\s+", " ", t)[:2000]


def assess(text: str) -> Assessment:
    t = _norm(text)
    fams: list[str] = []
    for name, (_strong, words) in FAMILIES.items():
        if L.has(t, words):
            fams.append(name)
    for name, rx in _EXTRA:
        if name not in fams and rx.search(t):
            fams.append(name)
    guarded = [g for g in GUARDED if re.search(rf"\b{g}\b", t)]
    if fams:
        fams_g = list(fams)
    else:
        fams_g = []
    # guarded words count only when another family already hit
    if guarded and fams_g:
        fams_g.append("guarded")
    accts = _ACCT.findall(re.sub(r"[\s-]", "", text or "")) if re.search(r"\d{4}[\s-]?\d{4}", text or "") else []
    accts = accts or _ACCT.findall(text or "")
    wallet = bool(_WALLET.search(text or ""))
    pay = bool(_PAY_CONTEXT.search(t))
    score = len(fams_g)
    if pay:
        score += 2
    if accts or wallet:
        score += 2
    for threat_like in ("threat", "authority", "untraceable"):
        if threat_like in fams_g:
            score += 1
    strong = any(FAMILIES[f][0] for f in fams if f in FAMILIES)
    # authority + threat together are a pattern of their own
    pattern = next((f for f in fams if FAMILIES[f][0]), "")
    if not pattern and "authority" in fams and "threat" in fams:
        pattern = "authority_threat"
    needs = score >= 3 if pay else score >= 4
    if _QUESTION.search(t.strip()) and not (accts or wallet):
        needs = False                                    # a question about credentials or scams with nothing to pay to is answered by the FAQ, not warned about
    if re.search(r"\bi (?:refused|did not|didn't|said no|won't|will not)\b|\b(?:don't|do not|never)\s+(?:ask|tell|send)\b|\bwithout (?:sending|giving|sharing)\b", t):
        needs = False                                    # "someone told me to share my passcode, but I refused": narration, not an inducement
    if not pattern and "threat" in fams and pay and re.search(r"\b(?:unless|or else|otherwise|or you will|or i will)\b", t):
        pattern = "authority_threat"
    gate = strong or pattern == "authority_threat" or len([f for f in fams if f != "guarded"]) >= 2
    a = Assessment(score=score, families=fams, pattern=pattern, pay_context=pay, accounts=accts, wallet=wallet, question=bool(_QUESTION.search(t.strip())))
    a.fire = bool(fams and gate and needs and pattern)
    return a


def warning(a: Assessment, registry_accounts: set[str] | None = None) -> str:
    head, fact = PATTERN_TEXT[a.pattern]
    out = [head, fact]
    if a.question and not a.pay_context:
        out.append("If you are unsure, ask me 'is it safe' and I will explain what protects your money.")
    else:
        out.append("Stop, don't pay. Call the organisation on its official number, not the one in the message. I only pay registered payees, so nothing moved.")
    reg = registry_accounts or set()
    for ac in a.accounts[:1]:
        if ac not in reg:
            out.append(f"****{ac[-4:]} is not in the registry.")
    if a.wallet:
        out.append("A wallet address is not a registered payee.")
    return " ".join(out)


def heads_up(a: Assessment) -> str:
    """Score 1 or 2: answer normally and add one line when a payment for a registry payee is drafted."""
    if a.score and not a.fire and a.pattern:
        return f"Heads up: {PATTERN_TEXT[a.pattern][0].replace('This looks like ', '').rstrip('.')} is a common scam signal. I only pay registered payees."
    return ""


# ------------------------------------------------------------------ attack text (section 7): rules, prompts, secrets, authority, approval forging
_ATTACKS: tuple[tuple[str, re.Pattern], ...] = tuple((k, re.compile(v, re.I)) for k, v in (
    ("rules", r"(?:set|change|raise|increase|lower|disable|turn off|switch off|remove|bypass|override|skip|waive|lift|whitelist|allow)\b[^.?!]{0,40}\b(?:tier ?1[_ ]?auto[_ ]?limit|auto[_ ]?limit|my limit|the limit|registry check|registry|canary|audit log|audit|signature check|signature|verification|approval|unregistered|payee check|safety check|cap)\b|"
              r"\bwhitelist\b|\bpre-?approved\b|\bno signature needed\b|\bskip (?:the )?(?:signature|approval|sign)\b|\bapprove (?:all|everything|pending)\b|\bauto-?sign\b|\bsign (?:it )?for me\b|\buse my key\b|\bapprove without asking\b|\bmark (?:it )?as approved\b|"
              r"\bdon'?t ask me to sign\b|\bconfirm everything automatically\b"),
    ("prompt", r"\b(?:print|repeat|show|output|display|dump)\b[^.?!]{0,15}\b(?:everything|all|the text|the words|text)\b[^.?!]{0,15}\b(?:before|above|prior to|preceding)\b[^.?!]{0,20}\b(?:message|this|conversation|chat)\b|\b(?:repeat|print|show|reveal|output|display|dump|tell me|give me|what (?:is|are))\b[^.?!]{0,30}\b(?:words above|text above|system prompt|your (?:system )?(?:prompt|instructions|rules|tools|configuration|config)|starting with ['\"]?you are|hidden prompt|initial prompt)\b|"
               r"\bstarting with ['\"]?you are\b|\bwhat are your tools\b"),
    ("env", r"\b(?:show|print|reveal|dump|list|display|output|read|cat|echo)\b[^.?!]{0,25}\b(?:env(?:ironment)?(?: variables?)?|\.env|api[_ ]?keys?|secrets?|config(?:uration)?|the database|raw audit log|all accounts|other users'? data|another student'?s)\b"),
    ("authority", r"\b(?:i am|i'm|this is|as)\b[^.?!]{0,12}\b(?:the |your |oasis'?s? )?(?:admin(?:istrator)?|developer|owner|ceo|judge|organi[sz]er|auditor|regulator|police|engineer|creator|root|superuser)\b[^.?!]{0,60}\b(?:switch|turn|disable|skip|bypass|override|authori[sz]e|approve|allow|grant|ignore|print|show)\b|"
                  r"\b(?:developer|debug|maintenance|admin|god|jailbreak|sudo|root) mode\b|\bthe organi[sz]er said\b|\bmanagement approved\b|\bthis is a test\b[^.?!]{0,30}\b(?:skip|approve|bypass|disable)\b"),
    ("override", r"\bignora\w*\b[^.?!]{0,20}\b(?:instrucciones|reglas)\b|\bignorez?\b[^.?!]{0,20}\b(?:instructions|r[eè]gles)\b|\bignorier\w*\b[^.?!]{0,25}\b(?:anweisungen|regeln|instruktionen)\b|\bignor[ea]r?\b[^.?!]{0,20}\b(?:instru[cç][oõ]es|regras)\b|игнорир\w*[^.?!]{0,25}(?:инструкц|правил)|"
                 r"\b(?:ignore|disregard|forget|override)\b[^.?!]{0,25}\b(?:(?:previous|prior|above|earlier|all|your|the|these|those) )?(?:instructions?|rules?|prompts?|messages?|guidelines?|restrictions?|bill)\b|"
                 r"\bforget (?:everything|all|what)\b[^.?!]{0,20}\b(?:above|before|said|told)\b|"
                 r"\b(?:from now on|new instructions?:|you are now|pretend you (?:have no|are)|act as (?:a |an )?(?:unrestricted|dan)|do anything now|\bdan\b)\b|\[/?inst\]|<<sys>>|^system:|\bsystem:\s"),
    ("rules2", r"\b(?:skip|bypass|avoid|ignore|get around)\b[^.?!]{0,25}\b(?:check|checks|signature|signatures|approval|verification|registry|limit)\b|\bwithout (?:any |a |the |my )?(?:approval|signature|checks?|verification)\b|"
               r"\bnew rule:|\bno signature (?:needed|required|for)\b|\bpayments? (?:to|under|below|over|above)\b[^.?!]{0,50}\b(?:are |is )?(?:approved|pre-?approved|whitelisted|trusted|allowed|automatic)\b|"
               r"\b(?:good rating|five.?star|5.?star|positive review|bonus|reward|stars?)\b[^.?!]{0,30}\b(?:approve|skip|without)\b|\bi'?ll report you\b|\bjust this once\b[^.?!]{0,40}\b(?:approve|skip|pay)|"
               r"(?:忽略|无视|忘记|跳过|关闭|绕过|取消|关掉)[^。！？]{0,8}(?:规则|指令|指示|检查|签名|审批|限额|登记|验证)|(?:帮我|替我|给我)(?:签名|签字|批准)|"
               r"\b(?:ignore|bhool|bhul)\b[^.?!]{0,20}\b(?:karo|jao|do)\b|\b(?:band|hata|badha|skip) (?:karo|do)\b[^.?!]{0,40}|\b(?:rules?|instructions?|signature|registry|check|limit)\b[^.?!]{0,25}\b(?:band|hata|badha|ignore|bhool)\b|\bsign kar do\b|\bmain admin hoon\b"),
    ("exfil", r"\b(?:email|e-mail|send|forward|post|publish|upload|share|text|dm)\b[^.?!]{0,30}\b(?:me )?(?:my |the )?(?:records?|trust pass|balance|payment history|account|data|statement)\b[^.?!]{0,30}(?:@|https?:|www\.|\bpublicly\b|\bpublic\b|\bonline\b|\btwitter\b|\bfacebook\b|\bthis link\b)|\bpost my\b[^.?!]{0,25}\bpublicly\b|\bemail me my\b[^.?!]{0,15}\b(?:records?|data|statement)\b"),
    ("indirect", r"\b(?:treat|consider|regard) (?:this|the following|it)\b[^.?!]{0,40}\b(?:as|like) (?:a |an )?(?:trusted|official|system|admin\w*)\b|\b(?:assistant|ai|agent|bot)\s*[:,]\s*(?:treat|ignore|approve|send|transfer|pay|skip|forward)\b|\btrusted system (?:notice|message)\b"),
    ("cross_user", r"\b(?:approve as (?:the )?parent|switch to the (?:parent|judge|admin)|log me in as|show the parent'?s (?:drafts|balance|data)|become the parent|act as the parent)\b"),
))
_NEGATED_ACT = re.compile(r"\b(?:do not|don't|never|please don't|please do not|no need to)\s+(?:ever\s+|try to\s+|attempt to\s+)?(?:bypass|skip|ignore|override|avoid|disable|turn off|switch off)\b[^.,;!?]*|(?:不要|请勿|别|不用|无需)[^，。,.;；!?！？]*", re.I)
_BASE64 = re.compile(r"(?:[A-Za-z0-9+/]{4}){6,}={0,2}")


def attack_kind(text: str, views: list[str] | None = None) -> str | None:
    """The attack family of a message (rules, prompt, env, authority, override, cross_user), looking at the text and any decoded views. A quoted mention
    ("what does 'ignore previous instructions' mean?") is a question about words, not an instruction, and does not count."""
    from . import nlu
    cands = [_norm(text)]
    for v in views or []:
        cands.append(_norm(v))
    t0 = _norm(text)
    if len(t0) >= 12 and " " in t0 and sum(ch.isalpha() for ch in t0) > 0.6 * len(t0):
        cands.append(codecs.decode(t0, "rot13"))          # a rot13 view is only a candidate: it can refuse, never allow
        cands.append(t0[::-1])
    for c in cands:
        c = nlu._drop_negated(nlu.strip_mentions(c))
        c = _NEGATED_ACT.sub(" ", c)                       # "do not bypass the safety check, pay my rent": a promise not to, not an attempt
        if re.search(r"\bwhat does\b|\bwhat is the meaning\b|\bmeaning of\b", c) and not re.search(r"\band (?:then )?(?:pay|send|do|approve)\b", c):
            continue
        if nlu._disarmed(c):                               # "how do I approve my draft", "the email said to ignore previous instructions, is this phishing"
            continue
        for kind, rx in _ATTACKS:
            if rx.search(c):
                return kind
    return None
