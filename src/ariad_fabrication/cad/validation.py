"""Deterministic OCCT geometry checks for the Golden Part."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class GeometryCheck:
    check_id: str
    description: str
    passed: bool
    expected: Any
    actual: Any
    tolerance_mm: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "description": self.description,
            "passed": self.passed,
            "expected": self.expected,
            "actual": self.actual,
            "tolerance_mm": self.tolerance_mm,
        }


@dataclass(frozen=True)
class GeometryValidationReport:
    benchmark_id: str
    passed: bool
    evidence_level: str | None
    checks: tuple[GeometryCheck, ...]
    measurements: Mapping[str, Any]
    tool_versions: Mapping[str, str]
    claim_boundary: str

    @property
    def failed_checks(self) -> tuple[GeometryCheck, ...]:
        return tuple(item for item in self.checks if not item.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "benchmark_id": self.benchmark_id,
            "passed": self.passed,
            "evidence_level": self.evidence_level,
            "checks": [item.to_dict() for item in self.checks],
            "measurements": dict(self.measurements),
            "tool_versions": dict(self.tool_versions),
            "claim_boundary": self.claim_boundary,
        }


def _near(actual: float, expected: float, tolerance: float) -> bool:
    return abs(float(actual) - float(expected)) <= float(tolerance) + 1e-9


def validate_golden_part_geometry(
    model: Any,
    expected: Mapping[str, Any],
    *,
    tool_versions: Mapping[str, str],
) -> GeometryValidationReport:
    """Measure the imported STEP model and evaluate every frozen M2 target."""

    from OCP.BRepAdaptor import BRepAdaptor_Surface

    shape = model.val() if hasattr(model, "val") else model
    faces = model.faces().vals() if hasattr(model, "faces") else []
    solids = model.solids().vals() if hasattr(model, "solids") else [shape]
    expected_counts = expected["expected_counts"]
    target = expected["expected_measurements_mm"]
    tolerance = float(expected["default_dimensional_tolerance_mm"])
    checks: list[GeometryCheck] = []
    measurements: dict[str, Any] = {}

    def exact(check_id: str, description: str, actual: Any, expected_value: Any) -> None:
        checks.append(
            GeometryCheck(
                check_id=check_id,
                description=description,
                passed=actual == expected_value,
                expected=expected_value,
                actual=actual,
            )
        )

    def dimensional(
        check_id: str,
        description: str,
        actual: float,
        expected_value: float,
        check_tolerance: float = tolerance,
    ) -> None:
        checks.append(
            GeometryCheck(
                check_id=check_id,
                description=description,
                passed=_near(actual, expected_value, check_tolerance),
                expected=expected_value,
                actual=round(float(actual), 6),
                tolerance_mm=check_tolerance,
            )
        )

    kernel_valid = bool(shape.isValid())
    solid_count = len(solids)
    exact("kernel_valid", "OCCT reports a valid shape", kernel_valid, True)
    exact(
        "solid_body_count",
        "The design contains exactly one solid body",
        solid_count,
        int(expected_counts["solid_bodies"]),
    )
    measurements["kernel_valid"] = kernel_valid
    measurements["solid_body_count"] = solid_count
    measurements["volume_mm3"] = round(float(shape.Volume()), 6)
    checks.append(
        GeometryCheck(
            check_id="positive_volume",
            description="The solid has positive volume",
            passed=shape.Volume() > 0,
            expected="> 0 mm3",
            actual=measurements["volume_mm3"],
        )
    )

    bounds = shape.BoundingBox()
    actual_envelope = {
        "x": round(float(bounds.xlen), 6),
        "y": round(float(bounds.ylen), 6),
        "z": round(float(bounds.zlen), 6),
    }
    measurements["design_envelope"] = actual_envelope
    for axis in ("x", "y", "z"):
        dimensional(
            f"envelope_{axis}",
            f"Overall {axis.upper()} envelope matches the frozen target",
            actual_envelope[axis],
            float(target["design_envelope"][axis]),
        )

    cylinders: list[dict[str, Any]] = []
    for face in faces:
        if face.geomType() != "CYLINDER":
            continue
        cylinder = BRepAdaptor_Surface(face.wrapped).Cylinder()
        direction = cylinder.Axis().Direction()
        location = cylinder.Axis().Location()
        components = {
            "X": abs(float(direction.X())),
            "Y": abs(float(direction.Y())),
            "Z": abs(float(direction.Z())),
        }
        axis = max(components, key=components.get)
        cylinders.append(
            {
                "radius": float(cylinder.Radius()),
                "axis": axis,
                "x": float(location.X()),
                "y": float(location.Y()),
                "z": float(location.Z()),
            }
        )

    def cylinder_matches(axis: str, radius: float) -> list[dict[str, Any]]:
        return [
            item
            for item in cylinders
            if item["axis"] == axis and _near(item["radius"], radius, 1e-5)
        ]

    bore_radius = float(target["stake_bore_diameter"]) / 2.0
    bore_surfaces = cylinder_matches("Z", bore_radius)
    exact(
        "stake_bore_count",
        "One cylindrical stake mating bore exists",
        len(bore_surfaces),
        int(expected_counts["cylindrical_mating_bores"]),
    )
    actual_bore_diameter = 2.0 * bore_surfaces[0]["radius"] if bore_surfaces else 0.0
    measurements["stake_bore_diameter"] = round(actual_bore_diameter, 6)
    dimensional(
        "stake_bore_diameter",
        "Stake bore diameter matches the controlled-clearance target",
        actual_bore_diameter,
        float(target["stake_bore_diameter"]),
    )
    actual_diametral_clearance = actual_bore_diameter - float(
        target["stake_nominal_diameter"]
    )
    measurements["stake_diametral_clearance"] = round(actual_diametral_clearance, 6)
    dimensional(
        "stake_diametral_clearance",
        "Stake bore minus nominal stake diameter matches the clearance target",
        actual_diametral_clearance,
        float(target["stake_diametral_clearance"]),
    )

    outer_radius_target = bore_radius + float(target["minimum_clamp_wall"])
    outer_surfaces = cylinder_matches("Z", outer_radius_target)
    actual_outer_radius = (
        sum(item["radius"] for item in outer_surfaces) / len(outer_surfaces)
        if outer_surfaces
        else 0.0
    )
    actual_wall = actual_outer_radius - actual_bore_diameter / 2.0
    measurements["minimum_clamp_wall"] = round(actual_wall, 6)
    checks.append(
        GeometryCheck(
            check_id="outer_clamp_surface_present",
            description="The split clamp retains its expected outer cylindrical surface",
            passed=len(outer_surfaces) >= 2,
            expected=">= 2 split cylindrical surface segments",
            actual=len(outer_surfaces),
        )
    )
    dimensional(
        "minimum_clamp_wall",
        "Radial wall derived from measured bore and outer cylinders",
        actual_wall,
        float(target["minimum_clamp_wall"]),
    )

    m3_radius = float(target["m3_hole_diameter"]) / 2.0
    m3_surfaces = sorted(cylinder_matches("Y", m3_radius), key=lambda item: item["z"])
    exact(
        "m3_hole_count",
        "Two M3 through-hole cylindrical surfaces exist",
        len(m3_surfaces),
        int(expected_counts["m3_through_holes"]),
    )
    m3_diameter = 2.0 * m3_surfaces[0]["radius"] if m3_surfaces else 0.0
    m3_centers = [round(float(item["z"]), 6) for item in m3_surfaces]
    m3_spacing = m3_centers[-1] - m3_centers[0] if len(m3_centers) == 2 else 0.0
    measurements["m3_hole_diameter"] = round(m3_diameter, 6)
    measurements["m3_hole_center_z_values"] = m3_centers
    measurements["m3_hole_center_spacing_z"] = round(m3_spacing, 6)
    dimensional(
        "m3_hole_diameter",
        "M3 through-hole diameter matches the target",
        m3_diameter,
        float(target["m3_hole_diameter"]),
    )
    dimensional(
        "m3_hole_center_spacing",
        "M3 through-hole center spacing matches the target",
        m3_spacing,
        float(target["m3_hole_center_spacing_z"]),
    )
    expected_centers = [float(item) for item in target["m3_hole_center_z_values"]]
    exact(
        "m3_hole_centers",
        "M3 through-hole Z centers match the frozen positions",
        m3_centers,
        expected_centers,
    )

    cable_radius = float(target["cable_channel_diameter"]) / 2.0
    cable_surfaces = [
        item
        for item in cylinder_matches("Y", cable_radius)
        if _near(item["x"], float(target["cable_channel_center_x"]), 1e-5)
        and _near(item["z"], float(target["cable_channel_center_z"]), 1e-5)
    ]
    exact(
        "cable_channel_count",
        "One cable-routing cylindrical feature exists",
        len(cable_surfaces),
        int(expected_counts["cable_routing_features"]),
    )
    actual_cable_diameter = 2.0 * cable_surfaces[0]["radius"] if cable_surfaces else 0.0
    measurements["cable_channel_diameter"] = round(actual_cable_diameter, 6)
    measurements["cable_channel_center_x"] = (
        round(cable_surfaces[0]["x"], 6) if cable_surfaces else None
    )
    measurements["cable_channel_center_z"] = (
        round(cable_surfaces[0]["z"], 6) if cable_surfaces else None
    )
    dimensional(
        "cable_channel_diameter",
        "Cable-routing hole diameter matches the target",
        actual_cable_diameter,
        float(target["cable_channel_diameter"]),
    )

    fillet_radius = float(target["transition_fillet_radius"])
    fillet_surfaces = cylinder_matches("Z", fillet_radius)
    exact(
        "transition_fillet_count",
        "Two Z-axis transition fillet surfaces connect the plate and clamp",
        len(fillet_surfaces),
        int(expected_counts["transition_fillets"]),
    )
    actual_fillet_radius = fillet_surfaces[0]["radius"] if fillet_surfaces else 0.0
    measurements["transition_fillet_radius"] = round(actual_fillet_radius, 6)
    dimensional(
        "transition_fillet_radius",
        "Transition fillet radius matches the target",
        actual_fillet_radius,
        fillet_radius,
    )

    mounting_faces = []
    for face in faces:
        if face.geomType() != "PLANE":
            continue
        center = face.Center()
        normal = face.normalAt(center)
        face_bounds = face.BoundingBox()
        if (
            normal.y > 0.99999
            and _near(center.y, bounds.ymax, 1e-5)
            and _near(face_bounds.xlen, float(target["mounting_plate_width"]), tolerance)
            and _near(face_bounds.zlen, float(target["mounting_plate_height"]), tolerance)
        ):
            mounting_faces.append(face)
    exact(
        "mounting_interface_count",
        "One planar electronics mounting interface spans the plate",
        len(mounting_faces),
        int(expected_counts["flat_mounting_interfaces"]),
    )
    plate_thickness = float(bounds.ymax) - actual_outer_radius
    measurements["mounting_plate_width"] = round(float(bounds.xlen), 6)
    measurements["mounting_plate_height"] = round(float(bounds.zlen), 6)
    measurements["mounting_plate_thickness"] = round(plate_thickness, 6)
    dimensional(
        "mounting_plate_width",
        "Mounting interface width matches the target",
        float(bounds.xlen),
        float(target["mounting_plate_width"]),
    )
    dimensional(
        "mounting_plate_height",
        "Mounting interface height matches the target",
        float(bounds.zlen),
        float(target["mounting_plate_height"]),
    )
    dimensional(
        "mounting_plate_thickness",
        "Mounting plate thickness matches the target",
        plate_thickness,
        float(target["mounting_plate_thickness"]),
    )

    split_half_width = float(target["split_gap_width"]) / 2.0
    split_faces = []
    for face in faces:
        if face.geomType() != "PLANE":
            continue
        center = face.Center()
        normal = face.normalAt(center)
        face_bounds = face.BoundingBox()
        if (
            abs(normal.x) > 0.99999
            and _near(abs(center.x), split_half_width, 1e-5)
            and _near(face_bounds.zlen, float(target["mounting_plate_height"]), tolerance)
        ):
            split_faces.append(face)
    actual_split_width = (
        abs(split_faces[0].Center().x - split_faces[1].Center().x)
        if len(split_faces) == 2
        else 0.0
    )
    measurements["split_gap_width"] = round(actual_split_width, 6)
    exact(
        "split_gap_face_count",
        "The open clamp split has two opposing planar walls",
        len(split_faces),
        2,
    )
    dimensional(
        "split_gap_width",
        "Clamp split width matches the target",
        actual_split_width,
        float(target["split_gap_width"]),
    )

    passed = all(item.passed for item in checks)
    return GeometryValidationReport(
        benchmark_id=str(expected["benchmark_id"]),
        passed=passed,
        evidence_level="R2" if passed else None,
        checks=tuple(checks),
        measurements=measurements,
        tool_versions=dict(tool_versions),
        claim_boundary=str(expected["claim_boundary"]),
    )
