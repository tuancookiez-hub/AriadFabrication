import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ariad_fabrication.cad import CadArtifactFormat, CadBuildRequest, CadBuildResult
from ariad_fabrication.cad.golden_part import PROVIDER_ID
from ariad_fabrication.cad.runner import CadWorkerRunner
from ariad_fabrication.cad.worker import execute_request


ROOT = Path(__file__).resolve().parents[1]


def _fixture(name: str):
    return json.loads((ROOT / "benchmarks" / "golden_part" / name).read_text(encoding="utf-8"))


def _request(**changes) -> CadBuildRequest:
    values = {
        "request_id": "cadreq_contract_test",
        "job_id": "job_contract_test",
        "revision_id": "rev_contract_test",
        "provider_id": PROVIDER_ID,
        "spec": _fixture("part_spec.json"),
        "expected": _fixture("expected.json"),
    }
    values.update(changes)
    return CadBuildRequest(**values)


class CadContractTests(unittest.TestCase):
    def test_request_round_trip_is_json_safe_and_immutable(self):
        source = _fixture("part_spec.json")
        request = _request(spec=source)
        source["name"] = "mutated after construction"

        self.assertEqual(request.spec["name"], "OpenGrow Stake Electronics Clamp v1")
        with self.assertRaises(TypeError):
            request.spec["name"] = "cannot mutate"  # type: ignore[index]

        serialized = request.to_dict()
        restored = CadBuildRequest.from_mapping(json.loads(json.dumps(serialized)))
        self.assertEqual(restored.to_dict(), serialized)

    def test_request_requires_step_and_finite_positive_tolerances(self):
        with self.assertRaisesRegex(ValueError, "STEP is required"):
            _request(requested_formats=(CadArtifactFormat.GLB,))
        with self.assertRaisesRegex(ValueError, "finite and greater than zero"):
            _request(linear_tolerance_mm=float("nan"))

    def test_result_parser_rejects_string_booleans(self):
        value = {
            "request_id": "cadreq_test",
            "provider_id": PROVIDER_ID,
            "success": "false",
            "validation_passed": False,
            "started_at": "2026-07-16T00:00:00+00:00",
            "completed_at": "2026-07-16T00:00:01+00:00",
        }
        with self.assertRaisesRegex(ValueError, "success must be a boolean"):
            CadBuildResult.from_mapping(value)

    def test_result_cannot_overclaim_validation_evidence(self):
        base = {
            "request_id": "cadreq_test",
            "provider_id": PROVIDER_ID,
            "started_at": "2026-07-16T00:00:00+00:00",
            "completed_at": "2026-07-16T00:00:01+00:00",
        }
        with self.assertRaisesRegex(ValueError, "R2 requires passed validation"):
            CadBuildResult(
                **base,
                success=True,
                validation_passed=False,
                evidence_level="R2",
            )
        with self.assertRaisesRegex(ValueError, "cannot pass geometry validation"):
            CadBuildResult(
                **base,
                success=False,
                validation_passed=True,
            )

    def test_runner_rejects_identifiers_that_could_escape_artifact_root(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            runner = CadWorkerRunner(root)
            with self.assertRaisesRegex(ValueError, "job_id cannot be used"):
                runner.run(_request(job_id="../outside"))
            self.assertFalse(root.exists())

    def test_worker_failure_does_not_publish_partial_output(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "design"
            request = _request(
                request_id="../../must-not-be-a-path",
                provider_id="unregistered_provider",
            )
            result = execute_request(request, output)

            self.assertFalse(result.success)
            self.assertIn("unregistered CAD provider", result.errors[0])
            self.assertFalse(output.exists())
            self.assertEqual(tuple(root.iterdir()), ())

    def test_worker_preserves_an_existing_immutable_output(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "design"
            output.mkdir()
            marker = output / "marker.txt"
            marker.write_text("keep", encoding="utf-8")

            result = execute_request(_request(), output)

            self.assertFalse(result.success)
            self.assertIn("immutable CAD output already exists", result.errors[0])
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
