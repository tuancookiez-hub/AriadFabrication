"""Editable parametric source for the OpenGrow Golden Part.

This file intentionally depends only on CadQuery plus the standard library so
the copied ``design.py`` artifact can rebuild the exact solid from the recorded
``parameters.json`` file.
"""

from __future__ import annotations

import argparse
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping


DESIGN_ID = "opengrow_stake_electronics_clamp_v1"
DESIGN_SOURCE_VERSION = "1.0.0"


def _number(parameters: Mapping[str, Any], key: str) -> float:
    if key not in parameters or isinstance(parameters[key], bool):
        raise ValueError(f"missing numeric CAD parameter {key!r}")
    number = float(parameters[key])
    if not isfinite(number) or number <= 0:
        raise ValueError(f"CAD parameter {key!r} must be finite and greater than zero")
    return number


def build_model(parameters: Mapping[str, Any]):
    """Build and return one CadQuery Workplane containing the clamp solid."""

    import cadquery as cq

    bore_diameter = _number(parameters, "stake_bore_diameter_mm")
    minimum_wall = _number(parameters, "minimum_clamp_wall_mm")
    height = _number(parameters, "body_height_mm")
    plate_width = _number(parameters, "mounting_plate_width_mm")
    plate_thickness = _number(parameters, "mounting_plate_thickness_mm")
    split_gap = _number(parameters, "split_gap_width_mm")
    m3_hole_diameter = _number(parameters, "m3_hole_diameter_mm")
    lower_hole_z = _number(parameters, "m3_lower_hole_z_mm")
    upper_hole_z = _number(parameters, "m3_upper_hole_z_mm")
    cable_diameter = _number(parameters, "cable_channel_diameter_mm")
    cable_x = _number(parameters, "cable_channel_center_x_mm")
    cable_z = _number(parameters, "cable_channel_center_z_mm")
    fillet_radius = _number(parameters, "transition_fillet_radius_mm")
    bridge_width = _number(parameters, "transition_bridge_width_mm")
    bridge_min_y = _number(parameters, "transition_bridge_min_y_mm")
    transverse_cutter_start_y = _number(parameters, "transverse_cutter_start_y_mm")
    cutter_overrun = _number(parameters, "cutter_overrun_mm")

    bore_radius = bore_diameter / 2.0
    outer_radius = bore_radius + minimum_wall
    plate_min_y = outer_radius
    plate_center_y = plate_min_y + plate_thickness / 2.0
    bridge_max_y = plate_center_y
    bridge_height = bridge_max_y - bridge_min_y
    if bridge_height <= fillet_radius:
        raise ValueError("transition bridge does not leave enough material for the fillets")
    if not 0 < lower_hole_z < upper_hole_z < height:
        raise ValueError("M3 hole centers must be ordered inside the body height")
    if cable_x + cable_diameter / 2.0 >= plate_width / 2.0:
        raise ValueError("cable channel does not fit inside the mounting plate width")
    if not cable_diameter / 2.0 < cable_z < height - cable_diameter / 2.0:
        raise ValueError("cable channel does not fit inside the body height")

    sleeve = cq.Workplane("XY").circle(outer_radius).extrude(height)
    plate = (
        cq.Workplane("XY")
        .rect(plate_width, plate_thickness)
        .extrude(height)
        .translate((0.0, plate_center_y, 0.0))
    )
    bridge = (
        cq.Workplane("XY")
        .rect(bridge_width, bridge_height)
        .extrude(height)
        .translate((0.0, (bridge_min_y + bridge_max_y) / 2.0, 0.0))
    )
    body = sleeve.union(bridge).union(plate).clean()

    transition_edges = [
        edge
        for edge in body.edges("|Z").vals()
        if abs(abs(edge.Center().x) - bridge_width / 2.0) <= 1e-7
        and abs(edge.Center().y - plate_min_y) <= 1e-7
    ]
    if len(transition_edges) != 2:
        raise ValueError(
            f"expected two transition edges before filleting, found {len(transition_edges)}"
        )
    body = body.newObject(transition_edges).fillet(fillet_radius).clean()

    bore = (
        cq.Workplane("XY")
        .workplane(offset=-cutter_overrun)
        .circle(bore_radius)
        .extrude(height + 2.0 * cutter_overrun)
    )
    split_depth = minimum_wall + 2.0 * cutter_overrun
    split = (
        cq.Workplane("XY")
        .workplane(offset=-cutter_overrun)
        .box(
            split_gap,
            split_depth,
            height + 2.0 * cutter_overrun,
            centered=(True, False, False),
        )
        .translate((0.0, -outer_radius - cutter_overrun, 0.0))
    )
    body = body.cut(bore).cut(split)

    plate_outer_y = plate_center_y + plate_thickness / 2.0
    if transverse_cutter_start_y >= bridge_min_y:
        raise ValueError("transverse cutters must begin behind the transition bridge face")
    cutter_length = plate_outer_y + cutter_overrun - transverse_cutter_start_y

    def y_axis_cylinder(x: float, z: float, diameter: float):
        solid = cq.Solid.makeCylinder(
            diameter / 2.0,
            cutter_length,
            cq.Vector(x, transverse_cutter_start_y, z),
            cq.Vector(0.0, 1.0, 0.0),
        )
        return cq.Workplane(obj=solid)

    for hole_z in (lower_hole_z, upper_hole_z):
        body = body.cut(y_axis_cylinder(0.0, hole_z, m3_hole_diameter))
    body = body.cut(y_axis_cylinder(cable_x, cable_z, cable_diameter)).clean()

    if len(body.solids().vals()) != 1 or not body.val().isValid():
        raise ValueError("Golden Part construction did not produce one valid solid")
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the OpenGrow Golden Part")
    parser.add_argument("--parameters", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    import cadquery as cq

    parameters = json.loads(args.parameters.read_text(encoding="utf-8"))
    model = build_model(parameters)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(model, str(args.output_dir / "part.step"))
    cq.exporters.export(model, str(args.output_dir / "compatibility.stl"))
    cq.exporters.export(model, str(args.output_dir / "part.3mf"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
