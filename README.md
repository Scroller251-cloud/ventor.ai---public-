# Ventor AI — Public Security Surface

This repository is the **public, deliberately scrubbed publication surface** for Ventor AI. It is not assumed to be a byte-for-byte mirror of the private development repository.

Ventor is designed as a local-first adaptive cognitive operating environment. The broader private development line includes durable runs, adaptive model routing, memory, agents/tools, verification, learning telemetry, and a governed Chief/Supervisor layer.

## Public-repository rule

Only material deliberately cleared for publication belongs here. Do not commit API keys, passwords, private keys, certificates, recovery credentials, authorization secrets, local databases, logs, model weights, `.env` files, runtime state, personal data, private operational endpoints, or unreviewed internal material.

The public repository may contain security primitives and documentation without containing the private authorization material they depend on.

## Security design

Ventor treats model output, uploaded content, retrieved documents, webpages, and tool responses as untrusted input. Tool access is capability- and risk-scoped. The Chief/Supervisor is governed and cannot grant itself credentials, remove its own controls, disable required human approval, or silently expand security boundaries.

See `SECURITY.md` for the public security policy.

## Source and release claims

A public commit is not considered a release candidate merely because it is present in Git. Release claims require reproducible tests, CI evidence for the exact commit, security review, and a deliberate publication decision.
