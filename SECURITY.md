# Ventor Security Model

## Authority

Ventor has four operational classes:

- **Root owner — Ventor Owner:** complete authority over non-root principals and core configuration.
- **Team admin — Ventor Team Admin:** operational and core-editing authority except the immutable root owner.
- **AI agents:** may participate in learning, debate and verification, but cannot administer Ventor, change the authorization roster, become an owner/admin, or self-approve core changes.
- **Public:** may use explicitly public endpoints, but has no source/core or administrative authority.

The root identity `VENTOR-OWNER-LOCAL` is cryptographically protected. No API caller, team admin, AI agent, or public user can remove, disable, demote, replace, or transfer it.

## Authentication

Privileged identities authenticate using Ed25519 challenge/response. Long-lived private keys are never sent to Ventor. Sessions are short-lived and command tokens are one-time and principal-bound.

Runtime credentials are local-only and ignored by Git. Public templates contain placeholders only.

## Public access

Public chat/model/health endpoints do not imply administrative permission. Every privileged operation performs a server-side role check.

## AI learning

External models are mentors/candidates, not administrators. Their outputs are independently debated and verified before becoming persistent lessons. Lessons do not automatically modify Ventor core code.

## Execution boundary

Arbitrary generated code is deny-by-default. Host execution is not used as a fallback for sandbox failures.

## Repository vs runtime

The public Git repository is a sanitized release surface. Runtime authorization is separately enforced by the backend. `CODEOWNERS` provides repository review controls; it is not a substitute for backend authorization.
