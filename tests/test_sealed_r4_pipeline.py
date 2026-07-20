import ctypes
import json
import os
from pathlib import Path
import tempfile
import unittest

from ariad_fabrication.cad import GoldenPartCadPipeline
from ariad_fabrication.domain import PartSpec
from ariad_fabrication.execution import (
    ExecutionTarget,
    SealedCadPipelineRunner,
    SealedPrusaSlicerAdapter,
    TrustedTargetRegistry,
)
from ariad_fabrication.intent_parser import RuleBasedIntentParser
from ariad_fabrication.orchestrator import PipelineOrchestrator
from ariad_fabrication.slicing import GoldenPartFabricationPipeline, ProfileBundle


WINDOWS_X64 = os.name == "nt" and ctypes.sizeof(ctypes.c_void_p) == 8


@unittest.skipUnless(WINDOWS_X64, "sealed R4 pipeline requires Windows x64")
class SealedR4PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.registry = TrustedTargetRegistry.from_checkout()
            cls.resolved = cls.registry.resolve(ExecutionTarget.GOLDEN_PART_R4)
            cls.spec = PartSpec.from_mapping(
                json.loads(cls.resolved.part_spec_path.read_text(encoding="utf-8"))
            )
            cls.geometry_expected = json.loads(
                cls.resolved.geometry_expectations_path.read_text(encoding="utf-8")
            )
            cls.printability_expected = json.loads(
                cls.resolved.printability_expectations_path.read_text(encoding="utf-8")
            )
            paths = cls.resolved.profile_paths
            cls.profiles = ProfileBundle.from_paths(
                printer_path=paths[0],
                material_path=paths[1],
                process_path=paths[2],
                orientation_path=paths[3],
                slicer_config_path=paths[4],
            )
        except Exception as exc:  # pragma: no cover - environment gate
            raise unittest.SkipTest(f"registered R4 target unavailable: {exc}") from exc

    def test_real_registered_r4_pipeline_uses_supervised_slicer_commands(self):
        with tempfile.TemporaryDirectory(prefix="ariad-sealed-r4-") as raw:
            root = Path(raw)
            journey = PipelineOrchestrator(RuleBasedIntentParser()).run_spec(self.spec)
            cad = GoldenPartCadPipeline(
                SealedCadPipelineRunner(
                    root,
                    self.registry,
                    self.resolved.plan,
                ),
                self.geometry_expected,
            ).run(journey)
            slicer = SealedPrusaSlicerAdapter(
                self.registry,
                self.resolved.plan,
                cad.revision_directory,
            )
            outcome = GoldenPartFabricationPipeline(
                self.profiles,
                self.printability_expected,
                slicer,
            ).run(cad)

            self.assertEqual(journey.status, "completed")
            self.assertEqual(len(journey.artifacts), 36)
            self.assertEqual(len(slicer.supervised_results), 3)
            self.assertTrue(all(item.return_code == 0 for item in slicer.supervised_results))
            self.assertTrue(all(not item.hardware_actions for item in slicer.supervised_results))
            self.assertTrue(
                all("cmd.exe" not in item.process_image_names for item in slicer.supervised_results)
            )
            for command in outcome.slice_outcome.commands[1:]:
                thread_index = command.arguments.index("--threads")
                self.assertEqual(command.arguments[thread_index + 1], "4")
            self.assertTrue(outcome.package_report_path.is_file())
            package = json.loads(outcome.package_report_path.read_text(encoding="utf-8"))
            self.assertEqual(package["evidence_level"], "R4")
            self.assertFalse(package["hardware"]["printer_connected"])
            self.assertFalse(package["hardware"]["print_started"])

    def test_r2_plan_cannot_construct_a_slicer_adapter(self):
        r2 = self.registry.resolve(ExecutionTarget.GOLDEN_PART_R2)
        with tempfile.TemporaryDirectory(prefix="ariad-sealed-r4-reject-") as raw:
            with self.assertRaisesRegex(ValueError, "requires the registered R4 target"):
                SealedPrusaSlicerAdapter(self.registry, r2.plan, Path(raw))


if __name__ == "__main__":
    unittest.main()
