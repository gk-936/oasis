"""Chat handler: turns a message into one of the existing, already-guarded actions and a short, grounded reply.

Nothing here moves money by itself. A payment request becomes a normal `Request` built from the OBLIGATION and the
REGISTRY's credential (never from an account in the text), goes through the same pipeline as an invoice, and ends as a
held draft that only the student's device-key signature can release (`/api/approve`). The model never signs, approves
or edits an audit entry; refusals are logged as `chat_refused` with a category only (never the message text).

Every reply carries machine-readable fields so a script can score a task without reading prose:
    intent, status, pending_id, draft_hash, needs, money_moved, proof_id
Every number in a reply comes from the session state (balances, obligations, rates) and rates carry their source badge.
"""
from __future__ import annotations
import re
from collections import OrderedDict

from ..mock.fx import CURRENCIES, FxError, mid as fx_mid, quote as fx_quote, table_for
from ..mock.rates import ROUTES
from ..passport import currency as currency_mod
from ..planning import spending
from ..planning.forecast import monthly_burn, runway_months, triggers
from ..planning.routes import quote_routes, rank
from ..proof import credit_growth as cg
from ..market import provenance
from . import localize as loc
from . import chat_llm, nl_extract, nlu
from .llm import LiveLLM
from .nlu import ChatIntent
from .pipeline import Request
from .planner import DeterministicPlanner, propose
from .zh_messages import route_zh

MAX_DIALOGS = 64                 # chat sessions kept at once (least recently used is dropped)
_OBL_ZH = {"tuition": "学费", "rent": "房租", "deposit": "押金", "living": "生活费", "family_support": "家庭资助"}
_PURPOSE_ZH = _OBL_ZH
_ROLE_NEEDS = {"student": "student_signature", "parent": "parent_signature"}

# ------------------------------------------------------------------ helpers


def new_dialog() -> dict:
    return {"awaiting": None, "ctx": {}, "last_pending": None, "last_paid": None, "last_cancelled": None}


def dialog_for(dialogs: OrderedDict, key: str) -> dict:
    d = dialogs.get(key)
    if d is None:
        d = dialogs[key] = new_dialog()
        while len(dialogs) > MAX_DIALOGS:
            dialogs.popitem(last=False)
    else:
        dialogs.move_to_end(key)
    return d


def mask(acct: str | None) -> str:
    a = str(acct or "")
    return "****" + a[-4:] if len(a) >= 4 else "****"


def money(x: float, lang: str) -> str:
    s = f"{x:,.0f}" if abs(x - round(x)) < 0.005 else f"{x:,.2f}"
    return f"¥{s}" if lang == "zh" else f"CNY {s}"


def _secret_values(extra) -> list[str]:
    return [s for s in (extra or []) if s and len(s) >= 4]


_TOKEN_PATTERNS = (re.compile(r"sk_bank_live_\w+"), re.compile(r"\bAKIA[0-9A-Z]{16}\b"), re.compile(r"\bgsk_\w{8,}"),
                   re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S),
                   re.compile(r"\b(?:[A-Za-z0-9+/]{48,}={0,2})\b"), re.compile(r"\b[0-9a-f]{40,}\b"))
_LONG_DIGITS = re.compile(r"(?<![\d.])(\d{4})\d{4,}(\d{4})(?![\d])")


def redact(text: str, secrets=None) -> str:
    """Last line of defence on every chat reply: no passcode, key, token or full account number leaves in text."""
    for s in _secret_values(secrets):
        text = text.replace(s, "[redacted]")
    for rx in _TOKEN_PATTERNS:
        text = rx.sub("[redacted]", text)
    return _LONG_DIGITS.sub(lambda m: "****" + m.group(2), text)


def _decoys(w) -> set:
    return w.canaries.decoy_payees if w.canaries else set()


def _recipients(w) -> list:
    d = _decoys(w)
    return [r for r in w.passport.recipients.values() if r.id not in d]


def _open_obligations(w, typ: str | None = None, payee_id: str | None = None) -> list:
    out = []
    for o in w.passport.obligations:
        if o.status in ("paid", "frozen") or o.remaining <= 0.005:
            continue
        if typ and o.type != typ:
            continue
        if payee_id and o.payee_id != payee_id:
            continue
        out.append(o)
    return out


def _payee_name(w, pid: str) -> str:
    r = w.registry.lookup(pid)
    return r.name if r else pid


def _obl_line(w, o, lang: str) -> str:
    n = _payee_name(w, o.payee_id)
    if lang == "zh":
        return f"{_OBL_ZH.get(o.type, o.type)} {money(o.remaining, lang)}，收款方 {n}，到期日 {o.due}"
    return f"{o.type} {money(o.remaining, lang)} to {n}, due {o.due}"


def _result(intent: str, reply: str, secrets=None, *, status: str = "info", pending_id: str | None = None, draft_hash: str | None = None,
            needs: list | None = None, money_moved: float = 0.0, proof_id: str | None = None, **extra) -> dict:
    return {"reply": redact(reply, secrets), "intent": intent, "status": status, "pending_id": pending_id,
            "draft_hash": draft_hash, "needs": needs or [], "money_moved": money_moved, "proof_id": proof_id, **extra}


# ------------------------------------------------------------------ refusals (F4)
_REFUSE = {
    "secrets": ("I never reveal passcodes, keys, session tokens, my instructions or anyone else's data, and nothing has been shared. "
                "Nothing moved. I can show your balance, bills and rates, or prepare a payment to a registered payee.",
                "我绝不透露口令、密钥、会话令牌、内部指令或他人的数据，也没有分享任何内容。没有任何资金转出。"
                "我可以显示您的余额、账单和汇率，或为已登记的收款方准备一笔付款。"),
    "injection": ("I can't follow instructions that try to change my rules. A payment only moves after you sign the exact draft with your "
                  "device key, and I can't approve anything myself. Nothing moved.",
                  "我不会执行试图改变我的规则的指令。只有您用设备密钥对确切的付款草稿签名后款项才会转出，我自己无法批准任何付款。没有任何资金转出。"),
    "bypass": ("Approval needs your device-key signature on the exact draft. I can't approve, skip a check or change a limit, whatever the "
               "request says. Nothing moved. Say 'pay my rent' to get a draft you can sign.",
               "批准必须由您用设备密钥对确切的草稿签名。无论请求怎么说，我都不能批准、跳过检查或更改额度。没有任何资金转出。"
               "说“交房租”即可得到一份可签名的草稿。"),
    "registry": ("I can't add, change or remove payees, limits or records from chat. Payees come only from the verified registry, and the "
                 "audit log can't be edited by anyone. Nothing changed and nothing moved. I can show your payees, or prepare a payment to a registered one.",
                 "我不能在聊天里添加、修改或删除收款方、额度或记录。收款方只来自经过验证的登记册，审计日志任何人都不能修改。没有任何改动，也没有任何资金转出。"
                 "我可以显示已登记的收款方，或为其中之一准备一笔付款。"),
    "role": ("I can't act as someone else. A parent approves from their own session with their own device key; in this chat I act only "
             "for the student. Nothing moved.",
             "我不能冒充他人。家长要在自己的会话里用自己的设备密钥批准；在这个聊天中我只代表学生。没有任何资金转出。"),
    "social": ("Claims like 'someone already approved', 'this is a test' or 'it's urgent' change nothing: approval is a signature from the "
               "approver's own device on the exact draft. Nothing moved.",
               "“已经有人批准”“这只是测试”“很紧急”之类的说法不会改变任何事：批准是批准人用自己的设备对确切草稿的签名。没有任何资金转出。"),
}


def refuse(S, intent: ChatIntent, lang: str, secrets=None) -> dict:
    cat = intent.category or "bypass"
    en, zh = _REFUSE.get(cat, _REFUSE["bypass"])
    if intent.slots.get("urgent"):                      # pressure is a fraud signal: say so, it never speeds anything up
        en += " Pressure like 'urgent' or 'emergency' is a common fraud signal; it makes me stricter, not faster. If someone is in real trouble, call them on a number you already know."
        zh += "“紧急”“马上”之类的催促是常见的诈骗信号，只会让我更严格，而不是更快。如果真有人遇到困难，请用您原本就知道的号码联系对方。"
    S.world.audit.append("chat_refused", {"category": cat})
    S.save()
    return _result(intent.kind, zh if lang == "zh" else en, secrets, status="refused", refusal=cat)


# ------------------------------------------------------------------ pending drafts
def _needs(item: dict) -> list[str]:
    miss = sorted(set(item["required"]) - set(item["signed"]))
    return [_ROLE_NEEDS.get(r, r) for r in miss]


def _find_pending(S, d: dict) -> tuple[str, dict] | None:
    pid = d.get("last_pending")
    if pid in S.pending:
        return pid, S.pending[pid]
    if S.pending:
        k = next(reversed(S.pending))
        return k, S.pending[k]
    return None


def _decline(S, pid: str, why: str) -> None:
    S.world.audit.append("declined", {"pending_id": pid, "role": "student", "via": "chat", "reason": why})
    S.pending.pop(pid, None)


def _draft_reply(S, o: dict, lang: str, d: dict, intent: str, secrets=None, lead: str = "") -> dict:
    """The held payment as a plain-language summary: payee, masked registered account, amount, route, what is still needed."""
    w = S.world
    dr = o.get("draft") or {}
    pid = o.get("pending_id")
    item = S.pending.get(pid, {})
    amt, payee = float(dr.get("amount") or 0), _payee_name(w, dr.get("payee_id", ""))
    route = next((r for r in ROUTES if r.id == dr.get("route_id")), None)
    needs = _needs(item) if item else []
    purpose = dr.get("purpose") or ""
    bal = w.passport.balance("CNY")
    if lang == "zh":
        parts = [lead, f"草稿已就绪：向 {payee}（登记账户 {mask(dr.get('account_ref'))}）支付 {money(amt, lang)}，用途：{_PURPOSE_ZH.get(purpose, purpose)}。"]
        if route:
            parts.append(f"路线：{route_zh(route.name)}，约 {route.days} 天到账。")
        if bal + 0.005 < amt:
            parts.append(f"提醒：您的人民币余额为 {money(bal, lang)}，不足以支付，请先兑换一部分卢比。")
        parts.append("款项只有在您用设备密钥对这份确切的草稿（#" + str(dr.get("draft_hash", ""))[:10] + "）签名后才会转出。"
                     + ("还需要家长共同批准。" if "parent_signature" in needs else "") + "请点击“签名并批准”。")
    else:
        parts = [lead, f"Draft ready: pay {money(amt, lang)} to {payee} (registered account {mask(dr.get('account_ref'))}) for {purpose}."]
        if route:
            parts.append(f"Route: {route.name}, about {route.days} day(s). If it arrives short, FlightPath flags it and proposes a top-up.")
        if bal + 0.005 < amt:
            parts.append(f"Note: your CNY balance is {money(bal, lang)}, below this amount; convert some INR first.")
        parts.append(f"It moves only after you sign this exact draft (#{str(dr.get('draft_hash', ''))[:10]}) with your device key"
                     + (" and a parent co-approves." if "parent_signature" in needs else ".") + " Tap Sign and approve.")
    d["last_pending"], d["awaiting"], d["ctx"] = pid, None, {}
    return _result(intent, " ".join(p for p in parts if p), secrets, status="held", pending_id=pid, draft_hash=dr.get("draft_hash"),
                   needs=needs, outcome=o)


def _stopped_reply(o: dict, lang: str, intent: str, secrets=None, lead: str = "") -> dict:
    card = (o.get("card") or {}).get("text") or ""
    pre = lead or ("我没有付这笔款。" if lang == "zh" else "I did not pay this.")
    return _result(intent, f"{pre} {card}".strip(), secrets, status=o["status"], outcome=o)


def _paid_reply(S, o: dict, lang: str, d: dict, intent: str, secrets=None) -> dict:
    w = S.world
    f = o.get("fields") or {}
    paid = float(o.get("paid_cny") or 0)
    payee = f.get("payee_name") or _payee_name(w, f.get("payee_id", ""))
    d["last_paid"] = o.get("proof_id")
    d["awaiting"], d["ctx"] = None, {}
    if lang == "zh":
        txt = f"已支付 {money(paid, lang)} 给 {payee}。" + (f" 证明包 {o['proof_id']} 已就绪。" if o.get("proof_id") else "")
    else:
        txt = f"Paid {money(paid, lang)} to {payee}." + (f" Proof pack {o['proof_id']} is ready." if o.get("proof_id") else "")
    return _result(intent, txt, secrets, status="paid", money_moved=paid, proof_id=o.get("proof_id"), outcome=o)


def _ask_missing(S, o: dict, lang: str, d: dict, intent: str, secrets=None) -> dict:
    """A held request with no draft: the extraction was not confident. Ask one question, offering only registry choices."""
    f = o.get("fields") or {}
    w = S.world
    if not f.get("amount"):
        d["awaiting"], d["ctx"] = "slot_amount", {"payee_id": f.get("payee_id"), "purpose": f.get("purpose")}
        q = ("您要支付多少金额（人民币）？" if lang == "zh" else "How much should I pay (in CNY)?")
        return _result(intent, q, secrets, status="needs_info", needs=["info:amount"], outcome=o)
    names = "、".join(r.name for r in _recipients(w) if r.payee_type != "student") if lang == "zh" else \
        " or ".join(r.name for r in _recipients(w) if r.payee_type != "student")
    d["awaiting"], d["ctx"] = "slot_payee", {"amount": f.get("amount")}
    q = (f"付给哪位收款方？已登记：{names}。" if lang == "zh" else f"Which payee: {names}?")
    return _result(intent, q, secrets, status="needs_info", needs=["info:payee"], outcome=o)


def _run(S, run_intake, req: Request, lang: str, d: dict, intent: str, secrets=None, lead: str = "") -> dict:
    o = loc.localize_outcome(run_intake(req), lang)
    if o["status"] == "paid":
        return _paid_reply(S, o, lang, d, intent, secrets)
    if o["status"] == "held" and o.get("pending_id"):
        return _draft_reply(S, o, lang, d, intent, secrets, lead)
    if o["status"] == "held":
        return _ask_missing(S, o, lang, d, intent, secrets)
    return _stopped_reply(o, lang, intent, secrets)


def _registry_request(w, payee_id: str, amount: float, purpose: str, due: str | None = None) -> Request | None:
    """A payment request built from the REGISTRY's credential and the obligation; nothing in it comes from the message."""
    cred = w.registry.lookup(payee_id)
    if cred is None:
        return None
    text = (f"Payee: {cred.name}\nPayee ID: {cred.payee_id}\nAccount: {cred.account_ref}\nAmount: CNY {amount:.2f}\nPurpose: {purpose}"
            + (f"\nDue: {due}" if due else ""))
    return Request(text, source="chat", remitter="student")


def _registry_has_account(w, acct: str | None) -> bool:
    return bool(acct) and any(c.get("account_ref") == acct for c in w.registry.all())


def _existing_draft(S, payee_id: str, amount: float, purpose: str) -> tuple[str, dict] | None:
    for pid, it in S.pending.items():
        dr = it["outcome"].get("draft") or {}
        if dr.get("payee_id") == payee_id and abs(float(dr.get("amount") or 0) - amount) < 0.005 and dr.get("purpose") == purpose:
            return pid, it
    return None


def _pay_obligation_now(S, run_intake, ob, amount: float | None, lang: str, d: dict, intent: str, secrets=None, lead: str = "") -> dict:
    w = S.world
    if ob.currency != "CNY":
        t = (f"这笔账单是 {ob.currency}，请到“外币计划”里处理。" if lang == "zh" else
             f"That bill is in {ob.currency}; use the foreign-currency plan to pay it.")
        return _result(intent, t, secrets, status="info")
    amt = round(float(amount if amount is not None else ob.remaining), 2)
    ex = _existing_draft(S, ob.payee_id, amt, ob.type)
    if ex:                                           # the same request twice is one draft, not two
        pid, it = ex
        o = {**it["outcome"], "pending_id": pid}
        again = "您已经有一份相同的草稿在等待签名。" if lang == "zh" else "You already have this exact draft waiting for your signature."
        return _draft_reply(S, o, lang, d, intent, secrets, (lead + " " + again).strip())
    req = _registry_request(w, ob.payee_id, amt, ob.type, ob.due)
    if req is None:
        return _result(intent, "收款方不在登记册中。" if lang == "zh" else "That payee is not in the registry.", secrets, status="rejected")
    return _run(S, run_intake, req, lang, d, intent, secrets, lead)


# ------------------------------------------------------------------ pay flows (F1, F2, F12)
def _type_from_words(message: str) -> str | None:
    t = nlu.normalise(message)
    if re.search(r"universit|college|school|学校|大学", t):
        return "tuition"
    if re.search(r"landlord|\blease\b|房东|租", t):
        return "rent"
    return None


_PHONE = re.compile(r"phone|mobile|\bsim\b|telecom|话费|手机", re.I)       # the registered carrier (Shenzhen Mobile) is the one bill of this kind
_UTILITY = nlu.UNREGISTERED                           # bill types with no registered payee (one list, shared with the router)


_AGAIN = re.compile(r"\bagain\b|\bonce more\b|\bre-?draft\b|phir se|फिर से|重新|再来", re.I)
_USUAL = re.compile(r"\b(?:usual|normal|regular|same as (?:last|every)|as always|monthly|again)\b|照旧|老样子", re.I)
_SOME = re.compile(r"\b(?:some|part|partial|portion|thoda|kuch)\b|一部分|部分", re.I)


_BILL_NAME = {"living": ("phone bill", "话费")}
_NEG_AMT = re.compile(r"(?:^|(?<=\s))[-−–][¥$₹€£]?\d|\b(?:negative|minus)\s*[¥$₹€£]?\d|负\s*\d", re.I)
_STRANGER = re.compile(r"陌生人|陌生账户|不认识的人|\bstrangers?\b|someone i (?:don'?t|do not) know|unknown (?:person|payee|account)|random (?:person|guy|account)|\bmy (?:brother|sister|friend|cousin|roommate|colleague|classmate|uncle|aunt|neighbou?r)\b", re.I)


def _negative(message: str, lang: str, intent: str, secrets=None) -> dict | None:
    """'-100' or 'minus 100' is never a payment amount; the sign must not be silently dropped."""
    if not _NEG_AMT.search(message):
        return None
    t = "金额必须是正数，所以我没有做任何改动，也没有任何资金转出。" if lang == "zh" else "An amount has to be a positive number, so I changed nothing and nothing moved."
    return _result(intent, t, secrets, status="rejected")


def _overpay(S, ob, amt: float, lang: str, kind: str, secrets=None, d: dict | None = None) -> dict:
    """Never more than is owed: refused and audited. An amount exactly 10x the bill is most likely a typo (an extra zero), so
    that one asks whether the bill's real amount was meant; the answer can only ever pay the bill's own amount."""
    w = S.world
    w.audit.append("chat_refused", {"category": "overpayment"})
    S.save()
    en, zh = _BILL_NAME.get(ob.type, (ob.type, _OBL_ZH.get(ob.type, ob.type)))
    slip = d is not None and ob.remaining > 0 and abs(amt - ob.remaining * 10) < 0.5
    if slip:
        d["awaiting"], d["ctx"] = "confirm_pay", {"ob": ob.id, "amount": None}
    if lang == "zh":
        t = (f"账单是 {_obl_line(w, ob, lang)}，您说的 {money(amt, lang)} 超过了应付金额，我不会多付。"
             + (f"是不是多打了一个零？按账单实际金额 {money(ob.remaining, lang)} 付款吗？（回复“是”或“否”）" if slip else
                f"您是想付全额 {money(ob.remaining, lang)} 吗？说“交{zh}”即可，或说一个较小的金额作为部分付款。"))
    else:
        t = (f"The bill is {_obl_line(w, ob, lang)}, and {money(amt, lang)} is more than is owed, so I won't pay that. "
             + (f"Was there an extra zero? Pay the bill's actual {money(ob.remaining, lang)} instead? (yes / no)" if slip else
                f"Did you mean the full {money(ob.remaining, lang)}? Say 'pay my {en}' for that, or give a smaller amount as a part payment."))
    return _result(kind, t, secrets, status="needs_confirmation" if slip else "rejected", refusal="overpayment",
                   **({"needs": ["info:confirm"]} if slip else {}))


def _part_prompt(w, ob, amt: float, lang: str, d: dict, kind: str, secrets=None) -> dict:
    """A smaller amount than the bill: a part payment, confirmed first."""
    d["awaiting"], d["ctx"] = "confirm_pay", {"ob": ob.id, "amount": amt}
    t = (f"账单 {_obl_line(w, ob, lang)}，而您说的是 {money(amt, lang)}（部分付款）。按 {money(amt, lang)} 付款吗？（回复“是”，或告诉我其他金额）"
         if lang == "zh" else
         f"The bill is {_obl_line(w, ob, lang)}, but you said {money(amt, lang)} (a part payment). Pay {money(amt, lang)}? "
         f"(yes, or tell me another amount)")
    return _result(kind, t, secrets, status="needs_confirmation", needs=["info:confirm"])


def _pay_several(S, run_intake, obs: list, it: ChatIntent, lang: str, d: dict, secrets=None) -> dict:
    """Two or more bills named in one message: one draft each. Every draft is signed on its own, so nothing is bundled."""
    results = [_pay_obligation_now(S, run_intake, ob, None, lang, d, it.kind, secrets) for ob in obs]
    held = [r for r in results if r["status"] == "held" and r.get("pending_id")]
    if not held:
        return results[0]
    lines = []
    for r in held:
        dr = (r.get("outcome") or {}).get("draft") or {}
        lines.append(f"{money(float(dr.get('amount') or 0), lang)} → {_payee_name(S.world, dr.get('payee_id', ''))} ({_OBL_ZH.get(dr.get('purpose'), dr.get('purpose')) if lang == 'zh' else dr.get('purpose')})")
    sep = "；" if lang == "zh" else "; "
    if lang == "zh":
        t = f"我准备了 {len(held)} 份草稿：{sep.join(lines)}。每一份都需要您用设备密钥单独签名，签名前不会转出任何款项。说“取消学费那笔”可以只撤销其中一份。"
    else:
        t = (f"I prepared {len(held)} drafts: {sep.join(lines)}. Each needs its own device-key signature and nothing moves until you sign. "
             f"Say 'cancel the tuition one' to drop just one.")
    d["last_pending"] = held[-1]["pending_id"]
    return {**held[0], "reply": redact(t, secrets), "pending_ids": [r["pending_id"] for r in held]}


_MULTI_KINDS = (("rent", re.compile(r"\brent\b|房租|租金", re.I)), ("tuition", re.compile(r"\btuition\b|学费", re.I)),
                ("deposit", re.compile(r"\bdeposit\b|押金", re.I)))


def _pay_obligation(S, run_intake, it: ChatIntent, message: str, lang: str, d: dict, secrets=None) -> dict:
    w = S.world
    typ = it.slots.get("type") or _type_from_words(message)
    amt, cur = it.slots.get("amount"), it.slots.get("currency")
    named = nl_extract.registry_payee(message, _recipients(w))
    if not typ and not named and _AGAIN.search(message) and d.get("last_cancelled"):
        typ = d["last_cancelled"]                                               # "ok, prepare it again" after a cancel: the same bill
    if not named and not typ and _PHONE.search(nlu.fix_typos(nlu.normalise(message))):
        named = next((r for r in _recipients(w) if r.id == "payee_telecom"), None)    # None where the world has no carrier: falls to the unregistered-bill reply
    bad = _negative(message, lang, it.kind, secrets)
    if bad:
        return bad
    unreg = None if named else (nl_extract.unregistered_payee_name(message) or (_STRANGER.search(message).group(0) if _STRANGER.search(message) and not typ else None))
    fr = it.slots.get("fraction")
    if fr and not typ and not named and not unreg and not amt and len(S.pending) == 1:           # "pay half" next to the one waiting draft: halve it (with several, ask which bill)
        f = _find_pending(S, d)
        dr0 = (f[1]["outcome"].get("draft") or {}) if f else {}
        mine = _open_obligations(w, dr0.get("purpose"), dr0.get("payee_id")) if dr0 else []
        if len(mine) == 1:
            return _correct(S, run_intake, ChatIntent(nlu.CORRECT, {"amount": round(mine[0].remaining * float(fr), 2), "currency": "CNY"}, lang=lang),
                            message, lang, d, secrets)
    cands = _open_obligations(w, typ, named.id if named else None)
    kinds = {k for k, rx in _MULTI_KINDS if rx.search(message)}
    if len(kinds) > 1 and not unreg and not _SOME.search(message):                                # "rent and tuition": one draft each, every one signed on its own
        both = [o for k in sorted(kinds) for o in _open_obligations(w, k, named.id if named else None)]
        if len(both) > 1 and (not amt or all(abs(o.remaining - amt) < 0.5 for o in both)):
            return _pay_several(S, run_intake, both, it, lang, d, secrets)
    if len(kinds) > 1 and not named and not unreg:                              # with an amount it is unclear which bill the amount is for: ask
        cands = [o for k in sorted(kinds) for o in _open_obligations(w, k)] or cands
        typ = None
    if not typ and not named and _UTILITY.search(nlu.normalise(message)):       # a bill type with no registered payee: say so, never guess
        w.audit.append("chat_unregistered_bill_type", {})
        S.save()
        allo = _open_obligations(w)
        listing = ("；" if lang == "zh" else "; ").join(_obl_line(w, o, lang) for o in allo) or ("无" if lang == "zh" else "none")
        t = (f"登记册里没有这类账单的收款方，我不会付给未登记的账户。目前可付：{listing}。" if lang == "zh" else
             f"There is no registered payee for that, and I only pay accounts in the registry. Open bills: {listing}.")
        return _result(it.kind, t, secrets, status="rejected")
    # Someone who is not in the registry (F12): explain, and offer the registered payee for the matching bill. Never auto-substitute.
    if unreg:
        w.audit.append("chat_unregistered_payee", {"asked_type": typ})
        S.save()
        if len(cands) == 1:
            o = cands[0]
            d["awaiting"], d["ctx"] = "confirm_pay", {"ob": o.id, "amount": None}
            diff_en = f" (you said {money(amt, lang)})" if amt and abs(amt - o.remaining) > 0.5 else ""
            diff_zh = f"（您说的是 {money(amt, lang)}）" if amt and abs(amt - o.remaining) > 0.5 else ""
            if lang == "zh":
                t = (f"“{unreg}”不是已登记的收款方，我只会付给登记册里的账户。您的{_OBL_ZH.get(o.type, o.type)}收款方是 "
                     f"{_payee_name(w, o.payee_id)}，应付 {money(o.remaining, lang)}{diff_zh}，到期日 {o.due}。要改付这一笔吗？（回复“是”或“否”）")
            else:
                t = (f"“{unreg}” is not a registered payee, and I only pay accounts in the registry. Your {o.type} payee is "
                     f"{_payee_name(w, o.payee_id)}, {money(o.remaining, lang)} due {o.due}{diff_en}. Pay that instead? (yes / no)")
            return _result(it.kind, t, secrets, status="needs_confirmation", needs=["info:confirm"])
        names = ("、" if lang == "zh" else ", ").join(r.name for r in _recipients(w) if r.payee_type != "student")
        t = (f"“{unreg}”不是已登记的收款方。我只能付给：{names}。" if lang == "zh" else
             f"“{unreg}” is not a registered payee. I can pay only: {names}.")
        return _result(it.kind, t, secrets, status="rejected")
    if not cands:
        if named and amt and named.payee_type != "student":              # a registered payee with no open bill: a free payment, still via the pipeline
            if cur and cur != "CNY":
                return _result(it.kind, f"我只能用人民币支付给 {named.name}。" if lang == "zh" else f"I can pay {named.name} only in CNY.", secrets)
            req = _registry_request(w, named.id, amt, typ or "living")
            return _run(S, run_intake, req, lang, d, it.kind, secrets) if req else _result(it.kind, "No registry credential.", secrets, status="rejected")
        if named and not amt:
            d["awaiting"], d["ctx"] = "slot_amount", {"payee_id": named.id, "purpose": typ or "living"}
            return _result(it.kind, f"付给 {named.name} 多少金额（人民币）？" if lang == "zh" else f"How much should I pay {named.name} (in CNY)?",
                           secrets, status="needs_info", needs=["info:amount"])
        allo = _open_obligations(w)
        listing = ("；" if lang == "zh" else "; ").join(_obl_line(w, o, lang) for o in allo) if allo else ("没有待付款项" if lang == "zh" else "nothing")
        t = (f"没有找到匹配的待付账单。目前待付：{listing}。" if lang == "zh" else f"I found no open bill like that. Open bills: {listing}.")
        return _result(it.kind, t, secrets, status="info")
    if len(cands) > 1 and not typ and named and _USUAL.search(message):                   # "the usual", "same as last month": the recurring bill, which is rent
        rents = [o for o in cands if o.type == "rent"]
        cands = rents if len(rents) == 1 else cands
    if len(cands) > 1:
        d["awaiting"], d["ctx"] = "choose_obligation", {"options": [o.id for o in cands], "amount": amt}
        lines = ("；" if lang == "zh" else "; ").join(f"{i}) {_obl_line(w, o, lang)}" for i, o in enumerate(cands, 1))
        t = (f"要付哪一笔？{lines}。回复编号或名称。" if lang == "zh" else f"Which one should I pay? {lines}. Reply with the number or the name.")
        return _result(it.kind, t, secrets, status="needs_info", needs=["info:obligation"])
    ob = cands[0]
    if cur and cur not in ("CNY", ob.currency):
        t = (f"这笔{_OBL_ZH.get(ob.type, ob.type)}以人民币计价，我不能用 {cur} 支付。需要先兑换吗？" if lang == "zh" else
             f"Your {ob.type} is in {ob.currency}; I can't pay it in {cur}. Convert first?")
        return _result(it.kind, t, secrets, status="needs_info")
    if not amt and it.slots.get("fraction"):                              # "pay half of my tuition": a part payment of this bill
        amt = round(ob.remaining * float(it.slots["fraction"]), 2)
    if not amt and _SOME.search(message) and not re.search(r"\d", message):                                   # "pay some of my tuition": how much? never a guess
        d["awaiting"], d["ctx"] = "slot_part_amount", {"ob": ob.id}
        t = (f"{_obl_line(w, ob, lang)}。您想付多少（人民币）？" if lang == "zh" else
             f"The bill is {_obl_line(w, ob, lang)}. How much of it would you like to pay (in CNY)?")
        return _result(it.kind, t, secrets, status="needs_info", needs=["info:amount"])
    if amt and amt > ob.remaining + 0.5:                                    # never more than is owed: refused outright, audited
        return _overpay(S, ob, amt, lang, it.kind, secrets, d)
    if amt and abs(amt - ob.remaining) > 0.5:                              # a smaller amount than the bill: a part payment, confirmed first
        return _part_prompt(w, ob, amt, lang, d, it.kind, secrets)
    lead = ""
    if nl_extract._ACCT_RUN.search(nlu.normalise(message)):                 # an account number in the sentence is never used, and the reply says so
        lead = ("我忽略了消息里的账号：款项只会汇到登记册中的账户。" if lang == "zh" else
                "I ignored the account number in your message: money goes only to the registry's account.")
    return _pay_obligation_now(S, run_intake, ob, None, lang, d, it.kind, secrets, lead)


_INFO_KINDS = (nlu.BALANCE, nlu.OBLIGATIONS, nlu.RATE, nlu.ROUTES, nlu.RUNWAY, nlu.STATUS, nlu.PLAN, nlu.PROOF, nlu.CREDIT,
               nlu.EXPLAIN, nlu.HELP, nlu.SPENDING)


def _continue(S, run_intake, it: ChatIntent, message: str, lang: str, d: dict, secrets=None) -> dict | None:
    """Answer to the question asked last turn. None = this message is not an answer, so it is handled as a fresh request."""
    w, aw, ctx = S.world, d["awaiting"], d["ctx"]
    if it.kind in _INFO_KINDS:                       # "when is my tuition due?" is a question, not a pick: answer it, keep ours open
        return None
    if aw in ("slot_amount", "slot_part_amount", "slot_target_amount", "slot_new_amount", "confirm_pay"):
        bad = _negative(message, lang, "correct", secrets)      # '-5' as the answer must not be read as 5; the question stays open
        if bad:
            return bad
    if aw == "confirm_pay":
        ob = w.passport.obligation(ctx.get("ob", ""))
        if ob is None or ob.status == "paid":
            d["awaiting"], d["ctx"] = None, {}
            return None
        if it.kind == nlu.CONFIRM:
            return _pay_obligation_now(S, run_intake, ob, ctx.get("amount"), lang, d, "confirm", secrets)
        if it.kind in (nlu.DENY, nlu.CANCEL):
            d["awaiting"], d["ctx"] = None, {}
            return _result("deny", "好的，我不会付款。" if lang == "zh" else "Okay, I won't pay anything.", secrets, status="cancelled")
        a = nlu._amount(message, bare=True) if it.kind in (nlu.CORRECT, nlu.UNKNOWN, nlu.PAY_OBLIGATION) else None
        if a:
            ctx["amount"] = a[0]
            t = (f"好的，按 {money(a[0], lang)} 支付 {_obl_line(w, ob, lang)}。确认吗？" if lang == "zh" else
                 f"Okay: pay {money(a[0], lang)} toward {_obl_line(w, ob, lang)}. Confirm?")
            return _result("correct", t, secrets, status="needs_confirmation", needs=["info:confirm"])
    elif aw == "choose_obligation":
        opts = [w.passport.obligation(i) for i in ctx.get("options", [])]
        opts = [o for o in opts if o is not None]
        t = nlu.normalise(message)
        pick = None
        m = re.fullmatch(r"\D*(\d)\D*", t)
        if m and 1 <= int(m.group(1)) <= len(opts):
            pick = opts[int(m.group(1)) - 1]
        else:
            typ = nl_extract.purpose_in_text(message)
            named = nl_extract.registry_payee(message, _recipients(w))
            hit = [o for o in opts if (typ and o.type == typ) or (named and o.payee_id == named.id)]
            if len(hit) == 1:
                pick = hit[0]
        if pick:
            amt = ctx.get("amount")
            d["awaiting"], d["ctx"] = None, {}
            if amt and abs(amt - pick.remaining) > 0.5:
                d["awaiting"], d["ctx"] = "confirm_pay", {"ob": pick.id, "amount": amt}
                return _result("pay_obligation", f"按 {money(amt, lang)} 支付 {_obl_line(w, pick, lang)}？" if lang == "zh"
                               else f"Pay {money(amt, lang)} toward {_obl_line(w, pick, lang)}? (yes / no)", secrets,
                               status="needs_confirmation", needs=["info:confirm"])
            return _pay_obligation_now(S, run_intake, pick, None, lang, d, "pay_obligation", secrets)
        if it.kind in (nlu.CANCEL, nlu.DENY):
            d["awaiting"], d["ctx"] = None, {}
            return _result("cancel", "好的，已取消。" if lang == "zh" else "Okay, cancelled.", secrets, status="cancelled")
        if it.kind == nlu.UNKNOWN:
            return _result("pay_obligation", "请回复编号（例如 1）或账单名称。" if lang == "zh" else "Please reply with a number (for example 1) or the bill's name.",
                           secrets, status="needs_info", needs=["info:obligation"])
    elif aw == "confirm_switch":
        d["awaiting"], d["ctx"] = None, {}
        if it.kind == nlu.CONFIRM and ctx.get("pid") in S.pending:
            old = S.pending[ctx["pid"]]["outcome"].get("draft") or {}
            _decline(S, ctx["pid"], "switched_via_chat")
            S.save()
            d["last_pending"], d["last_cancelled"] = None, old.get("purpose")
            swap = nlu.ChatIntent(nlu.PAY_OBLIGATION, {"type": ctx.get("type"), "amount": ctx.get("amount"), "currency": ctx.get("currency")}, lang=lang)
            r = _pay_obligation(S, run_intake, swap, ctx.get("message") or "", lang, d, secrets)
            r["reply"] = ("好的，已撤下上一份草稿。" if lang == "zh" else "Okay, I withdrew the earlier draft.") + " " + r["reply"]
            return r
        if it.kind in (nlu.DENY, nlu.CANCEL):
            return _result("deny", "好的，保留原来的草稿。" if lang == "zh" else "Okay, I'm keeping the draft you have.", secrets, status="held")
        return None
    elif aw == "slot_part_amount":
        ob = w.passport.obligation(ctx.get("ob", ""))
        a = nlu._amount(message, bare=True)
        if ob is not None and ob.status != "paid" and a and a[1] == "CNY" and not nl_extract.account_in_text(message):
            d["awaiting"], d["ctx"] = None, {}
            if a[0] > ob.remaining + 0.5:
                return _overpay(S, ob, a[0], lang, "pay_obligation", secrets, d)
            if abs(a[0] - ob.remaining) <= 0.5:
                return _pay_obligation_now(S, run_intake, ob, None, lang, d, "pay_obligation", secrets)
            return _part_prompt(w, ob, a[0], lang, d, "pay_obligation", secrets)
        if it.kind in (nlu.CANCEL, nlu.DENY):
            d["awaiting"], d["ctx"] = None, {}
            return _result("cancel", "好的，已取消。" if lang == "zh" else "Okay, cancelled.", secrets, status="cancelled")
    elif aw == "slot_amount":
        a = nlu._amount(message, bare=True)
        if a and a[1] in ("CNY",) and not nl_extract.account_in_text(message):
            pid = ctx.get("payee_id")
            d["awaiting"], d["ctx"] = None, {}
            req = _registry_request(w, pid, a[0], ctx.get("purpose") or "living") if pid else None
            if req:
                return _run(S, run_intake, req, lang, d, "pay_obligation", secrets)
        if it.kind in (nlu.CANCEL, nlu.DENY):
            d["awaiting"], d["ctx"] = None, {}
            return _result("cancel", "好的，已取消。" if lang == "zh" else "Okay, cancelled.", secrets, status="cancelled")
    elif aw == "slot_new_amount":                                 # "change the amount" -> "2600": the bare number is the new amount
        d["awaiting"], d["ctx"] = None, {}
        a = nlu._amount(message, bare=True)
        if a and not nl_extract.account_in_text(message):
            return _correct(S, run_intake, nlu.ChatIntent(nlu.CORRECT, {"amount": a[0], "currency": a[1]}), message, lang, d, secrets)
        if it.kind in (nlu.CANCEL, nlu.DENY):
            return _result("cancel", "好的，已取消。" if lang == "zh" else "Okay, cancelled.", secrets, status="cancelled")
    elif aw == "slot_target_amount":                              # "set a rate alert at 0.072" -> "2000": the bare number is the amount to convert
        a = nlu._amount(message, bare=True)
        if a and a[1] == "CNY" and not nl_extract.account_in_text(message):
            d["awaiting"], d["ctx"] = None, {}
            return _set_target(S, float(ctx["rate"]), a[0], lang, secrets)
        if it.kind in (nlu.CANCEL, nlu.DENY):
            d["awaiting"], d["ctx"] = None, {}
            return _result("cancel", "好的，已取消。" if lang == "zh" else "Okay, cancelled.", secrets, status="cancelled")
    elif aw == "slot_payee":
        if nl_extract.account_in_text(message):
            t = ("我不接受聊天中给出的账号。款项只会汇到登记册中的账户（已脱敏显示）。请告诉我收款方的名称。" if lang == "zh" else
                 "I don't take account numbers from chat: money goes only to the registry's account (shown masked). Please tell me the payee's name.")
            return _result("pay_obligation", t, secrets, status="needs_info", needs=["info:payee"])
        named = nl_extract.registry_payee(message, _recipients(w))
        if named and ctx.get("amount"):
            amt = ctx["amount"]
            d["awaiting"], d["ctx"] = None, {}
            req = _registry_request(w, named.id, amt, nl_extract.purpose_in_text(message) or "living")
            if req:
                return _run(S, run_intake, req, lang, d, "pay_obligation", secrets)
        if it.kind in (nlu.CANCEL, nlu.DENY):
            d["awaiting"], d["ctx"] = None, {}
            return _result("cancel", "好的，已取消。" if lang == "zh" else "Okay, cancelled.", secrets, status="cancelled")
    d["awaiting"], d["ctx"] = None, {}
    return None


def _pay_text(S, run_intake, it: ChatIntent, message: str, lang: str, d: dict, secrets=None) -> dict:
    """A payment written as a sentence with an account in it. The pipeline decides; the account in the text is only ever compared
    with the registry. A refusal (CNY 0 moved) says why, in words."""
    text = message
    if it.slots.get("amount") and nl_extract.money(message) is None:           # "wire 20000 to ...": the number has no currency word
        text += f"\nAmount: CNY {float(it.slots['amount']):.2f}"
    o = loc.localize_outcome(run_intake(Request(text, source="chat", remitter="student")), lang)
    if o["status"] == "held" and o.get("pending_id"):
        return _draft_reply(S, o, lang, d, it.kind, secrets)
    if o["status"] == "paid":
        return _paid_reply(S, o, lang, d, it.kind, secrets)
    S.world.audit.append("chat_refused", {"category": "transfer", "status": o["status"]})
    S.save()
    if o["status"] == "held" and _registry_has_account(S.world, it.slots.get("account")):
        return _ask_missing(S, o, lang, d, it.kind, secrets)             # a registered account with a detail missing: ask for it
    o = {**o, "status": "needs_verification" if o["status"] == "held" else o["status"]}
    urg_en = " 'Urgent' wording is a common fraud signal, so it makes me stricter." if it.slots.get("urgent") else ""
    urg_zh = "“紧急”之类的催促是常见的诈骗信号，所以我会更严格。" if it.slots.get("urgent") else ""
    acct = it.slots.get("account")
    if lang == "zh":
        lead = (f"我没有转这笔钱。款项只会汇到登记册中的收款方账户，而{mask(acct)}不是。{urg_zh}没有任何资金转出（¥0）。"
                "如果您是想付账单，请说“交房租”或“交学费”。")
    else:
        lead = (f"I did not send this. Money goes only to a payee's account in the registry, and {mask(acct)} is not one. {urg_en.strip()} "
                f"Nothing moved (CNY 0). If you meant to pay a bill, say 'pay my rent' or 'pay my tuition'.")
    return _result(it.kind, " ".join(lead.split()), secrets, status=o["status"], outcome=o, refusal="transfer")


# ------------------------------------------------------------------ cancel, correct, undo
_KEEP = re.compile(r"\b(?:keep|but|except|leave)\b|保留|留着|但是", re.I)


def _cancel_one(S, lang: str, d: dict, message: str, secrets=None) -> dict | None:
    """'cancel the tuition one, keep rent': withdraw only the draft of the bill named before 'keep'. None = no such part in the message."""
    typ = nl_extract.purpose_in_text(_KEEP.split(message)[0])
    if not typ or len(S.pending) < 1:
        return None
    hit = [pid for pid, it_ in S.pending.items() if (it_["outcome"].get("draft") or {}).get("purpose") == typ]
    if not hit:
        t = (f"没有等待签名的{_OBL_ZH.get(typ, typ)}草稿。其他草稿保持不变。" if lang == "zh" else f"There is no {typ} draft waiting. Your other drafts are unchanged.")
        return _result("cancel", t, secrets, status="info")
    for pid in hit:
        _decline(S, pid, "cancelled_via_chat")
    S.save()
    d["awaiting"], d["ctx"] = None, {}
    d["last_cancelled"] = typ
    if d.get("last_pending") in hit:
        d["last_pending"] = None
    left = len(S.pending)
    t = (f"已取消{_OBL_ZH.get(typ, typ)}草稿，没有任何资金转出。" + (f"还有 {left} 份草稿等待您签名。" if left else "") if lang == "zh" else
         f"Cancelled the {typ} draft. Nothing moved." + (f" {left} other draft(s) still wait for your signature." if left else ""))
    return _result("cancel", t, secrets, status="cancelled", pending_id=hit[0])


def _cancel(S, lang: str, d: dict, secrets=None, message: str = "") -> dict:
    had_q = d["awaiting"] is not None
    part = _cancel_one(S, lang, d, message, secrets) if message else None
    if part is not None:
        return part
    d["awaiting"], d["ctx"] = None, {}
    f = _find_pending(S, d)
    if not f:
        t = ("好的。目前没有等待批准的付款。" if lang == "zh" else "Okay. There is no payment waiting for approval.") if not had_q else \
            ("好的，已取消。" if lang == "zh" else "Okay, cancelled.")
        return _result("cancel", t, secrets, status="cancelled")
    pid, it_ = f
    dr = it_["outcome"].get("draft") or {}
    _decline(S, pid, "cancelled_via_chat")
    S.save()
    d["last_pending"] = None
    d["last_cancelled"] = dr.get("purpose")
    amt, payee = float(dr.get("amount") or 0), _payee_name(S.world, dr.get("payee_id", ""))
    t = (f"已取消向 {payee} 支付 {money(amt, lang)} 的草稿，没有任何资金转出。" if lang == "zh" else
         f"Cancelled the draft of {money(amt, lang)} to {payee}. Nothing moved.")
    return _result("cancel", t, secrets, status="cancelled", pending_id=pid)


def _switch_target(S, message: str, dr: dict) -> bool:
    """True when the message names a bill (type, registered payee or the phone bill) other than the one in the current draft."""
    w = S.world
    typ = nl_extract.purpose_in_text(message)
    named = nl_extract.registry_payee(message, _recipients(w))
    if not typ and not named and _PHONE.search(nlu.normalise(message)):
        named = next((r for r in _recipients(w) if r.id == "payee_telecom"), None)
    return bool((typ and typ != dr.get("purpose")) or (named and named.id != dr.get("payee_id")))


def _correct(S, run_intake, it: ChatIntent, message: str, lang: str, d: dict, secrets=None) -> dict:
    f = _find_pending(S, d)
    if it.slots.get("wants_account"):
        S.world.audit.append("chat_refused", {"category": "account_change"})
        S.save()
        t = ("账号不能在聊天里更改：款项只汇到登记册中的账户。如果收款方变了，需要先在登记册中重新验证。" if lang == "zh" else
             "I can't change an account from chat: money goes only to the registry's account. If the payee changed, it has to be re-verified first.")
        return _result("correct", t, secrets, status="rejected")
    if not f:
        t = ("目前没有可修改的草稿。您可以说“交房租”来生成一份。" if lang == "zh" else "There is no draft to change yet. Say 'pay my rent' to create one.")
        return _result("correct", t, secrets, status="info")
    if _switch_target(S, message, f[1]["outcome"].get("draft") or {}):          # a different bill is named: ask before withdrawing the draft
        dr0 = f[1]["outcome"].get("draft") or {}
        typ = nl_extract.purpose_in_text(message)
        d["awaiting"], d["ctx"] = "confirm_switch", {"pid": f[0], "message": message, "type": typ, "amount": it.slots.get("amount"),
                                                       "currency": it.slots.get("currency")}
        what = (_OBL_ZH.get(typ, typ) if lang == "zh" else typ) if typ else ("话费" if lang == "zh" else "phone bill")
        have = (_OBL_ZH.get(dr0.get("purpose"), dr0.get("purpose")) if lang == "zh" else dr0.get("purpose")) or ""
        t = (f"您有一份{have}草稿（{money(float(dr0.get('amount') or 0), lang)}）在等待签名。要撤下它，改付{what}吗？（回复“是”或“否”）" if lang == "zh" else
             f"You have a {have} draft ({money(float(dr0.get('amount') or 0), lang)}) waiting for your signature. Withdraw it and pay the {what} instead? (yes / no)")
        return _result("correct", t, secrets, status="needs_confirmation", needs=["info:confirm"])
    bad = _negative(message, lang, "correct", secrets)
    if bad:
        return bad
    amt = it.slots.get("amount")
    if not amt:
        d["awaiting"], d["ctx"] = "slot_new_amount", {}
        t = ("新的金额是多少？" if lang == "zh" else "What should the new amount be?")
        return _result("correct", t, secrets, status="needs_info", needs=["info:amount"])
    if it.slots.get("currency") not in (None, "CNY"):
        return _result("correct", "我只能用人民币付款。" if lang == "zh" else "I can pay only in CNY.", secrets, status="needs_info")
    pid, item = f
    dr = item["outcome"].get("draft") or {}
    if abs(float(dr.get("amount") or 0) - amt) < 0.005:
        return _result("correct", "金额没有变化，草稿保持不变。" if lang == "zh" else "That is the same amount; the draft is unchanged.", secrets,
                       status="held", pending_id=pid, draft_hash=dr.get("draft_hash"), needs=_needs(item))
    owed = _open_obligations(S.world, dr.get("purpose"), dr.get("payee_id"))
    if len(owed) == 1 and amt > owed[0].remaining + 0.5:                        # never more than is owed, also when the draft is corrected upwards
        return _overpay(S, owed[0], amt, lang, "correct", secrets, d)
    req = _registry_request(S.world, dr.get("payee_id", ""), amt, dr.get("purpose") or "living")
    if req is None:
        return _result("correct", "No registry credential.", secrets, status="rejected")
    _decline(S, pid, "corrected_via_chat")                      # the old draft and any signature on it are dead
    d["last_pending"] = None
    lead = (f"已把金额从 {money(float(dr.get('amount') or 0), lang)} 改为 {money(amt, lang)}。旧草稿已作废，需要重新签名。" if lang == "zh" else
            f"Changed the amount from {money(float(dr.get('amount') or 0), lang)} to {money(amt, lang)}. The old draft is void; you need to sign again.")
    if len(owed) == 1 and amt < owed[0].remaining - 0.5:
        lead += (f" 这是一笔部分付款，账单总额为 {money(owed[0].remaining, lang)}。" if lang == "zh" else
                 f" This is a part payment; the bill is {money(owed[0].remaining, lang)}.")
    return _run(S, run_intake, req, lang, d, "correct", secrets, lead)


def _undo(S, lang: str, d: dict, secrets=None) -> dict:
    if _find_pending(S, d):                 # nothing was sent yet, so undoing a draft is withdrawing it
        return _cancel(S, lang, d, secrets)
    proofs = list(S.world.proofs)
    if proofs:
        j = next(iter(S.journeys), None)
        if lang == "zh":
            t = ("已发出的付款我无法撤销。如果收款方没有收到或金额不足，可以在 FlightPath 中发起追回或退款流程（演示数据，MOCK）"
                 + (f"，行程编号 {j}。" if j else "。") + "没有任何付款会被我悄悄撤回。")
        else:
            t = ("A payment that has been sent can't be reversed by me. If the payee hasn't received it or it arrived short, FlightPath can start a "
                 "recall or refund (MOCK rails)" + (f" for journey {j}." if j else ".") + " I never reverse a payment silently.")
        return _result("undo", t, secrets, status="info", proof_id=proofs[-1])
    return _result("undo", "目前没有已付款项或待签草稿可以撤销。" if lang == "zh" else "There is nothing paid or waiting that I could undo.", secrets, status="info")


# ------------------------------------------------------------------ read-only answers (F1, F7)
def _balance(S, lang: str, secrets=None) -> dict:
    pp = S.world.passport
    parts = []
    for b in pp.balances:
        sym = {"INR": "₹", "CNY": "¥"}.get(b.currency)
        parts.append(f"{sym}{b.amount:,.0f}" if sym else f"{b.currency} {b.amount:,.0f}")
    t = ("您有 " + " 和 ".join(parts) + "。（演示数据，MOCK）") if lang == "zh" else ("You have " + " and ".join(parts) + ". (MOCK sandbox balances)")
    return _result("balance", t, secrets)


def _obligations(S, lang: str, secrets=None, message: str = "") -> dict:
    w = S.world
    typ = nl_extract.purpose_in_text(message) if message else None
    o = _open_obligations(w, typ) or _open_obligations(w)
    if not o:
        return _result("obligations", "您目前没有待付款项。" if lang == "zh" else "You have nothing due right now.", secrets)
    lines = ("；" if lang == "zh" else "; ").join(_obl_line(w, x, lang) for x in sorted(o, key=lambda x: x.due))
    t = (f"您有 {len(o)} 笔待付款项：{lines}。" if lang == "zh" else f"You have {len(o)} open bill{'s' if len(o) != 1 else ''}: {lines}.")
    return _result("obligations", t, secrets)


_CUR_RE = re.compile(r"(?<![a-z])(inr|cny|rmb|usd|eur|gbp|aud|jpy|hkd|cad|sgd|rupees?|rupaye|rupiya|yuan|dollars?|euros?|pounds?)(?![a-z])|[₹¥$€£]|人民币|卢比", re.I)
_CUR_CANON = {"rmb": "CNY", "yuan": "CNY", "人民币": "CNY", "¥": "CNY", "rupee": "INR", "rupees": "INR", "rupaye": "INR", "rupiya": "INR", "卢比": "INR", "₹": "INR", "dollar": "USD", "dollars": "USD",
              "$": "USD", "euro": "EUR", "euros": "EUR", "€": "EUR", "pound": "GBP", "pounds": "GBP", "£": "GBP"}


def _mentioned(message: str) -> list[str]:
    """Currencies named in the message, in order of appearance, upper-case codes, no repeats."""
    out = []
    for m in _CUR_RE.finditer(message or ""):
        t = m.group(0).lower()
        c = _CUR_CANON.get(t) or t.upper()
        if c not in out:
            out.append(c)
    return out


def _scope_note(curs: list[str], lang: str) -> str | None:
    """Currencies the wallet does not hold: say so instead of answering about a different pair."""
    bad = [c for c in curs if c not in CURRENCIES]
    if not bad:
        return None
    sup = ", ".join(CURRENCIES)
    return (f"我不支持 {', '.join(bad)}。钱包支持：{sup}。" if lang == "zh" else f"I do not support {', '.join(bad)}. The wallet holds: {sup}.")


def _rate(S, lang: str, secrets=None, message: str = "") -> dict:
    w = S.world
    curs = _mentioned(message)
    note = _scope_note(curs, lang)
    if note:
        return _result("rate", note, secrets, status="info")
    if len(curs) >= 2 and set(curs[:2]) != {"INR", "CNY"}:
        src, dst = curs[0], curs[1]
        try:
            r = fx_mid(src, dst, table_for(w.rates, w.day_index))
        except FxError as e:
            return _result("rate", str(e), secrets, status="rejected")
        t = (f"{src}→{dst} 参考汇率约 {r:.4f}（演示/参考汇率，MOCK，非行情报价；我不预测汇率）。" if lang == "zh" else
             f"{src}→{dst} reference rate about {r:.4f} (MOCK / reference cross, not a market quote; I do not predict rates).")
        return _result("rate", t, secrets)
    pv = provenance(w.rates, w.day_index)
    badge = pv.get("label") or f"INR→CNY {pv['rate']:.4f} · {pv.get('source')}"
    when = (pv.get("as_of") or pv.get("fetched_at") or "")[:10]
    stale = pv.get("stale")
    if lang == "zh":
        t = f"当前汇率：{badge}{'（已过期）' if stale else ''}{'，截至 ' + when if when else ''}。我不预测汇率。"
    else:
        t = f"Current rate: {badge}{' (STALE)' if stale else ''}{', as of ' + when if when else ''}. I do not predict rates."
    return _result("rate", t, secrets)


def _routes(S, it: ChatIntent, lang: str, secrets=None, message: str = "") -> dict:
    w = S.world
    curs = _mentioned(message)
    note = _scope_note(curs, lang)
    if note:
        return _result("routes", note, secrets, status="info")
    if curs and not {"INR", "CNY"} >= set(curs):                 # a pair other than INR/CNY: one price estimate, no route comparison
        src, dst = (curs + ["CNY"])[:2] if len(curs) >= 2 else (curs[0], "CNY" if curs[0] != "CNY" else "INR")
        base = float(it.slots.get("amount") or 1000)
        try:
            q = fx_quote(base, src, dst, table_for(w.rates, w.day_index))
        except FxError as e:
            return _result("routes", str(e), secrets, status="rejected")
        t = (f"路线比较只针对 INR→CNY。{src}→{dst} 我只能给出一个价格估算：{q.amount:,.0f} {src} 约得 {q.received:,.2f} {dst}（汇率 {q.rate:.4f}，费用 {q.fee:,.2f} {src}；"
             f"公开区间估算，MOCK，非报价）。" if lang == "zh" else
             f"Route comparison is built for INR→CNY only. For {src}→{dst} I can give one price estimate: {q.amount:,.0f} {src} gives about {q.received:,.2f} {dst} "
             f"(rate {q.rate:.4f}, fee {q.fee:,.2f} {src}; public-range estimate, MOCK, not a quote).")
        return _result("routes", t, secrets)
    amt = it.slots.get("amount") if it.slots.get("currency") == "INR" else None
    base = float(amt or 100000)
    qs = rank(quote_routes(w.rates, base, w.today, None, w.day_index))[:3]
    best = qs[0]
    if lang == "zh":
        lines = "；".join(f"{route_zh(q.route.name)}：约到账 ¥{q.delivered_cny:,.0f}，{q.arrives_in_days} 天" for q in qs)
        t = f"以汇出 ₹{base:,.0f} 计，最便宜且能按时到账的路线是{route_zh(best.route.name)}。前三名：{lines}。（演示数据，MOCK）"
    else:
        lines = "; ".join(f"{q.route.name}: about CNY {q.delivered_cny:,.0f}, {q.arrives_in_days} day(s)" for q in qs)
        t = f"For INR {base:,.0f}, the cheapest on-time route is {best.route.name}. Top 3: {lines}. (MOCK prices)"
    return _result("routes", t, secrets)


def _runway(S, lang: str, secrets=None, message: str = "") -> dict:
    w = S.world
    pp = w.passport
    m = runway_months(pp, w.rates, w.day_index)
    burn, _ = monthly_burn(pp)
    alerts = triggers(pp, w.rates, w.today, w.day_index)
    if lang == "zh":
        t = (f"付清应付款项后，您的资金可维持约 {m:.1f} 个月（按每月约 ¥{burn:,.0f} 的开销）。" +
             ("目前有提醒：" + " ".join(a.message for a in alerts) if alerts else "目前没有提醒。") + "这是估算，不是保证。")
    else:
        short = " You may run short; I can build a plan." if m < pp.rules.runway_alert_months else ""
        t = (f"After your open bills, your money lasts about {m:.1f} month(s) at roughly CNY {burn:,.0f} a month." + short +
             (" Alerts: " + " ".join(a.message for a in alerts) if alerts else " No alerts.") + " This is an estimate, not a guarantee.")
    typ = nl_extract.purpose_in_text(message)
    need = sum(o.remaining for o in _open_obligations(w, typ)) if typ else 0
    if need:                                  # "do I have enough to cover tuition?": compare the CNY balance with that bill
        bal = pp.balance("CNY")
        if lang == "zh":
            t += f" 您的人民币余额 {money(bal, lang)}，{_OBL_ZH.get(typ, typ)}待付 {money(need, lang)}：" + ("够付。" if bal + 0.005 >= need else "不够，需要先兑换一部分卢比。")
        else:
            t += f" Your CNY balance is {money(bal, lang)} and your open {typ} is {money(need, lang)}: " + ("covered." if bal + 0.005 >= need else "not enough yet, convert some INR first.")
    return _result("runway", t, secrets)


def _plan(S, lang: str, secrets=None) -> dict:
    w = S.world
    rec = propose(w, DeterministicPlanner(), "Plan my semester payments")
    S.save()
    why = (rec.get("why") or [rec.get("rationale") or ""])[:2]
    if lang == "zh":
        t = (f"我起草了计划 {rec['id']}（{len(rec.get('steps', []))} 步）。这只是建议：在“计划”页面接受并签名之前，不会付款或兑换。")
    else:
        t = (f"I drafted plan {rec['id']} with {len(rec.get('steps', []))} step(s). " + " ".join(why) +
             " It is only a proposal: nothing is paid or converted until you accept it in the Plan tab and sign.")
    return _result("plan", t, secrets, plan_id=rec["id"])


def _convert(S, it: ChatIntent, lang: str, d: dict, secrets=None, message: str = "") -> dict:
    w = S.world
    curs = _mentioned(message)
    note = _scope_note(curs, lang)
    if note:
        return _result("convert", note, secrets, status="info")
    amt, cur = it.slots.get("amount"), it.slots.get("currency")
    if not amt:
        return _result("convert", "您想兑换多少金额？例如“convert 20000 INR to CNY”。" if lang == "zh" else
                       "How much would you like to convert? For example: 'convert 20000 INR to CNY'.", secrets, status="needs_info", needs=["info:amount"])
    src, dst = (curs[0], curs[1]) if len(curs) >= 2 else (("INR", "CNY") if cur in (None, "INR") else ("CNY", "INR"))
    if len(curs) == 1 and curs[0] not in ("INR", "CNY"):
        src, dst = curs[0], "CNY"
    if len(curs) >= 2 and cur in curs[:2] and curs[0] != cur and re.search(r"how many", message, re.I):
        src, dst = cur, curs[0]               # "how many yuan for 1 lakh rupees?": the amount's currency is the one being sold
    try:
        q = fx_quote(float(amt), src, dst, table_for(w.rates, w.day_index))
    except FxError as e:
        return _result("convert", str(e), secrets, status="rejected")
    cny_equiv = q.received if dst == "CNY" else q.amount
    lim = w.passport.rules.tier1_auto_convert_cny
    if lang == "zh":
        t = f"报价：{q.amount:,.0f} {src} → 约 {q.received:,.2f} {dst}（汇率 {q.rate:.4f}，费用 {q.fee:,.2f} {src}；演示价格，MOCK）。"
    else:
        t = f"Quote: {q.amount:,.0f} {src} → about {q.received:,.2f} {dst} (rate {q.rate:.4f}, fee {q.fee:,.2f} {src}; MOCK prices)."
    if cny_equiv <= lim and (src, dst) == ("INR", "CNY"):
        d["awaiting"], d["ctx"] = "confirm_convert", {"amount": float(amt), "src": src, "dst": dst}
        t += (" 这是在您自己的余额之间兑换，不会付给任何人。回复“是”即可执行。" if lang == "zh" else
              " This moves money between your own balances only. Reply 'yes' to do it.")
        return _result("convert", t, secrets, status="needs_confirmation", needs=["info:confirm"])
    if (src, dst) != ("INR", "CNY"):
        t += (" 这只是报价；聊天里只能确认 INR→CNY 兑换，其他币种对请在“兑换”页面操作。" if lang == "zh" else
              " This is a quote only: chat confirms INR→CNY conversions; use the Convert screen for other pairs.")
    else:
        t += (f" 超过 ¥{lim:,.0f} 的自动额度，请在“兑换”页面操作。" if lang == "zh" else f" That is above your CNY {lim:,.0f} auto limit; use the Convert screen.")
    return _result("convert", t, secrets, status="info")


def _status(S, lang: str, d: dict, secrets=None) -> dict:
    w = S.world
    pend = list(S.pending.values())
    paid = [o for o in w.passport.obligations if o.status == "paid"]
    parts = []
    if pend:
        parts.append(f"{len(pend)} 笔付款等待签名" if lang == "zh" else f"{len(pend)} payment(s) waiting for a signature")
    parts.append((f"{len(paid)} 笔账单已付清" if lang == "zh" else f"{len(paid)} bill(s) paid") if paid else
                 ("还没有账单付清" if lang == "zh" else "no bill paid yet"))
    proof = list(w.proofs)[-1] if w.proofs else None
    t = ("状态：" if lang == "zh" else "Status: ") + ("；" if lang == "zh" else "; ").join(parts) + ("。" if lang == "zh" else ".")
    if proof:
        t += (f" 最近的证明包：{proof}。" if lang == "zh" else f" Latest proof pack: {proof}.")
    return _result("status", t, secrets, proof_id=proof)


def _spending(S, lang: str, secrets=None) -> dict:
    """This month's wallet spending by category and the bills paid, from the sandbox records (MOCK)."""
    w = S.world
    pp = w.passport
    month = w.today.isoformat()[:7]
    txs = [t for t in pp.transactions if t["date"].startswith(month)]
    cats: dict[str, float] = {}
    for t in txs:
        cats[t["category"]] = cats.get(t["category"], 0.0) + t["amount_cny"]
    paid = [o for o in pp.obligations if o.status == "paid"]
    fc = spending.summarize(pp)["monthly_cny"]
    if lang == "zh":
        t = (f"本月钱包支出 ¥{sum(cats.values()):,.0f}（" + "，".join(f"{c} ¥{v:,.0f}" for c, v in sorted(cats.items(), key=lambda x: -x[1])) + "）。"
             if txs else "本月还没有记录钱包支出。")
        t += (f"已付账单：" + "；".join(f"{_OBL_ZH.get(o.type, o.type)} {money(o.amount, lang)}" for o in paid) + "。" if paid else "还没有账单付清。")
        t += f"预计每月开销约 ¥{fc:,.0f}。（演示数据，MOCK）"
    else:
        t = (f"This month's wallet spending is CNY {sum(cats.values()):,.0f} (" + ", ".join(f"{c} CNY {v:,.0f}" for c, v in sorted(cats.items(), key=lambda x: -x[1])) + ")."
             if txs else "No wallet spending is recorded this month yet.")
        t += (" Bills paid: " + "; ".join(f"{o.type} {money(o.amount, lang)}" for o in paid) + "." if paid else " No bill paid yet.")
        t += f" Expected monthly spending is about CNY {fc:,.0f}. (MOCK sandbox data)"
    return _result("spending", t, secrets)


def _held_note(S, lang: str) -> str:
    """What 'held' means for a draft that is waiting: it is not stuck or lost, it waits for the signature."""
    if not S.pending:
        return ""
    needs = _needs(next(reversed(S.pending.values())))
    co = "parent_signature" in needs
    if lang == "zh":
        return "“暂缓/待批准”表示这是一份等待签名的草稿，没有卡住也没有付款：只有您用设备密钥对这份确切的草稿签名" + ("，并且家长共同批准，" if co else "") + "款项才会转出。"
    return ("'Held' means the payment is a draft waiting for approval, not stuck and not paid: it moves only after you sign this exact draft with your device key"
            + (" and a parent co-approves." if co else "."))


def _explain(S, lang: str, secrets=None) -> dict:
    cards = S.world.cards
    held = _held_note(S, lang)
    if not cards:
        return _result("explain", held or ("目前没有被拦截的付款。" if lang == "zh" else "Nothing has been stopped so far."), secrets)
    c = loc.localize_card(cards[-1], lang) if lang == "zh" else cards[-1]
    return _result("explain", (held + " " + c["text"]).strip(), secrets, rule=c.get("rule"))


def _next(S, lang: str, secrets=None) -> dict:
    if S.pending:
        t = (_held_note(S, lang) + (" 下一步：打开待批准的草稿，点击“签名并批准”。" if lang == "zh" else " Next: open the pending draft and tap Sign and approve."))
        return _result("help", t.strip(), secrets, status="info")
    allo = _open_obligations(S.world)
    listing = ("；" if lang == "zh" else "; ").join(_obl_line(S.world, o, lang) for o in allo) or ("无" if lang == "zh" else "none")
    t = (f"目前没有等待签名的草稿。待付账单：{listing}。说“交房租”即可开始。" if lang == "zh" else
         f"Nothing is waiting for your signature. Open bills: {listing}. Say 'pay my rent' (or tuition, deposit, phone bill) to start.")
    return _result("help", t, secrets, status="info")


def _bill_for(S, it: ChatIntent, message: str) -> list:
    w = S.world
    typ = it.slots.get("type") or _type_from_words(message)
    named = next((r for r in _recipients(w) if r.id == "payee_telecom"), None) if not typ and _PHONE.search(nlu.fix_typos(nlu.normalise(message))) else None
    return _open_obligations(w, typ, named.id if named else None)


def _estimate(S, it: ChatIntent, message: str, lang: str, secrets=None) -> dict:
    """An estimate for a bill, with no draft: what is owed and roughly what it takes to send it. Writes nothing."""
    w = S.world
    obs = _bill_for(S, it, message)
    if not obs:
        t = "没有找到匹配的待付账单，所以没有可估算的内容。" if lang == "zh" else "I found no matching open bill to estimate."
        return _result("estimate", t, secrets)
    if len(obs) > 1:
        lines = ("；" if lang == "zh" else "; ").join(f"{i}) {_obl_line(w, o, lang)}" for i, o in enumerate(obs, 1))
        t = (f"您想估算哪一笔？{lines}。这只是估算，不会创建任何草稿。" if lang == "zh" else
             f"Which bill should I estimate? {lines}. Estimates only; no draft is created.")
        return _result("estimate", t, secrets)
    ob = obs[0]
    qs = rank(quote_routes(w.rates, 100000.0, w.today, None, w.day_index))
    best = qs[0] if qs else None
    if best and best.delivered_cny > 0:
        need = ob.remaining * 100000.0 / best.delivered_cny
        if lang == "zh":
            t = (f"仅为估算，没有创建草稿，也没有任何资金转出。账单：{_obl_line(w, ob, lang)}。按最便宜且能按时到账的路线（{route_zh(best.route.name)}，约 {best.arrives_in_days} 天），"
                 f"大约需要汇出 ₹{need:,.0f}（演示价格 MOCK，不是报价）。需要时说“交{_OBL_ZH.get(ob.type, ob.type)}”，我会起草一份等您签名的草稿。")
        else:
            t = (f"Estimate only: no draft was created and nothing moved. Bill: {_obl_line(w, ob, lang)}. On the cheapest on-time route ({best.route.name}, "
                 f"about {best.arrives_in_days} day(s)) you would send roughly INR {need:,.0f} (MOCK prices, not a quote). "
                 f"Say 'pay my {ob.type}' when you want a draft to sign.")
    else:
        t = f"仅为估算：{_obl_line(w, ob, lang)}。没有创建草稿。" if lang == "zh" else f"Estimate only: {_obl_line(w, ob, lang)}. No draft was created."
    return _result("estimate", t, secrets)


def _later(S, it: ChatIntent, message: str, lang: str, secrets=None) -> dict:
    """Reminders, schedules and standing orders are not something chat sets up: every payment is signed when it is made."""
    obs = _bill_for(S, it, message)
    due = ("；" if lang == "zh" else "; ").join(_obl_line(S.world, o, lang) for o in obs[:3])
    if lang == "zh":
        t = ("我不能在聊天里设置提醒、定时付款或自动扣款：每一笔付款都要在支付当时由您用设备密钥签名。没有创建任何草稿，也没有任何资金转出。"
             + (f"相关账单：{due}。" if due else "") + "准备好时说“交房租”之类，我会起草一份等您签名的草稿。")
    else:
        t = ("I can't set reminders, schedules or automatic payments from chat: every payment is signed with your device key when it is made. "
             "No draft was created and nothing moved." + (f" Relevant bills: {due}." if due else "") +
             " Whenever you're ready, say 'pay my rent' (or another bill) and I'll draft it for your signature.")
    return _result("later", t, secrets)


def _unknown(S, message: str, lang: str, secrets=None) -> dict:
    """No dead end: name the nearest options and end with one question."""
    typ = nl_extract.purpose_in_text(message)
    pend = bool(S.pending)
    if lang == "zh":
        t = (f"您是想交{_OBL_ZH.get(typ, typ)}吗？说“交{_OBL_ZH.get(typ, typ)}”，我会起草一份等您签名的草稿。" if typ else
             "我没听明白。您想交账单、查余额，还是看汇率" + ("，或者取消草稿" if pend else "") + "？可以说“交房租”“交学费”“交押金”或“交话费”。")
    else:
        t = (f"Do you want me to prepare your {typ} payment? Say 'pay my {typ}' and I'll draft it for your signature." if typ else
             "I didn't catch that. Pay a bill, check your balance, or see the rate" + (", or cancel your draft" if pend else "") + "? "
             "Say for example 'pay my rent', 'pay my tuition', 'pay the deposit' or 'pay my phone bill'.")
    return _result(nlu.UNKNOWN, t, secrets, status="unknown")


def _proof(S, lang: str, secrets=None) -> dict:
    ids = list(S.world.proofs)
    if not ids:
        return _result("proof", "还没有证明包：付款完成后会生成。" if lang == "zh" else "No proof pack yet: one is created when a payment completes.", secrets)
    t = (f"最近的证明包：{ids[-1]}。任何人都可以在“证明”页面核验，无需登录。" if lang == "zh" else
         f"Latest proof pack: {ids[-1]}. Anyone can verify it in the Proof tab, no login needed.")
    return _result("proof", t, secrets, proof_id=ids[-1])


def _credit_growth(S, lang: str, secrets=None) -> dict:
    """Read-only summary of the credit-growth plan: verified record so far and the next milestone."""
    pl = cg.plan(S.world)
    v = pl["verified"]
    nxt = next((m for m in pl["milestones"] if not m["met"]), None)
    if lang == "zh":
        t = (f"信用成长计划（只读）：已核验付款 {v['payments']} 笔，其中按时 {v['on_time']} 笔。"
             + (f"下一个里程碑：{nxt['id']}（{nxt['current']}/{nxt['target']}）。" if nxt else "所有里程碑都已达成。")
             + "这不是信用评分，任何银行或征信机构都不承认它；数据为演示（MOCK）。完整计划见“护照”页。")
    else:
        t = (f"Credit growth plan (read-only): {v['payments']} verified payment(s), {v['on_time']} on time. "
             + (f"Next milestone: {nxt['id']} ({nxt['current']}/{nxt['target']}). " if nxt else "Every milestone is met. ")
             + "This is not a credit score and no bank or bureau accepts it; the data is MOCK. The full plan is in the Passport tab.")
    return _result("credit", t, secrets)


def _credit(S, lang: str, secrets=None) -> dict:
    n = S.world.passport.reputation.get("verified_on_time_payments", 0)
    t = (f"您已有 {n} 笔经核验的按时付款记录。信任通行证（Trust Pass）只基于这些已核验的记录；这不是信用评分，数据为演示（MOCK）。" if lang == "zh" else
         f"You have {n} verified on-time payment(s). The Trust Pass is built only from verified records like these; it is not a credit score, and the data is MOCK.")
    return _result("credit", t, secrets)


_HELP_EN = ("I can: pay a bill ('pay my rent', 'pay my tuition'), show your balance or bills, give today's rate or the cheapest route, "
            "say whether your money will last, convert (quote then confirm), set a rate target ('convert 2000 when the rate reaches 0.0700'), "
            "check a pasted invoice (or an uploaded screenshot or .eml email), cancel or correct a draft, and explain why something was stopped. Payments always end with your signature.")
_HELP_ZH = ("我可以：付账单（“交房租”“交学费”）、显示余额和待付账单、查询汇率和最便宜的路线、判断资金是否够用、兑换（先报价再确认）、"
            "设定汇率目标（“convert 2000 when the rate reaches 0.0700”）、检查粘贴的发票（或上传的截图、.eml 邮件）、取消或修改草稿，以及解释付款为何被拦截。付款最终一定需要您的签名。")


# ------------------------------------------------------------------ entry point
def handle(S, message: str, ui: str, *, jti: str, run_intake, secrets=None) -> dict:
    """One chat turn. `S` is the server session; `run_intake(Request) -> outcome dict` is the pipeline entry used by invoices.
    `source` in the result says who labelled the message: the keyword router, or (opt-in, F14) a model proposal that passed validation."""
    it = nlu.classify(message, ui)
    d = dialog_for(S.dialogs, jti)
    src = "router"
    if it.kind == nlu.UNKNOWN and not d["awaiting"] and chat_llm.enabled() and isinstance(S.world.llm, LiveLLM):
        m = chat_llm.propose(S.world.llm, message)
        if m is not None:
            it, src = m, "model"
    res = _handle(S, it, message, d, run_intake, secrets)
    res["source"] = src
    return res


# "I confirm the conversion" / "looks right, go ahead" while a conversion quote is waiting: same as a plain "yes".
_AFFIRM = re.compile(r"\bi confirm\b|\bconfirm(?:ed)? (?:the |that |this )?(?:conversion|quote)|\blooks? right\b|\bgo ahead\b|\bproceed\b|确认(?:兑换|换汇)", re.I)
_AFFIRM_NO = re.compile(r"\b(?:don'?t|do not|not|never|cancel|wait|before|until|unless)\b|不要|别|取消", re.I)


def _affirms(message: str) -> bool:
    """A short standalone confirmation only: pasted or long text that happens to contain 'go ahead' never confirms anything."""
    return len(message.strip()) <= 100 and bool(_AFFIRM.search(message)) and not _AFFIRM_NO.search(message)


def _handle(S, it: ChatIntent, message: str, d: dict, run_intake, secrets=None) -> dict:
    lang = it.lang
    if it.kind == nlu.UNKNOWN and nlu._SIGN_ASK.match(message.strip()):                   # "sign it": chat can't, and says so without touching any draft
        f = _find_pending(S, d)
        t = ("我不能替您签名。请点击“签名并批准”，由您的设备密钥对这份确切的草稿签名。" if lang == "zh" else
             "I can't sign for you. Tap Sign and approve so your device key signs the exact draft.")
        dr = (f[1]["outcome"].get("draft") or {}) if f else {}
        return _result("confirm", t, secrets, status="held" if f else "info", pending_id=f[0] if f else None,
                       draft_hash=dr.get("draft_hash"), needs=_needs(f[1]) if f else [])
    # an answer to the question asked last turn
    if d["awaiting"] == "confirm_convert":
        ctx = d["ctx"]
        d["awaiting"], d["ctx"] = None, {}
        if it.kind == nlu.CONFIRM or (it.kind not in nlu.REFUSALS and _affirms(message)):
            try:
                rec = currency_mod.convert(S.world, ctx["amount"], ctx["src"], ctx["dst"])
            except FxError as e:
                return _result("confirm", str(e), secrets, status="rejected")
            S.save()
            t = (f"已兑换：{rec['amount']:,.0f} {rec['from']} → {rec['received']:,.2f} {rec['to']}。" if lang == "zh" else
                 f"Converted {rec['amount']:,.0f} {rec['from']} to {rec['received']:,.2f} {rec['to']} between your own balances.")
            return _result("confirm", t, secrets, status="done")
        if it.kind in (nlu.DENY, nlu.CANCEL):
            return _result("deny", "好的，没有兑换。" if lang == "zh" else "Okay, I won't convert.", secrets, status="cancelled")
    elif d["awaiting"] and it.kind not in nlu.REFUSALS:
        r = _continue(S, run_intake, it, message, lang, d, secrets)
        if r is not None:
            return r
        if it.kind in _INFO_KINDS and d["awaiting"]:
            res = _handle(S, it, message, {**d, "awaiting": None}, run_intake, secrets)
            res["reply"] += (" （我之前的问题仍然有效。）" if lang == "zh" else " (My earlier question is still open.)")
            return res
    k = it.kind
    if k in nlu.REFUSALS:
        return refuse(S, it, lang, secrets)
    if k == nlu.PAY_INVOICE:
        o = loc.localize_outcome(run_intake(Request(message, source="invoice", remitter="student")), lang)
        d["last_pending"] = o.get("pending_id") or d["last_pending"]
        if lang == "zh":
            reply = (f"我已检查完毕。状态：{_STATUS_ZH.get(o['status'], o['status'])}。" + (f" {o['card']['text']}" if o.get("card") else "") +
                     (f" 证明包 {o['proof_id']} 已就绪。" if o.get("proof_id") else ""))
        else:
            reply = (f"I checked it. Status: {o['status']}." + (f" {o['card']['text']}" if o.get("card") else "") +
                     (f" Proof pack {o['proof_id']} is ready." if o.get("proof_id") else ""))
        item = S.pending.get(o.get("pending_id"), {})
        dr = o.get("draft") or {}
        return _result(k, reply, secrets, status=o["status"], pending_id=o.get("pending_id"), draft_hash=dr.get("draft_hash"),
                       needs=_needs(item) if item else [], money_moved=float(o.get("paid_cny") or 0), proof_id=o.get("proof_id"), outcome=o)
    if k == nlu.RATE_TARGET:
        if it.slots.get("incomplete"):
            rate = it.slots.get("rate")
            if rate:
                d["awaiting"], d["ctx"] = "slot_target_amount", {"rate": rate}
                t = (f"好的，汇率目标 {rate:.4f}。到达时要兑换多少人民币？回复一个金额，例如 2000。" if lang == "zh" else
                     f"Rate target {rate:.4f}: how much CNY should I convert when the rate reaches it? Reply with an amount, for example 2000.")
            else:
                t = ("要设定汇率目标，请说例如“convert 2000 when the rate reaches 0.0700”。" if lang == "zh" else
                     "To set a rate target, say for example 'convert 2000 when the rate reaches 0.0700'.")
            return _result(k, t, secrets, status="needs_info", needs=["info:amount"])
        return _rate_target(S, message, lang, secrets)
    if k == nlu.PAY_OBLIGATION:
        return _pay_obligation(S, run_intake, it, message, lang, d, secrets)
    if k == nlu.PAY_TEXT:
        return _pay_text(S, run_intake, it, message, lang, d, secrets)
    if k == nlu.CANCEL:
        return _cancel(S, lang, d, secrets, message)
    if k == nlu.DENY:
        return _cancel(S, lang, d, secrets) if _find_pending(S, d) and d.get("last_pending") else \
            _result("deny", "好的。" if lang == "zh" else "Okay.", secrets)
    if k == nlu.CONFIRM:
        f = _find_pending(S, d)
        if f:
            t = ("我不能替您签名。请点击“签名并批准”，由您的设备密钥对这份确切的草稿签名。" if lang == "zh" else
                 "I can't sign for you. Tap Sign and approve so your device key signs this exact draft.")
            dr = f[1]["outcome"].get("draft") or {}
            return _result("confirm", t, secrets, status="held", pending_id=f[0], draft_hash=dr.get("draft_hash"), needs=_needs(f[1]))
        return _result("confirm", "好的。有什么我可以帮您的？" if lang == "zh" else "Okay. What would you like me to do?", secrets)
    if k == nlu.CORRECT:
        return _correct(S, run_intake, it, message, lang, d, secrets)
    if k == nlu.UNDO:
        return _undo(S, lang, d, secrets)
    if k == nlu.BALANCE:
        return _balance(S, lang, secrets)
    if k == nlu.OBLIGATIONS:
        return _obligations(S, lang, secrets, message)
    if k == nlu.RATE:
        return _rate(S, lang, secrets, message)
    if k == nlu.ROUTES:
        return _routes(S, it, lang, secrets, message)
    if k == nlu.RUNWAY:
        return _runway(S, lang, secrets, message)
    if k == nlu.PLAN:
        return _plan(S, lang, secrets)
    if k == nlu.CONVERT:
        return _convert(S, it, lang, d, secrets, message)
    if k == nlu.STATUS:
        return _status(S, lang, d, secrets)
    if k == nlu.SPENDING:
        return _spending(S, lang, secrets)
    if k == nlu.EXPLAIN:
        return _explain(S, lang, secrets)
    if k == nlu.PROOF:
        return _proof(S, lang, secrets)
    if k == nlu.CREDIT:
        return _credit_growth(S, lang, secrets) if it.slots.get("growth") else _credit(S, lang, secrets)
    if k == nlu.ESTIMATE:
        return _estimate(S, it, message, lang, secrets)
    if k == nlu.LATER:
        return _later(S, it, message, lang, secrets)
    if k == nlu.NOPAY:
        t = ("明白了：我不会创建或更改任何付款。需要时可以问我余额、到期日、汇率或兑换报价。" if lang == "zh" else
             "Understood: I won't create or change any payment. Ask me for a balance, due dates, a rate or a conversion quote whenever you like.")
        return _result(k, t, secrets, status="info")
    if k == nlu.FAQ:
        return _faq(S, it.slots.get("topic"), lang, secrets, d)
    if k == nlu.GREETING and it.slots.get("thanks"):
        return _result(k, "不客气！还有什么需要我帮忙的吗？" if lang == "zh" else "You're welcome! Anything else I can help with?", secrets)
    if k == nlu.GREETING:
        return _result(k, ("您好！" if lang == "zh" else "Hello! ") + (_HELP_ZH if lang == "zh" else _HELP_EN), secrets)
    if k == nlu.HELP:
        if it.slots.get("next"):
            return _next(S, lang, secrets)
        if it.slots.get("reset"):
            t = ("我无法重置或查看登录口令；请联系沙盒的运营者。我可以帮您付账单、查余额。" if lang == "zh" else
                 "I can't reset or show a login passcode; ask whoever runs this sandbox. I can help with bills, balances and rates.")
            return _result(k, t, secrets)
        return _result(k, _HELP_ZH if lang == "zh" else _HELP_EN, secrets)
    if _affirms(message):                  # "I confirm" with no quote waiting: say so, never guess
        t = ("现在没有等待确认的兑换。先说“convert INR 10000 to CNY”，我会先报价，再由您确认。" if lang == "zh" else
             "No conversion is waiting for confirmation. Ask for a quote first (for example 'convert INR 10,000 to CNY') and I'll ask you to confirm it.")
        return _result(nlu.CONFIRM, t, secrets, status="info")
    return _unknown(S, message, lang, secrets)


def _faq(S, topic: str, lang: str, secrets, d: dict | None = None) -> dict:
    """Fixed how-it-works answers. Nothing here reads a credential or changes state."""
    zh = lang == "zh"
    if topic == "draft":
        f = _find_pending(S, d) if d is not None else None
        dr = (f[1]["outcome"].get("draft") or {}) if f else {}
        if dr:
            amt, name, purpose = float(dr.get("amount") or 0), _payee_name(S.world, dr.get("payee_id", "")), dr.get("purpose") or ""
            t = (f"这份草稿把 {money(amt, lang)} 付给 {name}（登记账户 {mask(dr.get('account_ref'))}），用途：{_PURPOSE_ZH.get(purpose, purpose)}。"
                 "在您用设备密钥签名之前不会转出任何款项；如果您不签名，草稿只会一直等待（也可以取消），不会有任何资金转出。" if zh else
                 f"This draft pays {money(amt, lang)} to {name} (registered account {mask(dr.get('account_ref'))}) for {purpose}. "
                 "Nothing moves until you sign it with your device key. If you don't sign, it just stays waiting (or you can cancel it) and no money leaves.")
        else:
            t = ("目前没有等待签名的草稿。任何草稿在您用设备密钥签名之前都不会转出款项；不签名就不会付款。" if zh else
                 "There is no draft waiting right now. A draft never moves money until you sign it with your device key; if you don't sign, nothing is paid.")
        return _result(nlu.FAQ, t, secrets, status="info")
    if topic == "safe":
        f = _find_pending(S, d) if d is not None else None
        dr = (f[1]["outcome"].get("draft") or {}) if f else {}
        extra = ""
        if dr:
            amt, name = float(dr.get("amount") or 0), _payee_name(S.world, dr.get("payee_id", ""))
            extra = (f"这份草稿是付给已登记收款方 {name} 的 {money(amt, lang)}。" if zh else
                     f"This draft is {money(amt, lang)} to {name}, a registered payee. ")
        t = (extra + "是的，有这些保护：只会付给登记册里经过验证的账户（不会按文本里的账号付款）；款项只有在您用设备密钥对确切草稿签名后才会转出；"
             "我无法批准或签名；检查和证明都有记录可查。所有资金都是模拟的（MOCK）。" if zh else
             extra + "Here is what protects it: money goes only to a verified account in the registry (never an account typed into chat), nothing moves until you "
             "sign the exact draft with your device key, I can't approve or sign anything myself, and every decision is recorded in a tamper-evident audit log. "
             "All money here is simulated (MOCK).")
        return _result(nlu.FAQ, t, secrets, status="info")
    if topic == "payees":
        names = ("、" if zh else ", ").join(f"{r.name}" for r in _recipients(S.world) if r.payee_type != "student")
        t = f"我只能付给登记册里的收款方：{names}。" if zh else f"I can pay only the payees in the registry: {names}."
    elif topic == "sign":
        t = ("在应用里签名：打开待批准的草稿，点击“签名并批准”，由您的设备密钥对这份确切的草稿签名。签名后系统会再次核对草稿和规则，才会付款到登记账户。我不能替您签名。" if zh else
             "Sign in the app: open the pending draft and tap Sign and approve, so your device key signs that exact draft. After you sign, the system re-checks the signed draft and the rules, then pays the registry account; if anything changed, nothing is paid. I can't sign for you.")
    else:
        t = ("Oasis 是一个模拟（MOCK）沙盒里的助手，帮在国外的学生付账单：它只起草付给登记收款方的付款，由您用设备密钥签名后才会执行。所有数据和资金都是模拟的。" if zh else
             "Oasis is an assistant in a MOCK sandbox that helps a student abroad pay bills: it only drafts payments to registered payees, and nothing is paid until you sign with your device key. All data and money are simulated.")
    return _result(nlu.FAQ, t, secrets, status="info")


_STATUS_ZH = {"paid": "已支付", "held": "已暂缓，等待批准", "frozen": "已冻结", "rejected": "已拒绝", "needs_verification": "需要验证"}


def _rate_target(S, message: str, lang: str, secrets=None) -> dict:
    m = nlu.TARGET_RE.search(message)
    mz = None if m else nlu.TARGET_RE_ZH.search(message)
    if mz:
        m = (mz.group(2), mz.group(1)) if mz.group(1) else (mz.group(3), mz.group(4))
    amount, rate = ((float(m[0].replace(",", "")), float(m[1])) if isinstance(m, tuple)
                    else (float(m.group(1).replace(",", "")), float(m.group(2))))
    return _set_target(S, rate, amount, lang, secrets)


def _set_target(S, rate: float, amount: float, lang: str, secrets=None) -> dict:
    t = S.agent.set_rate_target(rate, amount)
    S.save()
    lim = S.world.passport.rules.tier1_auto_convert_cny
    if lang == "zh":
        reply = (f"已设定汇率目标：我会关注 INR 对 CNY 的汇率，当它达到 {rate:.4f} 时，" +
                 (f"自行兑换 ¥{amount:,.0f}（在您的 1 级自动额度之内）。" if amount <= lim
                  else f"在您批准之后兑换 ¥{amount:,.0f}（超过 ¥{lim:,.0f} 的自动额度）。") + " 我不会预测汇率，只会按您设定的目标行动。")
    else:
        reply = (f"Rate target set: I will watch INR to CNY and, when it reaches {rate:.4f}, convert CNY {amount:,.0f} "
                 + ("on my own (within your Tier-1 limit)." if amount <= lim else f"after you approve it (above your CNY {lim:,.0f} auto limit).")
                 + " I do not predict rates; I only act on your target.")
    return _result(nlu.RATE_TARGET, reply, secrets, status="done", target=t)
