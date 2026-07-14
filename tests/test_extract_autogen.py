"""Tests for AutoGen extractor using stub objects."""

from agentproof.graph.model import NodeKind, node_by_id, successors
from agentproof.graph.extract._autogen import extract_autogen


class AssistantAgent:
    def __init__(self, name):
        self.name = name


class UserProxyAgent:
    def __init__(self, name):
        self.name = name


class GroupChat:
    def __init__(self, agents, allowed_speaker_transitions_dict=None, speaker_selection_method=None):
        self.agents = agents
        self.allowed_speaker_transitions_dict = allowed_speaker_transitions_dict
        self.speaker_selection_method = speaker_selection_method
        self.name = "group_chat"


class TestAgentList:
    def test_basic_transitions(self):
        alice = AssistantAgent("alice")
        bob = AssistantAgent("bob")
        transitions = {alice: [bob], bob: [alice]}

        graph = extract_autogen([alice, bob], allowed_transitions=transitions)

        assert graph.framework == "autogen"
        assert graph.entry_id == "__entry__"

        alice_node = node_by_id(graph, "alice")
        assert alice_node is not None
        assert alice_node.kind == NodeKind.LLM

        # alice -> bob edge exists
        assert "bob" in successors(graph, "alice")
        assert "alice" in successors(graph, "bob")

    def test_user_proxy_classified_as_human(self):
        user = UserProxyAgent("user")
        assistant = AssistantAgent("assistant")
        transitions = {user: [assistant], assistant: [user]}

        graph = extract_autogen([user, assistant], allowed_transitions=transitions)

        user_node = node_by_id(graph, "user")
        assert user_node is not None
        assert user_node.kind == NodeKind.HUMAN

    def test_entry_connects_to_first(self):
        a = AssistantAgent("first")
        b = AssistantAgent("second")
        transitions = {a: [b]}

        graph = extract_autogen([a, b], allowed_transitions=transitions)
        assert "first" in successors(graph, "__entry__")

    def test_leaves_connect_to_exit(self):
        a = AssistantAgent("only")
        graph = extract_autogen([a])

        # 'only' has no outgoing edges in transitions, so it connects to __exit__
        assert "__exit__" in successors(graph, "only")


class TestGroupChat:
    def test_groupchat_object(self):
        alice = AssistantAgent("alice")
        bob = AssistantAgent("bob")
        transitions = {alice: [bob], bob: [alice]}
        gc = GroupChat(agents=[alice, bob], allowed_speaker_transitions_dict=transitions)

        graph = extract_autogen(gc)
        assert graph.name == "group_chat"
        assert "bob" in successors(graph, "alice")

    def test_round_robin(self):
        a = AssistantAgent("a")
        b = AssistantAgent("b")
        c = AssistantAgent("c")
        gc = GroupChat(agents=[a, b, c], speaker_selection_method="round_robin")

        graph = extract_autogen(gc)

        assert "b" in successors(graph, "a")
        assert "c" in successors(graph, "b")
        assert "a" in successors(graph, "c")


class SelectorGroupChat:
    """Stub whose type name triggers the v0.4 selector path."""

    def __init__(self, participants):
        self.participants = participants
        self.name = "selector_chat"


class TestEntryExit:
    def test_synthetic_nodes(self):
        a = AssistantAgent("agent")
        graph = extract_autogen([a])

        entry = node_by_id(graph, "__entry__")
        exit_n = node_by_id(graph, "__exit__")
        assert entry is not None and entry.kind == NodeKind.ENTRY
        assert exit_n is not None and exit_n.kind == NodeKind.EXIT


class TestProvenance:
    def test_agent_nodes_are_runtime_exact(self):
        alice = AssistantAgent("alice")
        bob = AssistantAgent("bob")
        graph = extract_autogen([alice, bob], allowed_transitions={alice: [bob]})

        for nid in ("alice", "bob"):
            n = node_by_id(graph, nid)
            assert n is not None
            assert n.origin == "runtime"
            assert n.confidence == "exact"

    def test_declared_transitions_are_runtime_exact(self):
        alice = AssistantAgent("alice")
        bob = AssistantAgent("bob")
        transitions = {alice: [bob], bob: [alice]}
        gc = GroupChat(agents=[alice, bob], allowed_speaker_transitions_dict=transitions)
        graph = extract_autogen(gc)

        ab = next(e for e in graph.edges if (e.source, e.target) == ("alice", "bob"))
        assert ab.origin == "runtime"
        assert ab.confidence == "exact"

    def test_round_robin_ordering_is_inferred(self):
        a = AssistantAgent("a")
        b = AssistantAgent("b")
        gc = GroupChat(agents=[a, b], speaker_selection_method="round_robin")
        graph = extract_autogen(gc)

        ab = next(e for e in graph.edges if (e.source, e.target) == ("a", "b"))
        # Reconstructed from the LIVE team object (no AST involved): origin is
        # "runtime" (the information source), confidence stays non-exact.
        assert ab.origin == "runtime"
        assert ab.confidence == "may"

    def test_selector_full_connectivity_is_heuristic(self):
        a = AssistantAgent("a")
        b = AssistantAgent("b")
        c = AssistantAgent("c")
        team = SelectorGroupChat([a, b, c])
        graph = extract_autogen(team)

        agent_ids = {"a", "b", "c"}
        between = [
            e for e in graph.edges
            if e.source in agent_ids and e.target in agent_ids
        ]
        assert len(between) == 6  # fully-connected expansion
        # Expansion of a live SelectorGroupChat -> runtime origin, but the
        # fully-connected over-approximation is a guess -> heuristic.
        assert all(e.origin == "runtime" for e in between)
        assert all(e.confidence == "heuristic" for e in between)

    def test_synthesized_elements_tagged_non_exact(self):
        a = AssistantAgent("only")
        graph = extract_autogen([a])

        for nid in ("__entry__", "__exit__"):
            n = node_by_id(graph, nid)
            assert n is not None
            assert n.origin == "synthesized"
            assert n.confidence != "exact"
        for e in graph.edges:
            if "__entry__" in (e.source, e.target) or "__exit__" in (e.source, e.target):
                assert e.origin == "synthesized"
                assert e.confidence != "exact"
