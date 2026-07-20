"""Allocation-bounded snapshots for confined local files."""

from __future__ import annotations

from pathlib import Path


class BoundedFileError(RuntimeError):
    """Base class for bounded local-file snapshot failures."""


class BoundedFileMissingError(BoundedFileError):
    pass


class BoundedFileTooLargeError(BoundedFileError):
    pass


class BoundedFileSizeMismatchError(BoundedFileError):
    pass


class BoundedFileUnreadableError(BoundedFileError):
    pass


def read_bounded_bytes(
    path: Path,
    *,
    max_bytes: int,
    expected_size: int | None = None,
) -> bytes:
    """Read one snapshot while allocating no more than the accepted ceiling plus one byte."""

    if max_bytes < 0:
        raise ValueError("max_bytes cannot be negative")
    if expected_size is not None and expected_size < 0:
        raise ValueError("expected_size cannot be negative")
    try:
        with path.open("rb") as source:
            if expected_size is not None and expected_size > max_bytes:
                raise BoundedFileTooLargeError("recorded size exceeds the read ceiling")
            read_size = (
                expected_size + 1
                if expected_size is not None
                else max_bytes + 1
            )
            payload = source.read(read_size)
    except BoundedFileError:
        raise
    except FileNotFoundError as exc:
        raise BoundedFileMissingError("file is missing") from exc
    except OSError as exc:
        raise BoundedFileUnreadableError("file cannot be read") from exc
    if len(payload) > max_bytes:
        raise BoundedFileTooLargeError("file exceeds the read ceiling")
    if expected_size is not None and len(payload) != expected_size:
        raise BoundedFileSizeMismatchError("file size differs from the recorded size")
    return payload
