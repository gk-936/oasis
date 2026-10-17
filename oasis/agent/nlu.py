"""Deterministic intent router for chat (English and Chinese). Keywords and regexes, no model, no randomness.

`classify` only LABELS a message; it never acts. The chat handler (agent/chat.py) maps each label onto existing code, and
every money path still goes through the normal pipeline, the registry check and a device-key approval. Unknown input
falls to `help`, never to a guess. Security categories are decided first, on a normalised copy of the text (compatibility
characters folded, zero-width and bidi characters removed, spaced-out letters joined, base64 blobs decoded), so a
message cannot dodge them with formatting.
"""
from __future__ import annotations
import base64
import binascii
import difflib
import re
from dataclasses import dataclass, field

from . import nl_extract

CJK = re.compile(r"[一-鿿]")

# ------------------------------------------------------------------ intents
PAY_OBLIGATION, PAY_TEXT, BALANCE, OBLIGATIONS, RATE, ROUTES, RUNWAY, PLAN = (
    "pay_obligation", "pay_text", "balance", "obligations", "rate", "routes", "runway", "plan")
CONVERT, RATE_TARGET, STATUS, CANCEL, CORRECT, CONFIRM, DENY, EXPLAIN, PROOF, CREDIT, UNDO = (
    "convert", "rate_target", "status", "cancel", "correct", "confirm", "deny", "explain", "proof", "credit", "undo")
SECRETS, BYPASS, PAY_INVOICE, HELP, GREETING, UNKNOWN = "secrets", "bypass", "pay_invoice", "help", "greeting", "unknown"
SPENDING = "spending"
ESTIMATE, LATER = "estimate", "later"      # "what would it cost, without paying" and "remind me / pay every month": answers only, never a draft
NOPAY, FAQ = "nopay", "faq"            # "no payment, I am only asking" and fixed how-it-works answers: neither can move money
REFUSALS = (SECRETS, BYPASS)

INVOICE_HINT = re.compile(r"(Payee|Account|Amount|收款人|账号|金额)\s*[:：]", re.I)
TARGET_RE_ZH = re.compile(r"(?:汇率|rate)[^\d]{0,12}(0\.\d+)[^\d]{0,12}(?:兑换|换成|转换)\s*(?:¥|CNY|RMB|人民币)?\s*([\d,]+(?:\.\d+)?)"
                          r"|(?:兑换|换成|转换)\s*(?:¥|CNY|RMB|人民币)?\s*([\d,]+(?:\.\d+)?)[^\d]{0,24}?(?:汇率|rate)[^\d]{0,12}(0\.\d+)", re.I)
TARGET_RE = re.compile(r"convert\s+(?:cny\s*|¥|rmb\s*)?([\d,]+(?:\.\d+)?)[^.\n]*?(?:rate|inr)[^\d]{0,30}?(0\.\d+)", re.I)


@dataclass
class ChatIntent:
    kind: str
    slots: dict = field(default_factory=dict)
    confidence: float = 0.9
    lang: str = "en"
    category: str | None = None        # for refusals: which kind of attempt it was


def detect_lang(text: str, ui: str = "en") -> str:
    """Chinese characters in the message win; otherwise the interface language (zh or en)."""
    return "zh" if CJK.search(text or "") else ("zh" if ui == "zh" else "en")


# ------------------------------------------------------------------ normalisation
_SPACED = re.compile(r"(?<![A-Za-z])(?:[A-Za-z][ .\-_]){3,}[A-Za-z](?![A-Za-z])")
_B64 = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


def normalise(text: str) -> str:
    t = nl_extract._clean(text or "").casefold()
    t = _SPACED.sub(lambda m: re.sub(r"[ .\-_]", "", m.group(0)), t)
    return re.sub(r"\s+", " ", t).strip()


def decoded_views(text: str) -> list[str]:
    """Text hidden in base64 inside the message (decoded, normalised); only printable UTF-8 results count."""
    out = []
    for m in _B64.finditer(text or ""):
        blob = m.group(0)
        try:
            raw = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True)
            s = raw.decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            continue
        if len(s) >= 6 and all(c.isprintable() or c in "\n\t" for c in s):
            out.append(normalise(s))
    return out


# ------------------------------------------------------------------ security categories
_SECRET_WORDS = (r"pass ?code|password|passwd|\bpin\b|private key|signing key|secret key|api[ _-]?key|access key|secret|token|"
                 r"credential|\.env|aws|bedrock key|session (?:cookie|secret)|device key|seed phrase|mnemonic|"
                 r"system prompt|your prompt|your instructions|initial prompt|hidden prompt|prompt above|"
                 r"密码|口令|私钥|密钥|令牌|系统提示|提示词|你的指令|环境变量|凭证|पासवर्ड|पासकोड|सीक्रेट")
_SECRETS_ASK = re.compile(rf"(?:{_SECRET_WORDS})", re.I)
_SECRETS_VERB = re.compile(r"(?:print|show|tell|reveal|give|send|share|leak|dump|display|repeat|output|read|find|config(?!uration)|stored|written down|what(?:'s| is| are)|list|export|"
                           r"告诉|显示|打印|泄露|给我|发给|是什么|输出|透露)", re.I)
_OTHER_USERS = re.compile(r"(?:other|another|all|every) (?:users?|students?|judges?|accounts?|sessions?|customers?)|(?:everyone|everybody|anyone|anybody)'?s? (?:else'?s? )?(?:payments?|accounts?|balances?|data|transactions?|details)|"
                          r"(?:someone|somebody) else'?s? (?:account|data|balance|payments?)|(?:其他|别人|所有)(?:用户|学生|账户|账号)", re.I)
_INJECTION = re.compile(
    r"ignore (?:all |any |the )?(?:previous|prior|above|earlier|your|these) (?:instructions?|rules?|prompts?|guidelines?|polic\w+)|ignore (?:everything|all|the) (?:above|before)\b|ignore the above|"
    r"ignore (?:all |any |the |your |these |my |safety |security |payment |approval )*(?:rules|instructions|guidelines|polic(?:y|ies)|checks|limits)\b|"
    r"disregard (?:all |any |the )?(?:previous|prior|above|your) |forget (?:all |your |the )?(?:previous |prior )?(?:instructions?|rules?)|"
    r"new instructions?:|system (?:note|message|override)|you (?:must|will) now|you are now|from now on you|act as (?:if|an?) |"
    r"pretend (?:to be|you)|role-?play|developer mode|dev mode|god mode|admin(?:istrator)? mode|debug mode|maintenance mode|"
    r"jailbreak|\bdan\b|do anything now|sudo\b(?!\s+pay\b)|override (?:the )?(?:safety|security|policy|rules?|limit)|"
    r"忽略(?:以上|之前|上面|所有)?(?:的)?(?:指令|规则|提示)|忽略[^，。,.\s]{0,8}(?:规则|指令|提示|限制)|无视(?:以上|之前|所有)|开发者模式|管理员模式|调试模式|越狱|扮演", re.I)
_BYPASS = re.compile(
    r"approve (?:all|every|any|everything|the pending|all pending|them)|(?<!i'll )(?<!i will )(?<!i am going to )(?<!i'm going to )(?<!let me )(?<!app to )(?<!in the app )(?:approve|sign) my (?:[a-z]+ ){0,2}(?:draft|payment|bill)\b|(?:skip|bypass|disable|turn off|waive|without|no need for|don'?t need|no time for) "
    r"(?:the |a |an |any |my |your )?(?:(?:parent|mum|mom|dad|guardian)(?:'?s'?)? |parental )?(?:approval|signature|signing|verification|check|checks|2fa|otp|registry|policy|limits?|safety|security|co-?approv\w*)|"
    r"auto[- ]?approve|pre-?approved|already approved|i (?:hereby )?approve|(?:sign|approve) (?:it |this |that )?(?:for me|on my behalf)|(?:sign|approve)\b[^.?!]{0,40}\b(?:for me|on my behalf)\b|admin(?:istrator)? (?:privileges?|rights|access)|override (?:my |the )?(?:daily |spending |transfer |payment )*(?:limit|cap|threshold)|(?:even though|regardless of|despite|ignore) the registered|(?:larger|bigger|higher) amount\b[^.?!]{0,25}\banyway|"
    r"mark [a-z ]{0,30}?(?:as )?(?:approved|verified|paid|signed)|(?<!can )(?<!only )(?<!must )(?<!will )(?<!to )(?<!cannot )(?<!can't )release (?:the )?(?:funds?|money|payments?)|set (?:the )?status (?:to )?(?:paid|approved|verified)|"
    r"(?:raise|increase|remove|lift|change) (?:my |the )?(?:(?:daily|spending|transfer|payment) ){0,2}(?:limit|threshold|cap)|"
    r"(?:^|\b(?:can|could|would|will) you |\bplease |\bpls )(?:approve|sign)\b(?: all| every| the| my| these| those| this| that| pending){0,3} (?:drafts?|payments?|transfers?|bills?)\b|"
    r"(?:^|\b(?:can|could|would|will) you |\bplease |\bpls )(?:change|edit|update|replace|modify)\b[^.?!]{0,30}\b(?:registry|landlord'?s? (?:name|bank|account)|payee'?s? (?:name|account|details)|(?:bank|account) (?:number|details))|"
    r"approve kar(?: do|o)?\b|\bapprove\b[^.?!]{0,20}\bkar (?:do|o|dena|de)\b|\bsign kar ?do\b|(?:parent|mummy|papa) ki taraf se|\b(?:sab|sare|saare)\b[^.]{0,30}\bapprove\b|अप्रूव|मंज़ूर|मंजूर|बिना (?:साइन|हस्ताक्षर)|"
    r"批准所有|全部批准|跳过(?:批准|审批|签名|验证)|无需(?:批准|审批|签名|验证)|不用(?:批准|审批|签名)|绕过|关闭(?:安全|验证|检查)|"
    r"(?:do not|don'?t|dont|no) need (?:the |any |your |an? )?(?:approval|signature|signing|authori[sz]ation)|"
    r"(?:approve|sign|authori[sz]e) (?:it|this|that|them|the (?:draft|payment|transfer)) (?:yourself|by yourself|on your own)|(?:approve|sign|authori[sz]e) yourself", re.I)
_REGISTRY_EDIT = re.compile(r"\b(?:add|create|register|insert|include|set up)\s+(?:a |an |the )?(?:new |another )?(?:payee|recipient|beneficiary|contact)\b|"
                            r"\b(?:remove|delete|erase|wipe|clear|edit|modify)\s+(?:a |an |the |my |all |every )?(?:payees?|recipients?|beneficiar\w+|registry|payment history|transaction history|transactions?|payment records?|history|audit(?: log| trail)?|logs?)\b|"
                            r"\b(?:add|register|save|set up)\b[^.?!]{0,40}\bas (?:a |my )?(?:new )?(?:payee|recipient|beneficiary|contact)\b|"
                            r"\b(?:remove|delete|erase|drop)\b[^.?!]{0,40}\b(?:from|in|off) (?:the |my )?(?:registry|payee list|payees)\b|"
                            r"添加.{0,4}(?:收款人|收款方)|新增.{0,4}(?:收款人|收款方)|删除.{0,6}(?:记录|历史|收款|日志)", re.I)
_ROLE = re.compile(r"(?:i am|i'm|this is|act as|acting as|as|log(?:ged)? in as|switch to|become) (?:the |your |a |an )?(?:parent|guardian|mother|father|mom|dad|admin\w*|"
                   r"judge|bank|teacher|owner|developer|operator|support)\b|"
                   r"(?:parent|guardian) (?:here|speaking)|我是(?:家长|父母|管理员|银行|老师|开发者)|(?:作为|以)(?:家长|管理员)", re.I)
_SOCIAL = re.compile(r"(?:parent|mummy|papa|maa|bank)\b[^.]{0,25}\b(?:approve|confirm|authori[sz]e) kar (?:diya|di|chuk)|"
                     r"(?:your |my )?(?:parent|mother|father|mom|dad|guardian|bank|manager|university|landlord|embassy|police) "
                     r"(?:has |have |already |just )?(?:approved|confirmed|authori[sz]ed|instructed)|"
                     r"(?:your |my )?(?:parent|mother|father|mom|dad|guardian|bank|manager|university|embassy|police) "
                     r"(?:has |have |already |just )?(?:told|said|asked|called)|"
                     r"this is (?:just )?(?:a )?(?:test|drill|audit|debug|emergency|authori[sz]ed)|it'?s (?:fine|ok|okay|safe|allowed|authori[sz]ed)|"
                     r"trust me|i (?:am|'m) authori[sz]ed|official (?:request|order)|(?:for )?security (?:reasons|purposes)|"
                     r"your (?:developer|creator|admin\w*) (?:said|told|allowed)|家长(?:已经|已)?(?:批准|同意|确认)|这是(?:一个)?测试|银行(?:说|通知|要求)|相信我", re.I)
_URGENCY = re.compile(r"urgent|immediately|right now|asap|right away|emergency|hurry|within \d+ ?(?:hours?|minutes?)|last chance|final notice|"
                      r"紧急|马上|立刻|立即|尽快|急", re.I)


_NEGATED = re.compile(r"(?:\bdo not|\bdon'?t|\bnever|\bnot|\bwithout asking to|请勿|不要|别)\s*(?:please\s*)?$", re.I)
_CONDITIONAL_APPROVE = re.compile(r"(?:until|before|after|when|once|unless|so that|till)\s+i\s+(?:approve|aprove|apporve)", re.I)


def _bypass_asked(norm: str) -> bool:
    """A real bypass request. 'Do not bypass the safety check' (negated verb) and 'keep it a draft until I approve' (the user
    will sign later) are not requests; any other bypass match in the same message still counts."""
    cleaned = _CONDITIONAL_APPROVE.sub(" ", _snap(norm, ("until", "before", "unless")))
    for m in _BYPASS.finditer(cleaned):
        if re.match(r"(?:skip|bypass|disable|turn off|waive)\b", m.group(0)) and _NEGATED.search(cleaned[max(0, m.start() - 16):m.start()]):
            continue
        if re.match(r"(?:sign|approve)\b", m.group(0)) and _WHY_CURIOUS.search(cleaned) and _CURIOUS_MARK.search(cleaned):
            continue                         # "why can't you approve it for me? I'm curious how signing works" asks for the reason
        return True
    return False


_WHY_CURIOUS = re.compile(r"\bwhy (?:can'?t|won'?t|don'?t|couldn'?t)\b[^.?!]{0,40}\b(?:approve|sign)\b|\bhow (?:the )?(?:signing|approval) works\b", re.I)
_CURIOUS_MARK = re.compile(r"\b(?:curious|wondering|understand|designed|makes? sense)\b", re.I)
_QUOTED = re.compile(r"[“\"「『][^”\"」』]{3,200}[”\"」』]|(?<!\w)'[^']{3,200}'(?!\w)")
_MENTION = re.compile(r"\b(?:mean|means|meaning|quote[sd]?|quoting|example|says?|said|mentions?|mentioned|explain why|what does|why (?:must|can'?t|does)|kya (?:hota|matlab)|matlab|samjha\w*)\b|意思|含义|引用|例如|比如|什么是", re.I)


def strip_mentions(norm: str) -> str:
    """'The email says "ignore previous instructions"; what does it mean?' talks ABOUT a phrase. The quoted part is dropped before the
    security check; the rest of the sentence is still checked, and nothing quoted is ever acted on."""
    if not (_MENTION.search(norm) and _QUOTED.search(norm)):
        return norm
    rest = _QUOTED.sub(" ", norm)
    # a message that is almost all quote is not talking about a phrase, it IS the phrase: keep it whole
    return rest if len(re.sub(r"\W+", "", rest)) >= 0.35 * len(re.sub(r"\W+", "", norm)) else norm


_EXEMPT_WORDS = ("without", "sending", "giving", "telling", "sharing", "showing", "revealing")


def _snap(norm: str, words) -> str:
    """Snap near-misses ('withot', 'tellling') onto the words the reset-help exemption looks for. It only ever RELAXES a refusal for a
    help question; every other security pattern still runs on the unchanged text."""
    out = []
    for tok in norm.split(" "):
        w = tok.strip(".,!?;:")
        if len(w) >= 4 and w.isalpha() and w not in words:
            m = [v for v in difflib.get_close_matches(w, words, 1, 0.8) if v[0] == w[0] or sorted(v) == sorted(w)]
            if m:
                tok = tok.replace(w, m[0])
        out.append(tok)
    return " ".join(out)


_SEC_VOCAB = ("ignore", "instructions", "previous", "passcode", "password", "private", "signing", "signature", "approval", "approve", "approved", "registry",
              "verification", "credentials", "configuration", "device", "bypass", "disable", "forget", "authorized", "release", "waive", "override", "limit",
              "safety", "secret", "system", "prompt", "guardian", "transfer", "every", "everything", "pending", "checks", "remove", "raise", "daily", "called",
              "behalf", "parent", "payments", "bedrock", "rules", "funds", "university", "everyone", "mother", "father")


def snap_security(norm: str) -> str:
    """Typos in an attack ('ignroe', 'passcod', 'apprval') are snapped onto the attack vocabulary so the same patterns apply. Used only as an EXTRA
    view for the security check, so it can only add refusals; routing of ordinary messages never sees it."""
    out = []
    for tok in norm.split(" "):
        w = tok.strip(".,!?;:'\"")
        if len(w) >= 5 and w.isalpha() and w not in _SEC_VOCAB:
            m = [v for v in difflib.get_close_matches(w, _SEC_VOCAB, 1, 0.8) if v[0] == w[0] or sorted(v) == sorted(w)]
            if m:
                tok = tok.replace(w, m[0])
        out.append(tok)
    return " ".join(out)


# Honest context that is not an attack. Each only RELAXES one pattern and never skips the others.
_STILL_SIGN = re.compile(r"\b(?:still|myself|my own)\b[^.?!]{0,25}\bsign\w*|\bsign\w*\b[^.?!]{0,15}\bmyself|\bnot asking you to (?:approve|sign)|"
                         r"leave it for my[^.?!]{0,20}signature|我(?:自己|会)[^。]{0,6}签名", re.I)
_NEG_ASK = re.compile(r"\b(?:do not|don'?t|never)\s+(?:ask|make|have|require)\s+me\s+to\s+(?:send|share|give|provide|enter|paste|type|tell|submit|upload)\b[\w' ,/]{0,45}|"
                      r"不要让我[^。！？]{0,40}|"
                      r"\bi\s+(?:do not|don'?t)\s+need\b[\w' ,/]{0,40}?\b(?:information|info|data|details)\s+(?:about|of|on|from)\s+(?:other|another|all)\s+(?:users?|students?)\b",
                      re.I)
_REVEAL = re.compile(r"show|reveal|print|display|dump|leak|read|repeat|output|list|export|显示|打印|泄露|输出|透露|告诉我", re.I)
_SECURITY_QA = re.compile(r"\b(?:checks?|see|know)\b[^.?!]{0,25}\b(?:whether|if)\b[^.?!]{0,50}\b(?:registered|signed|updated|status)\b|explain why |忘记.{0,6}密码.{0,25}(?:流程|怎么|如何)|忘记.{0,6}(?:device key|密钥|设备密钥).{0,20}(?:怎么|如何|联系)|\bwhy (?:does|do|is|are)\b|\bwhere (?:do|can|should) i locate\b[^.?!]{0,30}\bsettings\b|"
                          r"\b(?:can|could|would) (?:they|someone|somebody|an attacker|a hacker|anyone)\b[^.?!]{0,30}\bsteal\b|\bhow (?:does|do)\b[^.?!]{0,30}\bprotect", re.I)


_HOWTO = re.compile(r"(?:请)?(?:只)?告诉我 ?(?:官方)? ?(?:recovery steps|reset 流程|流程|步骤)|(?:tell|show|explain|teach|guide) me how")


_REPORTED_ASK = re.compile(r"(?:told|asked|said|wants?|wanted)\s+(?:me\s+)?to\s+(?:give|share|send|tell|hand|reveal)\b[^.?!,;]*", re.I)
_I_REFUSED = re.compile(r"\bi\s+(?:didn['’]?t|did not|refused|said no|won['’]?t|will not|never did)\b", re.I)


def _drop_negated(norm: str) -> str:
    """Remove 'do not ask me to send you the password' style clauses (a promise not to share, not a request to see), and a
    story where someone else asked for a password and the speaker says they refused. Other clauses are still checked."""
    if _I_REFUSED.search(norm):
        rest = _REPORTED_ASK.sub(" ", norm)
        if not _SECRETS_VERB.search(rest):
            norm = rest
    return _NEG_ASK.sub(lambda m: m.group(0) if _REVEAL.search(m.group(0)) else " ", norm)


def security_category(norm: str) -> str | None:
    """secrets | injection | bypass | registry | role | social | None, for a normalised message."""
    norm = _drop_negated(norm)
    # asking HOW to reset a login is help, not a request to reveal one; every other check below still applies
    asked = re.sub(r"\bwithout (?:sending|giving|telling|sharing|showing|revealing)[^.?!]{0,30}|\bwhere is\b", "", _snap(norm, _EXEMPT_WORDS))
    asked = _HOWTO.sub(" ", asked)
    reset_help = bool(_RESET.search(_snap(norm, ("reset", "password", "passcode", "login")))) and not _SECRETS_VERB.search(asked)
    plain = _HOWTO.sub(" ", norm)           # "tell me the recovery steps" asks for steps, not for a secret
    reset_help = reset_help or bool(_SECURITY_QA.search(norm) and not _SECRETS_VERB.search(plain) and not _REVEAL.search(plain))
    if not reset_help and _SECRETS_ASK.search(norm) and (_SECRETS_VERB.search(norm) or "?" in norm or len(norm) < 40):
        return "secrets"
    if _OTHER_USERS.search(norm):
        return "secrets"
    if _INJECTION.search(norm):
        return "injection"
    if _SOCIAL.search(norm) and not (_STILL_SIGN.search(norm) and not _bypass_asked(norm)):
        return "social"
    if _ROLE.search(norm):
        return "role"
    if _bypass_asked(norm):
        return "bypass"
    if _REGISTRY_EDIT.search(norm):
        return "registry"
    return None


# ------------------------------------------------------------------ everyday intents
_PAY_IMPERATIVE = re.compile(
    r"^(?:(?:please|kindly|pls|can you|could you|would you|i (?:want|need|have|would like) to|i'?d like to|let'?s|go ahead and|help me|lets)\s+)*"
    r"(?:pay|settle|clear|send|transfer|remit|wire|cover|prepare|draft|sort(?: out)?|set up|make (?:a |the )?payment)\b|^(?:请|帮我|麻烦|我要|我想|我需要)?(?:帮我)?(?:交|付|缴|支付|转账|汇款|转|起草|准备|给)", re.I)
_PAY_WORD = re.compile(r"\b(?:pay|paying|settle|clear|send|transfer|remit|wire|cover|prepare|draft|bana do|banao)\b|草稿|给|交|付|缴|支付|转账|汇款|起草|处理|办理", re.I)
_OBL_WORD = re.compile(r"rent|kiraya|kiraaya|किराया|tuition|deposit|fees?\b|bills?\b|dues?\b|房租|租金|学费|押金|账单|费用", re.I)
_CANCEL = re.compile(r"^(?:(?:please|pls)\s+)?(?:cancel|stop|abort|abandon|never ?mind|forget it|scrap)\b|"
                     r"^(?:no,? )?(?:wait|hold on|hang on)\b(?!.*\b(?:make|change|instead|actually|should|meant)\b)|^(?:no,? )?stop\b|\bwrong (?:person|one|guy)\b|\bnot (?:that|this) one\b|\bcancel (?:kar|karo|do|please|pls)\b|\bundo (?:that|this|the)\b[^.]{0,25}\bdraft\b|^no,? (?:stop|cancel)\b|^no,? wait\b(?!.*\b(?:make|change|instead|actually|should|meant)\b)|"
                     r"\b(?:cancel|stop|abort|withdraw) (?:that|this|the|my|it)\b|(?:don'?t|do not|dont) (?:pay|send|go ahead)|"
                     r"取消|别付|不要付|不付了|停止|算了|撤回|"
                     r"\b(?:scrap|delete|discard|drop|trash|void) (?:the |this |that |my )?(?:whole |entire )?(?!first\b|old\b|previous\b|earlier\b)(?:\w+ )?(?:thing|it|draft|payment|one)\b|"
                     r"\bchhod(?:o|na)?\b|\bmat kar(?:o)?\b|\brehne (?:do|de)\b|\bnahi karna\b|删掉|删除|作废|不要了|छोड़ो|मत करो", re.I)
_CORRECT = re.compile(r"\bcorrection\b|\bcorrect (?:it|that|this|the (?:draft|amount))\b|\b(?:discard|replace|void|scrap) the (?:first|old|previous|earlier) draft\b|(?:the |that )?(?:amount|sum|figure|total|price)\s+(?:was |is |should be |must be |has to be |needs to be )"
                      r"|(?:should|must|ought to) be\b|make (?:it|that|the amount)\b|change (?:it|that|the amount)\b|"
                      r"\bactually\b|\bwrong (?:amount|account|payee|number)\b|\bi meant\b|\bno,? (?:it'?s|its|make)\b|\binstead\b|\bnahi\b|\bgalat\b|draft change|change kar|\bbadal\b|"
                      r"金额(?:应该|应为|是|改成|改为)|改成|改为|应该是|写错了|弄错了|不对", re.I)
_CONFIRM = re.compile(r"^(?:(?:yes|yep|yeah|ok|okay|sure)[,!. ]+)?(?:yes|yep|yeah|yup|y|ok|okay|sure|confirm|confirmed|go ahead|do it|proceed|please do|sounds good|that'?s right|correct|right|"
                      r"yes please|ok please|确认|是的?|好的?|可以|行|对|没错|同意)(?:[, ]+please)?[\s!.。！]*$", re.I)
_DENY = re.compile(r"^(?:no|nope|nah|n|not now|no thanks|don'?t|negative|否|不|不要|不用了?|别|不行)[\s!.。！]*$", re.I)
_UNDO = re.compile(r"\bundo\b|\brevers\w+|get (?:it|my money|the money) back|\brecall\b|\bclaw ?back\b|\brefund\b|撤销|追回|退回|退款", re.I)
_EXPLAIN = re.compile(r"\bheld for review\b|\bwhy (?:is|was|did)[^?]{0,40}\b(?:held|on hold)\b|暂停|搁置|扣留|why (?:was|is|did|has|were)[^?]{0,60}(?:block|stop|hold|held|reject|refus|declin|frozen|freez|flag|deny|denied)|"
                      r"what happened|explain (?:the|that|this|why)|why (?:are|do|am) (?:you|i)[^?]{0,40}(?:signature|sign|approv|confirm|asking)|why (?:can'?t|couldn'?t|won'?t) (?:i|you)|为什么[^？?]{0,20}(?:拦截|拒绝|冻结|暂缓|阻止|不能)|怎么回事|解释", re.I)
_PROOF = re.compile(r"\bproofs?\b|\breceipts?\b|\bevidence\b|\bverify (?:the )?payment\b|证明|凭证|回执|收据", re.I)
_CREDIT = re.compile(r"\bcredit\b|trust pass|\breputation\b|build (?:my )?(?:history|record|trust)|信用|信誉", re.I)
_STATUS = re.compile(r"(?:did|has|have|was|is)[^?]{0,40}(?:go through|gone through|arrive|arrived|get paid|got paid|been paid|sent|paid|received|land|landed|reach)|"
                     r"where(?:'s| is| are)[^?]{0,20}(?:my )?(?:money|payment|transfer|funds)|(?:payment|transfer) status|\bstatus\b|\bpending\b|paid yet|"
                     r"\bwas it waiting\b|waiting for (?:the |my )?(?:device )?signature|到账|付了吗|付款了吗|进度|状态|有没有付|是否已付|支付成功", re.I)
_RUNWAY = re.compile(r"kitne din|kab tak chal|\bchalega\b|\bhave enough\b|enough to (?:cover|pay)|run out|(?:money|funds|cash|savings) (?:will )?(?:last|run)|will (?:my )?(?:money|funds|cash|savings) last|runway|how long (?:will|can|do)|last me|(?:enough|sufficient) (?:money|funds|cash)|will i (?:have|be) (?:able|enough)|"
                     r"going to (?:run|be) (?:out|short|broke)|afford|够用|撑多久|够不够|用完|还能用", re.I)
_BALANCE = re.compile(r"(?:paisa|paise|balance) kitna|kitna (?:paisa|paise|bacha)|how much (?:money|cash|do i have\b(?! to)|have i got|is (?:in|left))|how much (?:\w+ ){0,2}(?:do )?i (?:have|got|have got|still have)\b(?! to)|how much (?:\w+ )?(?:is )?left\b|\bbalance|\bmy (?:funds|money|savings|wallet)\b|\bwhat do i have\b|\b(?:cny|inr|yuan|rupee) wallet\b|"
                      r"how much (?:is )?left|what(?:'s| is)? (?:remains?|left)|\bremain(?:s|ing)?\b[^?]{0,30}(?:wallet|balance|account)|\b(?:my|student|sandbox) (?:student |sandbox )?wallet\b|余额|还有多少钱|有多少钱|还剩|剩多少|账户里", re.I)
_OBLIGATIONS = re.compile(r"没交|未交|欠多少|\boverdue\b|\bpast due\b|截止|截至|哪天|几号|\b(?:bill|rent|tuition|fees?|deposit)\s+(?:ka\s+)?kitna\b|\bkitna\s+(?:baaki|baki|bacha|dena|dene)\b|how much (?:is|are|do i (?:owe|pay)|do i (?:have|need) to pay|must i pay|should i pay)[^?]{0,20}(?:rent|tuition|deposit|fees?|bills?)|what (?:do i|i) owe|how much (?:do )?i (?:still )?owe|how much (?:is )?(?:still )?(?:due|owed)|what(?:'s| is| are) (?:due|owed|upcoming|coming up)|\bupcoming\b|\bbills\b|\bobligations?\b|\bdue (?:soon|date|dates)\b|"
                          r"when (?:is|are)[^?]{0,30}due|(?:what|which) (?:payments|bills)|应付|要付|欠|到期|待付|哪些费用", re.I)
_SPENDING = re.compile(r"\b(?:what|how much) (?:did|have) i (?:spend|spent|paid|pay)\b|\bmy (?:spending|expenses|transactions)\b|\b(?:pichla|last|previous|recent) transactions?\b|\bspending\b|\bexpenses?\b|"
                       r"\btransaction (?:history|list)\b|where (?:did|does) my money go|花了多少|花销|开销|消费|支出", re.I)
_FRACTION = re.compile(r"\b(half|a third|one third|a quarter|one quarter|quarter)\b(?: of)?|一半", re.I)
_FRACTION_V = {"half": 0.5, "a third": 1 / 3, "one third": 1 / 3, "a quarter": 0.25, "one quarter": 0.25, "quarter": 0.25, "一半": 0.5}
_RATE = re.compile(r"\b(?:exchange |fx |forex |conversion )?rates?\b|inr (?:to|/|-|→) ?cny|cny (?:to|/) ?inr|how many (?:yuan|cny|rmb) (?:per|for|is)|汇率|兑换率|换汇率", re.I)
_ROUTES = re.compile(r"cheap\w*|best (?:way|route|option|rail)|which (?:route|way|rail|option|app)|\broutes?\b|how (?:should|do|can) i (?:send|transfer|move|remit)|"
                     r"\bfees?\b(?! due)|compare|fastest|路线|最便宜|怎么汇|怎么转|哪种方式|手续费", re.I)
_ROUTES_STRONG = re.compile(r"cheap\w*|best (?:way|route|option|rail)|\broutes?\b|fastest|how (?:should|do|can) i (?:send|transfer|move|remit)|路线|最便宜", re.I)
_PLAN = re.compile(r"\bplan\b|\bbudget\b|semester|schedule my|规划|计划|预算", re.I)
_CONVERT = re.compile(r"\b(?:inr|cny|rmb|usd|eur|gbp)\b[^.\n]{0,25}\b(?:mein|me|to|into|ko)\b[^.\n]{0,25}\b(?:quote|convert|exchange)\b|\b(?:convert|exchange|swap|change|quote)\b[^.\n]{0,40}(?:inr|cny|rmb|usd|eur|gbp|aud|jpy|rupees?|yuan|dollars?|euros?|pounds?|₹|¥|\$|€|£)|how much is[^?]{0,30}(?:inr|cny|rmb)[^?]{0,10}in (?:inr|cny|rmb)|\b(?:move|put|turn|shift|swap)\b[^.\n]{0,30}\b(?:inr|rupees?)\b[^.\n]{0,15}\b(?:into|to)\b[^.\n]{0,10}\b(?:cny|rmb|yuan)\b|兑换|换成|换汇|转换|换算", re.I)
_GREETING = re.compile(r"^(?:हाय|नमस्ते|नमस्कार|hii+|hi|hello|hey|hiya|yo|good (?:morning|afternoon|evening)|greetings|thanks|thank you|thx|你好|您好|嗨|谢谢|早上好|晚上好)"
                       r"(?:\s+(?:there|team|oasis|everyone|assistant|bot))?\b[\s!.。！?？]*$", re.I)
_RESET = re.compile(r"(?:forgot|forget|lost|reset|recover|change|locked out|can'?t (?:log ?in|sign ?in))[^.?!]{0,40}(?:password|passcode|login)|"
                    r"(?:password|passcode|login) (?:reset|recovery|help)|忘(?:了|记)(?:密码|口令)|重置(?:密码|口令)|(?:改|换|修改|更改|更换)(?:密码|口令)", re.I)
_INVOICE_WORD = re.compile(r"\binvoice\b|发票|账单号", re.I)
_DUE_PAY = re.compile(r"\b(?:rent|tuition|deposit|fees?|bill)\b[^.?!]{0,20}\bdue (?:today|now|tomorrow|this week)\b|(?:房租|学费|押金)(?:今天|今日)?到期", re.I)
_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_WORD_AMT = re.compile(r"\b(" + "|".join(_WORD_NUM) + r")\s+(thousand|hundred)\b", re.I)


_HAZAAR = re.compile(r"(\d+(?:\.\d+)?)\s*(?:hazaar|hazar|hajar)\b|(?<![\w.])(\d+(?:\.\d+)?)k\b", re.I)


def _words_to_digits(text: str) -> str:
    """'six thousand yuan' -> '6000 yuan' (one to ten, thousand or hundred only), '50 hazaar' -> '50000'; other text is untouched."""
    text = _HAZAAR.sub(lambda m: str(int(float(m.group(1) or m.group(2)) * 1000)), text)
    return _WORD_AMT.sub(lambda m: str(_WORD_NUM[m.group(1).lower()] * (1000 if m.group(2).lower() == "thousand" else 100)), text)
_SMALLTALK = re.compile(r"^(?:你好|您好|嗨|hi|hello|hey)[，, ]*(?:今天)?(?:怎么样|好吗|最近好吗)|how are you", re.I)
_HELP = re.compile(r"\bhelp\b|what can you do|what you do|how (?:do|does) (?:you|this|it) work|\bcapabilit|what are you|who are you|帮助|你能做什么|怎么用|你是谁", re.I)
_NOPAY = re.compile(r"\bno (?:drafts?|payments?)\b|\b(?:only|just) asking for (?:instructions?|info\w*|an explanation|help)\b|\banswer generally\b|\bnot requesting\b|\b(?:do not|don'?t|dont|no need to|without|not asking|just asking|only asking|only want to know|just answer|no payment|nahi chahiye)\b[^.]{0,45}\b(?:draft|payment|pay|convert|conversion|creat\w*|authori[sz]\w*|initiat\w*|sign\w*|action|needed)\b|\bonly (?:a|an) \w*\s*question\b|\b(?:asking|answer) (?:about|generally|for)? ?[^.]{0,30}\bonly\b|(?:不要|无需|不用|别)[^。]{0,8}(?:创建|付款|草稿|签名|执行)|只回答|只想知道|仅询问", re.I)
_FAQ = (("draft", re.compile(r"\bwho(?:'s| is| am i| are we| will)?\b[^?]{0,25}\b(?:this|it|that|the (?:money|payment|draft))\b[^?]{0,15}\b(?:going|go|paid|sent|receiv\w+|for)\b|\bwho am i (?:paying|sending)|\bwho gets\b|\bwho (?:will |would )?receives?\b|\bwhere (?:is|will|does|do) (?:this|it|that|the (?:money|payment))\b[^?]{0,10}\b(?:going|go)\b|\bwhich account\b[^?]{0,30}\b(?:this|it|that|going|paid|sent|used)|\bwhose account|\bto whom\b|"
                  r"\bwhat happens if i (?:don'?t|do not|never|won'?t) sign|\bwhat if i (?:don'?t|do not|never) sign|\bif i (?:don'?t|do not|never) sign|谁收款|付给谁|转给谁|哪个账户|不签名会", re.I)),
        ("payees", re.compile(r"\bwhat payees\b|\bmy payees\b|\bpayees (?:do )?i have\b|\bregistered payees|\bpayee list|\bwhich payees|\ball the payees|\bhow many (?:registered )?payees|\bwho (?:can|do) (?:i|you) pay\b|\bfixed payees|收款人有哪些|固定收款人|登记.{0,4}收款人", re.I)),
        ("sign", re.compile(r"\bwhere (?:do|can|should) i sign\b|\bhow (?:do|can|should) i sign\b|\bwhat happens (?:after|when) i sign\b|\bsign (?:kahan|kaise)\b|在哪.{0,3}签名|怎么签名|签名后", re.I)),
        ("what", re.compile(r"\bwhat(?:'s| is) oasis\b|\boasis (?:kya|what)\b|oasis是什么", re.I)))
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])(\d[\d,]*(?:\.\d+)?)(?![A-Za-z0-9_])")        # CJK text may touch the number: "话费交1500"


def _bare_number(text: str) -> float | None:
    """The one number in a short correction ('make it 2600'); None if there is none or more than one."""
    t = nl_extract._ACCT_RUN.sub(" ", nl_extract._clean(text))
    t = re.sub(r"\d+\s*(?:days?|weeks?|months?|years?|%|st|nd|rd|th)\b", " ", t, flags=re.I)
    nums = {m.group(1).replace(",", "") for m in _NUMBER.finditer(t)}
    if len(nums) != 1:
        return None
    try:
        return float(next(iter(nums)))
    except ValueError:
        return None


def _amount(text: str, bare: bool = False) -> tuple[float, str] | None:
    text = _words_to_digits(text)
    m = nl_extract.money(text, bare=bare)
    if m:
        return m
    v = _bare_number(text) if bare else None
    return (v, "CNY") if v else None


_RECEIPT_ASK = re.compile(r"\b(?:receipts?|proofs?|confirmation)\b", re.I)
_PAYING_EN = re.compile(r"\b(?:pay|settle|transfer|wire|remit)\b", re.I)
_AFFORD = re.compile(r"\b(?:do|will|would) (?:i|my (?:money|balance|funds))\b[^?]{0,30}\b(?:enough|afford|cover|last|sufficient)\b|"
                     r"kitne din|kab tak chal|\bchalega\b", re.I)
_CONVERT_HI = re.compile(r"\b(?:rupa\w*|rupees?|inr|yuan|cny|rmb|lakh|hazaar|hazar)\b[^.\n]{0,30}\b(?:mein|me|se)\b[^.\n]{0,20}\b(?:badal|convert|change|exchange)\w*|"
                         r"\bhow many (?:yuan|cny|rmb|rupees?|inr)\b[^?]{0,40}\b(?:get|for|from)\b", re.I)
_WAIT_Q = re.compile(r"^(?:no,? )?(?:wait|hold on|hang on)\b[^.]*(?:\?|\bwhat\b|\bhow\b|\bwhich\b|\bwhen\b|\bwhy\b)", re.I)
_LATER = re.compile(r"\bremind me\b|\bset (?:a |an )?reminders?\b|\breminders? (?:for|to|about)\b|\bschedule\b[^.?!]{0,30}\b(?:rent|tuition|deposit|phone)|\bevery month\b|\beach month\b|\bauto-?pay\b|\bautomatic(?:ally)?\b|\bstanding (?:order|instruction)\b|\brecurring\b|\bnext month\b[^.?!]{0,20}\b(?:pay|payment)|提醒|每个?月|自动(?:付|交|扣|支付)|定期(?:付|交|支付)", re.I)
_LATER_Q = re.compile(r"\b(?:what|how much|how many|how long|when|which|list|show|tell me|explain)\b|\?\s*$", re.I)
_LATER_STRONG = re.compile(r"\bremind me (?:to|about|next|on|in)\b|\bset (?:a |an )?reminders?\b|\bschedule\b|\bauto-?pay\b|\bstanding (?:order|instruction)\b|提醒我|每个?月自动|自动(?:付|交|扣|支付)", re.I)
_LATER_BILL = re.compile(r"\bauto-?pay\b|\b(?:pay\w*|rent|tuition|deposit|bills?|fees?|phone)\b|房租|学费|押金|话费|付款|支付", re.I)
_ESTIMATE = re.compile(r"\bestimate\b|\bcalculat\w+|\bpreview\b|\bsimulate\b|\bwork out\b|how much (?:would|will|does|is) (?:it|that|this|the \w+|my \w+)[^?]{0,25}\b(?:cost|take)\b|how much (?:would|will|does)\b[^?]{0,30}\bcost\b|without (?:actually )?(?:paying|sending|pay)\b|before (?:i|we) (?:pay|send)\b|估算|预估|试算|先算|不付款", re.I)
_EST_BILL = re.compile(r"\brent\b|\btuition\b|\bdeposit\b|\bphone\b|\bmobile\b|房租|学费|押金|话费", re.I)
_THANKS = re.compile(r"^(?:(?:ok(?:ay)?|great|cool|alright)[, ]+)?(?:thanks|thank you|thank u|thx|ty|cheers|shukriya|dhanyavaad|多谢|谢谢|感谢)(?:\s+(?:a lot|so much|very much))?(?:[,\s]+(?:bye|goodbye|see you))?[\s!.。！]*$", re.I)
_RATE_ALERT = re.compile(r"\b(?:rate|price)\s+(?:alert|target|alarm|notification|trigger)|\b(?:alert|notify|ping) me\b[^.?!]{0,40}\brate|\bset (?:a |an )?alert\b|汇率提醒", re.I)
_CREDIT_GROWTH = re.compile(r"\bplan\b|growth|\bgrow\b|improve|build|milestone|opportunit|\bhow (?:can|do|should) i\b|next step|增长|成长|提升|建立|计划|规划", re.I)
_OWE_PAY = re.compile(r"\bi owe\b[^.?!]{0,40}\b(?:university|landlord|school|college)\b[^.?!]{0,40}\b(?:clear|pay|settle|sort)", re.I)
_SAFE_Q = re.compile(r"\bis (?:this|it|my money|my payment|the payment|my account) (?:safe|secure|legit|legitimate|a scam|trustworthy)\b|\bcan i trust (?:this|it|you|oasis)\b|\bis (?:this|it) (?:real|genuine)\b", re.I)
_SIGN_ASK = re.compile(r"^(?:please |pls |ok,? |okay,? )?(?:yes,? )?(?:sign|approve|authori[sz]e) (?:it|this|that)(?: now| please| pls)?[.!]*$", re.I)
_NEXT = re.compile(r"\bwhat (?:do|should|can|must) i (?:do|need to do)\b|\bwhat(?:'s| is) next\b|\bnext steps?\b|\bwhat now\b|\bab kya\b|接下来|下一步|怎么办", re.I)
_HOLD_Q = re.compile(r"(?:\bis held\b|\bwas held\b)[^.]*?(?:\?|\bwhy\b|\bwhat\b)", re.I)
_PHONE_BILL = re.compile(r"\bphone\b|\bmobile\b|\bsim\b|话费|手机费|深圳移动", re.I)
UNREGISTERED = re.compile(r"electric|\bwater\b|\bgas\b|internet|broadband|wi-?fi|phone|mobile|utilit|gym|membership|subscription|airline|flight|ticket|\bvisa\b|hospital|medical|clinic|insurance|credit card|"
                          r"\bfriend|external (?:bank|account)|room-?mate|flat-?mate|class-?mate|canteen|cafeteria|\bmess\b|meal card|电费|水费|燃气|煤气|网费|宽带|话费|水电|室友|同学|朋友|食堂|饭卡", re.I)
_INFO_CUE = re.compile(r"\b(?:how much|how many|how long|what|when|why|which|where|who|is it|are they|do i|did i|have i|am i|tell me|explain|show|list|about|mean|means|balance|rate|due date|status|kitna|kab|kya|paid|already|yesterday|received|was|were|didn'?t|don'?t|do not|won'?t|not)\b|多少|什么|为什么|哪|吗|已经|显示|查看|看看|列出|分类|统计|明细|详情|\bspending\b|\bview\b|\bdisplay\b|\bsummary\b|\boverdue\b|\bpast due\b|\bany (?:bills|dues)\b", re.I)
_PAY_CUE = re.compile(r"\b(?:pls|please|prep\w*|ready|again|same as|full|poora|pura|dena|dene|bhar\w*|bhej\w*|pay|paying|start|begin|set up|initiate|process|handle|chahiye)\b|帮|准备|办理|处理|交|付|缴|一下", re.I)
_VOCAB = ("pay", "rent", "tuition", "deposit", "cancel", "balance", "convert", "transfer", "landlord", "university")
_HINGLISH_PAY = re.compile(r"\b(?:bhej(?:o|na|de)?|bharo|bhar (?:do|de)|de do|dedo|de de|chukao|kar do|karo|dena hai|dene hai|bharna hai|bharni hai)\b", re.I)
_TYPO_MAP = {"pya": "pay", "pyay": "pay", "phne": "phone", "phoen": "phone", "bil": "bill", "rnet": "rent", "retn": "rent", "chen wie": "chen wei", "chne wei": "chen wei"}
_TYPO_SKIP = {"paid", "pays", "send", "sent", "rents", "fees", "bill", "dues", "last", "cancels", "cover", "urgent", "pays", "rental", "balances"}


_FILLER = re.compile(r"^(?:(?:hey|hi|hello|ok|okay|um+|uh+|er+|hmm+|fine|sorry|just|bhai|yaar|arre|bro|so|well|oh|right|alright|yo|oasis|quick (?:one|question|favou?r)|one more thing|btw|by the way)[,:!.\s-]+)+", re.I)


def strip_filler(norm: str) -> str:
    """'ok so, hi oasis - pay my rent' routes like 'pay my rent'. Only used after the security checks, so it can never hide an attack."""
    if _GREETING.match(norm):
        return norm
    t = _FILLER.sub("", norm)
    return t if t else norm


def fix_typos(norm: str) -> str:
    """Snap near-misses of a few core words ('paay', 'depsoit', 'rnet') onto the word; only used to route, after security checks."""
    norm = re.sub(r"\bchen wie\b|\bchne wei\b", "chen wei", norm)
    out = []
    for tok in norm.split(" "):
        w = tok.strip(".,!?;:").lower()
        if w in _TYPO_MAP:
            out.append(tok.replace(w, _TYPO_MAP[w]))
            continue
        if len(w) >= 4 and w not in _VOCAB and w not in _TYPO_SKIP and w.isalpha():
            m = [v for v in difflib.get_close_matches(w, _VOCAB, 3, 0.8) if v[0] == w[0] and abs(len(v) - len(w)) <= 1][:1]
            if m:
                tok = re.sub(re.escape(w), m[0], tok, flags=re.I)
        out.append(tok)
    return " ".join(out)


def classify(text: str, ui: str = "en") -> ChatIntent:
    lang = detect_lang(text, ui)
    raw = (text or "").strip()
    norm = normalise(raw)
    if not norm:
        return ChatIntent(HELP, {"empty": True}, 1.0, lang)
    # 1. a labelled invoice (Payee:/Account:/Amount: lines) goes to the pipeline, which is the thing that judges injected text
    if INVOICE_HINT.search(raw):
        return ChatIntent(PAY_INVOICE, {"labelled": True}, 1.0, lang)
    # 2. security first, on the normalised text and on anything hidden in base64
    snapped = snap_security(norm)
    for view in [strip_mentions(norm), *([strip_mentions(snapped)] if snapped != norm else []), *decoded_views(raw)]:
        cat = security_category(view)
        if cat:
            return ChatIntent(SECRETS if cat == "secrets" else BYPASS, {"urgent": bool(_URGENCY.search(norm))}, 1.0, lang, cat)
    if _RESET.search(_snap(norm, ("reset", "password", "passcode", "login"))):
        return ChatIntent(HELP, {"reset": True}, 0.9, lang)
    raw, norm = fix_typos(strip_filler(raw)), fix_typos(strip_filler(norm))
    if _INVOICE_WORD.search(raw) and re.search(r"\d{3,}", raw) and not _PAY_IMPERATIVE.search(norm):
        return ChatIntent(PAY_INVOICE, {"labelled": False}, 0.8, lang)       # the pipeline judges it, as for a labelled invoice
    m = TARGET_RE.search(raw)
    mz = None if m else TARGET_RE_ZH.search(raw)
    if m or mz:
        return ChatIntent(RATE_TARGET, {}, 1.0, lang)
    urgent = bool(_URGENCY.search(norm))
    acct = nl_extract.account_in_text(raw)
    if _RATE_ALERT.search(norm) and not acct and not _PAY_IMPERATIVE.search(norm) and not re.search(r"\b(?:what|which|show|list|view|do i have|any)\b", norm):                    # "set a rate alert at 0.072": needs an amount before it can be a target
        rm = re.search(r"(?<![\d.])(0\.\d{2,6})(?!\d)", norm)
        return ChatIntent(RATE_TARGET, {"incomplete": True, "rate": float(rm.group(1)) if rm else None}, 0.8, lang)
    # 3. dialogue acts that only make sense next to a pending draft or question
    if _CONFIRM.match(norm):
        return ChatIntent(CONFIRM, {}, 0.95, lang)
    if _DENY.match(norm):
        return ChatIntent(DENY, {}, 0.95, lang)
    if _CANCEL.search(norm) and not acct and not _CONVERT.search(norm) and not _WAIT_Q.search(norm) and not (_ESTIMATE.search(norm) and _EST_BILL.search(norm)):
        return ChatIntent(CANCEL, {}, 0.9, lang)
    # 4. an account number next to "use / instead / change / wrong" is an attempt to change where money goes: never from chat
    if acct and re.search(r"\b(?:use|instead|change|update|replace|switch|new account|wrong|correct)\b|改|换|更换|用这个|错|转到|汇到|付到", norm):
        a = _amount(raw)
        return ChatIntent(CORRECT, {"amount": a[0] if a else None, "currency": a[1] if a else None, "wants_account": True}, 0.9, lang)
    # 4b. a payment with an explicit account, or a plain "pay/send ..." request
    if acct and (_PAY_WORD.search(norm) or nl_extract.money(raw)):
        a = _amount(raw, bare=True)
        return ChatIntent(PAY_TEXT, {"amount": a[0] if a else None, "currency": a[1] if a else None, "account": acct,
                                     "urgent": urgent, "purpose": nl_extract.purpose_in_text(raw)}, 0.9, lang)
    if _CONVERT_HI.search(norm) and not acct:
        a = _amount(raw)
        return ChatIntent(CONVERT, {"amount": a[0] if a else None, "currency": a[1] if a else None}, 0.8, lang)
    if _RECEIPT_ASK.search(norm) and not _PAYING_EN.search(norm) and not nl_extract.money(raw):     # "send me the receipt" asks for a proof, it is not a payment
        return ChatIntent(PROOF, {}, 0.85, lang)
    if _AFFORD.search(norm):
        return ChatIntent(RUNWAY, {}, 0.85, lang)
    if _SAFE_Q.search(norm) and not acct and len(norm) <= 45:                 # a short "is this safe?"; a long story about a scam is not this question
        return ChatIntent(FAQ, {"topic": "safe"}, 0.8, lang)
    if _OWE_PAY.search(norm) and not acct:
        return ChatIntent(PAY_OBLIGATION, {"type": nl_extract.purpose_in_text(raw), "amount": None, "currency": None, "urgent": urgent, "fraction": None}, 0.8, lang)
    if (_LATER.search(norm) and _LATER_BILL.search(norm) and not acct and not _CONVERT.search(norm)
            and len(norm) <= 160 and chr(10) not in raw                                           # a pasted email that says "reminder" is an invoice, not a request
            and (_LATER_STRONG.search(norm) or (_PAY_IMPERATIVE.search(norm) and not _LATER_Q.search(norm)))):   # "remind me what my tuition is" asks, it does not ask for a reminder
        return ChatIntent(LATER, {"type": nl_extract.purpose_in_text(raw)}, 0.8, lang)
    if (_ESTIMATE.search(norm) and _EST_BILL.search(norm) and not acct and not _CONVERT.search(norm) and not _CORRECT.search(norm)
            and not re.search(r"\b(?:and|then)\s+(?:pay|send|settle)\b", norm)):                                # "calculate it and pay my rent" still pays
        a = _amount(raw)
        return ChatIntent(ESTIMATE, {"type": nl_extract.purpose_in_text(raw), "amount": a[0] if a else None}, 0.8, lang)
    if _CREDIT.search(norm) and _CREDIT_GROWTH.search(norm) and not acct and not _PAY_IMPERATIVE.search(norm):
        return ChatIntent(CREDIT, {"growth": True}, 0.8, lang)
    if _CORRECT.search(norm) and not _PAY_IMPERATIVE.search(norm):
        a = _amount(re.sub(r"[,;]?\s*(?:\d[\d,.]*k?\s*nahi|not|instead of|rather than)\b.*$", "", raw, flags=re.I), bare=True)
        return ChatIntent(CORRECT, {"amount": a[0] if a else None, "currency": a[1] if a else None,
                                    "wants_account": bool(re.search(r"account|payee|账号|账户|收款", norm))}, 0.85, lang)
    if _STATUS.search(norm) and re.search(r"到账|了吗|吗[？?]?$|有没有|是否|^(?:did|has|have|was|is|where)", norm):
        return ChatIntent(STATUS, {}, 0.85, lang)
    zh_q = bool(CJK.search(norm) and re.search(r"哪些|多少|回执|收据|证明|凭证|什么|吗|[?？]", norm) and not re.search(r"草稿|起草|帮我(?:付|交|缴|处理|办理)", norm))     # "我有哪些待付账单" asks about bills, it does not pay one
    if not zh_q and (_PAY_IMPERATIVE.search(norm) or _DUE_PAY.search(norm) or (_HINGLISH_PAY.search(norm) and _OBL_WORD.search(norm))             or (_OBL_WORD.search(norm) and nl_extract.money(raw) and re.search(r"\bko\b|को|给", norm) and "?" not in norm)             or (_PAY_WORD.search(norm) and _OBL_WORD.search(norm) and (not re.search(r"\bhow much\b|\bwhat\b|\bwhen\b|\bwhy\b|\bwhich\b|\bwill\b|\bwould\b|\bwhether\b|^if\b|\bif i\b|多少|为什么|什么时候|会不会|够不够", norm) or (CJK.search(norm) and re.search(r"草稿|起草", norm))))):
        if not _CONVERT.search(norm) or _OBL_WORD.search(norm):
            a = _amount(raw, bare=True)
            fr = _FRACTION.search(norm)
            return ChatIntent(PAY_OBLIGATION, {"type": nl_extract.purpose_in_text(raw), "amount": a[0] if a else None,
                                               "currency": a[1] if a else None, "urgent": urgent,
                                               "fraction": _FRACTION_V[fr.group(1) or fr.group(0)] if fr and not a else None}, 0.85, lang)
    # 4c. a bill named without a verb ("phone bill pls", "Rent time again"), or a bill type with no registered payee: a payment request,
    # unless the sentence asks, reports a past payment or says not to. The chat layer decides which bill; the draft still needs a signature.
    if not zh_q and not _INFO_CUE.search(norm) and not _NOPAY.search(norm):
        unreg = UNREGISTERED.search(norm) and not _PHONE_BILL.search(norm)
        bill = _OBL_WORD.search(norm) or _PHONE_BILL.search(norm) or unreg
        if bill and (_PAY_CUE.search(norm) or len(norm) <= 20) and not _CONVERT.search(norm):
            a = _amount(raw, bare=True)
            return ChatIntent(PAY_OBLIGATION, {"type": nl_extract.purpose_in_text(raw), "amount": a[0] if a else None,
                                               "currency": a[1] if a else None, "urgent": urgent, "fraction": None}, 0.7, lang)
    # 5. questions
    if _EXPLAIN.search(norm) or _HOLD_Q.search(norm):
        return ChatIntent(EXPLAIN, {}, 0.85, lang)
    if _NEXT.search(norm):
        return ChatIntent(HELP, {"next": True}, 0.85, lang)
    if _UNDO.search(norm):
        return ChatIntent(UNDO, {}, 0.85, lang)
    if re.search(r"\brates?\b|汇率", norm) and not nl_extract.money(raw):          # "exchange rate USD to CNY" asks for a rate, not a conversion
        return ChatIntent(RATE, {}, 0.85, lang)
    if _CONVERT.search(norm):
        a = _amount(raw)
        return ChatIntent(CONVERT, {"amount": a[0] if a else None, "currency": a[1] if a else None}, 0.85, lang)
    if _SPENDING.search(norm):
        return ChatIntent(SPENDING, {}, 0.8, lang)
    for kind, rx in ((RUNWAY, _RUNWAY), (STATUS, _STATUS), (BALANCE, _BALANCE), (OBLIGATIONS, _OBLIGATIONS), (ROUTES, _ROUTES_STRONG), (RATE, _RATE), (ROUTES, _ROUTES),
                     (PLAN, _PLAN), (PROOF, _PROOF), (CREDIT, _CREDIT)):
        if rx.search(norm):
            if kind == BALANCE and _OBL_WORD.search(norm) and re.search(r"\bleft (?:on|for|of|to pay)\b", norm):                 # "how much is left on my tuition" asks about a bill
                kind = OBLIGATIONS
            a = _amount(raw)
            return ChatIntent(kind, {"amount": a[0] if a else None, "currency": a[1] if a else None}, 0.8, lang)
    for topic, rx in _FAQ:
        if rx.search(norm):
            return ChatIntent(FAQ, {"topic": topic}, 0.85, lang)
    if _NOPAY.search(norm):
        return ChatIntent(NOPAY, {}, 0.7, lang)
    if _THANKS.match(norm):
        return ChatIntent(GREETING, {"thanks": True}, 1.0, lang)
    if _GREETING.match(norm) or _SMALLTALK.search(norm):
        return ChatIntent(GREETING, {}, 1.0, lang)
    if _HELP.search(norm):
        return ChatIntent(HELP, {}, 0.9, lang)
    if nl_extract.account_in_text(raw) is None and nl_extract.money(raw) and not _PAY_WORD.search(norm):
        return ChatIntent(UNKNOWN, {"amount": nl_extract.money(raw)[0]}, 0.3, lang)
    return ChatIntent(UNKNOWN, {}, 0.2, lang)
