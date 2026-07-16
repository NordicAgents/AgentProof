"""Tri-valued may/must product checker for AgentProof-CEGAR (Paper 2, §3, §4.4).

This module compiles a :class:`~agentproof.cegar.policy.Policy` into a small
deterministic *monitor* and explores the product of that monitor with a
:class:`~agentproof.cegar.ir.MayMustGraph`, returning a tri-valued
:class:`ProductResult` (``SAFE`` / ``UNSAFE`` / ``UNKNOWN``) together with a
source-level witness.

It is the abstract-interpretation analogue of
:func:`agentproof.verify.temporal.check_temporal_property`: instead of a flat
DFA over a single-valued graph it drives a monitor over a *may/must* transition
system where each edge is ``MUST`` (forced) or ``MAY`` (possible), and each node
carries an abstract valuation of the policy's leaf predicates via
:meth:`Predicate.abstract_eval`.

Design in three layers
----------------------
* **Part A — monitor compilation** (:func:`compile_monitor`). Each policy
  operator becomes a deterministic :class:`Monitor` whose transition depends
  ONLY on the truth values of the policy's leaf predicates at the current step,
  exposed through a *truth lookup* ``truth(pred) -> bool``. The very same
  monitor can therefore be stepped by a concrete :class:`EffectEvent` (with
  ``pred.eval``) or by an abstract valuation (with a predicate→bool mapping).
  Every monitor realises the SHARED FINITE-TRACE SEMANTICS documented in the
  sprint brief verbatim; a differential test cross-checks it against the
  denotational oracle, so the two must agree exactly.

* **Part B — abstract stepping** (:func:`post_states`). For an
  :class:`EffectNode` ``v`` and monitor state ``q`` each leaf predicate ``P``
  has ``(may, must) = P.abstract_eval(v)``. The truth assignments considered
  are the Cartesian product where ``P`` ranges over ``{True}`` if ``must``,
  ``{False}`` if ``not may``, else ``{True, False}``. Stepping the monitor under
  every assignment yields ``may_bad`` (some assignment violates), ``must_bad``
  (the forced assignment — each ``P`` at its ``must`` value — violates), and the
  set of successor monitor states.

* **Part C/D — product BFS and verdict synthesis** (:func:`check`). A BFS over
  product states ``(node_id, monitor_state)`` tracks two reachability flags:
  *may-reachable* (any path) and *must-reachable* (reached from entry using only
  ``MUST`` edges, following the forced monitor transition). A ``must``-reachable
  state whose ``must_bad`` (or, at termination, whose forced monitor state is
  non-accepting) is a DEFINITE violation ⇒ ``UNSAFE``. When nothing bad and no
  possibly-unfulfilled obligation is may-reachable AND the explored region is
  certifiable (:func:`agentproof.cegar.ir.region_is_certifiable`, the
  reviewer-#6 soundness gate), the verdict is ``SAFE``. Everything else is
  ``UNKNOWN`` — a may-violation candidate for CEGAR to concretise/refute, or an
  uncertified / unsupported region.
"""

from __future__ import annotations

import itertools
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from agentproof.cegar.ir import (
    EffectEvent,
    EffectNode,
    MayMustGraph,
    Modality,
    Verdict,
    region_is_certifiable,
)
from agentproof.cegar.policy import (
    All,
    Bounded,
    Forbid,
    LeadsTo,
    Never,
    Policy,
    PredAnd,
    PredNot,
    PredOr,
    Predicate,
    RequireBefore,
    TrueP,
    FalseP,
    rule_id_of,
)

# A truth lookup: maps a (possibly compound) predicate to its truth value at the
# current step. The monitor calls this on the exact predicate objects its
# operator holds, so the same monitor works for concrete and abstract stepping.
Truth = Callable[[Predicate], bool]

# Sentinel monitor state marking a safety monitor that has entered a bad-prefix
# (violation) state. Bad states are absorbing and never accepting.
_BAD = ("bad",)


# ===========================================================================
# Part A — deterministic monitors (one per policy operator)
# ===========================================================================

class Monitor:
    """A deterministic finite monitor over the policy's leaf-predicate truths.

    Subclasses realise the shared finite-trace semantics of one operator. The
    contract:

    * :attr:`initial_state` — a hashable start state.
    * :meth:`is_accepting` — may a finite trace validly END in this state? A
      safety monitor (``Never`` / ``RequireBefore`` / ``Forbid`` / ``Bounded``)
      is accepting in every non-bad state; a ``LeadsTo`` monitor is accepting
      only when no obligation is pending.
    * :meth:`step_truth` — advance one step given a truth lookup, returning
      ``(next_state, bad)`` where ``bad`` is ``True`` iff *this* step drives the
      monitor into a bad-prefix (violation) state. Bad states are absorbing and
      re-stepping them returns ``bad=False`` (the violation was already
      recorded on the earliest offending event).

    All states are hashable (ints, bools, and tuples/sentinels thereof).
    """

    initial_state: Any

    def is_accepting(self, state: Any) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError

    def step_truth(self, state: Any, truth: Truth) -> tuple[Any, bool]:  # pragma: no cover
        raise NotImplementedError

    # -- convenience stepping (a concrete event or an abstract valuation) ----
    def step_event(self, state: Any, event: EffectEvent) -> tuple[Any, bool]:
        """Step using a concrete event (leaf predicates via ``pred.eval``)."""
        return self.step_truth(state, lambda p: p.eval(event))

    def step_valuation(
        self, state: Any, valuation: dict[Predicate, bool]
    ) -> tuple[Any, bool]:
        """Step using an explicit predicate→bool valuation of the leaf atoms."""
        return self.step_truth(state, lambda p: _eval_pred_under(p, valuation))


class _NeverMonitor(Monitor):
    """``Never(pred)``: bad prefix at the first step where ``pred`` holds."""

    def __init__(self, pred: Predicate) -> None:
        self.pred = pred
        self.initial_state: Any = False  # False = not yet bad

    def is_accepting(self, state: Any) -> bool:
        return state is not True

    def step_truth(self, state: Any, truth: Truth) -> tuple[Any, bool]:
        if state is True:  # absorbing bad state
            return (True, False)
        if truth(self.pred):
            return (True, True)
        return (False, False)


class _RequireBeforeMonitor(Monitor):
    """``RequireBefore(required, guarded, strict)``.

    State is ``("ok", seen)`` where ``seen`` records that ``required`` has held,
    or :data:`_BAD`. Realises exactly:

    * ``strict=True``:  if ``guarded`` and not ``seen`` → BAD; then if
      ``required`` → ``seen=True``.
    * ``strict=False``: if ``required`` → ``seen=True``; then if ``guarded`` and
      not ``seen`` → BAD.
    """

    def __init__(self, required: Predicate, guarded: Predicate, strict: bool) -> None:
        self.required = required
        self.guarded = guarded
        self.strict = strict
        self.initial_state: Any = ("ok", False)

    def is_accepting(self, state: Any) -> bool:
        return state != _BAD

    def step_truth(self, state: Any, truth: Truth) -> tuple[Any, bool]:
        if state == _BAD:
            return (_BAD, False)
        seen = state[1]
        g = truth(self.guarded)
        r = truth(self.required)
        if self.strict:
            if g and not seen:
                return (_BAD, True)
            return (("ok", seen or r), False)
        # non-strict: the same event may satisfy both.
        seen2 = seen or r
        if g and not seen2:
            return (_BAD, True)
        return (("ok", seen2), False)


class _ForbidMonitor(Monitor):
    """``Forbid(steps, contiguous)``: a forbidden ordered sequence.

    State is an integer prefix-match index ``0..n``; ``n`` is the absorbing bad
    state (the whole sequence matched). Non-contiguous advances the index on a
    match of the next step; contiguous additionally *resets* to ``1`` (if the
    first step matches) or ``0`` on a mismatch.
    """

    def __init__(self, steps: tuple[Predicate, ...], contiguous: bool) -> None:
        self.steps = steps
        self.n = len(steps)
        self.contiguous = contiguous
        self.initial_state: Any = 0

    def is_accepting(self, state: Any) -> bool:
        return state < self.n

    def step_truth(self, state: Any, truth: Truth) -> tuple[Any, bool]:
        n = self.n
        if n == 0:
            # Degenerate empty sequence: nothing to forbid; never bad.
            return (0, False)
        if state >= n:  # absorbing bad state
            return (n, False)
        if self.contiguous:
            if truth(self.steps[state]):
                nxt = state + 1
            else:
                nxt = 1 if truth(self.steps[0]) else 0
        else:
            nxt = state + 1 if truth(self.steps[state]) else state
        if nxt == n:
            return (n, True)
        return (nxt, False)


class _BoundedMonitor(Monitor):
    """``Bounded(pred, k)``: bad prefix on the ``(k+1)``-th occurrence."""

    def __init__(self, pred: Predicate, k: int) -> None:
        self.pred = pred
        self.k = k
        self.initial_state: Any = 0

    def is_accepting(self, state: Any) -> bool:
        return state <= self.k

    def step_truth(self, state: Any, truth: Truth) -> tuple[Any, bool]:
        if state > self.k:  # absorbing bad state (== k+1)
            return (state, False)
        nxt = state + 1 if truth(self.pred) else state
        if nxt > self.k:
            return (self.k + 1, True)
        return (nxt, False)


class _LeadsToMonitor(Monitor):
    """``LeadsTo(trigger, response)``: a termination-time obligation.

    Never a bad prefix. State is a ``pending`` flag: a trigger sets it, a
    response clears it (both applied, in that order, on a single event). The
    monitor is accepting iff nothing is pending; an unfulfilled obligation is
    detected only at end of trace.
    """

    def __init__(self, trigger: Predicate, response: Predicate) -> None:
        self.trigger = trigger
        self.response = response
        self.initial_state: Any = False  # pending

    def is_accepting(self, state: Any) -> bool:
        return state is False

    def step_truth(self, state: Any, truth: Truth) -> tuple[Any, bool]:
        pending = state
        if truth(self.trigger):
            pending = True
        if truth(self.response):
            pending = False
        return (pending, False)


class _AllMonitor(Monitor):
    """``All(policies)``: the synchronous product of the sub-monitors.

    State is the tuple of sub-states. ``bad`` iff any sub-monitor is driven bad
    this step; accepting iff every sub-monitor is accepting.
    """

    def __init__(self, subs: tuple[Monitor, ...]) -> None:
        self.subs = subs
        self.initial_state: Any = tuple(s.initial_state for s in subs)

    def is_accepting(self, state: Any) -> bool:
        return all(sub.is_accepting(s) for sub, s in zip(self.subs, state))

    def step_truth(self, state: Any, truth: Truth) -> tuple[Any, bool]:
        next_states: list[Any] = []
        bad = False
        for sub, s in zip(self.subs, state):
            ns, b = sub.step_truth(s, truth)
            next_states.append(ns)
            bad = bad or b
        return (tuple(next_states), bad)


def compile_monitor(policy: Policy) -> Monitor:
    """Compile a :class:`Policy` into a deterministic :class:`Monitor`."""
    if isinstance(policy, Never):
        return _NeverMonitor(policy.pred)
    if isinstance(policy, RequireBefore):
        return _RequireBeforeMonitor(policy.required, policy.guarded, policy.strict)
    if isinstance(policy, Forbid):
        return _ForbidMonitor(policy.steps, policy.contiguous)
    if isinstance(policy, Bounded):
        return _BoundedMonitor(policy.pred, policy.k)
    if isinstance(policy, LeadsTo):
        return _LeadsToMonitor(policy.trigger, policy.response)
    if isinstance(policy, All):
        return _AllMonitor(tuple(compile_monitor(p) for p in policy.policies))
    raise ValueError(f"cannot compile monitor for policy: {policy!r}")


# ===========================================================================
# Predicate evaluation under an abstract leaf-atom valuation
# ===========================================================================

def _eval_pred_under(pred: Predicate, valuation: dict[Predicate, bool]) -> bool:
    """Truth of a (possibly compound) predicate under a leaf-atom valuation.

    The valuation assigns a bool to each leaf *atom* (``pred.atoms()``); the
    Boolean structure of ``Not`` / ``And`` / ``Or`` / ``True`` / ``False`` is
    evaluated over it. This mirrors :meth:`Predicate.eval` but drives the truth
    from the abstract assignment rather than a concrete event.
    """
    if isinstance(pred, TrueP):
        return True
    if isinstance(pred, FalseP):
        return False
    if isinstance(pred, PredNot):
        return not _eval_pred_under(pred.inner, valuation)
    if isinstance(pred, PredAnd):
        return _eval_pred_under(pred.left, valuation) and _eval_pred_under(pred.right, valuation)
    if isinstance(pred, PredOr):
        return _eval_pred_under(pred.left, valuation) or _eval_pred_under(pred.right, valuation)
    return valuation.get(pred, False)


def _unique_atoms(policy: Policy) -> list[Predicate]:
    """Leaf atoms of a policy, de-duplicated and deterministically ordered."""
    seen: dict[Predicate, None] = {}
    for atom in policy.predicates():
        seen.setdefault(atom, None)
    return sorted(seen.keys(), key=lambda a: a.atom_key())


def _allowed_values(atom: Predicate, node: EffectNode) -> tuple[bool, ...]:
    """Truth values ``atom`` can take at ``node`` under its (may, must) pair."""
    may, must = atom.abstract_eval(node)
    if must:
        return (True,)
    if not may:
        return (False,)
    return (False, True)


# ===========================================================================
# Part B — abstract stepping over an EffectNode
# ===========================================================================

@dataclass
class _Expansion:
    """The result of stepping a monitor across one abstract node."""

    succ_states: list[Any]                 # unique successor monitor states
    forced_state: Any                      # successor under the forced (must) assignment
    forced_bad: bool                       # forced assignment drives a violation
    may_bad: bool                          # some assignment drives a violation
    bad_assignment: dict[Predicate, bool] | None      # a witnessing bad assignment
    has_nonaccepting: bool                 # some assignment yields a non-accepting state
    nonacc_assignment: dict[Predicate, bool] | None   # a witnessing non-accepting assignment


def _expand(
    monitor: Monitor, atoms: list[Predicate], node: EffectNode, state: Any
) -> _Expansion:
    """Step ``monitor`` from ``state`` across all abstractions of ``node``.

    Enumerates every leaf-atom assignment consistent with ``abstract_eval`` and
    steps the monitor once per assignment, collecting the successor states,
    the may/must violation flags, and witnessing assignments.
    """
    allowed = [_allowed_values(a, node) for a in atoms]

    succ_set: dict[Any, None] = {}
    may_bad = False
    bad_assignment: dict[Predicate, bool] | None = None
    has_nonaccepting = False
    nonacc_assignment: dict[Predicate, bool] | None = None

    for combo in itertools.product(*allowed) if atoms else [()]:
        assignment = dict(zip(atoms, combo))
        nstate, bad = monitor.step_valuation(state, assignment)
        succ_set.setdefault(nstate, None)
        if bad:
            may_bad = True
            if bad_assignment is None:
                bad_assignment = assignment
        if not monitor.is_accepting(nstate):
            has_nonaccepting = True
            if nonacc_assignment is None:
                nonacc_assignment = assignment

    # Forced assignment: each atom at its `must` value.
    forced_assignment = {a: a.abstract_eval(node)[1] for a in atoms}
    forced_state, forced_bad = monitor.step_valuation(state, forced_assignment)

    succ_states = sorted(succ_set.keys(), key=repr)
    return _Expansion(
        succ_states=succ_states,
        forced_state=forced_state,
        forced_bad=forced_bad,
        may_bad=may_bad,
        bad_assignment=bad_assignment,
        has_nonaccepting=has_nonaccepting,
        nonacc_assignment=nonacc_assignment,
    )


def post_states(
    monitor: Monitor, atoms: list[Predicate], node: EffectNode, state: Any
) -> tuple[list[Any], bool, bool]:
    """Successor monitor states and (may_bad, must_bad) for one abstract node.

    * ``successor_states``: every monitor state reachable by stepping ``node``
      from ``state`` under some admissible leaf-atom assignment.
    * ``may_bad``: ``True`` if any assignment drives the monitor into a bad
      state (a *possible* violation at this node).
    * ``must_bad``: ``True`` if the FORCED assignment (each atom at its ``must``
      value) drives a violation (this node is bad regardless of concretisation).
    """
    exp = _expand(monitor, atoms, node, state)
    return exp.succ_states, exp.may_bad, exp.forced_bad


# ===========================================================================
# Part D — result types
# ===========================================================================

@dataclass
class Witness:
    """A source-level explanation of a verdict (violation or candidate)."""

    product_path: list[str]                # node ids from entry to the witness node
    monitor_state: str                     # str() of the monitor state at the witness
    valuation: dict[str, bool]             # leaf-atom truth assignment (atom_key -> bool)
    node_args: dict[str, Any]              # abstract args of the witness node
    provenance_spans: list[str]            # source spans of the nodes on the path
    modality: str                          # "must" (forced) or "may" (candidate)

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_path": list(self.product_path),
            "monitor_state": self.monitor_state,
            "valuation": dict(self.valuation),
            "node_args": dict(self.node_args),
            "provenance_spans": list(self.provenance_spans),
            "modality": self.modality,
        }


@dataclass
class ProductResult:
    """Tri-valued outcome of checking one policy against a may/must graph."""

    rule_id: str
    verdict: Verdict
    violation_kind: str | None = None        # "bad_prefix" | "unfulfilled" | None
    witness: Witness | None = None
    certified: bool = False
    unknown_reason: str | None = None        # candidate / certification reason
    product_states_explored: int = 0
    unsupported_facts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "verdict": self.verdict.value,
            "violation_kind": self.violation_kind,
            "witness": self.witness.to_dict() if self.witness is not None else None,
            "certified": self.certified,
            "unknown_reason": self.unknown_reason,
            "product_states_explored": self.product_states_explored,
            "unsupported_facts": list(self.unsupported_facts),
        }


# ===========================================================================
# Part C — the product BFS and verdict synthesis
# ===========================================================================

# A product state key: (node_id, monitor_state, must_reachable_flag). The must
# flag is part of the key so a state reached both by a may path and a must path
# is explored (and remembered) separately — must-reachability must never be lost.
_ProdKey = tuple


def check(
    graph: MayMustGraph,
    policy: Policy,
    *,
    assume_trace_conservative: bool = False,
    max_states: int = 100000,
) -> ProductResult:
    """Check ``policy`` against ``graph`` and return a tri-valued result.

    Parameters
    ----------
    graph : MayMustGraph
        The provenance-carrying may/must effect transition system.
    policy : Policy
        The property to verify. Compiled to a monitor via :func:`compile_monitor`.
    assume_trace_conservative : bool
        Caller assertion that the extraction is trace-conservative regardless of
        per-element provenance. When ``True`` the certification gate is
        satisfied unconditionally (mirrors ``verify.temporal`` and
        :func:`region_is_certifiable`).
    max_states : int
        Upper bound on product states explored. If reached, the region is
        treated as uncertified (a would-be ``SAFE`` becomes ``UNKNOWN``).

    Returns
    -------
    ProductResult
        ``UNSAFE`` on a definite (must-reachable & forced) violation; ``SAFE``
        when nothing bad or possibly-unfulfilled is may-reachable and the
        explored region is certifiable; ``UNKNOWN`` otherwise.
    """
    rid = rule_id_of(policy)
    monitor = compile_monitor(policy)
    atoms = _unique_atoms(policy)
    exit_ids = set(graph.exit_ids)

    start: _ProdKey = (graph.entry_id, monitor.initial_state, True)
    visited: set[_ProdKey] = {start}
    parent: dict[_ProdKey, _ProdKey | None] = {start: None}
    queue: deque[_ProdKey] = deque([start])

    visited_nodes: set[str] = set()
    visited_edges: set[tuple[str, str]] = set()
    truncated = False

    # Definite (UNSAFE) finding: (key, kind, assignment). Set once, then break.
    definite: tuple[_ProdKey, str, dict[Predicate, bool] | None] | None = None
    # First may-level candidate (UNKNOWN): (key, kind, assignment) in BFS order.
    candidate: tuple[_ProdKey, str, dict[Predicate, bool] | None] | None = None
    any_may_bad = False
    any_may_unfulfilled = False

    while queue:
        key = queue.popleft()
        node_id, mstate, must = key
        visited_nodes.add(node_id)
        node = graph.node_by_id(node_id)
        if node is None:
            # A dangling target cannot be modelled or certified; leave it as a
            # dead-end contributing an uncertifiable node to the region.
            continue

        exp = _expand(monitor, atoms, node, mstate)

        # -- DEFINITE bad prefix (must-reachable & forced) => UNSAFE ---------
        if must and exp.forced_bad:
            definite = (key, "bad_prefix", exp.bad_assignment or exp.nonacc_assignment)
            break
        # -- may-level bad-prefix candidate ---------------------------------
        if exp.may_bad:
            any_may_bad = True
            if candidate is None:
                candidate = (key, "bad_prefix", exp.bad_assignment)

        out_edges = graph.out_edges(node_id)
        is_terminal = node_id in exit_ids or not out_edges
        if is_terminal:
            # LTLf end-of-trace check: a resolution that terminates here with a
            # non-accepting monitor state carries an unfulfilled obligation.
            if must and not monitor.is_accepting(exp.forced_state):
                definite = (key, "unfulfilled", None)
                break
            if exp.has_nonaccepting:
                any_may_unfulfilled = True
                if candidate is None:
                    candidate = (key, "unfulfilled", exp.nonacc_assignment)

        # -- successors: may-reachability follows every edge; must-reachability
        #    follows MUST edges taking the forced monitor transition ---------
        for e in out_edges:
            visited_edges.add((e.source, e.target))
            for s in exp.succ_states:
                child_must = (
                    must and e.modality is Modality.MUST and s == exp.forced_state
                )
                child: _ProdKey = (e.target, s, child_must)
                if child not in visited:
                    if len(visited) >= max_states:
                        truncated = True
                        continue
                    visited.add(child)
                    parent[child] = key
                    queue.append(child)

    unsupported_facts = _region_unsupported(graph, visited_nodes, visited_edges)

    # -- UNSAFE ------------------------------------------------------------
    if definite is not None:
        key, kind, assignment = definite
        certified = region_is_certifiable(
            graph, visited_nodes, visited_edges,
            assume_trace_conservative=assume_trace_conservative,
        )
        witness = _build_witness(graph, parent, key, assignment, "must")
        return ProductResult(
            rule_id=rid,
            verdict=Verdict.UNSAFE,
            violation_kind=kind,
            witness=witness,
            certified=certified,
            unknown_reason=None,
            product_states_explored=len(visited),
            unsupported_facts=unsupported_facts,
        )

    certified = region_is_certifiable(
        graph, visited_nodes, visited_edges,
        assume_trace_conservative=assume_trace_conservative,
    ) and not truncated

    # -- SAFE --------------------------------------------------------------
    if not any_may_bad and not any_may_unfulfilled and certified:
        return ProductResult(
            rule_id=rid,
            verdict=Verdict.SAFE,
            violation_kind=None,
            witness=None,
            certified=True,
            unknown_reason=None,
            product_states_explored=len(visited),
            unsupported_facts=unsupported_facts,
        )

    # -- UNKNOWN -----------------------------------------------------------
    if candidate is not None:
        # A may-violation the checker could not force: a CEGAR candidate.
        key, kind, assignment = candidate
        witness = _build_witness(graph, parent, key, assignment, "may")
        return ProductResult(
            rule_id=rid,
            verdict=Verdict.UNKNOWN,
            violation_kind=kind,
            witness=witness,
            certified=certified,
            unknown_reason="may_violation_candidate",
            product_states_explored=len(visited),
            unsupported_facts=unsupported_facts,
        )

    # No candidate: the only obstacle is certification of the explored region.
    reason = "unsupported_region" if unsupported_facts else "uncertified_extraction"
    return ProductResult(
        rule_id=rid,
        verdict=Verdict.UNKNOWN,
        violation_kind=None,
        witness=None,
        certified=False,
        unknown_reason=reason,
        product_states_explored=len(visited),
        unsupported_facts=unsupported_facts,
    )


def check_all(
    graph: MayMustGraph, policies: list[Policy], **kw: Any
) -> list[ProductResult]:
    """Check every policy in ``policies`` against ``graph``."""
    return [check(graph, p, **kw) for p in policies]


# ===========================================================================
# Witness / certification helpers
# ===========================================================================

def _path_to(parent: dict[_ProdKey, _ProdKey | None], key: _ProdKey) -> list[str]:
    """Reconstruct the node-id path from entry to ``key`` via parent pointers."""
    nodes: list[str] = []
    current: _ProdKey | None = key
    while current is not None:
        nodes.append(current[0])
        current = parent.get(current)
    nodes.reverse()
    return nodes


def _build_witness(
    graph: MayMustGraph,
    parent: dict[_ProdKey, _ProdKey | None],
    key: _ProdKey,
    assignment: dict[Predicate, bool] | None,
    modality: str,
) -> Witness:
    path = _path_to(parent, key)
    node = graph.node_by_id(key[0])
    valuation = (
        {a.atom_key(): bool(v) for a, v in assignment.items()}
        if assignment is not None
        else {}
    )
    node_args: dict[str, Any] = {}
    spans: list[str] = []
    if node is not None:
        node_args = {n: v.to_dict() for n, v in node.abstract_args}
    for nid in path:
        n = graph.node_by_id(nid)
        if n is not None and n.provenance.source_span:
            spans.append(n.provenance.source_span)
    return Witness(
        product_path=path,
        monitor_state=str(key[1]),
        valuation=valuation,
        node_args=node_args,
        provenance_spans=spans,
        modality=modality,
    )


def _region_unsupported(
    graph: MayMustGraph,
    visited_nodes: Iterable[str],
    visited_edges: Iterable[tuple[str, str]],
) -> list[str]:
    """Explicit unsupported facts touching the explored region (+ graph-level)."""
    facts: list[str] = []
    for u in graph.unsupported:
        facts.append(f"graph:{u.kind.value}:{u.detail}")
    node_ids = set(visited_nodes)
    for nid in node_ids:
        n = graph.node_by_id(nid)
        if n is None:
            continue
        for u in n.unsupported:
            facts.append(f"{nid}:{u.kind.value}:{u.detail}")
    edge_set = set(visited_edges)
    for e in graph.edges:
        if (e.source, e.target) in edge_set:
            for u in e.unsupported:
                facts.append(f"{e.source}->{e.target}:{u.kind.value}:{u.detail}")
    return facts


# ===========================================================================
# Smoke test
# ===========================================================================

def _smoke() -> None:
    from agentproof.cegar.ir import (
        EffectKind,
        ModalEdge,
        Provenance,
        UnsupportedFact,
        UnsupportedKind,
    )
    from agentproof.cegar.policy import Approval, Effect, Tool

    exact = Provenance(origin="ast_explicit", confidence="exact", source_span="f.py:1:1")
    mayp = Provenance(origin="ast_explicit", confidence="may", source_span="f.py:2:2")

    def node(nid: str, *, effect=EffectKind.NONE, tool="", prov=exact,
             unsupported=()) -> EffectNode:
        return EffectNode(id=nid, effect=effect, tool=tool, provenance=prov,
                          modeling_confidence=prov.confidence, unsupported=unsupported)

    must = Modality.MUST
    may = Modality.MAY

    # (1) forbidden tool on a MUST path, exact provenance -> UNSAFE.
    g1 = MayMustGraph(
        name="g1", framework="test",
        nodes=(
            node("entry"),
            node("call", effect=EffectKind.FINANCIAL, tool="wire_transfer"),
            node("exit"),
        ),
        edges=(
            ModalEdge("entry", "call", modality=must, provenance=exact),
            ModalEdge("call", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    r1 = check(g1, Never(Tool("wire_transfer"), rule_id="no_wire"))
    assert r1.verdict is Verdict.UNSAFE, r1
    assert r1.violation_kind == "bad_prefix", r1
    assert r1.witness is not None and r1.witness.modality == "must", r1
    assert r1.witness.product_path == ["entry", "call"], r1.witness.product_path

    # (2) clean graph, all-exact provenance, no bad reachable -> SAFE.
    g2 = MayMustGraph(
        name="g2", framework="test",
        nodes=(
            node("entry"),
            node("call", effect=EffectKind.COMMUNICATE, tool="send_email"),
            node("exit"),
        ),
        edges=(
            ModalEdge("entry", "call", modality=must, provenance=exact),
            ModalEdge("call", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    r2 = check(g2, Never(Tool("wire_transfer"), rule_id="no_wire"))
    assert r2.verdict is Verdict.SAFE, r2
    assert r2.certified is True, r2

    # (3) same clean structure but one non-exact node -> UNKNOWN / uncertified.
    g3 = MayMustGraph(
        name="g3", framework="test",
        nodes=(
            node("entry"),
            node("call", effect=EffectKind.COMMUNICATE, tool="send_email", prov=mayp),
            node("exit"),
        ),
        edges=(
            ModalEdge("entry", "call", modality=must, provenance=exact),
            ModalEdge("call", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    r3 = check(g3, Never(Tool("wire_transfer"), rule_id="no_wire"))
    assert r3.verdict is Verdict.UNKNOWN, r3
    assert r3.unknown_reason in ("uncertified_extraction", "unsupported_region"), r3
    assert r3.unknown_reason == "uncertified_extraction", r3

    # (3b) explicit unsupported fact -> UNKNOWN / unsupported_region.
    g3b = MayMustGraph(
        name="g3b", framework="test",
        nodes=(
            node("entry"),
            node("call", effect=EffectKind.COMMUNICATE, tool="send_email",
                 unsupported=(UnsupportedFact(UnsupportedKind.REFLECTION, detail="getattr"),)),
            node("exit"),
        ),
        edges=(
            ModalEdge("entry", "call", modality=must, provenance=exact),
            ModalEdge("call", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    r3b = check(g3b, Never(Tool("wire_transfer"), rule_id="no_wire"))
    assert r3b.verdict is Verdict.UNKNOWN, r3b
    assert r3b.unknown_reason == "unsupported_region", r3b
    assert r3b.unsupported_facts, r3b

    # (4) RequireBefore(approval, financial) with NO approval on a MUST path -> UNSAFE.
    g4 = MayMustGraph(
        name="g4", framework="test",
        nodes=(
            node("entry"),
            node("pay", effect=EffectKind.FINANCIAL, tool="wire_transfer"),
            node("exit"),
        ),
        edges=(
            ModalEdge("entry", "pay", modality=must, provenance=exact),
            ModalEdge("pay", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    pol4 = RequireBefore(Approval(), Effect(EffectKind.FINANCIAL),
                         strict=True, rule_id="approve_before_pay")
    r4 = check(g4, pol4)
    assert r4.verdict is Verdict.UNSAFE, r4
    assert r4.violation_kind == "bad_prefix", r4
    assert r4.witness is not None and r4.witness.product_path == ["entry", "pay"], r4

    # (4b) same but approval IS present before the financial effect -> SAFE.
    g4b = MayMustGraph(
        name="g4b", framework="test",
        nodes=(
            node("entry"),
            EffectNode(id="approve", effect=EffectKind.NONE,
                       capability="human_pause",
                       state_predicates=("kind:human",), provenance=exact,
                       modeling_confidence="exact"),
            node("pay", effect=EffectKind.FINANCIAL, tool="wire_transfer"),
            node("exit"),
        ),
        edges=(
            ModalEdge("entry", "approve", modality=must, provenance=exact),
            ModalEdge("approve", "pay", modality=must, provenance=exact),
            ModalEdge("pay", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    r4b = check(g4b, pol4)
    assert r4b.verdict is Verdict.SAFE, r4b

    # (5) Forbid: forbidden ordered subsequence realised on a MUST path -> UNSAFE.
    g5 = MayMustGraph(
        name="g5", framework="test",
        nodes=(
            node("entry"),
            node("read", tool="read_db"),
            node("send", tool="send_email"),
            node("exit"),
        ),
        edges=(
            ModalEdge("entry", "read", modality=must, provenance=exact),
            ModalEdge("read", "send", modality=must, provenance=exact),
            ModalEdge("send", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    r5 = check(g5, Forbid((Tool("read_db"), Tool("send_email")),
                          contiguous=False, rule_id="no_exfil"))
    assert r5.verdict is Verdict.UNSAFE, r5
    assert r5.violation_kind == "bad_prefix", r5
    assert r5.witness is not None
    assert r5.witness.product_path == ["entry", "read", "send"], r5.witness.product_path

    # (5b) same tools but the send does NOT follow the read (no read node) -> SAFE.
    g5b = MayMustGraph(
        name="g5b", framework="test",
        nodes=(node("entry"), node("send", tool="send_email"), node("exit")),
        edges=(
            ModalEdge("entry", "send", modality=must, provenance=exact),
            ModalEdge("send", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    r5b = check(g5b, Forbid((Tool("read_db"), Tool("send_email")),
                            contiguous=False, rule_id="no_exfil"))
    assert r5b.verdict is Verdict.SAFE, r5b

    # (6) Bounded: the (k+1)-th occurrence on a MUST path -> UNSAFE.
    g6 = MayMustGraph(
        name="g6", framework="test",
        nodes=(
            node("entry"),
            node("r1", tool="retry"),
            node("r2", tool="retry"),
            node("exit"),
        ),
        edges=(
            ModalEdge("entry", "r1", modality=must, provenance=exact),
            ModalEdge("r1", "r2", modality=must, provenance=exact),
            ModalEdge("r2", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    r6 = check(g6, Bounded(Tool("retry"), 1, rule_id="max_retry"))
    assert r6.verdict is Verdict.UNSAFE, r6
    assert r6.violation_kind == "bad_prefix", r6
    assert r6.witness.product_path == ["entry", "r1", "r2"], r6.witness.product_path
    # within the bound (k=2) the same graph is SAFE.
    r6b = check(g6, Bounded(Tool("retry"), 2, rule_id="max_retry"))
    assert r6b.verdict is Verdict.SAFE, r6b

    # (7) LeadsTo: trigger on a MUST path with no response before the end
    #     -> definite UNFULFILLED obligation (termination-time) -> UNSAFE.
    g7 = MayMustGraph(
        name="g7", framework="test",
        nodes=(node("entry"), node("open", tool="open"), node("exit")),
        edges=(
            ModalEdge("entry", "open", modality=must, provenance=exact),
            ModalEdge("open", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    r7 = check(g7, LeadsTo(Tool("open"), Tool("close"), rule_id="close_it"))
    assert r7.verdict is Verdict.UNSAFE, r7
    assert r7.violation_kind == "unfulfilled", r7

    # (7b) LeadsTo satisfied on the only (MUST) trace -> SAFE.
    g7b = MayMustGraph(
        name="g7b", framework="test",
        nodes=(
            node("entry"),
            node("open", tool="open"),
            node("close", tool="close"),
            node("exit"),
        ),
        edges=(
            ModalEdge("entry", "open", modality=must, provenance=exact),
            ModalEdge("open", "close", modality=must, provenance=exact),
            ModalEdge("close", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    r7b = check(g7b, LeadsTo(Tool("open"), Tool("close"), rule_id="close_it"))
    assert r7b.verdict is Verdict.SAFE, r7b

    # (7c) LeadsTo where a MAY branch skips the response -> the obligation is
    #      only *possibly* unfulfilled (no MUST trace forces it) -> UNKNOWN.
    g7c = MayMustGraph(
        name="g7c", framework="test",
        nodes=(
            node("entry"),
            node("open", tool="open"),
            node("close", tool="close"),
            node("exit1"),
            node("exit2"),
        ),
        edges=(
            ModalEdge("entry", "open", modality=must, provenance=exact),
            ModalEdge("open", "exit1", modality=may, provenance=exact),
            ModalEdge("open", "close", modality=may, provenance=exact),
            ModalEdge("close", "exit2", modality=may, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit1", "exit2"),
    )
    r7c = check(g7c, LeadsTo(Tool("open"), Tool("close"), rule_id="close_it"))
    assert r7c.verdict is Verdict.UNKNOWN, r7c
    assert r7c.violation_kind == "unfulfilled", r7c
    assert r7c.unknown_reason == "may_violation_candidate", r7c

    # (8) All: a conjunction where one conjunct is violated on a MUST path
    #     -> UNSAFE; check_all evaluates each policy independently.
    g8 = MayMustGraph(
        name="g8", framework="test",
        nodes=(node("entry"), node("retry", tool="retry"), node("exit")),
        edges=(
            ModalEdge("entry", "retry", modality=must, provenance=exact),
            ModalEdge("retry", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    pol8 = All((Never(Tool("wire_transfer")), Bounded(Tool("retry"), 0)),
               rule_id="all_rule")
    r8 = check(g8, pol8)
    assert r8.verdict is Verdict.UNSAFE, r8
    assert r8.violation_kind == "bad_prefix", r8
    results8 = check_all(g8, [Never(Tool("wire_transfer")), Bounded(Tool("retry"), 0)])
    assert [r.verdict for r in results8] == [Verdict.SAFE, Verdict.UNSAFE], results8

    # round-trip serialization of every result flavour (UNSAFE/SAFE/UNKNOWN)
    import json
    for r in (r1, r2, r3, r4, r5, r6, r7, r7c, r8):
        json.dumps(r.to_dict())

    print("PRODUCT SMOKE OK")


if __name__ == "__main__":
    _smoke()
