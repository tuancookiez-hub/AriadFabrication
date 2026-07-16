import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ariad_fabrication.slicing import PrinterProfile, ProfileBundle


ROOT = Path(__file__).resolve().parents[1]
PROFILE_ROOT = ROOT / "profiles" / "v1"


def _bundle(*, config_path: Path | None = None) -> ProfileBundle:
    return ProfileBundle.from_paths(
        printer_path=PROFILE_ROOT / "printers" / "generic_open_fdm_220.json",
        material_path=PROFILE_ROOT / "materials" / "generic_pla_175.json",
        process_path=PROFILE_ROOT / "processes" / "standard_020_no_support.json",
        orientation_path=PROFILE_ROOT / "orientations" / "upright_source_z_centered.json",
        slicer_config_path=config_path
        or PROFILE_ROOT
        / "prusaslicer"
        / "generic_open_fdm_220__generic_pla__standard_020_no_support.ini",
    )


class SlicingProfileTests(unittest.TestCase):
    def test_profile_bundle_matches_the_prusaslicer_config(self):
        bundle = _bundle()

        self.assertEqual(bundle.printer.profile_id, "generic_open_fdm_220_v1")
        self.assertEqual(bundle.material.material_type, "PLA")
        self.assertEqual(bundle.process.support_policy, "disabled")
        self.assertTrue(bundle.orientation.is_identity())
        self.assertGreaterEqual(len(bundle.validate()), 20)
        json.dumps(bundle.to_dict())

    def test_profile_bundle_can_record_relocatable_source_paths(self):
        serialized = _bundle().to_dict(relative_to=ROOT)

        paths = [item["path"] for item in serialized["source_files"]]
        self.assertTrue(all(not Path(path).is_absolute() for path in paths))
        self.assertEqual(paths[0], "profiles/v1/printers/generic_open_fdm_220.json")

    def test_profile_bundle_rejects_config_drift(self):
        source = (
            PROFILE_ROOT
            / "prusaslicer"
            / "generic_open_fdm_220__generic_pla__standard_020_no_support.ini"
        ).read_text(encoding="utf-8")
        with TemporaryDirectory() as temporary:
            altered = Path(temporary) / "altered.ini"
            altered.write_text(source.replace("support_material = 0", "support_material = 1"), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "support_policy"):
                _bundle(config_path=altered)

    def test_golden_part_petg_bundle_matches_material_and_process_intent(self):
        bundle = ProfileBundle.from_paths(
            printer_path=PROFILE_ROOT / "printers" / "generic_open_fdm_220.json",
            material_path=PROFILE_ROOT / "materials" / "generic_petg_175.json",
            process_path=PROFILE_ROOT / "processes" / "golden_part_020_no_support.json",
            orientation_path=PROFILE_ROOT / "orientations" / "upright_source_z_centered.json",
            slicer_config_path=PROFILE_ROOT
            / "prusaslicer"
            / "generic_open_fdm_220__generic_petg__golden_part_020_no_support.ini",
        )

        self.assertEqual(bundle.printer.profile_family_id, "generic_open_fdm_220")
        self.assertEqual(bundle.material.material_type, "PETG")
        self.assertEqual(bundle.material.first_layer_bed_temperature_c, 85.0)
        self.assertEqual(bundle.material.selected_bed_temperature_c, 90.0)
        self.assertEqual(bundle.process.infill_percent, 30.0)
        self.assertEqual(bundle.process.support_policy, "disabled")
        self.assertGreaterEqual(len(bundle.validate()), 29)

    def test_profile_mapping_rejects_scalar_coercion_and_unknown_fields(self):
        source = json.loads(
            (
                PROFILE_ROOT / "printers" / "generic_open_fdm_220.json"
            ).read_text(encoding="utf-8")
        )
        cases = (
            ("nozzle_diameter_mm", "0.4"),
            ("undeclared_capability", True),
        )
        for field, value in cases:
            with self.subTest(field=field):
                mutated = dict(source)
                mutated[field] = value
                with self.assertRaisesRegex(ValueError, "printer-profile.schema.json"):
                    PrinterProfile.from_mapping(mutated)

    def test_profile_file_rejects_duplicate_json_keys(self):
        source_path = PROFILE_ROOT / "printers" / "generic_open_fdm_220.json"
        source = source_path.read_text(encoding="utf-8")
        duplicate = source.replace(
            '  "profile_id":',
            '  "profile_id": "duplicate",\n  "profile_id":',
            1,
        )
        with TemporaryDirectory() as temporary:
            altered = Path(temporary) / "duplicate.json"
            altered.write_text(duplicate, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "strict UTF-8 JSON"):
                ProfileBundle.from_paths(
                    printer_path=altered,
                    material_path=PROFILE_ROOT / "materials" / "generic_pla_175.json",
                    process_path=(
                        PROFILE_ROOT
                        / "processes"
                        / "standard_020_no_support.json"
                    ),
                    orientation_path=(
                        PROFILE_ROOT
                        / "orientations"
                        / "upright_source_z_centered.json"
                    ),
                    slicer_config_path=(
                        PROFILE_ROOT
                        / "prusaslicer"
                        / "generic_open_fdm_220__generic_pla__standard_020_no_support.ini"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
