import unittest

from ariad_fabrication.domain import (
    FABRICATION_STAGES,
    EvidenceLevel,
    FabricationStage,
    StageRun,
    StageStatus,
    StageTransitionError,
    next_stage,
    previous_stage,
    transition_stage_run,
)


NOW = "2026-07-16T00:00:00+00:00"
LATER = "2026-07-16T00:01:00+00:00"


class LifecycleTests(unittest.TestCase):
    def test_stage_order_is_the_locked_seven_stage_journey(self):
        self.assertEqual(
            [stage.value for stage in FABRICATION_STAGES],
            [
                "brief",
                "design",
                "geometry_validation",
                "printability_validation",
                "slicing",
                "fabrication_package",
                "manufacturing",
            ],
        )
        self.assertIsNone(previous_stage(FabricationStage.BRIEF))
        self.assertEqual(next_stage(FabricationStage.BRIEF), FabricationStage.DESIGN)
        self.assertIsNone(next_stage(FabricationStage.MANUFACTURING))

    def test_needs_input_can_resume_and_pass(self):
        run = StageRun(job_id="job_test", stage=FabricationStage.BRIEF)
        run = transition_stage_run(run, StageStatus.RUNNING, at=NOW)
        run = transition_stage_run(run, StageStatus.NEEDS_INPUT, summary="clarify", at=NOW)
        run = transition_stage_run(run, StageStatus.RUNNING, at=LATER)
        run = transition_stage_run(
            run,
            StageStatus.PASSED,
            evidence_level=EvidenceLevel.R0,
            at=LATER,
        )

        self.assertEqual(run.status, StageStatus.PASSED)
        self.assertEqual(run.started_at, NOW)
        self.assertEqual(run.completed_at, LATER)
        self.assertEqual(run.evidence_level, EvidenceLevel.R0)

    def test_failed_run_cannot_be_restarted(self):
        run = StageRun(job_id="job_test", stage=FabricationStage.DESIGN)
        run = transition_stage_run(run, StageStatus.RUNNING, at=NOW)
        run = transition_stage_run(
            run,
            StageStatus.FAILED,
            error_message="worker failed",
            at=LATER,
        )

        with self.assertRaises(StageTransitionError):
            transition_stage_run(run, StageStatus.RUNNING, at=LATER)

    def test_failed_transition_requires_an_error(self):
        run = StageRun(job_id="job_test", stage=FabricationStage.DESIGN)
        run = transition_stage_run(run, StageStatus.RUNNING, at=NOW)

        with self.assertRaisesRegex(StageTransitionError, "error_message"):
            transition_stage_run(run, StageStatus.FAILED, at=LATER)

    def test_waiting_run_can_be_cancelled_before_execution(self):
        run = StageRun(job_id="job_test", stage=FabricationStage.MANUFACTURING)
        cancelled = transition_stage_run(run, StageStatus.CANCELLED, at=NOW)

        self.assertEqual(cancelled.status, StageStatus.CANCELLED)
        self.assertIsNone(cancelled.started_at)
        self.assertEqual(cancelled.completed_at, NOW)


if __name__ == "__main__":
    unittest.main()
