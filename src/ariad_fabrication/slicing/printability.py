"""Deterministic profile-specific printability assessment for exact B-rep geometry.

The first implementation is intentionally scoped to the Golden Part benchmark.
It materializes the accepted manufacturing orientation, measures exact OCCT
geometry, and applies a versioned policy.  It does not invoke a slicer and it
does not make physical-print, strength, fit, or safety claims.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import asin, degrees, isclose, isfinite, sqrt
from pathlib import Path
from typing import Any, Mapping

from ..cad.canonical import canonicalize_step
from ..schema_validation import (
    PRINTABILITY_REPORT_SCHEMA,
    validate_persisted_instance,
)
from .profiles import ProfileBundle


VALIDATOR_ID = "ariad_occt_printability_validator"
VALIDATOR_VERSION = "1.0.0"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


def _round(value: float) -> float:
    return round(float(value), 6)


@dataclass(frozen=True)
class PrintabilityCheck:
    check_id: str
    category: str
    description: str
    passed: bool
    actual: Any
    requirement: Any
    remediation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "category": self.category,
            "description": self.description,
            "passed": self.passed,
            "actual": self.actual,
            "requirement": self.requirement,
            "remediation": self.remediation,
        }


@dataclass(frozen=True)
class PrintabilityReport:
    benchmark_id: str
    passed: bool
    checks: tuple[PrintabilityCheck, ...]
    warnings: tuple[dict[str, Any], ...]
    measurements: Mapping[str, Any]
    profile_ids: Mapping[str, str]
    source_geometry: Mapping[str, Any]
    oriented_geometry: Mapping[str, Any]
    tool_versions: Mapping[str, str]
    policy: Mapping[str, Any]
    claim_boundary: str

    @property
    def status(self) -> str:
        if not self.passed:
            return "failed"
        return "passed_with_warnings" if self.warnings else "passed"

    @property
    def evidence_level(self) -> str | None:
        return "R3" if self.passed else None

    @property
    def failed_checks(self) -> tuple[PrintabilityCheck, ...]:
        return tuple(item for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "classification": "deterministic_profile_specific_printability_assessment",
            "benchmark_id": self.benchmark_id,
            "status": self.status,
            "passed": self.passed,
            "evidence_level": self.evidence_level,
            "checks": [item.to_dict() for item in self.checks],
            "warnings": list(self.warnings),
            "measurements": dict(self.measurements),
            "profile_ids": dict(self.profile_ids),
            "source_geometry": dict(self.source_geometry),
            "oriented_geometry": dict(self.oriented_geometry),
            "tool_versions": dict(self.tool_versions),
            "policy": dict(self.policy),
            "claim_boundary": self.claim_boundary,
        }


def _surface_axis(face: Any) -> tuple[float, float, float, float]:
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    cylinder = BRepAdaptor_Surface(face.wrapped).Cylinder()
    direction = cylinder.Axis().Direction()
    return (
        float(direction.X()),
        float(direction.Y()),
        float(direction.Z()),
        float(cylinder.Radius()),
    )


def _triangle_overhang_measurements(
    faces: list[Any],
    *,
    bridge_face_indexes: frozenset[int],
    bed_z_mm: float,
    bed_tolerance_mm: float,
    maximum_angle_degrees: float,
    linear_tolerance_mm: float,
    angular_tolerance_rad: float,
) -> dict[str, float]:
    downward_area = 0.0
    bed_supported_area = 0.0
    bounded_bridge_area = 0.0
    unresolved_steep_area = 0.0
    maximum_downward_angle = 0.0

    for face_index, face in enumerate(faces):
        vertices, triangles = face.tessellate(
            linear_tolerance_mm,
            angular_tolerance_rad,
        )
        for triangle in triangles:
            first, second, third = (vertices[index] for index in triangle)
            ux, uy, uz = second.x - first.x, second.y - first.y, second.z - first.z
            vx, vy, vz = third.x - first.x, third.y - first.y, third.z - first.z
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            magnitude = sqrt(nx * nx + ny * ny + nz * nz)
            if magnitude <= 1e-15:
                continue
            area = magnitude / 2.0
            normalized_z = nz / magnitude
            if normalized_z >= -1e-12:
                continue
            downward_area += area
            angle = degrees(asin(min(1.0, max(0.0, -normalized_z))))
            maximum_downward_angle = max(maximum_downward_angle, angle)
            centroid_z = (first.z + second.z + third.z) / 3.0
            if centroid_z <= bed_z_mm + bed_tolerance_mm:
                bed_supported_area += area
            elif face_index in bridge_face_indexes:
                bounded_bridge_area += area
            elif angle > maximum_angle_degrees + 1e-9:
                unresolved_steep_area += area

    return {
        "downward_facing_area_mm2": _round(downward_area),
        "bed_supported_downward_area_mm2": _round(bed_supported_area),
        "bounded_bridge_downward_area_mm2": _round(bounded_bridge_area),
        "unresolved_steep_overhang_area_mm2": _round(unresolved_steep_area),
        "maximum_downward_angle_degrees_from_vertical": _round(maximum_downward_angle),
    }


def assess_golden_part_printability(
    exact_step_path: Path,
    oriented_step_path: Path,
    *,
    geometry_report: Mapping[str, Any],
    part_spec: Mapping[str, Any],
    profiles: ProfileBundle,
    expected: Mapping[str, Any],
) -> PrintabilityReport:
    """Materialize the selected orientation and evaluate the frozen R3 rules."""

    import cadquery as cq
    import OCP

    exact_step_path = exact_step_path.resolve()
    oriented_step_path = oriented_step_path.resolve()
    if not exact_step_path.is_file():
        raise FileNotFoundError(exact_step_path)
    if oriented_step_path.exists():
        raise FileExistsError(f"oriented geometry is immutable: {oriented_step_path}")
    oriented_step_path.parent.mkdir(parents=True, exist_ok=True)
    profiles.validate()

    if expected.get("schema_version") != "1.0.0":
        raise ValueError("unsupported printability expectation schema")
    if expected.get("target_evidence_level") != "R3":
        raise ValueError("printability expectations must target R3")
    benchmark_id = str(expected.get("benchmark_id", "")).strip()
    if not benchmark_id or geometry_report.get("benchmark_id") != benchmark_id:
        raise ValueError("geometry report and printability benchmark do not match")
    if not geometry_report.get("passed") or geometry_report.get("evidence_level") != "R2":
        raise ValueError("R3 assessment requires a passed R2 geometry report")
    if part_spec.get("status") != "confirmed":
        raise ValueError("R3 assessment requires a confirmed part specification")

    required = _mapping(expected.get("required_profile"), "required_profile")
    rules = _mapping(expected.get("rules"), "rules")
    source = cq.importers.importStep(str(exact_step_path))
    source_solids = source.solids().vals()
    if len(source_solids) != 1 or not source.val().isValid():
        raise ValueError("exact STEP must re-import as one valid solid")
    source_bounds = source.val().BoundingBox()
    translation = (
        -(float(source_bounds.xmin) + float(source_bounds.xmax)) / 2.0,
        -(float(source_bounds.ymin) + float(source_bounds.ymax)) / 2.0,
        -float(source_bounds.zmin),
    )
    oriented = source.translate(translation)
    cq.exporters.export(oriented, str(oriented_step_path))
    canonicalize_step(oriented_step_path)
    materialized = cq.importers.importStep(str(oriented_step_path))
    if len(materialized.solids().vals()) != 1 or not materialized.val().isValid():
        raise ValueError("oriented STEP did not re-import as one valid solid")

    shape = materialized.val()
    bounds = shape.BoundingBox()
    size = (float(bounds.xlen), float(bounds.ylen), float(bounds.zlen))
    printer_size = profiles.printer.build_volume_mm
    bed_minimum = (
        (printer_size[0] - size[0]) / 2.0,
        (printer_size[1] - size[1]) / 2.0,
        0.0,
    )
    bed_maximum = tuple(bed_minimum[index] + size[index] for index in range(3))

    tolerance = _number(rules.get("tessellation_linear_tolerance_mm"), "linear tolerance")
    angular_tolerance = _number(
        rules.get("tessellation_angular_tolerance_rad"),
        "angular tolerance",
    )
    faces = materialized.faces().vals()
    bed_contact_area = 0.0
    bridge_faces: set[int] = set()
    horizontal_holes: list[dict[str, Any]] = []
    vertical_cylinders: list[dict[str, Any]] = []
    for face_index, face in enumerate(faces):
        face_bounds = face.BoundingBox()
        center = face.Center()
        if (
            face.geomType() == "PLANE"
            and float(face_bounds.zlen) <= tolerance
            and abs(float(center.z) - float(bounds.zmin)) <= tolerance
        ):
            bed_contact_area += float(face.Area())
        if face.geomType() != "CYLINDER":
            continue
        axis_x, axis_y, axis_z, radius = _surface_axis(face)
        cylinder = {
            "diameter_mm": _round(2.0 * radius),
            "axis": [_round(axis_x), _round(axis_y), _round(axis_z)],
            "area_mm2": _round(float(face.Area())),
        }
        if abs(axis_z) <= 1e-6:
            bridge_faces.add(face_index)
            horizontal_holes.append(cylinder)
        else:
            vertical_cylinders.append(cylinder)

    maximum_overhang = _number(
        rules.get("maximum_support_free_overhang_degrees_from_vertical"),
        "maximum overhang",
    )
    overhangs = _triangle_overhang_measurements(
        faces,
        bridge_face_indexes=frozenset(bridge_faces),
        bed_z_mm=float(bounds.zmin),
        bed_tolerance_mm=tolerance,
        maximum_angle_degrees=maximum_overhang,
        linear_tolerance_mm=tolerance,
        angular_tolerance_rad=angular_tolerance,
    )

    geometry_measurements = _mapping(geometry_report.get("measurements"), "measurements")
    minimum_wall = min(
        _number(geometry_measurements.get("minimum_clamp_wall"), "minimum clamp wall"),
        _number(
            geometry_measurements.get("mounting_plate_thickness"),
            "mounting plate thickness",
        ),
    )
    minimum_open_feature = min(
        _number(geometry_measurements.get("split_gap_width"), "split gap"),
        _number(geometry_measurements.get("m3_hole_diameter"), "M3 hole"),
        _number(geometry_measurements.get("cable_channel_diameter"), "cable channel"),
    )
    horizontal_spans = sorted(item["diameter_mm"] for item in horizontal_holes)
    maximum_bridge_span = max(horizontal_spans, default=0.0)
    nozzle = profiles.printer.nozzle_diameter_mm
    layer_ratio = profiles.process.layer_height_mm / nozzle
    diametral_clearance = _number(
        geometry_measurements.get("stake_diametral_clearance"),
        "stake clearance",
    )

    checks: list[PrintabilityCheck] = []

    def add(
        check_id: str,
        category: str,
        description: str,
        passed: bool,
        actual: Any,
        requirement: Any,
        remediation: str,
    ) -> None:
        checks.append(
            PrintabilityCheck(
                check_id=check_id,
                category=category,
                description=description,
                passed=bool(passed),
                actual=actual,
                requirement=requirement,
                remediation=remediation,
            )
        )

    add(
        "printer_profile_family",
        "profile",
        "Printer profile family matches the confirmed requirement",
        profiles.printer.profile_family_id == required.get("printer_profile_family_id"),
        profiles.printer.profile_family_id,
        required.get("printer_profile_family_id"),
        "Select the required printer family or create a new immutable revision.",
    )
    profile_pairs = (
        ("printer_profile", profiles.printer.profile_id, required.get("printer_profile_id")),
        ("material_profile", profiles.material.profile_id, required.get("material_profile_id")),
        ("process_profile", profiles.process.profile_id, required.get("process_profile_id")),
        ("orientation_profile", profiles.orientation.orientation_id, required.get("orientation_id")),
    )
    for check_id, actual, requirement in profile_pairs:
        add(
            check_id,
            "profile",
            f"Exact {check_id.replace('_', ' ')} is the frozen M3 selection",
            actual == requirement,
            actual,
            requirement,
            "Use the frozen profile or freeze a superseding benchmark policy.",
        )
    add(
        "material_matches_spec",
        "profile",
        "Material profile matches the confirmed part material",
        profiles.material.material_type == required.get("material_type") == part_spec.get("material"),
        profiles.material.material_type,
        part_spec.get("material"),
        "Resolve the material mismatch before slicing.",
    )
    numeric_profile_checks = (
        (
            "nozzle_diameter",
            profiles.printer.nozzle_diameter_mm,
            required.get("nozzle_diameter_mm"),
            "mm",
        ),
        (
            "layer_height",
            profiles.process.layer_height_mm,
            required.get("layer_height_mm"),
            "mm",
        ),
        (
            "infill_percent",
            profiles.process.infill_percent,
            required.get("infill_percent"),
            "%",
        ),
    )
    for check_id, actual, requirement, unit in numeric_profile_checks:
        expected_number = _number(requirement, check_id)
        add(
            check_id,
            "profile",
            f"{check_id.replace('_', ' ').title()} matches the frozen requirement",
            isclose(actual, expected_number, abs_tol=1e-9),
            {"value": actual, "unit": unit},
            {"value": expected_number, "unit": unit},
            "Use the required process profile or create a new assessed revision.",
        )
    add(
        "support_policy",
        "profile",
        "Generated-support policy matches the frozen requirement",
        profiles.process.support_policy == required.get("support_policy"),
        profiles.process.support_policy,
        required.get("support_policy"),
        "Resolve support policy before slicing.",
    )

    margin_xy = _number(rules.get("build_volume_margin_xy_mm"), "XY margin")
    margin_z = _number(rules.get("build_volume_margin_z_mm"), "Z margin")
    for axis_index, axis in enumerate("xyz"):
        margin = margin_xy if axis != "z" else margin_z
        required_extent = size[axis_index] + (2.0 * margin if axis != "z" else margin)
        add(
            f"build_volume_{axis}",
            "build_volume",
            f"Oriented {axis.upper()} extent fits with the frozen margin",
            required_extent <= printer_size[axis_index] + 1e-9,
            {"part_mm": _round(size[axis_index]), "required_with_margin_mm": _round(required_extent)},
            {"build_volume_mm": printer_size[axis_index], "margin_mm": margin},
            "Choose a larger build volume, revise orientation, or reduce the part envelope.",
        )
    add(
        "on_bed",
        "bed_contact",
        "The materialized orientation places its minimum Z on the bed datum",
        abs(float(bounds.zmin)) <= tolerance,
        _round(float(bounds.zmin)),
        {"bed_z_mm": 0.0, "tolerance_mm": tolerance},
        "Correct the orientation transform and rematerialize geometry.",
    )
    minimum_contact = _number(
        rules.get("minimum_bed_contact_area_mm2"),
        "minimum bed contact area",
    )
    add(
        "bed_contact_area",
        "bed_contact",
        "Exact coplanar bottom-face area meets the digital contact threshold",
        bed_contact_area >= minimum_contact,
        {"area_mm2": _round(bed_contact_area)},
        {"minimum_area_mm2": minimum_contact},
        "Revise orientation or add an intentional adhesion feature for reassessment.",
    )

    minimum_wall_required = nozzle * _number(
        rules.get("minimum_wall_nozzle_multiple"),
        "minimum wall multiple",
    )
    add(
        "minimum_wall_to_nozzle",
        "feature",
        "Measured minimum structural wall meets the nozzle-relative rule",
        minimum_wall >= minimum_wall_required,
        {"wall_mm": _round(minimum_wall), "nozzle_multiple": _round(minimum_wall / nozzle)},
        {"minimum_wall_mm": _round(minimum_wall_required)},
        "Increase the wall or select a compatible nozzle/process profile.",
    )
    minimum_feature_required = nozzle * _number(
        rules.get("minimum_open_feature_nozzle_multiple"),
        "minimum feature multiple",
    )
    add(
        "minimum_open_feature_to_nozzle",
        "feature",
        "Smallest measured hole or gap meets the nozzle-relative rule",
        minimum_open_feature >= minimum_feature_required,
        {
            "feature_mm": _round(minimum_open_feature),
            "nozzle_multiple": _round(minimum_open_feature / nozzle),
        },
        {"minimum_feature_mm": _round(minimum_feature_required)},
        "Enlarge the feature or use a smaller qualified nozzle.",
    )
    maximum_layer_ratio = _number(
        rules.get("maximum_layer_height_nozzle_ratio"),
        "maximum layer-height ratio",
    )
    add(
        "layer_height_to_nozzle",
        "process",
        "Layer height stays within the nozzle-relative policy",
        layer_ratio <= maximum_layer_ratio + 1e-9,
        _round(layer_ratio),
        {"maximum_ratio": maximum_layer_ratio},
        "Reduce layer height or select a larger qualified nozzle.",
    )

    unresolved_area = overhangs["unresolved_steep_overhang_area_mm2"]
    add(
        "unresolved_steep_overhangs",
        "overhang",
        "No steep downward area remains outside bed contact or bounded horizontal holes",
        unresolved_area <= 1e-6,
        {"area_mm2": unresolved_area, "threshold_degrees_from_vertical": maximum_overhang},
        {"maximum_unresolved_area_mm2": 0.0},
        "Revise orientation/geometry or explicitly enable and assess supports.",
    )
    maximum_bridge = _number(
        rules.get("maximum_bounded_internal_bridge_span_mm"),
        "maximum bridge span",
    )
    bridge_passed = bool(horizontal_spans) and maximum_bridge_span <= maximum_bridge + 1e-9
    add(
        "bounded_internal_bridge_spans",
        "bridging",
        "Every horizontal cylindrical hole stays within the frozen bridge-span policy",
        bridge_passed,
        {"count": len(horizontal_spans), "diameters_mm": horizontal_spans},
        {"maximum_span_mm": maximum_bridge},
        "Reorient, reshape hole crowns, split the part, or enable assessed supports.",
    )
    add(
        "support_disabled_risk_gate",
        "support",
        "Disabled supports are consistent with the deterministic overhang and bridge checks",
        profiles.process.support_policy == "disabled"
        and unresolved_area <= 1e-6
        and bridge_passed,
        {
            "support_policy": profiles.process.support_policy,
            "unresolved_overhang_area_mm2": unresolved_area,
            "maximum_bridge_span_mm": maximum_bridge_span,
        },
        "No unresolved steep overhangs and all bounded bridges within policy",
        "Revise the part or freeze a support-enabled process and reassess it.",
    )

    bore_diameter = _number(
        geometry_measurements.get("stake_bore_diameter"),
        "stake bore diameter",
    )
    vertical_bore_present = any(
        abs(item["diameter_mm"] - bore_diameter) <= 1e-5
        and abs(item["axis"][2]) >= 0.99999
        for item in vertical_cylinders
    )
    add(
        "stake_bore_build_axis",
        "orientation",
        "Stake mating bore remains parallel to build Z",
        vertical_bore_present,
        {"bore_diameter_mm": bore_diameter, "parallel_to_build_z": vertical_bore_present},
        "Bore axis parallel to build Z",
        "Restore the preferred orientation or reassess a superseding orientation.",
    )
    minimum_clearance = nozzle * _number(
        rules.get("minimum_elephant_foot_clearance_nozzle_multiple"),
        "minimum elephant-foot clearance multiple",
    )
    add(
        "digital_elephant_foot_clearance",
        "orientation",
        "Nominal diametral mating clearance exceeds the frozen first-layer risk allowance",
        diametral_clearance >= minimum_clearance,
        {"diametral_clearance_mm": diametral_clearance},
        {"minimum_clearance_mm": _round(minimum_clearance)},
        "Increase digital clearance or calibrate and record first-layer compensation.",
    )

    warnings = (
        {
            "code": "printability.generic_profile_uncalibrated",
            "title": "Generic profile is not calibrated",
            "evidence": profiles.printer.claim_boundary,
            "physical_resolution": "Select real hardware and calibrate its printer/material/process profile before R6.",
        },
        {
            "code": "printability.petg_bridging_unmeasured",
            "title": "PETG bridge behavior is digitally screened but physically unknown",
            "evidence": "Three horizontal holes are treated as bounded bridges; the largest exact diameter is "
            f"{maximum_bridge_span:g} mm.",
            "physical_resolution": "Print a material/profile bridge coupon and inspect the horizontal holes.",
        },
        {
            "code": "printability.elephant_foot_unmeasured",
            "title": "First-layer dimensional error is not calibrated",
            "evidence": f"The digital diametral stake clearance is {diametral_clearance:g} mm.",
            "physical_resolution": "Measure a first-layer and bore-clearance coupon before claiming stake fit.",
        },
        {
            "code": "printability.layer_strength_unverified",
            "title": "Layer-direction strength is not established",
            "evidence": "The preferred Z-up orientation is support-conscious, but no FEA or physical load test was performed.",
            "physical_resolution": "Load-test physically printed specimens under the recorded 10 N radial case before a capacity claim.",
        },
        {
            "code": "printability.build_surface_unspecified",
            "title": "PETG build-surface compatibility remains a hardware decision",
            "evidence": "The generic profile does not name a real sheet or release layer.",
            "physical_resolution": "Record the actual build surface and follow its manufacturer guidance before printing PETG.",
        },
    )
    measurements = {
        "source_bounds_mm": {
            "minimum": [_round(source_bounds.xmin), _round(source_bounds.ymin), _round(source_bounds.zmin)],
            "maximum": [_round(source_bounds.xmax), _round(source_bounds.ymax), _round(source_bounds.zmax)],
        },
        "orientation_translation_mm": [_round(item) for item in translation],
        "oriented_size_mm": dict(zip("xyz", (_round(item) for item in size), strict=True)),
        "bed_placement_bounds_mm": {
            "minimum": [_round(item) for item in bed_minimum],
            "maximum": [_round(item) for item in bed_maximum],
        },
        "bed_contact_area_mm2": _round(bed_contact_area),
        "minimum_wall_mm": _round(minimum_wall),
        "minimum_open_feature_mm": _round(minimum_open_feature),
        "horizontal_hole_diameters_mm": horizontal_spans,
        "overhang_analysis": overhangs,
        "stake_diametral_clearance_mm": _round(diametral_clearance),
    }
    passed = all(item.passed for item in checks)
    profile_ids = {
        "printer": profiles.printer.profile_id,
        "printer_family": profiles.printer.profile_family_id,
        "material": profiles.material.profile_id,
        "process": profiles.process.profile_id,
        "orientation": profiles.orientation.orientation_id,
    }
    source_geometry = {
        "filename": exact_step_path.name,
        "checksum_sha256": _sha256(exact_step_path),
        "size_bytes": exact_step_path.stat().st_size,
    }
    oriented_geometry = {
        "filename": oriented_step_path.name,
        "checksum_sha256": _sha256(oriented_step_path),
        "size_bytes": oriented_step_path.stat().st_size,
        "materialization": "identity Z-up orientation, local XY centering, and minimum Z placement",
    }
    return PrintabilityReport(
        benchmark_id=benchmark_id,
        passed=passed,
        checks=tuple(checks),
        warnings=warnings,
        measurements=measurements,
        profile_ids=profile_ids,
        source_geometry=source_geometry,
        oriented_geometry=oriented_geometry,
        tool_versions={
            "validator": VALIDATOR_VERSION,
            "cadquery": str(cq.__version__),
            "ocp": str(OCP.__version__),
        },
        policy={
            "status": expected.get("status"),
            "rules": dict(rules),
            "risk_policy": dict(_mapping(expected.get("risk_policy"), "risk_policy")),
            "policy_notes": list(expected.get("policy_notes", ())),
        },
        claim_boundary=str(expected.get("claim_boundary", "")).strip(),
    )


def write_printability_report(path: Path, report: PrintabilityReport) -> None:
    if path.exists():
        raise FileExistsError(f"printability report is immutable: {path}")
    value = report.to_dict()
    validate_persisted_instance(
        value,
        PRINTABILITY_REPORT_SCHEMA,
        record_name="generated printability report",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
