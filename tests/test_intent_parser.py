import unittest

from ariad_fabrication.domain import SpecStatus, SupportPolicy
from ariad_fabrication.intent_parser import IntentParseError, RuleBasedIntentParser


class RuleBasedIntentParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = RuleBasedIntentParser()

    def test_parses_only_explicit_manufacturing_facts(self):
        spec = self.parser.parse(
            "Create a mounting bracket, 40 x 20 x 5 mm, in PETG, "
            "with 35% infill and supports. Tolerance 0.2 mm."
        )

        self.assertEqual(spec.status, SpecStatus.DRAFT)
        self.assertEqual(spec.part_type, "mounting bracket")
        self.assertEqual(
            spec.dimensions_mm,
            {"length": 40.0, "width": 20.0, "height": 5.0},
        )
        self.assertEqual(spec.material, "PETG")
        self.assertEqual(spec.infill_pct, 35)
        self.assertEqual(spec.support_policy, SupportPolicy.REQUIRED)
        self.assertEqual(spec.tolerance_mm, 0.2)
        self.assertEqual(spec.unresolved_questions, ())

    def test_rejects_a_request_without_dimensions(self):
        with self.assertRaises(IntentParseError):
            self.parser.parse("Print a phone stand in PLA")

    def test_without_supports_records_avoid_policy(self):
        spec = self.parser.parse("Print a 30 x 30 x 10 mm box without supports")

        self.assertEqual(spec.support_policy, SupportPolicy.AVOID)
        self.assertFalse(spec.supports)
        self.assertTrue(any("material" in item.lower() for item in spec.unresolved_questions))
        self.assertTrue(any("tolerance" in item.lower() for item in spec.unresolved_questions))
        self.assertFalse(any("support" in item.lower() for item in spec.unresolved_questions))

    def test_missing_critical_facts_are_not_defaulted(self):
        spec = self.parser.parse("Create a 20 x 10 x 4 mm spacer")

        self.assertEqual(spec.material, "UNKNOWN")
        self.assertIsNone(spec.tolerance_mm)
        self.assertEqual(spec.support_policy, SupportPolicy.UNKNOWN)
        self.assertEqual(len(spec.unresolved_questions), 3)


if __name__ == "__main__":
    unittest.main()
