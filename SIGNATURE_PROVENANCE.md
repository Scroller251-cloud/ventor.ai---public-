# Ventor Signature Provenance

Ventor has no Owner Gate and does not require an application login/passphrase.

Documents and release artifacts may carry detached Ed25519 signatures containing creator identity, public-key fingerprint, SHA-256 digest, timestamp, document type, metadata, and signature.

The private signing key stays on the operator's machine and is never committed to the open-source repository. Signature provenance establishes authorship/integrity; it is not authorization. High-risk host actions remain sandboxed and require explicit confirmation.
