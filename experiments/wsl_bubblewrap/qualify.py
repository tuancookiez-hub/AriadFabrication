"""Qualify a WSL2 Bubblewrap boundary without running Ariad's CAD pipeline.

This experiment proves only mount/workspace/network namespace behavior for one
short-lived probe. It does not qualify Python, CadQuery, OCCT, PrusaSlicer, or
the registered R2/R4 execution service.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
import tempfile


QUALIFICATION_VERSION = "0.1.0"
_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class QualificationReport:
    qualification_version: str
    wsl_available: bool
    bubblewrap_available: bool
    host_mount_hidden: bool
    workspace_write_allowed: bool
    external_network_denied: bool
    exit_code: int | None
    evidence_mode: str = "experiment"
    cad_runtime_qualified: bool = False
    slicer_runtime_qualified: bool = False
    registered_execution_ready: bool = False
    hardware_actions: bool = False


def _run(arguments: list[str], *, timeout: int = _TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive
    if len(drive) != 2 or drive[1] != ":":
        raise RuntimeError("qualification paths must use a local Windows drive")
    tail = resolved.as_posix()[2:].lstrip("/")
    return f"/mnt/{drive[0].lower()}/{tail}"


def qualify() -> QualificationReport:
    version = _run(["wsl.exe", "--", "bwrap", "--version"])
    if version.returncode != 0:
        return QualificationReport(
            qualification_version=QUALIFICATION_VERSION,
            wsl_available="not recognized" not in version.stderr.casefold(),
            bubblewrap_available=False,
            host_mount_hidden=False,
            workspace_write_allowed=False,
            external_network_denied=False,
            exit_code=None,
        )

    with tempfile.TemporaryDirectory(prefix="ariad-bwrap-qualification-") as raw:
        workspace = Path(raw).resolve()
        sentinel = workspace.parent / f"{workspace.name}-host-sentinel.txt"
        sentinel.write_text("host-only", encoding="utf-8")
        try:
            wsl_workspace = _wsl_path(workspace)
            wsl_sentinel = _wsl_path(sentinel)
            script = (
                "set -eu; "
                f"test ! -e {json.dumps(wsl_sentinel)}; echo HOST_HIDDEN; "
                "printf workspace > /workspace/probe.txt; echo WORKSPACE_WRITABLE; "
                "if curl --noproxy '*' --connect-timeout 1 --max-time 2 "
                "http://1.1.1.1 >/dev/null 2>&1; then exit 71; fi; "
                "echo NETWORK_DENIED"
            )
            command = [
                "wsl.exe",
                "--",
                "bwrap",
                "--unshare-all",
                "--die-with-parent",
                "--new-session",
                "--clearenv",
                "--ro-bind",
                "/usr",
                "/usr",
                "--ro-bind",
                "/bin",
                "/bin",
                "--ro-bind",
                "/lib",
                "/lib",
                "--ro-bind",
                "/lib64",
                "/lib64",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "--bind",
                wsl_workspace,
                "/workspace",
                "--chdir",
                "/workspace",
                "--",
                "/bin/sh",
                "-c",
                script,
            ]
            completed = _run(command)
            markers = set(completed.stdout.splitlines())
            wrote_expected = (workspace / "probe.txt").read_text(encoding="utf-8") == "workspace"
            return QualificationReport(
                qualification_version=QUALIFICATION_VERSION,
                wsl_available=True,
                bubblewrap_available=True,
                host_mount_hidden="HOST_HIDDEN" in markers,
                workspace_write_allowed="WORKSPACE_WRITABLE" in markers and wrote_expected,
                external_network_denied="NETWORK_DENIED" in markers,
                exit_code=completed.returncode,
            )
        finally:
            sentinel.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = qualify()
    rendered = json.dumps(asdict(report), sort_keys=True, indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    controls_pass = (
        report.exit_code == 0
        and report.host_mount_hidden
        and report.workspace_write_allowed
        and report.external_network_denied
    )
    return 0 if controls_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
