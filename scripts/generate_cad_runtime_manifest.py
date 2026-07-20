"""Generate Ariad's traced CPython/CAD execution-runtime manifest.

This runs the registered Golden Part CAD worker in-process solely to observe the
Python modules it loads.  The resulting committed manifest identifies the
curated CPython runtime, every loaded dependency module, and all DLLs owned by
the distributions used by that trace.  It starts no slicer or hardware action.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "toolchains/v1/cad-runtime-cpython-3.11-windows-x64.json"
TRACE_ROOT = ROOT / "runs/verification/runtime-manifest-traces"
READ_CHUNK_BYTES = 1024 * 1024
TREE_ALGORITHM = "ariad-tree-sha256-v1"
_NORMALIZE_DISTRIBUTION = re.compile(r"[-_.]+")

_EXCLUDED_BASE_DIRECTORIES = {
    "__pycache__",
    "site-packages",
    "test",
    "tests",
    "tkinter",
    "idlelib",
    "ensurepip",
    "turtledemo",
    "venv",
    "lib2to3",
}
_BASE_ROOT_FILES = {
    "BUILD",
    "python.exe",
    "python3.dll",
    "python311.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _hash_file(path: Path) -> tuple[str, int]:
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise RuntimeError(f"runtime manifest input is not a regular file: {path}")
    digest = sha256()
    read = 0
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_size, opened.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise RuntimeError(f"runtime file changed before hashing: {path}")
        while read < before.st_size:
            block = handle.read(min(READ_CHUNK_BYTES, before.st_size - read))
            if not block:
                raise RuntimeError(f"runtime file ended while hashing: {path}")
            read += len(block)
            digest.update(block)
        if handle.read(1):
            raise RuntimeError(f"runtime file grew while hashing: {path}")
        after = os.fstat(handle.fileno())
    if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
        raise RuntimeError(f"runtime file changed while hashing: {path}")
    return digest.hexdigest(), before.st_size


def _is_link_or_reparse(path: Path) -> bool:
    value = path.lstat()
    attributes = getattr(value, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(value.st_mode) or bool(attributes & reparse)


def _regular_files(root: Path) -> Iterable[Path]:
    stack = [root]
    while stack:
        directory = stack.pop()
        children = sorted(directory.iterdir(), key=lambda item: (item.name.casefold(), item.name))
        for child in children:
            if _is_link_or_reparse(child):
                raise RuntimeError(f"runtime inputs cannot contain links: {child}")
            if child.is_dir():
                stack.append(child)
            elif child.is_file():
                yield child
            else:
                raise RuntimeError(f"unsupported runtime input: {child}")


def _tree(base: Path, files: Iterable[Path]) -> dict[str, Any]:
    unique = sorted(
        {path.resolve() for path in files},
        key=lambda path: (path.relative_to(base).as_posix().casefold(), path.as_posix()),
    )
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in unique:
        if _is_link_or_reparse(path):
            raise RuntimeError(f"runtime files cannot be links: {path}")
        relative = path.relative_to(base).as_posix()
        folded = relative.casefold()
        if folded in seen:
            raise RuntimeError(f"case-insensitive runtime path collision: {relative}")
        seen.add(folded)
        digest, size = _hash_file(path)
        entries.append({"path": relative, "size_bytes": size, "sha256": digest})
    digest = sha256(
        _canonical_bytes({"algorithm": TREE_ALGORITHM, "files": entries})
    ).hexdigest()
    return {
        "file_count": len(entries),
        "size_bytes": sum(item["size_bytes"] for item in entries),
        "tree_sha256": digest,
        "files": entries,
    }


def _base_runtime_files(base: Path) -> set[Path]:
    selected = {base / name for name in _BASE_ROOT_FILES}
    selected.update(_regular_files(base / "DLLs"))
    for path in _regular_files(base / "Lib"):
        relative_parts = {part.casefold() for part in path.relative_to(base / "Lib").parts[:-1]}
        if relative_parts & _EXCLUDED_BASE_DIRECTORIES:
            continue
        if path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        selected.add(path)
    if any(not path.is_file() for path in selected):
        raise RuntimeError("a required CPython runtime file is unavailable")
    return selected


def _application_bundle() -> dict[str, Any]:
    selected = {ROOT / "pyproject.toml"}
    for directory in (ROOT / "src/ariad_fabrication", ROOT / "schemas/v1"):
        for path in _regular_files(directory):
            if "__pycache__" in path.parts or path.suffix.lower() in {".pyc", ".pyo"}:
                continue
            selected.add(path)
    return _tree(ROOT, selected)


def _normalize_distribution(name: str) -> str:
    return _NORMALIZE_DISTRIBUTION.sub("-", name).lower()


def _run_trace() -> tuple[dict[str, Any], set[Path]]:
    from ariad_fabrication.cad.contracts import CadBuildRequest
    from ariad_fabrication.cad.golden_part import PROVIDER_ID
    from ariad_fabrication.cad.worker import execute_request

    spec_path = ROOT / "benchmarks/golden_part/part_spec.json"
    expected_path = ROOT / "benchmarks/golden_part/expected.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    TRACE_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="trace-", dir=TRACE_ROOT) as temporary:
        output = Path(temporary) / "revision"
        request = CadBuildRequest(
            request_id="cadreq_runtime_manifest_trace",
            job_id="job_runtime_manifest_trace",
            revision_id="rev_runtime_manifest_trace",
            provider_id=PROVIDER_ID,
            spec=spec,
            expected=expected,
        )
        result = execute_request(request, output)
        if not result.success or not result.validation_passed:
            raise RuntimeError("registered Golden Part trace did not pass R2")

    # Import the remaining R4 Python lane so its standard/dependency imports are
    # represented even though the manifest generator never launches a slicer.
    import ariad_fabrication.gcode_validate  # noqa: F401
    import ariad_fabrication.slicing.pipeline  # noqa: F401
    import ariad_fabrication.slicing.printability  # noqa: F401
    import ariad_fabrication.slicing.prusaslicer  # noqa: F401

    module_paths: set[Path] = set()
    for module in sys.modules.values():
        raw = getattr(module, "__file__", None)
        if not raw:
            continue
        try:
            path = Path(raw).resolve()
        except OSError:
            continue
        if path.is_file():
            module_paths.add(path)
    evidence = {
        "benchmark_id": "opengrow_stake_electronics_clamp_v1",
        "target": "golden_part_r4_python_lane",
        "cad_worker_success": True,
        "geometry_validation_passed": True,
        "requested_formats": ["step", "stl", "3mf", "glb"],
        "part_spec_sha256": sha256(spec_path.read_bytes()).hexdigest(),
        "geometry_expectations_sha256": sha256(expected_path.read_bytes()).hexdigest(),
        "module_file_count_observed": len(module_paths),
        "claim_boundary": (
            "The trace proves which Python module files were loaded by this successful "
            "registered digital path on the recorded runtime. It does not prove that "
            "unmanifested modules can never load until the process adapter enforces the "
            "allowlist, and it is not physical evidence."
        ),
    }
    return evidence, module_paths


def build_manifest() -> dict[str, Any]:
    if sys.platform != "win32" or sys.version_info[:2] != (3, 11):
        raise RuntimeError("the approved CAD runtime manifest requires CPython 3.11 on Windows")
    base = Path(sys.base_prefix).resolve()
    prefix = Path(sys.prefix).resolve()
    purelib = Path(sysconfig_path("purelib")).resolve()
    if not purelib.is_relative_to(prefix):
        raise RuntimeError("site-packages must remain inside the active environment")
    application = _application_bundle()
    trace, module_paths = _run_trace()
    trace["application_bundle_sha256"] = application["tree_sha256"]

    distributions = list(importlib.metadata.distributions(path=[str(purelib)]))
    owner: dict[Path, str] = {}
    installed: dict[str, str] = {}
    for distribution in distributions:
        raw_name = distribution.metadata.get("Name")
        if not raw_name:
            raise RuntimeError("an installed distribution has no name")
        name = _normalize_distribution(raw_name)
        if name in installed:
            raise RuntimeError(f"duplicate installed distribution: {name}")
        installed[name] = distribution.version
        for relative in distribution.files or ():
            path = Path(distribution.locate_file(relative)).resolve()
            if path.is_relative_to(purelib):
                owner[path] = name

    environment_modules = {path for path in module_paths if path.is_relative_to(purelib)}
    selected_distributions = sorted(
        {owner[path] for path in environment_modules if path in owner}
    )
    environment_files = set(environment_modules)
    for path, distribution in owner.items():
        if distribution in selected_distributions and path.suffix.lower() in {
            ".py",
            ".pyd",
            ".dll",
        }:
            environment_files.add(path)
    for path in purelib.glob("*.pth"):
        environment_files.add(path.resolve())
    virtualenv_hook = purelib / "_virtualenv.py"
    if virtualenv_hook.is_file():
        environment_files.add(virtualenv_hook.resolve())
    environment_configuration = prefix / "pyvenv.cfg"
    if not environment_configuration.is_file():
        raise RuntimeError("the active CAD environment has no pyvenv.cfg")
    environment_files.add(environment_configuration.resolve())

    base_tree = _tree(base, _base_runtime_files(base))
    environment_tree = _tree(prefix, environment_files)
    trace["module_file_count_in_python_base"] = sum(
        path.is_relative_to(base) for path in module_paths
    )
    trace["module_file_count_in_dependency_environment"] = len(environment_modules)
    installed = dict(sorted(installed.items()))
    return {
        "schema_version": "1.0.0",
        "manifest_kind": "traced_cad_execution_runtime",
        "platform": "windows",
        "architecture": "x86_64",
        "python": {
            "implementation": sys.implementation.name,
            "version": platform_version(),
            "build": (base / "BUILD").read_text(encoding="utf-8").strip(),
            "runtime_selection": (
                "Core executables, all DLLs, and standard-library files excluding "
                "development, GUI, test, ensurepip, venv, and transient bytecode trees."
            ),
            "runtime": base_tree,
        },
        "dependency_environment": {
            "lock_file": "uv.lock",
            "lock_sha256": sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
            "installed_distribution_count": len(installed),
            "installed_distributions": installed,
            "selected_distribution_count": len(selected_distributions),
            "selected_distributions": selected_distributions,
            "runtime_selection": (
                "Every importable Python/native module and DLL owned by a distribution "
                "observed in the registered trace, plus pyvenv.cfg and every active "
                "environment .pth/bootstrap file."
            ),
            "runtime": environment_tree,
        },
        "trace_evidence": trace,
        "claim_boundary": (
            "This manifest content-identifies the curated runtime for Ariad's registered "
            "digital Golden Part lane. It does not launch a slicer, contact hardware, "
            "prove process isolation, or establish physical print evidence."
        ),
    }


def sysconfig_path(name: str) -> str:
    import sysconfig

    value = sysconfig.get_path(name)
    if not value:
        raise RuntimeError(f"Python runtime path is unavailable: {name}")
    return value


def platform_version() -> str:
    import platform

    return platform.python_version()


def _render(value: MappingLike) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


MappingLike = dict[str, Any]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    rendered = _render(build_manifest())
    if arguments.check:
        if not OUTPUT.is_file() or OUTPUT.read_bytes() != rendered:
            print(f"CAD runtime manifest drifted: {OUTPUT}", file=sys.stderr)
            return 1
        print(f"CAD runtime manifest is current: {OUTPUT}")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(rendered)
    print(f"Wrote {OUTPUT} ({len(rendered)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
