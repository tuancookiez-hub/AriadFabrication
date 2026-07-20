"""Out-of-process deterministic CAD worker.

The worker accepts only registered hand-authored providers and fixed artifact
names. Its parent enforces a timeout and strips secrets. This is an explicit
process boundary with path confinement, not yet a hardened no-network sandbox.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import shutil
import sys
from typing import Any, Mapping
from zipfile import ZipFile, is_zipfile
import xml.etree.ElementTree as ET

from ..domain import PartSpec
from ..schema_validation import (
    GEOMETRY_VALIDATION_REPORT_SCHEMA,
    validate_persisted_instance,
)
from .contracts import (
    CAD_CONTRACT_VERSION,
    CadArtifactDescriptor,
    CadArtifactFormat,
    CadBuildRequest,
    CadBuildResult,
)
from .canonical import canonicalize_3mf, canonicalize_step
from .glb import export_glb, inspect_glb
from .golden_part import PROVIDER_ID, build
from .golden_part_design import DESIGN_SOURCE_VERSION
from .stl import inspect_binary_stl
from .validation import validate_golden_part_geometry


WORKER_VERSION = "1.0.0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _descriptor(
    path: Path,
    *,
    relative_path: str,
    role: str,
    media_type: str,
    format: CadArtifactFormat,
    producer: str,
    producer_version: str,
) -> CadArtifactDescriptor:
    payload = path.read_bytes()
    return CadArtifactDescriptor(
        role=role,
        path=relative_path,
        media_type=media_type,
        format=format,
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        producer=producer,
        producer_version=producer_version,
    )


def _inspect_3mf(path: Path) -> dict[str, Any]:
    if not is_zipfile(path):
        raise ValueError("3MF export is not a ZIP-based 3MF package")
    with ZipFile(path) as archive:
        names = set(archive.namelist())
        required = {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"}
        if not required.issubset(names):
            raise ValueError(f"3MF package is missing {sorted(required - names)}")
        root = ET.fromstring(archive.read("3D/3dmodel.model"))
    namespace = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    vertices = root.findall(".//m:vertex", namespace)
    triangles = root.findall(".//m:triangle", namespace)
    if root.attrib.get("unit") != "millimeter" or not vertices or not triangles:
        raise ValueError("3MF model must use millimetres and contain mesh geometry")
    return {
        "unit": "millimeter",
        "vertex_count": len(vertices),
        "triangle_count": len(triangles),
    }


def execute_request(request: CadBuildRequest, output_directory: Path) -> CadBuildResult:
    started_at = _utc_now()
    staging: Path | None = None

    try:
        output_directory = output_directory.resolve()
        parent = output_directory.parent
        parent.mkdir(parents=True, exist_ok=True)
        if output_directory.exists():
            raise FileExistsError(f"immutable CAD output already exists: {output_directory}")

        # Request IDs are external contract data, so never interpolate one into
        # a filesystem path. The digest keeps staging local to the output parent.
        request_key = hashlib.sha256(request.request_id.encode("utf-8")).hexdigest()[:16]
        staging = parent / f".{output_directory.name}.staging-{request_key}"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()

        if request.provider_id != PROVIDER_ID:
            raise ValueError(f"unregistered CAD provider {request.provider_id!r}")

        import cadquery as cq
        import OCP

        tool_versions = {
            "python": platform.python_version(),
            "cadquery": version("cadquery"),
            "cadquery_ocp_distribution": version("cadquery-ocp"),
            "ocp": getattr(OCP, "__version__", "unknown"),
            "cad_worker": WORKER_VERSION,
            "cad_contract": CAD_CONTRACT_VERSION,
            "design_source": DESIGN_SOURCE_VERSION,
        }
        spec = PartSpec.from_mapping(request.spec)
        model, parameters = build(spec, request.expected)
        if len(model.solids().vals()) != 1 or not model.val().isValid():
            raise ValueError("CAD source did not produce one valid solid")

        spec_path = staging / "part_spec.json"
        expected_path = staging / "expected.json"
        parameters_path = staging / "parameters.json"
        source_path = staging / "design.py"
        environment_path = staging / "cad_environment.json"
        report_path = staging / "geometry_validation.json"
        _write_json(spec_path, spec.to_dict())
        _write_json(expected_path, request.to_dict()["expected"])
        _write_json(parameters_path, parameters)
        shutil.copyfile(Path(__file__).with_name("golden_part_design.py"), source_path)

        requested = set(request.requested_formats)
        step_path = staging / "part.step"
        cq.exporters.export(model, str(step_path))
        canonicalize_step(step_path)
        imported = cq.importers.importStep(str(step_path))
        if len(imported.solids().vals()) != 1 or not imported.val().isValid():
            raise ValueError("STEP export did not re-import as one valid solid")

        report = validate_golden_part_geometry(
            imported,
            request.expected,
            tool_versions=tool_versions,
        )
        report_value = report.to_dict()
        validate_persisted_instance(
            report_value,
            GEOMETRY_VALIDATION_REPORT_SCHEMA,
            record_name="generated geometry validation report",
        )
        _write_json(report_path, report_value)

        export_evidence: dict[str, Any] = {
            "step": {
                "reimport_valid": imported.val().isValid(),
                "solid_count": len(imported.solids().vals()),
            }
        }
        if CadArtifactFormat.STL in requested:
            stl_path = staging / "compatibility.stl"
            cq.exporters.export(
                model,
                str(stl_path),
                tolerance=request.linear_tolerance_mm,
                angularTolerance=request.angular_tolerance_rad,
            )
            export_evidence["stl"] = inspect_binary_stl(stl_path)
            export_evidence["stl"]["bytes"] = stl_path.stat().st_size

        if CadArtifactFormat.THREEMF in requested:
            three_mf_path = staging / "part.3mf"
            cq.exporters.export(
                model,
                str(three_mf_path),
                tolerance=request.linear_tolerance_mm,
                angularTolerance=request.angular_tolerance_rad,
            )
            canonicalize_3mf(three_mf_path)
            export_evidence["3mf"] = _inspect_3mf(three_mf_path)

        if CadArtifactFormat.GLB in requested:
            glb_path = staging / "preview.glb"
            export_evidence["glb"] = export_glb(
                model.val(),
                glb_path,
                linear_tolerance_mm=request.linear_tolerance_mm,
                angular_tolerance_rad=request.angular_tolerance_rad,
            )
            inspect_glb(glb_path)

        environment = {
            "schema_version": "1.0.0",
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
            },
            "tool_versions": tool_versions,
            "execution_boundary": {
                "mode": "separate_process_with_timeout_and_confined_output",
                "registered_provider_only": True,
                "secrets_removed_by_parent": True,
                "network_disabled": False,
                "memory_limit_enforced": False,
                "hardened_sandbox": False,
            },
            "tessellation": {
                "linear_tolerance_mm": request.linear_tolerance_mm,
                "angular_tolerance_rad": request.angular_tolerance_rad,
            },
            "export_evidence": export_evidence,
            "canonicalization": {
                "step_header_metadata": "fixed for reproducible hashing",
                "3mf_creation_and_zip_metadata": "fixed for reproducible hashing",
            },
        }
        _write_json(environment_path, environment)

        prefix = output_directory.name
        artifact_specs = [
            ("part_spec", "part_spec.json", "application/json", CadArtifactFormat.JSON),
            (
                "benchmark_expectations",
                "expected.json",
                "application/json",
                CadArtifactFormat.JSON,
            ),
            ("cad_parameters", "parameters.json", "application/json", CadArtifactFormat.JSON),
            ("cad_source", "design.py", "text/x-python", CadArtifactFormat.PYTHON),
            ("exact_geometry", "part.step", "model/step", CadArtifactFormat.STEP),
            (
                "geometry_validation_report",
                "geometry_validation.json",
                "application/json",
                CadArtifactFormat.JSON,
            ),
            (
                "cad_environment",
                "cad_environment.json",
                "application/json",
                CadArtifactFormat.JSON,
            ),
        ]
        if CadArtifactFormat.STL in requested:
            artifact_specs.append(
                ("compatibility_mesh", "compatibility.stl", "model/stl", CadArtifactFormat.STL)
            )
        if CadArtifactFormat.THREEMF in requested:
            artifact_specs.append(
                ("manufacturing_model", "part.3mf", "model/3mf", CadArtifactFormat.THREEMF)
            )
        if CadArtifactFormat.GLB in requested:
            artifact_specs.append(
                ("preview_model", "preview.glb", "model/gltf-binary", CadArtifactFormat.GLB)
            )
        artifacts = tuple(
            _descriptor(
                staging / filename,
                relative_path=f"{prefix}/{filename}",
                role=role,
                media_type=media_type,
                format=format,
                producer="ariad_cad_worker",
                producer_version=WORKER_VERSION,
            )
            for role, filename, media_type, format in artifact_specs
        )
        result = CadBuildResult(
            request_id=request.request_id,
            provider_id=request.provider_id,
            success=True,
            started_at=started_at,
            completed_at=_utc_now(),
            artifacts=artifacts,
            validation_passed=report.passed,
            evidence_level="R2" if report.passed else "R1",
            tool_versions=tool_versions,
            measurements=report.measurements,
        )

        # Publication is the final operation. A failed export, inspection,
        # descriptor, or result validation can therefore never expose a partial
        # immutable design directory.
        staging.rename(output_directory)
        return result
    except Exception as exc:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
        return CadBuildResult(
            request_id=request.request_id,
            provider_id=request.provider_id,
            success=False,
            started_at=started_at,
            completed_at=_utc_now(),
            errors=(f"{type(exc).__name__}: {exc}",),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute one registered Ariad CAD request")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        raw = json.loads(args.request.read_text(encoding="utf-8"))
        request = CadBuildRequest.from_mapping(raw)
        result = execute_request(request, args.output)
    except Exception as exc:
        now = _utc_now()
        result = CadBuildResult(
            request_id="invalid_request",
            provider_id="unavailable",
            success=False,
            started_at=now,
            completed_at=now,
            errors=(f"{type(exc).__name__}: {exc}",),
        )
    args.result.parent.mkdir(parents=True, exist_ok=True)
    _write_json(args.result, result.to_dict())
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
