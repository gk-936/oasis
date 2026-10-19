"""Router v2 (ROUTER_OVERHAUL.md sections 3 and 5): picks WHICH existing handler runs, and what words come back. It never touches the money path.

Only two things can come out of here that can lead to a state change, and both go through the existing handlers and the existing signature:
  * a canonical rewrite such as "pay my rent" that is classified and handled exactly as if the student had typed it, or
  * a stored `last_offer` that the student accepts with an explicit yes.
Everything else is an answer-only intent, a fixed sentence or a refusal. The security lane (nlu.classify) has already looked at the raw text before this runs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import chat_llm, faq, frames, lexicon as L, nlu

_BAD_AMOUNT = re.compile(r"\b(?:nan|inf|infinity)\b|\b\d+(?:\.\d+)?e[+-]?\d+\b|\b(?:all|everything|entire|whole)\b[^.?!]{0,15}\b(?:my )?(?:money|balance|funds|savings|cash)\b|\bas much as (?:possible|you can)\b|\d{20,}|\bmillion million\b")
_SCHEDULE_ABUSE = re.compile(r"\bevery (?:day|minute|hour|second|week|morning)\b|\b(?:daily|hourly|weekly)\b|\bautopay for everything\b|\bunlimited\b")
_CONCEPT_Q = re.compile(r"^(?:what(?:'s| is| are| does| do)|explain|define|tell me what|is it true that|my \w+ said)\b[^,;]{0,80}\b(?:mean|means|meaning|jailbreak|injection|dan|attack|known|say|says)\b")
_HOW_APPROVE = re.compile(r"\b(?:how (?:do|can|could|to) (?:i )?(?:approve|sign)|(?:i want|i'd like|i need) to (?:approve|sign))\b[^.?!]{0,25}\b(?:draft|payment|transfer|bill)s?\b")
_IGNORE_PHISH = re.compile(r"\b(?:email|e-?mail|message|text|sms|site|website)\b[^.?!]{0,40}\b(?:ignore|disregard)\b[^.?!]{0,30}\b(?:instructions?|rules)\b[^.?!]*\b(?:phish\w*|scam|fake|legit|real|safe)\b")
_GET_TRUST = re.compile(r"\b(?:get|make|have|help)\b[^.?!]{0,30}\b(?:banks?|landlords?|lenders?|universit\w+)\b[^.?!]{0,12}\btrust me\b")
_CHEAPER_YUAN = re.compile(r"\b(?:tell|alert|notify|ping|let) me when (?:the )?(?:yuan|cny|rmb) (?:gets|goes|is|drops|falls|becomes)\b[^.?!]{0,15}\b(?:cheaper|below|under|lower)\b[^.?!]{0,10}\bthan (\d+(?:\.\d+)?) (?:rupees|inr)\b")
_USD_ALERT = re.compile(r"\b(?:alert|tell|notify|ping|let) me when (?:the )?(?:usd|dollar)\b")
_AUTOPAY_SETUP = re.compile(r"\b(?:set up|setup|start|enable|turn on|create|activate)\b[^.?!]{0,10}\b(?:auto-? ?pay|autopay|standing (?:order|instruction)|recurring (?:payment|pay))\b[^.?!]{0,12}\b(?:for )?(?:my |the )?(phone|mobile|rent|tuition)\b")
_MARKUP_ASK = re.compile(r"\b(?:ripping|ripped) (?:me )?off\b|\brip-?off\b|\bhow much is (?:my |the )?bank charging me\b|\b(?:overcharging|overcharged) me\b")
_ZH_PAY = re.compile(r"^(学费|房租|租金|押金|电话费|话费)(?:帮我|麻烦|请)?(?:付|交|缴)(?![了过完])(?!.*[吗嘛?？])")
_PROOF_FOR = re.compile(r"\bgive my (?:landlord|lender|bank)\b[^.?!]{0,20}\bproof\b")
_LANDLORD_Q = re.compile(r"\bwho(?:'s| is) my (?:landlord|landlady)\b|\bwhat(?:'s| is) my (?:landlord|landlady)'?s? name\b|\bmy (?:landlord|landlady)'?s? name\b")
_USD_NEED = re.compile(r"^i need (\d[\d,]*) (?:dollars|usd|bucks)\b")
# (pattern over the lower-cased message, canonical sentence handled exactly as if typed): wording the keyword router reads as a different intent
_R2_REWRITES = tuple((re.compile(p), t) for p, t in (
    (r"^(?!(?:how|what|which|when|why|is|are|do|does)\b).*?\b(?:get|clear|settle|sort|finish|handle|take care of)\b[^.?!]{0,25}\b(?:mobile|phone)\b[^.?!]{0,12}\b(?:bill|recharge|top.?up)\b", "pay my phone bill"),
    (r"\b(?:pay|clear|settle|sort)\b[^.?!]{0,25}\b(?:accommodation|lodging)\b(?!\s*(?:fee|charge)s?\?)", "pay my rent"),
    (r"^(?:what(?:'s| is) )?(?:my )?(?:wallet|balance|total)\b[^.?!]{0,15}\bin (?:rupees|inr)\??$", "what is my balance"),
    (r"\bhow much (?:do i|will i|must i|have i got to) (?:need to |have to )?pay in total\b|\btotal (?:i )?(?:need to|have to|must) pay\b", "what do I owe"),
    (r"\b(?:has|did|have) (?:the )?(?:university|school|landlord) (?:got|get|received|receive)\b[^.?!]{0,15}\b(?:my )?(?:money|payment)\b", "did my payment go through"),
    (r"\bwhat will (?:the )?(?:university|landlord|school|they) get if i send (\d[\d,]*) rupees\b", "cheapest way to send 100000 rupees to China"),
    (r"^what(?:'s| is) 1 (?:yuan|cny|rmb) in (?:rupees|inr)\??$", "what is the exchange rate today"),
    (r"\bmake something i can (?:send|give|show|hand)\b[^.?!]{0,15}\b(?:lender|bank|landlord)\b", "share my payment record"),
))
CRYPTO = {"BTC", "ETH", "USDT", "USDC"}


@dataclass
class Route:
    kind: str                                  # rewrite | say | bill_statement | bills_pile | worry | faq | revoke | ask_other_currency
    text: str = ""                             # rewrite: the canonical sentence; say: the whole reply
    intent: str = "info"
    status: str = "info"
    bills: list[str] = field(default_factory=list)
    offer: dict | None = None
    note: str = ""


@dataclass
class Ctx:
    message: str
    it: object                                  # nlu.ChatIntent from the keyword router
    d: dict                                     # the dialog state
    recips: list = field(default_factory=list)
    obls: list = field(default_factory=list)    # open obligations
    lang: str = "en"
    pending: bool = False                       # a draft is waiting for the student's signature


_FAQ_FIRST = {"not_a_scam", "hacked", "what_can_go_wrong", "phone_stolen", "lose_device_key", "is_it_safe", "payment_fails"}
_ANSWER_KINDS = {nlu.EXPLAIN, nlu.STATUS, nlu.HELP, nlu.FAQ, nlu.UNKNOWN, nlu.TRANSFER_ISSUE, nlu.PROOF}
_SCORECARD_Q = re.compile(r"\bwhat have you (?:done|been doing)\b|\bhow are you doing\b(?!\s*today)|\byour (?:track record|scorecard|record|performance)\b|\bhow reliable are you\b|\bagent scorecard\b|\bhow many (?:times|payments) did you\b|\bcan i trust you with my money\b")
_MANDATE_Q = re.compile(r"\bwhat(?:'s| is) your mandate\b|\bwhat are you allowed to do\b|\bwhat can you do (?:on your own|alone|by yourself|without me)\b|\bhow much can you spend\b|\bwhat(?:'s| is) your limit\b|\byour mandate\b")
_OBJECT = re.compile(r"\b(?:pay|settle|clear|cover|handle|fund|send|do|get)\s+(?:off\s+)?(?:my|the|our|a|an)\s+([a-z][a-z' -]{2,28}?)(?:\s+(?:for|to|now|today|please|pls|asap|thanks|paid|payment|bhej|bharo|chuka|de)\b|[?.!,]|$)")
_VAGUE = {"bills", "bill", "it", "them", "everything", "money", "dues", "payment", "payments", "thing", "stuff", "usual", "one", "rest", "remainder"}
_PAY_REWRITE_FROM = {nlu.UNKNOWN, nlu.CONFIRM, nlu.PLAN, nlu.RUNWAY, nlu.HELP, nlu.STATUS, nlu.OBLIGATIONS}
_NOT_REWRITTEN_TO_PAY = {nlu.PAY_OBLIGATION, nlu.PAY_TEXT, nlu.PAY_INVOICE, nlu.CANCEL, nlu.DENY, nlu.LATER, nlu.ESTIMATE, nlu.RATE_TARGET, nlu.SECRETS, nlu.BYPASS, nlu.NOPAY}
_CLOSER_SENSITIVE = {nlu.PLAN, nlu.RUNWAY, nlu.HELP, nlu.ROUTES, nlu.RATE, nlu.STATUS, nlu.PROOF, nlu.CREDIT, nlu.QUOTA}
_KIND_OF = {"parent_request": nlu.PARENT_REQUEST, "quota": nlu.QUOTA, "help": nlu.HELP, "balance": nlu.BALANCE, "obligations": nlu.OBLIGATIONS, "rate": nlu.RATE, "routes": nlu.ROUTES, "runway": nlu.RUNWAY, "spending": nlu.SPENDING,
            "status": nlu.STATUS, "transfer_issue": "transfer_issue", "credit": nlu.CREDIT, "share_record": "share_record", "proof": nlu.PROOF, "plan": nlu.PLAN}


def canon(bill: str) -> str:
    return L.BILLS[bill][0]


def _mask(ref: str) -> str:
    return "****" + str(ref)[-4:]


def _role(c: Ctx, payee_id: str) -> str:
    kinds = {o.type for o in c.obls if o.payee_id == payee_id}
    return "landlord" if "rent" in kinds or "deposit" in kinds else "university" if "tuition" in kinds else "payee"


def _name_check(c: Ctx, f: frames.Frame) -> Route | None:
    """5.7 item 2: a payee name that is not in the registry is never silently replaced by a similar registered one."""
    if not f.pay or re.search(r"\d{8,}", f.raw):
        return None
    reg = {r.name.casefold(): r for r in c.recips}
    for n in f.names:
        low = n.casefold()
        if low in reg or any(low in k or k in low for k in reg):
            continue
        near = next((r for k, r in reg.items() if L.edit1(low, k, 2)), None)
        claims = re.search(rf"{re.escape(n)}\s+(?:is|are)\s+my\s+(?:new\s+)?(?:landlord|landlady|payee|university|school)", f.raw)
        if near is None and not claims:
            continue
        who = near or next((r for r in c.recips if _role(c, r.id) == "landlord"), None)
        reg_part = (f" The registered {_role(c, who.id)} is {who.name} ({_mask(who.account_ref)})." if who else "")
        return Route("say", f"I don't have a payee called {n}.{reg_part} If the payee changed, the new payee must be added and verified in the registry first. Nothing moved.",
                     "pay_obligation", "needs_info")
    return None


def route(c: Ctx) -> Route | None:
    msg, it = c.message, c.it
    f = frames.parse(msg)
    refusal = it.kind in nlu.REFUSALS
    # S1b reported speech: narration is content, not an instruction to the agent
    if refusal:
        if it.kind == nlu.BYPASS and _CONCEPT_Q.match(f.text) and not re.search(r"\band (?:then )?(?:pay|send|approve|do|skip|ignore)\b|\bnow\b.*\b(?:pay|approve)\b", f.text):
            return Route("say", "That is a prompt-injection phrase: text meant to make an assistant ignore its rules. It does nothing here. My rules cannot be changed from chat, "
                         "and every payment still needs your device-key signature on the exact draft.", "faq", "info")
        if f.reported and not f.addressed:
            rest = frames.strip_reported(msg)
            if rest and rest != frames.clean(msg):
                it2 = nlu.classify(rest)
                if it2.kind not in nlu.REFUSALS:
                    sub = route(Ctx(rest, it2, c.d, c.recips, c.obls, c.lang))
                    return sub or (Route("rewrite", rest) if it2.kind != nlu.UNKNOWN else _content(rest, f))
        return None
    if chat_llm._META.search(msg):
        return None                                    # a message about labels, JSON or intents is an instruction to a labeller, not a request from the student
    if f.revoke:
        return Route("revoke")
    for rx, text in _R2_REWRITES:
        if rx.search(f.text):
            return Route("rewrite", text)
    mt = _CHEAPER_YUAN.search(f.text)
    if mt and float(mt.group(1)) > 0:
        return Route("rewrite", f"set a rate alert at {1 / float(mt.group(1)):.4f}")          # "12 rupees per yuan" is 0.0833 yuan per rupee
    if _USD_ALERT.search(f.text):
        return Route("say", "Rate alerts work on the INR to CNY rate only, for example 'alert me when the rate reaches 0.0720'. A USD target isn't supported. Nothing moved.", "rate_target", "needs_info")
    if _AUTOPAY_SETUP.search(f.text):
        return Route("rewrite", "pay my " + _AUTOPAY_SETUP.search(f.text).group(1) + " every month")
    if _MARKUP_ASK.search(f.text) and not re.search(r"\d{3,}", f.text):
        return Route("say", "I can check that. Tell me what the bank offered, for example 'my bank gave me 6800 yuan for 100000 rupees', and I'll compare it with the mid-market rate and show the markup. Nothing moved.", "markup_check", "info")
    m = _ZH_PAY.match(f.raw.strip())
    if m:
        return Route("rewrite", "交" + m.group(1))
    if _PROOF_FOR.search(f.text):
        return Route("rewrite", "share my payment record")
    if _LANDLORD_Q.search(f.text):
        ll = next((r for r in c.recips if _role(c, r.id) == "landlord"), None)
        if ll:
            return Route("say", f"Your registered landlord is {ll.name} (account {_mask(ll.account_ref)}). I only pay this registry account, never one from a message.", "info", "info")
    if _USD_NEED.search(f.text):
        return Route("say", "Do you want to buy 500 USD with your rupees, or pay a bill in USD? Tell me which and I'll continue. Nothing moved.".replace("500", _USD_NEED.search(f.text).group(1)), "fx_bill", "needs_info")
    if it.kind == nlu.UNKNOWN and _HOW_APPROVE.search(f.text):
        return Route("faq", "how_to_approve")
    if it.kind == nlu.UNKNOWN and _IGNORE_PHISH.search(f.text):
        return Route("faq", "ignore_rules_phishing")
    if it.kind == nlu.UNKNOWN and _GET_TRUST.search(f.text):
        return Route("rewrite", L.INFO["credit"][0])
    if _SCORECARD_Q.search(f.text) and not f.pay:
        return Route("scorecard")
    if _MANDATE_Q.search(f.text) and not f.pay:
        return Route("mandate_card")
    if f.pay and not f.nopay and _BAD_AMOUNT.search(f.text):
        b = f.bills[0] if f.bills else None
        full = next((o for o in c.obls if o.type == b), None) if b else None
        tail = f" The full {b} is CNY {full.remaining:,.0f}; say 'pay my {b}' for that." if full else ""
        return Route("say", f"I can't use that as an amount. Give me a number in digits (for example 'pay my rent 3000').{tail} Nothing moved.", "pay_obligation", "needs_info")
    if f.pay and not f.nopay and len({round(a, 2) for a in f.amounts if a > 0}) >= 2 and re.search(r"\b(?:actually|no wait|i mean|instead|rather|sorry)\b", f.text):
        a, b2 = f.amounts[0], f.amounts[-1]
        return Route("say", f"You gave two amounts ({a:,.0f} and {b2:,.0f}). Tell me which one, in one number, and I'll draft it for your signature. Nothing moved.", "pay_obligation", "needs_info")
    if f.pay and not f.nopay and _SCHEDULE_ABUSE.search(f.text):
        return Route("say", "I can't set that schedule. A standing instruction runs for a registry bill on its monthly due date, up to a cap you sign. Say 'pay my phone bill every month' to start one. Nothing moved.",
                     "later", "needs_info")
    if f.pay and f.bills and f.zero_amount and not f.nopay:
        b = f.bills[0]
        full = next((o for o in c.obls if o.type == b), None)
        tail = f" Did you mean the full {b} of CNY {full.remaining:,.0f}?" if full else ""
        return Route("say", f"Zero is not a payment.{tail} Nothing moved.", "pay_obligation", "needs_info")
    if it.kind == nlu.PAY_OBLIGATION and f.pay and not it.slots.get("type") and any(x in ("council tax", "parking fine") for x in f.no_payee):
        have = "; ".join(f"{o.type if o.type != 'living' else 'phone bill'} CNY {o.remaining:,.0f} (due {o.due})" for o in sorted(c.obls, key=lambda x: x.due)[:4])
        return Route("say", f"I can't pay a {f.no_payee[0]} because no registered payee exists for it. I can pay: {have or 'none are open'}. Nothing moved.", "pay_obligation", "needs_info")
    nm = _name_check(c, f)
    if nm:
        return nm
    unsup = [x for x in f.unsupported if x not in CRYPTO]
    if f.pay and unsup and not f.bills and re.search(r"\b(?:charge|fee|fine|bill|payment|invoice|tax)\b", f.text):
        sup = "INR, CNY, USD, EUR, GBP and AUD"
        return Route("say", f"I support {sup}; {unsup[0]} is not supported here. Nothing moved. I can pay your registered bills: "
                     + (", ".join(sorted({o.type for o in c.obls})) or "none are open") + ".", "fx_bill", "info")
    if f.wait_convert or (f.rate_target and f.convert and it.kind in (nlu.CANCEL, nlu.CONFIRM, nlu.UNKNOWN, nlu.HELP)):
        return Route("rewrite", "set a rate alert")
    if f.pay and f.approx and f.bills and not f.nopay:
        return Route("say", f"You said about {f.amounts[0]:,.0f}. Tell me the exact amount (for example 'pay my {f.bills[0]} {f.amounts[0]:,.0f}') and I'll draft it for your signature.",
                     "pay_obligation", "needs_info")
    if re.search(r"\bis it (?:safe|ok|okay|fine) to (?:give|share|send|tell|type|enter|put)\b", f.text) and not re.search(r"\d{6,}", f.raw):
        return Route("faq", "is_it_safe")
    fq = faq.answer(msg)
    if fq and fq[2] >= 0.8 and fq[3] in _FAQ_FIRST and it.kind in _ANSWER_KINDS:
        return Route("faq", fq[3])
    if f.convert and not f.amounts and f.act == "question" and re.search(r"\b(?:good|bad|right|wrong) time\b|\bshould i\b|\bwait\b", f.text):
        return Route("rewrite", "what is the exchange rate today")
    if c.pending and it.kind == nlu.UNKNOWN and not f.order and re.search(r"\b(?:wrong|instead|not|should be|use the|actually|amount|correct)\b", f.text):
        return Route("say", "You have a draft waiting. To change it, give the new amount (for example 'make it 2600') or cancel it and start again; the payee and account always come from the registry and cannot be changed from chat. Nothing moved.",
                     "correct", "needs_info")
    if f.act == "fact" and f.bills and not f.pay and (it.kind in _PAY_REWRITE_FROM or it.kind == nlu.ROUTES):
        return Route("bill_statement", bills=f.bills)
    if re.search(r"\b(?:bills?|payments?|dues|fees)\b.{0,15}\b(?:piling up|pile up|stacking up|adding up|mounting)\b|\b(?:so many|too many|lots? of|a lot of) (?:bills|payments|dues|things to pay)\b", f.text):
        return Route("bills_pile")
    if f.act == "worry" and not f.order and not (set(f.info) - {"runway", "balance"}) and re.search(r"money|enough|rent|tuition|fees|afford|broke|cash|funds|savings|tight|short", f.text) and not re.search(r"scam|hack|stolen|fraud", f.text):
        return Route("worry")
    if f.order and f.bills and not f.nopay and not f.info_q and it.kind in _PAY_REWRITE_FROM:
        a = f" {f.amounts[0]:.0f}" if f.amounts and f.amounts[0] > 0 and not f.approx else ""
        return Route("rewrite", f"pay my {canon(f.bills[0])}{a}")
    if it.kind == nlu.PAY_OBLIGATION and not it.slots.get("type") and f.bills and f.pay and not f.nopay and not f.info_q and not f.amounts:
        return Route("rewrite", f"pay my {canon(f.bills[0])}")                  # "settle my hostel", "pay the programme fee": the bill the keyword router has no word for
    if it.kind == nlu.PAY_OBLIGATION and not it.slots.get("type") and f.pay and not f.bills and not f.nopay and not f.info_q and not f.no_payee and not f.amounts:
        m = _OBJECT.search(f.text)
        word = m.group(1).strip() if m else ""
        if word and word.split()[-1] not in _VAGUE:
            have = "; ".join(f"{o.type if o.type != 'living' else 'phone bill'} CNY {o.remaining:,.0f} (due {o.due})" for o in sorted(c.obls, key=lambda x: x.due)[:4])
            return Route("say", f"I don't have a registered payee for '{word}'. Your open bills are: {have or 'none'}. Say for example 'pay my rent'. Nothing moved.", "pay_obligation", "needs_info")
    if it.kind == nlu.PAY_OBLIGATION and not f.pay and f.info and not f.bills and f.act != "command":
        return Route("rewrite", L.INFO[f.best_info][0])                         # "credit card" is a question about building a record, not an order to pay an unregistered card
    cm = frames.core(msg)
    if cm != msg and frames._RAMBLE.search(msg):
        it3 = nlu.classify(cm)
        if it3.kind not in nlu.REFUSALS and it3.kind not in (nlu.UNKNOWN, it.kind):
            return Route("rewrite", cm)                                         # "I'm so stressed, anyway cheapest way to send ...": the request after the lead-in decides
    if cm != msg and it.kind in _CLOSER_SENSITIVE:
        it2 = nlu.classify(cm)
        if it2.kind not in nlu.REFUSALS and it2.kind not in (nlu.UNKNOWN, it.kind):
            return Route("rewrite", cm)                                         # "... for this semester" must not turn a balance question into a plan
        f2 = frames.parse(cm)
        if f2.info and not f2.pay and _KIND_OF.get(f2.best_info) != it.kind:
            return Route("rewrite", L.INFO[f2.best_info][0])
    top = f.best_info
    if (top in _KIND_OF and it.kind in _KIND_OF.values() and it.kind != _KIND_OF[top] and f.info_len.get(top, 0) >= 3 and f.info_len.get(top, 0) >= max(f.info_len.values())
            and not f.pay):
        return Route("rewrite", L.INFO[top][0])                 # a multi-word phrase of another answer-only concept outweighs a one-word keyword hit
    if it.kind != nlu.UNKNOWN:
        return None
    fq2 = faq.answer(msg)
    if fq2 and fq2[2] >= 0.65:
        return Route("faq", fq2[3])                       # a fixed answer the corpus knows beats a guess at a concept
    r = _content(msg, f)
    if r is not None:
        r.note = "content"                                   # the existing similarity layer gets the first word on these (chat.handle)
    return r


def _content(msg: str, f: frames.Frame) -> Route | None:
    """The concept rewrite for a message the keyword router could not place."""
    if f.convert and f.currencies and f.amounts:
        pair = _pair(f)
        if pair:
            return Route("rewrite", f"convert {f.amounts[0]:.0f} {pair[0].lower()} to {pair[1].lower()}")
    if f.order and f.bills and not f.nopay and not f.info_q:
        a = f" {f.amounts[0]:.0f}" if f.amounts and f.amounts[0] > 0 and not f.approx else ""
        return Route("rewrite", f"pay my {canon(f.bills[0])}{a}")
    if f.info and not (f.pay and f.act != "question"):
        top = f.best_info
        if top in ("routes",) and f.amounts:
            cur = "rupees" if "INR" in f.currencies or not f.currencies else f.currencies[0].lower()
            return Route("rewrite", f"cheapest way to send {f.amounts[0]:.0f} {cur} to China")
        if top:
            return Route("rewrite", L.INFO[top][0])
    if f.bills and f.act in ("question", "other"):
        return Route("bill_statement", bills=f.bills[:1], note="content")
    return None


def _pair(f: frames.Frame) -> tuple[str, str] | None:
    t = f.text
    m = re.search(r"\bbuy (\w+) with\b", t)
    cs = f.currencies
    if m and len(cs) == 2:
        want = next((c for c in cs if any(w == m.group(1) for w in L.CURRENCIES[c])), None)
        if want:
            return next(c for c in cs if c != want), want
    if len(cs) >= 2:
        return cs[0], cs[1]
    if len(cs) == 1 and cs[0] != "CNY":
        return cs[0], "CNY"
    return None
