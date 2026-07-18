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
from ariad_fabrication.codex_conversation import ConversationEvent, ConversationEventType
from ariad_fabrication.local_codex import LocalCodexSnapshot, LocalCodexStatus


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
        self.assertEqual(detail.schema_version, "1.13.0")
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
        self.assertTrue(listing.window.discovery_complete)
        self.assertFalse(listing.window.snapshot_consistent)
        self.assertEqual(listing.window.ordering, "job_id_revision_id_ascending")
        self.assertEqual(listing.window.observed_candidate_count, 6)
        self.assertEqual(listing.window.returned_count, 6)
        self.assertEqual(listing.window.observed_omitted_count, 0)
        self.assertIsNone(listing.window.next_offset)
        self.assertFalse(listing.window.truncation_reasons)
        self.assertIn("not evidence", listing.window.claim_boundary)
        self.assertIn("not a snapshot", listing.window.claim_boundary)
        primary = next(item for item in listing.revisions if item.revision_id == REVISION_ID)
        self.assertEqual(primary.availability, "available")
        self.assertIsNone(primary.parent_revision_id)
        self.assertEqual(primary.warning_count, 2)
        child = next(
            item for item in listing.revisions if item.revision_id == COMPARISON_REVISION_ID
        )
        self.assertEqual(child.parent_revision_id, REVISION_ID)

    def test_revision_listing_pages_only_the_observed_bounded_window(self):
        repository = JourneyRepository(FIXTURE_ROOT)
        original_get_revision = repository._get_revision

        with patch.object(
            repository,
            "_get_revision",
            wraps=original_get_revision,
        ) as get_revision:
            listing = repository.list_revisions(offset=2, limit=2)

        self.assertEqual(get_revision.call_count, 2)
        self.assertEqual(len(listing.revisions), 2)
        self.assertTrue(listing.window.discovery_complete)
        self.assertEqual(listing.window.offset, 2)
        self.assertEqual(listing.window.limit, 2)
        self.assertEqual(listing.window.observed_candidate_count, 6)
        self.assertEqual(listing.window.returned_count, 2)
        self.assertEqual(listing.window.observed_omitted_count, 4)
        self.assertEqual(listing.window.next_offset, 4)
        self.assertEqual(listing.window.truncation_reasons, ["window_limit"])

    def test_revision_discovery_reports_safety_ceiling_without_claiming_completeness(self):
        repository = JourneyRepository(FIXTURE_ROOT)

        with patch(
            "ariad_fabrication.api.repository.MAX_REVISION_CANDIDATES",
            2,
        ):
            listing = repository.list_revisions(limit=2)

        self.assertFalse(listing.window.discovery_complete)
        self.assertEqual(listing.window.observed_candidate_count, 2)
        self.assertEqual(listing.window.max_candidates, 2)
        self.assertIn("candidate_limit", listing.window.truncation_reasons)
        self.assertIn("omitted revisions", listing.window.claim_boundary)

    def test_revision_discovery_bounds_directory_entries(self):
        repository = JourneyRepository(FIXTURE_ROOT)

        with patch(
            "ariad_fabrication.api.repository.MAX_REVISION_DISCOVERY_ENTRIES",
            1,
        ):
            listing = repository.list_revisions()

        self.assertFalse(listing.window.discovery_complete)
        self.assertEqual(listing.window.directory_entries_examined, 1)
        self.assertEqual(listing.window.max_directory_entries, 1)
        self.assertIn("directory_entry_limit", listing.window.truncation_reasons)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = JourneyRepository(root / "missing").list_revisions()
            self.assertTrue(missing.window.discovery_complete)
            self.assertEqual(missing.window.observed_candidate_count, 0)

            file_root = root / "not-a-directory"
            file_root.write_text("not a run tree", encoding="utf-8")
            not_directory = JourneyRepository(file_root).list_revisions()
            self.assertFalse(not_directory.window.discovery_complete)
            self.assertIn("filesystem_error", not_directory.window.truncation_reasons)

        with patch(
            "ariad_fabrication.api.repository.os.scandir",
            side_effect=PermissionError("denied"),
        ):
            unreadable = JourneyRepository(FIXTURE_ROOT).list_revisions()
        self.assertFalse(unreadable.window.discovery_complete)
        self.assertIn("filesystem_error", unreadable.window.truncation_reasons)
        self.assertIsNotNone(unreadable.window.error)

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
        self.assertIn(b"not a fabrication package", artifact.content)
        self.assertEqual(artifact.size_bytes, len(artifact.content))

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

    def test_repository_file_reads_use_bounded_snapshots(self):
        repository = JourneyRepository(FIXTURE_ROOT)
        with (
            patch.object(
                Path,
                "read_text",
                side_effect=AssertionError("repository must not use unbounded read_text"),
            ),
            patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError("repository must not use unbounded read_bytes"),
            ),
        ):
            detail = repository.get_revision(JOB_ID, REVISION_ID)
            artifact = repository.get_artifact(JOB_ID, REVISION_ID, "art_fixture_note")

        self.assertEqual(detail.revision.revision_id, REVISION_ID)
        self.assertGreater(len(artifact.content), 0)

    def test_root_json_size_and_nonfinite_values_fail_closed(self):
        with patch("ariad_fabrication.api.repository._MAX_JSON_BYTES", 64):
            with self.assertRaisesRegex(InvalidRevisionError, "size limit"):
                JourneyRepository(FIXTURE_ROOT).get_revision(JOB_ID, REVISION_ID)

        with patch("ariad_fabrication.api.repository._MAX_JSON_NODES", 10):
            with self.assertRaisesRegex(InvalidRevisionError, "complexity limit"):
                JourneyRepository(FIXTURE_ROOT).get_revision(JOB_ID, REVISION_ID)

        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            journey_path = (
                copied_root / JOB_ID / "revisions" / REVISION_ID / "journey.json"
            )
            journey = json.loads(journey_path.read_text(encoding="utf-8"))
            journey["job"]["metadata"]["nonfinite"] = float("nan")
            journey_path.write_text(
                json.dumps(journey, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(InvalidRevisionError, "bounded UTF-8 JSON"):
                JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)

        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            journey_path = (
                copied_root / JOB_ID / "revisions" / REVISION_ID / "journey.json"
            )
            duplicate = journey_path.read_text(encoding="utf-8").replace(
                '{\n  "approvals":',
                '{\n  "schema_version": "1.0.0",\n  "approvals":',
                1,
            )
            journey_path.write_text(duplicate, encoding="utf-8")

            with self.assertRaisesRegex(InvalidRevisionError, "bounded UTF-8 JSON"):
                JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)

    def test_boolean_and_numeric_strings_are_not_coerced_into_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            package_path = (
                copied_root
                / JOB_ID
                / "revisions"
                / REVISION_ID
                / "fabrication"
                / "package.json"
            )
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["gcode_summary"] = {"filament_mass_g": "NaN"}
            package_path.write_text(
                json.dumps(package, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(InvalidRevisionError, "must be a number"):
                JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)

        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            revision_root = copied_root / JOB_ID / "revisions" / REVISION_ID
            for record_name in ("journey.json", "manifest.json"):
                record_path = revision_root / record_name
                record = json.loads(record_path.read_text(encoding="utf-8"))
                record["findings"][0]["resolved"] = "false"
                record_path.write_text(
                    json.dumps(record, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(InvalidRevisionError, "finding.resolved"):
                JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)

    def test_lifecycle_vocabularies_and_cross_field_states_fail_closed(self):
        cases = (
            (
                "job status",
                ("job", "status"),
                "physically_complete",
                "journey.job.status has unsupported value",
            ),
            (
                "revision ownership",
                ("revisions", 0, "job_id"),
                "job_other",
                "revision ownership does not match",
            ),
            (
                "stage kind",
                ("stage_runs", 0, "stage"),
                "magic_modeling",
                "stage.stage has unsupported value",
            ),
            (
                "stage status",
                ("stage_runs", 0, "status"),
                "printable",
                "stage.status has unsupported value",
            ),
            (
                "stage evidence",
                ("stage_runs", 0, "evidence_level"),
                "R99",
                "stage.evidence_level has unsupported value",
            ),
            (
                "event status",
                ("events", 0, "status"),
                "done",
                "event.status has unsupported value",
            ),
            (
                "final event state",
                ("events", 0, "status"),
                "running",
                "final stage event status does not match",
            ),
            (
                "finding severity",
                ("findings", 0, "severity"),
                "success",
                "finding.severity has unsupported value",
            ),
            (
                "fixture evidence mode",
                ("stage_runs", 0, "evidence_mode"),
                "real",
                "fixture stages must remain fixture evidence",
            ),
            (
                "event stage ownership",
                ("events", 0, "stage"),
                "manufacturing",
                "event stage does not match",
            ),
            (
                "finding resolution",
                ("findings", 0, "resolved"),
                True,
                "resolved findings require",
            ),
        )
        for label, parts, value, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                copied_root = Path(temporary) / "interface"
                shutil.copytree(FIXTURE_ROOT, copied_root)
                revision_root = copied_root / JOB_ID / "revisions" / REVISION_ID
                (revision_root / "manifest.json").unlink()
                journey_path = revision_root / "journey.json"
                journey = json.loads(journey_path.read_text(encoding="utf-8"))
                target = journey
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = value
                journey_path.write_text(
                    json.dumps(journey, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                repository = JourneyRepository(copied_root)
                with self.assertRaisesRegex(InvalidRevisionError, expected):
                    repository.get_revision(JOB_ID, REVISION_ID)
                if label == "job status":
                    with self.assertRaisesRegex(InvalidRevisionError, expected):
                        repository.get_artifact(
                            JOB_ID, REVISION_ID, "art_fixture_note"
                        )

    def test_persisted_text_and_timestamp_types_fail_closed(self):
        cases = (
            (
                "job title",
                ("job", "title"),
                42,
                "journey.job.title must be a string",
            ),
            (
                "stage summary",
                ("stage_runs", 0, "summary"),
                False,
                "stage.summary must be a string",
            ),
            (
                "event message",
                ("events", 0, "message"),
                ["looks", "valid"],
                "event.message must be a string",
            ),
            (
                "optional finding text",
                ("findings", 0, "remediation"),
                7,
                "finding.remediation must be a string or null",
            ),
            (
                "artifact producer",
                ("artifacts", 0, "producer"),
                True,
                "artifact.producer must be a string",
            ),
            (
                "numeric timestamp",
                ("job", "created_at"),
                1_721_113_200,
                "journey.job.created_at must be a string",
            ),
            (
                "naive timestamp",
                ("job", "created_at"),
                "2026-07-16T08:00:00",
                "journey.job.created_at must include a timezone",
            ),
            (
                "invalid timestamp",
                ("events", 0, "timestamp"),
                "sometime later",
                "event.timestamp must be an ISO-8601 timestamp",
            ),
        )
        for label, parts, value, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                copied_root = Path(temporary) / "interface"
                shutil.copytree(FIXTURE_ROOT, copied_root)
                revision_root = copied_root / JOB_ID / "revisions" / REVISION_ID
                (revision_root / "manifest.json").unlink()
                journey_path = revision_root / "journey.json"
                journey = json.loads(journey_path.read_text(encoding="utf-8"))
                target = journey
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = value
                journey_path.write_text(
                    json.dumps(journey, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                repository = JourneyRepository(copied_root)
                with self.assertRaisesRegex(InvalidRevisionError, expected):
                    repository.get_revision(JOB_ID, REVISION_ID)
                if label == "job title":
                    with self.assertRaisesRegex(InvalidRevisionError, expected):
                        repository.get_artifact(
                            JOB_ID, REVISION_ID, "art_fixture_note"
                        )

    def test_persisted_temporal_ordering_fails_closed(self):
        cases = (
            (
                "job chronology",
                ("job", "updated_at"),
                "2026-07-16T07:59:59+00:00",
                "journey.job.updated_at cannot precede",
            ),
            (
                "revision chronology",
                ("revisions", 0, "created_at"),
                "2026-07-16T07:59:59+00:00",
                "revision.created_at cannot precede",
            ),
            (
                "stage chronology",
                ("stage_runs", 0, "completed_at"),
                "2026-07-16T07:59:59+00:00",
                "stage.completed_at cannot precede stage.started_at",
            ),
            (
                "event upper bound",
                ("events", 0, "timestamp"),
                "2026-07-16T08:00:01+00:00",
                "event.timestamp cannot follow journey.job.updated_at",
            ),
        )
        for label, parts, value, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                copied_root = Path(temporary) / "interface"
                shutil.copytree(FIXTURE_ROOT, copied_root)
                revision_root = copied_root / JOB_ID / "revisions" / REVISION_ID
                (revision_root / "manifest.json").unlink()
                journey_path = revision_root / "journey.json"
                journey = json.loads(journey_path.read_text(encoding="utf-8"))
                target = journey
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = value
                journey_path.write_text(
                    json.dumps(journey, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(InvalidRevisionError, expected):
                    JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)

        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            manifest_path = (
                copied_root
                / JOB_ID
                / "revisions"
                / REVISION_ID
                / "manifest.json"
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["generated_at"] = "2026-07-16T07:59:59+00:00"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                InvalidRevisionError,
                "manifest.generated_at cannot precede journey.job.updated_at",
            ):
                JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)

    def test_package_classification_and_hardware_states_fail_closed(self):
        cases = (
            (("status",), "physically_printable", "package.status has unsupported value"),
            (
                ("hardware", "print_started"),
                True,
                "hardware.print_started must remain false",
            ),
            (
                ("evidence_level",),
                "R4",
                "fixture packages require null evidence",
            ),
            (
                ("classification",),
                "printer_independent_fabrication_package",
                "package classification does not match",
            ),
            (
                ("allowed_claim",),
                42,
                "package.allowed_claim must be a string",
            ),
        )
        for parts, value, expected in cases:
            with self.subTest(parts=parts), tempfile.TemporaryDirectory() as temporary:
                copied_root = Path(temporary) / "interface"
                shutil.copytree(FIXTURE_ROOT, copied_root)
                package_path = (
                    copied_root
                    / JOB_ID
                    / "revisions"
                    / REVISION_ID
                    / "fabrication"
                    / "package.json"
                )
                package = json.loads(package_path.read_text(encoding="utf-8"))
                target = package
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = value
                package_path.write_text(
                    json.dumps(package, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(InvalidRevisionError, expected):
                    JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)

    def test_unsupported_report_and_profile_states_remain_unavailable(self):
        cases = (
            (
                "geometry_validation_report",
                Path("design") / "geometry_validation.json",
                "art_fixture_geometry_report",
                "status",
                "physically_passed",
            ),
            (
                "printer_profile",
                Path("profiles") / "printer.json",
                "art_fixture_printer_profile",
                "status",
                "calibrated",
            ),
        )
        for role, relative, artifact_id, field, value in cases:
            with self.subTest(role=role), tempfile.TemporaryDirectory() as temporary:
                copied_root = Path(temporary) / "interface"
                shutil.copytree(FIXTURE_ROOT, copied_root)
                revision_root = copied_root / JOB_ID / "revisions" / REVISION_ID
                source_path = revision_root / relative
                source = json.loads(source_path.read_text(encoding="utf-8"))
                source[field] = value
                payload = (
                    json.dumps(source, indent=2, sort_keys=True) + "\n"
                ).encode("utf-8")
                source_path.write_bytes(payload)
                checksum = hashlib.sha256(payload).hexdigest()
                for record_name in ("journey.json", "manifest.json"):
                    record_path = revision_root / record_name
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    artifact = next(
                        item
                        for item in record["artifacts"]
                        if item["artifact_id"] == artifact_id
                    )
                    artifact["checksum_sha256"] = checksum
                    artifact["size_bytes"] = len(payload)
                    record_path.write_text(
                        json.dumps(record, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )

                detail = JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)
                unavailable = next(
                    item for item in detail.inspection.unavailable if item.role == role
                )
                self.assertEqual(unavailable.reason, "unsupported_shape")
                with self.assertRaisesRegex(
                    ArtifactIntegrityError,
                    "failed semantic validation",
                ):
                    JourneyRepository(copied_root).get_artifact(
                        JOB_ID,
                        REVISION_ID,
                        artifact_id,
                    )

    def test_inspection_text_and_numbers_do_not_coerce(self):
        cases = (
            (("checks", 0, "description"), 42),
            (("checks", 1, "tolerance_mm"), "0.2"),
        )
        for parts, value in cases:
            with self.subTest(parts=parts), tempfile.TemporaryDirectory() as temporary:
                copied_root = Path(temporary) / "interface"
                shutil.copytree(FIXTURE_ROOT, copied_root)
                revision_root = copied_root / JOB_ID / "revisions" / REVISION_ID
                source_path = revision_root / "design" / "geometry_validation.json"
                source = json.loads(source_path.read_text(encoding="utf-8"))
                target = source
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = value
                payload = (
                    json.dumps(source, indent=2, sort_keys=True) + "\n"
                ).encode("utf-8")
                source_path.write_bytes(payload)
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
                self.assertEqual(unavailable.reason, "unsupported_shape")

    def test_decisions_and_approvals_are_typed_and_manifest_matched(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            revision_root = copied_root / JOB_ID / "revisions" / REVISION_ID
            journey_path = revision_root / "journey.json"
            manifest_path = revision_root / "manifest.json"
            journey = json.loads(journey_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            stage_id = journey["stage_runs"][0]["stage_run_id"]
            decision = {
                "decision_id": "decision_fixture_typed",
                "job_id": JOB_ID,
                "revision_id": REVISION_ID,
                "stage_run_id": stage_id,
                "question": "Use the fixture boundary?",
                "choice": "Keep it explicit",
                "rationale": "Fixtures cannot become evidence.",
                "actor": "system",
                "alternatives": ["Hide the boundary"],
                "created_at": "2026-07-16T08:00:00+00:00",
                "data": {},
            }
            approval = {
                "approval_id": "approval_fixture_typed",
                "job_id": JOB_ID,
                "revision_id": REVISION_ID,
                "stage_run_id": stage_id,
                "boundary": "No hardware action",
                "status": "requested",
                "requested_by": "system",
                "rationale": "No approval has been granted.",
                "requested_at": "2026-07-16T08:00:00+00:00",
                "decided_at": None,
                "decided_by": None,
            }
            journey["decisions"].append(decision)
            journey["approvals"].append(approval)
            journey["stage_runs"][0]["decision_ids"].append(decision["decision_id"])
            journey["stage_runs"][0]["approval_ids"].append(approval["approval_id"])
            manifest["decisions"].append(decision)
            manifest["approvals"].append(approval)
            for path, value in ((journey_path, journey), (manifest_path, manifest)):
                path.write_text(
                    json.dumps(value, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

            detail = JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)
            self.assertEqual(detail.stages[0].decisions[0].actor, "system")
            self.assertEqual(detail.stages[0].approvals[0].status, "requested")

            journey["decisions"][-1]["actor"] = "assistant"
            manifest["decisions"][-1]["actor"] = "assistant"
            for path, value in ((journey_path, journey), (manifest_path, manifest)):
                path.write_text(
                    json.dumps(value, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            with self.assertRaisesRegex(InvalidRevisionError, "decision.actor"):
                JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)

    def test_approval_decision_cannot_precede_its_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            revision_root = copied_root / JOB_ID / "revisions" / REVISION_ID
            journey_path = revision_root / "journey.json"
            manifest_path = revision_root / "manifest.json"
            journey = json.loads(journey_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            journey["job"]["created_at"] = "2026-07-16T07:00:00+00:00"
            journey["job"]["updated_at"] = "2026-07-16T09:00:00+00:00"
            manifest["generated_at"] = "2026-07-16T09:00:00+00:00"
            stage_id = journey["stage_runs"][0]["stage_run_id"]
            approval = {
                "approval_id": "approval_fixture_reversed_time",
                "job_id": JOB_ID,
                "revision_id": REVISION_ID,
                "stage_run_id": stage_id,
                "boundary": "Review the persisted chronology",
                "status": "granted",
                "requested_by": "system",
                "rationale": "The decision cannot happen first.",
                "requested_at": "2026-07-16T08:30:00+00:00",
                "decided_at": "2026-07-16T08:15:00+00:00",
                "decided_by": "user",
            }
            journey["approvals"].append(approval)
            journey["stage_runs"][0]["approval_ids"].append(
                approval["approval_id"]
            )
            manifest["approvals"].append(approval)
            for path, value in ((journey_path, journey), (manifest_path, manifest)):
                path.write_text(
                    json.dumps(value, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(
                InvalidRevisionError,
                "approval.decided_at cannot precede approval.requested_at",
            ):
                JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)

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
            (b'{"checks":[],"checks":[]}', "invalid_json"),
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

        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            journey_path = (
                copied_root / JOB_ID / "revisions" / REVISION_ID / "journey.json"
            )
            journey = json.loads(journey_path.read_text(encoding="utf-8"))
            duplicate_event = dict(journey["events"][0])
            duplicate_event["event_id"] = "evt_fixture_brief_duplicate_sequence"
            journey["events"].append(duplicate_event)
            journey["stage_runs"][0]["event_ids"].append(
                duplicate_event["event_id"]
            )
            journey_path.write_text(
                json.dumps(journey, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(InvalidRevisionError, "duplicate sequence"):
                JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)

        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            journey_path = (
                copied_root / JOB_ID / "revisions" / REVISION_ID / "journey.json"
            )
            journey = json.loads(journey_path.read_text(encoding="utf-8"))
            journey["events"][1]["sequence"] = journey["events"][0]["sequence"]
            journey_path.write_text(
                json.dumps(journey, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                InvalidRevisionError, "revision events cannot contain duplicate sequence"
            ):
                JourneyRepository(copied_root).get_revision(JOB_ID, REVISION_ID)


class InterfaceHttpTests(unittest.TestCase):
    def setUp(self):
        self.project_temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.project_temporary.cleanup)
        self.client = TestClient(
            create_app(FIXTURE_ROOT, projects_root=Path(self.project_temporary.name) / "projects")
        )

    def test_health_explicitly_disables_hardware(self):
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["capabilities"]["hardware_actions"])
        self.assertFalse(response.json()["capabilities"]["read_only"])
        self.assertTrue(response.json()["capabilities"]["project_intent_persistence"])
        self.assertFalse(response.json()["capabilities"]["fabrication_execution"])

    def test_project_intent_requires_session_and_explicit_confirmation(self):
        payload = {"title": "Floating airship", "prompt": "A 120 mm display model", "confirmed": True}
        self.assertEqual(self.client.post("/api/v1/projects", json=payload).status_code, 403)
        token = self.client.get("/api/v1/session").json()["session_token"]
        headers = {"X-Ariad-Session": token}
        unconfirmed = self.client.post(
            "/api/v1/projects", json={**payload, "confirmed": False}, headers=headers
        )
        self.assertEqual(unconfirmed.status_code, 422)
        created = self.client.post("/api/v1/projects", json=payload, headers=headers)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["status"], "intent_confirmed")
        self.assertIsNone(created.json()["brief_evidence_level"])
        self.assertFalse(created.json()["fabrication_started"])
        listing = self.client.get("/api/v1/projects", headers=headers)
        self.assertEqual(len(listing.json()["projects"]), 1)
        self.assertFalse(listing.json()["fabrication_started"])

    def test_codex_status_is_sanitized_and_does_not_start_work(self):
        response = self.client.get("/api/v1/codex/status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.13.0")
        self.assertEqual(payload["status"], "unavailable")
        self.assertIsNone(payload["authentication"])
        self.assertFalse(payload["conversation_available"])
        self.assertEqual(payload["tools_registered"], 0)
        self.assertFalse(payload["conversation_started"])
        self.assertFalse(payload["workspace_mutated"])
        self.assertFalse(payload["hardware_actions"])
        self.assertNotIn("email", str(payload).lower())
        self.assertNotIn("access_token", str(payload).lower())

    def test_browser_session_protects_account_using_conversation_routes(self):
        session = self.client.get("/api/v1/session")
        self.assertEqual(session.status_code, 200)
        self.assertEqual(session.headers["cache-control"], "no-store")
        token = session.json()["session_token"]
        self.assertGreaterEqual(len(token), 32)
        self.assertFalse(session.json()["codex_credentials_exposed"])

        unauthenticated = self.client.post(
            "/api/v1/codex/turns",
            json={"prompt": "Hello"},
        )
        self.assertEqual(unauthenticated.status_code, 403)
        unavailable = self.client.post(
            "/api/v1/codex/turns",
            json={"prompt": "Hello"},
            headers={"X-Ariad-Session": token},
        )
        self.assertEqual(unavailable.status_code, 503)

    def test_conversation_routes_expose_only_curated_no_tool_events(self):
        class FakeConversation:
            active_turn_id = "turn_demo"

            def start_turn(self, prompt):
                self.prompt = prompt
                return "turn_demo"

            def events_after(self, sequence):
                return (
                    ConversationEvent(
                        sequence + 1,
                        ConversationEventType.ASSISTANT_TEXT_DELTA,
                        "turn_demo",
                        "Hello from Codex",
                    ),
                )

            def cancel_active_turn(self):
                return True

        app = create_app(FIXTURE_ROOT)
        app.state.codex_snapshot = LocalCodexSnapshot(
            status=LocalCodexStatus.READY,
            cli_version="codex-cli 0.144.5",
            authentication="chatgpt",
            reason="Ready for test conversation.",
            conversation_available=True,
        )
        app.state.codex_executable = Path("configured-codex.exe")
        app.state.codex_workspace = Path("configured-workspace")
        app.state.codex_conversation = FakeConversation()
        client = TestClient(app)
        token = client.get("/api/v1/session").json()["session_token"]
        headers = {"X-Ariad-Session": token}

        started = client.post(
            "/api/v1/codex/turns",
            json={"prompt": "Design an airship"},
            headers=headers,
        )
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json()["turn_id"], "turn_demo")
        self.assertEqual(started.json()["tools_registered"], 3)
        self.assertFalse(started.json()["workspace_mutation_enabled"])

        events = client.get("/api/v1/codex/events?after=0", headers=headers)
        self.assertEqual(events.status_code, 200)
        self.assertEqual(events.json()["events"][0]["text"], "Hello from Codex")
        self.assertEqual(events.json()["tools_registered"], 3)
        self.assertFalse(events.json()["hardware_actions"])
        cancelled = client.post("/api/v1/codex/cancel", headers=headers)
        self.assertTrue(cancelled.json()["accepted"])

    def test_stateless_intake_accepts_an_idea_without_model_or_execution(self):
        response = self.client.post(
            "/api/v1/intake",
            json={"prompt": "Create a decorative floating air warship ✨"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.13.0")
        self.assertEqual(payload["intake"]["prompt"], "Create a decorative floating air warship ✨")
        self.assertEqual(len(payload["intake"]["prompt_sha256"]), 64)
        self.assertFalse(payload["provider"]["configured"])
        self.assertEqual(payload["provider"]["model"], "gpt-5.6-sol")
        self.assertEqual(payload["route"]["status"], "needs_input")
        self.assertEqual(payload["route"]["available_targets"], [])
        self.assertFalse(payload["persisted"])
        self.assertFalse(payload["executed"])
        self.assertFalse(payload["route"]["hardware_actions"])
        self.assertFalse(payload["route"]["physical_validation"])

    def test_stateless_intake_bounds_utf8_bytes_and_forbids_extra_fields(self):
        oversized = self.client.post(
            "/api/v1/intake",
            json={"prompt": "é" * 8193},
        )
        self.assertEqual(oversized.status_code, 422)
        extra = self.client.post(
            "/api/v1/intake",
            json={"prompt": "Make a bracket", "execute": True},
        )
        self.assertEqual(extra.status_code, 422)

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
        self.assertTrue(listing.json()["window"]["discovery_complete"])
        self.assertEqual(listing.json()["window"]["observed_candidate_count"], 6)

        page = self.client.get(
            "/api/v1/revisions",
            params={"offset": 2, "limit": 2},
        )
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(page.json()["revisions"]), 2)
        self.assertEqual(page.json()["window"]["offset"], 2)
        self.assertEqual(page.json()["window"]["next_offset"], 4)
        self.assertEqual(page.json()["window"]["truncation_reasons"], ["window_limit"])

        detail = self.client.get(f"/api/v1/revisions/{JOB_ID}/{REVISION_ID}")
        self.assertEqual(detail.status_code, 200)
        payload = detail.json()
        self.assertEqual(payload["schema_version"], "1.13.0")
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
        self.assertEqual(
            artifact.headers["x-ariad-integrity"],
            "sha256-verified-snapshot",
        )
        self.assertEqual(artifact.headers["x-ariad-hardware-action"], "false")

    def test_revision_list_query_bounds_fail_before_discovery(self):
        for params in (
            {"offset": -1},
            {"offset": 501},
            {"limit": 0},
            {"limit": 201},
        ):
            with self.subTest(params=params):
                with patch.object(
                    self.client.app.state.repository,
                    "_discover_revision_roots",
                    side_effect=AssertionError("invalid queries must not reach discovery"),
                ):
                    response = self.client.get("/api/v1/revisions", params=params)
                self.assertEqual(response.status_code, 422)

    def test_artifact_response_cannot_drift_after_repository_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied_root = Path(temporary) / "interface"
            shutil.copytree(FIXTURE_ROOT, copied_root)
            app = create_app(copied_root)
            repository = app.state.repository
            original_get = repository.get_artifact
            note = (
                copied_root
                / JOB_ID
                / "revisions"
                / REVISION_ID
                / "notes"
                / "interface-fixture.txt"
            )
            expected = note.read_bytes()

            def verified_then_mutated(*args):
                snapshot = original_get(*args)
                note.write_bytes(b"mutated only after the verified snapshot was captured")
                return snapshot

            with patch.object(
                repository,
                "get_artifact",
                side_effect=verified_then_mutated,
            ):
                response = TestClient(app).get(
                    f"/api/v1/revisions/{JOB_ID}/{REVISION_ID}/artifacts/art_fixture_note"
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, expected)
            self.assertEqual(response.headers["content-length"], str(len(expected)))
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(
                response.headers["etag"],
                f'"{hashlib.sha256(expected).hexdigest()}"',
            )
            self.assertTrue(
                response.headers["content-disposition"].startswith("attachment;")
            )

    def test_artifact_response_rejects_the_verified_download_ceiling(self):
        with patch(
            "ariad_fabrication.api.repository.MAX_ARTIFACT_DOWNLOAD_BYTES",
            16,
        ):
            response = self.client.get(
                f"/api/v1/revisions/{JOB_ID}/{REVISION_ID}/artifacts/art_fixture_note"
            )

        self.assertEqual(response.status_code, 413)
        self.assertIn("16-byte verified-download limit", response.json()["detail"])

    def test_artifact_response_rejects_untrusted_header_values(self):
        cases = (
            ("evidence_mode", "fixture\r\nX-Untrusted: yes"),
            ("media_type", "text/plain\r\nX-Untrusted: yes"),
        )
        for field, value in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                copied_root = Path(temporary) / "interface"
                shutil.copytree(FIXTURE_ROOT, copied_root)
                revision_root = copied_root / JOB_ID / "revisions" / REVISION_ID
                for record_name in ("journey.json", "manifest.json"):
                    record_path = revision_root / record_name
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    artifact = next(
                        item
                        for item in record["artifacts"]
                        if item["artifact_id"] == "art_fixture_note"
                    )
                    artifact[field] = value
                    record_path.write_text(
                        json.dumps(record, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )

                response = TestClient(create_app(copied_root)).get(
                    f"/api/v1/revisions/{JOB_ID}/{REVISION_ID}/artifacts/art_fixture_note"
                )

                self.assertEqual(response.status_code, 409)
                self.assertNotIn("x-untrusted", response.headers)

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
