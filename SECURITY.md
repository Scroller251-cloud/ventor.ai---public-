# Security Policy

Ventor treats model output, retrieved content, uploaded files, webpages, and external tool responses as **untrusted input**. This public repository must never contain secrets or private runtime state.

## Creator and Co-Creator

The human-readable Creator identity is `VENTOR-CREATOR-SUJAL-AJAY-KALE`. Authentication is proof-of-possession of a configured cryptographic key. Editing source code or role metadata must never be sufficient to become Creator.

Co-Creators may have broad operational authority but cannot replace, revoke, disable, or override the Creator root.

## Chief / Supervisor

The Chief is a governed meta-control layer. It must not grant itself credentials, remove or weaken its own controls, disable required human-approval gates, or silently expand network, filesystem, browser, or tool authority.

Operational policy changes should be versioned, evidence-backed, regression-checked, and reversible. Security-sensitive or authority-expanding changes require human approval.

## Tools and agents

Tool access is capability- and risk-scoped. Model output is never an authorization grant. Prompt injection and hostile instructions embedded in webpages, files, or tool results must be treated as untrusted content.

Destructive, credential-bearing, irreversible, or authority-expanding actions require stronger controls than read-only operations. Unbounded autonomous loops are prohibited.

## Memory and persistence

Memory is a persistence boundary. Retrieved text must not automatically become trusted policy or durable instruction. Memory promotion should retain provenance and confidence and resist poisoning. Durable runs should use explicit state transitions, cancellation, checkpoints, and idempotency so retries do not duplicate non-idempotent side effects.

## Secrets

Never commit API keys, passwords, private keys, certificates, recovery credentials, authorization rosters containing secrets, production data, local databases, logs, model weights, `.env` files, or other private runtime material.

If a secret is accidentally committed, treat it as compromised: revoke/rotate it first, then remove it from repository history as appropriate. Deleting the visible file alone is not sufficient.

## Reporting

Do not disclose suspected vulnerabilities, credentials, private keys, or personal data in public issues. Report security problems privately to the maintainers with reproduction details and impact. Runtime authorization rosters and private credentials must come from secure deployment storage; source-code changes alone must never grant administrative access.
