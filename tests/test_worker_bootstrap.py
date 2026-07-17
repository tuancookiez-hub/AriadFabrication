from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


BASE_PYTHON = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
BOOTSTRAP = (
    Path(__file__).parents[1]
    / "src/ariad_fabrication/execution/worker_bootstrap.py"
).resolve()


class SealedWorkerBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ariad-worker-bootstrap-")
        self.root = Path(self.temporary.name).resolve()
        package = self.root / "ariad_fabrication"
        cad = package / "cad"
        cad.mkdir(parents=True)
        self.package_init = package / "__init__.py"
        self.cad_init = cad / "__init__.py"
        self.worker = cad / "worker.py"
        self.helper = cad / "approved_helper.py"
        self.package_init.write_text("\n", encoding="utf-8")
        self.cad_init.write_text("\n", encoding="utf-8")
        self.helper.write_text("VALUE = 'sealed'\n", encoding="utf-8")
        self.worker.write_text(
            "from .approved_helper import VALUE\n"
            "from pathlib import Path\n"
            "import sys\n"
            "Path(sys.argv[1]).write_text(VALUE, encoding='utf-8')\n",
            encoding="utf-8",
        )
        self.result = self.root / "result.txt"
        self.config = self.root / "bootstrap.json"

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def digest(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    def write_config(self, *, include_helper: bool = True) -> None:
        files = {
            str(self.package_init): self.digest(self.package_init),
            str(self.cad_init): self.digest(self.cad_init),
            str(self.worker): self.digest(self.worker),
        }
        if include_helper:
            files[str(self.helper)] = self.digest(self.helper)
        value = {
            "version": "0.1.0",
            "module": "ariad_fabrication.cad.worker",
            "arguments": [str(self.result)],
            "sys_path": [str(self.root)],
            "files": files,
            "namespaces": [str(self.root), str(self.root / "ariad_fabrication"), str(self.root / "ariad_fabrication/cad")],
        }
        self.config.write_text(json.dumps(value), encoding="utf-8")

    def run_bootstrap(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(BASE_PYTHON), "-I", "-B", "-S", str(BOOTSTRAP), str(self.config)],
            cwd=self.root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )

    def test_registered_worker_runs_after_guard_installation(self):
        self.write_config()

        completed = self.run_bootstrap()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.result.read_text(encoding="utf-8"), "sealed")

    def test_worker_cannot_import_an_unlisted_module(self):
        self.write_config(include_helper=False)

        completed = self.run_bootstrap()

        self.assertEqual(completed.returncode, 70)
        self.assertIn("outside the approved runtime", completed.stderr)
        self.assertFalse(self.result.exists())

    def test_worker_cannot_import_a_file_changed_after_configuration(self):
        self.write_config()
        self.helper.write_text("VALUE = 'drifted'\n", encoding="utf-8")

        completed = self.run_bootstrap()

        self.assertEqual(completed.returncode, 70)
        self.assertIn("changed after target acceptance", completed.stderr)
        self.assertFalse(self.result.exists())

    def test_arbitrary_module_target_is_rejected(self):
        self.write_config()
        value = json.loads(self.config.read_text(encoding="utf-8"))
        value["module"] = "subprocess"
        self.config.write_text(json.dumps(value), encoding="utf-8")

        completed = self.run_bootstrap()

        self.assertEqual(completed.returncode, 70)
        self.assertIn("module is not registered", completed.stderr)

    def test_registered_worker_system_exit_zero_is_success(self):
        self.worker.write_text("raise SystemExit(0)\n", encoding="utf-8")
        self.write_config()

        completed = self.run_bootstrap()

        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
