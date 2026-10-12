"""Telegram intake: the student forwards an invoice (text, photo, PDF or .eml) to a bot and gets the verdict back.

Security model, because a bot is a public address:
- Nothing is processed until a chat is PAIRED. The logged-in student asks the app for a one-time code (10 minutes, single use)
  and sends `/pair CODE` to the bot; only then is that chat id trusted as "the student's phone". Anyone else who finds the bot
  gets one short refusal per minute and nothing else.
- The message content is untrusted text and goes through the normal pipeline. The channel adds NO authority: a payment still
  needs the student's signed approval in the app, so a stolen phone or a hijacked chat can submit invoices but cannot pay.
- Replies are plain text (no markup that a document could inject into) and long digit runs (account numbers) are masked, so the
  bot never echoes an attacker's account back into a chat.
- The bot token is never logged: errors are scrubbed before they are stored or shown.
"""
from __future__ import annotations
import hashlib
import json
import re
import secrets
import time
from pathlib import Path
from typing import Callable

import httpx

API = "https://api.telegram.org"
CODE_TTL_S = 600
MAX_CODES = 5
MAX_FILE = 12_000_000
MAX_TEXT = 20000
UNPAIRED_REPLY_EVERY_S = 60
_DIGITS = re.compile(r"\d{8,}")


class TelegramError(RuntimeError):
    pass


def mask_digits(s: str) -> str:
    """Long digit runs (account numbers) become '…1234'."""
    return _DIGITS.sub(lambda m: "…" + m.group(0)[-4:], s)


def summarize(o: dict, limit: int = 900) -> str:
    """A short plain-text verdict for a chat. `o` is a (localized) pipeline outcome."""
    st = o.get("status")
    f = o.get("fields") or {}
    who, amt = f.get("payee_name") or "the payee", f.get("amount")
    head = {"paid": "Paid", "held": "Needs your approval in Oasis", "frozen": "Frozen: nothing was paid",
            "rejected": "Rejected: nothing was paid", "needs_verification": "Needs verification: nothing was paid"}.get(st, str(st))
    lines = [f"{head}" + (f" - {who}, {f.get('currency') or 'CNY'} {amt:,.0f}" if isinstance(amt, (int, float)) and amt else "")]
    card = o.get("card") or {}
    if card.get("text"):
        lines.append(str(card["text"]))
    else:
        reasons = (o.get("decision") or {}).get("reasons") or (o.get("risk") or {}).get("evidence") or []
        lines += [f"- {r}" for r in reasons[:4]]
    if st == "held" and o.get("pending_id"):
        lines.append("Open Oasis and sign the approval there. Nothing moves until you do.")
    ch = o.get("channel") or {}
    if ch.get("kind") == "email" and (ch.get("hidden_text") or ch.get("reply_to_differs")):
        lines.append("Warning: this email has hidden text or a Reply-To that differs from the sender.")
    return mask_digits("\n".join(lines))[:limit]


class PairingStore:
    """Paired chat ids (persisted) and outstanding pairing codes (memory only)."""

    def __init__(self, path: Path | None = None, clock: Callable[[], float] = time.time):
        self.path, self.clock = path, clock
        self._chats: dict[str, dict] = {}
        self._codes: dict[str, float] = {}
        if path and path.exists():
            try:
                self._chats = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._chats = {}

    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._chats), encoding="utf-8")

    def new_code(self) -> dict:
        now = self.clock()
        self._codes = {c: e for c, e in self._codes.items() if e > now}
        while len(self._codes) >= MAX_CODES:
            self._codes.pop(min(self._codes, key=self._codes.get))
        code = secrets.token_hex(4).upper()
        self._codes[code] = now + CODE_TTL_S
        return {"code": code, "expires_in": CODE_TTL_S}

    def redeem(self, code: str, chat_id: int) -> bool:
        now = self.clock()
        ok = None
        for c, exp in list(self._codes.items()):
            if exp > now and secrets.compare_digest(c, str(code or "").strip().upper()):
                ok = c
        if ok is None:
            return False
        del self._codes[ok]                               # single use
        self._chats[str(chat_id)] = {"paired": time.strftime("%Y-%m-%d")}
        self._save()
        return True

    def is_paired(self, chat_id: int) -> bool:
        return str(chat_id) in self._chats

    def count(self) -> int:
        return len(self._chats)

    def clear(self) -> None:
        self._chats.clear()
        self._save()


class TelegramBot:
    def __init__(self, token: str, handler: Callable[[str, dict, list], str], store: PairingStore,
                 vision: Callable[[bytes, str], str] | None = None, http: httpx.Client | None = None,
                 base: str = API, clock: Callable[[], float] = time.time):
        self.token, self.handler, self.store, self.vision = token, handler, store, vision
        self.http = http or httpx.Client(timeout=40)
        self.base, self.clock = base, clock
        self.offset = 0
        self.last_error: str | None = None
        self.processed = 0
        self._unpaired_reply: dict[int, float] = {}

    # -- transport (the token is scrubbed from anything that leaves this class) ---------------------------------
    def _scrub(self, s: str) -> str:
        return s.replace(self.token, "[token]")

    def _call(self, method: str, **params):
        try:
            r = self.http.post(f"{self.base}/bot{self.token}/{method}", json=params)
            j = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise TelegramError(self._scrub(f"{method}: {type(e).__name__}")) from None
        if not j.get("ok"):
            raise TelegramError(self._scrub(f"{method}: {j.get('description', 'error')}"))
        return j["result"]

    def _download(self, file_id: str) -> bytes:
        info = self._call("getFile", file_id=file_id)
        if int(info.get("file_size") or 0) > MAX_FILE:
            raise TelegramError("file is larger than 12 MB")
        try:
            r = self.http.get(f"{self.base}/file/bot{self.token}/{info['file_path']}")
        except httpx.HTTPError as e:
            raise TelegramError(self._scrub(f"download: {type(e).__name__}")) from None
        if r.status_code != 200 or len(r.content) > MAX_FILE:
            raise TelegramError("download failed")
        return r.content

    def say(self, chat_id: int, text: str) -> None:
        try:
            self._call("sendMessage", chat_id=chat_id, text=text[:3500], disable_web_page_preview=True)
        except TelegramError as e:
            self.last_error = str(e)

    # -- one poll ------------------------------------------------------------------------------------------------
    def poll_once(self, timeout: int = 0) -> int:
        n = 0
        try:
            updates = self._call("getUpdates", offset=self.offset, timeout=timeout, allowed_updates=["message"])
        except TelegramError as e:
            self.last_error = str(e)
            return 0
        for u in updates:
            self.offset = max(self.offset, int(u.get("update_id", 0)) + 1)
            m = u.get("message")
            if isinstance(m, dict) and isinstance(m.get("chat"), dict) and m["chat"].get("type") == "private":
                try:
                    self._message(m)
                    n += 1
                except Exception as e:  # noqa: BLE001 - one bad message must not stop the bot
                    self.last_error = self._scrub(f"message: {type(e).__name__}")
        self.processed += n
        return n

    def _message(self, m: dict) -> None:
        chat = int(m["chat"]["id"])
        text = (m.get("text") or m.get("caption") or "").strip()
        if text.lower().startswith("/pair"):
            ok = self.store.redeem(text[5:].strip(), chat)
            self.say(chat, "Paired. Forward me an invoice (text, photo, PDF or .eml) and I will check it. "
                           "Payments still need your signed approval in Oasis." if ok else "That code is not valid or has expired.")
            return
        if not self.store.is_paired(chat):
            now = self.clock()
            if now - self._unpaired_reply.get(chat, 0) >= UNPAIRED_REPLY_EVERY_S:
                self._unpaired_reply[chat] = now
                self.say(chat, "This chat is not paired with an Oasis account. In Oasis, open Chat and press Connect Telegram.")
            return
        if text.lower() in ("/start", "/help"):
            self.say(chat, "Send or forward an invoice: text, a photo, a PDF or an .eml file. I will say whether it is safe to pay.")
            return
        body, notes = text, []
        try:
            body, notes = self._content(m, text)
        except TelegramError as e:
            self.say(chat, f"I could not read that: {e}. Please paste the invoice text instead.")
            return
        if not body.strip():
            self.say(chat, "I could not find any invoice text in that message.")
            return
        channel = {"kind": "telegram", "chat": hashlib.sha256(str(chat).encode()).hexdigest()[:8]}
        self.say(chat, self.handler(body[:MAX_TEXT], channel, notes))

    def _content(self, m: dict, text: str) -> tuple[str, list[str]]:
        notes: list[str] = []
        if m.get("photo"):
            if not self.vision:
                raise TelegramError("no image-reading model is configured")
            data = self._download(max(m["photo"], key=lambda p: int(p.get("file_size") or 0))["file_id"])
            return (text + "\n\n" if text else "") + self.vision(data, "image/jpeg"), notes
        d = m.get("document")
        if d:
            name, mime = str(d.get("file_name") or ""), str(d.get("mime_type") or "")
            data = self._download(d["file_id"])
            if mime == "message/rfc822" or name.lower().endswith(".eml"):
                from .mail import parse_eml
                pm = parse_eml(data, vision=self.vision)
                return pm.text, pm.notes
            if mime == "application/pdf":
                from .mail import _pdf_text
                t = _pdf_text(data)
                if not t:
                    raise TelegramError("that PDF has no readable text")
                return (text + "\n\n" if text else "") + t, notes
            if mime.startswith("image/") and self.vision:
                return (text + "\n\n" if text else "") + self.vision(data, mime), notes
            if mime.startswith("text/"):
                return data.decode("utf-8", "replace"), notes
            raise TelegramError(f"{mime or 'that file type'} is not supported")
        return text, notes
