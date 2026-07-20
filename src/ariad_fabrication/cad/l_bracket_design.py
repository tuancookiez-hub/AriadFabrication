"""Editable parametric source for Ariad's bounded L-bracket family.
This module is intentionally not registered for execution yet.  It establishes
the family geometry and input boundary before Ariad grants it R1/R2 evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping


DESIGN_ID = "ariad_l_bracket_v1"
DESIGN_SOURCE_VERSION = "0.1.0"


def _positive(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return number


@dataclass(frozen=True)
class LBracketParameters:
    width_mm: float
    base_depth_mm: float
    upright_height_mm: float
    thickness_mm: float
    hole_diameter_mm: float
    hole_spacing_mm: float
    edge_margin_mm: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LBracketParameters":
        if not isinstance(value, Mapping):
            raise ValueError("L-bracket parameters must be an object")
        parameters = cls(
            width_mm=_positive(value.get("width_mm"), "width_mm"),
            base_depth_mm=_positive(value.get("base_depth_mm"), "base_depth_mm"),
            upright_height_mm=_positive(
                value.get("upright_height_mm"), "upright_height_mm"
            ),
            thickness_mm=_positive(value.get("thickness_mm"), "thickness_mm"),
            hole_diameter_mm=_positive(
                value.get("hole_diameter_mm"), "hole_diameter_mm"
            ),
            hole_spacing_mm=_positive(value.get("hole_spacing_mm"), "hole_spacing_mm"),
            edge_margin_mm=_positive(value.get("edge_margin_mm"), "edge_margin_mm"),
        )
        parameters.validate()
        return parameters

    def validate(self) -> None:
        radius = self.hole_diameter_mm / 2.0
        if self.thickness_mm >= min(self.base_depth_mm, self.upright_height_mm):
            raise ValueError("thickness must be smaller than both bracket legs")
        if self.hole_spacing_mm + 2.0 * (radius + self.edge_margin_mm) > self.width_mm:
            raise ValueError("hole pair does not fit across the bracket width")
        required_leg = 2.0 * (radius + self.edge_margin_mm)
        if self.base_depth_mm < required_leg or self.upright_height_mm < required_leg:
            raise ValueError("holes do not retain the requested edge margin")

    def to_dict(self) -> dict[str, float | str]:
        return {"design_id": DESIGN_ID, **self.__dict__}


def build_model(values: Mapping[str, Any] | LBracketParameters):
    """Build one solid with two holes in each leg using CadQuery."""

    import cadquery as cq

    p = values if isinstance(values, LBracketParameters) else LBracketParameters.from_mapping(values)
    p.validate()

    base = (
        cq.Workplane("XY")
        .box(p.width_mm, p.base_depth_mm, p.thickness_mm, centered=(True, False, False))
    )
    upright = (
        cq.Workplane("XY")
        .box(p.width_mm, p.thickness_mm, p.upright_height_mm, centered=(True, False, False))
    )
    body = base.union(upright).clean()

    x_positions = (-p.hole_spacing_mm / 2.0, p.hole_spacing_mm / 2.0)
    base_y = p.base_depth_mm - p.edge_margin_mm - p.hole_diameter_mm / 2.0
    base_cutters = (
        cq.Workplane("XY")
        .pushPoints([(x, base_y) for x in x_positions])
        .circle(p.hole_diameter_mm / 2.0)
        .extrude(p.thickness_mm)
    )
    body = body.cut(base_cutters)

    upright_z = p.upright_height_mm - p.edge_margin_mm - p.hole_diameter_mm / 2.0
    for x in x_positions:
        cutter = cq.Solid.makeCylinder(
            p.hole_diameter_mm / 2.0,
            p.thickness_mm,
            cq.Vector(x, 0.0, upright_z),
            cq.Vector(0.0, 1.0, 0.0),
        )
        body = body.cut(cq.Workplane(obj=cutter))
    body = body.clean()
    if len(body.solids().vals()) != 1 or not body.val().isValid():
        raise ValueError("L-bracket construction did not produce one valid solid")
    return body
