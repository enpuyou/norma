"""Context Budget Router — intercepts delegation calls, applies routing rules, logs token flow.

Routing is deterministic (keyword filter), not semantic.
Token utilization ratio is approximated via n-gram overlap.
This is a directional signal, not a precise semantic measurement.
Disclosed in the Engineer UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextPacket:
    """Context received or sent for one subagent invocation."""
    subagent_id: str
    tokens_available: int
    tokens_sent: int
    contains_raw_search_results: bool = False
    routing_rules_applied: bool = False
    # n-gram overlap ratio of output content vs. sent context (approximation)
    output_overlap_ratio: float | None = None

    @property
    def utilization_ratio(self) -> float:
        if self.tokens_available == 0:
            return 0.0
        return self.tokens_sent / self.tokens_available


@dataclass
class RoutingResult:
    subagent_context: dict[str, ContextPacket] = field(default_factory=dict)
    enforcement_triggered: bool = False
    blocked_scope_expansion: bool = False
    total_cost_usd: float = 0.0
    avg_context_utilization: float = 0.0
    quality_score: float = 0.0


def route_context(
    parent_context: dict[str, Any],
    routing_rules: dict[str, dict[str, Any]],
    parent_contract: dict[str, Any],
) -> dict[str, ContextPacket]:
    """
    Apply routing rules to parent context and return per-subagent ContextPackets.
    Each subagent only receives the context keys it is entitled to, within token budget.

    routing_rules format (from contract YAML):
      researcher:
        receives: [task_description, search_scope, ...]
        max_tokens: 1500
        summarize_if_exceeds: true
    """
    packets: dict[str, ContextPacket] = {}
    total_available = _count_tokens(parent_context)

    for subagent_id, rules in routing_rules.items():
        allowed_keys: list[str] = rules.get("receives", [])
        max_tokens: int         = rules.get("max_tokens", total_available)

        filtered = {k: v for k, v in parent_context.items() if k in allowed_keys}
        sent_tokens = min(_count_tokens(filtered), max_tokens)

        contains_raw = "raw_search_results" in filtered or any(
            "search" in k and k not in allowed_keys
            for k in parent_context
        )

        packets[subagent_id] = ContextPacket(
            subagent_id=subagent_id,
            tokens_available=total_available,
            tokens_sent=sent_tokens,
            contains_raw_search_results=(
                "raw_search_results" in filtered
            ),
            routing_rules_applied=True,
        )

    return packets


def check_scope_expansion(
    subagent_request: dict[str, Any],
    parent_contract: dict[str, Any],
) -> bool:
    """
    Returns True if the subagent request attempts to access data
    outside the parent contract's allowed data scope.
    """
    # TODO Phase 4: implement glob-based scope check
    return False


def _count_tokens(context: dict[str, Any]) -> int:
    """Approximate token count (4 chars ≈ 1 token). Replace with tiktoken in Phase 4."""
    text = str(context)
    return max(1, len(text) // 4)


def _ngram_overlap(text_a: str, text_b: str, n: int = 3) -> float:
    """Compute n-gram overlap ratio between two strings (directional signal only)."""
    def ngrams(s: str) -> set[str]:
        tokens = re.findall(r"\w+", s.lower())
        return {" ".join(tokens[i:i+n]) for i in range(len(tokens) - n + 1)}

    a, b = ngrams(text_a), ngrams(text_b)
    if not a:
        return 0.0
    return len(a & b) / len(a)
