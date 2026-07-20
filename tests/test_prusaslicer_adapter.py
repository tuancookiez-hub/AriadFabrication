from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ariad_fabrication.slicing.prusaslicer import PrusaSlicerAdapter, SlicerInstallation


class PrusaSlicerAdapterFailureTests(unittest.TestCase):
    def test_timeout_preserves_partial_logs_and_raises(self):
        installation = SlicerInstallation(
            executable=Path("prusa-slicer-console.exe"),
            version="2.9.6",
            executable_size_bytes=1,
            executable_checksum_sha256="0" * 64,
        )
        with patch.object(SlicerInstallation, "inspect", return_value=installation):
            adapter = PrusaSlicerAdapter(
                Path("prusa-slicer-console.exe"),
                timeout_seconds=0.01,
            )
        timeout = subprocess.TimeoutExpired(
            cmd=["prusa-slicer-console.exe", "--info", "part.step"],
            timeout=0.01,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            stdout = directory / "stdout.log"
            stderr = directory / "stderr.log"
            with patch(
                "ariad_fabrication.slicing.prusaslicer.subprocess.run",
                side_effect=timeout,
            ):
                with self.assertRaisesRegex(TimeoutError, "0.01 second timeout"):
                    adapter._run(
                        ("--info", "part.step"),
                        cwd=directory,
                        stdout_path=stdout,
                        stderr_path=stderr,
                    )

            self.assertEqual(stdout.read_text(encoding="utf-8"), "partial stdout")
            self.assertEqual(stderr.read_text(encoding="utf-8"), "partial stderr")


if __name__ == "__main__":
    unittest.main()
