"""Output-side localisation of API payloads (English -> Simplified Chinese).

Everything here operates on COPIES of what the engine produced, at the edge of the API. The stored data (audit chain,
proof packs, cards, plans, benchmark) stays English and byte-identical, so signatures, hashes and replayed demos do not
change with the interface language. Anything without a translation is returned as it was (English fallback).

Never translated by design: invoice text, payee names, legal/regulatory source quotes, rule ids (R01..R17), machine
codes, hashes, key ids, endpoint names, and the model-written free text of a live planner.
"""
from __future__ import annotations

import copy
import re

from . import i18n
from .zh_messages import ACTION_ZH, CONTACT_ZH, route_zh, tr, tr_hint, tr_list, tr_trace

ZH = "zh"


def is_zh(lang) -> bool:
    return lang == ZH


# ---------------------------------------------------------------------------------------------- why-cards
def localize_card(card: dict | None, lang: str) -> dict | None:
    """The 'Why was I stopped?' card in `lang`: title and text rebuilt from the card's own facts (rule, action, amount, payee,
    reasons), so the rule id and the amount are always in the Chinese text. The stored card is not modified."""
    if not card or not is_zh(lang):
        return card
    out = dict(card)
    action = card.get("action")
    out["title"] = "等待批准" if action == "held" else "这笔款项为何被拦截？"
    out["text"] = i18n.why_stopped({"payee": card.get("payee", "?"), "amount": card.get("amount", 0), "action": action,
                                    "rule": card.get("rule", "?"), "reasons": card.get("reasons", [])}, ZH)
    out["reasons"] = tr_list(card.get("reasons", []), ZH)
    if card.get("uncertainty") is not None:
        out["uncertainty"] = i18n.card_uncertainty_zh(card["uncertainty"])
        out["next_step"] = i18n.card_next_step(action, card.get("next_step") if card.get("next_step") not in (i18n.NEXT_STEP["held"][0], i18n.NEXT_STEP["frozen"][0]) else None, ZH)
    return out


def localize_cards(cards, lang):
    return [localize_card(c, lang) for c in cards] if is_zh(lang) and isinstance(cards, list) else cards


# ---------------------------------------------------------------------------------------------- one payment outcome
RECOVERY_STEPS_ZH = {
    "freeze payment": "冻结这笔付款",
    "identify what changed": "找出发生了什么变化",
    "replan the safest route": "重新规划最安全的路线",
    "ask the student to approve the new plan": "请学生批准新的方案",
}


def _recovery_step(s: str) -> str:
    m = re.fullmatch(r"re-verify (.+) through the registry's verified channel", s)
    if m:
        return f"通过登记处核实的渠道重新核实{m.group(1)}"
    return RECOVERY_STEPS_ZH.get(s, s)


def localize_outcome(o, lang: str):
    """A payment outcome (pipeline `Outcome.to_dict()` JSON) with its human text in `lang`. Adds `trace_localized`."""
    if not is_zh(lang) or not isinstance(o, dict):
        return o
    o = copy.deepcopy(o)
    if o.get("card"):
        o["card"] = localize_card(o["card"], lang)
    dec = o.get("decision")
    if isinstance(dec, dict) and dec.get("reasons"):
        dec["reasons"] = tr_list(dec["reasons"], lang)
    ver = o.get("verification")
    if isinstance(ver, dict) and ver.get("reasons"):
        ver["reasons"] = tr_list(ver["reasons"], lang)
    risk = o.get("risk")
    if isinstance(risk, dict) and risk.get("evidence"):
        risk["evidence"] = tr_list(risk["evidence"], lang)
    cor = o.get("corridor")
    if isinstance(cor, dict):
        for f in cor.get("findings", []):
            f["message"] = tr(f.get("message", ""), lang)
    dup = o.get("duplicate")
    if isinstance(dup, dict) and dup.get("why"):
        dup["why"] = tr(dup["why"], lang)
    rec = o.get("recovery")
    if isinstance(rec, dict):
        rec["steps"] = [_recovery_step(s) for s in rec.get("steps", [])]
        vc = rec.get("verified_channel")
        if isinstance(vc, str):
            m = re.fullmatch(r"(.+) \(from the registry; never details from the suspicious request\)", vc)
            if m:
                rec["verified_channel_zh"] = f"{CONTACT_ZH.get(m.group(1), m.group(1))}（来自登记处；绝不使用可疑请求中的任何信息）"
        dm = rec.get("draft_message")
        if isinstance(dm, str) and rec.get("draft_source") == "template":
            m = re.fullmatch(r"Hello (?P<name>.+?), we received a payment request for (?P<type>\w+) \(CNY (?P<amt>[\d,]+), due (?P<due>[\d-]+)\) with changed details\. "
                             r"Nothing has been paid\. Please confirm your current receiving account to us through (?P<ch>.+)\.", dm)
            if m:       # the template draft, in Chinese; a model-written draft stays as written
                from .zh_messages import PURPOSE_ZH
                rec["draft_message_zh"] = (f"{m['name']}，您好：我们收到一份关于{PURPOSE_ZH.get(m['type'], m['type'])}（¥{m['amt']}，到期日 {m['due']}）的付款请求，"
                                           f"其中的收款信息有变更。目前尚未支付任何款项。请通过{CONTACT_ZH.get(m['ch'], m['ch'])}向我们确认您当前的收款账户。")
        chk = rec.get("draft_checks")
        if isinstance(chk, dict):
            chk["problems"] = list(chk.get("problems", []))
        src = rec.get("draft_source")
        if src == "template":
            rec["draft_source_zh"] = "模板"
    if o.get("trace"):
        o["trace_localized"] = [tr_trace(t, lang) for t in o["trace"]]
    return o


# ---------------------------------------------------------------------------------------------- triggers, spending, state
def localize_triggers(triggers, lang):
    if not is_zh(lang) or not isinstance(triggers, list):
        return triggers
    out = []
    for t in triggers:
        t = dict(t)
        t["message"] = tr(t.get("message", ""), lang)
        out.append(t)
    return out


def localize_spending(sp, lang):
    if not is_zh(lang) or not isinstance(sp, dict):
        return sp
    sp = dict(sp)
    for k in ("basis_text", "note"):
        if sp.get(k):
            sp[k] = tr(sp[k], lang)
    return sp


def localize_state(st: dict, lang: str) -> dict:
    if not is_zh(lang) or not isinstance(st, dict):
        return st
    st = dict(st)
    if "cards" in st:
        st["cards"] = localize_cards(st["cards"], lang)
    if "triggers" in st:
        st["triggers"] = localize_triggers(st["triggers"], lang)
    if "spending" in st:
        st["spending"] = localize_spending(st["spending"], lang)
    if isinstance(st.get("burn"), dict) and st["burn"].get("basis"):
        st["burn"] = {**st["burn"], "basis": tr(st["burn"]["basis"], lang)}
    if isinstance(st.get("autonomy"), dict) and isinstance(st["autonomy"].get("log"), list):
        st["autonomy"] = {**st["autonomy"], "log": localize_actions(st["autonomy"]["log"], lang)}
    if "pending" in st:
        pend = []
        for p in st["pending"]:
            p = dict(p)
            if p.get("card"):
                p["card"] = localize_card(p["card"], lang)
            if isinstance(p.get("duplicate"), dict) and p["duplicate"].get("why"):
                p["duplicate"] = {**p["duplicate"], "why": tr(p["duplicate"]["why"], lang)}
            pend.append(p)
        st["pending"] = pend
    return st


def localize_actions(actions, lang):
    """Autonomy actions / log entries: the hold/block `reasons` lists are translated; kinds, rules and figures are not."""
    if not is_zh(lang) or not isinstance(actions, list):
        return actions
    return [{**a, "reasons": tr_list(a["reasons"], lang)} if isinstance(a, dict) and isinstance(a.get("reasons"), list) else a for a in actions]


# ---------------------------------------------------------------------------------------------- plans
def _issue(i, lang):
    if not isinstance(i, dict):
        return i
    i = dict(i)
    if i.get("message"):
        i["message"] = tr(i["message"], lang)
    if i.get("hint"):
        i["hint"] = tr_hint(i["hint"], lang)
    return i


def localize_validation(v, lang):
    if not is_zh(lang) or not isinstance(v, dict):
        return v
    v = dict(v)
    for k in ("errors", "warnings"):
        if isinstance(v.get(k), list):
            v[k] = [_issue(i, lang) for i in v[k]]
    if isinstance(v.get("metrics"), dict) and v["metrics"].get("rate_basis"):
        v["metrics"] = {**v["metrics"], "rate_basis": tr(v["metrics"]["rate_basis"], lang)}
    return v


def localize_plan(plan, lang):
    """A plan view (`_plan_view`): why-this-plan, validator warnings/errors and fallback text. The model's own free-text
    rationale and the tool-call trace are left as written."""
    if not is_zh(lang) or not isinstance(plan, dict):
        return plan
    plan = dict(plan)
    if isinstance(plan.get("why"), list):
        plan["why"] = tr_list(plan["why"], lang)
    if plan.get("validation"):
        plan["validation"] = localize_validation(plan["validation"], lang)
    if plan.get("rationale"):
        plan["rationale"] = tr(plan["rationale"], lang)       # the deterministic planner's note; a live model's prose is unchanged
    if plan.get("fallback_reason"):
        plan["fallback_reason"] = _fallback_reason(plan["fallback_reason"])
    if isinstance(plan.get("trace"), list):
        tl = []
        for t in plan["trace"]:
            if isinstance(t, dict) and t.get("type") == "proposal" and t.get("validation"):
                t = {**t, "validation": localize_validation(t["validation"], lang), "rationale": tr(t.get("rationale") or "", lang)}
            elif isinstance(t, dict) and t.get("type") == "fallback":
                t = {**t, "reason": _fallback_reason(t.get("reason", "")),
                     "message": "实时模型没有给出有效的计划；改用确定性规划器的计划。"}
            tl.append(t)
        plan["trace"] = tl
    if isinstance(plan.get("step_status"), list):
        plan["step_status"] = [{**s, "note": _step_note(s["note"])} if s.get("note") else s for s in plan["step_status"]]
    return plan


def _fallback_reason(r: str) -> str:
    m = re.fullmatch(r"no valid plan after (\d+) proposal\(s\)", r or "")
    if m:
        return f"{m.group(1)} 次提案后仍没有有效的计划"
    if r == "the model never proposed a plan":
        return "模型从未提出过计划"
    return r


def _step_note(n: str) -> str:
    if n == "insufficient_inr":
        return "卢比余额不足"
    return n


def localize_plans(plans, lang):
    return [localize_plan(p, lang) for p in plans] if is_zh(lang) and isinstance(plans, list) else plans


# ---------------------------------------------------------------------------------------------- the scripted demo
DEMO_TEXT_ZH = {
    # titles
    "1. Arjun arrives with INR 5 lakh": "1. Arjun 带着 50 万卢比（INR 5 lakh）抵达",
    "2. Tuition to the verified university": "2. 向已验证的大学支付学费",
    "3. Parent co-approves a top-up": "3. 家长共同批准一笔补充汇款",
    "4. Landlord's genuine account change": "4. 房东真实的收款账户变更",
    "5. Tier-1 autonomy": "5. 1 级自主权限",
    "6. Proof packs and savings receipt": "6. 证明包与节省回执",
    "1. Forged invoice with swapped bank details": "1. 被调换银行账号的伪造发票",
    "2. Payment instructions rewritten after approval": "2. 批准之后付款指令被改写",
    "3. Hidden page injection reaches for a canary": "3. 页面中的隐藏注入触碰了诱饵",
    "4. The agent asks; the student approves the recovery": "4. 代理询问，学生批准恢复方案",
    "5. Receipts": "5. 回执",
    # narratives
    "One sentence to the agent. It builds the Passport, forecasts, compares routes and projects savings.":
        "对代理说一句话。它会建立财务护照、做出预测、比较汇款路线并估算节省。",
    "Registry check, signed hybrid intent, executor, proof pack.": "登记处核验、混合签名意图、执行器、证明包。",
    "A large family transfer needs the parent; the parent sees it in Tamil.": "大额家庭汇款需要家长批准；家长会以泰米尔语看到说明。",
    "The registry confirms the new account; test payment; limits open. Not blocked.": "登记处确认了新账户；先做测试付款，再开放额度。没有被误拦。",
    "A student-set rate target and a recurring bill are handled by the agent within policy.": "学生设定的汇率目标和一笔定期账单，由代理在策略范围内自行处理。",
    "Everything is checkable by anyone with the public keys.": "任何持有公钥的人都可以核查这一切。",
    "Enters at step 1. The registry contradicts the account at step 3; the card explains why.": "从第 1 步进入。第 3 步登记处否定了该账号；卡片会说明原因。",
    "A poisoned tool output swaps the account at execution. The executor's signed intent does not match.": "被投毒的工具输出在执行时调换了账号。执行器的签名意图与之不符。",
    "A decoy credential is touched: early-detection tripwire, freeze, re-verify, replan.": "诱饵凭据被触碰：早期预警绊线、冻结、重新验证、重新规划。",
    "Freeze, identify, re-verify through the registry, replan, ask. Then the genuine payment completes.": "冻结、识别、通过登记处重新验证、重新规划、询问。然后真实的付款完成。",
    "Zero money lost; every stop has a plain-language card.": "没有任何资金损失；每次拦截都有一张通俗易懂的卡片。",
    # advice + notes
    "Funds do not cover every obligation: ask the family for a top-up now (parent co-approval) and convert in stages on the cheapest on-time route.":
        "资金不足以覆盖全部应付款项：请现在向家里申请补充汇款（需家长共同批准），并在最便宜且能按时到账的路线上分批兑换。",
    "Scripted demo: fixed seed, fixed MOCK data, offline LLM, seeded DEMO keys. Replaying produces the same audit-chain head.":
        "脚本化演示：固定随机种子、固定模拟数据、离线模型、预置的演示密钥。重放会得到相同的审计链头部哈希。",
    "Live-replay demo: fixed seed, fixed MOCK data, seeded DEMO keys; the model's answers are replayed from a recorded fixture (no network). Anything not recorded falls back to offline and is labelled.":
        "实时回放演示：固定随机种子、固定模拟数据、预置的演示密钥；模型的回答来自已录制的样本回放（不联网）。未录制的部分会退回离线模式并加以标注。",
}
HEADLINES_ZH: list[tuple[str, str]] = [
    (r"Needs about INR (?P<inr>[\d,]+) for CNY (?P<cny>[\d,]+) of obligations; shortfall INR (?P<short>[\d,]+); the agent's plan is (?P<valid>valid|not yet valid) after (?P<n>\d+) proposal\(s\) \(saves CNY (?P<save>[\d,]+) vs a typical bank route\)",
     "总共 ¥{cny} 的应付款项约需 ₹{inr}；缺口 ₹{short}；代理的计划在 {n} 次提案后{valid}（比典型银行路线节省 ¥{save}）"),
    (r"Tuition (?P<st>\w+) - signed intent, proof pack (?P<pid>[\w-]+)", "学费{st}：已签名意图，证明包 {pid}"),
    (r"Top-up (?P<st>\w+) after parent approval \(shown to the parent in Tamil\)", "家长批准后，补充汇款{st}（以泰米尔语展示给家长）"),
    (r"Landlord's account change (?P<st>\w+) in (?P<m>\d+) simulated minutes - nothing wrongly blocked", "房东的账户变更{st}，用时 {m} 个模拟分钟：没有任何误拦"),
    (r"(?P<n>\d+) autonomous Tier-1 action\(s\) taken while the student did nothing", "学生什么也没做，代理自行执行了 {n} 项 1 级自主操作"),
    (r"(?P<n>\d+) proof packs; savings CNY (?P<s>[\d,.]+); audit chain intact", "{n} 个证明包；节省 ¥{s}；审计链完好"),
    (r"Forged invoice (?P<st>\w+): (?P<why>.*)", "伪造发票{st}：{why}"),
    (r"Payment instructions rewritten at execution: (?P<st>\w+) by the executor's intent check", "付款指令在执行时被改写：执行器的意图校验使其{st}"),
    (r"Hidden page injection reached for a canary: (?P<st>\w+); recovery plan ready", "页面中的隐藏注入触碰了诱饵：{st}；恢复方案已就绪"),
    (r"The hidden injection did not make the extractor reach for the canary here \((?P<st>\w+)\); the canary layer stays armed", "这里隐藏的注入没有让提取器去触碰诱饵（{st}）；诱饵层仍保持戒备"),
    (r"Student approved the recovery plan; genuine tuition payment (?P<st>\w+) to the registry-verified account", "学生批准了恢复方案；真实的学费付款已{st}，付至登记处验证过的账户"),
    (r"Money lost: CNY (?P<m>[\d,.]+); (?P<n>\d+) why-cards; audit chain intact", "损失资金：¥{m}；{n} 张原因卡片；审计链完好"),
]
_HEAD_C = [(re.compile(rx), t) for rx, t in HEADLINES_ZH]
_STATUS_ZH = {"paid": "已支付", "held": "已暂缓", "frozen": "已冻结", "rejected": "已拒绝", "valid": "有效", "not yet valid": "尚未有效",
              "needs_verification": "需要验证"}


def localize_text(s, lang):
    """Static demo text by exact match, then headline shapes, then the generic engine messages."""
    if not is_zh(lang) or not isinstance(s, str):
        return s
    if s in DEMO_TEXT_ZH:
        return DEMO_TEXT_ZH[s]
    for rx, tmpl in _HEAD_C:
        m = rx.fullmatch(s)
        if m:
            vals = {k: _STATUS_ZH.get(v, v) if k in ("st", "valid") else v for k, v in m.groupdict().items()}
            if "why" in vals:
                vals["why"] = tr(vals["why"], lang)
            return tmpl.format(**vals)
    return tr(s, lang)


def localize_demo_info(info: dict, lang: str) -> dict:
    if not is_zh(lang) or not isinstance(info, dict):
        return info
    info = dict(info)
    if isinstance(info.get("steps"), list):
        info["steps"] = [{**s, "title": localize_text(s["title"], lang), "narrative": localize_text(s["narrative"], lang)} for s in info["steps"]]
    return info


_KIND_ZH = {"extract": "提取", "risk": "风险评分", "plan": "规划", "other": "文本"}
_MISS_ZH = {"extract": "离线解析器", "risk": "启发式评分器", "plan": "确定性规划器", "other": "模板"}


def localize_ai(ai, lang):
    """The 'which model produced this step' line (agent/replay.ai_summary), rebuilt in Chinese from its own items."""
    if not is_zh(lang) or not isinstance(ai, dict):
        return ai
    from .replay import OFFLINE_LABEL, family, short_model
    ai = dict(ai)
    if ai.get("mode") != "live":
        ai["label"] = "离线解析器（确定性规则，不使用 AI 模型）" if ai.get("label") == OFFLINE_LABEL else ai.get("label")
        return ai
    parts = []
    for it in ai.get("items", []):
        name = _KIND_ZH.get(it["kind"], it["kind"])
        if it["source"] == "missing":
            lab = f"{_MISS_ZH.get(it['kind'], '离线')}（没有录制的回答；已退回离线）"
        else:
            how = f"回放自已录制的回答 {it.get('recorded')}" if it["source"] == "replayed" else "实时调用，刚刚录制"
            lab = f"{family(it.get('model'))} {short_model(it.get('model'))} — {how}"
        parts.append(f"{name}：{lab}" + (f"（{it['calls']} 次调用）" if it.get("calls", 1) > 1 else ""))
    ai["label"] = "；".join(parts) if parts else "这一步没有调用模型（只运行确定性代码）"
    return ai


def localize_demo_step(r: dict, lang: str) -> dict:
    """One step result (or the whole run summary) of the scripted demo, in `lang`."""
    if not is_zh(lang) or not isinstance(r, dict):
        return r
    r = dict(r)
    for k in ("title", "narrative", "headline", "note"):
        if isinstance(r.get(k), str):
            r[k] = localize_text(r[k], lang)
    if isinstance(r.get("steps"), list):                                  # run summary
        r["steps"] = [localize_demo_step(x, lang) for x in r["steps"]]
    if isinstance(r.get("ai"), dict):
        r["ai"] = localize_ai(r["ai"], lang)
    if isinstance(r.get("outcome"), dict):
        r["outcome"] = localize_outcome(r["outcome"], lang)
    if isinstance(r.get("agentic_plan"), dict):
        r["agentic_plan"] = localize_plan(r["agentic_plan"], lang)
    if isinstance(r.get("plan"), dict):
        p = dict(r["plan"])
        p["advice"] = localize_text(p.get("advice"), lang)
        p["triggers"] = localize_triggers(p.get("triggers"), lang)
        if isinstance(p.get("burn"), dict):
            p["burn"] = {**p["burn"], "basis": tr(p["burn"].get("basis", ""), lang)}
        r["plan"] = p
    if isinstance(r.get("savings_receipt"), dict):
        sr = dict(r["savings_receipt"])
        m = re.fullmatch(r"Oasis routes saved CNY ([\d,.]+) against a typical bank route \(MOCK rates\)\.", sr.get("text", ""))
        if m:
            sr["text"] = f"Oasis 的汇款路线相比典型银行路线共节省 ¥{m.group(1)}（模拟汇率）。"
        r["savings_receipt"] = sr
    if isinstance(r.get("cards"), list):
        r["cards"] = localize_cards(r["cards"], lang)
    if isinstance(r.get("recovery"), dict):
        pass
    return r


# ---------------------------------------------------------------------------------------------- savings / misc
def savings_text(total_saved_cny: float, lang: str, english: str) -> str:
    if is_zh(lang):
        return f"Oasis 的汇款路线相比典型银行路线共节省 ¥{total_saved_cny:,.2f}。"
    return english


SCENARIO_ZH = {
    "shortfall": ("到账缺口（演示学生）", "50 万卢比，而押金、房租和学费合计约 60.7 万卢比。",
                  "应当发现卢比缺口，并建议由家长汇款兑换，而不是让学费无着落。"),
    "tight_runway": ("资金紧张", "61.7 万卢比，对应最优路线下 60.7 万卢比的应付款项。",
                     "选择最便宜且能按时到账的路线；走昂贵的路线（或拆分）会让学费不够。"),
    "safe_quota_tuition": ("SAFE 额度内的学费", "一笔 ¥400,000 的课程费用，2027-01-20 到期，账户中有 640 万卢比。",
                           "2026 年内最多兑换 SAFE 额度以内的金额，其余从 1 月 1 日起兑换，赶在到期日之前到账。"),
    "late_scholarship": ("奖学金迟到", "一笔 ¥20,000 的津贴原定 2026-10-01 到账但尚未收到；账户中有 36.6 万卢比。",
                         "不要指望尚未到账的津贴；用其他方式填补缺口。"),
    "parent_tcs": ("家长汇款触及 TCS", "学生有 5 万卢比；家长今年已汇出 95 万卢比。",
                   "由家长作为汇款人，并提示一旦超过 100 万卢比（10 lakh）将触发的 TCS。"),
    "rate_target": ("需要保护的汇率目标", "63.5 万卢比；有一个待执行的目标，汇率达到 0.0700 时兑换 ¥20,000。",
                    "保留汇率目标所需的卢比，不要提前兑换。"),
    "multiple_obligations": ("五项应付款项", "十周内有宿舍费、押金、两期房租和学费；98 万卢比。",
                             "把兑换合并成批次，让固定费用尽可能少收几次。"),
    "urgent_deadline": ("紧急押金", "一笔 ¥6,000 的押金两天后到期，学费五周后到期。",
                        "3 天到账的路线无法支撑两天后到期的付款：这部分要选更快的路线。"),
}


def localize_scenarios(items, lang):
    if not is_zh(lang) or not isinstance(items, list):
        return items
    out = []
    for it in items:
        z = SCENARIO_ZH.get(it.get("id"))
        out.append({**it, "title": z[0], "description": z[1], "tests": z[2]} if z else it)
    return out


ERRORS_ZH: list[tuple[str, str]] = [
    (r"login required", "需要先登录"),
    (r"wrong role or passcode", "角色或口令不正确"),
    (r"too many failed logins; wait a minute", "登录失败次数过多，请等待一分钟"),
    (r"the (?P<r>\w+) role may not do this \(allowed: (?P<allowed>[\w, ]+)\)", "{r}角色无权执行此操作（允许的角色：{allowed}）"),
    (r"unknown pending id", "未知的待处理编号"),
    (r"this looks like a duplicate of a payment you already made: choose Pay again to start a deliberate second payment; it cannot be approved directly",
     "这看起来与您已付过的一笔款项重复：请选择“再次支付”来发起有意的第二笔付款；它不能被直接批准"),
    (r"this payment does not need the (?P<r>\w+)'s approval", "这笔付款不需要{r}的批准"),
    (r"this payment draft expired at (?P<na>\S+); submit the invoice again to get a fresh one to approve", "这份付款草案已于 {na} 过期；请重新提交发票以获得新的草案再批准"),
    (r"a signed approval is required: sign the payment draft with your device key", "需要签名批准：请用您的设备密钥对付款草案签名"),
    (r"approval signature does not verify for this exact payment", "批准签名与这笔付款不符，无法通过验证"),
    (r"this item is not a suspected duplicate", "此项并非疑似重复付款"),
    (r"no such plan", "没有这个计划"),
    (r"no such proof pack", "没有这个证明包"),
    (r"the parent can open only the proof packs of payments they approved", "家长只能打开自己批准过的付款所对应的证明包"),
    (r"attempt too large \(max (?P<a>\d+) bytes of text, (?P<b>\d+) of tool output\)", "尝试内容过大（文本最多 {a} 字节，工具输出最多 {b} 字节）"),
    (r"empty attempt", "尝试内容为空"),
    (r"rate limit: at most (?P<n>\d+) attempts per minute", "频率限制：每分钟最多 {n} 次尝试"),
    (r"request body too large", "请求内容过大"),
    (r"cross-origin request refused", "已拒绝跨源请求"),
    (r"not found", "未找到"),
    (r"rate and convert_cny must be positive", "汇率和兑换金额必须为正数"),
    (r"rate must be below 10 and convert_cny at most 10,000,000", "汇率必须低于 10，兑换金额最多为 10,000,000"),
    (r"no demo running; POST /api/demo/start first", "没有正在运行的演示；请先调用 POST /api/demo/start"),
    (r"unsupported language '(?P<l>.*)'; use one of (?P<ok>.+)", "不支持的语言“{l}”；请使用：{ok}"),
    (r"plan is (?P<s>\w+); only a valid proposal can be accepted", "计划当前状态为 {s}；只有有效的提案才能被接受"),
    (r"the plan no longer validates against the current Passport", "该计划已不再符合当前的财务护照"),
    (r"accept the plan first \(nothing runs from a proposal\)", "请先接受该计划（提案本身不会执行任何操作）"),
    (r"that step does not need the parent's consent", "该步骤不需要家长同意"),
    (r"consent signature does not verify for this conversion", "同意签名与这次兑换不符，无法通过验证"),
    (r"bad public key: (?P<e>.*)", "公钥无效：{e}"),
    (r"too many requests", "请求过于频繁"),
    (r"that is not valid JSON\.", "这不是有效的 JSON。"),
]
_ERR_C = [(re.compile(rx, re.S), t) for rx, t in ERRORS_ZH]


def tr_error(detail, lang):
    """HTTP error text for the user; machine behaviour (status codes) never changes."""
    if not is_zh(lang) or not isinstance(detail, str):
        return detail
    for rx, tmpl in _ERR_C:
        m = rx.fullmatch(detail.strip())
        if m:
            from .zh_messages import ROLE_ZH
            vals = {k: (ROLE_ZH.get(v, v) if k == "r" else "、".join(ROLE_ZH.get(x.strip(), x.strip()) for x in v.split(",")) if k == "allowed" else v)
                    for k, v in m.groupdict().items()}
            return tmpl.format(**vals)
    return detail
