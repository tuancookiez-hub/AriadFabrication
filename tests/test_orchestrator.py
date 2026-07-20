import json
from pathlib import Path
import unittest

from ariad_fabrication.domain import (
    BoundingBox,
    EvidenceLevel,
    PartSpec,
    SpecStatus,
    StageStatus,
    SupportPolicy,
)
from ariad_fabrication.intent_parser import IntentParseError, RuleBasedIntentParser
from ariad_fabrication.orchestrator import PipelineOrchestrator


def complete_draft() -> PartSpec:
    return PartSpec(
        name="Test bracket",
        purpose="Hold a sensor",
        part_type="bracket",
        bounding_box=BoundingBox(40, 20, 5),
        material="PETG",
        tolerance_mm=0.2,
        support_policy=SupportPolicy.AVOID,
        source="test",
    )


class FakeParser:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def parse(self, prompt):
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result


class PipelineOrchestratorTests(unittest.TestCase):
    def test_complete_draft_still_requires_explicit_confirmation(self):
        journey = PipelineOrchestrator(FakeParser([complete_draft()])).run("request")

        self.assertEqual(journey.status, "needs_input")
        self.assertEqual(journey.stage_runs[-1].status, StageStatus.NEEDS_INPUT)
        self.assertEqual(len(journey.findings), 1)
        self.assertIn("confirmation", journey.findings[0].evidence)

    def test_explicit_confirmation_reaches_only_r0(self):
        journey = PipelineOrchestrator(FakeParser([complete_draft()])).run(
            "request", confirm=True
        )

        run = journey.stage_runs[-1]
        self.assertEqual(journey.status, "ready_for_design")
        self.assertEqual(journey.spec.status, SpecStatus.CONFIRMED)
        self.assertEqual(run.status, StageStatus.PASSED)
        self.assertEqual(run.evidence_level, EvidenceLevel.R0)
        self.assertEqual(len(journey.decisions), 1)
        self.assertTrue(any(event.event_type == "spec_validated" for event in journey.events))

    def test_confirmation_cannot_hide_unknown_requirements(self):
        journey = PipelineOrchestrator(RuleBasedIntentParser()).run(
            "Create a 40 x 20 x 5 mm bracket", confirm=True
        )

        self.assertEqual(journey.status, "needs_input")
        self.assertEqual(journey.spec.status, SpecStatus.DRAFT)
        evidence = " ".join(item.evidence.lower() for item in journey.findings)
        self.assertIn("material", evidence)
        self.assertIn("tolerance", evidence)
        self.assertIn("support", evidence)

    def test_retry_creates_a_new_stage_run_instead_of_rewriting_failure(self):
        parser = FakeParser([IntentParseError("temporary failure"), complete_draft()])
        journey = PipelineOrchestrator(parser, max_attempts=2).run(
            "request", confirm=True
        )

        self.assertEqual(journey.status, "ready_for_design")
        self.assertEqual([run.attempt for run in journey.stage_runs], [1, 2])
        self.assertEqual(
            [run.status for run in journey.stage_runs],
            [StageStatus.FAILED, StageStatus.PASSED],
        )
        self.assertEqual(journey.stage_runs[0].error_message, "temporary failure")

    def test_exhausted_parser_retries_leave_a_failed_journey(self):
        parser = FakeParser([IntentParseError("bad request")])
        journey = PipelineOrchestrator(parser, max_attempts=2).run("request")

        self.assertEqual(journey.status, "failed")
        self.assertIsNone(journey.spec)
        self.assertEqual(len(journey.stage_runs), 2)
        self.assertTrue(all(run.status is StageStatus.FAILED for run in journey.stage_runs))
        self.assertEqual(len(journey.findings), 2)

    def test_hand_authored_golden_part_passes_the_same_brief_gate(self):
        root = Path(__file__).resolve().parents[1]
        mapping = json.loads(
            (root / "benchmarks" / "golden_part" / "part_spec.json").read_text(
                encoding="utf-8"
            )
        )
        spec = PartSpec.from_mapping(mapping)

        journey = PipelineOrchestrator(FakeParser([complete_draft()])).run_spec(spec)

        self.assertEqual(journey.status, "ready_for_design")
        self.assertEqual(journey.spec.name, "OpenGrow Stake Electronics Clamp v1")
        self.assertEqual(journey.stage_runs[-1].evidence_level, EvidenceLevel.R0)


if __name__ == "__main__":
    unittest.main()
