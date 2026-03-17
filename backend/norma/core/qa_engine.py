"""Conversational Q&A Engine — answers questions grounded in the run database.

Design rules (from design doc):
  - Answers from data only. Never speculate beyond what the DB shows.
  - Every answer states what it does know and what it cannot determine.
  - No hallucination: if the data does not support a confident answer, say so.
  - Confidence levels: high | medium | low | cannot_determine
"""

from __future__ import annotations

from typing import Any

from norma.config import get_settings

settings = get_settings()

_SYSTEM_PROMPT = """You are norma.ai's Q&A engine. You answer questions about AI agent performance
using only the data provided to you in the context. Follow these rules:

1. Only state what the data supports. If the data is ambiguous or incomplete, say so explicitly.
2. Always include the sample size (n=X runs) and time window when citing metrics.
3. Never speculate about causes that cannot be confirmed from the run data.
4. End your answer by stating what you CANNOT determine from this data alone.
5. Use plain English appropriate for the audience (VP or Engineer).

Data context will be provided as JSON. Respond in JSON:
{
  "answer": "...",
  "data_sources": ["table.column used", ...],
  "confidence": "high|medium|low|cannot_determine",
  "caveats": ["what this answer cannot tell you", ...]
}
"""


async def answer_question(
    question: str,
    db_context: dict[str, Any],
    audience: str = "vp",   # "vp" or "engineer"
) -> dict[str, Any]:
    """
    Answer a natural language question using the provided DB context.

    db_context: pre-queried data dict (assembled by the API layer before calling this function)
    audience:   affects tone and detail level of the response

    Returns: {answer, data_sources, confidence, caveats}
    """
    # TODO Phase 7: implement with OpenAI client
    return {
        "answer": "The Q&A engine is not yet implemented. (Phase 7)",
        "data_sources": list(db_context.keys()),
        "confidence": "cannot_determine",
        "caveats": [
            "Q&A engine not yet implemented.",
            "Phase 7 will implement this with OpenAI and data-grounded prompting.",
        ],
    }
