"""
norma.integrations — one-line opt-in for existing agents.

Quick start:
    from norma.integrations import track, session

    # Wrap an existing LangGraph graph:
    graph = track(my_graph, agent_id="my-agent")

    # Or track a run manually:
    with session("my-agent") as s:
        result = my_graph.invoke(inputs)
        s.record_quality(score=0.91)
"""

from norma.integrations.track import RunSession, session, track
from norma.integrations.importer import NormaImporter
from norma.integrations.crewai_adapter import CrewAISession
from norma.integrations.autogen_adapter import AutoGenSession

__all__ = [
    "track",
    "session",
    "RunSession",
    "NormaImporter",
    "CrewAISession",
    "AutoGenSession",
]
