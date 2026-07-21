import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from ariad_fabrication.domain import AssemblySpec, AssemblyStatus, EnvelopeEvidence


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "benchmarks/robot_casing/assembly_spec.json"
SCHEMA_PATH = ROOT / "schemas/v1/assembly-spec.schema.json"


def load_spec() -> dict[str, object]:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


class AssemblyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(
            cls.schema,
            format_checker=FormatChecker(),
        )

    def test_robot_assembly_round_trips_and_passes_schema(self):
        value = load_spec()
        self.validator.validate(value)
        assembly = AssemblySpec.from_mapping(value)
        self.assertEqual(assembly.status, AssemblyStatus.DRAFT)
        self.assertEqual(len(assembly.parts), 9)
        self.assertEqual(len(assembly.component_envelopes), 4)
        self.assertEqual(len(assembly.interfaces), 7)
        self.assertEqual(
            [item.evidence for item in assembly.component_envelopes],
            [
                EnvelopeEvidence.MANUFACTURER,
                EnvelopeEvidence.MANUFACTURER,
                EnvelopeEvidence.PLACEHOLDER,
                EnvelopeEvidence.PLACEHOLDER,
            ],
        )
        self.assertEqual(assembly.to_dict(), value)

    def test_every_manufactured_robot_item_is_a_separate_part(self):
        assembly = AssemblySpec.from_mapping(load_spec())
        part_ids = {item.part_id for item in assembly.parts}
        self.assertEqual(
            part_ids,
            {
                "front_shell",
                "electronics_tray",
                "service_panel",
                "left_limb",
                "right_limb",
                "left_servo_adapter",
                "right_servo_adapter",
                "camera_bezel",
                "electronics_carrier",
            },
        )
        self.assertTrue(all(item.separately_manufactured for item in assembly.parts))

    def test_unknown_interface_participant_fails_closed(self):
        value = load_spec()
        value["interfaces"][0]["participants"][0] = "part:missing_shell"
        with self.assertRaisesRegex(ValueError, "unknown participants"):
            AssemblySpec.from_mapping(value)

    def test_hardware_and_physical_claims_are_literal_false(self):
        value = load_spec()
        value["hardware_actions"] = True
        with self.assertRaisesRegex(ValueError, "hardware actions"):
            AssemblySpec.from_mapping(value)
        with self.assertRaises(ValidationError):
            self.validator.validate(value)

    def test_rotating_interface_requires_an_axis(self):
        value = load_spec()
        value["interfaces"][2]["axis"] = None
        with self.assertRaisesRegex(ValueError, "requires an axis"):
            AssemblySpec.from_mapping(value)


if __name__ == "__main__":
    unittest.main()
