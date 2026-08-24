# Security policy

## Scope

Security-sensitive components include authentication, authorization, command tokens, memory isolation, provider credentials, browser navigation, research, sandboxing and deployment configuration.

## Reporting

Do not disclose suspected vulnerabilities, credentials, private keys or personal data in public issues. Report security problems privately to the repository maintainers with reproduction details and impact. Use GitHub's private vulnerability reporting if enabled.

## Secrets

Runtime authorization rosters and private credentials must be supplied through secure deployment storage or environment/secret-management facilities. Source-code changes alone must never grant administrative access.

## Security invariants

1. Private keys and provider secrets never belong in source control.
2. Privileged commands require owner/team-admin authorization.
3. Command tokens are short-lived, one-time and principal-bound.
4. Persistent memory is namespaced by authenticated principal and session.
5. Untrusted code never falls back to host execution when Docker isolation is unavailable.
6. Learning cannot directly modify or approve core code.
7. External evidence is not treated as factual merely because a URL is syntactically valid.
8. Mandatory release gates must pass; skipped external tests are not passes.
