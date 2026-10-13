"""Interface languages (English default, Simplified Chinese): the UI dictionaries, the server-side Chinese text, the saved
student language and the access rules around it. Hermetic: in-memory sessions, offline LLM, a fake model client, no network."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from auth_helpers import new_client
from oasis.agent import i18n, localize, zh_messages
from oasis.agent.llm import LiveLLM, explain_template

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
I18N_DIR = SRC / "i18n"
PAIR = re.compile(r'^\s*("(?:[^"\\]|\\.)*"):\s*("(?:[^"\\]|\\.)*"),?\s*$')
PLACEHOLDER = re.compile(r"\{(\w+)\}")
TUITION = ("INVOICE\nPayee: University X Finance Office\nPayee ID: payee_univ_x\nAccount: 6228480000001234\n"
           "Amount: CNY 30,000\nPurpose: tuition\nDue: 2026-11-15")
FORGED = TUITION.replace("6228480000001234", "6228480000009999") + "\nURGENT: our bank details changed. Pay within 24 hours."
ZH = {"X-Oasis-Lang": "zh"}
CJK = re.compile(r"[一-鿿]")


def load(lang: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (I18N_DIR / f"{lang}.js").read_text(encoding="utf-8").splitlines():
        m = PAIR.match(line)
        if m:
            k = json.loads(m.group(1))
            assert k not in out, f"duplicate key {k} in {lang}.js"
            out[k] = json.loads(m.group(2))
    return out


EN, ZHD = load("en"), load("zh")


# ============================================================================================== UI dictionaries
def test_dictionaries_are_not_trivially_small_and_parse():
    assert len(EN) > 600 and len(ZHD) > 600


def test_en_and_zh_have_exactly_the_same_keys():
    assert set(EN) == set(ZHD), (sorted(set(EN) ^ set(ZHD))[:10])


def test_same_placeholders_and_marks_per_key():
    for k in EN:
        assert set(PLACEHOLDER.findall(EN[k])) == set(PLACEHOLDER.findall(ZHD[k])), k
        assert EN[k].count("**") == ZHD[k].count("**"), f"bold marks differ in {k}"
        assert EN[k].count("`") == ZHD[k].count("`"), f"code marks differ in {k}"


def test_no_empty_strings_and_zh_really_is_chinese():
    for k in EN:
        assert EN[k].strip() and ZHD[k].strip(), k
    # a value that is byte-identical to English must be a deliberate identifier / number, not a forgotten translation
    same = [k for k in EN if EN[k] == ZHD[k] and CJK.search(ZHD[k]) is None]
    allowed = {"misc.period", "misc.semicolon", "parent.approx", "rate.src.MOCK", "num.min"}
    suspicious = [k for k in same if k not in allowed and re.search(r"[A-Za-z]{4,}", ZHD[k])]
    assert suspicious == [], suspicious


def test_plural_keys_come_in_pairs():
    for d in (EN, ZHD):
        ones = {k[:-4] for k in d if k.endswith(".one")}
        others = {k[:-6] for k in d if k.endswith(".other")}
        assert ones == others, ones ^ others


def _source_files():
    return [f for f in SRC.rglob("*") if f.suffix in (".js", ".jsx") and f.parent != I18N_DIR]


USED = re.compile(r"(?<![\w.$])(?:t|R|tp|has)\(\s*([\"'])([\w.\-/+]+)\1")
TL = re.compile(r"\btl\(\s*\"([\w.]+)\"")
MSG_KEY = re.compile(r"\bk:\s*\"([\w.]+)\"")


def _used_keys():
    keys, prefixes = set(), set()
    for f in _source_files():
        s = f.read_text(encoding="utf-8")
        keys |= {m.group(2) for m in USED.finditer(s)} | {m.group(1) for m in MSG_KEY.finditer(s)}
        prefixes |= {m.group(1) for m in TL.finditer(s)}
    return keys, prefixes


def test_every_key_used_in_the_source_exists():
    keys, _ = _used_keys()
    assert len(keys) > 350                                  # the scan really found the usages
    missing = sorted(k for k in keys if k not in EN and f"{k}.other" not in EN)
    assert missing == [], missing


def test_every_dynamic_key_family_is_covered():
    """t(`prefix.${value}`) and tl(prefix, value) cannot be scanned literally, so the value sets are enumerated here."""
    from oasis.passport.models import Level
    from oasis.planning import spending
    from oasis.market.live_rates import SOURCE_LABELS
    ui = (SRC / "ui.jsx").read_text(encoding="utf-8")
    tone = set(re.findall(r'"(\w+)"', ui[ui.index("const TONE"):ui.index("export const toneOf")]))
    audit = set()
    for py in (ROOT / "oasis").rglob("*.py"):
        audit |= set(re.findall(r'audit\.append\(\s*"(\w+)"', py.read_text(encoding="utf-8")))
    want = {
        "status": tone | {"partially_paid", "test_paid", "declined"},
        "audit": audit,
        "level": {lv.value for lv in Level} | {"needs_verification"},
        "cat": set(spending.CATEGORIES),
        "rate.src": set(SOURCE_LABELS),
        "role": {"student", "parent", "judge"},
        "action": {"allow", "hold", "freeze"},
        "run": {"legit", "attack"},
        "label": {"matches_known", "new_or_changed", "stop"},
        "purpose": {"family_support", "tuition", "rent", "deposit", "living", "verification_test"},
        "type": {"tuition", "rent", "deposit", "living", "family_support"},
        "ptype": {"university", "landlord", "family", "merchant", "wallet", "student"},
        "cfg": {"baseline", "+verification", "+intents+policy", "full"},
        "conf": {"high", "medium-high", "medium", "low-medium", "n/a"},
        "pipe": {"understand", "plan", "verify", "commit", "execute", "prove"},
        "tab": {"demo", "chat", "passport", "parent", "redteam", "breakit", "proof", "numbers", "flightpath"},\n        "req": {"risk_review", "out_of_band_verification", "duplicate_confirmation", "corrected_cny_invoice", "verification"},
        "rr.check": {"signature", "key_pinned", "record_hash", "summary_consistent", "on_time_consistent", "proofs_checked"},
        "rules.status": {"confirmed-primary", "researched-secondary", "unconfirmed"},
        "rate.mode": {"live", "stale", "mock"},
        "role.desc": set(),
    }
    for prefix, values in want.items():
        for v in values:
            assert f"{prefix}.{v}" in EN, f"{prefix}.{v}"
    for r in ("student", "parent", "judge"):
        assert f"role.{r}.desc" in EN
    from oasis.trust import corridor
    for rule in corridor.rules_public()["rules"]:
        assert f"rule.{rule['id']}" in EN, rule["id"]
    _, prefixes = _used_keys()
    assert prefixes <= set(want) | {"role"}, prefixes - set(want)


def test_server_sentences_in_srv_keys_match_the_server_exactly():
    from oasis.api.main import MOCK_NOTE
    from oasis.market.live_rates import FEES_NOTE
    from oasis.mock.rates import ROUTES
    from oasis.proof.reliability import BANDS, CAVEATS, TOP_BAND
    from oasis.trust import corridor
    assert EN["srv.mock_note"] == MOCK_NOTE and EN["srv.fees_note"] == FEES_NOTE
    assert EN["srv.corridor_disclaimer"] == corridor.rules_public()["disclaimer"]
    for i, c in enumerate(CAVEATS):
        assert EN[f"srv.caveat.{i}"] == c
    assert [EN[f"srv.band.{i}"] for i in range(4)] == [b[1] for b in BANDS] and EN["srv.band.4"] == TOP_BAND
    for r in ROUTES:
        assert EN[f"srv.{r.id}"] == r.name, r.id
    from oasis.agent.replay import OFFLINE_LABEL  # noqa: F401  (the label is translated server-side)
    assert ZHD["srv.mock_note"].startswith("模拟")


def test_registry_has_one_line_per_language():
    idx = (I18N_DIR / "index.js").read_text(encoding="utf-8")
    codes = re.findall(r"^\s*(\w+): \{ name:", idx, re.M)
    assert codes == ["en", "zh"] and set(i18n.UI_LANGS) == set(codes)           # the server whitelist matches the registry
    assert 'DEFAULT_LANG = "en"' in idx and "localStorage" in idx and "try {" in idx


def test_amounts_are_formatted_with_indian_grouping_in_both_languages():
    ui = (SRC / "ui.jsx").read_text(encoding="utf-8")
    assert re.search(r'export const inr = .*toLocaleString\("en-IN"', ui)          # INR keeps Indian digit grouping everywhere
    assert re.search(r"export const cny = .*toLocaleString\(locale\(\)", ui)        # CNY follows the active locale (standard grouping)


# ============================================================================================== server-side Chinese
def test_ui_lang_and_accept_language_helpers():
    assert i18n.ui_lang("zh-CN") == "zh" and i18n.ui_lang("zh_Hans") == "zh" and i18n.ui_lang("EN-us") == "en"
    assert i18n.ui_lang("ta") is None and i18n.ui_lang("xx") is None and i18n.ui_lang("") is None and i18n.ui_lang(None) is None
    assert i18n.lang_from_accept("en;q=0.5, zh-CN,zh;q=0.9") == "zh"
    assert i18n.lang_from_accept("en-US,en;q=0.9,zh;q=0.1") == "en"
    assert i18n.lang_from_accept("fr, de;q=0.8") is None and i18n.lang_from_accept(None) is None


def test_every_translation_rule_is_well_formed():
    for code, rx, tmpl in zh_messages.RULES:
        groups = set(re.compile(rx).groupindex)
        used = zh_messages.placeholders(tmpl)
        assert used <= groups, (code, used - groups)                     # no placeholder without a capture
    for rx, tmpl in zh_messages.HINTS:
        assert zh_messages.placeholders(tmpl) <= set(re.compile(rx).groupindex), rx
    for rx, tmpl in localize.ERRORS_ZH:
        assert zh_messages.placeholders(tmpl) <= set(re.compile(rx).groupindex), rx


# English engine messages (one per shape) -> the Chinese keeps every number
SAMPLES = [
    "Canary tripped: bank_api_token at understand", "Amount exceeds the hard limit of CNY 200,000.",
    "Conversion exceeds the hard limit of CNY 200,000.", "The registry contradicts this recipient's details.",
    "Risk score 0.91 is above the freeze threshold.", "Recipient is not verified; the verification ramp must complete first.",
    "The document demands USD, but this obligation is settled in CNY. Oasis will not pay a foreign-currency demand as if it were CNY.",
    "Amount would exceed this recipient's verified limit of CNY 5,000.",
    "Risk score 0.62 requires review outside this document: confirm with the payee through the registry-verified contact, then re-submit "
    "the genuine invoice. An approval cannot release this hold.",
    "Approval required from: student, parent.", "Part payment of CNY 1,000.00 against CNY 6,000.00 still owed: an instalment is never automatic.",
    "All required approvals present; recipient verified; within limits.", "Small recurring payment to a fully verified recipient.",
    "Student-set rate target reached; conversion of CNY 2,000 is within the CNY 5,000 auto limit.",
    "Conversion of CNY 9,000 is above the CNY 5,000 auto limit.",
    "You already paid this on 2026-10-12, proof int_0001: it has the same invoice reference (INV-77).",
    "You already paid this on 2026-10-12, proof int_0001: it is the same document.",
    "Nothing was paid. If you really mean to pay it a second time, choose Pay again; otherwise dismiss this.",
    "Purpose 'rent' does not fit payee type 'university'.", "The student remitter's LRS limit would be exceeded this financial year.",
    "TCS of INR 12,000 would be collected (recoverable as a tax credit).",
    "TCS of INR 12,000 would be collected (recoverable as a tax credit). The 20% rate for this purpose is UNCONFIRMED/secondary-sourced "
    "(status: researched-secondary): confirm it with the authorised dealer bank.",
    "Conversions in 2026 would total INR 4,500,000, above the annual SAFE facilitation quota of INR 4,400,000; stage it or prepare documents.",
    "3 payments to the same payee just under the parent_coapproval_above_inr within 24h look like splitting to dodge approval.",
    "This looks like a refund or reversal request.",
    "No registry credential for this identity (name/ID unknown to the registry).", "Registry identity does not match the claimed payee ID.",
    "Registry contradicts the account on the request - details on the request are treated as forgeable.",
    "Account details changed - recipient reset to unverified and re-verified.",
    "Registry confirms the account; a small test payment is required before limits open.",
    "Test payment confirmed - low limit CNY 5,000 set.", "signature invalid", "intent expired", "nonce already used (replay)",
    "amount differs from signed intent (30000.0 vs 100.0)", "urgency/pressure language: urgent, within 24 hours",
    "payee name closely resembles known payee 'University X Finance Office' but is not identical",
    "amount 31,000 differs from the expected obligation 30,000", "amount sits just under the INR 50,000 approval threshold",
    "2 similar payment(s) to the same payee in the last 72h (possible splitting)",
    "INR→CNY mid-market moved up 1.10% over 7 days.", "Only 0.4 months of money left after obligations.",
    "tuition of CNY 30,000 due in 12 days; projected funds cover only CNY 10,000 of CNY 36,000 committed.",
    "Rate 0.0705 reached your target 0.0700: convert CNY 2,000.",
    "3 of 3 obligations are paid on or before their due dates.",
    "2 conversion(s) send INR 605,542 and deliver CNY 42,001; that is CNY 1,653 more than the same INR through a typical bank route (MOCK rates).",
    "Routes: Education payment specialist. Every route arrives before the payment it funds.",
    "TCS of INR 20,000 would be collected; it is an advance tax credit, not a fee.",
    "Rates are today's quote (today's mock mid-market rate 0.069964 (a quote, not a forecast)); Oasis does not predict exchange rates.",
    "Step 2: the student has INR 100 on 2026-10-20; the conversion sends INR 200.",
    "Step 1: only CNY 5,000 will be in the student's account on 2026-11-01; obl_rent_1 needs CNY 6,000.",
]


def test_samples_translate_and_keep_every_number():
    for src in SAMPLES:
        out = zh_messages.tr(src, "zh")
        assert out != src and CJK.search(out), f"not translated: {src}"
        assert i18n.numbers_preserved(src, out), (src, out)
        assert zh_messages.tr(src, "en") == src                                   # English is never touched


def test_untranslated_message_falls_back_to_english_unchanged():
    msg = "Some brand-new engine sentence 42 that has no translation yet."
    assert zh_messages.tr(msg, "zh") == msg and zh_messages.tr_list([msg, 7], "zh") == [msg, 7]
    assert zh_messages.tr_trace("garbage line", "zh") == "garbage line"
    assert localize.tr_error("no idea what this is", "zh") == "no idea what this is"


def test_zh_parent_approval_includes_amounts_labels_and_verification():
    ctx = {"student": "Arjun", "amount_inr": 94331, "amount_cny": 8000, "purpose": "family_support", "payee": "Arjun (own CNY account)",
           "verification_level": "verified_low", "verification_limit_cny": 4000, "threshold_inr": 50000}
    t = i18n.parent_approval(ctx, "zh")
    assert "94,331" in t and "8,000" in t and "50,000" in t and "4,000" in t and CJK.search(t)
    assert i18n.numbers_preserved(t, t) and not i18n.numbers_preserved(t, "无数字")
    facts = i18n.parent_facts(ctx, "zh")
    assert facts[0]["value"].startswith("₹94,331") and "8,000" in facts[0]["value"]
    assert i18n.LABELS["zh"]["approve"] == "批准" and i18n.LABELS["zh"]["decline"] == "拒绝" and "zh" in i18n.LANGS
    for lang in ("en", "ta", "hi"):                                                # the existing languages are untouched
        assert i18n.parent_approval(ctx, lang) and i18n.parent_facts(ctx, lang)
    assert "NOT" in i18n.parent_approval({**ctx, "verification_level": None}, "en")
    assert "尚未" in i18n.parent_approval({**ctx, "verification_level": None}, "zh")


def test_live_model_rewrite_in_chinese_must_keep_every_number(tmp_path):
    ctx = {"student": "Arjun", "amount_inr": 71000, "amount_cny": 6000, "purpose": "family_support", "payee": "P"}

    def llm(reply, d):
        class C:
            chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=reply))], usage=SimpleNamespace(total_tokens=10))))
        return LiveLLM(client=C(), cache_dir=tmp_path / d, sleep=lambda s: None, rpm=0)

    template = explain_template("parent_approval", ctx, "zh")
    assert "71,000" in template and "6,000" in template
    assert llm("Arjun想汇出 71,000 卢比（约 6,000 元）；超过 50,000 卢比需要家长批准。", "g").explain("parent_approval", ctx, "zh").startswith("Arjun想汇出")
    assert llm("Arjun想汇出一大笔钱。", "b").explain("parent_approval", ctx, "zh") == template          # numbers lost -> template
    assert i18n.LANG_NAMES["zh"] == "Simplified Chinese"


# ============================================================================================== API: language handling
def test_english_is_the_default_without_any_language_hint(api_client):
    r = api_client.post("/api/chat", json={"message": FORGED}).json()
    assert r["reply"].startswith("I checked it.") and "trace_localized" not in r["outcome"]
    assert r["outcome"]["card"]["title"] == "Why was I stopped?"


def test_zh_why_card_for_a_forged_invoice_has_rule_id_and_amounts(api_client):
    r = api_client.post("/api/chat", json={"message": FORGED}, headers=ZH).json()
    card = r["outcome"]["card"]
    assert card["rule"] == "R03_rejected_recipient" and "R03_rejected_recipient" in card["text"]
    assert "30,000" in card["text"] and CJK.search(card["text"]) and card["title"] == "这笔款项为何被拦截？"
    assert "30,000" in r["reply"] and r["reply"].startswith("我已检查完毕")
    out = r["outcome"]
    assert CJK.search(out["verification"]["reasons"][0]) and out["decision"] is None or CJK.search(" ".join(out["decision"]["reasons"]))
    assert out["trace"][0].startswith("Understand") and out["trace_localized"][0].startswith("理解")       # stored text stays English
    assert out["recovery"]["steps"][0] == "冻结这笔付款"
    # the stored data is English: the same card read in English (state) is the original
    st = api_client.get("/api/state").json()
    assert st["cards"][-1]["title"] == "Why was I stopped?" and "was rejected by rule" in st["cards"][-1]["text"]
    st_zh = api_client.get("/api/state?lang=zh").json()
    assert "R03_rejected_recipient" in st_zh["cards"][-1]["text"] and "30,000" in st_zh["cards"][-1]["text"]
    assert CJK.search(st_zh["cards"][-1]["text"])


def test_stored_audit_data_does_not_change_with_the_language(api_session):
    en, zh = new_client("student"), new_client("student")
    en.post("/api/intake", json={"text": FORGED})
    head = api_session.S.world.audit.head()
    zh.post("/api/intake", json={"text": FORGED}, headers=ZH)
    kinds = [e["data"].get("text", "") for e in api_session.S.world.audit.entries if e["kind"] == "why_card"]
    assert len(kinds) == 2 and kinds[0] == kinds[1] and not CJK.search(kinds[1])        # both stored in English
    assert head != api_session.S.world.audit.head()


def test_demo_runs_translate_every_engine_reason_and_keep_the_numbers(api_client):
    """All reasons/evidence/messages the two scripted runs produce have a Chinese rendering with the same numbers."""
    def strings(run, hdr):
        res = api_client.post("/api/demo/run", json={"run": run}, headers=hdr).json()
        found = []

        def walk(x, key=""):
            if isinstance(x, dict):
                for k, v in x.items():
                    if k not in ("trace", "parent_view", "labels", "trace_localized"):   # tool-call results are technical JSON; parent text has its own test
                        walk(v, k)
            elif isinstance(x, list):
                for v in x:
                    walk(v, key)
            elif isinstance(x, str) and key in ("reasons", "evidence", "why", "message", "headline", "advice"):
                found.append(x)
        walk(res["steps"])
        return found, res

    for run in ("legit", "attack"):
        en, res_en = strings(run, {})
        zh, res_zh = strings(run, ZH)
        assert len(en) == len(zh) and len(en) > 3
        pairs = [(a, b) for a, b in zip(en, zh)]
        untranslated = [a for a, b in pairs if a == b and not a.startswith("tool")]
        assert untranslated == [], untranslated                     # every reason, evidence line, plan sentence and headline is covered
        for a, b in pairs:
            assert i18n.numbers_preserved(a, b), (a, b)
        assert res_zh["steps"][0]["title"] != res_en["steps"][0]["title"] and CJK.search(res_zh["steps"][0]["title"])
    # the savings receipt and the scripted parent view
    legit = api_client.post("/api/demo/run", json={"run": "legit"}, headers=ZH).json()
    receipt = next(s for s in legit["steps"] if "savings_receipt" in s)["savings_receipt"]["text"]
    assert CJK.search(receipt) and re.search(r"¥[\d,]+\.\d\d", receipt)
    topup = next(s for s in legit["steps"] if "parent_view" in s)["parent_view"]
    assert set(topup) == {"ta", "hi", "en", "zh"} and "8,000" in topup["zh"]["explanation"] and CJK.search(topup["zh"]["explanation"])


def test_zh_plan_why_and_savings_endpoint(api_client):
    plan = api_client.post("/api/plan", json={"goal": "Pay everything due at the lowest cost."}, headers=ZH).json()
    assert plan["why"] and all(CJK.search(w) for w in plan["why"])
    assert "42,001" in " ".join(plan["why"]) or any(re.search(r"\d", w) for w in plan["why"])
    plan_en = api_client.post("/api/plan", json={"goal": "x"}).json()
    assert plan_en["why"][0].startswith(("3 of 3", "2 of 2", "1 of 1")) or "obligations are paid" in plan_en["why"][0]
    assert "保存" not in json.dumps(plan_en)
    sv = api_client.get("/api/explain/savings", headers=ZH).json()
    assert CJK.search(sv["text"]) and sv["text"].count("¥") == 1
    scen = api_client.get("/api/plan/scenarios", headers=ZH).json()
    assert all(CJK.search(s["title"]) for s in scen) and len(scen) == 8


def test_error_messages_follow_the_language_and_carry_a_neutral_code(api_session):
    judge = new_client("judge")
    en = judge.post("/api/intake", json={"text": "x"})
    zh = judge.post("/api/intake", json={"text": "x"}, headers=ZH)
    assert en.status_code == zh.status_code == 403
    assert "may not do this" in en.json()["detail"] and CJK.search(zh.json()["detail"])
    assert en.json()["code"] == zh.json()["code"] == "role_not_allowed"
    anon = TestClient(api_session.app)
    assert anon.get("/api/state").status_code == 401 and CJK.search(anon.get("/api/state", headers=ZH).json()["detail"])
    assert CJK.search(anon.get("/api/state?lang=zh").json()["detail"]) and "login required" in anon.get("/api/state?lang=xx").json()["detail"]
    st = new_client("student")
    bad = st.post("/api/chat", json={"message": "x" * 20001}, headers=ZH)
    assert bad.status_code == 422 and CJK.search(bad.json()["detail"][0]["msg"])
    assert st.post("/api/chat", json={"message": "x" * 20001}).json()["detail"][0]["msg"].startswith("String should have at most")


def test_accept_language_header_is_honoured_for_anonymous_and_x_oasis_lang_wins(api_session):
    anon = TestClient(api_session.app)
    assert CJK.search(anon.get("/api/state", headers={"Accept-Language": "zh-CN,zh;q=0.9"}).json()["detail"])
    assert "login required" in anon.get("/api/state", headers={"Accept-Language": "fr"}).json()["detail"]
    assert "login required" in anon.get("/api/state", headers={"Accept-Language": "zh-CN", "X-Oasis-Lang": "en"}).json()["detail"]


# ============================================================================================== saved student language
def test_student_language_persists_syncs_and_is_whitelisted(api_session):
    st = new_client("student")
    assert st.get("/api/auth/me").json()["language"] == "en"
    r = st.post("/api/student/language", json={"language": "zh"})
    assert r.status_code == 200 and r.json()["language"] == "zh" and r.json()["supported"] == ["en", "zh"]
    assert st.get("/api/auth/me").json()["language"] == "zh"
    assert api_session.S.world.passport.student.language == "zh"                      # the Passport holds it
    assert st.get("/api/state").json()["passport"]["student"]["language"] == "zh"
    # a request with no header now follows the saved language; a header or ?lang= still overrides it
    assert CJK.search(st.post("/api/chat", json={"message": "What do I owe?"}).json()["reply"])
    assert st.post("/api/chat", json={"message": "What do I owe?"}, headers={"X-Oasis-Lang": "en"}).json()["reply"].startswith("You have")
    assert st.post("/api/student/language", json={"language": "zh-CN"}).json()["language"] == "zh"        # region tags normalise
    assert st.post("/api/student/language", json={"language": "en"}).json()["language"] == "en"
    assert "audit" and any(e["kind"] == "language_set" for e in api_session.S.world.audit.entries)
    # persisted with the sandbox (snapshot round trip) and kept across a reset
    st.post("/api/student/language", json={"language": "zh"})
    snap = api_session.S.world.snapshot()
    assert snap["passport"]["student"]["language"] == "zh" if "passport" in snap else True
    st.post("/api/reset", json={})
    assert st.get("/api/auth/me").json()["language"] == "zh"


@pytest.mark.parametrize("bad", ["xx", "ta", "hi", "", "zh; DROP TABLE", "<script>", "français", "e" * 16])
def test_unknown_language_codes_are_rejected_and_change_nothing(api_session, bad):
    st = new_client("student")
    st.post("/api/student/language", json={"language": "zh"})
    r = st.post("/api/student/language", json={"language": bad}, headers={"X-Oasis-Lang": "en"})
    assert r.status_code == 400 and "unsupported language" in r.json()["detail"]
    assert st.get("/api/auth/me").json()["language"] == "zh"
    assert st.post("/api/student/language", json={"language": "e" * 17}).status_code == 422          # over the length cap
    assert st.post("/api/student/language", json={}).status_code == 422


def test_language_endpoint_is_student_only(api_session):
    anon = TestClient(api_session.app)
    assert anon.post("/api/student/language", json={"language": "zh"}).status_code == 401
    for role in ("parent", "judge"):
        c = new_client(role)
        assert c.post("/api/student/language", json={"language": "zh"}).status_code == 403
        assert "language" not in c.get("/api/auth/me").json()
    assert api_session.S.world.passport.student.language == "en"


def test_parent_view_supports_chinese_and_still_rejects_unknown_languages(api_session):
    st, pa = new_client("student"), new_client("parent")
    from auth_helpers import Approver
    s_dev = Approver(st, "student")
    topup = ("Payee: Arjun (own CNY account)\nPayee ID: payee_student_self\nAccount: acct_student_cny\nAmount: CNY 8,000\nPurpose: family_support")
    st.post("/api/intake", json={"text": topup, "remitter": "parent"})
    res = pa.get("/api/parent/pending?lang=zh").json()
    assert res["language"] == "zh" and set(res["available_languages"]) == {"en", "ta", "hi", "zh"}
    p = res["pending"][0]
    assert "8,000" in p["explanation"] and re.search(r"₹[\d,]+", p["explanation"]) and CJK.search(p["explanation"])
    assert p["labels"]["approve"] == "批准" and p["facts"][0]["label"] == "金额"
    assert pa.get("/api/parent/pending?lang=xx").status_code == 400
    assert pa.get("/api/parent/pending?lang=ta").json()["pending"][0]["language"] == "ta"        # Tamil / Hindi / English still work
    assert pa.get("/api/parent/pending?lang=hi").json()["pending"][0]["language"] == "hi"
    assert s_dev.key_id


def test_a_sandbox_reset_and_the_demo_keep_the_students_language(api_session):
    st = new_client("student")
    st.post("/api/student/language", json={"language": "zh"})
    st.post("/api/demo/start", json={"run": "legit"})
    assert st.get("/api/auth/me").json()["language"] == "zh"
    st.post("/api/demo/reset", json={})
    assert st.get("/api/auth/me").json()["language"] == "zh"
