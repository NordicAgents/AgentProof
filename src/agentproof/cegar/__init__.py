"""AgentProof-CEGAR (Paper 2): proof-carrying repair for tool-using agents.

Build order (plan §1.1a): (1) tri-valued SAFE/UNSAFE/UNKNOWN analysis over a
may/must effect IR, (2) source-level witnesses + effect/authority/arg/identity/
data-label annotations, (3) conservative modeling of exceptions/retries/
parallel/callbacks/nested agents, (4) typed policies + independent oracle,
(5) CEGAR + proof-carrying repair + certificate checking.

Three-way soundness contract
----------------------------
Every analysis returns one of three verdicts, and each is a *guarded* claim:

* ``SAFE``   — the policy holds on **every** concretization of the may/must
  IR (a ``must``-side proof). A ``SAFE`` verdict is accompanied by a
  machine-checkable :class:`~agentproof.cegar.certificate.Certificate`.
* ``UNSAFE`` — a concrete counterexample trace exists that the independent
  oracle agrees violates the policy (a ``may``-side refutation with witness).
* ``UNKNOWN`` — the abstraction is too coarse to decide, and CEGAR could not
  refine it to SAFE or UNSAFE within the budget. ``UNKNOWN`` is never silently
  upgraded to SAFE; it is a first-class, conservative outcome.

Trusted computing base (TCB)
----------------------------
Only :mod:`agentproof.cegar.checker` (the independent certificate checker) and
the definitions of :mod:`agentproof.cegar.ir` / :mod:`agentproof.cegar.policy`
it depends on must be trusted for a ``SAFE`` claim. The lifter
(:mod:`~agentproof.cegar.frontend`), the CEGAR loop, and the repair search are
**outside** the TCB: their output is re-validated by the checker, so a bug in
them can cause a false ``UNKNOWN``/``UNSAFE`` or a rejected certificate, but
never an accepted certificate for an actually-unsafe graph.

Public API
----------
``analyze`` / ``repair`` / ``certify`` / ``check_certificate`` /
``analyze_and_repair`` are the stable entry points; the key IR, policy, and
frontend types are re-exported alongside them. Heavy submodules are imported
lazily inside the entry points so the package stays importable during
incremental construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentproof.cegar.ir import (
    AbstractValue,
    EffectEvent,
    EffectKind,
    EffectNode,
    MayMustGraph,
    ModalEdge,
    Modality,
    Provenance,
    Trace,
    UnsupportedFact,
    UnsupportedKind,
    Verdict,
    region_is_certifiable,
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
    Policy,
    PolicyClass,
    PolicyContext,
    PredAnd,
    PredNot,
    PredOr,
    Predicate,
    RequireBefore,
    Tag,
    Tool,
    classify,
    policy_from_dict,
    pred_from_dict,
    rule_id_of,
    typecheck,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids import cycles at runtime
    from agentproof.cegar.cegar import CegarResult
    from agentproof.cegar.certificate import Certificate
    from agentproof.cegar.checker import CheckResult
    from agentproof.cegar.repair import RepairResult


def analyze(graph: "MayMustGraph", policy: "Policy", **kwargs: Any) -> "CegarResult":
    """Run CEGAR analysis of ``policy`` against the may/must ``graph``.

    Returns a :class:`~agentproof.cegar.cegar.CegarResult` whose ``verdict`` is
    ``Verdict.SAFE`` (policy holds on every concretization), ``Verdict.UNSAFE``
    (a concrete oracle-confirmed counterexample exists), or ``Verdict.UNKNOWN``
    (the abstraction could not be refined to a decision within the budget).

    Keyword arguments are forwarded to :func:`agentproof.cegar.cegar.analyze`
    (e.g. ``max_refinements``, ``concretizer``, ``assume_trace_conservative``).
    """
    from agentproof.cegar.cegar import analyze as _analyze

    return _analyze(graph, policy, **kwargs)


def repair(graph: "MayMustGraph", policy: "Policy", **kwargs: Any) -> "RepairResult":
    """Search for a minimal-cost, regression-safe patch making ``graph`` SAFE.

    Returns a :class:`~agentproof.cegar.repair.RepairResult`; on ``success`` its
    ``patched_graph`` is proven SAFE and ``certificate`` carries an
    independently re-checked proof. Keyword arguments are forwarded to
    :func:`agentproof.cegar.repair.repair` (e.g. ``config``, ``proposer``,
    ``regression``, ``assume_trace_conservative``).
    """
    from agentproof.cegar.repair import repair as _repair

    return _repair(graph, policy, **kwargs)


def certify(
    graph: "MayMustGraph", policy: "Policy", **kwargs: Any
) -> "Certificate | None":
    """Analyze ``graph`` and, iff it is SAFE, return a *checked* certificate.

    Runs :func:`analyze`; when the verdict is ``Verdict.SAFE`` a certificate is
    built for the analyzed graph and passed through the independent
    :func:`check_certificate`. The certificate is returned only if the checker
    accepts it; otherwise (non-SAFE verdict, or a certificate the TCB rejects)
    this returns ``None``. Keyword arguments are forwarded to :func:`analyze`.
    """
    from agentproof.cegar.certificate import build_certificate
    from agentproof.cegar.checker import check_certificate as _check

    result = analyze(graph, policy, **kwargs)
    if result.verdict is not Verdict.SAFE:
        return None
    graph_for_cert = result.refined_graph if result.refined_graph is not None else graph
    assume_trace_conservative = bool(kwargs.get("assume_trace_conservative", False))
    cert = build_certificate(
        graph_for_cert,
        policy,
        result.product_result,
        assume_trace_conservative=assume_trace_conservative,
        created_tag="certify",
    )
    return cert if _check(cert).accepted else None


def check_certificate(cert: "Certificate") -> "CheckResult":
    """Independently validate a certificate (the TCB entry point).

    Delegates to :func:`agentproof.cegar.checker.check_certificate`, which
    re-derives the SAFE claim from the certificate alone, without trusting the
    lifter, CEGAR loop, or repair search.
    """
    from agentproof.cegar.checker import check_certificate as _check

    return _check(cert)


def analyze_and_repair(
    graph: "MayMustGraph", policy: "Policy", **kwargs: Any
) -> dict:
    """Analyze ``graph``; if it is not SAFE, attempt a proof-carrying repair.

    Returns a combined report ``dict`` with keys:

    * ``verdict``        — the *final* :class:`Verdict` (post-repair if a repair
      succeeded, else the analysis verdict).
    * ``analysis``       — the initial :class:`CegarResult`.
    * ``repaired``       — ``True`` iff a repair was attempted and succeeded.
    * ``repair``         — the :class:`RepairResult`, or ``None`` if no repair
      was attempted (the graph was already SAFE).
    * ``certificate``    — a checker-accepted :class:`Certificate` for the final
      SAFE graph, or ``None`` if the final verdict is not SAFE.
    * ``patched_graph``  — the SAFE graph (the repaired graph if repaired, else
      the original when already SAFE, else ``None``).

    Keyword arguments are forwarded to both :func:`analyze` and :func:`repair`;
    only the keywords each accepts are passed through.
    """
    import inspect

    from agentproof.cegar.cegar import analyze as _analyze
    from agentproof.cegar.repair import repair as _repair

    analyze_kwargs = {
        k: v
        for k, v in kwargs.items()
        if k in inspect.signature(_analyze).parameters
    }
    result = _analyze(graph, policy, **analyze_kwargs)

    report: dict = {
        "verdict": result.verdict,
        "analysis": result,
        "repaired": False,
        "repair": None,
        "certificate": None,
        "patched_graph": None,
    }

    if result.verdict is Verdict.SAFE:
        report["patched_graph"] = (
            result.refined_graph if result.refined_graph is not None else graph
        )
        report["certificate"] = certify(graph, policy, **analyze_kwargs)
        return report

    repair_kwargs = {
        k: v
        for k, v in kwargs.items()
        if k in inspect.signature(_repair).parameters
    }
    repair_result = _repair(graph, policy, **repair_kwargs)
    report["repair"] = repair_result
    report["repaired"] = bool(repair_result.success)
    report["verdict"] = repair_result.verdict
    if repair_result.success:
        report["patched_graph"] = repair_result.patched_graph
        report["certificate"] = repair_result.certificate
    return report


# Lazily re-exported factories (kept out of module import to avoid cycles).
def lift(graph: Any, **kwargs: Any) -> "MayMustGraph":
    """Lift a framework ``AgentGraph`` into a may/must :class:`MayMustGraph`.

    Thin re-export of :func:`agentproof.cegar.frontend.lift`; the lifter is
    outside the TCB (its output is re-validated by the checker).
    """
    from agentproof.cegar.frontend import lift as _lift

    return _lift(graph, **kwargs)


def default_tool_schemas() -> dict:
    """Return the built-in tool-schema table used by the frontend lifter."""
    from agentproof.cegar.frontend import default_tool_schemas as _dts

    return _dts()


def build_certificate(
    graph: "MayMustGraph", policy: "Policy", product_result: Any, **kwargs: Any
) -> "Certificate":
    """Re-export of :func:`agentproof.cegar.certificate.build_certificate`."""
    from agentproof.cegar.certificate import build_certificate as _bc

    return _bc(graph, policy, product_result, **kwargs)


__all__ = [
    # --- convenience entry points ---
    "analyze",
    "repair",
    "certify",
    "check_certificate",
    "analyze_and_repair",
    # --- frontend / certificate factories ---
    "lift",
    "default_tool_schemas",
    "build_certificate",
    # --- IR types ---
    "AbstractValue",
    "EffectEvent",
    "EffectKind",
    "EffectNode",
    "MayMustGraph",
    "ModalEdge",
    "Modality",
    "Provenance",
    "Trace",
    "UnsupportedFact",
    "UnsupportedKind",
    "Verdict",
    "region_is_certifiable",
    # --- policy language ---
    "Policy",
    "Never",
    "RequireBefore",
    "Forbid",
    "Bounded",
    "LeadsTo",
    "All",
    "Effect",
    "Tool",
    "Action",
    "Approval",
    "Authority",
    "Identity",
    "Capability",
    "DataLabelIn",
    "DataLabelOut",
    "ArgConstraint",
    "Tag",
    "PredAnd",
    "PredOr",
    "PredNot",
    "Predicate",
    "Op",
    "PolicyClass",
    "PolicyContext",
    "classify",
    "typecheck",
    "rule_id_of",
    "policy_from_dict",
    "pred_from_dict",
]
