import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile, is_zipfile

try:
    import cadquery as cq
except ImportError:
    cq = None

from ariad_fabrication.cad import CadBuildRequest
from ariad_fabrication.cad.canonical import canonicalize_step
from ariad_fabrication.cad.glb import inspect_glb
from ariad_fabrication.cad.golden_part import PROVIDER_ID, build
from ariad_fabrication.cad.runner import CadWorkerRunner
from ariad_fabrication.cad.validation import validate_golden_part_geometry
from ariad_fabrication.domain import PartSpec


ROOT = Path(__file__).resolve().parents[1]


def _fixture(name: str):
    return json.loads((ROOT / "benchmarks" / "golden_part" / name).read_text(encoding="utf-8"))


@unittest.skipUnless(cq is not None, "install the cad optional dependency to run CAD tests")
class GoldenPartCadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec_mapping = _fixture("part_spec.json")
        cls.expected = _fixture("expected.json")
        cls.spec = PartSpec.from_mapping(cls.spec_mapping)

    @classmethod
    def request(
        cls,
        *,
        job_id: str,
        revision_id: str,
        expected=None,
        provider_id: str = PROVIDER_ID,
    ) -> CadBuildRequest:
        return CadBuildRequest(
            request_id=f"cadreq_{job_id}_{revision_id}",
            job_id=job_id,
            revision_id=revision_id,
            provider_id=provider_id,
            spec=cls.spec_mapping,
            expected=expected or cls.expected,
        )

    def test_parametric_model_step_reimport_and_geometry_checks(self):
        model, parameters = build(self.spec, self.expected)
        self.assertEqual(parameters["design_id"], PROVIDER_ID)
        self.assertTrue(model.val().isValid())
        self.assertEqual(len(model.solids().vals()), 1)

        with TemporaryDirectory() as temporary:
            step_path = Path(temporary) / "part.step"
            cq.exporters.export(model, str(step_path))
            canonicalize_step(step_path)
            imported = cq.importers.importStep(str(step_path))
            report = validate_golden_part_geometry(
                imported,
                self.expected,
                tool_versions={"test": "1.0.0"},
            )

        self.assertTrue(report.passed)
        self.assertEqual(report.evidence_level, "R2")
        self.assertEqual(len(report.checks), 25)
        self.assertEqual(report.failed_checks, ())
        self.assertEqual(report.measurements["stake_diametral_clearance"], 0.6)

    def test_worker_exports_traceable_rebuildable_artifacts(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = CadWorkerRunner(root, python_executable=Path(sys.executable))
            outcome = runner.run(self.request(job_id="job_export", revision_id="rev_1"))

            self.assertEqual(outcome.return_code, 0)
            self.assertFalse(outcome.timed_out)
            self.assertTrue(outcome.result.success)
            self.assertTrue(outcome.result.validation_passed)
            self.assertEqual(outcome.result.evidence_level, "R2")
            self.assertEqual(len(outcome.result.artifacts), 10)

            by_role = {item.role: item for item in outcome.result.artifacts}
            self.assertEqual(
                set(by_role),
                {
                    "part_spec",
                    "benchmark_expectations",
                    "cad_parameters",
                    "cad_source",
                    "exact_geometry",
                    "geometry_validation_report",
                    "cad_environment",
                    "compatibility_mesh",
                    "manufacturing_model",
                    "preview_model",
                },
            )
            for descriptor in outcome.result.artifacts:
                path = outcome.revision_directory / descriptor.path
                payload = path.read_bytes()
                self.assertEqual(len(payload), descriptor.size_bytes)
                self.assertEqual(hashlib.sha256(payload).hexdigest(), descriptor.checksum_sha256)

            imported = cq.importers.importStep(
                str(outcome.revision_directory / by_role["exact_geometry"].path)
            )
            self.assertTrue(imported.val().isValid())
            self.assertEqual(len(imported.solids().vals()), 1)
            inspect_glb(outcome.revision_directory / by_role["preview_model"].path)

            environment = json.loads(
                (outcome.revision_directory / by_role["cad_environment"].path).read_text(
                    encoding="utf-8"
                )
            )
            stl_evidence = environment["export_evidence"]["stl"]
            self.assertTrue(stl_evidence["closed_two_manifold"])
            self.assertEqual(stl_evidence["nonmanifold_edge_count"], 0)
            self.assertGreater(stl_evidence["triangle_count"], 0)

            three_mf = outcome.revision_directory / by_role["manufacturing_model"].path
            self.assertTrue(is_zipfile(three_mf))
            with ZipFile(three_mf) as archive:
                self.assertIn("3D/3dmodel.model", archive.namelist())

            rebuild_directory = root / "rebuild"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(outcome.revision_directory / by_role["cad_source"].path),
                    "--parameters",
                    str(outcome.revision_directory / by_role["cad_parameters"].path),
                    "--output-dir",
                    str(rebuild_directory),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            rebuilt = cq.importers.importStep(str(rebuild_directory / "part.step"))
            self.assertTrue(rebuilt.val().isValid())
            self.assertEqual(len(rebuilt.solids().vals()), 1)

    def test_repeated_runs_produce_identical_design_artifact_hashes(self):
        with TemporaryDirectory() as temporary:
            runner = CadWorkerRunner(Path(temporary), python_executable=Path(sys.executable))
            first = runner.run(self.request(job_id="job_repeat_a", revision_id="rev_1"))
            second = runner.run(self.request(job_id="job_repeat_b", revision_id="rev_1"))

            self.assertTrue(first.result.success)
            self.assertTrue(second.result.success)
            first_hashes = {item.role: item.checksum_sha256 for item in first.result.artifacts}
            second_hashes = {item.role: item.checksum_sha256 for item in second.result.artifacts}
            self.assertEqual(first_hashes, second_hashes)

    def test_failed_geometry_gate_preserves_r1_artifacts_without_claiming_r2(self):
        altered = json.loads(json.dumps(self.expected))
        altered["expected_measurements_mm"]["design_envelope"]["x"] = 31.0

        with TemporaryDirectory() as temporary:
            runner = CadWorkerRunner(Path(temporary), python_executable=Path(sys.executable))
            outcome = runner.run(
                self.request(job_id="job_r1_only", revision_id="rev_1", expected=altered)
            )

            self.assertTrue(outcome.result.success)
            self.assertFalse(outcome.result.validation_passed)
            self.assertEqual(outcome.result.evidence_level, "R1")
            self.assertTrue((outcome.revision_directory / "design" / "part.step").exists())
            report = json.loads(
                (outcome.revision_directory / "design" / "geometry_validation.json").read_text(
                    encoding="utf-8"
                )
            )
            failed_ids = {item["check_id"] for item in report["checks"] if not item["passed"]}
            self.assertIn("envelope_x", failed_ids)


if __name__ == "__main__":
    unittest.main()
