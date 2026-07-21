"""Export and slice the first-print interlock calibration coupon."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from ariad_fabrication.cad.glb import export_glb
from ariad_fabrication.cad.interlock_coupon_design import (
    DESIGN_SOURCE_VERSION,
    InterlockCouponParameters,
    build_parts,
)
from ariad_fabrication.slicing import PrusaSlicerAdapter
from build_robot_demo_package import _default_slicer, _profiles


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slicer", type=Path, default=_default_slicer())
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "web" / "public" / "demo" / "interlock-coupon",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    parameter_path = ROOT / "benchmarks" / "interlock_coupon" / "parameters.json"
    raw_parameters = json.loads(parameter_path.read_text(encoding="utf-8"))
    parameters = InterlockCouponParameters.from_mapping(raw_parameters)
    parts = build_parts(raw_parameters)
    profiles = _profiles()
    slicer = PrusaSlicerAdapter(args.slicer, timeout_seconds=180)

    from cadquery import exporters

    with tempfile.TemporaryDirectory(prefix="interlock-coupon-", dir=ROOT / "runs") as raw:
        work = Path(raw)
        records: list[dict[str, object]] = []
        total_seconds = 0
        total_mass_g = 0.0
        for name, part in parts.items():
            bounds = part.val().BoundingBox()
            oriented = part.translate((0.0, 0.0, -bounds.zmin))
            step_path = output / f"{name}.step"
            stl_path = output / f"{name}.stl"
            glb_path = output / f"{name}.glb"
            exporters.export(oriented, str(step_path))
            exporters.export(oriented, str(stl_path), tolerance=0.08, angularTolerance=0.12)
            preview = export_glb(
                oriented.val(),
                glb_path,
                linear_tolerance_mm=0.08,
                angular_tolerance_rad=0.12,
            )
            outcome = slicer.slice_model(stl_path, work / "slices" / name, profiles)
            total_seconds += outcome.summary.estimated_seconds
            total_mass_g += outcome.summary.filament_mass_g
            part_bounds = oriented.val().BoundingBox()
            records.append(
                {
                    "part_id": name,
                    "step": step_path.name,
                    "step_sha256": _sha256(step_path),
                    "stl": stl_path.name,
                    "stl_sha256": _sha256(stl_path),
                    "glb": glb_path.name,
                    "glb_sha256": _sha256(glb_path),
                    "preview_triangle_count": preview["triangle_count"],
                    "kernel_valid": bool(oriented.val().isValid()),
                    "solid_count": len(oriented.solids().vals()),
                    "bounds_mm": {
                        "x": round(part_bounds.xlen, 3),
                        "y": round(part_bounds.ylen, 3),
                        "z": round(part_bounds.zlen, 3),
                    },
                    "slice_status": outcome.status,
                    "slicer_warnings": list(outcome.slicer_warnings),
                    "layers": outcome.summary.layer_count,
                    "estimated_seconds": outcome.summary.estimated_seconds,
                    "filament_mass_g": round(outcome.summary.filament_mass_g, 2),
                    "gcode_preflight_passed": outcome.preflight.passed,
                }
            )

        instructions = {
            "artifact_kind": "physical_calibration_protocol",
            "hardware_action_performed": False,
            "steps": [
                "Print all six coupon parts together using the exact intended printer, material, and process profile.",
                "Let the parts cool completely before removing them from the build surface.",
                "Slide the dovetail key through channels one to five; the manifest maps them to 0.2 through 0.6 mm per-side clearances.",
                "Choose the smallest channel that moves fully by hand without binding, visible damage, or excessive looseness.",
                "Insert each snap key into the receiver, record whether it latches and releases by hand, and never force a specimen that binds.",
                "Repeat the preferred snap candidate for at least 25 gentle cycles and record cracks, whitening, permanent set, and retention loss.",
                "Create a calibrated child revision; do not silently replace the generic robot parameters.",
            ],
            "record": {
                "printer_profile_id": None,
                "material_profile_id": None,
                "process_profile_id": None,
                "measured_dovetail_clearance_mm": None,
                "preferred_hook_engagement_mm": None,
                "cycles_completed": 0,
                "observations": [],
                "accepted_by_user": False,
            },
            "claim_boundary": raw_parameters["claim_boundary"],
        }
        instructions_path = output / "instructions.json"
        _write_json(instructions_path, instructions)

        package_path = output / "ariad-interlock-calibration-coupon.zip"
        with ZipFile(package_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            archive.write(parameter_path, "design/parameters.json")
            archive.write(instructions_path, "instructions.json")
            for record in records:
                for key in ("step", "stl", "glb"):
                    archive.write(output / str(record[key]), f"parts/{record['part_id']}/{record[key]}")
                slice_root = work / "slices" / str(record["part_id"])
                for filename in (
                    "toolpath.gcode",
                    "slicer_project.3mf",
                    "slice_report.json",
                    "gcode_preflight.json",
                    "slicer_installation.json",
                ):
                    archive.write(slice_root / filename, f"parts/{record['part_id']}/{filename}")
            for profile_path in profiles.source_paths:
                archive.write(profile_path, f"profiles/{profile_path.name}")

        manifest = {
            "schema_version": "1.0.0",
            "artifact_kind": "interlock_calibration_coupon_package",
            "design_source_version": DESIGN_SOURCE_VERSION,
            "status": "digitally_sliced_awaiting_physical_calibration",
            "part_count": len(records),
            "candidate_clearances_mm": list(parameters.clearance_values_mm),
            "channel_mapping": [
                {"channel": index + 1, "clearance_mm_per_side": value}
                for index, value in enumerate(parameters.clearance_values_mm)
            ],
            "candidate_hook_engagements_mm": list(parameters.hook_engagement_values_mm),
            "profile": {
                "printer": profiles.printer.profile_id,
                "material": profiles.material.profile_id,
                "process": profiles.process.profile_id,
                "slicer": f"PrusaSlicer {slicer.installation.version}",
                "calibrated_to_hardware": False,
            },
            "parts": records,
            "checks": {
                "all_kernel_valid": all(record["kernel_valid"] for record in records),
                "all_single_solids": all(record["solid_count"] == 1 for record in records),
                "all_gcode_preflight_passed": all(
                    record["gcode_preflight_passed"] for record in records
                ),
                "physical_coupon_printed": False,
                "fit_measured": False,
                "snap_cycle_life_measured": False,
            },
            "totals": {
                "estimated_seconds": total_seconds,
                "filament_mass_g": round(total_mass_g, 2),
            },
            "instructions": instructions_path.name,
            "download": {
                "path": package_path.name,
                "size_bytes": package_path.stat().st_size,
                "checksum_sha256": _sha256(package_path),
            },
            "claim_boundary": raw_parameters["claim_boundary"],
        }
        _write_json(output / "manifest.json", manifest)
        print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
