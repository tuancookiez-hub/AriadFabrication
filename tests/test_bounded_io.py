from pathlib import Path
import tempfile
import unittest

from ariad_fabrication.api.bounded_io import (
    BoundedFileMissingError,
    BoundedFileSizeMismatchError,
    BoundedFileTooLargeError,
    BoundedFileUnreadableError,
    read_bounded_bytes,
)


class _RecordingSource:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.requested_size: int | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int) -> bytes:
        self.requested_size = size
        return self.payload[:size]


class _RecordingPath:
    def __init__(self, source: _RecordingSource):
        self.source = source

    def open(self, _mode: str):
        return self.source


class BoundedIoTests(unittest.TestCase):
    def test_unrecorded_size_reads_only_ceiling_plus_one(self):
        source = _RecordingSource(b"x" * 100)

        with self.assertRaises(BoundedFileTooLargeError):
            read_bounded_bytes(_RecordingPath(source), max_bytes=16)

        self.assertEqual(source.requested_size, 17)

    def test_recorded_size_reads_only_expected_size_plus_one(self):
        source = _RecordingSource(b"abcde-and-more")

        with self.assertRaises(BoundedFileSizeMismatchError):
            read_bounded_bytes(
                _RecordingPath(source),
                max_bytes=64,
                expected_size=4,
            )

        self.assertEqual(source.requested_size, 5)

    def test_recorded_size_above_ceiling_is_rejected_before_read(self):
        source = _RecordingSource(b"not read")

        with self.assertRaises(BoundedFileTooLargeError):
            read_bounded_bytes(
                _RecordingPath(source),
                max_bytes=4,
                expected_size=5,
            )

        self.assertIsNone(source.requested_size)

    def test_missing_and_unreadable_paths_are_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(BoundedFileMissingError):
                read_bounded_bytes(root / "missing.json", max_bytes=16)
            with self.assertRaises(BoundedFileUnreadableError):
                read_bounded_bytes(root, max_bytes=16)


if __name__ == "__main__":
    unittest.main()
