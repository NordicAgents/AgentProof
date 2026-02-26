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


class TestEntryExit:
    def test_synthetic_nodes(self):
        a = AssistantAgent("agent")
        graph = extract_autogen([a])

        entry = node_by_id(graph, "__entry__")
        exit_n = node_by_id(graph, "__exit__")
        assert entry is not None and entry.kind == NodeKind.ENTRY
        assert exit_n is not None and exit_n.kind == NodeKind.EXIT
