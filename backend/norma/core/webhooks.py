"""Webhook delivery for operational notifications (Slack, email, PagerDuty)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from norma.config import get_settings


def _targets() -> dict[str, str]:
    settings = get_settings()
    return {
        "slack": settings.webhook_slack_url.strip(),
        "email": settings.webhook_email_url.strip(),
        "pagerduty": settings.webhook_pagerduty_url.strip(),
    }


def _build_payload(event_type: str, severity: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "norma.ai",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "severity": severity,
        "payload": payload,
    }


def emit_webhooks_sync(event_type: str, payload: dict[str, Any], severity: str = "warning") -> dict[str, Any]:
    """Send event payload to configured webhook targets.

    Returns delivery summary and never raises network exceptions.
    """
    settings = get_settings()
    if not settings.enable_webhooks:
        return {"enabled": False, "sent": 0, "failed": 0, "results": []}

    body = _build_payload(event_type=event_type, severity=severity, payload=payload)
    results: list[dict[str, Any]] = []

    with httpx.Client(timeout=3.0) as client:
        for name, url in _targets().items():
            if not url:
                continue
            try:
                res = client.post(url, json=body)
                results.append({"target": name, "status_code": res.status_code, "ok": res.status_code < 400})
            except Exception as exc:
                results.append({"target": name, "ok": False, "error": str(exc)})

    sent = sum(1 for r in results if r.get("ok"))
    failed = sum(1 for r in results if not r.get("ok"))
    return {"enabled": True, "sent": sent, "failed": failed, "results": results}
