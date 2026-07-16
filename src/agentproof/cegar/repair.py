"""Proof-carrying repair for AgentProof-CEGAR (Paper 2, §4.5; Theorems 3 & 4).

When the tri-valued analyzer (:mod:`agentproof.cegar.cegar`) reports ``UNSAFE``
or ``UNKNOWN`` on a program, this module tries to *repair* the program so it
verifies ``SAFE`` — and it does so **soundly**: a repair is only ever accepted
when the INDEPENDENT certificate checker (:mod:`agentproof.cegar.checker`)
admits a certificate for the patched program. The patch proposer (a solver, or
in a follow-up an LLM) is **outside the trusted computing base**: it may suggest
anything, but nothing it suggests is trusted. The gate is the checker.

The pieces (all in this file)
-----------------------------
* **A finite edit grammar** (10 operators) over the may/must IR. Each operator
  is total — ``applicable`` gates ``apply`` — and every node/edge it synthesizes
  carries :class:`~agentproof.cegar.ir.Provenance` ``origin="synthesized"``,
  ``confidence="exact"`` so the edit is *proof-eligible* (it is our own trusted
  transformation, not a guess). Each edit also records a machine-readable source
  hint into the ``refinement_history`` of what it touches, for later real
  source patching.
* **A published cost model** (:func:`edit_cost`, :class:`RepairConfig`):
  ``cost = changed_lines + l1*added_approvals + l2*lost_capability
           + l3*added_latency + l4*residual_unknown_behavior``.
* **Patch proposers** (:class:`PatchProposer`): :class:`GrammarProposer`
  enumerates applicable edit sequences up to ``max_edits`` (the default,
  solver-side, trusted only to *suggest*); :class:`NullProposer` proposes
  nothing. An :class:`LLMProposer` injection point is documented but deliberately
  unimplemented (no model dependency in the TCB).
* **The repair loop** (:func:`repair`): analyze, propose, re-analyze each
  candidate, and accept only the minimum-cost candidate whose patched program
  re-verifies ``SAFE`` *and* whose certificate the independent checker accepts.

Soundness directive
-------------------
A false ``SAFE`` is the cardinal sin. :func:`repair` never reports success on an
unverified or unchecked patch: success requires (1) :func:`~agentproof.cegar.cegar.analyze`
to return ``SAFE`` on the patched graph, (2) an optional user regression predicate
to pass, and (3) the independent :func:`~agentproof.cegar.checker.check_certificate`
to accept the certificate built from that SAFE result. If any candidate fails a
gate it is discarded; if none pass, ``success=False`` with the residual verdict.

Relative minimality (Theorem 4)
-------------------------------
:func:`repair` returns the *minimum-cost* accepted candidate **over the finite
set of edit sequences the proposer explored** (with the default
:class:`GrammarProposer`, all applicable sequences of at most ``max_edits``
operators). This is minimality relative to the explored grammar, not global
minimality over all conceivable program rewrites; the docstring states this
scope explicitly to avoid over-claiming.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Protocol, runtime_checkable

from agentproof.cegar import checker as checker_mod
from agentproof.cegar import certificate as certificate_mod
from agentproof.cegar.cegar import CegarResult, analyze
from agentproof.cegar.certificate import Certificate
from agentproof.cegar.ir import (
    ControlKind,
    EffectKind,
    EffectNode,
    MayMustGraph,
    ModalEdge,
    Modality,
    Provenance,
    Verdict,
)
from agentproof.cegar.policy import (
    All,
    Approval,
    Authority,
    Effect,
    Identity,
    Policy,
    Predicate,
    RequireBefore,
    rule_id_of,
)
from agentproof.cegar.product import Witness


# Provenance stamped on every synthesized (repair-inserted) node/edge. It is
# EXACT because the repair is our own trusted transformation of the IR — unlike
# a front-end guess, a synthesized approval gate provably emits the event we say
# it does — so the patched region stays certifiable.
_SYNTH = Provenance(origin="synthesized", confidence="exact", source_span="")

# Effect kinds that are (by default) irreversible and therefore warrant a
# transaction boundary / preview-commit gate.
_IRREVERSIBLE: frozenset[EffectKind] = frozenset(
    {EffectKind.FINANCIAL, EffectKind.DELETE, EffectKind.WRITE, EffectKind.EXECUTE}
)


# ===========================================================================
# Cost model (plan §4.5)
# ===========================================================================

@dataclass(frozen=True)
class RepairConfig:
    """Weights and budget for the published repair cost model.

    ``cost = changed_lines + l1*added_approvals + l2*lost_capability
             + l3*added_latency + l4*residual_unknown_behavior``.

    ``max_edits`` bounds the length of the edit sequences the default
    :class:`GrammarProposer` enumerates (and thus the search space).
    """

    l1: float = 2.0   # weight on added human-approval gates
    l2: float = 3.0   # weight on lost capability / functionality
    l3: float = 1.0   # weight on added latency (extra sequential steps)
    l4: float = 5.0   # weight on residual unknown behaviour after the patch
    max_edits: int = 3


@dataclass(frozen=True)
class CostContrib:
    """Per-operator contribution to the weighted cost terms.

    ``changed_lines`` is *not* here — it is measured structurally from the
    before/after graphs by :func:`edit_cost` (a diff proxy for touched source
    lines), so it stays honest even when several operators overlap.
    """

    added_approvals: int = 0
    lost_capability: int = 0
    added_latency: int = 0


def _structural_changed_lines(before: MayMustGraph, after: MayMustGraph) -> int:
    """A deterministic proxy for changed source lines: the IR-level diff size.

    Counts added, removed, and value-changed nodes plus the symmetric
    difference of the edge sets. Because nodes and edges are frozen dataclasses
    (value equality), a re-bound node counts as one changed line.
    """
    nb = {n.id: n for n in before.nodes}
    na = {n.id: n for n in after.nodes}
    added = set(na) - set(nb)
    removed = set(nb) - set(na)
    changed = {nid for nid in (set(na) & set(nb)) if na[nid] != nb[nid]}

    def _ekey(e: ModalEdge) -> tuple[str, str, str, str, str]:
        return (e.source, e.target, e.modality.value, e.control.value, e.guard)

    eb = {_ekey(e) for e in before.edges}
    ea = {_ekey(e) for e in after.edges}
    edge_diff = len(eb ^ ea)
    return len(added) + len(removed) + len(changed) + edge_diff


def _residual_unknown_behavior(graph: MayMustGraph) -> int:
    """Residual unknown behaviour left in ``graph``: unsupported facts + UNKNOWN
    effects. A fully certifiable, effect-resolved graph scores ``0``."""
    unsupported = len(graph.all_unsupported())
    unknown_effects = sum(1 for n in graph.nodes if n.effect is EffectKind.UNKNOWN)
    return unsupported + unknown_effects


def edit_cost(
    edits: list["EditOp"],
    graph_before: MayMustGraph,
    graph_after: MayMustGraph,
    config: RepairConfig,
) -> float:
    """The published repair cost of turning ``graph_before`` into ``graph_after``.

    ``cost = changed_lines + l1*added_approvals + l2*lost_capability
             + l3*added_latency + l4*residual_unknown_behavior`` where
    ``changed_lines`` is the structural IR diff and the weighted terms sum the
    per-operator :class:`CostContrib` contributions (residual unknown behaviour
    is measured on the *patched* graph).
    """
    changed = _structural_changed_lines(graph_before, graph_after)
    approvals = sum(e.cost_contrib().added_approvals for e in edits)
    lost = sum(e.cost_contrib().lost_capability for e in edits)
    latency = sum(e.cost_contrib().added_latency for e in edits)
    residual = _residual_unknown_behavior(graph_after)
    return (
        float(changed)
        + config.l1 * approvals
        + config.l2 * lost
        + config.l3 * latency
        + config.l4 * residual
    )


# ===========================================================================
# The finite edit grammar
# ===========================================================================

class EditOp:
    """Base class for the 10 repair operators (all frozen dataclasses).

    Contract (kept total): ``applicable(graph, policy, witness)`` gates
    ``apply(graph, policy, witness)`` — callers must not ``apply`` an edit that
    is not ``applicable`` on the current graph. ``describe`` is human-readable;
    ``source_hint`` is a machine-readable string stitched into the
    ``refinement_history`` of touched elements for later real source patching;
    ``cost_contrib`` returns the operator's weighted cost contribution.
    """

    def applicable(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError

    def apply(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> MayMustGraph:  # pragma: no cover - abstract
        raise NotImplementedError

    def describe(self) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def source_hint(self) -> str:
        return self.describe()

    def cost_contrib(self) -> CostContrib:
        return CostContrib()


# -- shared IR-surgery helpers ----------------------------------------------

def _fresh_id(graph: MayMustGraph, base: str) -> str:
    """A node id derived from ``base`` not already present in ``graph``."""
    existing = {n.id for n in graph.nodes}
    if base not in existing:
        return base
    i = 1
    while f"{base}_{i}" in existing:
        i += 1
    return f"{base}_{i}"


def _insert_before(
    graph: MayMustGraph, target_id: str, node: EffectNode, hint: str
) -> MayMustGraph:
    """Splice ``node`` onto every path into ``target_id``.

    Every edge ``u -> target`` is redirected to ``u -> node`` and a fresh
    ``node -> target`` MUST edge is added, so every concrete run that reaches
    ``target`` now traverses ``node`` first. Provenance on the new edge is
    synthesized-exact.
    """
    new_edges: list[ModalEdge] = []
    for e in graph.edges:
        if e.target == target_id:
            new_edges.append(replace(
                e, target=node.id,
                refinement_history=e.refinement_history + (hint,),
            ))
        else:
            new_edges.append(e)
    new_edges.append(ModalEdge(
        source=node.id, target=target_id, modality=Modality.MUST,
        control=ControlKind.DIRECT, provenance=_SYNTH,
        refinement_history=(hint,),
    ))
    return graph.with_node(node).with_edges(tuple(new_edges))


def _insert_on_edge(
    graph: MayMustGraph, u: str, v: str, node: EffectNode, hint: str
) -> MayMustGraph:
    """Splice ``node`` onto the single edge ``u -> v`` (``u -> node -> v``)."""
    modality = Modality.MUST
    control = ControlKind.DIRECT
    new_edges: list[ModalEdge] = []
    for e in graph.edges:
        if e.source == u and e.target == v:
            modality, control = e.modality, e.control
            new_edges.append(replace(
                e, target=node.id,
                refinement_history=e.refinement_history + (hint,),
            ))
        else:
            new_edges.append(e)
    new_edges.append(ModalEdge(
        source=node.id, target=v, modality=modality, control=control,
        provenance=_SYNTH, refinement_history=(hint,),
    ))
    return graph.with_node(node).with_edges(tuple(new_edges))


def _human_gate_node(graph: MayMustGraph, base: str, label: str, *, tag: str) -> EffectNode:
    """A synthesized human approval / confirmation gate node."""
    return EffectNode(
        id=_fresh_id(graph, base),
        effect=EffectKind.NONE,
        label=label,
        capability="human_pause",
        state_predicates=("kind:human", f"tag:{tag}"),
        provenance=_SYNTH,
        modeling_confidence="exact",
    )


# -- 1. InsertApprovalBefore -------------------------------------------------

@dataclass(frozen=True)
class InsertApprovalBefore(EditOp):
    """Insert a human approval gate on every edge into a node with ``effect``.

    Repairs :class:`~agentproof.cegar.policy.RequireBefore` (``Approval`` before
    an effect): after the edit every path that reaches the effect first passes
    through a ``kind:human`` / ``human_pause`` node that satisfies
    :class:`~agentproof.cegar.policy.Approval`.
    """

    effect: EffectKind

    def _targets(self, graph: MayMustGraph) -> list[str]:
        return sorted(
            n.id for n in graph.nodes
            if n.effect is self.effect and graph.predecessors(n.id)
        )

    def applicable(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> bool:
        return bool(self._targets(graph))

    def apply(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> MayMustGraph:
        g = graph
        for t in self._targets(graph):
            gate = _human_gate_node(
                g, f"approve_{t}", f"approval before {t}", tag="approval"
            )
            g = _insert_before(g, t, gate, self.source_hint())
        return g

    def describe(self) -> str:
        return f"InsertApprovalBefore(effect={self.effect.value})"

    def source_hint(self) -> str:
        return f"insert_approval_before(effect={self.effect.value})"

    def cost_contrib(self) -> CostContrib:
        return CostContrib(added_approvals=1, added_latency=1)


# -- 2. StrengthenRouterGuard ------------------------------------------------

@dataclass(frozen=True)
class StrengthenRouterGuard(EditOp):
    """Add/strengthen the guard on a router/conditional edge.

    Setting the guard of a spurious branch to ``"false"`` lets the CEGAR loop
    prove the transition dead and remove it during re-analysis, closing off a
    may-reachable bad branch.
    """

    edge: tuple[str, str]
    guard: str = "false"

    def _matches(self, graph: MayMustGraph) -> list[ModalEdge]:
        u, v = self.edge
        return [e for e in graph.edges if e.source == u and e.target == v]

    def applicable(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> bool:
        u, _v = self.edge
        matches = self._matches(graph)
        if not matches:
            return False
        # Meaningful only where the source actually branches.
        return len(graph.out_edges(u)) > 1 and any(e.guard != self.guard for e in matches)

    def apply(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> MayMustGraph:
        u, v = self.edge
        hint = self.source_hint()
        new_edges = tuple(
            replace(
                e, guard=self.guard, control=ControlKind.CONDITIONAL,
                refinement_history=e.refinement_history + (hint,),
            )
            if (e.source == u and e.target == v)
            else e
            for e in graph.edges
        )
        return graph.with_edges(new_edges)

    def describe(self) -> str:
        return f"StrengthenRouterGuard(edge={self.edge[0]}->{self.edge[1]}, guard={self.guard!r})"

    def source_hint(self) -> str:
        return f"strengthen_router_guard({self.edge[0]}->{self.edge[1]}:={self.guard})"

    def cost_contrib(self) -> CostContrib:
        return CostContrib()


# -- 3. RestrictToolBinding --------------------------------------------------

@dataclass(frozen=True)
class RestrictToolBinding(EditOp):
    """Remove/narrow a node's tool binding and its ``invokes_tool`` capability.

    Repairs :class:`~agentproof.cegar.policy.Never`-a-tool violations by unbinding
    the forbidden tool from the node (the node keeps its other structure).
    """

    node_id: str

    def _node(self, graph: MayMustGraph) -> EffectNode | None:
        return graph.node_by_id(self.node_id)

    def applicable(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> bool:
        n = self._node(graph)
        return n is not None and (bool(n.tool) or "invokes_tool" in n.capability)

    def apply(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> MayMustGraph:
        n = self._node(graph)
        if n is None:
            return graph
        caps = ",".join(c for c in n.capability.split(",") if c and c != "invokes_tool")
        new_node = replace(
            n, tool="", tool_schema=None, capability=caps,
            provenance=_SYNTH, modeling_confidence="exact",
            guards=n.guards + (self.source_hint(),),
        )
        return graph.with_node(new_node)

    def describe(self) -> str:
        return f"RestrictToolBinding(node={self.node_id})"

    def source_hint(self) -> str:
        return f"restrict_tool_binding({self.node_id})"

    def cost_contrib(self) -> CostContrib:
        return CostContrib(lost_capability=1)


# -- 4. MoveToLeastPrivilege -------------------------------------------------

@dataclass(frozen=True)
class MoveToLeastPrivilege(EditOp):
    """Re-bind a node's tool to a least-privilege executor (change principal)."""

    node_id: str
    principal: str = "least_privilege"

    def _node(self, graph: MayMustGraph) -> EffectNode | None:
        return graph.node_by_id(self.node_id)

    def applicable(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> bool:
        n = self._node(graph)
        return n is not None and bool(n.tool) and n.principal != self.principal

    def apply(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> MayMustGraph:
        n = self._node(graph)
        if n is None:
            return graph
        new_node = replace(
            n, principal=self.principal, identity=self.principal,
            provenance=_SYNTH, modeling_confidence="exact",
            guards=n.guards + (self.source_hint(),),
        )
        return graph.with_node(new_node)

    def describe(self) -> str:
        return f"MoveToLeastPrivilege(node={self.node_id}, principal={self.principal})"

    def source_hint(self) -> str:
        return f"move_to_least_privilege({self.node_id}->{self.principal})"

    def cost_contrib(self) -> CostContrib:
        return CostContrib()


# -- 5. AddAuthPrecondition --------------------------------------------------

@dataclass(frozen=True)
class AddAuthPrecondition(EditOp):
    """Add an authentication / identity state node before an effect.

    Repairs :class:`~agentproof.cegar.policy.RequireBefore` (``Identity`` /
    ``Authority`` before an effect) by splicing a node whose identity/authority
    satisfies the requirement onto every path into the effect.
    """

    node_id: str
    identity: str = "authenticated"

    def applicable(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> bool:
        n = graph.node_by_id(self.node_id)
        return n is not None and n.effect is not EffectKind.NONE and bool(graph.predecessors(self.node_id))

    def apply(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> MayMustGraph:
        auth = EffectNode(
            id=_fresh_id(graph, f"auth_{self.node_id}"),
            effect=EffectKind.NONE,
            label=f"authenticate before {self.node_id}",
            capability="state_update",
            identity=self.identity,
            authority=self.identity,
            state_predicates=("kind:tool", "tag:auth"),
            provenance=_SYNTH,
            modeling_confidence="exact",
        )
        return _insert_before(graph, self.node_id, auth, self.source_hint())

    def describe(self) -> str:
        return f"AddAuthPrecondition(node={self.node_id}, identity={self.identity})"

    def source_hint(self) -> str:
        return f"add_auth_precondition({self.node_id}, identity={self.identity})"

    def cost_contrib(self) -> CostContrib:
        return CostContrib(added_latency=1)


# -- 6. InsertSanitizer ------------------------------------------------------

@dataclass(frozen=True)
class InsertSanitizer(EditOp):
    """Insert a sanitizer/declassifier node between a labeled source and sink.

    The synthesized node clears the flowing data labels (a declassify step), so
    a tainted-flow policy no longer sees the labeled source reach the sink.
    """

    source: str
    sink: str

    def applicable(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> bool:
        return any(e.source == self.source and e.target == self.sink for e in graph.edges)

    def apply(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> MayMustGraph:
        san = EffectNode(
            id=_fresh_id(graph, f"sanitize_{self.source}_{self.sink}"),
            effect=EffectKind.NONE,
            label=f"sanitize {self.source}->{self.sink}",
            capability="state_update",
            in_labels=(),
            out_labels=(),
            state_predicates=("kind:tool", "tag:sanitizer"),
            provenance=_SYNTH,
            modeling_confidence="exact",
        )
        return _insert_on_edge(graph, self.source, self.sink, san, self.source_hint())

    def describe(self) -> str:
        return f"InsertSanitizer(source={self.source}, sink={self.sink})"

    def source_hint(self) -> str:
        return f"insert_sanitizer({self.source}->{self.sink})"

    def cost_contrib(self) -> CostContrib:
        return CostContrib(added_latency=1)


# -- 7. RepairExit -----------------------------------------------------------

@dataclass(frozen=True)
class RepairExit(EditOp):
    """Fix a dead end / bypass by reconnecting a stranded node to a proper exit."""

    node_id: str

    def applicable(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> bool:
        n = graph.node_by_id(self.node_id)
        if n is None or not graph.exit_ids:
            return False
        return self.node_id not in graph.exit_ids and not graph.out_edges(self.node_id)

    def apply(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> MayMustGraph:
        exit_id = graph.exit_ids[0]
        edge = ModalEdge(
            source=self.node_id, target=exit_id, modality=Modality.MUST,
            control=ControlKind.DIRECT, provenance=_SYNTH,
            refinement_history=(self.source_hint(),),
        )
        return graph.with_edges(graph.edges + (edge,))

    def describe(self) -> str:
        return f"RepairExit(node={self.node_id})"

    def source_hint(self) -> str:
        return f"repair_exit({self.node_id})"

    def cost_contrib(self) -> CostContrib:
        return CostContrib()


# -- 8. BoundLoop ------------------------------------------------------------

@dataclass(frozen=True)
class BoundLoop(EditOp):
    """Bound a loop/retry count by annotating a ``Bounded``-enforcing guard."""

    edge: tuple[str, str]
    k: int

    def _matches(self, graph: MayMustGraph) -> list[ModalEdge]:
        u, v = self.edge
        return [
            e for e in graph.edges
            if e.source == u and e.target == v
            and (e.control is ControlKind.LOOP)
        ]

    def applicable(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> bool:
        return bool(self._matches(graph))

    def apply(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> MayMustGraph:
        u, v = self.edge
        guard = f"iterations < {self.k}"
        hint = self.source_hint()
        new_edges = tuple(
            replace(e, guard=guard, refinement_history=e.refinement_history + (hint,))
            if (e.source == u and e.target == v and e.control is ControlKind.LOOP)
            else e
            for e in graph.edges
        )
        return graph.with_edges(new_edges)

    def describe(self) -> str:
        return f"BoundLoop(edge={self.edge[0]}->{self.edge[1]}, k={self.k})"

    def source_hint(self) -> str:
        return f"bound_loop({self.edge[0]}->{self.edge[1]}, k={self.k})"

    def cost_contrib(self) -> CostContrib:
        return CostContrib()


# -- 9. InsertTransactionBoundary --------------------------------------------

@dataclass(frozen=True)
class InsertTransactionBoundary(EditOp):
    """Insert a preview/commit (confirm) gate around an irreversible effect."""

    node_id: str

    def applicable(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> bool:
        n = graph.node_by_id(self.node_id)
        if n is None or not graph.predecessors(self.node_id):
            return False
        irreversible = n.effect in _IRREVERSIBLE
        if n.tool_schema is not None and not n.tool_schema.reversible:
            irreversible = True
        return irreversible

    def apply(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> MayMustGraph:
        confirm = _human_gate_node(
            graph, f"confirm_{self.node_id}",
            f"preview/commit before {self.node_id}", tag="confirm",
        )
        return _insert_before(graph, self.node_id, confirm, self.source_hint())

    def describe(self) -> str:
        return f"InsertTransactionBoundary(node={self.node_id})"

    def source_hint(self) -> str:
        return f"insert_transaction_boundary({self.node_id})"

    def cost_contrib(self) -> CostContrib:
        return CostContrib(added_approvals=1, added_latency=1)


# -- 10. RouteUnknownToApproval ---------------------------------------------

@dataclass(frozen=True)
class RouteUnknownToApproval(EditOp):
    """Route unresolved/UNKNOWN behaviour through an approval (deny-by-default).

    Splices a human approval gate before a node with an UNKNOWN effect or an
    unsupported fact. Note: this cannot by itself *erase* an unsupported fact, so
    a region that remains uncertifiable will stay ``UNKNOWN`` — which is the
    sound outcome (better than a false ``SAFE``).
    """

    node_id: str

    def applicable(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> bool:
        n = graph.node_by_id(self.node_id)
        if n is None or not graph.predecessors(self.node_id):
            return False
        return n.effect is EffectKind.UNKNOWN or bool(n.unsupported)

    def apply(self, graph: MayMustGraph, policy: Policy, witness: Witness | None) -> MayMustGraph:
        gate = _human_gate_node(
            graph, f"gate_{self.node_id}",
            f"approval gate before unknown {self.node_id}", tag="approval",
        )
        return _insert_before(graph, self.node_id, gate, self.source_hint())

    def describe(self) -> str:
        return f"RouteUnknownToApproval(node={self.node_id})"

    def source_hint(self) -> str:
        return f"route_unknown_to_approval({self.node_id})"

    def cost_contrib(self) -> CostContrib:
        return CostContrib(added_approvals=1, added_latency=1)


# ===========================================================================
# Patch proposers (untrusted — they only SUGGEST; the checker decides)
# ===========================================================================

@runtime_checkable
class PatchProposer(Protocol):
    """Proposes candidate edit sequences. **Never in the TCB.**

    A proposer may be a solver (:class:`GrammarProposer`) or, in a follow-up, an
    LLM. Its output is never trusted: every proposed patch is re-analyzed and
    only admitted if the independent certificate checker accepts it.
    """

    def propose(
        self,
        graph: MayMustGraph,
        policy: Policy,
        witness: Witness | None,
        config: RepairConfig,
    ) -> list[list[EditOp]]:
        ...


class NullProposer:
    """The baseline "no repair" proposer — proposes nothing."""

    def propose(
        self,
        graph: MayMustGraph,
        policy: Policy,
        witness: Witness | None,
        config: RepairConfig,
    ) -> list[list[EditOp]]:
        return []


# Cap on the number of candidate sequences the grammar proposer emits, so the
# search stays bounded and deterministic even on large graphs.
_MAX_CANDIDATES = 256


class GrammarProposer:
    """Default, solver-side proposer: enumerate applicable edit sequences.

    It derives a finite set of *applicable* single operators from the graph, the
    policy, and the witness, then enumerates all combinations of up to
    ``config.max_edits`` of them (deterministically ordered). It is trusted only
    to *suggest*; the repair loop verifies each candidate independently.
    """

    def propose(
        self,
        graph: MayMustGraph,
        policy: Policy,
        witness: Witness | None,
        config: RepairConfig,
    ) -> list[list[EditOp]]:
        ops = _enumerate_ops(graph, policy, witness)
        ops = [op for op in ops if op.applicable(graph, policy, witness)]
        # Deterministic order (by human description).
        ops = sorted(ops, key=lambda o: o.describe())

        sequences: list[list[EditOp]] = []
        max_r = max(1, min(config.max_edits, len(ops)))
        for r in range(1, max_r + 1):
            for combo in itertools.combinations(ops, r):
                sequences.append(list(combo))
                if len(sequences) >= _MAX_CANDIDATES:
                    return sequences
        return sequences


# The injection point for an untrusted LLM proposer. It is intentionally NOT
# implemented here (no model dependency belongs in the TCB). A real
# implementation would call a model to produce candidate `list[list[EditOp]]`
# from the witness/policy, then hand them — unaltered and untrusted — to the
# same repair loop, which admits a candidate only when the independent checker
# accepts its certificate. Sketch::
#
#     class LLMProposer:
#         def __init__(self, client): self._client = client
#         def propose(self, graph, policy, witness, config):
#             raw = self._client.suggest_edits(graph.to_dict(), policy.to_dict(),
#                                              witness.to_dict() if witness else None)
#             return _parse_edit_sequences(raw)   # untrusted; validated downstream


def _enumerate_ops(
    graph: MayMustGraph, policy: Policy, witness: Witness | None
) -> list[EditOp]:
    """Derive candidate single operators from the graph, policy, and witness.

    The witness path (if any) focuses the operators on the nodes implicated in
    the violation; without a witness we scan the whole graph.
    """
    focus = _witness_node_ids(graph, witness)
    focus_nodes = [graph.node_by_id(nid) for nid in focus]
    focus_nodes = [n for n in focus_nodes if n is not None]

    req_effects = _required_effects(policy)
    ops: list[EditOp] = []

    # Effects present on focus nodes (drives approval / transaction / auth ops).
    present_effects = {n.effect for n in focus_nodes if n.effect not in (EffectKind.NONE,)}
    for eff in sorted(present_effects | req_effects, key=lambda e: e.value):
        if any(n.effect is eff for n in graph.nodes):
            ops.append(InsertApprovalBefore(eff))

    for n in focus_nodes:
        if n.tool:
            ops.append(RestrictToolBinding(n.id))
            ops.append(MoveToLeastPrivilege(n.id))
        if n.effect is not EffectKind.NONE:
            ops.append(AddAuthPrecondition(n.id))
        if n.effect in _IRREVERSIBLE:
            ops.append(InsertTransactionBoundary(n.id))
        if n.effect is EffectKind.UNKNOWN or n.unsupported:
            ops.append(RouteUnknownToApproval(n.id))
        if n.in_labels or n.out_labels:
            for e in graph.out_edges(n.id):
                ops.append(InsertSanitizer(n.id, e.target))
        if not graph.out_edges(n.id) and n.id not in graph.exit_ids and graph.exit_ids:
            ops.append(RepairExit(n.id))

    # Branch-guard strengthening on the edges along the witness path.
    for i in range(len(focus) - 1):
        u, v = focus[i], focus[i + 1]
        if len(graph.out_edges(u)) > 1:
            ops.append(StrengthenRouterGuard((u, v)))

    # Loop bounds on any loop edge touching a focus node.
    focus_set = set(focus)
    for e in graph.edges:
        if e.control is ControlKind.LOOP and (e.source in focus_set or e.target in focus_set):
            ops.append(BoundLoop((e.source, e.target), 1))

    # De-duplicate by description (keep first).
    seen: set[str] = set()
    unique: list[EditOp] = []
    for op in ops:
        d = op.describe()
        if d not in seen:
            seen.add(d)
            unique.append(op)
    return unique


def _witness_node_ids(graph: MayMustGraph, witness: Witness | None) -> list[str]:
    if witness is not None and witness.product_path:
        return [nid for nid in witness.product_path if graph.node_by_id(nid) is not None]
    return [n.id for n in graph.nodes]


def _required_effects(policy: Policy) -> set[EffectKind]:
    """Effect kinds named by ``guarded`` predicates of RequireBefore sub-policies."""
    effects: set[EffectKind] = set()

    def rec(p: Policy) -> None:
        if isinstance(p, RequireBefore):
            for atom in p.guarded.atoms():
                if isinstance(atom, Effect):
                    effects.add(atom.kind)
        elif isinstance(p, All):
            for sub in p.policies:
                rec(sub)

    rec(policy)
    return effects


# ===========================================================================
# The repair loop
# ===========================================================================

@dataclass
class RepairResult:
    """Outcome of a proof-carrying repair attempt.

    ``success`` is ``True`` only when ``certificate`` was admitted by the
    INDEPENDENT checker; ``verdict`` is the final verdict of the patched program
    (``SAFE`` on success, else the best residual). ``edits`` are the human
    descriptions of the accepted edit sequence; ``cost`` its published cost;
    ``regression`` the user regression report; ``candidates_tried`` how many
    proposer candidates were evaluated.
    """

    success: bool
    verdict: Verdict
    patched_graph: MayMustGraph | None
    edits: list[str]
    cost: float | None
    certificate: Certificate | None
    iterations: int
    regression: dict
    candidates_tried: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "verdict": self.verdict.value,
            "patched_graph": self.patched_graph.to_dict() if self.patched_graph is not None else None,
            "edits": list(self.edits),
            "cost": self.cost,
            "certificate": self.certificate.to_dict() if self.certificate is not None else None,
            "iterations": self.iterations,
            "regression": dict(self.regression),
            "candidates_tried": self.candidates_tried,
        }


def _apply_edits(
    graph: MayMustGraph,
    policy: Policy,
    witness: Witness | None,
    edits: list[EditOp],
) -> tuple[MayMustGraph, list[EditOp]]:
    """Apply an edit sequence, skipping edits not applicable on the current graph.

    Returns the patched graph and the list of edits actually applied (each
    ``apply`` is gated by its own ``applicable`` on the graph as it stands).
    """
    g = graph
    applied: list[EditOp] = []
    for op in edits:
        if op.applicable(g, policy, witness):
            g = op.apply(g, policy, witness)
            applied.append(op)
    return g, applied


def _certify_and_check(
    graph_for_cert: MayMustGraph,
    policy: Policy,
    cegar_result: CegarResult,
    *,
    assume_trace_conservative: bool,
    repair_cost: float | None,
    regression_manifest: dict,
) -> Certificate | None:
    """Build a certificate from a SAFE result and return it ONLY if the
    independent checker accepts it (else ``None``)."""
    cert = certificate_mod.build_certificate(
        graph_for_cert,
        policy,
        cegar_result.product_result,
        assume_trace_conservative=assume_trace_conservative,
        repair_cost=repair_cost,
        regression_manifest=regression_manifest,
        created_tag="repair",
    )
    check = checker_mod.check_certificate(cert)
    return cert if check.accepted else None


def repair(
    graph: MayMustGraph,
    policy: Policy,
    *,
    config: RepairConfig = RepairConfig(),
    proposer: PatchProposer | None = None,
    regression: Callable[[MayMustGraph], tuple[bool, dict]] | None = None,
    assume_trace_conservative: bool = False,
) -> RepairResult:
    """Proof-carrying repair of ``graph`` against ``policy`` (plan §4.5).

    Steps:

    1. :func:`~agentproof.cegar.cegar.analyze` the original graph. If already
       ``SAFE``, build a certificate, confirm the INDEPENDENT checker accepts it,
       and return success with ``cost=0`` and no edits.
    2. Ask ``proposer`` (default :class:`GrammarProposer`) for candidate edit
       sequences (at most ``config.max_edits`` operators each).
    3. For each candidate: apply the edits, RE-ANALYZE the patched graph, and — if
       it is ``SAFE``, the optional ``regression`` predicate passes, and the
       independent :func:`~agentproof.cegar.checker.check_certificate` accepts the
       certificate — record it with its :func:`edit_cost`.
    4. Return the **minimum-cost accepted** candidate (relative minimality,
       Theorem 4 — minimal over the finite grammar the proposer explored, not
       over all possible rewrites). If none verify, ``success=False`` with the
       residual verdict of the original analysis.

    The proposer/solver is outside the TCB: :func:`repair` NEVER reports success
    on a patch that the independent checker did not admit.
    """
    prop: PatchProposer = proposer if proposer is not None else GrammarProposer()

    # -- 1. baseline analysis ------------------------------------------------
    base = analyze(
        graph, policy, assume_trace_conservative=assume_trace_conservative
    )
    if base.verdict is Verdict.SAFE:
        reg_ok, reg_report = (True, {})
        if regression is not None:
            reg_ok, reg_report = regression(base.refined_graph)
        cert = None
        if reg_ok:
            cert = _certify_and_check(
                base.refined_graph, policy, base,
                assume_trace_conservative=assume_trace_conservative,
                repair_cost=0.0,
                regression_manifest=reg_report,
            )
        if cert is not None:
            return RepairResult(
                success=True,
                verdict=Verdict.SAFE,
                patched_graph=base.refined_graph,
                edits=[],
                cost=0.0,
                certificate=cert,
                iterations=1,
                regression=reg_report,
                candidates_tried=0,
            )
        # Analyzer says SAFE but the independent checker (or regression) refused:
        # do not claim success. Fall through to attempt repair.

    # -- 2. gather candidates ------------------------------------------------
    witness = base.product_result.witness
    candidates = prop.propose(graph, policy, witness, config)

    best: tuple[float, tuple[str, ...], MayMustGraph, list[str], Certificate, dict] | None = None
    analyze_calls = 1
    tried = 0
    residual = base.verdict

    for edits in candidates:
        tried += 1
        patched, applied = _apply_edits(graph, policy, witness, edits)
        if not applied or patched == graph:
            continue  # nothing actually changed
        res = analyze(
            patched, policy, assume_trace_conservative=assume_trace_conservative
        )
        analyze_calls += 1
        if res.verdict is not Verdict.SAFE:
            if res.verdict is Verdict.UNKNOWN:
                residual = Verdict.UNKNOWN  # prefer UNKNOWN residual over UNSAFE
            continue

        # regression gate (on the certified/refined graph)
        reg_ok, reg_report = (True, {})
        if regression is not None:
            reg_ok, reg_report = regression(res.refined_graph)
        if not reg_ok:
            continue

        cost = edit_cost(applied, graph, patched, config)

        # independent-checker gate — the only thing that admits a repair
        cert = _certify_and_check(
            res.refined_graph, policy, res,
            assume_trace_conservative=assume_trace_conservative,
            repair_cost=cost,
            regression_manifest=reg_report,
        )
        if cert is None:
            continue

        desc = [op.describe() for op in applied]
        key = (cost, tuple(desc))
        if best is None or key < (best[0], best[1]):
            best = (cost, tuple(desc), res.refined_graph, desc, cert, reg_report)

    if best is not None:
        cost, _dkey, refined, desc, cert, reg_report = best
        return RepairResult(
            success=True,
            verdict=Verdict.SAFE,
            patched_graph=refined,
            edits=desc,
            cost=cost,
            certificate=cert,
            iterations=analyze_calls,
            regression=reg_report,
            candidates_tried=tried,
        )

    # -- 4. no verified repair ----------------------------------------------
    return RepairResult(
        success=False,
        verdict=residual,
        patched_graph=None,
        edits=[],
        cost=None,
        certificate=None,
        iterations=analyze_calls,
        regression={},
        candidates_tried=tried,
    )


# ===========================================================================
# Smoke test
# ===========================================================================

def _smoke() -> None:
    from agentproof.cegar.ir import Provenance as Prov
    from agentproof.cegar.policy import Never, Tool

    exact = Prov(origin="ast_explicit", confidence="exact", source_span="f.py:1:1")
    must = Modality.MUST

    def node(nid: str, *, effect=EffectKind.NONE, tool="", cap="", sp=()) -> EffectNode:
        return EffectNode(
            id=nid, effect=effect, tool=tool, capability=cap,
            provenance=exact, modeling_confidence="exact",
            state_predicates=sp,
        )

    # ---- (a) unguarded FINANCIAL effect vs RequireBefore(Approval, FINANCIAL) --
    ga = MayMustGraph(
        name="ga", framework="test",
        nodes=(
            node("entry"),
            node("pay", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                 cap="invokes_tool", sp=("kind:tool",)),
            node("exit"),
        ),
        edges=(
            ModalEdge("entry", "pay", modality=must, provenance=exact),
            ModalEdge("pay", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    pol_a = RequireBefore(Approval(), Effect(EffectKind.FINANCIAL),
                          rule_id="approve_before_financial")
    assert analyze(ga, pol_a).verdict is Verdict.UNSAFE
    ra = repair(ga, pol_a)
    assert ra.success, ra
    assert ra.verdict is Verdict.SAFE, ra
    assert ra.cost is not None and ra.cost > 0, ra
    assert ra.edits, ra.edits
    assert ra.certificate is not None
    assert checker_mod.check_certificate(ra.certificate).accepted, "cert not accepted (a)"
    # the accepted patched graph really verifies SAFE on re-analysis
    assert analyze(ra.patched_graph, pol_a).verdict is Verdict.SAFE, ra

    # ---- (b) forbidden-tool Never(...) repaired by RestrictToolBinding --------
    gb = MayMustGraph(
        name="gb", framework="test",
        nodes=(
            node("entry"),
            node("call", effect=EffectKind.EXECUTE, tool="wire_transfer",
                 cap="invokes_tool", sp=("kind:tool",)),
            node("exit"),
        ),
        edges=(
            ModalEdge("entry", "call", modality=must, provenance=exact),
            ModalEdge("call", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    pol_b = Never(Tool("wire_transfer"), rule_id="no_wire")
    assert analyze(gb, pol_b).verdict is Verdict.UNSAFE
    rb = repair(gb, pol_b)
    assert rb.success, rb
    assert rb.verdict is Verdict.SAFE, rb
    assert any("RestrictToolBinding" in e for e in rb.edits), rb.edits
    assert rb.certificate is not None
    assert checker_mod.check_certificate(rb.certificate).accepted, "cert not accepted (b)"

    # ---- (c) already-SAFE graph -> success, cost 0, 0 edits, cert accepted ----
    gc = MayMustGraph(
        name="gc", framework="test",
        nodes=(
            node("entry"),
            node("send", effect=EffectKind.COMMUNICATE, tool="send_email",
                 cap="invokes_tool", sp=("kind:tool",)),
            node("exit"),
        ),
        edges=(
            ModalEdge("entry", "send", modality=must, provenance=exact),
            ModalEdge("send", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    rc = repair(gc, Never(Tool("wire_transfer"), rule_id="no_wire"))
    assert rc.success, rc
    assert rc.verdict is Verdict.SAFE, rc
    assert rc.cost == 0.0, rc
    assert rc.edits == [], rc
    assert rc.certificate is not None
    assert checker_mod.check_certificate(rc.certificate).accepted, "cert not accepted (c)"

    # ---- (d) minimality: two verifying candidates, cheaper one wins -----------
    class TwoCandidateProposer:
        def propose(self, graph, policy, witness, config):
            cheap = [InsertApprovalBefore(EffectKind.FINANCIAL)]
            # a strictly costlier sequence that still verifies SAFE (two approvals)
            costly = [
                InsertApprovalBefore(EffectKind.FINANCIAL),
                InsertTransactionBoundary("pay"),
            ]
            return [costly, cheap]

    rd = repair(ga, pol_a, proposer=TwoCandidateProposer())
    assert rd.success, rd
    # the returned repair is the single-approval one (fewer edits, lower cost)
    assert rd.edits == ["InsertApprovalBefore(effect=financial)"], rd.edits
    cheap_cost = rd.cost
    # confirm the costly candidate really does cost more (sanity on the model)
    g_cheap, a_cheap = _apply_edits(
        ga, pol_a, None, [InsertApprovalBefore(EffectKind.FINANCIAL)])
    g_costly, a_costly = _apply_edits(
        ga, pol_a, None,
        [InsertApprovalBefore(EffectKind.FINANCIAL), InsertTransactionBoundary("pay")])
    assert edit_cost(a_cheap, ga, g_cheap, RepairConfig()) == cheap_cost, rd
    assert edit_cost(a_costly, ga, g_costly, RepairConfig()) > cheap_cost, "costly not costlier"

    # ---- (e) no false success on an unverified / tampered patch ---------------
    # (e1) NullProposer cannot repair an unsafe graph -> success False.
    re1 = repair(ga, pol_a, proposer=NullProposer())
    assert not re1.success, re1
    assert re1.verdict is Verdict.UNSAFE, re1
    assert re1.certificate is None and re1.patched_graph is None, re1

    # (e2) a hand-tampered certificate whose embedded graph is NOT actually safe
    #      is REJECTED by the independent checker (only the checker admits repairs).
    good_cert = ra.certificate
    tampered = certificate_mod.Certificate(
        program_hash=certificate_mod.canonical_hash(ga.to_dict()),  # recompute so hash gate passes
        policy_hash=good_cert.policy_hash,
        policy=good_cert.policy,
        graph=ga.to_dict(),                      # swap in the UNSAFE graph
        verdict="safe",
        supported_semantics=good_cert.supported_semantics,
        dependency_versions=good_cert.dependency_versions,
        assumptions=good_cert.assumptions,
        abstract_transitions=good_cert.abstract_transitions,
        repair_cost=good_cert.repair_cost,
        regression_manifest=good_cert.regression_manifest,
        created_tag=good_cert.created_tag,
    )
    tcheck = checker_mod.check_certificate(tampered)
    assert not tcheck.accepted, "tampered cert wrongly accepted"
    assert any("BAD PREFIX" in r for r in tcheck.reasons), tcheck.reasons

    # (e3) repair() itself NEVER claims success when the INDEPENDENT checker
    #      refuses — even on an already-SAFE graph the analyzer blesses. Stub the
    #      checker to reject everything and confirm both the already-safe path and
    #      the repair path return success=False (the checker is the sole gate).
    from agentproof.cegar.checker import CheckResult
    _orig_check = checker_mod.check_certificate
    try:
        checker_mod.check_certificate = (  # type: ignore[assignment]
            lambda cert: CheckResult(accepted=False, reasons=["stub: forced reject"])
        )
        re3_safe = repair(gc, Never(Tool("wire_transfer"), rule_id="no_wire"))
        assert not re3_safe.success, "repair claimed success despite checker reject (safe graph)"
        assert re3_safe.certificate is None, re3_safe
        re3_unsafe = repair(ga, pol_a)
        assert not re3_unsafe.success, "repair claimed success despite checker reject (repaired graph)"
        assert re3_unsafe.certificate is None and re3_unsafe.patched_graph is None, re3_unsafe
    finally:
        checker_mod.check_certificate = _orig_check  # type: ignore[assignment]
    # sanity: with the real checker restored, the same repair DOES succeed —
    # proving e3's failure was caused by the checker gate, not something else.
    assert repair(ga, pol_a).success, "real checker should admit the repair"

    # ---- serialization round-trips ----------------------------------------
    import json
    for res in (ra, rb, rc, rd, re1):
        json.dumps(res.to_dict())

    print("REPAIR SMOKE OK")


if __name__ == "__main__":
    _smoke()
