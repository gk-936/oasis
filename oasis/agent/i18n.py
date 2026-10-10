"""Templated explanations in the parent's language (English, Tamil, Hindi).

These are the offline path. When an LLM is available it may rewrite them, but the numbers must survive
(see `numbers_preserved`); otherwise the template is used. Wording should be reviewed by a native speaker
before real use.
"""
from __future__ import annotations
import re

LANGS = {"en": "English", "ta": "தமிழ் (Tamil)", "hi": "हिन्दी (Hindi)"}
LANG_NAMES = {"en": "English", "ta": "Tamil", "hi": "Hindi"}

PURPOSE = {
    "en": {"family_support": "family support", "tuition": "tuition", "rent": "rent", "deposit": "a deposit",
           "living": "living costs"},
    "ta": {"family_support": "குடும்பச் செலவு", "tuition": "கல்விக் கட்டணம்", "rent": "வாடகை",
           "deposit": "முன்பணம்", "living": "வாழ்க்கைச் செலவு"},
    "hi": {"family_support": "पारिवारिक खर्च", "tuition": "ट्यूशन फ़ीस", "rent": "किराया",
           "deposit": "जमानत राशि", "living": "रोज़मर्रा का खर्च"},
}

LEVEL = {
    "en": {"verified_full": "fully verified", "verified_low": "verified (low limit)", "registry_checked": "registry checked"},
    "ta": {"verified_full": "முழுமையாகச் சரிபார்க்கப்பட்டது", "verified_low": "சரிபார்க்கப்பட்டது (குறைந்த வரம்பு)",
           "registry_checked": "பதிவேட்டில் சரிபார்க்கப்பட்டது"},
    "hi": {"verified_full": "पूरी तरह सत्यापित", "verified_low": "सत्यापित (कम सीमा)",
           "registry_checked": "रजिस्ट्री से जाँचा गया"},
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
}


def _n(x: float) -> str:
    return f"{x:,.0f}"


def parent_approval(ctx: dict, lang: str = "en") -> str:
    lang = lang if lang in LANGS else "en"
    student = ctx.get("student", "Your child")
    inr, cny = float(ctx.get("amount_inr", 0)), ctx.get("amount_cny")
    payee = ctx.get("payee") or "a verified recipient"
    purpose = PURPOSE[lang].get(ctx.get("purpose") or "family_support", ctx.get("purpose") or "")
    thr = _n(float(ctx.get("threshold_inr", 50000)))
    approx = f" (≈ ¥{_n(float(cny))})" if cny else ""
    if lang == "ta":
        return (f"{student} சார்பாக {payee} என்ற பெறுநருக்கு ₹{_n(inr)}{approx} அனுப்ப உங்கள் ஒப்புதல் கோரப்படுகிறது (நோக்கம்: {purpose}). "
                f"இந்தப் பெறுநர் அதிகாரப்பூர்வ பதிவேட்டில் சரிபார்க்கப்பட்டுள்ளார். "
                f"₹{thr}க்கு மேற்பட்ட குடும்பப் பரிமாற்றங்களுக்கு பெற்றோரின் ஒப்புதல் அவசியம். "
                f"நீங்கள் ஒப்புக்கொள்ளாத வரை எந்தப் பணமும் அனுப்பப்படாது. தயவுசெய்து ஒப்புக்கொள்ளுங்கள் அல்லது நிராகரியுங்கள்.")
    if lang == "hi":
        return (f"{student} की ओर से {payee} को {purpose} के लिए ₹{_n(inr)}{approx} भेजने के लिए आपकी मंज़ूरी माँगी जा रही है। "
                f"प्राप्तकर्ता की पुष्टि आधिकारिक रजिस्ट्री से हो चुकी है। "
                f"₹{thr} से अधिक के पारिवारिक ट्रांसफर के लिए माता-पिता की मंज़ूरी ज़रूरी है। "
                f"आपकी मंज़ूरी के बिना कोई पैसा नहीं भेजा जाएगा। कृपया मंज़ूर करें या अस्वीकार करें।")
    return (f"{student} wants to send INR {_n(inr)}{approx} for {purpose} to {payee}. The recipient is verified "
            f"through the official registry. Family transfers above INR {thr} need a parent's approval. "
            f"No money moves until you approve. Please approve or decline.")


def parent_facts(ctx: dict, lang: str = "en") -> list[dict]:
    lang = lang if lang in LANGS else "en"
    L = LABELS[lang]
    lvl = LEVEL[lang].get(ctx.get("verification_level") or "", ctx.get("verification_level") or "-")
    facts = [{"label": L["amount"], "value": f"₹{_n(float(ctx.get('amount_inr', 0)))}"
              + (f" (≈ ¥{_n(float(ctx['amount_cny']))})" if ctx.get("amount_cny") else "")},
             {"label": L["recipient"], "value": ctx.get("payee") or "-"},
             {"label": L["verified"], "value": lvl},
             {"label": L["why"], "value": L["why_text"]}]
    return facts


def why_stopped(ctx: dict, lang: str = "en") -> str:
    amt, payee, rule = _n(float(ctx.get("amount", 0))), ctx.get("payee", "?"), ctx.get("rule", "?")
    if lang == "ta":
        return (f"{payee} க்கு ¥{amt} பணப்பரிமாற்றம் நிறுத்தப்பட்டது (விதி {rule}). எந்தப் பணமும் நகரவில்லை. "
                f"அடுத்து: அதிகாரப்பூர்வ பதிவேட்டின் மூலம் மீண்டும் சரிபார்த்து, தொடரும் முன் உங்களிடம் கேட்போம்.")
    if lang == "hi":
        return (f"{payee} को ¥{amt} का भुगतान रोका गया (नियम {rule})। कोई पैसा नहीं गया। "
                f"आगे: हम आधिकारिक रजिस्ट्री से दोबारा जाँच करेंगे और आगे बढ़ने से पहले आपसे पूछेंगे।")
    return ""


_NUM = re.compile(r"\d[\d,]*")


def numbers_preserved(source: str, rewritten: str) -> bool:
    """An LLM rewrite is accepted only if every number in the template appears unchanged in it."""
    want = {m.group().replace(",", "") for m in _NUM.finditer(source)}
    have = {m.group().replace(",", "") for m in _NUM.finditer(rewritten)}
    return want <= have
