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
