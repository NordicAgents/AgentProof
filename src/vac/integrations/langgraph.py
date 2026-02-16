"""LangGraph proposal adapter preserving run metadata."""

from __future__ import annotations

from typing import Any, Mapping


def adapt_langgraph_proposal(
    proposal: Mapping[str, Any],
    *,
    run_id: str,
    node_id: str,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Attach LangGraph execution identifiers to VAC proposal metadata."""
    out = dict(proposal)
    metadata = dict(out.get("metadata", {}))
    metadata["langgraph_run_id"] = run_id
    metadata["langgraph_node_id"] = node_id
    if thread_id is not None:
        metadata["langgraph_thread_id"] = thread_id
    out["metadata"] = metadata
    return out
