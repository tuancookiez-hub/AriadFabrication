import json
from pathlib import Path
import unittest
try:
    import cadquery as cq
except ImportError:
    cq = None

from ariad_fabrication.cad.l_bracket_design import (
    DESIGN_ID,
    LBracketParameters,
    build_model,
)


ROOT = Path(__file__).resolve().parents[1]


def fixture() -> dict[str, object]:
    return json.loads(
        (ROOT / "benchmarks/l_bracket/parameters.json").read_text(encoding="utf-8")
    )


class LBracketParameterTests(unittest.TestCase):
    def test_fixture_has_a_closed_valid_geometry_boundary(self):
        parameters = LBracketParameters.from_mapping(fixture())
        self.assertEqual(parameters.to_dict()["design_id"], DESIGN_ID)
        self.assertEqual(parameters.width_mm, 50.0)

    def test_rejects_hole_pair_that_breaks_edge_margins(self):
        values = fixture()
        values["hole_spacing_mm"] = 45.0
        with self.assertRaisesRegex(ValueError, "does not fit"):
            LBracketParameters.from_mapping(values)

    def test_rejects_boolean_numeric_input(self):
        values = fixture()
        values["thickness_mm"] = True
        with self.assertRaisesRegex(ValueError, "must be a number"):
            LBracketParameters.from_mapping(values)


@unittest.skipUnless(cq is not None, "install the cad optional dependency to run CAD tests")
class LBracketCadTests(unittest.TestCase):
    def test_fixture_builds_one_valid_solid_with_expected_envelope(self):
        model = build_model(fixture())
        self.assertTrue(model.val().isValid())
        self.assertEqual(len(model.solids().vals()), 1)
        bounds = model.val().BoundingBox()
        self.assertAlmostEqual(bounds.xlen, 50.0, places=6)
        self.assertAlmostEqual(bounds.ylen, 35.0, places=6)
        self.assertAlmostEqual(bounds.zlen, 40.0, places=6)
