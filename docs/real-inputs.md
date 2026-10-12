# Real invoice intake (email, Telegram, mailbox)

Invoices do not have to be pasted. Three real channels feed the same pipeline as the paste box. None of them adds authority: a payment still needs the student's signed approval in the app.

| Channel | Needs | How to use it |
|---|---|---|
| **Email file (.eml)** | nothing | Chat tab, "Upload email (.eml)". In a mail app: Save as / Download message. Works on any server, including the offline judge sandbox. |
| **Telegram bot** | `OASIS_TELEGRAM_TOKEN` (from BotFather) | Chat tab, "Other ways to send an invoice", "Get pairing code", then send `/pair CODE` to the bot. Forward text, a photo, a PDF or an .eml; the verdict comes back in the chat. |
| **Mailbox watcher (IMAP)** | `OASIS_IMAP_HOST`, `OASIS_IMAP_USER`, `OASIS_IMAP_PASSWORD`, `OASIS_IMAP_ALLOWED_SENDERS` | A dedicated mailbox (use an app password). Allow-listed, authenticated senders are processed; everything else is marked read and ignored with no reply. |

**Where each one works.** Telegram is blocked in mainland China without a VPN (so is WhatsApp), and the intended student lives in China: treat the bot as optional, for parents or anyone outside China. The .eml upload needs nothing and works everywhere; the mailbox watcher works with any IMAP mailbox that is reachable from the server (QQ and 163 mail work from China, Gmail is unreliable there). WeChat would be the natural chat channel for China, but a bot needs a registered Official Account or Enterprise WeChat, so it is future work, not built.

## What an email adds to the risk score (evidence only)

From the real headers of the message: SPF/DKIM/DMARC failure reported by the receiving server, a `Reply-To` on a different domain than the sender (business-email compromise), a free-mail address behind an institutional display name, and text styled to be invisible (the classic prompt-injection carrier; it is kept in the text so the injection detector sees it). A forged test email reaches risk 0.98 and is rejected at the verify step; the genuine one scores 0 and is held for the student's signature.

## Safety rules

- **Untrusted input.** Message content goes through the normal extraction, verification, policy and executor; the channel changes the evidence, never the decision rules.
- **Telegram:** nothing is processed until a chat is paired with a one-time code (10 minutes, single use, at most 5 outstanding). Strangers get one refusal per minute. Replies are plain text and long digit runs (account numbers) are masked, so an attacker's account is never echoed. The token is scrubbed from every stored error.
- **IMAP:** an explicit sender allow-list is required (the server refuses to start the watcher without one). By default (`OASIS_IMAP_REQUIRE_AUTH=1`) a message is processed only if the receiving server reports SPF, DKIM or DMARC = pass; a missing header is treated as untrusted. A message is marked read before it is processed, so a crash cannot cause a loop. No auto-reply is sent.
- **Attachments:** text and PDF (text layer, if `pypdf` is installed) are read, images go to the vision model when one is configured; at most 5 attachments and 12 MB.

## What is and is not verified

Tested with fake servers (Telegram Bot API via an httpx mock transport, IMAP via a fake box) and, for the .eml upload, in real Chrome at desktop and phone width. **Not tested against the live Telegram or a live mailbox**: that needs a bot token and a mailbox that the repository does not have. `Authentication-Results` is only as trustworthy as the mail server that wrote it, and an uploaded .eml can carry any header.

See [configuration.md](configuration.md) for the variables.
