import json
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import ariad_fabrication.api.comparison as comparison_module
from ariad_fabrication.api import JourneyRepository, create_app
from ariad_fabrication.api.comparison import compare_revision_details
from ariad_fabrication.api.fixture import (
    COMPARISON_REVISION_ID,
    JOB_ID,
    REVISION_ID,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "benchmarks" / "interface"


class RevisionComparisonTests(unittest.TestCase):
    def setUp(self):
        self.repository = JourneyRepository(FIXTURE_ROOT)
        self.base = self.repository.get_revision(JOB_ID, REVISION_ID)
        self.child = self.repository.get_revision(JOB_ID, COMPARISON_REVISION_ID)

    def test_identical_revision_has_no_observed_changes(self):
        result = compare_revision_details(self.base, self.base)

        self.assertEqual(result.relationship, "same_revision")
        self.assertTrue(result.complete)
        self.assertEqual(result.total_change_count, 0)
        self.assertFalse(result.changes)
        self.assertFalse(result.summaries)

    def test_persisted_child_fixture_exposes_only_semantic_changes(self):
        result = compare_revision_details(self.base, self.child)

        self.assertEqual(result.relationship, "parent_to_child")
        self.assertTrue(result.complete)
        self.assertEqual(result.total_change_count, 12)
        self.assertEqual(
            {(item.area, item.record_key) for item in result.changes},
            {
                ("stage", "design:1"),
                ("requirement", "infill_pct"),
                ("requirement", "mating_requirements"),
                ("requirement", "name"),
                ("requirement", "notes"),
                ("feature", "stake_bore"),
                ("report", "geometry"),
                ("check", "geometry:stake_bore_diameter"),
                ("profile", "process"),
                ("artifact", "geometry_validation_report"),
                ("artifact", "interface_fixture_note"),
                ("artifact", "process_profile"),
            },
        )
        values = json.dumps(
            [item.model_dump(mode="json") for item in result.changes],
            sort_keys=True,
        )
        for volatile_field in (
            "revision_id",
            "stage_run_id",
            "artifact_id",
            "event_id",
            "created_at",
            "started_at",
            "completed_at",
        ):
            with self.subTest(field=volatile_field):
                self.assertNotIn(volatile_field, values)
        requirement_keys = {
            item.key
            for item in comparison_module._comparison_records(self.base).records
            if item.area == "requirement"
        }
        self.assertEqual(
            requirement_keys,
            set(self.base.revision.spec) - {"features"},
            "every current top-level specification field must be compared or handled as features",
        )

    def test_relationship_is_explicit_for_unrelated_jobs(self):
        unrelated = self.repository.get_revision(
            "job_interface_needs_input",
            "rev_interface_needs_input",
        )

        result = compare_revision_details(self.base, unrelated)

        self.assertEqual(result.relationship, "unrelated")
        self.assertGreater(result.total_change_count, 0)

    def test_oversized_value_is_hashed_and_marks_response_incomplete(self):
        candidate = self.base.model_copy(deep=True)
        candidate.revision.revision_id = "rev_synthetic_large"
        candidate.revision.parent_revision_id = self.base.revision.revision_id
        candidate.revision.spec["notes"] = "x" * 70_000

        result = compare_revision_details(self.base, candidate)

        change = next(item for item in result.changes if item.record_key == "notes")
        self.assertFalse(result.complete)
        self.assertEqual(result.incomplete_value_count, 1)
        self.assertFalse(change.detail_complete)
        self.assertEqual(
            change.candidate_value["comparison_unavailable"],
            "normalized record exceeds the detail limit",
        )
        self.assertEqual(len(change.candidate_value["canonical_sha256"]), 64)

    def test_change_limit_is_explicit_instead_of_silently_dropping_rows(self):
        candidate = self.base.model_copy(deep=True)
        template = candidate.inspection.features[0]
        candidate.inspection.features.extend(
            template.model_copy(update={"feature_id": f"synthetic_{index:04d}"})
            for index in range(comparison_module.MAX_COMPARISON_CHANGES + 5)
        )

        result = compare_revision_details(self.base, candidate)

        self.assertFalse(result.complete)
        self.assertEqual(result.returned_change_count, result.max_changes)
        self.assertEqual(result.omitted_change_count, 5)
        self.assertEqual(result.total_change_count, result.max_changes + 5)

    def test_input_record_limit_is_visible_even_when_observed_rows_match(self):
        with patch.object(comparison_module, "MAX_COMPARISON_RECORDS_PER_REVISION", 2):
            result = compare_revision_details(self.base, self.base)

        self.assertFalse(result.complete)
        self.assertGreater(result.base.omitted_record_count, 0)
        self.assertGreater(result.candidate.omitted_record_count, 0)
        self.assertEqual(result.max_records_per_revision, 2)


class RevisionComparisonHttpTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(FIXTURE_ROOT))

    def test_get_comparison_is_read_only_and_preserves_claim_boundaries(self):
        tracked = [
            FIXTURE_ROOT / JOB_ID / "revisions" / REVISION_ID / "journey.json",
            FIXTURE_ROOT
            / JOB_ID
            / "revisions"
            / COMPARISON_REVISION_ID
            / "journey.json",
        ]
        before = {path: path.read_bytes() for path in tracked}

        response = self.client.get(
            "/api/v1/revision-comparison",
            params={
                "base_job_id": JOB_ID,
                "base_revision_id": REVISION_ID,
                "candidate_job_id": JOB_ID,
                "candidate_revision_id": COMPARISON_REVISION_ID,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.12.0")
        self.assertEqual(payload["relationship"], "parent_to_child")
        self.assertEqual(payload["total_change_count"], 12)
        self.assertTrue(payload["capabilities"]["read_only"])
        self.assertFalse(payload["capabilities"]["hardware_actions"])
        self.assertIn("does not rerun CAD", payload["claim_boundary"])
        self.assertEqual(before, {path: path.read_bytes() for path in tracked})

    def test_missing_comparison_revision_is_not_presented_as_an_empty_diff(self):
        response = self.client.get(
            "/api/v1/revision-comparison",
            params={
                "base_job_id": JOB_ID,
                "base_revision_id": REVISION_ID,
                "candidate_job_id": JOB_ID,
                "candidate_revision_id": "rev_missing",
            },
        )

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
