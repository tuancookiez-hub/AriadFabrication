"""Sealed, supervised adapter for the registered Ariad CAD worker."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Mapping

from ..cad.contracts import CadBuildRequest, CadBuildResult
from ..cad.runner import CadRunOutcome, CadWorkerRunner
from .bootstrap_config import write_worker_bootstrap_config
from .contracts import NO_HARDWARE_RUNNER_POLICY, ExecutionPlan, RunnerPolicy
from .registry import TrustedTargetRegistry
from .windows_job import (
    CancellationToken,
    ExecutionDeadline,
    ProcessTerminationReason,
    SupervisedCommand,
    SupervisedProcessResult,
    SupervisionLimits,
    WindowsJobProcessSupervisor,
)


SEALED_CAD_ADAPTER_VERSION = "0.1.0"
_MAX_RESULT_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class SealedCadRun:
    process: SupervisedProcessResult
    result: CadBuildResult
    workspace: Path
    request_path: Path
    result_path: Path
    output_directory: Path
    stdout_path: Path
    stderr_path: Path
    hardware_actions: bool = False
    adapter_version: str = SEALED_CAD_ADAPTER_VERSION

    def __post_init__(self) -> None:
        if self.hardware_actions:
            raise ValueError("sealed CAD execution cannot enable hardware actions")
        if self.adapter_version != SEALED_CAD_ADAPTER_VERSION:
            raise ValueError("unsupported sealed CAD adapter version")


def _sanitized_environment(workspace: Path) -> Mapping[str, str]:
    home = workspace / ".home"
    local = home / "AppData/Local"
    roaming = home / "AppData/Roaming"
    for directory in (home, local, roaming):
        directory.mkdir(parents=True, exist_ok=True)
    result = {
        name: os.environ[name]
        for name in ("SYSTEMROOT", "WINDIR")
        if name in os.environ
    }
    result.update(
        {
            "TEMP": str(workspace),
            "TMP": str(workspace),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "LOCALAPPDATA": str(local),
            "APPDATA": str(roaming),
            "COMSPEC": str(workspace / ".command-processor-disabled.exe"),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    return result


def _read_result(path: Path, request: CadBuildRequest) -> CadBuildResult:
    with path.open("rb") as stream:
        payload = stream.read(_MAX_RESULT_BYTES + 1)
    if len(payload) > _MAX_RESULT_BYTES:
        raise ValueError("sealed CAD result exceeds its byte ceiling")
    value = json.loads(payload.decode("utf-8"))
    result = CadBuildResult.from_mapping(value)
    if result.request_id != request.request_id or result.provider_id != request.provider_id:
        raise ValueError("sealed CAD result identity does not match its request")
    return result


class SealedCadWorkerAdapter:
    """Run only an accepted, launch-reverified Golden Part CAD request."""

    def __init__(
        self,
        registry: TrustedTargetRegistry,
        *,
        supervisor: WindowsJobProcessSupervisor | None = None,
        policy: RunnerPolicy = NO_HARDWARE_RUNNER_POLICY,
    ) -> None:
        if not isinstance(registry, TrustedTargetRegistry):
            raise TypeError("registry must be a TrustedTargetRegistry")
        if not isinstance(policy, RunnerPolicy):
            raise TypeError("policy must be a RunnerPolicy")
        self.registry = registry
        self.supervisor = supervisor or WindowsJobProcessSupervisor()
        self.policy = policy

    def run(
        self,
        accepted_plan: ExecutionPlan,
        request: CadBuildRequest,
        workspace: Path,
        *,
        cancellation: CancellationToken | None = None,
        execution_deadline: ExecutionDeadline | None = None,
    ) -> SealedCadRun:
        if not isinstance(accepted_plan, ExecutionPlan):
            raise TypeError("accepted_plan must be an ExecutionPlan")
        if not isinstance(request, CadBuildRequest):
            raise TypeError("request must be a CadBuildRequest")
        resolved = self.registry.reverify(accepted_plan)
        root = Path(workspace).resolve(strict=True)
        if any(root.iterdir()):
            raise FileExistsError("sealed CAD workspace must be empty")

        request_path = root / "cad_request.json"
        result_path = root / "cad_result.json"
        output_directory = root / "design"
        config_path = root / "bootstrap.json"
        stdout_path = root / "cad_worker.stdout.log"
        stderr_path = root / "cad_worker.stderr.log"
        request_path.write_text(
            json.dumps(request.to_dict(), sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        bootstrap = (
            resolved.project_root
            / "src/ariad_fabrication/execution/worker_bootstrap.py"
        ).resolve(strict=True)
        write_worker_bootstrap_config(
            resolved,
            config_path,
            arguments=(
                "--request",
                str(request_path),
                "--output",
                str(output_directory),
                "--result",
                str(result_path),
            ),
        )
        command = SupervisedCommand(
            executable=resolved.python_executable,
            arguments=("-I", "-B", "-S", str(bootstrap), str(config_path)),
            cwd=root,
            environment=_sanitized_environment(root),
            workspace=root,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        limits = SupervisionLimits.from_policy(
            self.policy,
            command_timeout_seconds=self.policy.cad_timeout_seconds,
        )
        process = self.supervisor.run(
            command,
            limits,
            cancellation=cancellation,
            execution_deadline=execution_deadline,
        )
        if process.reason is not ProcessTerminationReason.EXITED:
            raise RuntimeError(f"sealed CAD worker stopped at {process.reason.value}")
        if not result_path.is_file():
            raise RuntimeError("sealed CAD worker did not publish a result")
        result = _read_result(result_path, request)
        if process.return_code == 0 and not result.success:
            raise RuntimeError("sealed CAD worker returned zero with a failed result")
        if process.return_code != 0 and result.success:
            raise RuntimeError("sealed CAD worker returned nonzero with a successful result")
        if result.success:
            CadWorkerRunner._verify_artifacts(result, root)
        return SealedCadRun(
            process=process,
            result=result,
            workspace=root,
            request_path=request_path,
            result_path=result_path,
            output_directory=output_directory,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )


class SealedCadPipelineRunner(CadWorkerRunner):
    """Drop-in GoldenPartCadPipeline runner backed by the sealed adapter."""

    def __init__(
        self,
        artifact_root: Path,
        registry: TrustedTargetRegistry,
        accepted_plan: ExecutionPlan,
        *,
        cancellation: CancellationToken | None = None,
        execution_deadline: ExecutionDeadline | None = None,
    ) -> None:
        super().__init__(artifact_root)
        if not isinstance(registry, TrustedTargetRegistry):
            raise TypeError("registry must be a TrustedTargetRegistry")
        if not isinstance(accepted_plan, ExecutionPlan):
            raise TypeError("accepted_plan must be an ExecutionPlan")
        self._adapter = SealedCadWorkerAdapter(registry)
        self._accepted_plan = accepted_plan
        self._cancellation = cancellation
        self._execution_deadline = execution_deadline

    def run(self, request: CadBuildRequest) -> CadRunOutcome:
        revision_directory = (
            self.artifact_root / request.job_id / "revisions" / request.revision_id
        ).resolve()
        if not revision_directory.is_relative_to(self.artifact_root):
            raise ValueError("revision directory escapes the configured artifact root")
        revision_directory.mkdir(parents=True, exist_ok=False)
        run = self._adapter.run(
            self._accepted_plan,
            request,
            revision_directory,
            cancellation=self._cancellation,
            execution_deadline=self._execution_deadline,
        )
        return CadRunOutcome(
            result=run.result,
            revision_directory=revision_directory,
            request_path=run.request_path,
            result_path=run.result_path,
            stdout_path=run.stdout_path,
            stderr_path=run.stderr_path,
            return_code=run.process.return_code,
            timed_out=run.process.reason is ProcessTerminationReason.WALL_TIMEOUT,
        )


__all__ = [
    "SEALED_CAD_ADAPTER_VERSION",
    "SealedCadRun",
    "SealedCadPipelineRunner",
    "SealedCadWorkerAdapter",
]
