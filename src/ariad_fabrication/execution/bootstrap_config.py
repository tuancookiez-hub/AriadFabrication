"""Build the sealed Python-worker configuration from a resolved target."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from typing import Sequence

from .import_boundary import ImportAllowlist
from .registry import ResolvedTarget, TargetIntegrityError
from .worker_bootstrap import BOOTSTRAP_VERSION, MAX_CONFIG_BYTES


CAD_RUNTIME_MANIFEST = Path("toolchains/v1/cad-runtime-cpython-3.11-windows-x64.json")
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_MAX_APPLICATION_IMPORT_FILES = 2_000
_MAX_APPLICATION_IMPORT_BYTES = 16 * 1024 * 1024


def _read_strict_json(path: Path, maximum_bytes: int) -> tuple[dict[str, object], str]:
    try:
        with path.open("rb") as stream:
            payload = stream.read(maximum_bytes + 1)
    except OSError as exc:
        raise TargetIntegrityError(f"approved JSON cannot be read: {path.name}") from exc
    if len(payload) > maximum_bytes:
        raise TargetIntegrityError(f"approved JSON exceeds its byte ceiling: {path.name}")

    def strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise TargetIntegrityError(f"approved JSON repeats key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TargetIntegrityError(f"approved JSON is invalid: {path.name}") from exc
    if not isinstance(value, dict):
        raise TargetIntegrityError(f"approved JSON must be an object: {path.name}")
    return value, sha256(payload).hexdigest()


def _application_import_files(project_root: Path) -> dict[Path, str]:
    source = (project_root / "src/ariad_fabrication").resolve(strict=True)
    result: dict[Path, str] = {}
    total = 0
    for directory, names, filenames in os.walk(source, topdown=True, followlinks=False):
        names[:] = sorted(name for name in names if name != "__pycache__")
        current = Path(directory)
        if current.is_symlink():
            raise TargetIntegrityError("application import directories cannot be links")
        for filename in sorted(filenames):
            path = current / filename
            if path.suffix.lower() not in {".py", ".pyd", ".dll"}:
                continue
            if path.is_symlink() or not path.is_file():
                raise TargetIntegrityError("application import files must be regular files")
            payload = path.read_bytes()
            total += len(payload)
            if (
                len(result) >= _MAX_APPLICATION_IMPORT_FILES
                or total > _MAX_APPLICATION_IMPORT_BYTES
            ):
                raise TargetIntegrityError("application import allowlist exceeds its ceiling")
            result[path.resolve()] = sha256(payload).hexdigest()
    if not result:
        raise TargetIntegrityError("application import allowlist is empty")
    return result


def build_registered_import_allowlist(resolved: ResolvedTarget) -> ImportAllowlist:
    if not isinstance(resolved, ResolvedTarget):
        raise TypeError("resolved must be a ResolvedTarget")
    project_root = resolved.project_root.resolve(strict=True)
    manifest_path = (project_root / CAD_RUNTIME_MANIFEST).resolve(strict=True)
    value, manifest_digest = _read_strict_json(manifest_path, _MAX_MANIFEST_BYTES)
    if manifest_digest != resolved.plan.cad_runtime.cad_runtime_manifest_sha256:
        raise TargetIntegrityError("CAD runtime manifest changed after target resolution")
    environment_base = resolved.python_executable.resolve(strict=True).parent.parent
    python_base = Path(sys.base_prefix).resolve(strict=True)
    return ImportAllowlist.from_runtime_manifest(
        manifest_value=value,
        manifest_sha256=manifest_digest,
        python_base=python_base,
        environment_base=environment_base,
        application_files=_application_import_files(project_root),
        accepted_application_bundle_sha256=resolved.plan.application_bundle_sha256,
    )


def write_worker_bootstrap_config(
    resolved: ResolvedTarget,
    destination: Path,
    *,
    arguments: Sequence[str],
) -> Path:
    """Write one immutable configuration for the registered CAD worker."""

    allowlist = build_registered_import_allowlist(resolved)
    if (
        not isinstance(arguments, Sequence)
        or isinstance(arguments, (str, bytes))
        or len(arguments) > 32
        or any(not isinstance(value, str) or not value for value in arguments)
    ):
        raise ValueError("worker arguments are invalid")
    environment_base = resolved.python_executable.resolve(strict=True).parent.parent
    python_base = Path(sys.base_prefix).resolve(strict=True)
    search_path = (
        resolved.project_root / "src",
        environment_base / "Lib/site-packages",
        python_base / "Lib",
        python_base / "DLLs",
    )
    if any(not path.resolve(strict=True).is_dir() for path in search_path):
        raise TargetIntegrityError("registered worker search path is unavailable")
    value = {
        "version": BOOTSTRAP_VERSION,
        "module": "ariad_fabrication.cad.worker",
        "arguments": list(arguments),
        "sys_path": [str(path.resolve()) for path in search_path],
        "files": dict(allowlist.files),
        "namespaces": sorted(allowlist.namespace_directories),
    }
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if len(payload) > MAX_CONFIG_BYTES:
        raise TargetIntegrityError("worker bootstrap configuration exceeds its ceiling")
    path = Path(destination).resolve(strict=False)
    if path.exists():
        raise FileExistsError("worker bootstrap configuration already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return path


__all__ = [
    "build_registered_import_allowlist",
    "write_worker_bootstrap_config",
]
