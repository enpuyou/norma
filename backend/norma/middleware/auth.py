from __future__ import annotations

import json
from typing import Literal

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from norma.config import get_settings

Role = Literal["viewer", "operator", "admin"]

_RANK: dict[str, int] = {
    "viewer": 1,
    "operator": 2,
    "admin": 3,
}


def _required_role_for_path(path: str, method: str) -> Role:
    method = method.upper()
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "viewer"

    # High-risk controls require admin.
    if "/approve/" in path or path.endswith("/bulk/pause"):
        return "admin"

    # Most write operations require operator.
    return "operator"


def _parse_keys(raw_json: str) -> dict[str, Role]:
    if not raw_json.strip():
        return {}
    try:
        data = json.loads(raw_json)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, Role] = {}
    for key, role in data.items():
        if not isinstance(key, str) or not isinstance(role, str):
            continue
        if role in {"viewer", "operator", "admin"}:
            out[key] = role  # type: ignore[assignment]
    return out


class NormaAuthMiddleware(BaseHTTPMiddleware):
    """Optional API key auth with coarse RBAC.

    Disabled unless `enable_api_key_auth=true` and keys are configured.
    Role is read from `x-api-key` using `api_keys_json` mapping.
    """

    async def dispatch(self, request, call_next):  # type: ignore[override]
        settings = get_settings()

        if not settings.enable_api_key_auth:
            return await call_next(request)

        path = request.url.path
        if path in {"/health", "/docs", "/redoc", "/openapi.json"}:
            return await call_next(request)
        if not path.startswith("/api/"):
            return await call_next(request)

        api_keys = _parse_keys(settings.api_keys_json)
        if not api_keys:
            return JSONResponse(
                status_code=503,
                content={"detail": "API key auth enabled but no keys configured"},
            )

        key = request.headers.get("x-api-key", "").strip()
        role = api_keys.get(key)
        if role is None:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})

        required = _required_role_for_path(path, request.method)
        if _RANK[role] < _RANK[required]:
            return JSONResponse(
                status_code=403,
                content={"detail": f"Role '{required}' required"},
            )

        request.state.auth_role = role
        return await call_next(request)
