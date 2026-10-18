"""Generate the 30 HELD-OUT MOCK invoice photos in eval/vision_heldout/images/ (JPEG) and expected.json.

Never used to set the quality-gate thresholds (those come from eval/vision). Different layout, different fonts (Georgia, Calibri,
Cambria, Candara, Tahoma, Segoe UI, Comic Sans, Courier New, Bahnschrift; Microsoft JhengHei and Yu Gothic for Chinese), perspective tilt,
shadows, paper texture, phone-like sensor noise and JPEG compression. 24 are readable photos that must NOT be hard-held; 6 are unusable
controls (2 tiny, 2 very dark, 2 very blurry) that should be. Run: python -m eval.vision_heldout.generate
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

HERE = Path(__file__).parent
OUT = HERE / "images"
FONTS = "C:/Windows/Fonts/"
UNIV = ("payee_univ_x", "University X Finance Office", "测试大学财务处", "6228480000001234")
CHEN = ("payee_landlord_chen", "Chen Wei", "陈伟", "6222021111110001")
PUR_ZH = {"tuition": "学费", "rent": "房租", "deposit": "押金"}
PUR_EN = {"tuition": "Tuition fee", "rent": "Monthly rent", "deposit": "Security deposit"}
EN_FONTS = ["georgia.ttf", "calibri.ttf", "cambria.ttc", "Candara.ttf", "tahoma.ttf", "segoeui.ttf", "comic.ttf", "cour.ttf", "bahnschrift.ttf"]
ZH_FONTS = ["msjh.ttc", "YuGothM.ttc"]


def page(payee, account, amount, purpose, due, lang, font, fsize, size, rng, tint):
    """Ruled table layout (the tuning set used a plain label/value list)."""
    img = Image.new("RGB", size, tint)
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONTS + font, fsize)
    ft = ImageFont.truetype(FONTS + (font if lang == "en" else ZH_FONTS[0]), int(fsize * 1.25))
    pid, en, zh, _ = payee
    if lang == "en":
        rows = [("Payee", en), ("Payee ID", pid), ("Account no.", account), ("Amount due", f"CNY {amount:,.2f}"), ("Purpose", PUR_EN[purpose]), ("Due date", due)]
        title = "Payment notice (MOCK)"
    else:
        rows = [("收款单位", zh), ("单位编号", pid), ("收款账号", account), ("应付金额", f"人民币 {amount:,.2f} 元"), ("款项用途", PUR_ZH[purpose]), ("缴费期限", due)]
        title = "缴费通知单（演示）"
    x0, y0 = int(size[0] * 0.06), int(size[1] * 0.07)
    d.text((x0, y0), title, fill=(25, 25, 40), font=ft)
    y = y0 + int(fsize * 2.2)
    row_h = int(fsize * 1.9)
    col = x0 + int(size[0] * 0.30)
    for k, v in rows:
        d.line((x0, y, size[0] - x0, y), fill=(150, 150, 160), width=max(1, fsize // 18))
        d.text((x0 + 8, y + row_h * 0.18), k, fill=(80, 80, 95), font=f)
        d.text((col, y + row_h * 0.18), str(v), fill=(15, 15, 25), font=f)
        y += row_h
    d.line((x0, y, size[0] - x0, y), fill=(150, 150, 160), width=max(1, fsize // 18))
    return img


def texture(img, rng, strength):
    """Paper texture: low-frequency mottling plus fibre-like fine grain."""
    w, h = img.size
    low = Image.effect_noise((max(2, w // 40), max(2, h // 40)), 40).resize((w, h), Image.BICUBIC).convert("RGB")
    img = Image.blend(img, ImageEnhance.Brightness(low).enhance(1.6), strength)
    return img


def shadow(img, side, depth):
    """A hand/phone shadow: a smooth ramp that darkens one side."""
    w, h = img.size
    ramp = Image.linear_gradient("L").resize((w, h) if side in ("top", "bottom") else (h, w))
    if side in ("left", "right"):
        ramp = ramp.rotate(90 if side == "left" else -90, expand=True)
    if side in ("bottom", "right"):
        ramp = ramp.transpose(Image.FLIP_TOP_BOTTOM if side == "bottom" else Image.FLIP_LEFT_RIGHT)
    mask = ramp.point(lambda v: int(255 * (1 - depth * (1 - v / 255) ** 1.5)))
    dark = Image.merge("RGB", [mask] * 3)
    from PIL import ImageChops
    return ImageChops.multiply(img, dark)


def tilt(img, rng, amount, bg):
    """Perspective tilt with Pillow only: Image.transform(PERSPECTIVE) needs 8 coefficients, solved here by Gaussian elimination."""
    w, h = img.size
    dx, dy = w * amount, h * amount
    quad = [(rng.uniform(0, dx), rng.uniform(0, dy)), (w - rng.uniform(0, dx), rng.uniform(0, dy)),
            (w - rng.uniform(0, dx), h - rng.uniform(0, dy)), (rng.uniform(0, dx), h - rng.uniform(0, dy))]
    out_pts = [(0, 0), (w, 0), (w, h), (0, h)]
    # output pixel (x, y) takes its colour from input pixel (X, Y) = ((a x + b y + c) / (g x + h y + 1), (d x + e y + f) / (g x + h y + 1))
    A, B = [], []
    for (x, y), (X, Y) in zip(out_pts, quad):
        A.append([x, y, 1, 0, 0, 0, -X * x, -X * y]); B.append(X)
        A.append([0, 0, 0, x, y, 1, -Y * x, -Y * y]); B.append(Y)
    n = 8
    for i in range(n):
        piv = max(range(i, n), key=lambda r: abs(A[r][i]))
        A[i], A[piv], B[i], B[piv] = A[piv], A[i], B[piv], B[i]
        for r in range(i + 1, n):
            f = A[r][i] / A[i][i]
            A[r] = [a - f * b for a, b in zip(A[r], A[i])]
            B[r] -= f * B[i]
    coef = [0.0] * n
    for i in reversed(range(n)):
        coef[i] = (B[i] - sum(A[i][j] * coef[j] for j in range(i + 1, n))) / A[i][i]
    return img.transform(img.size, Image.PERSPECTIVE, coef, Image.BICUBIC, fillcolor=bg)


def sensor_noise(img, rng, sigma):
    """Phone-like noise: gaussian luminance noise plus weaker chroma noise (Image.effect_noise is centred on 128), then the slight
    softness of a small sensor."""
    from PIL import ImageChops
    w, h = img.size
    lum = Image.effect_noise((w, h), sigma)
    chroma = [Image.effect_noise((w, h), sigma / 3) for _ in range(3)]
    noise = Image.merge("RGB", [ImageChops.add(lum, c, scale=2, offset=0) for c in chroma])      # (lum + chroma) / 2 stays centred on 128
    return ImageChops.add(img.convert("RGB"), noise, scale=1, offset=-128).filter(ImageFilter.GaussianBlur(0.5))


def build() -> list[dict]:
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.jpg"):
        old.unlink()
    cases: list[dict] = []
    spec = [(UNIV, 28800.0, "tuition", "2026-11-12"), (CHEN, 5800.0, "rent", "2026-11-03"), (CHEN, 5800.0, "deposit", "2026-10-28"),
            (UNIV, 15750.5, "tuition", "2026-12-05")]

    def add(name, cat, img, case, gate, quality, note):
        path = OUT / f"{name}.jpg"
        img.convert("RGB").save(path, "JPEG", quality=quality)
        p, amt, pur, due = case
        cases.append({"file": f"images/{name}.jpg", "category": cat, "payee_id": p[0], "account_printed": p[3], "registry_account": p[3],
                      "amount": amt, "purpose": pur, "due": due, "gate": gate, "jpeg_quality": quality, "note": note,
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()[:16]})

    # 24 readable photos
    for i in range(24):
        rng = random.Random(1000 + i)
        case = spec[i % 4]
        lang = "zh" if i % 3 == 2 else "en"
        font = ZH_FONTS[i % 2] if lang == "zh" else EN_FONTS[i % len(EN_FONTS)]
        w = rng.choice([1280, 1400, 1600, 1100])
        size = (w, int(w * rng.uniform(0.62, 0.78)))
        fsize = int(w * rng.uniform(0.034, 0.042))
        tint = rng.choice([(247, 246, 238), (242, 240, 230), (250, 250, 252), (238, 240, 232)])
        img = page(case[0], case[0][3], case[1], case[2], case[3], lang, font, fsize, size, rng, tint)
        img = texture(img, rng, rng.uniform(0.04, 0.12))
        bits = [f"font {font}", lang]
        if i % 2 == 0:
            img = tilt(img, rng, rng.uniform(0.02, 0.07), tint)
            bits.append("perspective tilt")
        if i % 3 == 0:
            img = shadow(img, rng.choice(["left", "right", "top", "bottom"]), rng.uniform(0.25, 0.5))
            bits.append("shadow")
        if i % 4 == 1:
            img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.55, 0.75))
            bits.append("dim light")
        if i % 5 == 4:
            img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.8, 1.4)))
            bits.append("slight blur")
        img = sensor_noise(img, rng, rng.uniform(3, 9))
        add(f"photo_{i+1:02d}", "readable", img, case, "pass", rng.choice([40, 50, 60, 75, 85]), ", ".join(bits))

    # 6 unusable controls
    rng = random.Random(2000)
    base = lambda k: page(spec[k][0], spec[k][0][3], spec[k][1], spec[k][2], spec[k][3], "en", EN_FONTS[k], 46, (1400, 960), rng, (246, 245, 238))
    for j in range(2):
        img = base(j).resize((200 + 20 * j, 137 + 14 * j), Image.LANCZOS)
        add(f"control_tiny_{j+1}", "control_tiny", img, spec[j], "hold", 60, f"{img.width}px wide")
    for j in range(2):
        img = ImageEnhance.Brightness(texture(base(j), rng, 0.08)).enhance(0.07 + 0.02 * j)
        add(f"control_dark_{j+1}", "control_dark", sensor_noise(img, rng, 2), spec[j], "hold", 70, "brightness x0.07-0.09")
    for j in range(2):
        img = base(j + 2).filter(ImageFilter.GaussianBlur(9 + 2 * j))
        add(f"control_blur_{j+1}", "control_blur", sensor_noise(img, rng, 4), spec[j + 2], "hold", 65, "gaussian blur radius 9-11 at 1400px")
    (HERE / "expected.json").write_text(json.dumps(
        {"note": "MOCK invoices, HELD OUT: not used to set the quality-gate thresholds. gate=pass means a readable photo that must not be "
                 "hard-held; gate=hold means an unusable control. Fields are what each image prints.", "cases": cases},
        indent=1, ensure_ascii=False), encoding="utf-8")
    return cases


if __name__ == "__main__":
    print(len(build()), "images written to", OUT)
