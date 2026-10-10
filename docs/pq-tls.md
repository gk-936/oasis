# Post-quantum hybrid TLS (X25519MLKEM768): deployment recipe

## Status: NOT exercised in the demo build

The demo serves plain HTTP from uvicorn on localhost. Nothing in this repository negotiates X25519MLKEM768, and nothing here has been tested end to end. This page is a recipe for a deployment, not a result.

What was checked on the development machine (2026-10-10):

| Component | Version | ML-KEM / X25519MLKEM768 support |
|---|---|---|
| `.venv` Python `ssl.OPENSSL_VERSION` | OpenSSL 1.1.1t (7 Feb 2023) | No |
| Git-for-Windows `openssl` CLI | OpenSSL 3.2.3 | No (hybrid ML-KEM groups arrived in 3.5) |
| Caddy, nginx | not installed | not testable here |

Because no available OpenSSL is 3.5 or later, the negotiation could not be tested locally. The signature side (ML-DSA-65, FIPS 204) is separate and is implemented and tested; see `oasis/trust/crypto.py`.

## Recipe: reverse proxy terminating TLS in front of uvicorn

Python itself does not need to change. Terminate TLS in a proxy built against OpenSSL 3.5 or later (or any TLS stack with X25519MLKEM768, for example Go 1.24+ enables it by default), and keep uvicorn on loopback.

1. Run the app on loopback only: `uvicorn oasis.api.main:app --host 127.0.0.1 --port 8000`.
2. Caddy (built with Go 1.24 or later, where `X25519MLKEM768` is a default key-exchange group):
   ```
   oasis.example.com {
       reverse_proxy 127.0.0.1:8000
       tls {
           curves x25519mlkem768 x25519 secp256r1
       }
   }
   ```
   nginx alternative, built against OpenSSL 3.5 or later:
   ```
   ssl_protocols TLSv1.3;
   ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1;
   ```
3. Keep classical groups in the list so older clients still connect (the key exchange is hybrid, so security holds if either X25519 or ML-KEM-768 holds).

Note the scope: this protects confidentiality of traffic against "harvest now, decrypt later". Certificates are still classical (ECDSA or RSA) unless the CA ecosystem offers PQ certificates, which it does not yet widely.

## Checking the negotiated group

With an OpenSSL 3.5+ client:

```
openssl s_client -connect oasis.example.com:443 -groups X25519MLKEM768 -tls1_3 </dev/null 2>&1 | grep -i -E "Negotiated|group|Server Temp Key"
```

Expect a negotiated group of `X25519MLKEM768`. Forcing only that group means the handshake fails if the server does not support it, which is the useful test. Browsers: recent Chrome and Firefox offer X25519MLKEM768; the DevTools Security tab shows the key exchange group.

## What would make this tested

Install OpenSSL 3.5+ (or a Caddy build) on a Linux host or container, run the config above in front of the app, and record the `s_client` output. Until that is done this feature is documented-only.
