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
from datetime import date

from ..mock.fx import CURRENCIES, FxError, mid as fx_mid, quote as fx_quote, table_for
from ..mock.rates import ROUTES
from ..passport import currency as currency_mod
from ..flightpath import core as fpath
from ..planning import fxplan, spending
from ..planning import validator as plan_validator
from ..planning.forecast import cover_position, monthly_burn, runway_months, triggers
from ..planning.routes import inr_needed, quote_routes, rank
from ..trust.policy import RISK_HOLD
from ..proof import credit_growth as cg
from ..trust import corridor
from ..market import provenance
from . import localize as loc
from . import activity, chat_llm, faq, frames, glossary, fx_exec, nl_extract, nlu, robust, router_v2
from . import context as ctx_mod
from . import scorecard as scorecard_mod
from . import scam_lane
from .llm import LiveLLM, heuristic_risk
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
    return {"awaiting": None, "ctx": {}, "last_pending": None, "last_paid": None, "last_cancelled": None, "log": []}


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


def _mask_fields(o):
    """The account read out of a document is shown masked in a chat reply; the signable draft (registry account) is left exact."""
    f = o.get("fields") if isinstance(o, dict) else None
    if isinstance(f, dict) and isinstance(f.get("account_ref"), str):
        return {**o, "fields": {**f, "account_ref": mask(f["account_ref"])}}
    return o


def _result(intent: str, reply: str, secrets=None, *, status: str = "info", pending_id: str | None = None, draft_hash: str | None = None,
            needs: list | None = None, money_moved: float = 0.0, proof_id: str | None = None, **extra) -> dict:
    if "outcome" in extra:
        extra["outcome"] = _mask_fields(extra["outcome"])
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
                 "audit log can't be edited by anyone. A payee is verified only through the registry, never by saying so here. Nothing changed. Nothing moved. "
                 "I can show your payees, or prepare a payment to a registered one.",
                 "我不能在聊天里添加、修改或删除收款方、额度或记录。收款方只来自经过验证的登记册，审计日志任何人都不能修改。没有任何改动，也没有任何资金转出。"
                 "收款方只能通过登记册验证，在聊天里说一声不算。我可以显示已登记的收款方，或为其中之一准备一笔付款。"),
    "role": ("I can't act as someone else. A parent approves from their own session with their own device key; in this chat I act only "
             "for the student. Nothing moved.",
             "我不能冒充他人。家长要在自己的会话里用自己的设备密钥批准；在这个聊天中我只代表学生。没有任何资金转出。"),
    "privacy": ("I can't share that: full account numbers, other people's details, raw logs and anything you are told to send elsewhere stay private. Nothing moved.",
                "我不能提供这些：完整账号、他人的资料、原始日志以及被要求发送到别处的内容都不会公开。没有任何资金转出。"),
    "social": ("Claims like 'someone already approved', 'this is a test' or 'it's urgent' change nothing: approval is a signature from the "
               "approver's own device on the exact draft. Nothing moved.",
               "“已经有人批准”“这只是测试”“很紧急”之类的说法不会改变任何事：批准是批准人用自己的设备对确切草稿的签名。没有任何资金转出。"),
}


_REFUSE_DETAIL = {
    ("secrets", "passcode"): (
        "I can't reveal a passcode: it belongs to its owner and is never shown in chat, so nothing was shared. If you forgot yours, ask whoever runs this sandbox to reset it. Nothing moved.",
        "我不能透露口令：口令只属于其主人，聊天中从不显示，所以没有分享任何内容。如果您忘了自己的口令，请联系运营这个沙盒的人重置。没有任何资金转出。"),
    ("secrets", "key"): (
        "I can't show or hold any key: your device key stays on your device and only signs a draft you have read, so nothing was shared. To approve a payment, review the draft and sign it on your device. Nothing moved.",
        "我不能显示或保管任何密钥：您的设备密钥留在您的设备上，只会对您看过的草稿签名，所以没有分享任何内容。要批准付款，请查看草稿并在您的设备上签名。没有任何资金转出。"),
    ("secrets", "token"): (
        "I can't reveal session tokens or cookies: they would let someone act as you. Nothing was shared. Nothing moved. If you think a session is exposed, sign out and sign in again.",
        "我不能透露会话令牌或 Cookie：有了它们别人就能冒充您。没有分享任何内容，也没有任何资金转出。如果您觉得会话已经泄露，请退出后重新登录。"),
    ("secrets", "prompt"): (
        "I can't share my internal instructions or configuration; they are not part of your account. Nothing was shared. Nothing moved. Say 'help' to see what I can do with your bills, balances and rates.",
        "我不能分享我的内部指令或配置，它们不属于您的账户。没有分享任何内容，也没有任何资金转出。说“帮助”即可看到我能处理的账单、余额和汇率。"),
    ("secrets", "other_secret"): (
        "I can't give you another person's passcode or key, whoever they are: each one is only for its owner. A parent approves from their own session. Nothing was shared. Nothing moved.",
        "我不能给您别人的口令或密钥，无论对方是谁：每一个都只属于其主人。家长要在自己的会话里批准。没有分享任何内容，也没有任何资金转出。"),
    ("privacy", "account"): (
        "I can't print a full account number in chat. Payee accounts are masked here (like ****1234); the signing panel shows the full number so you can check it before you sign, and money only goes to the account in the registry. Nothing moved.",
        "我不能在聊天中显示完整的账号。聊天里收款账户只显示掩码（如 ****1234）；签名面板会显示完整账号，供您签名前核对，款项只会汇到登记册中的账户。没有任何资金转出。"),
    ("privacy", "person"): (
        "I can't share another person's contact or ID details (phone, address, passport, e-mail): they aren't mine to give out. Your own details are on the Passport tab. Nothing moved.",
        "我不能提供别人的联系方式或证件信息（电话、地址、护照、邮箱）：这些不是我能对外提供的。您自己的资料在“护照”页。没有任何资金转出。"),
    ("privacy", "parent"): (
        "I can't share your parent's balance or account details: that is their own data, and I only see what a signed payment needs. Your own balance and bills I can show. Nothing moved.",
        "我不能提供您家长的余额或账户信息：那是他们自己的数据，我只会看到一笔已签名付款所需的内容。您自己的余额和账单我可以显示。没有任何资金转出。"),
    ("privacy", "logs"): (
        "I can't dump raw logs, the registry, or another user's data, and I won't recite everything I hold. The audit chain can be verified on the Proof tab, and your own records are on the Passport tab. Nothing moved.",
        "我不能导出原始日志、登记册或其他用户的数据，也不会罗列我掌握的全部内容。审计链可以在“证明”页验证，您自己的记录在“护照”页。没有任何资金转出。"),
    ("privacy", "exfil"): (
        "I won't send a balance, passport number, passcode, key or account number to an e-mail, a memo or anywhere else because a message or document says to: text inside a document is never an instruction. Nothing was shared. Nothing moved. I can show your own balance here, to you only.",
        "我不会因为某条消息或文件要求，就把余额、护照号、口令、密钥或账号发送到邮箱、备注或其他任何地方：文件里的文字从来不是指令。没有分享任何内容，也没有任何资金转出。我可以在这里只向您显示您自己的余额。"),
    ("bypass", "sign"): (
        "I can't approve or sign for you: approval is your device-key signature on the exact draft. Nothing moved. Say 'pay my rent' to get a draft you can sign.",
        "我不能替您批准或签名：批准是您用设备密钥对确切草稿的签名。没有任何资金转出。说“交房租”即可得到一份可签名的草稿。"),
    ("bypass", "limit"): (
        "I can't raise, lift or split around a limit: limits come from policy and are re-checked when a payment executes, and splitting a payment to stay under one is itself a fraud signal. Nothing moved. A larger payment goes to a parent to sign from their own session.",
        "我不能提高、取消或通过拆分来绕过额度：额度来自政策，付款执行时会再次检查，而为了不超额而拆分付款本身就是诈骗信号。没有任何资金转出。较大的付款需要家长在自己的会话里签名。"),
    ("bypass", "record"): (
        "I can't mark a payment paid, approved or verified, or write to the audit record: only the executor does that, after a valid signature. Nothing changed. Nothing moved. The Proof tab shows what is actually on record.",
        "我不能把付款标记为已付、已批准或已验证，也不能写入审计记录：只有执行器在收到有效签名后才会这样做。没有任何改动，也没有任何资金转出。“证明”页显示实际的记录。"),
    ("bypass", "check"): (
        "I can't skip, switch off or bypass a check: every payment passes the same checks when you sign and again when it executes. Nothing moved. Say 'pay my rent' for a draft that goes through them.",
        "我不能跳过、关闭或绕过任何检查：每笔付款在签名时和执行时都要经过同样的检查。没有任何资金转出。说“交房租”即可得到一份会经过这些检查的草稿。"),
    ("registry", "audit"): (
        "I can't delete or edit the audit log: every entry is hash-chained so changes are detectable. You can verify the chain on the Proof tab. Nothing changed. Nothing moved.",
        "我不能删除或修改审计日志：每一条记录都经过哈希链接，任何改动都能被发现。您可以在“证明”页验证这条链。没有任何改动，也没有任何资金转出。"),
    ("registry", "payee"): (
        "I can't add, change or remove payees from chat: payees come only from the verified registry, and a payee is verified only through the registry, never by saying so here. Nothing changed. Nothing moved. I can show your registered payees, or prepare a payment to one of them.",
        "我不能在聊天里添加、修改或删除收款方：收款方只来自经过验证的登记册。没有任何改动，也没有任何资金转出。我可以显示已登记的收款方，或为其中之一准备一笔付款。"),
    ("registry", "verify"): (
        "I can't mark a payee verified: a payee is verified only through the registry, never by saying so here. Nothing changed. Nothing moved. I can prepare a payment to a payee that is already registered.",
        "我不能把收款方标记为已验证：验证只能通过登记册完成，在这里说一声不算。没有任何改动，也没有任何资金转出。我可以为已登记的收款方准备一笔付款。"),
    ("registry", "account"): (
        "I can't change a payee's account: money goes only to the account in the registry, and a payee is verified only through the registry, never by saying so here. Nothing changed. Nothing moved. If an account really changed, the registry has to be updated and verified first.",
        "我不能修改收款方的账户：款项只会汇到登记册中的账户。没有任何改动，也没有任何资金转出。如果账户确实变了，需要先更新并验证登记册。"),
}
_CONCEPT_HELP = {
    "login": ("Signing in takes the role passcode your sandbox gave you. Approving a payment is separate: it needs your device key's signature on the exact draft. I never see either one, and I won't ask you to type them here.",
              "登录需要沙盒给您的角色口令。批准付款是另一回事：需要您的设备密钥对确切草稿签名。这两样我都看不到，也不会让您在这里输入。"),
    "device_key": ("A device key is a private key that stays on your device. It signs the exact payment draft you approve, so nobody else, including me, can approve for you. I never see it.",
                   "设备密钥是留在您设备上的私钥。它会对您批准的确切付款草稿签名，所以别人（包括我）都无法替您批准。我看不到它。"),
    "sign": ("You sign because a payment only moves when you approve the exact draft (payee, amount and hash) with your device key. That keeps me, a document or another person from moving money without you.",
             "您需要签名，因为只有您用设备密钥批准确切的草稿（收款方、金额和哈希）后款项才会转出。这样我、文件或其他人都无法在没有您的情况下转走资金。"),
    "safe": ("Passcodes and keys are never shown in chat, and I can't read or reveal them. Your device key stays on your device, and the audit log records only that a request was refused, never its text.",
             "口令和密钥不会在聊天中显示，我也无法读取或透露它们。您的设备密钥留在您的设备上，审计日志只记录请求被拒绝，不记录请求的内容。"),
}


def _refusal_text(cat: str, detail: str, lang: str) -> tuple[str, str]:
    """Each refusal names what was asked, why it can't be done and one safe next step. Wording only: the decision was made upstream."""
    if cat == "role":
        who = detail if detail and detail != "other" else "someone else"
        return (f"I can't act as {who}: a parent approves from their own session with their own device key, and in this chat I act only for the student. Nothing moved. Ask them to sign in themselves.",
                f"我不能以“{who}”的身份行事：家长要在自己的会话里用自己的设备密钥批准，在这个聊天中我只代表学生。没有任何资金转出。请让对方自己登录。")
    return _REFUSE_DETAIL.get((cat, detail)) or _REFUSE.get(cat, _REFUSE["bypass"])


def refuse(S, intent: ChatIntent, lang: str, secrets=None) -> dict:
    cat = intent.category or "bypass"
    en, zh = _refusal_text(cat, intent.slots.get("detail") or "", lang)
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


def _new_payee_reply(S, kind: str, lang: str, secrets=None) -> dict:
    """A person who is not in the registry: explain the two ways forward. No draft, and an account number in the text is never stored or used."""
    S.world.audit.append("chat_unregistered_payee", {"asked_type": None})
    S.save()
    t = ("对方不是已登记的收款方。我只能付给登记册里的收款方，新收款方必须先经登记册核验，我不会使用消息里的账号。如果这是家人给您的生活费，请说“规划我的学期”，计划里包含由家长同意并签名的汇款；"
         "如果要付给朋友，请让对方先在登记册中登记。没有创建任何草稿，CNY 0 转出。" if lang == "zh" else
         "That person is not a registered payee. I can pay only payees in the registry, and a new payee has to be verified there first; I never use an account taken from a message. If this is family support, say 'plan my semester': "
         "the plan includes a parent remittance that your parent consents to and signs. For a friend, ask them to be registered first. I made no draft and CNY 0 moved.")
    return _result(kind, t, secrets, status="rejected")


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
_PERSON = re.compile(r"\b(?:to|for)\s+(?:my\s+)?(?:friend|mother|mom|mum|father|dad|parents?|cousin|brother|sister|uncle|aunt|roommate|classmate|girlfriend|boyfriend)\b|给我的?(?:朋友|妈妈|爸爸|父母|表哥|表弟|哥哥|姐姐)", re.I)
_BILL_KEYWORDS = (
    ("payee_telecom", _PHONE),
    ("payee_power", re.compile(r"electric|power bill|电费|水电", re.I)),
    ("payee_internet", re.compile(r"internet|broadband|wi-?fi|宽带|网费", re.I)),
    ("payee_health", re.compile(r"insurance|保险", re.I)),
    ("payee_visa", re.compile(r"" + chr(92) + r"bvisa|residence permit|residency|签证|居留", re.I)),
    ("payee_library", re.compile(r"librar|图书馆", re.I)),
    ("payee_gym", re.compile(r"" + chr(92) + r"bgym|membership|健身", re.I)),
    ("payee_peer_priya", re.compile(r"" + chr(92) + r"bpriya" + chr(92) + r"b", re.I)),
)


def _keyword_payee(w, text: str):
    """The registered payee a bill word points to (phone, electricity, internet, insurance, visa fee, library, gym), or None where the world has none."""
    for pid, rx in _BILL_KEYWORDS:
        if rx.search(text):
            r = next((r for r in _recipients(w) if r.id == pid), None)
            if r is not None:
                return r
    return None


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
    if not named and not typ:
        named = _keyword_payee(w, nlu.fix_typos(nlu.normalise(message)))               # None where the world has no such payee: falls to the unregistered-bill reply
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
    if not typ and not named and _PERSON.search(message):                      # "send 5000 yuan to my mother / friend Li Wei": a person, not a registry payee
        return _new_payee_reply(S, it.kind, lang, secrets)
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
        t = (f"“{unreg}”不是已登记的收款方，我只能付给：{names}。新收款方必须先经登记册核验，我不会使用消息里的账号。如果是家人给您的生活费，请说“规划我的学期”，计划里包含由家长同意并签名的汇款；"
             f"如果要付给朋友，请让对方先在登记册中登记。" if lang == "zh" else
             f"“{unreg}” is not a registered payee. I can pay only: {names}. A new payee has to be verified through the registry first, and I never use an account taken from a message. "
             f"If this is family support, say 'plan my semester': the plan includes a parent remittance your parent consents to and signs. For a friend, ask them to be registered first.")
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
        done = [o for o in w.passport.obligations if o.status == "paid" and (not typ or o.type == typ) and (not named or o.payee_id == named.id)] if (typ or named) else []
        if done:                                                   # a bill that is already settled: say so, with the proof, instead of "no open bill"
            o = done[-1]
            pr = f" (proof {list(w.proofs)[-1]})" if w.proofs else ""
            pr_zh = f"（证明包 {list(w.proofs)[-1]}）" if w.proofs else ""
            t = (f"{_OBL_ZH.get(o.type, o.type)}已经付清（{money(o.amount, lang)}）{pr_zh}，无需再付。其他待付账单：{listing}。" if lang == "zh" else
                 f"Your {o.type} ({money(o.amount, lang)}) is already paid{pr}. Nothing to pay. Other open bills: {listing}.")
            return _result(it.kind, t, secrets, status="info", already_paid=o.id)
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
    if not amt and it.slots.get("instalment"):                            # "pay tuition in instalments": N equal parts offered, the first one confirmed, then a normal held draft
        n = int(it.slots.get("n_parts") or 2)
        amt = round(ob.remaining / n, 2)
        res = _part_prompt(w, ob, amt, lang, d, it.kind, secrets)
        res["reply"] += (f" 这是 {n} 期中的第 1 期，之后还剩 {money(ob.remaining - amt, lang)}，每一期都要您单独签名。想分成别的期数请说“分三期”。" if lang == "zh" else
                         f" This is part 1 of {n} equal parts; {money(ob.remaining - amt, lang)} would remain, and every part is signed separately. Say 'three parts' for a different split.")
        return res
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


_FRESH_KINDS = (nlu.CONVERT, nlu.ESTIMATE, nlu.LATER, nlu.FAQ, nlu.UNDO)
_INFO_KINDS = (nlu.FINANCE_SUMMARY, nlu.BALANCE, nlu.OBLIGATIONS, nlu.RATE, nlu.ROUTES, nlu.RUNWAY, nlu.STATUS, nlu.PLAN, nlu.PROOF, nlu.CREDIT,
               nlu.EXPLAIN, nlu.HELP, nlu.SPENDING, *nlu.TOPIC_KINDS)


def _continue(S, run_intake, it: ChatIntent, message: str, lang: str, d: dict, secrets=None) -> dict | None:
    """Answer to the question asked last turn. None = this message is not an answer, so it is handled as a fresh request."""
    w, aw, ctx = S.world, d["awaiting"], d["ctx"]
    if it.kind in _FRESH_KINDS or it.slots.get("instalment"):                      # a clear new request ("quote", "undo", a reminder): drop our question and handle it normally
        d["awaiting"], d["ctx"] = None, {}
        return None
    if aw == "cancel_which":
        opts = [p_ for p_ in ctx.get("options", []) if p_ in S.pending]
        m = re.fullmatch(r"\D*(\d)\D*", nlu.normalise(message))
        if m and 1 <= int(m.group(1)) <= len(opts):
            pid = opts[int(m.group(1)) - 1]
            dr = S.pending[pid]["outcome"].get("draft") or {}
            _decline(S, pid, "cancelled_via_chat")
            S.save()
            d["awaiting"], d["ctx"], d["last_cancelled"] = None, {}, dr.get("purpose")
            if d.get("last_pending") == pid:
                d["last_pending"] = None
            left = len(S.pending)
            return _result("cancel", (f"已取消该草稿，没有任何资金转出。还有 {left} 份草稿等待您签名。" if lang == "zh" else
                                      f"Cancelled that draft. Nothing moved. {left} other draft(s) still wait for your signature."), secrets, status="cancelled", pending_id=pid)
        r = _cancel_one(S, lang, d, message, secrets) if not m else None
        if r is not None:
            if r["status"] == "cancelled":
                d["awaiting"], d["ctx"] = None, {}
            return r
        if it.kind in (nlu.DENY, nlu.CANCEL):
            d["awaiting"], d["ctx"] = None, {}
            return _result("deny", "好的，没有取消任何草稿。" if lang == "zh" else "Okay, I left your drafts as they are.", secrets, status="held")
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
            return _set_target(S, float(ctx["rate"]), a[0], lang, secrets, run_intake, d)
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
    if len({(i_["outcome"].get("draft") or {}).get("purpose") for i_ in S.pending.values()}) > 1:       # never guess between different bills: name them and wait
        opts = list(S.pending)
        lines = []
        for i, pid in enumerate(opts, 1):
            dr = S.pending[pid]["outcome"].get("draft") or {}
            purpose = _PURPOSE_ZH.get(dr.get("purpose"), dr.get("purpose")) if lang == "zh" else dr.get("purpose")
            lines.append(f"{i}. {purpose} {money(float(dr.get('amount') or 0), lang)} {'→' if lang == 'zh' else 'to'} {_payee_name(S.world, dr.get('payee_id', ''))}")
        d["awaiting"], d["ctx"] = "cancel_which", {"options": opts}
        if lang == "zh":
            t = f"您有 {len(opts)} 份草稿在等待，要取消哪一份？回复编号或名称（例如“取消房租”）。目前没有取消任何草稿。" + "；".join(lines)
        else:
            t = (f"Which draft should I cancel? You have {len(opts)} waiting. Reply with a number or a name (for example 'cancel the rent draft'). "
                 "Nothing is cancelled yet. " + "; ".join(lines))
        return _result("cancel", t, secrets, status="needs_info", needs=["info:draft"])
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
    if not typ and not named:
        named = _keyword_payee(w, nlu.normalise(message))
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


_UNDO_DRAFT = re.compile(r"\bundo\b|撤销|\b(?:revers\w*|withdraw|discard)\b[^.?!]{0,15}\bdraft\b", re.I)


def _undo(S, lang: str, d: dict, secrets=None, advice: bool = False) -> dict:
    if not advice and _find_pending(S, d):  # nothing was sent yet, so undoing a draft is withdrawing it
        return _cancel(S, lang, d, secrets)
    proofs = list(S.world.proofs)
    if advice:                              # "paid twice by mistake" / "refund": tell them who can fix it; no draft is touched
        j = next(iter(S.journeys), None)
        if lang == "zh":
            t = ("我无法退款或撤销已付款项，也没有改动任何草稿。请联系收款方或服务商，说明重复或误付并要求退回；如果是通过 Oasis 汇出的，"
                 "可以在 FlightPath 中发起追回（演示数据，MOCK）" + (f"，行程编号 {j}。" if j else "。") + "您的待签草稿保持不变。")
        else:
            t = ("I can't refund or reverse a payment, and I haven't changed any draft. Contact the payee or provider, explain the duplicate or mistaken payment and ask "
                 "for it back; if it went out through Oasis, FlightPath can start a recall (MOCK rails)" + (f" for journey {j}." if j else ".") + " Your pending drafts are unchanged.")
        return _result("undo", t, secrets, status="info", proof_id=proofs[-1] if proofs else None)
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
    """All six wallet currencies, zero balances included, so the student sees what the wallet can hold."""
    pp = S.world.passport
    sym = {"INR": "₹", "CNY": "¥", "USD": "$", "EUR": "€", "GBP": "£", "AUD": "A$"}
    parts = [f"{sym[c]}{pp.balance(c):,.0f}" for c in CURRENCIES]
    t = ("您有 " + "、".join(parts) + "。（演示数据，MOCK）") if lang == "zh" else ("You have " + ", ".join(parts[:-1]) + " and " + parts[-1] + ". (MOCK sandbox balances)")
    return _result("balance", t, secrets)


_DUE_Q = re.compile(r"\bhow much\b|\bwhen\b|\bdue\b|多少|什么时候|何时|到期", re.I)


def _obligations(S, lang: str, secrets=None, message: str = "") -> dict:
    w = S.world
    typ = nl_extract.purpose_in_text(message) if message else None
    o = _open_obligations(w, typ) or _open_obligations(w)
    if not o:
        return _result("obligations", "您目前没有待付款项。" if lang == "zh" else "You have nothing due right now.", secrets)
    if typ and len(o) == 1 and o[0].type == typ and _DUE_Q.search(message):       # "how much is the deposit and when is it due?" asks about that one bill
        x = o[0]
        t = (f"{_OBL_ZH.get(x.type, x.type)}：{money(x.remaining, lang)}，到期日 {x.due}。" if lang == "zh" else
             f"{x.type.capitalize()}: {money(x.remaining, lang)}, due {x.due}.")
        return _result("obligations", t, secrets)
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
    if it.slots.get("topic") == "transfer_time" or (it.slots.get("topic") == "bank_vs_app" and not nl_extract.purpose_in_text(message)):    # a named bill gets the bill-sized comparison below
        return _transfer_time(S, lang, secrets, it.slots["topic"] == "bank_vs_app")
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
    typ = nl_extract.purpose_in_text(message) if message else None
    bills = _open_obligations(w, typ) if typ and not amt else []
    if len(bills) == 1:                              # "compare bank vs apps for my tuition": size the quote to that bill and show the bank route
        ob = bills[0]
        due = date.fromisoformat(str(ob.due))
        ranked0 = rank(quote_routes(w.rates, 100000.0, w.today, due, w.day_index))
        route0 = (ranked0[0] if ranked0 else next(q for q in quote_routes(w.rates, 100000.0, w.today, None, w.day_index) if not q.route.typical_bank)).route
        send = inr_needed(w.rates, route0, ob.remaining, w.day_index)
        allq = quote_routes(w.rates, send, w.today, due, w.day_index)
        bank = next(q for q in allq if q.route.typical_bank)
        okq = rank(allq)
        best = okq[0] if okq else max((q for q in allq if not q.route.typical_bank), key=lambda q: q.delivered_cny)
        saved = best.delivered_cny - bank.delivered_cny
        apps = "; ".join(f"{q.route.name} about CNY {q.delivered_cny:,.0f} ({q.arrives_in_days} day(s))" for q in allq if not q.route.typical_bank)
        if lang == "zh":
            t = (f"您的{_OBL_ZH.get(ob.type, ob.type)} {money(ob.remaining, lang)}（{ob.due} 到期），汇出约 ₹{send:,.0f}：{route_zh(best.route.name)}约到账 ¥{best.delivered_cny:,.0f}（{best.arrives_in_days} 天）；"
                 f"常规银行电汇（SWIFT）约到账 ¥{bank.delivered_cny:,.0f}（{bank.arrives_in_days} 天），相比银行多到账约 ¥{saved:,.0f}。（演示数据，MOCK；只是比较，没有创建草稿）")
        else:
            t = (f"For your {ob.type} ({money(ob.remaining, lang)}, due {ob.due}), sending about INR {send:,.0f}: {best.route.name} delivers about CNY {best.delivered_cny:,.0f} "
                 f"in {best.arrives_in_days} day(s). The typical bank route ({bank.route.name}) delivers about CNY {bank.delivered_cny:,.0f} in {bank.arrives_in_days} day(s), "
                 f"so {best.route.name} saves about CNY {saved:,.0f}. All routes: {apps}. (MOCK prices; a comparison only, no draft made.)")
        return _result("routes", t, secrets)
    base = float(amt or 100000)
    qs = rank(quote_routes(w.rates, base, w.today, None, w.day_index))[:3]
    best = qs[0]
    if it.slots.get("quote"):                    # a "how much will I get" question: the answer first, then every route, no draft
        if lang == "zh":
            lines = "；".join(f"{route_zh(q.route.name)} 约 ¥{q.delivered_cny:,.0f}（{q.arrives_in_days} 天）" for q in qs)
            t = f"汇出 ₹{base:,.0f}，走{route_zh(best.route.name)}约到账 ¥{best.delivered_cny:,.0f}，这是按时到账的最佳路线。各路线：{lines}。（演示数据，MOCK；只是报价，没有创建草稿）"
        else:
            lines = "; ".join(f"{q.route.name} about CNY {q.delivered_cny:,.0f} ({q.arrives_in_days} day(s))" for q in qs)
            t = f"INR {base:,.0f} gets you about CNY {best.delivered_cny:,.0f} via {best.route.name}, the best on-time route. By route: {lines}. (MOCK prices; a quote only, no draft made.)"
        return _result("routes", t, secrets)
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
    pos = cover_position(pp, w.rates, w.day_index)
    alerts = triggers(pp, w.rates, w.today, w.day_index)
    if pos["shortfall_cny"]:
        alerts = [x for x in alerts if x.kind != "low_runway"]        # the shortfall sentence already says it; "0.0 months" adds nothing
    if lang == "zh":
        lead = (f"您的待付账单共 ¥{pos['bills_cny']:,.0f}，账户余额按今日汇率约合 ¥{pos['available_cny']:,.0f}，缺口约 ¥{pos['shortfall_cny']:,.0f}。我可以帮您制定计划。"
                if pos["shortfall_cny"] else f"付清应付款项后，您的资金可维持约 {m:.1f} 个月（按每月约 ¥{burn:,.0f} 的开销）。")
        t = (lead + ("目前有提醒：" + " ".join(a.message for a in alerts) if alerts else "目前没有提醒。") + "这是估算，不是保证。")
    else:
        if pos["shortfall_cny"]:
            lead = (f"Your open bills total CNY {pos['bills_cny']:,.0f} and your balances are worth about CNY {pos['available_cny']:,.0f} at today's MOCK rate, "
                    f"so you are about CNY {pos['shortfall_cny']:,.0f} short. I can build a plan.")
        else:
            short = " You may run short; I can build a plan." if m < pp.rules.runway_alert_months else ""
            lead = f"After your open bills, your money lasts about {m:.1f} months at roughly CNY {burn:,.0f} a month." + short
        t = (lead + (" Alerts: " + " ".join(a.message for a in alerts) if alerts else " No alerts.") + " This is an estimate, not a guarantee.")
    typ = nl_extract.purpose_in_text(message)
    need = sum(o.remaining for o in _open_obligations(w, typ)) if typ else 0
    if need:                                  # "do I have enough to cover tuition?": compare the CNY balance with that bill
        bal = pp.balance("CNY")
        if lang == "zh":
            t += f" 您的人民币余额 {money(bal, lang)}，{_OBL_ZH.get(typ, typ)}待付 {money(need, lang)}：" + ("够付。" if bal + 0.005 >= need else "不够，需要先兑换一部分卢比。")
        else:
            t += f" Your CNY balance is {money(bal, lang)} and your open {typ} is {money(need, lang)}: " + ("covered." if bal + 0.005 >= need else "not enough yet, convert some INR first.")
    return _result("runway", t, secrets)


def _plan(S, lang: str, secrets=None, d: dict | None = None) -> dict:
    w = S.world
    rec = propose(w, DeterministicPlanner(), "Plan my semester payments")
    S.save()
    why = (rec.get("why") or [rec.get("rationale") or ""])[:2]
    first = min(_open_obligations(w), key=lambda o: o.due, default=None)
    nxt_en = f" Next: say 'pay the {first.type}' and I'll draft the earliest bill for your signature." if first else ""
    nxt_zh = f" 下一步：说“交{_OBL_ZH.get(first.type, first.type)}”，我会为最早到期的账单起草一份等您签名的草稿。" if first else ""
    if lang == "zh":
        t = (f"我起草了计划 {rec['id']}（{len(rec.get('steps', []))} 步）。这只是建议：在“计划”页面接受并签名之前，不会付款或兑换。" + nxt_zh)
    else:
        t = (f"I drafted plan {rec['id']} with {len(rec.get('steps', []))} step(s). " + " ".join(why) +
             " It is only a proposal: nothing is paid or converted until you accept it in the Plan tab and sign." + nxt_en)
    return _result("plan", t, secrets, plan_id=rec["id"], next_bill=first.type if first else None)


def _convert(S, it: ChatIntent, lang: str, d: dict, secrets=None, message: str = "", run_intake=None) -> dict:
    w = S.world
    curs = _mentioned(message)
    note = _scope_note(curs, lang)
    if note:
        return _result("convert", note, secrets, status="info")
    amt, cur = it.slots.get("amount"), it.slots.get("currency")
    cur = cur.upper() if isinstance(cur, str) else cur
    if not amt and _ALL_WORD.search(message) and curs and curs[0] in CURRENCIES and not it.slots.get("quote_only"):   # "convert all my INR": the actual balance, stated before the draft
        bal = w.passport.balance(curs[0])
        if bal > 0:
            amt, cur = round(bal, 2), curs[0]
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
        if "fixed fee" in str(e):           # "1 INR in CNY": a small amount is a rate question, so answer it, and say why no conversion is quoted
            try:
                r = fx_mid(src, dst, table_for(w.rates, w.day_index))
            except FxError:
                return _result("convert", str(e), secrets, status="rejected")
            ind = float(amt) * r
            t = (f"按参考汇率，{float(amt):,.4g} {src} 约合 {ind:,.4f} {dst}（MOCK，不含费用，不是报价）。金额太小，无法兑换：{e}。" if lang == "zh" else
                 f"At the reference rate, {float(amt):,.4g} {src} is about {ind:,.4f} {dst} (MOCK mid-market, no fees, not a quote). "
                 f"That is too small to convert: {e}.")
            return _result("convert", t, secrets, status="info")
        return _result("convert", str(e), secrets, status="rejected")
    cny_equiv = q.received if dst == "CNY" else q.amount
    lim = w.passport.rules.tier1_auto_convert_cny
    if lang == "zh":
        t = f"报价：{q.amount:,.0f} {src} → 约 {q.received:,.2f} {dst}（汇率 {q.rate:.4f}，费用 {q.fee:,.2f} {src}；演示价格，MOCK）。"
    else:
        t = f"Quote: {q.amount:,.0f} {src} → about {q.received:,.2f} {dst} (rate {q.rate:.4f}, fee {q.fee:,.2f} {src}; MOCK prices)."
    if it.slots.get("quote_only"):                 # chosen by similarity, not by an explicit "convert ...": a quote, nothing waits for a "yes"
        t += (" 这只是报价，没有兑换任何资金。要兑换请明确说“convert 20000 INR to CNY”。" if lang == "zh" else
              " This is a quote only and nothing was converted. To convert, say for example 'convert 20000 INR to CNY'.")
        return _result("convert", t, secrets, status="info")
    if cny_equiv <= lim and (src, dst) == ("INR", "CNY"):
        d["awaiting"], d["ctx"] = "confirm_convert", {"amount": float(amt), "src": src, "dst": dst}
        t += (" 这是在您自己的余额之间兑换，不会付给任何人。回复“是”即可执行。" if lang == "zh" else
              " This moves money between your own balances only. Reply 'yes' to do it.")
        return _result("convert", t, secrets, status="needs_confirmation", needs=["info:confirm"])
    if run_intake is not None and not _ASKING.search(message) and not (cny_equiv <= lim and (src, dst) == ("INR", "CNY")) and src != dst:     # a question stays a quote
        return _conversion_draft(S, run_intake, float(amt), src, dst, q, lang, d, secrets, t)     # above the auto limit or another pair: a draft only the device key can release
    d["last_offer"] = {"kind": "convert_quote", "src": src, "dst": dst, "amount": float(amt)}      # a bare "yes" next turn binds to THIS quote, never to an unrelated draft
    return _result("convert", t, secrets, status="info")


def _conversion_draft(S, run_intake, amt: float, src: str, dst: str, q, lang: str, d: dict, secrets, quote_text: str) -> dict:
    """A conversion chat cannot confirm on its own becomes a held draft: your own wallets only, released by your device-key signature on this exact draft."""
    o = loc.localize_outcome(run_intake(Request("", source="chat", conversion={"src": src, "dst": dst, "amount": amt})), lang)
    dr = o.get("draft") or {}
    pid = o.get("pending_id")
    if o["status"] == "held" and pid:
        item = S.pending.get(pid, {})
        h = str(dr.get("draft_hash", ""))[:10]
        t = (f"{quote_text} 草稿已就绪：在您自己的钱包之间把 {amt:,.2f} {src} 换成 {dst}，不会付给任何人。只有您用设备密钥对这份确切的草稿（#{h}）签名后才会执行；"
             f"执行时按当时的价格计算。请点击“签名并批准”。" if lang == "zh" else
             f"{quote_text} Draft ready: convert {amt:,.2f} {src} to {dst} between your own wallets; nobody is paid. It runs only after you sign this exact draft (#{h}) "
             f"with your device key, at the price then; the amount is checked again when it runs. Tap Sign and approve.")
        d["last_pending"], d["awaiting"], d["ctx"] = pid, None, {}
        return _result("convert", t, secrets, status="held", pending_id=pid, draft_hash=dr.get("draft_hash"), needs=_needs(item) if item else [], outcome=o)
    reasons = "; ".join((o.get("card") or {}).get("reasons") or []) or o["status"]
    t = (f"我没有创建兑换草稿（{amt:,.0f} {src} → {dst}）：{reasons}。没有任何资金变动。" if lang == "zh" else
         f"I made no conversion draft for {amt:,.0f} {src} → {dst}: {reasons}. Nothing was converted.")
    return _result("convert", t, secrets, status="rejected")


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
    named = _keyword_payee(w, nlu.fix_typos(nlu.normalise(message))) if not typ else None
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


def _later(S, it: ChatIntent, message: str, lang: str, secrets=None, run_intake=None, d: dict | None = None) -> dict:
    """Reminders and schedules are not set up from chat. A recurring BILL is: it becomes a held mandate draft that only your device-key signature creates."""
    obs = _bill_for(S, it, message)
    if run_intake is not None and d is not None and _RECUR.search(message) and len(obs) >= 1:
        base = obs[0]
        o = loc.localize_outcome(run_intake(Request("", source="chat", mandate={"obligation_id": base.id})), lang)
        dr, pid = o.get("draft") or {}, o.get("pending_id")
        if o["status"] == "held" and pid:
            item = S.pending.get(pid, {})
            h = str(dr.get("draft_hash", ""))[:10]
            t = (f"这是一条长期指令草稿：每 {base.every_days or 30} 天向 {_payee_name(S.world, base.payee_id)}（登记账户）自动支付{_OBL_ZH.get(base.type, base.type)}，每次不超过 {money(base.amount, lang)}。"
                 f"创建它不会转出任何款项；只有您用设备密钥对这份确切的草稿（#{h}）签名后才生效，之后每次自动付款仍会重新检查规则并留痕。请点击“签名并批准”。" if lang == "zh" else
                 f"Standing instruction draft: pay your {base.type} to {_payee_name(S.world, base.payee_id)} (registry account) every {base.every_days or 30} days, up to {money(base.amount, lang)} each time. "
                 f"Creating it moves no money and takes effect only after you sign this exact draft (#{h}) with your device key; every automatic run is re-checked by the same rules and audited. Tap Sign and approve.")
            d["last_pending"] = pid
            return _result("later", t, secrets, status="held", pending_id=pid, draft_hash=dr.get("draft_hash"), needs=_needs(item) if item else [], outcome=o)
    if _RECUR.search(message) and obs and lang != "zh":
        cap = float(S.world.passport.rules.tier1_auto_limit_cny)
        b = obs[0]
        name = _bill_name(b.type)
        if b.remaining > cap or b.currency != "CNY":
            return _result("later", f"{name.capitalize()} is CNY {b.remaining:,.0f}, above the CNY {cap:,.0f} cap for standing instructions, so I can't automate it. "
                           f"I can draft the one-off payment: say 'pay my {name}'. Nothing moved.", secrets, status="info")
    due = ("；" if lang == "zh" else "; ").join(_obl_line(S.world, o, lang) for o in obs[:3])
    if lang == "zh":
        t = ("我不能在聊天里设置提醒、定时付款或自动扣款：每一笔付款都要在支付当时由您用设备密钥签名。没有创建任何草稿，也没有任何资金转出。"
             + (f"相关账单：{due}。" if due else "") + "准备好时说“交房租”之类，我会起草一份等您签名的草稿。")
    else:
        t = ("I can't set reminders, schedules or automatic payments from chat: every payment is signed with your device key when it is made. "
             "No draft was created and nothing moved." + (f" Relevant bills: {due}." if due else "") +
             " Whenever you're ready, say 'pay my rent' (or another bill) and I'll draft it for your signature.")
    return _result("later", t, secrets)


def _recap(d: dict, lang: str, secrets=None) -> dict:
    log = d.get("log") or []
    if not log:
        t = "这次会话里我还没有替您做任何事：没有草稿、取消或付款。" if lang == "zh" else "Nothing yet in this session: no drafts, cancellations or payments."
        return _result("recap", t, secrets)
    lines = " ".join(f"{i}) {x[2]}." if not x[2].endswith(".") else f"{i}) {x[2]}" for i, x in enumerate(log[-5:], 1))
    t = (f"本次会话您最近的操作：{lines}" if lang == "zh" else f"Your latest actions this session: {lines}")
    return _result("recap", t, secrets)


def _unknown(S, message: str, lang: str, secrets=None) -> dict:
    """No dead end: name the nearest options and end with one question."""
    typ = nl_extract.purpose_in_text(message)
    pend = bool(S.pending)
    if lang == "zh":
        t = (f"您是想交{_OBL_ZH.get(typ, typ)}吗？说“交{_OBL_ZH.get(typ, typ)}”，我会起草一份等您签名的草稿。" if typ else
             "我没听明白。您想交账单、查余额，还是看汇率" + ("，或者取消草稿" if pend else "") + "？可以说“交房租”“交学费”“交押金”或“交话费”。")
    else:
        if typ:
            t = f"Do you want me to prepare your {typ} payment? Say 'pay my {typ}' and I'll draft it for your signature."
        else:
            hit = faq.answer(message)
            if hit:
                return _result("faq", f"{hit[0]} (Screen: {hit[1]}.)", secrets, status="info")
            t = faq.hedge(message) + (" You can also cancel your draft." if pend else "")
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


def _credit_status(S, lang: str, secrets=None) -> dict:
    """On-time count, streak and the next step for the payment record (read-only, from verified records only)."""
    v = cg.plan(S.world)
    nxt = next((m for m in cg.plan(S.world)["milestones"] if not m["met"]), None)
    ver = v["verified"]
    if lang == "zh":
        t = (f"已核验付款 {ver['payments']} 笔，其中按时 {ver['on_time']} 笔，连续按时 {ver['streak']} 笔，已有 {ver['months']} 个月的记录。"
             + (f"下一步：{nxt['id']}（{nxt['current']}/{nxt['target']}），按时付清下一笔账单即可推进。" if nxt else "所有里程碑都已达成。")
             + "这不是信用评分；数据为演示（MOCK）。")
    else:
        t = (f"{ver['on_time']} of your {ver['payments']} verified payment(s) were on time; current on-time streak {ver['streak']}, {ver['months']} month(s) of record. "
             + (f"Next step: {nxt['id']} ({nxt['current']}/{nxt['target']}) - paying your next bill on time moves it forward. " if nxt else "Every milestone is met. ")
             + "This is not a credit score and no bank or bureau accepts it; the data is MOCK.")
    return _result("credit", t, secrets)


def _finance_summary(S, lang: str, secrets=None) -> dict:
    """One answer from the passport only: balances, open and overdue bills, runway or shortfall, spending against the expected month, payment record."""
    w = S.world
    pp = w.passport
    sym = {"INR": "₹", "CNY": "¥", "USD": "$", "EUR": "€", "GBP": "£", "AUD": "A$"}
    bal = ", ".join(f"{sym[c]}{pp.balance(c):,.0f}" for c in CURRENCIES if pp.balance(c))
    obs = _open_obligations(w)
    overdue = [o for o in obs if str(o.due) < w.today.isoformat()]
    pos = cover_position(pp, w.rates, w.day_index)
    m = runway_months(pp, w.rates, w.day_index)
    month = w.today.isoformat()[:7]
    spent = sum(t["amount_cny"] for t in pp.transactions if t["date"].startswith(month))
    exp = spending.summarize(pp)["monthly_cny"]
    ver = cg.plan(w)["verified"]
    gap = pos["shortfall_cny"]
    over = spent > exp * 1.1 if exp else False
    if lang == "zh":
        t = (f"余额：{bal or '无'}。待付账单 {len(obs)} 笔共 ¥{pos['bills_cny']:,.0f}" + (f"，其中 {len(overdue)} 笔已逾期" if overdue else "，没有逾期") + "。"
             + (f"资金缺口约 ¥{gap:,.0f}。" if gap else f"付清账单后资金约可维持 {m:.1f} 个月。")
             + f"本月钱包支出 ¥{spent:,.0f}，预计每月约 ¥{exp:,.0f}" + ("，偏高。" if over else "，在正常范围内。")
             + f"按时付款记录：{ver['on_time']}/{ver['payments']}，连续 {ver['streak']} 笔。（演示数据，MOCK；估算，不是建议）")
    else:
        t = (f"Balances: {bal or 'none'}. Open bills: {len(obs)} totalling CNY {pos['bills_cny']:,.0f}" + (f", {len(overdue)} overdue" if overdue else ", none overdue") + ". "
             + (f"You are about CNY {gap:,.0f} short of covering them; say 'plan my semester' for a plan. " if gap else f"After your bills, your money lasts about {m:.1f} months. ")
             + f"Spending this month is CNY {spent:,.0f} against an expected CNY {exp:,.0f}" + (": you are spending more than usual. " if over else ": in line with the usual. ")
             + f"Payment record: {ver['on_time']} of {ver['payments']} on time, streak {ver['streak']}. (MOCK sandbox data; an estimate, not advice.)")
    return _result(nlu.FINANCE_SUMMARY, t, secrets)


def _transfer_time(S, lang: str, secrets=None, bank_vs_app: bool = False) -> dict:
    """Days per route first (and the bank wire against the best app), from the sandbox route table."""
    w = S.world
    qs = quote_routes(w.rates, 100000.0, w.today, None, w.day_index)
    by = sorted(qs, key=lambda q: (q.arrives_in_days, -q.delivered_cny))
    bank = next((q for q in qs if q.route.typical_bank), None)
    apps = [q for q in qs if not q.route.typical_bank]
    best = max(apps, key=lambda q: q.delivered_cny) if apps else None
    days = "; ".join(f"{q.route.name}: {q.arrives_in_days} day(s)" for q in by)
    if bank_vs_app and bank and best:
        saved = best.delivered_cny - bank.delivered_cny
        if lang == "zh":
            t = (f"以汇出 ₹100,000 计：银行电汇（{route_zh(bank.route.name)}）约到账 ¥{bank.delivered_cny:,.0f}，{bank.arrives_in_days} 天；最划算的汇款应用（{route_zh(best.route.name)}）约 ¥{best.delivered_cny:,.0f}，"
                 f"{best.arrives_in_days} 天，多约 ¥{saved:,.0f}。（演示数据，MOCK；只是比较，没有创建草稿）")
        else:
            t = (f"For INR 100,000: the bank wire ({bank.route.name}) delivers about CNY {bank.delivered_cny:,.0f} in {bank.arrives_in_days} day(s); the best remittance app ({best.route.name}) "
                 f"delivers about CNY {best.delivered_cny:,.0f} in {best.arrives_in_days} day(s), about CNY {saved:,.0f} {'more' if saved >= 0 else 'less'}. Ask 'cheapest way to send <amount>' to size it to your bill. (MOCK prices; a comparison only, no draft made.)")
        return _result("routes", t, secrets)
    if lang == "zh":
        t = "到账时间（按路线）：" + "；".join(f"{route_zh(q.route.name)} {q.arrives_in_days} 天" for q in by) + "。银行电汇通常最慢。（演示数据，MOCK；实际时间取决于服务商）"
    else:
        t = f"Transfer time by route, fastest first: {days}. A bank wire is usually the slowest; the cheapest route is not always the fastest. (MOCK route table; real times depend on the provider.)"
    return _result("routes", t, secrets)


def _start_here(S, lang: str, secrets=None) -> dict:
    """Guided start for a new student: what is due, the four things Oasis does, one next step."""
    w = S.world
    obs = sorted(_open_obligations(w), key=lambda o: o.due)
    first = obs[0] if obs else None
    if lang == "zh":
        due = f"最近到期：{_OBL_ZH.get(first.type, first.type)} {money(first.remaining, lang)}，{first.due}。" if first else "目前没有待付账单。"
        t = ("欢迎！Oasis 帮您做四件事：1) 汇款（比较路线、算出到账金额）；2) 交学费和各类账单（起草后由您签名）；3) 建立付款记录（按时付款，生成可分享的信任通行证）；"
             f"4) 多币种管理（查看余额、兑换、设汇率目标）。{due}建议第一步：说“规划我的学期”。")
    else:
        due = f"Next due: {first.type} {money(first.remaining, lang)} on {first.due}. " if first else "Nothing is due right now. "
        t = ("Welcome! Oasis does four things: 1) remittances (compare routes, see what arrives); 2) tuition and other bills (I draft, you sign); "
             "3) credit building (pay on time and share a Trust Pass); 4) multi-currency money (balances, conversion, rate targets). "
             f"{due}Suggested first step: say 'plan my semester'.")
    return _result("help", t, secrets, status="info")


_HELP_EN = ("I can: pay a bill ('pay my rent', 'pay my tuition'), show your balance or bills, give today's rate or the cheapest route, "
            "say whether your money will last, convert (quote then confirm), set a rate target ('convert 2000 when the rate reaches 0.0700'), "
            "check a pasted invoice (or an uploaded screenshot or .eml email), cancel or correct a draft, and explain why something was stopped. Payments always end with your signature.")
_HELP_ZH = ("我可以：付账单（“交房租”“交学费”）、显示余额和待付账单、查询汇率和最便宜的路线、判断资金是否够用、兑换（先报价再确认）、"
            "设定汇率目标（“convert 2000 when the rate reaches 0.0700”）、检查粘贴的发票（或上传的截图、.eml 邮件）、取消或修改草稿，以及解释付款为何被拦截。付款最终一定需要您的签名。")


# ------------------------------------------------------------------ sub-topic questions: answer-only, never a draft or a move of money
_ISSUE_KIND = (("rejected", re.compile(r"reject|declin|bounc|return|came back|拒|退回|失败", re.I)),
               ("short", re.compile(r"less|short|smaller|only part|少", re.I)),
               ("delayed", re.compile(r"delay|not arrived|n'?t arrived|never arrived|not reach|n'?t reach|not credited|n'?t come|missing|没到|未到账|延迟", re.I)))


def _transfer_issue(S, it: ChatIntent, lang: str, secrets=None) -> dict:
    """A late, short or rejected transfer. Advice only: nothing is resent, and a resend is never offered."""
    w = S.world
    wording = it.slots.get("wording") or ""
    if S.journeys and not it.slots.get("hypo"):
        j = list(S.journeys.values())[-1]
        f = fpath.reconcile(j, w.day_index)
        a = fpath.advise(j, f)
        fpath.audit_event(w.audit, j, f, a)
        c = fpath.consequences(j, f, w.day_index)
        text = w.llm.explain("flightpath", {"text": c["text"], "facts": c["facts"], "options": c["options"]}, lang)    # the same rewrite guard as the FlightPath tab
        t = (f"您最近一笔汇款（{j.id}）的情况：{text} 我没有重新发送任何款项。详情见“FlightPath”标签。" if lang == "zh" else
             f"About your latest transfer ({j.id}): {text} I have not sent anything again. See the FlightPath tab for the full picture.")
        return _result(nlu.TRANSFER_ISSUE, t, secrets, status="info", resend_offered=False, journey=j.id)
    kind = next((k for k, rx in _ISSUE_KIND if rx.search(wording)), "tracking")
    if lang == "zh":
        head = {"delayed": "汇款迟迟未到：", "short": "到账金额少于汇出金额：", "rejected": "汇款被退回或被拒：", "tracking": "追踪汇款："}[kind]
        body = {"delayed": "先向汇款服务商查询状态，不要重复汇款，否则同一笔账单可能被付两次。",
                "short": "先向汇款服务商索取扣费明细；补差额要作为一笔新的付款，经您签名后才会发出。",
                "rejected": "请等退款确认之后再考虑新的付款，退款与新付款同时到账会造成重复支付。",
                "tracking": "我可以按 FlightPath 的汇款进度帮您判断是否延迟、少收或被拒。"}[kind]
        t = f"{head}{body} 我没有重新发送任何款项，也不会替您重发。请在“FlightPath”标签里添加这笔汇款查看进度（演示数据，MOCK）。"
    else:
        head = {"delayed": "A transfer that is late:", "short": "A transfer that arrived short:", "rejected": "A transfer that was rejected:", "tracking": "Tracking a transfer:"}[kind]
        body = {"delayed": "ask the provider for its status first, and do not send it again, because the same bill could be paid twice.",
                "short": "ask the provider for the deduction breakdown; a top-up is a new payment that only goes out after you sign it.",
                "rejected": "wait for the refund to be confirmed before any new payment; a refund and a new payment landing together would pay twice.",
                "tracking": "add the transfer in the FlightPath tab and I can tell whether it is late, short or rejected."}[kind]
        t = f"{head} {body} I have not resent anything and will not resend it for you. Open the FlightPath tab to follow it (MOCK rails)."
    return _result(nlu.TRANSFER_ISSUE, t, secrets, status="info", resend_offered=False)


_PAYVERB = re.compile(r"\b(?:pay|settle|clear)\b", re.I)
_ASKING = re.compile(r"\bhow\b|\bcan i\b|\bwhat\b|\bwhere\b|\bwhy\b|\bwhich\b|\bshould\b|[?？]", re.I)
_FXKIND = {"USD": "us", "EUR": "eu"}


def _fx_draft(S, run_intake, ob, lang: str, d: dict, intent: str, secrets=None, lead: str = "") -> dict:
    """A bill owed in USD / EUR becomes a normal held draft (registry payee and account, the student's device-key signature, the executor)."""
    o = loc.localize_outcome(run_intake(Request("", source="chat", fx={"obligation_id": ob.id})), lang)
    dr = o.get("draft") or {}
    pid = o.get("pending_id")
    if o["status"] == "held" and pid:
        item = S.pending.get(pid, {})
        cur, amt = dr.get("currency") or ob.currency, float(dr.get("amount") or ob.remaining)
        bal = S.world.passport.balance(cur)
        payee = _payee_name(S.world, dr.get("payee_id", ob.payee_id))
        if lang == "zh":
            t = (f"{lead}草稿已就绪：向 {payee}（登记账户 {mask(dr.get('account_ref'))}）支付 {cur} {amt:,.2f}。"
                 + (f"提醒：您的 {cur} 余额为 {bal:,.2f}，不足以支付，请先兑换。" if bal + 0.005 < amt else "")
                 + f"款项只有在您用设备密钥对这份确切的草稿（#{str(dr.get('draft_hash', ''))[:10]}）签名后才会转出。请点击“签名并批准”。")
        else:
            t = (f"{lead}Draft ready: pay {cur} {amt:,.2f} to {payee} (registered account {mask(dr.get('account_ref'))}) for {ob.type}. "
                 + (f"Note: your {cur} balance is {bal:,.2f}, below this amount; convert first. " if bal + 0.005 < amt else "")
                 + f"It moves only after you sign this exact draft (#{str(dr.get('draft_hash', ''))[:10]}) with your device key. Tap Sign and approve.")
        d["last_pending"], d["awaiting"], d["ctx"] = pid, None, {}
        return _result(intent, t, secrets, status="held", pending_id=pid, draft_hash=dr.get("draft_hash"), needs=_needs(item) if item else [], outcome=o)
    return _stopped_reply(o, lang, intent, secrets)


def _fx_bill(S, it: ChatIntent, message: str, lang: str, secrets=None, run_intake=None, d: dict | None = None) -> dict:
    w = S.world
    if run_intake is not None and d is not None and _PAYVERB.search(message) and not _ASKING.search(message):
        cur = next((c for c in _mentioned(message) if c in _FXKIND), None)
        asks_cny_bill = nl_extract.purpose_in_text(message) in ("rent", "deposit", "living") or (
            nl_extract.purpose_in_text(message) == "tuition" and not re.search(r"fees?|application", message, re.I))
        if cur and not (asks_cny_bill and not nlu._amount(message, bare=True)):    # "pay rent in dollars" names a registered CNY bill: the answer below, not a new USD bill
            have = [o for o in fxplan.foreign_obligations(w.passport) if o.currency == cur and o.status != "frozen"]
            lead = ""
            if not have:                                   # a sandbox bill to the fixed MOCK university, then the usual draft
                a = nlu._amount(message, bare=True)
                if not a or not a[0] or a[0] > fx_exec.DEMO_MAX:
                    t = (f"{cur} 账单是多少金额？请告诉我，例如“支付 100 {cur} 的申请费”。" if lang == "zh" else
                         f"How much is the {cur} bill? Tell me the amount, for example 'pay my {cur} application fee of 100'.")
                    return _result(nlu.FX_BILL, t, secrets, status="needs_info", needs=["info:amount"])
                ob = fx_exec.add_demo_obligation(w, _FXKIND[cur], a[0], 30)
                S.save()
                have = [w.passport.obligation(ob["id"])]
                lead = (f"我已把这笔 {cur} {a[0]:,.2f} 的账单登记为沙盒（MOCK）账单，收款方是固定的模拟大学。" if lang == "zh" else
                        f"I added this {cur} {a[0]:,.2f} bill as a sandbox (MOCK) bill to the fixed MOCK university. ")
            return _fx_draft(S, run_intake, have[0], lang, d, nlu.FX_BILL, secrets, lead)
    if it.slots.get("pay_in"):
        typ = nl_extract.purpose_in_text(message) or "bill"
        t = (f"不能直接用美元付：您的{_OBL_ZH.get(typ, '账单')}以人民币登记，我只会按人民币向登记收款方起草，您签名后才会付款。"
             "以美元或欧元开具的账单，请先登记为账单，再在“计划 → 外币计划”里安排，每一笔都需要您签名。" if lang == "zh" else
             f"Not directly: your {typ} bill is registered in CNY, so I only draft it in CNY to the registered payee, and nothing moves until you sign. "
             "A bill issued in USD or EUR is added as a bill and planned under Plan, then FX plan, with your signature on each payment.")
        return _result(nlu.FX_BILL, t, secrets, status="info")
    if fxplan.has_foreign(w):
        t = ("您有外币账单。请打开“计划 → 外币计划”：每一笔美元或欧元付款都必须由您本人签名（规则 R18/R19），我不会自动付款。" if lang == "zh" else
             "You have a foreign-currency bill. Open Plan, then FX plan: every USD or EUR payment needs your own signature (rules R18 and R19), and I never pay one on my own.")
        return _result(nlu.FX_BILL, t, secrets, status="info")
    a = nlu._amount(message, bare=True)
    cur = next((c for c in _mentioned(message) if c in ("USD", "EUR", "GBP", "AUD")), None)        # "200 dollars" reads as a bare number, so the currency comes from the words
    ind = ""
    if a and cur:
        try:
            ind = (f" 按参考汇率，{a[0]:,.0f} {cur} 约合 ₹{a[0] * fx_mid(cur, 'INR', table_for(w.rates, w.day_index)):,.0f}（MOCK，不含费用）。" if lang == "zh" else
                   f" At the reference rate, {a[0]:,.0f} {cur} is about ₹{a[0] * fx_mid(cur, 'INR', table_for(w.rates, w.day_index)):,.0f} (MOCK, before fees).")
        except FxError:
            ind = ""
    t = (("外币账单（美元或欧元）要先登记为账单，再在“计划 → 外币计划”里安排；每一笔外币付款都需要您的签名。" + ind) if lang == "zh" else
         ("A bill in USD or EUR is added as a bill first and then planned under Plan, then FX plan. Every foreign-currency payment needs your signature." + ind))
    return _result(nlu.FX_BILL, t, secrets, status="info")


def _parent_request(S, it: ChatIntent, message: str, lang: str, secrets=None) -> dict:
    """Asking a parent for money: show the gap and the safe way. The assistant cannot pay or approve for the parent."""
    w = S.world
    typ = nl_extract.purpose_in_text(message)
    bills = _open_obligations(w, typ) or _open_obligations(w)
    need = sum(o.remaining for o in bills)
    bal = w.passport.balance("CNY")
    gap = max(need - bal, 0.0)
    label = (_OBL_ZH.get(typ, typ) if lang == "zh" else typ) if typ and _open_obligations(w, typ) else None
    if lang == "zh":
        t = (f"您{('的' + label) if label else '的待付账单'}共 {money(need, lang)}，您的人民币余额 {money(bal, lang)}，缺口 {money(gap, lang)}。"
             "我无法替您的父母付款或批准。可以说“制定学期计划”：计划会包含一笔需要父母同意的汇款，由父母在自己的会话里签名，并计入父母的 LRS/TCS 额度。")
    else:
        t = (f"Your open {label or 'bills'} {'totals' if label else 'total'} {money(need, lang)} and your CNY balance is {money(bal, lang)}, a gap of {money(gap, lang)}. "
             "I can't pay or approve anything for your parent. Say 'plan my semester': the plan includes a parent remittance that your parent consents to "
             "and signs in their own session, and it counts against their LRS and TCS.")
    return _result(nlu.PARENT_REQUEST, t, secrets, status="info")


def _quota(S, lang: str, secrets=None) -> dict:
    w = S.world
    lim = plan_validator.lrs_limit_inr()
    used = {r: w.passport.remitted_inr_fy.get(r, 0.0) for r in plan_validator.REMITTERS}
    tcs = corridor.load_rules()["rules"]["tcs_threshold_inr"]["value"]
    if lang == "zh":
        rows = "；".join(f"{'学生' if r == 'student' else '父母'}已用 ₹{u:,.0f}，剩余 ₹{max(lim - u, 0):,.0f}" for r, u in used.items())
        t = (f"LRS 年度额度约为每位汇款人 ₹{lim:,.0f}（学生和父母各自计算）：{rows}。每位汇款人每财年超过 ₹{tcs:,.0f} 的部分可能被代扣 TCS。"
             "数字来自带来源的汇款规则（MOCK），不是法律意见，请向授权银行确认。")
    else:
        rows = "; ".join(f"{r} used ₹{u:,.0f}, ₹{max(lim - u, 0):,.0f} left" for r, u in used.items())
        t = (f"The LRS annual limit is about ₹{lim:,.0f} per remitter (a parent and the student have separate limits): {rows}. "
             f"TCS may apply above ₹{tcs:,.0f} per remitter per financial year. These figures come from the sourced corridor rules (MOCK data); "
             "they are not legal advice, so confirm with your authorised dealer bank.")
    return _result(nlu.QUOTA, t, secrets, status="info")


_AUDIENCE = re.compile(r"\b(?:with|to|for)\s+(?:my|the|a)\s+([a-z][a-z ]{2,30}?)(?=$|[.,!?]|\s+(?:so|because|please|pls|and|to)\b)", re.I)
_SHARE_VERB = re.compile(r"\b(?:share|send|show|give|issue|generate|create|make)\b|分享|出示|发给", re.I)


def _share_record(S, lang: str, secrets=None, message: str = "", tp_share=None) -> dict:
    n = S.world.passport.reputation.get("verified_on_time_payments", 0)
    if tp_share is not None and _SHARE_VERB.search(message) and not _ASKING.search(message):
        m = _AUDIENCE.search(message)
        aud = m.group(1).strip() if m else None
        try:
            sh = tp_share(aud)
        except ValueError as e:
            t = (f"现在还不能生成信任通行证：{e}。" if lang == "zh" else f"I can't issue a Trust Pass yet: {e}.")
            return _result(nlu.SHARE_RECORD, t, secrets, status="rejected")
        claims = "; ".join(sh["claims"])
        if lang == "zh":
            t = (f"已生成信任通行证{('（接收方：' + aud + '）') if aud else ''}：{claims}。对方可打开此链接核验：{sh['link']}（也可扫二维码；有效期至 {sh['valid_until']}）。"
                 "它只披露这些声明，不披露任何单笔付款；这不是信用评分（数据为 MOCK）。没有任何资金转出。")
        else:
            t = (f"Trust Pass issued{(' for your ' + aud) if aud else ''}: {claims}. Open this link to verify it: {sh['link']} (the same link works as a QR; valid until {sh['valid_until']}). "
                 "It discloses only those claims and no individual payment, and it is not a credit score (MOCK data). Nothing moved." + ("" if n else " Your record is empty so far: pay a bill and sign it to build one."))
        return _result(nlu.SHARE_RECORD, t, secrets, status="done", share_code=sh["code"], share_link=sh["link"])
    if lang == "zh":
        t = (f"您目前有 {n} 笔经核验的按时付款。要分享记录，请打开“护照 → Oasis 信任通行证”：选择要披露的阈值声明（例如“至少 N 笔按时付款”）、接收方和有效期，"
             "再出示二维码。信任通行证只基于已核验的付款，这不是信用评分（数据为 MOCK）。")
    else:
        t = (f"You have {n} verified on-time payment(s). To share your record, open Passport, then Oasis Trust Pass: pick the threshold claims to disclose "
             "(for example 'at least N on-time payments'), the audience and an expiry, then show the QR code. The Trust Pass is built only from verified "
             "payments and is not a credit score (MOCK data).")
    return _result(nlu.SHARE_RECORD, t, secrets, status="info")


# ------------------------------------------------------------------ "where is my transfer?"
_WHERE = re.compile(r"\bwhere(?:'s| is| are)\b[^?]{0,30}\b(?:transfer|payment|remittance|money|tuition|rent|deposit)\b|\b(?:track|trace)\b[^?]{0,25}\b(?:transfer|payment|remittance)\b|"
                    r"\bstatus of\b[^?]{0,25}\b(?:transfer|payment|remittance)\b|我的.{0,6}(?:汇款|转账).{0,4}(?:在哪|到哪)", re.I)


def _where(S, it: ChatIntent, message: str, lang: str, secrets=None) -> dict:
    """That transfer's status and advice: the FlightPath journey when one is tracked, else the bill's own state. Advice only; nothing is resent."""
    w = S.world
    typ = nl_extract.purpose_in_text(message)
    js = [j for j in S.journeys.values() if not typ or (getattr(j, "purpose", None) in (None, typ))]
    if js:
        res = _transfer_issue(S, ChatIntent(nlu.TRANSFER_ISSUE, {"wording": ""}, 0.9, lang), lang, secrets)
        res["intent"] = "where"
        return res
    obs = [o for o in w.passport.obligations if not typ or o.type == typ]
    paid = [o for o in obs if o.status == "paid"]
    if paid:
        o = paid[-1]
        proof = list(w.proofs)[-1] if w.proofs else None
        t = (f"您的{_OBL_ZH.get(o.type, o.type)}已付清{('，证明包 ' + proof) if proof else ''}。没有在途汇款。" if lang == "zh" else
             f"Your {o.type} is paid" + (f"; proof pack {proof}" if proof else "") + ". Nothing is in transit.")
        return _result("where", t, secrets, proof_id=proof)
    pend = [v for v in S.pending.values() if not typ or ((v.get("outcome") or {}).get("draft") or {}).get("purpose") == typ]
    o = _open_obligations(w, typ)
    if pend:
        t = ("这笔款项还没有转出：草稿在等您用设备密钥签名，签名之前没有任何汇款在途。" if lang == "zh" else
             "It hasn't left yet: the draft is waiting for your device-key signature, so nothing is in transit.")
    elif o:
        x = min(o, key=lambda b: b.due)
        t = (f"{_OBL_ZH.get(x.type, x.type)} {money(x.remaining, lang)} 还没付，也没有在途汇款（到期日 {x.due}）。说“交{_OBL_ZH.get(x.type, x.type)}”即可起草。" if lang == "zh" else
             f"Your {x.type} ({money(x.remaining, lang)}, due {x.due}) is not paid and no transfer is in transit. Say 'pay my {x.type}' and I'll draft it for your signature.")
    else:
        t = "没有找到在途汇款，也没有待付账单。" if lang == "zh" else "I found no transfer in transit and no open bill."
    return _result("where", t, secrets)


# ------------------------------------------------------------------ scam check (read-only: a verdict and the evidence, never a draft)
def _scam_check(S, message: str, ui: str, secrets=None) -> dict | None:
    lang = nlu.detect_lang(message, ui)
    body = _SCAM_Q.sub(" ", message)
    if len(body.strip()) < 25:                                   # a bare "is this a scam?" is the general safety FAQ, not a pasted message
        return None
    if len(body.strip()) < 60 and not re.search(r"\d|https?:|www\.|@|[¥￥$€£₹]", body):      # "is it safe to give you my bank details": a question with nothing pasted is the safety FAQ
        return None
    w = S.world
    recs = [r for r in _recipients(w)]
    known = {r.name: r.account_ref for r in recs}
    acct = nl_extract.account_in_text(message)
    amt = nl_extract.money(body)
    reg = nl_extract.registry_payee(message, recs)
    name = reg.name if reg else nl_extract.unregistered_payee_name(message)
    cred = (w.registry.lookup(reg.id) if reg else None) or (w.registry.lookup_by_name(name) if name else None)
    ctx = {"registry_known": cred is not None, "registry_account": cred.account_ref if cred else None}
    fields = {"payee_name": name, "account_ref": acct, "amount": amt[0] if amt else None, "payee_id": reg.id if reg else None}
    risk = heuristic_risk(fields, message, list(known), {r.id: r.account_ref for r in recs}, None, ctx)
    flags = list(risk.evidence)
    decoys = w.canaries
    trip = [v for v in (*decoys.decoy_tokens, *decoys.decoy_payees, *decoys.decoy_fields) if v and v in message] if decoys else []    # read-only: the live tripwire list is not touched
    if trip:
        flags.append("the message contains a planted decoy value that no genuine bill carries (canary)")
    reg_line_en = reg_line_zh = ""
    if acct:
        match = cred is not None and cred.account_ref == acct
        if cred is None:
            reg_line_en, reg_line_zh = ("The account in the message is not in the verified registry. ", "消息里的账号不在已核验的登记册中。")
        elif not match:
            reg_line_en, reg_line_zh = (f"The registry has a different account for {cred.name} ({mask(cred.account_ref)}); the message's account does not match. ",
                                        f"登记册里 {cred.name} 的账户（{mask(cred.account_ref)}）与消息里的账号不一致。")
        else:
            reg_line_en, reg_line_zh = (f"The account matches the registry entry for {cred.name}. ", f"账号与登记册中 {cred.name} 的记录一致。")
    elif name and cred is None:
        reg_line_en, reg_line_zh = (f"'{name}' is not a registered payee. ", f"“{name}”不是已登记的收款方。")
    score = max(risk.score, 0.9 if trip else 0.0)
    verdict = "likely_scam" if score >= RISK_HOLD or (acct and cred is not None and cred.account_ref != acct) else ("suspicious" if score >= 0.25 or (acct and cred is None) else "no_signs")
    word_en = {"likely_scam": "Likely a scam", "suspicious": "Suspicious, verify before doing anything", "no_signs": "No warning signs found (that is not a guarantee)"}[verdict]
    word_zh = {"likely_scam": "很可能是诈骗", "suspicious": "可疑，请先核实再操作", "no_signs": "没有发现警示信号（但这不是保证）"}[verdict]
    why_en = "; ".join(flags[:4]) or "none of the checks fired"
    if lang == "zh":
        t = (f"判断：{word_zh}。风险分 {score:.2f}。依据：{('；'.join(flags[:4])) or '没有触发任何检查'}。{reg_line_zh}"
             "不要点击链接、不要回复或转账；如需付款，请只通过已登记收款方和您自己签名的草稿。我没有创建草稿，CNY 0 转出。")
    else:
        t = (f"Verdict: {word_en}. Risk score {score:.2f}. Why: {why_en}. {reg_line_en}"
             "Don't click links, reply or send money from this message; pay only through a registered payee with a draft you sign yourself. I made no draft: CNY 0 moved.")
    return _result("scam_check", t, secrets, status="info", verdict=verdict, risk_score=round(score, 2), evidence=flags[:6], lang=lang)


# ------------------------------------------------------------------ hidden-markup check (read-only)
def _markup_check(S, message: str, ui: str, secrets=None) -> dict | None:
    lang = nlu.detect_lang(message, ui)
    amts = nl_extract.all_money(message)
    inr = next((v for v, c in amts if c == "INR"), None)
    cny = next((v for v, c in amts if c == "CNY"), None)
    if not inr or not cny or nlu._PAY_IMPERATIVE.search(nlu.normalise(message)):
        return None
    w = S.world
    mid = w.rates.mid(w.day_index)
    implied = cny / inr
    markup = (1 - implied / mid) * 100
    ranked = rank(quote_routes(w.rates, inr, w.today, None, w.day_index))
    best = ranked[0] if ranked else None
    extra = (best.delivered_cny - cny) if best else 0.0
    fair = markup <= 1.0
    if lang == "zh":
        t = (f"隐含汇率 {implied:.4f} CNY/INR，对比中间价 {mid:.4f}，加价约 {markup:.1f}%。"
             + (f"最便宜的按时路线（{route_zh(best.route.name)}）约到账 ¥{best.delivered_cny:,.0f}，" + (f"比报价多 ¥{extra:,.0f}。" if extra > 0 else f"报价反而多 ¥{-extra:,.0f}。") if best else "")
             + ("这个报价基本合理。" if fair else "这个报价偏贵。") + "（演示汇率，MOCK；只是比较，没有创建草稿。）")
    else:
        t = (f"Implied rate {implied:.4f} CNY per INR against a mid-market {mid:.4f}: a markup of about {markup:.1f}%. "
             + (f"The cheapest on-time route ({best.route.name}) would deliver about CNY {best.delivered_cny:,.0f} for INR {inr:,.0f}, " + (f"CNY {extra:,.0f} more than the quote. " if extra > 0 else f"so the quote is CNY {-extra:,.0f} better than that route. ") if best else "")
             + ("That quote is roughly fair. " if fair else "That quote is on the expensive side. ") + "(MOCK rates; a comparison only, no draft made.)")
    return _result("markup_check", t, secrets, status="info", implied_rate=round(implied, 6), mid_rate=round(mid, 6), markup_pct=round(markup, 2),
                   cheapest_cny=best.delivered_cny if best else None)


# ------------------------------------------------------------------ proactive check-in
def checkin(S, jti: str, lang: str = "en") -> dict:
    """Once per session: what is due soon, the shortfall and an offer. 'yes' next turn continues into the plan."""
    d = dialog_for(S.dialogs, jti)
    if d.get("checked_in"):
        return {"reply": None, "intent": "checkin", "status": "info"}
    d["checked_in"] = True
    w = S.world
    obs = sorted(_open_obligations(w), key=lambda o: o.due)
    if not obs:
        return {"reply": None, "intent": "checkin", "status": "info"}
    first = obs[0]
    days = (date.fromisoformat(str(first.due)) - w.today).days
    gap = max(sum(o.remaining for o in obs) - w.passport.balance("CNY"), 0.0)
    d["awaiting"], d["ctx"] = "offer_plan", {}
    if lang == "zh":
        t = (f"{_OBL_ZH.get(first.type, first.type)} {money(first.remaining, lang)} 将在 {days} 天后到期" + (f"；您目前缺口 {money(gap, lang)}。要我做个计划吗？回复“是”即可。" if gap > 0.5
             else "；您的余额足够。要我做个计划吗？回复“是”即可。"))
    else:
        t = (f"{first.type.capitalize()} {money(first.remaining, lang)} is due in {days} day(s)" + (f"; you're {money(gap, lang)} short. Want a plan?" if gap > 0.5
             else "; your balance covers your bills. Want a plan anyway?"))
    return _result("checkin", t, None, status="info", due_days=days, shortfall_cny=round(gap, 2))


# ------------------------------------------------------------------ entry point
_SCAM_Q = re.compile(r"\b(?:is|are|was)\s+(?:this|that|it|these|the (?:following|message|email|text|invoice))\b[^\n]{0,40}\b(?:scam|scams|fraud|fraudulent|phishing|fake|suspicious|legit|legitimate|genuine|real|authentic|true|safe|trustworthy)\b|"
                     r"\b(?:scam|fraud|phishing)\s+check\b|\bcheck\b[^\n]{0,20}\b(?:scam|fraud|phishing|legit)\b|这是(?:不是)?诈骗|是不是诈骗", re.I)
_MARKUP_Q = re.compile(r"\b(?:quoted|offered|charged|quotes?|fair|rip-?off|mark-?up|good deal|bad deal|worth it|overcharg\w*|gave me|said they(?:'d| would| will)? (?:give|send|deliver))\b", re.I)
_LOGGED = ("held", "cancelled", "done", "paid", "rejected", "refused")
_RECAP = re.compile(r"\bwhat (?:did|have|had) (?:i|we) (?:just )?(?:do|done|ask(?:ed)?|request(?:ed)?)\b|\bwhat (?:have )?(?:we|i) (?:just )?(?:did|done)\b|\bwhat (?:just )?happened\b|"
                    r"\b(?:recap|summari[sz]e)\b[^.?!]{0,25}\b(?:session|chat|conversation|so far|what i did)\b|\bwhat did you (?:just )?do\b|我刚才(?:做了什么|干了什么)|刚才做了什么", re.I)
_ALL_WORD = re.compile(r"\b(?:all|entire|whole|everything|full)\b|全部|所有", re.I)
_RECUR = re.compile(r"\b(?:every|each) month|\bmonthly|\brecurring|\bstanding (?:order|instruction)|\bauto-?pay|\bautomatic(?:ally)?|\bset up|每个?月|自动(?:付|交|扣|支付)|定期", re.I)
_NEXT_STEP = re.compile(r"^(?:next|next one|next step|continue|go on|and then)[ !.]*$", re.I)
_SPLIT = re.compile(r"[,;]?\s+(?:and then|and|then|after that|also)\s+", re.I)
_ACTIVITY = re.compile(r"\bwhat (?:did|have) you (?:do|done)\b[^?.]{0,25}\b(?:for me|on your own|by yourself|automatically)\b|\bagent activity\b|\bwhat\'?s you\'?ve done|你替我做了什么|代理活动", re.I)
_REPEAT = re.compile(r"\b\d+\s*(?:times|x)\b|\b(?:twice|thrice)\b", re.I)
_EXTRA = re.compile(r"\b(?:also|and|plus|with)\b[^.?!]{0,30}\b(?:additional|extra|another)?\s*(?P<what>tip|gift|bonus|commission|fee|donation)\b[^.?!]{0,20}?(?P<amt>\d[\d,]*(?:\.\d+)?)", re.I)


_TRAD_TO_SIMP = str.maketrans("學費雜繳匯轉賬帳餘額電話幫還單據預約條線證記錄戶號證請問題確認統計劃寫費", "学费杂缴汇转账账余额电话帮还单据预约条线证记录户号证请问题确认统计划写费")


def handle(S, message: str, ui: str, *, jti: str, run_intake, secrets=None, tp_share=None) -> dict:
    """One chat turn. `S` is the server session; `run_intake(Request) -> outcome dict` is the pipeline entry used by invoices.
    `source` in the result says who labelled the message: the keyword router, or (opt-in, F14) a model proposal that passed validation."""
    message = message.translate(_TRAD_TO_SIMP).replace("月租", "房租")        # Traditional forms and 月租 (monthly rent) read as the Simplified words the router knows
    d = dialog_for(S.dialogs, jti)
    if not d["awaiting"]:
        extra = _scam_check(S, message, ui, secrets) if _SCAM_Q.search(message) else (_markup_check(S, message, ui, secrets) if _MARKUP_Q.search(message) else None)
        if extra is not None:
            extra["source"] = "router"
            return extra
    if not d["awaiting"] and d.get("queue") and _NEXT_STEP.match(message.strip()):      # walk the rest of a compound request, one step at a time
        nxt = d["queue"].pop(0)
        res = handle(S, nxt, ui, jti=jti, run_intake=run_intake, secrets=secrets, tp_share=tp_share)
        if d["queue"]:
            res["reply"] += f" Still to do: {d['queue'][0]!r}. Say 'next' when you are ready."
        return res
    if not d["awaiting"] and not d.get("queue"):
        parts = _SPLIT.split(message.strip(), maxsplit=1)
        if len(parts) == 2 and len(message) <= 160:
            k1, k2 = nlu.classify(parts[0], ui).kind, nlu.classify(parts[1], ui).kind
            if {k1, k2} == {nlu.CONVERT, nlu.PAY_OBLIGATION} and nlu.classify(parts[0], ui).slots.get("amount"):
                d["queue"] = [parts[1]]                                       # each step is a separate request: its own quote or draft, its own signature
                res = handle(S, parts[0], ui, jti=jti, run_intake=run_intake, secrets=secrets, tp_share=tp_share)
                res["reply"] += f" Next in your list: {parts[1]!r}. Say 'next' to continue; each step needs its own confirmation or signature."
                return res
    if not d["awaiting"] and _ACTIVITY.search(message):
        res = _result("activity", activity.summary(S, d.get("log"), nlu.detect_lang(message, ui)), secrets, status="info")
        res["source"] = "router"
        return res
    it = nlu.classify(message, ui)
    d["_msg"] = message[:300]
    src, conf, clar = "router", None, None
    if d["awaiting"] == "clarify":                        # "1" / "the second" / "quote" answers our numbered question; anything else leaves it
        picked = _clarify_pick(d, message, it)
        d["awaiting"], d["ctx"] = None, {}
        if picked is not None:
            it, src = picked, "clarify"
    lo0 = d.get("last_offer") or {}
    if not d["awaiting"] and lo0.get("kind") in ("pay", "plan") and (it.kind == nlu.CONFIRM or _affirms(message)):
        d.pop("last_offer", None)                         # a bare "yes" binds only to the offer made last turn; a pay offer still ends in a draft that needs the device-key signature
        message = f"pay my {router_v2.canon(lo0['bill'])}" if lo0["kind"] == "pay" else "plan my payments"
        it, src = nlu.classify(message, ui), "offer"
    ctx_mod.tick(d)
    social_refusal = it.kind == nlu.BYPASS and it.category == "social"          # "police called me ...": a scam pattern, so name the pattern rather than the approval claim
    if (it.kind not in nlu.REFUSALS or social_refusal) and it.kind != nlu.PAY_INVOICE and not nlu.INVOICE_HINT.search(message):
        ak = scam_lane.attack_kind(message, nlu.decoded_views(message))
        if ak:                                            # section 7: rule changes, prompt and secret requests, authority claims, override text: a clear refusal
            cat = "secrets" if ak in ("prompt", "env", "exfil") else "bypass"
            nm = nlu.normalise(message)
            it = ChatIntent(nlu.SECRETS if cat == "secrets" else nlu.BYPASS, {"urgent": False, "detail": nlu.refusal_detail(nm, cat)}, 1.0, it.lang, cat)
            d["awaiting"], d["ctx"] = None, {}
        else:
            a = scam_lane.assess(message)
            if a.fire:                                    # section 6: the inducement is described in plain words; warn, never draft
                reg = {r.account_ref for r in _recipients(S.world)}
                S.world.audit.append("chat_refused", {"category": "scam"})
                res = _result("scam_warning", scam_lane.warning(a, reg), secrets, status="info" if a.question and not a.pay_context else "refused")
                res["source"] = "scam_lane"
                res["money_moved"] = 0
                return res
    if not d["awaiting"] and src == "router" and not (_affirms(message) and len(message.split()) <= 3) and it.kind not in nlu.REFUSALS:
        act = ctx_mod.resolve(d, message, frames.parse(message), [_bill_name(o.type) for o in _open_obligations(S.world)])
        if act and act[0] == "say":
            res = _result("info", act[1], secrets, status="info")
            res["source"] = "router_v2"
            return res
        if act:
            it2 = nlu.classify(act[1], ui)
            if it2.kind not in nlu.REFUSALS and it2.kind != nlu.UNKNOWN:
                it, message, src = it2, act[1], "context"
        if src == "router":
            comp = _compound(S, message, ui, d, run_intake, secrets, tp_share)
            if comp is not None:
                return comp
    rt = None
    if not d["awaiting"] and src in ("router", "context") and not nlu._SIGN_ASK.match(message.strip()) and not (_affirms(message) and len(message.split()) <= 3):
        rt = router_v2.route(router_v2.Ctx(message, it, d, _recipients(S.world), _open_obligations(S.world), it.lang, bool(S.pending)))
    if rt is not None and rt.note == "content" and robust.enabled() and robust.resolve(message, ui, _recipients(S.world)).status == "intent":
        rt = None                                         # the similarity layer already places this message: keep its answer, the concept layer only fills the gaps
    if rt is not None and rt.kind != "rewrite":
        res = _v2_reply(S, rt, it.lang, d, run_intake, secrets)
        res["source"] = "router_v2"
        if res.get("status") in _LOGGED:
            d.setdefault("log", []).append((res["intent"], res["status"], res["reply"].split(". ")[0][:140]))
        if rt.offer:
            d["last_offer"] = rt.offer
        elif res.get("intent") not in ("convert", "confirm", "clarify"):
            d.pop("last_offer", None)
        if res.get("intent") == "info":
            _remember(d, res, message, it)                # "who is my landlord" then "pay him" binds to the rent; chit-chat must not refresh the context
        return res
    if rt is not None:
        it2 = nlu.classify(rt.text, ui)
        if it2.kind not in nlu.REFUSALS and it2.kind != nlu.UNKNOWN:
            it, message, src = it2, rt.text, "router_v2"
    if not d["awaiting"] and src == "router" and robust.enabled() and not nlu._SIGN_ASK.match(message.strip()) and not _affirms(message):
        payees = _recipients(S.world)
        if it.kind == nlu.UNKNOWN:
            r = robust.resolve(message, ui, payees)
            if r.status == "intent":
                it, src, conf = r.intent, r.source, r.confidence
            else:                                         # weak or ambiguous: a second opinion from the live labeller if it is on, else ask
                if chat_llm.enabled() and isinstance(S.world.llm, LiveLLM):
                    m = chat_llm.propose(S.world.llm, message)
                    if m is not None:
                        it, src = m, "model"
                if it.kind == nlu.UNKNOWN and r.status == "clarify" and not nl_extract.purpose_in_text(message):    # a named bill keeps the "pay my <bill>?" offer
                    clar = r
        elif src == "router":
            alt = robust.arbitrate(message, ui, payees, it)
            if alt is not None and alt.status == "intent":
                it, src, conf = alt.intent, "arbitrated", alt.confidence
            elif alt is not None and alt.status == "none":        # chit-chat the keyword rules read as a payment: treat as unplaced
                it = nlu.ChatIntent(nlu.UNKNOWN, {}, 0.2, it.lang)
            elif alt is not None:
                clar = alt
    elif it.kind == nlu.UNKNOWN and not d["awaiting"] and chat_llm.enabled() and isinstance(S.world.llm, LiveLLM):
        m = chat_llm.propose(S.world.llm, message)
        if m is not None:
            it, src = m, "model"
    if (it.kind == nlu.UNKNOWN and not d["awaiting"] and not d.get("_interp") and chat_llm.interpret_enabled() and chat_llm.usable(S.world.llm)
            and not nl_extract.purpose_in_text(message) and faq.answer(message) is None):
        # section 8: the offline router would only hedge; one verified model interpretation may widen it. The canonical sentence is routed again through everything above.
        facts = str(_balance(S, "en")["reply"]) + " " + str(_obligations(S, "en")["reply"])
        out = chat_llm.interpret(S.world.llm, message, [x[2] for x in d.get("log", [])][-2:], [_bill_name(o.type) for o in _open_obligations(S.world)], facts, d.setdefault("_calls", []))
        if out and out["kind"] == "question":
            return _result("clarify_q", out["text"], secrets, status="needs_info")
        if out and out["kind"] == "answer":
            return _result("faq", out["text"], secrets, status="info")
        if out and out["kind"] == "rewrite":
            d["_interp"] = True
            try:
                res = handle(S, out["canonical"], ui, jti=jti, run_intake=run_intake, secrets=secrets, tp_share=tp_share)
            finally:
                d.pop("_interp", None)
            res["source"] = "model_interpret"
            return res
    offer = None
    if clar is None and not d["awaiting"] and (d.get("last_offer") or {}).get("kind") == "show" and (it.kind == nlu.CONFIRM or _affirms(message)):
        lo = d.pop("last_offer")                          # a bare "yes" binds to the read-only answer offered last turn, nothing else
        it, src = ChatIntent(lo["intent"], dict(lo["slots"]), 0.7, lo["lang"]), "offer"
    if clar is not None:
        res, offer = _answer_best(S, clar, message, d, run_intake, secrets, tp_share)
    else:
        res = _handle(S, it, message, d, run_intake, secrets, tp_share)
    res["source"] = "clarify" if clar is not None else src
    if res.get("intent") not in ("convert", "confirm", "clarify"):
        d.pop("last_offer", None)                         # only the very last offer can be confirmed
    if offer:
        d["last_offer"] = offer
    if res.get("status") in _LOGGED:                      # the session's own actions, for "what did I just do?"
        d.setdefault("log", []).append((res["intent"], res["status"], res["reply"].split(". ")[0][:140]))
        del d["log"][:-12]
    if conf is not None or clar is not None:
        res["confidence"] = round(conf if conf is not None else clar.confidence, 3)
    _remember(d, res, message, it)
    return res


_BILL_OF_TYPE = {"living": "phone"}
_STATEFUL = (nlu.PAY_OBLIGATION, nlu.PAY_TEXT, nlu.PAY_INVOICE, nlu.RATE_TARGET, nlu.LATER, nlu.CORRECT, nlu.UNDO)
_CLAUSE_LABEL = {"balance": "Balance", "obligations": "Open bills", "rate": "Rate", "routes": "Routes", "runway": "Runway", "plan": "Plan", "credit": "Record",
                 "status": "Status", "spending": "Spending", "proof": "Proof", "transfer_issue": "Transfer", "quota": "Limits", "help": "Help", "convert": "Quote",
                 "pay_obligation": "Payment", "faq": "Answer", "explain": "Why"}


def _bill_name(typ: str) -> str:
    t = _BILL_OF_TYPE.get(typ, typ)
    return t if t in router_v2.L.BILLS else "rent"


def _remember(d: dict, res: dict, message: str, it) -> None:
    f = frames.parse(message)
    bill = f.bills[0] if f.bills else (_bill_name(it.slots["type"]) if it.slots.get("type") else None)
    keep = message if res.get("intent") in ("pay_obligation", "convert", "routes", "obligations", "balance", "rate") else None
    ctx_mod.remember(d, res.get("intent") or "", keep, bill)


def _compound(S, message: str, ui: str, d: dict, run_intake, secrets, tp_share):
    """Section 5.5: a message with several requests answers every read-only part in one reply, makes the first state-changing draft and queues the rest.
    A refused part is refused alone and named; the other parts still run. Returns None when the message is not a compound request."""
    if len(message) > 220 or d.get("queue") or re.search(r"\b(?:pay|settle|send)\s+(?:it|that|this|them)\b", message, re.I):       # "calculate it and then pay it": one request, not two
        return None
    parts = frames.split_clauses(message)
    if len(parts) < 2:
        return None
    its = []
    if any(nlu.classify(p, ui).kind in (nlu.CORRECT, nlu.CANCEL, nlu.CONFIRM, nlu.DENY, nlu.UNDO) for p in parts):
        return None                                       # corrections, cancels and confirmations talk about the draft already on the table: one request, not several
    for p in parts:
        i = nlu.classify(p, ui)
        if i.kind == nlu.UNKNOWN:                         # the keyword router does not know this clause: ask the concept layer for a canonical sentence
            rt = router_v2.route(router_v2.Ctx(p, i, d, _recipients(S.world), _open_obligations(S.world), i.lang))
            i2 = nlu.classify(rt.text, ui) if rt is not None and rt.kind == "rewrite" else None
            if i2 is None or i2.kind in (nlu.UNKNOWN,):
                return None
            i = i2
        its.append(i)
    out, first_state, refused, res_state, queued = [], None, [], None, []
    last = None
    for p, i in zip(parts, its):
        if i.kind in nlu.REFUSALS:
            r = _handle(S, i, p, d, run_intake, secrets, tp_share)
            refused.append(p)
            out.append(f"I refused this part ({p!r}): {r['reply']}")
            continue
        if i.kind in _STATEFUL:
            if first_state is None:
                first_state = p
                res_state = _handle(S, i, p, d, run_intake, secrets, tp_share)
                out.append(f"{_CLAUSE_LABEL.get(i.kind, 'Draft')}: {res_state['reply']}")
            else:
                queued.append(p)
            continue
        r = _handle(S, i, p, d, run_intake, secrets, tp_share)
        last = r
        out.append(f"{_CLAUSE_LABEL.get(r.get('intent'), 'Answer')}: {r['reply']}")
    if queued:
        d["queue"] = queued
        out.append(f"Still to do: {queued[0]!r}. Say 'next' when you are ready; each step needs its own confirmation or signature.")
    res = dict(res_state or last or _result("info", "", secrets))
    res["reply"] = " ".join(out)
    res["source"] = "compound"
    if refused and res_state is None and last is None:
        res["status"] = "refused"
    return res


def _v2_reply(S, rt, lang: str, d: dict, run_intake, secrets) -> dict:
    """Fixed-grammar replies of the router v2 (sections 5.3 and 5.7). Everything here is read-only except `revoke`, which makes a held draft."""
    w = S.world
    if rt.kind == "say":
        return _result(rt.intent, rt.text, secrets, status=rt.status)
    if rt.kind == "faq":
        hit = faq.by_id(rt.text)
        return _result("faq", f"{hit[0]} (Screen: {hit[1]}.)", secrets, status="info")
    if rt.kind == "bill_statement":
        parts, first = [], None
        for b in rt.bills:
            xs = _open_obligations(w, b)
            if not xs:
                parts.append(f"Your {b} is not an open bill right now.")
                continue
            x = sorted(xs, key=lambda o: o.due)[0]
            first = first or b
            parts.append(f"{x.type.capitalize()} is {money(x.remaining, lang)} to {_payee_name(w, x.payee_id)}, due {x.due}.")
        if first:
            parts.append(f"Want me to draft the payment? Say 'pay my {router_v2.canon(first)}' and I'll draft it for your signature.")
        res = _result("obligations", " ".join(parts), secrets, status="info")
        rt.offer = {"kind": "pay", "bill": first} if first else None
        return res
    if rt.kind == "bills_pile":
        o = sorted(_open_obligations(w), key=lambda x: x.due)
        if not o:
            return _result("obligations", "You have nothing due right now.", secrets)
        tot = sum(x.remaining for x in o)
        t = (f"You have {len(o)} open bill{'s' if len(o) != 1 else ''} totalling {money(tot, lang)}; the earliest is {o[0].type} due {o[0].due}. "
             + "; ".join(_obl_line(w, x, lang) for x in o) + ". Want me to plan the order?")
        rt.offer = {"kind": "plan"}
        return _result("obligations", t, secrets, status="info")
    if rt.kind == "worry":
        res = _runway(S, lang, secrets, "will my money last")
        res["reply"] += " Want me to plan what to pay first?"
        rt.offer = {"kind": "plan"}
        return res
    if rt.kind == "revoke":
        return _revoke(S, d, run_intake, lang, secrets)
    if rt.kind == "scorecard":
        return _result("scorecard", scorecard_mod.summary(S, lang), secrets, status="info")
    if rt.kind == "mandate_card":
        return _result("mandate", scorecard_mod.mandate_card(S), secrets, status="info")
    return _result(nlu.UNKNOWN, faq.hedge(""), secrets, status="unknown")


_REVOKE_RATE = re.compile(r"rate|target|alert|convert", re.I)


def _revoke(S, d: dict, run_intake, lang: str, secrets=None) -> dict:
    """5.7 item 9: ending a standing instruction or rate target is a held draft that only the student's device-key signature completes."""
    msg = d.get("_msg", "")
    ms = [m for m in S.world.passport.rules.mandates if m.get("active")]
    want_rate = bool(_REVOKE_RATE.search(msg))
    ms = [m for m in ms if (m.get("kind") == "rate_target") == want_rate]
    if not ms:
        return _result("revoke", "You have no active rate alert or standing instruction to stop." if want_rate else "You have no active standing instruction to stop.", secrets, status="info")
    m = ms[0]
    o = loc.localize_outcome(run_intake(Request("", source="chat", mandate={"kind": "revoke", "mandate_id": m["id"]})), lang)
    dr, pid = o.get("draft") or {}, o.get("pending_id")
    if o["status"] == "held" and pid:
        item = S.pending.get(pid, {})
        what = f"rate alert at {m.get('rate')}" if m.get("kind") == "rate_target" else f"standing instruction for your {m.get('obligation', 'bill')}"
        t = (f"Stopping your {what}: this is a draft, not done yet. It ends only after you sign this exact draft (#{str(dr.get('draft_hash', ''))[:10]}) with your device key. "
             f"No money moves. Tap Sign and approve.")
        d["last_pending"] = pid
        return _result("revoke", t, secrets, status="held", pending_id=pid, draft_hash=dr.get("draft_hash"), needs=_needs(item) if item else [], outcome=o)
    return _result("revoke", "I could not prepare that change. Nothing was changed.", secrets, status="info")


# ------------------------------------------------------------------ clarification (layer 6): numbered options, answer-only intents
_OPTION = {
    "obligations": ("see your open bills", "查看待付账单", r"bill|due|owe|outstanding|账单|待付"),
    "balance": ("check your balance", "查看余额", r"balance|money|funds|余额|资金"),
    "routes": ("compare ways to send money", "比较汇款方式", r"route|way|send|compare|路线|汇款"),
    "runway": ("check whether your money will last", "看看钱够不够用", r"last|enough|runway|够用|撑"),
    "quota": ("see the yearly remittance limits", "了解年度汇款额度", r"limit|quota|lrs|tcs|额度"),
    "credit": ("see how to build your payment record", "了解如何建立付款记录", r"credit|record|history|信用"),
    "status": ("check whether a payment went through", "查看付款状态", r"status|went through|paid|状态|到账"),
    "transfer_issue": ("get help with a late or short transfer", "处理延迟或少到账的汇款", r"late|short|delay|issue|problem|延迟|少"),
    "fx_bill": ("ask about a bill in USD or EUR", "咨询美元或欧元账单", r"usd|eur|dollar|euro|foreign|美元|欧元|外币"),
    "parent_request": ("ask your parents for money", "向父母要钱的办法", r"parent|mom|dad|family|父母|爸妈|家"),
    "share_record": ("share your payment record", "分享付款记录", r"share|landlord|lender|分享|房东"),
    "help": ("see what I can do", "看看我能做什么", r"help|what can|帮助|功能"),
    "convert": ("get a conversion quote", "获取兑换报价", r"convert|exchange|swap|兑换|换"),
    "rate_target": ("set up a rate alert", "设置汇率提醒", r"alert|target|notify|提醒|通知"),
    "explain": ("hear why a payment was held or refused", "了解付款为何被暂缓或拒绝", r"why|explain|reason|为什么|原因"),
    "rate": ("check today's exchange rate", "查看今日汇率", r"rate|汇率"),
    "spending": ("see your recent spending", "查看最近的支出", r"spend|expense|transaction|支出|交易"),
    "proof": ("get a payment proof or receipt", "获取付款证明或收据", r"proof|receipt|证明|收据"),
    "plan": ("plan your payments", "规划付款", r"plan|budget|schedule|计划|预算"),
}
_LABEL_KIND = {"routes": nlu.ROUTES, "convert": nlu.CONVERT, "rate_target": nlu.RATE_TARGET}
_ORDINAL = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "第一": 1, "第二": 2, "第三": 3, "一": 1, "二": 2, "三": 3}


def _option_text(o: dict, lang: str) -> str:
    en, zh, _ = _OPTION[o["label"]]
    amt = o["slots"].get("amount")
    if o["label"] in ("routes", "convert") and amt:
        cur = o["slots"].get("currency") or "INR"
        return (f"获取 {cur} {amt:,.0f} 的报价" if o["label"] == "routes" else f"获取 {cur} {amt:,.0f} 的兑换报价") if lang == "zh" else \
               (f"get a quote for {cur} {amt:,.0f}" if o["label"] == "routes" else f"get a conversion quote for {cur} {amt:,.0f}")
    return zh if lang == "zh" else en


def _answer_best(S, r, message: str, d: dict, run_intake, secrets, tp_share):
    """Section 5.2: every candidate is answer-only, so answer the best one. A runner-up within 25% is offered in one line (a bare 'yes' shows it); never a numbered menu."""
    (lab, sc, it), rest = r.candidates[0], r.candidates[1:]
    res = _handle(S, it, message, d, run_intake, secrets, tp_share)
    if not rest or res.get("status") in ("refused", "held") or rest[0][1] < 0.75 * sc:
        return res, None
    lab2, _, it2 = rest[0]
    en, zh, _ = _OPTION[lab2]
    res["reply"] += (f" 我也可以{zh}——回复“是”即可。" if it.lang == "zh" else f" I can also show you how to {en} - say 'yes'.")
    return res, {"kind": "show", "intent": it2.kind, "slots": dict(it2.slots), "lang": it2.lang}


def _clarify(d: dict, r, message: str, secrets=None) -> dict:
    """The keyword router and the similarity step could not decide: offer the best answer-only candidates as numbered options. Nothing is drafted."""
    opts = [{"label": lab, "kind": ci.kind, "slots": ci.slots, "lang": ci.lang} for lab, _, ci in r.candidates[:3]]
    lang = r.candidates[0][2].lang
    items = " ".join(f"{i}) {_option_text(o, lang)}" for i, o in enumerate(opts, 1))
    pay = bool(nlu._PAY_WORD.search(nlu.normalise(message)) or nlu._OBL_WORD.search(nlu.normalise(message)))
    if lang == "zh":
        t = f"请选择：{items}？回复编号或名称即可。" + (" 要付账单请直接说“交房租”。" if pay else "")
    else:
        t = f"Which of these do you want: {items}? Reply with a number or the name." + (" To pay a bill, say for example 'pay my rent'." if pay else "")
    d["awaiting"], d["ctx"] = "clarify", {"options": opts}
    return _result("clarify", t, secrets, status="needs_info", needs=["info:intent"], options=[o["label"] for o in opts])


def _clarify_pick(d: dict, message: str, it: ChatIntent) -> ChatIntent | None:
    """Which numbered option the reply chooses ('2', 'second', the option's name or a message the router places on one of them), else None."""
    opts = d["ctx"].get("options", [])
    t = nlu.normalise(message)
    pick = None
    m = re.fullmatch(r"(?:option |number |no\.? |#|第)?(\d)(?:\)|\.|号)?", t)
    if m and 1 <= int(m.group(1)) <= len(opts):
        pick = opts[int(m.group(1)) - 1]
    elif t in _ORDINAL and _ORDINAL[t] <= len(opts):
        pick = opts[_ORDINAL[t] - 1]
    if pick is None and len(t) <= 40:
        named = [o for o in opts if re.search(_OPTION[o["label"]][2], t, re.I)]
        if len(named) == 1:
            pick = named[0]
    if pick is None and it.kind != nlu.UNKNOWN:
        same = [o for o in opts if o["kind"] == it.kind]
        if len(same) == 1 and it.kind not in nlu.REFUSALS:
            pick = same[0]
    if pick is None:
        return None
    return ChatIntent(pick["kind"], dict(pick["slots"]), 0.7, nlu.detect_lang(message, pick.get("lang", "en")))



# "I confirm the conversion" / "looks right, go ahead" while a conversion quote is waiting: same as a plain "yes".
_AFFIRM = re.compile(r"\bi confirm\b|\bconfirm(?:ed)? (?:the |that |this )?(?:conversion|quote)|\blooks? right\b|\bgo ahead\b|\bproceed\b|确认(?:兑换|换汇)", re.I)
_AFFIRM_NO = re.compile(r"\b(?:don'?t|do not|not|never|cancel|wait|before|until|unless)\b|不要|别|取消", re.I)


def _affirms(message: str) -> bool:
    """A short standalone confirmation only: pasted or long text that happens to contain 'go ahead' never confirms anything."""
    return len(message.strip()) <= 100 and bool(_AFFIRM.search(message)) and not _AFFIRM_NO.search(message)


def _handle(S, it: ChatIntent, message: str, d: dict, run_intake, secrets=None, tp_share=None) -> dict:
    lang = it.lang
    if it.kind == nlu.UNKNOWN and nlu._SIGN_ASK.match(message.strip()):                   # "sign it": chat can't, and says so without touching any draft
        f = _find_pending(S, d)
        t = ("我不能替您签名。请点击“签名并批准”，由您的设备密钥对这份确切的草稿签名。" if lang == "zh" else
             "I can't sign for you. Tap Sign and approve so your device key signs the exact draft.")
        dr = (f[1]["outcome"].get("draft") or {}) if f else {}
        return _result("confirm", t, secrets, status="held" if f else "info", pending_id=f[0] if f else None,
                       draft_hash=dr.get("draft_hash"), needs=_needs(f[1]) if f else [])
    # an answer to the question asked last turn
    if d["awaiting"] == "offer_plan":
        d["awaiting"], d["ctx"] = None, {}
        if it.kind == nlu.CONFIRM or (it.kind not in nlu.REFUSALS and _affirms(message)):
            return _plan(S, lang, secrets, d)
        if it.kind in (nlu.DENY, nlu.CANCEL):
            return _result("deny", "好的，我不会制定计划。" if lang == "zh" else "Okay, no plan for now.", secrets, status="cancelled")
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
    elif d["awaiting"] and it.kind in nlu.REFUSALS:
        d["awaiting"], d["ctx"] = None, {}
    elif d["awaiting"]:
        r = _continue(S, run_intake, it, message, lang, d, secrets)
        if r is not None:
            return r
        if it.kind in _INFO_KINDS and d["awaiting"]:
            res = _handle(S, it, message, {**d, "awaiting": None}, run_intake, secrets, tp_share)
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
        if (o.get("card") or {}).get("rule") == "extract_low_confidence":     # never print "CNY 0 to ?": say what could not be read and ask for it
            reply = ("我没能从这段文字里可靠地读出收款方和金额，所以没有创建草稿，也没有任何资金转出。请告诉我收款方和金额（例如“交学费”），或贴出完整的发票。" if lang == "zh" else
                     "I couldn't read a payee and an amount from that text, so I made no draft and CNY 0 moved. Tell me who it is for and how much (or say 'pay my tuition'), "
                     "or paste the whole invoice. If you only want to know whether it is genuine, ask 'is this a scam?' with the message pasted.")
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
        return _rate_target(S, message, lang, secrets, run_intake, d)
    if k == nlu.PAY_OBLIGATION:
        if _REPEAT.search(message):                       # "pay my rent 6 times": a count is not an amount, and one bill is paid once
            t = ("“6 次”不是金额。一笔账单只会付一次。您是想一次付清整笔账单，还是分期付一部分？请告诉我金额，例如“交房租 3000”。" if lang == "zh" else
                 "A number next to 'times' is a count, not an amount, and a bill is paid once. Do you want the whole bill in one payment, or a part payment? Tell me the amount, for example 'pay rent 3000'.")
            return _result(k, t, secrets, status="needs_info")
        res = _pay_obligation(S, run_intake, it, message, lang, d, secrets)
        ex = _EXTRA.search(message)
        if ex and res.get("status") != "refused":
            v = float(ex["amt"].replace(",", ""))
            res["reply"] += (f" 另外的 {ex['what']} CNY {v:,.0f} 不是登记在册的账单，所以我没有为它起草付款；这笔钱不会转出。" if lang == "zh" else
                             f" The extra {ex['what']} of CNY {v:,.0f} is not a bill that can be paid, so I did not draft it and none of it moves.")
        return res
    if k == nlu.PAY_TEXT:
        return _pay_text(S, run_intake, it, message, lang, d, secrets)
    if k == nlu.CANCEL:
        if nlu.REFUND_ADVICE.search(nlu.normalise(message)):       # "paid twice by mistake, cancel it": advice only
            return _undo(S, lang, d, secrets, advice=True)
        return _cancel(S, lang, d, secrets, message)
    if k == nlu.DENY:
        return _cancel(S, lang, d, secrets) if len(S.pending) == 1 and d.get("last_pending") in S.pending else \
            _result("deny", "好的。" if lang == "zh" else "Okay.", secrets)
    lo = d.get("last_offer")
    if lo and lo.get("kind") == "convert_quote" and (k == nlu.CONFIRM or _affirms(message)):      # "yes" after a quote chat cannot confirm: say what it binds to, and that it moved nothing
        d.pop("last_offer", None)
        q = f"{lo['amount']:,.0f} {lo['src']} → {lo['dst']}"
        t = (f"“是”只对应刚才的兑换报价（{q}）：聊天里不能确认这笔兑换（超过自动额度或不是 INR→CNY），请在“兑换”页面操作。没有兑换任何资金；您的其他草稿不受影响，仍需您自己签名。" if lang == "zh" else
             f"Your 'yes' applies to the conversion quote just shown ({q}), which chat cannot confirm (above the auto limit or not INR→CNY): use the Convert screen. "
             f"Nothing was converted, and any other draft is unchanged and still needs your own signature.")
        return _result(nlu.CONFIRM, t, secrets, status="info")
    if k == nlu.CONFIRM:
        f = _find_pending(S, d)
        if f:
            t = ("我不能替您签名。请点击“签名并批准”，由您的设备密钥对这份确切的草稿签名。" if lang == "zh" else
                 "I can't sign for you. Tap Sign and approve so your device key signs this exact draft.")
            dr = f[1]["outcome"].get("draft") or {}
            return _result("confirm", t, secrets, status="held", pending_id=f[0], draft_hash=dr.get("draft_hash"), needs=_needs(f[1]))
        first = sorted(_open_obligations(S.world), key=lambda o: o.due)[:1]
        hint = f" I can pay your {'phone bill' if first[0].type == 'living' else first[0].type} or show your balance." if first else " I can show your balance or your open bills."
        return _result("confirm", "好的。有什么我可以帮您的？" if lang == "zh" else "Do what?" + hint, secrets)
    if k == nlu.CORRECT:
        return _correct(S, run_intake, it, message, lang, d, secrets)
    if k == nlu.UNDO:
        return _undo(S, lang, d, secrets, advice=bool(it.slots.get("advice") or not _UNDO_DRAFT.search(nlu.normalise(message))))
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
        return _plan(S, lang, secrets, d)
    if k == nlu.CONVERT:
        return _convert(S, it, lang, d, secrets, message, run_intake)
    if k == nlu.STATUS:
        if _WHERE.search(message):
            return _where(S, it, message, lang, secrets)
        return _status(S, lang, d, secrets)
    if k == nlu.SPENDING:
        return _spending(S, lang, secrets)
    if k == nlu.TRANSFER_ISSUE:
        return _transfer_issue(S, it, lang, secrets)
    if k == nlu.FX_BILL:
        return _fx_bill(S, it, message, lang, secrets, run_intake, d)
    if k == nlu.PARENT_REQUEST:
        return _parent_request(S, it, message, lang, secrets)
    if k == nlu.QUOTA:
        return _quota(S, lang, secrets)
    if k == nlu.SHARE_RECORD:
        return _share_record(S, lang, secrets, message, tp_share)
    if k == nlu.EXPLAIN:
        return _explain(S, lang, secrets)
    if k == nlu.PROOF:
        return _proof(S, lang, secrets)
    if k == nlu.FINANCE_SUMMARY:
        return _finance_summary(S, lang, secrets)
    if k == nlu.CREDIT and it.slots.get("status"):
        return _credit_status(S, lang, secrets)
    if k == nlu.CREDIT:
        return _credit_growth(S, lang, secrets) if it.slots.get("growth") else _credit(S, lang, secrets)
    if k == nlu.ESTIMATE:
        return _estimate(S, it, message, lang, secrets)
    if k == nlu.LATER:
        return _later(S, it, message, lang, secrets, run_intake, d)
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
        if it.slots.get("start"):
            return _start_here(S, lang, secrets)
        if it.slots.get("next"):
            return _next(S, lang, secrets)
        if it.slots.get("concept") and it.slots["concept"] != "forgot":
            en, zh = _CONCEPT_HELP[it.slots["concept"]]
            return _result(k, zh if lang == "zh" else en, secrets, status="info")
        if it.slots.get("reset") or it.slots.get("concept"):
            t = ("我无法重置或查看登录口令；请联系沙盒的运营者。我可以帮您付账单、查余额。" if lang == "zh" else
                 "I can't reset or show a login passcode; ask whoever runs this sandbox. I can help with bills, balances and rates.")
            return _result(k, t, secrets)
        if it.slots.get("cancel_hint"):
            t = ("我只会在您明确说“取消”并指明哪份草稿时才取消，例如“取消房租草稿”。我没有改动任何草稿。" if lang == "zh" else
                 "I only cancel a draft when you clearly say cancel and name it, for example 'cancel the rent draft'. I haven't changed any draft.")
            return _result(k, t, secrets, status="info")
        return _result(k, _HELP_ZH if lang == "zh" else _HELP_EN, secrets)
    if _RECAP.search(message):
        return _recap(d, lang, secrets)
    if _affirms(message) and _find_pending(S, d):         # "ok approve it, I confirm" with a draft waiting: only the device key can release it
        f = _find_pending(S, d)
        dr = f[1]["outcome"].get("draft") or {}
        t = ("我不能替您批准。草稿正在等待：只有您用设备密钥对这份确切的草稿签名后，款项才会转出。请点击“签名并批准”。" if lang == "zh" else
             "I can't approve for you. Your draft is waiting, and it moves only after your device key signs this exact draft. Tap Sign and approve.")
        return _result("confirm", t, secrets, status="held", pending_id=f[0], draft_hash=dr.get("draft_hash"), needs=_needs(f[1]))
    if _affirms(message):                  # "I confirm" with no quote waiting: say so, never guess
        t = ("现在没有等待确认的兑换。先说“convert INR 10000 to CNY”，我会先报价，再由您确认。" if lang == "zh" else
             "No conversion is waiting for confirmation. Ask for a quote first (for example 'convert INR 10,000 to CNY') and I'll ask you to confirm it.")
        return _result(nlu.CONFIRM, t, secrets, status="info")
    if _PERSON.search(message) and re.search(r"\d{3,}", message):       # "Forward 50000 to my cousin, acct ...": never a payment from chat
        return _new_payee_reply(S, nlu.PAY_OBLIGATION, lang, secrets)
    g = glossary.answer(message, S.world.passport.rules, lang)
    if g:                                                  # a concept question: a fixed answer written in code, no model, no draft
        return _result(nlu.FAQ, g, secrets, status="info")
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
    elif topic == "acct_changed":
        t = ("银行账户变更的通知不能直接相信：邮件、短信或电话里的账号我从不使用。款项只会汇到登记册里的账户；学校真的换了账户，也必须经学校办公室核实后在登记册里更新。"
             "请不要回复或转账，我没有创建任何草稿。需要付款时说“交学费”，我会用登记册里的账户起草。您也可以贴出这条消息并问“这是诈骗吗”。" if zh else
             "Treat a message saying the university's bank account changed as a likely scam until the registry confirms it. I never use an account taken from an email, text or call: "
             "money goes only to the registry account, and a real change has to be verified with the university office and then updated in the registry. "
             "Don't reply or transfer anything; I made no draft. To pay, say 'pay my tuition' and I'll draft it to the registry account. You can also paste the message and ask 'is this a scam?'.")
    elif topic == "sign":
        t = ("在应用里签名：打开待批准的草稿，点击“签名并批准”，由您的设备密钥对这份确切的草稿签名。签名后系统会再次核对草稿和规则，才会付款到登记账户。我不能替您签名。" if zh else
             "Sign in the app: open the pending draft and tap Sign and approve, so your device key signs that exact draft. After you sign, the system re-checks the signed draft and the rules, then pays the registry account; if anything changed, nothing is paid. I can't sign for you.")
    else:
        t = ("Oasis 是一个模拟（MOCK）沙盒里的助手，帮在国外的学生付账单：它只起草付给登记收款方的付款，由您用设备密钥签名后才会执行。所有数据和资金都是模拟的。" if zh else
             "Oasis is an assistant in a MOCK sandbox that helps a student abroad pay bills: it only drafts payments to registered payees, and nothing is paid until you sign with your device key. All data and money are simulated.")
    return _result(nlu.FAQ, t, secrets, status="info")


_STATUS_ZH = {"paid": "已支付", "held": "已暂缓，等待批准", "frozen": "已冻结", "rejected": "已拒绝", "needs_verification": "需要验证"}


def _rate_target(S, message: str, lang: str, secrets=None, run_intake=None, d: dict | None = None) -> dict:
    m = nlu.TARGET_RE.search(message)
    mz = None if m else nlu.TARGET_RE_ZH.search(message)
    if mz:
        m = (mz.group(2), mz.group(1)) if mz.group(1) else (mz.group(3), mz.group(4))
    amount, rate = ((float(m[0].replace(",", "")), float(m[1])) if isinstance(m, tuple)
                    else (float(m.group(1).replace(",", "")), float(m.group(2))))
    return _set_target(S, rate, amount, lang, secrets, run_intake, d)


def _set_target(S, rate: float, amount: float, lang: str, secrets=None, run_intake=None, d: dict | None = None) -> dict:
    lim = S.world.passport.rules.tier1_auto_convert_cny
    if run_intake is not None and d is not None:           # a standing instruction: a held draft, set only by the student's device-key signature
        o = loc.localize_outcome(run_intake(Request("", source="chat", mandate={"kind": "rate_target", "rate": rate, "convert_cny": amount})), lang)
        dr, pid = o.get("draft") or {}, o.get("pending_id")
        if o["status"] == "held" and pid:
            item = S.pending.get(pid, {})
            h = str(dr.get("draft_hash", ""))[:10]
            t = (f"汇率目标草稿：当 INR→CNY 达到 {rate:.4f} 时兑换 ¥{amount:,.0f}" + ("（在您的 1 级自动额度之内，之后由我自行执行）" if amount <= lim else f"（超过 ¥{lim:,.0f} 的自动额度，到时仍需您批准）")
                 + f"。创建它不会转出款项；只有您用设备密钥对这份确切的草稿（#{h}）签名后才生效。请点击“签名并批准”。我不预测汇率。" if lang == "zh" else
                 f"Rate target draft: when INR to CNY reaches {rate:.4f}, convert CNY {amount:,.0f}"
                 + (" on my own (inside your Tier-1 limit)" if amount <= lim else f" after you approve it (above your CNY {lim:,.0f} auto limit)")
                 + f". Creating it moves no money and takes effect only after you sign this exact draft (#{h}) with your device key. Tap Sign and approve. I do not predict rates.")
            d["last_pending"] = pid
            return _result(nlu.RATE_TARGET, t, secrets, status="held", pending_id=pid, draft_hash=dr.get("draft_hash"), needs=_needs(item) if item else [], outcome=o)
        reasons = "; ".join((o.get("card") or {}).get("reasons") or []) or o["status"]
        return _result(nlu.RATE_TARGET, (f"我没有设定汇率目标：{reasons}。" if lang == "zh" else f"I did not set a rate target: {reasons}."), secrets, status="rejected")
    t = S.agent.set_rate_target(rate, amount)
    S.save()
    if lang == "zh":
        reply = (f"已设定汇率目标：我会关注 INR 对 CNY 的汇率，当它达到 {rate:.4f} 时，" +
                 (f"自行兑换 ¥{amount:,.0f}（在您的 1 级自动额度之内）。" if amount <= lim
                  else f"在您批准之后兑换 ¥{amount:,.0f}（超过 ¥{lim:,.0f} 的自动额度）。") + " 我不会预测汇率，只会按您设定的目标行动。")
    else:
        reply = (f"Rate target set: I will watch INR to CNY and, when it reaches {rate:.4f}, convert CNY {amount:,.0f} "
                 + ("on my own (within your Tier-1 limit)." if amount <= lim else f"after you approve it (above your CNY {lim:,.0f} auto limit).")
                 + " I do not predict rates; I only act on your target.")
    return _result(nlu.RATE_TARGET, reply, secrets, status="done", target=t)
