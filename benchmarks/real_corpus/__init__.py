"""Real-corpus evaluation harness for AgentProof-CEGAR (Paper 2, §4.3).

This package evaluates the tri-valued may/must analyzer on the *real* mined agent
workflows in ``corpus/real_world/graphs_v2/`` rather than the synthetic-only
benchmark. Its job is to measure — honestly and soundly — how the analyzer
behaves on lossy, provenance-mixed extractions.

The public surface lives in :mod:`benchmarks.real_corpus.policies`:

* :func:`~benchmarks.real_corpus.policies.classify_tool` — a fixed, documented
  tool-name → effect heuristic (a MAY-side aid only; it never upgrades
  certification).
* :func:`~benchmarks.real_corpus.policies.lift_real` — lift a flat corpus JSON
  into a :class:`~agentproof.cegar.ir.MayMustGraph`, optionally tagging TOOL
  nodes with heuristic effects for may-side analysis while leaving the real,
  lossy provenance (and therefore the SAFE certification gate) untouched.
* :data:`~benchmarks.real_corpus.policies.POLICIES` — the deployer-style safety
  policy library, plus classification/alphabet helpers.
"""

from __future__ import annotations

from benchmarks.real_corpus.policies import (
    DANGEROUS_TOOLS,
    POLICIES,
    TOOL_EFFECT_RULES,
    classify_tool,
    lift_real,
    policy_alphabet_atoms,
    policy_class,
    real_corpus_context,
)

__all__ = [
    "DANGEROUS_TOOLS",
    "POLICIES",
    "TOOL_EFFECT_RULES",
    "classify_tool",
    "lift_real",
    "policy_alphabet_atoms",
    "policy_class",
    "real_corpus_context",
]
