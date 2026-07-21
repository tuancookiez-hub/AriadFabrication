"""Bounded on-demand generation for Ariad's qualified L-bracket family."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .glb import export_glb
from .l_bracket_design import DESIGN_ID, DESIGN_SOURCE_VERSION, LBracketParameters, build_model


ARTIFACT_NAMES = frozenset({"model.step", "model.stl", "preview.glb", "manifest.json"})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_parameters(parameters: LBracketParameters) -> bytes:
    return json.dumps(parameters.__dict__, sort_keys=True, separators=(",", ":")).encode("utf-8")


def generate_l_bracket(values: Mapping[str, Any], root: Path) -> tuple[dict[str, Any], bool]:
    """Generate or deterministically reuse one parameter-bound digital CAD result."""

    parameters = LBracketParameters.from_mapping(values)
    digest = hashlib.sha256(_canonical_parameters(parameters)).hexdigest()
    generation_id = f"lbracket_{digest[:20]}"
    output = root.resolve() / generation_id
    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        return json.loads(manifest_path.read_text(encoding="utf-8")), True

    output.mkdir(parents=True, exist_ok=False)
    try:
        from cadquery import exporters

        model = build_model(parameters)
        step_path = output / "model.step"
        stl_path = output / "model.stl"
        glb_path = output / "preview.glb"
        exporters.export(model, str(step_path))
        exporters.export(model, str(stl_path), tolerance=0.08, angularTolerance=0.12)
        preview = export_glb(
            model.val(),
            glb_path,
            linear_tolerance_mm=0.08,
            angular_tolerance_rad=0.12,
        )
        bounds = model.val().BoundingBox()
        artifacts = []
        for role, path, media_type in (
            ("editable_step", step_path, "model/step"),
            ("compatibility_stl", stl_path, "model/stl"),
            ("browser_preview", glb_path, "model/gltf-binary"),
        ):
            artifacts.append(
                {
                    "role": role,
                    "filename": path.name,
                    "media_type": media_type,
                    "size_bytes": path.stat().st_size,
                    "checksum_sha256": _sha256(path),
                }
            )
        manifest: dict[str, Any] = {
            "schema_version": "1.0.0",
            "generation_id": generation_id,
            "design_id": DESIGN_ID,
            "design_source_version": DESIGN_SOURCE_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "parameter_sha256": digest,
            "parameters": parameters.__dict__,
            "checks": {
                "kernel_valid": bool(model.val().isValid()),
                "solid_count": len(model.solids().vals()),
                "bounds_mm": {
                    "x": round(bounds.xlen, 3),
                    "y": round(bounds.ylen, 3),
                    "z": round(bounds.zlen, 3),
                },
                "preview_triangle_count": preview["triangle_count"],
            },
            "artifacts": artifacts,
            "evidence_mode": "live_digital_generation",
            "claim_boundary": (
                "Fresh parameter-bound CAD and kernel checks only. Printability, slicing, "
                "physical fit, strength, safety, and print success are not validated."
            ),
            "hardware_actions": False,
            "physical_validation": False,
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest, False
    except Exception:
        for path in output.glob("*"):
            if path.is_file():
                path.unlink()
        output.rmdir()
        raise


def live_artifact_path(root: Path, generation_id: str, filename: str) -> Path:
    if not generation_id.startswith("lbracket_") or len(generation_id) != 29:
        raise ValueError("Invalid live generation identifier")
    if filename not in ARTIFACT_NAMES:
        raise ValueError("Unsupported live CAD artifact")
    path = (root.resolve() / generation_id / filename).resolve()
    if path.parent.parent != root.resolve() or not path.is_file():
        raise ValueError("Live CAD artifact not found")
    return path
