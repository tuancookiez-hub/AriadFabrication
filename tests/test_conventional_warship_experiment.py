import json
from pathlib import Path
import unittest

try:
    import cadquery as cq
except ImportError:
    cq = None

if cq is not None:
    from experiments.conventional_warship.generate import build_model, validate_geometry


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(cq is not None, "install the cad optional dependency to run CAD tests")
class ConventionalWarshipExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parameters = json.loads(
            (ROOT / "experiments" / "conventional_warship" / "parameters.json").read_text(
                encoding="utf-8"
            )
        )

    def test_default_recipe_is_one_geometry_checked_solid(self):
        model = build_model(self.parameters)
        report = validate_geometry(model, self.parameters)

        self.assertTrue(report["passed"])
        self.assertTrue(model.isValid())
        self.assertEqual(len(model.Solids()), 1)
        self.assertAlmostEqual(report["bounds_mm"]["x"], 160.0, places=2)
        self.assertAlmostEqual(report["bounds_mm"]["y"], 32.0, places=2)
        self.assertGreaterEqual(report["flat_contact_area_mm2"], 800.0)

    def test_recipe_rejects_details_below_four_nozzle_widths(self):
        altered = dict(self.parameters)
        altered["minimum_nominal_feature_mm"] = 1.2

        with self.assertRaisesRegex(ValueError, "at least four nozzle widths"):
            build_model(altered)


if __name__ == "__main__":
    unittest.main()
