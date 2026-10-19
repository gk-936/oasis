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
# sub-topic questions: every one is answer-only (no draft, no signature, no conversion, no money moves)
TRANSFER_ISSUE, FX_BILL, PARENT_REQUEST, QUOTA, SHARE_RECORD = "transfer_issue", "fx_bill", "parent_request", "quota", "share_record"
TOPIC_KINDS = (TRANSFER_ISSUE, FX_BILL, PARENT_REQUEST, QUOTA, SHARE_RECORD)
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
_HEX = re.compile(r"(?:[0-9a-fA-F]{2}){8,}")
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
    for m in _HEX.finditer(text or ""):          # the same trick written as hex digits
        try:
            s = bytes.fromhex(m.group(0)).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if len(s) >= 6 and all(c.isprintable() or c in "\n\t" for c in s):
            out.append(normalise(s))
    return out


# ------------------------------------------------------------------ security categories
_SECRET_WORDS = (r"pass ?code|password|passwd|\bpin\b|private key|signing key|secret key|api[ _-]?key|access key|secret|token|"
                 r"credential|\.env|aws|bedrock key|session (?:cookie|secret)|device key|seed phrase|mnemonic|"
                 r"system prompt|your prompt|your instructions|initial prompt|hidden prompt|prompt above|"
                 r"密码|口令|私钥|密钥|令牌|系统提示|提示词|你的指令|环境变量|(?<!付款)(?<!缴费)(?<!支付)(?<!转账)(?<!汇款)(?<!房租)(?<!学费)(?<!租金)(?<!交易)凭证|पासवर्ड|पासकोड|सीक्रेट")
_SECRETS_ASK = re.compile(rf"(?:{_SECRET_WORDS})", re.I)
_SECRETS_VERB = re.compile(r"(?:print|show|tell|reveal|give|send|share|leak|dump|display|repeat|output|read|find|config(?!uration)|stored|written down|what(?:'s| is| are)|list|export|"
                           r"confirm|provide|disclose|expose|paste|forward|"
                           r"告诉|显示|打印|泄露|给我|发给|是什么|输出|透露)", re.I)
_OTHER_USERS = re.compile(r"(?:other|another|all|every) (?:users?|students?|judges?|accounts?|sessions?|customers?)|(?:everyone|everybody|anyone|anybody)'?s? (?:else'?s? )?(?:payments?|accounts?|balances?|data|transactions?|details)|"
                          r"(?:someone|somebody) else'?s? (?:account|data|balance|payments?)|(?:其他|别人|所有)(?:用户|学生|账户|账号)", re.I)
_INJECTION = re.compile(
    r"ignore (?:all |any |the )?(?:previous|prior|above|earlier|your|these) (?:instructions?|rules?|prompts?|guidelines?|polic\w+)|ignore (?:everything|all|the) (?:above|before)\b|ignore the above|"
    r"ignore (?:all |any |the |your |these |my |safety |security |payment |approval )*(?:rules|instructions|guidelines|polic(?:y|ies)|checks|limits)\b|"
    r"disregard (?:all |any |the )?(?:previous|prior|above|your) |forget (?:all |your |the )?(?:previous |prior )?(?:instructions?|rules?)|"
    r"new instructions?:|system (?:note|message|override)|you (?:must|will) now|you are now|from now on you|act as (?:if|an?) |"
    r"pretend (?:to be|you)|role-?play|developer mode|dev mode|god mode|admin(?:istrator)? mode|debug mode|maintenance mode|"
    r"ignore (?:all |any )?(?:previous|prior) (?:safety |security )?(?:rules|instructions)|(?:reveal|print|show|display|dump)\b[^.?!]{0,25}\b(?:internal|hidden|system|your) (?:instructions|prompt|rules)|"
    r"jailbreak|\bdan\b|do anything now|sudo\b(?!\s+pay\b)|override (?:the )?(?:safety|security|policy|rules?|limit)|"
    r"忽略(?:以上|之前|上面|所有)?(?:的)?(?:指令|规则|提示)|忽略[^，。,.\s]{0,8}(?:规则|指令|提示|限制)|无视(?:以上|之前|所有)|开发者模式|管理员模式|调试模式|越狱|扮演", re.I)
_BYPASS = re.compile(
    r"(?:remove|drop|lift|delete|get rid of|waive) (?:the |my |a |any )?(?:(?:parent|mum|mom|dad|guardian)(?:'?s'?)? |parental )?(?:co-?approv\w*|approval|co-?sign\w*|co-?signature)\b|"
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
    r"(?:approve|sign|authori[sz]e) (?:it|this|that|them|the (?:draft|payment|transfer)) (?:yourself|by yourself|on your own)|(?:approve|sign|authori[sz]e) yourself|"
    r"as if you were me|impersonat\w+ (?:me|the student|my parent)|(?:^|[;,.]\s*|\b(?:please|pls)\s+|\b(?:can|could|would|will) you\s+)co-?sign[^.?!]{0,30}\b(?:for|on behalf of) (?:them|him|her|my (?:parent|mum|mom|dad|guardian))|"
    r"(?:instead of|rather than|not) (?:the )?(?:registered|registry|verified) (?:payee|recipient|account|university payee)|(?:replacement|new) account\b[^.?!]{0,60}\b(?:do not|don'?t|without) verif\w*|use the invoice'?s? (?:spelling|account|details|name)|look-?alike payee|不要用登记的|"
    r"(?:break|split|divide|chop|cut)\b[^.?!]{0,40}\b(?:chunks?|pieces|parts)\b[^.?!]{0,40}\b(?:under|below|beneath)\b|(?:separate|several|multiple) transfers\b[^.?!]{0,60}\b(?:look|so (?:that )?each)\b[^.?!]{0,10}\bsmall|"
    r"(?:change|edit|alter|forge|rewrite|fake|backdate)\b[^.?!]{0,30}\baudit\b|judge (?:powers?|rights?|access|role|mode)|(?:elevate|upgrade|escalate)\b[^.?!]{0,20}\b(?:role|privileges?|permissions?)\b|"
    r"pretend\b[^.?!]{0,30}\b(?:signed|approved|co-?sign\w*|authori[sz]ed)\b|(?:^|[;,.]\s*|\b(?:please|pls)\s+|\b(?:can|could|would|will) you\s+)(?:sign|approve)\b[^.?!]{0,10}\bfor (?:them|him|her|the student|my (?:parent|mum|mom|dad))\b|"
    r"\b(?:fake|forged?|dummy|stolen|borrowed) (?:device )?(?:key|signature|approval)\b|\b(?:reuse|replay|recycle)\b[^.?!]{0,25}\b(?:approval|signature)\b|"
    r"\b(?:change|swap|edit|replace|modify)\b[^.?!]{0,20}\bhash\b|\b(?:write|put|record|log|enter)\b[^.?!]{0,30}\b(?:successful|paid|approved)\b[^.?!]{0,30}\b(?:audit|log)\b|"
    r"\b(?:remove|delete|erase)\b[^.?!]{0,30}\b(?:from )?(?:the )?audit\b|\b(?:set|mark|make|change)\b[^.?!]{0,20}\bstatus\b[^.?!]{0,12}\b(?:to )?(?:paid|approved|verified)\b|"
    r"\b(?:switch|change|set|become)\b[^.?!]{0,25}\brole\b[^.?!]{0,10}\bto (?:parent|admin|judge)\b|"
    r"\b(?:raise|increase|lift|change|reduce|waive)\b[^.?!]{0,25}\b(?:parent|family)[- ]?(?:transfer )?(?:approval|limit|co-?approval)\b|\bavoids? (?:the )?parent\b|"
    r"\bparent (?:co-?)?approval (?:is )?not (?:needed|required)\b|\b(?:do not|don'?t|without) involv\w+ (?:my )?(?:parent|mum|mom|dad)\b|"
    r"\b(?:add|register|put)\b[^.?!]{0,20}\baccount\b[^.?!]{0,25}\b(?:registry|payees?)\b|"
    r"\b(?:harmless|innocent)[- ]looking\b|\b(?:smaller|little|tiny)\b[^.?!]{0,20}\b(?:chunks|payments|amounts|transfers)\b[^.?!]{0,40}\b(?:instead of one|under|below)\b|"
    r"\b(?:split|divide|break)\b[^.?!]{0,60}\bso\b[^.?!]{0,30}\b(?:approval|parent)\b|"
    r"\b(?:ai|assistant) operator\b|\bignore (?:the )?previous user\b|<script|\"role\"\s*:\s*\"system\"|\b(?:old|current) registry is (?:obsolete|outdated|wrong)\b|\byou may skip (?:the )?(?:review|check|approval)\b", re.I)
_REGISTRY_EDIT = re.compile(r"\b(?:add|create|register|insert|include|set up)\s+(?:a |an |the )?(?:new |another )?(?:payee|recipient|beneficiary|contact)\b|"
                            r"\b(?:remove|delete|erase|wipe|clear|edit|modify)\s+(?:a |an |the |my |all |every )?(?:payees?|recipients?|beneficiar\w+|registry|payment history|transaction history|transactions?|payment records?|history|audit(?: log| trail)?|logs?)\b|"
                            r"\b(?:add|register|save|set up)\b[^.?!]{0,40}\bas (?:a |my )?(?:new )?(?:payee|recipient|beneficiary|contact)\b|"
                            r"\b(?:remove|delete|erase|drop)\b[^.?!]{0,40}\b(?:from|in|off) (?:the |my )?(?:registry|payee list|payees)\b|"
                            r"添加.{0,4}(?:收款人|收款方)|新增.{0,4}(?:收款人|收款方)|删除.{0,6}(?:记录|历史|收款|日志)", re.I)
# marking a payee verified or editing its account from chat is a registry edit, not an approval bypass: the registry is the only way in
_PAYEE_VERIFY = re.compile(r"\bmark\b[^.?!]{0,30}\bpayee\b[^.?!]{0,25}\b(?:as )?(?:verified|trusted)\b|\bverify (?:this|the|that|my|a|new) (?:new )?payee\b|"
                           r"\bpayee\b[^.?!]{0,40}\bmark(?:ed)? (?:as )?verified\b|(?:标记|设为|设置为)[^。！？]{0,10}(?:已验证|验证通过)", re.I)
_PAYEE_EDIT = re.compile(r"\b(?:update|change|edit|modify|replace)\s+(?:the |my )?[\w.' -]{1,30}?'s (?:bank )?(?:account|details)(?: number| details)?\b[^.?!]{0,12}\bto\b|"
                         r"(?:修改|更改|更新)[^。！？]{0,12}(?:收款人|收款方)[^。！？]{0,6}(?:账号|账户)", re.I)
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


# ------------------------------------------------------------------ privacy (decided before every other check)
# Four kinds of request to hand over data that is not the student's own to see: a full third-party account number, another person's
# details, a raw log or dump, and an instruction (often inside pasted text) to send a secret or balance somewhere.
_SENS = (r"balance|passport|pass ?code|password|\bpin\b|private key|signing key|device key|secret|token|session|account (?:number|no\.?)|credentials?|"
         r"card (?:number|details)|\botp\b|api[ _-]?key|\bssn\b|aadhaar|statement|system prompt|instructions|余额|护照|口令|密码|密钥|私钥|令牌|账号|凭证")
_P_VERB = r"(?:print|show|give|tell|reveal|send|share|list|dump|display|read|paste|export|provide|spell|state|read out|what(?:'s| is| are)|告诉|显示|打印|给我|发给我|发我|列出|导出|透露|说出)"
_PEOPLE = r"(?:parents?|mother|father|mom|mum|dad|guardian|landlord|university|school|students?|teacher|professor|roommate|classmate|friend|payee|recipient|beneficiary|finance office|admin\w*|judge)"
_PRIV_ACCOUNT = re.compile(
    r"\bfull(?:y)? (?:bank )?account (?:number|no\b|details)|\b(?:complete|entire|whole|unmasked|unredacted|uncensored) (?:bank )?account\b|"
    r"\baccount (?:number |no\.? )?(?:in full|unmasked|without (?:the )?mask\w*)|\bwithout (?:the )?(?:mask\w*|asterisks|stars)\b|\bunmask\b|\ball (?:the )?digits\b|"
    r"\baccount\b[^.?!]{0,40}\bin full\b|\bin full\b[^.?!]{0,30}\baccount\b|\b(?:remove|drop|strip|lift|take off|turn off|disable)\b[^.?!]{0,15}\b(?:mask\w*|asterisks|redaction)\b|"
    rf"{_P_VERB}\b[^.?!]{{0,30}}\b{_PEOPLE}'?s?\b[^.?!]{{0,15}}\b(?:account|iban|swift|bank details|card)\b[^.?!]{{0,10}}\b(?:number|no\b|details)?|"
    r"完整(?:的)?.{0,4}(?:账号|账户|卡号)|全部(?:账号|账户|卡号)|(?:不要|别|去掉|取消)(?:打码|遮挡|隐藏|掩码)|(?:账号|账户)(?:的)?(?:全部|完整)", re.I)
_CONTACT = (r"(?:phone|mobile|cell|telephone|contact)(?: ?(?:number|no\.?|details|info\w*))?|(?:id|passport|aadhaar|ssn|visa|national id)(?: ?(?:number|no\.?|card|copy|details))?|"
            r"home address|address|e-?mail(?: address)?|wechat|whatsapp|\bdob\b|date of birth|bank details")
_PRIV_PARENT = re.compile(r"\b(?:parents?|mother|father|mom|mum|dad|guardian)(?:'s|s'|')\s+(?:\w+ ){0,2}(?:balance|savings|funds|salary|income|transactions?|bank account|account)\b|\b(?:balance|savings|funds|salary|income)\b (?:of|for) (?:my |the )?(?:parents?|mother|father|mom|mum|dad|guardian)\b|"
                          r"(?:家长|父母|妈妈|爸爸)(?:的)?(?:余额|存款|收入|工资|账户|账号)", re.I)       # a parent's money is the parent's own data, whoever asks
_PRIV_PERSON = re.compile(
    rf"\b{_PEOPLE}'?s? (?:\w+ ){{0,2}}(?:{_CONTACT})\b|\b(?:{_CONTACT})\b (?:of|for) (?:my |the )?{_PEOPLE}\b|"
    r"(?:家长|父母|妈妈|爸爸|房东|学校|大学|财务处|老师|室友|同学|收款人|收款方)(?:的)?(?:电话|手机|手机号|身份证|护照|地址|联系方式|邮箱|微信|银行卡)", re.I)
_PRIV_LOGS = re.compile(
    rf"{_P_VERB}\b[^.?!]{{0,25}}\b(?:full|entire|complete|whole|raw|unredacted|unmasked|all)\b[^.?!]{{0,20}}\b(?:logs?|audit|ledger|registry|database|db|records|history|trail|table|chats?)\b|"
    r"\b(?:full|entire|complete|whole|raw|unredacted) (?:\w+ )?(?:logs?|trail|dump)\b|\b(?:dump|export)\b[^.?!]{0,20}\b(?:the |your |all )?(?:database|db|registry|ledger|logs?|memory|sessions?|everything|all data)\b|"
    r"\b(?:transaction|payment|audit|chat|system|access) (?:logs?|history|records)\b[^.?!]{0,40}\bwith (?:the )?(?:full |complete |all )?(?:account|card)\b|"
    rf"{_P_VERB}\b[^.?!]{{0,10}}\b(?:the |your |whole |entire |full )?(?:payee )?registry\b|"
    r"\beverything (?:you|oasis) (?:know|have|store|hold|remember|keep)\b|\ball (?:the |my )?(?:data|information|details) (?:you|oasis) (?:have|store|hold|know|keep)\b|"
    r"完整(?:的)?(?:审计|交易|系统|操作)?(?:日志|记录|流水)|(?:导出|打印|显示|给我|发给我|列出|转储).{0,6}(?:全部|所有|完整).{0,6}(?:日志|记录|数据|登记册|数据库|账户|流水)|你(?:知道|掌握|保存)的.{0,4}(?:一切|所有)|所有(?:数据|信息)", re.I)
def _exfil_rx(_SENS: str):
    return re.compile(
        rf"\b(?:reply|respond|answer|write back)\b[^.?!]{{0,25}}\b(?:with|including|containing)\b[^.?!]{{0,40}}(?:{_SENS})|"
        rf"\b(?:send|e-?mail|mail|forward|text|post|transmit|upload|leak|message)\b[^.?!]{{0,60}}(?:{_SENS})[^.?!]{{0,60}}(?:\bto\b|\bat\b|\bvia\b)[^.?!]{{0,25}}(?:@|https?:|\.com|e-?mail|address|url|webhook|external|outside|\bme\b|\bus\b|\d{7,})|"
        rf"\b(?:send|e-?mail|mail|forward|text|post|transmit|upload|message)\b[^.?!]{{0,40}}\b(?:to|at)\b[^.?!]{{0,40}}(?:@|https?:)[^.?!]{{0,60}}(?:{_SENS})|"
        rf"\b(?:include|put|add|append|write|insert|type|enter|attach|paste|copy)\b[^.?!]{{0,50}}(?:{_SENS})[^.?!]{{0,30}}\b(?:in|into|inside|on|as|to)\b[^.?!]{{0,15}}\b(?:memo|reference|note|remark|comment|description|narrative|purpose|ledger|subject|body)\b|"
        rf"\b(?:in|into|inside) (?:the |your |a )?(?:memo|reference|note|remark|comment|description|narrative|purpose)\b[^.?!]{{0,30}}\b(?:include|put|add|append|write|insert|attach|paste)\b[^.?!]{{0,40}}(?:{_SENS})|"
        r"\bforward\b[^.?!]{0,30}\b(?:this |the |your |our )?(?:conversation|chat|logs?|history|prompt|statement)\b|"
    r"\b(?:send|e-?mail|mail|forward|upload|post)\b[^.?!]{0,30}\b(?:registry|audit log|logs?|database|ledger|chat history)\b[^.?!]{0,30}(?:@|https?:|\bto\b)|"
        rf"(?:回复|发送|发给(?!我)|转发|附上|附在|写在|写入|写进|放在|填入).{{0,20}}(?:{_SENS}).{{0,20}}|(?:{_SENS}).{{0,12}}(?:发送到|发给(?!我)|发至|写入备注|写在备注|放在备注|填入备注|回复)|备注.{{0,12}}(?:{_SENS})", re.I)


_PRIV_EXFIL = _exfil_rx(_SENS)
# a vendor invoice may legitimately mention "account number" or a "statement"; only the student's own secrets and balance count there
_PRIV_EXFIL_DOC = _exfil_rx(_SENS.replace(r"|account (?:number|no\.?)", "").replace("card (?:number|details)|", "").replace("|instructions", "").replace("|statement", "").replace("|账号", ""))


def privacy_kind(norm: str, doc: bool = False) -> str | None:
    """account | person | logs | exfil | None. Asking ABOUT these words is not enough; each pattern needs a reveal/send/include verb or a 'full' qualifier."""
    if (_PRIV_EXFIL_DOC if doc else _PRIV_EXFIL).search(norm):
        return "exfil"
    if doc:
        return None
    if _PRIV_PARENT.search(norm):
        return "parent"
    if _PRIV_ACCOUNT.search(norm):
        return "account"
    if _PRIV_PERSON.search(norm) and (re.search(_P_VERB, norm, re.I) or "?" in norm or len(norm) < 40):
        return "person"
    if _PRIV_LOGS.search(norm) or _OTHER_USERS.search(norm):
        return "logs"
    return None


# Asking ABOUT a sensitive concept is help; asking to REVEAL / PRINT / SEND / CHANGE one is not. Needs no reveal verb, no other person's
# secret and no encoding trick in the same message; every other security check still runs on top.
_S_NAME = r"(?:pass ?code|password|passwd|\bpin\b|(?:device|private|signing|secret|api|access) key|\bkeys?\b|token|credentials?|login|seed phrase|密码|口令|密钥|私钥|设备密钥|令牌|凭证)"
_CONCEPT_Q = re.compile(
    rf"\b(?:do|does|will|would|must|should|can) (?:i|we) (?:need|have to|require|use|set|create|get|find|change|reset|recover|know)\b[^.?!]{{0,30}}{_S_NAME}|"
    rf"{_S_NAME}\s*(?:\w+\s+)?(?:u|you|i|we) (?:need|require)\b|\bis (?:a |an |the |my |this )?{_S_NAME}s? (?:needed|required|necessary|safe|secure|private|encrypted|stored safely|protected)\b|"
    rf"\b(?:is|are) (?:my |the )?{_S_NAME}s? (?:safe|secure|protected|private)\b|\bwho (?:can|could|will|would) (?:see|access|read|know)\b[^.?!]{{0,20}}{_S_NAME}|"
    rf"\bhow (?:does|do|is|are) (?:a |an |the |my )?(?:\w+ )?{_S_NAME}|\bwhat(?:'s| is| are) (?:a|an|the purpose of|the point of) {_S_NAME}|\bwhat (?:does|do) (?:a |an |the |my )?(?:\w+ )?{_S_NAME} (?:mean|do|for)\b|"
    rf"\bwhy (?:do|does|is|are|must|should) (?:i|we|it|oasis|the)\b[^.?!]{{0,30}}(?:need|have to|required|sign|{_S_NAME})|\bhow (?:do|can|should|does|to) (?:i|we|one|you)?\s?(?:\w+ ){{0,3}}(?:use|set up|set|create|get|find|change|reset|recover|replace|protect|keep|store|secure|log ?in|register)\b[^.?!]{{0,30}}{_S_NAME}|"
    rf"\b(?:forgot|forgotten|lost|misplaced|reset|recover)\b[^.?!]{{0,25}}{_S_NAME}|{_S_NAME}\s*(?:kya|kaise|kyun)\b|"
    r"(?:密码|口令|密钥|私钥|设备密钥).{0,6}(?:忘|丢|怎么办|怎么|如何|需要吗|要吗|安全吗|吗)|(?:需要|要).{0,4}(?:口令|密码|密钥)吗|什么是.{0,6}(?:口令|密码|密钥|私钥|设备密钥|令牌)|(?:如何|怎么|怎样).{0,10}(?:口令|密码|密钥|私钥|设备密钥)|为什么.{0,8}(?:签名|口令|密钥)|忘(?:了|记).{0,4}(?:口令|密码|密钥)", re.I)
_REVEAL_STRICT = re.compile(r"\b(?:print|show|tell|reveal|give|send|share|leak|dump|display|repeat|output|read(?: out)?|export|list|paste|spell|whisper|disclose|expose|provide|forward|email|text)\b|告诉|显示|打印|泄露|给我|发给|输出|透露|发我|说出|告知", re.I)
_S_STRICT = _S_NAME.replace("|login", "")
_OTHER_SECRET = re.compile(rf"\b(?:parents?|mother|father|mom|mum|dad|guardian|admin\w*|judge|teacher|landlord|bank|his|her|their|someone|somebody|another|other|everyone)'?s?\b[^.?!]{{0,12}}{_S_STRICT}|"
                           r"(?:家长|父母|管理员|别人|其他人|他的|她的|对方)(?:的)?(?:口令|密码|密钥|私钥|令牌)", re.I)
_ENCODING = re.compile(r"\b(?:base64|b64|hex|rot ?13|binary|reversed?|backwards|encoded?|encrypted|cipher|morse|spelled|letter by letter|char\w* by char\w*|acrostic|pig latin|leet)\b|编码|加密|倒过来|逐字", re.I)
_PAYSTYLE = re.compile(r"\b(?:ignore|bypass|override|jailbreak|pretend|developer mode|admin mode)\b|忽略|绕过", re.I)


def concept_help(norm: str) -> str | None:
    """device_key | sign | safe | login | forgot | None: a question ABOUT a secret, not a request for one."""
    if not _CONCEPT_Q.search(norm) or _REVEAL_STRICT.search(norm) or _OTHER_SECRET.search(norm) or _ENCODING.search(norm) or _PAYSTYLE.search(norm):
        return None
    if re.search(r"\bwhat(?:'s| is| are) (?:a|an|the (?:purpose|point) of)\b|什么是", norm) and re.search(r"device key|设备密钥|密钥|\bkeys?\b", norm):
        return "device_key"
    if re.search(r"\bwhy\b[^.?!]{0,30}\bsign|为什么.{0,8}签名", norm):
        return "sign"
    if re.search(r"\b(?:safe|secure|protected|private|encrypted)\b|安全吗", norm):
        return "safe"
    if re.search(r"forgot|forgotten|lost|misplaced|reset|recover|忘|丢|怎么办|重置|找回", norm):
        return "forgot"
    if re.search(r"device key|设备密钥", norm):
        return "device_key"
    return "login"


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


_LEET = str.maketrans("013457", "oieast")


def snap_security(norm: str) -> str:
    """Typos in an attack ('ignroe', 'passcod', 'apprval') are snapped onto the attack vocabulary so the same patterns apply. Used only as an EXTRA
    view for the security check, so it can only add refusals; routing of ordinary messages never sees it."""
    out = []
    for tok in norm.split(" "):
        w = tok.strip(".,!?;:'\"")
        if len(w) >= 5 and w.isalnum() and not w.isalpha() and not w.isdigit():       # 'p4sscode', 'pr1nt': digits standing in for letters
            deleet = w.translate(_LEET)
            if deleet.isalpha():
                tok, w = tok.replace(w, deleet), deleet
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
    """privacy | secrets | injection | bypass | registry | role | social | None, for a normalised message."""
    norm = _drop_negated(norm)
    if privacy_kind(norm):                  # decided before any other intent
        return "privacy"
    # asking HOW to reset a login is help, not a request to reveal one; every other check below still applies
    asked = re.sub(r"\bwithout (?:sending|giving|telling|sharing|showing|revealing)[^.?!]{0,30}|\bwhere is\b", "", _snap(norm, _EXEMPT_WORDS))
    asked = _HOWTO.sub(" ", asked)
    reset_help = bool(_RESET.search(_snap(norm, ("reset", "password", "passcode", "login")))) and not _SECRETS_VERB.search(asked)
    plain = _HOWTO.sub(" ", norm)           # "tell me the recovery steps" asks for steps, not for a secret
    reset_help = reset_help or bool(_SECURITY_QA.search(norm) and not _SECRETS_VERB.search(plain) and not _REVEAL.search(plain))
    reset_help = reset_help or bool(concept_help(norm))
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
    if _REGISTRY_EDIT.search(norm) or _PAYEE_VERIFY.search(norm):        # before the bypass check: "add payee Bob, mark as verified" is a registry edit
        return "registry"
    if _bypass_asked(norm):
        return "bypass"
    if _PAYEE_EDIT.search(norm):
        return "registry"
    return None


def refusal_detail(view: str, cat: str) -> str:
    """Which thing was asked for, so the refusal can name it. Wording only: it never changes the decision."""
    if cat == "privacy":
        return privacy_kind(_drop_negated(view)) or "logs"
    if cat == "secrets":
        if _OTHER_SECRET.search(view):
            return "other_secret"
        for key, rx in (("prompt", r"prompt|instructions|系统提示|提示词|你的指令"), ("token", r"token|session|cookie|令牌"),
                        ("passcode", r"pass ?code|password|passwd|\bpin\b|密码|口令|पासवर्ड|पासकोड"), ("key", r"key|seed|mnemonic|私钥|密钥|\.env|aws|credential|凭证|secret")):
            if re.search(rx, view):
                return key
        return "key"
    if cat == "registry":
        if re.search(r"audit|logs?\b|history|trail|日志|历史|记录", view):
            return "audit"
        if re.search(r"verif|trusted|已验证|验证", view):
            return "verify"
        if re.search(r"account|details|账号|账户", view):
            return "account"
        return "payee"
    if cat == "role":
        m = re.search(r"parent|guardian|mother|father|mom|dad|admin\w*|judge|bank|teacher|owner|developer|operator|support|家长|父母|管理员|银行|老师|开发者", view)
        return m.group(0) if m else "other"
    if cat == "bypass":
        if re.search(r"skip|bypass|disable|turn off|waive|without|no need|don.t need|绕过|跳过|无需|不用|关闭", view):
            return "check"
        if re.search(r"limit|cap|threshold|chunks?|pieces|split|额度", view):
            return "limit"
        if re.search(r"audit|hash|status|paid|released?|mark", view):
            return "record"
        if re.search(r"sign|approv|批准|签名|co-?sign", view):
            return "sign"
        return "check"
    return ""


# ------------------------------------------------------------------ everyday intents
_PAY_IMPERATIVE = re.compile(
    r"^(?:(?:please|kindly|pls|can you|could you|would you|i (?:want|need|have|would like) to|i'?d like to|let'?s|go ahead and|help me|lets)\s+)*"
    r"(?:pay|settle|clear|send|transfer|remit|wire|cover|prepare|draft|sort(?: out)?|set up|make (?:a |the )?payment)\b|^(?:请|帮我|麻烦|我要|我想|我需要)?(?:帮我)?(?:交|付|缴|支付|转账|汇款|转|起草|准备|给[^，。！？]{0,8}(?:付|交|缴|转|汇))", re.I)
_PAY_WORD = re.compile(r"\b(?:pay|paying|settle|clear|send|transfer|remit|wire|cover|prepare|draft|bana do|banao)\b|草稿|给|交|付|缴|支付|转账|汇款|起草|处理|办理", re.I)
_OBL_WORD = re.compile(r"\brent\b|kiraya|kiraaya|किराया|tuition|deposit|fees?\b|bills?\b|dues?\b|房租|租金|学费|押金|账单|费用", re.I)
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
                      r"what happened|why it (?:was|is|got)\b[^?]{0,30}(?:held|stopp|block|reject|refus|declin|flag|frozen)|explain (?:the|that|this|why)|why (?:are|do|am) (?:you|i)[^?]{0,40}(?:signature|sign|approv|confirm|asking)|why (?:can'?t|couldn'?t|won'?t) (?:i|you)|为什么[^？?]{0,20}(?:拦截|拒绝|冻结|暂缓|阻止|不能)|怎么回事|解释", re.I)
_PROOF = re.compile(r"\bproofs?\b|\breceipts?\b|\bevidence\b|\bverify (?:the )?payment\b|证明|凭证|回执|回单|收据", re.I)
_CREDIT = re.compile(r"\bcredit\b|trust pass|\breputation\b|build (?:my )?(?:history|record|trust)|信用|信誉", re.I)
_STATUS = re.compile(r"(?:where|how) (?:does|do|is|are) (?:my|the)[^?]{0,25}(?:payment|transfer|bill|rent|tuition)[^?]{0,10}(?:stand|standing)|(?:did|has|have|was|is)[^?]{0,40}(?:go through|gone through|arrive|arrived|get paid|got paid|been paid|sent|paid|received|land|landed|reach)|"
                     r"where(?:'s| is| are)[^?]{0,20}(?:my )?(?:money|payment|transfer|funds)|(?:payment|transfer) status|\bstatus\b|(?<!what is )(?<!whats )(?<!what's )\bpending\b|paid yet|"
                     r"\bwas it waiting\b|waiting for (?:the |my )?(?:device )?signature|到账|付了吗|付款了吗|进度|状态|有没有付|是否已付|支付成功|结清|付了没|交了没|到了没|完成了没|成功了没|转账完成|付款完成|支付完成|进展", re.I)
_OWING = re.compile(r"\b(?:pending|unpaid|outstanding|still open|left to pay|still owe|owed|owing)\b|没结清|未结清|尚未结清|没付清|还没付|没缴|没交|还有哪些|尚未|待付|待缴|还欠", re.I)
_SENT = re.compile(r"\b(?:sent|transfer(?:red)?|remittance|wire|arrived|received|went through|go through|reach(?:ed)?|credited)\b|汇款|转账|到账|收到", re.I)
_APPROVAL = re.compile(r"\b(?:approval|signature|signed|sign)\b|审批|签名|批准", re.I)
_RUNWAY = re.compile(r"kitne din|kab tak chal|\bchalega\b|\bhave enough\b|enough to (?:cover|pay)|run out|(?:money|funds|cash|savings) (?:will )?(?:last|run)|will (?:my )?(?:money|funds|cash|savings) last|runway|how long (?:will|can|do)|last me|(?:enough|sufficient) (?:money|funds|cash)|will i (?:have|be) (?:able|enough)|"
                     r"going to (?:run|be) (?:out|short|broke)|afford|够用|撑多久|够不够|用完|还能用|撑到|熬到|能撑|撑得|资金跑道|how far will (?:my )?(?:money|balance|funds|savings)|keep going|够到|\b(?:can|will|could|would) (?:my )?(?:money|funds|savings|cash|balance)\b[^?.]{0,20}\b(?:cover|last|stretch|carry|get me)\b|\bmake it (?:to|through|until|till)\b|\bcarry me\b|\bsurvive\b|\b(?:till|until|through) (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*|\benough (?:for|to|till|until|through)\b|\bhow many months\b|够用到|撑到|够不够|撑得|支撑|\b(?:my )?(?:money|funds|savings|cash|balance) (?:can|will|could|would) (?:cover|last|stretch|carry)\b", re.I)
_BALANCE = re.compile(r"(?:paisa|paise|balance) kitna|kitna (?:paisa|paise|bacha)|how much (?:money|cash|do i have\b(?! to)|have i got|is (?:in|left))|how much (?:\w+ ){0,2}(?:do )?i (?:have|got|have got|still have)\b(?! to)|how much (?:\w+ )?(?:is )?left\b|\bbalance|\bmy (?:funds|money|savings|wallet)\b|\bwhat do i have\b|\b(?:cny|inr|yuan|rupee) wallet\b|"
                      r"how much (?:is )?left|what(?:'s| is)? (?:remains?|left)|\bremain(?:s|ing)?\b[^?]{0,30}(?:wallet|balance|account)|\b(?:my|student|sandbox) (?:student |sandbox )?wallet\b|余额|还有多少钱|有多少钱|还剩|剩多少|账户里", re.I)
_OBLIGATIONS = re.compile(r"没交|未交|没有支付|未支付|还没(?:有)?(?:付|支付|交|缴)|欠多少|\boverdue\b|\bpast due\b|截止|截至|哪天|几号|\b(?:bill|rent|tuition|fees?|deposit)\s+(?:ka\s+)?kitna\b|\bkitna\s+(?:baaki|baki|bacha|dena|dene)\b|how much (?:is|are|do i (?:owe|pay)|do i (?:have|need) to pay|must i pay|should i pay)[^?]{0,20}(?:rent|tuition|deposit|fees?|bills?)|what (?:do i|i) owe|how much (?:do )?i (?:still )?owe|how much (?:is )?(?:still )?(?:due|owed)|what(?:'s| is| are) (?:due|owed|upcoming|coming up)|\bupcoming\b|\bbills\b|\bobligations?\b|\bdue (?:soon|date|dates)\b|"
                          r"when (?:is|are)[^?]{0,30}due|(?:what|which) (?:payments|bills)|应付|要付|欠|到期|待付|哪些费用|哪些账单|什么账单|要交什么|交什么钱|什么(?:钱)?没(?:付|交|缴)|没(?:付|交|缴)的", re.I)
_SPENDING = re.compile(r"\b(?:what|how much) (?:did|have) i (?:spend|spent|paid|pay)\b|\bmy (?:spending|expenses|transactions)\b|\b(?:pichla|last|previous|recent) transactions?\b|\bspending\b|\bexpenses?\b|"
                       r"\btransaction (?:history|list)\b|where (?:did|does) my money go|花了多少|花销|开销|消费|支出|\balready paid\b|\bwhich (?:bills|fees|payments)\b[^?]{0,25}\b(?:already|have i|did i)\b|已经付过|付过哪些|已付", re.I)
_FRACTION = re.compile(r"\b(half|a third|one third|a quarter|one quarter|quarter)\b(?: of)?|一半", re.I)
_FRACTION_V = {"half": 0.5, "a third": 1 / 3, "one third": 1 / 3, "a quarter": 0.25, "one quarter": 0.25, "quarter": 0.25, "一半": 0.5}
_RATE = re.compile(r"\b(?:exchange |fx |forex |conversion )?rates?\b|inr (?:to|/|-|→) ?cny|cny (?:to|/) ?inr|how many (?:yuan|cny|rmb) (?:per|for|is)|汇率|兑换率|换汇率", re.I)
_ROUTES = re.compile(r"cheap\w*|best (?:way|route|option|rail)|which (?:route|way|rail|option|app)|\broutes?\b|how (?:should|do|can) i (?:send|transfer|move|remit)|"
                     r"\bfees?\b(?! due)|compare|fastest|路线|最便宜|怎么汇|怎么转|哪种方式|手续费", re.I)
_ROUTES_STRONG = re.compile(r"cheap\w*|best (?:transfer |payment )?(?:way|route|option|rail|method)|\broutes?\b|fastest|how (?:should|do|can) i (?:send|transfer|move|remit)|路线|最便宜|通道|渠道|哪种方式|方式是什么|最短|最快|最划算|最省", re.I)
_PLAN = re.compile(r"\bplan\b|\bbudget\b|semester|schedule my|规划|计划|预算", re.I)
_PLAN_STRONG = re.compile(r"\bschedule\b|\bbest order\b|\border to pay\b|\bsequence\b|run short|方案|不超支|安排|不会缺钱|顺序|排期", re.I)
_CONVERT = re.compile(r"\b(?:inr|cny|rmb|usd|eur|gbp)\b[^.\n]{0,25}\b(?:mein|me|to|into|ko)\b[^.\n]{0,25}\b(?:quote|convert|exchange)\b|\b(?:convert|exchange|swap|change|quote)\b[^.\n]{0,40}(?:inr|cny|rmb|usd|eur|gbp|aud|jpy|rupees?|yuan|dollars?|euros?|pounds?|₹|¥|\$|€|£)|how much is[^?]{0,30}(?:inr|cny|rmb)[^?]{0,10}in (?:inr|cny|rmb)|(?<![\w.])\d[\d,]*(?:\.\d+)?\s*(?:inr|cny|rmb|usd|eur|gbp)\s+(?:in|into)\s+(?:inr|cny|rmb|usd|eur|gbp)\b|\b(?:move|put|turn|shift|swap)\b[^.\n]{0,30}\b(?:inr|rupees?)\b[^.\n]{0,15}\b(?:into|to)\b[^.\n]{0,10}\b(?:cny|rmb|yuan)\b|兑换|换成|换汇|转换|换算|\b(?:switch|make|put|turn|move)\b[^.\n]{0,30}\b(?:rupees?|inr)\b[^.\n]{0,25}\b(?:yuan|cny|rmb|wallet)\b|\bcurrency (?:exchange|swap|conversion)\b|\b(?:want|need) (?:yuan|cny|rmb)\b[^.\n]{0,20}\binstead of\b|换点|兑成|\b(?:convert|change|swap|exchange)\b[^.\n]{0,25}\b(?:my )?(?:balance|savings|funds|wallet)\b", re.I)
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
_RATE_ALERT = re.compile(r"\b(?:rate|price)\s+(?:alert|target|alarm|notification|trigger)|\b(?:alert|notify|ping) me\b[^.?!]{0,40}\brate|\bset (?:a |an )?alert\b|汇率提醒|"
    r"\b(?:alert|notify|ping|remind|wake) me\b[^.?!]{0,40}\b(?:rate|exchange rate)\b|\b(?:rate|exchange rate)\b[^.?!]{0,50}\b(?:let me know|tell me|ping me|notify me|alert me|remind me|wake me|call me)\b|"
    r"\b(?:watch|monitor|track|keep an eye on|follow)\b[^.?!]{0,25}\b(?:the )?(?:exchange )?rate\b|\brate (?:watcher|watch|monitor|threshold|trigger|target|alarm)\b|"
    r"\b(?:i want|i'd like|i would like) (?:an? )?(?:alert|notification)\b[^.?!]{0,30}\brate\b|\b(?:convert|buy|exchange)\b[^.?!]{0,30}\b(?:when|once|if)\b[^.?!]{0,20}\brate\b|"
    r"\bset (?:a )?target\b[^.?!]{0,20}\brate\b|\bautomatically convert\b|\bwhen (?:the )?rate\b[^.?!]{0,30}\b(?:hits|reaches|crosses|gets|improves|is)\b|\bnotify me (?:at|when|if)\b|"
    r"汇率[^。！？]{0,14}(?:提醒|通知|告诉|叫我|预警|触发|监控|目标|阈值)|(?:提醒|通知|告诉|叫|盯|监控|关注)[^。！？]{0,10}汇率|设[^。！？]{0,4}汇率|汇率目标|"
    r"汇率[^。！？]{0,6}(?:涨到|高于|低于)\s*[\d.]+|"
    r"汇率[^。！？]{0,6}(?:好|合适|不错)[^。！？]{0,3}(?:的时候|时)|自动兑换|自动换汇|\balert\b[^.?!]{0,20}\b(?:if|when)\b[^.?!]{0,30}\b(?:rate|reaches|drops|rises|hits|crosses)\b|"
    r"\b(?:inr|cny)\b[^.?!]{0,15}\b(?:reaches|hits|crosses|drops below|rises above)\b|"
    r"\b(?:notify|alert|tell|let|ping|remind|wake)\b[^.?!]{0,25}\b(?:when|once|if)\b[^.?!]{0,40}\b(?:rate|rupee|yuan|rmb|inr|cny)\b|\btell me (?:when|once|if)\b[^.?!]{0,40}\brate\b|"
    r"\b(?:notified|notify|alerted|alert)\b[^.?!]{0,15}\babout\b[^.?!]{0,10}\brate\b|\bonce the rate\b|"
    r"(?:提醒|通知|告诉)[^。！？]{0,6}(?:我)?[^。！？]{0,6}汇率|汇率[^。！？]{0,8}(?:好了|变好|到了|达到)[^。！？]{0,4}(?:提醒|通知|告诉|叫)", re.I)
_CREDIT_GROWTH = re.compile(r"\bplan\b|growth|\bgrow\b|improve|build|milestone|opportunit|\bhow (?:can|do|should) i\b|next step|增长|成长|提升|建立|计划|规划", re.I)
_OWE_PAY = re.compile(r"\bi owe\b[^.?!]{0,40}\b(?:university|landlord|school|college)\b[^.?!]{0,40}\b(?:clear|pay|settle|sort)", re.I)
_SAFE_Q = re.compile(r"\bis (?:this|it|my money|my payment|the payment|my account) (?:safe|secure|legit|legitimate|a scam|trustworthy)\b|\bcan i trust (?:this|it|you|oasis)\b|\bis (?:this|it) (?:real|genuine)\b", re.I)
_SIGN_ASK = re.compile(r"^(?:please |pls |ok,? |okay,? )?(?:yes,? )?(?:sign|approve|authori[sz]e) (?:it|this|that)(?: now| please| pls)?[.!]*$", re.I)
_NEXT = re.compile(r"\bwhat (?:do|should|can|must) i (?:do|need to do)\b|\bwhat(?:'s| is) next\b|\bnext steps?\b|\bwhat now\b|\bab kya\b|接下来|下一步|怎么办", re.I)
_HOLD_Q = re.compile(r"(?:\bis held\b|\bwas held\b)[^.]*?(?:\?|\bwhy\b|\bwhat\b)", re.I)
_PHONE_BILL = re.compile(r"\bphone\b|\bmobile\b|\bsim\b|话费|手机费|深圳移动", re.I)
UNREGISTERED = re.compile(r"electric|\bwater\b|\bgas\b|internet|broadband|wi-?fi|phone|mobile|utilit|gym|membership|subscription|airline|flight|ticket|\bvisa\b|hospital|medical|clinic|insurance|credit card|"
                          r"\bfriend|external (?:bank|account)|room-?mate|flat-?mate|class-?mate|canteen|cafeteria|\bmess\b|meal card|电费|水费|燃气|煤气|网费|宽带|话费|水电|室友|同学|朋友|食堂|饭卡", re.I)
_INFO_CUE = re.compile(r"\b(?:how much|how many|how long|what|when|why|which|where|who|is it|are they|do i|did i|have i|am i|tell me|explain|show|list|about|mean|means|balance|rate|due date|status|kitna|kab|kya|paid|already|yesterday|received|was|were|didn'?t|don'?t|do not|won'?t|not)\b|多少|什么|为什么|哪|吗|已经|显示|查看|看看|列出|分类|统计|明细|详情|\bspending\b|\bview\b|\bdisplay\b|\bsummary\b|\boverdue\b|\bpast due\b|\bany (?:bills|dues)\b|\bdeadlines?\b|逾期|待缴|未缴|\banything\b|\bsoon\b|^(?:do you|does|has|have|is|are|was|were)\b|\b(?:finished|completed|handle|accept|support|recommend)\b", re.I)
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


_XFER_WORD = r"(?:transfers?|remittances?|payments?|wires?|money)"
# no bare "late" or "stuck" and no "where is my money": those stay with status or the labeller (see the chat-LLM benchmark set)
_TRANSFER_ISSUE = re.compile(
    rf"\b{_XFER_WORD}\b[^.?!]{{0,45}}\b(?:is |was |got |has been |been )?(?:delayed|rejected|returned|bounced|declined|failed|never (?:arrived|reached)|"
    r"(?:has not|hasn'?t|have not|haven'?t|did not|didn'?t|not) (?:yet )?(?:arrived?|reach(?:ed)?|come|credited|show(?:n)? up)|came back|went missing)\b"
    r"|\b(?:received|got|credited|arrived)\b[^.?!]{0,25}\b(?:less|short|only part|a smaller amount|not the full)\b[^.?!]{0,30}\b(?:than|money|amount|sent)\b"
    rf"|\b{_XFER_WORD}\b[^.?!]{{0,20}}\b(?:arrived|came|was credited|got credited)\b[^.?!]{{0,10}}\bshort\b"
    r"|\b(?:says?|said|told me|claims?)\b[^.?!]{0,40}\b(?:received|got)\b[^.?!]{0,20}\b(?:less|nothing|short)\b"
    r"|\b(?:never|didn'?t|did not) (?:showed? up|show up|arrive|arrived)\b|\bnothing (?:has )?arrived\b|"
    r"\b(?:recipient|school|university|landlord|they|he|she|them)\b[^.?!]{0,20}\b(?:hasn'?t|has not|haven'?t|have not|still hasn'?t|still haven'?t)\b[^.?!]{0,10}\b(?:received|got|gotten)\b|"
    r"\b(?:hasn'?t|has not|haven'?t|have not|not)\b[^.?!]{0,10}\b(?:arrived|reached)\b[^.?!]{0,20}\b(?:after|for|in)\b[^.?!]{0,10}\b(?:days?|weeks?)\b|"
    r"\b(?:been|it'?s been)\b[^.?!]{0,15}\b(?:days?|weeks?)\b[^.?!]{0,40}\b(?:not|hasn'?t|haven'?t|nothing|never)\b|"
    r"\b(?:credited|received|arrived)\b[^.?!]{0,20}\b(?:lower|smaller|less)\b|\b(?:extra|hidden) fees?\b[^.?!]{0,30}\b(?:short|less|lower)\b|"
    r"(?:汇款|转账|付款|钱)[^。！？]{0,8}(?:卡住|不见了|丢了|没到|没有到|迟迟|异常|被驳回|被退回|少到|少了)|(?:到账|收到)[^。！？]{0,8}(?:比|少于|不足|只有|只收到)|只收到[^。！？]{0,6}(?:一半|部分)|被多扣|(?:还)?没(?:有)?到账|还没收到|没收到(?:钱|款|汇款|转账)|(?:到账|金额)[^。！？]{0,4}少了?|\bdelayed (?:transfers?|payments?|remittances?|wires?)\b"
    r"|\b(?:says?|said|told me|claims?)\b[^.?!]{0,40}\bonly (?:received|got)\b|\b(?:credited|arrived|came through|received) short\b|\bshort[- ]credit\w*"
    r"|\b(?:landlord|university|school|college|payee)\b[^.?!]{0,25}\b(?:got|received|gets)\b[^.?!]{0,10}\bless\b"
    r"|\b(?:only (?:part|some|half)|part) of (?:the |my )?(?:payment|transfer|money|rent|tuition)\b[^.?!]{0,20}\b(?:arrived|came|reached|was received|got there)\b"
    r"|\b(?:bounced|bounce)\b[^.?!]{0,20}\b(?:back|payment|transfer)\b|\b(?:has not|hasn'?t|have not|haven'?t|did not|didn'?t) (?:yet )?(?:seen|received|got)\b[^.?!]{0,15}\b(?:the )?(?:funds|money|payment|transfer)\b"
    r"|\b(?:should i|shall i)\b[^.?!]{0,15}\b(?:re-?send|send|pay|transfer)\b[^.?!]{0,30}\bagain\b|\bre-?send\b"
    r"|\b(?:transfers?|remittances?)\b[^.?!]{0,30}\b(?:is|was|seems|looks) (?:very |really )?late\b"
    r"|\b(?:track|trace|follow|locate)\b[^.?!]{0,15}\b(?:my |the |this )?(?:transfers?|payments?|remittances?)\b"
    r"|\bwhere(?:'s| is) my (?:transfer|remittance)\b"
    r"|汇款[^。！？]{0,6}(?:延迟|没到|未到账|被拒|被退回|失败|少了)|转账[^。！？]{0,6}(?:延迟|没到|未到账|被拒|被退回|失败|少了)|没收到(?:汇款|转账|钱)|追踪(?:我的)?(?:汇款|转账|付款)", re.I)
_FX_BILL = re.compile(
    r"\b(?:bill|invoice|fee|fees|charge|registration|subscription)\b[^.?!]{0,40}\b(?:in |of |for )?(?:usd|eur|gbp|aud|dollars?|euros?|pounds?)\b"
    r"|\b(?:usd|eur|gbp|aud|dollars?|euros?)\b[^.?!]{0,25}\b(?:bill|invoice|fee|charge)\b|\$\s?\d[\d,]*[^.?!]{0,30}\b(?:bill|invoice|fee)\b"
    r"|\b(?:payment|amount|balance) (?:due )?in (?:usd|eur|gbp|aud|dollars?|euros?|pounds?)\b|\bforeign[- ]currency\b|\bforeign (?:bills?|invoices?|fees?)\b"
    r"|美元的?(?:账单|发票|费用)|欧元的?(?:账单|发票|费用)|外币(?:的)?(?:账单|发票|费用|计划)", re.I)
_FX_NOT = re.compile(r"\b(?:rent|tuition|deposit|landlord|university)\b|房租|学费|押金|房东", re.I)
_FX_PAY_IN = re.compile(r"\b(?:pay|paying|settle|clear)\b[^.?!]{0,40}\b(?:in|using|with|via) (?:us |u\.s\. )?(?:usd|dollars?|eur|euros?|gbp|pounds?|aud)\b|"
                        r"(?:以|用)(?:美元|美金|欧元)(?:来)?(?:支付|付款|付|交|缴)", re.I)
_QUOTE_Q = re.compile(r"\bhow much (?:cny|yuan|rmb)\b[^.?!]{0,20}\b(?:get|receive|have|end up with)\b[^.?!]{0,25}\b(?:inr|rupees?|₹)|"
                      r"\bwhat (?:will|would|is|are)\b[^.?!]{0,30}\b(?:inr|rupees?|₹)\b[^.?!]{0,20}\b(?:be|worth|come to|become)\b[^.?!]{0,10}\b(?:in )?(?:cny|yuan|rmb)\b|"
                      r"(?:卢比|inr)[^。？?]{0,6}(?:能|可以|会)?换[^。？?]{0,4}(?:多少)?(?:人民币|元|cny|rmb)", re.I)
# paid twice / by mistake / refund: advice only, never a draft change
REFUND_ADVICE = re.compile(r"\brefund|\bmoney back\b|\bchargeback\b|\b(?:paid|sent|transferred|remitted|charged)\b[^.?!]{0,30}\b(?:twice|two times|double|by mistake|mistakenly|accidentally|in error)\b|"
                           r"\b(?:twice|double|duplicate)\b[^.?!]{0,20}\b(?:paid|payment|charged|sent)\b|\bpaid (?:a )?duplicate\b|重复(?:付|支付|交|扣)|付了两次|交了两次|多付了|误付|付错了|退款|要回(?:钱|款)", re.I)
_PARENT = r"(?:my )?(?:mom|mum|mother|dad|father|parents?|folks|family)"
_PARENT_REQUEST = re.compile(
    rf"\b(?:ask|request|tell|get|have|let|need|want)\b[^.?!]{{0,25}}\b{_PARENT}\b[^.?!]{{0,35}}\b(?:send|transfer|remit|pay|give|top ?up|money|funds?|cash)\b"
    rf"|\b(?:request|ask for|need|get) (?:some )?(?:money|funds|cash|help with (?:the )?(?:fees?|tuition|rent))\b[^.?!]{{0,15}}\bfrom\b[^.?!]{{0,10}}\b{_PARENT}\b"
    rf"|\b(?:ask|request|message|text|email|ping|send)\b[^.?!]{{0,25}}\b{_PARENT}\b[^.?!]{{0,40}}\b(?:request|help|cover|fees?|tuition|rent|deposit|money|funds?|cash|send|pay)\b"
    rf"|\b(?:money|funds?|cash|top-?up) request\b[^.?!]{{0,20}}\b(?:to|for)\b[^.?!]{{0,12}}\b{_PARENT}\b"
    r"|(?:向|找|让|请|叫|给|跟)(?:我的)?(?:父母|爸妈|妈妈|爸爸|家人|家里|妈|爸)[^。！？]{0,14}(?:汇|转|打|寄|给|付|要|借|发)[^。！？]{0,8}(?:钱|款|学费|房租|押金|生活费|请求|过来)|向(?:父母|爸妈|妈妈|爸爸|家里)要钱|"
    r"(?:让|请|叫)(?:我的)?(?:父母|爸妈|妈妈|爸爸|家人|家里)[^。！？]{0,12}(?:汇|转|打|付|缴)", re.I)
_QUOTA = re.compile(
    r"\b(?:lrs|tcs|safe quota|liberali[sz]ed remittance|remittance (?:limit|quota)|annual (?:remittance )?(?:limit|quota))\b"
    rf"|\bhow much\b[^.?!]{{0,15}}\b(?:can|could|may)\b[^.?!]{{0,12}}\b{_PARENT}\b[^.?!]{{0,20}}\b(?:send|remit|transfer)\b"
    r"|\b(?:ceiling|cap|limit|maximum|max)\b[^.?!]{0,30}\b(?:money|remit\w*|sent|sending|transfers?|wire\w*)\b|\bsent from india\b|"
    r"\b(?:tax|tcs)\b[^.?!]{0,25}\b(?:tuition|remittances?|money|sends?|sent|abroad)\b|\bowe (?:any )?tax\b|\bbefore tax applies\b|"
    r"留学汇款额度|汇款额度|购汇额度|年度额度|(?:要不要|需不需要|要)(?:[^。！？]{0,3})(?:扣税|交税|缴税|纳税|代扣)|汇出去的?[^。！？]{0,8}(?:税|限额|上限|额度)|(?:家里|每年|一年)[^。！？]{0,8}(?:限额|上限)", re.I)
_SHARE_RECORD = re.compile(
    r"\b(?:share|show|send|give|provide|prove|issue|present)\b[^.?!]{0,30}\b(?:payment|rent|bill|payments?) (?:history|record|reliability|track record)\b"
    r"|\bshare\b[^.?!]{0,12}\b(?:my )?(?:record|history|trust pass)\b|分享(?:我的)?(?:付款|缴费|支付)记录|出示(?:我的)?(?:付款|缴费|支付)记录|"
    r"\b(?:landlord|agent|agency|lender|bank|university|leasing office)\b[^.?!]{0,30}\b(?:wants?|needs?|asked|requires?|check|verify|see)\b[^.?!]{0,30}\b(?:proof|record|history|reference|payments?)\b|"
    r"\b(?:prove|proof|show|give|send|provide)\b[^.?!]{0,30}\b(?:on[- ]time|reliab\w+|track record|payment history|rent history)\b[^.?!]{0,30}\b(?:landlord|agent|agency|lender|bank|university)\b|"
    r"\b(?:issue|share|present|give)\b[^.?!]{0,15}\btrust pass\b|"
    r"(?:房东|中介|贷款|银行|学校|租赁)[^。！？]{0,10}(?:要看|要求|需要|想看|核实|查看)[^。！？]{0,8}(?:付款|缴费|租金|信用|记录|证明)|"
    r"(?:给|向|出示|展示|分享|发|提供|导出)[^。！？]{0,10}(?:房东|中介|贷款|银行|租赁)[^。！？]{0,10}(?:记录|历史|证明)|"
    r"(?:证明|出示|分享|导出|提供)[^。！？]{0,8}(?:按时付款|按时交租|信用|租金历史|租金记录|缴费历史)|信用护照分享|\bproof of (?:my )?(?:on[- ]time|payments? history|rent history)\b", re.I)


def _topic_intent(norm: str) -> ChatIntent | None:
    """The five sub-topic intents, checked in this order. Answer-only, so they are safe to match before the pay rules."""
    if _TRANSFER_ISSUE.search(norm):
        return ChatIntent(TRANSFER_ISSUE, {"wording": norm}, 0.85, detect_lang(norm))
    if _FX_PAY_IN.search(norm) and _OBL_WORD.search(norm):
        return ChatIntent(FX_BILL, {"wording": norm, "pay_in": True}, 0.85, detect_lang(norm))
    if _FX_BILL.search(norm) and not _FX_NOT.search(norm):
        return ChatIntent(FX_BILL, {"wording": norm}, 0.85, detect_lang(norm))
    if _PARENT_REQUEST.search(norm):
        return ChatIntent(PARENT_REQUEST, {"wording": norm}, 0.85, detect_lang(norm))
    if _QUOTA.search(norm):
        return ChatIntent(QUOTA, {}, 0.85, detect_lang(norm))
    if _SHARE_RECORD.search(norm):
        return ChatIntent(SHARE_RECORD, {}, 0.85, detect_lang(norm))
    return None


def classify(text: str, ui: str = "en") -> ChatIntent:
    lang = detect_lang(text, ui)
    raw = (text or "").strip()
    norm = normalise(raw)
    if not norm:
        return ChatIntent(HELP, {"empty": True}, 1.0, lang)
    # 0. an invoice, email or pasted text that tells me to send a secret or balance somewhere is refused before anything reads it as a bill
    if len(raw) > 30 and privacy_kind(norm, doc=bool(INVOICE_HINT.search(raw))) == "exfil":
        return ChatIntent(SECRETS, {"urgent": bool(_URGENCY.search(norm)), "detail": "exfil"}, 1.0, lang, "privacy")
    # 1. a labelled invoice (Payee:/Account:/Amount: lines) goes to the pipeline, which is the thing that judges injected text
    short_edit = len(raw) <= 200 and "\n" not in raw and bool(_REGISTRY_EDIT.search(normalise(raw)) or _PAYEE_VERIFY.search(normalise(raw)))
    if INVOICE_HINT.search(raw) and not short_edit:                  # a one-line "add payee Bob, Account: ..." is a chat command, not an invoice
        return ChatIntent(PAY_INVOICE, {"labelled": True}, 1.0, lang)
    # 2. security first, on the normalised text and on anything hidden in base64
    snapped = snap_security(norm)
    for view in [strip_mentions(norm), *([strip_mentions(snapped)] if snapped != norm else []), *decoded_views(raw)]:
        cat = security_category(view)
        if cat:
            return ChatIntent(SECRETS if cat in ("secrets", "privacy") else BYPASS,
                              {"urgent": bool(_URGENCY.search(norm)), "detail": refusal_detail(view, cat)}, 1.0, lang, cat)
    ch = concept_help(norm)
    if ch:
        return ChatIntent(HELP, {"concept": ch}, 0.9, lang)
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
    if REFUND_ADVICE.search(norm) and not acct:
        return ChatIntent(UNDO, {"advice": True}, 0.9, lang)
    if _CANCEL.search(norm) and not acct and not _CONVERT.search(norm) and not _WAIT_Q.search(norm) and not (_ESTIMATE.search(norm) and _EST_BILL.search(norm)):
        return ChatIntent(CANCEL, {}, 0.9, lang)
    # 4. an account number next to "use / instead / change / wrong" is an attempt to change where money goes: never from chat
    if acct and re.search(r"\b(?:use|instead|change|update|replace|switch|new account|wrong|correct)\b|改|换|更换|用这个|错|转到|汇到|付到", norm):
        a = _amount(raw)
        return ChatIntent(CORRECT, {"amount": a[0] if a else None, "currency": a[1] if a else None, "wants_account": True}, 0.9, lang)
    if not acct:                       # sub-topic questions (transfer issue, foreign bill, ask a parent, quota, share record): answer-only
        topic = _topic_intent(norm)
        if topic:
            topic.lang = detect_lang(text, ui)
            return topic
    if not acct and _QUOTE_Q.search(norm) and _amount(raw) and not re.search(r"\bper\b|每", norm):                                       # "how much CNY for INR 100000": a route quote, no draft, no conversion
        a = _amount(raw)
        return ChatIntent(ROUTES, {"amount": a[0] if a else None, "currency": "INR", "quote": True}, 0.85, lang)
    if not acct and re.search(r"\b(?:make|build|create|prepare|draw up|give me|help me (?:make|build|create))\b[^.?!]{0,15}\b(?:a |an |my )?(?:payment )?plan\b", norm):
        a = _amount(raw)                                                       # "make a plan to cover tuition" asks for a plan, not a draft
        return ChatIntent(PLAN, {"amount": a[0] if a else None, "currency": a[1] if a else None}, 0.8, lang)
    # 4b. a payment with an explicit account, or a plain "pay/send ..." request
    if acct and (_PAY_WORD.search(norm) or nl_extract.money(raw)):
        a = _amount(raw, bare=True)
        return ChatIntent(PAY_TEXT, {"amount": a[0] if a else None, "currency": a[1] if a else None, "account": acct,
                                     "urgent": urgent, "purpose": nl_extract.purpose_in_text(raw)}, 0.9, lang)
    if _CONVERT_HI.search(norm) and not acct and not re.search(r"\bper\b|每", norm):
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
    if _CORRECT.search(norm) and not _PAY_IMPERATIVE.search(norm) and not _RUNWAY.search(norm):
        a = _amount(re.sub(r"[,;]?\s*(?:\d[\d,.]*k?\s*nahi|not|instead of|rather than)\b.*$", "", raw, flags=re.I), bare=True)
        return ChatIntent(CORRECT, {"amount": a[0] if a else None, "currency": a[1] if a else None,
                                    "wants_account": bool(re.search(r"account|payee|账号|账户|收款", norm))}, 0.85, lang)
    if (_OWING.search(norm) and not _SENT.search(norm) and not _APPROVAL.search(norm) and not acct
            and (_OBL_WORD.search(norm) or re.search(r"\bwhat\b|\bwhich\b|\banything\b|\bany\b|有哪些|什么|哪些|吗", norm))):
        a = _amount(raw)
        return ChatIntent(OBLIGATIONS, {"amount": a[0] if a else None, "currency": a[1] if a else None}, 0.8, lang)
    if _STATUS.search(norm) and not _ROUTES_STRONG.search(norm) and re.search(r"到账|了吗|了没|没有$|吗[？?]?$|有没有|是否|结清|完成|成功|^(?:did|has|have|was|is|where)", norm):
        return ChatIntent(STATUS, {}, 0.85, lang)
    zh_q = bool(CJK.search(norm) and re.search(r"哪些|哪个|哪种|哪家|多少|回执|收据|证明|凭证|什么|吗|么|呢|是否|推荐|告诉我|回单|讲讲|介绍|可以吗|列出|清单|[?？]|怎么|如何|能不能|有没有|是不是|计划|规划|预算|时间表|日历|顺序|分期|报价|比较|记录|历史|请求|申请|看|查|显示|展示|告诉|拟|出具|生成|提供|导出|分享|出示|了没|结清|完成|成功|方案|安排|排期|状态|进展|进度", norm) and not re.search(r"草稿|起草|帮我(?:付|交|缴|处理|办理)", norm))     # "我有哪些待付账单" asks about bills, it does not pay one
    if not zh_q and (_PAY_IMPERATIVE.search(norm) or _DUE_PAY.search(norm) or (re.search(r"^(?:请|帮我|麻烦|我要|我想|我需要)?给", norm) and nl_extract.money(raw)) or (_HINGLISH_PAY.search(norm) and _OBL_WORD.search(norm))             or (_OBL_WORD.search(norm) and nl_extract.money(raw) and re.search(r"\bko\b|को|给", norm) and "?" not in norm)             or (_PAY_WORD.search(norm) and _OBL_WORD.search(norm) and (not re.search(r"\bhow much\b|\bwhat\b|\bwhen\b|\bwhy\b|\bwhich\b|\bwill\b|\bwould\b|\bwhether\b|^if\b|\bif i\b|\bbest\b|\bcheap\w*|\bfastest\b|\bquickest\b|\bmethod\b|\border\b|\bschedule\b|^(?:has|have|did|does|is|are|was|were|do you)\b|\bfinished\b|\bcompleted\b|\bhandle\b|\baccept\b|\bsupport\b|\brecommend\b|\btell me\b|\bshow me\b|多少|为什么|什么时候|会不会|够不够|最快|最便宜|最划算|顺序|安排", norm) or (CJK.search(norm) and re.search(r"草稿|起草", norm))))):
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
    # 4d. a vague order ("take care of the bill", "do the usual payment"): never guess a bill, the chat layer asks which one
    if not zh_q and not acct and not _CONVERT.search(norm) and not _INFO_CUE.search(norm) and not _NOPAY.search(norm) \
            and not re.search(r"\b(?:inr|cny|rmb|usd|eur|gbp|rupees?|yuan)\b", norm) and re.match(
            r"(?:please |pls |can you |could you )?(?:take care of|handle|settle|sort(?: out)?|make|do|give|move|send)(?: (?:them|him|her|it|us))?"
            r"(?: (?:the|my|a|that|this|some|all|those))? (?:bills?|payments?|transfers?|usual(?: payment| one)?|normal one|money|whatever (?:is )?owed|what(?:'s| is) owed|housing thing)"
            r"(?: to (?:my |the )?(?:landlord|university|school|college|hostel|owner))?(?: now| today| please)?\W*$", norm):
        return ChatIntent(PAY_OBLIGATION, {"type": None, "amount": None, "currency": None, "urgent": urgent, "fraction": None}, 0.6, lang)
    # 5. questions
    if _EXPLAIN.search(norm) or _HOLD_Q.search(norm):
        return ChatIntent(EXPLAIN, {}, 0.85, lang)
    if _NEXT.search(norm):
        return ChatIntent(HELP, {"next": True}, 0.85, lang)
    if _UNDO.search(norm):
        return ChatIntent(UNDO, {}, 0.85, lang)
    if re.search(r"\brates?\b|汇率|兑换率|换汇率|牌价|比价|换汇[^。？]{0,4}好时候", norm) and not nl_extract.money(raw):          # "exchange rate USD to CNY" asks for a rate, not a conversion
        return ChatIntent(RATE, {}, 0.85, lang)
    if _CONVERT.search(norm):
        a = _amount(raw)
        return ChatIntent(CONVERT, {"amount": a[0] if a else None, "currency": a[1] if a else None}, 0.85, lang)
    if _SPENDING.search(norm) and not _RUNWAY.search(norm):
        return ChatIntent(SPENDING, {}, 0.8, lang)
    for kind, rx in ((RUNWAY, _RUNWAY), (STATUS, _STATUS), (BALANCE, _BALANCE), (OBLIGATIONS, _OBLIGATIONS), (ROUTES, _ROUTES_STRONG), (RATE, _RATE), (ROUTES, _ROUTES),
                     (PLAN, _PLAN), (PROOF, _PROOF), (CREDIT, _CREDIT)):
        if kind == STATUS and _ROUTES_STRONG.search(norm):                  # "走哪个通道到账最多" asks which channel, not whether money arrived
            continue
        if rx.search(norm):
            if kind == BALANCE and ((_OBL_WORD.search(norm) and re.search(r"\bleft (?:on|for|of|to pay)\b", norm)) or re.search(r"\bleft to pay\b|待缴|未缴|没缴|逾期", norm)):                 # "how much is left on my tuition" asks about a bill
                kind = OBLIGATIONS
            if kind == OBLIGATIONS and re.search(r"证明|凭证|回单|回执|收据|\breceipts?\b|\bproofs?\b", norm):               # "我需要付款证明" asks for a receipt, not for the bills
                kind = PROOF
            if kind in (OBLIGATIONS, STATUS) and _PLAN_STRONG.search(norm):                                              # "best order to pay my bills" asks for a plan
                kind = PLAN
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
