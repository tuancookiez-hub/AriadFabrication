"""Manifest-backed import enforcement for sealed Ariad Python workers.

This module provides one process-local control.  It does not provide filesystem
or network isolation and is not, by itself, permission to expose browser Run.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import importlib.abc
import importlib.machinery
import os
from pathlib import Path, PurePosixPath
import sys
from types import MappingProxyType
from typing import Iterator, Mapping, Sequence

from .registry import TargetIntegrityError, _parse_cad_runtime_manifest


IMPORT_BOUNDARY_VERSION = "0.1.0"
_MAX_IMPORT_FILE_BYTES = 128 * 1024 * 1024


class ImportBoundaryError(ImportError):
    """A module escaped or drifted from the accepted import allowlist."""


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _checked_relative_path(root: Path, relative: str, name: str) -> Path:
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise TargetIntegrityError(f"{name} contains an unsafe path: {relative}")
    candidate = (root / Path(*parsed.parts)).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise TargetIntegrityError(f"{name} escapes its approved root: {relative}") from exc
    return candidate


@dataclass(frozen=True)
class ImportAllowlist:
    """Exact path-to-SHA-256 approvals for one accepted Python worker."""

    files: Mapping[str, str]
    namespace_directories: frozenset[str]
    application_bundle_sha256: str
    manifest_sha256: str
    version: str = IMPORT_BOUNDARY_VERSION

    def __post_init__(self) -> None:
        if self.version != IMPORT_BOUNDARY_VERSION:
            raise ValueError("unsupported import boundary version")
        files = {_path_key(Path(path)): digest for path, digest in self.files.items()}
        if not files:
            raise ValueError("import allowlist cannot be empty")
        if any(
            not isinstance(path, str)
            or not path
            or not isinstance(digest, str)
            or len(digest) != 64
            for path, digest in files.items()
        ):
            raise ValueError("import allowlist entries are invalid")
        for name, value in (
            ("application_bundle_sha256", self.application_bundle_sha256),
            ("manifest_sha256", self.manifest_sha256),
        ):
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError(f"{name} must be a SHA-256 digest")
        object.__setattr__(self, "files", MappingProxyType(files))
        object.__setattr__(
            self,
            "namespace_directories",
            frozenset(_path_key(Path(path)) for path in self.namespace_directories),
        )

    @classmethod
    def from_runtime_manifest(
        cls,
        *,
        manifest_value: Mapping[str, object],
        manifest_sha256: str,
        python_base: Path,
        environment_base: Path,
        application_files: Mapping[Path, str],
        accepted_application_bundle_sha256: str,
    ) -> "ImportAllowlist":
        python_tree, environment_tree, _ = _parse_cad_runtime_manifest(manifest_value)
        trace = manifest_value.get("trace_evidence")
        if not isinstance(trace, Mapping):
            raise TargetIntegrityError("CAD runtime trace evidence is unavailable")
        if trace.get("application_bundle_sha256") != accepted_application_bundle_sha256:
            raise TargetIntegrityError(
                "CAD runtime manifest is not bound to the accepted application bundle"
            )

        roots_and_files: Sequence[tuple[Path, Sequence[object], str]] = (
            (Path(python_base).resolve(), python_tree.files, "Python runtime manifest"),
            (
                Path(environment_base).resolve(),
                environment_tree.files,
                "dependency runtime manifest",
            ),
        )
        approved: dict[str, str] = {}
        for root, entries, name in roots_and_files:
            for entry in entries:
                path = _checked_relative_path(root, entry.path, name)
                key = _path_key(path)
                if key in approved and approved[key] != entry.sha256:
                    raise TargetIntegrityError("import manifests contradict one another")
                approved[key] = entry.sha256

        for raw_path, digest in application_files.items():
            path = Path(raw_path).resolve(strict=False)
            if path.suffix.lower() not in {".py", ".pyd", ".dll"}:
                continue
            key = _path_key(path)
            if key in approved and approved[key] != digest:
                raise TargetIntegrityError("application and runtime import approvals conflict")
            approved[key] = digest

        directories: set[str] = set()
        for raw_path in approved:
            directories.add(_path_key(Path(raw_path).parent))
        return cls(
            files=approved,
            namespace_directories=frozenset(directories),
            application_bundle_sha256=accepted_application_bundle_sha256,
            manifest_sha256=manifest_sha256,
        )

    def verify_origin(self, module_name: str, origin: str | None) -> None:
        if origin in {"built-in", "frozen"}:
            return
        if not isinstance(origin, str) or not origin:
            raise ImportBoundaryError(f"module {module_name!r} has no approved origin")
        path = Path(origin)
        if path.suffix.lower() in {".pyc", ".pyo"}:
            raise ImportBoundaryError(
                f"module {module_name!r} resolved to unapproved bytecode"
            )
        key = _path_key(path)
        expected = self.files.get(key)
        if expected is None:
            raise ImportBoundaryError(
                f"module {module_name!r} resolved outside the approved runtime"
            )
        try:
            stat = path.stat()
            if not path.is_file() or stat.st_size > _MAX_IMPORT_FILE_BYTES:
                raise ImportBoundaryError(
                    f"module {module_name!r} is not an approved bounded file"
                )
            actual = sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ImportBoundaryError(
                f"module {module_name!r} could not be verified"
            ) from exc
        if actual != expected:
            raise ImportBoundaryError(
                f"module {module_name!r} changed after target acceptance"
            )

    def verify_namespace(self, module_name: str, locations: Sequence[str]) -> None:
        if not locations:
            raise ImportBoundaryError(f"namespace {module_name!r} has no search location")
        for location in locations:
            if _path_key(Path(location)) not in self.namespace_directories:
                raise ImportBoundaryError(
                    f"namespace {module_name!r} escapes the approved runtime"
                )


class ManifestImportFinder(importlib.abc.MetaPathFinder):
    """Resolve through PathFinder and reject every unapproved result."""

    def __init__(self, allowlist: ImportAllowlist) -> None:
        if not isinstance(allowlist, ImportAllowlist):
            raise TypeError("allowlist must be an ImportAllowlist")
        self.allowlist = allowlist

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: object | None = None,
    ):
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is None:
            return None
        if spec.origin is None:
            locations = tuple(spec.submodule_search_locations or ())
            self.allowlist.verify_namespace(fullname, locations)
        else:
            self.allowlist.verify_origin(fullname, spec.origin)
        return spec


@contextmanager
def enforce_import_allowlist(allowlist: ImportAllowlist) -> Iterator[None]:
    """Install the guard before PathFinder and restore the exact prior chain."""

    finder = ManifestImportFinder(allowlist)
    previous = tuple(sys.meta_path)
    try:
        path_index = next(
            index
            for index, candidate in enumerate(sys.meta_path)
            if candidate is importlib.machinery.PathFinder
        )
    except StopIteration as exc:  # pragma: no cover - unsupported interpreter shape
        raise ImportBoundaryError("PathFinder is unavailable") from exc
    sys.meta_path.insert(path_index, finder)
    try:
        yield
    finally:
        sys.meta_path[:] = previous


__all__ = [
    "IMPORT_BOUNDARY_VERSION",
    "ImportAllowlist",
    "ImportBoundaryError",
    "ManifestImportFinder",
    "enforce_import_allowlist",
]
