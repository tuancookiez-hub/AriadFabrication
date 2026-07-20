"""Command-line entry point for a local pipeline smoke test."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

from .intent_parser import RuleBasedIntentParser
from .orchestrator import PipelineOrchestrator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Ariad Brief gate or the printer-independent Golden Part evidence path."
    )
    parser.add_argument(
        "request",
        nargs="*",
        help='Example: "Print a 40 x 20 x 5 mm mounting bracket in PETG"',
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm the draft only when no material requirements remain unresolved.",
    )
    golden = parser.add_mutually_exclusive_group()
    golden.add_argument(
        "--golden-part",
        action="store_true",
        help="Run the frozen OpenGrow benchmark through the real disconnected R4 fabrication package.",
    )
    golden.add_argument(
        "--golden-part-r2",
        action="store_true",
        help="Stop the frozen OpenGrow benchmark after deterministic R2 geometry verification.",
    )
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=Path("runs"),
        help="Artifact root used by Golden Part commands (default: ./runs).",
    )
    parser.add_argument(
        "--slicer-executable",
        type=Path,
        help=(
            "Approved prusa-slicer-console executable for --golden-part. "
            "Defaults to ARIAD_PRUSASLICER, the pinned runs/tools location, or PATH."
        ),
    )
    args = parser.parse_args(argv)
    request = " ".join(args.request).strip()

    if args.golden_part or args.golden_part_r2:
        if request:
            parser.error("Golden Part commands use the frozen benchmark and do not accept a request")
        if args.confirm:
            parser.error("the Golden Part is already a confirmed benchmark")
        if args.golden_part_r2 and args.slicer_executable:
            parser.error("--slicer-executable is not used with --golden-part-r2")
        return _run_golden_part(
            args.runs_root,
            slicer_executable=args.slicer_executable,
            r2_only=args.golden_part_r2,
        )

    if not request:
        parser.error("provide a natural-language part request")

    journey = PipelineOrchestrator(RuleBasedIntentParser()).run(
        request,
        confirm=args.confirm,
    )
    print(json.dumps(journey.to_dict(), indent=2))
    if journey.status == "ready_for_design":
        return 0
    if journey.status == "needs_input":
        return 2
    return 1


def _find_slicer(runs_root: Path, explicit: Path | None) -> Path | None:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    if environment := os.environ.get("ARIAD_PRUSASLICER"):
        candidates.append(Path(environment))
    candidates.append(
        runs_root
        / "tools"
        / "prusaslicer"
        / "2.9.6"
        / "portable"
        / "PrusaSlicer-2.9.6"
        / "prusa-slicer-console.exe"
    )
    if discovered := shutil.which("prusa-slicer-console"):
        candidates.append(Path(discovered))
    if discovered := shutil.which("prusa-slicer-console.exe"):
        candidates.append(Path(discovered))
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_file():
            return resolved
    return None


def _run_golden_part(
    runs_root: Path,
    *,
    slicer_executable: Path | None,
    r2_only: bool,
) -> int:
    from .cad import GoldenPartCadPipeline
    from .cad.runner import CadWorkerRunner
    from .domain import PartSpec

    root = Path(__file__).resolve().parents[2]
    benchmark = root / "benchmarks" / "golden_part"
    spec = PartSpec.from_mapping(
        json.loads((benchmark / "part_spec.json").read_text(encoding="utf-8"))
    )
    expected = json.loads((benchmark / "expected.json").read_text(encoding="utf-8"))
    slicer_path = None if r2_only else _find_slicer(runs_root, slicer_executable)
    if not r2_only and slicer_path is None:
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "error": "approved PrusaSlicer console executable was not found",
                    "remediation": (
                        "Pass --slicer-executable, set ARIAD_PRUSASLICER, or install the pinned "
                        "portable build under runs/tools/prusaslicer/2.9.6."
                    ),
                    "hardware_action": False,
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 3
    journey = PipelineOrchestrator(RuleBasedIntentParser()).run_spec(spec)
    cad_outcome = GoldenPartCadPipeline(
        CadWorkerRunner(runs_root, python_executable=Path(sys.executable)),
        expected,
    ).run(journey)
    outcome = cad_outcome
    if not r2_only and journey.status == "geometry_verified":
        from .slicing import (
            GoldenPartFabricationPipeline,
            ProfileBundle,
            PrusaSlicerAdapter,
        )

        profile_root = root / "profiles" / "v1"
        profiles = ProfileBundle.from_paths(
            printer_path=profile_root / "printers" / "generic_open_fdm_220.json",
            material_path=profile_root / "materials" / "generic_petg_175.json",
            process_path=profile_root / "processes" / "golden_part_020_no_support.json",
            orientation_path=profile_root
            / "orientations"
            / "upright_source_z_centered.json",
            slicer_config_path=profile_root
            / "prusaslicer"
            / "generic_open_fdm_220__generic_petg__golden_part_020_no_support.ini",
        )
        printability_expected = json.loads(
            (benchmark / "printability_expected.json").read_text(encoding="utf-8")
        )
        outcome = GoldenPartFabricationPipeline(
            profiles,
            printability_expected,
            PrusaSlicerAdapter(slicer_path),
        ).run(cad_outcome)
    stage_evidence = [
        {
            "stage": item.stage.value,
            "status": item.status.value,
            "evidence_level": item.evidence_level.value if item.evidence_level else None,
        }
        for item in journey.stage_runs
    ]
    print(
        json.dumps(
            {
                "job_id": journey.job.job_id,
                "revision_id": journey.current_revision.revision_id,
                "status": journey.status,
                "stage_evidence": stage_evidence,
                "artifact_count": len(journey.artifacts),
                "revision_directory": str(outcome.revision_directory),
                "journey": str(outcome.journey_path),
                "manifest": str(outcome.manifest_path),
                "fabrication_package": (
                    str(outcome.package_report_path)
                    if hasattr(outcome, "package_report_path") and outcome.package_report_path
                    else None
                ),
                "slicer_executable": str(slicer_path) if slicer_path else None,
                "physical_validation": False,
                "claim_boundary": (
                    "R2 means geometry-verified for the frozen checks only; printability is not "
                    "established. R4 means slicer-verified only for the recorded generic profile; "
                    "no physical performance or print success is established."
                ),
            },
            indent=2,
        )
    )
    expected_status = "geometry_verified" if r2_only else "completed"
    return 0 if journey.status == expected_status else 1


if __name__ == "__main__":
    sys.exit(main())
