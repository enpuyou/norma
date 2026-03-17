from __future__ import annotations

import pytest
import yaml

from norma.config import get_settings
from norma.integrations.session import NormaAgentSession


CONTRACT_YAML = yaml.dump(
    {
        "agent_id": "otlp-test-agent",
        "authorities": {
            "tools": {"allow": ["list_reports"], "deny": []},
            "data": {"allow": ["reports/public/*"], "deny": ["reports/confidential/*"]},
        },
        "sla": {
            "max_latency_ms": 5000,
            "max_cost_per_run": 10.0,
            "max_tool_calls_per_run": 5,
        },
        "trust": {
            "clean_run_increment": 0.025,
            "violation_penalty": 0.25,
            "tier_thresholds": {
                "standard": {"min_score": 0.65, "min_clean_runs": 10},
                "trusted": {"min_score": 0.82, "min_clean_runs": 20},
            },
        },
    }
)


def test_otlp_export_called_after_persist(scenario_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "enable_otlp_export", True)
    monkeypatch.setattr(settings, "otlp_endpoint", "http://otel.test/v1/traces")

    calls: list[dict] = []

    def _fake_export(*, agent_id: str, run_id: int, framework: str, contract_version: str, spans: list) -> bool:
        calls.append(
            {
                "agent_id": agent_id,
                "run_id": run_id,
                "framework": framework,
                "contract_version": contract_version,
                "span_count": len(spans),
            }
        )
        return True

    monkeypatch.setattr("norma.core.otel_export.export_trace_spans", _fake_export)

    with NormaAgentSession(
        agent_id="otlp-test-agent",
        contract_yaml=CONTRACT_YAML,
        db_url=scenario_db,
        check_enabled=False,
    ) as sess:
        sess.record_llm_call(
            model="gpt-4o",
            input_data={"prompt": "hello"},
            output_text="ok",
            tokens_in=20,
            tokens_out=5,
        )

    assert len(calls) == 1
    assert calls[0]["agent_id"] == "otlp-test-agent"
    assert calls[0]["framework"] == "langchain"
    assert calls[0]["span_count"] >= 2
