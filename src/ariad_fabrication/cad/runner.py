"""Parent-side runner for the separate CAD worker process."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from .contracts import CadBuildRequest, CadBuildResult


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True)
class CadRunOutcome:
    result: CadBuildResult
    revision_directory: Path
    request_path: Path
    result_path: Path
    stdout_path: Path
    stderr_path: Path
    return_code: int | None
    timed_out: bool = False


class CadWorkerRunner:
    """Invoke the registered worker with timeout and confined output paths."""

    def __init__(
        self,
        artifact_root: Path,
        *,
        python_executable: Path | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.artifact_root = artifact_root.resolve()
        self.python_executable = (python_executable or Path(sys.executable)).resolve()
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self.timeout_seconds = float(timeout_seconds)

    def run(self, request: CadBuildRequest) -> CadRunOutcome:
        for name, value in (("job_id", request.job_id), ("revision_id", request.revision_id)):
            if not _SAFE_ID.fullmatch(value):
                raise ValueError(f"{name} cannot be used in an artifact path")
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        revision_directory = (
            self.artifact_root / request.job_id / "revisions" / request.revision_id
        ).resolve()
        if not revision_directory.is_relative_to(self.artifact_root):
            raise ValueError("revision directory escapes the configured artifact root")
        revision_directory.mkdir(parents=True, exist_ok=True)
        request_path = revision_directory / "cad_request.json"
        result_path = revision_directory / "cad_result.json"
        stdout_path = revision_directory / "cad_worker.stdout.log"
        stderr_path = revision_directory / "cad_worker.stderr.log"
        output_directory = revision_directory / "design"
        protected = (request_path, result_path, output_directory)
        if any(path.exists() for path in protected):
            raise FileExistsError("CAD run artifacts are immutable and already exist")
        _write_json(request_path, request.to_dict())

        command = [
            str(self.python_executable),
            "-m",
            "ariad_fabrication.cad.worker",
            "--request",
            str(request_path),
            "--output",
            str(output_directory),
            "--result",
            str(result_path),
        ]
        environment = self._worker_environment()
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = subprocess.run(
                command,
                cwd=revision_directory,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                creationflags=creation_flags,
            )
            stdout_path.write_text(completed.stdout, encoding="utf-8")
            stderr_path.write_text(completed.stderr, encoding="utf-8")
            result = self._read_result(
                result_path,
                request,
                fallback_error=(
                    f"CAD worker exited with code {completed.returncode} without a valid result"
                ),
            )
            if result.success:
                try:
                    self._verify_artifacts(result, revision_directory)
                except Exception as exc:
                    quarantine_error = ""
                    try:
                        self._quarantine_output(output_directory, request.request_id)
                    except Exception as quarantine_exc:
                        quarantine_error = (
                            f"; quarantine failed: {type(quarantine_exc).__name__}: "
                            f"{quarantine_exc}"
                        )
                    result = self._failure(
                        request,
                        "CAD worker artifact verification failed: "
                        f"{type(exc).__name__}: {exc}{quarantine_error}",
                    )
                    _write_json(result_path, result.to_dict())
            if completed.returncode != 0 and result.success:
                result = self._failure(
                    request,
                    f"CAD worker returned success with non-zero exit code {completed.returncode}",
                )
                _write_json(result_path, result.to_dict())
            return CadRunOutcome(
                result=result,
                revision_directory=revision_directory,
                request_path=request_path,
                result_path=result_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                return_code=completed.returncode,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else exc.stdout
            stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else exc.stderr
            stdout_path.write_text(stdout or "", encoding="utf-8")
            stderr_path.write_text(stderr or "", encoding="utf-8")
            result = self._failure(
                request,
                f"CAD worker exceeded the {self.timeout_seconds:g} second timeout",
            )
            _write_json(result_path, result.to_dict())
            return CadRunOutcome(
                result=result,
                revision_directory=revision_directory,
                request_path=request_path,
                result_path=result_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                return_code=None,
                timed_out=True,
            )

    @staticmethod
    def _verify_artifacts(result: CadBuildResult, revision_directory: Path) -> None:
        if not result.artifacts:
            raise ValueError("successful CAD result contains no artifacts")
        for descriptor in result.artifacts:
            path = (revision_directory / descriptor.path).resolve()
            if not path.is_relative_to(revision_directory):
                raise ValueError(f"artifact path escapes the revision directory: {descriptor.path}")
            payload = path.read_bytes()
            if len(payload) != descriptor.size_bytes:
                raise ValueError(f"artifact size does not match: {descriptor.path}")
            if hashlib.sha256(payload).hexdigest() != descriptor.checksum_sha256:
                raise ValueError(f"artifact checksum does not match: {descriptor.path}")

    @staticmethod
    def _quarantine_output(output_directory: Path, request_id: str) -> None:
        if not output_directory.exists():
            return
        key = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:16]
        quarantine = output_directory.parent / f".rejected-design-{key}"
        if quarantine.exists():
            raise FileExistsError(f"CAD quarantine path already exists: {quarantine}")
        output_directory.rename(quarantine)

    @staticmethod
    def _read_result(
        result_path: Path,
        request: CadBuildRequest,
        *,
        fallback_error: str,
    ) -> CadBuildResult:
        try:
            value = json.loads(result_path.read_text(encoding="utf-8"))
            result = CadBuildResult.from_mapping(value)
            if result.request_id != request.request_id or result.provider_id != request.provider_id:
                raise ValueError("CAD result identity does not match its request")
            return result
        except Exception as exc:
            result = CadWorkerRunner._failure(
                request,
                f"{fallback_error}: {type(exc).__name__}: {exc}",
            )
            _write_json(result_path, result.to_dict())
            return result

    @staticmethod
    def _failure(request: CadBuildRequest, message: str) -> CadBuildResult:
        now = _utc_now()
        return CadBuildResult(
            request_id=request.request_id,
            provider_id=request.provider_id,
            success=False,
            started_at=now,
            completed_at=now,
            errors=(message,),
        )

    def _worker_environment(self) -> dict[str, str]:
        allowed = {
            "SYSTEMROOT",
            "WINDIR",
            "PATH",
            "PATHEXT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "LOCALAPPDATA",
            "APPDATA",
            "PROGRAMDATA",
        }
        environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        environment.update(
            {
                "PYTHONNOUSERSITE": "1",
                "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        return environment
