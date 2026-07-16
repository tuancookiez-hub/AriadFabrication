import hashlib
import json
from pathlib import Path
import struct
import unittest


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmarks" / "3dbenchy"


class ThreeDBenchyFixtureTests(unittest.TestCase):
    def test_pinned_external_fixture_matches_its_provenance(self):
        provenance = json.loads((BENCHMARK / "provenance.json").read_text(encoding="utf-8"))
        path = BENCHMARK / provenance["local_path"]
        payload = path.read_bytes()

        self.assertEqual(provenance["license"], "CC0-1.0")
        self.assertEqual(provenance["file_format"], "binary_stl")
        self.assertEqual(len(payload), provenance["size_bytes"])
        self.assertEqual(hashlib.sha256(payload).hexdigest(), provenance["checksum_sha256"])
        triangle_count = struct.unpack_from("<I", payload, 80)[0]
        self.assertEqual(triangle_count, provenance["binary_triangle_count"])
        self.assertEqual(len(payload), 84 + triangle_count * 50)

    def test_comparison_profile_matches_official_generic_fff_limits(self):
        provenance = json.loads((BENCHMARK / "provenance.json").read_text(encoding="utf-8"))
        expected = provenance["official_generic_fff_settings"]
        profile_root = ROOT / "profiles" / "v1"
        printer = json.loads(
            (profile_root / "printers" / "generic_open_fdm_220.json").read_text(encoding="utf-8")
        )
        process = json.loads(
            (profile_root / "processes" / "standard_020_no_support.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(printer["nozzle_diameter_mm"], expected["nozzle_diameter_mm"])
        self.assertEqual(process["layer_height_mm"], expected["layer_height_mm"])
        self.assertEqual(process["infill_percent"], expected["infill_percent"])
        self.assertEqual(process["support_policy"], "disabled")
        print_speeds = [
            speed for name, speed in process["speeds_mm_s"].items() if name != "travel"
        ]
        self.assertLessEqual(max(print_speeds), expected["maximum_print_speed_mm_s"])


if __name__ == "__main__":
    unittest.main()
