# Ventor.ai

Ventor is a local-first multi-agent AI runtime focused on reliable routing, evidence-gated learning, persistent private memory, and fail-closed privileged tooling.

## Architecture

```text
Qwen + Gemma
    ↓
independent candidates
    ↓
claim comparison / debate
    ↓
evidence-gated verification
    ↓
verified lesson
    ↓
persistent learning record
```

Privileged capabilities are outside the model's authority boundary. They require authenticated owner/team-admin authority, explicit confirmation for high-risk actions, short-lived principal-bound command tokens, and a sandbox boundary.

## Performance and reliability

- Reused async HTTP clients for model/provider traffic.
- Parallel independent mentor calls.
- Bounded rate-limiter cardinality with amortized pruning.
- Thread-local SQLite connections with WAL and batched writes.
- Cached hardware telemetry.
- Append-only learning records with bounded recent-lesson reads.
- Provider timeouts, circuit breakers, fallback and latency telemetry.
- Docker execution is fail-closed when isolation is unavailable.

## Run locally

```bash
python -m venv .venv
# activate the environment
python -m pip install -r requirements.txt
uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

For owner authentication, configure `VENTOR_AUTH_ROSTER` and create a roster containing public Ed25519 keys. Never commit private keys, credentials, runtime databases or workspace data.

## Test

```bash
python -m compileall -q backend Ventor_2_9 tests
python -m pytest -q
python backend/stress_tests.py
```

## Docker

```bash
docker compose up --build
```

## Production boundary

The repository can certify deterministic code, security and resource behavior, but live certification still requires the target Ollama models, Docker runtime, real owner roster, intended hardware and provider credentials. A skipped external test is never treated as a pass.

## Security

See `SECURITY.md` and `AGENT_POLICY.json`.
