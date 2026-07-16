"""May/must effect intermediate representation for AgentProof-CEGAR (Paper 2).

This module is the **shared contract** for the tri-valued analyzer described in
``papers/paper2/EXPERIMENT_PLAN.md`` (§3, §4.1). Everything else in
:mod:`agentproof.cegar` imports its types from here.

Design commitments carried from the plan
-----------------------------------------
* **Tri-valued outcomes.** :class:`Verdict` is ``SAFE`` / ``UNSAFE`` /
  ``UNKNOWN``. ``UNKNOWN`` is a first-class result, never a silent ``SAFE``.
* **Uncertainty must survive.** Every :class:`EffectNode` and :class:`ModalEdge`
  carries :class:`Provenance`. Behaviour the front-end cannot model precisely
  is recorded as an explicit :class:`UnsupportedFact` (unknown dispatch,
  reflection, native calls, unresolved parallelism, nested agents, …). A region
  that contains an unsupported fact is *outside the abstraction contract* and
  can never be certified ``SAFE`` (§2.3, §4.1). :func:`region_is_certifiable`
  is the single predicate the product checker consults.
* **May/must modality.** Edges are ``MUST`` (the transition is forced),
  ``MAY`` (it can happen, e.g. a conditional/parallel branch), or ``UNKNOWN``
  (the front-end could not decide). The abstraction-soundness contract
  (Theorem 1) is ``Tr(P) ⊆ Tr_may(M(P))`` and ``Tr_must(M(P)) ⊆ Tr(P)``.
* **Flat graph is a compatibility view only.** :meth:`MayMustGraph.from_agent_graph`
  lifts Paper 1's flat :class:`~agentproof.graph.model.AgentGraph` into the IR
  *without erasing uncertainty*, and :meth:`MayMustGraph.to_agent_graph`
  projects back for visualization. The flat graph is not the proof abstraction.

Concrete semantics (the thing the abstraction over-approximates) is the finite
:class:`EffectEvent` trace model at the bottom of this file; the oracle and the
product checker both consume it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable, Mapping

# Reuse Paper 1's provenance vocabulary verbatim so the two systems agree on
# what "exact"/"may" and "runtime"/"ast_explicit"/… mean.
from agentproof.graph.model import (
    VALID_CONFIDENCES,
    VALID_ORIGINS,
    AgentGraph,
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
)


# ---------------------------------------------------------------------------
# Core enumerations
# ---------------------------------------------------------------------------

class Verdict(str, Enum):
    """Tri-valued analysis outcome (plan §3)."""

    SAFE = "safe"
    UNSAFE = "unsafe"
    UNKNOWN = "unknown"


class EffectKind(str, Enum):
    """Observable side effect of executing a node (plan §4.1).

    ``NONE`` is a genuine effect kind (pure routing / passthrough). Anything the
    front-end could not resolve is ``UNKNOWN`` *and* must be accompanied by an
    :class:`UnsupportedFact`; ``UNKNOWN`` on its own never licenses ``SAFE``.
    """

    NONE = "none"
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    COMMUNICATE = "communicate"
    FINANCIAL = "financial"
    DELETE = "delete"
    UNKNOWN = "unknown"


class Modality(str, Enum):
    """Edge modality in the may/must transition system."""

    MUST = "must"      # the transition is forced when the source is taken
    MAY = "may"        # the transition can happen (branch/parallel/loop)
    UNKNOWN = "unknown"  # front-end could not decide; conservatively ~ MAY


class ControlKind(str, Enum):
    """Control-flow shape of an edge (plan §4.1)."""

    DIRECT = "direct"
    CONDITIONAL = "conditional"
    LOOP = "loop"
    PARALLEL = "parallel"
    EXCEPTION = "exception"
    CALLBACK = "callback"
    DYNAMIC = "dynamic"  # dynamic dispatch (target not statically resolved)


class UnsupportedKind(str, Enum):
    """Taxonomy of behaviour outside the abstraction contract (plan §2.3, §4.1).

    A node/edge/graph carrying any of these is *not proof-eligible*: the region
    it participates in cannot be certified ``SAFE``. It must still remain
    visible in the model (never silently dropped).
    """

    UNKNOWN_DISPATCH = "unknown_dispatch"        # target resolved at runtime
    DIRECT_CALL_BYPASS = "direct_call_bypass"    # call bypasses declared tools
    INCOMPLETE_SCHEMA = "incomplete_schema"      # tool schema partially known
    UNMODELED_EXCEPTION = "unmodeled_exception"  # exception/abort not modeled
    UNRESOLVED_PARALLEL = "unresolved_parallel"  # parallel interleaving unknown
    NESTED_AGENT = "nested_agent"                # unmediated subagent
    REFLECTION = "reflection"                    # getattr/eval/exec-style
    NATIVE_EXTENSION = "native_extension"        # native / C extension call
    DYNAMIC_LOAD = "dynamic_load"                # importlib/dynamic code load
    ALIASING = "aliasing"                        # unresolved object aliasing
    CALLBACK = "callback"                        # unmodeled callback target
    GUESSED_STRUCTURE = "guessed_structure"      # connectivity/kind guessed


# ---------------------------------------------------------------------------
# Provenance (shared with Paper 1's vocabulary)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Provenance:
    """Where an element came from and how strong the claim is.

    ``origin`` ∈ :data:`~agentproof.graph.model.VALID_ORIGINS`,
    ``confidence`` ∈ :data:`~agentproof.graph.model.VALID_CONFIDENCES`.
    ``source_span`` is ``"file:start_line:end_line"`` or ``""``.
    Only ``confidence == "exact"`` elements can participate in a ``SAFE`` proof.
    """

    origin: str = "unknown"
    confidence: str = "may"
    source_span: str = ""

    def __post_init__(self) -> None:  # pragma: no cover - cheap guard
        if self.origin not in VALID_ORIGINS:
            raise ValueError(f"bad origin: {self.origin!r}")
        if self.confidence not in VALID_CONFIDENCES:
            raise ValueError(f"bad confidence: {self.confidence!r}")

    @property
    def is_exact(self) -> bool:
        return self.confidence == "exact"


@dataclass(frozen=True)
class UnsupportedFact:
    """An explicit statement that some behaviour is outside the contract."""

    kind: UnsupportedKind
    detail: str = ""
    source_span: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "detail": self.detail,
            "source_span": self.source_span,
        }

    @staticmethod
    def from_dict(d: Mapping[str, str]) -> "UnsupportedFact":
        return UnsupportedFact(
            kind=UnsupportedKind(d["kind"]),
            detail=d.get("detail", ""),
            source_span=d.get("source_span", ""),
        )


# ---------------------------------------------------------------------------
# Abstract value domain
# ---------------------------------------------------------------------------
# A small, finite-by-construction lattice over concrete argument values. The
# concretization gamma(a) is the set of concrete values `a` represents;
# `contains` tests membership. Refinement (CEGAR) only ever SPLITS a coarse
# value into finer values drawn from a *finite* candidate pool (the constants
# appearing in the program and policy), so the reachable lattice is finite —
# this is what underwrites conditional CEGAR termination (Theorem 5).

class AVKind(str, Enum):
    TOP = "top"        # gamma = everything (unknown)
    BOTTOM = "bottom"  # gamma = {} (unreachable)
    CONST = "const"    # gamma = {value}
    SET = "set"        # gamma = values (finite frozenset)
    INTERVAL = "interval"  # gamma = {x : lo <= x <= hi}, numeric


@dataclass(frozen=True)
class AbstractValue:
    """An element of the abstract-argument lattice."""

    kind: AVKind = AVKind.TOP
    value: Any = None                 # CONST
    values: frozenset = frozenset()   # SET
    lo: float = float("-inf")         # INTERVAL
    hi: float = float("inf")          # INTERVAL

    # -- constructors -------------------------------------------------------
    @staticmethod
    def top() -> "AbstractValue":
        return AbstractValue(AVKind.TOP)

    @staticmethod
    def bottom() -> "AbstractValue":
        return AbstractValue(AVKind.BOTTOM)

    @staticmethod
    def const(v: Any) -> "AbstractValue":
        return AbstractValue(AVKind.CONST, value=v)

    @staticmethod
    def one_of(vs: Iterable[Any]) -> "AbstractValue":
        s = frozenset(vs)
        if not s:
            return AbstractValue.bottom()
        if len(s) == 1:
            return AbstractValue.const(next(iter(s)))
        return AbstractValue(AVKind.SET, values=s)

    @staticmethod
    def interval(lo: float, hi: float) -> "AbstractValue":
        if lo > hi:
            return AbstractValue.bottom()
        return AbstractValue(AVKind.INTERVAL, lo=lo, hi=hi)

    # -- semantics ----------------------------------------------------------
    @property
    def is_top(self) -> bool:
        return self.kind is AVKind.TOP

    @property
    def is_bottom(self) -> bool:
        return self.kind is AVKind.BOTTOM

    def contains(self, c: Any) -> bool:
        """Is concrete value ``c`` in gamma(self)?"""
        if self.kind is AVKind.TOP:
            return True
        if self.kind is AVKind.BOTTOM:
            return False
        if self.kind is AVKind.CONST:
            return c == self.value
        if self.kind is AVKind.SET:
            return c in self.values
        if self.kind is AVKind.INTERVAL:
            try:
                return self.lo <= c <= self.hi
            except TypeError:
                return False
        return False  # pragma: no cover

    def join(self, other: "AbstractValue") -> "AbstractValue":
        """Least-upper-bound (over-approximation). Falls back to TOP."""
        if self.is_bottom:
            return other
        if other.is_bottom:
            return self
        if self.is_top or other.is_top:
            return AbstractValue.top()
        # both finite (CONST/SET): union of enumerable members
        a, b = self._members(), other._members()
        if a is not None and b is not None:
            return AbstractValue.one_of(a | b)
        if self.kind is AVKind.INTERVAL and other.kind is AVKind.INTERVAL:
            return AbstractValue.interval(min(self.lo, other.lo), max(self.hi, other.hi))
        return AbstractValue.top()

    def leq(self, other: "AbstractValue") -> bool:
        """Partial order: gamma(self) ⊆ gamma(other) (sound; may say False)."""
        if self.is_bottom or other.is_top:
            return True
        if self.is_top or other.is_bottom:
            return other.is_top  # TOP ⊆ x only if x is TOP; x ⊆ BOTTOM only x=BOTTOM
        a, b = self._members(), other._members()
        if a is not None and b is not None:
            return a <= b
        if self.kind is AVKind.INTERVAL and other.kind is AVKind.INTERVAL:
            return other.lo <= self.lo and self.hi <= other.hi
        if a is not None and other.kind is AVKind.INTERVAL:
            return all(other.contains(x) for x in a)
        return False

    def _members(self) -> frozenset | None:
        if self.kind is AVKind.CONST:
            return frozenset({self.value})
        if self.kind is AVKind.SET:
            return self.values
        return None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind.value}
        if self.kind is AVKind.CONST:
            d["value"] = self.value
        elif self.kind is AVKind.SET:
            d["values"] = sorted(self.values, key=repr)
        elif self.kind is AVKind.INTERVAL:
            d["lo"], d["hi"] = self.lo, self.hi
        return d

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "AbstractValue":
        k = AVKind(d["kind"])
        if k is AVKind.CONST:
            return AbstractValue.const(d["value"])
        if k is AVKind.SET:
            return AbstractValue.one_of(d["values"])
        if k is AVKind.INTERVAL:
            return AbstractValue.interval(d["lo"], d["hi"])
        return AbstractValue(k)


# ---------------------------------------------------------------------------
# Tool schema
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str = "any"          # "str" | "int" | "float" | "bool" | "any"
    sensitive: bool = False


@dataclass(frozen=True)
class ToolSchema:
    """Declared interface of a trusted tool (plan §2.1)."""

    name: str
    params: tuple[ParamSpec, ...] = ()
    effect: EffectKind = EffectKind.UNKNOWN
    authority_required: str = ""       # authority principal must hold, or ""
    reversible: bool = True            # irreversible tools need approval-before
    complete: bool = True              # False => INCOMPLETE_SCHEMA unsupported

    def param(self, name: str) -> ParamSpec | None:
        for p in self.params:
            if p.name == name:
                return p
        return None


# ---------------------------------------------------------------------------
# Nodes and edges
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EffectNode:
    """A node in the may/must effect transition system (plan §4.1)."""

    id: str
    effect: EffectKind = EffectKind.NONE
    label: str = ""
    # framework binding
    framework_object: str = ""
    call_target: str = ""
    tool: str = ""                      # bound tool name ("" if none)
    tool_schema: ToolSchema | None = None
    # abstract state
    abstract_args: tuple[tuple[str, AbstractValue], ...] = ()
    state_predicates: tuple[str, ...] = ()
    # authority / identity
    principal: str = ""
    authority: str = ""
    identity: str = ""
    capability: str = ""
    # data-flow labels
    in_labels: tuple[str, ...] = ()
    out_labels: tuple[str, ...] = ()
    # control behaviour local to the node
    guards: tuple[str, ...] = ()
    possible_exceptions: tuple[str, ...] = ()
    cancellation: bool = False
    abort: bool = False
    # provenance and proof-eligibility
    provenance: Provenance = field(default_factory=Provenance)
    modeling_confidence: str = "may"    # exact|may|heuristic (weakest attribute)
    unsupported: tuple[UnsupportedFact, ...] = ()

    def arg(self, name: str) -> AbstractValue:
        for n, v in self.abstract_args:
            if n == name:
                return v
        return AbstractValue.top()

    @property
    def is_certifiable(self) -> bool:
        """May this node participate in a ``SAFE`` proof?

        Requires exact provenance AND no unsupported facts. A node whose kind,
        binding, or effect was guessed (non-exact) could emit events the model
        does not predict, so it is not proof-eligible.
        """
        return self.provenance.is_exact and not self.unsupported


@dataclass(frozen=True)
class ModalEdge:
    """A may/must transition (plan §4.1)."""

    source: str
    target: str
    modality: Modality = Modality.MAY
    control: ControlKind = ControlKind.DIRECT
    guard: str = ""
    framework_rule: str = ""
    refinement_history: tuple[str, ...] = ()
    provenance: Provenance = field(default_factory=Provenance)
    unsupported: tuple[UnsupportedFact, ...] = ()

    @property
    def is_certifiable(self) -> bool:
        return self.provenance.is_exact and not self.unsupported


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MayMustGraph:
    """A provenance-carrying may/must effect transition system."""

    name: str
    framework: str
    nodes: tuple[EffectNode, ...]
    edges: tuple[ModalEdge, ...]
    entry_id: str
    exit_ids: tuple[str, ...] = ()
    unsupported: tuple[UnsupportedFact, ...] = ()  # graph-level facts

    # -- lookups ------------------------------------------------------------
    def node_by_id(self, node_id: str) -> EffectNode | None:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def successors(self, node_id: str, *, modality: Modality | None = None) -> tuple[str, ...]:
        return tuple(
            e.target
            for e in self.edges
            if e.source == node_id and (modality is None or e.modality is modality)
        )

    def predecessors(self, node_id: str) -> tuple[str, ...]:
        return tuple(e.source for e in self.edges if e.target == node_id)

    def out_edges(self, node_id: str) -> tuple[ModalEdge, ...]:
        return tuple(e for e in self.edges if e.source == node_id)

    def adjacency(self) -> dict[str, list[str]]:
        adj: dict[str, list[str]] = {n.id: [] for n in self.nodes}
        for e in self.edges:
            adj.setdefault(e.source, []).append(e.target)
        return adj

    def all_unsupported(self) -> tuple[UnsupportedFact, ...]:
        facts: list[UnsupportedFact] = list(self.unsupported)
        for n in self.nodes:
            facts.extend(n.unsupported)
        for e in self.edges:
            facts.extend(e.unsupported)
        return tuple(facts)

    def with_node(self, node: EffectNode) -> "MayMustGraph":
        """Return a copy with ``node`` replacing any same-id node (or appended)."""
        nodes = tuple(node if n.id == node.id else n for n in self.nodes)
        if all(n.id != node.id for n in self.nodes):
            nodes = nodes + (node,)
        return replace(self, nodes=nodes)

    def with_edges(self, edges: tuple[ModalEdge, ...]) -> "MayMustGraph":
        return replace(self, edges=edges)

    # -- serialization ------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return _graph_to_dict(self)

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "MayMustGraph":
        return _graph_from_dict(d)

    # -- flat-graph interop (compatibility view only) -----------------------
    def to_agent_graph(self) -> AgentGraph:
        return _to_agent_graph(self)

    @staticmethod
    def from_agent_graph(g: AgentGraph) -> "MayMustGraph":
        return _from_agent_graph(g)


# ---------------------------------------------------------------------------
# Proof-eligibility predicate (the linchpin of the SAFE gate)
# ---------------------------------------------------------------------------

def region_is_certifiable(
    graph: MayMustGraph,
    node_ids: Iterable[str],
    edges: Iterable[tuple[str, str]] = (),
    *,
    assume_trace_conservative: bool = False,
) -> bool:
    """Can the explored region participate in a ``SAFE`` certificate?

    The region is certifiable iff the caller asserts trace-conservatism, OR
    every visited node and traversed edge is exact and free of unsupported
    facts, AND the graph carries no graph-level unsupported fact. This mirrors
    (and generalizes to the effect IR) the certification gate in
    :mod:`agentproof.verify.temporal`. ``SAFE`` is forbidden whenever it
    returns ``False``.
    """
    if assume_trace_conservative:
        return True
    if graph.unsupported:
        return False
    node_ids = set(node_ids)
    for nid in node_ids:
        n = graph.node_by_id(nid)
        if n is None or not n.is_certifiable:
            return False
    edge_index: dict[tuple[str, str], list[ModalEdge]] = {}
    for e in graph.edges:
        edge_index.setdefault((e.source, e.target), []).append(e)
    for pair in edges:
        es = edge_index.get(pair)
        if not es or not all(e.is_certifiable for e in es):
            return False
    return True


# ---------------------------------------------------------------------------
# Concrete effect-trace model (what the abstraction over-approximates)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EffectEvent:
    """One concrete step of an execution.

    The ``action_type`` / ``tool_name`` / ``tags`` fields keep bit-compatible
    with Paper 1's event-dict shape (see
    :func:`agentproof.monitor.ltl._event_matches_predicate`) so the existing
    monitor machinery can be reused, while the richer fields carry the effect,
    authority, argument, identity, and data-label information Paper 2 needs.
    """

    node_id: str
    effect: EffectKind = EffectKind.NONE
    action_type: str = ""              # node kind value, compat
    tool_name: str | None = None
    args: tuple[tuple[str, Any], ...] = ()
    principal: str = ""
    authority: str = ""
    identity: str = ""
    capability: str = ""
    in_labels: tuple[str, ...] = ()
    out_labels: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    decision: str = ""

    def arg(self, name: str, default: Any = None) -> Any:
        for n, v in self.args:
            if n == name:
                return v
        return default

    def to_symbol_event(self) -> dict[str, Any]:
        """Project to the dict shape :func:`_event_symbol` consumes."""
        d: dict[str, Any] = {
            "node_id": self.node_id,
            "action_type": self.action_type,
            "tags": list(self.tags),
        }
        if self.tool_name is not None:
            d["tool_name"] = self.tool_name
        if self.decision:
            d["decision"] = self.decision
        return d


# A finite execution is a sequence of events.
Trace = tuple[EffectEvent, ...]


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _prov_to_dict(p: Provenance) -> dict[str, str]:
    return {"origin": p.origin, "confidence": p.confidence, "source_span": p.source_span}


def _prov_from_dict(d: Mapping[str, Any]) -> Provenance:
    return Provenance(
        origin=d.get("origin", "unknown"),
        confidence=d.get("confidence", "may"),
        source_span=d.get("source_span", ""),
    )


def _graph_to_dict(g: MayMustGraph) -> dict[str, Any]:
    return {
        "name": g.name,
        "framework": g.framework,
        "entry_id": g.entry_id,
        "exit_ids": list(g.exit_ids),
        "unsupported": [u.to_dict() for u in g.unsupported],
        "nodes": [
            {
                "id": n.id,
                "effect": n.effect.value,
                "label": n.label,
                "framework_object": n.framework_object,
                "call_target": n.call_target,
                "tool": n.tool,
                "tool_schema": _toolschema_to_dict(n.tool_schema),
                "abstract_args": [[k, v.to_dict()] for k, v in n.abstract_args],
                "state_predicates": list(n.state_predicates),
                "principal": n.principal,
                "authority": n.authority,
                "identity": n.identity,
                "capability": n.capability,
                "in_labels": list(n.in_labels),
                "out_labels": list(n.out_labels),
                "guards": list(n.guards),
                "possible_exceptions": list(n.possible_exceptions),
                "cancellation": n.cancellation,
                "abort": n.abort,
                "provenance": _prov_to_dict(n.provenance),
                "modeling_confidence": n.modeling_confidence,
                "unsupported": [u.to_dict() for u in n.unsupported],
            }
            for n in g.nodes
        ],
        "edges": [
            {
                "source": e.source,
                "target": e.target,
                "modality": e.modality.value,
                "control": e.control.value,
                "guard": e.guard,
                "framework_rule": e.framework_rule,
                "refinement_history": list(e.refinement_history),
                "provenance": _prov_to_dict(e.provenance),
                "unsupported": [u.to_dict() for u in e.unsupported],
            }
            for e in g.edges
        ],
    }


def _toolschema_to_dict(ts: ToolSchema | None) -> dict[str, Any] | None:
    if ts is None:
        return None
    return {
        "name": ts.name,
        "params": [{"name": p.name, "type": p.type, "sensitive": p.sensitive} for p in ts.params],
        "effect": ts.effect.value,
        "authority_required": ts.authority_required,
        "reversible": ts.reversible,
        "complete": ts.complete,
    }


def _toolschema_from_dict(d: Mapping[str, Any] | None) -> ToolSchema | None:
    if d is None:
        return None
    return ToolSchema(
        name=d["name"],
        params=tuple(
            ParamSpec(name=p["name"], type=p.get("type", "any"), sensitive=p.get("sensitive", False))
            for p in d.get("params", [])
        ),
        effect=EffectKind(d.get("effect", "unknown")),
        authority_required=d.get("authority_required", ""),
        reversible=d.get("reversible", True),
        complete=d.get("complete", True),
    )


def _graph_from_dict(d: Mapping[str, Any]) -> MayMustGraph:
    nodes = tuple(
        EffectNode(
            id=n["id"],
            effect=EffectKind(n.get("effect", "none")),
            label=n.get("label", ""),
            framework_object=n.get("framework_object", ""),
            call_target=n.get("call_target", ""),
            tool=n.get("tool", ""),
            tool_schema=_toolschema_from_dict(n.get("tool_schema")),
            abstract_args=tuple((k, AbstractValue.from_dict(v)) for k, v in n.get("abstract_args", [])),
            state_predicates=tuple(n.get("state_predicates", ())),
            principal=n.get("principal", ""),
            authority=n.get("authority", ""),
            identity=n.get("identity", ""),
            capability=n.get("capability", ""),
            in_labels=tuple(n.get("in_labels", ())),
            out_labels=tuple(n.get("out_labels", ())),
            guards=tuple(n.get("guards", ())),
            possible_exceptions=tuple(n.get("possible_exceptions", ())),
            cancellation=n.get("cancellation", False),
            abort=n.get("abort", False),
            provenance=_prov_from_dict(n.get("provenance", {})),
            modeling_confidence=n.get("modeling_confidence", "may"),
            unsupported=tuple(UnsupportedFact.from_dict(u) for u in n.get("unsupported", [])),
        )
        for n in d["nodes"]
    )
    edges = tuple(
        ModalEdge(
            source=e["source"],
            target=e["target"],
            modality=Modality(e.get("modality", "may")),
            control=ControlKind(e.get("control", "direct")),
            guard=e.get("guard", ""),
            framework_rule=e.get("framework_rule", ""),
            refinement_history=tuple(e.get("refinement_history", ())),
            provenance=_prov_from_dict(e.get("provenance", {})),
            unsupported=tuple(UnsupportedFact.from_dict(u) for u in e.get("unsupported", [])),
        )
        for e in d["edges"]
    )
    return MayMustGraph(
        name=d["name"],
        framework=d["framework"],
        nodes=nodes,
        edges=edges,
        entry_id=d["entry_id"],
        exit_ids=tuple(d.get("exit_ids", ())),
        unsupported=tuple(UnsupportedFact.from_dict(u) for u in d.get("unsupported", [])),
    )


# ---------------------------------------------------------------------------
# Flat AgentGraph interop
# ---------------------------------------------------------------------------

# NodeKind -> default effect kind when the flat node carries no `effects`.
_KIND_EFFECT: dict[NodeKind, EffectKind] = {
    NodeKind.ENTRY: EffectKind.NONE,
    NodeKind.EXIT: EffectKind.NONE,
    NodeKind.PASSTHROUGH: EffectKind.NONE,
    NodeKind.ROUTER: EffectKind.NONE,
    NodeKind.HUMAN: EffectKind.NONE,
    NodeKind.LLM: EffectKind.NONE,
    NodeKind.TOOL: EffectKind.UNKNOWN,   # a bound tool's effect is unknown a priori
    NodeKind.SUBGRAPH: EffectKind.UNKNOWN,
}

_EFFECT_STR: dict[str, EffectKind] = {e.value: e for e in EffectKind}

_CONTROL_FROM_EDGEKIND: dict[EdgeKind, ControlKind] = {
    EdgeKind.DIRECT: ControlKind.DIRECT,
    EdgeKind.CONDITIONAL: ControlKind.CONDITIONAL,
    EdgeKind.PARALLEL: ControlKind.PARALLEL,
    EdgeKind.LOOP: ControlKind.LOOP,
}


def _from_agent_graph(g: AgentGraph) -> MayMustGraph:
    """Lift a flat AgentGraph into the may/must IR without erasing uncertainty.

    Modality assignment: a DIRECT edge that is the *sole* successor of its
    source is ``MUST``; conditional/parallel/loop or multi-successor DIRECT
    edges are ``MAY``; an edge with unknown provenance is ``UNKNOWN``. Guessed
    structure (non-exact provenance) is recorded as a
    :class:`UnsupportedFact` (``GUESSED_STRUCTURE``) so it cannot be certified.
    A TOOL node whose effect cannot be resolved from ``effects`` carries an
    ``INCOMPLETE_SCHEMA`` unsupported fact.
    """
    succ_count: dict[str, int] = {}
    for e in g.edges:
        succ_count[e.source] = succ_count.get(e.source, 0) + 1

    nodes: list[EffectNode] = []
    for n in g.nodes:
        # effect: prefer the orthogonal `effects` descriptor; else fall back
        # to the NodeKind default. Multiple declared effects with different
        # kinds collapse to UNKNOWN (cannot pick one soundly).
        eff = _effect_from_flat(n)
        unsup: list[UnsupportedFact] = []
        prov = Provenance(origin=n.origin, confidence=n.confidence, source_span=n.source_span)
        if not prov.is_exact:
            unsup.append(UnsupportedFact(UnsupportedKind.GUESSED_STRUCTURE,
                                         detail=f"node kind/binding confidence={n.confidence}",
                                         source_span=n.source_span))
        if n.kind is NodeKind.TOOL and eff is EffectKind.UNKNOWN:
            unsup.append(UnsupportedFact(UnsupportedKind.INCOMPLETE_SCHEMA,
                                         detail=f"tool node {n.id} effect not resolved",
                                         source_span=n.source_span))
        if n.kind is NodeKind.SUBGRAPH:
            unsup.append(UnsupportedFact(UnsupportedKind.NESTED_AGENT,
                                         detail=f"subgraph {n.id}", source_span=n.source_span))
        caps = set(n.capabilities)
        nodes.append(EffectNode(
            id=n.id,
            effect=eff,
            label=n.label,
            tool=n.tools[0] if n.tools else "",
            capability=",".join(sorted(caps)),
            provenance=prov,
            modeling_confidence=n.confidence,
            unsupported=tuple(unsup),
            state_predicates=tuple(f"kind:{n.kind.value}"),
        ))

    edges: list[ModalEdge] = []
    for e in g.edges:
        prov = Provenance(origin=e.origin, confidence=e.confidence, source_span=e.source_span)
        control = _CONTROL_FROM_EDGEKIND.get(e.kind, ControlKind.DIRECT)
        if e.origin == "unknown":
            modality = Modality.UNKNOWN
        elif control is ControlKind.DIRECT and succ_count.get(e.source, 0) == 1 and not e.back_edge:
            modality = Modality.MUST
        else:
            modality = Modality.MAY
        if e.back_edge and control is ControlKind.DIRECT:
            control = ControlKind.LOOP
        unsup = []
        if not prov.is_exact:
            unsup.append(UnsupportedFact(UnsupportedKind.GUESSED_STRUCTURE,
                                         detail=f"edge {e.source}->{e.target} confidence={e.confidence}",
                                         source_span=e.source_span))
        edges.append(ModalEdge(
            source=e.source,
            target=e.target,
            modality=modality,
            control=control,
            guard=e.condition,
            provenance=prov,
            unsupported=tuple(unsup),
        ))

    return MayMustGraph(
        name=g.name,
        framework=g.framework,
        nodes=tuple(nodes),
        edges=tuple(edges),
        entry_id=g.entry_id,
        exit_ids=tuple(g.exit_ids),
    )


def _effect_from_flat(n: GraphNode) -> EffectKind:
    kinds = {_EFFECT_STR[e] for e in n.effects if e in _EFFECT_STR}
    if len(kinds) == 1:
        return next(iter(kinds))
    if len(kinds) > 1:
        return EffectKind.UNKNOWN  # several declared effects; cannot pick soundly
    return _KIND_EFFECT.get(n.kind, EffectKind.NONE)


# EffectNode -> flat NodeKind for the compat view. Best-effort; when the IR
# effect is ambiguous the node is projected as its recorded `kind:` predicate
# if present, else TOOL/LLM heuristics. Uncertainty is preserved by copying
# unsupported facts into node metadata.
def _to_agent_graph(g: MayMustGraph) -> AgentGraph:
    nodes: list[GraphNode] = []
    for n in g.nodes:
        kind = _flat_kind_for(n, g)
        meta: list[tuple[str, Any]] = []
        if n.unsupported:
            meta.append(("unsupported", [u.kind.value for u in n.unsupported]))
        effects = () if n.effect in (EffectKind.NONE, EffectKind.UNKNOWN) else (n.effect.value,)
        nodes.append(GraphNode(
            id=n.id,
            kind=kind,
            label=n.label,
            tools=(n.tool,) if n.tool else (),
            metadata=tuple(meta),
            origin=n.provenance.origin,
            confidence=n.provenance.confidence,
            source_span=n.provenance.source_span,
            effects=effects,
        ))
    edges: list[GraphEdge] = []
    for e in g.edges:
        ek = {
            ControlKind.DIRECT: EdgeKind.DIRECT,
            ControlKind.CONDITIONAL: EdgeKind.CONDITIONAL,
            ControlKind.PARALLEL: EdgeKind.PARALLEL,
            ControlKind.LOOP: EdgeKind.LOOP,
        }.get(e.control, EdgeKind.DIRECT)
        edges.append(GraphEdge(
            source=e.source,
            target=e.target,
            kind=ek,
            condition=e.guard,
            origin=e.provenance.origin,
            confidence=e.provenance.confidence,
            source_span=e.provenance.source_span,
            back_edge=(e.control is ControlKind.LOOP),
        ))
    return AgentGraph(
        name=g.name,
        framework=g.framework,
        nodes=tuple(nodes),
        edges=tuple(edges),
        entry_id=g.entry_id,
        exit_ids=tuple(g.exit_ids),
    )


def _flat_kind_for(n: EffectNode, g: MayMustGraph) -> NodeKind:
    if n.id == g.entry_id:
        return NodeKind.ENTRY
    if n.id in g.exit_ids:
        return NodeKind.EXIT
    for sp in n.state_predicates:
        if sp.startswith("kind:"):
            try:
                return NodeKind(sp.split(":", 1)[1])
            except ValueError:
                pass
    if n.tool:
        return NodeKind.TOOL
    if "routes" in n.capability:
        return NodeKind.ROUTER
    if "human_pause" in n.capability:
        return NodeKind.HUMAN
    return NodeKind.PASSTHROUGH
