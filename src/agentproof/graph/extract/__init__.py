"""Lazy-import shim for framework extractors."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentproof.graph.model import AgentGraph


def extract_langgraph(graph: Any) -> AgentGraph:
    from ._langgraph import extract_langgraph as _impl

    return _impl(graph)


def extract_adk(agent: Any) -> AgentGraph:
    from ._adk import extract_adk as _impl

    return _impl(agent)


def extract_autogen(
    agents_or_groupchat: Any,
    allowed_transitions: dict[Any, list[Any]] | None = None,
) -> AgentGraph:
    from ._autogen import extract_autogen as _impl

    return _impl(agents_or_groupchat, allowed_transitions)


def extract_crewai(crew: Any) -> AgentGraph:
    from ._crewai import extract_crewai as _impl

    return _impl(crew)
