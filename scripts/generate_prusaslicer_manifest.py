"""Generate or verify Ariad's approved PrusaSlicer portable-runtime manifest.

The ignored portable installation is the input.  The committed manifest is a
deterministic allowlist of every runtime file needed to identify that install;
it does not install, launch, or contact PrusaSlicer or any hardware.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "runs/tools/prusaslicer/2.9.6/PrusaSlicer-2.9.6.zip"
INSTALLATION = (
    ROOT
    / "runs/tools/prusaslicer/2.9.6/portable/PrusaSlicer-2.9.6"
)
OUTPUT = ROOT / "toolchains/v1/prusaslicer-2.9.6-windows-x64.json"

ARCHIVE_SHA256 = "5aaf22e42f95accecfa122d23a835911f289ecc2ff606db3e83d637ddcc0a209"
ARCHIVE_SIZE_BYTES = 106_598_059
EXECUTABLE = "prusa-slicer-console.exe"
EXECUTABLE_SHA256 = "7fd50b52d1cc3da87dbcb71e45e764412dd45688bea028f351333e86d9769704"
MAX_FILES = 2_000
MAX_INSTALLATION_BYTES = 512 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _hash_file(path: Path, expected_size: int) -> str:
    digest = sha256()
    read = 0
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size != expected_size:
            raise RuntimeError(f"file size/type changed before hashing: {path}")
        while read < expected_size:
            block = handle.read(min(READ_CHUNK_BYTES, expected_size - read))
            if not block:
                raise RuntimeError(f"file ended while hashing: {path}")
            read += len(block)
            digest.update(block)
        if handle.read(1):
            raise RuntimeError(f"file grew while hashing: {path}")
        after = os.fstat(handle.fileno())
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise RuntimeError(f"file changed while hashing: {path}")
    return digest.hexdigest()


def _is_reparse_or_link(path: Path) -> bool:
    item = path.lstat()
    attributes = getattr(item, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(item.st_mode) or bool(attributes & reparse)


def _installation_entries() -> list[dict[str, Any]]:
    if not INSTALLATION.is_dir():
        raise RuntimeError(f"portable installation is unavailable: {INSTALLATION}")
    entries: list[dict[str, Any]] = []
    seen_casefolded: set[str] = set()
    total_bytes = 0
    stack = [INSTALLATION]
    while stack:
        directory = stack.pop()
        if directory != INSTALLATION and _is_reparse_or_link(directory):
            raise RuntimeError(f"runtime directory cannot be a link/reparse point: {directory}")
        children = sorted(directory.iterdir(), key=lambda item: (item.name.casefold(), item.name))
        for child in children:
            if _is_reparse_or_link(child):
                raise RuntimeError(f"runtime entry cannot be a link/reparse point: {child}")
            if child.is_dir():
                stack.append(child)
                continue
            if not child.is_file():
                raise RuntimeError(f"runtime entry is not a regular file: {child}")
            relative = child.relative_to(INSTALLATION).as_posix()
            folded = relative.casefold()
            if folded in seen_casefolded:
                raise RuntimeError(f"case-insensitive runtime path collision: {relative}")
            seen_casefolded.add(folded)
            size = child.stat().st_size
            total_bytes += size
            if len(entries) >= MAX_FILES or total_bytes > MAX_INSTALLATION_BYTES:
                raise RuntimeError("portable installation exceeds manifest resource limits")
            entries.append(
                {
                    "path": relative,
                    "size_bytes": size,
                    "sha256": _hash_file(child, size),
                }
            )
    entries.sort(key=lambda item: (item["path"].casefold(), item["path"]))
    return entries


def build_manifest() -> dict[str, Any]:
    if sys.platform != "win32" or os.environ.get("PROCESSOR_ARCHITECTURE", "").upper() not in {
        "AMD64",
        "X86_64",
    }:
        raise RuntimeError("this approved manifest is only for Windows x86-64")
    if not ARCHIVE.is_file() or ARCHIVE.stat().st_size != ARCHIVE_SIZE_BYTES:
        raise RuntimeError("approved PrusaSlicer archive is unavailable or has the wrong size")
    if _hash_file(ARCHIVE, ARCHIVE_SIZE_BYTES) != ARCHIVE_SHA256:
        raise RuntimeError("approved PrusaSlicer archive checksum does not match")
    files = _installation_entries()
    total_bytes = sum(item["size_bytes"] for item in files)
    tree_sha256 = sha256(
        _canonical_bytes({"algorithm": "ariad-tree-sha256-v1", "files": files})
    ).hexdigest()
    executable = next((item for item in files if item["path"] == EXECUTABLE), None)
    if executable is None or executable["sha256"] != EXECUTABLE_SHA256:
        raise RuntimeError("approved PrusaSlicer console executable does not match")
    return {
        "schema_version": "1.0.0",
        "manifest_kind": "approved_portable_toolchain",
        "tool": "PrusaSlicer",
        "version": "2.9.6",
        "platform": "windows",
        "architecture": "x86_64",
        "adapter": {"id": "prusaslicer_cli", "version": "1.0.0"},
        "portable_archive": {
            "filename": ARCHIVE.name,
            "size_bytes": ARCHIVE_SIZE_BYTES,
            "sha256": ARCHIVE_SHA256,
            "release_url": (
                "https://github.com/prusa3d/PrusaSlicer/releases/download/"
                "version_2.9.6/PrusaSlicer-2.9.6.zip"
            ),
        },
        "installation": {
            "root_directory_name": INSTALLATION.name,
            "executable": EXECUTABLE,
            "file_count": len(files),
            "size_bytes": total_bytes,
            "tree_sha256": tree_sha256,
            "files": files,
        },
        "claim_boundary": (
            "This manifest identifies one approved local Windows x86-64 PrusaSlicer "
            "runtime. Matching it does not prove a G-code result, a safe or successful "
            "print, or any physical action."
        ),
    }


def _render(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify that the committed manifest equals the approved runtime",
    )
    arguments = parser.parse_args()
    rendered = _render(build_manifest())
    if arguments.check:
        if not OUTPUT.is_file() or OUTPUT.read_bytes() != rendered:
            print(f"PrusaSlicer manifest drifted: {OUTPUT}", file=sys.stderr)
            return 1
        print(f"PrusaSlicer manifest is current: {OUTPUT}")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(rendered)
    print(f"Wrote {OUTPUT} ({len(rendered)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
