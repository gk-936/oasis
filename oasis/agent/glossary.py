"""Fixed, code-written answers for product and concept questions the router left `unknown` (the offline answer-only floor).
Every number comes from the passport rules passed in; nothing here reads a credential, creates a draft or moves money."""
from __future__ import annotations

import re

_T = (
    (r"\bswift\b|\bbic\b", "SWIFT is the bank-to-bank messaging network behind a typical international wire. It usually costs more and takes longer than a remittance app because several banks take a fee on the way; ask 'bank or app' to see the numbers for your amount.",
     "SWIFT 是银行之间的国际电汇报文网络，通常比汇款应用更贵、更慢，因为沿途多家银行会收费。说“银行还是应用”可以看到按您的金额算出的对比。"),
    (r"\bnonce\b", "A nonce is a one-time number inside a signed payment intent. The executor accepts each nonce once, so a captured approval cannot be replayed.",
     "Nonce 是已签名付款意图里的一次性数字。执行器每个 nonce 只接受一次，所以截获的批准无法重放。"),
    (r"\bmock\b", "MOCK means simulated: the rails, rates, balances and registry here are a sandbox, not real money, real banks or a real credit record.",
     "MOCK 表示模拟：这里的通道、汇率、余额和登记册都是沙盒，不是真钱、真银行，也不是真实的信用记录。"),
    (r"\bflight ?path\b", "FlightPath follows a cross-border transfer after it leaves: it flags late, short or rejected arrivals and proposes a top-up path. It never resends a payment on its own.",
     "FlightPath 在跨境汇款发出后继续跟踪：标出延迟、少收或被退回，并给出补差额的办法。它从不自动重发付款。"),
    (r"\bwhat currenc\w+|\bwhich currenc\w+|\bcurrencies (?:do|can) you\b|\bsupported currenc", "The wallet holds INR, CNY, USD, EUR, GBP and AUD (MOCK balances). Chat can quote any supported pair; INR to CNY inside your auto limit can be confirmed in chat.",
     "钱包支持 INR、CNY、USD、EUR、GBP 和 AUD（MOCK 余额）。聊天里可以给任何支持币种对报价；自动额度内的 INR→CNY 可以在聊天里确认。"),
    (r"\bwho (?:made|built|created|developed) you\b|\bwho are you\b", "I'm Oasis, a payments assistant for international students in a MOCK sandbox. I propose and explain; only your device-key signature releases money.",
     "我是 Oasis，面向留学生的付款助手（MOCK 沙盒）。我负责提议和解释；只有您用设备密钥签名，款项才会转出。"),
    (r"\b(?:rate target|rate alert)s?\b.*\b(?:work|mean|is|how)\b|\bhow (?:does|do) (?:the |a )?rate (?:target|alert)", "A rate target is a standing instruction: 'convert 3000 when the rate reaches 0.075'. When the rate hits it, an own-balance conversion inside your Tier-1 limit runs on its own and is audited; anything larger waits for your signature.",
     "汇率目标是一条长期指令，例如“汇率到 0.075 时兑换 3000”。到达目标时，自动额度内的自有余额兑换会自动执行并留痕；更大的金额要等您签名。"),
    (r"\b(?:limit|cap|maximum)\b.*\b(?:automatic|auto)\b.*\bconver|\b(?:automatic|auto)\b.*\bconver\w*\b.*\b(?:limit|cap|maximum)\b", "AUTO_LIMIT", None),
    (r"\bhow (?:do|can) i (?:add|register|set up) (?:a )?(?:new )?payee\b|\badd (?:a )?(?:new )?payee\b", "New payees are added only through the registry: the payee is verified there (out of band) before I can pay them. I never create a payee from a chat message or use an account number from one.",
     "新收款方只能通过登记册添加：先在那里完成核验，我才能付款。我不会根据聊天消息创建收款方，也不会使用消息里的账号。"),
    (r"\bhow (?:do|can|should) i use (?:this|oasis|it|the app)\b", "Start with 'plan my semester' or 'pay my tuition'. I draft payments to registry payees, you sign each one with your device key, and I keep a proof you can share. Ask 'what can you do?' for the full list.",
     "可以从“规划我的学期”或“交学费”开始。我起草付给登记收款方的付款，每一笔由您用设备密钥签名，并保留可分享的证明。问“你能做什么”看完整列表。"),
)
_RX = [(re.compile(a, re.I | re.S), en, zh) for a, en, zh in _T]


def answer(message: str, rules, lang: str = "en") -> str | None:
    """The fixed answer for a concept question, or None. `rules` is the passport's Rules (for the auto-conversion limit)."""
    for rx, en, zh in _RX:
        if rx.search(message):
            if en == "AUTO_LIMIT":
                lim = rules.tier1_auto_convert_cny
                return (f"自动兑换的上限是每笔 ¥{lim:,.0f}（自有余额之间）；超过的要在“兑换”页面或经您签名。" if lang == "zh"
                        else f"Automatic own-balance conversions are capped at CNY {lim:,.0f} each (your Tier-1 limit); larger ones need the Convert screen and your signature.")
            return zh if lang == "zh" else en
    return None
