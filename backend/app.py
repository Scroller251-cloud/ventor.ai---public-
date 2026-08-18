from __future__ import annotations

import os
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(_BACKEND_DIR / ".env")

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .owner_gate import require_team_or_owner
from .local_models import QwenMentor, GemmaMentor
from .debate_engine import DebateEngine
from .critic_verifier import CriticVerifier
from .evidence_checker import check_urls
from .agent_registry import public_registry
from .unified_router import UnifiedRouter
from .stress_tests import run as run_stress_tests
from .learning_loop import LearningLoop
from .learning_engine import VerifiedLearningEngine
from .mentor_learning import MentorLearningPipeline
from .coding_tests import run_python_test, security_check
from .production_runtime import ProductionMiddleware, ProductionRuntime
from .model_manager import ModelManager

APP_VERSION = "3.0.0"
runtime = ProductionRuntime()
model_manager = ModelManager()
app = FastAPI(title="Ventor.ai — Production Multi-Agent AI", version=APP_VERSION, docs_url="/docs" if os.getenv("VENTOR_DISABLE_DOCS", "0") != "1" else None, redoc_url="/redoc" if os.getenv("VENTOR_DISABLE_DOCS", "0") != "1" else None)
app.add_middleware(ProductionMiddleware, limiter=runtime.limiter, metrics=runtime.metrics, audit=runtime.audit)

cors = [x.strip() for x in os.getenv("VENTOR_CORS_ORIGINS", "").split(",") if x.strip()]
if cors:
    app.add_middleware(CORSMiddleware, allow_origins=cors, allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-Request-ID"])
trusted_hosts = [x.strip() for x in os.getenv("VENTOR_TRUSTED_HOSTS", "").split(",") if x.strip()]
if trusted_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

qwen = QwenMentor(); gemma = GemmaMentor(); learning = VerifiedLearningEngine(); debate = DebateEngine(qwen, gemma, learning); verifier = CriticVerifier([qwen, gemma]); router = UnifiedRouter(qwen, gemma); learner = LearningLoop(); mentor_learning = MentorLearningPipeline([qwen, gemma], debate, verifier, learning)

class Task(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    agents: list[str] | None = None

@app.get("/health")
def health(): return {"status":"ok","version":APP_VERSION,"service":"ventor","auto_upgrade":False}

@app.get("/ready")
def readiness():
    checks={"runtime":True,"auth_roster":bool(os.getenv("VENTOR_AUTH_ROSTER"))}; ready=all(checks.values()) if os.getenv("VENTOR_PRODUCTION","0")=="1" else True
    from fastapi.responses import JSONResponse
    return JSONResponse({"status":"ready" if ready else "not_ready","version":APP_VERSION,"checks":checks},status_code=200 if ready else 503)

@app.get("/metrics")
def metrics(): return {"version":APP_VERSION,"runtime":runtime.snapshot(),"models":model_manager.snapshot()}
@app.get("/api/agents")
def agents(): return {"agents":public_registry(),"owner_gate":"immutable_external"}

@app.post("/api/route", dependencies=[Depends(require_team_or_owner)])
async def route(t:Task):
    selected=t.agents or router.select_specialists(t.prompt); results=await router.run(t.prompt,selected)
    return {"version":APP_VERSION,"selected":selected,"results":[r.__dict__ for r in results],"owner_approval_required":True}

@app.post("/api/verify", dependencies=[Depends(require_team_or_owner)])
async def verify(t:Task):
    results=await router.run(t.prompt,t.agents or router.select_specialists(t.prompt))
    class C:
        def __init__(self,mentor,answer): self.mentor=mentor; self.answer=answer
    candidates=[C(r.agent,r.answer) for r in results if r.answer]; verdict=await verifier.verify(t.prompt,candidates)
    evidence=[{"agent":r.agent,"check":(await check_urls(r.answer)).__dict__} for r in results if r.answer]
    return {"version":APP_VERSION,"results":[r.__dict__ for r in results],"evidence_checks":evidence,"verdict":verdict.__dict__,"owner_approval_required":True,"upgrade_allowed":False}

class LearnTask(BaseModel): prompt:str=Field(min_length=1,max_length=20000)
@app.post("/api/learn", dependencies=[Depends(require_team_or_owner)])
async def learn(t:LearnTask):
    result=await mentor_learning.learn(t.prompt)
    return {"version":APP_VERSION,**result,"owner_approval_required":True,"core_modified":False,"message":"Verified lessons may inform candidate improvements; core changes require owner approval."}

@app.get("/api/learning/status")
def learning_status(): return {"version":APP_VERSION,**learning.snapshot(),"core_modified":False,"auto_apply":False}
@app.get("/api/models")
def models(): return {"agents":public_registry(),"runtime":model_manager.snapshot()}

class CodeTest(BaseModel):
    code:str=Field(min_length=1,max_length=50000); timeout:float=Field(default=3.0,ge=0.1,le=10.0)
@app.post("/api/code/security")
def code_security(t:CodeTest): return {"version":APP_VERSION,"security":security_check(t.code),"owner_approval_required":False,"note":"Only the restricted deterministic subset may execute; arbitrary generated code is rejected."}
@app.get("/api/selftest",dependencies=[Depends(require_team_or_owner)])
async def selftest():
    results=await run_stress_tests(); return {"version":APP_VERSION,"passed":all(x["passed"] for x in results),"tests":results,"owner_gate":"external_immutable","auto_upgrade":False}

from .v3_routes import install_v3
install_v3(app)
_FRONTEND=Path(__file__).resolve().parent.parent/"frontend"
if _FRONTEND.exists(): app.mount("/",StaticFiles(directory=str(_FRONTEND),html=True),name="frontend")
