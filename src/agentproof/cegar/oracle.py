"""Slow, independent, obviously-correct finite-trace oracle (Paper 2, plan §4.3).

This module is the **differential oracle** for E0. It evaluates a
:class:`~agentproof.cegar.policy.Policy` over a concrete finite
:class:`~agentproof.cegar.ir.Trace` *denotationally* — a direct, dead-simple
transcription of the shared finite-trace semantics — deliberately WITHOUT
reusing the optimized product-checker automaton
(:mod:`agentproof.cegar.product`). The two implementations must be independent
so a later differential test can cross-check them: any behavioural divergence
is then a real bug in one of them, not a shared mistake (plan §7, E0).

Shared finite-trace semantics (authoritative)
---------------------------------------------
For a policy and a finite trace ``t = e_0 .. e_{n-1}`` we compute either the
earliest **bad-prefix** index (the event at which a safety violation becomes
inevitable) or an **unfulfilled** obligation detected only at end of trace:

* ``Never(pred)`` — bad prefix at the first ``i`` with ``pred.eval(e_i)``; else
  satisfied.
* ``RequireBefore(required, guarded, strict)`` — scan ``i = 0 .. n-1`` with
  ``seen = False``:

  * ``strict=True``:  if ``guarded`` and not ``seen`` -> BAD at ``i``; THEN if
    ``required``: ``seen = True``.
  * ``strict=False``: if ``required``: ``seen = True``; THEN if ``guarded`` and
    not ``seen`` -> BAD at ``i``.

* ``Forbid(steps, contiguous)``:

  * non-contiguous: ``idx = 0``; for each ``i``: if ``idx < len(steps)`` and
    ``steps[idx].eval(e_i)`` then ``idx += 1``; if ``idx == len(steps)`` ->
    BAD at ``i``.
  * contiguous: ``idx = 0``; for each ``i``: if ``steps[idx].eval(e_i)`` then
    ``idx += 1`` else ``idx = 1 if steps[0].eval(e_i) else 0``; if
    ``idx == len(steps)`` -> BAD at ``i``.

* ``Bounded(pred, k)`` — ``count = 0``; for each ``i``: if ``pred`` then
  ``count += 1``; if ``count > k`` -> BAD at ``i`` (the ``(k+1)``-th match).
* ``LeadsTo(trigger, response)`` — **termination-time**, never a bad prefix:
  ``pending = False``; for each ``i``: if ``trigger`` then ``pending = True``;
  if ``response`` then ``pending = False``. At end of trace UNFULFILLED iff
  ``pending``.
* ``All(policies)`` — BAD at the earliest bad index across sub-policies;
  UNFULFILLED if any sub is unfulfilled at end. The reported verdict is the
  most-severe / earliest sub-verdict (see :func:`evaluate`).

A safety monitor (Never / RequireBefore / Forbid / Bounded) is *accepting* in
every non-bad state — a trace may validly end there. A LeadsTo monitor is
accepting only when ``pending`` is ``False``.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from typing import Any

from agentproof.cegar.ir import EffectEvent, EffectKind, Trace
from agentproof.cegar.policy import (
    Action,
    ArgConstraint,
    Approval,
    Authority,
    Bounded,
    Capability,
    DataLabelIn,
    DataLabelOut,
    Effect,
    Forbid,
    Identity,
    LeadsTo,
    Never,
    Op,
    Policy,
    PolicyContext,
    Predicate,
    RequireBefore,
    Tag,
    Tool,
    All,
    rule_id_of,
)


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

# Status constants (kept as plain strings for cheap serialization / diffing).
SATISFIED = "satisfied"
BAD_PREFIX = "bad_prefix"
UNFULFILLED = "unfulfilled"

# Severity ordering used to pick the offending sub-policy in ``All``: a
# bad prefix is worse than an unfulfilled obligation, which is worse than
# satisfaction. Lower rank == more severe.
_SEVERITY = {BAD_PREFIX: 0, UNFULFILLED: 1, SATISFIED: 2}


@dataclass(frozen=True)
class OracleVerdict:
    """The oracle's decision for one policy over one trace.

    Attributes
    ----------
    rule_id:
        Identifier of the (sub-)policy the verdict pertains to. For a violated
        :class:`~agentproof.cegar.policy.All`, this is the ``rule_id`` of the
        offending sub-policy (via
        :func:`~agentproof.cegar.policy.rule_id_of`); otherwise the policy's own
        ``rule_id``.
    status:
        One of ``"satisfied"``, ``"bad_prefix"``, ``"unfulfilled"``.
    bad_index:
        The earliest bad-prefix event index for a ``"bad_prefix"`` verdict, else
        ``None`` (``"satisfied"`` and ``"unfulfilled"`` carry no index).
    satisfied:
        Convenience flag; ``True`` iff ``status == "satisfied"``.
    """

    rule_id: str
    status: str
    bad_index: int | None
    satisfied: bool


def _verdict(rule_id: str, status: str, bad_index: int | None) -> OracleVerdict:
    return OracleVerdict(
        rule_id=rule_id,
        status=status,
        bad_index=bad_index,
        satisfied=(status == SATISFIED),
    )


# ---------------------------------------------------------------------------
# The denotational evaluator
# ---------------------------------------------------------------------------

def evaluate(policy: Policy, trace: Trace) -> OracleVerdict:
    """Evaluate ``policy`` over the concrete finite ``trace``.

    Realizes the shared finite-trace semantics documented at module top,
    directly over concrete events using ``predicate.eval(event)``. This is the
    reference implementation; it favours clarity over speed.
    """
    if isinstance(policy, Never):
        return _eval_never(policy, trace)
    if isinstance(policy, RequireBefore):
        return _eval_require_before(policy, trace)
    if isinstance(policy, Forbid):
        return _eval_forbid(policy, trace)
    if isinstance(policy, Bounded):
        return _eval_bounded(policy, trace)
    if isinstance(policy, LeadsTo):
        return _eval_leads_to(policy, trace)
    if isinstance(policy, All):
        return _eval_all(policy, trace)
    raise TypeError(f"oracle cannot evaluate policy of type {type(policy).__name__}")


def _eval_never(policy: Never, trace: Trace) -> OracleVerdict:
    rid = rule_id_of(policy)
    for i, e in enumerate(trace):
        if policy.pred.eval(e):
            return _verdict(rid, BAD_PREFIX, i)
    return _verdict(rid, SATISFIED, None)


def _eval_require_before(policy: RequireBefore, trace: Trace) -> OracleVerdict:
    rid = rule_id_of(policy)
    seen = False
    for i, e in enumerate(trace):
        if policy.strict:
            # Check the guard against what was seen at *strictly earlier*
            # events, then let the current event satisfy the requirement.
            if policy.guarded.eval(e) and not seen:
                return _verdict(rid, BAD_PREFIX, i)
            if policy.required.eval(e):
                seen = True
        else:
            # The same event may both satisfy the requirement and be guarded.
            if policy.required.eval(e):
                seen = True
            if policy.guarded.eval(e) and not seen:
                return _verdict(rid, BAD_PREFIX, i)
    return _verdict(rid, SATISFIED, None)


def _eval_forbid(policy: Forbid, trace: Trace) -> OracleVerdict:
    rid = rule_id_of(policy)
    steps = policy.steps
    if not steps:
        # An empty forbidden sequence matches vacuously at the very start.
        # (Degenerate; documented for total behaviour.)
        return _verdict(rid, BAD_PREFIX, 0) if trace else _verdict(rid, SATISFIED, None)

    idx = 0
    if policy.contiguous:
        for i, e in enumerate(trace):
            if steps[idx].eval(e):
                idx += 1
            else:
                # Reset, but a fresh match of the first step may start here.
                idx = 1 if steps[0].eval(e) else 0
            if idx == len(steps):
                return _verdict(rid, BAD_PREFIX, i)
    else:
        for i, e in enumerate(trace):
            if idx < len(steps) and steps[idx].eval(e):
                idx += 1
            if idx == len(steps):
                return _verdict(rid, BAD_PREFIX, i)
    return _verdict(rid, SATISFIED, None)


def _eval_bounded(policy: Bounded, trace: Trace) -> OracleVerdict:
    rid = rule_id_of(policy)
    count = 0
    for i, e in enumerate(trace):
        if policy.pred.eval(e):
            count += 1
        if count > policy.k:
            return _verdict(rid, BAD_PREFIX, i)
    return _verdict(rid, SATISFIED, None)


def _eval_leads_to(policy: LeadsTo, trace: Trace) -> OracleVerdict:
    rid = rule_id_of(policy)
    pending = False
    for e in trace:
        if policy.trigger.eval(e):
            pending = True
        if policy.response.eval(e):
            pending = False
    if pending:
        return _verdict(rid, UNFULFILLED, None)
    return _verdict(rid, SATISFIED, None)


def _eval_all(policy: All, trace: Trace) -> OracleVerdict:
    """Aggregate sub-verdicts, returning the most-severe / earliest one.

    Ordering key per sub-policy: ``(severity_rank, bad_index_or_inf,
    position)``. ``bad_prefix`` beats ``unfulfilled`` beats ``satisfied``; among
    bad prefixes the smallest ``bad_index`` wins; ties break to the earliest
    sub-policy in declaration order. The winning sub-verdict is returned
    verbatim (its ``rule_id`` already identifies the offending sub-policy via
    :func:`~agentproof.cegar.policy.rule_id_of`).
    """
    if not policy.policies:
        return _verdict(rule_id_of(policy), SATISFIED, None)

    best: OracleVerdict | None = None
    best_key: tuple[int, float, int] | None = None
    for pos, sub in enumerate(policy.policies):
        v = evaluate(sub, trace)
        idx_key = v.bad_index if v.bad_index is not None else float("inf")
        key = (_SEVERITY[v.status], idx_key, pos)
        if best_key is None or key < best_key:
            best_key = key
            best = v
    assert best is not None
    return best


def satisfies(policy: Policy, trace: Trace) -> bool:
    """``True`` iff ``policy`` has no bad prefix AND no unfulfilled obligation.

    Equivalent to ``evaluate(policy, trace).status == "satisfied"``.
    """
    return evaluate(policy, trace).status == SATISFIED


# ---------------------------------------------------------------------------
# Distinguishing-trace search (NL-policy disambiguation, plan §4.3)
# ---------------------------------------------------------------------------

def find_distinguishing_trace(
    p1: Policy,
    p2: Policy,
    ctx: PolicyContext,
    *,
    max_len: int = 4,
    alphabet: list[EffectEvent] | None = None,
) -> Trace | None:
    """Exhaustively search short traces for one that separates ``p1`` and ``p2``.

    Returns the FIRST (in the deterministic enumeration order below) trace
    ``t`` with ``satisfies(p1, t) != satisfies(p2, t)``, or ``None`` if no trace
    of length ``0 .. max_len`` over the alphabet distinguishes them. This backs
    the NL-policy distinguishing-trace idea: when an untrusted proposer offers
    two candidate policies for the same English sentence, a witnessing trace
    shows the user where they disagree.

    Alphabet construction (when ``alphabet is None``)
    -------------------------------------------------
    The default alphabet is kept deliberately small and is derived
    deterministically from the material appearing in the two policies and the
    context:

    * a single **neutral** event that satisfies no atom (``node_id="_"``), so
      "nothing happened this step" is always available; then
    * for every predicate atom occurring in ``p1`` or ``p2`` (in first-seen
      order), one event constructed to satisfy exactly that atom, when such an
      event can be built (see :func:`_events_for_atom`); then
    * for every tool name declared in ``ctx.tools`` (sorted) not already
      covered, one tool-invocation event.

    Duplicate events (by canonical key) are dropped, preserving first-seen
    order. Enumeration then proceeds by increasing length ``0, 1, .. max_len``
    and, within a length, in lexicographic order over the alphabet index —
    fully deterministic.
    """
    alpha = alphabet if alphabet is not None else _default_alphabet(p1, p2, ctx)

    for length in range(max_len + 1):
        for combo in itertools.product(alpha, repeat=length):
            trace: Trace = tuple(combo)
            if satisfies(p1, trace) != satisfies(p2, trace):
                return trace
    return None


def _default_alphabet(p1: Policy, p2: Policy, ctx: PolicyContext) -> list[EffectEvent]:
    """Build the small default event alphabet (see :func:`find_distinguishing_trace`)."""
    events: list[EffectEvent] = []
    seen_keys: set[str] = set()

    def _add(ev: EffectEvent) -> None:
        key = _event_key(ev)
        if key not in seen_keys:
            seen_keys.add(key)
            events.append(ev)

    # 1) The neutral event: satisfies no atom.
    _add(EffectEvent(node_id="_"))

    # 2) One satisfying event per atom of p1/p2, in first-seen order.
    covered_tools: set[str] = set()
    for atom in _ordered_atoms(p1, p2):
        for ev in _events_for_atom(atom):
            _add(ev)
            if ev.tool_name:
                covered_tools.add(ev.tool_name)

    # 3) A tool-invocation event per declared tool not already covered.
    for name in sorted(ctx.tools):
        if name not in covered_tools:
            _add(EffectEvent(node_id=f"tool_{name}", tool_name=name, action_type="tool"))

    return events


def _ordered_atoms(*policies: Policy) -> list[Predicate]:
    """Leaf atoms across ``policies`` in first-seen order (deduped by key)."""
    out: list[Predicate] = []
    seen: set[str] = set()
    for pol in policies:
        for atom in pol.predicates():
            k = atom.atom_key()
            if k not in seen:
                seen.add(k)
                out.append(atom)
    return out


def _event_key(ev: EffectEvent) -> str:
    """A canonical, hashable identity for deduping alphabet events."""
    return repr((
        ev.effect.value,
        ev.action_type,
        ev.tool_name,
        tuple(sorted((str(k), repr(v)) for k, v in ev.args)),
        ev.principal,
        ev.authority,
        ev.identity,
        ev.capability,
        tuple(ev.in_labels),
        tuple(ev.out_labels),
        tuple(ev.tags),
        ev.decision,
    ))


def _events_for_atom(atom: Predicate) -> list[EffectEvent]:
    """Concrete event(s) that make ``atom`` true, or ``[]`` if none can be built.

    Best-effort and minimal: each event sets only the field(s) the atom
    inspects, so it tends to satisfy that atom alone. Atoms whose satisfying
    witness cannot be synthesized (``TrueP``/``FalseP``, some ``ArgConstraint``
    ops) contribute nothing; the neutral event and the remaining alphabet still
    give the search useful separating power.
    """
    node = "a"
    if isinstance(atom, Effect):
        return [EffectEvent(node_id=node, effect=atom.kind)]
    if isinstance(atom, Tool):
        return [EffectEvent(node_id=node, tool_name=atom.name, action_type="tool")]
    if isinstance(atom, Action):
        return [EffectEvent(node_id=node, action_type=atom.name)]
    if isinstance(atom, Tag):
        return [EffectEvent(node_id=node, tags=(atom.name,))]
    if isinstance(atom, Approval):
        return [EffectEvent(node_id=node, action_type="human", tags=("approval",))]
    if isinstance(atom, Authority):
        return [EffectEvent(node_id=node, authority=atom.name)]
    if isinstance(atom, Identity):
        return [EffectEvent(node_id=node, identity=atom.name)]
    if isinstance(atom, Capability):
        return [EffectEvent(node_id=node, capability=atom.name)]
    if isinstance(atom, DataLabelIn):
        return [EffectEvent(node_id=node, in_labels=(atom.label,))]
    if isinstance(atom, DataLabelOut):
        return [EffectEvent(node_id=node, out_labels=(atom.label,))]
    if isinstance(atom, ArgConstraint):
        ok, actual = _arg_value_satisfying(atom.op, atom.value)
        if not ok:
            return []
        tool_name = atom.tool if atom.tool is not None else "any_tool"
        return [EffectEvent(
            node_id=node,
            tool_name=tool_name,
            action_type="tool",
            args=((atom.arg, actual),),
        )]
    # TrueP / FalseP / anything else: no distinguishing witness to add.
    return []


def _arg_value_satisfying(op: Op, value: Any) -> tuple[bool, Any]:
    """Synthesize a concrete ``actual`` with ``_cmp(actual, op, value)`` true.

    Returns ``(True, actual)`` on success, ``(False, None)`` when no witness can
    be produced deterministically for this operator/value. Mirrors the concrete
    comparison in :func:`agentproof.cegar.policy._cmp`.
    """
    if op is Op.EQ:
        return (True, value)
    if op is Op.NE:
        return (True, _distinct_from(value))
    if op is Op.LE or op is Op.GE:
        return (True, value)
    if op is Op.LT:
        if isinstance(value, bool):
            return (False, None)
        if isinstance(value, (int, float)):
            return (True, value - 1)
        return (False, None)
    if op is Op.GT:
        if isinstance(value, bool):
            return (False, None)
        if isinstance(value, (int, float)):
            return (True, value + 1)
        return (False, None)
    if op is Op.IN:
        try:
            it = iter(value)
        except TypeError:
            return (False, None)
        for elem in it:
            return (True, elem)
        return (False, None)  # empty collection: nothing is IN it
    if op is Op.NIN:
        # A value not in the collection: probe a couple of sentinels.
        for cand in _distinct_from(value), 0, "", "__nin__":
            try:
                if cand not in value:
                    return (True, cand)
            except TypeError:
                continue
        return (False, None)
    if op is Op.REGEX:
        # A literal-ish witness: any string containing the pattern text often
        # matches (re.search). Only claim success if it actually does.
        cand = str(value)
        try:
            if re.search(str(value), cand) is not None:
                return (True, cand)
        except re.error:
            return (False, None)
        return (False, None)
    return (False, None)


def _distinct_from(value: Any) -> Any:
    """A value guaranteed ``!=`` ``value`` for the common scalar types."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    if isinstance(value, str):
        return value + "_x"
    # Fallback sentinel; unequal to arbitrary objects by identity/type.
    return object()


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def _smoke() -> None:
    def ev(**kw: Any) -> EffectEvent:
        kw.setdefault("node_id", "n")
        return EffectEvent(**kw)

    # -- Never fires at the right index -----------------------------------
    pol = Never(Effect(EffectKind.DELETE), rule_id="no_delete")
    trace = (ev(), ev(effect=EffectKind.READ), ev(effect=EffectKind.DELETE), ev())
    v = evaluate(pol, trace)
    assert v.status == BAD_PREFIX and v.bad_index == 2, v
    assert v.rule_id == "no_delete"
    assert not satisfies(pol, trace)
    assert satisfies(pol, (ev(), ev(effect=EffectKind.READ)))

    # -- RequireBefore strict vs non-strict -------------------------------
    approve = Approval()
    delete = Effect(EffectKind.DELETE)
    both = ev(effect=EffectKind.DELETE, action_type="human", tags=("approval",))
    strict = RequireBefore(approve, delete, strict=True, rule_id="rb_strict")
    loose = RequireBefore(approve, delete, strict=False, rule_id="rb_loose")
    # A single event satisfying both: strict => bad (approval not strictly
    # earlier); non-strict => ok.
    assert evaluate(strict, (both,)).status == BAD_PREFIX
    assert evaluate(loose, (both,)).status == SATISFIED
    # Approval strictly before delete: both satisfied.
    ok_trace = (ev(action_type="human", tags=("approval",)), ev(effect=EffectKind.DELETE))
    assert satisfies(strict, ok_trace) and satisfies(loose, ok_trace)
    # Delete with no prior approval: both bad at index 0.
    assert evaluate(strict, (ev(effect=EffectKind.DELETE),)).bad_index == 0
    assert evaluate(loose, (ev(effect=EffectKind.DELETE),)).bad_index == 0

    # -- Forbid contiguous vs scattered -----------------------------------
    a = Tag("a")
    b = Tag("b")
    scattered = Forbid((a, b), contiguous=False, rule_id="f_scatter")
    contig = Forbid((a, b), contiguous=True, rule_id="f_contig")
    t_gap = (ev(tags=("a",)), ev(tags=("x",)), ev(tags=("b",)))
    # Scattered: a..b with a gap => bad at the b (index 2).
    assert evaluate(scattered, t_gap).bad_index == 2
    # Contiguous: the gap resets, so a..gap..b is NOT a violation.
    assert satisfies(contig, t_gap)
    # Contiguous adjacent a,b => bad at index 1.
    assert evaluate(contig, (ev(tags=("a",)), ev(tags=("b",)))).bad_index == 1

    # -- Bounded (k+1)-th --------------------------------------------------
    quota = Bounded(Tool("send"), k=1, rule_id="bnd")
    send = ev(tool_name="send", action_type="tool")
    assert satisfies(quota, (send,))                       # 1 <= k
    v = evaluate(quota, (send, ev(), send))                # 2nd send at index 2
    assert v.status == BAD_PREFIX and v.bad_index == 2, v

    # -- LeadsTo unfulfilled at end ---------------------------------------
    lt = LeadsTo(Tool("open"), Tool("close"), rule_id="lt")
    opened = ev(tool_name="open", action_type="tool")
    closed = ev(tool_name="close", action_type="tool")
    assert evaluate(lt, (opened,)).status == UNFULFILLED
    assert not satisfies(lt, (opened,))
    assert satisfies(lt, (opened, closed))
    assert satisfies(lt, ())                               # never triggered

    # -- All picks earliest / most-severe ---------------------------------
    combined = All((
        Never(Effect(EffectKind.DELETE), rule_id="A_never"),
        Bounded(Tool("send"), k=0, rule_id="B_bounded"),
    ), rule_id="combo")
    # send (bad for Bounded at idx 0), then delete (bad for Never at idx 1).
    # Earliest bad index wins => Bounded at index 0.
    trace = (ev(tool_name="send", action_type="tool"), ev(effect=EffectKind.DELETE))
    v = evaluate(combined, trace)
    assert v.status == BAD_PREFIX and v.bad_index == 0 and v.rule_id == "B_bounded", v
    # bad_prefix beats unfulfilled: pair a satisfiable-but-unfulfilled LeadsTo
    # with a later Never violation.
    combined2 = All((
        LeadsTo(Tool("open"), Tool("close"), rule_id="L"),
        Never(Effect(EffectKind.DELETE), rule_id="N"),
    ))
    v = evaluate(combined2, (opened, ev(effect=EffectKind.DELETE)))
    assert v.status == BAD_PREFIX and v.rule_id == "N", v
    # No bad prefix but an unfulfilled sub => All is UNFULFILLED, and the
    # reported rule_id is that of the unfulfilled sub (severity: bad>unful>sat).
    v = evaluate(combined2, (opened,))
    assert v.status == UNFULFILLED and v.bad_index is None and v.rule_id == "L", v
    # A fully satisfied All is satisfied.
    assert satisfies(combined2, (opened, closed))

    # -- empty-trace edge cases (every operator accepts the empty trace) ---
    assert satisfies(Never(Effect(EffectKind.DELETE)), ())
    assert satisfies(RequireBefore(approve, delete), ())
    assert satisfies(Forbid((a, b)), ())
    assert satisfies(Forbid((a, b), contiguous=True), ())
    assert satisfies(Bounded(Tool("send"), k=0), ())
    assert satisfies(LeadsTo(Tool("open"), Tool("close")), ())
    assert satisfies(All((strict, quota, lt)), ())

    # -- Bounded k=0 fires on the very first match ------------------------
    v = evaluate(Bounded(Tool("send"), k=0, rule_id="k0"), (send,))
    assert v.status == BAD_PREFIX and v.bad_index == 0, v

    # -- Forbid: a partial (incomplete) match never violates --------------
    # Non-contiguous a..b with the b missing is satisfied; the lone a is not
    # enough to complete the forbidden subsequence.
    assert satisfies(scattered, (ev(tags=("a",)), ev(tags=("x",))))
    assert satisfies(contig, (ev(tags=("a",)),))
    # Contiguous reset: a, a, b still violates on the adjacent a,b tail.
    v = evaluate(contig, (ev(tags=("a",)), ev(tags=("a",)), ev(tags=("b",))))
    assert v.status == BAD_PREFIX and v.bad_index == 2, v

    # -- find_distinguishing_trace ----------------------------------------
    from agentproof.cegar.ir import ToolSchema

    ctx = PolicyContext(tools={"send": ToolSchema("send")})
    k1 = Bounded(Tool("send"), k=1, rule_id="k1")
    k2 = Bounded(Tool("send"), k=2, rule_id="k2")
    witness = find_distinguishing_trace(k1, k2, ctx, max_len=4)
    assert witness is not None, "expected a distinguishing trace for k=1 vs k=2"
    # The witness must actually separate them.
    assert satisfies(k1, witness) != satisfies(k2, witness)
    # It takes exactly two `send` events to tell k=1 from k=2.
    assert sum(1 for e in witness if e.tool_name == "send") == 2, witness

    # Identical policies: no distinguishing trace.
    k1b = Bounded(Tool("send"), k=1, rule_id="k1b")
    assert find_distinguishing_trace(k1, k1b, ctx, max_len=4) is None

    # Two genuinely different operators also separate.
    never_del = Never(Effect(EffectKind.DELETE))
    bounded_del = Bounded(Effect(EffectKind.DELETE), k=1)
    w2 = find_distinguishing_trace(never_del, bounded_del, PolicyContext(), max_len=3)
    assert w2 is not None and satisfies(never_del, w2) != satisfies(bounded_del, w2), w2

    print("ORACLE SMOKE OK")


if __name__ == "__main__":
    _smoke()
