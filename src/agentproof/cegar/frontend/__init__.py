"""Framework semantic front-ends for AgentProof-CEGAR (plan §4.2).

A front-end turns a framework-specific agent program into an enriched
provenance-carrying :class:`~agentproof.cegar.ir.MayMustGraph`, attaching tool
schemas and explicit :class:`~agentproof.cegar.ir.UnsupportedFact` s for
constructs it cannot model precisely. The LangGraph front-end is the reference
implementation.
"""

from __future__ import annotations

from agentproof.cegar.frontend.langgraph import (
    default_tool_schemas,
    extract_and_lift,
    lift,
)

__all__ = ["lift", "extract_and_lift", "default_tool_schemas"]
