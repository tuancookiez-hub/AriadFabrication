import ctypes
import json
import os
from pathlib import Path
import tempfile
import unittest

from ariad_fabrication.cad.contracts import CadBuildRequest
from ariad_fabrication.cad.golden_part import PROVIDER_ID
from ariad_fabrication.cad import GoldenPartCadPipeline
from ariad_fabrication.domain import PartSpec
from ariad_fabrication.execution import (
    ExecutionTarget,
    ProcessTerminationReason,
    SealedCadWorkerAdapter,
    SealedCadPipelineRunner,
    TrustedTargetRegistry,
)
from ariad_fabrication.intent_parser import RuleBasedIntentParser
from ariad_fabrication.orchestrator import PipelineOrchestrator


WINDOWS_X64 = os.name == "nt" and ctypes.sizeof(ctypes.c_void_p) == 8


@unittest.skipUnless(WINDOWS_X64, "sealed CAD adapter requires Windows x64")
class SealedCadWorkerAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.registry = TrustedTargetRegistry.from_checkout()
            cls.resolved = cls.registry.resolve(ExecutionTarget.GOLDEN_PART_R2)
            cls.spec = json.loads(
                cls.resolved.part_spec_path.read_text(encoding="utf-8")
            )
            cls.expected = json.loads(
                cls.resolved.geometry_expectations_path.read_text(encoding="utf-8")
            )
        except Exception as exc:  # pragma: no cover - environment gate
            raise unittest.SkipTest(f"registered R2 target unavailable: {exc}") from exc

    def test_real_registered_r2_worker_is_sealed_and_supervised(self):
        request = CadBuildRequest(
            request_id="cadreq_supervised_sealed_test",
            job_id="job_supervised_sealed_test",
            revision_id="rev_supervised_sealed_test",
            provider_id=PROVIDER_ID,
            spec=self.spec,
            expected=self.expected,
        )
        with tempfile.TemporaryDirectory(prefix="ariad-sealed-cad-") as raw:
            run = SealedCadWorkerAdapter(self.registry).run(
                self.resolved.plan,
                request,
                Path(raw),
            )

            self.assertEqual(run.process.reason, ProcessTerminationReason.EXITED)
            self.assertEqual(
                run.process.return_code,
                0,
                f"stderr={run.stderr_path.read_text(encoding='utf-8')!r} "
                f"errors={run.result.errors!r}",
            )
            self.assertFalse(run.process.forced_termination)
            self.assertTrue(run.result.success)
            self.assertTrue(run.result.validation_passed)
            self.assertEqual(run.result.evidence_level, "R2")
            self.assertEqual(len(run.result.artifacts), 10)
            self.assertFalse(run.hardware_actions)
            self.assertGreaterEqual(run.process.total_processes_observed, 1)
            self.assertLessEqual(run.process.peak_active_processes_observed, 3)
            self.assertIn("python.exe", run.process.process_image_names)
            self.assertNotIn("cmd.exe", run.process.process_image_names)
            self.assertNotIn(
                "sealed worker rejected",
                run.stderr_path.read_text(encoding="utf-8"),
            )

    def test_nonempty_workspace_is_rejected_before_launch(self):
        request = CadBuildRequest(
            request_id="cadreq_nonempty_workspace_test",
            job_id="job_nonempty_workspace_test",
            revision_id="rev_nonempty_workspace_test",
            provider_id=PROVIDER_ID,
            spec=self.spec,
            expected=self.expected,
        )
        with tempfile.TemporaryDirectory(prefix="ariad-sealed-cad-") as raw:
            workspace = Path(raw)
            (workspace / "occupied").write_text("no", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "must be empty"):
                SealedCadWorkerAdapter(self.registry).run(
                    self.resolved.plan,
                    request,
                    workspace,
                )

    def test_existing_golden_part_pipeline_reaches_persisted_r2_through_sealed_runner(self):
        spec = PartSpec.from_mapping(self.spec)
        journey = PipelineOrchestrator(RuleBasedIntentParser()).run_spec(spec)
        with tempfile.TemporaryDirectory(prefix="ariad-sealed-pipeline-") as raw:
            outcome = GoldenPartCadPipeline(
                SealedCadPipelineRunner(
                    Path(raw),
                    self.registry,
                    self.resolved.plan,
                ),
                self.expected,
            ).run(journey)

            diagnostics = [
                (stage.stage.value, stage.status.value, stage.error_message)
                for stage in journey.stage_runs
            ]
            self.assertEqual(journey.status, "geometry_verified", diagnostics)
            self.assertTrue(outcome.journey_path.is_file())
            self.assertTrue(outcome.manifest_path.is_file())
            self.assertEqual(len(journey.artifacts), 15)
            self.assertNotIn(
                "manufacturing",
                {stage.stage.value for stage in journey.stage_runs},
            )


if __name__ == "__main__":
    unittest.main()
