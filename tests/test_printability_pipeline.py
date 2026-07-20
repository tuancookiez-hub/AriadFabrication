from dataclasses import replace
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
from ariad_fabrication.domain import EvidenceLevel, FabricationStage, PartSpec, StageStatus
from ariad_fabrication.intent_parser import RuleBasedIntentParser
from ariad_fabrication.orchestrator import PipelineOrchestrator
from ariad_fabrication.slicing import (
    GoldenPartFabricationPipeline,
    ProfileBundle,
    PrusaSlicerAdapter,
    assess_golden_part_printability,
)


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmarks" / "golden_part"
PROFILE_ROOT = ROOT / "profiles" / "v1"
SLICER = (
    ROOT
    / "runs"
    / "tools"
    / "prusaslicer"
    / "2.9.6"
    / "portable"
    / "PrusaSlicer-2.9.6"
    / "prusa-slicer-console.exe"
)


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _journey():
    spec = PartSpec.from_mapping(_json(BENCHMARK / "part_spec.json"))
    return PipelineOrchestrator(RuleBasedIntentParser()).run_spec(spec)


def _profiles(
    *,
    printer_path: Path | None = None,
    config_path: Path | None = None,
) -> ProfileBundle:
    return ProfileBundle.from_paths(
        printer_path=printer_path
        or PROFILE_ROOT / "printers" / "generic_open_fdm_220.json",
        material_path=PROFILE_ROOT / "materials" / "generic_petg_175.json",
        process_path=PROFILE_ROOT / "processes" / "golden_part_020_no_support.json",
        orientation_path=PROFILE_ROOT / "orientations" / "upright_source_z_centered.json",
        slicer_config_path=config_path
        or PROFILE_ROOT
        / "prusaslicer"
        / "generic_open_fdm_220__generic_petg__golden_part_020_no_support.ini",
    )


def _r2_outcome(root: Path):
    return GoldenPartCadPipeline(
        CadWorkerRunner(root, python_executable=Path(sys.executable)),
        _json(BENCHMARK / "expected.json"),
    ).run(_journey())


@unittest.skipUnless(CAD_AVAILABLE, "install the cad optional dependency to run R3 tests")
class PrintabilityValidatorTests(unittest.TestCase):
    def test_r3_report_is_deterministic_and_fails_closed_for_oversized_height(self):
        with TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            cad = _r2_outcome(temporary_root / "runs")
            exact = cad.revision_directory / "design" / "part.step"
            geometry = _json(cad.revision_directory / "design" / "geometry_validation.json")
            spec = _json(cad.revision_directory / "design" / "part_spec.json")
            expected = _json(BENCHMARK / "printability_expected.json")

            first_path = temporary_root / "first" / "oriented.step"
            second_path = temporary_root / "second" / "oriented.step"
            first = assess_golden_part_printability(
                exact,
                first_path,
                geometry_report=geometry,
                part_spec=spec,
                profiles=_profiles(),
                expected=expected,
            )
            second = assess_golden_part_printability(
                exact,
                second_path,
                geometry_report=geometry,
                part_spec=spec,
                profiles=_profiles(),
                expected=expected,
            )

            self.assertTrue(first.passed)
            self.assertEqual(first.status, "passed_with_warnings")
            self.assertEqual(first.evidence_level, "R3")
            self.assertEqual(len(first.checks), 23)
            self.assertEqual(len(first.warnings), 5)
            self.assertEqual(first.to_dict(), second.to_dict())
            self.assertEqual(
                hashlib.sha256(first_path.read_bytes()).hexdigest(),
                hashlib.sha256(second_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                first.measurements["horizontal_hole_diameters_mm"],
                [3.4, 3.4, 4.0],
            )
            self.assertEqual(
                first.measurements["overhang_analysis"][
                    "unresolved_steep_overhang_area_mm2"
                ],
                0.0,
            )

            printer = _json(PROFILE_ROOT / "printers" / "generic_open_fdm_220.json")
            printer["build_volume_mm"]["z"] = 40.0
            printer_path = temporary_root / "short_printer.json"
            printer_path.write_text(json.dumps(printer), encoding="utf-8")
            config = (
                PROFILE_ROOT
                / "prusaslicer"
                / "generic_open_fdm_220__generic_petg__golden_part_020_no_support.ini"
            ).read_text(encoding="utf-8")
            config_path = temporary_root / "short_printer.ini"
            config_path.write_text(
                config.replace("max_print_height = 250", "max_print_height = 40"),
                encoding="utf-8",
            )
            oversized = assess_golden_part_printability(
                exact,
                temporary_root / "oversized" / "oriented.step",
                geometry_report=geometry,
                part_spec=spec,
                profiles=_profiles(printer_path=printer_path, config_path=config_path),
                expected=expected,
            )

            self.assertFalse(oversized.passed)
            self.assertIsNone(oversized.evidence_level)
            self.assertEqual(
                [item.check_id for item in oversized.failed_checks],
                ["build_volume_z"],
            )


@unittest.skipUnless(
    CAD_AVAILABLE and SLICER.is_file(),
    "install CAD dependencies and the approved PrusaSlicer fixture to run R4 tests",
)
class FabricationPipelineTests(unittest.TestCase):
    def test_real_golden_part_path_records_r0_through_r4_and_package_lineage(self):
        with TemporaryDirectory() as temporary:
            cad = _r2_outcome(Path(temporary) / "runs")
            pipeline = GoldenPartFabricationPipeline(
                _profiles(),
                _json(BENCHMARK / "printability_expected.json"),
                PrusaSlicerAdapter(SLICER, timeout_seconds=180, threads=2),
            )
            outcome = pipeline.run(cad)
            journey = outcome.journey

            self.assertEqual(journey.status, "completed")
            self.assertEqual(
                [item.stage for item in journey.stage_runs],
                [
                    FabricationStage.BRIEF,
                    FabricationStage.DESIGN,
                    FabricationStage.GEOMETRY_VALIDATION,
                    FabricationStage.PRINTABILITY_VALIDATION,
                    FabricationStage.SLICING,
                    FabricationStage.FABRICATION_PACKAGE,
                ],
            )
            self.assertEqual(
                [item.evidence_level for item in journey.stage_runs],
                [
                    EvidenceLevel.R0,
                    EvidenceLevel.R1,
                    EvidenceLevel.R2,
                    EvidenceLevel.R3,
                    EvidenceLevel.R4,
                    EvidenceLevel.R4,
                ],
            )
            self.assertEqual(journey.stage_runs[3].status, StageStatus.PASSED_WITH_WARNINGS)
            self.assertEqual(journey.stage_runs[4].status, StageStatus.PASSED)
            self.assertEqual(journey.stage_runs[5].status, StageStatus.PASSED_WITH_WARNINGS)
            self.assertEqual(len(journey.artifacts), 36)
            self.assertEqual(len(journey.findings), 5)
            self.assertTrue(
                all(item.severity.value == "warning" for item in journey.findings)
            )

            by_role = {item.role: item for item in journey.artifacts}
            required = {
                "oriented_geometry",
                "profile_bundle",
                "printability_report",
                "slicer_installation",
                "slicer_project",
                "gcode",
                "gcode_preflight",
                "slicer_run_report",
                "fabrication_package_report",
            }
            self.assertTrue(required.issubset(by_role))
            oriented_parent_roles = {
                next(
                    item.role
                    for item in journey.artifacts
                    if item.artifact_id == parent_id
                )
                for parent_id in by_role["oriented_geometry"].parent_artifact_ids
            }
            self.assertEqual(oriented_parent_roles, {"exact_geometry", "orientation_profile"})

            for artifact in journey.artifacts:
                path = outcome.revision_directory / artifact.path
                payload = path.read_bytes()
                self.assertEqual(len(payload), artifact.size_bytes)
                self.assertEqual(hashlib.sha256(payload).hexdigest(), artifact.checksum_sha256)

            manifest = _json(outcome.manifest_path)
            schema = _json(ROOT / "schemas" / "v1" / "artifact-manifest.schema.json")
            Draft202012Validator(
                schema,
                format_checker=FormatChecker(),
            ).validate(manifest)
            self.assertEqual(len(manifest["artifacts"]), 36)

            printability_schema = _json(
                ROOT / "schemas" / "v1" / "printability-report.schema.json"
            )
            Draft202012Validator(
                printability_schema,
                format_checker=FormatChecker(),
            ).validate(_json(outcome.revision_directory / "printability" / "report.json"))

            package = _json(outcome.package_report_path)
            package_schema = _json(
                ROOT / "schemas" / "v1" / "fabrication-package.schema.json"
            )
            Draft202012Validator(
                package_schema,
                format_checker=FormatChecker(),
            ).validate(package)
            self.assertEqual(package["evidence_level"], "R4")
            self.assertEqual(
                package["status"],
                "slicer_verified_with_physical_unknowns",
            )
            self.assertEqual(
                package["allowed_claim"],
                "Slicer-verified for this recorded generic profile (R4).",
            )
            self.assertEqual(
                package["hardware"],
                {
                    "printer_selected": False,
                    "printer_connected": False,
                    "gcode_uploaded": False,
                    "print_started": False,
                },
            )
            self.assertTrue(package["preflight"]["passed"])
            self.assertEqual(package["slicer_warnings"], [])
            self.assertEqual(outcome.slice_outcome.model_info.facets_removed, 0)
            self.assertGreater(outcome.slice_outcome.summary.layer_count, 0)
            self.assertGreater(outcome.slice_outcome.summary.filament_mass_g, 0)

            low_adhesion = replace(
                outcome.slice_outcome,
                slicer_warnings=("Low bed adhesion",),
            )
            blockers, advisories = pipeline._evaluate_slicer_gate(low_adhesion)
            self.assertEqual(blockers, [])
            self.assertEqual(advisories, ["Low bed adhesion"])
            floating = replace(
                outcome.slice_outcome,
                slicer_warnings=("Floating bridge anchors",),
            )
            blockers, advisories = pipeline._evaluate_slicer_gate(floating)
            self.assertEqual(blockers, ["Floating bridge anchors"])
            self.assertEqual(advisories, [])
            repaired = replace(
                outcome.slice_outcome,
                model_info=replace(outcome.slice_outcome.model_info, facets_removed=1),
            )
            blockers, _ = pipeline._evaluate_slicer_gate(repaired)
            self.assertTrue(any("mesh repair" in item for item in blockers))


if __name__ == "__main__":
    unittest.main()
