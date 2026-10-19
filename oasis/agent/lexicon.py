"""Concept lexicons as data (ROUTER_OVERHAUL.md section 4). Words live here, not in regexes.
Entries are matched on lower-cased, NFKC-normalised text. Multi-word entries match as phrases; CJK entries match as substrings.
Each entry in the BILLS / INFO tables was added with a test (tests/test_lexicon.py). Hinglish is romanised."""
from __future__ import annotations

import re

# ---- 4.1 pay-action words
PAY_ACTIONS = (
    "pay", "pay off", "pay up", "pay out", "settle", "settle up", "clear", "clear my dues", "clear the balance", "send", "send over", "remit", "wire", "transfer",
    "push", "release", "fund", "top up", "top-up", "topup", "recharge", "reload", "cover", "handle", "take care of", "deal with", "sort out", "sort",
    "finish paying", "get paid", "get it paid", "make the payment", "make a payment", "do the payment", "process the payment", "go ahead and pay",
    "proceed with paying", "proceed with the payment", "square up", "square away", "pay in full", "pay the full amount", "pay the rest", "pay the remainder",
    "pay what i owe",
    "bhejo", "bhej do", "bhej dena", "de do", "dedo", "de dena", "bharo", "bhar do", "chukao", "chuka do", "pay karo", "pay kar do", "pay kar dena", "kar do", "jama karo",
    "交", "缴", "付", "支付", "付款", "付钱", "汇款", "转账", "转给", "充值", "结清", "还清", "结算",
)
PAY_DESIRE = (
    "i want to pay", "i need to pay", "i have to pay", "i'd like to pay", "i must pay", "i should pay", "let's pay", "time to pay", "it's time to pay",
    "ready to pay", "going to pay", "gotta pay", "wanna pay", "help me pay", "can you pay", "could you pay", "would you pay", "please pay",
    "i want to settle", "i need to settle", "i need to clear",
)

# ---- 4.2 bills: concept -> (canonical command phrase, words)
BILLS: dict[str, tuple[str, tuple[str, ...]]] = {
    "tuition": ("tuition", (
        "tuition", "tuition fee", "tuition fees", "fees", "fee", "school fees", "college fees", "university fees", "university dues", "course fees", "semester fees",
        "semester payment", "semester charges", "term fees", "term payment", "academic fees", "education fee", "programme fee", "program fee", "the university",
        "the school", "the college", "the finance office", "the bursar", "the registrar", "university", "college ki fees", "university ki fees", "dues",
        "学费", "学杂费", "学校费用", "学期费用")),
    "rent": ("rent", (
        "rent", "house rent", "flat rent", "apartment rent", "room rent", "monthly rent", "lease", "lease payment", "the lease", "accommodation",
        "accommodation charges", "lodging", "housing", "housing payment", "hostel", "hostel fees", "hostel charges", "hostel fee", "dorm", "dorm fees", "dormitory",
        "dormitory fees", "the landlord", "the landlady", "my landlord", "landlord", "kiraya", "hostel ki fees", "房租", "租金", "住宿费", "宿舍费", "房东")),
    "deposit": ("deposit", (
        "deposit", "security deposit", "caution deposit", "refundable deposit", "advance", "booking amount", "booking fee for the room", "押金", "定金")),
    "phone": ("phone bill", (
        "phone", "phone bill", "mobile", "mobile bill", "mobile recharge", "recharge", "sim", "sim card", "data plan", "airtime", "top up my phone", "话费", "手机费", "手机充值")),
    "electricity": ("electricity bill", ("electricity", "electric bill", "power bill", "utility bill", "utilities", "bijli ka bill", "电费")),
    "internet": ("internet bill", ("internet", "wifi", "wi-fi", "broadband", "internet bill", "wifi ka bill", "宽带", "网费")),
    "insurance": ("health insurance", ("health insurance", "medical insurance", "insurance", "insurance premium", "医保", "保险", "医疗保险")),
    "visa": ("visa fee", ("visa fee", "visa charges", "visa renewal", "residence permit fee", "permit fee", "签证费", "居留许可费")),
    "application": ("application fee", ("application fee", "admission fee", "registration fee", "exam fee", "申请费", "报名费", "考试费")),
    "library": ("library fee", ("library fee", "library fine", "library charges", "图书馆费")),
    "gym": ("gym membership", ("gym", "gym membership", "sports fee", "sports club", "gym fees", "健身房")),
}
# bills the registry cannot pay: reply "no registered payee"
NO_PAYEE = {
    "gas": ("gas bill", "gas ka bill", "燃气费", "gas"),
    "water": ("water bill", "paani", "水费", "water"),
    "council tax": ("council tax",),
    "parking fine": ("parking fine", "parking ticket", "speeding fine", "traffic fine"),
}

# ---- 4.3 information targets (answer-only): intent -> canonical question that the existing router understands
INFO: dict[str, tuple[str, tuple[str, ...]]] = {
    "balance": ("what is my balance", (
        "balance", "balances", "how much do i have", "how much money do i have", "how much cash", "funds", "my funds", "what's in my account", "what is in my account",
        "in my account", "in my wallet", "wallets", "my wallets", "show my wallets", "holdings", "what do i hold", "what do i own", "how many dollars do i have", "how many euros do i have", "how many pounds do i have", "how many rupees do i have", "how many yuan do i have", "how much is left", "what's left",
        "money left", "available money", "available funds", "spendable", "kitne paise hain", "balance kitna hai", "wallet mein kitna", "余额", "还剩多少", "钱包里有多少", "账户里有多少")),
    "obligations": ("how much do i owe", (
        "what do i owe", "how much do i owe", "what am i supposed to pay", "what do i need to pay", "what must i pay", "what's due", "anything due", "what is due",
        "my bills", "open bills", "outstanding", "unpaid", "pending bills", "list everything i need to pay", "what's coming up", "upcoming payments", "payment schedule",
        "due dates", "deadlines", "when is it due", "when are my bills due", "how much is outstanding", "kitna baki hai", "kya bharna hai", "欠多少", "待付", "账单", "到期")),
    "rate": ("what is the exchange rate today", (
        "exchange rate", "today's rate", "current rate", "rupee to yuan", "yuan to rupee", "inr to cny", "cny to inr", "how strong is the rupee", "how weak is the rupee",
        "rupee vs yuan", "what's the dollar at", "what's 1 usd in inr", "mid-market rate", "market rate", "rate kya hai", "汇率", "今天汇率")),
    "routes": ("cheapest way to send 50000 rupees to China", (
        "cheapest way", "cheapest route", "cheapest method", "least expensive", "lowest fees", "lowest cost", "lowest charges", "best way to send", "best way to transfer",
        "best service", "fastest way", "which route", "which service", "which provider", "bank or app", "bank vs wise", "wise", "western union", "remitly", "swift",
        "wire vs app", "compare transfer options", "compare providers", "send money to china", "move money to china", "remit to china", "transfer abroad",
        "sabse sasta tareeka", "最便宜", "最快", "汇款方式", "怎么汇款")),
    "runway": ("will my money last", (
        "will my money last", "how long will my money last", "how far will my money go", "when will i run out", "run out of money", "runway", "enough for the semester",
        "enough for rent and tuition", "can i afford", "savings last", "short by how much", "shortfall", "paise kab tak chalenge", "够不够", "够用多久")),
    "spending": ("what did i spend", (
        "what did i spend", "expenses", "where does my money go", "where did my money go", "how much did i spend", "spent last month", "transactions",
        "history of payments", "kharcha", "花了多少", "开销", "支出")),
    "status": ("did my payment go through", (
        "did it go through", "has it gone through", "was it paid", "is it paid", "paid yet", "did the university receive", "did my landlord get it", "payment status",
        "status of my payment", "where is my payment", "confirmation", "payment hua kya", "付了吗", "到账了吗", "付款状态")),
    "transfer_issue": ("my transfer arrived short", (
        "stuck", "missing", "delayed", "hasn't arrived", "has not arrived", "didn't arrive", "not received", "haven't received", "arrived short", "less than expected",
        "wrong amount arrived", "lost in transit", "in transit too long", "bounced", "bank deducted", "charged twice", "paisa nahi aaya", "i don't see it", "i can't see it", "don't see the money", "can't see the money", "sent the money but", "没到账", "少了", "延迟", "卡住")),
    "quota": ("what is the yearly remittance limit", (
        "limit", "limits", "quota", "lrs", "tcs", "how much can my parents send", "annual limit", "yearly limit", "maximum i can receive", "cap on remittance",
        "tax on remittance", "tax when parents send money", "education remittance tax", "form a2", "limit kitna hai", "额度", "限额", "年度额度")),
    "parent_request": ("ask my parents for money", (
        "ask my parents", "ask my father", "ask my mother", "ask my dad", "ask my mum", "ask my mom", "request money from", "request funds", "my family sends",
        "family support", "my parents want to send", "tell my parents", "message my parents", "parent approval", "向父母要钱", "家里汇款")),
    "credit": ("how do i build credit", (
        "credit history", "credit score", "credit record", "build credit", "creditworthy", "financial reputation", "financial history", "payment history",
        "payment record", "track record", "on-time payments", "streak", "credit card", "get a credit card", "loan eligibility", "bank account opening",
        "improve my record", "next step to improve", "have my payments been reported", "are my payments reported", "信用", "信用记录", "信用卡", "按时还款")),
    "share_record": ("share my payment record", (
        "share my record", "show my landlord", "prove to my landlord", "prove i pay on time", "proof of payment history", "reference letter", "financial reference",
        "bank reference", "export my record", "export my payment record", "hand to a bank", "give to a landlord", "shareable", "trust pass", "verifiable record",
        "certificate", "generate something i can hand", "出示记录", "证明", "信任通行证")),
    "proof": ("show me the proof of payment", ("proof", "proof pack", "receipt", "payment proof", "prove it was paid", "show me proof", "audit trail", "verification link", "证明包", "凭证")),
    "plan": ("plan my payments", ("plan my payments", "what should i pay first", "order of payments", "prioritise", "prioritize", "priorities", "budget plan", "how should i split", "计划", "先付哪个")),
    "markup": ("is the exchange rate fair", ("markup", "hidden fee", "hidden charges", "spread", "margin", "what is the real cost", "is the rate fair", "overcharged", "隐藏费用", "汇率差价")),
    "help": ("what can you do", (
        "what can you do", "what do you do", "how do i use this", "how does this work", "getting started", "where do i start", "new here", "first time",
        "new international student", "i just landed", "i just arrived", "i'm new", "what should i sort out first", "menu", "options", "commands", "madad", "帮助", "你能做什么", "怎么用")),
    "checkin": ("what should i know today", ("check in", "daily check", "anything i should know", "anything new", "what's new", "what needs my attention", "what's next", "anything for me", "kuch naya", "有什么新消息", "接下来")),
}

# ---- 4.4 currencies
CURRENCIES = {
    "INR": ("rupee", "rupees", "rupaye", "rupiya", "rs", "rs.", "₹", "inr", "卢比"),
    "CNY": ("yuan", "rmb", "renminbi", "cny", "¥", "￥", "元", "块", "kuai", "人民币"),
    "USD": ("dollar", "dollars", "usd", "$", "us dollar", "us dollars", "american dollars", "buck", "bucks", "greenback", "美元", "美金", "刀"),
    "EUR": ("euro", "euros", "eur", "€", "欧元"),
    "GBP": ("pound", "pounds", "gbp", "£", "sterling", "quid", "british pounds", "英镑"),
    "AUD": ("australian dollar", "australian dollars", "aussie dollars", "aud", "a$", "澳元"),
}
UNSUPPORTED_CURRENCIES = {
    "CAD": ("canadian dollar", "canadian dollars", "loonie", "cad", "c$"), "SGD": ("singapore dollar", "sgd", "s$"), "JPY": ("yen", "jpy"), "KRW": ("won", "krw"),
    "HKD": ("hong kong dollar", "hkd", "hk$"), "AED": ("dirham", "aed"), "MYR": ("ringgit", "myr"), "THB": ("baht", "thb"), "NZD": ("kiwi dollar", "nzd", "nz$"),
    "CHF": ("swiss franc", "chf"), "RUB": ("ruble", "rub"), "BTC": ("bitcoin", "btc"), "ETH": ("ethereum", "eth"), "USDT": ("usdt", "tether"), "USDC": ("usdc",),
}
CONVERT_VERBS = ("convert", "exchange", "swap", "turn into", "make into", "move into", "put into", "cash into", "换", "兑换", "换成", "转换", "badlo", "badal do", "exchange karo")
CURRENCY_VERBS = ("change", "switch", "buy", "get")          # only with a currency noun
RATE_TARGET_WORDS = (
    "when the rate hits", "when the rate reaches", "rate crosses", "rate touches", "goes above", "goes below", "gets to", "when it improves", "alert me", "notify me",
    "tell me when", "ping me when", "let me know when", "remind me when", "wait until", "wait for", "set a target", "target rate", "limit order", "convert when",
    "convert once", "convert if", "once the rate",
)

# ---- 4.5 control words
CONFIRM = ("yes", "yeah", "yep", "yup", "ya", "sure", "ok", "okay", "okey", "alright", "go ahead", "do it", "proceed", "continue", "confirm", "confirmed", "correct",
           "right", "that's right", "sounds good", "please do", "go on", "ji", "haan", "theek hai", "是", "好", "可以", "确认")
DENY = ("no", "nope", "nah", "not that", "not that one", "wrong", "don't", "do not", "stop", "no thanks", "nahi", "nahin", "mat karo", "不", "不要", "不是")
CANCEL = ("cancel", "cancel it", "cancel that", "cancel the payment", "cancel my payment", "drop it", "forget it", "forget that", "never mind", "nevermind", "scrap it",
          "abort", "call it off", "discard", "withdraw the draft", "stop it", "hold on", "hold off", "don't send", "don't pay", "取消", "算了", "别付")
REVOKE = ("stop my autopay", "cancel my standing instruction", "stop the recurring payment", "remove the rate alert", "cancel my autopay", "stop autopay", "end my standing instruction",
          "revoke my mandate", "revoke the mandate", "cancel the rate alert", "delete the rate alert", "remove my rate alert", "turn off autopay", "stop my standing order",
          "cancel my standing order", "cancel the standing instruction", "remove the standing instruction", "stop the autopay", "cancel the autopay", "cancel the recurring payment",
          "remove my autopay", "cancel my recurring payment", "stop my recurring payment", "cancel my rate target", "remove the rate target", "停止自动付款", "取消定期付款")
NOPAY = ("just asking", "only asking", "don't pay", "do not pay", "no payment", "not paying", "without paying", "hypothetically", "what if", "just checking", "for information", "只是问问", "不付款")
ANAPHORA = ("and my", "what about", "how about", "the other one", "the other bill", "same again", "again", "once more", "one more", "same but", "like before", "as before", "and the rest", "还有", "那个", "另一个", "同样")

# ---- 4.6 speech-act cues
QUESTION_STARTS = ("what", "when", "where", "who", "why", "how", "which", "is", "are", "am", "do", "does", "did", "can", "could", "will", "would", "should", "may", "shall")
QUESTION_CUES = ("tell me", "let me know", "i want to know", "i'd like to know", "any idea", "wondering", "curious", "show me", "list", "explain")
NEED_CUES = ("i need", "i have to", "i must", "i should", "i'm supposed to", "i've got to", "i got to")
FACT_CUES = ("is due", "are due", "due on", "due by", "due friday", "deadline", "deadlines", "expires", "owe", "overdue", "late on", "behind on", "chasing me", "reminded me",
             "emailed me", "messaged me", "sent me a bill", "piling up", "forgot to pay", "i forgot", "is due tomorrow", "due tomorrow", "due today")
WORRY_CUES = ("worried", "afraid", "scared", "nervous", "stressed", "anxious", "not sure i can", "won't have enough", "might not have enough", "short on", "running low",
              "running out", "tight this month", "i'm broke", "i am broke", "i'll run out", "i will run out")
REPORTED_CUES = ("he said", "she said", "they said", "they told me", "he told me", "she told me", "my dad said", "my mum said", "my mom said", "my parents said",
                 "the email says", "the message says", "the website says", "someone said", "i was told", "i heard", "apparently", "according to", "my dad says",
                 "my mom says", "my mum says", "my parents say", "he says", "she says", "they say", "the officer called", "asked me to", "told me to")
ADDRESSED_CUES = ("you must", "you should", "you will", "i authorise you", "i authorize you", "oasis,", "assistant,", "system:", "ignore", "disregard", "you are now", "from now on")

# ---- 4.8 dates
DATE_WORDS = ("today", "tonight", "tomorrow", "day after tomorrow", "this week", "next week", "this month", "next month", "end of the month", "end of month", "month end",
              "by friday", "on friday", "next friday", "asap", "urgent", "tmrw", "下周", "本月底", "明天", "后天")

_CACHE: dict[str, re.Pattern] = {}


def phrase_rx(words: tuple[str, ...] | list[str]) -> re.Pattern:
    """One compiled alternation, longest first, with word boundaries for Latin entries and substring match for CJK ones."""
    key = "\x00".join(words)
    rx = _CACHE.get(key)
    if rx is None:
        latin = sorted((w for w in words if not re.search(r"[一-鿿]", w)), key=len, reverse=True)
        cjk = sorted((w for w in words if re.search(r"[一-鿿]", w)), key=len, reverse=True)
        parts = []
        if latin:
            parts.append(r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in latin) + r")(?![a-z0-9])")
        if cjk:
            parts.append("(?:" + "|".join(re.escape(w) for w in cjk) + ")")
        rx = _CACHE[key] = re.compile("|".join(parts), re.I)
    return rx


def has(text: str, words) -> bool:
    return bool(phrase_rx(tuple(words)).search(text))


def edit1(a: str, b: str, limit: int = 1) -> bool:
    """True if the Levenshtein distance of a and b is at most `limit` (1 or 2)."""
    if abs(len(a) - len(b)) > limit:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] <= limit
