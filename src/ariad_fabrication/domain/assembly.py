"""Assembly-first fabrication intent contracts.

These records describe decomposition and interfaces.  They do not assert CAD,
printability, simulation, slicing, assembly success, or physical validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Any, Mapping, Sequence

from .spec import BoundingBox


ASSEMBLY_SCHEMA_VERSION = "1.0.0"


class AssemblyStatus(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"


class EnvelopeEvidence(str, Enum):
    PLACEHOLDER = "placeholder"
    MANUFACTURER = "manufacturer"
    MEASURED = "measured"


class InterfaceKind(str, Enum):
    FASTENED = "fastened"
    ROTATING = "rotating"
    REMOVABLE_PANEL = "removable_panel"
    CAPTURED = "captured"
    CLEARANCE = "clearance"


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _string_tuple(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be an array")
    result = tuple(_text(item, name) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must not contain duplicates")
    return result


def _number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not isfinite(number) or number < minimum:
        raise ValueError(f"{name} must be finite and at least {minimum}")
    return number


@dataclass(frozen=True)
class AssemblyPart:
    part_id: str
    name: str
    role: str
    quantity: int
    separately_manufactured: bool
    manufacturing_process: str
    material: str
    notes: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AssemblyPart":
        quantity = value.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ValueError("part quantity must be a positive integer")
        separate = value.get("separately_manufactured")
        if not isinstance(separate, bool):
            raise ValueError("separately_manufactured must be a boolean")
        return cls(
            part_id=_text(value.get("part_id"), "part_id"),
            name=_text(value.get("name"), "part name"),
            role=_text(value.get("role"), "part role"),
            quantity=quantity,
            separately_manufactured=separate,
            manufacturing_process=_text(
                value.get("manufacturing_process"), "manufacturing_process"
            ),
            material=_text(value.get("material"), "part material"),
            notes=_text(value.get("notes", "Not specified"), "part notes"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_id": self.part_id,
            "name": self.name,
            "role": self.role,
            "quantity": self.quantity,
            "separately_manufactured": self.separately_manufactured,
            "manufacturing_process": self.manufacturing_process,
            "material": self.material,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ComponentEnvelope:
    component_id: str
    name: str
    quantity: int
    evidence: EnvelopeEvidence
    dimensions_mm: BoundingBox
    mass_g: float | None
    source: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ComponentEnvelope":
        quantity = value.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ValueError("component quantity must be a positive integer")
        mass = value.get("mass_g")
        return cls(
            component_id=_text(value.get("component_id"), "component_id"),
            name=_text(value.get("name"), "component name"),
            quantity=quantity,
            evidence=EnvelopeEvidence(value.get("evidence")),
            dimensions_mm=BoundingBox.from_mapping(value.get("dimensions_mm")),
            mass_g=None if mass is None else _number(mass, "mass_g", minimum=0.001),
            source=_text(value.get("source"), "component source"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "name": self.name,
            "quantity": self.quantity,
            "evidence": self.evidence.value,
            "dimensions_mm": self.dimensions_mm.to_dict(),
            "mass_g": self.mass_g,
            "source": self.source,
        }


@dataclass(frozen=True)
class AssemblyInterface:
    interface_id: str
    name: str
    kind: InterfaceKind
    participants: tuple[str, ...]
    clearance_mm: float | None
    axis: str | None
    requirements: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AssemblyInterface":
        clearance = value.get("clearance_mm")
        axis = value.get("axis")
        result = cls(
            interface_id=_text(value.get("interface_id"), "interface_id"),
            name=_text(value.get("name"), "interface name"),
            kind=InterfaceKind(value.get("kind")),
            participants=_string_tuple(value.get("participants"), "interface participants"),
            clearance_mm=(
                None
                if clearance is None
                else _number(clearance, "clearance_mm", minimum=0.0)
            ),
            axis=None if axis is None else _text(axis, "interface axis"),
            requirements=_string_tuple(value.get("requirements"), "interface requirements"),
        )
        if len(result.participants) < 2:
            raise ValueError("an interface must contain at least two participants")
        if result.kind is InterfaceKind.ROTATING and result.axis is None:
            raise ValueError("a rotating interface requires an axis")
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface_id": self.interface_id,
            "name": self.name,
            "kind": self.kind.value,
            "participants": list(self.participants),
            "clearance_mm": self.clearance_mm,
            "axis": self.axis,
            "requirements": list(self.requirements),
        }


@dataclass(frozen=True)
class AssemblySpec:
    assembly_id: str
    name: str
    purpose: str
    status: AssemblyStatus
    parts: tuple[AssemblyPart, ...]
    component_envelopes: tuple[ComponentEnvelope, ...]
    interfaces: tuple[AssemblyInterface, ...]
    assembly_constraints: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    claim_boundary: str
    hardware_actions: bool = False
    physical_validation: bool = False
    schema_version: str = ASSEMBLY_SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AssemblySpec":
        if value.get("schema_version") != ASSEMBLY_SCHEMA_VERSION:
            raise ValueError("unsupported assembly schema_version")
        if value.get("hardware_actions") is not False:
            raise ValueError("assembly specifications cannot authorize hardware actions")
        if value.get("physical_validation") is not False:
            raise ValueError("assembly specifications cannot claim physical validation")
        parts = tuple(AssemblyPart.from_mapping(item) for item in value.get("parts", ()))
        components = tuple(
            ComponentEnvelope.from_mapping(item)
            for item in value.get("component_envelopes", ())
        )
        interfaces = tuple(
            AssemblyInterface.from_mapping(item) for item in value.get("interfaces", ())
        )
        if not parts:
            raise ValueError("assembly must contain at least one part")
        result = cls(
            assembly_id=_text(value.get("assembly_id"), "assembly_id"),
            name=_text(value.get("name"), "assembly name"),
            purpose=_text(value.get("purpose"), "assembly purpose"),
            status=AssemblyStatus(value.get("status")),
            parts=parts,
            component_envelopes=components,
            interfaces=interfaces,
            assembly_constraints=_string_tuple(
                value.get("assembly_constraints"), "assembly_constraints"
            ),
            unresolved_questions=_string_tuple(
                value.get("unresolved_questions"), "unresolved_questions"
            ),
            claim_boundary=_text(value.get("claim_boundary"), "claim_boundary"),
        )
        result.validate_references()
        return result

    def validate_references(self) -> None:
        part_ids = tuple(item.part_id for item in self.parts)
        component_ids = tuple(item.component_id for item in self.component_envelopes)
        interface_ids = tuple(item.interface_id for item in self.interfaces)
        for values, label in (
            (part_ids, "part_id"),
            (component_ids, "component_id"),
            (interface_ids, "interface_id"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"assembly contains duplicate {label} values")
        known = {f"part:{item}" for item in part_ids} | {
            f"component:{item}" for item in component_ids
        }
        for interface in self.interfaces:
            unknown = set(interface.participants) - known
            if unknown:
                raise ValueError(
                    f"interface {interface.interface_id!r} has unknown participants: "
                    f"{sorted(unknown)}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "assembly_id": self.assembly_id,
            "name": self.name,
            "purpose": self.purpose,
            "status": self.status.value,
            "parts": [item.to_dict() for item in self.parts],
            "component_envelopes": [item.to_dict() for item in self.component_envelopes],
            "interfaces": [item.to_dict() for item in self.interfaces],
            "assembly_constraints": list(self.assembly_constraints),
            "unresolved_questions": list(self.unresolved_questions),
            "claim_boundary": self.claim_boundary,
            "hardware_actions": self.hardware_actions,
            "physical_validation": self.physical_validation,
        }
