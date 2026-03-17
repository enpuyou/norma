import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from norma.config import get_settings
from norma.database import init_db
from norma.middleware.auth import NormaAuthMiddleware

settings = get_settings()
log = structlog.get_logger()

app = FastAPI(
    title="norma.ai",
    description="The Operating System for Your AI Agents",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(NormaAuthMiddleware)


# ─── Lifecycle ────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup() -> None:
    log.info("norma.ai starting up", env=settings.app_env)
    await init_db()
    log.info("database initialised")


# ─── Exception Handlers ───────────────────────────────────────────────────────
from norma.integrations.session_core import AgentPausedError

@app.exception_handler(AgentPausedError)
async def agent_paused_exception_handler(request: Request, exc: AgentPausedError):
    return JSONResponse(
        status_code=200,
        content={
            "mode": "paused",
            "agent_id": exc.agent_id,
            "message": str(exc),
        },
    )

# ─── Routers ──────────────────────────────────────────────────────────────────
from norma.api import agents, alerts, analytics, attributions, compliance, contracts, events, qa, runs, telemetry, violations  # noqa: E402

app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["alerts"])
app.include_router(attributions.router, prefix="/api/attributions", tags=["attributions"])
app.include_router(contracts.router, prefix="/api/contracts", tags=["contracts"])
app.include_router(events.router, prefix="/api/events", tags=["events"])
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(violations.router, prefix="/api/violations", tags=["violations"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(qa.router, prefix="/api/qa", tags=["qa"])
app.include_router(compliance.router, prefix="/api/compliance", tags=["compliance"])
app.include_router(telemetry.router, prefix="/api/telemetry", tags=["telemetry"])


# ─── Health ───────────────────────────────────────────────────────────────────
@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}
