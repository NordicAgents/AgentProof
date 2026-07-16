"""Unit + property tests for the typed policy language (Paper 2, plan §7, §11).

Covers type-checking / classification cases, predicate serialization
round-trips, and the *abstract-predicate soundness* property: over many
generated abstract nodes and concretizations, if the abstract ``must`` is
``True`` then every concretization evaluates ``True``, and if the abstract
``may`` is ``False`` then every concretization evaluates ``False``.
"""

from __future__ import annotations

import itertools

from agentproof.cegar.ir import (
    AbstractValue,
    EffectEvent,
    EffectKind,
    EffectNode,
    ParamSpec,
    Provenance,
    ToolSchema,
)
from agentproof.cegar.policy import (
    Action,
    All,
    Approval,
    ArgConstraint,
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
    PolicyClass,
    PolicyContext,
    PredAnd,
    PredNot,
    PredOr,
    RequireBefore,
    Tag,
    Tool,
    classify,
    pred_from_dict,
    policy_from_dict,
    rule_id_of,
    typecheck,
)


_EXACT = Provenance("ast_explicit", "exact")


def _ctx() -> PolicyContext:
    return PolicyContext(
        tools={
            "wire_transfer": ToolSchema(
                "wire_transfer",
                params=(ParamSpec("amount", "float"), ParamSpec("to", "str")),
                effect=EffectKind.FINANCIAL,
            ),
            "send_email": ToolSchema("send_email"),
        },
        data_labels=frozenset({"pii", "public"}),
        identities=frozenset({"user", "admin"}),
        authorities=frozenset({"finance", "messaging"}),
    )


# ---------------------------------------------------------------------------
# typecheck / classify
# ---------------------------------------------------------------------------

def test_typecheck_accepts_well_typed():
    ctx = _ctx()
    pol = Never(Tool("wire_transfer"), rule_id="no_wire")
    assert typecheck(pol, ctx) == []
    assert classify(pol, ctx) is PolicyClass.SHIELD_ENFORCEABLE


def test_typecheck_unknown_tool():
    ctx = _ctx()
    issues = typecheck(Never(Tool("ghost_tool")), ctx)
    assert issues and "ghost_tool" in issues[0]
    assert classify(Never(Tool("ghost_tool")), ctx) is PolicyClass.UNSUPPORTED


def test_typecheck_unknown_action_authority_identity_label():
    ctx = _ctx()
    assert typecheck(Never(Action("nonsense")), ctx)
    assert typecheck(Never(Authority("nobody")), ctx)
    assert typecheck(Never(Identity("nobody")), ctx)
    assert typecheck(Never(DataLabelIn("secret")), ctx)
    assert typecheck(Never(Capability("teleport")), ctx)


def test_typecheck_arg_constraint_unknown_param():
    ctx = _ctx()
    good = Never(ArgConstraint("wire_transfer", "amount", Op.GT, 100))
    bad = Never(ArgConstraint("wire_transfer", "nonexistent", Op.GT, 100))
    assert typecheck(good, ctx) == []
    assert typecheck(bad, ctx)


def test_classify_leadsto_is_termination_time():
    ctx = _ctx()
    lt = LeadsTo(Tool("send_email"), Approval())
    assert classify(lt, ctx) is PolicyClass.TERMINATION_TIME
    # nested inside All still termination-time
    combined = All((Never(Tool("wire_transfer")), lt))
    assert classify(combined, ctx) is PolicyClass.TERMINATION_TIME


def test_classify_all_shield_enforceable():
    ctx = _ctx()
    combined = All((Never(Tool("wire_transfer")), Bounded(Tool("send_email"), 2)))
    assert classify(combined, ctx) is PolicyClass.SHIELD_ENFORCEABLE


def test_rule_id_of_falls_back_to_class_name():
    assert rule_id_of(Never(Tool("x"), rule_id="custom")) == "custom"
    assert rule_id_of(Never(Tool("x"))) == "never"


# ---------------------------------------------------------------------------
# Serialization round-trips
# ---------------------------------------------------------------------------

def _all_predicates():
    return [
        Effect(EffectKind.FINANCIAL),
        Tool("wire_transfer"),
        Action("human"),
        Tag("approval"),
        Approval(),
        Authority("finance"),
        Identity("user"),
        Capability("invokes_tool"),
        DataLabelIn("pii"),
        DataLabelOut("public"),
        ArgConstraint("wire_transfer", "amount", Op.GT, 10000),
        ArgConstraint(None, "amount", Op.IN, [1, 2, 3]),
        PredNot(Tool("wire_transfer")),
        PredAnd(Tool("wire_transfer"), Effect(EffectKind.FINANCIAL)),
        PredOr(Tag("a"), Tag("b")),
    ]


def test_predicate_roundtrip():
    for p in _all_predicates():
        restored = pred_from_dict(p.to_dict())
        assert restored.to_dict() == p.to_dict()


def test_policy_roundtrip_every_operator():
    policies = [
        Never(Effect(EffectKind.DELETE), rule_id="r1"),
        RequireBefore(Approval(), Effect(EffectKind.FINANCIAL), strict=True, rule_id="r2"),
        RequireBefore(Approval(), Effect(EffectKind.FINANCIAL), strict=False, rule_id="r3"),
        Forbid((Tool("read_database"), Tool("send_email")), contiguous=False, rule_id="r4"),
        Forbid((Tag("a"), Tag("b")), contiguous=True, rule_id="r5"),
        Bounded(Tool("run_shell"), 3, rule_id="r6"),
        LeadsTo(Tool("open"), Tool("close"), rule_id="r7"),
        All((Never(Tool("x")), Bounded(Tool("y"), 1)), rule_id="r8"),
    ]
    for pol in policies:
        restored = policy_from_dict(pol.to_dict())
        assert restored.to_dict() == pol.to_dict()


# ---------------------------------------------------------------------------
# Abstract-predicate soundness (may/must vs. every concretization)
# ---------------------------------------------------------------------------

def _build_node(effect, tool, authority, identity, capability,
                in_labels, out_labels, tags, action_type, av):
    sp = tuple(tags)
    if action_type:
        sp = sp + (f"kind:{action_type}",)
    return EffectNode(
        id="n", effect=effect, tool=tool, authority=authority, identity=identity,
        capability=capability, in_labels=in_labels, out_labels=out_labels,
        abstract_args=(("amount", av),), state_predicates=sp,
        provenance=_EXACT, modeling_confidence="exact",
    )


def _concretizations(node, av):
    """Concrete events consistent with ``node``, ranging the arg over gamma(av)."""
    action = ""
    tags = []
    for sp in node.state_predicates:
        if sp.startswith("kind:"):
            action = sp.split(":", 1)[1]
        else:
            tags.append(sp)
    concretes = [0, 1, 5, 9999, 10000, 10001, 20000, -5, "x"]
    for c in concretes:
        if not av.contains(c):
            continue
        yield EffectEvent(
            node_id="n", effect=node.effect, tool_name=node.tool or None,
            action_type=action, args=(("amount", c),),
            authority=node.authority, identity=node.identity,
            capability=node.capability, in_labels=node.in_labels,
            out_labels=node.out_labels, tags=tuple(tags),
        )


def test_abstract_predicate_soundness_property():
    """must=True ⇒ every concretization True; may=False ⇒ every concretization False."""
    avs = [
        AbstractValue.top(),
        AbstractValue.const(0),
        AbstractValue.const(10001),
        AbstractValue.one_of([5, 10001]),
        AbstractValue.interval(0, 20000),
        AbstractValue.interval(10001, 10001),
    ]
    base_preds = [
        Effect(EffectKind.FINANCIAL),
        Tool("wire_transfer"),
        Authority("finance"),
        Identity("user"),
        Capability("invokes_tool"),
        DataLabelIn("pii"),
        DataLabelOut("public"),
        Tag("approval"),
        Action("human"),
        Approval(),
        ArgConstraint("wire_transfer", "amount", Op.GT, 10000),
        ArgConstraint("wire_transfer", "amount", Op.LE, 10000),
        ArgConstraint(None, "amount", Op.EQ, 5),
    ]
    # a couple of node shapes (matching / non-matching fields)
    node_shapes = [
        dict(effect=EffectKind.FINANCIAL, tool="wire_transfer", authority="finance",
             identity="user", capability="invokes_tool", in_labels=("pii",),
             out_labels=("public",), tags=("approval",), action_type="human"),
        dict(effect=EffectKind.READ, tool="send_email", authority="messaging",
             identity="admin", capability="routes", in_labels=(), out_labels=(),
             tags=(), action_type="tool"),
    ]
    checked = 0
    for shape, av in itertools.product(node_shapes, avs):
        node = _build_node(av=av, **shape)
        concs = list(_concretizations(node, av))
        for base in base_preds:
            wrapped = [
                base,
                PredNot(base),
                PredAnd(base, Effect(node.effect)),
                PredOr(base, Tool(node.tool or "")),
            ]
            for pred in wrapped:
                may, must = pred.abstract_eval(node)
                for ev in concs:
                    truth = pred.eval(ev)
                    if must:
                        assert truth, (pred.to_dict(), av.to_dict(), ev)
                    if not may:
                        assert not truth, (pred.to_dict(), av.to_dict(), ev)
                    checked += 1
    assert checked > 500  # a meaningful number of concretization checks


def test_effect_unknown_node_is_may_not_must():
    """An UNKNOWN-effect node makes an Effect atom possible but not forced."""
    node = EffectNode(id="n", effect=EffectKind.UNKNOWN, provenance=_EXACT,
                      modeling_confidence="exact")
    may, must = Effect(EffectKind.FINANCIAL).abstract_eval(node)
    assert may is True and must is False
