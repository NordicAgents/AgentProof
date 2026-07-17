"""Real-corpus policy library for AgentProof-CEGAR (Paper 2, plan §4.3).

The mined agent workflows in ``corpus/real_world/graphs_v2/`` are *real* and
therefore *lossy*: AST extraction gives us node kinds and connectivity with
mixed provenance, but the tools carry **no schema**, so every TOOL node lifts to
:attr:`~agentproof.cegar.ir.EffectKind.UNKNOWN`. Under the sound default gate
(:func:`agentproof.cegar.ir.region_is_certifiable`) this makes essentially every
real graph return :attr:`~agentproof.cegar.ir.Verdict.UNKNOWN` — which is the
*correct* behaviour and itself the headline measurement (it quantifies Paper 1's
extraction-bottleneck thesis). Nothing here weakens that gate.

This module provides three things (see the module functions/data below):

1. :func:`classify_tool` — a fixed, documented **MAY-side** heuristic that maps a
   real tool *name* to a likely :class:`~agentproof.cegar.ir.EffectKind`. It lets
   the analyzer *find candidate violations* on the may side; because it is a
   guess and not exact provenance it must never let anything certify
   :attr:`~agentproof.cegar.ir.Verdict.SAFE` — see :func:`lift_real`.
2. :func:`lift_real` — lift a flat corpus JSON into a
   :class:`~agentproof.cegar.ir.MayMustGraph`, optionally tagging TOOL nodes with
   heuristic effects **without touching the extracted provenance/confidence**.
3. :data:`POLICIES` — a library of deployer-style safety policies, plus
   :func:`policy_class` (each is shield-enforceable) and
   :func:`policy_alphabet_atoms`.

Soundness contract (why the heuristic cannot cause a false SAFE)
---------------------------------------------------------------
:func:`classify_tool` only ever *adds* a concrete effect to a node's MAY side.
Certification remains governed by the real provenance:

* A node with non-``exact`` provenance can never be certifiable
  (:attr:`EffectNode.is_certifiable` requires ``provenance.is_exact``), so the
  tag cannot flip it to SAFE — the tag only makes may-side violations *findable*.
* For the rare node that already carries ``exact`` provenance, :func:`lift_real`
  **keeps** the ``INCOMPLETE_SCHEMA`` unsupported fact (it does not remove it on
  the basis of a guessed effect), so the node stays non-certifiable and the guess
  can never underwrite a SAFE certificate. The ``INCOMPLETE_SCHEMA`` fact is only
  retired for nodes whose provenance is already non-exact, where certification is
  blocked by provenance anyway — there the removal is purely cosmetic.

The net guarantee: tagging can produce extra ``UNSAFE`` / ``UNKNOWN`` findings
(acceptable false alarms) but can never manufacture a ``SAFE``.
"""

from __future__ import annotations

from dataclasses import replace

from agentproof.cegar.frontend import lift
from agentproof.cegar.ir import (
    EffectKind,
    EffectNode,
    MayMustGraph,
    ToolSchema,
    UnsupportedKind,
)
from agentproof.cegar.policy import (
    Action,
    All,
    Approval,
    Bounded,
    Effect,
    Never,
    Policy,
    PolicyClass,
    PolicyContext,
    PredOr,
    Predicate,
    RequireBefore,
    Tool,
    classify,
)
from agentproof.graph.model import NodeKind, graph_from_dict


# ---------------------------------------------------------------------------
# 1. Real-tool effect classifier (a MAY-side heuristic only)
# ---------------------------------------------------------------------------

# A FIXED, documented substring table. Each rule is
# ``(EffectKind, keywords, sensitive, reversible)``. Rules are tried **in order**
# and the first whose keyword appears (case-insensitively) as a substring of the
# tool name wins, so more dangerous categories are matched first (e.g.
# ``rollback_deploy`` matches ``delete`` via "rollback" before ``execute`` via
# "deploy"). This ordering is part of the contract — do not reorder casually.
#
# ``sensitive``/``reversible`` follow the plan: financial / delete / execute are
# sensitive and irreversible; the rest are non-sensitive and reversible.
TOOL_EFFECT_RULES: tuple[tuple[EffectKind, tuple[str, ...], bool, bool], ...] = (
    (
        EffectKind.FINANCIAL,
        ("pay", "payment", "wire", "transfer", "refund", "invoice",
         "charge", "trade", "bank", "financial"),
        True,   # sensitive
        False,  # reversible
    ),
    (
        EffectKind.DELETE,
        ("delete", "drop", "remove", "rollback", "revoke", "purge",
         "destroy", "shutdown", "kill", "terminate"),
        True,
        False,
    ),
    (
        EffectKind.EXECUTE,
        ("exec", "shell", "bash", "run_", "deploy", "restart", "kubectl",
         "sql", "command", "script"),
        True,
        False,
    ),
    (
        EffectKind.COMMUNICATE,
        ("email", "send", "slack", "notify", "publish", "post",
         "message", "sms", "tweet"),
        False,
        True,
    ),
    (
        EffectKind.WRITE,
        ("write", "save", "update", "insert", "create", "upload",
         "commit", "store"),
        False,
        True,
    ),
    (
        EffectKind.READ,
        ("read", "get", "fetch", "search", "query", "list", "lookup",
         "retrieve", "scrape", "extract"),
        False,
        True,
    ),
)


def classify_tool(name: str) -> tuple[EffectKind, bool, bool]:
    """Guess a real tool's ``(effect, sensitive, reversible)`` from its name.

    Real agent tools carry no schema, so a TOOL node lifts to
    :attr:`EffectKind.UNKNOWN`. This maps the tool *name* to a likely effect by
    the fixed, ordered, case-insensitive substring rules in
    :data:`TOOL_EFFECT_RULES`. An unmatched name yields
    ``(EffectKind.UNKNOWN, False, True)``.

    This is a **heuristic MAY-side aid**: it lets the analyzer *find* candidate
    violations. It is *not* exact provenance and — per the module soundness
    contract — it must never let anything certify ``SAFE``. :func:`lift_real`
    enforces that by leaving provenance untouched.

    Parameters
    ----------
    name:
        The tool name (e.g. ``"wire_transfer"``, ``"rollback_deploy"``). An
        empty string returns the unmatched default.

    Returns
    -------
    tuple[EffectKind, bool, bool]
        ``(effect, sensitive, reversible)``.
    """
    lowered = name.lower()
    for effect, keywords, sensitive, reversible in TOOL_EFFECT_RULES:
        if any(kw in lowered for kw in keywords):
            return (effect, sensitive, reversible)
    return (EffectKind.UNKNOWN, False, True)


# ---------------------------------------------------------------------------
# 2. Real-corpus lift with optional may-side effect tagging
# ---------------------------------------------------------------------------

def lift_real(graph_dict: dict, *, tag_effects: bool = True) -> MayMustGraph:
    """Lift a flat corpus JSON into a may/must IR, tagging TOOL-node effects.

    Runs :func:`agentproof.graph.model.graph_from_dict` then
    :func:`agentproof.cegar.frontend.lift`. When ``tag_effects`` is ``True``,
    every TOOL node whose effect is still :attr:`EffectKind.UNKNOWN` and whose
    name :func:`classify_tool` can categorise gets a concrete
    :class:`~agentproof.cegar.ir.ToolSchema` attached so the node carries a
    concrete effect for **may-side** analysis.

    Crucially this does **not** change any node/edge provenance or confidence —
    certification stays governed by the real, lossy provenance. The
    ``INCOMPLETE_SCHEMA`` unsupported fact is retired only on nodes that are
    already non-exact (where certification is blocked by provenance regardless);
    on the rare ``exact`` node it is kept, so a guessed effect can never
    underwrite a ``SAFE`` certificate (see the module soundness contract).

    Parameters
    ----------
    graph_dict:
        A flat AgentGraph JSON dict (keys ``name``, ``framework``, ``entry_id``,
        ``exit_ids``, ``nodes``, ``edges``).
    tag_effects:
        When ``True`` (default) attach heuristic effects to TOOL nodes. When
        ``False`` the result is the plain provenance-faithful lift.

    Returns
    -------
    MayMustGraph
        The lifted may/must transition system.
    """
    agent_graph = graph_from_dict(graph_dict)
    mm = lift(agent_graph)
    if not tag_effects:
        return mm

    # TOOL-node ids come from the flat graph kinds (the lifted IR's
    # ``state_predicates`` are not a reliable kind carrier). We tag only real
    # tool nodes, never LLM/router/subgraph nodes.
    tool_ids = {n.id for n in agent_graph.nodes if n.kind is NodeKind.TOOL}

    nodes = tuple(
        _tag_tool_node(node) if node.id in tool_ids else node for node in mm.nodes
    )
    if nodes == mm.nodes:
        return mm
    return replace(mm, nodes=nodes)


def _tag_tool_node(node: EffectNode) -> EffectNode:
    """Attach a heuristic :class:`ToolSchema`/effect to an UNKNOWN TOOL node.

    Only acts when the node's effect is still :attr:`EffectKind.UNKNOWN` and the
    tool name classifies to a concrete effect. Provenance is never touched. The
    ``INCOMPLETE_SCHEMA`` fact is removed only for non-exact nodes (see
    :func:`lift_real` for the soundness rationale).
    """
    if node.effect is not EffectKind.UNKNOWN:
        return node

    # Prefer the bound tool name; fall back to the label when no tool is bound
    # (some corpus tool nodes carry the tool identity only in the label).
    name = node.tool or node.label
    effect, _sensitive, reversible = classify_tool(name)
    if effect is EffectKind.UNKNOWN:
        return node  # cannot categorise: leave the node UNKNOWN + INCOMPLETE_SCHEMA

    schema = ToolSchema(
        name=node.tool or name,
        effect=effect,
        reversible=reversible,
        complete=True,
    )

    unsupported = node.unsupported
    if not node.provenance.is_exact:
        # Non-exact node: provenance already blocks certification, so retiring
        # the now-modelled INCOMPLETE_SCHEMA placeholder is cosmetic and safe.
        unsupported = tuple(
            u for u in unsupported if u.kind is not UnsupportedKind.INCOMPLETE_SCHEMA
        )
    # Exact node: KEEP INCOMPLETE_SCHEMA so a guessed effect cannot certify SAFE.

    return replace(node, effect=effect, tool_schema=schema, unsupported=unsupported)


# ---------------------------------------------------------------------------
# 3. Policy library (deployer-style safety policies, plan §4.3)
# ---------------------------------------------------------------------------

# Concrete dangerous tool names that actually occur in the corpus. ``Tool`` binds
# to a node's *first* tool (``tools[0]``); ``restart_service`` is that first tool
# on the incident-response graph, and ``rollback_deploy`` appears both standalone
# and as a co-bound tool, so both are worth forbidding by name.
DANGEROUS_TOOLS: tuple[str, ...] = ("restart_service", "rollback_deploy")


def _sensitive_effect() -> Predicate:
    """``FINANCIAL ∨ DELETE ∨ EXECUTE`` as a single predicate."""
    return PredOr(
        Effect(EffectKind.FINANCIAL),
        PredOr(Effect(EffectKind.DELETE), Effect(EffectKind.EXECUTE)),
    )


# Each entry is ``(id, Policy, description)``. Every policy is a bad-prefix safety
# property, i.e. shield-enforceable (see :func:`policy_class`).
POLICIES: list[tuple[str, Policy, str]] = [
    (
        "approval_before_financial",
        RequireBefore(
            Approval(), Effect(EffectKind.FINANCIAL),
            rule_id="approval_before_financial",
        ),
        "A human approval must precede any FINANCIAL effect.",
    ),
    (
        "approval_before_delete",
        RequireBefore(
            Approval(), Effect(EffectKind.DELETE),
            rule_id="approval_before_delete",
        ),
        "A human approval must precede any DELETE effect.",
    ),
    (
        "approval_before_execute",
        RequireBefore(
            Approval(), Effect(EffectKind.EXECUTE),
            rule_id="approval_before_execute",
        ),
        "A human approval must precede any EXECUTE (shell/deploy/etc.) effect.",
    ),
    (
        "never_dangerous_tool",
        All(
            tuple(
                Never(Tool(t), rule_id=f"never_{t}") for t in DANGEROUS_TOOLS
            ),
            rule_id="never_dangerous_tool",
        ),
        "The dangerous corpus tools (restart_service, rollback_deploy) must "
        "never be invoked.",
    ),
    (
        "human_before_sensitive",
        RequireBefore(
            Approval(), _sensitive_effect(),
            rule_id="human_before_sensitive",
        ),
        "A human approval must precede any sensitive effect "
        "(FINANCIAL, DELETE, or EXECUTE).",
    ),
    (
        "bounded_router",
        Bounded(Action("router"), 3, rule_id="bounded_router"),
        "A router action may fire at most 3 times (illustrative retry/quota "
        "bound).",
    ),
]


# ---------------------------------------------------------------------------
# Classification metadata and alphabet helpers
# ---------------------------------------------------------------------------

def real_corpus_context() -> PolicyContext:
    """The declared vocabulary these policies are type-checked against.

    Declares the concrete dangerous tool names (so ``Tool(...)`` atoms type-check
    to :attr:`PolicyClass.SHIELD_ENFORCEABLE` rather than ``UNSUPPORTED``) on top
    of the default action types / capabilities. Effect / approval / action atoms
    need no extra declaration.
    """
    tools = {t: ToolSchema(name=t, effect=EffectKind.UNKNOWN) for t in DANGEROUS_TOOLS}
    return PolicyContext(tools=tools)


def policy_class(policy: Policy) -> PolicyClass:
    """Classify a policy against :func:`real_corpus_context`.

    Every policy in :data:`POLICIES` is a bad-prefix safety property, so this
    returns :attr:`PolicyClass.SHIELD_ENFORCEABLE` for all of them (a veto can
    enforce each one).
    """
    return classify(policy, real_corpus_context())


def policy_alphabet_atoms(policy: Policy) -> tuple[str, ...]:
    """Return the policy's leaf-atom alphabet as sorted, de-duplicated keys.

    These are the atoms the product monitor's transitions depend on
    (:meth:`Predicate.atom_key`), useful for reporting a policy's vocabulary.
    """
    keys = {atom.atom_key() for atom in policy.predicates()}
    return tuple(sorted(keys))


# ---------------------------------------------------------------------------
# __main__ smoke: lift ~20 real graphs and count verdicts for one policy
# ---------------------------------------------------------------------------

def _smoke() -> None:
    import glob
    import os
    from collections import Counter

    from agentproof.cegar.product import check

    # classify_tool sanity on the documented / corpus examples.
    assert classify_tool("wire_transfer")[0] is EffectKind.FINANCIAL
    assert classify_tool("rollback_deploy")[0] is EffectKind.DELETE   # delete before execute
    assert classify_tool("restart_service")[0] is EffectKind.EXECUTE
    assert classify_tool("send_email")[0] is EffectKind.COMMUNICATE
    assert classify_tool("read_financial_document")[0] is EffectKind.FINANCIAL  # financial 1st
    assert classify_tool("yt_tool") == (EffectKind.UNKNOWN, False, True)
    # sensitivity / reversibility flags.
    assert classify_tool("wire_transfer")[1] is True and classify_tool("wire_transfer")[2] is False

    # Every policy is shield-enforceable and round-trips its alphabet.
    for pid, pol, _desc in POLICIES:
        assert policy_class(pol) is PolicyClass.SHIELD_ENFORCEABLE, pid
        assert isinstance(policy_alphabet_atoms(pol), tuple)

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    corpus_dir = os.path.join(repo_root, "corpus", "real_world", "graphs_v2")
    files = sorted(glob.glob(os.path.join(corpus_dir, "*.json")))[:20]
    assert files, f"no corpus graphs under {corpus_dir}"

    import json

    # Report verdict counts for one representative policy.
    probe_id, probe_policy, _ = POLICIES[0]  # approval_before_financial
    verdicts: Counter[str] = Counter()
    tagged_tool_nodes = 0
    for path in files:
        with open(path, encoding="utf-8") as fh:
            graph_dict = json.load(fh)
        mm = lift_real(graph_dict, tag_effects=True)
        tagged_tool_nodes += sum(
            1 for n in mm.nodes if n.effect is not EffectKind.UNKNOWN and n.tool_schema is not None
        )
        result = check(mm, probe_policy)
        verdicts[result.verdict.value] += 1
        # Soundness invariant: no lifted real graph may certify SAFE off a
        # heuristic tag unless the whole explored region is genuinely certified.
        if result.verdict.value == "safe":
            assert result.certified, path

    print(f"lifted {len(files)} real graphs; tagged {tagged_tool_nodes} tool-effect nodes")
    print(f"policy '{probe_id}' verdicts: {dict(sorted(verdicts.items()))}")
    print("REAL POLICIES OK")


if __name__ == "__main__":
    _smoke()
