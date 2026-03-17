"""API router stubs — filled in per-phase during implementation."""

from norma.api.agents import router as agents_router
from norma.api.analytics import router as analytics_router
from norma.api.contracts import router as contracts_router
from norma.api.qa import router as qa_router
from norma.api.runs import router as runs_router
from norma.api.violations import router as violations_router

__all__ = [
    "agents_router",
    "contracts_router",
    "runs_router",
    "violations_router",
    "analytics_router",
    "qa_router",
]
