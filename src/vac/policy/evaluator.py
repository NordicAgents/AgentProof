"""Deterministic predicate evaluation for policy checks."""

from __future__ import annotations

from typing import Any, Mapping


class PolicyEvaluationError(ValueError):
    """Raised when predicates are malformed."""


Predicate = bool | Mapping[str, Any]


def evaluate_predicate(predicate: Predicate, context: Mapping[str, Any]) -> bool:
    """Evaluate a small deterministic predicate DSL."""
    if isinstance(predicate, bool):
        return predicate
    if not isinstance(predicate, Mapping):
        raise PolicyEvaluationError("predicate must be bool or mapping")

    op = predicate.get("op")
    if not isinstance(op, str):
        raise PolicyEvaluationError("predicate missing string op")

    if op in {"and", "or"}:
        args = predicate.get("args", [])
        if not isinstance(args, list):
            raise PolicyEvaluationError("logical args must be list")
        values = [evaluate_predicate(arg, context) for arg in args]
        return all(values) if op == "and" else any(values)

    if op == "not":
        return not evaluate_predicate(predicate.get("arg", False), context)

    left = _resolve(predicate.get("left"), context)
    right = _resolve(predicate.get("right"), context)

    if op == "eq":
        return left == right
    if op == "ne":
        return left != right
    if op == "lt":
        return left < right
    if op == "le":
        return left <= right
    if op == "gt":
        return left > right
    if op == "ge":
        return left >= right
    if op == "in":
        return left in right
    if op == "contains":
        return right in left

    raise PolicyEvaluationError(f"unsupported op: {op}")


def evaluate_budget(
    *,
    max_calls: int,
    used_calls: int,
    max_cost: float,
    used_cost: float,
    estimated_cost: float,
    additional_rule: Predicate | None = None,
) -> bool:
    """Evaluate built-in and optional policy-defined budget constraints."""
    if used_calls + 1 > max_calls:
        return False
    if used_cost + estimated_cost > max_cost:
        return False

    if additional_rule is None:
        return True

    return evaluate_predicate(
        additional_rule,
        {
            "max_calls": max_calls,
            "used_calls": used_calls,
            "max_cost": max_cost,
            "used_cost": used_cost,
            "estimated_cost": estimated_cost,
        },
    )


def _resolve(node: Any, context: Mapping[str, Any]) -> Any:
    if isinstance(node, Mapping) and "var" in node:
        name = node["var"]
        if not isinstance(name, str):
            raise PolicyEvaluationError("var reference must be a string")
        return context.get(name)
    return node
