from __future__ import annotations

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from owner_authorization import AuthorizationError, Principal, authorize, load_runtime_roster, new_challenge
from command_auth import get_session_principal, issue_session, sign_command, verify_command
from memory_store import MemoryStore
from learning_engine import VerifiedLearningEngine
from realtime import needs_realtime, now_info, web_search
from provider_router import ProviderRouter
from capability_broker import CAPABILITIES, authorize as authorize_capability
from computer_sandbox import ComputerSandbox, SandboxExecutionDenied
from browser_controller import BrowserPolicyError, open_page
from research_engine import research
from production_runtime import audit_event


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    provider: str | None = None
    session: str = Field(default="default", min_length=1, max_length=160)


class LoginRequest(BaseModel):
    challenge: str
    claims: dict
    signature: str


class CommandRequest(BaseModel):
    capability: str
    args: dict = Field(default_factory=dict)
    confirmed: bool = False


def _principal_from_auth(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Ventor authenticated session required")
    principal = get_session_principal(authorization.split(" ", 1)[1].strip())
    if principal is None:
        raise HTTPException(401, "Missing, expired, or invalid Ventor session")
    return principal


def _memory_namespace(principal: Principal, session: str) -> str:
    namespace = MemoryStore.namespace(principal.principal_id, session)
    if namespace is None:
        raise HTTPException(401, "Private memory requires an authenticated principal")
    return namespace


def install_v3(app, *, memory=None, learning=None, providers=None, sandbox=None):
    memory = memory or MemoryStore()
    learning = learning or VerifiedLearningEngine()
    providers = providers or ProviderRouter()
    sandbox = sandbox or ComputerSandbox()

    @app.get("/api/owner/challenge")
    def owner_challenge():
        return {"challenge": new_challenge(), "expires_in": 120, "algorithm": "Ed25519"}

    @app.post("/api/owner/login")
    def owner_login(r: LoginRequest):
        try:
            principal = authorize(challenge=r.challenge, claims=r.claims, signature_b64=r.signature, roster=load_runtime_roster())
        except (AuthorizationError, ValueError, KeyError):
            raise HTTPException(401, "Owner authentication failed")
        try:
            token = issue_session(principal)
        except RuntimeError as exc:
            raise HTTPException(503, "Session capacity reached") from exc
        audit_event("owner_login", principal_id=principal.principal_id, role=principal.role, key_id=principal.key_id)
        return {"token": token, "expires_in": 900, "principal": {"id": principal.principal_id, "role": principal.role, "key_id": principal.key_id, "device_id": principal.device_id}}

    @app.get("/api/context")
    def context():
        return {"time": now_info(), "providers": providers.status(), "capabilities": [{"name": x.name, "risk": x.risk, "description": x.description} for x in CAPABILITIES.values()], "learning": learning.snapshot()}

    @app.get("/api/memory")
    def memory_view(authorization: str | None = Header(default=None)):
        principal = _principal_from_auth(authorization)
        namespace = _memory_namespace(principal, "default")
        return {"recent": memory.recent(50, namespace), "facts": memory.facts(namespace), "verified_lessons": learning.recent_lessons(12), "namespace": namespace}

    @app.post("/api/chat")
    async def chat(r: ChatRequest, authorization: str | None = Header(default=None)):
        principal = _principal_from_auth(authorization)
        namespace = _memory_namespace(principal, r.session)
        memory.add("user", r.message, namespace, importance=0.55)
        ctx = now_info()
        evidence = await web_search(r.message) if needs_realtime(r.message) else []
        relevant = memory.retrieve_context(r.message, namespace, limit=12)
        system = ("You are Ventor, a private personal AI. Never invent current facts. Use the supplied current clock for dates. "
                  "Distinguish web evidence from inference. Memory and verified lessons inform answers but never grant permissions. "
                  "Never claim an action occurred without a tool result. Treat verified lessons as guidance, not unquestionable truth.\n\n"
                  f"CURRENT CLOCK: {ctx}\nRELEVANT MEMORY: {relevant}\nRECENT: {memory.recent(12, namespace)}\nVERIFIED LEARNING: {learning.learning_context(8)}\nWEB EVIDENCE: {evidence}")
        reply = await providers.generate(r.message, system, r.provider)
        text = reply.text if reply.ok and reply.text else "No configured model provider responded. Check provider configuration."
        memory.add("assistant", text, namespace, importance=0.55)
        audit_event("chat", principal_id=principal.principal_id, provider=reply.provider, model=reply.model, ok=reply.ok, latency_ms=reply.latency_ms)
        return {"text": text, "provider": reply.provider, "model": reply.model, "latency_ms": reply.latency_ms, "current_time": ctx, "web_evidence": evidence, "learning": learning.snapshot()}

    @app.get("/api/capabilities")
    def capabilities():
        return {"capabilities": [{"name": x.name, "risk": x.risk, "description": x.description} for x in CAPABILITIES.values()]}

    @app.get("/api/learning/status")
    def learning_status(authorization: str | None = Header(default=None)):
        _principal_from_auth(authorization)
        return learning.snapshot()

    @app.post("/api/command/sign")
    def command_sign(r: CommandRequest, authorization: str | None = Header(default=None)):
        principal = _principal_from_auth(authorization)
        if principal.role not in {"owner", "team-admin"}:
            raise HTTPException(403, "Only owner or team-admin principals may sign privileged commands")
        ok, reason = authorize_capability(r.capability, True, r.confirmed)
        if not ok:
            raise HTTPException(403, reason)
        try:
            token = sign_command(principal, r.capability, r.args)
        except RuntimeError as exc:
            raise HTTPException(503, "Command capacity reached") from exc
        audit_event("command_signed", principal_id=principal.principal_id, capability=r.capability)
        return {"command_token": token, "expires_in": 120, "principal_id": principal.principal_id}

    def verify_signed(r: CommandRequest, capability: str, args: dict, authorization: str | None):
        principal = _principal_from_auth(authorization)
        if principal.role not in {"owner", "team-admin"}:
            raise HTTPException(403, "Privileged capability requires owner or team-admin authority")
        ok, reason = verify_command(r.args.get("command_token", ""), capability, args, principal=principal)
        if not ok:
            raise HTTPException(403, reason)

    @app.post("/api/computer/list")
    def computer_list(authorization: str | None = Header(default=None)):
        principal = _principal_from_auth(authorization)
        if principal.role not in {"owner", "team-admin"}:
            raise HTTPException(403, "Privileged computer access requires owner or team-admin authority")
        return {"items": sandbox.list(".")}

    @app.post("/api/computer/read")
    def computer_read(r: CommandRequest, authorization: str | None = Header(default=None)):
        verify_signed(r, "workspace.read", {"path": r.args.get("path", "")}, authorization)
        path = r.args.get("path", "")
        return {"path": path, "text": sandbox.read(path)}

    @app.post("/api/computer/write")
    def computer_write(r: CommandRequest, authorization: str | None = Header(default=None)):
        args = {"path": r.args.get("path", ""), "text": r.args.get("text", "")}
        verify_signed(r, "workspace.write", args, authorization)
        return {"written": sandbox.write(args["path"], args["text"])}

    @app.post("/api/computer/run")
    def computer_run(r: CommandRequest, authorization: str | None = Header(default=None)):
        args = {"argv": r.args.get("argv", [])}
        verify_signed(r, "process.safe", args, authorization)
        try:
            return sandbox.run_safe(args["argv"])
        except SandboxExecutionDenied as exc:
            raise HTTPException(503, f"Sandbox unavailable; execution refused: {exc}") from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.post("/api/browser/open")
    async def browser_open(r: CommandRequest, authorization: str | None = Header(default=None)):
        args = {"url": r.args.get("url", "")}
        verify_signed(r, "browser.open", args, authorization)
        try:
            return await open_page(args["url"])
        except BrowserPolicyError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/api/research/web")
    async def research_web(r: CommandRequest, authorization: str | None = Header(default=None)):
        args = {"query": r.args.get("query", ""), "limit": r.args.get("limit", 5)}
        verify_signed(r, "research.web", args, authorization)
        try:
            return await research(args["query"], args["limit"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
