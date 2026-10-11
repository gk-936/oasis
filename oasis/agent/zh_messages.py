"""Simplified Chinese (zh-CN) translation layer for the human-readable strings the Oasis engine produces in English.

The engine (policy, verification, corridor, executor, planner, forecast) keeps producing English `reasons`/`message`
text: that text is stored in the audit chain, in proof packs and in the benchmark, so it is never rewritten in place.
Instead this module translates it on the way OUT of the API, keyed by the message shape (the rule id/code selects the
table row): a regex over the English text with named groups, and a zh template that uses the same placeholders.

    tr("Amount would exceed this recipient's verified limit of CNY 5,000.", "zh")
    -> "金额将超过该收款人已验证的额度 ¥5,000。"

Rules of the layer:
  * a message with no translation is returned UNCHANGED (English) - nothing is marked broken;
  * numbers, dates, ids and rule codes are copied from the English text verbatim, never re-computed;
  * invoice text, payee names and legal/regulatory source quotes are never passed through here;
  * wording is machine-drafted and needs native-speaker review (see docs/i18n-glossary.md).
"""
from __future__ import annotations

import ast
import re
import string

ZH = "zh"

ROLE_ZH = {"student": "学生", "parent": "家长", "judge": "评审", "verification": "收款人验证",
           "risk_review": "文档之外的风险复核", "out_of_band_verification": "文档之外的确认",
           "duplicate_confirmation": "您明确选择“再次支付”", "corrected_cny_invoice": "更正后的人民币发票"}
PURPOSE_ZH = {"family_support": "家庭资助", "tuition": "学费", "rent": "房租", "deposit": "押金", "living": "生活费",
              "verification_test": "验证用小额测试付款"}
TYPE_ZH = {"university": "大学", "landlord": "房东", "family": "家人", "merchant": "商户", "wallet": "钱包", "student": "学生本人"}
LABEL_ZH = {  # agent/request_types.LABELS
    "a request to change who approves payments or the approval rules": "要求更改付款审批人或审批规则的请求",
    "a message asking to change where a payee is paid": "要求更改收款账户的消息",
    "a refund or reversal request": "退款或撤销付款的请求",
    "a payment demand from an authority that is not an obligation in the Passport": "来自某机构、且不属于财务护照中任何应付款项的付款要求",
}
LEVEL_ZH = {"verified_full": "已完全验证", "verified_low": "已验证（低额度）", "registry_checked": "已在登记处核验",
            "test_paid": "已测试付款", "unverified": "未验证", "rejected": "已拒绝", "needs_verification": "需要验证"}
ACTION_ZH = {"allow": "放行", "hold": "暂缓", "freeze": "冻结", "held": "暂缓", "frozen": "冻结", "rejected": "拒绝",
             "needs_verification": "需要验证",
             "executed": "已执行", "paid": "已支付"}
WORD_ZH = {"up": "上涨", "down": "下跌"}
_FILTERS = {"roles": ROLE_ZH, "purpose": PURPOSE_ZH, "ptype": TYPE_ZH, "who": ROLE_ZH, "what": LABEL_ZH, "level": LEVEL_ZH,
            "dir": WORD_ZH, "action": ACTION_ZH}


ROUTE_ZH = {"Typical bank SWIFT transfer": "典型银行 SWIFT 汇款", "Digital remitter A (INR→CNY)": "数字汇款平台 A（INR→CNY）",
            "Digital remitter B (INR→CNY)": "数字汇款平台 B（INR→CNY）", "Education payment specialist": "教育缴费专业服务商"}
CONTACT_ZH = {"the finance office's official portal inbox": "财务处官方门户的收件箱",
              "the phone number on the signed lease": "租约上签署的电话号码", "the carrier's official app": "运营商的官方应用",
              "the registry-listed channel": "登记处列出的渠道"}


def route_zh(text: str) -> str:
    for en, zh in ROUTE_ZH.items():
        text = text.replace(en, zh)
    return text


def _fix(name: str, value: str) -> str:
    if name in ("routes", "route", "name") and value:
        return route_zh(value)
    if name == "rest" and value and value.strip():         # trailing planner notes: several sentences, each translated on its own
        return "".join(tr(x, ZH) for x in re.split(r"(?<=\.)\s+(?=[A-Z])", value.strip()))
    if name == "basis" and value:                          # e.g. the rate basis nested inside a plan sentence
        return tr(value, ZH)
    table = _FILTERS.get(name)
    if table is None or value is None:
        return value
    if name == "roles":                                    # "student, parent" -> "学生、家长"
        return "、".join(table.get(x.strip(), x.strip()) for x in re.split(r",\s*", value) if x.strip())
    return table.get(value, value)


N = r"[\d,]+(?:\.\d+)?"      # an already formatted number, copied verbatim
# (code, english regex (full match), zh template with the same {placeholders}); first match wins.
RULES: list[tuple[str, str, str]] = [
    # ---- policy engine (trust/policy.py): reasons by rule id
    ("R01_canary", r"Canary tripped: (?P<kind>\S+) at (?P<where>.+)", "诱饵警报被触发：{kind}（位置：{where}）。"),
    ("R02_hard_limit", rf"Amount exceeds the hard limit of CNY (?P<limit>{N})\.", "金额超过 ¥{limit} 的硬性上限。"),
    ("R02_hard_limit", rf"Conversion exceeds the hard limit of CNY (?P<limit>{N})\.", "兑换金额超过 ¥{limit} 的硬性上限。"),
    ("R03_rejected_recipient", r"The registry contradicts this recipient's details\.", "登记处的记录与该收款人的信息不一致。"),
    ("R04_risk_freeze", rf"Risk score (?P<score>{N}) is above the freeze threshold\.", "风险评分 {score} 高于冻结阈值。"),
    ("R04b_test_payment", r"Registry-confirmed recipient; small verification test payment\.", "收款人已由登记处确认；这是一笔用于验证的小额测试付款。"),
    ("R04c_bad_test_payment", r"A test payment is only allowed to a registry-confirmed recipient, up to CNY 10\.",
     "测试付款只允许付给已由登记处确认的收款人，且不超过 ¥10。"),
    ("R15_currency_mismatch", r"The document demands (?P<cur>[A-Za-z]{3}), but this obligation is settled in CNY\. Oasis will not pay "
     r"a foreign-currency demand as if it were CNY\.", "文件要求以 {cur} 支付，但这笔应付款项以人民币结算。Oasis 不会把外币要求当作人民币来支付。"),
    ("R05_unverified", r"Recipient is not verified; the verification ramp must complete first\.", "收款人尚未验证；必须先完成分级验证流程。"),
    ("R17_duplicate_payment", r"Nothing was paid\. If you really mean to pay it a second time, choose Pay again; otherwise dismiss this\.",
     "尚未支付任何款项。如果您确实要再付一次，请选择“再次支付”；否则请忽略此项。"),
    ("R17_duplicate_payment", r"You asked to pay it again: this is a deliberate second payment and needs your signature\.",
     "您选择了再次支付：这是一笔有意的重复付款，需要您的签名。"),
    ("R17_duplicate_payment", r"You already paid this on (?P<when>[^,:]+?)(?:, proof (?P<proof>[\w-]+))?: it has the same invoice reference "
     r"\((?P<ref>[^)]+)\)\.", "您已在 {when} 支付过这笔款项（证明包 {proof}）：发票编号相同（{ref}）。"),
    ("R17_duplicate_payment", r"You already paid this on (?P<when>[^,:]+?)(?:, proof (?P<proof>[\w-]+))?: it is the same document\.",
     "您已在 {when} 支付过这笔款项（证明包 {proof}）：这是同一份文件。"),
    ("R17_duplicate_payment", r"You already paid this on (?P<when>[^,:]+?)(?:, proof (?P<proof>[\w-]+))?: it matches an obligation that is already paid\.",
     "您已在 {when} 支付过这笔款项（证明包 {proof}）：它对应的应付款项已经付清。"),
    ("R06_corridor", r"Purpose '(?P<purpose>[\w ]+)' does not fit payee type '(?P<ptype>[\w ]+)'\.", "用途“{purpose}”与收款人类型“{ptype}”不匹配。"),
    ("R06_corridor", r"The (?P<who>\w+) remitter's LRS limit would be exceeded this financial year\.", "本财年内，{who}作为汇款人将超出其 LRS（自由汇款计划）额度。"),
    ("R06_corridor", rf"TCS of INR (?P<tcs>{N}) would be collected \(recoverable as a tax credit\)\.", "将代扣 TCS（税收代扣）₹{tcs}，可作为税收抵免追回。"),
    ("R06_corridor", r"Approaching the INR 10 lakh TCS threshold for this remitter\.", "该汇款人即将达到 ₹10 lakh（100 万卢比）的 TCS 起征门槛。"),
    ("R06_corridor", rf"Conversions in (?P<y>\d{{4}}) would total INR (?P<tot>{N}), above the annual SAFE facilitation quota of INR "
     rf"(?P<q>{N}); stage it or prepare documents\.", "{y} 年的兑换总额将达 ₹{tot}，超过 SAFE（国家外汇管理局）年度便利化额度 ₹{q}；请分批办理或准备证明材料。"),
    ("R06_corridor", r"Report under education purpose code (?P<code>.+?) \(UNCONFIRMED: (?P<st>[^;]+); verify with the authorised dealer bank\)\.",
     "请按教育用途代码 {code} 申报（未经确认：{st}；请向授权外汇指定银行核实）。"),
    ("R06_corridor", r"(?P<n>\d+) payments to the same payee just under the (?P<label>\w+) within (?P<h>\d+)h look like splitting to dodge approval\.",
     "{h} 小时内向同一收款人支付了 {n} 笔刚好低于 {label} 的款项，疑似拆分付款以规避审批。"),
    ("R07_recipient_limit", rf"Amount would exceed this recipient's verified limit of CNY (?P<limit>{N})\.", "金额将超过该收款人已验证的额度 ¥{limit}。"),
    ("R08_risk_hold", rf"Risk score (?P<score>{N}) requires review outside this document: confirm with the payee through the "
     r"registry-verified contact, then re-submit the genuine invoice\. An approval cannot release this hold\.",
     "风险评分 {score} 需要在本文件之外进行复核：请通过登记处核实的联系方式向收款人确认，然后重新提交真实的发票。批准无法解除此项暂缓。"),
    ("R10_tier1_auto", r"Small recurring payment to a fully verified recipient\.", "向已完全验证的收款人支付的小额定期款项。"),
    ("R11_approval_required", r"Approval required from: (?P<roles>[\w, ]+)\.", "需要以下人员批准：{roles}。"),
    ("R11_approval_required", rf"Part payment of CNY (?P<part>{N}) against CNY (?P<rest>{N}) still owed: an instalment is never automatic\.",
     "部分付款 ¥{part}（尚欠 ¥{rest}）：分期付款从不自动执行。"),
    ("R11_approval_required", rf"Part payment of CNY (?P<part>{N}): an instalment is never automatic\.", "部分付款 ¥{part}：分期付款从不自动执行。"),
    ("R12_approved", r"All required approvals present; recipient verified; within limits\.", "所需批准齐全；收款人已验证；未超出额度。"),
    ("R13_tier1_rate_target", rf"Student-set rate target reached; conversion of CNY (?P<amt>{N}) is within the CNY (?P<lim>{N}) auto limit\.",
     "已达到学生设定的汇率目标；兑换 ¥{amt} 在 ¥{lim} 的自动额度之内。"),
    ("R14_conversion_approved", r"Conversion above the auto limit approved by the student\.", "超过自动额度的兑换已获学生批准。"),
    ("R14_conversion_approval", rf"Conversion of CNY (?P<amt>{N}) is above the CNY (?P<lim>{N}) auto limit\.", "兑换 ¥{amt} 超过 ¥{lim} 的自动额度。"),
    ("R16_out_of_band_verification", r"This looks like (?P<what>.+)\.", "这看起来像是：{what}。"),
    ("R16_out_of_band_verification", r"A document or message cannot change approvers, approval limits or a payee's bank details, and Oasis does not "
     r"act on refund or reversal requests found in a document\. Nothing in it was actioned\.",
     "文件或消息无法更改审批人、审批额度或收款人的银行信息，Oasis 也不会执行文件中的退款或撤销请求。其中的任何内容均未被执行。"),
    ("extract_low_confidence", r"Required payment fields could not be read confidently\.", "无法可靠地读取必需的付款字段。"),
    ("extract_low_confidence", r"Amount rejected: (?P<why>.+)\.", "金额被拒绝：{why}。"),
    # ---- verification ramp (trust/verification.py)
    ("verification", r"No registry credential for this identity \(name/ID unknown to the registry\)\.", "登记处没有该身份的凭证（登记处不认识此名称/编号）。"),
    ("verification", r"Registry identity does not match the claimed payee ID\.", "登记处的身份与所声称的收款人编号不一致。"),
    ("verification", r"Registry contradicts the account on the request - details on the request are treated as forgeable\.",
     "登记处与请求中的账号不一致：请求上的信息一律视为可能被伪造。"),
    ("verification", r"Account details changed - recipient reset to unverified and re-verified\.", "账户信息已变更：收款人被重置为未验证并重新验证。"),
    ("verification", r"Registry confirms the account; a small test payment is required before limits open\.", "登记处确认了该账户；开放额度之前需要先做一笔小额测试付款。"),
    ("verification", r"Test payment ignored: recipient is not at registry_checked\.", "测试付款已忽略：收款人尚未达到“已在登记处核验”级别。"),
    ("verification", rf"Test payment confirmed - low limit CNY (?P<limit>{N}) set\.", "测试付款已确认：已设定 ¥{limit} 的低额度。"),
    # ---- executor / signed intent
    ("executor", r"signature invalid", "签名无效"),
    ("executor", r"intent expired", "签名意图已过期"),
    ("executor", r"nonce already used \(replay\)", "随机数已被使用（重放）"),
    ("executor", r"(?P<f>\w+) differs from signed intent \((?P<a>.+) vs (?P<b>.+)\)", "{f} 与签名意图不一致（{a} 对 {b}）"),
    ("executor", r"approval by '?(?P<role>\w+)'? has no valid signature over this payment", "{role} 的批准没有针对这笔付款的有效签名"),
    ("executor", r"canary tripped: (?P<kind>\S+)", "诱饵警报被触发：{kind}"),
    ("executor", r"matches signed intent; policy allow", "与签名意图一致；策略放行"),
    # ---- risk-score evidence (agent/llm.heuristic_risk)
    ("risk", r"urgency/pressure language: (?P<words>.+)", "催促/施压措辞：{words}"),
    ("risk", r"document contains instructions addressed to the assistant", "文件中含有写给助手的指令"),
    ("risk", r"document tells the reader not to contact or verify with anyone", "文件要求读者不要联系或向任何人核实"),
    ("risk", r"payee name closely resembles known payee '(?P<name>.+)' but is not identical", "收款人名称与已知收款人“{name}”非常相似，但并不相同"),
    ("risk", r"payee name partly matches known payee '(?P<name>.+)' \(possible impersonation\)", "收款人名称与已知收款人“{name}”部分吻合（可能是冒充）"),
    ("risk", r"payee identity not found in the independent registry", "独立登记处中找不到该收款人的身份"),
    ("risk", r"account on the request contradicts the independent registry", "请求中的账号与独立登记处的记录相矛盾"),
    ("risk", r"bank details changed, but the independent registry confirms the new account \(it will be re-verified, not blocked\)",
     "银行信息已变更，但独立登记处确认了新账户（将重新验证，而不是直接拦截）"),
    ("risk", r"bank details differ from the account on file", "银行信息与档案中的账户不一致"),
    ("risk", rf"amount (?P<a>{N}) differs from the expected obligation (?P<b>{N})", "金额 {a} 与预期的应付款项 {b} 不一致"),
    ("risk", r"payee is new to this student", "该收款人对此学生而言是新的"),
    ("risk", rf"amount sits just under the INR (?P<thr>{N}) approval threshold", "金额恰好略低于 ₹{thr} 的审批门槛"),
    ("risk", r"(?P<n>\d+) similar payment\(s\) to the same payee in the last 72h \(possible splitting\)", "过去 72 小时内向同一收款人有 {n} 笔类似付款（可能是拆分付款）"),
    ("risk", r"invisible \(zero-width\) characters inside the account number", "账号中含有不可见（零宽）字符"),
    ("risk", r"full-width or non-ASCII digits in the account number", "账号中含有全角或非 ASCII 数字"),
    ("risk", r"look-alike \(non-ASCII\) letters in the account number", "账号中含有形似的（非 ASCII）字母"),
    # ---- forecast triggers (planning/forecast.py)
    ("trigger", rf"(?P<type>\w+) of CNY (?P<amt>{N}) due in (?P<days>-?\d+) days; projected funds cover only CNY (?P<avail>{N}) of CNY (?P<comm>{N}) committed\.",
     "{type} ¥{amt} 将在 {days} 天后到期；预计资金仅能覆盖已承诺的 ¥{comm} 中的 ¥{avail}。"),
    ("trigger", rf"INR→CNY mid-market moved (?P<dir>up|down) (?P<pct>{N})% over 7 days\.", "近 7 天内，INR→CNY 中间价{dir}了 {pct}%。"),
    ("trigger", rf"Only (?P<m>{N}) months of money left after obligations\.", "付清应付款项后，资金仅够维持 {m} 个月。"),
    ("trigger", rf"(?P<label>.+) \(CNY (?P<amt>{N})\) was expected on (?P<d>[\d-]+) and has not arrived\.", "{label}（¥{amt}）原定于 {d} 到账，但尚未收到。"),
    ("trigger", rf"Rate (?P<cur>{N}) reached your target (?P<t>{N}): convert CNY (?P<amt>{N})\.", "汇率 {cur} 已达到您的目标 {t}：可兑换 ¥{amt}。"),
    # ---- spending / forecast basis
    ("basis", r"student budget \+ labelled reference costs \(cold start\)", "学生预算 + 标注的参考成本（冷启动）"),
    ("basis", r"own spending pattern \(per-category average \+ damped trend\)", "本人的消费模式（各类别平均值 + 平滑趋势）"),
    ("basis", r"Need (?P<d>\d+) days / (?P<t>\d+) transactions to switch to your own pattern\.", "需要 {d} 天 / {t} 笔交易才能切换为本人的消费模式。"),
    # ---- agentic plan: "why this plan" (agent/planner.explain_plan)
    ("plan_why", rf"(?P<a>\d+) of (?P<b>\d+) obligations are paid on or before their due dates\.", "{b} 项应付款项中有 {a} 项会在到期日当天或之前付清。"),
    ("plan_why", rf"(?P<n>\d+) conversion\(s\) send INR (?P<inr>{N}) and deliver CNY (?P<cny>{N}); that is CNY (?P<more>{N}) more than the same INR "
     r"through a typical bank route \(MOCK rates\)\.", "共 {n} 次兑换，汇出 ₹{inr}，到账 ¥{cny}；比同样的卢比走典型银行路线多出 ¥{more}（模拟汇率）。"),
    ("plan_why", r"Routes: (?P<routes>.+?)\. Every route arrives before the payment it funds\.", "路线：{routes}。每条路线都会在其所支撑的付款之前到账。"),
    ("plan_why", r"No conversion is needed: the CNY already held covers every obligation\.", "无需兑换：已持有的人民币足以覆盖全部应付款项。"),
    ("plan_why", r"Conversions are split across two calendar years so each year stays inside the SAFE facilitation quota\.",
     "兑换被分到两个日历年内，使每一年都不超出 SAFE（国家外汇管理局）便利化额度。"),
    ("plan_why", r"The student's own INR is not enough, so part is proposed as a parent remittance\. It needs the parent's consent and counts against "
     r"the parent's LRS and TCS\.", "学生本人的卢比不足，因此部分金额建议由家长汇出。这需要家长同意，并计入家长的 LRS 额度和 TCS。"),
    ("plan_why", rf"TCS of INR (?P<tcs>{N}) would be collected; it is an advance tax credit, not a fee\.", "将代扣 TCS ₹{tcs}；这是预缴的税收抵免，不是手续费。"),
    ("plan_why", r"Payments above the Tier-1 limit wait for the student's approval and pass verification, signed intent, policy and the executor\.",
     "超过 1 级额度的付款会等待学生批准，并依次通过验证、签名意图、策略和执行器。"),
    ("plan_why", r"Rates are today's quote \((?P<basis>.+)\); Oasis does not predict exchange rates\.", "汇率采用今日报价（{basis}）；Oasis 不预测汇率。"),
    ("plan_why", r"today's mock mid-market rate (?P<r>[\d.]+) \(a quote, not a forecast\)", "今日模拟中间价 {r}（只是报价，不是预测）"),
    ("plan_why", r"today's live mid-market rate (?P<r>[\d.]+) \((?P<src>[^,]+), as of (?P<d>[\d-]+)(?P<stale>, STALE)?; route spreads and fees are mock; a quote, not a forecast\)",
     "今日实时中间价 {r}（{src}，截至 {d}{stale}；路线点差与费用为模拟数据；只是报价，不是预测）"),
    ("plan_rationale", rf"Pay (?P<n>\d+) obligation\(s\) (?P<d>\d+) days before each due date; fund the CNY shortfall of (?P<sf>{N}) with (?P<c>\d+) "
     r"conversion\(s\) on the cheapest route that arrives in time\.(?P<rest>.*)", "在每笔应付款项到期日前 {d} 天付清这 {n} 项；用 {c} 次兑换补足 ¥{sf} 的人民币缺口，选择最便宜且能按时到账的路线。{rest}"),
    ("plan_rationale", r"Pay (?P<n>\d+) obligation\(s\) (?P<d>\d+) days before each due date; the CNY already in the account covers everything, so no conversion "
     r"is needed\.(?P<rest>.*)", "在每笔应付款项到期日前 {d} 天付清这 {n} 项；账户中已有的人民币足以覆盖全部款项，因此无需兑换。{rest}"),
    ("plan_note", r"SAFE quota for (?P<y>\d{4}) is used up, so the rest waits for (?P<d>[\d-]+)\.", "{y} 年的 SAFE 额度已用完，因此其余部分顺延到 {d}。"),
    ("plan_note", rf"The student's own INR \(after keeping INR (?P<r>{N}) for rate targets\) covers INR (?P<stu>{N}); the parent would remit INR (?P<par>{N}), "
     r"which needs the parent's consent\.", "学生本人的卢比（为汇率目标保留 ₹{r} 之后）可覆盖 ₹{stu}；家长将汇出 ₹{par}，这需要家长同意。"),
    ("plan_note", rf"Staged: INR (?P<s>{N}) now \(the SAFE quota leaves INR (?P<room>{N}) this calendar year\), the rest from January\.",
     "分批办理：现在兑换 ₹{s}（今年 SAFE 额度还剩 ₹{room}），其余从 1 月起办理。"),
    ("R01_canary", r"canary tripwire fired during understanding", "在“理解”步骤触发了诱饵绊线"),
    # ---- plan validator warnings (planning/validator.py), by code
    ("frozen_excluded", r"(?P<id>[\w#]+) is frozen and is not part of this plan until recovery is approved\.", "{id} 已被冻结，在恢复方案获批之前不纳入本计划。"),
    ("safe_quota_near", rf"Conversions in (?P<y>\d{{4}}) reach (?P<p>\d+)% of the SAFE quota\.", "{y} 年的兑换已达到 SAFE 额度的 {p}%。"),
    ("tcs", rf"Step (?P<i>\d+): TCS of INR (?P<tcs>{N}) would be collected from the (?P<who>\w+) remitter \((?P<rate>\d+)% above (?P<thr>INR [\w. ]+?); "
     r"recoverable as a tax credit, not a fee\)\.", "第 {i} 步：将向{who}汇款人代扣 TCS ₹{tcs}（超过 {thr} 的部分按 {rate}% 计；可作为税收抵免追回，不是手续费）。"),
    ("tcs_near", r"Step (?P<i>\d+): the (?P<who>\w+) remitter is approaching the (?P<thr>INR [\w. ]+?) TCS threshold\.", "第 {i} 步：{who}汇款人即将达到 {thr} 的 TCS 起征门槛。"),
    ("parent_remitter", rf"Step (?P<i>\d+): INR (?P<inr>{N}) would be sent by the parent; it needs the parent's consent and counts against the parent's LRS/TCS\.",
     "第 {i} 步：将由家长汇出 ₹{inr}；需要家长同意，并计入家长的 LRS/TCS。"),
    ("small_conversion", rf"Step (?P<i>\d+): CNY (?P<d>{N}) delivered is below the CNY (?P<m>{N}) minimum worth converting \(fixed fees dominate\)\.",
     "第 {i} 步：到账 ¥{d} 低于值得兑换的最低金额 ¥{m}（固定费用占比过高）。"),
    ("approval_expected", rf"Step (?P<i>\d+): paying CNY (?P<amt>{N}) is above the Tier-1 limit; it will wait for the student's approval and passes verification, "
     r"signed intent, policy and executor like any payment\.", "第 {i} 步：支付 ¥{amt} 超过 1 级额度；将等待学生批准，并像其他付款一样通过验证、签名意图、策略和执行器。"),
    ("route_not_cheapest", rf"Step (?P<i>\d+): (?P<name>.+) would deliver CNY (?P<diff>{N}) more and still arrive on time\.", "第 {i} 步：{name}可多到账 ¥{diff}，且仍能按时到账。"),
    ("late_income_ignored", rf"(?P<label>.+) \(CNY (?P<amt>{N})\) was expected on (?P<d>[\d-]+) and has not arrived; the plan does not count on it\.",
     "{label}（¥{amt}）原定于 {d} 到账但尚未收到；本计划不依赖它。"),
    ("low_runway", rf"After the plan the student has about (?P<m>{N}) months of budget left \(alert below (?P<a>{N})\)\.", "按此计划执行后，学生的预算约可维持 {m} 个月（低于 {a} 个月将提醒）。"),
    # ---- plan validator errors (messages)
    ("bad_step", r"A plan needs a non-empty list of steps\.", "计划必须包含至少一个步骤。"),
    ("bad_date", r"Step date (?P<d>.+) is not a YYYY-MM-DD date\.", "步骤日期 {d} 不是 YYYY-MM-DD 格式。"),
    ("date_in_past", r"Step is dated (?P<d>[\d-]+), before today \((?P<t>[\d-]+)\)\.", "步骤日期 {d} 早于今天（{t}）。"),
    ("already_paid", r"(?P<id>[\w#]+) is already paid\.", "{id} 已经付清。"),
    ("obligation_frozen", r"(?P<id>[\w#]+) is frozen after a security stop; the student must approve the recovery plan first\.", "{id} 因安全拦截被冻结；学生必须先批准恢复方案。"),
    ("duplicate_payment", r"(?P<id>[\w#]+) is paid twice \(steps (?P<a>\d+) and (?P<b>\d+)\)\.", "{id} 被支付了两次（第 {a} 步和第 {b} 步）。"),
    ("payee_mismatch", r"(?P<id>[\w#]+) is owed to (?P<a>\S+), not (?P<b>\S+)\.", "{id} 应付给 {a}，而不是 {b}。"),
    ("amount_mismatch", rf"(?P<id>[\w#]+) still has CNY (?P<a>{N}) to pay; the step pays CNY (?P<b>{N})\.", "{id} 尚需支付 ¥{a}；该步骤支付 ¥{b}。"),
    ("late_payment", r"(?P<id>[\w#]+) is due (?P<due>[\d-]+); the step pays on (?P<d>[\d-]+)\.", "{id} 的到期日为 {due}；该步骤在 {d} 付款。"),
    ("obligation_unfunded", rf"(?P<id>[\w#]+) \((?P<type>\w+), CNY (?P<amt>{N}), due (?P<due>[\d-]+)\) has no pay step\.", "{id}（{type}，¥{amt}，到期日 {due}）没有对应的付款步骤。"),
    ("insufficient_inr", rf"Step (?P<i>\d+): the student has INR (?P<have>{N}) on (?P<d>[\d-]+); the conversion sends INR (?P<send>{N})\.",
     "第 {i} 步：学生在 {d} 只有 ₹{have}；该兑换需汇出 ₹{send}。"),
    ("route_too_slow", rf"Step (?P<i>\d+): CNY (?P<amt>{N}) is paid on (?P<d>[\d-]+) but the conversion that funds it arrives on (?P<arr>[\d-]+), after the payment date\.",
     "第 {i} 步：¥{amt} 在 {d} 付款，但为其提供资金的兑换在 {arr} 才到账，晚于付款日期。"),
    ("insufficient_cny", rf"Step (?P<i>\d+): only CNY (?P<avail>{N}) will be in the student's account on (?P<d>[\d-]+); (?P<id>[\w#]+) needs CNY (?P<amt>{N})\.",
     "第 {i} 步：学生账户在 {d} 只有 ¥{avail}；{id} 需要 ¥{amt}。"),
    ("lrs_exceeded", rf"Step (?P<i>\d+): the (?P<who>\w+) remitter's LRS limit \(INR (?P<lrs>{N})\) would be exceeded this financial year\.",
     "第 {i} 步：本财年内{who}汇款人将超出其 LRS 额度（₹{lrs}）。"),
    ("rate_target_reserve", rf"The student's pending rate target\(s\) need about INR (?P<r>{N}) to stay unconverted; the plan leaves INR (?P<l>{N})\.",
     "学生待执行的汇率目标需要保留约 ₹{r} 不兑换；该计划只留下 ₹{l}。"),
    ("safe_quota", rf"Step (?P<i>\d+): conversions dated in (?P<y>\d{{4}}) would total INR (?P<tot>{N}), above the SAFE facilitation quota of INR (?P<q>{N}) "
     r"\(USD 50,000 equivalent\)\.", "第 {i} 步：{y} 年的兑换总额将达 ₹{tot}，超过 SAFE 便利化额度 ₹{q}（约合 5 万美元）。"),
    # ---- chat / misc server sentences
]

# Suffix sentences appended to otherwise translatable messages (corridor.tcs_caveat).
_SUFFIXES: list[tuple[str, str]] = [
    (rf" The (?P<rate>\d+)% rate for this purpose is UNCONFIRMED/secondary-sourced \(status: (?P<st>[\w-]+)\): confirm it with the authorised dealer bank\.",
     "该用途适用的 {rate}% 税率未经确认或仅有二手来源（状态：{st}）：请向授权外汇指定银行核实。"),
]

# Hints that follow validator errors (kept short; anything not listed stays English).
HINTS: list[tuple[str, str]] = [
    (rf"Short by INR (?P<x>{N})\. Reduce it or fund the shortfall with a parent-remitted conversion \(remitter 'parent', needs the parent's consent\)\.",
     "缺口 ₹{x}。请减少金额，或用家长汇出的兑换来补足缺口（汇款人选“parent”，需要家长同意）。"),
    (rf"Convert at most INR (?P<room>{N}) in (?P<y>\d{{4}}) \(that includes INR (?P<b>{N}) already used\) and schedule the rest on or after (?P<d>[\d-]+), "
     r"early enough to arrive before the payment date\.", "{y} 年最多兑换 ₹{room}（已包含已用的 ₹{b}），其余安排在 {d} 或之后，并且要早到足以赶在付款日期之前。"),
    (r"Convert earlier or use a faster route \(check days in get_routes\)\.", "请更早兑换，或使用更快的路线（在 get_routes 中查看天数）。"),
    (rf"Short by CNY (?P<x>{N}): add or enlarge a conversion arriving on or before (?P<d>[\d-]+)\.", "缺口 ¥{x}：请增加或加大一笔在 {d} 当天或之前到账的兑换。"),
    (rf"Keep at least INR (?P<r>{N}) unconverted \(or fund the difference from the parent\)\.", "请至少保留 ₹{r} 不兑换（或由家长补足差额）。"),
    (r"Use (?P<d>[\d-]+) or later\.", "请使用 {d} 或之后的日期。"),
    (r"Set payee_id to (?P<id>\S+)\.", "请把 payee_id 设为 {id}。"),
    (r"Pay on or before (?P<d>[\d-]+)\.", "请在 {d} 当天或之前付款。"),
    (rf"Set amount_cny to (?P<a>{N})\.", "请把 amount_cny 设为 {a}。"),
    (r"Use the other remitter or reduce the amount\.", "请改用另一位汇款人，或减少金额。"),
    (r"Add a pay step for (?P<id>[\w#]+) on or before (?P<d>[\d-]+)\.", "请在 {d} 当天或之前为 {id} 添加付款步骤。"),
]

_COMPILED = [(c, re.compile(rx, re.S), t) for c, rx, t in RULES]
_SUFFIX_C = [(re.compile(rx), t) for rx, t in _SUFFIXES]
_HINTS_C = [(re.compile(rx), t) for rx, t in HINTS]
_FIELD = string.Formatter()


def placeholders(template: str) -> set[str]:
    return {f for _, f, _, _ in _FIELD.parse(template) if f}


def _render(template: str, m: re.Match) -> str:
    vals = {k: _fix(k, v if v is not None else "") for k, v in m.groupdict().items()}
    out = template.format(**{k: vals.get(k, "") for k in placeholders(template)})
    return out.replace("（证明包 ）", "").replace("（证明包 ）", "")


def tr(msg, lang: str = ZH):
    """Translate one English engine message; unchanged when lang is not zh or there is no translation."""
    if lang != ZH or not isinstance(msg, str) or not msg:
        return msg
    s = msg.strip()
    for rx, tmpl in _SUFFIX_C:                         # "<translatable>. The 20% rate ... UNCONFIRMED ..."
        sm = rx.search(msg)
        if sm and sm.end() == len(msg):
            head = tr(msg[:sm.start()], lang)
            if head != msg[:sm.start()]:
                return head + _render(tmpl, sm)
    for _code, rx, tmpl in _COMPILED:
        m = rx.fullmatch(s)
        if m:
            return _render(tmpl, m)
    return msg


def tr_hint(hint, lang: str = ZH):
    if lang != ZH or not isinstance(hint, str) or not hint:
        return hint
    s = hint.strip()
    for rx, tmpl in _HINTS_C:
        m = rx.fullmatch(s)
        if m:
            return _render(tmpl, m)
    return hint


def tr_list(msgs, lang: str = ZH):
    return [tr(x, lang) for x in msgs] if isinstance(msgs, list) else msgs


def is_translated(msg: str) -> bool:
    return tr(msg, ZH) != msg


# ---------------------------------------------------------------------------------------------- pipeline trace lines
_TRACE_PREFIX = {"Understand": "理解", "Plan": "规划", "Verify": "验证", "Commit": "决定", "Execute": "执行", "Prove": "证明"}
_TRACE: list[tuple[str, str]] = [
    (r"extracted payee=(?P<payee>.+?) amount=(?P<amt>\S+) purpose=(?P<purpose>\S+) \(untrusted\)", "读取到收款人={payee} 金额={amt} 用途={purpose}（不可信）"),
    (r"amount rejected - (?P<why>.+)", "金额被拒绝：{why}"),
    (r"label=(?P<label>\w+); risk=(?P<score>[\d.]+) (?P<ev>\[.*\])", "类别={label}；风险={score} {ev}"),
    (r"low-confidence extraction - asking the student to confirm fields", "读取置信度较低：请学生确认各字段"),
    (r"request type (?P<kind>\w+) - requires out-of-band verification", "请求类型 {kind}：需要在文档之外进行验证"),
    (r"test payment confirmed -> (?P<level>\w+)", "测试付款已确认 → {level}"),
    (r"(?P<level>\w+) (?P<lst>\[.*\])", "{level} {lst}"),
    (r"possible duplicate payment - (?P<why>.+)", "疑似重复付款：{why}"),
    (r"policy (?P<action>\w+) \((?P<rule>\w+)\) (?P<lst>\[.*\])", "策略{action}（{rule}）{lst}"),
    (r"approvals (?P<lst>\[.*\]) -> (?P<action>\w+) \((?P<rule>\w+)\)", "批准 {lst} → {action}（{rule}）"),
    (r"(?P<status>\w+) (?P<lst>\[.*\])", "{status} {lst}"),
    (r"\(agent holds credentials\)\: paid (?P<amt>\S+) to (?P<acct>\S+)", "（由代理持有凭据）已向 {acct} 支付 {amt}"),
    (r"paid CNY (?P<amt>{N})(?:; proof pack (?P<proof>[\w-]+))?".replace("{N}", N), "已支付 ¥{amt}（证明包 {proof}）"),
]
_TRACE_C = [(re.compile(rx, re.S), t) for rx, t in _TRACE]


def _tr_repr_list(s: str) -> str:
    try:
        items = ast.literal_eval(s)
        if isinstance(items, list):
            return "；".join(tr(str(x), ZH) for x in items) if items else "（无）"
    except (ValueError, SyntaxError):
        pass
    return s


def tr_trace(line: str, lang: str = ZH) -> str:
    """'Understand: label=...; risk=0.12 [...]' -> '理解: ...'. The step name prefix is translated, the rest by shape."""
    if lang != ZH or not isinstance(line, str):
        return line
    m = re.match(r"^(Understand|Plan|Verify|Commit|Execute|Prove)(?P<paren> \(agent holds credentials\))?:\s*(.*)$", line, re.S)
    if not m:
        return line
    head, body = _TRACE_PREFIX[m.group(1)], m.group(3)
    if m.group("paren"):
        body = "(agent holds credentials): " + body
    for rx, tmpl in _TRACE_C:
        mm = rx.fullmatch(body.strip())
        if mm:
            vals = {k: (v or "") for k, v in mm.groupdict().items()}
            if "lst" in vals:
                vals["lst"] = _tr_repr_list(vals["lst"])
            if "ev" in vals:
                vals["ev"] = _tr_repr_list(vals["ev"])
            if "why" in vals:
                vals["why"] = tr(vals["why"], ZH)
            for k in ("level", "action", "status"):
                if k in vals:
                    vals[k] = LEVEL_ZH.get(vals[k]) or ACTION_ZH.get(vals[k]) or vals[k]
            out = tmpl.format(**{k: vals.get(k, "") for k in placeholders(tmpl)})
            return f"{head}：{out}".replace("（证明包 ）", "")
    return f"{head}：{tr(body, ZH)}"
