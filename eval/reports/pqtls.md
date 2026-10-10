# Post-quantum TLS evidence (X25519MLKEM768), 2026-10-10

Server: Caddy v2.11.7 (Apache-2.0), built with go1.26.8 (`caddy build-info`; Go >= 1.24 ships X25519MLKEM768).
Config: `tools/caddy/Caddyfile` (`tls internal`, `curves x25519mlkem768`, TLS 1.3 only) reverse-proxying uvicorn on 127.0.0.1:8000.
Client: OpenSSL 3.5.9 built from source inside the `oasis-fisco` WSL distro (D:), connecting to the Windows host.
Certificate trust: Caddy's local internal CA root (`Verification: OK`); the root was NOT installed into any OS trust store.

## Command

    tools\caddy\verify-pq.ps1      (runs tools/caddy/pq-client.sh in the distro)

    echo | openssl s_client -connect <host>:8443 -servername localhost -CAfile root.crt -groups X25519MLKEM768 -tls1_3
    echo | openssl s_client -connect <host>:8443 -servername localhost -CAfile root.crt -groups X25519 -tls1_3

## Output (filtered)

    === groups=X25519MLKEM768
    Negotiated TLS1.3 group: X25519MLKEM768
    Verification: OK
    New, TLSv1.3, Cipher is TLS_AES_128_GCM_SHA256
    Protocol: TLSv1.3
    === groups=X25519
    ...ssl/tls alert handshake failure... SSL alert number 40
    Negotiated TLS1.3 group: <NULL>

A classical-only client is refused (no downgrade) because the Caddyfile offers only the hybrid group.
A second client, curl 8.22.0 (LibreSSL 4.3.3, Windows), connected with its defaults (so it offers the hybrid group)
and was refused with `--curves X25519`; LibreSSL does not print the group name, so OpenSSL is the evidence of record.

## Caveats

- Hybrid key exchange only: the certificate is still classical (ECDSA from Caddy's internal CA).
- Restricting to one group is a demo/strictness choice; for public sites keep classical groups for older clients.
- Chrome/Edge >= 131 and Firefox offer X25519MLKEM768 by default (not tested here).
