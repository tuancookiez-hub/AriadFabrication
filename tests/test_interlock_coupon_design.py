import json
from pathlib import Path
import unittest

try:
    import cadquery as cq
except ImportError:
    cq = None

from ariad_fabrication.cad.interlock_coupon_design import (
    DESIGN_ID,
    InterlockCouponParameters,
    build_parts,
)


ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads(
        (ROOT / "benchmarks/interlock_coupon/parameters.json").read_text(encoding="utf-8")
    )


class InterlockCouponParameterTests(unittest.TestCase):
    def test_fixture_is_closed_and_valid(self):
        parameters = InterlockCouponParameters.from_mapping(fixture())
        self.assertEqual(DESIGN_ID, fixture()["design_id"])
        self.assertEqual(parameters.clearance_values_mm, (0.2, 0.3, 0.4, 0.5, 0.6))

    def test_rejects_unsorted_clearances(self):
        values = fixture()
        values["clearance_values_mm"] = [0.2, 0.4, 0.3, 0.5, 0.6]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            InterlockCouponParameters.from_mapping(values)

    def test_rejects_short_snap_arm(self):
        values = fixture()
        values["snap_arm_length_mm"] = 8.0
        with self.assertRaisesRegex(ValueError, "snap arm"):
            InterlockCouponParameters.from_mapping(values)


@unittest.skipUnless(cq is not None, "install the cad optional dependency to run CAD tests")
class InterlockCouponCadTests(unittest.TestCase):
    def test_fixture_builds_six_valid_small_parts(self):
        parts = build_parts(fixture())
        self.assertEqual(
            set(parts),
            {
                "dovetail_gauge", "dovetail_key", "snap_receiver",
                "snap_key_0_4", "snap_key_0_8", "snap_key_1_2",
            },
        )
        for part in parts.values():
            self.assertTrue(part.val().isValid())
            self.assertEqual(len(part.solids().vals()), 1)
            bounds = part.val().BoundingBox()
            self.assertLessEqual(max(bounds.xlen, bounds.ylen, bounds.zlen), 80.0)

    def test_candidate_geometry_changes_with_hook_engagement(self):
        parts = build_parts(fixture())
        volumes = [
            parts[name].val().Volume()
            for name in ("snap_key_0_4", "snap_key_0_8", "snap_key_1_2")
        ]
        self.assertLess(volumes[0], volumes[1])
        self.assertLess(volumes[1], volumes[2])

    def test_gauge_has_five_open_dovetail_channels(self):
        gauge = build_parts(fixture())["dovetail_gauge"]
        self.assertGreaterEqual(len(gauge.faces().vals()), 35)
        self.assertAlmostEqual(gauge.val().BoundingBox().xlen, 75.0, places=6)
