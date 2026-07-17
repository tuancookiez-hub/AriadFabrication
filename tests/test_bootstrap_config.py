import json
from pathlib import Path
import tempfile
import unittest

from ariad_fabrication.execution import (
    ExecutionTarget,
    TrustedTargetRegistry,
    build_registered_import_allowlist,
    write_worker_bootstrap_config,
)


class RegisteredBootstrapConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.resolved = TrustedTargetRegistry.from_checkout().resolve(
                ExecutionTarget.GOLDEN_PART_R2
            )
        except Exception as exc:  # pragma: no cover - environment-gated production evidence
            raise unittest.SkipTest(f"pinned CAD runtime unavailable: {exc}") from exc

    def test_current_target_builds_a_large_exact_import_allowlist(self):
        allowlist = build_registered_import_allowlist(self.resolved)

        self.assertGreater(len(allowlist.files), 1_500)
        self.assertGreater(len(allowlist.namespace_directories), 100)
        self.assertEqual(
            allowlist.application_bundle_sha256,
            self.resolved.plan.application_bundle_sha256,
        )

    def test_configuration_is_immutable_closed_and_secret_free(self):
        with tempfile.TemporaryDirectory(prefix="ariad-bootstrap-config-") as raw:
            path = Path(raw) / "bootstrap.json"
            written = write_worker_bootstrap_config(
                self.resolved,
                path,
                arguments=("--request", "request.json", "--output", "design", "--result", "result.json"),
            )
            value = json.loads(written.read_text(encoding="utf-8"))

            self.assertEqual(
                set(value),
                {"version", "module", "arguments", "sys_path", "files", "namespaces"},
            )
            self.assertEqual(value["module"], "ariad_fabrication.cad.worker")
            self.assertNotIn("environment", value)
            with self.assertRaises(FileExistsError):
                write_worker_bootstrap_config(
                    self.resolved,
                    path,
                    arguments=("--request", "request.json"),
                )


if __name__ == "__main__":
    unittest.main()
