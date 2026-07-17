"""Versioned capability catalog for a local Codex fabrication agent.

This module describes authority; it does not start Codex, execute a tool, open
the network, mutate evidence, or contact hardware. Only ``available`` entries
may be registered with the current Codex client.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


AGENT_TOOL_CONTRACT_VERSION = "1.0.0"


class ToolAvailability(str, Enum):
    AVAILABLE = "available"
    INTERNAL_ONLY = "internal_only"
    BLOCKED = "blocked"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class AgentToolDescriptor:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    availability: ToolAvailability
    mutates_state: bool = False
    hardware_actions: bool = False
    blocked_reason: str | None = None
    contract_version: str = AGENT_TOOL_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != AGENT_TOOL_CONTRACT_VERSION:
            raise ValueError("unsupported agent tool contract version")
        if not self.name.startswith("ariad.") or len(self.name) > 96:
            raise ValueError("agent tool name must use the ariad namespace")
        if not self.description.strip() or len(self.description) > 512:
            raise ValueError("agent tool description is required and bounded")
        object.__setattr__(self, "availability", ToolAvailability(self.availability))
        if self.hardware_actions is not False:
            raise ValueError("Codex-facing Ariad tools cannot enable hardware actions")
        schema = dict(self.input_schema)
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            raise ValueError("agent tool input schemas must be closed objects")
        if not isinstance(schema.get("properties"), dict):
            raise ValueError("agent tool input schemas require properties")
        required = schema.get("required")
        if not isinstance(required, list) or set(required) != set(schema["properties"]):
            raise ValueError("every agent tool input field must be required")
        object.__setattr__(self, "input_schema", _freeze(schema))
        if self.availability is ToolAvailability.AVAILABLE and self.blocked_reason is not None:
            raise ValueError("available tools cannot have a blocked reason")
        if self.availability is not ToolAvailability.AVAILABLE and not self.blocked_reason:
            raise ValueError("non-available tools require a blocked reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "name": self.name,
            "description": self.description,
            "input_schema": _thaw(self.input_schema),
            "availability": self.availability.value,
            "mutates_state": self.mutates_state,
            "hardware_actions": False,
            "blocked_reason": self.blocked_reason,
        }


def _closed(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def current_agent_tool_catalog() -> tuple[AgentToolDescriptor, ...]:
    """Return the complete current catalog, including visibly unavailable tools."""

    return (
        AgentToolDescriptor(
            name="ariad.capture_idea",
            description="Capture one bounded fabrication idea without persistence or execution.",
            input_schema=_closed({"prompt": {"type": "string", "minLength": 1, "maxLength": 16384}}),
            availability=ToolAvailability.AVAILABLE,
        ),
        AgentToolDescriptor(
            name="ariad.list_evidence",
            description="List a bounded page of persisted or fixture fabrication revisions.",
            input_schema=_closed(
                {
                    "offset": {"type": "integer", "minimum": 0, "maximum": 500},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                }
            ),
            availability=ToolAvailability.AVAILABLE,
        ),
        AgentToolDescriptor(
            name="ariad.read_evidence",
            description="Read one validated persisted fabrication revision by closed identifiers.",
            input_schema=_closed(
                {
                    "job_id": {"type": "string", "minLength": 1, "maxLength": 128},
                    "revision_id": {"type": "string", "minLength": 1, "maxLength": 128},
                }
            ),
            availability=ToolAvailability.AVAILABLE,
        ),
        AgentToolDescriptor(
            name="ariad.run_registered_target",
            description="Request the sealed Golden Part R2 or R4 digital evidence target.",
            input_schema=_closed(
                {
                    "target": {"type": "string", "enum": ["golden_part_r2", "golden_part_r4"]},
                    "idempotency_key": {"type": "string", "minLength": 16, "maxLength": 128},
                }
            ),
            availability=ToolAvailability.INTERNAL_ONLY,
            mutates_state=True,
            blocked_reason="OS filesystem/network isolation and authenticated publication are incomplete.",
        ),
        AgentToolDescriptor(
            name="ariad.cancel_execution",
            description="Request cancellation of one Ariad-controlled digital execution.",
            input_schema=_closed(
                {"request_id": {"type": "string", "minLength": 1, "maxLength": 128}}
            ),
            availability=ToolAvailability.INTERNAL_ONLY,
            mutates_state=True,
            blocked_reason="No authenticated Codex/browser control surface exists yet.",
        ),
        AgentToolDescriptor(
            name="ariad.submit_cad_source",
            description="Submit editable generated CAD source for isolated Ariad validation.",
            input_schema=_closed(
                {
                    "project_id": {"type": "string", "minLength": 1, "maxLength": 128},
                    "source": {"type": "string", "minLength": 1, "maxLength": 262144},
                }
            ),
            availability=ToolAvailability.BLOCKED,
            mutates_state=True,
            blocked_reason="Arbitrary generated CAD does not yet have an enforceable isolated workspace.",
        ),
    )


def exposed_codex_tools() -> tuple[AgentToolDescriptor, ...]:
    """Return only tools safe to register with the current local Codex client."""

    return tuple(
        item
        for item in current_agent_tool_catalog()
        if item.availability is ToolAvailability.AVAILABLE
    )


__all__ = [
    "AGENT_TOOL_CONTRACT_VERSION",
    "AgentToolDescriptor",
    "ToolAvailability",
    "current_agent_tool_catalog",
    "exposed_codex_tools",
]
