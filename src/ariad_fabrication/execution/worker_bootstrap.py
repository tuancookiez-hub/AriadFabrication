"""Standalone bootstrap for a manifest-sealed Ariad Python worker.

This file is executed by absolute path with ``python -I -B -S``.  Keep its
imports in the standard library: the import boundary is installed before the
registered worker package is imported.
"""

from __future__ import annotations

from hashlib import sha256
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import runpy
import sys
from typing import Any, Mapping, Sequence


BOOTSTRAP_VERSION = "0.1.0"
MAX_CONFIG_BYTES = 16 * 1024 * 1024
MAX_IMPORT_FILE_BYTES = 128 * 1024 * 1024
ALLOWED_MODULES = frozenset({"ariad_fabrication.cad.worker"})


class BootstrapError(RuntimeError):
    pass


def _path_key(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).resolve(strict=False)))


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BootstrapError(f"bootstrap configuration repeats key {key!r}")
        result[key] = value
    return result


def _read_config(path: Path) -> Mapping[str, Any]:
    try:
        with path.open("rb") as stream:
            payload = stream.read(MAX_CONFIG_BYTES + 1)
    except OSError as exc:
        raise BootstrapError("bootstrap configuration cannot be read") from exc
    if len(payload) > MAX_CONFIG_BYTES:
        raise BootstrapError("bootstrap configuration exceeds its byte ceiling")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootstrapError("bootstrap configuration is not strict UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise BootstrapError("bootstrap configuration must be an object")
    expected = {"version", "module", "arguments", "sys_path", "files", "namespaces"}
    if set(value) != expected:
        raise BootstrapError("bootstrap configuration has an unexpected shape")
    return value


class _SealedFinder(importlib.abc.MetaPathFinder):
    def __init__(self, files: Mapping[str, str], namespaces: Sequence[str]) -> None:
        self.files = {_path_key(path): digest for path, digest in files.items()}
        self.namespaces = frozenset(_path_key(path) for path in namespaces)

    def _verify_origin(self, fullname: str, origin: str | None) -> None:
        if origin in {"built-in", "frozen"}:
            return
        if not isinstance(origin, str) or not origin:
            raise ImportError(f"module {fullname!r} has no approved origin")
        path = Path(origin)
        if path.suffix.lower() in {".pyc", ".pyo"}:
            raise ImportError(f"module {fullname!r} resolved to unapproved bytecode")
        expected = self.files.get(_path_key(path))
        if expected is None:
            raise ImportError(f"module {fullname!r} resolved outside the approved runtime")
        try:
            size = path.stat().st_size
            if not path.is_file() or size > MAX_IMPORT_FILE_BYTES:
                raise ImportError(f"module {fullname!r} is not an approved bounded file")
            actual = sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ImportError(f"module {fullname!r} could not be verified") from exc
        if actual != expected:
            raise ImportError(f"module {fullname!r} changed after target acceptance")

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
            if not locations or any(
                _path_key(location) not in self.namespaces for location in locations
            ):
                raise ImportError(f"namespace {fullname!r} escapes the approved runtime")
        else:
            self._verify_origin(fullname, spec.origin)
        return spec


def _string_list(value: Any, name: str, *, maximum: int) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or len(value) > maximum
        or any(not isinstance(item, str) or not item or len(item) > 32_768 for item in value)
    ):
        raise BootstrapError(f"bootstrap {name} is invalid")
    return tuple(value)


def execute(config_path: Path) -> None:
    value = _read_config(config_path)
    if value["version"] != BOOTSTRAP_VERSION:
        raise BootstrapError("bootstrap configuration version is unsupported")
    module = value["module"]
    if module not in ALLOWED_MODULES:
        raise BootstrapError("bootstrap module is not registered")
    arguments = _string_list(value["arguments"], "arguments", maximum=32)
    search_path = _string_list(value["sys_path"], "sys_path", maximum=16)
    namespaces = _string_list(value["namespaces"], "namespaces", maximum=8_000)
    raw_files = value["files"]
    if (
        not isinstance(raw_files, Mapping)
        or not raw_files
        or len(raw_files) > 8_000
        or any(
            not isinstance(path, str)
            or not path
            or not isinstance(digest, str)
            or len(digest) != 64
            for path, digest in raw_files.items()
        )
    ):
        raise BootstrapError("bootstrap file allowlist is invalid")

    finder = _SealedFinder(raw_files, namespaces)
    path_index = next(
        (
            index
            for index, candidate in enumerate(sys.meta_path)
            if candidate is importlib.machinery.PathFinder
        ),
        None,
    )
    if path_index is None:
        raise BootstrapError("PathFinder is unavailable")
    sys.path[:] = list(search_path)
    sys.meta_path.insert(path_index, finder)
    sys.argv[:] = [module, *arguments]
    runpy.run_module(module, run_name="__main__", alter_sys=False)


def main(argv: Sequence[str] | None = None) -> int:
    values = tuple(sys.argv[1:] if argv is None else argv)
    if len(values) != 1:
        print("sealed worker bootstrap requires one configuration path", file=sys.stderr)
        return 64
    try:
        execute(Path(values[0]))
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        print(f"sealed worker exited: {exc.code}", file=sys.stderr)
        return 70
    except Exception as exc:
        print(f"sealed worker rejected: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 70
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
