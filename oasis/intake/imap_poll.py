"""Mailbox intake over IMAP: invoices that arrive at a dedicated address (for example oasis.student@gmail.com) are picked up.

Use a DEDICATED mailbox and an app password (never the account password). Rules, because anyone can email an address:
- Only senders on the allow-list (OASIS_IMAP_ALLOWED_SENDERS, exact addresses) are processed; everything else is marked read and
  ignored, with nothing sent back (no auto-reply: that would confirm the address to spammers and spoofed senders).
- The From header is easy to forge, so by default (OASIS_IMAP_REQUIRE_AUTH=1) an allow-listed message is processed only if the
  receiving server reports SPF, DKIM or DMARC = pass in Authentication-Results. A message with no such header is NOT trusted.
- What passes is still untrusted text for the pipeline; the email adds provenance evidence and no authority. Payments still need
  the student's signed approval in the app.
"""
from __future__ import annotations
import imaplib
import time
from typing import Callable

from .mail import MAX_RAW, parse_eml


class ImapPoller:
    def __init__(self, host: str, user: str, password: str, handler: Callable[[str, dict, list], str], allowed: set[str],
                 mailbox: str = "INBOX", factory=imaplib.IMAP4_SSL, vision=None, require_auth: bool = True,
                 clock: Callable[[], float] = time.time):
        if not allowed:
            raise ValueError("OASIS_IMAP_ALLOWED_SENDERS must list at least one sender address")
        self.host, self.user, self._password = host, user, password
        self.handler, self.allowed = handler, {a.strip().casefold() for a in allowed if a.strip()}
        self.mailbox, self.factory, self.vision, self.require_auth, self.clock = mailbox, factory, vision, require_auth, clock
        self.last_poll: float | None = None
        self.last_error: str | None = None
        self.processed = 0
        self.ignored = 0
        self.results: list[dict] = []        # last few: {"sender", "subject", "status": processed|ignored, "why"}

    def _scrub(self, s: str) -> str:
        return s.replace(self._password, "[password]") if self._password else s

    def _note(self, **kw) -> None:
        self.results = (self.results + [kw])[-20:]

    def poll_once(self) -> int:
        n = 0
        self.last_poll = self.clock()
        box = None
        try:
            box = self.factory(self.host)
            box.login(self.user, self._password)
            box.select(self.mailbox)
            typ, data = box.search(None, "UNSEEN")
            if typ != "OK":
                raise imaplib.IMAP4.error("search failed")
            for num in (data[0] or b"").split():
                typ, msg = box.fetch(num, "(BODY.PEEK[])")
                raw = next((p[1] for p in msg if isinstance(p, tuple)), b"") if typ == "OK" else b""
                box.store(num, "+FLAGS", "\\Seen")           # never process the same message twice
                if not raw or len(raw) > MAX_RAW:
                    self._note(sender="?", subject="", status="ignored", why="empty or too large")
                    self.ignored += 1
                    continue
                pm = parse_eml(raw, vision=self.vision)
                ch = pm.channel
                sender = (ch.get("sender") or "").casefold()
                if sender not in self.allowed:
                    self._note(sender=sender, subject=ch.get("subject", ""), status="ignored", why="sender not on the allow-list")
                    self.ignored += 1
                    continue
                if self.require_auth and "pass" not in (ch.get("auth") or {}).values():
                    self._note(sender=sender, subject=ch.get("subject", ""), status="ignored",
                               why="no SPF/DKIM/DMARC pass reported for this sender")
                    self.ignored += 1
                    continue
                self.handler(pm.text, ch, pm.notes)
                self._note(sender=sender, subject=ch.get("subject", ""), status="processed", why="")
                self.processed += 1
                n += 1
            self.last_error = None
        except (imaplib.IMAP4.error, OSError) as e:
            self.last_error = self._scrub(f"{type(e).__name__}: {e}")[:200]
        finally:
            try:
                if box is not None:
                    box.logout()
            except Exception:  # noqa: BLE001
                pass
        return n
