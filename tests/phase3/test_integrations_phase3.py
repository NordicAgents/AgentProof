from __future__ import annotations

from vac.integrations.langgraph import adapt_langgraph_proposal
from vac.integrations.openai import adapt_openai_tool_call


def test_openai_adapter_maps_tool_call_to_vac_proposal() -> None:
    tool_call = {
        "id": "call-123",
        "type": "function",
        "function": {
            "name": "email.send",
            "arguments": {"to": "user@example.com", "subject": "Hi", "body": "Hello"},
        },
    }

    proposal = adapt_openai_tool_call(
        tool_call,
        response_id="resp-1",
        turn_id="turn-7",
        correlation_id="corr-55",
        timestamp="2026-03-01T00:00:00Z",
    )

    assert proposal["schema_version"] == "1.0"
    assert proposal["tool_name"] == "email.send"
    assert proposal["input"]["to"] == "user@example.com"
    assert proposal["metadata"]["proposal_id"] == "call-123"
    assert proposal["metadata"]["response_id"] == "resp-1"


def test_langgraph_adapter_preserves_existing_metadata(valid_proposal) -> None:
    adapted = adapt_langgraph_proposal(
        valid_proposal,
        run_id="lg-run-1",
        node_id="adapter-node",
        thread_id="thread-9",
    )

    assert adapted["metadata"]["proposal_id"] == valid_proposal["metadata"]["proposal_id"]
    assert adapted["metadata"]["langgraph_run_id"] == "lg-run-1"
    assert adapted["metadata"]["langgraph_node_id"] == "adapter-node"
    assert adapted["metadata"]["langgraph_thread_id"] == "thread-9"
