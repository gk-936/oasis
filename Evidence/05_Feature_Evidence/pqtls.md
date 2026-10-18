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

## Re-run on 2026-10-16 (Go reference server, not Caddy)

The Caddy binary and the `oasis-fisco` WSL distro used on 2026-10-10 are no longer on this machine, so Caddy itself was NOT re-run.
Instead `tools/caddy/pq-selfcheck/main.go` (go1.26.6, standard library `crypto/tls`, the same TLS stack Caddy uses) serves TLS 1.3 with
`CurvePreferences = [X25519MLKEM768]` only, the same policy as `tools/caddy/Caddyfile`, on 127.0.0.1:8444 with a throwaway self-signed
certificate. Client: OpenSSL 3.5.5 (Windows, MSYS2), run with `-CAfile` pointing at that certificate.

    go build -o pqsrv.exe .   (in tools/caddy/pq-selfcheck)   then run pqsrv.exe

    echo | openssl s_client -connect 127.0.0.1:8444 -servername localhost -CAfile cert.pem -groups X25519MLKEM768 -tls1_3
    echo | openssl s_client -connect 127.0.0.1:8444 -servername localhost -CAfile cert.pem -groups X25519 -tls1_3

Output (filtered):

    === groups=X25519MLKEM768
    Negotiated TLS1.3 group: X25519MLKEM768
    Verification: OK
    New, TLSv1.3, Cipher is TLS_AES_128_GCM_SHA256
    Protocol: TLSv1.3
    === groups=X25519
    ...ssl/tls alert handshake failure... SSL alert number 40
    Negotiated TLS1.3 group: <NULL>

Caveats: this shows the Go TLS stack and the pinned-curve policy negotiate the hybrid group and refuse a classical-only client; it is not
a run of the Caddy proxy in front of Oasis. Certificate is classical and self-signed; OpenSSL client only; the app itself still serves plain HTTP.

## Browser test on 2026-10-17 (Chrome 155, Go reference server)

Server: the same `tools/caddy/pq-selfcheck` Go server as the 2026-10-16 re-run (TLS 1.3 only, `CurvePreferences = [X25519MLKEM768]`), listening on 127.0.0.1:8444 with a throwaway self-signed certificate; a local OpenSSL 3.5.5 client again negotiated X25519MLKEM768 against it first.
Client: Google Chrome 155.0.8059.80 (Windows), default settings, no flags. Opened `https://127.0.0.1:8444`, clicked through the certificate warning, read the connection section of the page-info panel:

    Connection - secure connection settings
    The connection to this site is encrypted and authenticated using TLS 1.3, X25519MLKEM768, and AES_128_GCM.
    Certificate - missing (net::ERR_CERT_AUTHORITY_INVALID)   [expected: self-signed, not trusted]

Caveats: Chrome on one machine. This is the Go reference server, not the Caddy proxy in front of Oasis. The certificate is classical and self-signed. Hybrid key exchange only.
