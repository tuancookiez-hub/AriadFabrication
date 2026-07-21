import json
from pathlib import Path
import unittest

try:
    import cadquery as cq
except ImportError:
    cq = None

from ariad_fabrication.cad.robot_casing_design import (
    DESIGN_ID,
    RobotCasingParameters,
    assembly_offsets,
    build_parts,
)
from scripts.export_robot_prototype_parts import manufacturing_orientation


ROOT = Path(__file__).resolve().parents[1]


def fixture() -> dict[str, object]:
    return json.loads(
        (ROOT / "benchmarks/robot_casing/parameters.json").read_text(encoding="utf-8")
    )


class RobotCasingParameterTests(unittest.TestCase):
    def test_fixture_has_a_closed_valid_parameter_boundary(self):
        parameters = RobotCasingParameters.from_mapping(fixture())
        self.assertEqual(parameters.to_dict()["design_id"], DESIGN_ID)
        self.assertEqual(parameters.body_width_mm, 86.0)

    def test_rejects_side_servo_axis_outside_lower_body(self):
        values = fixture()
        values["servo_axis_body_z_mm"] = 60.0
        with self.assertRaisesRegex(ValueError, "side servo axis"):
            RobotCasingParameters.from_mapping(values)

    def test_rejects_camera_opening_outside_front_face(self):
        values = fixture()
        values["camera_center_z_mm"] = 4.0
        with self.assertRaisesRegex(ValueError, "camera opening does not fit"):
            RobotCasingParameters.from_mapping(values)

    def test_rejects_clearance_below_generic_fdm_starting_boundary(self):
        values = fixture()
        values["interlock_clearance_mm"] = 0.2
        with self.assertRaisesRegex(ValueError, "interlock clearance"):
            RobotCasingParameters.from_mapping(values)

    def test_rejects_short_brittle_snap_arm_proportion(self):
        values = fixture()
        values["snap_arm_length_mm"] = 8.0
        with self.assertRaisesRegex(ValueError, "snap arm"):
            RobotCasingParameters.from_mapping(values)

    def test_rejects_inverted_dovetail_profile(self):
        values = fixture()
        values["dovetail_top_width_mm"] = values["dovetail_base_width_mm"]
        with self.assertRaisesRegex(ValueError, "dovetail"):
            RobotCasingParameters.from_mapping(values)

    def test_neutral_assembly_places_limbs_outside_side_joint_bosses(self):
        parameters = RobotCasingParameters.from_mapping(fixture())
        offsets = assembly_offsets(parameters)
        minimum_side_x = (
            parameters.body_width_mm / 2.0
            + parameters.joint_boss_depth_mm
            + parameters.joint_running_clearance_mm
            + parameters.limb_thickness_mm / 2.0
        )
        self.assertEqual(offsets["left_limb"][0], -minimum_side_x)
        self.assertEqual(offsets["right_limb"][0], minimum_side_x)
        self.assertEqual(
            offsets["body_shell"][2] + parameters.servo_axis_body_z_mm,
            parameters.limb_length_mm - parameters.servo_axle_offset_from_end_mm,
        )
        self.assertEqual(offsets["electronics_tray"][1], parameters.body_depth_mm / 2.0)
        self.assertEqual(offsets["service_panel"], offsets["rear_panel"])


@unittest.skipUnless(cq is not None, "install the cad optional dependency to run CAD tests")
class RobotCasingCadTests(unittest.TestCase):
    def test_fixture_builds_nine_valid_separate_parts(self):
        parts = build_parts(fixture())
        self.assertEqual(
            set(parts),
            {
                "front_shell", "electronics_tray", "service_panel",
                "left_limb", "right_limb", "left_servo_adapter",
                "right_servo_adapter", "camera_bezel", "electronics_carrier",
            },
        )
        for part in parts.values():
            self.assertTrue(part.val().isValid())
            self.assertEqual(len(part.solids().vals()), 1)
            self.assertGreater(part.val().Volume(), 0.0)
        bounds = parts["front_shell"].val().BoundingBox()
        self.assertAlmostEqual(bounds.xlen, 94.0, places=6)
        self.assertAlmostEqual(bounds.ylen, 48.0, places=6)
        self.assertAlmostEqual(bounds.zlen, 78.0, places=6)

    def test_limb_manufacturing_orientation_lays_the_broad_side_on_z_zero(self):
        limb = build_parts(fixture())["left_limb"]
        oriented, label = manufacturing_orientation("left_limb", limb)
        bounds = oriented.val().BoundingBox()
        self.assertEqual(label, "laid flat on broad side")
        self.assertAlmostEqual(bounds.zmin, 0.0, places=6)
        self.assertAlmostEqual(bounds.zlen, fixture()["limb_thickness_mm"], places=6)
        self.assertGreater(max(bounds.xlen, bounds.ylen), bounds.zlen * 4)

    def test_service_parts_are_exported_on_broad_faces(self):
        parts = build_parts(fixture())
        expected = {
            "service_panel": "laid flat with latch relief opening upward",
            "camera_bezel": "laid flat on broad service face",
        }
        for name in ("service_panel", "camera_bezel"):
            oriented, label = manufacturing_orientation(name, parts[name])
            bounds = oriented.val().BoundingBox()
            self.assertEqual(label, expected[name])
            self.assertAlmostEqual(bounds.zmin, 0.0, places=6)
            self.assertGreater(max(bounds.xlen, bounds.ylen), bounds.zlen * 4)

    def test_interlocking_features_are_present_in_part_envelopes(self):
        parameters = RobotCasingParameters.from_mapping(fixture())
        parts = build_parts(parameters.to_dict())
        tray = parts["electronics_tray"].val().BoundingBox()
        panel = parts["service_panel"].val().BoundingBox()
        adapter = parts["left_servo_adapter"].val().BoundingBox()
        self.assertGreater(tray.xlen, parameters.body_width_mm - 2.0 * parameters.wall_mm)
        self.assertGreater(tray.zlen, parameters.panel_thickness_mm)
        self.assertGreater(panel.xlen, parameters.body_width_mm - 2.0 * parameters.wall_mm)
        self.assertGreater(adapter.zlen, parameters.limb_thickness_mm)

    def test_nominal_internal_placements_do_not_have_unintended_interference(self):
        parameters = RobotCasingParameters.from_mapping(fixture())
        parts = build_parts(parameters.to_dict())
        offsets = assembly_offsets(parameters)
        shell = parts["front_shell"].translate(offsets["front_shell"])
        tray = parts["electronics_tray"].translate(offsets["electronics_tray"])
        carrier = parts["electronics_carrier"].translate(offsets["electronics_carrier"])
        panel = parts["service_panel"].translate(offsets["service_panel"])
        bezel = parts["camera_bezel"].translate(offsets["camera_bezel"])

        def common_volume(left, right):
            return sum(solid.Volume() for solid in left.intersect(right).solids().vals())

        # The tray's two hooks intentionally engage 7.68 mm³ of shell latch land.
        self.assertAlmostEqual(common_volume(shell, tray), 7.68, places=2)
        self.assertAlmostEqual(common_volume(shell, carrier), 0.0, places=6)
        self.assertAlmostEqual(common_volume(shell, panel), 0.0, places=6)
        self.assertAlmostEqual(common_volume(shell, bezel), 0.0, places=6)
        self.assertAlmostEqual(common_volume(tray, carrier), 0.0, places=6)
