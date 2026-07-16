"""Counterexample-guided refinement loop for AgentProof-CEGAR (Paper 2, §4.4).

This module wires the tri-valued product checker
(:mod:`agentproof.cegar.product`) to a *concretizer* in a
counterexample-guided abstraction-refinement (CEGAR) loop and exposes the
top-level :func:`analyze` entry point. It closes the gap between the two
weak spots of a pure over-approximation:

* the product checker can report ``UNKNOWN`` with a *may*-violation candidate
  (some concretization might violate) that a concrete witness would upgrade to
  ``UNSAFE``; and
* it can report ``UNSAFE`` (or ``UNKNOWN``) on a *spurious* path — one no
  concrete execution can realize (an unsatisfiable edge guard, an empty
  abstract argument, or a required atom truth no concrete value supports) —
  which refinement should refute.

Because real agent programs cannot be executed in this environment (frameworks
are not installed and the code is untrusted), the default concretizer is a
**symbolic, IR-level feasibility checker** (:class:`SymbolicConcretizer`) that
never runs code: it reconstructs the witness path node-by-node, picks
representative concrete argument values consistent with the traversed guards
and the recorded monitor valuation, and cross-checks the resulting concrete
:class:`~agentproof.cegar.ir.Trace` against the independent oracle
(:func:`agentproof.cegar.oracle.satisfies`). A real sandboxed executor is a
pluggable follow-up: it only has to satisfy the :class:`Concretizer` protocol.

Soundness directive
-------------------
A false ``SAFE`` is the cardinal sin and must never happen; false alarms
(spurious ``UNSAFE`` / ``UNKNOWN``) are acceptable. Concretization can only
*upgrade* ``UNKNOWN`` to ``UNSAFE`` when it produces a concrete trace the oracle
independently confirms violates. Refinement only ever removes provably-dead
transitions (guard proven ``False``, or an unreachable node with an empty
abstract argument) or replaces an unbounded argument domain with a finite set
that *covers every truth-class* of the policy constraints on that argument — so
the refined graph never drops a realizable behaviour and a refined ``SAFE`` is a
real ``SAFE``. On the refinement budget the loop returns ``UNKNOWN``, never
``SAFE``.

Termination (Theorem 5, conditional CEGAR termination)
------------------------------------------------------
The candidate pool is the finite set of constants appearing in the policy and
program. Each refinement step strictly decreases a well-founded measure —
either the number of graph edges (an edge is removed) or the size of some
argument's may-set (an unbounded ``TOP`` / ``INTERVAL`` domain is replaced by a
finite ``SET`` drawn from that pool, and thereafter a ``SET`` only ever shrinks)
— so no argument domain can be refined more than finitely often and the loop
terminates. Independently, the loop is hard-bounded by ``max_refinements``; on
the bound it returns ``UNKNOWN`` with ``timed_out=True``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Protocol, runtime_checkable

from agentproof.cegar import oracle, product
from agentproof.cegar.ir import (
    AbstractValue,
    AVKind,
    EffectEvent,
    EffectNode,
    MayMustGraph,
    Trace,
    Verdict,
)
from agentproof.cegar.policy import (
    All,
    ArgConstraint,
    Op,
    Policy,
    Predicate,
    RequireBefore,
    rule_id_of,
)
from agentproof.cegar.product import ProductResult, Witness


# ===========================================================================
# Result type
# ===========================================================================

@dataclass
class CegarResult:
    """Outcome of the CEGAR analysis of one policy against one graph.

    Attributes
    ----------
    verdict:
        The final tri-valued :class:`~agentproof.cegar.ir.Verdict`. May differ
        from ``product_result.verdict`` when concretization upgraded an
        ``UNKNOWN`` candidate to ``UNSAFE``, downgraded a spurious ``UNSAFE`` to
        ``UNKNOWN`` (precision protection), or the refinement budget was
        exhausted.
    rule_id:
        Identifier of the checked policy.
    product_result:
        The *last* :class:`~agentproof.cegar.product.ProductResult` computed
        (on the most-refined graph).
    concrete_witness:
        A concrete violating :class:`~agentproof.cegar.ir.Trace` when the
        verdict is ``UNSAFE`` and a witness could be realized, else ``None``.
        Always oracle-confirmed to violate the policy.
    refinements:
        Human-readable descriptions of the refinement steps applied, in order.
    iterations:
        Number of refinement iterations performed.
    timed_out:
        ``True`` iff the loop stopped because it hit ``max_refinements`` while a
        refinement was still pending (verdict is then ``UNKNOWN``).
    refined_graph:
        The final (possibly refined) :class:`~agentproof.cegar.ir.MayMustGraph`.
    """

    verdict: Verdict
    rule_id: str
    product_result: ProductResult
    concrete_witness: Trace | None
    refinements: list[str]
    iterations: int
    timed_out: bool
    refined_graph: MayMustGraph

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "rule_id": self.rule_id,
            "product_result": self.product_result.to_dict(),
            "concrete_witness": (
                [_event_to_dict(e) for e in self.concrete_witness]
                if self.concrete_witness is not None
                else None
            ),
            "refinements": list(self.refinements),
            "iterations": self.iterations,
            "timed_out": self.timed_out,
            "refined_graph": self.refined_graph.to_dict(),
        }


# ===========================================================================
# Concretizer protocol + symbolic default
# ===========================================================================

@runtime_checkable
class Concretizer(Protocol):
    """Decides whether a *may*-witness path is concretely realizable.

    Returns a triple ``(feasible, trace, reason)``:

    * ``feasible`` — ``True`` iff a concrete execution realizes the witness path
      *and* violates the policy (independently confirmed).
    * ``trace`` — the realizing concrete :class:`~agentproof.cegar.ir.Trace`
      when ``feasible``; otherwise ``None``.
    * ``reason`` — a machine-readable string. A ``"spurious:..."`` prefix means
      the path was *proven* unrealizable (refinement should follow); a
      ``"feasible:..."`` prefix accompanies ``feasible=True``; any other prefix
      (``"undecided:..."``) means the concretizer could neither realize nor
      refute the path.
    """

    def feasible(
        self, graph: MayMustGraph, policy: Policy, witness: Witness
    ) -> tuple[bool, Trace | None, str]:
        ...


class SymbolicConcretizer:
    """The default, IR-only concretizer — it never executes program code.

    It reconstructs the witness path node-by-node and, for each node, builds a
    concrete :class:`~agentproof.cegar.ir.EffectEvent` whose arguments are drawn
    from the node's ``abstract_args`` — picking a representative concrete value
    from each :class:`~agentproof.cegar.ir.AbstractValue` that is consistent
    with the guards on the traversed edges and with the monitor valuation
    recorded in the witness.

    Feasibility is *proven* to fail (a spurious path) when:

    * a traversed edge guard is unconditionally unsatisfiable (or evaluates to
      ``False`` under the chosen arguments); or
    * an abstract argument is ``BOTTOM`` (its concretization is empty, so the
      node cannot execute); or
    * the witness required an atom to be ``True``/``False`` that no concrete
      value in the argument's domain supports.

    When a concrete trace is built it is cross-checked with
    :func:`agentproof.cegar.oracle.satisfies`: the trace must *actually* violate
    the policy for the witness to count as feasible. This checks the abstract
    product against the independent denotational oracle at the concrete level;
    if the built trace does not violate, the result is ``undecided`` (a
    different concretization of a ``TOP`` argument might, so the path is not
    proven spurious).
    """

    def feasible(
        self, graph: MayMustGraph, policy: Policy, witness: Witness
    ) -> tuple[bool, Trace | None, str]:
        if witness is None or not witness.product_path:
            return (False, None, "undecided:no_witness")

        path = list(witness.product_path)
        nodes: list[EffectNode] = []
        for nid in path:
            n = graph.node_by_id(nid)
            if n is None:
                return (False, None, f"undecided:dangling_node:{nid}")
            nodes.append(n)

        valuation = dict(witness.valuation or {})
        # The recorded monitor valuation constrains the witness (last) node: it
        # is the truth assignment under which the violation was flagged.
        targets = _targets_for_node(policy, nodes[-1], valuation)

        events: list[EffectEvent] = []
        for i, n in enumerate(nodes):
            tgt = targets if i == len(nodes) - 1 else {}
            event, err = _build_event(n, tgt)
            if err is not None:
                return (False, None, "spurious:" + err)
            events.append(event)

        # -- guard feasibility along the traversed edges --------------------
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            parallel = [e for e in graph.edges if e.source == u and e.target == v]
            if not parallel:
                continue
            holds = [_guard_holds(e.guard, events[i]) for e in parallel]
            # The transition is realizable if *some* parallel edge can hold; it
            # is proven spurious only when every guard is definitely False.
            if all(h is False for h in holds):
                guard = parallel[0].guard
                return (False, None, f"spurious:unsat_guard:{u}->{v}:{guard}")

        trace: Trace = tuple(events)

        # -- concrete cross-check against the independent oracle ------------
        if not oracle.satisfies(policy, trace):
            return (True, trace, "feasible:oracle_confirmed")
        return (False, None, "undecided:oracle_unconfirmed")


# ===========================================================================
# The CEGAR loop
# ===========================================================================

def analyze(
    graph: MayMustGraph,
    policy: Policy,
    *,
    concretizer: Concretizer | None = None,
    max_refinements: int = 16,
    assume_trace_conservative: bool = False,
) -> CegarResult:
    """Tri-valued CEGAR analysis of ``policy`` against ``graph``.

    The loop:

    1. Run :func:`agentproof.cegar.product.check`.
    2. ``SAFE`` — return ``SAFE`` immediately (the product's certification gate
       already forbids ``SAFE`` on an uncertified/unsupported region).
    3. ``UNSAFE`` — try to concretize the witness. If a concrete violating trace
       is realized, return ``UNSAFE`` with it. If the path is *proven spurious*,
       refine and loop. If concretization is undecided, the product's
       must-forced violation stands (``UNSAFE``) *unless* it relies on a
       ``RequireBefore`` requirement atom forced ``False`` that could actually
       hold (the known soft spot) — then downgrade to ``UNKNOWN`` to protect
       ``UNSAFE`` precision.
    4. ``UNKNOWN`` with a candidate witness — try to concretize. Feasible ⇒
       ``UNSAFE``. Proven spurious ⇒ refine and loop. Undecided / no witness /
       unsupported region ⇒ keep ``UNKNOWN`` (do not refine forever).
    5. Refinement strictly shrinks the may-set of the abstraction (remove a
       provably-dead edge, or replace an unbounded argument domain by a finite
       truth-class-covering set) and records the step.
    6. On ``max_refinements`` return ``UNKNOWN`` with ``timed_out=True`` — never
       ``SAFE`` on the bound.

    See the module docstring for the termination argument (Theorem 5).
    """
    conc: Concretizer = concretizer if concretizer is not None else SymbolicConcretizer()
    rid = rule_id_of(policy)
    refinements: list[str] = []
    current = graph
    iterations = 0

    while True:
        r = product.check(
            current, policy, assume_trace_conservative=assume_trace_conservative
        )

        # -- 2. SAFE ----------------------------------------------------------
        if r.verdict is Verdict.SAFE:
            return _result(Verdict.SAFE, rid, r, None, refinements, iterations, False, current)

        # -- 3 & 4 share the concretize/refine machinery ---------------------
        witness = r.witness

        # No witness to work with: keep the product's UNKNOWN (unsupported or
        # uncertified region). A witnessless UNSAFE cannot occur (product only
        # emits UNSAFE with a witness), but guard defensively.
        if witness is None:
            if r.verdict is Verdict.UNKNOWN:
                return _result(
                    Verdict.UNKNOWN, rid, r, None, refinements, iterations, False, current
                )
            return _result(
                r.verdict, rid, r, None, refinements, iterations, False, current
            )

        feasible, trace, reason = conc.feasible(current, policy, witness)

        # -- concretization realized the violation => UNSAFE -----------------
        if feasible:
            return _result(
                Verdict.UNSAFE, rid, r, trace, refinements, iterations, False, current
            )

        spurious = reason.startswith("spurious:")

        if spurious:
            # Proven spurious: refine and loop, unless the budget is exhausted.
            if iterations >= max_refinements:
                # Budget hit with a refinement still pending: never SAFE.
                return _result(
                    Verdict.UNKNOWN, rid, r, None, refinements, iterations, True, current
                )
            new_graph, desc = _refine(current, policy, witness, reason)
            if new_graph is None:
                # Nothing to refine on a path we proved spurious: report
                # UNKNOWN (do not claim UNSAFE on a refuted path).
                return _result(
                    Verdict.UNKNOWN, rid, r, None, refinements, iterations, False, current
                )
            refinements.append(desc)
            current = new_graph
            iterations += 1
            continue

        # -- undecided -------------------------------------------------------
        if r.verdict is Verdict.UNSAFE:
            # A product must-forced violation stands (false alarms are
            # acceptable), UNLESS it hinges on a RequireBefore requirement atom
            # forced False that concretization could not rule out — the known
            # soft spot — in which case downgrade to UNKNOWN to protect
            # UNSAFE precision.
            if _requirebefore_soft_spot(policy, witness):
                return _result(
                    Verdict.UNKNOWN, rid, r, None, refinements, iterations, False, current
                )
            return _result(
                Verdict.UNSAFE, rid, r, None, refinements, iterations, False, current
            )

        # UNKNOWN + undecided: keep UNKNOWN (do not refine forever).
        return _result(
            Verdict.UNKNOWN, rid, r, None, refinements, iterations, False, current
        )


def _result(
    verdict: Verdict,
    rid: str,
    r: ProductResult,
    trace: Trace | None,
    refinements: list[str],
    iterations: int,
    timed_out: bool,
    graph: MayMustGraph,
) -> CegarResult:
    return CegarResult(
        verdict=verdict,
        rule_id=rid,
        product_result=r,
        concrete_witness=trace,
        refinements=list(refinements),
        iterations=iterations,
        timed_out=timed_out,
        refined_graph=graph,
    )


# ===========================================================================
# Concretization helpers
# ===========================================================================

# Sentinel for "no concrete value could be found".
_NO_VALUE = object()


def _targets_for_node(
    policy: Policy, node: EffectNode, valuation: dict[str, bool]
) -> dict[str, list[tuple[Op, Any, bool]]]:
    """Argument constraints the witness valuation imposes on ``node``.

    For every :class:`~agentproof.cegar.policy.ArgConstraint` leaf atom of the
    policy that applies to ``node`` (matching tool, or tool-agnostic) and whose
    truth was recorded in the witness ``valuation``, produce a
    ``(op, value, desired_truth)`` target for its argument. These steer the
    choice of concrete argument values so the built event reproduces the
    flagged violation.
    """
    out: dict[str, list[tuple[Op, Any, bool]]] = {}
    for atom in policy.predicates():
        if not isinstance(atom, ArgConstraint):
            continue
        if atom.tool is not None and atom.tool != node.tool:
            continue
        key = atom.atom_key()
        if key in valuation:
            out.setdefault(atom.arg, []).append((atom.op, atom.value, bool(valuation[key])))
    return out


def _build_event(
    node: EffectNode, targets: dict[str, list[tuple[Op, Any, bool]]]
) -> tuple[EffectEvent | None, str | None]:
    """Build a concrete event for ``node`` or report why it is infeasible.

    Returns ``(event, None)`` on success or ``(None, reason)`` where ``reason``
    is a bare (unprefixed) spurious cause: an empty (``BOTTOM``) argument, or an
    argument for which no concrete value supports the required atom truths.
    """
    args: list[tuple[str, Any]] = []
    for name, av in node.abstract_args:
        if av.is_bottom:
            return (None, f"bottom_arg:{node.id}:{name}")
        tgts = targets.get(name, [])
        if tgts:
            val = _solve_arg(av, tgts)
            if val is _NO_VALUE:
                return (None, f"unsat_atom:{node.id}:{name}")
        else:
            val = _pick_representative(av)
        args.append((name, val))

    caps = node.capability
    action_type = _action_type_for(node)
    tags = tuple(sp for sp in node.state_predicates if not sp.startswith("kind:"))

    event = EffectEvent(
        node_id=node.id,
        effect=node.effect,
        action_type=action_type,
        tool_name=node.tool or None,
        args=tuple(args),
        principal=node.principal,
        authority=node.authority,
        identity=node.identity,
        capability=caps,
        in_labels=node.in_labels,
        out_labels=node.out_labels,
        tags=tags,
    )
    return (event, None)


def _action_type_for(node: EffectNode) -> str:
    """Concrete ``action_type`` reproducing the node's structural predicates."""
    for sp in node.state_predicates:
        if sp.startswith("kind:"):
            kind = sp.split(":", 1)[1]
            # A human-pause node must satisfy the concrete Approval predicate.
            return kind
    if "kind:human" in node.state_predicates or "human_pause" in node.capability:
        return "human"
    if node.tool:
        return "tool"
    return ""


def _solve_arg(av: AbstractValue, targets: list[tuple[Op, Any, bool]]) -> Any:
    """A concrete value in ``gamma(av)`` satisfying every ``target``, or sentinel.

    ``targets`` is a list of ``(op, value, desired_truth)``; the returned value
    ``c`` satisfies ``av.contains(c)`` and, for each target,
    ``_cmp(c, op, value) == desired``. Returns :data:`_NO_VALUE` when no such
    value can be found in the candidate pool (the witness required an atom truth
    the domain cannot support ⇒ spurious).
    """
    candidates: list[Any] = []
    seen: set[Any] = set()

    def _add(c: Any) -> None:
        try:
            if c in seen:
                return
        except TypeError:
            pass
        seen.add(c)
        candidates.append(c)

    for op, value, _desired in targets:
        for c in _candidate_values(av, value):
            _add(c)
    # Also try the plain representative(s) of the domain.
    rep = _pick_representative(av)
    if rep is not _NO_VALUE:
        _add(rep)

    for c in candidates:
        if not av.contains(c):
            continue
        if all(_cmp(c, op, value) == desired for op, value, desired in targets):
            return c
    return _NO_VALUE


def _candidate_values(av: AbstractValue, threshold: Any) -> list[Any]:
    """Concrete candidate values for an argument constrained against ``threshold``.

    For a finite domain the enumerable members; otherwise numeric neighbours of
    the threshold (``t-1, t, t+1`` — a representative of every order class),
    collection members, interval bounds, and a few scalar sentinels.
    """
    members = av._members()
    if members is not None:
        return sorted(members, key=repr)

    out: list[Any] = []
    if isinstance(threshold, bool):
        out.extend([True, False])
    elif isinstance(threshold, (int, float)):
        out.extend([threshold - 1, threshold, threshold + 1])
    else:
        out.append(threshold)
    # IN / NIN collection members (and a non-member sentinel).
    try:
        for m in threshold:  # type: ignore[union-attr]
            out.append(m)
    except TypeError:
        pass
    if av.kind is AVKind.INTERVAL:
        if av.lo != float("-inf"):
            out.append(av.lo)
        if av.hi != float("inf"):
            out.append(av.hi)
    out.extend([0, 1, "", "__cegar__"])
    return out


def _pick_representative(av: AbstractValue) -> Any:
    """A single representative concrete value of ``gamma(av)`` (or sentinel)."""
    if av.kind is AVKind.CONST:
        return av.value
    if av.kind is AVKind.SET:
        return sorted(av.values, key=repr)[0]
    if av.kind is AVKind.INTERVAL:
        if av.lo != float("-inf"):
            return av.lo
        if av.hi != float("inf"):
            return av.hi
        return 0
    if av.kind is AVKind.TOP:
        return 0
    return _NO_VALUE  # BOTTOM


# ===========================================================================
# Guard evaluation (conservative, IR-level, no code execution)
# ===========================================================================

_UNKNOWN_OPERAND = object()
# Comparison tokens, longest-first so "<=" is tried before "<".
_CMP_TOKENS: tuple[tuple[str, Op], ...] = (
    ("==", Op.EQ),
    ("!=", Op.NE),
    ("<=", Op.LE),
    (">=", Op.GE),
    ("<", Op.LT),
    (">", Op.GT),
)


def _guard_holds(guard: str, event: EffectEvent) -> bool | None:
    """Truth of an edge ``guard`` under ``event``: ``True``/``False``/``None``.

    Deliberately conservative — it recognizes only forms it can decide for
    certain: the empty guard (always holds), literal ``true``/``false``
    (``1``/``0``), and a single comparison ``lhs OP rhs`` whose operands are
    numeric/string literals or argument names resolvable on ``event``. Anything
    else returns ``None`` (unknown), so a guard is never *wrongly* proven
    unsatisfiable — a false ``False`` would drop a live edge and risk a false
    ``SAFE``.
    """
    g = guard.strip()
    if not g:
        return True
    low = g.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    parsed = _parse_cmp(g)
    if parsed is None:
        return None
    lhs, op, rhs = parsed
    lv = _resolve_operand(lhs, event)
    rv = _resolve_operand(rhs, event)
    if lv is _UNKNOWN_OPERAND or rv is _UNKNOWN_OPERAND:
        return None
    return _cmp(lv, op, rv)


def _parse_cmp(g: str) -> tuple[str, Op, str] | None:
    for token, op in _CMP_TOKENS:
        idx = g.find(token)
        if idx > 0:
            lhs = g[:idx].strip()
            rhs = g[idx + len(token):].strip()
            if lhs and rhs:
                return (lhs, op, rhs)
    return None


def _resolve_operand(tok: str, event: EffectEvent) -> Any:
    """Resolve a guard operand to a literal or an argument value on ``event``."""
    t = tok.strip()
    if not t:
        return _UNKNOWN_OPERAND
    if (t[0] == t[-1]) and t[0] in ("'", '"') and len(t) >= 2:
        return t[1:-1]
    low = t.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    val = event.arg(t)
    if val is None:
        return _UNKNOWN_OPERAND
    return val


# ===========================================================================
# Refinement
# ===========================================================================

def _refine(
    graph: MayMustGraph, policy: Policy, witness: Witness, reason: str
) -> tuple[MayMustGraph | None, str]:
    """Produce a strictly-refined graph that removes the proven-spurious cause.

    Dispatches on the spurious ``reason``:

    * ``unsat_guard`` — remove the provably-dead edge(s) (guard unconditionally
      ``False``). Sound: a dead transition can never occur.
    * ``bottom_arg`` — remove every edge into the node whose argument domain is
      empty. Sound: the node can never execute.
    * otherwise (``unsat_atom`` / fallback) — replace an unbounded argument
      domain on the witness node by a finite, truth-class-covering set drawn
      from the policy/program candidate pool. Sound: the set contains a
      representative of every order class of the policy constraints, so the
      argument's may/must truth is preserved exactly.

    Returns ``(None, "")`` when no strictly-smaller refinement applies.
    """
    body = reason.split("spurious:", 1)[1] if reason.startswith("spurious:") else reason

    if body.startswith("unsat_guard:"):
        rest = body[len("unsat_guard:"):]
        uv = rest.split(":", 1)[0]
        if "->" in uv:
            u, v = uv.split("->", 1)
            bare = EffectEvent(node_id=u)
            kept = tuple(
                e
                for e in graph.edges
                if not (
                    e.source == u
                    and e.target == v
                    and _guard_holds(e.guard, bare) is False
                )
            )
            if len(kept) != len(graph.edges):
                return (
                    graph.with_edges(kept),
                    f"removed unsatisfiable edge {u}->{v} (guard proven false)",
                )
        return (None, "")

    if body.startswith("bottom_arg:"):
        rest = body[len("bottom_arg:"):]
        node_id = rest.split(":", 1)[0]
        kept = tuple(e for e in graph.edges if e.target != node_id)
        if len(kept) != len(graph.edges):
            return (
                graph.with_edges(kept),
                f"removed edges into unreachable node {node_id} (empty argument domain)",
            )
        return (None, "")

    return _tighten_argument(graph, policy, witness)


def _tighten_argument(
    graph: MayMustGraph, policy: Policy, witness: Witness
) -> tuple[MayMustGraph | None, str]:
    """Replace an unbounded arg domain on the witness node by a finite set.

    The finite set is the subset of the policy/program candidate pool that lies
    inside the current domain — a truth-class-covering refinement (see
    :func:`_refine`). Strictly reduces the argument's may-set (``TOP`` /
    ``INTERVAL`` → finite ``SET``), so the loop's well-founded measure decreases.
    """
    if not witness.product_path:
        return (None, "")
    node = graph.node_by_id(witness.product_path[-1])
    if node is None:
        return (None, "")

    pool = _candidate_pool(policy, graph)
    for name, av in node.abstract_args:
        if av.kind not in (AVKind.TOP, AVKind.INTERVAL):
            continue
        relevant = [c for c in pool.get(name, ()) if av.contains(c)]
        if not relevant:
            continue
        new_av = AbstractValue.one_of(relevant)
        # Must be strictly smaller: new_av ⊆ av but not av ⊆ new_av.
        if new_av.leq(av) and not av.leq(new_av):
            new_args = tuple(
                (k, new_av if k == name else v) for k, v in node.abstract_args
            )
            new_node = replace(node, abstract_args=new_args)
            pretty = sorted(relevant, key=repr)
            return (
                graph.with_node(new_node),
                f"refined argument {node.id}.{name}: {av.kind.value} -> finite set {pretty}",
            )
    return (None, "")


def _candidate_pool(policy: Policy, graph: MayMustGraph) -> dict[str, set[Any]]:
    """Finite candidate pool per argument name (policy + program constants).

    For every :class:`~agentproof.cegar.policy.ArgConstraint` on an argument the
    pool includes a representative of every order class of its threshold
    (``t-1, t, t+1`` for numerics), collection members, and the threshold
    itself; plus any concrete constants that already appear in the program's
    abstract arguments (``CONST`` values, ``SET`` members, finite interval
    bounds). This is the finite set that underwrites termination.
    """
    pool: dict[str, set[Any]] = {}

    def _add(name: str, value: Any) -> None:
        pool.setdefault(name, set()).add(value)

    for atom in policy.predicates():
        if not isinstance(atom, ArgConstraint):
            continue
        v = atom.value
        if isinstance(v, bool):
            _add(atom.arg, True)
            _add(atom.arg, False)
        elif isinstance(v, (int, float)):
            _add(atom.arg, v - 1)
            _add(atom.arg, v)
            _add(atom.arg, v + 1)
        else:
            _add(atom.arg, v)
            try:
                for m in v:
                    _add(atom.arg, m)
            except TypeError:
                pass

    for node in graph.nodes:
        for name, av in node.abstract_args:
            if av.kind is AVKind.CONST:
                _add(name, av.value)
            elif av.kind is AVKind.SET:
                for m in av.values:
                    _add(name, m)
            elif av.kind is AVKind.INTERVAL:
                if av.lo != float("-inf"):
                    _add(name, av.lo)
                if av.hi != float("inf"):
                    _add(name, av.hi)

    return pool


# ===========================================================================
# RequireBefore soft-spot detection (UNSAFE precision protection)
# ===========================================================================

def _requirebefore_required_keys(policy: Policy) -> set[str]:
    """Atom keys of the ``required`` predicate of every RequireBefore sub-policy."""
    keys: set[str] = set()

    def rec(p: Policy) -> None:
        if isinstance(p, RequireBefore):
            for atom in p.required.atoms():
                keys.add(atom.atom_key())
        elif isinstance(p, All):
            for sub in p.policies:
                rec(sub)

    rec(policy)
    return keys


def _requirebefore_soft_spot(policy: Policy, witness: Witness) -> bool:
    """Does the witness hinge on a RequireBefore requirement forced ``False``?

    The product's forced (must) assignment sets a may-true-but-not-must
    ``required`` atom to ``False``, which can manufacture a *spurious* bad
    prefix for :class:`~agentproof.cegar.policy.RequireBefore` (the requirement
    might actually hold concretely). When concretization cannot rule the
    violation in, downgrading such an ``UNSAFE`` to ``UNKNOWN`` protects
    precision. Detected as: some requirement atom is recorded ``False`` in the
    witness valuation.
    """
    if witness is None:
        return False
    keys = _requirebefore_required_keys(policy)
    if not keys:
        return False
    valuation = witness.valuation or {}
    return any(valuation.get(k) is False for k in keys)


# ===========================================================================
# Small local helpers (concrete comparison + serialization)
# ===========================================================================

def _cmp(actual: Any, op: Op, value: Any) -> bool:
    """Concrete comparison mirroring :func:`agentproof.cegar.policy._cmp`."""
    try:
        if op is Op.EQ:
            return actual == value
        if op is Op.NE:
            return actual != value
        if op is Op.LT:
            return actual < value
        if op is Op.LE:
            return actual <= value
        if op is Op.GT:
            return actual > value
        if op is Op.GE:
            return actual >= value
        if op is Op.IN:
            return actual in value
        if op is Op.NIN:
            return actual not in value
        if op is Op.REGEX:
            import re

            return re.search(str(value), str(actual)) is not None
    except TypeError:
        return False
    return False


def _event_to_dict(ev: EffectEvent) -> dict[str, Any]:
    return {
        "node_id": ev.node_id,
        "effect": ev.effect.value,
        "action_type": ev.action_type,
        "tool_name": ev.tool_name,
        "args": [[k, v] for k, v in ev.args],
        "principal": ev.principal,
        "authority": ev.authority,
        "identity": ev.identity,
        "capability": ev.capability,
        "in_labels": list(ev.in_labels),
        "out_labels": list(ev.out_labels),
        "tags": list(ev.tags),
        "decision": ev.decision,
    }


# ===========================================================================
# Smoke test
# ===========================================================================

def _smoke() -> None:
    from agentproof.cegar.ir import (
        EffectKind,
        ModalEdge,
        Modality,
        Provenance,
    )
    from agentproof.cegar.policy import Never, Tool

    exact = Provenance(origin="ast_explicit", confidence="exact", source_span="f.py:1:1")
    must = Modality.MUST
    may = Modality.MAY

    def node(nid: str, *, effect=EffectKind.NONE, tool="", args=(),
             prov=exact, sp=()) -> EffectNode:
        return EffectNode(
            id=nid, effect=effect, tool=tool, abstract_args=args,
            provenance=prov, modeling_confidence=prov.confidence,
            state_predicates=sp,
        )

    # -- (a) UNKNOWN (amount=TOP) that concretizes to UNSAFE at amount=10001 --
    ga = MayMustGraph(
        name="ga", framework="test",
        nodes=(
            node("entry"),
            node("call", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                 args=(("amount", AbstractValue.top()),), sp=("kind:tool",)),
            node("exit"),
        ),
        edges=(
            ModalEdge("entry", "call", modality=must, provenance=exact),
            ModalEdge("call", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    pol_a = Never(ArgConstraint("wire_transfer", "amount", Op.GT, 10000),
                  rule_id="amount_cap")
    # sanity: the product alone is UNKNOWN (may-violation candidate).
    assert product.check(ga, pol_a).verdict is Verdict.UNKNOWN
    ra = analyze(ga, pol_a)
    assert ra.verdict is Verdict.UNSAFE, ra
    assert ra.concrete_witness is not None, ra
    # the concrete witness must actually violate per the independent oracle.
    assert not oracle.satisfies(pol_a, ra.concrete_witness), ra.concrete_witness
    amount = ra.concrete_witness[1].arg("amount")
    assert amount is not None and amount > 10000, amount
    assert ra.iterations == 0 and not ra.timed_out, ra

    # -- (b) spurious MAY branch (contradictory guard) -> refine -> SAFE/UNKNOWN
    gb = MayMustGraph(
        name="gb", framework="test",
        nodes=(
            node("entry"),
            node("branch"),
            node("badcall", effect=EffectKind.FINANCIAL, tool="wire_transfer",
                 sp=("kind:tool",)),
            node("exit"),
        ),
        edges=(
            ModalEdge("entry", "branch", modality=must, provenance=exact),
            ModalEdge("branch", "badcall", modality=may, guard="false", provenance=exact),
            ModalEdge("branch", "exit", modality=may, provenance=exact),
            ModalEdge("badcall", "exit", modality=may, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    pol_b = Never(Tool("wire_transfer"), rule_id="no_wire")
    assert product.check(gb, pol_b).verdict is Verdict.UNKNOWN
    rb = analyze(gb, pol_b)
    assert rb.verdict in (Verdict.SAFE, Verdict.UNKNOWN), rb
    assert rb.verdict is not Verdict.UNSAFE, rb
    assert len(rb.refinements) >= 1, rb.refinements
    assert rb.iterations >= 1, rb
    # this particular graph is fully exact, so refinement clears it to SAFE.
    assert rb.verdict is Verdict.SAFE, rb

    # -- (c) clean, all-exact SAFE graph -> SAFE with 0 refinements ----------
    gc = MayMustGraph(
        name="gc", framework="test",
        nodes=(
            node("entry"),
            node("send", effect=EffectKind.COMMUNICATE, tool="send_email",
                 sp=("kind:tool",)),
            node("exit"),
        ),
        edges=(
            ModalEdge("entry", "send", modality=must, provenance=exact),
            ModalEdge("send", "exit", modality=must, provenance=exact),
        ),
        entry_id="entry", exit_ids=("exit",),
    )
    rc = analyze(gc, Never(Tool("wire_transfer"), rule_id="no_wire"))
    assert rc.verdict is Verdict.SAFE, rc
    assert rc.iterations == 0 and rc.refinements == [] and not rc.timed_out, rc

    # -- (d) timeout: max_refinements=0 on the spurious UNKNOWN case ----------
    rd = analyze(gb, pol_b, max_refinements=0)
    assert rd.verdict is Verdict.UNKNOWN, rd
    assert rd.timed_out is True, rd
    assert rd.iterations == 0, rd

    # -- serialization round-trips for every flavour ------------------------
    import json
    for res in (ra, rb, rc, rd):
        json.dumps(res.to_dict())

    print("CEGAR SMOKE OK")


if __name__ == "__main__":
    _smoke()
