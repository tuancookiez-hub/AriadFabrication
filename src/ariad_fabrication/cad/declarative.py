"""Closed declarative CSG contract and deterministic CadQuery interpreter.

Codex may propose this data contract, but it cannot submit or execute Python.
Every primitive, transform, boolean, count, and dimension is validated before
CadQuery sees it.  The resulting artifacts remain digital geometry only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from math import isfinite
from pathlib import Path
import re
from typing import Any, Mapping

from .glb import export_glb


DECLARATIVE_CAD_CONTRACT_VERSION = "1.0.0"
DECLARATIVE_CAD_INTERPRETER_VERSION = "0.1.0"
MAX_PARTS = 8
MAX_OPERATIONS_PER_PART = 48
MAX_TOTAL_OPERATIONS = 128
MAX_TEXT_ITEMS = 20
MAX_TEXT_CHARS = 512
MAX_DIMENSION_MM = 400.0
MAX_POSITION_MM = 500.0
MAX_ASSEMBLY_SPAN_MM = 800.0
MAX_MANIFEST_BYTES = 512 * 1024
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_GENERATION_ID = re.compile(r"^csg_[0-9a-f]{20}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _closed(value: Mapping[str, Any], names: set[str], label: str) -> None:
    if set(value) != names:
        raise ValueError(f"{label} must contain exactly: {', '.join(sorted(names))}")


def _text(value: Any, label: str, maximum: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{label} must be non-empty bounded text")
    return value.strip()


def _number(value: Any, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be a JSON number")
    result = float(value)
    if not isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return result


def _text_list(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_TEXT_ITEMS:
        raise ValueError(f"{label} must contain at most {MAX_TEXT_ITEMS} items")
    return tuple(_text(item, label) for item in value)


@dataclass(frozen=True)
class CsgOperation:
    operation_id: str
    combine: str
    primitive: str
    size_x_mm: float
    size_y_mm: float
    size_z_mm: float
    radius_mm: float
    radius2_mm: float
    position_x_mm: float
    position_y_mm: float
    position_z_mm: float
    rotation_x_deg: float
    rotation_y_deg: float
    rotation_z_deg: float

    FIELDS = {
        "operation_id", "combine", "primitive", "size_x_mm", "size_y_mm",
        "size_z_mm", "radius_mm", "radius2_mm", "position_x_mm",
        "position_y_mm", "position_z_mm", "rotation_x_deg", "rotation_y_deg",
        "rotation_z_deg",
    }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CsgOperation":
        if not isinstance(value, Mapping):
            raise ValueError("each CSG operation must be an object")
        _closed(value, cls.FIELDS, "CSG operation")
        operation_id = _text(value["operation_id"], "operation_id", 48)
        if not _IDENTIFIER.fullmatch(operation_id):
            raise ValueError("operation_id must be a lowercase identifier")
        combine = value["combine"]
        if combine not in {"base", "union", "cut", "intersect"}:
            raise ValueError("combine must be base, union, cut, or intersect")
        primitive = value["primitive"]
        if primitive not in {"box", "cylinder", "sphere", "cone"}:
            raise ValueError("primitive must be box, cylinder, sphere, or cone")
        result = cls(
            operation_id=operation_id,
            combine=combine,
            primitive=primitive,
            size_x_mm=_number(value["size_x_mm"], "size_x_mm", 0, MAX_DIMENSION_MM),
            size_y_mm=_number(value["size_y_mm"], "size_y_mm", 0, MAX_DIMENSION_MM),
            size_z_mm=_number(value["size_z_mm"], "size_z_mm", 0, MAX_DIMENSION_MM),
            radius_mm=_number(value["radius_mm"], "radius_mm", 0, MAX_DIMENSION_MM / 2),
            radius2_mm=_number(value["radius2_mm"], "radius2_mm", 0, MAX_DIMENSION_MM / 2),
            position_x_mm=_number(value["position_x_mm"], "position_x_mm", -MAX_POSITION_MM, MAX_POSITION_MM),
            position_y_mm=_number(value["position_y_mm"], "position_y_mm", -MAX_POSITION_MM, MAX_POSITION_MM),
            position_z_mm=_number(value["position_z_mm"], "position_z_mm", -MAX_POSITION_MM, MAX_POSITION_MM),
            rotation_x_deg=_number(value["rotation_x_deg"], "rotation_x_deg", -360, 360),
            rotation_y_deg=_number(value["rotation_y_deg"], "rotation_y_deg", -360, 360),
            rotation_z_deg=_number(value["rotation_z_deg"], "rotation_z_deg", -360, 360),
        )
        result.validate_dimensions()
        return result

    def validate_dimensions(self) -> None:
        if self.primitive == "box" and min(self.size_x_mm, self.size_y_mm, self.size_z_mm) <= 0:
            raise ValueError("box operations require positive size_x_mm, size_y_mm, and size_z_mm")
        if self.primitive == "cylinder" and (self.radius_mm <= 0 or self.size_z_mm <= 0):
            raise ValueError("cylinder operations require positive radius_mm and size_z_mm")
        if self.primitive == "sphere" and self.radius_mm <= 0:
            raise ValueError("sphere operations require positive radius_mm")
        if self.primitive == "cone" and (
            self.size_z_mm <= 0 or max(self.radius_mm, self.radius2_mm) <= 0
        ):
            raise ValueError("cone operations require height and at least one positive radius")

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.FIELDS}


@dataclass(frozen=True)
class CsgPart:
    part_id: str
    name: str
    purpose: str
    operations: tuple[CsgOperation, ...]

    FIELDS = {"part_id", "name", "purpose", "operations"}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CsgPart":
        if not isinstance(value, Mapping):
            raise ValueError("each CSG part must be an object")
        _closed(value, cls.FIELDS, "CSG part")
        part_id = _text(value["part_id"], "part_id", 48)
        if not _IDENTIFIER.fullmatch(part_id):
            raise ValueError("part_id must be a lowercase identifier")
        raw_operations = value["operations"]
        if not isinstance(raw_operations, list) or not 1 <= len(raw_operations) <= MAX_OPERATIONS_PER_PART:
            raise ValueError(f"each part requires 1 through {MAX_OPERATIONS_PER_PART} operations")
        operations = tuple(CsgOperation.from_mapping(item) for item in raw_operations)
        if operations[0].combine != "base" or any(item.combine == "base" for item in operations[1:]):
            raise ValueError("each part must have exactly one base operation, listed first")
        operation_ids = [item.operation_id for item in operations]
        if len(set(operation_ids)) != len(operation_ids):
            raise ValueError("operation identifiers must be unique within a part")
        return cls(
            part_id=part_id,
            name=_text(value["name"], "part name", 120),
            purpose=_text(value["purpose"], "part purpose", 512),
            operations=operations,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_id": self.part_id,
            "name": self.name,
            "purpose": self.purpose,
            "operations": [item.to_dict() for item in self.operations],
        }


@dataclass(frozen=True)
class DeclarativeCadDocument:
    title: str
    summary: str
    parts: tuple[CsgPart, ...]
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]
    contract_version: str = DECLARATIVE_CAD_CONTRACT_VERSION

    FIELDS = {"contract_version", "title", "summary", "parts", "assumptions", "warnings"}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DeclarativeCadDocument":
        if not isinstance(value, Mapping):
            raise ValueError("declarative CAD document must be an object")
        _closed(value, cls.FIELDS, "declarative CAD document")
        if value["contract_version"] != DECLARATIVE_CAD_CONTRACT_VERSION:
            raise ValueError("unsupported declarative CAD contract version")
        raw_parts = value["parts"]
        if not isinstance(raw_parts, list) or not 1 <= len(raw_parts) <= MAX_PARTS:
            raise ValueError(f"declarative CAD requires 1 through {MAX_PARTS} parts")
        parts = tuple(CsgPart.from_mapping(item) for item in raw_parts)
        if sum(len(part.operations) for part in parts) > MAX_TOTAL_OPERATIONS:
            raise ValueError(f"declarative CAD exceeds {MAX_TOTAL_OPERATIONS} total operations")
        part_ids = [item.part_id for item in parts]
        if len(set(part_ids)) != len(part_ids):
            raise ValueError("part identifiers must be unique")
        return cls(
            title=_text(value["title"], "document title", 120),
            summary=_text(value["summary"], "document summary", 1000),
            parts=parts,
            assumptions=_text_list(value["assumptions"], "assumptions"),
            warnings=_text_list(value["warnings"], "warnings"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "title": self.title,
            "summary": self.summary,
            "parts": [item.to_dict() for item in self.parts],
            "assumptions": list(self.assumptions),
            "warnings": list(self.warnings),
        }


def declarative_cad_agent_schema() -> dict[str, Any]:
    number = {"type": "number", "minimum": 0, "maximum": MAX_DIMENSION_MM}
    radius = {"type": "number", "minimum": 0, "maximum": MAX_DIMENSION_MM / 2}
    position = {"type": "number", "minimum": -MAX_POSITION_MM, "maximum": MAX_POSITION_MM}
    rotation = {"type": "number", "minimum": -360, "maximum": 360}
    operation_properties = {
        "operation_id": {"type": "string", "pattern": _IDENTIFIER.pattern},
        "combine": {"type": "string", "enum": ["base", "union", "cut", "intersect"]},
        "primitive": {"type": "string", "enum": ["box", "cylinder", "sphere", "cone"]},
        "size_x_mm": number,
        "size_y_mm": number,
        "size_z_mm": number,
        "radius_mm": radius,
        "radius2_mm": radius,
        "position_x_mm": position,
        "position_y_mm": position,
        "position_z_mm": position,
        "rotation_x_deg": rotation,
        "rotation_y_deg": rotation,
        "rotation_z_deg": rotation,
    }
    operation = {
        "type": "object",
        "additionalProperties": False,
        "required": list(operation_properties),
        "properties": operation_properties,
    }
    part_properties = {
        "part_id": {"type": "string", "pattern": _IDENTIFIER.pattern},
        "name": {"type": "string", "minLength": 1, "maxLength": 120},
        "purpose": {"type": "string", "minLength": 1, "maxLength": 512},
        "operations": {"type": "array", "minItems": 1, "maxItems": MAX_OPERATIONS_PER_PART, "items": operation},
    }
    text_items = {
        "type": "array",
        "maxItems": MAX_TEXT_ITEMS,
        "items": {"type": "string", "minLength": 1, "maxLength": MAX_TEXT_CHARS},
    }
    properties = {
        "project_id": {"type": "string", "pattern": "^project_[0-9a-f]{32}$"},
        "contract_version": {"type": "string", "enum": [DECLARATIVE_CAD_CONTRACT_VERSION]},
        "title": {"type": "string", "minLength": 1, "maxLength": 120},
        "summary": {"type": "string", "minLength": 1, "maxLength": 1000},
        "parts": {"type": "array", "minItems": 1, "maxItems": MAX_PARTS, "items": {
            "type": "object", "additionalProperties": False,
            "required": list(part_properties), "properties": part_properties,
        }},
        "assumptions": text_items,
        "warnings": text_items,
    }
    return {"type": "object", "additionalProperties": False, "required": list(properties), "properties": properties}


def _canonical_bytes(document: DeclarativeCadDocument) -> bytes:
    return json.dumps(document.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
        if not 1 <= size <= MAX_MANIFEST_BYTES:
            raise ValueError("Declarative CAD manifest exceeds its size boundary")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Declarative CAD manifest is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("Declarative CAD manifest must be an object")
    return value


def _primitive_shape(operation: CsgOperation, cq: Any) -> Any:
    if operation.primitive == "box":
        shape = cq.Workplane("XY").box(
            operation.size_x_mm, operation.size_y_mm, operation.size_z_mm,
            centered=(True, True, True),
        ).val()
    elif operation.primitive == "cylinder":
        shape = cq.Solid.makeCylinder(
            operation.radius_mm, operation.size_z_mm,
            cq.Vector(0, 0, -operation.size_z_mm / 2.0),
        )
    elif operation.primitive == "sphere":
        shape = cq.Solid.makeSphere(operation.radius_mm)
    else:
        shape = cq.Solid.makeCone(
            operation.radius_mm, operation.radius2_mm, operation.size_z_mm,
            cq.Vector(0, 0, -operation.size_z_mm / 2.0),
        )
    origin = cq.Vector(0, 0, 0)
    for axis, angle in (
        (cq.Vector(1, 0, 0), operation.rotation_x_deg),
        (cq.Vector(0, 1, 0), operation.rotation_y_deg),
        (cq.Vector(0, 0, 1), operation.rotation_z_deg),
    ):
        if angle:
            shape = shape.rotate(origin, axis, angle)
    return shape.translate(cq.Vector(
        operation.position_x_mm, operation.position_y_mm, operation.position_z_mm
    ))


def build_declarative_parts(document: DeclarativeCadDocument) -> dict[str, Any]:
    import cadquery as cq

    built: dict[str, Any] = {}
    for part in document.parts:
        current = None
        for operation in part.operations:
            operand = _primitive_shape(operation, cq)
            if current is None:
                current = operand
            elif operation.combine == "union":
                current = current.fuse(operand)
            elif operation.combine == "cut":
                current = current.cut(operand)
            else:
                current = current.intersect(operand)
            if current is None or current.isNull():
                raise ValueError(f"{part.part_id}/{operation.operation_id} produced empty geometry")
        solids = current.Solids()
        if len(solids) != 1 or not current.isValid():
            raise ValueError(f"{part.part_id} must finish as one kernel-valid solid")
        bounds = current.BoundingBox()
        if max(bounds.xlen, bounds.ylen, bounds.zlen) > MAX_ASSEMBLY_SPAN_MM:
            raise ValueError(f"{part.part_id} exceeds the bounded geometry envelope")
        built[part.part_id] = current
    return built


def generate_declarative_cad(
    document: DeclarativeCadDocument,
    root: Path,
) -> tuple[dict[str, Any], bool]:
    """Interpret a validated document and publish exact digital artifacts."""

    document_bytes = _canonical_bytes(document)
    document_digest = hashlib.sha256(document_bytes).hexdigest()
    generation_digest = hashlib.sha256(
        DECLARATIVE_CAD_INTERPRETER_VERSION.encode("ascii") + b"\0" + document_bytes
    ).hexdigest()
    generation_id = f"csg_{generation_digest[:20]}"
    output = root.expanduser().resolve() / generation_id
    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        manifest = _load_manifest(manifest_path)
        if (
            manifest.get("generation_id") != generation_id
            or manifest.get("document_sha256") != document_digest
            or manifest.get("interpreter_version") != DECLARATIVE_CAD_INTERPRETER_VERSION
            or manifest.get("document") != document.to_dict()
        ):
            raise ValueError("Cached declarative CAD identity does not match the request")
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise ValueError("Cached declarative CAD artifacts are invalid")
        for artifact in artifacts:
            if not isinstance(artifact, dict) or not isinstance(artifact.get("filename"), str):
                raise ValueError("Cached declarative CAD artifact descriptor is invalid")
            declarative_artifact_path(root, generation_id, artifact["filename"])
        return manifest, True
    output.mkdir(parents=True, exist_ok=False)
    try:
        import cadquery as cq
        from cadquery import exporters

        parts = build_declarative_parts(document)
        compound = cq.Compound.makeCompound(list(parts.values()))
        assembly_step = output / "assembly.step"
        assembly_glb = output / "preview.glb"
        exporters.export(compound, str(assembly_step))
        preview = export_glb(
            compound, assembly_glb,
            linear_tolerance_mm=0.1,
            angular_tolerance_rad=0.15,
        )
        artifacts: list[dict[str, Any]] = []
        for role, path, part_id in (
            ("assembly_step", assembly_step, None),
            ("browser_preview", assembly_glb, None),
        ):
            artifacts.append({
                "role": role, "part_id": part_id, "filename": path.name,
                "media_type": "model/step" if path.suffix == ".step" else "model/gltf-binary",
                "size_bytes": path.stat().st_size, "checksum_sha256": _sha256(path),
            })
        part_checks: list[dict[str, Any]] = []
        for part in document.parts:
            shape = parts[part.part_id]
            step_path = output / f"{part.part_id}.step"
            stl_path = output / f"{part.part_id}.stl"
            exporters.export(shape, str(step_path))
            exporters.export(shape, str(stl_path), tolerance=0.1, angularTolerance=0.15)
            for role, path, media_type in (
                ("part_step", step_path, "model/step"),
                ("part_stl", stl_path, "model/stl"),
            ):
                artifacts.append({
                    "role": role, "part_id": part.part_id, "filename": path.name,
                    "media_type": media_type, "size_bytes": path.stat().st_size,
                    "checksum_sha256": _sha256(path),
                })
            bounds = shape.BoundingBox()
            part_checks.append({
                "part_id": part.part_id,
                "kernel_valid": bool(shape.isValid()),
                "solid_count": len(shape.Solids()),
                "bounds_mm": {"x": round(bounds.xlen, 3), "y": round(bounds.ylen, 3), "z": round(bounds.zlen, 3)},
                "operation_count": len(part.operations),
            })
        bounds = compound.BoundingBox()
        manifest: dict[str, Any] = {
            "schema_version": DECLARATIVE_CAD_CONTRACT_VERSION,
            "generation_id": generation_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "document_sha256": document_digest,
            "interpreter_version": DECLARATIVE_CAD_INTERPRETER_VERSION,
            "document": document.to_dict(),
            "checks": {
                "part_count": len(parts),
                "all_parts_kernel_valid": all(item["kernel_valid"] for item in part_checks),
                "all_parts_single_solid": all(item["solid_count"] == 1 for item in part_checks),
                "bounds_mm": {"x": round(bounds.xlen, 3), "y": round(bounds.ylen, 3), "z": round(bounds.zlen, 3)},
                "preview_triangle_count": preview["triangle_count"],
                "parts": part_checks,
            },
            "artifacts": artifacts,
            "evidence_mode": "model_proposed_live_digital_generation",
            "claim_boundary": (
                "Codex proposed a closed declarative CSG document and Ariad generated exact "
                "digital geometry. Semantic correctness, printability, slicing, fit, strength, "
                "safety, and physical success remain unverified."
            ),
            "hardware_actions": False,
            "physical_validation": False,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return manifest, False
    except Exception:
        for path in output.glob("*"):
            if path.is_file():
                path.unlink()
        output.rmdir()
        raise


def declarative_artifact_path(root: Path, generation_id: str, filename: str) -> Path:
    if not _GENERATION_ID.fullmatch(generation_id):
        raise ValueError("Invalid declarative generation identifier")
    directory = (root.expanduser().resolve() / generation_id).resolve()
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Declarative CAD generation not found")
    manifest = _load_manifest(manifest_path)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) > 2 + (2 * MAX_PARTS):
        raise ValueError("Declarative CAD artifact manifest is invalid")
    matches = [item for item in artifacts if isinstance(item, dict) and item.get("filename") == filename]
    if len(matches) != 1:
        raise ValueError("Unsupported declarative CAD artifact")
    path = (directory / filename).resolve()
    if path.parent != directory or not path.is_file():
        raise ValueError("Declarative CAD artifact not found")
    descriptor = matches[0]
    expected_size = descriptor.get("size_bytes")
    expected_checksum = descriptor.get("checksum_sha256")
    if (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size <= 0
        or not isinstance(expected_checksum, str)
        or not _SHA256.fullmatch(expected_checksum)
        or path.stat().st_size != expected_size
        or _sha256(path) != expected_checksum
    ):
        raise ValueError("Declarative CAD artifact failed its content identity check")
    return path


__all__ = [
    "DECLARATIVE_CAD_CONTRACT_VERSION",
    "DECLARATIVE_CAD_INTERPRETER_VERSION",
    "CsgOperation",
    "CsgPart",
    "DeclarativeCadDocument",
    "build_declarative_parts",
    "declarative_artifact_path",
    "declarative_cad_agent_schema",
    "generate_declarative_cad",
]
