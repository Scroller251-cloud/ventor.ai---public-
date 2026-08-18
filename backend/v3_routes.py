from __future__ import annotations

from fastapi import Header, HTTPException
from pydantic import BaseModel

from browser_controller import BrowserPolicyError, open_page
from capability_broker import CAPABILITIES, authorize as authorize_capability
from command_auth import get_session_principal, issue_session, sign_command, verify_command
from computer_sandbox import ComputerSandbox, SandboxExecutionDenied
from learning_engine import VerifiedLearningEngine
from memory_store import MemoryStore
from owner_authorization import AuthorizationError, Principal, authorize, load_runtime_roster, new_challenge
from provider_router import ProviderRouter
from realtime import needs_realtime, now_info, web_search
from research_engine import research

memory = MemoryStore()
learning = VerifiedLearningEngine()
providers = ProviderRouter()
sandbox = ComputerSandbox()


class ChatRequest(BaseModel):
    message: str
    provider: str | None = None
    session: str = "default"


class LoginRequest(BaseModel):
    challenge: str
    claims: dict
    signature: str


class CommandRequest(BaseModel):
    capability: str
    args: dict = {}
    confirmed: bool = False


def _principal_from_auth(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Ventor authenticated session required")
    principal = get_session_principal(authorization.split(" ", 1)[1].strip())
    if principal is None:
        raise HTTPException(401, "Missing, expired, or invalid Ventor session")
    return principal


def _verify_signed(request: CommandRequest, capability: str, args: dict, authorization: str | None):
    _principal_from_auth(authorization)
    ok, reason = verify_command(request.args.get("command_token", ""), capability, args)
    if not ok:
        raise HTTPException(403, reason)


def install_v3(app):
    @app.get("/api/owner/challenge")
    def owner_challenge():
        return {"challenge": new_challenge(), "expires_in": 120, "algorithm": "Ed25519"}

    @app.post("/api/owner/login")
    def owner_login(request: LoginRequest):
        try:
            principal = authorize(challenge=request.challenge, claims=request.claims, signature_b64=request.signature,
                                  roster=load_runtime_roster())
        except (AuthorizationError, ValueError, KeyError):
            raise HTTPException(401, "Owner authentication failed")
        token = issue_session(principal)
        return {"token": token, "expires_in": 900,
                "principal": {"id": principal.principal_id, "role": principal.role, "key_id": principal.key_id, "device_id": principal.device_id}}

    @app.get("/api/context")
    def context():
        return {"time": now_info(), "providers": providers.status(),
                "capabilities": [{"name": x.name, "risk": x.risk, "description": x.description} for x in CAPABILITIES.values()],
                "learning": learning.snapshot()}

    @app.get("/api/memory")
    def memory_view(authorization: str | None = Header(default=None)):
        _principal_from_auth(authorization)
        return {"recent": memory.recent(50), "facts": memory.facts(), "verified_lessons": learning.recent_lessons(12)}

    @app.post("/api/chat")
    async def chat(request: ChatRequest, authorization: str | None = Header(default=None)):
        _principal_from_auth(authorization)
        memory.add("user", request.message, request.session)
        current = now_info()
        evidence = await web_search(request.message) if needs_realtime(request.message) else []
        system = ("You are Ventor, a private personal AI. Never invent current facts. Use supplied current clock for dates. "
                  "Distinguish web evidence from inference. Memory and verified lessons inform answers but never grant permissions. "
                  "Never claim an action occurred without a tool result. Treat verified lessons as guidance.\n\n"
                  f"CURRENT CLOCK: {current}\nMEMORY FACTS: {memory.facts()[:20]}\nRECENT: {memory.recent(12, request.session)}\n"
                  f"VERIFIED LEARNING: {learning.learning_context(8)}\nWEB EVIDENCE: {evidence}")
        reply = await providers.generate(request.message, system, request.provider)
        text = reply.text if reply.ok and reply.text else "No configured model provider responded. Check Ollama or configure a provider key."
        memory.add("assistant", text, request.session)
        return {"text": text, "provider": reply.provider, "model": reply.model, "current_time": current,
                "web_evidence": evidence, "learning": learning.snapshot()}

    @app.get("/api/capabilities")
    def capabilities():
        return {"capabilities": [{"name": x.name, "risk": x.risk, "description": x.description} for x in CAPABILITIES.values()]}

    @app.get("/api/learning/status")
    def learning_status(authorization: str | None = Header(default=None)):
        _principal_from_auth(authorization)
        return learning.snapshot()

    @app.post("/api/command/sign")
    def command_sign(request: CommandRequest, authorization: str | None = Header(default=None)):
        principal = _principal_from_auth(authorization)
        ok, reason = authorize_capability(request.capability, principal.is_owner, request.confirmed)
        if not ok:
            raise HTTPException(403, reason)
        return {"command_token": sign_command(principal, request.capability, request.args), "expires_in": 120}

    @app.post("/api/computer/list")
    def computer_list(authorization: str | None = Header(default=None)):
        _principal_from_auth(authorization)
        return {"items": sandbox.list(".")}

    @app.post("/api/computer/read")
    def computer_read(request: CommandRequest, authorization: str | None = Header(default=None)):
        args = {"path": request.args.get("path", "")}
        _verify_signed(request, "workspace.read", args, authorization)
        return {"path": args["path"], "text": sandbox.read(args["path"])}

    @app.post("/api/computer/write")
    def computer_write(request: CommandRequest, authorization: str | None = Header(default=None)):
        args = {"path": request.args.get("path", ""), "text": request.args.get("text", "")}
        _verify_signed(request, "workspace.write", args, authorization)
        return {"written": sandbox.write(args["path"], args["text"])}

    @app.post("/api/computer/run")
    def computer_run(request: CommandRequest, authorization: str | None = Header(default=None)):
        args = {"argv": request.args.get("argv", [])}
        _verify_signed(request, "process.safe", args, authorization)
        try:
            return sandbox.run_safe(args["argv"])
        except SandboxExecutionDenied as exc:
            raise HTTPException(503, f"Sandbox unavailable; execution refused: {exc}") from exc

    @app.post("/api/browser/open")
    async def browser_open(request: CommandRequest, authorization: str | None = Header(default=None)):
        args = {"url": request.args.get("url", "")}
        _verify_signed(request, "browser.open", args, authorization)
        try:
            return await open_page(args["url"])
        except BrowserPolicyError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/api/research/web")
    async def research_web(request: CommandRequest, authorization: str | None = Header(default=None)):
        args = {"query": request.args.get("query", ""), "limit": request.args.get("limit", 5)}
        _verify_signed(request, "research.web", args, authorization)
        try:
            return await research(args["query"], args["limit"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
