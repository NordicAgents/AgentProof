"""First-party integration adapters."""

from .langgraph import adapt_langgraph_proposal
from .openai import adapt_openai_tool_call

__all__ = ["adapt_langgraph_proposal", "adapt_openai_tool_call"]
