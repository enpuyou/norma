from __future__ import annotations

import pytest
from click.testing import CliRunner

from norma.integrations.cli import norma_cmd


class _Resp:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self) -> dict:
        return self._payload


class _Client:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url: str):
        return _Resp(self.payload)


def test_compliance_cli_returns_zero_when_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "passed": True,
        "summary": {"total_rules": 12, "failed_rules": 0},
        "findings": [],
    }
    monkeypatch.setattr("norma.integrations.cli.httpx.Client", lambda timeout=10.0: _Client(payload))

    runner = CliRunner()
    result = runner.invoke(norma_cmd, ["compliance", "check", "--agent-id", "a1"])
    assert result.exit_code == 0
    assert "COMPLIANT" in result.output


def test_compliance_cli_returns_one_when_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "passed": False,
        "summary": {"total_rules": 12, "failed_rules": 2},
        "findings": [
            {"rule_id": "OWASP-LLM06", "passed": False, "message": "Sensitive disclosure pattern detected"}
        ],
    }
    monkeypatch.setattr("norma.integrations.cli.httpx.Client", lambda timeout=10.0: _Client(payload))

    runner = CliRunner()
    result = runner.invoke(norma_cmd, ["compliance", "check", "--agent-id", "a1"])
    assert result.exit_code == 1
    assert "NON-COMPLIANT" in result.output
