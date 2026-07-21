"""Original configurable casing family for a cute two-servo desktop robot.

GrowBot motivated the small two-servo architecture, but this geometry is an
original Ariad design and does not copy or import GrowBot meshes.  The family is
concept-only until exact purchased component measurements replace placeholders.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping


DESIGN_ID = "ariad_two_servo_robot_component_first_rev_a"
DESIGN_SOURCE_VERSION = "0.4.0"


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
    camera_board_width_mm: float
    camera_board_height_mm: float
    camera_board_thickness_mm: float
    servo_width_mm: float
    servo_depth_mm: float
    servo_height_mm: float
    servo_fit_clearance_mm: float
    servo_axis_body_z_mm: float
    pi_board_length_mm: float
    pi_board_width_mm: float
    pi_board_thickness_mm: float
    pi_hole_spacing_x_mm: float
    pi_hole_spacing_y_mm: float
    pi_mount_hole_diameter_mm: float
    pi_standoff_height_mm: float
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
    interlock_clearance_mm: float
    snap_arm_length_mm: float
    snap_arm_thickness_mm: float
    snap_hook_mm: float
    dovetail_base_width_mm: float
    dovetail_top_width_mm: float
    dovetail_height_mm: float
    carrier_thickness_mm: float
    panel_guide_depth_mm: float
    panel_latch_length_mm: float
    adapter_key_width_mm: float
    adapter_retention_bead_mm: float

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
        if self.servo_height_mm + self.wall_mm >= self.body_height_mm / 2.0:
            raise ValueError("servo envelopes consume too much body height")
        if not self.wall_mm < self.servo_axis_body_z_mm < (
            self.body_height_mm / 2.0
        ):
            raise ValueError("side servo axis must remain in the lower half of the body")
        if self.connector_width_mm + 2.0 * self.wall_mm > self.body_depth_mm:
            raise ValueError("connector opening does not fit on the side wall")
        if self.connector_height_mm + 2.0 * self.wall_mm > self.body_height_mm:
            raise ValueError("connector opening does not fit on the side wall")
        if self.pi_board_length_mm + 2.0 * self.servo_width_mm + 8.0 > (
            self.body_width_mm - 2.0 * self.wall_mm
        ):
            raise ValueError("Pi and both servo envelopes do not fit across the body")
        if self.pi_board_width_mm + 2.0 * self.wall_mm > self.body_depth_mm:
            raise ValueError("Pi envelope does not fit inside the body depth")
        if self.pi_hole_spacing_x_mm >= self.pi_board_length_mm or self.pi_hole_spacing_y_mm >= self.pi_board_width_mm:
            raise ValueError("Pi mounting-hole pattern does not fit the board")
        if self.pi_mount_hole_diameter_mm >= min(
            self.pi_board_length_mm - self.pi_hole_spacing_x_mm,
            self.pi_board_width_mm - self.pi_hole_spacing_y_mm,
        ):
            raise ValueError("Pi mounting holes exceed the board edge margin")
        if self.camera_board_width_mm + 2.0 * self.wall_mm > self.body_width_mm or self.camera_board_height_mm + 2.0 * self.wall_mm > self.body_height_mm:
            raise ValueError("camera board envelope does not fit behind the front face")
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
        if self.interlock_clearance_mm < 0.3 or self.interlock_clearance_mm >= self.wall_mm:
            raise ValueError("interlock clearance must be at least 0.3 mm and smaller than the wall")
        if self.snap_arm_length_mm < 6.0 * self.snap_arm_thickness_mm:
            raise ValueError("snap arms must be long enough to limit root strain")
        if self.snap_arm_thickness_mm < 1.2 or self.snap_arm_thickness_mm >= self.wall_mm:
            raise ValueError("snap arm thickness is outside the supported FDM range")
        if self.snap_hook_mm > self.snap_arm_thickness_mm:
            raise ValueError("snap hook must not exceed snap arm thickness")
        if not self.dovetail_base_width_mm < self.dovetail_top_width_mm:
            raise ValueError("dovetail top must be wider than its base")
        if self.dovetail_height_mm < 4.0 * 0.4:
            raise ValueError("dovetail height must span at least four 0.4 mm nozzle widths")
        if self.carrier_thickness_mm <= self.dovetail_height_mm + 1.0:
            raise ValueError("carrier must retain a roof above its dovetail channels")
        if self.panel_guide_depth_mm <= self.interlock_clearance_mm:
            raise ValueError("panel guides must exceed their interlock clearance")
        if self.panel_latch_length_mm < 6.0 * self.panel_thickness_mm:
            raise ValueError("panel latch must be long enough to flex in its print plane")
        if self.adapter_key_width_mm <= 2.0 * self.interlock_clearance_mm:
            raise ValueError("adapter key must retain printable width after clearance")
        if self.adapter_retention_bead_mm >= self.interlock_clearance_mm * 2.0:
            raise ValueError("adapter retention bead is too aggressive for the generic fit")

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

    camera_mount_diameter = p.camera_diameter_mm + 2.0 * p.wall_mm
    camera = cq.Solid.makeCylinder(
        camera_mount_diameter / 2.0,
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
    # An annular collar gives the bezel a replaceable, tool-less press fit.
    # Its generic clearance remains a calibration target, not a proven fit.
    collar_outer_diameter = camera_mount_diameter - 2.0 * p.interlock_clearance_mm
    collar_outer = cq.Solid.makeCylinder(
        collar_outer_diameter / 2.0,
        p.wall_mm + 1.0,
        cq.Vector(0.0, -1.0, p.camera_center_z_mm),
        cq.Vector(0.0, 1.0, 0.0),
    )
    collar_inner = cq.Solid.makeCylinder(
        p.camera_diameter_mm / 2.0,
        p.wall_mm + 1.0,
        cq.Vector(0.0, -1.0, p.camera_center_z_mm),
        cq.Vector(0.0, 1.0, 0.0),
    )
    collar = cq.Workplane(obj=collar_outer.cut(collar_inner))
    camera_bezel = camera_bezel.union(collar).clean()
    # The visible ring continues into a rectangular rear frame sized for the
    # selected 25 x 24 mm OV5647-family reservation.  It locates the camera
    # PCB against the shell rather than pretending the lens alone is a mount.
    camera_frame_outer = (
        cq.Workplane("XY")
        .box(
            p.camera_board_width_mm + 4.0,
            2.4,
            p.camera_board_height_mm + 4.0,
            centered=(True, False, True),
        )
        .translate((0.0, p.wall_mm, p.camera_center_z_mm))
    )
    camera_frame_window = (
        cq.Workplane("XY")
        .box(
            p.camera_diameter_mm + 2.0,
            2.8,
            p.camera_diameter_mm + 2.0,
            centered=(True, False, True),
        )
        .translate((0.0, p.wall_mm - 0.2, p.camera_center_z_mm))
    )
    camera_bezel = camera_bezel.union(camera_frame_outer.cut(camera_frame_window)).clean()

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
    body = body.cut(connector)

    # The horizontal tray slides in from the open rear.  Planar cantilever
    # hooks printed in XY engage these two side-wall windows.
    tray_slot_y = p.body_depth_mm - 9.0
    tray_slot_z = p.wall_mm + p.panel_thickness_mm / 2.0
    for side in (-1.0, 1.0):
        slot = (
            cq.Workplane("XY")
            .box(
                p.wall_mm + 2.0 * overrun,
                7.0,
                p.panel_thickness_mm + 2.0 * p.interlock_clearance_mm,
                centered=(True, True, True),
            )
            .translate((side * (p.body_width_mm / 2.0), tray_slot_y, tray_slot_z))
        )
        body = body.cut(slot)

    # Rear vertical channels receive the service-panel guide tongues.  A
    # central top pocket receives the panel's releasable flex latch.
    panel_width = p.body_width_mm - 2.0 * (p.wall_mm + p.panel_clearance_mm)
    for side in (-1.0, 1.0):
        guide_channel = (
            cq.Workplane("XY")
            .box(
                p.panel_guide_depth_mm + 2.0 * p.interlock_clearance_mm,
                p.wall_mm + 2.0 * overrun,
                p.body_height_mm - 2.0 * p.wall_mm,
                centered=(True, True, False),
            )
            .translate(
                (
                    side * (panel_width / 2.0 + p.panel_guide_depth_mm / 2.0),
                    p.body_depth_mm - p.wall_mm / 2.0,
                    p.wall_mm,
                )
            )
        )
        body = body.cut(guide_channel)
    latch_pocket = (
        cq.Workplane("XY")
        .box(10.0, p.wall_mm + 2.0 * overrun, 2.0, centered=(True, True, True))
        .translate((0.0, p.body_depth_mm - p.wall_mm / 2.0, p.body_height_mm - p.wall_mm))
    )
    body = body.cut(latch_pocket).clean()

    panel_height = p.body_height_mm - 2.0 * (p.wall_mm + p.panel_clearance_mm)
    service_panel = cq.Workplane("XY").box(
        panel_width,
        p.panel_thickness_mm,
        panel_height,
        centered=(True, False, False),
    )
    service_panel = service_panel.edges("|Y").fillet(min(p.corner_radius_mm / 2.0, 3.0))
    guide_height = panel_height - 2.0 * (p.corner_radius_mm + p.interlock_clearance_mm)
    for side in (-1.0, 1.0):
        guide = (
            cq.Workplane("XY")
            .box(p.panel_guide_depth_mm, p.panel_thickness_mm, guide_height, centered=(True, False, False))
            .translate((side * (panel_width / 2.0 + p.panel_guide_depth_mm / 2.0), 0.0, p.corner_radius_mm))
        )
        service_panel = service_panel.union(guide)
    # Two relief cuts leave one long central tab whose tapered hook can be
    # pressed from outside for repeated service access.
    latch_width = 8.0
    for x in (-latch_width / 2.0 - 0.8, latch_width / 2.0 + 0.8):
        relief = (
            cq.Workplane("XY")
            .box(1.6, p.panel_thickness_mm + 2.0 * overrun, p.panel_latch_length_mm, centered=(True, True, False))
            .translate((x, p.panel_thickness_mm / 2.0, panel_height - p.panel_latch_length_mm))
        )
        service_panel = service_panel.cut(relief)
    panel_hook = (
        cq.Workplane("XY")
        .box(latch_width, p.snap_hook_mm, 1.6, centered=(True, False, False))
        .translate((0.0, -p.snap_hook_mm, panel_height - 2.2))
    )
    service_panel = service_panel.union(panel_hook)
    # Rev A is deliberately tethered.  This rear notch admits a regulated 5 V
    # lead while leaving the service panel removable; it is not a claim that
    # every cable overmould will fit.
    power_notch = (
        cq.Workplane("XY")
        .box(
            p.connector_width_mm,
            p.panel_thickness_mm + 2.0 * overrun,
            p.connector_height_mm,
            centered=(True, True, False),
        )
        .translate((-8.5, p.panel_thickness_mm / 2.0, -overrun))
    )
    service_panel = service_panel.cut(power_notch).clean()

    # The tray and carrier are deliberately independent: the tray establishes
    # the structural body interface, while the carrier can be revised around
    # electronics without changing the cosmetic shell.
    tray_width = (
        p.body_width_mm - 2.0 * p.wall_mm - 2.0 * p.interlock_clearance_mm
    )
    tray_depth = p.body_depth_mm - 3.0 * p.wall_mm
    electronics_tray = (
        cq.Workplane("XY")
        .box(tray_width, tray_depth, p.panel_thickness_mm, centered=(True, True, False))
        .edges("|Z")
        .fillet(2.0)
        .clean()
    )
    # Two manufacturer-envelope servo cradles are structural features of the
    # chassis, not decorative holes in the shell.  Each U-shaped pocket sits
    # on the tray and includes inward lips as provisional serviceable retainers.
    servo_inner_x = p.servo_width_mm + 2.0 * p.servo_fit_clearance_mm
    servo_inner_y = p.servo_depth_mm + 2.0 * p.servo_fit_clearance_mm
    cradle_wall = 1.8
    cradle_height = p.servo_height_mm * 0.72
    servo_center_x = tray_width / 2.0 - cradle_wall - servo_inner_x / 2.0 - 1.0
    for center_x in (-servo_center_x, servo_center_x):
        for side in (-1.0, 1.0):
            wall = (
                cq.Workplane("XY")
                .box(cradle_wall, servo_inner_y + 2.0 * cradle_wall, cradle_height, centered=(True, True, False))
                .translate((center_x + side * (servo_inner_x + cradle_wall) / 2.0, 0.0, p.panel_thickness_mm))
            )
            electronics_tray = electronics_tray.union(wall)
        for side in (-1.0, 1.0):
            end_wall = (
                cq.Workplane("XY")
                .box(servo_inner_x, cradle_wall, 7.0, centered=(True, True, False))
                .translate((center_x, side * (servo_inner_y + cradle_wall) / 2.0, p.panel_thickness_mm))
            )
            electronics_tray = electronics_tray.union(end_wall)
        for side in (-1.0, 1.0):
            lip = (
                cq.Workplane("XY")
                .box(cradle_wall + 1.0, 5.0, 1.6, centered=(True, True, False))
                .translate((
                    center_x + side * (servo_inner_x / 2.0 + cradle_wall / 2.0 - 0.5),
                    0.0,
                    p.panel_thickness_mm + cradle_height - 1.6,
                ))
            )
            electronics_tray = electronics_tray.union(lip)
    # Cut two planar reliefs to create long XY cantilever arms, then add
    # tapered outward hooks.  The arms remain part of the tray at their front
    # roots and flex inward as the tray enters the shell.
    arm_y = tray_depth / 2.0 - p.snap_arm_length_mm / 2.0 - 1.5
    for side in (-1.0, 1.0):
        relief_x = side * (
            tray_width / 2.0 - p.snap_arm_thickness_mm - 1.0
        )
        relief = (
            cq.Workplane("XY")
            .box(2.0, p.snap_arm_length_mm, p.panel_thickness_mm + 2.0 * overrun, centered=(True, True, False))
            .translate((relief_x, arm_y, -overrun))
        )
        electronics_tray = electronics_tray.cut(relief)
        hook = (
            cq.Workplane("XY")
            .box(p.snap_hook_mm, 4.0, p.panel_thickness_mm, centered=(False, True, False))
            .translate(
                (
                    side * tray_width / 2.0,
                    tray_depth / 2.0 - 5.0,
                    0.0,
                )
            )
        )
        if side < 0:
            hook = hook.translate((-p.snap_hook_mm, 0.0, 0.0))
        electronics_tray = electronics_tray.union(hook)

    carrier_width = min(68.0, tray_width - 4.0)
    carrier_depth = min(32.0, tray_depth - 4.0)
    rail_length = carrier_depth - 4.0
    rail_spacing = carrier_width * 0.46

    def dovetail(*, base_width: float, top_width: float, height: float, length: float):
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

    for x in (-rail_spacing / 2.0, rail_spacing / 2.0):
        rail = dovetail(
            base_width=p.dovetail_base_width_mm,
            top_width=p.dovetail_top_width_mm,
            height=p.dovetail_height_mm,
            length=rail_length,
        ).translate((x, 0.0, p.panel_thickness_mm))
        electronics_tray = electronics_tray.union(rail)
    electronics_tray = electronics_tray.clean()

    electronics_carrier = (
        cq.Workplane("XY")
        .box(carrier_width, carrier_depth, p.carrier_thickness_mm, centered=(True, True, False))
        .edges("|Z")
        .fillet(1.5)
    )
    groove_base = p.dovetail_base_width_mm + 2.0 * p.interlock_clearance_mm
    groove_top = p.dovetail_top_width_mm + 2.0 * p.interlock_clearance_mm
    groove_height = p.dovetail_height_mm + p.interlock_clearance_mm
    for x in (-rail_spacing / 2.0, rail_spacing / 2.0):
        groove = dovetail(
            base_width=groove_base,
            top_width=groove_top,
            height=groove_height,
            length=rail_length + 2.0 * p.interlock_clearance_mm,
        ).translate((x, 0.0, -0.05))
        electronics_carrier = electronics_carrier.cut(groove)
    # The Pi carrier uses the official Zero-family 58 x 23 mm hole pattern.
    # Purchased M2.5 nylon hardware is preferred here: tool-less printed-part
    # interfaces do not justify risking an expensive PCB with improvised clips.
    standoff_outer_diameter = 6.0
    for x in (-p.pi_hole_spacing_x_mm / 2.0, p.pi_hole_spacing_x_mm / 2.0):
        for y in (-p.pi_hole_spacing_y_mm / 2.0, p.pi_hole_spacing_y_mm / 2.0):
            standoff = cq.Solid.makeCylinder(
                standoff_outer_diameter / 2.0,
                p.pi_standoff_height_mm,
                cq.Vector(x, y, p.carrier_thickness_mm),
                cq.Vector(0.0, 0.0, 1.0),
            )
            hole = cq.Solid.makeCylinder(
                p.pi_mount_hole_diameter_mm / 2.0,
                p.carrier_thickness_mm + p.pi_standoff_height_mm + 2.0 * overrun,
                cq.Vector(x, y, -overrun),
                cq.Vector(0.0, 0.0, 1.0),
            )
            electronics_carrier = electronics_carrier.union(cq.Workplane(obj=standoff)).cut(cq.Workplane(obj=hole))
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
    limb = limb.cut(cq.Workplane(obj=axle))
    keyway = (
        cq.Workplane("XY")
        .box(
            p.limb_thickness_mm + 2.0 * overrun,
            p.servo_axle_diameter_mm / 2.0 + p.interlock_clearance_mm,
            p.adapter_key_width_mm + 2.0 * p.interlock_clearance_mm,
            centered=(True, False, True),
        )
        .translate((0.0, 0.0, axle_center_z))
    )
    limb = limb.cut(keyway).clean()

    adapter_outer = cq.Solid.makeCylinder(
        p.joint_boss_diameter_mm / 2.0, p.panel_thickness_mm
    )
    # The provisional servo-side bore stops at the disk; the printed limb-side
    # stem remains solid so it can carry torque through the key.
    adapter_bore = cq.Solid.makeCylinder(
        2.4,
        p.panel_thickness_mm + 0.2,
        cq.Vector(0.0, 0.0, -0.1),
        cq.Vector(0.0, 0.0, 1.0),
    )
    stem_diameter = p.servo_axle_diameter_mm - 2.0 * p.interlock_clearance_mm
    stem_length = p.limb_thickness_mm + p.interlock_clearance_mm
    stem = cq.Solid.makeCylinder(
        stem_diameter / 2.0,
        stem_length,
        cq.Vector(0.0, 0.0, p.panel_thickness_mm),
        cq.Vector(0.0, 0.0, 1.0),
    )
    key = (
        cq.Workplane("XY")
        .box(
            stem_diameter / 2.0 + p.interlock_clearance_mm,
            p.adapter_key_width_mm,
            stem_length,
            centered=(False, True, False),
        )
        .translate((0.0, 0.0, p.panel_thickness_mm))
    )
    bead_outer = cq.Solid.makeCylinder(
        (p.servo_axle_diameter_mm + p.adapter_retention_bead_mm) / 2.0,
        1.2,
        cq.Vector(0.0, 0.0, p.panel_thickness_mm + stem_length - 1.2),
        cq.Vector(0.0, 0.0, 1.0),
    )
    servo_adapter = (
        cq.Workplane(obj=adapter_outer)
        .union(cq.Workplane(obj=stem))
        .union(key)
        .union(cq.Workplane(obj=bead_outer))
        .cut(cq.Workplane(obj=adapter_bore))
    )
    # One slot creates two broad compliant fingers. They stay connected at the
    # disk and avoid the four fragile tips produced by a crossed-slot stem.
    slot_start = p.panel_thickness_mm + stem_length - 5.0
    split = (
        cq.Workplane("XY")
        .box(0.7, stem_diameter + 2.0, 6.0, centered=(True, True, False))
        .translate((0.0, 0.0, slot_start))
    )
    servo_adapter = servo_adapter.cut(split)
    servo_adapter = servo_adapter.clean()

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
            raise ValueError(
                f"{name} did not produce one valid solid "
                f"(solids={len(part.solids().vals())}, valid={part.val().isValid()})"
            )
    return parts


def build_component_envelopes(values: Mapping[str, Any] | RobotCasingParameters):
    """Return selected Rev A hardware envelopes in body-local coordinates.

    These solids are layout references, never printable parts. They make the
    component-first constraint inspectable while preserving the distinction
    between manufacturer dimensions and unmeasured supplier details.
    """

    import cadquery as cq

    p = values if isinstance(values, RobotCasingParameters) else RobotCasingParameters.from_mapping(values)
    tray_width = p.body_width_mm - 2.0 * p.wall_mm - 2.0 * p.interlock_clearance_mm
    cradle_wall = 1.8
    servo_inner_x = p.servo_width_mm + 2.0 * p.servo_fit_clearance_mm
    servo_center_x = tray_width / 2.0 - cradle_wall - servo_inner_x / 2.0 - 1.0
    component_floor_z = p.wall_mm + p.panel_thickness_mm
    pi_floor_z = component_floor_z + p.carrier_thickness_mm + p.pi_standoff_height_mm

    pi = (
        cq.Workplane("XY")
        .box(p.pi_board_length_mm, p.pi_board_width_mm, p.pi_board_thickness_mm, centered=(True, True, False))
        .translate((0.0, p.body_depth_mm / 2.0, pi_floor_z))
    )
    for x in (-p.pi_hole_spacing_x_mm / 2.0, p.pi_hole_spacing_x_mm / 2.0):
        for y in (-p.pi_hole_spacing_y_mm / 2.0, p.pi_hole_spacing_y_mm / 2.0):
            pi = pi.cut(cq.Workplane(obj=cq.Solid.makeCylinder(
                p.pi_mount_hole_diameter_mm / 2.0,
                p.pi_board_thickness_mm + 0.4,
                cq.Vector(x, p.body_depth_mm / 2.0 + y, pi_floor_z - 0.2),
                cq.Vector(0.0, 0.0, 1.0),
            )))
    for x, width in ((-9.0, 8.0), (6.0, 7.0)):
        connector = (
            cq.Workplane("XY")
            .box(width, 4.0, 3.2, centered=(True, False, False))
            .translate((x, p.body_depth_mm / 2.0 + p.pi_board_width_mm / 2.0 - 0.2, pi_floor_z))
        )
        pi = pi.union(connector)
    left_servo = (
        cq.Workplane("XY")
        .box(p.servo_width_mm, p.servo_depth_mm, p.servo_height_mm, centered=(True, True, False))
        .translate((-servo_center_x, p.body_depth_mm / 2.0, component_floor_z))
    )
    right_servo = (
        cq.Workplane("XY")
        .box(p.servo_width_mm, p.servo_depth_mm, p.servo_height_mm, centered=(True, True, False))
        .translate((servo_center_x, p.body_depth_mm / 2.0, component_floor_z))
    )
    for side, center_x in ((-1.0, -servo_center_x), (1.0, servo_center_x)):
        flange = (
            cq.Workplane("XY")
            .box(1.8, p.servo_depth_mm + 4.0, 5.0, centered=(True, True, True))
            .translate((
                center_x + side * (p.servo_width_mm / 2.0 - 0.9),
                p.body_depth_mm / 2.0,
                p.servo_axis_body_z_mm,
            ))
        )
        shaft = cq.Solid.makeCylinder(
            2.0,
            2.5,
            cq.Vector(
                center_x + side * p.servo_width_mm / 2.0,
                p.body_depth_mm / 2.0,
                p.servo_axis_body_z_mm,
            ),
            cq.Vector(side, 0.0, 0.0),
        )
        if side < 0:
            left_servo = left_servo.union(flange).union(cq.Workplane(obj=shaft))
        else:
            right_servo = right_servo.union(flange).union(cq.Workplane(obj=shaft))
    camera = (
        cq.Workplane("XY")
        .box(
            p.camera_board_width_mm,
            p.camera_board_thickness_mm,
            p.camera_board_height_mm,
            centered=(True, True, True),
        )
        .translate((0.0, p.wall_mm + 2.4 + p.camera_board_thickness_mm / 2.0, p.camera_center_z_mm))
    )
    camera_lens = cq.Solid.makeCylinder(
        p.camera_diameter_mm / 2.0,
        5.0,
        cq.Vector(0.0, p.wall_mm + 2.4, p.camera_center_z_mm),
        cq.Vector(0.0, -1.0, 0.0),
    )
    camera = camera.union(cq.Workplane(obj=camera_lens))
    return {
        "raspberry_pi_zero_2_w": pi,
        "left_scs0009": left_servo,
        "right_scs0009": right_servo,
        "ov5647_camera_reservation": camera,
    }


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
        "front_shell": (0.0, 0.0, body_z),
        "body_shell": (0.0, 0.0, body_z),
        "electronics_tray": (0.0, p.body_depth_mm / 2.0, body_z + p.wall_mm),
        "electronics_carrier": (
            0.0,
            p.body_depth_mm / 2.0,
            body_z + p.wall_mm + p.panel_thickness_mm,
        ),
        "service_panel": (
            0.0,
            p.body_depth_mm - p.panel_thickness_mm,
            body_z + p.wall_mm + p.panel_clearance_mm,
        ),
        "rear_panel": (
            0.0,
            p.body_depth_mm - p.panel_thickness_mm,
            body_z + p.wall_mm + p.panel_clearance_mm,
        ),
        "camera_bezel": (0.0, 0.0, body_z),
        "left_limb": (-side_x, p.body_depth_mm / 2.0, 0.0),
        "right_limb": (side_x, p.body_depth_mm / 2.0, 0.0),
    }
