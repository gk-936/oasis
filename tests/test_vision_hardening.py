"""Hardened image intake: quality gate, preprocessing, closed-list prompt, validators, two-pass check, replay of the two live failures.

Offline: the model is a scripted function; images are the generated MOCK set in eval/vision/images (read only).
"""
import io
import json
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from oasis.agent import vision as V
from oasis.agent.llm import VisionExtractor, VisionUnavailable
from oasis.agent.vision import VisionHold
from oasis.mock.registry import ALIASES
from oasis.world import World

IMGS = Path(__file__).resolve().parents[1] / "eval" / "vision" / "images"
GOOD = {"Payee ID": "payee_univ_x", "Account": "6228480000001234", "Amount": "30000", "Purpose": "tuition", "Due": "2026-11-15"}


def img(name: str) -> bytes:
    return (IMGS / f"{name}.png").read_bytes()


def reply(**over) -> str:
    names = {k.lower().replace(" ", "_"): k for k in GOOD}
    return "\n".join(f"{k}: {v}" for k, v in {**GOOD, **{names[k]: v for k, v in over.items()}}.items())


@pytest.fixture(scope="module")
def ctx():
    return V.context_from_world(World())


class Model:
    """Scripted model: one reply per call; records the prompts. Fails the test if called more often than scripted."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, system, user, image):
        self.calls.append((system, user, image))
        assert self.replies, "the model was called more often than scripted"
        return self.replies.pop(0)


class NeverCalled:
    def __call__(self, *a):
        raise AssertionError("the model must not be called for an image that fails the quality gate")


# ------------------------------------------------------------------ quality gate
@pytest.mark.parametrize("name,word", [("blurry_2_1", "blurry"), ("blurry_3_2", "blurry"), ("low_res_1", "resolution"),
                                       ("low_res_3", "resolution"), ("low_light_2", "dark")])
def test_poor_photo_is_held_before_any_model_call(name, word, ctx):
    with pytest.raises(VisionHold) as e:
        V.read_invoice(img(name), NeverCalled(), ctx)
    assert e.value.kind == "quality" and word in " ".join(e.value.reasons)
    assert "clearer photo" in str(e.value) and "paste" in str(e.value)


def test_blank_white_and_non_image_are_held(ctx):
    buf = io.BytesIO()
    Image.new("RGB", (900, 560), (255, 255, 255)).save(buf, "PNG")
    with pytest.raises(VisionHold) as e:
        V.read_invoice(buf.getvalue(), NeverCalled(), ctx)
    assert e.value.kind == "quality"
    with pytest.raises(VisionHold):
        V.read_invoice(b"\x89PNGfake", NeverCalled(), ctx)


@pytest.mark.parametrize("name,n", [("vision", 40), ("vision_heldout", 30)])
def test_gate_never_hard_holds_a_readable_image_and_holds_every_unusable_one(name, n):
    base = IMGS.parents[1] / name
    cases = json.loads((base / "expected.json").read_text(encoding="utf-8"))["cases"]
    assert len(cases) == n
    for c in cases:
        hard, soft, _ = V.quality_gate(V.open_image((base / c["file"]).read_bytes()))
        assert bool(hard) == (c["gate"] == "hold"), c["file"]


def borderline_png() -> bytes:
    from PIL import ImageFilter
    buf = io.BytesIO()
    Image.open(IMGS / "clean_en_1.png").filter(ImageFilter.GaussianBlur(1.8)).save(buf, "PNG")
    return buf.getvalue()


def test_borderline_photo_goes_to_the_model_with_two_passes_even_if_one_is_configured(ctx, monkeypatch):
    monkeypatch.setenv("OASIS_VISION_PASSES", "1")
    hard, soft, _ = V.quality_gate(V.open_image(borderline_png()))
    assert not hard and soft
    m = Model(reply(), reply())
    text, info = V.read_invoice(borderline_png(), m, ctx)
    assert len(m.calls) == 2 and info["borderline"] and "Amount: CNY 30,000" in text


def test_borderline_photo_is_held_only_on_disagreement_or_validation_failure(ctx):
    with pytest.raises(VisionHold) as e:
        V.read_invoice(borderline_png(), Model(reply(), reply(amount="13000")), ctx)
    assert e.value.kind == "disagreement" and "borderline" in str(e.value)
    with pytest.raises(VisionHold) as e:
        V.read_invoice(borderline_png(), Model(reply(purpose="gambling")), ctx)
    assert e.value.kind == "validation" and "borderline" in str(e.value)


# ------------------------------------------------------------------ preprocessing
def test_exif_orientation_is_applied():
    stored = Image.open(IMGS / "rotated_1.png")
    assert stored.size == (560, 900)                      # pixels were stored turned
    assert V.open_image(img("rotated_1")).size == (900, 560)


@pytest.mark.parametrize("name,deg", [("skewed_1", 3), ("skewed_2", -4), ("skewed_3", 6), ("skewed_4", -7)])
def test_deskew_estimates_the_correction(name, deg):
    assert abs(V.estimate_skew(V.open_image(img(name))) + deg) <= 1.0


def test_preprocess_upscales_small_images_and_returns_png():
    small = Image.new("L", (500, 320), 230)
    out = Image.open(io.BytesIO(V.preprocess(small)))
    assert out.format == "PNG" and max(out.size) >= 1400


# ------------------------------------------------------------------ closed-list prompt
def test_prompt_lists_registry_payees_with_chinese_aliases(ctx):
    for variant in (0, 1):
        sys_, user = V.build_prompt(ctx, variant)
        for p in ctx.payees:
            assert p.id in sys_ and p.name in sys_ and all(a in sys_ for a in p.aliases) and p.aliases, p.id
        assert "none" in sys_ and "Payees" in sys_ and "收款方" in sys_ and V._CJK.search(user) and "invoice" in user


def test_every_registry_payee_has_chinese_aliases():
    ids = {c["payee_id"] for c in World(autonomy=True).registry.all()} | {"payee_us_univ", "payee_eu_univ"}
    for pid in ids:
        assert pid in ALIASES and all(V._CJK.search(a) for a in ALIASES[pid]), pid


def test_prompts_are_reworded_between_passes(ctx):
    assert V.build_prompt(ctx, 0) != V.build_prompt(ctx, 1)


@pytest.mark.parametrize("hint", ["", "invoice.png lang=en", "发票.png", "invoice.png lang=zh"])
def test_prompt_is_the_same_bilingual_prompt_for_every_image_whatever_the_hint(ctx, hint):
    m = Model(reply(), reply())
    V.read_invoice(img("clean_en_1"), m, ctx, hint=hint)
    assert m.calls[0][:2] == V.build_prompt(ctx, 0) and m.calls[1][:2] == V.build_prompt(ctx, 1)


def test_bilingual_labels_in_a_reply_are_parsed():
    raw = V.parse_fields("收款方编号: payee_univ_x\n账号: 6228480000001234\n金额: 30000\n用途: tuition\n到期日: 2026-11-15\n"
                         "Payee ID (收款方编号): ignored second\nPayee: 赵凯旋")
    assert raw == {"payee_id": "payee_univ_x", "account": "6228480000001234", "amount": "30000", "purpose": "tuition", "due": "2026-11-15"}
    raw = V.parse_fields("Payee ID (收款方编号): payee_univ_x\nAmount (金额): 30000")
    assert raw["payee_id"] == "payee_univ_x" and raw["amount"] == "30000"
    png = Image.new("RGB", (900, 560), (240, 240, 240))
    assert V.detect_zh("", img=png) is False
    png.info["Description"] = "学费发票"
    assert V.detect_zh("", img=png) is True


# ------------------------------------------------------------------ validators
def check(raw_over, ctx):
    clean, bad, _confirm = V.validate(V.parse_fields(reply(**raw_over)), ctx)
    return clean, bad


def test_valid_reply_is_clean_and_canonical(ctx):
    clean, bad = check({}, ctx)
    assert not bad and clean == {"payee_id": "payee_univ_x", "account": "6228480000001234", "amount": 30000.0,
                                 "purpose": "tuition", "due": "2026-11-15"}
    text = V.canonical_text(clean, ctx)
    assert "Payee: University X Finance Office" in text and "Amount: CNY 30,000" in text


@pytest.mark.parametrize("over,field", [
    ({"payee_id": "payee_made_up"}, "payee_id"), ({"payee_id": "none"}, "payee_id"), ({"payee_id": "payee_" + "0" * 80}, "payee_id"),
    ({"account": "12345"}, "account"), ({"account": "62284800000012AB"}, "account"), ({"account": "9" * 25}, "account"),
    ({"amount": "-5"}, "amount"), ({"amount": "0"}, "amount"), ({"amount": "9999999"}, "amount"), ({"amount": "abc"}, "amount"),
    ({"amount": "none"}, "amount"), ({"amount": "300000"}, "amount"),            # 10x the open tuition obligation
    ({"due": "2026-13-45"}, "due"), ({"due": "2030-01-01"}, "due"), ({"due": "2019-01-01"}, "due"), ({"due": "soon"}, "due"),
    ({"purpose": "测试"}, "purpose"), ({"purpose": "gambling"}, "purpose"),
])
def test_each_validator_rejects_and_names_the_field(over, field, ctx):
    _, bad = check(over, ctx)
    assert field in [f for f, _ in bad]


def test_optional_fields_may_be_missing_and_purpose_may_be_chinese_label(ctx):
    clean, bad, _ = V.validate({"payee_id": "payee_landlord_chen", "amount": "6,000", "purpose": "房租"}, ctx)
    assert not bad and clean["purpose"] == "rent" and "account" not in clean and "due" not in clean


def test_amount_for_a_payee_without_an_open_obligation_is_not_failed_but_confirmed(ctx):
    own = {"payee_id": "payee_student_self", "amount": "250000", "account": "none"}      # no obligation: the 2x rule cannot apply
    clean, bad, confirm = V.validate(V.parse_fields(reply(**own)), ctx)
    assert not any(f == "amount" for f, _ in bad) and [f for f, _ in confirm] == ["amount"] and clean["amount"] == 250000.0
    with pytest.raises(VisionHold) as e:
        V.read_invoice(img("clean_en_1"), Model(reply(**own), reply(**own)), ctx)
    assert e.value.kind == "confirmation" and e.value.fields == ["amount"]
    assert "open obligation" in e.value.reasons[0] and "confirm" in str(e.value).lower()
    # a payee WITH an open obligation still fails the plausibility rule, and an in-range amount needs no confirmation
    assert "amount" in [f for f, _ in V.validate(V.parse_fields(reply(amount="300000")), ctx)[1]]
    assert V.validate(V.parse_fields(reply()), ctx)[2] == []
    # still capped in absolute terms even without an obligation
    assert "amount" in [f for f, _ in V.validate(V.parse_fields(reply(**{**own, "amount": "9999999"})), ctx)[1]]


def test_validation_failure_is_a_hold_with_a_why_card_field(ctx):
    with pytest.raises(VisionHold) as e:
        V.read_invoice(img("clean_en_1"), Model(reply(purpose="gambling")), ctx)
    assert e.value.kind == "validation" and e.value.fields == ["purpose"]
    assert "Purpose" in str(e.value) and "Purpose" in e.value.reasons[0]


def test_model_payee_name_is_never_used(ctx):
    text, _ = V.read_invoice(img("clean_en_1"), Model("Payee: Evil Corp Ltd\n" + reply(), "Payee: Other\n" + reply()), ctx)
    assert "Evil" not in text and "Other" not in text and text.startswith("Payee: University X Finance Office")


# ------------------------------------------------------------------ two passes
def test_two_passes_by_default_and_the_second_is_reworded(ctx):
    m = Model(reply(), reply())
    text, info = V.read_invoice(img("clean_en_1"), m, ctx)
    assert info["passes"] == 2 and len(m.calls) == 2 and m.calls[0][0] != m.calls[1][0]
    assert "Amount: CNY 30,000" in text


@pytest.mark.parametrize("second,field", [({"amount": "13000"}, "amount"), ({"payee_id": "payee_landlord_chen", "amount": "6000"}, "payee_id"),
                                          ({"account": "6222021111110001"}, "account")])
def test_disagreement_between_passes_is_held(second, field, ctx):
    with pytest.raises(VisionHold) as e:
        V.read_invoice(img("clean_en_1"), Model(reply(), reply(**second)), ctx)
    assert e.value.kind == "disagreement" and field in e.value.fields and "confirm" in str(e.value)


def test_a_bad_first_reading_is_held_without_the_second_call(ctx):
    m = Model(reply(amount="9999999"))
    with pytest.raises(VisionHold):
        V.read_invoice(img("clean_en_1"), m, ctx)
    assert len(m.calls) == 1


def test_single_pass_is_configurable(ctx, monkeypatch):
    monkeypatch.setenv("OASIS_VISION_PASSES", "1")
    m = Model(reply())
    _, info = V.read_invoice(img("clean_en_1"), m, ctx)
    assert info["passes"] == 1 and len(m.calls) == 1
    monkeypatch.setenv("OASIS_VISION_PASSES", "junk")
    assert V.passes() == 2


# ------------------------------------------------------------------ replay of the two failed live responses (eval/reports/vision_live.md)
# The raw rows were not saved; these are reconstructed from the report's description of each failure.
LIVE_CHINESE = ("Payee: 赵凯旋 (MOCK)\nPayee ID: payee_univ_x\nAccount: 6228480000001234\nAmount: CNY 30,000\n"
                "Purpose: 测试\nDue: 2026-11-15")
LIVE_BLURRY = "Payee: 财务部 采购付款\nPayee ID: " + "0" * 3000


def test_replay_invented_payee_and_purpose_on_the_chinese_invoice_is_held(ctx):
    for passes in ("2", "1"):
        with pytest.raises(VisionHold) as e:
            V.read_invoice(img("clean_zh_1"), Model(LIVE_CHINESE, LIVE_CHINESE), ctx, hint="lang=zh")
        assert e.value.fields == ["purpose"]


def test_replay_invented_payee_is_corrected_when_the_rest_is_valid(ctx):
    fixed = LIVE_CHINESE.replace("Purpose: 测试", "Purpose: 学费")
    text, _ = V.read_invoice(img("clean_zh_1"), Model(fixed, fixed), ctx, hint="lang=zh")
    assert "赵凯旋" not in text and "University X Finance Office" in text and "Purpose: tuition" in text


def test_replay_runaway_payee_id_on_the_blurry_image_never_reaches_the_model(ctx):
    with pytest.raises(VisionHold) as e:
        V.read_invoice(img("blurry_3_1"), NeverCalled(), ctx)
    assert e.value.kind == "quality"


def test_replay_runaway_payee_id_is_held_even_if_the_gate_lets_the_image_through(ctx):
    for _ in range(2):
        with pytest.raises(VisionHold) as e:
            V.read_invoice(img("clean_en_1"), Model(LIVE_BLURRY, LIVE_BLURRY), ctx)
        assert e.value.fields == ["payee_id"]
    short = "Payee: 财务部 采购付款\nPayee ID: payee_" + "0" * 20        # not long enough for the runaway rule: the registry check catches it
    with pytest.raises(VisionHold) as e:
        V.read_invoice(img("clean_en_1"), Model(short, short), ctx)
    assert "payee_id" in e.value.fields


# ------------------------------------------------------------------ extractor + endpoint
class FakeLLM:
    def __init__(self, *replies):
        self.replies, self.n = list(replies), 0

    def _chat(self, system, user, image=None):
        self.n += 1
        return self.replies.pop(0)


def test_extractor_wires_gate_and_world(ctx):
    w = World()
    llm = FakeLLM()
    with pytest.raises(VisionHold):
        VisionExtractor(llm, w).to_text(img("blurry_3_1"))
    assert llm.n == 0
    llm = FakeLLM(reply(), reply())
    ex = VisionExtractor(llm, w)
    assert "payee_univ_x" in ex.to_text(img("clean_zh_1"), "image/png", hint="发票")
    assert ex.last["passes"] == 2


def _post(api_client, api, monkeypatch, llm, name):
    monkeypatch.setattr(api, "VisionExtractor", lambda l=None, world=None: VisionExtractor(llm, world))
    return api_client.post("/api/intake/image", files={"file": (f"{name}.png", img(name), "image/png")}).json()


def test_endpoint_holds_a_blurry_photo_with_a_why_card_and_no_model_call(api_client, monkeypatch):
    from oasis.api import main as api
    llm = FakeLLM()
    out = _post(api_client, api, monkeypatch, llm, "blurry_3_1")
    assert out["status"] == "held" and llm.n == 0
    assert out["vision"]["kind"] == "quality" and out["card"]["rule"] == "vision_quality"
    assert "clearer photo" in out["message"]


def test_endpoint_holds_a_doubtful_field_and_never_pays(api_client, monkeypatch):
    from oasis.api import main as api
    bad = reply(purpose="测试")
    out = _post(api_client, api, monkeypatch, FakeLLM(bad, bad), "clean_zh_1")
    assert out["status"] == "held" and out["vision"]["fields"] == ["purpose"]
    assert out["card"]["reasons"][0].startswith("Purpose:") and not out.get("transfer")


def test_endpoint_good_image_flows_into_the_normal_pipeline(api_client, monkeypatch):
    from oasis.api import main as api
    out = _post(api_client, api, monkeypatch, FakeLLM(reply(), reply()), "clean_en_1")
    assert out["fields"]["payee_id"] == "payee_univ_x" and out["fields"]["amount"] == 30000 and out["status"] == "held"


def test_endpoint_injected_and_wrong_account_images_stay_held(api_client, monkeypatch):
    from oasis.api import main as api
    # the model transcribes what is printed (an injected account, or a different one): the registry rule holds it
    r = reply(account="6666000000000002")
    out = _post(api_client, api, monkeypatch, FakeLLM(r, r), "injected_2")
    assert out["status"] in ("held", "frozen", "rejected", "needs_verification") and not out.get("transfer")
    r = reply(account="6228480000009999")
    out = _post(api_client, api, monkeypatch, FakeLLM(r, r), "wrong_account_1")
    assert out["status"] in ("held", "frozen", "rejected", "needs_verification") and not out.get("transfer")


# ------------------------------------------------------------------ live-run rows
def test_no_rows_are_written_unless_the_run_is_live(tmp_path, monkeypatch, ctx):
    monkeypatch.setenv("OASIS_VISION_ROWS", str(tmp_path / "rows.json"))
    assert V.row_recorder() is None                      # tests run with OASIS_LLM=offline
    V.read_invoice(img("clean_en_1"), Model(reply(), reply()), ctx, on_event=V.row_recorder())
    assert not (tmp_path / "rows.json").exists()
    monkeypatch.setattr(V.config, "LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("OASIS_VISION_ROWS", "0")
    assert V.row_recorder() is None


def test_live_calls_save_the_raw_reply_per_image_and_pass(tmp_path, monkeypatch):
    path = tmp_path / "rows.json"
    w = World()                                          # built offline; only the recorder sees the "live" switch
    monkeypatch.setattr(V.config, "LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("OASIS_VISION_ROWS", str(path))
    first, second = reply(), reply(amount="13000") + "\nPayee: free text the model added"
    with pytest.raises(VisionHold):
        VisionExtractor(FakeLLM(first, second), w).to_text(img("clean_en_1"))
    ok = reply()
    VisionExtractor(FakeLLM(ok, ok), w).to_text(img("clean_zh_1"))
    with pytest.raises(VisionHold):                         # a hard-held image: no model call, but the outcome is recorded
        VisionExtractor(FakeLLM(), w).to_text(img("blurry_3_1"))
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    passes = [r for r in rows if r["kind"] == "pass"]
    assert [(r["pass"], r["raw_reply"]) for r in passes[:2]] == [(1, first), (2, second)]      # raw text, byte for byte
    assert all(r["model"] == V.config.AGENT_MODEL and len(r["image"]) == 16 for r in rows)
    outcomes = [(r["outcome"], r.get("hold_kind")) for r in rows if r["kind"] == "outcome"]
    assert outcomes == [("held", "disagreement"), ("accepted", None), ("held", "quality")]
    assert len({r["image"] for r in passes}) == 2


# ------------------------------------------------------------------ verify_evidence.py recomputes the vision figures from the rows
def _verify(tmp_path, rows):
    import shutil
    import subprocess
    import sys
    src = Path(__file__).resolve().parents[1] / "execution_evidence"
    dst = tmp_path / "execution_evidence"
    dst.mkdir()
    for f in ("verify_evidence.py", "operation_log.jsonl", "evidence_results.json", "participant_logs.json"):
        shutil.copyfile(src / f, dst / f)
    shutil.copytree(src / "live_reports", dst / "live_reports")
    (dst / "live_reports" / "vision_live_final_rows.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", str(dst / "verify_evidence.py")], capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout


def _row(img, n, reply_text):
    return {"kind": "pass", "image": img, "pass": n, "variant": n - 1, "raw_reply": reply_text}


def test_verify_evidence_recomputes_the_vision_figures_from_raw_replies(tmp_path):
    good = reply()
    ok_rows = [_row("a" * 16, 1, good), _row("a" * 16, 2, good), {"kind": "outcome", "image": "a" * 16, "outcome": "accepted"},
               _row("b" * 16, 1, good), _row("b" * 16, 2, reply(amount="13000")),
               {"kind": "outcome", "image": "b" * 16, "outcome": "held", "hold_kind": "disagreement"}]
    (tmp_path / "ok").mkdir()
    code, out = _verify(tmp_path / "ok", ok_rows)
    assert code == 0 and "[PASS] vision: every accepted image" in out and "disagreement 1" in out
    # an accepted image whose raw replies disagree, or whose payee is not on the list, or that ran away, must fail the check
    for i, bad in enumerate([reply(amount="13000"), reply(payee_id="payee_made_up"), reply(payee_id="payee_" + "0" * 60)]):
        (tmp_path / f"bad{i}").mkdir()
        rows = [_row("c" * 16, 1, good), _row("c" * 16, 2, bad), {"kind": "outcome", "image": "c" * 16, "outcome": "accepted"}]
        code, out = _verify(tmp_path / f"bad{i}", rows)
        assert code == 1 and "[FAIL] vision" in out, bad
