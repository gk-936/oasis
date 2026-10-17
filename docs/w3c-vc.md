# W3C Verifiable Credentials export of the Trust Pass

The native Trust Pass (`oasis/proof/trust_pass.py`) is unchanged. `oasis/proof/vc_export.py` adds a second, standards-shaped
view of the same signed credential.

- `POST /api/trust-pass/vc/export` (student): body `{"holder": {"credential": ...}}`, returns the VC. Refused (400) unless the credential verifies against this server's key.
- `POST /api/trust-pass/vc/verify` (public): checks a pasted VC against this server's pinned key.
- Python: `export_vc(holder, signer)`, `verify_vc(vc, trusted_fingerprints=None)`, `import_vc(vc)` (returns the native credential, raises `ValueError` on any failure).
- UI: "Export as W3C VC" next to the JSON download on the Trust Pass tab.

## Shape

`type: ["VerifiableCredential", "OasisTrustPass"]`; `issuer` is a `did:key` (Ed25519, multicodec `0xed01`, base58btc multibase `z6Mk...`) made from the server's existing Ed25519 trust key. `credentialSubject` carries `claims`, `paymentCommitments` (the salted payment digests), `zkCommitments` (Pedersen commitments for the zero-knowledge thresholds) and `audience`. Salts and ZK openings are never exported, so the holder still chooses what to reveal. The subject `id` is a pseudonymous `did:key` derived from the Trust Pass pseudonym; its seed is public, so it names the subject but proves no key possession (no holder binding). The full native credential, with its hybrid Ed25519 + ML-DSA-65 signatures, is embedded under `evidence`; `verify_vc` checks both proofs and that the VC fields equal the native ones.

## What is spec-conformant

- VC Data Model 1.1 envelope: `@context`, `type`, `issuer`, `issuanceDate`, `expirationDate`, `credentialSubject`, `proof`, `evidence`.
- `did:key` encoding and resolution for Ed25519 (the verification method is derived from the DID itself).
- `proofValue` is a multibase base58btc Ed25519 signature; `proof.type` is `Ed25519Signature2020`.

## What is not

- The signature covers Oasis sorted-key canonical JSON (`proof.canonicalization = "oasis-sorted-json-v1"`), not RDF Dataset Canonicalization (URDNA2015) over JSON-LD. A stock Ed25519Signature2020 / Data Integrity verifier will therefore reject it; use `verify_vc`. The signature input is the VC with `proof` present minus `proofValue`.
- The Oasis terms use an inline `@vocab` placeholder (`https://oasis.example/vocab#`), not a published context; the JSON-LD is not validated against a schema. `proof` has one extra non-standard property (`canonicalization`).
- Only the Ed25519 half of the hybrid signature is in the VC proof; the post-quantum ML-DSA-65 signature lives in the embedded native credential. There is no DID revocation, rotation or `did:web`.
- No holder-bound Verifiable Presentation is produced. Trust in the issuer is by pinned fingerprint (`key_pinned`), as with the native pass: a `did:key` is self-certifying but says nothing about who controls it.
- Sandbox credential, not a credit score (see README, limitation 6).
