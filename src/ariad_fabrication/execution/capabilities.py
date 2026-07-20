"""Fail-closed capability reporting for the no-hardware execution adapter.

Capability discovery is read-only.  It does not launch a process, create an
AppContainer profile, change ACLs or firewall state, or contact hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import ctypes
import os
import platform
import struct
from typing import Iterable


POLICY_ADAPTER_VERSION = "0.1.0"


class PolicyControl(str, Enum):
    PROCESS_TREE = "process_tree"
    PROCESS_MEMORY = "process_memory"
    PROCESS_COUNT = "process_count"
    WALL_DEADLINE = "wall_deadline"
    CANCELLATION = "cancellation"
    BOUNDED_LOGS = "bounded_logs"
    WORKSPACE_LIMIT = "workspace_limit"
    FILESYSTEM_ISOLATION = "filesystem_isolation"
    NETWORK_DENIAL = "network_denial"
    PYTHON_IMPORT_BOUNDARY = "python_import_boundary"


_REQUIRED_CONTROLS = tuple(PolicyControl)


@dataclass(frozen=True)
class ControlCapability:
    control: PolicyControl
    enforced: bool
    mechanism: str
    limitation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.control, PolicyControl):
            raise ValueError("control must be a PolicyControl")
        if type(self.enforced) is not bool:
            raise ValueError("enforced must be a boolean")
        if not isinstance(self.mechanism, str) or not self.mechanism.strip():
            raise ValueError("capability mechanism is required")
        if self.enforced and self.limitation is not None:
            raise ValueError("an enforced capability cannot retain a limitation")
        if not self.enforced and (
            not isinstance(self.limitation, str) or not self.limitation.strip()
        ):
            raise ValueError("an unenforced capability requires a limitation")


@dataclass(frozen=True)
class PolicyCapabilityReport:
    system: str
    release: str
    version: str
    machine: str
    pointer_bits: int
    controls: tuple[ControlCapability, ...]
    job_object_api_available: bool
    appcontainer_api_available: bool
    experimental_sandbox_api_available: bool
    hardware_actions: bool = False
    adapter_version: str = POLICY_ADAPTER_VERSION

    def __post_init__(self) -> None:
        for name in ("system", "release", "version", "machine"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise ValueError(f"host {name} is invalid")
        if self.pointer_bits not in {32, 64}:
            raise ValueError("pointer_bits must be 32 or 64")
        if self.adapter_version != POLICY_ADAPTER_VERSION:
            raise ValueError("unsupported policy adapter version")
        if self.hardware_actions:
            raise ValueError("policy capability discovery cannot enable hardware actions")
        for name in (
            "job_object_api_available",
            "appcontainer_api_available",
            "experimental_sandbox_api_available",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        controls = tuple(self.controls)
        if len(controls) != len(_REQUIRED_CONTROLS):
            raise ValueError("capability report must name every required control once")
        identities = tuple(item.control for item in controls)
        if identities != _REQUIRED_CONTROLS:
            raise ValueError("capability report controls are not canonically ordered")
        object.__setattr__(self, "controls", controls)

    @property
    def registered_execution_ready(self) -> bool:
        return all(item.enforced for item in self.controls)

    @property
    def missing_controls(self) -> tuple[PolicyControl, ...]:
        return tuple(item.control for item in self.controls if not item.enforced)

    def require_registered_execution(self) -> None:
        if self.registered_execution_ready:
            return
        names = ", ".join(item.value for item in self.missing_controls)
        raise PolicyUnavailableError(
            "registered execution remains unavailable; unenforced controls: " + names
        )


class PolicyUnavailableError(RuntimeError):
    """The frozen runner policy cannot be enforced on the current adapter."""


def _exports(library_name: str, names: Iterable[bytes]) -> bool:
    if os.name != "nt":
        return False
    try:
        library = ctypes.WinDLL(library_name, use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_proc_address = kernel32.GetProcAddress
        get_proc_address.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        get_proc_address.restype = ctypes.c_void_p
        return all(bool(get_proc_address(library._handle, name)) for name in names)
    except (AttributeError, OSError):
        return False


def probe_policy_capabilities() -> PolicyCapabilityReport:
    """Report only controls Ariad's current adapter can actually enforce."""

    windows_x64 = (
        os.name == "nt"
        and platform.machine().lower() in {"amd64", "x86_64"}
        and struct.calcsize("P") == 8
    )
    job_api = windows_x64 and _exports(
        "kernel32",
        (
            b"CreateJobObjectW",
            b"CreateProcessW",
            b"SetInformationJobObject",
            b"AssignProcessToJobObject",
            b"TerminateJobObject",
            b"QueryInformationJobObject",
            b"CreateToolhelp32Snapshot",
            b"Thread32First",
            b"Thread32Next",
            b"OpenThread",
            b"ResumeThread",
            b"CreateIoCompletionPort",
            b"GetQueuedCompletionStatus",
            b"OpenProcess",
            b"WaitForSingleObject",
            b"CloseHandle",
        ),
    )
    appcontainer_api = windows_x64 and _exports(
        "userenv",
        (
            b"CreateAppContainerProfile",
            b"DeriveAppContainerSidFromAppContainerName",
            b"DeleteAppContainerProfile",
        ),
    )
    experimental_api = windows_x64 and _exports(
        "processmodel",
        (b"Experimental_CreateProcessInSandbox",),
    )

    job_mechanism = "Windows Job Object assigned while the root process is suspended"
    job_limitation = (
        None
        if job_api
        else "required 64-bit Windows Job Object and thread-resume APIs are unavailable"
    )
    controls = (
        ControlCapability(
            PolicyControl.PROCESS_TREE,
            job_api,
            job_mechanism,
            job_limitation,
        ),
        ControlCapability(
            PolicyControl.PROCESS_MEMORY,
            job_api,
            "JOB_OBJECT_LIMIT_JOB_MEMORY",
            job_limitation,
        ),
        ControlCapability(
            PolicyControl.PROCESS_COUNT,
            job_api,
            "JOB_OBJECT_LIMIT_ACTIVE_PROCESS for the root plus one allowed child",
            job_limitation,
        ),
        ControlCapability(
            PolicyControl.WALL_DEADLINE,
            job_api,
            "monotonic parent deadline followed by TerminateJobObject",
            job_limitation,
        ),
        ControlCapability(
            PolicyControl.CANCELLATION,
            job_api,
            "parent CancellationToken followed by bounded TerminateJobObject cleanup",
            job_limitation,
        ),
        ControlCapability(
            PolicyControl.BOUNDED_LOGS,
            job_api,
            "bounded binary pipe drains with job termination on overflow",
            job_limitation,
        ),
        ControlCapability(
            PolicyControl.WORKSPACE_LIMIT,
            True,
            "bounded recursive polling, immediate Job termination, and final scan; "
            "D-036 permits temporary overshoot for sealed R2/R4 targets",
        ),
        ControlCapability(
            PolicyControl.FILESYSTEM_ISOLATION,
            False,
            "Windows AppContainer",
            "the stable AppContainer filesystem launcher is not implemented",
        ),
        ControlCapability(
            PolicyControl.NETWORK_DENIAL,
            False,
            "Windows AppContainer without network capabilities",
            "the stable AppContainer network-denial launcher is not implemented",
        ),
        ControlCapability(
            PolicyControl.PYTHON_IMPORT_BOUNDARY,
            True,
            "-I -B -S sealed worker bootstrap with exact path/SHA-256 module verification",
        ),
    )
    return PolicyCapabilityReport(
        system=platform.system() or os.name,
        release=platform.release() or "unknown",
        version=platform.version() or "unknown",
        machine=platform.machine() or "unknown",
        pointer_bits=struct.calcsize("P") * 8,
        controls=controls,
        job_object_api_available=job_api,
        appcontainer_api_available=appcontainer_api,
        experimental_sandbox_api_available=experimental_api,
    )


__all__ = [
    "ControlCapability",
    "POLICY_ADAPTER_VERSION",
    "PolicyCapabilityReport",
    "PolicyControl",
    "PolicyUnavailableError",
    "probe_policy_capabilities",
]
