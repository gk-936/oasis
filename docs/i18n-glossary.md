# Translation glossary (English / 简体中文)

English is the default and the competition's official language. The Chinese below is **machine-drafted and needs native-speaker review** before real use (the Tamil and Hindi parent text was checked by the team). Keep this list in step with `frontend/src/i18n/zh.js`, `oasis/agent/zh_messages.py` and `oasis/agent/i18n.py`.

| English | 简体中文 | Note |
|---|---|---|
| remittance / transfer | 汇款 | cross-border: 跨境汇款 |
| tuition | 学费 | |
| deposit | 押金 | |
| rent | 房租 | |
| living costs | 生活费 | |
| family support / top-up | 家庭资助 / 补充汇款 | |
| payee / recipient | 收款人 | |
| verified (recipient) | 已验证 | levels: 已完全验证, 已验证（低额度）, 已在登记处核验 |
| registry | 登记处 | the verified-payee registry |
| held / pending approval | 暂缓 / 待批准 | status `held` = 暂缓 |
| frozen | 冻结 | |
| rejected | 已拒绝 | |
| paid | 已支付 | |
| proof pack | 证明包 | |
| audit chain / log | 审计日志 | chain integrity: 完好 / 已中断 |
| signed intent | 签名意图 | |
| device key | 设备密钥 | Ed25519 stays Latin |
| parent co-approval | 家长共同批准 | |
| why-card | 原因卡片 | title "这笔款项为何被拦截？" |
| sandbox | 沙盒 | |
| mock / simulated | 模拟 | tag text 模拟 |
| canary / decoy | 诱饵 | tripwire = 绊线 |
| policy | 策略 | |
| risk score | 风险评分 | never "the decision" |
| Passport (Student Financial Passport) | 财务护照 | |
| red team | 红队 | |
| Tier-1 | 1 级 | digits kept so figures survive the number check |
| runway | 可维持的月数 | |
| route | 汇款路线 | |
| corridor (rules) | 跨境通道（规则） | |

Acronyms stay Latin with a gloss on first use: LRS（自由汇款计划）, TCS（税收代扣）, SAFE（国家外汇管理局）, ECB.

## Stays English by design

Invoice text and sample payloads, payee and person names, legal and regulatory source quotes, rule ids (R01-R19), machine codes, hashes, key ids, endpoint names, tool-call JSON in the planner trace, the generated benchmark reports (Numbers tab, shown with a note), and the recovery draft message to a third party when a model wrote it. Chinese appears next to them, never instead of them.

## Formats

Rupees keep Indian digit grouping (₹12,34,567) in both languages; yuan use standard grouping (¥1,234,567). Dates read as 2026年11月15日 in Chinese and 15 Nov 2026 in English.
