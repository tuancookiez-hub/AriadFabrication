"""Parametric first-print coupon for Ariad's tool-less FDM interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Sequence

if TYPE_CHECKING:
    import cadquery as cq


DESIGN_ID = "ariad_interlock_calibration_coupon_v1"
DESIGN_SOURCE_VERSION = "0.1.0"


def _numbers(value: object, name: str) -> tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    result = tuple(float(item) for item in value)
    if not result or any(item <= 0.0 for item in result):
        raise ValueError(f"{name} must contain positive values")
    if tuple(sorted(set(result))) != result:
        raise ValueError(f"{name} must be strictly increasing and unique")
    return result


@dataclass(frozen=True)
class InterlockCouponParameters:
    clearance_values_mm: tuple[float, ...]
    hook_engagement_values_mm: tuple[float, ...]
    dovetail_base_width_mm: float
    dovetail_top_width_mm: float
    dovetail_height_mm: float
    gauge_width_mm: float
    gauge_depth_mm: float
    gauge_thickness_mm: float
    rail_length_mm: float
    snap_receiver_width_mm: float
    snap_receiver_depth_mm: float
    snap_floor_mm: float
    snap_wall_mm: float
    snap_key_width_mm: float
    snap_key_length_mm: float
    snap_arm_thickness_mm: float
    snap_arm_length_mm: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "InterlockCouponParameters":
        if value.get("design_id") != DESIGN_ID:
            raise ValueError("unsupported interlock coupon design_id")
        known = {
            "schema_version", "design_id", "clearance_values_mm",
            "hook_engagement_values_mm", "dovetail_base_width_mm",
            "dovetail_top_width_mm", "dovetail_height_mm", "gauge_width_mm",
            "gauge_depth_mm", "gauge_thickness_mm", "rail_length_mm",
            "snap_receiver_width_mm", "snap_receiver_depth_mm", "snap_floor_mm",
            "snap_wall_mm", "snap_key_width_mm", "snap_key_length_mm",
            "snap_arm_thickness_mm", "snap_arm_length_mm", "claim_boundary",
        }
        unknown = set(value) - known
        if unknown:
            raise ValueError(f"unknown interlock coupon parameters: {sorted(unknown)}")
        params = cls(
            clearance_values_mm=_numbers(value.get("clearance_values_mm"), "clearances"),
            hook_engagement_values_mm=_numbers(
                value.get("hook_engagement_values_mm"), "hook engagements"
            ),
            **{
                name: float(value[name])
                for name in (
                    "dovetail_base_width_mm", "dovetail_top_width_mm",
                    "dovetail_height_mm", "gauge_width_mm", "gauge_depth_mm",
                    "gauge_thickness_mm", "rail_length_mm", "snap_receiver_width_mm",
                    "snap_receiver_depth_mm", "snap_floor_mm", "snap_wall_mm",
                    "snap_key_width_mm", "snap_key_length_mm", "snap_arm_thickness_mm",
                    "snap_arm_length_mm",
                )
            },
        )
        params.validate()
        return params

    def validate(self) -> None:
        if len(self.clearance_values_mm) != 5:
            raise ValueError("coupon requires exactly five clearance candidates")
        if len(self.hook_engagement_values_mm) != 3:
            raise ValueError("coupon requires exactly three hook-engagement candidates")
        if self.clearance_values_mm[0] < 0.2 or self.clearance_values_mm[-1] > 0.8:
            raise ValueError("clearance candidates must stay within 0.2 to 0.8 mm")
        if self.dovetail_top_width_mm <= self.dovetail_base_width_mm:
            raise ValueError("dovetail top must be wider than its base")
        if self.gauge_thickness_mm <= self.dovetail_height_mm + self.clearance_values_mm[-1]:
            raise ValueError("gauge roof is too thin above the largest channel")
        minimum_width = len(self.clearance_values_mm) * (
            self.dovetail_top_width_mm + 2.0 * self.clearance_values_mm[-1] + 5.0
        )
        if self.gauge_width_mm < minimum_width:
            raise ValueError("gauge is too narrow to separate all channels")
        if self.rail_length_mm < self.gauge_depth_mm:
            raise ValueError("test rail must pass through the complete gauge")
        if self.snap_arm_length_mm < 6.0 * self.snap_arm_thickness_mm:
            raise ValueError("snap arm must remain long relative to its thickness")
        inner_width = self.snap_receiver_width_mm - 2.0 * self.snap_wall_mm
        if inner_width <= self.snap_key_width_mm:
            raise ValueError("snap receiver must retain sliding side clearance")
        if self.snap_key_length_mm >= self.snap_receiver_depth_mm:
            raise ValueError("snap key must leave a visible removal handle")


def _dovetail(*, base_width: float, top_width: float, height: float, length: float):
    import cadquery as cq

    return (
        cq.Workplane("XZ")
        .polyline(
            (
                (-base_width / 2.0, 0.0),
                (base_width / 2.0, 0.0),
                (top_width / 2.0, height),
                (-top_width / 2.0, height),
            )
        )
        .close()
        .extrude(length / 2.0, both=True)
    )


def build_parts(value: Mapping[str, object]) -> dict[str, cq.Workplane]:
    import cadquery as cq

    p = InterlockCouponParameters.from_mapping(value)
    gauge = cq.Workplane("XY").box(
        p.gauge_width_mm,
        p.gauge_depth_mm,
        p.gauge_thickness_mm,
        centered=(True, True, False),
    )
    spacing = p.gauge_width_mm / (len(p.clearance_values_mm) + 1)
    channel_positions = tuple(
        (index - (len(p.clearance_values_mm) - 1) / 2.0) * spacing
        for index in range(len(p.clearance_values_mm))
    )
    for index, (x, clearance) in enumerate(
        zip(channel_positions, p.clearance_values_mm, strict=True)
    ):
        groove = _dovetail(
            base_width=p.dovetail_base_width_mm + 2.0 * clearance,
            top_width=p.dovetail_top_width_mm + 2.0 * clearance,
            height=p.dovetail_height_mm + clearance,
            length=p.gauge_depth_mm + 0.4,
        ).translate((x, 0.0, -0.05))
        gauge = gauge.cut(groove)
        # One to five shallow top notches identify the channels without relying on fonts.
        for marker in range(index + 1):
            notch = (
                cq.Workplane("XY")
                .box(0.6, 2.0, 0.5, centered=(True, True, False))
                .translate(
                    (
                        x + (marker - index / 2.0) * 1.1,
                        -p.gauge_depth_mm / 2.0 + 2.0,
                        p.gauge_thickness_mm - 0.5,
                    )
                )
            )
            gauge = gauge.cut(notch)
    gauge = gauge.clean()

    rail = _dovetail(
        base_width=p.dovetail_base_width_mm,
        top_width=p.dovetail_top_width_mm,
        height=p.dovetail_height_mm,
        length=p.rail_length_mm,
    )
    handle = (
        cq.Workplane("XY")
        .box(12.0, 6.0, p.gauge_thickness_mm, centered=(True, True, False))
        .translate((0.0, -p.rail_length_mm / 2.0 - 3.0, 0.0))
    )
    rail_key = rail.union(handle).clean()

    receiver = cq.Workplane("XY").box(
        p.snap_receiver_width_mm,
        p.snap_receiver_depth_mm,
        p.snap_floor_mm,
        centered=(True, True, False),
    )
    wall_height = p.snap_floor_mm + 3.0
    for side in (-1.0, 1.0):
        wall = (
            cq.Workplane("XY")
            .box(
                p.snap_wall_mm,
                p.snap_receiver_depth_mm,
                wall_height,
                centered=(True, True, False),
            )
            .translate(
                (
                    side * (p.snap_receiver_width_mm - p.snap_wall_mm) / 2.0,
                    0.0,
                    p.snap_floor_mm,
                )
            )
        )
        receiver = receiver.union(wall)
    back_stop = (
        cq.Workplane("XY")
        .box(
            p.snap_receiver_width_mm,
            p.snap_wall_mm,
            wall_height,
            centered=(True, True, False),
        )
        .translate(
            (
                0.0,
                p.snap_receiver_depth_mm / 2.0 - p.snap_wall_mm / 2.0,
                p.snap_floor_mm,
            )
        )
    )
    receiver = receiver.union(back_stop)
    latch_window = (
        cq.Workplane("XY")
        .box(
            p.snap_wall_mm + 0.4,
            4.0,
            p.snap_floor_mm + 1.0,
            centered=(True, True, False),
        )
        .translate(
            (
                (p.snap_receiver_width_mm - p.snap_wall_mm) / 2.0,
                p.snap_receiver_depth_mm / 2.0 - 5.0,
                p.snap_floor_mm + 0.6,
            )
        )
    )
    snap_receiver = receiver.cut(latch_window).clean()

    parts: dict[str, cq.Workplane] = {
        "dovetail_gauge": gauge,
        "dovetail_key": rail_key,
        "snap_receiver": snap_receiver,
    }
    for engagement in p.hook_engagement_values_mm:
        key = cq.Workplane("XY").box(
            p.snap_key_width_mm,
            p.snap_key_length_mm,
            p.snap_floor_mm,
            centered=(True, True, False),
        )
        arm_center_x = p.snap_key_width_mm / 2.0 - p.snap_arm_thickness_mm / 2.0
        relief = (
            cq.Workplane("XY")
            .box(1.2, p.snap_arm_length_mm, p.snap_floor_mm + 0.4, centered=(True, True, False))
            .translate((arm_center_x - p.snap_arm_thickness_mm / 2.0 - 0.6, 2.0, -0.1))
        )
        key = key.cut(relief)
        hook = (
            cq.Workplane("XY")
            .box(engagement, 3.0, p.snap_floor_mm, centered=(False, True, False))
            .translate((p.snap_key_width_mm / 2.0, 7.0, 0.0))
        )
        key = key.union(hook)
        handle_cut = (
            cq.Workplane("XY")
            .box(4.0, 2.0, 0.7, centered=(True, True, False))
            .translate((0.0, -p.snap_key_length_mm / 2.0 + 2.0, p.snap_floor_mm - 0.7))
        )
        parts[f"snap_key_{engagement:.1f}".replace(".", "_")] = key.cut(handle_cut).clean()

    for name, part in parts.items():
        if len(part.solids().vals()) != 1 or not part.val().isValid():
            raise ValueError(f"{name} did not produce one valid solid")
    return parts
