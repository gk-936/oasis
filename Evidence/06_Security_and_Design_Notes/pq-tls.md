# Post-quantum hybrid TLS (X25519MLKEM768): tested with Caddy

Status: tested with an OpenSSL client (2026-10-10)

Caddy v2.11.7 (Apache-2.0, go1.26.8; Go >= 1.24 supports X25519MLKEM768) terminates TLS 1.3 in front of uvicorn, configured to offer only `x25519mlkem768`. An OpenSSL 3.5.9 client reported `Negotiated TLS1.3 group: X25519MLKEM768`, and a classical-only X25519 client was refused. Also tested in a real browser (Chrome 155, 2026-10-17, Go reference server; see `eval/reports/pqtls.md`); the certificate is classical. Evidence, copied verbatim from `eval/reports/pqtls.md` (filtered `openssl s_client` output):

```
=== groups=X25519MLKEM768
Negotiated TLS1.3 group: X25519MLKEM768
Verification: OK
New, TLSv1.3, Cipher is TLS_AES_128_GCM_SHA256
Protocol: TLSv1.3
=== groups=X25519
...ssl/tls alert handshake failure... SSL alert number 40
Negotiated TLS1.3 group: <NULL>
```

Full command and output: `eval/reports/pqtls.md`.

The demo app itself still serves plain HTTP unless you run the proxy; the Python process is unchanged.

## Run

1. Caddy lives at `D:\china_hackathon\tools\caddy\caddy.exe` (download the Windows amd64 zip from the Caddy GitHub releases; not committed).
2. `uvicorn oasis.api.main:app --host 127.0.0.1 --port 8000`
3. `tools\caddy\start.ps1` serves `https://localhost:8443`. It sets XDG_DATA_HOME, XDG_CONFIG_HOME, CADDY_DATA and TEMP to folders under `D:\china_hackathon\tools\caddy`, so nothing is written under the user profile. Do not run `caddy trust` if you want to avoid touching the OS trust store; use the CA root at `tools\caddy\data\pki\authorities\local\root.crt` explicitly.
4. `tools\caddy\verify-pq.ps1` repeats the proof (needs OpenSSL 3.5+; here built in the `oasis-fisco` distro at `/opt/openssl35`).

## Notes

- `curves x25519mlkem768` is strict: clients without ML-KEM fail the handshake. For a public site remove it (Go's default prefers X25519MLKEM768 and keeps X25519/P-256 for older clients). nginx alternative with OpenSSL 3.5+: `ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1;`.
- Hybrid key exchange only protects confidentiality against harvest-now-decrypt-later. The certificate is classical (ECDSA from Caddy's internal CA). Signatures in Oasis (ML-DSA-65) are separate, see `oasis/trust/crypto.py`.
- Client support: Chrome/Edge 131+ and Firefox offer X25519MLKEM768 by default (not tested here). Python's `ssl` here is OpenSSL 1.1.1 and cannot negotiate it; curl 8.22 (LibreSSL 4.3.3) connected but does not display the group.
