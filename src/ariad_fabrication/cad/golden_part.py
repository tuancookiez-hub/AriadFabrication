"""Golden Part parameter extraction and registered provider boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Mapping

from ..domain import PartSpec
from .golden_part_design import DESIGN_ID, build_model


PROVIDER_ID = DESIGN_ID


def _feature(spec: PartSpec, feature_id: str):
    matches = [item for item in spec.features if item.feature_id == feature_id]
    if len(matches) != 1:
        raise ValueError(f"PartSpec must contain exactly one {feature_id!r} feature")
    return matches[0]


def _dimension(feature: Any, name: str) -> float:
    if name not in feature.dimensions_mm:
        raise ValueError(f"feature {feature.feature_id!r} is missing dimension {name!r}")
    return float(feature.dimensions_mm[name])


def parameters_from_spec(
    spec: PartSpec,
    expected: Mapping[str, Any],
) -> dict[str, Any]:
    """Create the complete, recorded parameter set used by the CAD source."""

    spec.assert_ready_for_design()
    if spec.part_type != "split_stake_electronics_clamp":
        raise ValueError(f"provider {PROVIDER_ID!r} does not support {spec.part_type!r}")

    stake_bore = _feature(spec, "stake_bore")
    clamp_wall = _feature(spec, "clamp_wall")
    split_gap = _feature(spec, "split_gap")
    plate = _feature(spec, "mounting_plate")
    mounting_holes = _feature(spec, "m3_mounting_holes")
    cable_channel = _feature(spec, "cable_channel")
    fillets = _feature(spec, "transition_fillets")
    measurements = expected.get("expected_measurements_mm", {})
    if not isinstance(measurements, Mapping):
        raise ValueError("expected_measurements_mm must be an object")
    hole_centers = measurements.get("m3_hole_center_z_values", ())
    if (
        not isinstance(hole_centers, Sequence)
        or isinstance(hole_centers, (str, bytes))
        or len(hole_centers) != 2
    ):
        raise ValueError("expected M3 hole centers must contain two Z values")

    parameters = {
        "design_id": PROVIDER_ID,
        "units": "mm",
        "stake_bore_diameter_mm": _dimension(stake_bore, "diameter"),
        "minimum_clamp_wall_mm": _dimension(clamp_wall, "thickness"),
        "body_height_mm": _dimension(plate, "height"),
        "mounting_plate_width_mm": _dimension(plate, "width"),
        "mounting_plate_thickness_mm": _dimension(plate, "thickness"),
        "split_gap_width_mm": _dimension(split_gap, "width"),
        "m3_hole_diameter_mm": _dimension(mounting_holes, "diameter"),
        "m3_lower_hole_z_mm": float(hole_centers[0]),
        "m3_upper_hole_z_mm": float(hole_centers[1]),
        "cable_channel_diameter_mm": _dimension(cable_channel, "diameter"),
        "cable_channel_center_x_mm": float(measurements["cable_channel_center_x"]),
        "cable_channel_center_z_mm": float(measurements["cable_channel_center_z"]),
        "transition_fillet_radius_mm": _dimension(fillets, "radius"),
        "transition_bridge_width_mm": 18.0,
        "transition_bridge_min_y_mm": 8.0,
        "transverse_cutter_start_y_mm": 7.3,
        "cutter_overrun_mm": 0.1,
    }
    expected_spacing = _dimension(mounting_holes, "center_spacing")
    actual_spacing = parameters["m3_upper_hole_z_mm"] - parameters["m3_lower_hole_z_mm"]
    if abs(actual_spacing - expected_spacing) > 1e-9:
        raise ValueError("expected M3 hole centers do not match the PartSpec spacing")
    return parameters


def build(spec: PartSpec, expected: Mapping[str, Any]):
    parameters = parameters_from_spec(spec, expected)
    return build_model(parameters), parameters
