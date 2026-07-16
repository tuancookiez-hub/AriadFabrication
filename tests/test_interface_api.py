import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ariad_fabrication.api import JourneyRepository, create_app
from ariad_fabrication.api.fixture import (
    COMPARISON_REVISION_ID,
    GATE_SCENARIOS,
    JOB_ID,
    REVISION_ID,
    STAGES,
    generate_interface_fixtures,
)
from ariad_fabrication.api.repository import (
    ArtifactIntegrityError,
    InvalidRevisionError,
    RevisionNotFoundError,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "benchmarks" / "interface"


class InterfaceFixtureTests(unittest.TestCase):
    def test_committed_fixture_family_is_reproducible(self):
        with tempfile.TemporaryDirectory() as temporary:
            generated_root = Path(temporary)
            generate_interface_fixtures(
                generated_root,
                ROOT / "benchmarks" / "golden_part" / "part_spec.json",
            )
            generated_files = sorted(
                path.relative_to(generated_root)
                for path in generated_root.rglob("*")
                if path.is_file()
            )
            committed_files = sorted(
                path.relative_to(FIXTURE_ROOT)
                for path in FIXTURE_ROOT.rglob("*")
                if path.is_file()
                and path.relative_to(FIXTURE_ROOT).parts[0].startswith("job_interface_")
            )
            self.assertEqual(generated_files, committed_files)
            for relative in generated_files:
                self.assertEqual(
                    (generated_root / relative).read_bytes(),
                    (FIXTURE_ROOT / relative).read_bytes(),
                    relative,
                )


class JourneyRepositoryTests(unittest.TestCase):
    def test_fixture_is_grouped_without_becoming_real_evidence(self):
        repository = JourneyRepository(FIXTURE_ROOT)
        detail = repository.get_revision(JOB_ID, REVISION_ID)

        self.assertTrue(detail.source.fixture)
        self.assertEqual(detail.source.evidence_mode, "fixture")
        self.assertFalse(detail.source.physical_evidence_present)
        self.assertEqual(len(detail.stages), 6)
        self.assertEqual(detail.stages[-1].evidence_level, "R4")
        self.assertIsNotNone(detail.package)
        self.assertIsNone(detail.package.evidence_level)
        self.assertEqual(
            detail.package.allowed_claim,
            "Interface fixture only — no fabrication evidence.",
        )
        self.assertFalse(detail.package.hardware.printer_selected)
        self.assertFalse(detail.package.hardware.print_started)
        self.assertEqual(len(detail.stages[3].findings), 2)
        self.assertTrue(all(stage.evidence_mode == "fixture" for stage in detail.stages))
        self.assertFalse(detail.capabilities.hardware_actions)
        self.assertEqual(detail.schema_version, "1.2.0")
        self.assertEqual(
            [report.report_kind for report in detail.inspection.reports],
            ["geometry", "printability", "gcode_preflight"],
        )
        self.assertEqual(
            [len(report.checks) for report in detail.inspection.reports],
            [3, 3, 3],
        )
        self.assertTrue(
            all(
                report.artifact.checksum_verified
                and report.artifact.evidence_mode == "fixture"
                for report in detail.inspection.reports
            )
        )
        self.assertEqual(len(detail.inspection.profiles), 4)
        self.assertEqual(len(detail.inspection.features), 7)
        self.assertTrue(all(item.fixture for item in detail.inspection.features))
        self.assertFalse(detail.inspection.unavailable)

        with patch.object(
            repository,
            "_read_inspection_json",
            side_effect=AssertionError("listing must not parse inspection artifacts"),
        ):
            listing = repository.list_revisions()
        self.assertEqual(len(listing.revisions), 6)
        primary = next(item for item in listing.revisions if item.revision_id == REVISION_ID)
        self.assertEqual(primary.availability, "available")
        self.assertIsNone(primary.parent_revision_id)
        self.assertEqual(primary.warning_count, 2)
        child = next(
            item for item in listing.revisions if item.revision_id == COMPARISON_REVISION_ID
        )
        self.assertEqual(child.parent_revision_id, REVISION_ID)

    def test_gate_fixtures_stop_at_their_persisted_boundary(self):
        repository = JourneyRepository(FIXTURE_ROOT)

        for scenario in GATE_SCENARIOS:
            with self.subTest(scenario=scenario["slug"]):
                slug = scenario["slug"]
                detail = repository.get_revision(
                    f"job_interface_{slug}",
                    f"rev_interface_{slug}",
                )
                expected_stages = [
                    item[0] for item in STAGES[: scenario["prior_stage_count"]]
                ] + [scenario["stage"]]
                self.assertEqual([stage.stage for stage in detail.stages], expected_stages)
                self.assertEqual(detail.stages[-1].status, scenario["status"])
                self.assertIsNone(detail.stages[-1].evidence_level)
                self.assertEqual(detail.job.status, scenario["job_status"])
                self.assertEqual(
                    detail.manifest_available,
                    scenario["manifest_available"],
                )
                self.assertIsNone(detail.package)
                self.assertTrue(detail.source.fixture)
                self.assertFalse(detail.source.physical_evidence_present)
                self.assertTrue(
                    all(stage.evidence_mode == "fixture" for stage in detail.stages)
                )
                self.assertEqual(len(detail.stages[-1].findings), 1)
                self.assertEqual(
                    detail.stages[-1].findings[0].severity,
                    scenario["finding_severity"],
                )
                self.assertFalse(detail.inspection.reports)
                self.assertFalse(detail.inspection.profiles)
                self.assertFalse(detail.inspection.features)
    def test_artifact_download_is_checksum_verified(self):
        repository = JourneyRepository(FIXTURE_ROOT)
        artifact = repository.get_artifact(JOB_ID, REVISION_ID, "art_fixture_note")
        self.assertEqual(artifact.evidence_mode, "fixture")
        self.assertIn(b"not a fabrication package", artifact.path.read_bytes())

        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            note = (
                copied_root
                / JOB_ID
                / "revisions"
                / REVISION_ID
                / "notes"
                / "interface-fixture.txt"
            )
            note.write_text("same size is unnecessary; any mutation must fail", encoding="utf-8")
            with self.assertRaises(ArtifactIntegrityError):
                JourneyRepository(copied_root).get_artifact(
                    JOB_ID, REVISION_ID, "art_fixture_note"
                )

    def test_inspection_report_checksum_drift_is_visible_and_not_parsed(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            report = (
                copied_root
                / JOB_ID
                / "revisions"
                / REVISION_ID
                / "design"
                / "geometry_validation.json"
            )
            payload = report.read_bytes()
            mutated = payload.replace(
                b"Fixture kernel-validity row",
                b"Fixture kernel-validity ROW",
            )
            self.assertEqual(len(mutated), len(payload))
            self.assertNotEqual(mutated, payload)
            report.write_bytes(mutated)

            detail = JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)
            self.assertNotIn(
                "geometry",
                [item.report_kind for item in detail.inspection.reports],
            )
            unavailable = next(
                item
                for item in detail.inspection.unavailable
                if item.role == "geometry_validation_report"
            )
            self.assertEqual(unavailable.reason, "checksum_mismatch")

    def test_inspection_json_shape_and_size_fail_closed(self):
        cases = (
            (b"{", "invalid_json"),
            (b"x" * (2 * 1024 * 1024 + 1), "size_limit"),
        )
        for payload, expected_reason in cases:
            with self.subTest(reason=expected_reason), tempfile.TemporaryDirectory() as temporary:
                copied_root = Path(temporary) / "interface"
                shutil.copytree(FIXTURE_ROOT, copied_root)
                revision_root = copied_root / JOB_ID / "revisions" / REVISION_ID
                report = revision_root / "design" / "geometry_validation.json"
                report.write_bytes(payload)
                checksum = hashlib.sha256(payload).hexdigest()
                for record_name in ("journey.json", "manifest.json"):
                    record_path = revision_root / record_name
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    artifact = next(
                        item
                        for item in record["artifacts"]
                        if item["artifact_id"] == "art_fixture_geometry_report"
                    )
                    artifact["checksum_sha256"] = checksum
                    artifact["size_bytes"] = len(payload)
                    record_path.write_text(
                        json.dumps(record, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )

                detail = JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)
                unavailable = next(
                    item
                    for item in detail.inspection.unavailable
                    if item.role == "geometry_validation_report"
                )
                self.assertEqual(unavailable.reason, expected_reason)

    def test_path_identifiers_cannot_escape_the_root(self):
        repository = JourneyRepository(FIXTURE_ROOT)
        with self.assertRaises(RevisionNotFoundError):
            repository.get_revision("..", REVISION_ID)

    def test_missing_manifest_preserves_an_incomplete_journey(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            manifest = (
                copied_root / JOB_ID / "revisions" / REVISION_ID / "manifest.json"
            )
            manifest.unlink()
            detail = JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)
            self.assertFalse(detail.manifest_available)
            self.assertEqual(len(detail.stages), 6)

    def test_job_level_journey_can_contain_another_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            journey_path = (
                copied_root / JOB_ID / "revisions" / REVISION_ID / "journey.json"
            )
            journey = json.loads(journey_path.read_text(encoding="utf-8"))
            primary_artifact_ids = {
                item["artifact_id"]
                for item in journey["artifacts"]
                if item["revision_id"] == REVISION_ID
            }
            second_revision = dict(journey["revisions"][0])
            second_revision["revision_id"] = "rev_other"
            second_revision["number"] = 2
            second_revision["stage_run_ids"] = ["run_other"]
            journey["revisions"].append(second_revision)
            second_run = dict(journey["stage_runs"][0])
            second_run["revision_id"] = "rev_other"
            second_run["stage_run_id"] = "run_other"
            second_run["event_ids"] = []
            journey["stage_runs"].append(second_run)
            second_artifact = dict(journey["artifacts"][0])
            second_artifact["artifact_id"] = "art_other"
            second_artifact["revision_id"] = "rev_other"
            second_artifact["stage_run_id"] = "run_other"
            journey["artifacts"].append(second_artifact)
            journey_path.write_text(
                json.dumps(journey, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            detail = JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)
            artifact_ids = {
                artifact.artifact_id
                for stage in detail.stages
                for artifact in stage.artifacts
            }
            self.assertEqual(artifact_ids, primary_artifact_ids)

    def test_cross_stage_record_reference_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            journey_path = (
                copied_root / JOB_ID / "revisions" / REVISION_ID / "journey.json"
            )
            journey = json.loads(journey_path.read_text(encoding="utf-8"))
            journey["stage_runs"][0]["event_ids"] = ["evt_fixture_design"]
            journey_path.write_text(
                json.dumps(journey, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(InvalidRevisionError, "owned by another stage"):
                JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)


class InterfaceHttpTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(FIXTURE_ROOT))

    def test_health_explicitly_disables_hardware(self):
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["capabilities"]["hardware_actions"])

    def test_runtime_surface_has_no_docs_schema_or_mutation_routes(self):
        for path in ("/docs", "/redoc", "/openapi.json"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.post("/api/v1/revisions").status_code, 405)

    def test_list_detail_and_artifact_contracts(self):
        listing = self.client.get("/api/v1/revisions")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.json()["revisions"]), 6)
        self.assertEqual(listing.json()["revisions"][0]["source"]["kind"], "interface_fixture")

        detail = self.client.get(f"/api/v1/revisions/{JOB_ID}/{REVISION_ID}")
        self.assertEqual(detail.status_code, 200)
        payload = detail.json()
        self.assertEqual(payload["schema_version"], "1.2.0")
        self.assertEqual(
            [stage["stage"] for stage in payload["stages"]],
            [item[0] for item in STAGES],
        )
        self.assertEqual(
            payload["package"]["allowed_claim"],
            "Interface fixture only — no fabrication evidence.",
        )
        self.assertEqual(len(payload["inspection"]["reports"]), 3)
        self.assertEqual(len(payload["inspection"]["profiles"]), 4)

        artifact = self.client.get(
            f"/api/v1/revisions/{JOB_ID}/{REVISION_ID}/artifacts/art_fixture_note"
        )
        self.assertEqual(artifact.status_code, 200)
        self.assertEqual(artifact.headers["x-ariad-evidence-mode"], "fixture")
        self.assertEqual(artifact.headers["x-ariad-hardware-action"], "false")

    def test_missing_and_invalid_revisions_do_not_look_successful(self):
        missing = self.client.get("/api/v1/revisions/job_missing/rev_missing")
        self.assertEqual(missing.status_code, 404)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            revision = root / "job_bad" / "revisions" / "rev_bad"
            revision.mkdir(parents=True)
            (revision / "journey.json").write_text("{}", encoding="utf-8")
            response = TestClient(create_app(root)).get(
                "/api/v1/revisions/job_bad/rev_bad"
            )
            self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
