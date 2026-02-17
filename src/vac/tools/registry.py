"""Tool registration API and guardrails for invocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


class ToolRegistryError(RuntimeError):
    """Base tool registry exception."""


class UnregisteredToolError(ToolRegistryError):
    """Raised when a tool invocation references an unknown tool."""


class ToolPermissionError(ToolRegistryError):
    """Raised when required permission scope is missing."""


class ToolSchemaError(ToolRegistryError):
    """Raised when tool input schema validation fails."""


@dataclass(frozen=True)
class ToolDefinition:
    """Registered tool wrapper metadata."""

    name: str
    input_schema: Mapping[str, type | tuple[type, ...]]
    permission_scope: str
    cost_model: Callable[[Mapping[str, Any]], float]
    wrapper: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    sandbox_profile: str = "standard"


class ToolRegistry:
    """In-memory deterministic tool registry."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if not definition.name.strip():
            raise ToolRegistryError("tool name must be non-empty")
        if definition.name in self._tools:
            raise ToolRegistryError(f"tool already registered: {definition.name}")
        self._tools[definition.name] = definition

    def is_registered(self, tool_name: str) -> bool:
        return tool_name in self._tools

    def get(self, tool_name: str) -> ToolDefinition:
        try:
            return self._tools[tool_name]
        except KeyError as exc:
            raise UnregisteredToolError(f"unregistered tool: {tool_name}") from exc

    def estimate_cost(self, tool_name: str, payload: Mapping[str, Any]) -> float:
        tool = self.get(tool_name)
        return float(tool.cost_model(payload))

    def validate_input(self, tool_name: str, payload: Mapping[str, Any]) -> None:
        tool = self.get(tool_name)
        for field, expected_type in tool.input_schema.items():
            if field not in payload:
                raise ToolSchemaError(f"missing tool input field: {field}")
            if not isinstance(payload[field], expected_type):
                raise ToolSchemaError(f"invalid type for field {field}: expected {expected_type}")

    def check_permission(self, tool_name: str, permissions: set[str]) -> None:
        tool = self.get(tool_name)
        if tool.permission_scope not in permissions:
            raise ToolPermissionError(
                f"missing permission {tool.permission_scope} for tool {tool_name}"
            )

    def invoke(self, tool_name: str, payload: Mapping[str, Any], permissions: set[str]) -> Mapping[str, Any]:
        """Run registered wrapper only after registration, schema, and permission checks."""
        self.validate_input(tool_name, payload)
        self.check_permission(tool_name, permissions)
        tool = self.get(tool_name)
        result = tool.wrapper(payload)
        if not isinstance(result, Mapping):
            raise ToolRegistryError("tool wrapper must return a mapping")
        return result
