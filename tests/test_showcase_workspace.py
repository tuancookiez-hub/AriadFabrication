from pathlib import Path
import tempfile
import unittest

from ariad_fabrication.api.repository import JourneyRepository
from ariad_fabrication.api.showcase import prepare_showcase


class ShowcaseWorkspaceTests(unittest.TestCase):
    def test_fixture_only_fallback_is_clean_and_truthful(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            runtime = root / "runtime"
            runtime.mkdir()
            output = runtime / "showcase"
            result = prepare_showcase(runtime, Path("benchmarks/interface"), output)

            self.assertEqual(result.fixture_revisions, 6)
            self.assertIsNone(result.real_revision)
            listing = JourneyRepository(output).list_revisions(offset=0, limit=20)
            self.assertEqual(len(listing.revisions), 6)
            self.assertTrue(all(item.availability == "available" for item in listing.revisions))
            self.assertTrue(all(item.source and item.source.fixture for item in listing.revisions))

    def test_sources_cannot_be_replaced_by_the_output(self):
        with self.assertRaisesRegex(ValueError, "must differ"):
            prepare_showcase(
                Path("benchmarks/interface"),
                Path("benchmarks/interface"),
                Path("benchmarks/interface"),
            )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            runtime = root / "runtime"
            runtime.mkdir()
            with self.assertRaisesRegex(ValueError, "remain inside runtime root"):
                prepare_showcase(runtime, Path("benchmarks/interface"), root / "outside")


if __name__ == "__main__":
    unittest.main()
