"""Real, disconnected PrusaSlicer CLI adapter with provenance and logs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Sequence
from zipfile import is_zipfile

from .gcode import GCodePreflightReport, GCodeSummary
from .profiles import ProfileBundle


ADAPTER_ID = "prusaslicer_cli"
ADAPTER_VERSION = "1.0.0"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _environment() -> dict[str, str]:
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
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


@dataclass(frozen=True)
class SlicerInstallation:
    executable: Path
    version: str
    executable_size_bytes: int
    executable_checksum_sha256: str
    adapter_id: str = ADAPTER_ID
    adapter_version: str = ADAPTER_VERSION
    license: str = "AGPL-3.0"
    release_url: str = "https://github.com/prusa3d/PrusaSlicer/releases"

    @classmethod
    def inspect(cls, executable: Path, *, timeout_seconds: float = 30.0) -> "SlicerInstallation":
        executable = executable.resolve()
        if not executable.is_file():
            raise FileNotFoundError(f"PrusaSlicer console executable not found: {executable}")
        completed = subprocess.run(
            [str(executable), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=_environment(),
        )
        output = "\n".join(item for item in (completed.stdout, completed.stderr) if item)
        match = re.search(r"PrusaSlicer-([0-9][^\s]*) based on Slic3r", output)
        if not match:
            raise ValueError("executable did not identify itself as PrusaSlicer")
        return cls(
            executable=executable,
            version=match.group(1),
            executable_size_bytes=executable.stat().st_size,
            executable_checksum_sha256=_sha256(executable),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "tool": "PrusaSlicer",
            "version": self.version,
            "license": self.license,
            "release_url": self.release_url,
            "executable": self.executable.name,
            "executable_size_bytes": self.executable_size_bytes,
            "executable_checksum_sha256": self.executable_checksum_sha256,
        }


@dataclass(frozen=True)
class ModelInfo:
    filename: str
    size_mm: tuple[float, float, float]
    minimum_mm: tuple[float, float, float]
    maximum_mm: tuple[float, float, float]
    number_of_facets: int
    manifold: bool
    degenerate_facets: int
    facets_removed: int
    number_of_parts: int
    volume_mm3: float

    @classmethod
    def parse(cls, output: str) -> "ModelInfo":
        values: dict[str, str] = {}
        filename = "unknown"
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                filename = line[1:-1]
                continue
            key, separator, value = line.partition(" = ")
            if separator:
                values[key.strip()] = value.strip()

        def number(key: str, default: float | None = None) -> float:
            raw = values.get(key)
            if raw is None:
                if default is None:
                    raise ValueError(f"PrusaSlicer model info is missing {key}")
                return default
            return float(raw)

        def integer(key: str, default: int = 0) -> int:
            return int(number(key, float(default)))

        manifold = values.get("manifold")
        if manifold not in {"yes", "no"}:
            raise ValueError("PrusaSlicer model info is missing manifold status")
        return cls(
            filename=filename,
            size_mm=tuple(number(f"size_{axis}") for axis in "xyz"),
            minimum_mm=tuple(number(f"min_{axis}") for axis in "xyz"),
            maximum_mm=tuple(number(f"max_{axis}") for axis in "xyz"),
            number_of_facets=integer("number_of_facets"),
            manifold=manifold == "yes",
            degenerate_facets=integer("degenerate_facets"),
            facets_removed=integer("facets_removed"),
            number_of_parts=integer("number_of_parts"),
            volume_mm3=number("volume"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "size_mm": dict(zip("xyz", self.size_mm, strict=True)),
            "minimum_mm": dict(zip("xyz", self.minimum_mm, strict=True)),
            "maximum_mm": dict(zip("xyz", self.maximum_mm, strict=True)),
            "number_of_facets": self.number_of_facets,
            "manifold": self.manifold,
            "degenerate_facets": self.degenerate_facets,
            "facets_removed": self.facets_removed,
            "number_of_parts": self.number_of_parts,
            "volume_mm3": self.volume_mm3,
        }


@dataclass(frozen=True)
class CommandRecord:
    arguments: tuple[str, ...]
    return_code: int
    stdout_path: Path
    stderr_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "arguments": list(self.arguments),
            "return_code": self.return_code,
            "stdout": self.stdout_path.name,
            "stderr": self.stderr_path.name,
        }


@dataclass(frozen=True)
class SliceOutcome:
    input_model_path: Path
    model_info: ModelInfo
    summary: GCodeSummary
    preflight: GCodePreflightReport
    slicer_warnings: tuple[str, ...]
    project_path: Path
    gcode_path: Path
    installation_path: Path
    preflight_path: Path
    report_path: Path
    installation: SlicerInstallation
    profiles: ProfileBundle
    commands: tuple[CommandRecord, ...]

    @property
    def status(self) -> str:
        if not self.preflight.passed:
            return "failed"
        return "passed_with_warnings" if self.slicer_warnings else "passed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "classification": "real_disconnected_slicer_run",
            "status": self.status,
            "slicer_completed": True,
            "input_model": {
                "filename": self.input_model_path.name,
                "size_bytes": self.input_model_path.stat().st_size,
                "checksum_sha256": _sha256(self.input_model_path),
            },
            "slicer": self.installation.to_dict(),
            "profiles": self.profiles.to_dict(relative_to=self.report_path.parent),
            "model_info": self.model_info.to_dict(),
            "gcode_summary": self.summary.to_dict(),
            "preflight": self.preflight.to_dict(),
            "slicer_warnings": list(self.slicer_warnings),
            "artifacts": {
                "slicer_project": {
                    "path": self.project_path.name,
                    "size_bytes": self.project_path.stat().st_size,
                    "checksum_sha256": _sha256(self.project_path),
                },
                "gcode": {
                    "path": self.gcode_path.name,
                    "size_bytes": self.gcode_path.stat().st_size,
                    "checksum_sha256": _sha256(self.gcode_path),
                },
                "slicer_installation": {
                    "path": self.installation_path.name,
                    "size_bytes": self.installation_path.stat().st_size,
                    "checksum_sha256": _sha256(self.installation_path),
                },
                "gcode_preflight": {
                    "path": self.preflight_path.name,
                    "size_bytes": self.preflight_path.stat().st_size,
                    "checksum_sha256": _sha256(self.preflight_path),
                },
            },
            "commands": [item.to_dict() for item in self.commands],
            "claim_boundary": (
                "A real slicer produced a project and G-code under the recorded disconnected "
                "profile. Slicer warnings remain unresolved findings, and no hardware action or "
                "physical print occurred."
            ),
        }


def parse_slicer_warnings(output: str) -> tuple[str, ...]:
    warnings: list[str] = []
    active = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if "print warning:" in line.lower():
            active = True
            continue
        if not active:
            continue
        if re.match(r"^\d+\s*=>", line) or "Slicing process finished" in line:
            active = False
            continue
        if not line or line.lower().startswith("detected print stability issues"):
            continue
        if line.lower().startswith(("consider ", "also consider ")):
            continue
        if line.lower().endswith((".stl", ".3mf", ".obj")):
            continue
        if line not in warnings:
            warnings.append(line)
    return tuple(warnings)


class PrusaSlicerAdapter:
    """Invoke one approved local PrusaSlicer executable without hardware access."""

    def __init__(
        self,
        executable: Path,
        *,
        timeout_seconds: float = 180.0,
        threads: int = 4,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if threads <= 0:
            raise ValueError("threads must be greater than zero")
        self.installation = SlicerInstallation.inspect(executable)
        self.timeout_seconds = float(timeout_seconds)
        self.threads = int(threads)

    def _run(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path,
        stdout_path: Path,
        stderr_path: Path,
    ) -> tuple[CommandRecord, str]:
        command = [str(self.installation.executable), *arguments]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                cwd=cwd,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                env=_environment(),
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else exc.stdout
            stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else exc.stderr
            stdout_path.write_text(stdout or "", encoding="utf-8")
            stderr_path.write_text(stderr or "", encoding="utf-8")
            raise TimeoutError(f"PrusaSlicer exceeded the {self.timeout_seconds:g} second timeout") from exc
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        record = CommandRecord(
            arguments=tuple(arguments),
            return_code=completed.returncode,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        return record, "\n".join(item for item in (completed.stdout, completed.stderr) if item)

    def slice_model(
        self,
        model_path: Path,
        output_directory: Path,
        profiles: ProfileBundle,
    ) -> SliceOutcome:
        model_path = model_path.resolve()
        output_directory = output_directory.resolve()
        if not model_path.is_file():
            raise FileNotFoundError(model_path)
        output_directory.mkdir(parents=True, exist_ok=True)
        datadir = output_directory / "slicer_datadir"
        datadir.mkdir()
        project_path = output_directory / "slicer_project.3mf"
        gcode_path = output_directory / "toolpath.gcode"
        report_path = output_directory / "slice_report.json"
        installation_path = output_directory / "slicer_installation.json"
        preflight_path = output_directory / "gcode_preflight.json"
        if any(
            path.exists()
            for path in (
                project_path,
                gcode_path,
                report_path,
                installation_path,
                preflight_path,
            )
        ):
            raise FileExistsError("slicer output artifacts are immutable and already exist")
        _write_json(installation_path, self.installation.to_dict())

        commands: list[CommandRecord] = []

        def relative(path: Path) -> str:
            return Path(os.path.relpath(path, output_directory)).as_posix()

        info_record, info_output = self._run(
            ("--info", relative(model_path)),
            cwd=output_directory,
            stdout_path=output_directory / "model_info.stdout.log",
            stderr_path=output_directory / "model_info.stderr.log",
        )
        commands.append(info_record)
        if info_record.return_code != 0:
            raise RuntimeError(f"PrusaSlicer model inspection failed with code {info_record.return_code}")
        model_info = ModelInfo.parse(info_output)
        if not model_info.manifold or model_info.number_of_parts != 1:
            raise ValueError("slicer input must be one manifold part after reported repairs")

        center = f"{profiles.printer.build_volume_mm[0] / 2:g},{profiles.printer.build_volume_mm[1] / 2:g}"
        common = (
            "--datadir",
            relative(datadir),
            "--load",
            relative(profiles.slicer_config_path),
            "--center",
            center,
            "--threads",
            str(self.threads),
            "--loglevel",
            "3",
        )
        project_record, _ = self._run(
            (*common, "--export-3mf", "--output", relative(project_path), relative(model_path)),
            cwd=output_directory,
            stdout_path=output_directory / "project.stdout.log",
            stderr_path=output_directory / "project.stderr.log",
        )
        commands.append(project_record)
        if project_record.return_code != 0 or not project_path.is_file() or not is_zipfile(project_path):
            raise RuntimeError("PrusaSlicer did not produce a valid 3MF project")

        slice_record, slice_output = self._run(
            (*common, "--export-gcode", "--output", relative(gcode_path), relative(model_path)),
            cwd=output_directory,
            stdout_path=output_directory / "slice.stdout.log",
            stderr_path=output_directory / "slice.stderr.log",
        )
        commands.append(slice_record)
        if slice_record.return_code != 0 or not gcode_path.is_file():
            raise RuntimeError(f"PrusaSlicer G-code export failed with code {slice_record.return_code}")
        summary = GCodeSummary.parse(gcode_path)
        if summary.slicer_version != self.installation.version:
            raise ValueError("G-code slicer version does not match the approved executable")
        preflight = GCodePreflightReport.evaluate(summary, profiles)
        outcome = SliceOutcome(
            input_model_path=model_path,
            model_info=model_info,
            summary=summary,
            preflight=preflight,
            slicer_warnings=parse_slicer_warnings(slice_output),
            project_path=project_path,
            gcode_path=gcode_path,
            installation_path=installation_path,
            preflight_path=preflight_path,
            report_path=report_path,
            installation=self.installation,
            profiles=profiles,
            commands=tuple(commands),
        )
        _write_json(preflight_path, preflight.to_dict())
        _write_json(report_path, outcome.to_dict())
        return outcome
