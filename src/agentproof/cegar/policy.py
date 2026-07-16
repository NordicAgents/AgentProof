"""Typed recursive policy language for AgentProof-CEGAR (Paper 2, plan §4.3).

A policy is a finite-trace safety (or termination-time) property built from
**predicate atoms** over a single :class:`~agentproof.cegar.ir.EffectEvent` and
**temporal/structural operators** over traces. The language is deliberately
small and closed under the operations the shield can actually enforce
(authorization, required-before, forbidden sequences, quotas, argument
restrictions, identity/authority/data-label constraints).

Two evaluation modes — the differential backbone
-------------------------------------------------
Every predicate supports:

* ``eval(event) -> bool`` — truth on a **concrete** event. The slow oracle
  (:mod:`agentproof.cegar.oracle`) evaluates a policy over a concrete trace by
  composing these.
* ``abstract_eval(node) -> (may, must)`` — a **sound** pair on an abstract
  :class:`~agentproof.cegar.ir.EffectNode`: ``may`` over-approximates (True if
  *some* concretization makes the atom true), ``must`` under-approximates (True
  only if *every* concretization does). The product checker
  (:mod:`agentproof.cegar.product`) drives the may/must automaton with these.

The *temporal* semantics of each operator is documented here in prose and
implemented **independently twice** — once denotationally in the oracle, once
as a monitor automaton in the product checker. E0 differential testing
cross-checks the two; that redundancy is intentional (plan §7, E0).

Classification (plan §4.3)
--------------------------
:func:`classify` sorts a policy into ``SHIELD_ENFORCEABLE`` (a bad-prefix
safety property a veto can enforce), ``TERMINATION_TIME`` (a response /
eventual obligation, only checkable when a run ends), or ``UNSUPPORTED``
(references a tool/state/label the schema does not declare — a type error).
Compilability alone is never a quality signal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable

from agentproof.cegar.ir import (
    AbstractValue,
    AVKind,
    EffectEvent,
    EffectKind,
    EffectNode,
    ToolSchema,
)


class PolicyClass(str, Enum):
    SHIELD_ENFORCEABLE = "shield_enforceable"
    TERMINATION_TIME = "termination_time"
    UNSUPPORTED = "unsupported"


class Op(str, Enum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"
    IN = "in"
    NIN = "nin"
    REGEX = "regex"


# ---------------------------------------------------------------------------
# Predicate atoms (state formulas over a single event / abstract node)
# ---------------------------------------------------------------------------

class Predicate:
    """Base class for per-event predicates. Subclasses are frozen dataclasses."""

    def eval(self, event: EffectEvent) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:  # pragma: no cover
        raise NotImplementedError

    def atoms(self) -> tuple["Predicate", ...]:
        """Leaf atoms (for the DFA alphabet and type checking)."""
        return (self,)

    def atom_key(self) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError


@dataclass(frozen=True)
class TrueP(Predicate):
    def eval(self, event: EffectEvent) -> bool:
        return True

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        return (True, True)

    def atoms(self) -> tuple[Predicate, ...]:
        return ()

    def atom_key(self) -> str:
        return "true"

    def to_dict(self) -> dict[str, Any]:
        return {"pred": "true"}


@dataclass(frozen=True)
class FalseP(Predicate):
    def eval(self, event: EffectEvent) -> bool:
        return False

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        return (False, False)

    def atoms(self) -> tuple[Predicate, ...]:
        return ()

    def atom_key(self) -> str:
        return "false"

    def to_dict(self) -> dict[str, Any]:
        return {"pred": "false"}


@dataclass(frozen=True)
class Effect(Predicate):
    """The event's observable effect is ``kind``."""

    kind: EffectKind

    def eval(self, event: EffectEvent) -> bool:
        return event.effect == self.kind

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        if node.effect == self.kind:
            return (True, True)
        if node.effect == EffectKind.UNKNOWN:
            return (True, False)  # could be `kind`; not forced
        return (False, False)

    def atom_key(self) -> str:
        return f"effect:{self.kind.value}"

    def to_dict(self) -> dict[str, Any]:
        return {"pred": "effect", "kind": self.kind.value}


@dataclass(frozen=True)
class Tool(Predicate):
    """The event invokes tool ``name``."""

    name: str

    def eval(self, event: EffectEvent) -> bool:
        return event.tool_name == self.name

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        m = node.tool == self.name
        return (m, m)

    def atom_key(self) -> str:
        return f"tool:{self.name}"

    def to_dict(self) -> dict[str, Any]:
        return {"pred": "tool", "name": self.name}


@dataclass(frozen=True)
class Action(Predicate):
    """The event's action type (node kind) is ``name`` (e.g. ``human``)."""

    name: str

    def eval(self, event: EffectEvent) -> bool:
        return event.action_type == self.name

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        m = f"kind:{self.name}" in node.state_predicates
        return (m, m)

    def atom_key(self) -> str:
        return f"action:{self.name}"

    def to_dict(self) -> dict[str, Any]:
        return {"pred": "action", "name": self.name}


@dataclass(frozen=True)
class Tag(Predicate):
    name: str

    def eval(self, event: EffectEvent) -> bool:
        return self.name in event.tags

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        m = self.name in node.state_predicates
        return (m, m)

    def atom_key(self) -> str:
        return f"tag:{self.name}"

    def to_dict(self) -> dict[str, Any]:
        return {"pred": "tag", "name": self.name}


@dataclass(frozen=True)
class Approval(Predicate):
    """The event is a human approval / confirmation gate."""

    def eval(self, event: EffectEvent) -> bool:
        return (
            "approval" in event.tags
            or "human" in event.tags
            or event.action_type == "human"
            or event.decision in ("approve", "approved")
        )

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        m = (
            "human_pause" in node.capability
            or "kind:human" in node.state_predicates
        )
        return (m, m)

    def atom_key(self) -> str:
        return "approval"

    def to_dict(self) -> dict[str, Any]:
        return {"pred": "approval"}


@dataclass(frozen=True)
class Authority(Predicate):
    name: str

    def eval(self, event: EffectEvent) -> bool:
        return event.authority == self.name

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        m = node.authority == self.name
        return (m, m)

    def atom_key(self) -> str:
        return f"authority:{self.name}"

    def to_dict(self) -> dict[str, Any]:
        return {"pred": "authority", "name": self.name}


@dataclass(frozen=True)
class Identity(Predicate):
    name: str

    def eval(self, event: EffectEvent) -> bool:
        return event.identity == self.name

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        m = node.identity == self.name
        return (m, m)

    def atom_key(self) -> str:
        return f"identity:{self.name}"

    def to_dict(self) -> dict[str, Any]:
        return {"pred": "identity", "name": self.name}


@dataclass(frozen=True)
class Capability(Predicate):
    name: str

    def eval(self, event: EffectEvent) -> bool:
        return self.name in _split_caps(event.capability)

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        m = self.name in _split_caps(node.capability)
        return (m, m)

    def atom_key(self) -> str:
        return f"capability:{self.name}"

    def to_dict(self) -> dict[str, Any]:
        return {"pred": "capability", "name": self.name}


@dataclass(frozen=True)
class DataLabelIn(Predicate):
    label: str

    def eval(self, event: EffectEvent) -> bool:
        return self.label in event.in_labels

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        m = self.label in node.in_labels
        return (m, m)

    def atom_key(self) -> str:
        return f"in_label:{self.label}"

    def to_dict(self) -> dict[str, Any]:
        return {"pred": "in_label", "label": self.label}


@dataclass(frozen=True)
class DataLabelOut(Predicate):
    label: str

    def eval(self, event: EffectEvent) -> bool:
        return self.label in event.out_labels

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        m = self.label in node.out_labels
        return (m, m)

    def atom_key(self) -> str:
        return f"out_label:{self.label}"

    def to_dict(self) -> dict[str, Any]:
        return {"pred": "out_label", "label": self.label}


@dataclass(frozen=True)
class ArgConstraint(Predicate):
    """Holds when the event invokes ``tool`` (or any tool if ``tool is None``)
    and its argument ``arg`` satisfies ``op value``.

    Typically wrapped in :class:`Never` to forbid a bad argument (e.g.
    ``Never(ArgConstraint("wire_transfer", "amount", Op.GT, 10000))``).
    """

    tool: str | None
    arg: str
    op: Op
    value: Any

    def eval(self, event: EffectEvent) -> bool:
        if self.tool is not None and event.tool_name != self.tool:
            return False
        actual = event.arg(self.arg)
        if actual is None:
            return False  # argument absent on this concrete event
        return _cmp(actual, self.op, self.value)

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        if self.tool is not None and node.tool != self.tool:
            return (False, False)
        av = node.arg(self.arg)
        return _av_may_must(av, self.op, self.value)

    def atom_key(self) -> str:
        return f"arg:{self.tool}:{self.arg}:{self.op.value}:{self.value!r}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pred": "arg",
            "tool": self.tool,
            "arg": self.arg,
            "op": self.op.value,
            "value": self.value,
        }


@dataclass(frozen=True)
class PredNot(Predicate):
    inner: Predicate

    def eval(self, event: EffectEvent) -> bool:
        return not self.inner.eval(event)

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        may, must = self.inner.abstract_eval(node)
        return (not must, not may)

    def atoms(self) -> tuple[Predicate, ...]:
        return self.inner.atoms()

    def atom_key(self) -> str:
        return f"not({self.inner.atom_key()})"

    def to_dict(self) -> dict[str, Any]:
        return {"pred": "not", "inner": self.inner.to_dict()}


@dataclass(frozen=True)
class PredAnd(Predicate):
    left: Predicate
    right: Predicate

    def eval(self, event: EffectEvent) -> bool:
        return self.left.eval(event) and self.right.eval(event)

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        lm, lM = self.left.abstract_eval(node)
        rm, rM = self.right.abstract_eval(node)
        return (lm and rm, lM and rM)

    def atoms(self) -> tuple[Predicate, ...]:
        return self.left.atoms() + self.right.atoms()

    def atom_key(self) -> str:
        return f"and({self.left.atom_key()},{self.right.atom_key()})"

    def to_dict(self) -> dict[str, Any]:
        return {"pred": "and", "left": self.left.to_dict(), "right": self.right.to_dict()}


@dataclass(frozen=True)
class PredOr(Predicate):
    left: Predicate
    right: Predicate

    def eval(self, event: EffectEvent) -> bool:
        return self.left.eval(event) or self.right.eval(event)

    def abstract_eval(self, node: EffectNode) -> tuple[bool, bool]:
        lm, lM = self.left.abstract_eval(node)
        rm, rM = self.right.abstract_eval(node)
        return (lm or rm, lM or rM)

    def atoms(self) -> tuple[Predicate, ...]:
        return self.left.atoms() + self.right.atoms()

    def atom_key(self) -> str:
        return f"or({self.left.atom_key()},{self.right.atom_key()})"

    def to_dict(self) -> dict[str, Any]:
        return {"pred": "or", "left": self.left.to_dict(), "right": self.right.to_dict()}


# ---------------------------------------------------------------------------
# Policy operators (temporal / structural, over traces)
# ---------------------------------------------------------------------------

class Policy:
    """Base class for trace properties."""

    def predicates(self) -> tuple[Predicate, ...]:  # pragma: no cover - abstract
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError


@dataclass(frozen=True)
class Never(Policy):
    """``G ¬pred`` — ``pred`` must never hold. Bad prefix: ``pred`` holds."""

    pred: Predicate
    rule_id: str = ""

    def predicates(self) -> tuple[Predicate, ...]:
        return self.pred.atoms()

    def to_dict(self) -> dict[str, Any]:
        return {"policy": "never", "rule_id": self.rule_id, "pred": self.pred.to_dict()}


@dataclass(frozen=True)
class RequireBefore(Policy):
    """``guarded`` may not occur unless ``required`` occurred earlier.

    Enforces authorization / approval / authentication before an effect. With
    ``strict=True`` (default) ``required`` must hold at a *strictly earlier*
    event than ``guarded``; with ``strict=False`` the same event may satisfy
    both. Bad prefix: ``guarded`` fires with the obligation unmet.
    """

    required: Predicate
    guarded: Predicate
    strict: bool = True
    rule_id: str = ""

    def predicates(self) -> tuple[Predicate, ...]:
        return self.required.atoms() + self.guarded.atoms()

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": "require_before",
            "rule_id": self.rule_id,
            "required": self.required.to_dict(),
            "guarded": self.guarded.to_dict(),
            "strict": self.strict,
        }


@dataclass(frozen=True)
class Forbid(Policy):
    """A forbidden ordered sequence of predicates.

    Violation once every predicate in ``steps`` has matched in order. With
    ``contiguous=False`` (default) the matches need not be adjacent (scattered
    subsequence, the conservative reading); with ``contiguous=True`` they must
    be consecutive events.
    """

    steps: tuple[Predicate, ...]
    contiguous: bool = False
    rule_id: str = ""

    def predicates(self) -> tuple[Predicate, ...]:
        out: list[Predicate] = []
        for s in self.steps:
            out.extend(s.atoms())
        return tuple(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": "forbid",
            "rule_id": self.rule_id,
            "steps": [s.to_dict() for s in self.steps],
            "contiguous": self.contiguous,
        }


@dataclass(frozen=True)
class Bounded(Policy):
    """``pred`` may occur at most ``k`` times (quota / retry limit).

    Bad prefix: the ``(k+1)``-th occurrence.
    """

    pred: Predicate
    k: int
    rule_id: str = ""

    def predicates(self) -> tuple[Predicate, ...]:
        return self.pred.atoms()

    def to_dict(self) -> dict[str, Any]:
        return {"policy": "bounded", "rule_id": self.rule_id,
                "pred": self.pred.to_dict(), "k": self.k}


@dataclass(frozen=True)
class LeadsTo(Policy):
    """``trigger`` must eventually be followed by ``response`` before the trace
    ends (a termination-time / response obligation, **not** a bad-prefix safety
    property — classified :attr:`PolicyClass.TERMINATION_TIME`). A veto cannot
    enforce it; it is checked as an unfulfilled obligation when a run ends.
    """

    trigger: Predicate
    response: Predicate
    rule_id: str = ""

    def predicates(self) -> tuple[Predicate, ...]:
        return self.trigger.atoms() + self.response.atoms()

    def to_dict(self) -> dict[str, Any]:
        return {"policy": "leads_to", "rule_id": self.rule_id,
                "trigger": self.trigger.to_dict(), "response": self.response.to_dict()}


@dataclass(frozen=True)
class All(Policy):
    """Conjunction: every sub-policy must hold. Violation if any sub violates."""

    policies: tuple[Policy, ...]
    rule_id: str = ""

    def predicates(self) -> tuple[Predicate, ...]:
        out: list[Predicate] = []
        for p in self.policies:
            out.extend(p.predicates())
        return tuple(out)

    def to_dict(self) -> dict[str, Any]:
        return {"policy": "all", "rule_id": self.rule_id,
                "policies": [p.to_dict() for p in self.policies]}


# ---------------------------------------------------------------------------
# Analysis context / schema
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PolicyContext:
    """Declared vocabulary the policy is type-checked against (plan §2.1)."""

    tools: Mapping[str, ToolSchema] = field(default_factory=dict)
    action_types: frozenset[str] = frozenset(
        {"entry", "exit", "tool", "llm", "router", "human", "subgraph", "passthrough"}
    )
    state_vars: frozenset[str] = frozenset()
    data_labels: frozenset[str] = frozenset()
    identities: frozenset[str] = frozenset()
    authorities: frozenset[str] = frozenset()
    capabilities: frozenset[str] = frozenset(
        {"llm", "invokes_tool", "human_pause", "routes", "state_update", "subgraph"}
    )


# ---------------------------------------------------------------------------
# Type checking and classification
# ---------------------------------------------------------------------------

def typecheck(policy: Policy, ctx: PolicyContext) -> list[str]:
    """Return a list of type errors (empty == well typed)."""
    issues: list[str] = []
    for atom in policy.predicates():
        issues.extend(_typecheck_atom(atom, ctx))
    return issues


def _typecheck_atom(atom: Predicate, ctx: PolicyContext) -> list[str]:
    issues: list[str] = []
    if isinstance(atom, Tool):
        if atom.name not in ctx.tools:
            issues.append(f"unknown tool: {atom.name}")
    elif isinstance(atom, Action):
        if atom.name not in ctx.action_types:
            issues.append(f"unknown action type: {atom.name}")
    elif isinstance(atom, Authority):
        if ctx.authorities and atom.name not in ctx.authorities:
            issues.append(f"unknown authority: {atom.name}")
    elif isinstance(atom, Identity):
        if ctx.identities and atom.name not in ctx.identities:
            issues.append(f"unknown identity: {atom.name}")
    elif isinstance(atom, Capability):
        if atom.name not in ctx.capabilities:
            issues.append(f"unknown capability: {atom.name}")
    elif isinstance(atom, (DataLabelIn, DataLabelOut)):
        if ctx.data_labels and atom.label not in ctx.data_labels:
            issues.append(f"unknown data label: {atom.label}")
    elif isinstance(atom, ArgConstraint):
        if atom.tool is not None:
            ts = ctx.tools.get(atom.tool)
            if ts is None:
                issues.append(f"unknown tool: {atom.tool}")
            elif ts.params and ts.param(atom.arg) is None:
                issues.append(f"tool {atom.tool} has no parameter {atom.arg}")
    return issues


def _contains_leadsto(policy: Policy) -> bool:
    if isinstance(policy, LeadsTo):
        return True
    if isinstance(policy, All):
        return any(_contains_leadsto(p) for p in policy.policies)
    return False


def classify(policy: Policy, ctx: PolicyContext) -> PolicyClass:
    """Sort a policy into shield-enforceable / termination-time / unsupported."""
    if typecheck(policy, ctx):
        return PolicyClass.UNSUPPORTED
    if _contains_leadsto(policy):
        return PolicyClass.TERMINATION_TIME
    return PolicyClass.SHIELD_ENFORCEABLE


def rule_id_of(policy: Policy) -> str:
    rid = getattr(policy, "rule_id", "")
    return rid or policy.__class__.__name__.lower()


# ---------------------------------------------------------------------------
# NL front-end hook (untrusted; the actual model call lives outside the TCB)
# ---------------------------------------------------------------------------

@runtime_checkable
class PolicyProposer(Protocol):
    """An untrusted natural-language → policy translator (plan §4.3).

    Implementations (e.g. an LLM) are *outside* the trusted computing base:
    their output must be type-checked and disambiguated with distinguishing
    traces before use. Kept as a Protocol so no model dependency leaks in.
    """

    def propose(self, text: str, ctx: PolicyContext) -> Policy: ...


# ---------------------------------------------------------------------------
# Serialization (round-trips policies for certificates / the checker)
# ---------------------------------------------------------------------------

_PRED_BUILDERS = {
    "true": lambda d: TrueP(),
    "false": lambda d: FalseP(),
    "effect": lambda d: Effect(EffectKind(d["kind"])),
    "tool": lambda d: Tool(d["name"]),
    "action": lambda d: Action(d["name"]),
    "tag": lambda d: Tag(d["name"]),
    "approval": lambda d: Approval(),
    "authority": lambda d: Authority(d["name"]),
    "identity": lambda d: Identity(d["name"]),
    "capability": lambda d: Capability(d["name"]),
    "in_label": lambda d: DataLabelIn(d["label"]),
    "out_label": lambda d: DataLabelOut(d["label"]),
    "arg": lambda d: ArgConstraint(d["tool"], d["arg"], Op(d["op"]), d["value"]),
    "not": lambda d: PredNot(pred_from_dict(d["inner"])),
    "and": lambda d: PredAnd(pred_from_dict(d["left"]), pred_from_dict(d["right"])),
    "or": lambda d: PredOr(pred_from_dict(d["left"]), pred_from_dict(d["right"])),
}


def pred_from_dict(d: Mapping[str, Any]) -> Predicate:
    return _PRED_BUILDERS[d["pred"]](d)


def policy_from_dict(d: Mapping[str, Any]) -> Policy:
    kind = d["policy"]
    rid = d.get("rule_id", "")
    if kind == "never":
        return Never(pred_from_dict(d["pred"]), rule_id=rid)
    if kind == "require_before":
        return RequireBefore(pred_from_dict(d["required"]), pred_from_dict(d["guarded"]),
                             strict=d.get("strict", True), rule_id=rid)
    if kind == "forbid":
        return Forbid(tuple(pred_from_dict(s) for s in d["steps"]),
                      contiguous=d.get("contiguous", False), rule_id=rid)
    if kind == "bounded":
        return Bounded(pred_from_dict(d["pred"]), d["k"], rule_id=rid)
    if kind == "leads_to":
        return LeadsTo(pred_from_dict(d["trigger"]), pred_from_dict(d["response"]), rule_id=rid)
    if kind == "all":
        return All(tuple(policy_from_dict(p) for p in d["policies"]), rule_id=rid)
    raise ValueError(f"unknown policy kind: {kind}")


# ---------------------------------------------------------------------------
# Comparison helpers (concrete + abstract)
# ---------------------------------------------------------------------------

def _split_caps(cap: str) -> frozenset[str]:
    return frozenset(c for c in cap.split(",") if c)


def _cmp(actual: Any, op: Op, value: Any) -> bool:
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
            return re.search(str(value), str(actual)) is not None
    except TypeError:
        return False
    return False


def _av_may_must(av: AbstractValue, op: Op, value: Any) -> tuple[bool, bool]:
    """Sound (may, must) truth of ``av op value``.

    ``may`` over-approximates (True if some concretization satisfies), ``must``
    under-approximates (True only if every concretization does). ``TOP`` yields
    ``(True, False)`` for most ops (unknown => possible but not forced).
    """
    if av.is_bottom:
        return (False, False)
    members = av._members()

    if members is not None:
        may = any(_cmp(m, op, value) for m in members)
        must = all(_cmp(m, op, value) for m in members)
        return (may, must)

    if av.kind is AVKind.INTERVAL:
        return _interval_may_must(av.lo, av.hi, op, value)

    # TOP (unknown): possible for most ops, never forced.
    return (True, False)


def _interval_may_must(lo: float, hi: float, op: Op, value: Any) -> tuple[bool, bool]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        # Non-numeric comparison against a numeric interval: cannot refine.
        return (True, False)
    singleton = lo == hi
    if op is Op.EQ:
        return (lo <= v <= hi, singleton and lo == v)
    if op is Op.NE:
        return (not (singleton and lo == v), not (lo <= v <= hi))
    if op is Op.LT:
        return (lo < v, hi < v)
    if op is Op.LE:
        return (lo <= v, hi <= v)
    if op is Op.GT:
        return (hi > v, lo > v)
    if op is Op.GE:
        return (hi >= v, lo >= v)
    # IN / NIN / REGEX against an interval: not soundly refinable here.
    return (True, False)
