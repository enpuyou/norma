from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from norma.config import get_settings
from norma.core.trace import SpanData

log = structlog.get_logger()


def _ns(dt: datetime | None) -> int:
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


def _trace_id(agent_id: str, run_id: int) -> str:
    return hashlib.sha256(f"{agent_id}:{run_id}".encode("utf-8")).hexdigest()[:32]


def _attr_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": value}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": str(value)}


def _attrs(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, value in mapping.items():
        if value is None:
            continue
        out.append({"key": key, "value": _attr_value(value)})
    return out


def _span_status(status: str) -> dict[str, Any]:
    if status == "ok":
        return {"code": 1}
    if status == "blocked":
        return {"code": 2, "message": "blocked"}
    return {"code": 2, "message": status}


def _to_otlp_span(trace_id_hex: str, span: SpanData, run_id: int, framework: str, contract_version: str) -> dict[str, Any]:
    attributes = dict(span.attributes or {})
    attributes.update(
        {
            "norma.run_id": run_id,
            "norma.framework": framework,
            "norma.contract_version": contract_version,
            "norma.span_type": span.span_type,
        }
    )
    if span.tokens_in is not None:
        attributes["llm.tokens_in"] = span.tokens_in
    if span.tokens_out is not None:
        attributes["llm.tokens_out"] = span.tokens_out
    if span.cost_usd is not None:
        attributes["llm.cost_usd"] = span.cost_usd
    if span.latency_ms is not None:
        attributes["latency.ms"] = span.latency_ms

    if span.input_data:
        attributes["norma.input_data"] = span.input_data[:4000]
    if span.output_data:
        attributes["norma.output_data"] = span.output_data[:4000]

    payload: dict[str, Any] = {
        "traceId": trace_id_hex,
        "spanId": span.span_id,
        "name": span.name,
        "kind": 1,
        "startTimeUnixNano": str(_ns(span.start_time)),
        "endTimeUnixNano": str(_ns(span.end_time)),
        "attributes": _attrs(attributes),
        "status": _span_status(span.status),
    }
    if span.parent_span_id:
        payload["parentSpanId"] = span.parent_span_id
    return payload


def export_trace_spans(
    *,
    agent_id: str,
    run_id: int,
    framework: str,
    contract_version: str,
    spans: list[SpanData],
) -> bool:
    settings = get_settings()
    if not getattr(settings, "enable_otlp_export", False):
        return False

    endpoint = getattr(settings, "otlp_endpoint", "")
    if not endpoint:
        return False

    trace_id_hex = _trace_id(agent_id, run_id)
    otlp_spans = [
        _to_otlp_span(trace_id_hex, s, run_id, framework, contract_version)
        for s in spans
    ]

    service_name = getattr(settings, "otlp_service_name", "norma-ai")
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": service_name}},
                        {"key": "service.namespace", "value": {"stringValue": "norma"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "norma.trace", "version": "0.1.0"},
                        "spans": otlp_spans,
                    }
                ],
            }
        ]
    }

    headers = {
        "Content-Type": "application/json",
    }
    raw_headers = getattr(settings, "otlp_headers_json", "")
    if raw_headers:
        try:
            parsed = json.loads(raw_headers)
            if isinstance(parsed, dict):
                headers.update({str(k): str(v) for k, v in parsed.items()})
        except Exception:
            log.warning("norma: invalid otlp_headers_json, ignoring")

    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
        return True
    except Exception as exc:
        log.warning(
            "norma: otlp export failed",
            agent_id=agent_id,
            run_id=run_id,
            endpoint=endpoint,
            error=str(exc),
        )
        return False
