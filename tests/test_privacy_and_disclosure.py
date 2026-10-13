"""Two claims that docs/compliance-mapping.md used to back by code inspection only.

1. Data minimisation: a screenshot or invoice photo is read once; its bytes are never stored. Only the payment
   fields extracted from it survive.
2. The 'information, not licensed financial advice' disclosure is on every screen of the shipped UI.
"""
import base64
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auth_helpers import login
from oasis import config
from oasis.api import main as api

ROOT = Path(__file__).resolve().parent.parent
MARKER = b"IMG-SECRET-MARKER-7c1e9a40"       # stands in for third-party personal data inside a chat screenshot
IMG = b"\x89PNG\r\n\x1a\n" + MARKER + bytes(range(256)) * 8
INVOICE_TEXT = ("Payee: University X Finance Office\nPayee ID: payee_univ_x\nAccount: 6228480000001234\n"
                "Amount: CNY 30,000\nPurpose: tuition\nDue: 2026-11-15")


class FakeVision:
    """Stands in for the Live vision call: records what it was given and returns the transcribed payment fields."""
    seen: bytes | None = None

    def __init__(self, llm=None):
        pass

    def to_text(self, data, mime="image/png"):
        FakeVision.seen = data
        return INVOICE_TEXT


def _needles():
    b64 = base64.b64encode(IMG).decode()
    return [MARKER, MARKER.decode(), base64.b64encode(MARKER).decode(), IMG.hex(), b64[16:96], IMG.hex()[40:120]]


def _contains_image(blob: str | bytes) -> bool:
    for n in _needles():
        if isinstance(blob, bytes):
            n = n if isinstance(n, bytes) else n.encode()
        elif isinstance(n, bytes):
            n = n.decode("latin-1")
        if n in blob:
            return True
    return False


def _session_dump(session) -> str:
    w = session.world
    return json.dumps({"audit": w.audit.entries, "proofs": w.proofs, "cards": w.cards,
                       "passport": w.passport.model_dump(), "pending": session.pending}, default=str)


def test_uploaded_image_bytes_are_never_stored(tmp_path, monkeypatch):
    db = str(tmp_path / "oasis.db")
    monkeypatch.setattr(api, "VisionExtractor", FakeVision)
    monkeypatch.setattr(FakeVision, "seen", None)
    saved, s = api.S, api.Session(db)
    api.S = s
    try:
        c = login(TestClient(api.app), "student")
        r = c.post("/api/intake/image", files={"file": ("invoice.png", IMG, "image/png")})
        assert r.status_code == 200, r.text
        out = r.json()
        assert FakeVision.seen == IMG, "the extractor must receive the image"
        # What survives is the payment fields read from it, and the normal pipeline ran on them.
        assert out["fields"]["payee_id"] == "payee_univ_x" and out["fields"]["amount"] == 30000
        assert out["status"] == "held" and out["pending_id"]

        # 1) nothing in the live session, nor in the response, contains the image in any common encoding
        assert not _contains_image(_session_dump(s)) and not _contains_image(r.text)

        # 2) nothing in the persisted state either: reload the encrypted SQLite file and look again
        s2 = api.Session(db)
        assert s2.world.audit.entries, "the reloaded session must have content to inspect"
        assert not _contains_image(_session_dump(s2))

        # 3) nothing was written to disk anywhere the app writes (database, keys, caches), raw or encoded
        files = [p for p in list(tmp_path.rglob("*")) + list(Path(config.DATA_DIR).rglob("*")) if p.is_file()]
        assert any(p.name == "oasis.db" for p in files)
        for p in files:
            assert not _contains_image(p.read_bytes()), f"image bytes found in {p}"
    finally:
        api.S = saved


def test_unreadable_image_is_held_and_still_not_stored(api_client, monkeypatch):
    """Even when the vision call fails, the upload is not kept: the student gets a low-confidence hold."""
    from oasis.agent.llm import VisionUnavailable

    class Broken(FakeVision):
        def to_text(self, data, mime="image/png"):
            raise VisionUnavailable("cannot read this image")

    monkeypatch.setattr(api, "VisionExtractor", Broken)
    r = api_client.post("/api/intake/image", files={"file": ("x.png", IMG, "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "held" and "cannot read" in body["message"]
    assert not _contains_image(r.text) and not _contains_image(_session_dump(api.S))


def test_disclosure_is_on_every_screen_of_the_ui_source():
    src = (ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    m = re.search(r"<footer>([^<]*)</footer>", src)
    assert m, "the app must render a footer"
    assert m.group(1).strip() == '{t("app.footer")}'          # the sentence lives in the language dictionaries
    for lang, phrases in (("en", ("not licensed financial advice", "hackathon prototype")), ("zh", ("不构成持牌金融建议", "黑客松原型"))):
        d = (ROOT / "frontend" / "src" / "i18n" / f"{lang}.js").read_text(encoding="utf-8")
        line = next(x for x in d.splitlines() if x.lstrip().startswith('"app.footer"'))
        assert all(ph in line for ph in phrases), (lang, line)
    # The footer sits in the persistent layout, after <main>, so it is not tied to a tab or to being logged in.
    layout = src[src.rindex("<div className=\"app\">"):]
    assert layout.index("</main>") < layout.index("<footer>") < layout.index("</div>")
    assert "{tab ===" not in layout[layout.index("</main>"):]


def test_disclosure_is_in_the_committed_ui_build():
    """frontend/dist is what the API serves; it must carry the same sentence."""
    assets = list((ROOT / "frontend" / "dist" / "assets").glob("*.js"))
    assert assets, "frontend/dist must be committed (the API serves it)"
    bundle = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in assets)
    assert "not licensed financial advice" in bundle
