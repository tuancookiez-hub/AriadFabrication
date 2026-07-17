from hashlib import sha256
import importlib
from pathlib import Path
import sys
import tempfile
import unittest

from ariad_fabrication.execution import (
    ImportAllowlist,
    ImportBoundaryError,
    enforce_import_allowlist,
)


class ManifestImportBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ariad-import-boundary-")
        self.root = Path(self.temporary.name).resolve()
        self.allowed_name = "ariad_boundary_allowed_fixture"
        self.blocked_name = "ariad_boundary_blocked_fixture"
        self.allowed = self.root / f"{self.allowed_name}.py"
        self.blocked = self.root / f"{self.blocked_name}.py"
        self.allowed.write_text("VALUE = 7\n", encoding="utf-8")
        self.blocked.write_text("VALUE = 9\n", encoding="utf-8")
        self.original_path = tuple(sys.path)
        sys.path.insert(0, str(self.root))

    def tearDown(self):
        sys.path[:] = self.original_path
        sys.modules.pop(self.allowed_name, None)
        sys.modules.pop(self.blocked_name, None)
        self.temporary.cleanup()

    def allowlist(self) -> ImportAllowlist:
        digest = sha256(self.allowed.read_bytes()).hexdigest()
        return ImportAllowlist(
            files={str(self.allowed): digest},
            namespace_directories=frozenset({str(self.root)}),
            application_bundle_sha256="a" * 64,
            manifest_sha256="b" * 64,
        )

    def test_exact_approved_source_imports(self):
        with enforce_import_allowlist(self.allowlist()):
            module = importlib.import_module(self.allowed_name)

        self.assertEqual(module.VALUE, 7)

    def test_unlisted_module_is_rejected(self):
        with enforce_import_allowlist(self.allowlist()), self.assertRaisesRegex(
            ImportBoundaryError, "outside the approved runtime"
        ):
            importlib.import_module(self.blocked_name)

        self.assertNotIn(self.blocked_name, sys.modules)

    def test_changed_approved_module_is_rejected(self):
        allowlist = self.allowlist()
        self.allowed.write_text("VALUE = 70\n", encoding="utf-8")

        with enforce_import_allowlist(allowlist), self.assertRaisesRegex(
            ImportBoundaryError, "changed after target acceptance"
        ):
            importlib.import_module(self.allowed_name)

    def test_builtin_modules_remain_available_and_guard_restores_chain(self):
        before = tuple(sys.meta_path)
        with enforce_import_allowlist(self.allowlist()):
            self.assertIsNotNone(importlib.import_module("sys"))
        self.assertEqual(tuple(sys.meta_path), before)


if __name__ == "__main__":
    unittest.main()
