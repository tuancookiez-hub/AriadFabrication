from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest

from ariad_fabrication.api import JourneyRepository
from ariad_fabrication.api.fixture import JOB_ID, REVISION_ID
from ariad_fabrication.api.repository import InvalidRevisionError
from ariad_fabrication.fabrication_contracts import PRODUCTION_PACKAGE_REQUIRED_ROLES
from ariad_fabrication.schema_validation import (
    ARTIFACT_MANIFEST_SCHEMA,
    GCODE_PREFLIGHT_REPORT_SCHEMA,
    GEOMETRY_VALIDATION_REPORT_SCHEMA,
    INTERFACE_FABRICATION_PACKAGE_SCHEMA,
    INTERFACE_GCODE_PREFLIGHT_REPORT_SCHEMA,
    INTERFACE_GEOMETRY_VALIDATION_REPORT_SCHEMA,
    INTERFACE_MATERIAL_PROFILE_SCHEMA,
    INTERFACE_ORIENTATION_PROFILE_SCHEMA,
    INTERFACE_PRINTER_PROFILE_SCHEMA,
    INTERFACE_PRINTABILITY_REPORT_SCHEMA,
    INTERFACE_PROCESS_PROFILE_SCHEMA,
    JOURNEY_EVENT_SCHEMA,
    MATERIAL_PROFILE_SCHEMA,
    ORIENTATION_PROFILE_SCHEMA,
    PART_SPEC_SCHEMA,
    PERSISTED_SCHEMA_FILENAMES,
    PRINTER_PROFILE_SCHEMA,
    PRINTABILITY_REPORT_SCHEMA,
    PROCESS_PROFILE_SCHEMA,
    PersistedSchemaValidationError,
    check_persisted_schema_asset,
    schema_asset_path,
    validate_persisted_instance,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "benchmarks" / "interface"

def _fixture_revision_root(root: Path) -> Path:
    return root / JOB_ID / "revisions" / REVISION_ID


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class PersistedSchemaRuntimeTests(unittest.TestCase):
    def test_all_runtime_schema_assets_are_available_and_meta_valid(self):
        for schema_name in sorted(PERSISTED_SCHEMA_FILENAMES):
            with self.subTest(schema=schema_name):
                self.assertTrue(schema_asset_path(schema_name).is_file())
                check_persisted_schema_asset(schema_name)

    def test_committed_fixture_uses_the_production_record_schemas_and_fixture_package_schema(self):
        revision_root = _fixture_revision_root(FIXTURE_ROOT)
        journey = _read_json(revision_root / "journey.json")
        manifest = _read_json(revision_root / "manifest.json")
        package = _read_json(revision_root / "fabrication" / "package.json")
        revision = next(
            item for item in journey["revisions"] if item["revision_id"] == REVISION_ID
        )

        validate_persisted_instance(
            revision["spec"], PART_SPEC_SCHEMA, record_name="fixture PartSpec"
        )
        for event in journey["events"]:
            validate_persisted_instance(
                event, JOURNEY_EVENT_SCHEMA, record_name="fixture event"
            )
        validate_persisted_instance(
            manifest, ARTIFACT_MANIFEST_SCHEMA, record_name="fixture manifest"
        )
        validate_persisted_instance(
            package,
            INTERFACE_FABRICATION_PACKAGE_SCHEMA,
            record_name="fixture package",
        )

    def test_every_committed_profile_and_inspection_fixture_has_an_exact_role_schema(self):
        profile_cases = (
            (
                ROOT / "profiles" / "v1" / "printers" / "generic_open_fdm_220.json",
                PRINTER_PROFILE_SCHEMA,
            ),
            (
                ROOT / "profiles" / "v1" / "materials" / "generic_petg_175.json",
                MATERIAL_PROFILE_SCHEMA,
            ),
            (
                ROOT / "profiles" / "v1" / "materials" / "generic_pla_175.json",
                MATERIAL_PROFILE_SCHEMA,
            ),
            (
                ROOT
                / "profiles"
                / "v1"
                / "processes"
                / "golden_part_020_no_support.json",
                PROCESS_PROFILE_SCHEMA,
            ),
            (
                ROOT
                / "profiles"
                / "v1"
                / "processes"
                / "standard_020_no_support.json",
                PROCESS_PROFILE_SCHEMA,
            ),
            (
                ROOT
                / "profiles"
                / "v1"
                / "orientations"
                / "upright_source_z_centered.json",
                ORIENTATION_PROFILE_SCHEMA,
            ),
        )
        for path, schema_name in profile_cases:
            with self.subTest(path=path.name, schema=schema_name):
                validate_persisted_instance(
                    _read_json(path),
                    schema_name,
                    record_name=str(path),
                )

        fixture_cases = {
            Path("design/geometry_validation.json"): (
                INTERFACE_GEOMETRY_VALIDATION_REPORT_SCHEMA
            ),
            Path("printability/report.json"): INTERFACE_PRINTABILITY_REPORT_SCHEMA,
            Path("slicing/gcode_preflight.json"): (
                INTERFACE_GCODE_PREFLIGHT_REPORT_SCHEMA
            ),
            Path("profiles/printer.json"): INTERFACE_PRINTER_PROFILE_SCHEMA,
            Path("profiles/material.json"): INTERFACE_MATERIAL_PROFILE_SCHEMA,
            Path("profiles/process.json"): INTERFACE_PROCESS_PROFILE_SCHEMA,
            Path("profiles/orientation.json"): INTERFACE_ORIENTATION_PROFILE_SCHEMA,
        }
        revision_root = _fixture_revision_root(FIXTURE_ROOT)
        for relative, schema_name in fixture_cases.items():
            with self.subTest(path=relative.as_posix(), schema=schema_name):
                validate_persisted_instance(
                    _read_json(revision_root / relative),
                    schema_name,
                    record_name=relative.as_posix(),
                )

        self.assertIn(GEOMETRY_VALIDATION_REPORT_SCHEMA, PERSISTED_SCHEMA_FILENAMES)
        self.assertIn(PRINTABILITY_REPORT_SCHEMA, PERSISTED_SCHEMA_FILENAMES)
        self.assertIn(GCODE_PREFLIGHT_REPORT_SCHEMA, PERSISTED_SCHEMA_FILENAMES)

    def test_schema_errors_include_a_path_and_bound_untrusted_values(self):
        event = _read_json(
            _fixture_revision_root(FIXTURE_ROOT) / "journey.json"
        )["events"][0]
        event["timestamp"] = "2026-07-16T08:00:00"
        with self.assertRaisesRegex(
            PersistedSchemaValidationError,
            r"\$\.timestamp",
        ):
            validate_persisted_instance(
                event, JOURNEY_EVENT_SCHEMA, record_name="bad event"
            )

        oversized_key = "untrusted_" + "x" * 5_000
        with self.assertRaises(PersistedSchemaValidationError) as raised:
            validate_persisted_instance(
                {oversized_key: True},
                ARTIFACT_MANIFEST_SCHEMA,
                record_name="bad manifest",
            )
        self.assertLess(len(str(raised.exception)), 700)
        self.assertTrue(str(raised.exception).endswith("…"))

    def test_preflight_schema_requires_each_check_once_and_consistent_pass_state(self):
        check_ids = (
            "has_layers",
            "millimetre_units",
            "absolute_xyz_mode",
            "extrusion_mode",
            "x_bounds",
            "y_bounds",
            "z_bounds",
            "nozzle_temperature",
            "bed_temperature",
            "single_tool",
            "forbidden_commands",
            "support_policy",
            "profile_layer_height",
        )
        report = {
            "passed": True,
            "checks": [
                {
                    "check_id": check_id,
                    "passed": True,
                    "measured": True,
                    "requirement": "identity unit requirement",
                }
                for check_id in check_ids
            ],
            "errors": [],
            "warnings": [],
            "claim_boundary": "Disconnected preflight schema unit value.",
        }
        validate_persisted_instance(
            report,
            GCODE_PREFLIGHT_REPORT_SCHEMA,
            record_name="complete preflight",
        )

        duplicate = deepcopy(report)
        duplicate["checks"][-1]["check_id"] = "has_layers"
        inconsistent = deepcopy(report)
        inconsistent["checks"][0]["passed"] = False
        for value in (duplicate, inconsistent):
            with self.subTest(value=value):
                with self.assertRaises(PersistedSchemaValidationError):
                    validate_persisted_instance(
                        value,
                        GCODE_PREFLIGHT_REPORT_SCHEMA,
                        record_name="invalid preflight",
                    )


class PersistedRepositoryIntegrityTests(unittest.TestCase):
    def _assert_fixture_invalid(self, mutate, pattern: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            mutate(_fixture_revision_root(copied_root))
            with self.assertRaisesRegex(InvalidRevisionError, pattern):
                JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)

    def test_raw_spec_event_manifest_and_fixture_package_schemas_fail_closed(self):
        def mutate_spec(root: Path) -> None:
            path = root / "journey.json"
            journey = _read_json(path)
            revision = next(
                item
                for item in journey["revisions"]
                if item["revision_id"] == REVISION_ID
            )
            revision["spec"]["undeclared_evidence"] = True
            _write_json(path, journey)

        def mutate_event(root: Path) -> None:
            path = root / "journey.json"
            journey = _read_json(path)
            journey["events"][0]["undeclared_evidence"] = True
            _write_json(path, journey)

        def mutate_manifest(root: Path) -> None:
            path = root / "manifest.json"
            manifest = _read_json(path)
            manifest["undeclared_evidence"] = True
            _write_json(path, manifest)

        def mutate_package(root: Path) -> None:
            path = root / "fabrication" / "package.json"
            package = _read_json(path)
            package["undeclared_evidence"] = True
            _write_json(path, package)

        cases = (
            ("PartSpec", mutate_spec, "part-spec.schema.json"),
            ("event", mutate_event, "journey-event.schema.json"),
            ("manifest", mutate_manifest, "artifact-manifest.schema.json"),
            (
                "fixture package",
                mutate_package,
                "interface-fabrication-package.schema.json",
            ),
        )
        for name, mutate, pattern in cases:
            with self.subTest(record=name):
                self._assert_fixture_invalid(mutate, pattern)

    def test_stage_coverage_and_artifact_lineage_fail_closed(self):
        def omit_stage_reference(root: Path) -> None:
            path = root / "journey.json"
            journey = _read_json(path)
            stage = next(
                item
                for item in journey["stage_runs"]
                if item["stage_run_id"] == "run_fixture_printability_validation"
            )
            stage["artifact_ids"].remove("art_fixture_printer_profile")
            _write_json(path, journey)

        def mutate_artifacts(root: Path, mutation) -> None:
            for name in ("journey.json", "manifest.json"):
                path = root / name
                value = _read_json(path)
                mutation(value["artifacts"])
                _write_json(path, value)

        def missing_parent(root: Path) -> None:
            def mutation(artifacts: list[dict]) -> None:
                artifact = next(
                    item
                    for item in artifacts
                    if item["artifact_id"] == "art_fixture_printer_profile"
                )
                artifact["parent_artifact_ids"] = ["art_missing_parent"]

            mutate_artifacts(root, mutation)

        def lineage_cycle(root: Path) -> None:
            def mutation(artifacts: list[dict]) -> None:
                by_id = {item["artifact_id"]: item for item in artifacts}
                by_id["art_fixture_printer_profile"]["parent_artifact_ids"] = [
                    "art_fixture_material_profile"
                ]
                by_id["art_fixture_material_profile"]["parent_artifact_ids"] = [
                    "art_fixture_printer_profile"
                ]

            mutate_artifacts(root, mutation)

        def duplicate_path(root: Path) -> None:
            def mutation(artifacts: list[dict]) -> None:
                by_id = {item["artifact_id"]: item for item in artifacts}
                by_id["art_fixture_material_profile"]["path"] = by_id[
                    "art_fixture_printer_profile"
                ]["path"]

            mutate_artifacts(root, mutation)

        cases = (
            (omit_stage_reference, "unreferenced artifact"),
            (missing_parent, "references missing parent"),
            (lineage_cycle, "artifact lineage contains a cycle"),
            (duplicate_path, "artifact path .* is shared"),
        )
        for mutate, pattern in cases:
            with self.subTest(pattern=pattern):
                self._assert_fixture_invalid(mutate, pattern)

    def test_package_warning_and_successful_stage_parity_fail_closed(self):
        def warning_drift(root: Path) -> None:
            path = root / "fabrication" / "package.json"
            package = _read_json(path)
            package["unresolved_warning_findings"].pop()
            _write_json(path, package)

        def stale_package(root: Path) -> None:
            path = root / "journey.json"
            journey = _read_json(path)
            stage = next(
                item
                for item in journey["stage_runs"]
                if item["stage_run_id"] == "run_fixture_fabrication_package"
            )
            event = next(
                item
                for item in journey["events"]
                if item["stage_run_id"] == stage["stage_run_id"]
            )
            stage["status"] = "failed"
            stage["evidence_level"] = None
            stage["error_message"] = "Fixture package attempt failed."
            event["status"] = "failed"
            _write_json(path, journey)

        self._assert_fixture_invalid(warning_drift, "warning ids differ")
        self._assert_fixture_invalid(
            stale_package, "exactly one successful package stage"
        )


class InspectionContentIdentityTests(unittest.TestCase):
    @staticmethod
    def _case() -> tuple[SimpleNamespace, dict[str, dict]]:
        profile_ids = {
            "printer": "printer_v1",
            "printer_family": "printer_family",
            "material": "material_v1",
            "process": "process_v1",
            "orientation": "orientation_v1",
        }
        preflight = {
            "passed": True,
            "checks": [],
            "errors": [],
            "warnings": [],
            "claim_boundary": "Disconnected fixture for identity unit testing.",
        }
        package = {
            "profile_ids": deepcopy(profile_ids),
            "preflight": deepcopy(preflight),
            "required_artifacts": [
                {
                    "role": "exact_geometry",
                    "path": "design/part.step",
                    "checksum_sha256": "a" * 64,
                    "size_bytes": 101,
                },
                {
                    "role": "oriented_geometry",
                    "path": "printability/oriented.step",
                    "checksum_sha256": "b" * 64,
                    "size_bytes": 103,
                },
            ],
        }
        part_spec = {"schema_version": "1.0.0", "name": "Identity unit part"}
        values = {
            "part_spec": deepcopy(part_spec),
            "printer_profile": {
                "profile_id": "printer_v1",
                "profile_family_id": "printer_family",
            },
            "material_profile": {"profile_id": "material_v1"},
            "process_profile": {"profile_id": "process_v1"},
            "orientation_profile": {"orientation_id": "orientation_v1"},
            "geometry_validation_report": {"benchmark_id": "benchmark_v1"},
            "printability_report": {
                "benchmark_id": "benchmark_v1",
                "profile_ids": deepcopy(profile_ids),
                "source_geometry": {
                    "filename": "part.step",
                    "checksum_sha256": "a" * 64,
                    "size_bytes": 101,
                },
                "oriented_geometry": {
                    "filename": "oriented.step",
                    "checksum_sha256": "b" * 64,
                    "size_bytes": 103,
                    "materialization": "identity",
                },
            },
            "gcode_preflight": deepcopy(preflight),
        }
        loaded = SimpleNamespace(
            fixture=None,
            package=package,
            revision={"spec": part_spec},
        )
        return loaded, values

    def test_checksum_verified_content_identities_match_the_package(self):
        loaded, values = self._case()

        JourneyRepository(ROOT)._validate_inspection_content_identity(loaded, values)

    def test_semantic_identity_drift_fails_closed_after_schema_validation(self):
        cases = (
            (
                lambda values: values["material_profile"].update(
                    profile_id="other_material"
                ),
                "material_profile identity differs",
            ),
            (
                lambda values: values["printability_report"][
                    "source_geometry"
                ].update(checksum_sha256="c" * 64),
                "source_geometry identity differs",
            ),
            (
                lambda values: values["gcode_preflight"].update(passed=False),
                "preflight artifact differs",
            ),
            (
                lambda values: values["part_spec"].update(name="Different part"),
                "PartSpec content differs",
            ),
        )
        for mutate, pattern in cases:
            with self.subTest(pattern=pattern):
                loaded, values = self._case()
                mutate(values)
                with self.assertRaisesRegex(InvalidRevisionError, pattern):
                    JourneyRepository(ROOT)._validate_inspection_content_identity(
                        loaded,
                        values,
                    )


class ProductionPackageParityTests(unittest.TestCase):
    def _case(self) -> dict:
        package_stage_id = "run_package"
        required_artifacts: list[dict] = []
        artifacts: dict[str, dict] = {}
        for role in PRODUCTION_PACKAGE_REQUIRED_ROLES:
            artifact_id = f"art_{role}"
            path = (
                "slicing/toolpath.gcode"
                if role == "gcode"
                else f"evidence/{role}.json"
            )
            descriptor = {
                "artifact_id": artifact_id,
                "role": role,
                "path": path,
                "size_bytes": 7,
                "checksum_sha256": "a" * 64,
            }
            required_artifacts.append(descriptor)
            artifacts[artifact_id] = {
                **descriptor,
                "evidence_mode": "real",
                "stage_run_id": "run_evidence",
            }

        package_payload = b"bounded package snapshot"
        artifacts["art_package"] = {
            "artifact_id": "art_package",
            "role": "fabrication_package_report",
            "path": "fabrication/package.json",
            "size_bytes": len(package_payload),
            "checksum_sha256": hashlib.sha256(package_payload).hexdigest(),
            "evidence_mode": "real",
            "stage_run_id": package_stage_id,
        }
        package = {
            "status": "slicer_verified",
            "required_artifacts": required_artifacts,
            "unresolved_warning_findings": [],
            "gcode_summary": {
                "path": "toolpath.gcode",
                "size_bytes": 7,
                "checksum_sha256": "a" * 64,
            },
        }
        stage_runs = {
            package_stage_id: {
                "stage": "fabrication_package",
                "status": "passed",
                "evidence_level": "R4",
                "evidence_mode": "real",
                "input_artifact_ids": [
                    item["artifact_id"] for item in required_artifacts
                ],
            }
        }
        return {
            "package": package,
            "package_payload": package_payload,
            "manifest": {},
            "fixture": False,
            "stage_ids": [package_stage_id],
            "stage_runs": stage_runs,
            "artifacts": artifacts,
            "findings": {},
        }

    def _validate(self, case: dict) -> None:
        JourneyRepository(ROOT)._validate_package_consistency(**case)

    def test_complete_production_package_metadata_is_consistent(self):
        self._validate(self._case())

    def test_production_package_metadata_drift_fails_closed(self):
        case = self._case()
        case["artifacts"].pop("art_part_spec")
        with self.assertRaisesRegex(InvalidRevisionError, "absent from manifest"):
            self._validate(case)

        case = self._case()
        case["package"]["required_artifacts"][0]["size_bytes"] = 8
        with self.assertRaisesRegex(InvalidRevisionError, "differs from manifest"):
            self._validate(case)

        case = self._case()
        case["package"]["gcode_summary"]["path"] = "other.gcode"
        with self.assertRaisesRegex(InvalidRevisionError, "summary path differs"):
            self._validate(case)

        case = self._case()
        case["artifacts"]["art_package"]["checksum_sha256"] = "b" * 64
        with self.assertRaisesRegex(InvalidRevisionError, "checksum differs"):
            self._validate(case)

        case = self._case()
        case["stage_runs"]["run_package"]["status"] = "failed"
        with self.assertRaisesRegex(InvalidRevisionError, "successful package stage"):
            self._validate(case)

        case = self._case()
        finding = {
            "finding_id": "finding_warning",
            "severity": "warning",
            "resolved": False,
        }
        case["findings"] = {finding["finding_id"]: finding}
        case["stage_runs"]["run_package"]["status"] = "passed_with_warnings"
        case["package"]["status"] = "slicer_verified_with_physical_unknowns"
        with self.assertRaisesRegex(InvalidRevisionError, "warning records differ"):
            self._validate(case)


if __name__ == "__main__":
    unittest.main()
