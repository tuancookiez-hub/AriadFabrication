from dataclasses import replace
from hashlib import sha256
import inspect
import json
from pathlib import Path
import platform
import re
import shutil
import tempfile
import tomllib
import unittest

from ariad_fabrication.execution import (
    AdmissionDecision,
    ExecutionControlStore,
    ExecutionRequest,
    ExecutionTarget,
    RegisteredTargetAdmission,
    TargetIntegrityError,
    TargetUnavailableError,
    TrustedTargetRegistry,
)
from ariad_fabrication.execution.registry import (
    TREE_ALGORITHM,
    _Approval,
    _Layout,
    _PRODUCTION_ASSET_SHA256,
    _parse_cad_runtime_manifest,
    _parse_slicer_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
ZERO = "0" * 64
_NORMALIZE_DISTRIBUTION = re.compile(r"[-_.]+")


def canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def tree_value(base: Path, paths) -> dict:
    entries = []
    for path in sorted(
        {item.resolve() for item in paths},
        key=lambda item: (
            item.relative_to(base).as_posix().casefold(),
            item.relative_to(base).as_posix(),
        ),
    ):
        payload = path.read_bytes()
        entries.append(
            {
                "path": path.relative_to(base).as_posix(),
                "size_bytes": len(payload),
                "sha256": sha256(payload).hexdigest(),
            }
        )
    digest = sha256(
        canonical_bytes({"algorithm": TREE_ALGORITHM, "files": entries})
    ).hexdigest()
    return {
        "file_count": len(entries),
        "size_bytes": sum(item["size_bytes"] for item in entries),
        "tree_sha256": digest,
        "files": entries,
    }


def selected_lock_versions(lock: dict) -> dict[str, str]:
    selected = {}
    for package in lock["package"]:
        markers = package.get("resolution-markers")
        if markers and "python_full_version < '3.12'" not in markers:
            continue
        name = _NORMALIZE_DISTRIBUTION.sub("-", package["name"]).lower()
        selected[name] = package["version"]
    return selected


class RegistryFixture:
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "checkout"
        self.root.mkdir(parents=True)
        for relative in _PRODUCTION_ASSET_SHA256:
            source = ROOT / relative
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        (self.root / "pyproject.toml").write_text(
            "[project]\nname = 'fixture'\nversion = '0.0.0'\n",
            encoding="utf-8",
        )
        self.support_source = self.root / "src/ariad_fabrication/registry_support.py"
        self.support_source.write_text("VALUE = 'approved'\n", encoding="utf-8")
        schema = self.root / "schemas/v1/fixture.schema.json"
        schema.parent.mkdir(parents=True, exist_ok=True)
        schema.write_text('{"type":"object"}\n', encoding="utf-8")

        self.python_base = self.root / "runtime/python"
        (self.python_base / "DLLs").mkdir(parents=True)
        (self.python_base / "Lib").mkdir(parents=True)
        for name in (
            "BUILD",
            "python.exe",
            "python3.dll",
            "python311.dll",
            "vcruntime140.dll",
            "vcruntime140_1.dll",
        ):
            (self.python_base / name).write_bytes(f"fixture:{name}".encode())
        (self.python_base / "DLLs/runtime.dll").write_bytes(b"runtime-dll")
        self.python_module = self.python_base / "Lib/runtime.py"
        self.python_module.write_text("RUNTIME = 1\n", encoding="utf-8")

        self.environment = self.root / "runtime/environment"
        self.purelib = self.environment / "Lib/site-packages"
        self.purelib.mkdir(parents=True)
        (self.environment / "pyvenv.cfg").write_text("home = fixture\n", encoding="utf-8")
        lock = tomllib.loads((self.root / "uv.lock").read_text(encoding="utf-8"))
        self.installed = selected_lock_versions(lock)
        self.dist_info = {}
        for index, (name, version) in enumerate(sorted(self.installed.items())):
            directory = self.purelib / f"fixture_{index}-{version}.dist-info"
            directory.mkdir()
            self.dist_info[name] = directory
            directory.joinpath("METADATA").write_text(
                f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
                encoding="utf-8",
            )
        (self.purelib / "_virtualenv.pth").write_text(
            "import _virtualenv\n", encoding="utf-8"
        )
        self.environment_hook = self.purelib / "_virtualenv.py"
        self.environment_hook.write_text("BOOTSTRAP = True\n", encoding="utf-8")

        base_files = [
            self.python_base / name
            for name in (
                "BUILD",
                "python.exe",
                "python3.dll",
                "python311.dll",
                "vcruntime140.dll",
                "vcruntime140_1.dll",
            )
        ] + [self.python_base / "DLLs/runtime.dll", self.python_module]
        environment_files = [
            self.environment / "pyvenv.cfg",
            self.purelib / "_virtualenv.pth",
            self.environment_hook,
        ]
        application_files = [self.root / "pyproject.toml"]
        for directory in (self.root / "src/ariad_fabrication", self.root / "schemas/v1"):
            application_files.extend(
                path
                for path in directory.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix.lower() not in {".pyc", ".pyo"}
            )
        application_digest = tree_value(self.root, application_files)["tree_sha256"]
        runtime_manifest = {
            "schema_version": "1.0.0",
            "manifest_kind": "traced_cad_execution_runtime",
            "platform": "windows",
            "architecture": "x86_64",
            "python": {
                "implementation": "cpython",
                "version": platform.python_version(),
                "build": "fixture",
                "runtime_selection": "Fixture equivalent of the frozen selection.",
                "runtime": tree_value(self.python_base, base_files),
            },
            "dependency_environment": {
                "lock_file": "uv.lock",
                "lock_sha256": file_sha256(self.root / "uv.lock"),
                "installed_distribution_count": len(self.installed),
                "installed_distributions": self.installed,
                "selected_distribution_count": 2,
                "selected_distributions": ["cadquery", "cadquery-ocp"],
                "runtime_selection": "Fixture modules and environment bootstrap files.",
                "runtime": tree_value(self.environment, environment_files),
            },
            "trace_evidence": {
                "benchmark_id": "opengrow_stake_electronics_clamp_v1",
                "target": "golden_part_r4_python_lane",
                "cad_worker_success": True,
                "geometry_validation_passed": True,
                "requested_formats": ["step", "stl", "3mf", "glb"],
                "part_spec_sha256": file_sha256(
                    self.root / "benchmarks/golden_part/part_spec.json"
                ),
                "geometry_expectations_sha256": file_sha256(
                    self.root / "benchmarks/golden_part/expected.json"
                ),
                "module_file_count_observed": 2,
                "claim_boundary": "Fixture trace only; no physical evidence.",
                "module_file_count_in_python_base": 1,
                "module_file_count_in_dependency_environment": 1,
                "application_bundle_sha256": application_digest,
            },
            "claim_boundary": "Fixture runtime identity only; no hardware action.",
        }
        self.runtime_manifest_path = (
            self.root / "toolchains/v1/cad-runtime-cpython-3.11-windows-x64.json"
        )
        self.runtime_manifest_path.parent.mkdir(parents=True)
        self.runtime_manifest_path.write_text(
            json.dumps(runtime_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        self.archive = self.root / "runtime/PrusaSlicer-2.9.6.zip"
        self.archive.write_bytes(b"approved-fixture-archive")
        self.slicer_installation = self.root / "runtime/PrusaSlicer-2.9.6"
        self.slicer_installation.mkdir()
        self.slicer_executable = (
            self.slicer_installation / "prusa-slicer-console.exe"
        )
        self.slicer_executable.write_bytes(b"fixture-console")
        self.slicer_dll = self.slicer_installation / "PrusaSlicer.dll"
        self.slicer_dll.write_bytes(b"fixture-runtime")
        slicer_tree = tree_value(
            self.slicer_installation, [self.slicer_executable, self.slicer_dll]
        )
        slicer_manifest = {
            "schema_version": "1.0.0",
            "manifest_kind": "approved_portable_toolchain",
            "tool": "PrusaSlicer",
            "version": "2.9.6",
            "platform": "windows",
            "architecture": "x86_64",
            "adapter": {"id": "prusaslicer_cli", "version": "1.0.0"},
            "portable_archive": {
                "filename": "PrusaSlicer-2.9.6.zip",
                "size_bytes": self.archive.stat().st_size,
                "sha256": file_sha256(self.archive),
                "release_url": "https://example.invalid/fixture.zip",
            },
            "installation": {
                "root_directory_name": "PrusaSlicer-2.9.6",
                "executable": "prusa-slicer-console.exe",
                **slicer_tree,
            },
            "claim_boundary": "Fixture tool identity only; no physical evidence.",
        }
        self.slicer_manifest_path = (
            self.root / "toolchains/v1/prusaslicer-2.9.6-windows-x64.json"
        )
        self.slicer_manifest_path.write_text(
            json.dumps(slicer_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        asset_hashes = {
            relative: file_sha256(self.root / relative)
            for relative in _PRODUCTION_ASSET_SHA256
        }
        self.approval = _Approval(
            asset_sha256=asset_hashes,
            slicer_manifest_sha256=file_sha256(self.slicer_manifest_path),
            slicer_archive_sha256=file_sha256(self.archive),
            slicer_archive_size_bytes=self.archive.stat().st_size,
        )
        self.layout = _Layout(
            project_root=self.root,
            python_executable=self.python_base / "python.exe",
            python_base=self.python_base,
            environment_root=self.environment,
            purelib=self.purelib,
            platlib=self.purelib,
            cad_runtime_manifest=self.runtime_manifest_path,
            slicer_archive=self.archive,
            slicer_installation=self.slicer_installation,
            slicer_manifest=self.slicer_manifest_path,
        )
        self.registry = TrustedTargetRegistry._from_layout_for_test(
            self.layout, self.approval
        )

    def close(self):
        self.temporary.cleanup()


class TrustedTargetRegistryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = RegistryFixture()

    def tearDown(self):
        self.fixture.close()

    def test_only_registered_target_choice_resolves_closed_r2_and_r4_plans(self):
        signature = inspect.signature(TrustedTargetRegistry.resolve)
        self.assertEqual(tuple(signature.parameters), ("self", "target"))

        r2 = self.fixture.registry.resolve(ExecutionTarget.GOLDEN_PART_R2)
        r4 = self.fixture.registry.resolve("golden_part_r4")

        self.assertFalse(r2.hardware_actions)
        self.assertFalse(r4.hardware_actions)
        self.assertIsNone(r2.plan.profiles)
        self.assertIsNone(r2.slicer_executable_path)
        self.assertIsNotNone(r4.plan.profiles)
        self.assertEqual(r4.slicer_executable_path, self.fixture.slicer_executable)
        self.assertEqual(
            r2.plan.canonical_sha256(),
            sha256(canonical_bytes(r2.plan.to_dict())).hexdigest(),
        )
        self.assertEqual(
            r4.plan.slicer.installation_tree_sha256,
            json.loads(self.fixture.slicer_manifest_path.read_text(encoding="utf-8"))[
                "installation"
            ]["tree_sha256"],
        )
        self.assertEqual(r2.plan.cad_runtime.host.system, platform.system())
        self.assertEqual(r2.plan.cad_runtime.host.release, platform.release())
        self.assertEqual(r2.plan.cad_runtime.host.version, platform.version())
        self.assertEqual(r2.plan.cad_runtime.host.machine, platform.machine())
        with self.assertRaisesRegex(ValueError, "trusted registry"):
            replace(r2, _seal=None)
        with self.assertRaises(TargetUnavailableError):
            self.fixture.registry.resolve("caller_selected_target")

    def test_reverification_detects_application_and_accepted_plan_drift(self):
        resolved = self.fixture.registry.resolve(ExecutionTarget.GOLDEN_PART_R2)
        tampered_plan = replace(resolved.plan, application_bundle_sha256=ZERO)
        with self.assertRaisesRegex(TargetIntegrityError, "application_bundle_sha256"):
            self.fixture.registry.reverify(tampered_plan)

        self.fixture.support_source.write_text("VALUE = 'changed'\n", encoding="utf-8")
        with self.assertRaisesRegex(TargetIntegrityError, "runtime trace.*application bundle"):
            self.fixture.registry.reverify(resolved.plan)

    def test_fixed_benchmark_asset_drift_fails_before_admission(self):
        path = self.fixture.root / "benchmarks/golden_part/part_spec.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(TargetIntegrityError, "asset drifted"):
            self.fixture.registry.resolve(ExecutionTarget.GOLDEN_PART_R2)

    def test_python_and_dependency_runtime_content_drift_fail_closed(self):
        accepted = self.fixture.registry.resolve(ExecutionTarget.GOLDEN_PART_R2).plan
        self.fixture.python_module.write_text("RUNTIME = 2\n", encoding="utf-8")
        with self.assertRaisesRegex(TargetIntegrityError, "CPython runtime"):
            self.fixture.registry.reverify(accepted)

        other = RegistryFixture()
        try:
            accepted = other.registry.resolve(ExecutionTarget.GOLDEN_PART_R2).plan
            other.environment_hook.write_text("BOOTSTRAP = None\n", encoding="utf-8")
            with self.assertRaisesRegex(TargetIntegrityError, "dependency runtime"):
                other.registry.reverify(accepted)
        finally:
            other.close()

        another = RegistryFixture()
        try:
            accepted = another.registry.resolve(ExecutionTarget.GOLDEN_PART_R2).plan
            (another.environment / "pyvenv.cfg").write_text(
                "home = changed\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(TargetIntegrityError, "dependency runtime"):
                another.registry.reverify(accepted)
        finally:
            another.close()

    def test_missing_locked_dependency_and_extra_startup_hook_are_unavailable(self):
        shutil.rmtree(self.fixture.dist_info["cadquery"])
        with self.assertRaisesRegex(TargetUnavailableError, "do not match uv.lock"):
            self.fixture.registry.resolve(ExecutionTarget.GOLDEN_PART_R2)

        other = RegistryFixture()
        try:
            (other.purelib / "unapproved.pth").write_text(
                "import unapproved\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(TargetIntegrityError, "pth inventory"):
                other.registry.resolve(ExecutionTarget.GOLDEN_PART_R2)
        finally:
            other.close()

    def test_slicer_tree_and_archive_drift_fail_closed(self):
        accepted = self.fixture.registry.resolve(ExecutionTarget.GOLDEN_PART_R4).plan
        self.fixture.slicer_dll.write_bytes(b"changed-runtime")
        with self.assertRaisesRegex(TargetIntegrityError, "slicer runtime"):
            self.fixture.registry.reverify(accepted)

        other = RegistryFixture()
        try:
            other.archive.unlink()
            with self.assertRaises(TargetUnavailableError):
                other.registry.resolve(ExecutionTarget.GOLDEN_PART_R4)
        finally:
            other.close()

    def test_manifest_parsers_reject_open_shapes_and_unsafe_paths(self):
        runtime = json.loads(
            self.fixture.runtime_manifest_path.read_text(encoding="utf-8")
        )
        runtime["unexpected"] = True
        with self.assertRaisesRegex(TargetIntegrityError, "unsupported or missing"):
            _parse_cad_runtime_manifest(runtime)

        slicer = json.loads(
            self.fixture.slicer_manifest_path.read_text(encoding="utf-8")
        )
        slicer["installation"]["files"][0]["path"] = "../escape.dll"
        with self.assertRaisesRegex(TargetIntegrityError, "unsafe"):
            _parse_slicer_manifest(slicer)

    def test_admission_resolves_new_keys_but_replays_persisted_original(self):
        store = ExecutionControlStore(self.fixture.root / "execution-control.sqlite3")
        admission = RegisteredTargetAdmission(store, self.fixture.registry)
        request = ExecutionRequest(
            idempotency_key="registered-admission",
            target=ExecutionTarget.GOLDEN_PART_R2,
        )

        accepted = admission.admit(
            request, accepted_at="2026-07-16T00:00:00+00:00"
        )
        self.assertEqual(accepted.decision, AdmissionDecision.ACCEPT)
        self.assertTrue(accepted.current_target_checked)
        self.assertEqual(
            accepted.store_result.snapshot.record.plan,
            accepted.resolved_target.plan,
        )
        self.assertEqual(
            store.lookup_request(request), accepted.store_result.snapshot
        )

        # Current target drift cannot rewrite or hide the immutable original.
        self.fixture.python_module.write_text("RUNTIME = 2\n", encoding="utf-8")
        replay = admission.admit(
            request, accepted_at="2026-07-16T00:00:01+00:00"
        )
        self.assertEqual(replay.decision, AdmissionDecision.IDEMPOTENT_REPLAY)
        self.assertFalse(replay.current_target_checked)
        self.assertIsNone(replay.resolved_target)

        conflict = admission.admit(
            ExecutionRequest(
                idempotency_key="registered-admission",
                target=ExecutionTarget.GOLDEN_PART_R4,
            ),
            accepted_at="2026-07-16T00:00:02+00:00",
        )
        self.assertEqual(conflict.decision, AdmissionDecision.IDEMPOTENCY_CONFLICT)
        self.assertFalse(conflict.current_target_checked)
        with self.assertRaises(TargetIntegrityError):
            admission.admit(
                ExecutionRequest(
                    idempotency_key="new-drifted-target",
                    target=ExecutionTarget.GOLDEN_PART_R2,
                ),
                accepted_at="2026-07-16T00:00:03+00:00",
            )
        self.assertEqual(len(store.list_records()), 1)


class ProductionTargetRegistryTests(unittest.TestCase):
    def test_current_pinned_r4_target_matches_committed_content_manifests(self):
        try:
            resolved = TrustedTargetRegistry.from_checkout().resolve(
                ExecutionTarget.GOLDEN_PART_R4
            )
        except TargetUnavailableError as exc:
            self.skipTest(f"pinned CAD/slicer environment unavailable: {exc}")

        self.assertFalse(resolved.hardware_actions)
        self.assertEqual(
            resolved.plan.cad_runtime.cad_runtime_manifest_sha256,
            "8217567ffd154c7afe3dc21bbb76ccb440608b2c798087b93050c8837480cfc3",
        )
        self.assertEqual(
            resolved.plan.slicer.installation_manifest_sha256,
            "9caf181848d739493c509eb82eff1412b520805da6e57551a3c586c458c9700d",
        )
        self.assertEqual(
            resolved.plan.slicer.installation_tree_sha256,
            "9c0719e49db384ddb61220ab5f49c9c9996b1819b060368aa763b836fc489b62",
        )


if __name__ == "__main__":
    unittest.main()
