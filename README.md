# Ventor.ai — Multi-Agent Mentor Core

Ventor combines local AI mentors, external providers, debate/verification, persistent lessons, memory, adaptive resource management, and a deny-by-default execution boundary.

## Mentor learning

The core learning path is:

Qwen + Gemma + permitted external mentors
→ independent candidates
→ debate
→ verification/evidence checks
→ conservative lesson extraction
→ persistent verified lessons
→ future mentor context.

Lessons do not directly modify Ventor core. Core changes remain an administrative action.

### Testing without Ollama

Set `MOCK_LLM=true` to make Qwen/Gemma mentors return deterministic synthetic candidates. This exercises the real debate → verification → lesson-extraction → persistence path while replacing only the bottom-level model call. No network call is made in this mode.

## Security boundary

Generated code is deny-by-default. Arbitrary code is never executed directly on the host. Public users and AI agents cannot turn learning output into administrative authority.

Runtime authorization is enforced server-side; repository review rules are a separate layer.

## Provider-neutral routing

Ventor can use optional Ollama, OpenRouter, NVIDIA NIM, Bytez, OpenAI, Anthropic, and Gemini providers. Configure credentials through environment variables; blank providers remain disabled.

## Adaptive RAM

Ventor uses a Memory Waterline / RAM Lease controller. It estimates model weights, runtime overhead, KV-cache context, OS reserve, and available memory before local inference.

- **Green:** normal operation.
- **Amber:** reduce transient context, batch, and concurrency before changing models.
- **Red:** minimize the working set and fall back when necessary.

Hardware limits and external-provider quotas remain real constraints.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:MOCK_LLM='true'
uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

For real local inference, configure Ollama and the desired model/provider settings in `backend/.env`.

## Tests

```bash
python -m pytest -q
```

The public repository is a sanitized release surface. Runtime credentials, databases, model weights, recovery material, and private deployment state are intentionally excluded.
