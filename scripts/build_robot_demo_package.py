"""Build the disconnected robot prototype slicing and fabrication package.

This deliberately creates a prototype package with unresolved assembly and
physical warnings.  It does not promote the robot to Journey R4 evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from ariad_fabrication.slicing import ProfileBundle, PrusaSlicerAdapter


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _profiles() -> ProfileBundle:
    root = ROOT / "profiles" / "v1"
    return ProfileBundle.from_paths(
        printer_path=root / "printers" / "generic_open_fdm_220.json",
        material_path=root / "materials" / "generic_petg_175.json",
        process_path=root / "processes" / "golden_part_020_no_support.json",
        orientation_path=root / "orientations" / "upright_source_z_centered.json",
        slicer_config_path=root
        / "prusaslicer"
        / "generic_open_fdm_220__generic_petg__golden_part_020_no_support.ini",
    )


def _default_slicer() -> Path:
    return (
        ROOT
        / "runs"
        / "tools"
        / "prusaslicer"
        / "2.9.6"
        / "portable"
        / "PrusaSlicer-2.9.6"
        / "prusa-slicer-console.exe"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slicer", type=Path, default=_default_slicer())
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "web" / "public" / "demo" / "robot-package",
    )
    args = parser.parse_args()

    cad_root = ROOT / "web" / "public" / "demo" / "robot-cad"
    geometry = json.loads((cad_root / "manifest.json").read_text(encoding="utf-8"))
    coupon_root = ROOT / "web" / "public" / "demo" / "interlock-coupon"
    coupon = json.loads((coupon_root / "manifest.json").read_text(encoding="utf-8"))
    profiles = _profiles()
    slicer = PrusaSlicerAdapter(args.slicer, timeout_seconds=180)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="robot-package-", dir=ROOT / "runs") as raw:
        work = Path(raw)
        part_records: list[dict[str, object]] = []
        total_seconds = 0
        total_mass_g = 0.0
        total_filament_mm = 0.0

        for source in geometry["parts"]:
            part_id = source["part_id"]
            outcome = slicer.slice_model(
                cad_root / source["stl"], work / "slices" / part_id, profiles
            )
            summary = outcome.summary
            fits_build_volume = all(
                actual <= limit
                for actual, limit in zip(
                    outcome.model_info.size_mm,
                    profiles.printer.build_volume_mm,
                    strict=True,
                )
            )
            on_bed = abs(outcome.model_info.minimum_mm[2]) <= 0.02
            total_seconds += summary.estimated_seconds
            total_mass_g += summary.filament_mass_g
            total_filament_mm += summary.filament_length_mm
            part_records.append(
                {
                    "part_id": part_id,
                    "geometry": {
                        "kernel_valid": source["kernel_valid"],
                        "solid_count": source["solid_count"],
                        "manifold_mesh": outcome.model_info.manifold,
                        "fits_generic_build_volume": fits_build_volume,
                        "placed_on_bed": on_bed,
                    },
                    "slice_status": outcome.status,
                    "support_risk": (
                        "review_slicer_warnings" if outcome.slicer_warnings else "no_slicer_warning"
                    ),
                    "slicer_warnings": list(outcome.slicer_warnings),
                    "layers": summary.layer_count,
                    "estimated_seconds": summary.estimated_seconds,
                    "filament_mass_g": round(summary.filament_mass_g, 2),
                    "filament_length_mm": round(summary.filament_length_mm, 2),
                    "gcode_preflight_passed": outcome.preflight.passed,
                    "artifacts": {
                        "gcode": "parts/{0}/toolpath.gcode".format(part_id),
                        "gcode_sha256": _sha256(outcome.gcode_path),
                        "slicer_project": "parts/{0}/slicer_project.3mf".format(part_id),
                        "slice_report": "parts/{0}/slice_report.json".format(part_id),
                    },
                }
            )

        manifest: dict[str, object] = {
            "schema_version": "1.0.0",
            "artifact_kind": "robot_prototype_fabrication_package",
            "status": "sliced_with_unresolved_assembly_and_physical_checks",
            "part_count": len(part_records),
            "profile": {
                "printer": profiles.printer.profile_id,
                "material": profiles.material.profile_id,
                "process": profiles.process.profile_id,
                "slicer": "PrusaSlicer {0}".format(slicer.installation.version),
                "calibrated_to_hardware": False,
            },
            "totals": {
                "estimated_seconds": total_seconds,
                "filament_mass_g": round(total_mass_g, 2),
                "filament_length_mm": round(total_filament_mm, 2),
            },
            "parts": part_records,
            "checks": {
                "all_kernel_valid": all(p["kernel_valid"] for p in geometry["parts"]),
                "all_single_solids": all(p["solid_count"] == 1 for p in geometry["parts"]),
                "all_fit_generic_build_volume": all(
                    p["geometry"]["fits_generic_build_volume"] for p in part_records
                ),
                "all_gcode_preflight_passed": all(
                    p["gcode_preflight_passed"] for p in part_records
                ),
                "component_fit_verified": False,
                "assembly_clearance_verified": False,
                "interlock_fit_verified": False,
                "latch_cycle_life_verified": False,
                "physical_print_verified": False,
            },
            "unresolved_warnings": [
                "Exact purchased-component fit is not verified against measured hardware.",
                "The generic 0.4 mm interlock allowance is not calibrated to a printer or material batch.",
                "Snap retention force, removal force, and repeated latch life are not physically verified.",
                "Assembly clearances, collisions, balance, and motion are not physically verified.",
                "The generic printer and PETG profiles are not calibrated to physical hardware.",
                "Slicer support and bridge warnings require human review before a physical attempt.",
                "No physical print, dimensional inspection, strength test, or safety test occurred.",
            ],
            "first_print_calibration": {
                "status": coupon["status"],
                "part_count": coupon["part_count"],
                "candidate_clearances_mm": coupon["candidate_clearances_mm"],
                "candidate_hook_engagements_mm": coupon[
                    "candidate_hook_engagements_mm"
                ],
                "estimated_seconds": coupon["totals"]["estimated_seconds"],
                "filament_mass_g": coupon["totals"]["filament_mass_g"],
                "physical_coupon_printed": coupon["checks"]["physical_coupon_printed"],
                "path": "/demo/interlock-coupon/{0}".format(coupon["download"]["path"]),
                "size_bytes": coupon["download"]["size_bytes"],
                "checksum_sha256": coupon["download"]["checksum_sha256"],
            },
            "claim_boundary": (
                "Nine real prototype meshes were sliced locally with the recorded disconnected "
                "generic profile and their G-code passed digital preflight. This package is a "
                "reviewable prototype handoff, not proof of fit, print success, strength, motion, "
                "safety, or hardware readiness."
            ),
        }
        manifest_path = work / "package-manifest.json"
        _write_json(manifest_path, manifest)

        package_path = output / "ariad-robot-prototype-package.zip"
        with ZipFile(package_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            archive.write(manifest_path, "package-manifest.json")
            for filename in ("parameters.json", "assembly_spec.json"):
                archive.write(ROOT / "benchmarks" / "robot_casing" / filename, f"design/{filename}")
            for source in geometry["parts"]:
                for key in ("step", "stl", "glb"):
                    archive.write(cad_root / source[key], f"parts/{source['part_id']}/{source[key]}")
                slice_root = work / "slices" / source["part_id"]
                for filename in (
                    "toolpath.gcode",
                    "slicer_project.3mf",
                    "slice_report.json",
                    "gcode_preflight.json",
                    "slicer_installation.json",
                    "model_info.stdout.log",
                    "slice.stdout.log",
                    "slice.stderr.log",
                ):
                    archive.write(slice_root / filename, f"parts/{source['part_id']}/{filename}")
            for profile_path in profiles.source_paths:
                archive.write(profile_path, f"profiles/{profile_path.name}")
            archive.write(
                coupon_root / coupon["download"]["path"],
                "calibration/{0}".format(coupon["download"]["path"]),
            )
            archive.write(
                coupon_root / coupon["instructions"],
                "calibration/{0}".format(coupon["instructions"]),
            )

        manifest["download"] = {
            "path": package_path.name,
            "size_bytes": package_path.stat().st_size,
            "checksum_sha256": _sha256(package_path),
        }
        _write_json(output / "manifest.json", manifest)
        print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
