"""Abstraction-soundness property test (Paper 2, plan §7, §11; Theorem 1).

The cardinal contract: **no false SAFE**. For a battery of generated may/must
graphs and every concrete resolution the may-abstraction admits (a path through
the graph, with each abstract argument / UNKNOWN effect resolved to a concrete
value), if the independent oracle judges that concrete trace to *violate* the
policy, then the product checker must NOT return ``SAFE``.

Equivalently, and how we assert it: ``product.check(...) == SAFE`` implies every
admitted concrete resolution *satisfies* the policy. We also confirm the may
abstraction *contains* every concrete effect a resolution assigns (the
over-approximation direction of Theorem 1).
"""

from __future__ import annotations

import itertools

from agentproof.cegar import oracle
from agentproof.cegar.ir import (
    AbstractValue,
    EffectEvent,
    EffectKind,
    EffectNode,
    MayMustGraph,
    ModalEdge,
    Modality,
    Provenance,
    Verdict,
)
from agentproof.cegar.policy import (
    Approval,
    ArgConstraint,
    Bounded,
    Effect,
    Forbid,
    LeadsTo,
    Never,
    Op,
    Policy,
    RequireBefore,
    Tool,
)
from agentproof.cegar.product import check

_EXACT = Provenance("ast_explicit", "exact", "gen.py:1:1")


def _node(nid, *, effect=EffectKind.NONE, tool="", args=(), capability="", sp=()):
    return EffectNode(
        id=nid, effect=effect, tool=tool, abstract_args=args, capability=capability,
        state_predicates=sp, provenance=_EXACT, modeling_confidence="exact",
    )


def _e(u, v, modality=Modality.MUST):
    return ModalEdge(u, v, modality=modality, provenance=_EXACT)


# ---------------------------------------------------------------------------
# A deterministic battery of graphs
# ---------------------------------------------------------------------------

def _graphs() -> list[MayMustGraph]:
    graphs: list[MayMustGraph] = []

    # 1) linear must path with two tools
    graphs.append(MayMustGraph(
        "linear", "t",
        nodes=(_node("entry", sp=("kind:entry",)),
               _node("read", effect=EffectKind.READ, tool="read", sp=("kind:tool",)),
               _node("send", effect=EffectKind.COMMUNICATE, tool="send", sp=("kind:tool",)),
               _node("exit", sp=("kind:exit",))),
        edges=(_e("entry", "read"), _e("read", "send"), _e("send", "exit")),
        entry_id="entry", exit_ids=("exit",),
    ))

    # 2) branch (both may) — one branch calls a financial tool
    graphs.append(MayMustGraph(
        "branch", "t",
        nodes=(_node("entry", sp=("kind:entry",)),
               _node("pay", effect=EffectKind.FINANCIAL, tool="wire", sp=("kind:tool",)),
               _node("noop", sp=("kind:passthrough",)),
               _node("exit", sp=("kind:exit",))),
        edges=(_e("entry", "pay", Modality.MAY), _e("entry", "noop", Modality.MAY),
               _e("pay", "exit", Modality.MAY), _e("noop", "exit", Modality.MAY)),
        entry_id="entry", exit_ids=("exit",),
    ))

    # 3) financial tool with an abstract amount argument (TOP)
    graphs.append(MayMustGraph(
        "amount", "t",
        nodes=(_node("entry", sp=("kind:entry",)),
               _node("pay", effect=EffectKind.FINANCIAL, tool="wire",
                     args=(("amount", AbstractValue.top()),), sp=("kind:tool",)),
               _node("exit", sp=("kind:exit",))),
        edges=(_e("entry", "pay"), _e("pay", "exit")),
        entry_id="entry", exit_ids=("exit",),
    ))

    # 4) financial tool with a bounded interval amount
    graphs.append(MayMustGraph(
        "amount_iv", "t",
        nodes=(_node("entry", sp=("kind:entry",)),
               _node("pay", effect=EffectKind.FINANCIAL, tool="wire",
                     args=(("amount", AbstractValue.interval(0, 5000)),), sp=("kind:tool",)),
               _node("exit", sp=("kind:exit",))),
        edges=(_e("entry", "pay"), _e("pay", "exit")),
        entry_id="entry", exit_ids=("exit",),
    ))

    # 5) approval-before-financial (safe control)
    graphs.append(MayMustGraph(
        "approved", "t",
        nodes=(_node("entry", sp=("kind:entry",)),
               _node("approve", capability="human_pause", sp=("kind:human", "approval")),
               _node("pay", effect=EffectKind.FINANCIAL, tool="wire", sp=("kind:tool",)),
               _node("exit", sp=("kind:exit",))),
        edges=(_e("entry", "approve"), _e("approve", "pay"), _e("pay", "exit")),
        entry_id="entry", exit_ids=("exit",),
    ))

    # 6) two retries (bounded quota)
    graphs.append(MayMustGraph(
        "retries", "t",
        nodes=(_node("entry", sp=("kind:entry",)),
               _node("r1", tool="retry", sp=("kind:tool",)),
               _node("r2", tool="retry", sp=("kind:tool",)),
               _node("exit", sp=("kind:exit",))),
        edges=(_e("entry", "r1"), _e("r1", "r2"), _e("r2", "exit")),
        entry_id="entry", exit_ids=("exit",),
    ))

    return graphs


def _policies() -> list[Policy]:
    return [
        Never(Tool("wire"), rule_id="never_wire"),
        Never(Effect(EffectKind.FINANCIAL), rule_id="never_fin"),
        Never(ArgConstraint("wire", "amount", Op.GT, 1000), rule_id="amount_cap"),
        RequireBefore(Approval(), Effect(EffectKind.FINANCIAL), strict=True, rule_id="rb"),
        Forbid((Tool("read"), Tool("send")), contiguous=False, rule_id="exfil"),
        Bounded(Tool("retry"), 1, rule_id="retry_cap"),
        LeadsTo(Tool("read"), Tool("send"), rule_id="lt"),
    ]


# ---------------------------------------------------------------------------
# Concrete resolution enumeration
# ---------------------------------------------------------------------------

_ARG_POOL = [0, 500, 1000, 1001, 5000, 20000]


def _enumerate_paths(graph: MayMustGraph, max_len: int = 6) -> list[list[str]]:
    """All entry-rooted paths ending at a terminal (or hitting ``max_len``)."""
    paths: list[list[str]] = []

    def dfs(nid: str, acc: list[str]) -> None:
        acc = acc + [nid]
        out = graph.out_edges(nid)
        terminal = nid in graph.exit_ids or not out
        if terminal or len(acc) >= max_len:
            paths.append(acc)
            return
        for e in out:
            dfs(e.target, acc)

    dfs(graph.entry_id, [])
    return paths


def _node_events(node: EffectNode) -> list[EffectEvent]:
    """Every concrete event a resolution may assign to ``node``.

    Definite fields (tool, tags, capability) are copied; an UNKNOWN effect is
    resolved over all concrete effect kinds; each abstract argument is resolved
    over the finite candidate pool intersected with its concretization.
    """
    action = ""
    tags: list[str] = []
    for sp in node.state_predicates:
        if sp.startswith("kind:"):
            action = sp.split(":", 1)[1]
        else:
            tags.append(sp)

    if node.effect is EffectKind.UNKNOWN:
        effects = [k for k in EffectKind if k is not EffectKind.UNKNOWN]
    else:
        effects = [node.effect]

    arg_choices: list[list[tuple[str, object]]] = [[]]
    for name, av in node.abstract_args:
        vals = [v for v in _ARG_POOL if av.contains(v)]
        if not vals:  # e.g. a const outside the pool
            from agentproof.cegar.cegar import _pick_representative

            rep = _pick_representative(av)
            vals = [rep]
        arg_choices = [prev + [(name, v)] for prev in arg_choices for v in vals]

    events: list[EffectEvent] = []
    for eff in effects:
        for args in arg_choices:
            events.append(EffectEvent(
                node_id=node.id, effect=eff, tool_name=node.tool or None,
                action_type=action, args=tuple(args), capability=node.capability,
                tags=tuple(tags),
            ))
    return events


def _resolutions(graph: MayMustGraph, path: list[str]):
    """Cartesian product of per-node concrete events along ``path``."""
    per_node = [_node_events(graph.node_by_id(nid)) for nid in path]
    for combo in itertools.product(*per_node):
        yield tuple(combo)


# ---------------------------------------------------------------------------
# The property
# ---------------------------------------------------------------------------

def test_no_false_safe_over_all_resolutions():
    checked = 0
    for graph in _graphs():
        paths = _enumerate_paths(graph)
        for policy in _policies():
            result = check(graph, policy)
            if result.verdict is not Verdict.SAFE:
                continue  # the contract only constrains SAFE verdicts
            # SAFE must mean EVERY admitted concrete resolution satisfies.
            for path in paths:
                for trace in _resolutions(graph, path):
                    checked += 1
                    assert oracle.satisfies(policy, trace), (
                        "FALSE SAFE: product said SAFE but a concrete resolution "
                        f"violates: graph={graph.name} policy={result.rule_id} "
                        f"trace={[(e.node_id, e.effect.value, e.tool_name, e.args) for e in trace]}"
                    )
    assert checked > 40  # a meaningful number of SAFE resolutions cross-checked


def test_may_abstraction_contains_concrete_effects():
    """Every concrete effect a resolution assigns is in the node's may-set."""
    checked = 0
    for graph in _graphs():
        for node in graph.nodes:
            for ev in _node_events(node):
                may, _must = Effect(ev.effect).abstract_eval(node)
                assert may, (node.id, ev.effect, node.effect)
                checked += 1
    assert checked > 0


def test_definite_violation_paths_are_never_safe():
    """A must-path that concretely violates must never be certified SAFE."""
    for graph in _graphs():
        for policy in _policies():
            result = check(graph, policy)
            # Find a must-only path; if it violates concretely, verdict != SAFE.
            must_path = _must_path(graph)
            if must_path is None:
                continue
            for trace in _resolutions(graph, must_path):
                if not oracle.satisfies(policy, trace):
                    assert result.verdict is not Verdict.SAFE, (
                        graph.name, result.rule_id,
                        [e.node_id for e in trace],
                    )
                    break


def _must_path(graph: MayMustGraph) -> list[str] | None:
    """The unique path following only MUST edges from entry, if one exists."""
    path = [graph.entry_id]
    cur = graph.entry_id
    seen = {cur}
    while True:
        must_out = [e for e in graph.out_edges(cur) if e.modality is Modality.MUST]
        if len(must_out) != 1:
            break
        nxt = must_out[0].target
        if nxt in seen:
            break
        path.append(nxt)
        seen.add(nxt)
        cur = nxt
    return path if len(path) > 1 else None
