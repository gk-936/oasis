"""Fixed Q&A corpus: answers that never need a model. Retrieval = the character n-gram index of robust.py over the phrasings below.
Every answer states only what the product does (MOCK data, registry-only payees, device-key signatures) and is at most 60 words."""
from __future__ import annotations

import re

from . import robust

FAQ_FLOOR = 0.60       # minimum cosine to the nearest stored phrasing (set on the DEV phrasings only)

# (id, [phrasings], answer, screen)
_E: list[tuple[str, list[str], str, str]] = [
    ("what_is_oasis", ["what is oasis", "who are you", "what are you", "tell me about oasis", "what is this app", "what is this assistant", "oasis kya hai", "oasis是什么"],
     "Oasis is a payment assistant for international students. I read your bills, draft payments to registered payees and wait for your device-key signature. Data here is MOCK demo data.", "Home"),
    ("what_can_you_do", ["what can you do", "what do you do", "what are your features", "what can i ask you", "list your abilities", "what are you able to do", "tum kya kar sakte ho", "你能做什么"],
     "I can show your balance and open bills, compare transfer routes, quote conversions, draft bill payments for your signature, set rate alerts and standing instructions, and explain holds. I never move money without your signature.", "Home"),
    ("is_it_safe", ["is it safe", "is oasis safe", "can i trust oasis", "is it secure", "is my money safe here", "is it safe to give you my bank details", "can i trust you", "is it safe to type my card number", "kya ye safe hai", "安全吗"],
     "Never type a card number, password or passcode into chat; I never need them. I only pay registered payees, and every payment needs your device-key signature on the exact draft. Nothing moves otherwise.", "Security"),
    ("not_a_scam", ["how do i know this isn't a scam", "how do i know this is not a scam", "is this a scam", "is this legit", "is this real or fake", "how can i tell if a payment request is fake", "how to spot a scam", "someone is asking me for money is it a scam", "kaise pata chalega scam hai", "这是骗局吗"],
     "Real universities, embassies, police and banks never ask you to pay a private account, buy gift cards or move money to a 'safe account'. I only pay payees in the registry, so a stranger's account is refused. Call the organisation on its official number.", "Security"),
    ("hacked", ["what happens if i get hacked", "what if my account is hacked", "what if someone hacks my account", "what if a hacker gets in", "what if my password leaks", "someone has my password", "what if i am hacked", "我被黑了怎么办"],
     "A hacker still cannot pay: payments need a signature from your device key, and money goes only to registered payees. Tell me and I will show recent activity; remove the device key from Security if you think it was exposed.", "Security"),
    ("phone_stolen", ["what if my phone is stolen", "my phone was stolen", "i lost my phone", "what if someone steals my phone", "phone stolen what do i do", "my device is lost", "手机丢了怎么办", "phone chori ho gaya"],
     "The device key signs payments, so tell the support contact and revoke that key from Security. Drafts waiting for a signature stay unpaid until a trusted device signs them.", "Security"),
    ("lose_device_key", ["what if i lose my device key", "i lost my device key", "device key missing", "i can't sign anymore", "how do i recover my key", "my key is gone", "reset my device key", "设备密钥丢了"],
     "Without the key nobody can approve a payment, so nothing is lost. Register a new device key from Security; old drafts need a fresh signature.", "Security"),
    ("what_can_go_wrong", ["what can go wrong with a payment", "what could go wrong", "what are the risks", "what are the risks of sending money abroad", "what if something goes wrong", "what are the dangers of a transfer", "kya galat ho sakta hai", "付款会出什么问题"],
     "A payment can be held for review, refused if the payee is not in the registry, arrive short after bank fees, or be delayed. I show the reason for a hold and how to fix it; FlightPath helps with short or late transfers.", "Payments"),
    ("payment_fails", ["what if a payment fails", "my payment failed", "what happens if a payment is rejected", "what if the payment does not go through", "payment declined what now", "payment error", "payment fail ho gaya", "付款失败了怎么办"],
     "Failed or held payments are shown with a reason. Nothing is taken twice. Ask 'why was it held' and I will explain; fix the cause and I will draft it again for your signature.", "Payments"),
    ("arrives_short", ["what if the money arrives short", "the money arrived short", "less money arrived than expected", "my transfer arrived with less", "fees were deducted from my transfer", "the amount received is lower", "paise kam aaye", "到账金额少了"],
     "Intermediary banks can deduct fees. FlightPath compares what was sent with what arrived and tells you what to ask the bank for, using a payment-trace request. Say 'my transfer arrived short'.", "FlightPath"),
    ("what_is_flightpath", ["what is flightpath", "explain flightpath", "tell me about flightpath", "what does flightpath do", "flightpath kya hai", "how does flightpath work", "what is the flight path feature", "flightpath是什么"],
     "FlightPath follows a cross-border transfer, shows where fees were taken and what to do when it is late or short. It is guidance only: it never resends or moves money.", "FlightPath"),
    ("reverse_payment", ["can i reverse a payment", "can i undo a payment", "can i take back a payment", "can i cancel a payment after it is sent", "how do i reverse a transfer", "can a payment be recalled", "payment wapas ho sakta hai", "能撤销付款吗"],
     "A draft can be cancelled any time before you sign. After it is sent, a bank recall is not guaranteed; I can explain the steps but cannot reverse money on my own.", "Payments"),
    ("refund", ["can i get a refund", "how do i get a refund", "i want my money back", "refund for a payment", "how do refunds work", "i paid twice what now", "refund kaise milega", "怎么退款"],
     "Refunds come from the payee, not from me. I can show your proof pack and explain what to send them. I never pull money back by myself.", "Proof"),
    ("how_long_payment", ["how long does a payment take", "how long until the university gets the money", "how many days does a payment take", "when will my payment arrive", "how fast is a payment", "payment time", "kitna time lagta hai", "付款多久到账"],
     "Domestic bill payments are usually the same day; cross-border transfers take 1 to 4 days depending on the route. The route comparison shows each estimate (demo values).", "Routes"),
    ("why_held", ["why was my payment held", "why is my payment on hold", "why did you hold my payment", "why is my draft waiting", "payment is pending why", "why was it held", "kyun rok diya", "为什么付款被暂缓"],
     "A payment is held when it needs your signature or a policy check flags it, for example a large amount or a new payee. Ask me 'why' right after and I will give the exact reason.", "Payments"),
    ("why_refused", ["why was my payment refused", "why did you refuse", "why was it rejected", "why can't you pay this", "why did you say no", "why was my request refused", "kyun mana kiya", "为什么被拒绝"],
     "Payments are refused when the payee is not in the registry, the text tries to change the rules, or a safety check fails. Nothing moves in those cases. Ask 'why' and I will name the reason.", "Payments"),
    ("what_is_draft", ["what is a draft", "what does draft mean", "what is a payment draft", "explain drafts", "draft kya hai", "what is a held draft", "what is the draft hash", "草稿是什么"],
     "A draft is a prepared payment: payee, amount and hash. It does nothing until your device key signs that exact draft.", "Payments"),
    ("what_is_signature", ["what is a signature", "what does signing mean", "why do i sign", "what am i signing", "how does signing work", "what is sign and approve", "signature kya hai", "什么是签名"],
     "Signing means your device key creates a cryptographic signature over the draft's exact details. Change anything and the signature fails, so only what you saw can be paid.", "Security"),
    ("what_is_device_key", ["what is a device key", "what is my device key", "explain the device key", "where is my device key stored", "device key kya hai", "what is a passkey here", "how is my key protected", "设备密钥是什么"],
     "The device key is a private key on your device that signs approvals. It never leaves the device and I never see it, so a role name or a chat message cannot approve a payment.", "Security"),
    ("why_sign", ["why do i have to sign", "why do you need my signature", "why can't you just pay", "why do i need to approve", "why is approval needed", "why not pay automatically", "signature kyun chahiye", "为什么要签名"],
     "Because the money is yours. A signature proves you saw the exact payee and amount. Only small, pre-agreed Tier 1 items under a signed standing instruction can run without a fresh signature.", "Security"),
    ("what_is_nonce", ["what is a nonce", "what is a one time number", "what does nonce mean", "why does each approval have a nonce", "explain nonce", "replay attack protection", "what stops an old approval being reused", "nonce kya hai"],
     "A nonce is a one-time number inside each approval. Once used it cannot be used again, so a copied approval cannot pay twice.", "Security"),
    ("what_are_tiers", ["what is tier 1", "what is tier 2", "what is tier 3", "what are the tiers", "explain tiers", "what do the tiers mean", "tier kya hai", "什么是第一级"],
     "Tier 1: small registry bills the agent may prepare inside your signed standing limit. Tier 2: needs your device-key signature. Tier 3: needs extra review or is never done by me.", "Security"),
    ("auto_limit", ["what is the auto limit", "what is the tier 1 limit", "how much can the agent pay alone", "what is the automatic limit", "what is the spending cap", "how much can you pay without asking", "auto limit kya hai", "自动额度是什么"],
     "The auto limit is the most the agent may pay by itself under a standing instruction you signed. Above it, or outside it, I always ask. It cannot be changed from chat.", "Security"),
    ("what_is_canary", ["what is a canary", "what is the canary", "what are canary tripwires", "what does canary mean", "what triggers a freeze", "canary kya hai", "what are tripwires", "金丝雀是什么"],
     "A canary is a hidden tripwire. If something touches it, for example an unregistered account, the system freezes and records an alert instead of paying.", "Security"),
    ("what_is_audit_log", ["what is the audit log", "what is the audit trail", "who can see the audit log", "what gets recorded", "is everything logged", "what is the hash chain", "audit log kya hai", "审计日志是什么"],
     "Every action is written to an append-only audit log where each entry includes the hash of the previous one, so edits are detectable. The agent cannot write to or alter it.", "Audit"),
    ("what_is_proof_pack", ["what is a proof pack", "what is a proof", "what is the payment proof", "how do i prove a payment", "show me proof of payment", "explain proof packs", "proof pack kya hai", "证明包是什么"],
     "A proof pack is a verifiable receipt for a completed payment with its signature and audit hashes. Anyone can verify it in the Proof tab without logging in.", "Proof"),
    ("what_is_trust_pass", ["what is a trust pass", "what is the trust pass", "explain trust pass", "can i show my landlord a trust pass", "trust pass kya hai", "what is a payment passport", "what does the trust pass show", "信任通行证是什么"],
     "The Trust Pass is a shareable record of your verified on-time payments. You choose who sees it. It is a payment record, not a credit score, and the data here is MOCK.", "Passport"),
    ("trust_pass_credit_score", ["is the trust pass a credit score", "is this a credit score", "will a bank accept my trust pass", "does this build my credit score", "is this my cibil score", "is my payment record official", "kya ye credit score hai", "这是信用分吗"],
     "No. It is not a credit score and no bank or credit bureau recognises it. It is a verifiable payment history you may choose to share. Data here is MOCK.", "Passport"),
    ("who_sees_record", ["who can see my record", "who can see my data", "who sees my payments", "is my record private", "can the university see my record", "who has access to my information", "mera record kaun dekh sakta hai", "谁能看到我的记录"],
     "Only you, unless you share it. Sharing creates a signed link that you control and can stop. Parents see requests you send them, nothing else.", "Passport"),
    ("how_share_record", ["how do i share my record", "how can i share my payment history", "how do i give my landlord my record", "how to export my record", "how do i send my trust pass", "share my record with a bank", "record kaise share karun", "怎么分享我的记录"],
     "Open the Passport, choose Share, and sign. You get a signed link or file for the one person you pick. Say 'share my record' and I will start it.", "Passport"),
    ("what_is_registry", ["what is the registry", "what is a payee registry", "what is the registry for", "what is a registered payee", "explain the registry", "registry kya hai", "who is in the registry", "登记簿是什么"],
     "The registry is the list of verified payees and their bank accounts. Money goes only to an account in this list, never to an account read from a message or invoice.", "Registry"),
    ("why_registry_only", ["why only registry accounts", "why can't i pay any account", "why can't i pay a new account", "why won't you pay this account", "why do you refuse unknown accounts", "why only registered payees", "kyun sirf registry", "为什么只能付登记账户"],
     "Scams change the account number. By paying only accounts already verified in the registry, a forged invoice or a pasted account cannot redirect your money.", "Registry"),
    ("add_payee", ["how do i add a payee", "how can i add a new payee", "how do i register a new landlord", "my landlord changed his account", "how to add a new account", "my landlord has a new account", "new payee kaise jodein", "怎么添加收款人"],
     "New payees are added and verified in the Registry screen, with a check against the payee's own records and a small test payment. Chat cannot add a payee.", "Registry"),
    ("payee_verification", ["what is payee verification", "how is a payee verified", "how do you verify a payee", "what does verified mean", "verification status", "who verifies the payee", "payee verify kaise hota hai", "收款人验证是什么"],
     "A payee is verified by comparing its details with an independent source and confirming with a test payment. I cannot change a verification status.", "Registry"),
    ("test_payment", ["what is a test payment", "why a small test payment", "what is a penny drop", "test payment kya hai", "do i have to do a test payment", "what is the micro payment for", "explain test transfer", "测试付款是什么"],
     "A test payment is a very small transfer to a new payee to prove the account is real and belongs to them before a full payment is allowed.", "Registry"),
    ("what_is_mock", ["what does mock mean", "is this mock data", "why does it say mock", "what is mock", "is the data simulated", "is this a simulation", "mock ka matlab", "模拟是什么意思"],
     "MOCK means simulated demo data: balances, rates, bills and credentials are made up for the demonstration and nothing real is claimed.", "Home"),
    ("real_money", ["is this real money", "is this real", "does it move real money", "am i paying real bills", "is any of this real", "is my money really moving", "kya ye asli paisa hai", "这是真钱吗"],
     "No. Everything here is a sandbox with MOCK data. No real bank, university or landlord receives anything.", "Home"),
    ("currencies", ["what currencies are supported", "which currencies do you support", "do you support euros", "do you support yen", "can i convert pounds", "which currencies can i hold", "kaun si currency chalti hai", "支持哪些货币"],
     "INR, CNY, USD, EUR, GBP and AUD. Other currencies such as CAD, SGD, JPY or crypto are not supported.", "Wallets"),
    ("what_is_lrs", ["what is lrs", "explain the liberalised remittance scheme", "what is the lrs limit", "lrs kya hai", "how does lrs work", "what is the lrs cap", "lrs limit kitna hai", "LRS是什么"],
     "LRS is India's Liberalised Remittance Scheme, which caps the foreign currency an Indian resident can send abroad per financial year. Exact caps change, so check the Limits screen and your bank.", "Limits"),
    ("what_is_tcs", ["what is tcs", "what is tax collected at source", "do my parents pay tax when sending money", "tcs kya hai", "is there tax on remittance", "tax on education remittance", "how does tcs work", "TCS是什么"],
     "TCS is tax collected at source by the bank on some remittances from India. Rates depend on purpose and amount and can be claimed back later. Check the Limits screen and your bank for the current rule.", "Limits"),
    ("education_limit", ["what is the education remittance limit", "is there a limit for tuition transfers", "education remittance rules", "how much can be sent for education", "tuition remittance limit", "limit for studying abroad", "padhai ke liye limit", "教育汇款额度"],
     "Education payments follow the same LRS framework with their own treatment; the Limits screen shows what applies in this demo. Your bank confirms the final rule.", "Limits"),
    ("parents_send", ["how much can my parents send", "how much money can my parents send me", "what is the yearly limit for my parents", "limit on parents sending money", "maximum my family can send", "mummy papa kitna bhej sakte hain", "annual limit for family remittance", "父母每年能汇多少"],
     "It depends on the remittance scheme and the purpose. The Limits screen shows the yearly quota in this demo and how much is used.", "Limits"),
    ("ask_parents", ["how do i ask my parents for money", "how do i request money from my family", "can you message my parents", "i need money from my dad", "ask my mom for funds", "parents se paise kaise maangu", "send a request to my parents", "怎么向父母要钱"],
     "Say 'ask my parents for money'. I prepare a request with the amount and reason; your parent approves it with their own device key. I do not send money myself.", "Parents"),
    ("what_is_swift", ["what is swift", "what is a swift transfer", "how does swift work", "swift kya hai", "what is an international wire", "what is a bank wire", "explain swift payments", "SWIFT是什么"],
     "SWIFT is the network banks use for international wires. Each bank on the path may take a fee, so the amount received can be lower than the amount sent.", "Routes"),
    ("bank_vs_app", ["what is the difference between a bank and a remittance app", "bank or app which is better", "bank transfer vs wise", "is a remittance app cheaper than a bank", "should i use my bank or an app", "bank ya app kaun sasta", "bank wire vs transfer app", "银行和汇款应用有什么区别"],
     "Banks wire through SWIFT with fixed fees and a wider spread. Specialist apps often cost less and are faster but have their own limits. The route comparison shows both for your amount (demo values).", "Routes"),
    ("mid_market", ["what is the mid-market rate", "what is the real exchange rate", "what is the market rate", "mid market rate kya hai", "what is the interbank rate", "what is the fair exchange rate", "explain mid-market", "中间价是什么"],
     "The mid-market rate is the midpoint between buy and sell prices on the interbank market. It is the fair benchmark: anything worse is the provider's markup.", "Rates"),
    ("what_is_markup", ["what is a markup", "what is the spread", "what is a hidden fee in an exchange rate", "how do banks make money on exchange", "markup kya hai", "what is exchange rate margin", "explain fx markup", "汇率差价是什么"],
     "The markup is the gap between the provider's rate and the mid-market rate. Ask me to check a quote and I will show it as a percentage.", "Rates"),
    ("what_is_rate_target", ["what is a rate target", "how does a rate alert work", "what is a rate alert", "tell me when the rate improves how", "explain rate targets", "rate target kya hai", "what is a limit order here", "汇率目标是什么"],
     "A rate target is a standing instruction: when the rate reaches your number I prepare the conversion for your signature. It has a cap and an expiry, and you can revoke it.", "Convert"),
    ("what_is_standing", ["what is a standing instruction", "what is a mandate", "what is autopay here", "what is a recurring payment", "explain standing instructions", "standing instruction kya hai", "how do monthly payments work", "常设指令是什么"],
     "A standing instruction lets the agent prepare a recurring bill payment inside a cap you signed. It stops at the first anomaly, expires, and you can revoke it.", "Convert"),
    ("stop_standing", ["how do i stop a standing instruction", "how do i cancel autopay", "stop my recurring payment", "remove the rate alert", "how do i revoke a mandate", "autopay band kaise karein", "turn off the monthly payment", "怎么停止定期付款"],
     "A standing instruction or rate target ends when you revoke it with your device key, from the Convert or Activity screen. Chat cannot silently remove it.", "Activity"),
    ("activity_feed", ["what is the activity feed", "where can i see what the agent did", "what has the agent done", "show agent activity", "what is the activity screen", "activity feed kya hai", "history of agent actions", "活动记录是什么"],
     "The Activity feed lists everything the agent did on its own or proposed, each tied to the audit log, so you can check or revoke it.", "Activity"),
    ("agent_alone", ["what does the agent do on its own", "what can the agent do without me", "what does the agent do automatically", "how autonomous are you", "what actions are automatic", "agent apne aap kya karta hai", "what do you do without asking", "代理自己会做什么"],
     "Inside a signed standing instruction it may prepare small registry bills and conversions up to your cap. Everything else waits for your signature, and every action is audited.", "Activity"),
    ("agent_never", ["what will the agent never do", "what can't you do", "what are your limits", "what is off limits for you", "what will you refuse to do", "agent kya nahi karega", "what can't the agent do", "代理绝不会做什么"],
     "I never pay an unregistered account, sign for you, change limits or verification, read secrets, or write the audit log. My risk score can only raise a concern, never lower one.", "Security"),
    ("spend_without_asking", ["can the agent spend my money without asking", "can you pay without my permission", "will you pay on your own", "can you take money from my account", "can you spend my money", "kya tum bina puche paisa kharch karoge", "do you pay things automatically", "代理能不经我同意花钱吗"],
     "Not outside a limit you signed. Without a signed standing instruction, every payment waits for your device-key signature.", "Security"),
    ("who_responsible", ["who is responsible if something goes wrong", "who is liable for mistakes", "who do i blame if a payment is wrong", "who covers a loss", "who is accountable", "zimmedar kaun hai", "what if the agent makes a mistake", "出了问题谁负责"],
     "The system is built so money moves only on your signed approval to a registered payee, and each step is audited, so mistakes are traceable. This is a demo; no real funds are at risk.", "Audit"),
    ("data_kept", ["what data do you keep", "what information do you store", "what do you remember about me", "how long do you keep my data", "is my data stored", "kya data rakhte ho", "what personal data is collected", "你们保存什么数据"],
     "Demo balances, bills, drafts and the audit log for the session, all MOCK. Chat text is not used to store secrets, and account numbers are shown masked.", "Privacy"),
    ("store_account_numbers", ["do you store my account numbers", "do you keep my bank account number", "is my account number saved", "do you save my card number", "where are account numbers kept", "account number store hota hai", "do you store payee numbers", "你们存我的账号吗"],
     "Payee accounts live only in the registry and are shown masked, for example ****0001. I never need your own card or account number.", "Privacy"),
    ("share_data", ["do you share my data", "do you sell my data", "who do you share my information with", "is my data shared with third parties", "is my data private", "kya data share karte ho", "do you give my data to anyone", "你们会分享我的数据吗"],
     "No. Your record is shared only when you sign a share to a person you pick. Demo data stays in the sandbox.", "Privacy"),
    ("who_made_you", ["who made you", "who built oasis", "who created you", "who is behind oasis", "which team made this", "tumhe kisne banaya", "who developed you", "谁做的你"],
     "Oasis was built by a student team for a fintech challenge. It is a demonstration, not a licensed service.", "Home"),
    ("how_to_use", ["how do i use this", "how does this work", "how do i get started", "show me how to use oasis", "tutorial", "kaise use karun", "give me a quick guide", "怎么使用"],
     "Type what you need: 'pay my rent', 'what do I owe', 'plan my semester', 'cheapest way to send 50000 rupees'. I show the details and, for payments, prepare a draft you sign.", "Home"),
    ("new_student", ["i am a new student where do i start", "i just landed what should i do first", "i'm new here what first", "first time here help me start", "new international student", "mai abhi pahuncha hoon kya karun", "what should i sort out first", "我刚到该先做什么"],
     "Start with: 1) see what you owe, 2) check your balance, 3) compare ways to move money from home, 4) pay tuition and rent by signing the drafts. Ask for any of these.", "Home"),
    ("chinese_support", ["do you support chinese", "can i talk in chinese", "do you speak chinese", "can you reply in mandarin", "chinese language option", "kya tum chinese bolte ho", "switch to chinese", "支持中文吗"],
     "Yes. Write in Chinese or switch the language in settings. Chinese text here is machine-translated.", "Settings"),
    ("hindi_support", ["do you support hindi", "can i talk in hindi", "do you speak hindi", "hindi mein baat kar sakte ho", "can you reply in tamil", "hindi language option", "do you understand hinglish", "支持印地语吗"],
     "Yes. Hindi and Tamil are available and were checked by the team. You can also write Hinglish.", "Settings"),
    ("gas_water_bill", ["can you pay my gas bill", "can you pay my water bill", "pay my council tax", "pay my parking fine", "can you pay my electricity bill", "gas ka bill bharna hai", "can you pay a utility", "能交燃气费吗"],
     "I can only pay bills that have a registered payee. For gas, water and similar utilities no payee exists in the registry, so I cannot pay them here. Ask me to list the bills I can pay.", "Registry"),
    ("send_to_friend", ["can you send money to a friend", "can i pay my friend", "send money to my cousin", "can i send money to someone new", "pay a person who is not a bill", "dost ko paisa bhej sakte ho", "can you transfer to another student", "能给朋友转账吗"],
     "Only to a payee in the registry. A new person must be added and verified there first; I will not send to an account typed in chat.", "Registry"),
    ("crypto", ["can you pay in crypto", "do you support bitcoin", "can i pay with usdt", "can you send crypto", "can i pay with a stablecoin", "bitcoin se pay kar sakte ho", "do you accept ethereum", "能用加密货币吗"],
     "No. I do not handle crypto or stablecoins. A request to pay a wallet address is a common scam sign, so I refuse it and nothing moves.", "Security"),
    ("gift_card", ["can you pay by gift card", "can i pay with gift cards", "someone asked me to pay with itunes cards", "pay a fine with gift cards", "do you accept gift cards", "gift card se pay kar sakte ho", "pay in steam cards", "能用礼品卡付款吗"],
     "No. Nobody legitimate - not a university, landlord, bank or government - asks to be paid in gift cards. That is a scam. I only pay registered payees.", "Security"),
    ("scope", ["what's the capital of france", "tell me a joke", "who won the match", "what is the weather", "write me a poem", "what is 2 plus 2", "sing a song", "recommend a movie"],
     "I help with student payments only: bills, balances, transfers and conversions. Try 'what do I owe', 'pay my rent' or 'cheapest way to send 50000 rupees'.", "Home"),
]

_INDEX: robust.Index | None = None


def entries() -> list[tuple[str, list[str], str, str]]:
    return _E


def _idx() -> robust.Index:
    global _INDEX
    if _INDEX is None:
        _INDEX = robust.Index({f"{e[0]}#{i}": [q] for e in _E for i, q in enumerate(e[1])})     # one class per phrasing: score = cosine to the nearest phrasing
    return _INDEX


def answer(text: str) -> tuple[str, str, float, str] | None:
    """(answer, screen, score, id) for the entry whose nearest phrasing is closest, if above the floor, else None."""
    if not text or not re.search(r"[A-Za-z]{3}|[一-鿿]{2}", text):
        return None                                       # digits or emoji alone match nothing
    ranked = _idx().scores(text)
    if not ranked or ranked[0][1] * 5 < FAQ_FLOOR:        # Index.scores divides the cosine by 5 (mean of 5 neighbours)
        return None
    by = {e[0]: e for e in _E}[ranked[0][0].split("#")[0]]
    return by[2], by[3], ranked[0][1] * 5, by[0]


def by_id(eid: str) -> tuple[str, str]:
    e = next(x for x in _E if x[0] == eid)
    return e[2], e[3]


_GUESS = (
    (r"owe|due|bill|pay|fee|rent|tuition|deadline", "what you owe or a payment", "I can list your open bills or draft a payment for your signature."),
    (r"rate|rupee|yuan|dollar|convert|exchange", "the exchange rate or a conversion", "I can show today's rate or quote a conversion."),
    (r"money|balance|account|wallet|funds|cash|afford|enough", "your money", "I can show your balance and whether it will last."),
    (r"send|transfer|remit|arrive|stuck|parent", "a transfer", "I can compare routes or help trace a late or short transfer."),
    (r"credit|record|history|landlord|bank", "your payment record", "I can show how your on-time payments build a shareable record."),
)


def hedge(text: str) -> str:
    """Never a dead end: name the best guess, give one sentence, list the four things to say."""
    t = text.lower()
    for pat, what, sent in _GUESS:
        if re.search(pat, t):
            return f"I think you're asking about {what}. {sent} If that's not it, tell me which: pay a bill, see your balance, see what you owe, or check the rate."
    return ("What do you need: pay a bill, see your balance, see what you owe, or check the rate? "
            "Try 'pay my rent' or 'what do I owe'.")
