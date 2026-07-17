"""Untrusted LLM patch proposer for AgentProof-CEGAR (plan §4.5, §6.2).

This wires a real language model into the :class:`~agentproof.cegar.repair.PatchProposer`
injection point. The model is a **search heuristic over the trusted finite edit
grammar** — it selects and parameterizes operators from
:mod:`agentproof.cegar.repair`, it does not author graphs or source. Its output is
**never trusted**: :func:`agentproof.cegar.repair.repair` re-analyzes every proposed
patch and admits it *only* when the independent
:func:`agentproof.cegar.checker.check_certificate` accepts the resulting certificate.
The LLM is therefore strictly **outside the trusted computing base** (§2.2). A
malformed, adversarial, or simply wrong suggestion can at worst cause a missed
repair — never a false certificate.

Provider independence
---------------------
The core (:class:`LLMProposer`, :func:`parse_edit_sequences`, :func:`build_op`,
:func:`render_prompt`) depends only on a ``complete: Callable[[str], str]`` that maps a
prompt to the model's raw text — no SDK, no key, no network. This keeps the module
importable and fully unit-testable offline with a fake ``complete``.
:func:`anthropic_completer` is the thin, lazily-imported adapter that drives Claude via
the official ``anthropic`` SDK (structured JSON output, adaptive thinking); it is used
only when a real model is wanted.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from agentproof.cegar.ir import EffectKind, MayMustGraph
from agentproof.cegar.policy import Policy
from agentproof.cegar.repair import (
    AddAuthPrecondition,
    BoundLoop,
    EditOp,
    InsertApprovalBefore,
    InsertSanitizer,
    InsertTransactionBoundary,
    MoveToLeastPrivilege,
    RepairConfig,
    RepairExit,
    RestrictToolBinding,
    RouteUnknownToApproval,
    StrengthenRouterGuard,
)
from agentproof.cegar.product import Witness

Completer = Callable[[str], str]


# ---------------------------------------------------------------------------
# Operator registry: LLM-facing op name -> builder + human parameter spec
# ---------------------------------------------------------------------------
# Every builder takes the untrusted ``params`` dict and returns a real EditOp, or
# raises. build_op() turns any failure into a dropped candidate. The `spec`
# strings are shown to the model so it emits well-formed params.

def _kind(params: dict[str, Any]) -> EffectKind:
    return EffectKind(str(params["effect"]))


_OP_BUILDERS: dict[str, Callable[[dict[str, Any]], EditOp]] = {
    "insert_approval_before": lambda p: InsertApprovalBefore(_kind(p)),
    "strengthen_router_guard": lambda p: StrengthenRouterGuard(
        (str(p["edge_source"]), str(p["edge_target"])), str(p["guard"])
    ),
    "restrict_tool_binding": lambda p: RestrictToolBinding(str(p["node_id"])),
    "move_to_least_privilege": lambda p: MoveToLeastPrivilege(
        str(p["node_id"]), str(p["principal"])
    ),
    "add_auth_precondition": lambda p: AddAuthPrecondition(
        str(p["node_id"]), str(p["identity"])
    ),
    "insert_sanitizer": lambda p: InsertSanitizer(str(p["source"]), str(p["sink"])),
    "repair_exit": lambda p: RepairExit(str(p["node_id"])),
    "bound_loop": lambda p: BoundLoop(
        (str(p["edge_source"]), str(p["edge_target"])), int(p["k"])
    ),
    "insert_transaction_boundary": lambda p: InsertTransactionBoundary(str(p["node_id"])),
    "route_unknown_to_approval": lambda p: RouteUnknownToApproval(str(p["node_id"])),
}

_OP_SPEC = [
    ("insert_approval_before", 'params: {"effect": one of ' + str([e.value for e in EffectKind])
        + "} — insert a human-approval node before every node with that effect."),
    ("strengthen_router_guard", 'params: {"edge_source", "edge_target", "guard"} — add/strengthen a guard on a routing edge.'),
    ("restrict_tool_binding", 'params: {"node_id"} — remove the tool binding/capability from a node.'),
    ("move_to_least_privilege", 'params: {"node_id", "principal"} — rebind a node to a least-privilege principal.'),
    ("add_auth_precondition", 'params: {"node_id", "identity"} — require an authenticated identity before a node.'),
    ("insert_sanitizer", 'params: {"source", "sink"} — insert a sanitizer between a labeled source and sink node.'),
    ("repair_exit", 'params: {"node_id"} — reconnect a dead-end/bypass node to a proper exit.'),
    ("bound_loop", 'params: {"edge_source", "edge_target", "k"} — bound a loop/retry edge to k iterations.'),
    ("insert_transaction_boundary", 'params: {"node_id"} — insert a preview/commit confirm node around an irreversible node.'),
    ("route_unknown_to_approval", 'params: {"node_id"} — route unresolved/UNKNOWN behavior to approval or deny-by-default.'),
]


def build_op(name: str, params: dict[str, Any]) -> EditOp | None:
    """Build a real :class:`EditOp` from an untrusted ``(name, params)`` pair.

    Returns ``None`` on any problem — unknown op, missing/typed-wrong params —
    so a malformed model suggestion is silently dropped rather than trusted.
    """
    builder = _OP_BUILDERS.get(name)
    if builder is None or not isinstance(params, dict):
        return None
    try:
        return builder(params)
    except (KeyError, ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Parsing the model's (untrusted) reply
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> Any:
    """Best-effort JSON parse of a model reply (tolerates prose / ``` fences)."""
    raw = raw.strip()
    if raw.startswith("```"):
        # strip a ```json ... ``` fence
        raw = raw.split("```", 2)[1] if raw.count("```") >= 2 else raw
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def parse_edit_sequences(raw: str, *, max_candidates: int = 8) -> list[list[EditOp]]:
    """Parse a model reply into candidate edit sequences (untrusted → validated).

    Expects ``{"candidates": [{"edits": [{"op", "params"}, ...]}, ...]}``. Any
    edit that fails :func:`build_op` is dropped; a candidate with no valid edits
    is dropped; at most ``max_candidates`` candidates are returned. Never raises.
    """
    data = _extract_json(raw)
    if not isinstance(data, dict):
        return []
    out: list[list[EditOp]] = []
    for cand in data.get("candidates", []) or []:
        if not isinstance(cand, dict):
            continue
        seq: list[EditOp] = []
        for edit in cand.get("edits", []) or []:
            if not isinstance(edit, dict):
                continue
            op = build_op(str(edit.get("op", "")), edit.get("params", {}) or {})
            if op is not None:
                seq.append(op)
        if seq:
            out.append(seq)
        if len(out) >= max_candidates:
            break
    return out


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _graph_summary(graph: MayMustGraph) -> str:
    lines = [f"name={graph.name} framework={graph.framework} entry={graph.entry_id} exits={list(graph.exit_ids)}"]
    lines.append("nodes:")
    for n in graph.nodes:
        kinds = [sp for sp in n.state_predicates if sp.startswith("kind:")]
        lines.append(
            f"  {n.id}: effect={n.effect.value} tool={n.tool or '-'} "
            f"authority={n.authority or '-'} identity={n.identity or '-'} "
            f"{' '.join(kinds)} conf={n.provenance.confidence}"
            + (f" unsupported={[u.kind.value for u in n.unsupported]}" if n.unsupported else "")
        )
    lines.append("edges:")
    for e in graph.edges:
        lines.append(f"  {e.source}->{e.target} modality={e.modality.value} control={e.control.value}"
                     + (f" guard={e.guard!r}" if e.guard else ""))
    return "\n".join(lines)


def render_prompt(
    graph: MayMustGraph,
    policy: Policy,
    witness: Witness | None,
    config: RepairConfig,
) -> str:
    ops_doc = "\n".join(f"  - {name}: {spec}" for name, spec in _OP_SPEC)
    witness_txt = (
        json.dumps(witness.to_dict(), indent=2)
        if witness is not None
        else "(no counterexample witness available)"
    )
    return f"""You are a program-repair assistant for tool-using agent workflows. A workflow \
(represented as a may/must effect graph) VIOLATES a safety policy. Propose minimal edits, \
drawn ONLY from the finite edit grammar below, that would make it satisfy the policy.

Your suggestions are UNTRUSTED and will be independently re-verified and certificate-checked; \
propose your best candidates and do not worry about proving them — but reference only real node \
and edge ids from the graph, and use at most {config.max_edits} edits per candidate.

EDIT GRAMMAR (op name : params — description):
{ops_doc}

WORKFLOW GRAPH:
{_graph_summary(graph)}

POLICY (JSON):
{json.dumps(policy.to_dict(), indent=2)}

COUNTEREXAMPLE WITNESS (the reachable violation the repair must eliminate):
{witness_txt}

Respond with ONLY a JSON object of this exact shape (no prose, no markdown fence):
{{"candidates": [{{"edits": [{{"op": "<op name>", "params": {{...}}}}], "rationale": "<one line>"}}]}}
Order candidates cheapest-first (fewer edits, fewer added approvals). Propose 1 to 4 diverse candidates."""


# ---------------------------------------------------------------------------
# The proposer
# ---------------------------------------------------------------------------

class LLMProposer:
    """An untrusted LLM patch proposer implementing the ``PatchProposer`` protocol.

    ``complete`` maps a prompt string to the model's raw reply string. A failing
    or nonsensical model never crashes the repair loop — :meth:`propose` returns
    ``[]`` on any error, and malformed edits are dropped during parsing.
    """

    def __init__(self, complete: Completer, *, max_candidates: int = 8) -> None:
        self._complete = complete
        self._max_candidates = max_candidates

    def propose(
        self,
        graph: MayMustGraph,
        policy: Policy,
        witness: Witness | None,
        config: RepairConfig,
    ) -> list[list[EditOp]]:
        try:
            raw = self._complete(render_prompt(graph, policy, witness, config))
        except Exception:
            return []  # an unreliable proposer must never break the repair loop
        return parse_edit_sequences(raw, max_candidates=self._max_candidates)


class CombinedProposer:
    """Union of several proposers (plan §4.5: "solver + LLM + their combination").

    Concatenates each sub-proposer's candidates in order; a sub-proposer that
    raises contributes nothing. The repair loop still verifies every candidate,
    so combining an untrusted LLM with the solver grammar cannot weaken soundness.
    """

    def __init__(self, proposers: list[Any]) -> None:
        self._proposers = list(proposers)

    def propose(
        self,
        graph: MayMustGraph,
        policy: Policy,
        witness: Witness | None,
        config: RepairConfig,
    ) -> list[list[EditOp]]:
        out: list[list[EditOp]] = []
        for p in self._proposers:
            try:
                out.extend(p.propose(graph, policy, witness, config))
            except Exception:
                continue
        return out


# ---------------------------------------------------------------------------
# Anthropic (Claude) adapter — lazily imported, structured JSON output
# ---------------------------------------------------------------------------

# JSON-schema shape for structured output. `params` carries every operator's
# possible fields as optional; build_op selects the ones each op needs.
EDIT_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidates"],
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["edits"],
                "properties": {
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["op", "params"],
                            "properties": {
                                "op": {"type": "string", "enum": list(_OP_BUILDERS)},
                                "params": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": [],
                                    "properties": {
                                        "effect": {"type": "string"},
                                        "node_id": {"type": "string"},
                                        "edge_source": {"type": "string"},
                                        "edge_target": {"type": "string"},
                                        "guard": {"type": "string"},
                                        "principal": {"type": "string"},
                                        "identity": {"type": "string"},
                                        "source": {"type": "string"},
                                        "sink": {"type": "string"},
                                        "k": {"type": "integer"},
                                    },
                                },
                            },
                        },
                    },
                    "rationale": {"type": "string"},
                },
            },
        }
    },
}


def anthropic_completer(
    *,
    client: Any = None,
    model: str = "claude-opus-4-8",
    max_tokens: int = 8192,
) -> Completer:
    """Return a ``complete`` backed by Claude via the official ``anthropic`` SDK.

    Uses adaptive thinking and structured JSON output (``output_config.format``);
    if the API rejects the schema it retries once without it (the prompt still
    fully specifies the JSON shape). Credentials resolve from the environment
    (``ANTHROPIC_API_KEY`` or an ``ant auth login`` profile). ``anthropic`` is
    imported lazily so this module stays importable without the SDK; install it
    with ``pip install "agentproofx[llm]"``.
    """
    state: dict[str, Any] = {"client": client}

    def complete(prompt: str) -> str:
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "anthropic SDK not installed; run `pip install \"agentproofx[llm]\"` "
                "or pass your own `complete` callable to LLMProposer."
            ) from e
        if state["client"] is None:
            state["client"] = anthropic.Anthropic()
        cl = state["client"]
        base = dict(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            resp = cl.messages.create(
                output_config={"format": {"type": "json_schema", "schema": EDIT_PLAN_SCHEMA}},
                **base,
            )
        except anthropic.BadRequestError:  # pragma: no cover - live-API only
            resp = cl.messages.create(**base)
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")

    return complete
