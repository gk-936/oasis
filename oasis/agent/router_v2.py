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
    if f.act == "worry" and not f.order and not (set(f.info) - {"runway", "balance"}) and re.search(r"money|enough|rent|tuition|fees|afford|broke|cash|funds|savings|tight", f.text) and not re.search(r"scam|hack|stolen|fraud", f.text):
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
