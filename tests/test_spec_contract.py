import copy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from ariad_fabrication.domain import BoundingBox, PartSpec, SupportPolicy


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "v1" / "part-spec.schema.json"
GOLDEN_SPEC_PATH = ROOT / "benchmarks" / "golden_part" / "part_spec.json"


class PartSpecContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.golden_mapping = json.loads(GOLDEN_SPEC_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(
            cls.schema,
            format_checker=FormatChecker(),
        )

    def test_golden_part_validates_and_round_trips_without_loss(self):
        self.validator.validate(self.golden_mapping)
        spec = PartSpec.from_mapping(self.golden_mapping)

        self.assertEqual(spec.readiness_issues(), ())
        self.assertEqual(spec.to_dict(), self.golden_mapping)
        self.assertEqual(len(spec.features), 7)

    def test_confirmed_schema_rejects_unknown_material(self):
        invalid = copy.deepcopy(self.golden_mapping)
        invalid["material"] = "UNKNOWN"

        with self.assertRaises(ValidationError):
            self.validator.validate(invalid)

        with self.assertRaisesRegex(ValueError, "design-ready"):
            PartSpec.from_mapping(invalid)

    def test_zero_tolerance_is_rejected_by_runtime_contract(self):
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            PartSpec(
                name="Invalid",
                purpose="Test invalid tolerance",
                part_type="fixture",
                bounding_box=BoundingBox(1, 1, 1),
                material="PETG",
                tolerance_mm=0,
                support_policy=SupportPolicy.AVOID,
            )

    def test_fractional_integer_fields_are_rejected(self):
        invalid = copy.deepcopy(self.golden_mapping)
        invalid["infill_pct"] = 30.5

        with self.assertRaisesRegex(ValueError, "infill_pct must be an integer"):
            PartSpec.from_mapping(invalid)

    def test_legacy_string_boolean_is_not_treated_as_truthy(self):
        mapping = copy.deepcopy(self.golden_mapping)
        mapping.pop("support_policy")
        mapping["status"] = "draft"
        mapping["supports"] = "false"

        spec = PartSpec.from_mapping(mapping)

        self.assertEqual(spec.support_policy, SupportPolicy.AVOID)

    def test_part_spec_is_immutable(self):
        spec = PartSpec.from_mapping(self.golden_mapping)

        with self.assertRaises(FrozenInstanceError):
            spec.material = "PLA"
        with self.assertRaises(TypeError):
            spec.features[0].dimensions_mm["diameter"] = 99

    def test_draft_with_unknowns_cannot_be_confirmed(self):
        draft = PartSpec(
            name="Draft",
            purpose="Test confirmation gate",
            part_type="fixture",
            bounding_box=BoundingBox(10, 10, 10),
            material="UNKNOWN",
            support_policy=SupportPolicy.UNKNOWN,
            unresolved_questions=("Which material should be used?",),
        )

        with self.assertRaisesRegex(ValueError, "cannot confirm"):
            draft.confirm()


if __name__ == "__main__":
    unittest.main()
