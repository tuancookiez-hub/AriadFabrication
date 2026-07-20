from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from ariad_fabrication.domain import (
    Approval,
    ApprovalStatus,
    Artifact,
    BoundingBox,
    Decision,
    DecisionActor,
    EvidenceLevel,
    FabricationJourney,
    FabricationStage,
    Finding,
    FindingSeverity,
    Job,
    PartSpec,
    SpecStatus,
    StageStatus,
    StageRun,
    SupportPolicy,
    transition_stage_run,
)


ROOT = Path(__file__).resolve().parents[1]


def confirmed_spec() -> PartSpec:
    return PartSpec(
        name="Trace fixture",
        purpose="Exercise journey records",
        part_type="fixture",
        bounding_box=BoundingBox(20, 10, 5),
        material="PETG",
        status=SpecStatus.CONFIRMED,
        tolerance_mm=0.2,
        support_policy=SupportPolicy.AVOID,
        source="test",
    )


class JourneyContractTests(unittest.TestCase):
    def test_event_emitted_from_terminal_snapshot_uses_completion_boundary(self):
        journey = FabricationJourney.create("Complete a Brief")
        run = journey.add_stage_run(FabricationStage.BRIEF)
        run = journey.replace_stage_run(
            transition_stage_run(run, StageStatus.RUNNING, at="2026-07-16T00:00:00+00:00")
        )
        run = journey.replace_stage_run(
            transition_stage_run(
                run,
                StageStatus.PASSED,
                evidence_level=EvidenceLevel.R0,
                at="2026-07-16T00:01:00+00:00",
            )
        )

        event = journey.emit_event(run.stage_run_id, "spec_validated", "Brief passed")

        self.assertEqual(event.timestamp, run.completed_at)
        self.assertEqual(event.status, StageStatus.PASSED)

    def test_events_and_manifest_are_traceable_and_schema_valid(self):
        journey = FabricationJourney.create("Build the trace fixture")
        revision = journey.add_revision(confirmed_spec(), reason="Initial confirmed spec")
        run = journey.add_stage_run(
            FabricationStage.DESIGN,
            revision_id=revision.revision_id,
            tool_name="cad_fixture",
            tool_version="1.0.0",
        )
        run = journey.replace_stage_run(
            transition_stage_run(run, StageStatus.RUNNING, at="2026-07-16T00:00:00+00:00")
        )
        event = journey.emit_event(run.stage_run_id, "cad_kernel_completed", "Solid created")

        artifact = journey.add_artifact(
            Artifact(
                job_id=journey.job.job_id,
                revision_id=revision.revision_id,
                stage_run_id=run.stage_run_id,
                role="editable_geometry",
                path="part.step",
                media_type="model/step",
                checksum_sha256="0" * 64,
                producer="cad_fixture",
                producer_version="1.0.0",
            )
        )
        finding = journey.add_finding(
            Finding(
                job_id=journey.job.job_id,
                revision_id=revision.revision_id,
                stage_run_id=run.stage_run_id,
                code="geometry.example",
                title="Example checked feature",
                severity=FindingSeverity.INFO,
                evidence="The fixture query returned one solid body.",
            )
        )
        decision = journey.add_decision(
            Decision(
                job_id=journey.job.job_id,
                revision_id=revision.revision_id,
                stage_run_id=run.stage_run_id,
                question="Which coordinate system should be canonical?",
                choice="Z-up",
                rationale="It matches the benchmark specification.",
                actor=DecisionActor.SYSTEM,
            )
        )
        approval = journey.add_approval(
            Approval(
                job_id=journey.job.job_id,
                revision_id=revision.revision_id,
                stage_run_id=run.stage_run_id,
                boundary="accept_design_warning",
            )
        )
        run = journey.get_stage_run(run.stage_run_id)
        journey.replace_stage_run(
            transition_stage_run(
                run,
                StageStatus.PASSED,
                evidence_level=EvidenceLevel.R1,
                at="2026-07-16T00:01:00+00:00",
            )
        )

        revision = journey.get_revision(revision.revision_id)
        manifest = journey.manifest_for_revision(revision.revision_id)
        serialized = manifest.to_dict()
        schema = json.loads(
            (ROOT / "schemas" / "v1" / "artifact-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(serialized)
        event_schema = json.loads(
            (ROOT / "schemas" / "v1" / "journey-event.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(event_schema)
        Draft202012Validator(
            event_schema,
            format_checker=FormatChecker(),
        ).validate(event.to_dict())

        self.assertIn(run.stage_run_id, revision.stage_run_ids)
        self.assertIn(event.event_id, journey.get_stage_run(run.stage_run_id).event_ids)
        self.assertIn(artifact.artifact_id, journey.get_stage_run(run.stage_run_id).artifact_ids)
        self.assertEqual(serialized["findings"][0]["finding_id"], finding.finding_id)
        self.assertEqual(serialized["decisions"][0]["decision_id"], decision.decision_id)
        self.assertEqual(serialized["approvals"][0]["approval_id"], approval.approval_id)
        json.dumps(journey.to_dict())

        with self.assertRaisesRegex(ValueError, "duplicate artifact_id"):
            journey.add_artifact(artifact)
        self.assertEqual(len(journey.artifacts), 1)
        self.assertEqual(journey.get_stage_run(run.stage_run_id).artifact_ids, (artifact.artifact_id,))

        with self.assertRaises(FrozenInstanceError):
            event.message = "rewritten"

    def test_artifact_rejects_path_traversal(self):
        with self.assertRaisesRegex(ValueError, "safe relative path"):
            Artifact(
                job_id="job_test",
                revision_id="rev_test",
                stage_run_id="run_test",
                role="bad",
                path="../outside.step",
                media_type="model/step",
                checksum_sha256="0" * 64,
                producer="test",
                producer_version="1",
            )

    def test_record_metadata_must_be_json_safe(self):
        with self.assertRaisesRegex(ValueError, "unsupported value"):
            FabricationJourney.create("test", metadata={"bad": object()})

        with self.assertRaisesRegex(ValueError, "keys must be strings"):
            FabricationJourney.create("test", metadata={1: "not a JSON key"})

    def test_trace_record_text_does_not_coerce_non_strings(self):
        with self.assertRaisesRegex(ValueError, "request must be a string"):
            FabricationJourney.create(42)  # type: ignore[arg-type]

        with self.assertRaisesRegex(ValueError, "stage summary must be a string"):
            StageRun(
                job_id="job_test",
                stage=FabricationStage.BRIEF,
                summary=False,  # type: ignore[arg-type]
            )

    def test_trace_record_chronology_is_timezone_aware_and_ordered(self):
        with self.assertRaisesRegex(ValueError, "include a timezone"):
            Job(request="test", created_at="2026-07-16T08:00:00")

        with self.assertRaisesRegex(ValueError, "updated_at cannot precede"):
            Job(
                request="test",
                created_at="2026-07-16T08:00:00+00:00",
                updated_at="2026-07-16T07:59:59+00:00",
            )

        with self.assertRaisesRegex(ValueError, "completed_at cannot precede"):
            StageRun(
                job_id="job_test",
                stage=FabricationStage.BRIEF,
                status=StageStatus.PASSED,
                evidence_level=EvidenceLevel.R0,
                started_at="2026-07-16T08:00:01+00:00",
                completed_at="2026-07-16T08:00:00+00:00",
            )

        with self.assertRaisesRegex(ValueError, "require a completion time"):
            StageRun(
                job_id="job_test",
                stage=FabricationStage.BRIEF,
                status=StageStatus.CANCELLED,
            )

        with self.assertRaisesRegex(ValueError, "decided_at cannot precede"):
            Approval(
                job_id="job_test",
                revision_id="rev_test",
                boundary="review",
                status=ApprovalStatus.GRANTED,
                requested_at="2026-07-16T08:00:01+00:00",
                decided_at="2026-07-16T08:00:00+00:00",
                decided_by=DecisionActor.USER,
            )


if __name__ == "__main__":
    unittest.main()
