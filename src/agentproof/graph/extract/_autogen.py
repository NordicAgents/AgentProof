"""AutoGen agent topology extractor."""

from __future__ import annotations

from typing import Any

from agentproof.graph.model import (
    AgentGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)


def _classify_agent(agent: Any) -> NodeKind:
    type_name = type(agent).__name__
    if "UserProxy" in type_name:
        return NodeKind.HUMAN
    if "Assistant" in type_name:
        return NodeKind.LLM
    if "GroupChat" in type_name:
        return NodeKind.ROUTER
    return NodeKind.LLM


def _agent_name(agent: Any) -> str:
    return getattr(agent, "name", type(agent).__name__)


def _get_team_participants(team: Any) -> list[Any]:
    """Get participants from an AutoGen v0.4 team or v0.2 GroupChat."""
    # v0.4: .participants or ._participants
    participants = getattr(team, "participants", None)
    if participants is None:
        participants = getattr(team, "_participants", None)
    if participants is not None:
        return list(participants)
    # v0.2: .agents
    agents = getattr(team, "agents", None)
    if agents is not None:
        return list(agents)
    return []


def extract_autogen(
    agents_or_groupchat: Any,
    allowed_transitions: dict[Any, list[Any]] | None = None,
) -> AgentGraph:
    """Extract an AgentGraph from AutoGen agents.

    Accepts either:
    - A list of agents + allowed_speaker_transitions_dict
    - A GroupChat object (v0.2: reads .agents and .allowed_speaker_transitions_dict)
    - A v0.4 Team object (RoundRobinGroupChat, SelectorGroupChat)
    """
    agents: list[Any]
    transitions: dict[Any, list[Any]] | None
    # Provenance of the transition edges depends on how `transitions` was
    # obtained: declared dicts are runtime/exact; orderings the extractor
    # reconstructs from team semantics keep origin="runtime" (the information
    # source is the live object, no AST involved) with non-exact confidence.
    trans_origin = "runtime"
    trans_confidence = "exact"

    if isinstance(agents_or_groupchat, list):
        agents = agents_or_groupchat
        transitions = allowed_transitions
    else:
        type_name = type(agents_or_groupchat).__name__

        # v0.4 Team types
        if type_name == "RoundRobinGroupChat":
            agents = _get_team_participants(agents_or_groupchat)
            # Round-robin: each agent speaks to the next in cyclic order.
            # Real agents, ordering reconstructed from team semantics.
            transitions = {}
            for i, a in enumerate(agents):
                transitions[a] = [agents[(i + 1) % len(agents)]]
            trans_origin, trans_confidence = "runtime", "may"

        elif type_name == "SelectorGroupChat":
            agents = _get_team_participants(agents_or_groupchat)
            # Selector: any agent can speak to any other (fully connected).
            # Fully-connected expansion is a guessed over-approximation.
            transitions = {}
            for a in agents:
                transitions[a] = [b for b in agents if b is not a]
            trans_origin, trans_confidence = "runtime", "heuristic"

        else:
            # v0.2 GroupChat or similar
            agents = getattr(agents_or_groupchat, "agents", [])
            transitions = getattr(
                agents_or_groupchat,
                "allowed_speaker_transitions_dict",
                allowed_transitions,
            )

            # Detect round-robin if speaker_selection_method is set
            selection = getattr(agents_or_groupchat, "speaker_selection_method", None)
            if selection == "round_robin" and transitions is None:
                transitions = {}
                for i, a in enumerate(agents):
                    transitions[a] = [agents[(i + 1) % len(agents)]]
                trans_origin, trans_confidence = "runtime", "may"

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    agent_id_map: dict[int, str] = {}

    for agent in agents:
        # Agent objects are read from the live team/group chat: runtime/exact.
        nid = _agent_name(agent)
        kind = _classify_agent(agent)
        nodes.append(
            GraphNode(
                id=nid, kind=kind, label=nid,
                origin="runtime", confidence="exact",
            )
        )
        agent_id_map[id(agent)] = nid

    if transitions:
        for src_agent, targets in transitions.items():
            src_id = agent_id_map.get(id(src_agent))
            if src_id is None:
                continue
            for tgt_agent in targets:
                tgt_id = agent_id_map.get(id(tgt_agent))
                if tgt_id is None:
                    continue
                edges.append(
                    GraphEdge(
                        source=src_id, target=tgt_id,
                        origin=trans_origin, confidence=trans_confidence,
                    )
                )

    # Synthesize entry/exit: AutoGen declares no such nodes.
    entry = GraphNode(
        id="__entry__", kind=NodeKind.ENTRY, label="__entry__",
        origin="synthesized", confidence="may",
    )
    exit_node = GraphNode(
        id="__exit__", kind=NodeKind.EXIT, label="__exit__",
        origin="synthesized", confidence="may",
    )
    nodes.insert(0, entry)
    nodes.append(exit_node)

    if agents:
        # Judgment call: the initial speaker is assumed to be the first agent
        # in the list; AutoGen actually decides this at initiate_chat time.
        first_id = agent_id_map[id(agents[0])]
        edges.insert(
            0,
            GraphEdge(
                source="__entry__", target=first_id,
                origin="synthesized", confidence="heuristic",
            ),
        )

    # Nodes with no outgoing edges connect to exit: guessed connectivity.
    outgoing = {e.source for e in edges}
    agent_ids = {agent_id_map[id(a)] for a in agents}
    leaves = agent_ids - outgoing
    for leaf_id in sorted(leaves):
        edges.append(
            GraphEdge(
                source=leaf_id, target="__exit__",
                origin="synthesized", confidence="heuristic",
            )
        )

    name = getattr(agents_or_groupchat, "name", None) or "autogen"
    if isinstance(agents_or_groupchat, list):
        name = "autogen"

    return AgentGraph(
        name=str(name),
        framework="autogen",
        nodes=tuple(nodes),
        edges=tuple(edges),
        entry_id="__entry__",
        exit_ids=("__exit__",),
    )
