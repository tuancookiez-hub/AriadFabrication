"""Original configurable casing family for a cute two-servo desktop robot.

GrowBot motivated the small two-servo architecture, but this geometry is an
original Ariad design and does not copy or import GrowBot meshes.  The family is
concept-only until exact purchased component measurements replace placeholders.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping


DESIGN_ID = "ariad_two_servo_robot_casing_v0"
DESIGN_SOURCE_VERSION = "0.2.0"


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
class RobotCasingParameters:
    body_width_mm: float
    body_depth_mm: float
    body_height_mm: float
    wall_mm: float
    corner_radius_mm: float
    camera_diameter_mm: float
    camera_center_z_mm: float
    servo_width_mm: float
    servo_depth_mm: float
    servo_axis_body_z_mm: float
    connector_width_mm: float
    connector_height_mm: float
    panel_clearance_mm: float
    panel_thickness_mm: float
    camera_bezel_diameter_mm: float
    camera_bezel_depth_mm: float
    speaker_hole_diameter_mm: float
    speaker_hole_spacing_mm: float
    limb_length_mm: float
    limb_contact_diameter_mm: float
    limb_thickness_mm: float
    servo_axle_diameter_mm: float
    servo_axle_offset_from_end_mm: float
    joint_boss_diameter_mm: float
    joint_boss_depth_mm: float
    joint_running_clearance_mm: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RobotCasingParameters":
        if not isinstance(value, Mapping):
            raise ValueError("robot casing parameters must be an object")
        fields = {
            name: _positive(value.get(name), name)
            for name in cls.__dataclass_fields__
        }
        result = cls(**fields)
        result.validate()
        return result

    def validate(self) -> None:
        if self.wall_mm * 2.0 >= min(
            self.body_width_mm, self.body_depth_mm, self.body_height_mm
        ):
            raise ValueError("wall thickness leaves no enclosed cavity")
        if self.corner_radius_mm >= min(self.body_width_mm, self.body_depth_mm) / 2.0:
            raise ValueError("corner radius is too large for the body")
        camera_radius = self.camera_diameter_mm / 2.0
        if not camera_radius + self.wall_mm < self.camera_center_z_mm < (
            self.body_height_mm - camera_radius - self.wall_mm
        ):
            raise ValueError("camera opening does not fit on the front face")
        if self.servo_width_mm + 2.0 * self.wall_mm > self.body_width_mm:
            raise ValueError("servo envelopes do not fit across the body")
        if self.servo_depth_mm + 2.0 * self.wall_mm > self.body_depth_mm:
            raise ValueError("servo envelopes do not fit inside the body depth")
        if not self.wall_mm < self.servo_axis_body_z_mm < (
            self.body_height_mm / 2.0
        ):
            raise ValueError("side servo axis must remain in the lower half of the body")
        if self.connector_width_mm + 2.0 * self.wall_mm > self.body_depth_mm:
            raise ValueError("connector opening does not fit on the side wall")
        if self.connector_height_mm + 2.0 * self.wall_mm > self.body_height_mm:
            raise ValueError("connector opening does not fit on the side wall")
        if self.panel_clearance_mm >= self.wall_mm:
            raise ValueError("rear-panel clearance must be smaller than the wall")
        if self.panel_thickness_mm > self.wall_mm:
            raise ValueError("rear panel must not be thicker than the body wall")
        if self.camera_bezel_diameter_mm <= self.camera_diameter_mm + 2.0 * self.wall_mm:
            raise ValueError("camera bezel does not retain the body wall")
        if self.camera_bezel_depth_mm > self.wall_mm:
            raise ValueError("camera bezel projection is too deep")
        if self.speaker_hole_spacing_mm * 2.0 + self.speaker_hole_diameter_mm > (
            self.body_width_mm / 2.0
        ):
            raise ValueError("speaker grille does not fit on the front face")
        if self.limb_thickness_mm >= self.body_width_mm / 2.0:
            raise ValueError("side limbs are too thick for the body")
        if self.limb_contact_diameter_mm > self.body_depth_mm:
            raise ValueError("limb contact diameter is larger than the body depth")
        if self.limb_length_mm <= self.limb_contact_diameter_mm:
            raise ValueError("limb length must exceed its rounded contact diameter")
        axle_radius = self.servo_axle_diameter_mm / 2.0
        contact_radius = self.limb_contact_diameter_mm / 2.0
        if not axle_radius + self.wall_mm < self.servo_axle_offset_from_end_mm < (
            contact_radius - axle_radius
        ):
            raise ValueError("servo axle opening does not fit inside the rounded limb end")
        if self.joint_boss_diameter_mm <= self.servo_axle_diameter_mm + 2.0 * self.wall_mm:
            raise ValueError("joint boss does not retain the requested wall")
        if self.joint_boss_diameter_mm > self.limb_contact_diameter_mm:
            raise ValueError("joint boss is larger than the limb contact end")
        boss_radius = self.joint_boss_diameter_mm / 2.0
        if not boss_radius <= self.servo_axis_body_z_mm <= (
            self.body_height_mm - boss_radius
        ):
            raise ValueError("joint boss extends beyond the body height")
        if self.joint_boss_depth_mm > self.limb_thickness_mm:
            raise ValueError("joint boss projection is deeper than the limb")
        if self.joint_running_clearance_mm >= self.wall_mm:
            raise ValueError("joint running clearance must be smaller than the body wall")

    def to_dict(self) -> dict[str, float | str]:
        return {"design_id": DESIGN_ID, **self.__dict__}


def build_parts(values: Mapping[str, Any] | RobotCasingParameters):
    """Return the nine separate prototype solids from the assembly plan.

    Purchased-component interfaces remain provisional until their exact
    mechanical drawings or measurements are frozen into the parameter set.
    """

    import cadquery as cq

    p = values if isinstance(values, RobotCasingParameters) else RobotCasingParameters.from_mapping(values)
    p.validate()
    overrun = 1.0

    outer = cq.Workplane("XY").box(
        p.body_width_mm,
        p.body_depth_mm,
        p.body_height_mm,
        centered=(True, False, False),
    )
    # Round the four vertical silhouette edges while preserving the exact
    # component envelope and flat assembly faces.
    outer = outer.edges("|Z").fillet(p.corner_radius_mm)
    inner = (
        cq.Workplane("XY")
        .box(
            p.body_width_mm - 2.0 * p.wall_mm,
            p.body_depth_mm - p.wall_mm + overrun,
            p.body_height_mm - 2.0 * p.wall_mm,
            centered=(True, False, False),
        )
        .translate((0.0, p.wall_mm, p.wall_mm))
    )
    body = outer.cut(inner)

    camera = cq.Solid.makeCylinder(
        p.camera_diameter_mm / 2.0,
        p.wall_mm + 2.0 * overrun,
        cq.Vector(0.0, -overrun, p.camera_center_z_mm),
        cq.Vector(0.0, 1.0, 0.0),
    )
    body = body.cut(cq.Workplane(obj=camera))

    bezel_outer = cq.Solid.makeCylinder(
        p.camera_bezel_diameter_mm / 2.0,
        p.camera_bezel_depth_mm,
        cq.Vector(0.0, -p.camera_bezel_depth_mm, p.camera_center_z_mm),
        cq.Vector(0.0, 1.0, 0.0),
    )
    bezel_inner = cq.Solid.makeCylinder(
        p.camera_diameter_mm / 2.0,
        p.camera_bezel_depth_mm,
        cq.Vector(0.0, -p.camera_bezel_depth_mm, p.camera_center_z_mm),
        cq.Vector(0.0, 1.0, 0.0),
    )
    camera_bezel = cq.Workplane(obj=bezel_outer.cut(bezel_inner)).clean()

    speaker_z = p.body_height_mm * 0.35
    speaker_points = (
        (-p.speaker_hole_spacing_mm, speaker_z),
        (0.0, speaker_z - p.speaker_hole_spacing_mm),
        (p.speaker_hole_spacing_mm, speaker_z),
    )
    for x, z in speaker_points:
        speaker_hole = cq.Solid.makeCylinder(
            p.speaker_hole_diameter_mm / 2.0,
            p.wall_mm + 2.0 * overrun,
            cq.Vector(x, -overrun, z),
            cq.Vector(0.0, 1.0, 0.0),
        )
        body = body.cut(cq.Workplane(obj=speaker_hole))

    side_axle = cq.Solid.makeCylinder(
        p.servo_axle_diameter_mm / 2.0,
        p.body_width_mm + 2.0 * overrun,
        cq.Vector(
            -p.body_width_mm / 2.0 - overrun,
            p.body_depth_mm / 2.0,
            p.servo_axis_body_z_mm,
        ),
        cq.Vector(1.0, 0.0, 0.0),
    )
    body = body.cut(cq.Workplane(obj=side_axle))
    for side in (-1.0, 1.0):
        start_x = side * p.body_width_mm / 2.0
        direction = cq.Vector(side, 0.0, 0.0)
        boss_outer = cq.Solid.makeCylinder(
            p.joint_boss_diameter_mm / 2.0,
            p.joint_boss_depth_mm,
            cq.Vector(start_x, p.body_depth_mm / 2.0, p.servo_axis_body_z_mm),
            direction,
        )
        boss_inner = cq.Solid.makeCylinder(
            p.servo_axle_diameter_mm / 2.0,
            p.joint_boss_depth_mm,
            cq.Vector(start_x, p.body_depth_mm / 2.0, p.servo_axis_body_z_mm),
            direction,
        )
        body = body.union(cq.Workplane(obj=boss_outer.cut(boss_inner)))

    connector = (
        cq.Workplane("XY")
        .box(
            p.wall_mm + 2.0 * overrun,
            p.connector_width_mm,
            p.connector_height_mm,
            centered=(False, True, True),
        )
        .translate(
            (
                p.body_width_mm / 2.0 - p.wall_mm - overrun,
                p.body_depth_mm / 2.0,
                p.body_height_mm * 0.35,
            )
        )
    )
    body = body.cut(connector).clean()

    panel_width = p.body_width_mm - 2.0 * (p.wall_mm + p.panel_clearance_mm)
    panel_height = p.body_height_mm - 2.0 * (p.wall_mm + p.panel_clearance_mm)
    service_panel = cq.Workplane("XY").box(
        panel_width,
        p.panel_thickness_mm,
        panel_height,
        centered=(True, False, False),
    )
    service_panel = service_panel.edges("|Y").fillet(min(p.corner_radius_mm / 2.0, 3.0)).clean()

    # The tray and carrier are deliberately independent: the tray establishes
    # the structural body interface, while the carrier can be revised around
    # electronics without changing the cosmetic shell.
    tray_width = p.body_width_mm - 4.0 * p.wall_mm
    tray_depth = p.body_depth_mm - 3.0 * p.wall_mm
    electronics_tray = (
        cq.Workplane("XY")
        .box(tray_width, tray_depth, p.panel_thickness_mm, centered=(True, True, False))
        .edges("|Z")
        .fillet(2.0)
        .clean()
    )
    carrier_width = min(68.0, tray_width - 4.0)
    carrier_depth = min(32.0, tray_depth - 4.0)
    electronics_carrier = (
        cq.Workplane("XY")
        .box(carrier_width, carrier_depth, p.panel_thickness_mm, centered=(True, True, False))
        .edges("|Z")
        .fillet(1.5)
    )
    for x in (-carrier_width / 2.0 + 3.5, carrier_width / 2.0 - 3.5):
        for y in (-carrier_depth / 2.0 + 3.5, carrier_depth / 2.0 - 3.5):
            post = cq.Workplane("XY").center(x, y).circle(3.0).extrude(4.0)
            hole = cq.Workplane("XY").center(x, y).circle(1.4).extrude(5.0)
            electronics_carrier = electronics_carrier.union(post).cut(hole)
    electronics_carrier = electronics_carrier.clean()

    contact_radius = p.limb_contact_diameter_mm / 2.0
    straight_length = p.limb_length_mm - p.limb_contact_diameter_mm
    limb_center = (
        cq.Workplane("XY")
        .box(
            p.limb_thickness_mm,
            p.limb_contact_diameter_mm,
            straight_length,
            centered=(True, True, False),
        )
        .translate((0.0, 0.0, contact_radius))
    )
    lower_end = cq.Solid.makeCylinder(
        contact_radius,
        p.limb_thickness_mm,
        cq.Vector(-p.limb_thickness_mm / 2.0, 0.0, contact_radius),
        cq.Vector(1.0, 0.0, 0.0),
    )
    upper_center_z = p.limb_length_mm - contact_radius
    upper_end = cq.Solid.makeCylinder(
        contact_radius,
        p.limb_thickness_mm,
        cq.Vector(-p.limb_thickness_mm / 2.0, 0.0, upper_center_z),
        cq.Vector(1.0, 0.0, 0.0),
    )
    limb = (
        limb_center
        .union(cq.Workplane(obj=lower_end))
        .union(cq.Workplane(obj=upper_end))
        .clean()
    )
    axle_center_z = p.limb_length_mm - p.servo_axle_offset_from_end_mm
    axle = cq.Solid.makeCylinder(
        p.servo_axle_diameter_mm / 2.0,
        p.limb_thickness_mm + 2.0 * overrun,
        cq.Vector(-p.limb_thickness_mm / 2.0 - overrun, 0.0, axle_center_z),
        cq.Vector(1.0, 0.0, 0.0),
    )
    limb = limb.cut(cq.Workplane(obj=axle)).clean()

    adapter_outer = cq.Solid.makeCylinder(p.joint_boss_diameter_mm / 2.0, p.panel_thickness_mm)
    adapter_bore = cq.Solid.makeCylinder(2.4, p.panel_thickness_mm)
    servo_adapter = cq.Workplane(obj=adapter_outer.cut(adapter_bore)).clean()

    parts = {
        "front_shell": body,
        "electronics_tray": electronics_tray,
        "service_panel": service_panel,
        "left_limb": limb,
        "right_limb": limb,
        "left_servo_adapter": servo_adapter,
        "right_servo_adapter": servo_adapter,
        "camera_bezel": camera_bezel,
        "electronics_carrier": electronics_carrier,
    }
    for name, part in parts.items():
        if len(part.solids().vals()) != 1 or not part.val().isValid():
            raise ValueError(f"{name} did not produce one valid solid")
    return parts


def assembly_offsets(p: RobotCasingParameters) -> dict[str, tuple[float, float, float]]:
    """Return the approved neutral-pose offsets without asserting motion evidence."""

    body_z = p.limb_length_mm - p.servo_axle_offset_from_end_mm - p.servo_axis_body_z_mm
    side_x = (
        p.body_width_mm / 2.0
        + p.joint_boss_depth_mm
        + p.joint_running_clearance_mm
        + p.limb_thickness_mm / 2.0
    )
    return {
        "body_shell": (0.0, 0.0, body_z),
        "rear_panel": (
            0.0,
            p.body_depth_mm,
            body_z + p.wall_mm + p.panel_clearance_mm,
        ),
        "left_limb": (-side_x, p.body_depth_mm / 2.0, 0.0),
        "right_limb": (side_x, p.body_depth_mm / 2.0, 0.0),
    }
