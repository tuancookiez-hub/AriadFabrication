"""Trusted, content-addressed resolution of Ariad's two executable targets.

The public resolver accepts only an execution target.  Every path and provider
is selected internally from the checkout, and resolution performs no process,
network, browser, or hardware action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import struct
import sys
import sysconfig
import tomllib
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ..cad.golden_part import parameters_from_spec
from ..domain import PartSpec
from ..schema_validation import PART_SPEC_SCHEMA, validate_persisted_instance
from ..slicing.profiles import ProfileBundle
from .contracts import (
    CADQUERY_VERSION,
    GOLDEN_PART_BENCHMARK_ID,
    OCP_VERSION,
    CadRuntimeSnapshot,
    ExecutionPlan,
    ExecutionTarget,
    HostRuntimeSnapshot,
    R4ProfileSnapshot,
    SlicerSnapshot,
)


TREE_ALGORITHM = "ariad-tree-sha256-v1"
TARGET_REGISTRY_VERSION = "1.0.0"
MAX_JSON_ASSET_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NORMALIZE_DISTRIBUTION = re.compile(r"[-_.]+")
_REGISTRY_SEAL = object()

_PART_SPEC = "benchmarks/golden_part/part_spec.json"
_GEOMETRY_EXPECTATIONS = "benchmarks/golden_part/expected.json"
_PRINTABILITY_EXPECTATIONS = "benchmarks/golden_part/printability_expected.json"
_CAD_SOURCE = "src/ariad_fabrication/cad/golden_part_design.py"
_DEPENDENCY_LOCK = "uv.lock"
_PRINTER_PROFILE = "profiles/v1/printers/generic_open_fdm_220.json"
_MATERIAL_PROFILE = "profiles/v1/materials/generic_petg_175.json"
_PROCESS_PROFILE = "profiles/v1/processes/golden_part_020_no_support.json"
_ORIENTATION_PROFILE = "profiles/v1/orientations/upright_source_z_centered.json"
_SLICER_CONFIG = (
    "profiles/v1/prusaslicer/"
    "generic_open_fdm_220__generic_petg__golden_part_020_no_support.ini"
)
_SLICER_MANIFEST = "toolchains/v1/prusaslicer-2.9.6-windows-x64.json"
_CAD_RUNTIME_MANIFEST = "toolchains/v1/cad-runtime-cpython-3.11-windows-x64.json"


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value

_PRODUCTION_ASSET_SHA256 = MappingProxyType(
    {
        _PART_SPEC: "34f3299a921e497b7d9e4bfa3c458a5ce30c2ee047ccc6ccd730224800d12445",
        _GEOMETRY_EXPECTATIONS: (
            "81fe5be964b47c727a581f2590a56bacd69ca3885cfc5c12db568e1e138b4f7d"
        ),
        _PRINTABILITY_EXPECTATIONS: (
            "2054b84759cfb105c5084762681be80dd9269a083e2df9fd6d920be6310cb44a"
        ),
        _CAD_SOURCE: "08eea4f647ac39358b33a4de1b1d1e691c9109ee78a06066a775b73a7231a305",
        _DEPENDENCY_LOCK: (
            "b88e851cd7704a95ecb83469b1c2c49b60ebe0582f8f187cd72389c869e90547"
        ),
        _PRINTER_PROFILE: (
            "f83ac088ba54fa09df383fb496b68ad2e36b44e272db53022372d3e7a727f53e"
        ),
        _MATERIAL_PROFILE: (
            "e136278521073456457b67cf35dfbb349fea3fbe3daa8de5466f86265822513a"
        ),
        _PROCESS_PROFILE: (
            "7e5eda7c28df90f00e2212d1729e551e057068ceccfc6605b8ee70ec06097fb1"
        ),
        _ORIENTATION_PROFILE: (
            "6b910a9b7f3e1c074e5b61963f4fc1c6f7ca563ac5899373195a1f14d35a97c9"
        ),
        _SLICER_CONFIG: (
            "6cfe25a5d60280a18cb5eee82dc05654fc28b52bde706b72c48b8b38d32b46c9"
        ),
    }
)


class TargetRegistryError(RuntimeError):
    """Base class for a target that cannot be admitted safely."""


class TargetUnavailableError(TargetRegistryError):
    """A required approved dependency is absent on this host."""


class TargetIntegrityError(TargetRegistryError):
    """A present target input differs from its approved or accepted identity."""


@dataclass(frozen=True)
class _Approval:
    asset_sha256: Mapping[str, str]
    slicer_manifest_sha256: str
    slicer_archive_sha256: str
    slicer_archive_size_bytes: int

    def __post_init__(self) -> None:
        assets = dict(self.asset_sha256)
        if set(assets) != set(_PRODUCTION_ASSET_SHA256):
            raise ValueError("registry approval must name every fixed target asset")
        for name, digest in assets.items():
            _digest(digest, f"approved digest for {name}")
        _digest(self.slicer_manifest_sha256, "approved slicer manifest digest")
        _digest(self.slicer_archive_sha256, "approved slicer archive digest")
        if type(self.slicer_archive_size_bytes) is not int or self.slicer_archive_size_bytes <= 0:
            raise ValueError("approved slicer archive size must be a positive integer")
        object.__setattr__(self, "asset_sha256", MappingProxyType(assets))


_PRODUCTION_APPROVAL = _Approval(
    asset_sha256=_PRODUCTION_ASSET_SHA256,
    slicer_manifest_sha256=(
        "9caf181848d739493c509eb82eff1412b520805da6e57551a3c586c458c9700d"
    ),
    slicer_archive_sha256=(
        "5aaf22e42f95accecfa122d23a835911f289ecc2ff606db3e83d637ddcc0a209"
    ),
    slicer_archive_size_bytes=106_598_059,
)


@dataclass(frozen=True)
class _Layout:
    project_root: Path
    python_executable: Path
    python_base: Path
    environment_root: Path
    purelib: Path
    platlib: Path
    cad_runtime_manifest: Path
    slicer_archive: Path
    slicer_installation: Path
    slicer_manifest: Path


@dataclass(frozen=True)
class _FileEntry:
    path: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class _TreeIdentity:
    sha256: str
    file_count: int
    size_bytes: int
    files: tuple[_FileEntry, ...] = field(repr=False)


@dataclass(frozen=True)
class ResolvedTarget:
    """A registry-sealed target plan and the internally selected local paths."""

    plan: ExecutionPlan
    project_root: Path
    python_executable: Path
    part_spec_path: Path
    geometry_expectations_path: Path
    cad_source_path: Path
    dependency_lock_path: Path
    printability_expectations_path: Path | None
    profile_paths: tuple[Path, ...]
    slicer_executable_path: Path | None
    hardware_actions: bool = False
    _seal: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _REGISTRY_SEAL:
            raise ValueError("ResolvedTarget values may only be created by the trusted registry")
        if self.hardware_actions:
            raise ValueError("resolved targets cannot enable hardware actions")
        r4 = self.plan.target is ExecutionTarget.GOLDEN_PART_R4
        if r4 != (self.printability_expectations_path is not None):
            raise ValueError("resolved target printability paths do not match the plan")
        if r4 != (self.slicer_executable_path is not None):
            raise ValueError("resolved target slicer path does not match the plan")
        if r4 != bool(self.profile_paths):
            raise ValueError("resolved target profile paths do not match the plan")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _is_link_or_reparse(path: Path) -> bool:
    try:
        value = path.lstat()
    except OSError as exc:
        raise TargetUnavailableError(f"required target path is unavailable: {path}") from exc
    attributes = getattr(value, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(value.st_mode) or bool(attributes & reparse)


def _regular_file_snapshot(path: Path, *, maximum_bytes: int) -> tuple[int, int, int]:
    if _is_link_or_reparse(path):
        raise TargetIntegrityError(f"target files cannot be links or reparse points: {path}")
    try:
        value = path.stat()
    except OSError as exc:
        raise TargetUnavailableError(f"required target file is unavailable: {path}") from exc
    if not stat.S_ISREG(value.st_mode):
        raise TargetUnavailableError(f"required target path is not a regular file: {path}")
    if value.st_size > maximum_bytes:
        raise TargetIntegrityError(f"target file exceeds its resource limit: {path}")
    return value.st_size, value.st_mtime_ns, getattr(value, "st_ino", 0)


def _hash_file(
    path: Path,
    *,
    maximum_bytes: int,
    expected_size: int | None = None,
) -> tuple[str, int]:
    size, mtime_ns, inode = _regular_file_snapshot(path, maximum_bytes=maximum_bytes)
    if expected_size is not None and size != expected_size:
        raise TargetIntegrityError(f"target file has an unexpected size: {path}")
    digest = sha256()
    read = 0
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or (
                before.st_size,
                before.st_mtime_ns,
                getattr(before, "st_ino", 0),
            ) != (size, mtime_ns, inode):
                raise TargetIntegrityError(f"target file changed before hashing: {path}")
            while read < size:
                block = handle.read(min(READ_CHUNK_BYTES, size - read))
                if not block:
                    raise TargetIntegrityError(f"target file ended while hashing: {path}")
                read += len(block)
                digest.update(block)
            if handle.read(1):
                raise TargetIntegrityError(f"target file grew while hashing: {path}")
            after = os.fstat(handle.fileno())
    except TargetRegistryError:
        raise
    except OSError as exc:
        raise TargetUnavailableError(f"required target file cannot be read: {path}") from exc
    if (after.st_size, after.st_mtime_ns, getattr(after, "st_ino", 0)) != (
        size,
        mtime_ns,
        inode,
    ):
        raise TargetIntegrityError(f"target file changed while hashing: {path}")
    return digest.hexdigest(), size


def _snapshot_file(path: Path, *, maximum_bytes: int) -> tuple[bytes, str]:
    size, mtime_ns, inode = _regular_file_snapshot(path, maximum_bytes=maximum_bytes)
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if (
                before.st_size,
                before.st_mtime_ns,
                getattr(before, "st_ino", 0),
            ) != (size, mtime_ns, inode):
                raise TargetIntegrityError(f"target file changed before capture: {path}")
            payload = handle.read(size + 1)
            after = os.fstat(handle.fileno())
    except TargetRegistryError:
        raise
    except OSError as exc:
        raise TargetUnavailableError(f"required target file cannot be read: {path}") from exc
    if len(payload) != size or (
        after.st_size,
        after.st_mtime_ns,
        getattr(after, "st_ino", 0),
    ) != (size, mtime_ns, inode):
        raise TargetIntegrityError(f"target file changed during capture: {path}")
    return payload, sha256(payload).hexdigest()


def _safe_relative(path: Path, base: Path) -> str:
    try:
        relative = path.relative_to(base)
    except ValueError as exc:
        raise TargetIntegrityError(f"target path escapes its approved root: {path}") from exc
    value = relative.as_posix()
    if not value or len(value) > 512 or "\\" in value:
        raise TargetIntegrityError(f"target path has an unsupported relative name: {path}")
    parts = PurePosixPath(value).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise TargetIntegrityError(f"target path has an unsafe relative name: {path}")
    return value


def _collect_files(
    base: Path,
    selected: Sequence[Path],
    *,
    exclude_transient_python: bool,
    maximum_files: int,
    maximum_bytes: int,
) -> list[tuple[Path, str, int, int, int]]:
    if _is_link_or_reparse(base) or not base.is_dir():
        raise TargetIntegrityError(f"target tree root must be a regular directory: {base}")
    base = base.resolve(strict=True)
    stack = list(reversed(selected))
    found: list[tuple[Path, str, int, int, int]] = []
    casefolded: set[str] = set()
    checked_components: set[Path] = {base}
    total_bytes = 0
    while stack:
        candidate = stack.pop()
        try:
            relative_candidate = candidate.relative_to(base)
        except ValueError as exc:
            raise TargetIntegrityError(
                f"selected target path escapes its tree root: {candidate}"
            ) from exc
        current = base
        for part in relative_candidate.parts:
            current /= part
            if current in checked_components:
                continue
            if _is_link_or_reparse(current):
                raise TargetIntegrityError(
                    f"target tree entries cannot be links or reparse points: {current}"
                )
            checked_components.add(current)
        if _is_link_or_reparse(candidate):
            raise TargetIntegrityError(
                f"target tree entries cannot be links or reparse points: {candidate}"
            )
        if candidate.is_dir():
            if exclude_transient_python and candidate.name == "__pycache__":
                continue
            try:
                children = sorted(
                    candidate.iterdir(), key=lambda item: (item.name.casefold(), item.name)
                )
            except OSError as exc:
                raise TargetUnavailableError(
                    f"target directory cannot be enumerated: {candidate}"
                ) from exc
            stack.extend(reversed(children))
            continue
        if not candidate.is_file():
            raise TargetUnavailableError(f"target tree entry is not a file: {candidate}")
        if exclude_transient_python and candidate.suffix.lower() in {".pyc", ".pyo"}:
            continue
        relative = _safe_relative(candidate.resolve(strict=True), base)
        folded = relative.casefold()
        if folded in casefolded:
            raise TargetIntegrityError(
                f"target tree contains a case-insensitive path collision: {relative}"
            )
        casefolded.add(folded)
        size, mtime_ns, inode = _regular_file_snapshot(
            candidate, maximum_bytes=maximum_bytes
        )
        total_bytes += size
        if len(found) >= maximum_files or total_bytes > maximum_bytes:
            raise TargetIntegrityError("target tree exceeds its resource limits")
        found.append((candidate, relative, size, mtime_ns, inode))
    found.sort(key=lambda item: (item[1].casefold(), item[1]))
    return found


def _fingerprint_tree(
    base: Path,
    selected: Sequence[Path],
    *,
    exclude_transient_python: bool,
    maximum_files: int,
    maximum_bytes: int,
) -> _TreeIdentity:
    first = _collect_files(
        base,
        selected,
        exclude_transient_python=exclude_transient_python,
        maximum_files=maximum_files,
        maximum_bytes=maximum_bytes,
    )
    entries: list[_FileEntry] = []
    for path, relative, size, _, _ in first:
        digest, actual_size = _hash_file(
            path, maximum_bytes=maximum_bytes, expected_size=size
        )
        entries.append(_FileEntry(relative, actual_size, digest))
    second = _collect_files(
        base,
        selected,
        exclude_transient_python=exclude_transient_python,
        maximum_files=maximum_files,
        maximum_bytes=maximum_bytes,
    )
    first_state = tuple((item[1], item[2], item[3], item[4]) for item in first)
    second_state = tuple((item[1], item[2], item[3], item[4]) for item in second)
    if first_state != second_state:
        raise TargetIntegrityError("target tree changed while it was being fingerprinted")
    files_value = [item.to_dict() for item in entries]
    digest = sha256(
        _canonical_bytes({"algorithm": TREE_ALGORITHM, "files": files_value})
    ).hexdigest()
    return _TreeIdentity(
        sha256=digest,
        file_count=len(entries),
        size_bytes=sum(item.size_bytes for item in entries),
        files=tuple(entries),
    )


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key is not allowed: {key!r}")
        result[key] = value
    return result


def _read_json(path: Path, *, maximum_bytes: int) -> tuple[dict[str, Any], str]:
    payload, digest = _snapshot_file(path, maximum_bytes=maximum_bytes)
    try:
        value = json.loads(
            payload.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise TargetIntegrityError(f"target JSON is invalid: {path}") from exc
    if not isinstance(value, dict):
        raise TargetIntegrityError(f"target JSON must contain an object: {path}")
    return value, digest


def _read_toml(path: Path, *, maximum_bytes: int) -> tuple[dict[str, Any], str]:
    payload, digest = _snapshot_file(path, maximum_bytes=maximum_bytes)
    try:
        value = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise TargetIntegrityError(f"target TOML is invalid: {path}") from exc
    return value, digest


def _normalize_distribution(name: str) -> str:
    return _NORMALIZE_DISTRIBUTION.sub("-", name).lower()


def _marker_applies(markers: Any) -> bool:
    if markers is None:
        return True
    if not isinstance(markers, list) or any(not isinstance(item, str) for item in markers):
        raise TargetIntegrityError("dependency lock has invalid resolution markers")
    supported = {
        "python_full_version < '3.12'": sys.version_info < (3, 12),
        "python_full_version >= '3.12'": sys.version_info >= (3, 12),
    }
    unknown = set(markers) - set(supported)
    if unknown:
        raise TargetIntegrityError(
            f"dependency lock uses unsupported resolution marker {sorted(unknown)[0]!r}"
        )
    return any(supported[item] for item in markers)


def _validate_locked_environment(
    lock: Mapping[str, Any], purelib: Path
) -> dict[str, str]:
    packages = lock.get("package")
    if not isinstance(packages, list):
        raise TargetIntegrityError("dependency lock does not contain a package array")
    locked: dict[str, str] = {}
    for item in packages:
        if not isinstance(item, Mapping):
            raise TargetIntegrityError("dependency lock package entry is invalid")
        if not _marker_applies(item.get("resolution-markers")):
            continue
        name = item.get("name")
        version = item.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise TargetIntegrityError("dependency lock package identity is invalid")
        normalized = _normalize_distribution(name)
        if normalized in locked and locked[normalized] != version:
            raise TargetIntegrityError("dependency lock selects conflicting package versions")
        locked[normalized] = version
    installed: dict[str, str] = {}
    try:
        distributions = importlib.metadata.distributions(path=[str(purelib)])
        for distribution in distributions:
            raw_name = distribution.metadata.get("Name")
            if not raw_name:
                raise TargetIntegrityError("installed distribution is missing its name")
            name = _normalize_distribution(raw_name)
            if name in installed:
                raise TargetIntegrityError(f"installed distribution is duplicated: {name}")
            installed[name] = distribution.version
    except TargetRegistryError:
        raise
    except Exception as exc:
        raise TargetUnavailableError("installed dependency metadata cannot be read") from exc
    if installed != locked:
        missing = sorted(set(locked) - set(installed))
        extra = sorted(set(installed) - set(locked))
        changed = sorted(
            name
            for name in set(locked) & set(installed)
            if locked[name] != installed[name]
        )
        detail = (
            f"missing={missing[:3]}, extra={extra[:3]}, version_drift={changed[:3]}"
        )
        raise TargetUnavailableError(f"installed dependencies do not match uv.lock: {detail}")
    if installed.get("cadquery") != CADQUERY_VERSION:
        raise TargetUnavailableError("the approved CadQuery version is unavailable")
    if installed.get("cadquery-ocp") != OCP_VERSION:
        raise TargetUnavailableError("the approved cadquery-ocp version is unavailable")
    return installed


def _exact_keys(value: Any, names: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TargetIntegrityError(f"{name} must be an object")
    if set(value) != names:
        raise TargetIntegrityError(f"{name} has unsupported or missing fields")
    return value


def _manifest_file_entry(value: Any) -> _FileEntry:
    mapping = _exact_keys(value, {"path", "size_bytes", "sha256"}, "manifest file")
    path = mapping["path"]
    if not isinstance(path, str) or not path or len(path) > 512 or "\\" in path:
        raise TargetIntegrityError("manifest file path is invalid")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or parsed.as_posix() != path or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise TargetIntegrityError("manifest file path is unsafe")
    size = mapping["size_bytes"]
    if type(size) is not int or size < 0:
        raise TargetIntegrityError("manifest file size is invalid")
    try:
        digest = _digest(mapping["sha256"], "manifest file digest")
    except ValueError as exc:
        raise TargetIntegrityError(str(exc)) from exc
    return _FileEntry(path, size, digest)


def _parse_manifest_tree(
    value: Any,
    *,
    name: str,
    maximum_files: int,
    maximum_bytes: int,
) -> _TreeIdentity:
    mapping = _exact_keys(
        value,
        {"file_count", "size_bytes", "tree_sha256", "files"},
        name,
    )
    raw_files = mapping["files"]
    if not isinstance(raw_files, list) or not 1 <= len(raw_files) <= maximum_files:
        raise TargetIntegrityError(f"{name} file list is invalid")
    files = tuple(_manifest_file_entry(item) for item in raw_files)
    paths = [item.path for item in files]
    if paths != sorted(paths, key=lambda item: (item.casefold(), item)):
        raise TargetIntegrityError(f"{name} files are not canonically ordered")
    if len({item.casefold() for item in paths}) != len(paths):
        raise TargetIntegrityError(f"{name} contains a path collision")
    size = sum(item.size_bytes for item in files)
    if size > maximum_bytes:
        raise TargetIntegrityError(f"{name} exceeds its size limit")
    digest = sha256(
        _canonical_bytes(
            {"algorithm": TREE_ALGORITHM, "files": [item.to_dict() for item in files]}
        )
    ).hexdigest()
    if (
        mapping["file_count"] != len(files)
        or mapping["size_bytes"] != size
        or mapping["tree_sha256"] != digest
    ):
        raise TargetIntegrityError(f"{name} aggregate identity is inconsistent")
    return _TreeIdentity(digest, len(files), size, files)


def _parse_cad_runtime_manifest(
    value: Mapping[str, Any],
) -> tuple[_TreeIdentity, _TreeIdentity, dict[str, str]]:
    top = _exact_keys(
        value,
        {
            "schema_version",
            "manifest_kind",
            "platform",
            "architecture",
            "python",
            "dependency_environment",
            "trace_evidence",
            "claim_boundary",
        },
        "CAD runtime manifest",
    )
    if {
        "schema_version": top["schema_version"],
        "manifest_kind": top["manifest_kind"],
        "platform": top["platform"],
        "architecture": top["architecture"],
    } != {
        "schema_version": "1.0.0",
        "manifest_kind": "traced_cad_execution_runtime",
        "platform": "windows",
        "architecture": "x86_64",
    }:
        raise TargetIntegrityError("CAD runtime manifest identifies an unsupported runtime")
    if not isinstance(top["claim_boundary"], str) or not top["claim_boundary"].strip():
        raise TargetIntegrityError("CAD runtime manifest claim boundary is required")
    python_value = _exact_keys(
        top["python"],
        {"implementation", "version", "build", "runtime_selection", "runtime"},
        "CAD Python runtime",
    )
    if (
        python_value["implementation"] != "cpython"
        or python_value["version"] != platform.python_version()
        or not isinstance(python_value["build"], str)
        or not python_value["build"].strip()
        or not isinstance(python_value["runtime_selection"], str)
        or not python_value["runtime_selection"].strip()
    ):
        raise TargetIntegrityError("CAD Python runtime identity is inconsistent")
    python_tree = _parse_manifest_tree(
        python_value["runtime"],
        name="CAD Python runtime tree",
        maximum_files=2_000,
        maximum_bytes=128 * 1024 * 1024,
    )
    environment = _exact_keys(
        top["dependency_environment"],
        {
            "lock_file",
            "lock_sha256",
            "installed_distribution_count",
            "installed_distributions",
            "selected_distribution_count",
            "selected_distributions",
            "runtime_selection",
            "runtime",
        },
        "CAD dependency environment",
    )
    if (
        environment["lock_file"] != "uv.lock"
        or not isinstance(environment["runtime_selection"], str)
        or not environment["runtime_selection"].strip()
    ):
        raise TargetIntegrityError("CAD dependency environment metadata is invalid")
    try:
        _digest(environment["lock_sha256"], "CAD runtime lock digest")
    except ValueError as exc:
        raise TargetIntegrityError(str(exc)) from exc
    raw_installed = environment["installed_distributions"]
    if not isinstance(raw_installed, Mapping) or any(
        not isinstance(name, str)
        or not name
        or name != _normalize_distribution(name)
        or not isinstance(version, str)
        or not version
        for name, version in raw_installed.items()
    ):
        raise TargetIntegrityError("CAD runtime distribution inventory is invalid")
    installed = dict(raw_installed)
    if environment["installed_distribution_count"] != len(installed):
        raise TargetIntegrityError("CAD runtime distribution count is inconsistent")
    selected = environment["selected_distributions"]
    if (
        not isinstance(selected, list)
        or any(
            not isinstance(name, str)
            or not name
            or name != _normalize_distribution(name)
            for name in selected
        )
        or selected != sorted(set(selected))
        or environment["selected_distribution_count"] != len(selected)
        or not set(selected).issubset(installed)
    ):
        raise TargetIntegrityError("CAD runtime selected distributions are invalid")
    environment_tree = _parse_manifest_tree(
        environment["runtime"],
        name="CAD dependency runtime tree",
        maximum_files=4_000,
        maximum_bytes=1024 * 1024 * 1024,
    )
    trace = _exact_keys(
        top["trace_evidence"],
        {
            "benchmark_id",
            "target",
            "cad_worker_success",
            "geometry_validation_passed",
            "requested_formats",
            "part_spec_sha256",
            "geometry_expectations_sha256",
            "module_file_count_observed",
            "claim_boundary",
            "module_file_count_in_python_base",
            "module_file_count_in_dependency_environment",
            "application_bundle_sha256",
        },
        "CAD runtime trace evidence",
    )
    if (
        trace["benchmark_id"] != GOLDEN_PART_BENCHMARK_ID
        or trace["target"] != "golden_part_r4_python_lane"
        or trace["cad_worker_success"] is not True
        or trace["geometry_validation_passed"] is not True
        or trace["requested_formats"] != ["step", "stl", "3mf", "glb"]
        or trace["part_spec_sha256"] != _PRODUCTION_ASSET_SHA256[_PART_SPEC]
        or trace["geometry_expectations_sha256"]
        != _PRODUCTION_ASSET_SHA256[_GEOMETRY_EXPECTATIONS]
        or not isinstance(trace["application_bundle_sha256"], str)
        or not isinstance(trace["claim_boundary"], str)
    ):
        raise TargetIntegrityError("CAD runtime trace evidence is inconsistent")
    for name in (
        "module_file_count_observed",
        "module_file_count_in_python_base",
        "module_file_count_in_dependency_environment",
    ):
        if type(trace[name]) is not int or trace[name] <= 0:
            raise TargetIntegrityError("CAD runtime trace counts are invalid")
    return python_tree, environment_tree, installed


_PYTHON_RUNTIME_ROOT_FILES = frozenset(
    {
        "BUILD",
        "python.exe",
        "python3.dll",
        "python311.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
    }
)
_PYTHON_RUNTIME_EXCLUDED_DIRECTORIES = frozenset(
    {
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
)


def _walk_runtime_policy_files(
    root: Path, *, excluded_directories: frozenset[str] = frozenset()
) -> tuple[Path, ...]:
    selected: list[Path] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        if _is_link_or_reparse(directory):
            raise TargetIntegrityError(f"runtime directories cannot be links: {directory}")
        try:
            children = sorted(
                directory.iterdir(), key=lambda item: (item.name.casefold(), item.name)
            )
        except OSError as exc:
            raise TargetUnavailableError(f"runtime directory cannot be read: {directory}") from exc
        for child in children:
            if _is_link_or_reparse(child):
                raise TargetIntegrityError(f"runtime entries cannot be links: {child}")
            if child.is_dir():
                if child.name.casefold() not in excluded_directories:
                    stack.append(child)
            elif child.is_file():
                if child.suffix.lower() not in {".pyc", ".pyo"}:
                    selected.append(child)
            else:
                raise TargetIntegrityError(f"unsupported runtime entry: {child}")
    return tuple(selected)


def _python_runtime_policy_files(base: Path) -> tuple[Path, ...]:
    files = [base / name for name in sorted(_PYTHON_RUNTIME_ROOT_FILES)]
    files.extend(_walk_runtime_policy_files(base / "DLLs"))
    files.extend(
        _walk_runtime_policy_files(
            base / "Lib", excluded_directories=_PYTHON_RUNTIME_EXCLUDED_DIRECTORIES
        )
    )
    return tuple(files)


def _fingerprint_manifest_files(base: Path, expected: _TreeIdentity) -> _TreeIdentity:
    selected = tuple(base / PurePosixPath(item.path) for item in expected.files)
    return _fingerprint_tree(
        base,
        selected,
        exclude_transient_python=False,
        maximum_files=max(1, expected.file_count),
        maximum_bytes=max(1, expected.size_bytes),
    )


def _parse_slicer_manifest(value: Mapping[str, Any]) -> tuple[_TreeIdentity, str]:
    top = _exact_keys(
        value,
        {
            "schema_version",
            "manifest_kind",
            "tool",
            "version",
            "platform",
            "architecture",
            "adapter",
            "portable_archive",
            "installation",
            "claim_boundary",
        },
        "slicer manifest",
    )
    expected = {
        "schema_version": "1.0.0",
        "manifest_kind": "approved_portable_toolchain",
        "tool": "PrusaSlicer",
        "version": "2.9.6",
        "platform": "windows",
        "architecture": "x86_64",
    }
    if any(top[name] != expected_value for name, expected_value in expected.items()):
        raise TargetIntegrityError("slicer manifest names an unsupported toolchain")
    if not isinstance(top["claim_boundary"], str) or not top["claim_boundary"].strip():
        raise TargetIntegrityError("slicer manifest claim boundary is required")
    adapter = _exact_keys(top["adapter"], {"id", "version"}, "slicer adapter")
    if adapter != {"id": "prusaslicer_cli", "version": "1.0.0"}:
        raise TargetIntegrityError("slicer manifest adapter identity is not approved")
    archive = _exact_keys(
        top["portable_archive"],
        {"filename", "size_bytes", "sha256", "release_url"},
        "slicer archive",
    )
    if archive["filename"] != "PrusaSlicer-2.9.6.zip" or not isinstance(
        archive["release_url"], str
    ):
        raise TargetIntegrityError("slicer archive provenance is invalid")
    installation = _exact_keys(
        top["installation"],
        {
            "root_directory_name",
            "executable",
            "file_count",
            "size_bytes",
            "tree_sha256",
            "files",
        },
        "slicer installation",
    )
    if installation["root_directory_name"] != "PrusaSlicer-2.9.6":
        raise TargetIntegrityError("slicer installation root is not approved")
    if installation["executable"] != "prusa-slicer-console.exe":
        raise TargetIntegrityError("slicer executable name is not approved")
    raw_files = installation["files"]
    if not isinstance(raw_files, list) or not 1 <= len(raw_files) <= 2_000:
        raise TargetIntegrityError("slicer manifest file list is invalid")
    files = tuple(_manifest_file_entry(item) for item in raw_files)
    paths = [item.path for item in files]
    if paths != sorted(paths, key=lambda item: (item.casefold(), item)):
        raise TargetIntegrityError("slicer manifest files are not canonically ordered")
    if len({item.casefold() for item in paths}) != len(paths):
        raise TargetIntegrityError("slicer manifest contains a path collision")
    size = sum(item.size_bytes for item in files)
    if size > 512 * 1024 * 1024:
        raise TargetIntegrityError("slicer manifest exceeds its installation size limit")
    tree_digest = sha256(
        _canonical_bytes(
            {"algorithm": TREE_ALGORITHM, "files": [item.to_dict() for item in files]}
        )
    ).hexdigest()
    if (
        installation["file_count"] != len(files)
        or installation["size_bytes"] != size
        or installation["tree_sha256"] != tree_digest
    ):
        raise TargetIntegrityError("slicer manifest aggregate identity is inconsistent")
    executable = next((item for item in files if item.path == installation["executable"]), None)
    if executable is None:
        raise TargetIntegrityError("slicer manifest does not contain its executable")
    return _TreeIdentity(tree_digest, len(files), size, files), executable.sha256


class TrustedTargetRegistry:
    """Resolve and re-verify the fixed Golden Part R2/R4 target allowlist."""

    def __init__(self, layout: _Layout, approval: _Approval, *, _seal: object) -> None:
        if _seal is not _REGISTRY_SEAL:
            raise ValueError("use TrustedTargetRegistry.from_checkout()")
        self._layout = layout
        self._approval = approval

    @classmethod
    def from_checkout(cls) -> "TrustedTargetRegistry":
        root = Path(__file__).resolve().parents[3]
        purelib = Path(sysconfig.get_path("purelib")).resolve()
        platlib = Path(sysconfig.get_path("platlib")).resolve()
        layout = _Layout(
            project_root=root,
            python_executable=Path(sys.executable).resolve(),
            python_base=Path(sys.base_prefix).resolve(),
            environment_root=Path(sys.prefix).resolve(),
            purelib=purelib,
            platlib=platlib,
            cad_runtime_manifest=root / _CAD_RUNTIME_MANIFEST,
            slicer_archive=root / "runs/tools/prusaslicer/2.9.6/PrusaSlicer-2.9.6.zip",
            slicer_installation=(
                root
                / "runs/tools/prusaslicer/2.9.6/portable/PrusaSlicer-2.9.6"
            ),
            slicer_manifest=root / _SLICER_MANIFEST,
        )
        return cls(layout, _PRODUCTION_APPROVAL, _seal=_REGISTRY_SEAL)

    @classmethod
    def _from_layout_for_test(
        cls, layout: _Layout, approval: _Approval
    ) -> "TrustedTargetRegistry":
        return cls(layout, approval, _seal=_REGISTRY_SEAL)

    def resolve(self, target: ExecutionTarget | str) -> ResolvedTarget:
        try:
            target_value = target if isinstance(target, ExecutionTarget) else ExecutionTarget(target)
        except (TypeError, ValueError) as exc:
            raise TargetUnavailableError(f"unsupported execution target {target!r}") from exc
        common = self._resolve_common()
        profiles: tuple[Path, ...] = ()
        printability_path: Path | None = None
        slicer_path: Path | None = None
        slicer_snapshot: SlicerSnapshot | None = None
        profile_snapshot: R4ProfileSnapshot | None = None
        printability_digest: str | None = None
        if target_value is ExecutionTarget.GOLDEN_PART_R4:
            (
                printability_path,
                printability_digest,
                profiles,
                profile_snapshot,
                slicer_path,
                slicer_snapshot,
            ) = self._resolve_r4()
        plan = ExecutionPlan(
            target=target_value,
            part_spec_sha256=common["part_spec_sha256"],
            geometry_expectations_sha256=common["geometry_expectations_sha256"],
            cad_source_sha256=common["cad_source_sha256"],
            dependency_lock_sha256=common["dependency_lock_sha256"],
            application_bundle_sha256=common["application_bundle_sha256"],
            cad_runtime=common["cad_runtime"],
            printability_validator_version="1.0.0" if printability_path else None,
            fabrication_pipeline_version="1.0.0" if printability_path else None,
            printability_expectations_sha256=printability_digest,
            profiles=profile_snapshot,
            slicer=slicer_snapshot,
        )
        root = self._layout.project_root.resolve()
        return ResolvedTarget(
            plan=plan,
            project_root=root,
            python_executable=self._layout.python_executable.resolve(),
            part_spec_path=(root / _PART_SPEC).resolve(),
            geometry_expectations_path=(root / _GEOMETRY_EXPECTATIONS).resolve(),
            cad_source_path=(root / _CAD_SOURCE).resolve(),
            dependency_lock_path=(root / _DEPENDENCY_LOCK).resolve(),
            printability_expectations_path=printability_path,
            profile_paths=profiles,
            slicer_executable_path=slicer_path,
            _seal=_REGISTRY_SEAL,
        )

    def reverify(self, accepted_plan: ExecutionPlan) -> ResolvedTarget:
        if not isinstance(accepted_plan, ExecutionPlan):
            raise TypeError("accepted_plan must be an ExecutionPlan")
        current = self.resolve(accepted_plan.target)
        if current.plan != accepted_plan:
            accepted = accepted_plan.to_dict()
            actual = current.plan.to_dict()
            changed = [name for name in sorted(accepted) if accepted[name] != actual[name]]
            summary = ", ".join(changed[:8])
            raise TargetIntegrityError(
                f"accepted execution identity no longer matches the target: {summary}"
            )
        return current

    def _project_path(self, relative: str) -> Path:
        root = self._layout.project_root.resolve()
        if _is_link_or_reparse(root):
            raise TargetIntegrityError("project root cannot be a link or reparse point")
        parsed = PurePosixPath(relative)
        if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
            raise TargetIntegrityError(f"approved asset name is unsafe: {relative}")
        candidate = root
        for part in parsed.parts:
            candidate /= part
            if _is_link_or_reparse(candidate):
                raise TargetIntegrityError(
                    f"approved asset path cannot contain a link: {relative}"
                )
        try:
            path = candidate.resolve(strict=True)
        except OSError as exc:
            raise TargetUnavailableError(f"approved target asset is unavailable: {relative}") from exc
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise TargetIntegrityError(f"approved asset escapes the project root: {relative}") from exc
        return path

    def _approved_asset(self, relative: str) -> tuple[Path, str]:
        path = self._project_path(relative)
        expected = self._approval.asset_sha256[relative]
        _, actual = _snapshot_file(path, maximum_bytes=MAX_JSON_ASSET_BYTES)
        if actual != expected:
            raise TargetIntegrityError(f"approved target asset drifted: {relative}")
        return path, actual

    def _project_layout_path(self, path: Path, name: str) -> Path:
        root = self._layout.project_root.resolve()
        candidate = Path(path).absolute()
        try:
            relative = candidate.relative_to(root)
        except ValueError as exc:
            raise TargetIntegrityError(f"{name} escapes the project root") from exc
        current = root
        for part in relative.parts:
            current /= part
            if _is_link_or_reparse(current):
                raise TargetIntegrityError(f"{name} path cannot contain a link")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise TargetUnavailableError(f"{name} is unavailable") from exc
        if not resolved.is_relative_to(root):
            raise TargetIntegrityError(f"{name} escapes the project root")
        return resolved

    def _resolve_common(self) -> dict[str, Any]:
        if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 11):
            raise TargetUnavailableError("the target requires CPython 3.11")
        if (
            sys.platform != "win32"
            or platform.machine().lower() not in {"amd64", "x86_64"}
            or struct.calcsize("P") != 8
        ):
            raise TargetUnavailableError("the registered target currently requires Windows x86-64")
        root = self._layout.project_root.resolve()
        app = _fingerprint_tree(
            root,
            (
                root / "pyproject.toml",
                root / "src/ariad_fabrication",
                root / "schemas/v1",
            ),
            exclude_transient_python=True,
            maximum_files=1_024,
            maximum_bytes=32 * 1024 * 1024,
        )
        python_executable_sha256, _ = _hash_file(
            self._layout.python_executable, maximum_bytes=128 * 1024 * 1024
        )
        part_spec_path, part_spec_digest = self._approved_asset(_PART_SPEC)
        geometry_path, geometry_digest = self._approved_asset(_GEOMETRY_EXPECTATIONS)
        _, cad_source_digest = self._approved_asset(_CAD_SOURCE)
        lock_path, lock_digest = self._approved_asset(_DEPENDENCY_LOCK)
        part_spec_value, captured_part_spec = _read_json(
            part_spec_path, maximum_bytes=MAX_JSON_ASSET_BYTES
        )
        geometry_value, captured_geometry = _read_json(
            geometry_path, maximum_bytes=MAX_JSON_ASSET_BYTES
        )
        if captured_part_spec != part_spec_digest or captured_geometry != geometry_digest:
            raise TargetIntegrityError("approved benchmark input changed during resolution")
        validate_persisted_instance(
            part_spec_value, PART_SPEC_SCHEMA, record_name="registered target PartSpec"
        )
        spec = PartSpec.from_mapping(part_spec_value)
        spec.assert_ready_for_design()
        if (
            geometry_value.get("benchmark_id") != GOLDEN_PART_BENCHMARK_ID
            or geometry_value.get("target_evidence_level") != "R2"
            or geometry_value.get("status") != "frozen_for_m2"
        ):
            raise TargetIntegrityError("geometry expectations do not identify the approved R2 gate")
        parameters_from_spec(spec, geometry_value)
        lock_value, captured_lock = _read_toml(
            lock_path, maximum_bytes=MAX_JSON_ASSET_BYTES
        )
        if captured_lock != lock_digest:
            raise TargetIntegrityError("approved dependency lock changed during resolution")
        installed = _validate_locked_environment(lock_value, self._layout.purelib)
        runtime_manifest_digest, python_runtime, environment = (
            self._resolve_cad_runtime(lock_digest, installed, app.sha256)
        )
        return {
            "part_spec_sha256": part_spec_digest,
            "geometry_expectations_sha256": geometry_digest,
            "cad_source_sha256": cad_source_digest,
            "dependency_lock_sha256": lock_digest,
            "application_bundle_sha256": app.sha256,
            "cad_runtime": CadRuntimeSnapshot(
                python_version=platform.python_version(),
                python_executable_sha256=python_executable_sha256,
                cad_runtime_manifest_sha256=runtime_manifest_digest,
                python_runtime_sha256=python_runtime.sha256,
                dependency_environment_sha256=environment.sha256,
                host=HostRuntimeSnapshot(
                    system=platform.system(),
                    release=platform.release(),
                    version=platform.version(),
                    machine=platform.machine(),
                ),
            ),
        }

    def _resolve_cad_runtime(
        self,
        lock_digest: str,
        installed: Mapping[str, str],
        application_bundle_digest: str,
    ) -> tuple[str, _TreeIdentity, _TreeIdentity]:
        manifest_path = self._project_path(_CAD_RUNTIME_MANIFEST)
        if manifest_path != self._layout.cad_runtime_manifest.resolve():
            raise TargetIntegrityError("CAD runtime manifest layout is inconsistent")
        manifest, manifest_digest = _read_json(
            manifest_path, maximum_bytes=MAX_MANIFEST_BYTES
        )
        expected_python, expected_environment, expected_installed = (
            _parse_cad_runtime_manifest(manifest)
        )
        environment_value = manifest["dependency_environment"]
        if environment_value["lock_sha256"] != lock_digest:
            raise TargetIntegrityError("CAD runtime manifest does not match uv.lock")
        if expected_installed != dict(installed):
            raise TargetIntegrityError(
                "installed distribution inventory differs from the CAD runtime manifest"
            )
        if (
            manifest["trace_evidence"]["application_bundle_sha256"]
            != application_bundle_digest
        ):
            raise TargetIntegrityError(
                "CAD runtime trace does not match the current application bundle"
            )
        actual_python = _fingerprint_tree(
            self._layout.python_base,
            _python_runtime_policy_files(self._layout.python_base),
            exclude_transient_python=False,
            maximum_files=2_000,
            maximum_bytes=128 * 1024 * 1024,
        )
        if actual_python != expected_python:
            raise TargetIntegrityError("CPython runtime differs from its approved manifest")
        try:
            purelib_relative = self._layout.purelib.relative_to(
                self._layout.environment_root
            ).as_posix()
        except ValueError as exc:
            raise TargetIntegrityError(
                "dependency environment escapes the active Python environment"
            ) from exc
        expected_pth = {
            item.path.casefold()
            for item in expected_environment.files
            if PurePosixPath(item.path).parent == PurePosixPath(purelib_relative)
            and PurePosixPath(item.path).suffix.lower() == ".pth"
        }
        try:
            actual_pth = {
                item.relative_to(self._layout.environment_root).as_posix().casefold()
                for item in self._layout.purelib.glob("*.pth")
                if item.is_file()
            }
        except OSError as exc:
            raise TargetUnavailableError("environment bootstrap files cannot be read") from exc
        if actual_pth != expected_pth:
            raise TargetIntegrityError("environment bootstrap .pth inventory drifted")
        expected_paths = {item.path.casefold() for item in expected_environment.files}
        for name in ("sitecustomize.py", "usercustomize.py"):
            startup_path = self._layout.purelib / name
            startup_relative = startup_path.relative_to(
                self._layout.environment_root
            ).as_posix().casefold()
            if startup_path.exists() and startup_relative not in expected_paths:
                raise TargetIntegrityError(
                    f"unapproved Python startup customization is present: {name}"
                )
        actual_environment = _fingerprint_manifest_files(
            self._layout.environment_root, expected_environment
        )
        if actual_environment != expected_environment:
            raise TargetIntegrityError(
                "CAD dependency runtime differs from its approved manifest"
            )
        return manifest_digest, actual_python, actual_environment

    def _resolve_r4(
        self,
    ) -> tuple[
        Path,
        str,
        tuple[Path, ...],
        R4ProfileSnapshot,
        Path,
        SlicerSnapshot,
    ]:
        printability_path, printability_digest = self._approved_asset(
            _PRINTABILITY_EXPECTATIONS
        )
        printability, captured_printability = _read_json(
            printability_path, maximum_bytes=MAX_JSON_ASSET_BYTES
        )
        if captured_printability != printability_digest:
            raise TargetIntegrityError("approved printability policy changed during resolution")
        if (
            printability.get("benchmark_id") != GOLDEN_PART_BENCHMARK_ID
            or printability.get("target_evidence_level") != "R3"
            or printability.get("status") != "frozen_for_m3"
        ):
            raise TargetIntegrityError("printability policy does not identify the approved R3 gate")
        profile_relatives = (
            _PRINTER_PROFILE,
            _MATERIAL_PROFILE,
            _PROCESS_PROFILE,
            _ORIENTATION_PROFILE,
            _SLICER_CONFIG,
        )
        approved_profiles = [self._approved_asset(name) for name in profile_relatives]
        profile_paths = tuple(item[0] for item in approved_profiles)
        bundle = ProfileBundle.from_paths(
            printer_path=profile_paths[0],
            material_path=profile_paths[1],
            process_path=profile_paths[2],
            orientation_path=profile_paths[3],
            slicer_config_path=profile_paths[4],
        )
        for (profile_path, expected_digest) in approved_profiles:
            actual_digest, _ = _hash_file(
                profile_path, maximum_bytes=MAX_JSON_ASSET_BYTES
            )
            if actual_digest != expected_digest:
                raise TargetIntegrityError("approved profile changed during validation")
        required = printability.get("required_profile")
        if not isinstance(required, Mapping):
            raise TargetIntegrityError("printability policy is missing required_profile")
        required_identity = {
            "printer_profile_family_id": bundle.printer.profile_family_id,
            "printer_profile_id": bundle.printer.profile_id,
            "material_type": bundle.material.material_type,
            "material_profile_id": bundle.material.profile_id,
            "process_profile_id": bundle.process.profile_id,
            "orientation_id": bundle.orientation.orientation_id,
            "nozzle_diameter_mm": bundle.printer.nozzle_diameter_mm,
            "layer_height_mm": bundle.process.layer_height_mm,
            "infill_percent": bundle.process.infill_percent,
            "support_policy": bundle.process.support_policy,
        }
        if dict(required) != required_identity:
            raise TargetIntegrityError("printability policy and profile bundle identities differ")
        profile_snapshot = R4ProfileSnapshot(
            printer_profile_sha256=approved_profiles[0][1],
            material_profile_sha256=approved_profiles[1][1],
            process_profile_sha256=approved_profiles[2][1],
            orientation_sha256=approved_profiles[3][1],
            slicer_config_sha256=approved_profiles[4][1],
        )
        manifest_path = self._project_path(_SLICER_MANIFEST)
        if manifest_path != self._layout.slicer_manifest.resolve():
            raise TargetIntegrityError("slicer manifest layout is inconsistent")
        manifest_value, manifest_digest = _read_json(
            manifest_path, maximum_bytes=MAX_MANIFEST_BYTES
        )
        if manifest_digest != self._approval.slicer_manifest_sha256:
            raise TargetIntegrityError("approved slicer manifest drifted")
        manifest_tree, executable_digest = _parse_slicer_manifest(manifest_value)
        archive = _exact_keys(
            manifest_value["portable_archive"],
            {"filename", "size_bytes", "sha256", "release_url"},
            "slicer archive",
        )
        if (
            archive["size_bytes"] != self._approval.slicer_archive_size_bytes
            or archive["sha256"] != self._approval.slicer_archive_sha256
        ):
            raise TargetIntegrityError("slicer manifest archive identity is not approved")
        archive_path = self._project_layout_path(
            self._layout.slicer_archive, "slicer archive"
        )
        installation_path = self._project_layout_path(
            self._layout.slicer_installation, "slicer installation"
        )
        if archive_path.name != archive["filename"]:
            raise TargetIntegrityError("slicer archive filename differs from its manifest")
        if installation_path.name != manifest_value["installation"]["root_directory_name"]:
            raise TargetIntegrityError("slicer installation directory differs from its manifest")
        archive_digest, _ = _hash_file(
            archive_path,
            maximum_bytes=256 * 1024 * 1024,
            expected_size=self._approval.slicer_archive_size_bytes,
        )
        if archive_digest != self._approval.slicer_archive_sha256:
            raise TargetIntegrityError("approved slicer archive drifted")
        actual_tree = _fingerprint_tree(
            installation_path,
            (installation_path,),
            exclude_transient_python=False,
            maximum_files=2_000,
            maximum_bytes=512 * 1024 * 1024,
        )
        if actual_tree != manifest_tree:
            raise TargetIntegrityError("installed slicer runtime differs from its manifest")
        executable_path = (
            installation_path
            / str(manifest_value["installation"]["executable"])
        ).resolve()
        actual_executable, _ = _hash_file(
            executable_path, maximum_bytes=64 * 1024 * 1024
        )
        if actual_executable != executable_digest:
            raise TargetIntegrityError("installed slicer executable differs from its manifest")
        return (
            printability_path,
            printability_digest,
            profile_paths,
            profile_snapshot,
            executable_path,
            SlicerSnapshot(
                executable_sha256=actual_executable,
                portable_archive_sha256=archive_digest,
                installation_manifest_sha256=manifest_digest,
                installation_tree_sha256=actual_tree.sha256,
            ),
        )


__all__ = [
    "ResolvedTarget",
    "TARGET_REGISTRY_VERSION",
    "TREE_ALGORITHM",
    "TargetIntegrityError",
    "TargetRegistryError",
    "TargetUnavailableError",
    "TrustedTargetRegistry",
]
