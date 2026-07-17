"""Bounded read-only probe for a locally authenticated Codex app-server.

The probe performs the documented initialize handshake and ``account/read``.
It never starts a thread or turn, reads authentication files, exposes account
identifiers, registers tools, mutates the workspace, or performs fabrication.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import re
from threading import Thread
from time import monotonic
from typing import Any, Mapping, TextIO


LOCAL_CODEX_CONTRACT_VERSION = "1.0.0"
MAX_CODEX_LINE_BYTES = 256 * 1024
MAX_CODEX_VERSION_CHARS = 128
MINIMUM_CONVERSATION_VERSION = (0, 144, 5)


class LocalCodexStatus(str, Enum):
    READY = "ready"
    UNAUTHENTICATED = "unauthenticated"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class LocalCodexSnapshot:
    status: LocalCodexStatus
    cli_version: str | None
    authentication: str | None
    reason: str
    conversation_available: bool = False
    tools_registered: int = 0
    conversation_started: bool = False
    workspace_mutated: bool = False
    hardware_actions: bool = False
    contract_version: str = LOCAL_CODEX_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", LocalCodexStatus(self.status))
        if self.contract_version != LOCAL_CODEX_CONTRACT_VERSION:
            raise ValueError("unsupported local Codex contract version")
        if self.cli_version is not None and len(self.cli_version) > MAX_CODEX_VERSION_CHARS:
            raise ValueError("Codex CLI version is too long")
        if self.authentication not in {None, "chatgpt", "api_key", "other"}:
            raise ValueError("unsupported Codex authentication classification")
        if self.conversation_available != (self.status is LocalCodexStatus.READY):
            raise ValueError("Codex conversation availability must match ready status")
        if not self.reason or len(self.reason) > 512:
            raise ValueError("local Codex reason is required and bounded")
        if self.tools_registered != 0:
            raise ValueError("the read-only probe cannot register tools")
        if self.conversation_started or self.workspace_mutated or self.hardware_actions:
            raise ValueError("the read-only probe cannot start work or enable hardware")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "status": self.status.value,
            "cli_version": self.cli_version,
            "authentication": self.authentication,
            "reason": self.reason,
            "conversation_available": self.conversation_available,
            "tools_registered": 0,
            "conversation_started": False,
            "workspace_mutated": False,
            "hardware_actions": False,
        }


def snapshot_from_account_response(
    cli_version: str,
    response: Mapping[str, Any],
) -> LocalCodexSnapshot:
    """Reduce an app-server response without retaining account metadata."""

    result = response.get("result")
    if not isinstance(result, Mapping):
        raise ValueError("Codex account response has no result object")
    if not isinstance(result.get("requiresOpenaiAuth"), bool):
        raise ValueError("Codex account response has invalid auth policy")
    account = result.get("account")
    if account is None:
        return LocalCodexSnapshot(
            status=LocalCodexStatus.UNAUTHENTICATED,
            cli_version=cli_version,
            authentication=None,
            reason="Codex is installed, but no local account is authenticated.",
        )
    if not isinstance(account, Mapping) or not isinstance(account.get("type"), str):
        raise ValueError("Codex account response has invalid account state")
    account_type = account["type"]
    classification = {
        "chatgpt": "chatgpt",
        "apiKey": "api_key",
    }.get(account_type, "other")
    match = re.fullmatch(r"codex-cli (\d+)\.(\d+)\.(\d+)", cli_version)
    compatible = bool(
        match and tuple(int(item) for item in match.groups()) >= MINIMUM_CONVERSATION_VERSION
    )
    if not compatible:
        return LocalCodexSnapshot(
            status=LocalCodexStatus.INCOMPATIBLE,
            cli_version=cli_version,
            authentication=classification,
            reason="Codex is authenticated, but this CLI version cannot run the required model.",
            conversation_available=False,
        )
    return LocalCodexSnapshot(
        status=LocalCodexStatus.READY,
        cli_version=cli_version,
        authentication=classification,
        reason="Local Codex authentication is available; no conversation was started.",
        conversation_available=True,
    )


def _codex_environment() -> dict[str, str]:
    allowed = {
        "APPDATA",
        "CODEX_HOME",
        "HOME",
        "LOCALAPPDATA",
        "PATH",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _read_messages(stream: TextIO, output: Queue[object]) -> None:
    try:
        for line in stream:
            encoded = line.encode("utf-8", errors="replace")
            if len(encoded) > MAX_CODEX_LINE_BYTES:
                output.put(ValueError("Codex app-server emitted an oversized protocol line"))
                return
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                output.put(ValueError("Codex app-server emitted invalid JSON"))
                return
            output.put(value)
    finally:
        output.put(EOFError("Codex app-server closed its output"))


def _await_response(output: Queue[object], request_id: int, deadline: float) -> Mapping[str, Any]:
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Codex app-server probe timed out")
        try:
            message = output.get(timeout=remaining)
        except Empty as exc:
            raise TimeoutError("Codex app-server probe timed out") from exc
        if isinstance(message, BaseException):
            raise message
        if not isinstance(message, Mapping):
            raise ValueError("Codex app-server emitted a non-object message")
        if message.get("id") == request_id:
            if "error" in message:
                raise ValueError("Codex app-server rejected a read-only probe request")
            return message


def probe_local_codex(executable: Path, *, timeout_seconds: float = 5.0) -> LocalCodexSnapshot:
    """Probe one explicitly configured Codex executable over stdio."""

    path = executable.expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".exe":
        return LocalCodexSnapshot(
            status=LocalCodexStatus.UNAVAILABLE,
            cli_version=None,
            authentication=None,
            reason="A trusted absolute Codex executable was not configured.",
        )
    if not 0.5 <= timeout_seconds <= 15.0:
        raise ValueError("Codex probe timeout must be between 0.5 and 15 seconds")
    environment = _codex_environment()
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        version_result = subprocess.run(
            [str(path), "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            env=environment,
            creationflags=creationflags,
        )
        version = " ".join(version_result.stdout.split())[:MAX_CODEX_VERSION_CHARS]
        if version_result.returncode != 0 or not version:
            raise RuntimeError("Codex CLI version check failed")
        process = subprocess.Popen(
            [str(path), "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=environment,
            creationflags=creationflags,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return LocalCodexSnapshot(
            status=LocalCodexStatus.ERROR,
            cli_version=None,
            authentication=None,
            reason=f"Codex could not be probed: {type(exc).__name__}.",
        )

    try:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("Codex app-server pipes are unavailable")
        output: Queue[object] = Queue(maxsize=64)
        Thread(target=_read_messages, args=(process.stdout, output), daemon=True).start()
        deadline = monotonic() + timeout_seconds

        initialize = {
            "method": "initialize",
            "id": 1,
            "params": {
                "clientInfo": {
                    "name": "ariad_fabrication",
                    "title": "Ariad Fabrication",
                    "version": LOCAL_CODEX_CONTRACT_VERSION,
                }
            },
        }
        process.stdin.write(json.dumps(initialize, separators=(",", ":")) + "\n")
        process.stdin.flush()
        _await_response(output, 1, deadline)
        process.stdin.write('{"method":"initialized","params":{}}\n')
        process.stdin.write(
            '{"method":"account/read","id":2,"params":{"refreshToken":false}}\n'
        )
        process.stdin.flush()
        return snapshot_from_account_response(version, _await_response(output, 2, deadline))
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        return LocalCodexSnapshot(
            status=LocalCodexStatus.ERROR,
            cli_version=version,
            authentication=None,
            reason=f"Codex app-server handshake failed: {type(exc).__name__}.",
        )
    finally:
        if process.stdin is not None:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


__all__ = [
    "LOCAL_CODEX_CONTRACT_VERSION",
    "LocalCodexSnapshot",
    "LocalCodexStatus",
    "probe_local_codex",
    "snapshot_from_account_response",
]
