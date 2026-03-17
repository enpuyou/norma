"""NormaSessionCore — framework-agnostic base for all norma adapter sessions.

This class owns:
  - TraceCollector (span lifecycle)
  - Circuit breaker (max tool calls, max cost)
  - Agent pause check (enabled=False → reject)
  - DB flush (runs, violations, spans, trust update, SSE broadcast)
  - Quality scoring (auto or manual)

Framework-specific adapters (LangChain, OpenAI func-calling, OpenAI Agents SDK)
subclass this and implement their own tool-wrapping / interception logic.

Direct usage is possible for any framework that norma doesn't have a
dedicated adapter for — just call record_tool_call() / record_llm_call()
manually.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import time
from datetime import datetime
from typing import Any

import structlog
import yaml

from norma.config import get_settings
from norma.core.enforcement import ExecutionContext, EnforcementResult, enforce
from norma.core.pricing import calculate_llm_cost, context_utilization_ratio
from norma.core.quality_scorer import evaluate_quality, evaluate_quality_sync
from norma.core.trace import TraceCollector, SpanData
from norma.core.trust_engine import TrustState, record_clean_run, record_violation

log = structlog.get_logger()
settings = get_settings()


class ToolBlockedError(Exception):
    """Raised when norma enforcement denies a tool call."""
    def __init__(self, result: EnforcementResult) -> None:
        self.result = result
        super().__init__(f"[norma] Blocked: {result.policy_rule} — {result.action_attempted}")


class AgentPausedError(Exception):
    """Raised when trying to run a paused (enabled=False) agent."""
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(f"[norma] Agent '{agent_id}' is paused (enabled=False). Resume before running.")


class CircuitBreakerError(Exception):
    """Raised when a run exceeds circuit breaker limits."""
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"[norma] Circuit breaker tripped: {reason}")


class NormaSessionCore:
    """
    Framework-agnostic session base class.

    Subclasses must implement their own tool wrapping (e.g. wrap_tools for
    LangChain, patching for OpenAI). The core handles everything else.
    """

    framework: str = "generic"  # subclasses override: "langchain", "openai_func", "openai_agents"

    def __init__(
        self,
        agent_id: str,
        contract_yaml: str,
        contract_version: str = "1.0",
        db_url: str | None = None,
        remote_url: str | None = None,
        parent_run_id: int | None = None,
        initiated_by: str | None = None,
        session_id: str | None = None,
        check_enabled: bool = True,
    ) -> None:
        self.agent_id = agent_id
        self.contract: dict[str, Any] = yaml.safe_load(contract_yaml)
        self.contract_yaml = contract_yaml
        self.contract_version = contract_version

        # Run state
        self._start_time: float | None = None
        self._input_tokens: int = 0
        self._output_tokens: int = 0
        self._cost_usd: float = 0.0
        self._quality_score: float | None = None
        self._quality_rationale: str | None = None
        self._quality_breakdown: dict[str, Any] | None = None
        self._quality_explicitly_set: bool = False
        self._violations: list[dict[str, Any]] = []
        self._blocked: bool = False
        self._completion_status: str = "success"
        self._trust_score_after: float | None = None
        self._tool_outputs: list[str] = []

        self._parent_run_id: int | None = parent_run_id
        # Active sub-agent span — when set, tool spans are parented here instead of root
        self._active_subagent_span: "SpanData | None" = None
        self._initiated_by: str | None = initiated_by
        self._session_id: str | None = session_id
        self._check_enabled: bool = check_enabled
        self._db_url = (db_url or settings.database_url).replace("+aiosqlite", "")
        # When set, POST telemetry to this URL instead of writing to local DB.
        # Use "http://localhost:8080" to send to a local norma server, or any
        # remote norma API base URL for out-of-process agent monitoring.
        self._remote_url: str | None = remote_url.rstrip("/") if remote_url else None
        self._steps: list[dict[str, Any]] = []  # backward-compat RunStep data

        # Tracing
        self.trace = TraceCollector()
        self._root_span: SpanData | None = None

        # Circuit breaker
        sla = self.contract.get("sla", {})
        self._max_cost_per_run: float = sla.get("max_cost_per_run", 100.0)
        self._max_tool_calls: int = sla.get("max_tool_calls_per_run", 50)
        self._tool_call_count: int = 0
        self._circuit_broken: bool = False

    def _prompt_hash(self, payload: Any) -> str:
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _llm_quality_subscore(self, output_text: str) -> float | None:
        if not output_text:
            return None
        from norma.core.quality_scorer import score_deterministic

        score, _ = score_deterministic(output_text, contract=self.contract)
        return score

    def _apply_llm_metrics(
        self,
        *,
        span: SpanData,
        model: str,
        tokens_in: int,
        tokens_out: int,
        output_text: str = "",
        prompt_payload: Any = None,
        cost_usd: float | None = None,
        extra_attributes: dict[str, Any] | None = None,
    ) -> float:
        resolved_cost = calculate_llm_cost(model, tokens_in, tokens_out) if cost_usd is None else cost_usd
        utilization = context_utilization_ratio(model, tokens_in)
        quality_subscore = self._llm_quality_subscore(output_text)

        attrs: dict[str, Any] = {
            "model": model,
            "framework": self.framework,
            "context_utilization_ratio": utilization,
        }
        if extra_attributes:
            attrs.update(extra_attributes)
            if "temperature" in extra_attributes:
                attrs["temperature"] = extra_attributes["temperature"]
            if "max_tokens" in extra_attributes:
                attrs["max_tokens"] = extra_attributes["max_tokens"]
            if "top_p" in extra_attributes:
                attrs["top_p"] = extra_attributes["top_p"]
        if prompt_payload is not None:
            attrs["prompt_hash"] = self._prompt_hash(prompt_payload)
        if quality_subscore is not None:
            attrs["quality_subscore"] = quality_subscore
        if extra_attributes:
            attrs.update(extra_attributes)

        self.trace.end_span(
            span,
            output_data=output_text[:1000] if output_text else None,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=resolved_cost,
            attributes=attrs,
        )
        self._input_tokens += tokens_in
        self._output_tokens += tokens_out
        self._cost_usd += resolved_cost
        return resolved_cost

    # ── Public API ─────────────────────────────────────────────────────────────

    def record_quality(self, score: float) -> None:
        """Record the quality output score for this run (0.0–1.0)."""
        self._quality_score = max(0.0, min(1.0, score))
        self._quality_explicitly_set = True

    def record_quality_result(self, result: Any) -> None:
        """Record a full QualityResult (score + rationale + per-check breakdown)."""
        self._quality_score = max(0.0, min(1.0, result.score))
        self._quality_rationale = result.rationale
        self._quality_breakdown = result.checks
        self._quality_explicitly_set = True

    def record_tokens(self, *, input: int, output: int) -> None:
        """Record LLM token usage."""
        self._input_tokens = input
        self._output_tokens = output
        self._cost_usd = calculate_llm_cost("gpt-4o", input, output)

    def record_cost(self, cost_usd: float) -> None:
        self._cost_usd = cost_usd

    def record_tool_call(
        self,
        tool_name: str,
        input_text: str,
        output_text: str,
        latency_ms: int,
        blocked: bool = False,
        policy_rule: str | None = None,
    ) -> None:
        """Record a tool call (for frameworks where we can't intercept directly)."""
        self._tool_outputs.append(output_text)
        self._steps.append({
            "tool_name": tool_name,
            "input_text": input_text[:500],
            "output_text": output_text[:1000],
            "latency_ms": latency_ms,
            "blocked": blocked,
            "policy_rule": policy_rule,
        })

    def record_llm_call(
        self,
        model: str,
        input_data: Any = None,
        output_text: str = "",
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float | None = None,
    ) -> SpanData:
        """Record an LLM call as a span. Returns the completed span."""
        span = self.trace.start_span(
            "llm_call", model,
            parent=self._root_span,
            input_data=input_data,
        )
        self._apply_llm_metrics(
            span=span,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            output_text=output_text,
            prompt_payload=input_data,
            cost_usd=cost_usd,
        )
        return span

    # ── Context manager ────────────────────────────────────────────────────────

    def __enter__(self) -> "NormaSessionCore":
        if self._check_enabled:
            self._verify_agent_enabled()

        self._verify_budget_before_run()
        self._start_time = time.time()
        self._root_span = self.trace.start_span(
            "session", self.agent_id,
            input_data={
                "contract_version": self.contract_version,
                "session_id": self._session_id,
                "framework": self.framework,
            },
        )
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        latency_ms = int((time.time() - (self._start_time or time.time())) * 1000)
        if exc_type and not self._blocked:
            self._completion_status = "failed"
        elif self._blocked:
            self._completion_status = "failed"

        # Close root span
        if self._root_span:
            self.trace.end_span(
                self._root_span,
                status="error" if self._completion_status == "failed" else "ok",
                attributes={
                    "completion_status": self._completion_status,
                    "tool_call_count": self._tool_call_count,
                    "violation_count": len(self._violations),
                    "circuit_broken": self._circuit_broken,
                    "framework": self.framework,
                },
            )
        self.trace.close_all()

        # Auto-score quality if not explicitly set
        if not self._quality_explicitly_set:
            combined_output = "\n".join(self._tool_outputs) if self._tool_outputs else ""
            if self._blocked:
                self._quality_score = 0.0
                self._quality_breakdown = {"blocked": True}
            elif combined_output:
                import asyncio
                # Run in a dedicated thread so asyncio.run() always gets a
                # fresh event loop — works whether or not a loop is already
                # running (FastAPI/uvicorn context).
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        asyncio.run,
                        evaluate_quality(
                            combined_output,
                            task_description=self.agent_id,
                            contract=self.contract,
                        ),
                    )
                    try:
                        result = future.result(timeout=30)
                    except Exception as _qe:
                        log.warning("norma: llm quality scoring failed, falling back to deterministic", error=str(_qe))
                        result = evaluate_quality_sync(combined_output, contract=self.contract)
                log.info("norma: quality scored", source=result.source, score=result.score, has_rationale=bool(result.rationale))
                self._quality_score = result.score
                self._quality_rationale = result.rationale
                self._quality_breakdown = result.checks
            else:
                self._quality_score = None

        try:
            if self._remote_url:
                self._flush_to_remote(latency_ms)
            else:
                self._flush_to_db(latency_ms)
        except Exception as e:
            log.warning("norma: failed to persist run", error=str(e))

        return False

    # ── Enforcement ────────────────────────────────────────────────────────────

    def enforce_tool(self, tool_name: str, data_path: str | None = None) -> EnforcementResult:
        """Check enforcement for a tool call. Returns the result (may be blocked)."""
        ctx = ExecutionContext(
            agent_id=self.agent_id,
            tool_requested=tool_name,
            data_path_requested=data_path,
            contract=self.contract,
        )
        return enforce(ctx)

    def check_and_enforce_tool(
        self,
        tool_name: str,
        raw_input: str = "",
    ) -> tuple[bool, str | None]:
        """Full pre-flight check: circuit breaker + enforcement.

        Returns:
            (allowed: bool, block_message: str | None)
        """
        # Circuit breaker
        cb_msg = self._check_circuit_breaker(tool_name)
        if cb_msg:
            log.warning("norma: circuit breaker tripped", tool=tool_name, reason=cb_msg)
            self._completion_status = "failed"
            cb_span = self.trace.start_span(
                "tool_call", tool_name, parent=self._root_span,
                input_data={"circuit_breaker": True},
            )
            self.trace.end_span(cb_span, status="blocked",
                                output_data=cb_msg,
                                attributes={"circuit_breaker": True})
            return False, f"[HALTED by norma.ai] {cb_msg}"

        self._tool_call_count += 1

        # Data path extraction
        data_path: str | None = None
        if "/" in raw_input or "." in raw_input:
            data_path = raw_input

        # Enforcement
        enforce_span = self.trace.start_span(
            "enforcement_check", f"enforce:{tool_name}",
            parent=self._root_span,
            input_data={"tool": tool_name, "data_path": data_path},
        )

        result = self.enforce_tool(tool_name, data_path)

        if result.blocked:
            self.trace.end_span(enforce_span, status="blocked",
                                output_data={"policy_rule": result.policy_rule,
                                              "event_type": result.event_type})
            self._blocked = True
            self._completion_status = "failed"
            self._violations.append({
                "policy_rule": result.policy_rule,
                "action_attempted": result.action_attempted,
                "event_type": result.event_type,
            })
            self._steps.append({
                "tool_name": tool_name,
                "input_text": raw_input[:500],
                "output_text": None,
                "latency_ms": 0,
                "blocked": True,
                "policy_rule": result.policy_rule,
            })
            log.warning("norma: tool call blocked", tool=tool_name, rule=result.policy_rule)
            msg = (
                f"[BLOCKED by norma.ai] "
                f"Tool '{tool_name}' is not permitted under the active contract. "
                f"Policy: {result.policy_rule}"
            )
            return False, msg

        self.trace.end_span(enforce_span, status="ok", output_data={"allowed": True})
        return True, None

    def start_tool_span(self, tool_name: str, input_data: Any = None) -> SpanData:
        """Start a tool_call span (call end_tool_span when done)."""
        parent = self._active_subagent_span or self._root_span
        return self.trace.start_span(
            "tool_call", tool_name,
            parent=parent,
            input_data=input_data,
        )

    def push_subagent_span(self, name: str, input_data: Any = None) -> SpanData:
        """Open an agent_handoff span and make it the parent for subsequent tool spans.

        Call pop_subagent_span() when the sub-agent node finishes.
        """
        self._active_subagent_span = self.trace.start_span(
            "agent_handoff", name,
            parent=self._root_span,
            input_data=input_data,
        )
        return self._active_subagent_span

    def pop_subagent_span(self, output: str = "") -> None:
        """Close the current sub-agent span and restore tool parenting to root."""
        if self._active_subagent_span:
            self.trace.end_span(self._active_subagent_span, output_data=output[:500])
            self._active_subagent_span = None

    def end_tool_span(
        self,
        span: SpanData,
        output: str,
        latency_ms: int,
    ) -> None:
        """End a tool_call span and record the step."""
        self._tool_outputs.append(output)
        self.trace.end_span(
            span,
            output_data=output[:1000],
            attributes={"latency_ms": latency_ms},
        )

    # ── Agent pause check ──────────────────────────────────────────────────────

    def _verify_agent_enabled(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from norma.models.agent import Agent

        try:
            engine = create_engine(self._db_url, echo=False)
            Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
            with Session() as db:
                agent_row = db.get(Agent, self.agent_id)
                if agent_row is not None and not agent_row.enabled:
                    raise AgentPausedError(self.agent_id)
            engine.dispose()
        except AgentPausedError:
            raise
        except Exception:
            pass

    def _verify_budget_before_run(self) -> None:
        from sqlalchemy import and_, create_engine, func
        from sqlalchemy.orm import sessionmaker

        from norma.models.budget import Budget
        from norma.models.run import Run

        try:
            engine = create_engine(self._db_url, echo=False)
            Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
            with Session() as db:
                budget = (
                    db.query(Budget)
                    .filter(
                        and_(
                            Budget.agent_id == self.agent_id,
                            Budget.enabled == True,  # noqa: E712
                        )
                    )
                    .first()
                )
                if not budget:
                    return
                now = datetime.utcnow()
                if budget.period == "daily":
                    period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                else:
                    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

                used_cost = (
                    db.query(func.coalesce(func.sum(Run.cost_usd), 0.0))
                    .filter(Run.agent_id == self.agent_id, Run.timestamp >= period_start)
                    .scalar()
                    or 0.0
                )
                run_count = (
                    db.query(func.count(Run.id))
                    .filter(Run.agent_id == self.agent_id, Run.timestamp >= period_start)
                    .scalar()
                    or 0
                )

                if used_cost >= budget.max_cost_usd:
                    raise CircuitBreakerError(
                        f"Budget exceeded for {budget.period} window (${used_cost:.4f}/${budget.max_cost_usd:.2f})"
                    )
                if budget.max_runs and run_count >= budget.max_runs:
                    raise CircuitBreakerError(
                        f"Run budget exceeded for {budget.period} window ({run_count}/{budget.max_runs})"
                    )
            engine.dispose()
        except CircuitBreakerError:
            raise
        except Exception:
            pass

    # ── Circuit breaker ────────────────────────────────────────────────────────

    def _check_circuit_breaker(self, tool_name: str) -> str | None:
        if self._tool_call_count >= self._max_tool_calls:
            self._circuit_broken = True
            return (
                f"Circuit breaker: tool call limit exceeded "
                f"({self._tool_call_count}/{self._max_tool_calls}). "
                f"Run halted to prevent runaway execution."
            )
        if self._cost_usd > self._max_cost_per_run:
            self._circuit_broken = True
            return (
                f"Circuit breaker: cost limit exceeded "
                f"(${self._cost_usd:.4f}/${self._max_cost_per_run:.2f}). "
                f"Run halted to prevent budget overrun."
            )
        return None

    # ── Remote HTTP persistence ─────────────────────────────────────────────────

    def _flush_to_remote(self, latency_ms: int) -> None:
        """POST run telemetry to a remote norma API server (POST /api/runs/ingest)."""
        import urllib.request

        trace_tokens_in = self.trace.total_tokens_in()
        trace_tokens_out = self.trace.total_tokens_out()
        trace_cost = self.trace.total_cost()
        input_tokens = trace_tokens_in if trace_tokens_in > 0 else self._input_tokens
        output_tokens = trace_tokens_out if trace_tokens_out > 0 else self._output_tokens
        cost = trace_cost if trace_cost > 0 else self._cost_usd

        spans = []
        for s in self.trace.spans:
            d = s.to_dict()
            spans.append({
                "span_id": d["span_id"],
                "parent_span_id": d.get("parent_span_id"),
                "span_type": d["span_type"],
                "name": d["name"],
                "status": d.get("status", "ok"),
                "start_time": d.get("start_time"),
                "end_time": d.get("end_time"),
                "input_data": d.get("input_data"),
                "output_data": d.get("output_data"),
                "tokens_in": d.get("tokens_in"),
                "tokens_out": d.get("tokens_out"),
                "cost_usd": d.get("cost_usd"),
                "latency_ms": d.get("latency_ms"),
                "attributes": d.get("attributes"),
            })

        payload = {
            "agent_id": self.agent_id,
            "contract_version": self.contract_version,
            "parent_run_id": self._parent_run_id,
            "initiated_by": self._initiated_by,
            "session_id": self._session_id,
            "framework": self.framework,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 5),
            "latency_ms": latency_ms,
            "quality_score": self._quality_score,
            "quality_rationale": self._quality_rationale,
            "quality_breakdown": self._quality_breakdown,
            "completion_status": self._completion_status,
            "violations": [
                {
                    "policy_rule": v["policy_rule"],
                    "action_attempted": v["action_attempted"],
                    "blocked": True,
                    "event_type": v.get("event_type", "access_blocked"),
                }
                for v in self._violations
            ],
            "spans": spans,
        }

        body = json.dumps(payload).encode("utf-8")
        url = f"{self._remote_url}/api/runs/ingest"
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            self._trust_score_after = result.get("trust_score_after", 0.0)
            log.info(
                "norma: run submitted to remote",
                agent=self.agent_id,
                remote_url=self._remote_url,
                run_id=result.get("run_id"),
                trust=self._trust_score_after,
            )

    # ── DB persistence ─────────────────────────────────────────────────────────

    def _flush_to_db(self, latency_ms: int) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from norma.models.agent import Agent
        from norma.models.run import Run
        from norma.models.span import Span
        from norma.models.violation import Violation
        from norma.models.observability import PromptSnapshot, SharedContext

        engine = create_engine(self._db_url, echo=False)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

        with Session() as db:
            agent_row = db.get(Agent, self.agent_id)
            if agent_row is None:
                agent_row = Agent(
                    agent_id=self.agent_id,
                    name=self.agent_id,
                    type="single",
                    current_tier="restricted",
                    trust_score=0.40,
                    enabled=True,
                )
                db.add(agent_row)
                db.flush()

            trust_cfg = self.contract.get("trust", {})
            trust_state = TrustState(
                agent_id=self.agent_id,
                trust_score=agent_row.trust_score,
                clean_run_count=agent_row.clean_run_count,
                clean_run_increment=trust_cfg.get("clean_run_increment", 0.025),
                violation_penalty=trust_cfg.get("violation_penalty", 0.25),
                tier_thresholds=trust_cfg.get(
                    "tier_thresholds",
                    {
                        "standard": {"min_score": 0.65, "min_clean_runs": 10},
                        "trusted": {"min_score": 0.82, "min_clean_runs": 20},
                    },
                ),
            )
            trust_state.current_tier = agent_row.current_tier

            trace_tokens_in = self.trace.total_tokens_in()
            trace_tokens_out = self.trace.total_tokens_out()
            trace_cost = self.trace.total_cost()
            input_tokens = trace_tokens_in if trace_tokens_in > 0 else self._input_tokens
            output_tokens = trace_tokens_out if trace_tokens_out > 0 else self._output_tokens
            cost = trace_cost if trace_cost > 0 else self._cost_usd

            import json as _json_mod
            _quality_breakdown_json = (
                _json_mod.dumps(self._quality_breakdown) if self._quality_breakdown else None
            )

            run = Run(
                agent_id=self.agent_id,
                parent_run_id=self._parent_run_id,
                initiated_by=self._initiated_by,
                session_id=self._session_id,
                contract_version=self.contract_version,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(cost, 5),
                latency_ms=latency_ms,
                quality_score=self._quality_score,
                quality_rationale=self._quality_rationale,
                quality_breakdown=_quality_breakdown_json,
                trust_score_after=0.0,
                completion_status=self._completion_status,
                timestamp=datetime.utcnow(),
            )
            db.add(run)
            db.flush()

            if self._violations:
                record_violation(trust_state, resource=self._violations[0]["action_attempted"], run_id=run.id)
            else:
                record_clean_run(trust_state, run_id=run.id)

            self._trust_score_after = trust_state.trust_score
            run.trust_score_after = self._trust_score_after

            for v in self._violations:
                db.add(Violation(
                    run_id=run.id,
                    agent_id=self.agent_id,
                    policy_rule=v["policy_rule"],
                    action_attempted=v["action_attempted"],
                    blocked=True,
                    event_type=v.get("event_type", "access_blocked"),
                    timestamp=datetime.utcnow(),
                ))

            from norma.models.run_step import RunStep
            for idx, step in enumerate(self._steps):
                db.add(RunStep(
                    run_id=run.id,
                    step_index=idx,
                    tool_name=step["tool_name"],
                    input_text=step.get("input_text"),
                    output_text=step.get("output_text"),
                    latency_ms=step.get("latency_ms"),
                    blocked=step.get("blocked", False),
                    policy_rule=step.get("policy_rule"),
                    timestamp=datetime.utcnow(),
                ))

            for span_data in self.trace.spans:
                # Extract model_name from span attributes for first-class storage
                raw_attrs = span_data.to_dict()["attributes"]
                span_model_name: str | None = None
                if raw_attrs:
                    try:
                        import json as _jmod
                        parsed = _jmod.loads(raw_attrs) if isinstance(raw_attrs, str) else raw_attrs
                        span_model_name = parsed.get("model") or parsed.get("model_name")
                    except Exception:
                        pass

                db.add(Span(
                    span_id=span_data.span_id,
                    trace_id=run.id,
                    parent_span_id=span_data.parent_span_id,
                    span_type=span_data.span_type,
                    name=span_data.name,
                    status=span_data.status,
                    start_time=span_data.start_time,
                    end_time=span_data.end_time,
                    input_data=span_data.input_data,
                    output_data=span_data.output_data,
                    tokens_in=span_data.tokens_in,
                    tokens_out=span_data.tokens_out,
                    cost_usd=span_data.cost_usd,
                    latency_ms=span_data.latency_ms,
                    model_name=span_model_name,
                    attributes=raw_attrs,
                    timestamp=datetime.utcnow(),
                ))

                # Extract PromptSnapshots from LLM span input/output
                if span_data.span_type == "llm_call":
                    try:
                        import json as _jmod
                        # Parse inputs (usually chat messages)
                        if span_data.input_data:
                            inp = _jmod.loads(span_data.input_data)
                            msgs = inp.get("messages", []) if isinstance(inp, dict) else inp
                            if isinstance(msgs, list):
                                for msg in msgs:
                                    if isinstance(msg, dict) and "role" in msg:
                                        db.add(PromptSnapshot(
                                            run_id=run.id,
                                            span_id=span_data.span_id,
                                            role=msg["role"],
                                            content=str(msg.get("content", ""))[:5000],
                                            token_count=None,  # Not easily granular per-message yet
                                        ))
                        # Parse outputs (usually assistant message)
                        if span_data.output_data:
                            outp = _jmod.loads(span_data.output_data)
                            if isinstance(outp, dict):
                                msg = outp.get("message") or outp.get("choices", [{}])[0].get("message")
                                if msg and isinstance(msg, dict) and "role" in msg:
                                    db.add(PromptSnapshot(
                                        run_id=run.id,
                                        span_id=span_data.span_id,
                                        role=msg["role"],
                                        content=str(msg.get("content", ""))[:5000],
                                        token_count=span_data.tokens_out,
                                    ))
                    except Exception as e:
                        log.debug("norma: failed to extract prompt snapshots", error=str(e))

                # Extract SharedContext from agent handoff spans
                if span_data.span_type == "agent_handoff" and span_data.output_data:
                    try:
                        import json as _jmod
                        outp = _jmod.loads(span_data.output_data)
                        if isinstance(outp, dict) and "run_id" in outp:
                            to_run_id = outp["run_id"]
                            preview = str(outp.get("state", {}))[:1000]
                            db.add(SharedContext(
                                from_run_id=run.id,
                                to_run_id=to_run_id,
                                context_type="handoff",
                                data_preview=preview,
                            ))
                    except Exception as e:
                        log.debug("norma: failed to extract shared context", error=str(e))

            agent_row.trust_score = trust_state.trust_score
            agent_row.current_tier = trust_state.current_tier
            agent_row.clean_run_count = trust_state.clean_run_count
            agent_row.pending_contract_version = trust_state.pending_contract_version

            db.commit()

            if self._violations:
                try:
                    from norma.core.webhooks import emit_webhooks_sync

                    emit_webhooks_sync(
                        event_type="violation_detected",
                        severity="critical",
                        payload={
                            "agent_id": self.agent_id,
                            "run_id": run.id,
                            "violation_count": len(self._violations),
                            "violations": self._violations,
                            "trust_score_after": self._trust_score_after,
                        },
                    )
                except Exception as exc:
                    log.warning(
                        "norma: webhook delivery skipped",
                        agent_id=self.agent_id,
                        run_id=run.id,
                        error=str(exc),
                    )

            try:
                from norma.core.otel_export import export_trace_spans

                export_trace_spans(
                    agent_id=self.agent_id,
                    run_id=run.id,
                    framework=self.framework,
                    contract_version=self.contract_version,
                    spans=self.trace.spans,
                )
            except Exception as exc:
                log.warning(
                    "norma: otlp export skipped",
                    agent_id=self.agent_id,
                    run_id=run.id,
                    error=str(exc),
                )

            log.info(
                "norma: run persisted",
                agent=self.agent_id,
                framework=self.framework,
                status=self._completion_status,
                trust=round(trust_state.trust_score, 3),
                tier=trust_state.current_tier,
                violations=len(self._violations),
                latency_ms=latency_ms,
                spans=len(self.trace.spans),
            )

            try:
                from norma.api.events import broadcast

                broadcast("run_completed", {
                    "agent_id": self.agent_id,
                    "run_id": run.id,
                    "status": self._completion_status,
                    "quality_score": self._quality_score,
                    "trust_score_after": self._trust_score_after,
                    "latency_ms": latency_ms,
                    "framework": self.framework,
                    "prompt_hash": self._prompt_hash({
                        "agent_id": self.agent_id,
                        "contract_version": self.contract_version,
                    }),
                })

                broadcast("trust_changed", {
                    "agent_id": self.agent_id,
                    "trust_score": trust_state.trust_score,
                    "tier": trust_state.current_tier,
                    "delta": round(trust_state.trust_score - (agent_row.trust_score or 0.40), 4),
                })

                for v in self._violations:
                    broadcast("violation_detected", {
                        "agent_id": self.agent_id,
                        "run_id": run.id,
                        "policy_rule": v["policy_rule"],
                        "action_attempted": v["action_attempted"],
                    })
            except Exception:
                pass
