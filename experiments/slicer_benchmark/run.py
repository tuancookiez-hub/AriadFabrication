"""Run a provenance-tracked real-slicer comparison for Benchy and the warship."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from ariad_fabrication.slicing import ProfileBundle, PrusaSlicerAdapter


EXPERIMENT_VERSION = "1.0.0"
CLAIM_BOUNDARY = (
    "PrusaSlicer produced profile-bearing 3MF projects and G-code that were parsed and "
    "preflighted while disconnected. Slicer warnings remain unresolved findings. No "
    "printer was connected, calibrated, heated, moved, or observed, so physical success "
    "remains unproven."
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _default_slicer(root: Path) -> Path:
    candidates = sorted(
        (root / "runs" / "tools" / "prusaslicer" / "2.9.6" / "portable").glob(
            "**/prusa-slicer-console.exe"
        )
    )
    if len(candidates) != 1:
        raise FileNotFoundError(
            "expected one portable PrusaSlicer 2.9.6 console executable; use --slicer"
        )
    return candidates[0]


def _copy_profiles(root: Path, staging: Path) -> ProfileBundle:
    profile_directory = staging / "profiles"
    profile_directory.mkdir()
    sources = {
        "printer.json": root / "profiles" / "v1" / "printers" / "generic_open_fdm_220.json",
        "material.json": root / "profiles" / "v1" / "materials" / "generic_pla_175.json",
        "process.json": root / "profiles" / "v1" / "processes" / "standard_020_no_support.json",
        "orientation.json": root
        / "profiles"
        / "v1"
        / "orientations"
        / "upright_source_z_centered.json",
        "prusaslicer.ini": root
        / "profiles"
        / "v1"
        / "prusaslicer"
        / "generic_open_fdm_220__generic_pla__standard_020_no_support.ini",
    }
    copied: dict[str, Path] = {}
    for name, source in sources.items():
        destination = profile_directory / name
        shutil.copyfile(source, destination)
        copied[name] = destination
    bundle = ProfileBundle.from_paths(
        printer_path=copied["printer.json"],
        material_path=copied["material.json"],
        process_path=copied["process.json"],
        orientation_path=copied["orientation.json"],
        slicer_config_path=copied["prusaslicer.ini"],
    )
    _write_json(profile_directory / "profile_bundle.json", bundle.to_dict(relative_to=staging))
    return bundle


def _support_related(warnings: tuple[str, ...]) -> bool:
    return any(
        token in warning.lower()
        for warning in warnings
        for token in ("floating", "bridge anchor", "unsupported", "overhang")
    )


def _comparison_entry(name: str, source: Path, outcome: Any) -> dict[str, Any]:
    return {
        "name": name,
        "input": {
            "source_path": source.as_posix(),
            "size_bytes": source.stat().st_size,
            "checksum_sha256": _sha256(source),
        },
        "status": outcome.status,
        "model_info": outcome.model_info.to_dict(),
        "slicer_warnings": list(outcome.slicer_warnings),
        "support_related_warning": _support_related(outcome.slicer_warnings),
        "preflight_passed": outcome.preflight.passed,
        "layer_count": outcome.summary.layer_count,
        "estimated_seconds": outcome.summary.estimated_seconds,
        "filament_length_mm": outcome.summary.filament_length_mm,
        "filament_volume_cm3": outcome.summary.filament_volume_cm3,
        "filament_mass_g": outcome.summary.filament_mass_g,
        "generated_support_feature_count": sum(
            count
            for feature, count in outcome.summary.feature_counts.items()
            if "support" in feature.lower()
        ),
    }


def _comparison_markdown(comparison: Mapping[str, Any]) -> str:
    models = comparison["models"]

    def duration(seconds: int) -> str:
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}h {minutes}m {seconds}s"

    rows = []
    for key in ("3dbenchy", "conventional_warship"):
        item = models[key]
        warnings = ", ".join(item["slicer_warnings"]) or "none"
        rows.append(
            f"| {item['name']} | {item['status']} | {item['layer_count']} | "
            f"{duration(item['estimated_seconds'])} | {item['filament_mass_g']:.2f} g | "
            f"{item['model_info']['facets_removed']} | {warnings} |"
        )
    return "\n".join(
        (
            "# Real-slicer comparison",
            "",
            "Both models used the same PrusaSlicer executable, composite profile, and upright centered orientation.",
            "",
            "| Model | Status | Layers | Estimate | PLA | Repaired facets | Slicer findings |",
            "|---|---:|---:|---:|---:|---:|---|",
            *rows,
            "",
            f"**Warship support-free candidate:** {str(comparison['warship_support_free_candidate']).lower()}",
            "",
            comparison["conclusion"],
            "",
            f"**Evidence boundary:** {CLAIM_BOUNDARY}",
            "",
        )
    )


def run(
    *,
    root: Path,
    slicer: Path,
    tool_archive: Path | None,
    benchy: Path,
    warship: Path,
    output_directory: Path,
) -> dict[str, Any]:
    root = root.resolve()
    slicer = slicer.resolve()
    benchy = benchy.resolve()
    warship = warship.resolve()
    output_directory = output_directory.resolve()
    if output_directory.exists():
        raise FileExistsError(f"immutable experiment output already exists: {output_directory}")
    for path in (slicer, benchy, warship):
        if not path.is_file():
            raise FileNotFoundError(path)

    provenance_path = root / "benchmarks" / "3dbenchy" / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if provenance["checksum_sha256"] != _sha256(benchy):
        raise ValueError("3DBenchy checksum differs from its pinned provenance")
    warship_report_path = warship.with_name("geometry_report.json")
    warship_geometry = json.loads(warship_report_path.read_text(encoding="utf-8"))
    if not warship_geometry.get("passed"):
        raise ValueError("warship geometry report did not pass")

    output_directory.parent.mkdir(parents=True, exist_ok=True)
    staging = output_directory.parent / f".{output_directory.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        shutil.copyfile(Path(__file__), staging / "run.py")
        shutil.copyfile(provenance_path, staging / "3dbenchy_provenance.json")
        shutil.copyfile(warship_report_path, staging / "warship_geometry_report.json")
        profiles = _copy_profiles(root, staging)
        adapter = PrusaSlicerAdapter(slicer)

        tool = adapter.installation.to_dict()
        if tool_archive is not None:
            archive = tool_archive.resolve()
            if not archive.is_file():
                raise FileNotFoundError(archive)
            tool["portable_archive"] = {
                "filename": archive.name,
                "size_bytes": archive.stat().st_size,
                "checksum_sha256": _sha256(archive),
                "release_url": (
                    "https://github.com/prusa3d/PrusaSlicer/releases/download/"
                    "version_2.9.6/PrusaSlicer-2.9.6.zip"
                ),
            }
        tool.update(
            {
                "installation_scope": "portable under ignored runs/tools; not system-installed",
                "selection_reason": (
                    "Dedicated documented Windows console executable, stable official release, "
                    "smaller portable archive than the reviewed OrcaSlicer alternative, and "
                    "successful local Benchy/warship CLI spike."
                ),
                "alternative_reviewed": {
                    "tool": "OrcaSlicer",
                    "version": "2.4.2",
                    "license": "AGPL-3.0",
                    "release_url": "https://github.com/OrcaSlicer/OrcaSlicer/releases/tag/v2.4.2",
                    "portable_archive_size_bytes": 171367668,
                    "reason_not_first": (
                        "Larger runtime and less mature CLI evidence for this first adapter; "
                        "kept as a replaceable future adapter."
                    ),
                },
                "removal_path": (
                    "Delete the ignored runs/tools/prusaslicer directory and remove the adapter "
                    "selection decision; profile contracts and benchmark fixtures remain usable."
                ),
                "boundary": (
                    "Local CLI process with confined explicit paths and no printer adapter. "
                    "Network denial and OS-level resource limits are not enforced by this spike."
                ),
            }
        )
        _write_json(staging / "slicer_environment.json", tool)

        models_directory = staging / "models"
        models_directory.mkdir()
        sources = {"3dbenchy": benchy, "conventional_warship": warship}
        outcomes = {}
        for key, source in sources.items():
            model_directory = models_directory / key
            model_directory.mkdir()
            copied_model = model_directory / "input.stl"
            shutil.copyfile(source, copied_model)
            outcomes[key] = adapter.slice_model(copied_model, model_directory, profiles)

        entries = {
            key: _comparison_entry(
                "Official 3DBenchy" if key == "3dbenchy" else "Ariad conventional warship v1",
                sources[key],
                outcomes[key],
            )
            for key in sources
        }
        warship_clean = (
            outcomes["conventional_warship"].preflight.passed
            and not _support_related(outcomes["conventional_warship"].slicer_warnings)
        )
        comparison = {
            "schema_version": "1.0.0",
            "experiment_version": EXPERIMENT_VERSION,
            "classification": "real_slicer_comparison",
            "profile_ids": {
                "printer": profiles.printer.profile_id,
                "material": profiles.material.profile_id,
                "process": profiles.process.profile_id,
                "orientation": profiles.orientation.orientation_id,
            },
            "models": entries,
            "both_real_slices_completed": all(item.preflight.passed for item in outcomes.values()),
            "warship_support_free_candidate": warship_clean,
            "physical_validation": "not_started",
            "conclusion": (
                "Both models produced real G-code that passed disconnected preflight. The warship "
                "is not accepted as a clean support-free candidate because PrusaSlicer reported "
                "floating bridge anchors; revise that geometry or explicitly evaluate supports "
                "before any physical attempt."
                if not warship_clean
                else
                "Both models produced real G-code that passed disconnected preflight, and the "
                "warship produced no support-related slicer warning. Physical behavior remains untested."
            ),
            "claim_boundary": CLAIM_BOUNDARY,
        }
        _write_json(staging / "comparison.json", comparison)
        (staging / "comparison.md").write_text(
            _comparison_markdown(comparison), encoding="utf-8", newline="\n"
        )

        artifact_paths = tuple(
            sorted(path for path in staging.rglob("*") if path.is_file())
        )
        manifest = {
            "schema_version": "1.0.0",
            "experiment_version": EXPERIMENT_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "classification": "real_slicer_comparison",
            "artifacts": [
                {
                    "path": path.relative_to(staging).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "checksum_sha256": _sha256(path),
                }
                for path in artifact_paths
            ],
            "claim_boundary": CLAIM_BOUNDARY,
        }
        _write_json(staging / "manifest.json", manifest)
        staging.rename(output_directory)
        return {
            "output_directory": str(output_directory),
            "comparison": comparison,
            "manifest": str(output_directory / "manifest.json"),
        }
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Compare Benchy and the warship in a real slicer")
    parser.add_argument("--slicer", type=Path)
    parser.add_argument("--tool-archive", type=Path)
    parser.add_argument(
        "--benchy",
        type=Path,
        default=root / "benchmarks" / "3dbenchy" / "3DBenchy.stl",
    )
    parser.add_argument(
        "--warship",
        type=Path,
        default=root
        / "runs"
        / "experiments"
        / "conventional_warship"
        / "v1"
        / "conventional_warship.stl",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    slicer = args.slicer or _default_slicer(root)
    archive = args.tool_archive
    if archive is None:
        candidate = root / "runs" / "tools" / "prusaslicer" / "2.9.6" / "PrusaSlicer-2.9.6.zip"
        archive = candidate if candidate.is_file() else None
    result = run(
        root=root,
        slicer=slicer,
        tool_archive=archive,
        benchy=args.benchy,
        warship=args.warship,
        output_directory=args.output_dir,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
