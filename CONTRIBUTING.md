# Contributing to Ventor

## Development

Create a feature, fix, security, or performance branch from `main`. Keep changes focused and provide tests for behavior changes.

## Pull requests

All changes to `main` must go through a pull request. Do not force-push or directly rewrite release history.

Before opening a pull request:

1. Run the full test suite.
2. Run Python compilation checks.
3. Run security/dependency checks when dependencies or security-sensitive code changes.
4. Update documentation for user-visible or operational changes.
5. Never commit `.env` files, credentials, private keys, recovery material, runtime databases, model weights, or personal data.

Security-sensitive changes require repository-owner review through CODEOWNERS.

## Commit quality

Use clear, focused commits. Avoid mixing unrelated refactors with fixes.

## Public/private boundary

The public repository contains the sanitized open-source distribution. Private operational credentials, protected infrastructure, recovery material, and other sensitive development state must remain outside this repository.
