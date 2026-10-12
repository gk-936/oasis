"""Parse a real RFC 822 email (.eml, or a message fetched over IMAP) into pipeline text plus provenance signals.

What is extracted: From / Reply-To / Subject, the visible AND hidden text of the body (hidden text is kept on purpose: it is
the classic carrier of prompt injection, so the injection detector must see it), text and PDF attachments, and images (read by
the vision model when one is available, otherwise noted). What is recorded as risk evidence: failed SPF/DKIM/DMARC in the
receiving server's Authentication-Results header, a Reply-To on a different domain than the sender (business-email
compromise), a free-mail address behind an institutional display name, and hidden text.

Limits: Authentication-Results is only as trustworthy as the mail server that added it (an uploaded .eml may carry any
header); a missing header is "unknown", never "pass".
"""
from __future__ import annotations
import io
import re
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses
from html.parser import HTMLParser

MAX_TEXT = 20000                  # same cap as the paste box
MAX_RAW = 12_000_000
MAX_ATTACHMENTS = 5
FREEMAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "qq.com", "163.com", "126.com",
            "sina.com", "foxmail.com", "proton.me", "protonmail.com", "icloud.com", "live.com"}
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|opacity\s*:\s*0(?:\.0+)?\b|"
                           r"color\s*:\s*(?:#f{3,6}|white)\b", re.I)
_AUTH = re.compile(r"\b(spf|dkim|dmarc)\s*=\s*(pass|fail|softfail|neutral|none|temperror|permerror|policy)", re.I)


class _Text(HTMLParser):
    """HTML to text that KEEPS hidden content and reports that some of it was styled to be invisible."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_seen = False
        self._stack: list[bool] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        hidden = bool(_HIDDEN_STYLE.search(a.get("style") or "")) or "hidden" in a
        if tag in ("br", "p", "div", "tr", "li", "table"):
            self.parts.append("\n")
        if tag in ("br", "img", "hr", "input", "meta", "link"):
            return
        self._stack.append(hidden)

    def handle_endtag(self, tag):
        if self._stack:
            self._stack.pop()
        if tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data)
            if any(self._stack):
                self.hidden_seen = True


def html_to_text(html: str) -> tuple[str, bool]:
    p = _Text()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001 - malformed markup must not stop intake; fall back to a tag strip
        return re.sub(r"<[^>]+>", " ", html), bool(_HIDDEN_STYLE.search(html))
    txt = "".join(p.parts)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", txt)).strip(), p.hidden_seen


@dataclass
class ParsedMail:
    text: str
    channel: dict
    notes: list[str] = field(default_factory=list)


def _domain(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].casefold().strip(" >") if "@" in addr else ""


def _pdf_text(data: bytes) -> str | None:
    try:
        from pypdf import PdfReader
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages[:10]).strip() or None
    except Exception:  # noqa: BLE001 - pypdf missing or the file is not a readable PDF
        return None


def auth_results(msg: EmailMessage) -> dict:
    """spf/dkim/dmarc -> result, from the receiving server's Authentication-Results header(s). Absent = not reported."""
    out: dict[str, str] = {}
    for h in msg.get_all("Authentication-Results", []) or []:
        for k, v in _AUTH.findall(str(h)):
            out.setdefault(k.lower(), v.lower())
    return out


def parse_eml(raw: bytes, vision=None) -> ParsedMail:
    """`vision(bytes, mime) -> str` reads an image attachment (or raises); None means images are only noted."""
    if len(raw) > MAX_RAW:
        raise ValueError("email is too large")
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    frm = getaddresses([str(msg.get("From", ""))])
    rto = getaddresses([str(msg.get("Reply-To", ""))])
    name, addr = (frm[0] if frm else ("", ""))
    subject = str(msg.get("Subject", "") or "")
    notes: list[str] = []
    body_parts: list[str] = []
    hidden = False
    atts: list[str] = []
    n_att = 0
    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        fn = part.get_filename()
        try:
            if fn or part.get_content_disposition() == "attachment":
                n_att += 1
                if n_att > MAX_ATTACHMENTS:
                    notes.append(f"more than {MAX_ATTACHMENTS} attachments: the rest were ignored")
                    continue
                data = part.get_payload(decode=True) or b""
                if ctype == "application/pdf":
                    t = _pdf_text(data)
                    atts.append(f"[Attachment {fn}]\n{t}" if t else f"[Attachment {fn}: PDF text could not be read]")
                    if not t:
                        notes.append(f"{fn}: PDF has no readable text layer")
                elif ctype.startswith("image/"):
                    if vision:
                        try:
                            atts.append(f"[Attachment {fn}]\n{vision(data, ctype)}")
                        except Exception as e:  # noqa: BLE001
                            notes.append(f"{fn}: image could not be read ({type(e).__name__})")
                    else:
                        notes.append(f"{fn}: image not read (no vision model configured)")
                elif ctype.startswith("text/"):
                    atts.append(f"[Attachment {fn}]\n{data.decode(part.get_content_charset() or 'utf-8', 'replace')}")
                else:
                    notes.append(f"{fn}: {ctype} ignored")
            elif ctype == "text/plain":
                body_parts.append(part.get_content())
            elif ctype == "text/html":
                t, h = html_to_text(part.get_content())
                body_parts.append(t)
                hidden |= h
        except Exception as e:  # noqa: BLE001 - one broken part must not lose the rest of the message
            notes.append(f"a {ctype} part could not be read ({type(e).__name__})")
    head = f"From: {name} <{addr}>\nSubject: {subject}" if addr else f"Subject: {subject}"
    text = (head + "\n\n" + "\n\n".join(p for p in body_parts + atts if p and p.strip())).strip()
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT]
        notes.append(f"message was cut at {MAX_TEXT} characters")
    sd, rd = _domain(addr), (_domain(rto[0][1]) if rto else "")
    channel = {"kind": "email", "sender": addr, "sender_name": name, "sender_domain": sd, "subject": subject[:200],
               "auth": auth_results(msg), "reply_to_differs": bool(rd and sd and rd != sd), "reply_to_domain": rd or None,
               "freemail_sender": sd in FREEMAIL, "hidden_text": hidden, "attachments": n_att}
    return ParsedMail(text, channel, notes)
