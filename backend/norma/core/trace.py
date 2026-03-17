"""TraceCollector — collects OpenTelemetry-style spans during an agent run.

Usage:

    collector = TraceCollector()
    root = collector.start_span("session", "financial-reader-v1")

    tool_span = collector.start_span("tool_call", "read_report", parent=root)
    # ... tool executes ...
    collector.end_span(tool_span, output_data='{"result": "..."}', tokens_out=120)

    llm_span = collector.start_span("llm_call", "gpt-4o", parent=root)
    collector.end_span(llm_span, tokens_in=800, tokens_out=200, cost_usd=0.003)

    spans = collector.spans  # list of SpanData dicts ready for DB persistence

SpanData is a plain dict so it has no dependency on SQLAlchemy — the session
layer converts them to Span ORM objects at flush time.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _span_id() -> str:
    """Generate a 16-char hex span ID (compatible with OTel trace/span IDs)."""
    return uuid.uuid4().hex[:16]


@dataclass
class SpanData:
    """In-memory representation of a span before DB persistence."""
    span_id: str
    span_type: str          # llm_call | tool_call | agent_handoff | enforcement_check | guardrail | session
    name: str
    parent_span_id: str | None = None
    status: str = "ok"      # ok | error | blocked
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None
    input_data: str | None = None    # JSON string
    output_data: str | None = None   # JSON string
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def is_finished(self) -> bool:
        return self.end_time is not None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict suitable for Span ORM constructor."""
        return {
            "span_id": self.span_id,
            "span_type": self.span_type,
            "name": self.name,
            "parent_span_id": self.parent_span_id,
            "status": self.status,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "attributes": json.dumps(self.attributes) if self.attributes else None,
        }


class TraceCollector:
    """Collects spans for a single run (trace).

    Thread-safe for the common case of sequential tool calls within a
    single agent run.  Not designed for concurrent writes from multiple threads.
    """

    def __init__(self) -> None:
        self._spans: list[SpanData] = []
        self._active: dict[str, SpanData] = {}  # span_id → SpanData (open spans)

    @property
    def spans(self) -> list[SpanData]:
        """All collected spans (finished and unfinished)."""
        return list(self._spans)

    @property
    def root_span(self) -> SpanData | None:
        """Return the root span (first span with no parent), if any."""
        for s in self._spans:
            if s.parent_span_id is None:
                return s
        return None

    def start_span(
        self,
        span_type: str,
        name: str,
        parent: SpanData | str | None = None,
        input_data: Any = None,
        attributes: dict[str, Any] | None = None,
    ) -> SpanData:
        """Start a new span and add it to the collection.

        Args:
            span_type: One of 'llm_call', 'tool_call', 'agent_handoff',
                       'enforcement_check', 'guardrail', 'session'.
            name: Human-readable name (tool name, model name, agent ID).
            parent: Parent SpanData object or parent span_id string, or None for root.
            input_data: Arbitrary data to store as JSON (will be serialized).
            attributes: Key-value metadata dict.

        Returns:
            The new SpanData object (pass to end_span when complete).
        """
        parent_id: str | None = None
        if isinstance(parent, SpanData):
            parent_id = parent.span_id
        elif isinstance(parent, str):
            parent_id = parent

        input_json: str | None = None
        if input_data is not None:
            try:
                input_json = json.dumps(input_data, default=str)[:5000]  # truncate
            except (TypeError, ValueError):
                input_json = str(input_data)[:5000]

        span = SpanData(
            span_id=_span_id(),
            span_type=span_type,
            name=name,
            parent_span_id=parent_id,
            input_data=input_json,
            attributes=attributes or {},
        )
        self._spans.append(span)
        self._active[span.span_id] = span
        return span

    def end_span(
        self,
        span: SpanData,
        *,
        output_data: Any = None,
        status: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        cost_usd: float | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> SpanData:
        """Finalize an open span with its results.

        Args:
            span: The SpanData returned by start_span().
            output_data: Result data (serialized to JSON).
            status: Override status ('ok', 'error', 'blocked').
            tokens_in: Input token count (for LLM calls).
            tokens_out: Output token count.
            cost_usd: Cost for this span.
            attributes: Additional attributes to merge.

        Returns:
            The updated SpanData.
        """
        span.end_time = datetime.now(timezone.utc)
        span.latency_ms = int((span.end_time - span.start_time).total_seconds() * 1000)

        if output_data is not None:
            try:
                span.output_data = json.dumps(output_data, default=str)[:5000]
            except (TypeError, ValueError):
                span.output_data = str(output_data)[:5000]

        if status is not None:
            span.status = status
        if tokens_in is not None:
            span.tokens_in = tokens_in
        if tokens_out is not None:
            span.tokens_out = tokens_out
        if cost_usd is not None:
            span.cost_usd = cost_usd
        if attributes:
            span.attributes.update(attributes)

        self._active.pop(span.span_id, None)
        return span

    def close_all(self) -> None:
        """End any still-open spans (safety net at session exit)."""
        for span in list(self._active.values()):
            if not span.is_finished:
                self.end_span(span, status="error",
                              attributes={"note": "auto-closed at session exit"})

    def total_tokens_in(self) -> int:
        """Sum of tokens_in across all spans."""
        return sum(s.tokens_in or 0 for s in self._spans)

    def total_tokens_out(self) -> int:
        """Sum of tokens_out across all spans."""
        return sum(s.tokens_out or 0 for s in self._spans)

    def total_cost(self) -> float:
        """Sum of cost_usd across all spans."""
        return sum(s.cost_usd or 0.0 for s in self._spans)

    def tool_call_count(self) -> int:
        """Number of tool_call spans."""
        return sum(1 for s in self._spans if s.span_type == "tool_call")

    def llm_call_count(self) -> int:
        """Number of llm_call spans."""
        return sum(1 for s in self._spans if s.span_type == "llm_call")

    def to_tree(self) -> dict[str, Any]:
        """Build a nested tree dict from the flat span list (for API response)."""
        by_id: dict[str, SpanData] = {s.span_id: s for s in self._spans}
        children: dict[str | None, list[SpanData]] = {}
        for s in self._spans:
            children.setdefault(s.parent_span_id, []).append(s)

        def _build(span: SpanData) -> dict[str, Any]:
            node = span.to_dict()
            node["children"] = [_build(c) for c in children.get(span.span_id, [])]
            return node

        root = self.root_span
        if root:
            return _build(root)
        return {"spans": [s.to_dict() for s in self._spans]}
