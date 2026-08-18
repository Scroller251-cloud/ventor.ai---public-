from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parent / ".env")

from agent_registry import public_registry
from coding_tests import run_python_test, security_check
from critic_verifier import CriticVerifier
from debate_engine import DebateEngine
from evidence_checker import check_urls
from learning_engine import VerifiedLearningEngine
from learning_loop import LearningLoop
from local_models import GemmaMentor, QwenMentor
from mentor_learning import MentorLearningPipeline
from owner_gate import require_owner
from production_runtime import audit_event, install_production, metrics, readiness, runtime_snapshot
from provider_router import ProviderRouter
from runtime_manager import RuntimeManager
from unified_router import UnifiedRouter
from stress_tests import run as run_stress_tests

APP_VERSION = "3.0.1"

qwen = QwenMentor()
gemma = GemmaMentor()
learning = VerifiedLearningEngine()
debate = DebateEngine(qwen, gemma, learning=learning)
verifier = CriticVerifier([qwen, gemma])
router = UnifiedRouter(qwen, gemma)
learner = LearningLoop()
mentor_learning = MentorLearningPipeline([qwen, gemma], debate, verifier, learning)
providers = ProviderRouter()
runtime_manager = RuntimeManager()


@asynccontextmanager
async def lifespan(app):
    yield
    await qwen.aclose()
    await gemma.aclose()
    await providers.aclose()


app = FastAPI(title="Ventor — Production AI Core", version=APP_VERSION, lifespan=lifespan, docs_url="/docs" if os.getenv("VENTOR_DISABLE_DOCS", "0") != "1" else None, redoc_url="/redoc" if os.getenv("VENTOR_DISABLE_DOCS", "0") != "1" else None)
install_production(app)


class Task(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)
    agents: list[str] | None = None


@app.get("/health")
def health():
    return {"status": "ok", "version": APP_VERSION, "service": "ventor", "auto_upgrade": False, "metrics": metrics.snapshot()}


@app.get("/ready")
async def ready():
    result = await readiness(providers)
    return result


@app.get("/metrics")
def metrics_endpoint():
    return runtime_snapshot()


@app.get("/api/runtime")
def runtime_endpoint():
    return runtime_manager.snapshot()


@app.get("/api/agents")
def agents():
    return {"agents": public_registry(), "owner_gate": "immutable_external"}


@app.post("/api/route", dependencies=[Depends(require_owner)])
async def route(t: Task):
    selected = t.agents or router.select_specialists(t.prompt)
    results = await router.run(t.prompt, selected)
    audit_event("mentor_route", agents=selected, result_count=len(results))
    return {"version": APP_VERSION, "selected": selected, "results": [r.__dict__ for r in results], "owner_approval_required": True}


@app.post("/api/verify", dependencies=[Depends(require_owner)])
async def verify(t: Task):
    results = await router.run(t.prompt, t.agents or router.select_specialists(t.prompt))

    class Candidate:
        def __init__(self, mentor, answer):
            self.mentor = mentor
            self.answer = answer

    candidates = [Candidate(r.agent, r.answer) for r in results if r.answer]
    verdict = await verifier.verify(t.prompt, candidates[:4])
    evidence = [{"agent": r.agent, "check": (await check_urls(r.answer)).__dict__} for r in results if r.answer]
    return {"version": APP_VERSION, "results": [r.__dict__ for r in results], "evidence_checks": evidence, "verdict": verdict.__dict__, "owner_approval_required": True, "upgrade_allowed": False}


class LearnTask(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)


@app.post("/api/learn", dependencies=[Depends(require_owner)])
async def learn(t: LearnTask):
    result = await mentor_learning.learn(t.prompt)
    return {"version": APP_VERSION, **result, "owner_approval_required": True, "core_modified": False, "message": "Verified lessons may inform candidate improvements; core changes require owner approval."}


@app.get("/api/learning/status")
def learning_status():
    return {"version": APP_VERSION, **learning.snapshot(), "core_modified": False, "auto_apply": False}


class CandidateProposal(BaseModel):
    title: str
    rationale: str
    lesson_ids: list[str]
    benchmark: dict
    impact: dict
    risks: list[str]
    rollback: str


@app.post("/api/learning/propose", dependencies=[Depends(require_owner)])
def learning_propose(p: CandidateProposal):
    candidate = learning.propose_candidate(p.title, p.rationale, p.lesson_ids, p.benchmark, p.impact, p.risks, p.rollback)
    return {"version": APP_VERSION, "candidate": candidate, "owner_approval_required": True, "executed": False, "core_modified": False}


@app.get("/api/models")
def models():
    return {"agents": public_registry(), "providers": providers.status(), "runtime": runtime_manager.snapshot()}


class CodeTest(BaseModel):
    code: str = Field(min_length=1, max_length=100_000)
    timeout: float = Field(default=3.0, ge=0.1, le=10.0)


@app.post("/api/code/security")
def code_security(t: CodeTest):
    return {"version": APP_VERSION, "security": security_check(t.code), "owner_approval_required": False, "note": "Arbitrary generated code is rejected unless execution occurs through the isolated sandbox."}


@app.post("/api/code/test", dependencies=[Depends(require_owner)])
async def code_test(t: CodeTest):
    result = await run_python_test(t.code, t.timeout)
    return {"version": APP_VERSION, "result": result.__dict__, "owner_approval_required": False, "autonomous_host_execution": False}


@app.get("/api/selftest", dependencies=[Depends(require_owner)])
async def selftest():
    results = await run_stress_tests()
    return {"version": APP_VERSION, "passed": all(x["passed"] for x in results), "tests": results, "owner_gate": "external_immutable", "auto_upgrade": False}


class UpgradeProposal(BaseModel):
    title: str
    files: list[str]
    impact: str
    risks: list[str]
    benchmark: dict
    rollback: str


@app.post("/api/propose-upgrade", dependencies=[Depends(require_owner)])
def propose_upgrade(p: UpgradeProposal):
    proposal = learner.propose_upgrade(p.title, p.files, p.impact, p.risks, p.benchmark, p.rollback)
    return {"proposal": proposal, "executed": False, "owner_approval_required": True, "message": "Proposal recorded. Ventor cannot execute or approve upgrades itself."}


from v3_routes import install_v3
install_v3(app, memory=None, learning=learning, providers=providers)

_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")
