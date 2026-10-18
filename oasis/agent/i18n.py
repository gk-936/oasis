"""Templated explanations in the parent's language (English, Tamil, Hindi, Simplified Chinese).

These are the offline path. When an LLM is available it may rewrite them, but the numbers must survive
(see `numbers_preserved`); otherwise the template is used. Wording should be reviewed by a native speaker
before real use.
"""
from __future__ import annotations
import re

LANGS = {"en": "English", "ta": "தமிழ் (Tamil)", "hi": "हिन्दी (Hindi)", "zh": "简体中文 (Chinese)"}
LANG_NAMES = {"en": "English", "ta": "Tamil", "hi": "Hindi", "zh": "Simplified Chinese"}

# Interface languages (the web UI and the server-originated text shown in it). English is the default and the official
# language of the competition; adding a language = a UI dictionary file, one registration line in frontend/src/i18n/index.js
# and its entry here. Parent-approval wording (LANGS above) is a separate, larger set.
UI_LANGS = ("en", "zh")
DEFAULT_UI_LANG = "en"


def ui_lang(value) -> str | None:
    """Normalise a language code ('zh', 'zh-CN', 'zh_Hans', 'en-US') to a supported UI code, or None if unsupported."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower().replace("_", "-")
    if not v:
        return None
    base = v.split("-", 1)[0]
    return base if base in UI_LANGS else None


def lang_from_accept(header: str | None) -> str | None:
    """The first supported language in an Accept-Language header (q-values respected), or None."""
    if not header:
        return None
    best: tuple[float, int, str] | None = None
    for i, part in enumerate(header.split(",")):
        bits = part.strip().split(";")
        code = ui_lang(bits[0])
        q = 1.0
        for b in bits[1:]:
            b = b.strip()
            if b.startswith("q="):
                try:
                    q = float(b[2:])
                except ValueError:
                    q = 0.0
        if code and q > 0 and (best is None or (q, -i) > (best[0], -best[1])):
            best = (q, i, code)
    return best[2] if best else None

PURPOSE = {
    "en": {"family_support": "family support", "tuition": "tuition", "rent": "rent", "deposit": "a deposit",
           "living": "living costs"},
    "ta": {"family_support": "குடும்பச் செலவு", "tuition": "கல்விக் கட்டணம்", "rent": "வாடகை",
           "deposit": "முன்பணம்", "living": "வாழ்க்கைச் செலவு"},
    "hi": {"family_support": "पारिवारिक खर्च", "tuition": "ट्यूशन फ़ीस", "rent": "किराया",
           "deposit": "जमानत राशि", "living": "रोज़मर्रा का खर्च"},
    "zh": {"family_support": "家庭资助", "tuition": "学费", "rent": "房租", "deposit": "押金", "living": "生活费"},
}

LEVEL = {
    "en": {"verified_full": "fully verified", "verified_low": "verified (low limit)", "registry_checked": "registry checked"},
    "ta": {"verified_full": "முழுமையாகச் சரிபார்க்கப்பட்டது", "verified_low": "சரிபார்க்கப்பட்டது (குறைந்த வரம்பு)",
           "registry_checked": "பதிவேட்டில் சரிபார்க்கப்பட்டது"},
    "hi": {"verified_full": "पूरी तरह सत्यापित", "verified_low": "सत्यापित (कम सीमा)",
           "registry_checked": "रजिस्ट्री से जाँचा गया"},
    "zh": {"verified_full": "已完全验证", "verified_low": "已验证（低额度）", "registry_checked": "已在登记处核验"},
}

LABELS = {
    "en": {"amount": "Amount", "recipient": "Recipient", "verified": "Recipient check", "why": "Why you are asked",
           "why_text": "Family transfers above the co-approval limit need a parent", "approve": "Approve",
           "decline": "Decline", "nomove": "No money moves until you approve."},
    "ta": {"amount": "தொகை", "recipient": "பெறுநர்", "verified": "பெறுநர் சரிபார்ப்பு", "why": "ஏன் உங்களிடம் கேட்கப்படுகிறது",
           "why_text": "வரம்புக்கு மேற்பட்ட குடும்பப் பரிமாற்றங்களுக்கு பெற்றோரின் ஒப்புதல் தேவை",
           "approve": "ஒப்புக்கொள்", "decline": "நிராகரி", "nomove": "நீங்கள் ஒப்புக்கொள்ளும் வரை எந்தப் பணமும் நகராது."},
    "hi": {"amount": "राशि", "recipient": "प्राप्तकर्ता", "verified": "प्राप्तकर्ता की जाँच", "why": "आपसे क्यों पूछा जा रहा है",
           "why_text": "सीमा से ऊपर के पारिवारिक ट्रांसफर के लिए माता-पिता की मंज़ूरी ज़रूरी है",
           "approve": "मंज़ूर करें", "decline": "अस्वीकार करें", "nomove": "आपकी मंज़ूरी के बिना कोई पैसा नहीं जाएगा।"},
    "zh": {"amount": "金额", "recipient": "收款人", "verified": "收款人核验", "why": "为什么需要您确认",
           "why_text": "超过共同批准限额的家庭汇款需要家长批准", "approve": "批准", "decline": "拒绝",
           "nomove": "在您批准之前，不会有任何资金转出。"},
}


def _n(x: float) -> str:
    return f"{x:,.0f}"


VERIFY_SENTENCE = {
    "en": {"verified_full": "The recipient is fully verified through the official registry.",
           "verified_low": "The recipient is verified only up to a low limit (CNY {limit}) and is not yet fully verified.",
           "registry_checked": "The recipient was found in the official registry but is not fully verified yet.",
           "none": "The recipient has NOT been verified."},
    "ta": {"verified_full": "இந்தப் பெறுநர் அதிகாரப்பூர்வ பதிவேட்டில் முழுமையாகச் சரிபார்க்கப்பட்டுள்ளார்.",
           "verified_low": "இந்தப் பெறுநர் குறைந்த வரம்புக்கு (¥{limit} வரை) மட்டுமே சரிபார்க்கப்பட்டுள்ளார்; இன்னும் முழுமையாகச் சரிபார்க்கப்படவில்லை.",
           "registry_checked": "இந்தப் பெறுநர் அதிகாரப்பூர்வ பதிவேட்டில் உள்ளார், ஆனால் இன்னும் முழுமையாகச் சரிபார்க்கப்படவில்லை.",
           "none": "இந்தப் பெறுநர் இன்னும் சரிபார்க்கப்படவில்லை."},
    "hi": {"verified_full": "प्राप्तकर्ता की पुष्टि आधिकारिक रजिस्ट्री से पूरी तरह हो चुकी है।",
           "verified_low": "प्राप्तकर्ता की पुष्टि केवल कम सीमा (¥{limit} तक) के लिए हुई है; पूरी तरह सत्यापन अभी नहीं हुआ है।",
           "registry_checked": "प्राप्तकर्ता आधिकारिक रजिस्ट्री में मिला है, पर अभी पूरी तरह सत्यापित नहीं है।",
           "none": "प्राप्तकर्ता का अभी सत्यापन नहीं हुआ है।"},
    "zh": {"verified_full": "该收款人已通过官方登记处完成全面验证。",
           "verified_low": "该收款人仅验证至低额度（¥{limit}），尚未完成全面验证。",
           "registry_checked": "已在官方登记处查到该收款人，但尚未完成全面验证。",
           "none": "尚未对该收款人进行验证。"},
}


def verification_sentence(ctx: dict, lang: str = "en") -> str:
    """What the parent is told about the recipient, taken from the actual verification level in the Passport."""
    lang = lang if lang in LANGS else "en"
    lvl = ctx.get("verification_level")
    key = lvl if lvl in ("verified_full", "verified_low", "registry_checked") else "none"
    return VERIFY_SENTENCE[lang][key].format(limit=_n(float(ctx.get("verification_limit_cny") or 0)))


def parent_approval(ctx: dict, lang: str = "en") -> str:
    lang = lang if lang in LANGS else "en"
    student = ctx.get("student", "您的孩子" if lang == "zh" else "Your child")
    inr, cny = float(ctx.get("amount_inr", 0)), ctx.get("amount_cny")
    payee = ctx.get("payee") or ("一位已验证的收款人" if lang == "zh" else "a verified recipient")
    purpose = PURPOSE[lang].get(ctx.get("purpose") or "family_support", ctx.get("purpose") or "")
    thr = _n(float(ctx.get("threshold_inr", 50000)))
    approx = f" (≈ ¥{_n(float(cny))})" if cny else ""
    approx_zh = f"（约 ¥{_n(float(cny))}）" if cny else ""
    if lang == "ta":
        return (f"{student} சார்பாக {payee} என்ற பெறுநருக்கு ₹{_n(inr)}{approx} அனுப்ப உங்கள் ஒப்புதல் கோரப்படுகிறது (நோக்கம்: {purpose}). "
                f"{verification_sentence(ctx, lang)} "
                f"₹{thr}க்கு மேற்பட்ட குடும்பப் பரிமாற்றங்களுக்கு பெற்றோரின் ஒப்புதல் அவசியம். "
                f"நீங்கள் ஒப்புக்கொள்ளாத வரை எந்தப் பணமும் அனுப்பப்படாது. தயவுசெய்து ஒப்புக்கொள்ளுங்கள் அல்லது நிராகரியுங்கள்.")
    if lang == "hi":
        return (f"{student} की ओर से {payee} को {purpose} के लिए ₹{_n(inr)}{approx} भेजने के लिए आपकी मंज़ूरी माँगी जा रही है। "
                f"{verification_sentence(ctx, lang)} "
                f"₹{thr} से अधिक के पारिवारिक ट्रांसफर के लिए माता-पिता की मंज़ूरी ज़रूरी है। "
                f"आपकी मंज़ूरी के बिना कोई पैसा नहीं भेजा जाएगा। कृपया मंज़ूर करें या अस्वीकार करें।")
    if lang == "zh":
        return (f"{student}请求您批准一笔汇款：向{payee}汇出₹{_n(inr)}{approx_zh}，用途：{purpose}。"
                f"{verification_sentence(ctx, lang)}"
                f"超过₹{thr}的家庭汇款需要家长共同批准。"
                f"在您批准之前，不会有任何资金转出。请选择批准或拒绝。")
    return (f"{student} wants to send INR {_n(inr)}{approx} for {purpose} to {payee}. {verification_sentence(ctx, lang)} "
            f"Family transfers above INR {thr} need a parent's approval. "
            f"No money moves until you approve. Please approve or decline.")


def parent_facts(ctx: dict, lang: str = "en") -> list[dict]:
    lang = lang if lang in LANGS else "en"
    L = LABELS[lang]
    lvl = LEVEL[lang].get(ctx.get("verification_level") or "", ctx.get("verification_level") or "-")
    facts = [{"label": L["amount"], "value": f"₹{_n(float(ctx.get('amount_inr', 0)))}"
              + ((f"（约 ¥{_n(float(ctx['amount_cny']))}）" if lang == "zh" else f" (≈ ¥{_n(float(ctx['amount_cny']))})")
                 if ctx.get("amount_cny") else "")},
             {"label": L["recipient"], "value": ctx.get("payee") or "-"},
             {"label": L["verified"], "value": lvl},
             {"label": L["why"], "value": L["why_text"]}]
    return facts


NEXT_ZH = {
    "R16_out_of_band_verification": "请通过登记处核实的联系方式亲自确认（不要使用文件中提供的任何联系方式），然后重新提交真实的发票。",
    "extract_low_confidence": "请确认付款详情。",
    "default": "我们会通过官方登记处重新核实，并在继续之前征求您的意见。",
}


def why_stopped(ctx: dict, lang: str = "en") -> str:
    amt, payee, rule = _n(float(ctx.get("amount", 0))), ctx.get("payee", "?"), ctx.get("rule", "?")
    if lang == "ta":
        return (f"{payee} க்கு ¥{amt} பணப்பரிமாற்றம் நிறுத்தப்பட்டது (விதி {rule}). எந்தப் பணமும் நகரவில்லை. "
                f"அடுத்து: அதிகாரப்பூர்வ பதிவேட்டின் மூலம் மீண்டும் சரிபார்த்து, தொடரும் முன் உங்களிடம் கேட்போம்.")
    if lang == "hi":
        return (f"{payee} को ¥{amt} का भुगतान रोका गया (नियम {rule})। कोई पैसा नहीं गया। "
                f"आगे: हम आधिकारिक रजिस्ट्री से दोबारा जाँच करेंगे और आगे बढ़ने से पहले आपसे पूछेंगे।")
    if lang == "zh":
        from .zh_messages import ACTION_ZH, tr
        action = ACTION_ZH.get(ctx.get("action"), ctx.get("action") or "拦截")
        reasons = "；".join(tr(r, "zh").rstrip("。.") for r in ctx.get("reasons", [])) or "暂无更多详情"
        nxt = ctx.get("next_zh") or NEXT_ZH.get(rule, NEXT_ZH["default"])
        return (f"这笔向{payee}支付 ¥{amt} 的款项已被{action}（规则 {rule}）。原因：{reasons}。"
                f"没有任何资金转出。下一步：{nxt}")
    return ""


# ---- why-card: what the evidence cannot establish, and the next step. Deterministic; shown beside the reasons, never part of the audited card.
UNCERTAINTY = {
    "unverified": ("whether this account really belongs to the payee has not been verified yet",
                   "尚未核实该账户是否真的属于收款方"),
    "registry_conflict": ("whether the document was altered or the payee changed banks; only the payee can confirm that through a channel you already know",
                          "无法确定文件是否被篡改，或收款方是否更换了银行；只有收款方本人通过您已知的渠道才能确认"),
    "score_estimate": ("the risk score is an estimate from warning signs, not proof of fraud",
                       "风险评分只是根据预警信号的估计，不是欺诈的证明"),
    "duplicate": ("whether the payee already received the first payment", "无法确定收款方是否已收到第一笔付款"),
    "amount_changed": ("whether the amount was changed on purpose (for example an instalment or a late fee)",
                       "无法确定金额变化是否有意为之（例如分期或滞纳金）"),
    "details_changed": ("whether the payee really changed banks", "无法确定收款方是否真的更换了银行"),
    "name_match": ("a name match on a public list can be a coincidence", "公开名单上的姓名匹配可能只是巧合"),
    "corridor": ("whether the limit or purpose rule applies to your situation; confirm with your bank",
                 "无法确定该额度或用途规则是否适用于您的情况；请向银行确认"),
    "currency": ("whether the payee accepts payment in CNY", "无法确定收款方是否接受人民币付款"),
    "low_confidence": ("some fields could not be read reliably from the document", "文件中的部分字段无法可靠读取"),
    "sender": ("who really sent the request cannot be established from the message itself", "仅凭消息本身无法确定请求的真实发送者"),
}
_RULE_UNC = (("R05", "unverified"), ("R03", "registry_conflict"), ("R04", "score_estimate"), ("R08", "score_estimate"), ("R17", "duplicate"),
             ("R06", "corridor"), ("R15", "currency"), ("R16", "sender"), ("extract_low_confidence", "low_confidence"))
_REASON_UNC = (("differs from the expected obligation", "amount_changed"), ("bank details differ", "details_changed"),
               ("account on the request contradicts", "registry_conflict"), ("sanctions", "name_match"), ("OFAC", "name_match"))
NEXT_STEP = {
    "held": ("Check the details and sign if they are right. Nothing moves until you do.", "请核对详情，确认无误后再签名。签名之前不会转出任何款项。"),
    "frozen": ("Verify the payee through a channel you already know. Nothing moves until the registry confirms.",
               "请通过您已知的渠道向收款方核实。登记册确认之前不会转出任何款项。"),
}


def card_uncertainty(rule: str, reasons: list[str]) -> list[str]:
    """English statements of what the evidence cannot establish, from the rule that fired and the wording of the reasons (at most 3)."""
    codes: list[str] = []
    for prefix, code in _RULE_UNC:
        if (rule or "").startswith(prefix) and code not in codes:
            codes.append(code)
    for needle, code in _REASON_UNC:
        if any(needle in str(r) for r in reasons) and code not in codes:
            codes.append(code)
    return [UNCERTAINTY[c][0] for c in codes[:3]]


def card_uncertainty_zh(items: list[str]) -> list[str]:
    zh = {en: z for en, z in UNCERTAINTY.values()}
    return [zh.get(x, x) for x in items]


def card_next_step(action: str, nxt: str | None, lang: str = "en") -> str:
    if nxt:
        return nxt
    en, zh = NEXT_STEP["held" if action == "held" else "frozen"]       # only a held draft can be signed; stopped ones are verified first
    return zh if lang == "zh" else en


_NUM = re.compile(r"\d[\d,]*")


def numbers_preserved(source: str, rewritten: str) -> bool:
    """An LLM rewrite is accepted only if every number in the template appears unchanged in it."""
    want = {m.group().replace(",", "") for m in _NUM.finditer(source)}
    have = {m.group().replace(",", "") for m in _NUM.finditer(rewritten)}
    return want <= have


def no_new_numbers(source: str, rewritten: str) -> bool:
    """...and it may not add a number the template did not have (a model must not invent a figure, a date or a count)."""
    want = {m.group().replace(",", "") for m in _NUM.finditer(source)}
    have = {m.group().replace(",", "") for m in _NUM.finditer(rewritten)}
    return have <= want


# Markdown, bullet or numbered lists, rules, and a chatty preface ("Here's a rewrite ...") do not belong in a message shown to a student.
_NOT_PLAIN = re.compile(r"\*\*|^\s*(?:\d+[.)]|[-*\u2022])\s|^#{1,6}\s|^-{3,}\s*$|^\s*(?:here(?:'|\u2019)s|here is|sure[,!. ]|certainly)", re.I | re.M)


def plain_rewrite(rewritten: str) -> bool:
    return not _NOT_PLAIN.search(rewritten or "")
