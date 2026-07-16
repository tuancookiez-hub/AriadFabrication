import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from jsonschema import Draft202012Validator, FormatChecker

try:
    import cadquery  # noqa: F401

    CAD_AVAILABLE = True
except ImportError:
    CAD_AVAILABLE = False

from ariad_fabrication.cad import GoldenPartCadPipeline
from ariad_fabrication.cad.runner import CadWorkerRunner
from ariad_fabrication.domain import (
    EvidenceLevel,
    FabricationStage,
    PartSpec,
    StageStatus,
)
from ariad_fabrication.intent_parser import RuleBasedIntentParser
from ariad_fabrication.orchestrator import PipelineOrchestrator


ROOT = Path(__file__).resolve().parents[1]


def _fixture(name: str):
    return json.loads((ROOT / "benchmarks" / "golden_part" / name).read_text(encoding="utf-8"))


def _r0_journey():
    spec = PartSpec.from_mapping(_fixture("part_spec.json"))
    return PipelineOrchestrator(RuleBasedIntentParser()).run_spec(spec)


@unittest.skipUnless(CAD_AVAILABLE, "install the cad optional dependency to run CAD tests")
class CadPipelineTests(unittest.TestCase):
    def test_real_vertical_slice_records_r0_r1_r2_and_persistent_lineage(self):
        journey = _r0_journey()
        with TemporaryDirectory() as temporary:
            runner = CadWorkerRunner(Path(temporary), python_executable=Path(sys.executable))
            outcome = GoldenPartCadPipeline(runner, _fixture("expected.json")).run(journey)

            self.assertEqual(journey.status, "geometry_verified")
            self.assertEqual(
                [item.stage for item in journey.stage_runs],
                [
                    FabricationStage.BRIEF,
                    FabricationStage.DESIGN,
                    FabricationStage.GEOMETRY_VALIDATION,
                ],
            )
            self.assertEqual(
                [item.status for item in journey.stage_runs],
                [StageStatus.PASSED, StageStatus.PASSED, StageStatus.PASSED],
            )
            self.assertEqual(
                [item.evidence_level for item in journey.stage_runs],
                [EvidenceLevel.R0, EvidenceLevel.R1, EvidenceLevel.R2],
            )
            self.assertEqual(len(journey.artifacts), 15)

            design_run = journey.stage_runs[1]
            geometry_run = journey.stage_runs[2]
            self.assertEqual(len(design_run.artifact_ids), 14)
            self.assertEqual(len(geometry_run.artifact_ids), 1)
            self.assertEqual(len(geometry_run.input_artifact_ids), 2)

            by_role = {item.role: item for item in journey.artifacts}
            exact = by_role["exact_geometry"]
            parent_roles = {
                next(item.role for item in journey.artifacts if item.artifact_id == parent_id)
                for parent_id in exact.parent_artifact_ids
            }
            self.assertEqual(parent_roles, {"cad_source", "cad_parameters"})
            self.assertEqual(
                by_role["geometry_validation_report"].stage_run_id,
                geometry_run.stage_run_id,
            )

            for artifact in journey.artifacts:
                path = outcome.revision_directory / artifact.path
                payload = path.read_bytes()
                self.assertEqual(len(payload), artifact.size_bytes)
                self.assertEqual(hashlib.sha256(payload).hexdigest(), artifact.checksum_sha256)

            manifest = json.loads(outcome.manifest_path.read_text(encoding="utf-8"))
            schema = json.loads(
                (ROOT / "schemas" / "v1" / "artifact-manifest.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(manifest)
            self.assertEqual(len(manifest["artifacts"]), 15)
            persisted = json.loads(outcome.journey_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["job"]["status"], "geometry_verified")
            self.assertTrue(
                any(item["event_type"] == "geometry_validation_completed" for item in persisted["events"])
            )

    def test_failed_geometry_gate_keeps_design_at_r1_and_records_findings(self):
        altered = _fixture("expected.json")
        altered["expected_measurements_mm"]["design_envelope"]["x"] = 31.0
        journey = _r0_journey()

        with TemporaryDirectory() as temporary:
            runner = CadWorkerRunner(Path(temporary), python_executable=Path(sys.executable))
            outcome = GoldenPartCadPipeline(runner, altered).run(journey)

            self.assertEqual(journey.status, "failed")
            design_run = journey.stage_runs[1]
            geometry_run = journey.stage_runs[2]
            self.assertEqual(design_run.status, StageStatus.PASSED)
            self.assertEqual(design_run.evidence_level, EvidenceLevel.R1)
            self.assertEqual(geometry_run.status, StageStatus.FAILED)
            self.assertIsNone(geometry_run.evidence_level)
            self.assertTrue(any(item.code == "geometry.envelope_x" for item in journey.findings))
            self.assertTrue(
                (outcome.revision_directory / "design" / "part.step").exists()
            )
            manifest = json.loads(outcome.manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(any(item["code"] == "geometry.envelope_x" for item in manifest["findings"]))


if __name__ == "__main__":
    unittest.main()
