# Security Policy

Ventor does not store Creator private keys, recovery credentials, API keys, passwords, or production secrets in Git.

## Creator and Co-Creator

The human-readable Creator identity is `VENTOR-CREATOR-SUJAL-AJAY-KALE`. Authentication is proof-of-possession of a configured cryptographic key. Co-Creators have broad operational authority but cannot replace, revoke, disable, or override the Creator root.

## Reporting

Do not disclose suspected vulnerabilities, credentials, private keys, or personal data in public issues. Report security problems privately to the maintainers with reproduction details and impact.

## Secrets

Runtime authorization rosters and private credentials must be supplied through secure deployment storage or environment/secret-management facilities. Source-code changes alone must never grant administrative access.
