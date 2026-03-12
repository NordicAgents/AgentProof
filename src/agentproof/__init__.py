"""Agentproof — static graph verification for agent workflow graphs."""

from .graph.model import AgentGraph, graph_from_dict, graph_to_dict
from .api import generate_traces, verify

__version__ = "0.3.0"

__all__: list[str] = [
    "AgentGraph",
    "generate_traces",
    "graph_from_dict",
    "graph_to_dict",
    "verify",
]
