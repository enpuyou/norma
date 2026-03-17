"""Failure Attribution Engine — probabilistic per-node fault attribution.

Attribution is a confidence-weighted score, not a verdict.
Reports include evidence strings and alternative hypotheses.
Input-quality problems are never attributed to downstream agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class NodeResult:
    id: str
    input_quality_score: float
    output_quality_score: float
    confidence_score: float | None = None


@dataclass
class RunTree:
    nodes: list[NodeResult]
    input_quality_score: float   # quality of the original task input


def attribute_failure(run_tree: RunTree) -> dict[str, Any]:
    """
    Returns:
        most_likely_node:       str
        confidence:             float  (0.0–1.0)
        evidence:               str    (must be > 20 chars, non-generic)
        alternative_hypotheses: list[{node, confidence}]
    """
    # Input quality check — do not blame agents for bad inputs
    if run_tree.input_quality_score < 0.60:
        return {
            "most_likely_node": "input_quality",
            "confidence": 0.85,
            "evidence": (
                f"Input quality score {run_tree.input_quality_score:.2f} is below the 0.60 "
                "threshold. All agent nodes are excluded from attribution when input is malformed."
            ),
            "alternative_hypotheses": [],
        }

    node_scores: dict[str, dict[str, Any]] = {}
    for node in run_tree.nodes:
        quality_delta   = node.input_quality_score - node.output_quality_score
        confidence_flag = (node.confidence_score is not None and node.confidence_score < 0.70)
        attribution_prob = min(quality_delta * 1.5 + (0.2 if confidence_flag else 0), 1.0)
        node_scores[node.id] = {
            "quality_delta":    quality_delta,
            "confidence_flag":  confidence_flag,
            "attribution_prob": attribution_prob,
            "node":             node,
        }

    if not node_scores:
        return {
            "most_likely_node": "unknown",
            "confidence": 0.0,
            "evidence": "No nodes available for attribution.",
            "alternative_hypotheses": [],
        }

    best_id   = max(node_scores, key=lambda n: node_scores[n]["attribution_prob"])
    best_data = node_scores[best_id]
    best_prob = best_data["attribution_prob"]

    evidence = _build_evidence(best_id, best_data)

    alternatives = [
        {"node": nid, "confidence": round(d["attribution_prob"], 2)}
        for nid, d in node_scores.items()
        if nid != best_id and d["attribution_prob"] > 0.20
    ]

    return {
        "most_likely_node": best_id,
        "confidence": round(best_prob, 2),
        "evidence": evidence,
        "alternative_hypotheses": alternatives,
    }


def _build_evidence(node_id: str, data: dict[str, Any]) -> str:
    node: NodeResult = data["node"]
    parts = [
        f"Node '{node_id}': input quality {node.input_quality_score:.2f} → "
        f"output quality {node.output_quality_score:.2f} "
        f"(delta {data['quality_delta']:+.2f})."
    ]
    if data["confidence_flag"] and node.confidence_score is not None:
        parts.append(
            f"Confidence score {node.confidence_score:.2f} is below the 0.70 threshold, "
            "which increases attribution probability."
        )
    return " ".join(parts)
