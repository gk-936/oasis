# API authorization sweep (offline)

Run: 2026-10-14 21:52

**Caveat.** Reads the allowed roles from the code's own require(...) dependencies and checks the responses. It does not check that the roles themselves are the right ones; that is the security evidence matrix and a human review.

| Check | Result |
|---|---|
| Route/method pairs | 94 |
| Calls made (4 identities, 2 bodies) | 752 |
| Routes without a role dependency (public) | 14 |
| Findings | 0 |

## Findings

None.

## Public routes seen

- `GET /api/auth/config`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/passkey/login/finish`
- `GET /api/evidence-passport/check/{code}`
- `POST /api/evidence-passport/verify`
- `GET /api/health`
- `POST /api/proof/verify`
- `GET /api/proof/{intent_id}/verify`
- `POST /api/reliability/verify`
- `GET /api/trust-pass/check/{code}`
- `POST /api/trust-pass/vc/verify`
- `POST /api/trust-pass/verify`
- `GET /api/trust/fingerprint`
