"""Registry-sealed PrusaSlicer adapter using Windows Job supervision."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from ..slicing.profiles import ProfileBundle
from ..slicing.prusaslicer import (
    ADAPTER_ID,
    ADAPTER_VERSION,
    CommandRecord,
    PrusaSlicerAdapter,
    SlicerInstallation,
    SliceOutcome,
)
from .cad_adapter import _sanitized_environment
from .contracts import (
    NO_HARDWARE_RUNNER_POLICY,
    ExecutionPlan,
    ExecutionTarget,
    RunnerPolicy,
)
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


SEALED_SLICER_ADAPTER_VERSION = "0.1.0"


class SealedPrusaSlicerAdapter(PrusaSlicerAdapter):
    """Run only the accepted R4 slicer and fixed four-thread policy."""

    def __init__(
        self,
        registry: TrustedTargetRegistry,
        accepted_plan: ExecutionPlan,
        workspace: Path,
        *,
        supervisor: WindowsJobProcessSupervisor | None = None,
        cancellation: CancellationToken | None = None,
        execution_deadline: ExecutionDeadline | None = None,
        policy: RunnerPolicy = NO_HARDWARE_RUNNER_POLICY,
    ) -> None:
        if not isinstance(registry, TrustedTargetRegistry):
            raise TypeError("registry must be a TrustedTargetRegistry")
        if not isinstance(accepted_plan, ExecutionPlan):
            raise TypeError("accepted_plan must be an ExecutionPlan")
        if accepted_plan.target is not ExecutionTarget.GOLDEN_PART_R4:
            raise ValueError("sealed slicer requires the registered R4 target")
        if accepted_plan.slicer is None:
            raise ValueError("accepted R4 plan has no slicer identity")
        if not isinstance(policy, RunnerPolicy):
            raise TypeError("policy must be a RunnerPolicy")
        resolved = registry.reverify(accepted_plan)
        executable = resolved.slicer_executable_path
        if executable is None:
            raise ValueError("registered R4 target has no slicer executable")
        executable = executable.resolve(strict=True)
        if sha256(executable.read_bytes()).hexdigest() != accepted_plan.slicer.executable_sha256:
            raise ValueError("slicer executable changed after target re-verification")
        root = Path(workspace).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("sealed slicer workspace must be a directory")

        # Deliberately bypass PrusaSlicerAdapter.__init__: its legacy executable
        # inspection uses an unsupervised subprocess. The registry already
        # verified the complete installation and accepted version identity.
        self.installation = SlicerInstallation(
            executable=executable,
            version=accepted_plan.slicer.slicer_version,
            executable_size_bytes=executable.stat().st_size,
            executable_checksum_sha256=accepted_plan.slicer.executable_sha256,
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
        )
        self.timeout_seconds = float(policy.slicer_command_timeout_seconds)
        self.threads = policy.slicer_threads
        self.registry = registry
        self.accepted_plan = accepted_plan
        self.workspace = root
        self.supervisor = supervisor or WindowsJobProcessSupervisor()
        self.cancellation = cancellation
        self.execution_deadline = execution_deadline
        self.policy = policy
        self.supervised_results: list[SupervisedProcessResult] = []

    def slice_model(
        self,
        model_path: Path,
        output_directory: Path,
        profiles: ProfileBundle,
    ) -> SliceOutcome:
        resolved = self.registry.reverify(self.accepted_plan)
        if resolved.slicer_executable_path != self.installation.executable:
            raise ValueError("registered slicer path changed before slicing")
        model = Path(model_path).resolve(strict=True)
        output = Path(output_directory).resolve(strict=False)
        if not model.is_relative_to(self.workspace) or not output.is_relative_to(self.workspace):
            raise ValueError("sealed slicer inputs and outputs must remain in the workspace")
        return super().slice_model(model, output, profiles)

    def _run(
        self,
        arguments,
        *,
        cwd: Path,
        stdout_path: Path,
        stderr_path: Path,
    ) -> tuple[CommandRecord, str]:
        cwd = Path(cwd).resolve(strict=True)
        stdout_path = Path(stdout_path).resolve(strict=False)
        stderr_path = Path(stderr_path).resolve(strict=False)
        if (
            not cwd.is_relative_to(self.workspace)
            or not stdout_path.is_relative_to(self.workspace)
            or not stderr_path.is_relative_to(self.workspace)
        ):
            raise ValueError("sealed slicer command paths must remain in the workspace")
        command = SupervisedCommand(
            executable=self.installation.executable,
            arguments=tuple(arguments),
            cwd=cwd,
            environment=_sanitized_environment(self.workspace),
            workspace=self.workspace,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        limits = SupervisionLimits.from_policy(
            self.policy,
            command_timeout_seconds=self.policy.slicer_command_timeout_seconds,
        )
        result = self.supervisor.run(
            command,
            limits,
            cancellation=self.cancellation,
            execution_deadline=self.execution_deadline,
        )
        self.supervised_results.append(result)
        if result.reason is ProcessTerminationReason.WALL_TIMEOUT:
            raise TimeoutError(
                f"PrusaSlicer exceeded the {self.timeout_seconds:g} second timeout"
            )
        if result.reason is not ProcessTerminationReason.EXITED:
            raise RuntimeError(f"sealed PrusaSlicer stopped at {result.reason.value}")
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
        record = CommandRecord(
            arguments=tuple(arguments),
            return_code=result.return_code,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        return record, "\n".join(item for item in (stdout, stderr) if item)


__all__ = ["SEALED_SLICER_ADAPTER_VERSION", "SealedPrusaSlicerAdapter"]
