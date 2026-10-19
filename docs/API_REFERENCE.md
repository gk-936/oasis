# Oasis API reference for graders

`/docs`, `/redoc` and `/openapi.json` are off in judge mode, so this page lists the five endpoints a grader needs to run a task end to end. All money is simulated (MOCK). Replace `BASE` with the hosted address (for example `https://oasis.koreacentral.cloudapp.azure.com`) or `http://127.0.0.1:8000`.

The chain for any payment is always the same: **chat creates a draft, the student's device key signs that exact draft, the executor releases it.** Nothing in chat can approve or sign, and a role string grants nothing.

| Endpoint | Role | Purpose |
|---|---|---|
| `POST /api/auth/login` | public | Start a session (cookie, or a bearer token with `?return_token=true`) |
| `POST /api/reset` | student | Reset the sandbox to the seeded state |
| `POST /api/device/register` | student, parent | Register the Ed25519 public key that will sign approvals |
| `POST /api/chat` | student | One natural-language turn |
| `GET /api/chat/checkin` | student | Once per session: what is due soon, the shortfall and an offer |
| `GET /api/agent-scorecard` | student, judge | The agent's record and live mandate, read from the audit log (read-only) |
| `GET /api/state` | student, parent, judge | Balances, bills, rates, pending drafts, registered device keys |
| `POST /api/approve` | student, parent | Release a pending draft with a device-key signature |
| `GET /api/health` | public | Liveness (`200`) |

## 1. `POST /api/auth/login`

```bash
curl -s -c jar.txt -X POST "$BASE/api/auth/login?return_token=true" \
  -H 'Content-Type: application/json' \
  -d '{"role":"student","passcode":"<student passcode>"}'
```

```json
{"role": "student", "expires_at": "2026-10-20T10:30:00+00:00", "token": "<session token>"}
```

- Roles: `student`, `parent`, `judge`. The judge role is read-only.
- Use the cookie jar (`-b jar.txt`) or send `Authorization: Bearer <token>` on later calls. The `token` field appears only with `?return_token=true`.
- A wrong role or passcode returns `401`; repeated failures return `429` with `Retry-After`.
- Judge mode logs a session out after the configured lifetime (`OASIS_SESSION_TTL_S`, default 3600 s). Log in again if you get `401`.

## 2. `POST /api/reset`

```bash
curl -s -b jar.txt -X POST "$BASE/api/reset"
```

```json
{"ok": true}
```

Student only. Restores the seeded sandbox (bills, balances, no drafts). Call it before a scripted run. If `GET /api/state` then shows `devices.student: null`, register the device key again.

## 3. `POST /api/chat`

```bash
curl -s -b jar.txt -X POST "$BASE/api/chat" \
  -H 'Content-Type: application/json' \
  -d '{"message":"pay my rent"}'
```

```json
{
  "reply": "Draft ready: pay CNY 6,000 to Chen Wei (registered account ****0001) for rent. ... It moves only after you sign this exact draft (#8dc8914ce5) with your device key. Tap Sign and approve.",
  "intent": "pay_obligation",
  "status": "held",
  "pending_id": "pend_deab9777",
  "draft_hash": "8dc8914ce5a327bdcaf84499bb49c334ef622d36cbd9e7cb9c5852594653e836",
  "needs": ["student_signature"],
  "money_moved": 0.0,
  "proof_id": null,
  "source": "router"
}
```

Request: `{"message": "<up to 20000 characters>"}`. Add `?lang=zh` to answer in Chinese (English is the default; Hindi and Tamil messages are recognised from the text itself).

Every reply carries the same machine-readable fields, so a script can score a task without reading the prose:

| Field | Meaning |
|---|---|
| `intent` | What the router understood (`pay_obligation`, `fx_bill`, `routes`, `scam_check`, `scam_warning`, `share_record`, `where`, `plan`, `faq`, `scorecard`, `revoke`, ...) |
| `status` | `held` (a draft waits for a signature), `paid`, `refused`, `needs_info`, `needs_confirmation`, `cancelled`, `done`, `info`, `unknown`, `rejected` |
| `pending_id` | The draft to sign, or `null` |
| `draft_hash` | SHA-256 of the exact draft; this is what the device key signs |
| `needs` | `student_signature`, `parent_signature`, or `info:<slot>` (a question still to answer) |
| `money_moved` | CNY moved by this turn. A draft moves nothing, so it is `0` |
| `proof_id` | Proof pack id once a payment has executed |

Examples that finish inside chat (each ends at a draft, an advice-only answer or a refusal; none can release money):

| Message | Result |
|---|---|
| `pay my rent` | `status: held`, a draft to the registry account |
| `I need to pay a USD application fee of 100 dollars` | `intent: fx_bill`, a USD draft to the fixed MOCK university, `status: held` |
| `share my payment record with my landlord` | `intent: share_record`, `status: done`, `share_link` for the Trust Pass (not a credit score) |
| `where is my tuition transfer?` | `intent: where`, status and advice for that transfer |
| `plan my semester`, then `pay the deposit` | a plan proposal, then a draft for the earliest bill |
| `is this a scam? <pasted message>` | `intent: scam_check`, `verdict`, `risk_score`, `evidence`; no draft |
| `my bank quoted ¥6,550 for ₹1,00,000, is that fair?` | `intent: markup_check`, `implied_rate`, `markup_pct`, `cheapest_cny` |
| `approve it` / `sign it` | refused or pointed to the draft; chat cannot sign |
| `my tuition is due on Friday` | `intent: obligations`: the tuition line and "Want me to draft the payment?"; a following `yes` makes the draft (still unsigned) |
| `what's in my account and what do I owe` | one reply with a `Balance:` part and an `Open bills:` part |
| `pay my rent then check my balance` | one held draft plus the balance; a second payment in the same message is queued until `next` |
| `and my phone?` after `pay my rent` | the same action for the phone bill (a draft, still unsigned); context lasts 6 turns |
| `The embassy officer called, I have to transfer 20000` | `intent: scam_warning`, `status: refused`, no draft |
| `stop my autopay` / `remove the rate alert` | `intent: revoke`, `status: held`: a draft that ends the instruction only after the device-key signature |
| `how are you doing` / `what is your mandate` | `intent: scorecard` / `mandate`: counts from the audit log, and the agent's cap |

`GET /api/chat/checkin` returns `{"reply": "Living CNY 150 is due in 3 day(s); you're CNY 42,150 short. Want a plan?", "intent": "checkin", ...}` the first time it is called in a session and `{"reply": null, ...}` afterwards. A following `yes` in `/api/chat` continues into the plan.

`GET /api/agent-scorecard` (student or judge, read-only) returns `acted_alone_tier1`, `drafts_waiting_for_you`, `refusals_by_reason`, `scam_warnings`, `canary_freezes`, `money_lost_cny`, `audit_head`, `audit_chain_ok`, `caps` (the Tier-1 limit and each active standing instruction with its id, kind, cap, interval, `payee_id` and `rate`) and a one-sentence `mandate_card`. Every number comes from the audit log, the passport or the pending list.

## 4. `POST /api/approve` (how to sign a draft)

Release a draft by signing its hash with the device key registered for your role.

1. Generate an Ed25519 key pair. Keep the private key; send only the public key (base64).
2. Register it once per session:

```bash
curl -s -b jar.txt -X POST "$BASE/api/device/register" \
  -H 'Content-Type: application/json' -d '{"public_key":"<base64 public key>"}'
# {"role":"student","key_id":"ad3a1b7b692b6e48","active":true}
```

3. Read the draft from `GET /api/state` (`pending[].draft.draft_hash`, or the `draft_hash` already in the chat reply).
4. Sign the message `oasis-approval-v1|<role>|<draft_hash>` (UTF-8) with the private key and base64 the 64-byte signature.
5. Send it:

```bash
curl -s -b jar.txt -X POST "$BASE/api/approve" \
  -H 'Content-Type: application/json' \
  -d '{"pending_id":"pend_deab9777","signature":"<base64 signature>","key_id":"ad3a1b7b692b6e48"}'
```

Python (PyNaCl):

```python
import base64, requests
from nacl.signing import SigningKey

sk = SigningKey.generate()
pub = base64.b64encode(bytes(sk.verify_key)).decode()
s = requests.Session()
s.post(f"{BASE}/api/auth/login", json={"role": "student", "passcode": PASSCODE})
key_id = s.post(f"{BASE}/api/device/register", json={"public_key": pub}).json()["key_id"]

draft = s.post(f"{BASE}/api/chat", json={"message": "pay my rent"}).json()
msg = f"oasis-approval-v1|student|{draft['draft_hash']}".encode()
sig = base64.b64encode(sk.sign(msg).signature).decode()
paid = s.post(f"{BASE}/api/approve", json={"pending_id": draft["pending_id"], "signature": sig, "key_id": key_id}).json()
print(paid["status"], paid.get("proof_id"))
```

Responses:

- `200` with the outcome (`status`: `paid`, or `held` if another approval is still missing). When a parent must co-approve, the response is `{"status": "waiting", "missing": ["parent"], ...}` until the parent signs with their own key from their own session.
- `403` when the signature does not verify for this exact draft (wrong key, edited draft, wrong role) or when no signature is sent. The attempt is written to the audit log.
- `410` when the draft expired (`not_after`); ask for a fresh draft.
- `{"pending_id": "...", "approve": false}` declines a draft (`{"status": "declined"}`).

The executor then re-checks the signed intent (signature, exact match, nonce, expiry, policy). Money only ever goes to the registry account, never to an account read from a message.

## 5. `GET /api/state`

```bash
curl -s -b jar.txt "$BASE/api/state"
```

Returns one JSON object. The fields a grader usually needs:

| Field | Content |
|---|---|
| `passport.obligations` | Open and paid bills (`id`, `type`, `payee_id`, `amount`, `currency`, `due`, `status`) |
| `passport.balances` | Balances per currency |
| `pending` | Drafts waiting for a signature: `id`, `required` (roles), `draft.draft_hash`, `draft.amount`, `draft.account_ref` |
| `devices` | Registered device key id per role (`null` until registered) |
| `proofs` | Proof pack ids of executed payments |
| `rate_mid`, `rates`, `routes` | Today's MOCK rate with its source badge and the route comparison |
| `canaries_tripped`, `ledger_money_lost` | Security signals (`false` and `0` on a clean run) |

The parent role gets a reduced view: only `pending` items that need the parent, plus proofs. Proof packs can be fetched with `GET /api/proof/{intent_id}` and verified with `GET /api/proof/{intent_id}/verify`; the audit chain with `GET /api/audit/verify`.

## Errors

| Code | Meaning |
|---|---|
| `401` | Not logged in, or the session expired |
| `403` | Wrong role for the endpoint, or a signature that does not verify |
| `410` | Draft expired |
| `422` | Body does not match the schema (unknown fields are rejected) |
| `429` | Too many failed logins or too many requests |

## What this API cannot do

There is no endpoint, flag or debug mode that approves a payment without a device-key signature, sends money to an account from a message, or edits the audit log. See `docs/security-evidence-matrix.md` for the tests behind each rule.
