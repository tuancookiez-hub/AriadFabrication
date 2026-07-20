"""Bounded Windows Job Object process supervision.

This is a process-control primitive, not the complete registered-target adapter.
It enforces process-tree ownership, aggregate committed memory, active-process
count, wall time, cancellation cleanup, and persisted log ceilings.  Workspace
polling is detection rather than a hard quota, and this module does not provide
filesystem isolation, network denial, or Python import allowlisting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import ctypes
from ctypes import wintypes
import math
import os
from pathlib import Path
import re
import stat
import subprocess
from threading import Event, Lock, Thread
import time
from types import MappingProxyType
from typing import Mapping

from .contracts import RunnerPolicy


WINDOWS_JOB_SUPERVISOR_VERSION = "0.1.0"
_READ_BYTES = 64 * 1024
_MAX_COMMAND_ARGUMENTS = 256
_MAX_ARGUMENT_CHARACTERS = 8 * 1024
_MAX_ENVIRONMENT_ENTRIES = 256
_MAX_ENVIRONMENT_CHARACTERS = 128 * 1024
_MAX_WORKSPACE_ENTRIES = 100_000
_NATURAL_EXIT_SETTLE_SECONDS = 0.25
_TREE_CLEANUP_SECONDS = 5.0
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_()]*$")
_OUTPUT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WINDOWS_RESERVED_STEMS = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}

_CREATE_SUSPENDED = 0x00000004
_CREATE_NO_WINDOW = 0x08000000
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_THREAD_SUSPEND_RESUME = 0x0002
_TH32CS_SNAPTHREAD = 0x00000004
_INVALID_DWORD = 0xFFFFFFFF
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_WAIT_FAILED = 0xFFFFFFFF
_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
_JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS = 1
_JOB_OBJECT_BASIC_PROCESS_ID_LIST_CLASS = 3
_JOB_OBJECT_ASSOCIATE_COMPLETION_PORT_INFORMATION_CLASS = 7
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_JOB_OBJECT_MSG_ACTIVE_PROCESS_LIMIT = 3
_JOB_OBJECT_MSG_NEW_PROCESS = 6
_JOB_OBJECT_MSG_PROCESS_MEMORY_LIMIT = 9
_JOB_OBJECT_MSG_JOB_MEMORY_LIMIT = 10
_COMPLETION_KEY = 0xA11D
_SUPERVISOR_TERMINATION_CODE = 0xA11D0001


class ProcessTerminationReason(str, Enum):
    EXITED = "exited"
    CANCELLED = "cancelled"
    WALL_TIMEOUT = "wall_timeout"
    PROCESS_LIMIT = "process_limit"
    MEMORY_LIMIT = "memory_limit"
    STDOUT_LIMIT = "stdout_limit"
    STDERR_LIMIT = "stderr_limit"
    WORKSPACE_LIMIT = "workspace_limit"


class ProcessSupervisorError(RuntimeError):
    """The supervisor could not establish or maintain its own control boundary."""


class Win32CallError(ProcessSupervisorError):
    def __init__(self, operation: str, error_code: int | None = None) -> None:
        code = ctypes.get_last_error() if error_code is None else error_code
        try:
            detail = ctypes.FormatError(code).strip()
        except OSError:
            detail = "unknown Windows error"
        super().__init__(f"{operation} failed with Windows error {code}: {detail}")
        self.operation = operation
        self.error_code = code


@dataclass(frozen=True)
class SupervisionLimits:
    wall_seconds: float
    cancellation_grace_seconds: float
    max_log_stream_bytes: int
    max_workspace_bytes: int
    max_job_memory_bytes: int
    max_active_processes: int
    workspace_poll_seconds: float = 0.1

    def __post_init__(self) -> None:
        for name in (
            "wall_seconds",
            "cancellation_grace_seconds",
            "workspace_poll_seconds",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                raise ValueError(f"{name} must be a finite positive number")
            object.__setattr__(self, name, float(value))
        for name in (
            "max_log_stream_bytes",
            "max_workspace_bytes",
            "max_job_memory_bytes",
            "max_active_processes",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_active_processes > 64:
            raise ValueError("max_active_processes cannot exceed 64")

    @classmethod
    def from_policy(
        cls,
        policy: RunnerPolicy,
        *,
        command_timeout_seconds: int,
    ) -> "SupervisionLimits":
        if not isinstance(policy, RunnerPolicy):
            raise TypeError("policy must be a RunnerPolicy")
        if type(command_timeout_seconds) is not int or command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be a positive integer")
        if command_timeout_seconds > policy.max_wall_seconds:
            raise ValueError("command timeout cannot exceed the total wall policy")
        return cls(
            wall_seconds=command_timeout_seconds,
            cancellation_grace_seconds=policy.cancellation_grace_seconds,
            max_log_stream_bytes=policy.max_log_stream_bytes,
            max_workspace_bytes=policy.max_workspace_bytes,
            max_job_memory_bytes=policy.max_memory_bytes,
            # A Job Object counts the supervised root in ActiveProcessLimit.
            # The frozen policy counts descendants of that root.
            max_active_processes=policy.max_child_processes + 1,
        )


@dataclass(frozen=True)
class SupervisedCommand:
    executable: Path
    arguments: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]
    workspace: Path
    stdout_path: Path
    stderr_path: Path
    hardware_actions: bool = False

    def __post_init__(self) -> None:
        if self.hardware_actions:
            raise ValueError("supervised commands cannot enable hardware actions")
        executable = _existing_regular_file(self.executable, "executable")
        workspace = _existing_directory(self.workspace, "workspace")
        cwd = _existing_directory(self.cwd, "cwd")
        if not cwd.is_relative_to(workspace):
            raise ValueError("command cwd must remain inside the workspace")
        arguments = tuple(self.arguments)
        if len(arguments) > _MAX_COMMAND_ARGUMENTS:
            raise ValueError("command has too many arguments")
        for argument in arguments:
            if (
                not isinstance(argument, str)
                or "\x00" in argument
                or len(argument) > _MAX_ARGUMENT_CHARACTERS
            ):
                raise ValueError("command argument is invalid")
        command_line = subprocess.list2cmdline([str(executable), *arguments])
        if len(command_line) >= 32_767:
            raise ValueError("Windows command line exceeds its length limit")
        environment = _frozen_environment(self.environment)
        stdout = _new_workspace_file(self.stdout_path, workspace, "stdout_path")
        stderr = _new_workspace_file(self.stderr_path, workspace, "stderr_path")
        if str(stdout).casefold() == str(stderr).casefold():
            raise ValueError("stdout_path and stderr_path must differ")
        object.__setattr__(self, "executable", executable)
        object.__setattr__(self, "arguments", arguments)
        object.__setattr__(self, "cwd", cwd)
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "stdout_path", stdout)
        object.__setattr__(self, "stderr_path", stderr)

    @property
    def argv(self) -> tuple[str, ...]:
        return (str(self.executable), *self.arguments)


@dataclass(frozen=True)
class SupervisedProcessResult:
    reason: ProcessTerminationReason
    return_code: int
    started_at: str
    completed_at: str
    elapsed_seconds: float
    stdout_bytes: int
    stderr_bytes: int
    peak_job_memory_bytes: int
    peak_workspace_bytes_observed: int
    total_processes_observed: int
    peak_active_processes_observed: int
    process_image_names: tuple[str, ...]
    forced_termination: bool
    hardware_actions: bool = False
    supervisor_version: str = WINDOWS_JOB_SUPERVISOR_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.reason, ProcessTerminationReason):
            raise ValueError("reason must be a ProcessTerminationReason")
        if type(self.return_code) is not int:
            raise ValueError("return_code must be an integer")
        if not isinstance(self.started_at, str) or not isinstance(self.completed_at, str):
            raise ValueError("result timestamps must be strings")
        if not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds is invalid")
        for name in (
            "stdout_bytes",
            "stderr_bytes",
            "peak_job_memory_bytes",
            "peak_workspace_bytes_observed",
            "total_processes_observed",
            "peak_active_processes_observed",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if type(self.forced_termination) is not bool:
            raise ValueError("forced_termination must be a boolean")
        if (
            not isinstance(self.process_image_names, tuple)
            or any(not isinstance(name, str) or not name for name in self.process_image_names)
            or tuple(sorted(set(self.process_image_names), key=str.casefold))
            != self.process_image_names
        ):
            raise ValueError("process image names must be unique and canonically ordered")
        if self.hardware_actions:
            raise ValueError("supervision cannot report hardware actions")
        if self.supervisor_version != WINDOWS_JOB_SUPERVISOR_VERSION:
            raise ValueError("unsupported supervisor version")


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    @property
    def requested(self) -> bool:
        return self._event.is_set()

    def request(self) -> None:
        self._event.set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)


@dataclass(frozen=True)
class ExecutionDeadline:
    """One process-local monotonic wall budget shared by every execution command."""

    started_monotonic: float
    expires_monotonic: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.started_monotonic, bool)
            or not isinstance(self.started_monotonic, (int, float))
            or not math.isfinite(float(self.started_monotonic))
        ):
            raise ValueError("started_monotonic must be finite")
        if (
            isinstance(self.expires_monotonic, bool)
            or not isinstance(self.expires_monotonic, (int, float))
            or not math.isfinite(float(self.expires_monotonic))
            or float(self.expires_monotonic) <= float(self.started_monotonic)
        ):
            raise ValueError("expires_monotonic must follow started_monotonic")
        object.__setattr__(self, "started_monotonic", float(self.started_monotonic))
        object.__setattr__(self, "expires_monotonic", float(self.expires_monotonic))

    @classmethod
    def start(cls, wall_seconds: float) -> "ExecutionDeadline":
        if (
            isinstance(wall_seconds, bool)
            or not isinstance(wall_seconds, (int, float))
            or not math.isfinite(float(wall_seconds))
            or float(wall_seconds) <= 0
        ):
            raise ValueError("wall_seconds must be a finite positive number")
        started = time.monotonic()
        return cls(started, started + float(wall_seconds))

    def remaining_seconds(self) -> float:
        return max(0.0, self.expires_monotonic - time.monotonic())


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong),
        ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _JOBOBJECT_ASSOCIATE_COMPLETION_PORT(ctypes.Structure):
    _fields_ = [
        ("CompletionKey", ctypes.c_void_p),
        ("CompletionPort", wintypes.HANDLE),
    ]


class _JOBOBJECT_BASIC_PROCESS_ID_LIST(ctypes.Structure):
    _fields_ = [
        ("NumberOfAssignedProcesses", wintypes.DWORD),
        ("NumberOfProcessIdsInList", wintypes.DWORD),
        ("ProcessIdList", ctypes.c_size_t * 64),
    ]


class _THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


class _Kernel32:
    def __init__(self) -> None:
        if os.name != "nt":
            raise ProcessSupervisorError("Windows Job Object supervision requires Windows")
        self.library = ctypes.WinDLL("kernel32", use_last_error=True)
        self.create_job = self.library.CreateJobObjectW
        self.create_job.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.create_job.restype = wintypes.HANDLE
        self.set_job = self.library.SetInformationJobObject
        self.set_job.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.set_job.restype = wintypes.BOOL
        self.query_job = self.library.QueryInformationJobObject
        self.query_job.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.query_job.restype = wintypes.BOOL
        self.assign_job = self.library.AssignProcessToJobObject
        self.assign_job.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.assign_job.restype = wintypes.BOOL
        self.terminate_job = self.library.TerminateJobObject
        self.terminate_job.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.terminate_job.restype = wintypes.BOOL
        self.open_process = self.library.OpenProcess
        self.open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.open_process.restype = wintypes.HANDLE
        self.query_process_image = self.library.QueryFullProcessImageNameW
        self.query_process_image.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.query_process_image.restype = wintypes.BOOL
        self.snapshot = self.library.CreateToolhelp32Snapshot
        self.snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.snapshot.restype = wintypes.HANDLE
        self.thread_first = self.library.Thread32First
        self.thread_first.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
        self.thread_first.restype = wintypes.BOOL
        self.thread_next = self.library.Thread32Next
        self.thread_next.argtypes = [wintypes.HANDLE, ctypes.POINTER(_THREADENTRY32)]
        self.thread_next.restype = wintypes.BOOL
        self.open_thread = self.library.OpenThread
        self.open_thread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.open_thread.restype = wintypes.HANDLE
        self.resume_thread = self.library.ResumeThread
        self.resume_thread.argtypes = [wintypes.HANDLE]
        self.resume_thread.restype = wintypes.DWORD
        self.create_completion_port = self.library.CreateIoCompletionPort
        self.create_completion_port.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.c_size_t,
            wintypes.DWORD,
        ]
        self.create_completion_port.restype = wintypes.HANDLE
        self.get_completion = self.library.GetQueuedCompletionStatus
        self.get_completion.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.DWORD,
        ]
        self.get_completion.restype = wintypes.BOOL
        self.wait_single = self.library.WaitForSingleObject
        self.wait_single.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.wait_single.restype = wintypes.DWORD
        self.close_handle = self.library.CloseHandle
        self.close_handle.argtypes = [wintypes.HANDLE]
        self.close_handle.restype = wintypes.BOOL


class _Handle:
    def __init__(self, kernel: _Kernel32, value: int, operation: str) -> None:
        if not value or value == _INVALID_HANDLE_VALUE:
            raise Win32CallError(operation)
        self.kernel = kernel
        self.value = value

    def close(self) -> None:
        if self.value:
            value, self.value = self.value, 0
            if not self.kernel.close_handle(value):
                raise Win32CallError("CloseHandle")

    def __enter__(self) -> "_Handle":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class _WindowsJob:
    def __init__(self, kernel: _Kernel32, limits: SupervisionLimits) -> None:
        self.kernel = kernel
        self.process_assigned = False
        self._tracked_processes: dict[int, _Handle] = {}
        self._observed_limit_reason: ProcessTerminationReason | None = None
        self.handle = _Handle(kernel, kernel.create_job(None, None), "CreateJobObjectW")
        try:
            self.completion_port = _Handle(
                kernel,
                kernel.create_completion_port(
                    _INVALID_HANDLE_VALUE,
                    None,
                    0,
                    1,
                ),
                "CreateIoCompletionPort",
            )
        except Exception:
            self.handle.close()
            raise
        information = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        information.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | _JOB_OBJECT_LIMIT_JOB_MEMORY
            | _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        information.BasicLimitInformation.ActiveProcessLimit = limits.max_active_processes
        information.JobMemoryLimit = limits.max_job_memory_bytes
        if not kernel.set_job(
            self.handle.value,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            error = ctypes.get_last_error()
            try:
                self.completion_port.close()
            finally:
                self.handle.close()
            raise Win32CallError("SetInformationJobObject", error)
        association = _JOBOBJECT_ASSOCIATE_COMPLETION_PORT(
            CompletionKey=_COMPLETION_KEY,
            CompletionPort=self.completion_port.value,
        )
        if not kernel.set_job(
            self.handle.value,
            _JOB_OBJECT_ASSOCIATE_COMPLETION_PORT_INFORMATION_CLASS,
            ctypes.byref(association),
            ctypes.sizeof(association),
        ):
            error = ctypes.get_last_error()
            try:
                self.completion_port.close()
            finally:
                self.handle.close()
            raise Win32CallError(
                "SetInformationJobObject completion port association", error
            )

    def assign_suspended(self, process_id: int) -> None:
        rights = (
            _PROCESS_SET_QUOTA
            | _PROCESS_TERMINATE
            | _PROCESS_QUERY_LIMITED_INFORMATION
            | _SYNCHRONIZE
        )
        with _Handle(
            self.kernel,
            self.kernel.open_process(rights, False, process_id),
            "OpenProcess",
        ) as process:
            if not self.kernel.assign_job(self.handle.value, process.value):
                raise Win32CallError("AssignProcessToJobObject")
            self.process_assigned = True
        self._track_process_id(process_id)
        self._resume_initial_thread(process_id)

    def _resume_initial_thread(self, process_id: int) -> None:
        with _Handle(
            self.kernel,
            self.kernel.snapshot(_TH32CS_SNAPTHREAD, 0),
            "CreateToolhelp32Snapshot",
        ) as snapshot:
            entry = _THREADENTRY32()
            entry.dwSize = ctypes.sizeof(entry)
            thread_ids: list[int] = []
            ctypes.set_last_error(0)
            found = self.kernel.thread_first(snapshot.value, ctypes.byref(entry))
            while found:
                if entry.th32OwnerProcessID == process_id:
                    thread_ids.append(int(entry.th32ThreadID))
                entry.dwSize = ctypes.sizeof(entry)
                ctypes.set_last_error(0)
                found = self.kernel.thread_next(snapshot.value, ctypes.byref(entry))
            final_error = ctypes.get_last_error()
            if final_error not in {0, 18}:  # ERROR_NO_MORE_FILES
                raise Win32CallError("Thread32Next", final_error)
        if len(thread_ids) != 1:
            raise ProcessSupervisorError(
                "suspended process did not expose exactly one initial thread"
            )
        with _Handle(
            self.kernel,
            self.kernel.open_thread(_THREAD_SUSPEND_RESUME, False, thread_ids[0]),
            "OpenThread",
        ) as thread:
            previous = int(self.kernel.resume_thread(thread.value))
            if previous == _INVALID_DWORD:
                raise Win32CallError("ResumeThread")
            if previous != 1:
                raise ProcessSupervisorError(
                    "initial process thread had an unexpected suspend count"
                )

    def terminate(self) -> None:
        self.poll_limit_reason()
        self._track_active_processes()
        if self.handle.value and not self.kernel.terminate_job(
            self.handle.value, _SUPERVISOR_TERMINATION_CODE
        ):
            raise Win32CallError("TerminateJobObject")

    def peak_memory(self) -> int:
        information = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        returned = wintypes.DWORD()
        if not self.kernel.query_job(
            self.handle.value,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(information),
            ctypes.sizeof(information),
            ctypes.byref(returned),
        ):
            raise Win32CallError("QueryInformationJobObject")
        return int(information.PeakJobMemoryUsed)

    def active_processes(self) -> int:
        return self.accounting()[1]

    def accounting(self) -> tuple[int, int]:
        information = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        returned = wintypes.DWORD()
        if not self.kernel.query_job(
            self.handle.value,
            _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
            ctypes.byref(information),
            ctypes.sizeof(information),
            ctypes.byref(returned),
        ):
            raise Win32CallError("QueryInformationJobObject")
        return int(information.TotalProcesses), int(information.ActiveProcesses)

    def process_ids(self) -> tuple[int, ...]:
        information = _JOBOBJECT_BASIC_PROCESS_ID_LIST()
        returned = wintypes.DWORD()
        if not self.kernel.query_job(
            self.handle.value,
            _JOB_OBJECT_BASIC_PROCESS_ID_LIST_CLASS,
            ctypes.byref(information),
            ctypes.sizeof(information),
            ctypes.byref(returned),
        ):
            raise Win32CallError("QueryInformationJobObject process list")
        assigned = int(information.NumberOfAssignedProcesses)
        included = int(information.NumberOfProcessIdsInList)
        if assigned > len(information.ProcessIdList) or included != assigned:
            raise ProcessSupervisorError(
                "job process list exceeded the frozen active-process ceiling"
            )
        return tuple(int(information.ProcessIdList[index]) for index in range(included))

    def process_image_names(self) -> tuple[str, ...]:
        names: set[str] = set()
        for process_id in self.process_ids():
            handle = self.kernel.open_process(0x1000, False, process_id)
            if not handle:
                continue
            with _Handle(self.kernel, handle, "OpenProcess image query") as process:
                capacity = wintypes.DWORD(32_768)
                buffer = ctypes.create_unicode_buffer(capacity.value)
                if self.kernel.query_process_image(
                    process.value, 0, buffer, ctypes.byref(capacity)
                ):
                    names.add(Path(buffer.value).name)
        return tuple(sorted(names, key=str.casefold))

    def _track_process_id(self, process_id: int) -> None:
        if process_id <= 0 or process_id in self._tracked_processes:
            return
        ctypes.set_last_error(0)
        handle = self.kernel.open_process(_SYNCHRONIZE, False, process_id)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: process is already gone.
                return
            raise Win32CallError("OpenProcess for cleanup tracking", error)
        self._tracked_processes[process_id] = _Handle(
            self.kernel, handle, "OpenProcess for cleanup tracking"
        )

    def _track_active_processes(self) -> None:
        for process_id in self.process_ids():
            self._track_process_id(process_id)

    def _wait_tracked_processes(self, deadline: float) -> bool:
        for process_id, handle in tuple(self._tracked_processes.items()):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            milliseconds = max(1, math.ceil(remaining * 1000))
            result = int(self.kernel.wait_single(handle.value, milliseconds))
            if result == _WAIT_TIMEOUT:
                return False
            if result == _WAIT_FAILED:
                raise Win32CallError("WaitForSingleObject")
            if result != _WAIT_OBJECT_0:
                raise ProcessSupervisorError(
                    f"unexpected process wait result {result} for process {process_id}"
                )
            handle.close()
            del self._tracked_processes[process_id]
        return True

    def wait_empty(self, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while True:
            self.poll_limit_reason()
            self._track_active_processes()
            if self.active_processes() == 0:
                return self._wait_tracked_processes(deadline)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.01, remaining))

    def poll_limit_reason(self) -> ProcessTerminationReason | None:
        while True:
            message = wintypes.DWORD()
            key = ctypes.c_size_t()
            process_id = ctypes.c_void_p()
            ctypes.set_last_error(0)
            received = self.kernel.get_completion(
                self.completion_port.value,
                ctypes.byref(message),
                ctypes.byref(key),
                ctypes.byref(process_id),
                0,
            )
            if not received:
                error = ctypes.get_last_error()
                if error == _WAIT_TIMEOUT:
                    return self._observed_limit_reason
                raise Win32CallError("GetQueuedCompletionStatus", error)
            if key.value != _COMPLETION_KEY:
                raise ProcessSupervisorError(
                    "job completion port returned an unexpected completion key"
                )
            if message.value == _JOB_OBJECT_MSG_NEW_PROCESS:
                self._track_process_id(int(process_id.value or 0))
            if message.value == _JOB_OBJECT_MSG_ACTIVE_PROCESS_LIMIT:
                self._observed_limit_reason = (
                    self._observed_limit_reason or ProcessTerminationReason.PROCESS_LIMIT
                )
            elif message.value in {
                _JOB_OBJECT_MSG_PROCESS_MEMORY_LIMIT,
                _JOB_OBJECT_MSG_JOB_MEMORY_LIMIT,
            }:
                self._observed_limit_reason = (
                    self._observed_limit_reason or ProcessTerminationReason.MEMORY_LIMIT
                )

    def close(self) -> None:
        first_error: ProcessSupervisorError | None = None

        def remember(error: ProcessSupervisorError) -> None:
            nonlocal first_error
            first_error = first_error or error

        try:
            self.handle.close()
        except ProcessSupervisorError as exc:
            remember(exc)
        deadline = time.monotonic() + _TREE_CLEANUP_SECONDS
        for process_id, handle in tuple(self._tracked_processes.items()):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                remember(
                    ProcessSupervisorError(
                        "timed out closing a tracked supervised process handle"
                    )
                )
            else:
                result = int(
                    self.kernel.wait_single(
                        handle.value, max(1, math.ceil(remaining * 1000))
                    )
                )
                if result == _WAIT_TIMEOUT:
                    remember(
                        ProcessSupervisorError(
                            f"process {process_id} remained active while closing its job"
                        )
                    )
                elif result == _WAIT_FAILED:
                    remember(Win32CallError("WaitForSingleObject"))
                elif result != _WAIT_OBJECT_0:
                    remember(
                        ProcessSupervisorError(
                            f"unexpected cleanup wait result {result} for process {process_id}"
                        )
                    )
            try:
                handle.close()
            except ProcessSupervisorError as exc:
                remember(exc)
        self._tracked_processes.clear()
        try:
            self.completion_port.close()
        except ProcessSupervisorError as exc:
            remember(exc)
        if first_error is not None:
            raise first_error


@dataclass
class _StreamState:
    bytes_written: int = 0
    error: BaseException | None = None


@dataclass
class _StopState:
    reason: ProcessTerminationReason | None = None
    error: BaseException | None = None
    lock: Lock = field(default_factory=Lock)

    def request(
        self,
        reason: ProcessTerminationReason | None,
        error: BaseException | None = None,
    ) -> None:
        with self.lock:
            if self.reason is None and self.error is None:
                self.reason = reason
                self.error = error

    def snapshot(self) -> tuple[ProcessTerminationReason | None, BaseException | None]:
        with self.lock:
            return self.reason, self.error


class WindowsJobProcessSupervisor:
    """Run one internal command under a race-free Windows Job Object."""

    def __init__(self) -> None:
        self._kernel = _Kernel32()

    def run(
        self,
        command: SupervisedCommand,
        limits: SupervisionLimits,
        *,
        cancellation: CancellationToken | None = None,
        execution_deadline: ExecutionDeadline | None = None,
    ) -> SupervisedProcessResult:
        if not isinstance(command, SupervisedCommand):
            raise TypeError("command must be a SupervisedCommand")
        if not isinstance(limits, SupervisionLimits):
            raise TypeError("limits must be SupervisionLimits")
        if cancellation is not None and not isinstance(cancellation, CancellationToken):
            raise TypeError("cancellation must be a CancellationToken")
        if execution_deadline is not None and not isinstance(
            execution_deadline, ExecutionDeadline
        ):
            raise TypeError("execution_deadline must be an ExecutionDeadline")
        if cancellation is not None and cancellation.requested:
            raise ProcessSupervisorError(
                "a command cannot launch after cancellation was already requested"
            )

        started_wall = datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        deadline = started + limits.wall_seconds
        if execution_deadline is not None:
            deadline = min(deadline, execution_deadline.expires_monotonic)
        if deadline <= started:
            raise ProcessSupervisorError(
                "the execution-wide wall deadline expired before process launch"
            )
        next_workspace_poll = started
        workspace_peak = 0
        forced = False
        cancellation_observed = False
        stop = _StopState()
        stdout_state = _StreamState()
        stderr_state = _StreamState()
        job = _WindowsJob(self._kernel, limits)
        process: subprocess.Popen[bytes] | None = None
        readers: list[Thread] = []
        peak_memory = 0
        peak_active_processes = 0
        total_processes = 0
        process_image_names: set[str] = set()
        reason = ProcessTerminationReason.EXITED
        try:
            process = subprocess.Popen(
                command.argv,
                executable=str(command.executable),
                cwd=str(command.cwd),
                env=dict(command.environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                shell=False,
                creationflags=_CREATE_SUSPENDED | _CREATE_NO_WINDOW,
            )
            if process.stdout is None or process.stderr is None:  # pragma: no cover
                raise ProcessSupervisorError("subprocess pipes were not created")
            readers = [
                Thread(
                    target=_drain_stream,
                    args=(
                        process.stdout,
                        command.stdout_path,
                        limits.max_log_stream_bytes,
                        stdout_state,
                        stop,
                        ProcessTerminationReason.STDOUT_LIMIT,
                    ),
                    name="ariad-stdout-drain",
                    daemon=True,
                ),
                Thread(
                    target=_drain_stream,
                    args=(
                        process.stderr,
                        command.stderr_path,
                        limits.max_log_stream_bytes,
                        stderr_state,
                        stop,
                        ProcessTerminationReason.STDERR_LIMIT,
                    ),
                    name="ariad-stderr-drain",
                    daemon=True,
                ),
            ]
            for reader in readers:
                reader.start()
            job.assign_suspended(process.pid)

            while process.poll() is None:
                now = time.monotonic()
                observed_total, observed_active = job.accounting()
                total_processes = max(total_processes, observed_total)
                peak_active_processes = max(peak_active_processes, observed_active)
                process_image_names.update(job.process_image_names())
                limit_reason = job.poll_limit_reason()
                if limit_reason is not None:
                    reason = limit_reason
                    job.terminate()
                    forced = True
                    break
                stop_reason, stop_error = stop.snapshot()
                if stop_error is not None:
                    job.terminate()
                    forced = True
                    break
                if stop_reason is not None:
                    reason = stop_reason
                    job.terminate()
                    forced = True
                    break
                if cancellation is not None and cancellation.requested:
                    cancellation_observed = True
                    reason = ProcessTerminationReason.CANCELLED
                    job.terminate()
                    forced = True
                    break
                if now >= deadline:
                    reason = ProcessTerminationReason.WALL_TIMEOUT
                    job.terminate()
                    forced = True
                    break
                if now >= next_workspace_poll:
                    observed, exceeded = _workspace_size(
                        command.workspace, limits.max_workspace_bytes
                    )
                    workspace_peak = max(workspace_peak, observed)
                    if exceeded:
                        reason = ProcessTerminationReason.WORKSPACE_LIMIT
                        job.terminate()
                        forced = True
                        break
                    next_workspace_poll = now + limits.workspace_poll_seconds
                if cancellation is None:
                    time.sleep(min(0.02, max(0.001, deadline - now)))
                else:
                    cancellation.wait(min(0.02, max(0.001, deadline - now)))

            root_exit_observed_at = (
                time.monotonic() if process.poll() is not None else None
            )
            termination_wait_seconds = (
                limits.cancellation_grace_seconds
                if reason is ProcessTerminationReason.CANCELLED
                else _TREE_CLEANUP_SECONDS
            )
            if process.poll() is None:
                process.wait(timeout=termination_wait_seconds)
            elif not job.wait_empty(_NATURAL_EXIT_SETTLE_SECONDS):
                # A root process must not leave descendants alive after it exits.
                job.terminate()
                forced = True
            process.wait(timeout=termination_wait_seconds)
            if not job.wait_empty(termination_wait_seconds):
                raise ProcessSupervisorError(
                    "the supervised Windows Job did not reach zero active processes"
                )
            for reader in readers:
                reader.join(timeout=5)
            if any(reader.is_alive() for reader in readers):
                raise ProcessSupervisorError("bounded log drain did not terminate")
            limit_reason = job.poll_limit_reason()
            stop_reason, stop_error = stop.snapshot()
            stream_error = stdout_state.error or stderr_state.error or stop_error
            if stream_error is not None:
                raise ProcessSupervisorError(
                    "bounded log persistence failed"
                ) from stream_error
            if reason is ProcessTerminationReason.EXITED and limit_reason is not None:
                reason = limit_reason
            if reason is ProcessTerminationReason.EXITED and stop_reason is not None:
                reason = stop_reason
            observed, workspace_exceeded = _workspace_size(
                command.workspace, limits.max_workspace_bytes
            )
            workspace_peak = max(workspace_peak, observed)
            if reason is ProcessTerminationReason.EXITED and workspace_exceeded:
                reason = ProcessTerminationReason.WORKSPACE_LIMIT
            if (
                reason is ProcessTerminationReason.EXITED
                and root_exit_observed_at is not None
                and root_exit_observed_at >= deadline
            ):
                reason = ProcessTerminationReason.WALL_TIMEOUT
            if reason is ProcessTerminationReason.EXITED and cancellation_observed:
                reason = ProcessTerminationReason.CANCELLED
            peak_memory = job.peak_memory()
            observed_total, observed_active = job.accounting()
            total_processes = max(total_processes, observed_total)
            peak_active_processes = max(peak_active_processes, observed_active)
            process_image_names.update(job.process_image_names())
        except Exception as exc:
            if process is not None:
                try:
                    if job.process_assigned:
                        job.terminate()
                    elif process.poll() is None:
                        process.kill()
                except (OSError, ProcessSupervisorError):
                    if process.poll() is None:
                        process.kill()
                if process.poll() is None:
                    try:
                        process.wait(timeout=_TREE_CLEANUP_SECONDS)
                    except subprocess.TimeoutExpired as cleanup_error:
                        process.kill()
                        try:
                            process.wait(timeout=_TREE_CLEANUP_SECONDS)
                        except subprocess.TimeoutExpired as final_cleanup_error:
                            raise ProcessSupervisorError(
                                "Windows did not terminate the supervised process tree"
                            ) from final_cleanup_error
                        raise ProcessSupervisorError(
                            "Windows Job termination required root-process fallback"
                        ) from cleanup_error
                if job.process_assigned and not job.wait_empty(_TREE_CLEANUP_SECONDS):
                    raise ProcessSupervisorError(
                        "Windows did not terminate every supervised descendant"
                    ) from exc
            if isinstance(exc, subprocess.TimeoutExpired):
                raise ProcessSupervisorError(
                    "Windows did not terminate the supervised process tree in time"
                ) from exc
            raise
        finally:
            for reader in readers:
                reader.join(timeout=_TREE_CLEANUP_SECONDS)
            job.close()

        if any(reader.is_alive() for reader in readers):
            raise ProcessSupervisorError("bounded log drain did not terminate")
        if process is None or process.returncode is None:  # pragma: no cover
            raise ProcessSupervisorError("supervised process has no terminal return code")
        completed = time.monotonic()
        return SupervisedProcessResult(
            reason=reason,
            return_code=int(process.returncode),
            started_at=started_wall,
            completed_at=datetime.now(timezone.utc).isoformat(),
            elapsed_seconds=completed - started,
            stdout_bytes=stdout_state.bytes_written,
            stderr_bytes=stderr_state.bytes_written,
            peak_job_memory_bytes=peak_memory,
            peak_workspace_bytes_observed=workspace_peak,
            total_processes_observed=total_processes,
            peak_active_processes_observed=peak_active_processes,
            process_image_names=tuple(sorted(process_image_names, key=str.casefold)),
            forced_termination=forced,
        )


def _existing_regular_file(value: Path, name: str) -> Path:
    path = Path(value)
    try:
        if _is_link_or_reparse(path):
            raise ValueError(f"{name} cannot be a link or reparse point")
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{name} is unavailable") from exc
    if not resolved.is_file():
        raise ValueError(f"{name} must be a regular file")
    return resolved


def _existing_directory(value: Path, name: str) -> Path:
    path = Path(value)
    try:
        if _is_link_or_reparse(path):
            raise ValueError(f"{name} cannot be a link or reparse point")
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{name} is unavailable") from exc
    if not resolved.is_dir():
        raise ValueError(f"{name} must be a directory")
    return resolved


def _new_workspace_file(value: Path, workspace: Path, name: str) -> Path:
    path = Path(value).absolute()
    try:
        parent = _existing_directory(path.parent, f"{name} parent")
        resolved = parent / path.name
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(f"{name} must remain inside the workspace") from exc
    filename = path.name
    stem = filename.split(".", 1)[0].casefold()
    if (
        not _OUTPUT_NAME.fullmatch(filename)
        or filename.endswith((".", " "))
        or stem in _WINDOWS_RESERVED_STEMS
    ):
        raise ValueError(f"{name} has an unsafe Windows filename")
    if resolved.exists():
        raise ValueError(f"{name} must identify a new regular file")
    return resolved


def _frozen_environment(value: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("environment must be a mapping")
    if len(value) > _MAX_ENVIRONMENT_ENTRIES:
        raise ValueError("environment has too many entries")
    result: dict[str, str] = {}
    folded: set[str] = set()
    characters = 0
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or not _ENVIRONMENT_NAME.fullmatch(key)
            or "\x00" in key
        ):
            raise ValueError("environment name is invalid")
        if not isinstance(item, str) or "\x00" in item:
            raise ValueError("environment value is invalid")
        lowered = key.casefold()
        if lowered in folded:
            raise ValueError("environment contains a case-insensitive duplicate")
        folded.add(lowered)
        characters += len(key) + len(item) + 2
        if characters > _MAX_ENVIRONMENT_CHARACTERS:
            raise ValueError("environment exceeds its character limit")
        result[key] = item
    return MappingProxyType(result)


def _is_link_or_reparse(path: Path) -> bool:
    value = path.lstat()
    attributes = getattr(value, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(value.st_mode) or bool(attributes & reparse)


def _workspace_size(root: Path, maximum_bytes: int) -> tuple[int, bool]:
    stack = [root]
    total = 0
    entries = 0
    while stack:
        directory = stack.pop()
        try:
            children = os.scandir(directory)
        except OSError as exc:
            raise ProcessSupervisorError(
                f"workspace cannot be enumerated: {directory}"
            ) from exc
        with children:
            for child in children:
                entries += 1
                if entries > _MAX_WORKSPACE_ENTRIES:
                    return total, True
                try:
                    value = child.stat(follow_symlinks=False)
                except OSError as exc:
                    raise ProcessSupervisorError(
                        f"workspace entry cannot be inspected: {child.path}"
                    ) from exc
                attributes = getattr(value, "st_file_attributes", 0)
                reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                if child.is_symlink() or attributes & reparse:
                    raise ProcessSupervisorError(
                        f"workspace contains a link or reparse point: {child.path}"
                    )
                if stat.S_ISDIR(value.st_mode):
                    stack.append(Path(child.path))
                elif stat.S_ISREG(value.st_mode):
                    total += int(value.st_size)
                    if total > maximum_bytes:
                        return total, True
                else:
                    raise ProcessSupervisorError(
                        f"workspace contains an unsupported entry: {child.path}"
                    )
    return total, False


def _drain_stream(
    pipe: object,
    path: Path,
    maximum_bytes: int,
    state: _StreamState,
    stop: _StopState,
    overflow_reason: ProcessTerminationReason,
) -> None:
    try:
        with path.open("xb", buffering=0) as output:
            while True:
                block = pipe.read(_READ_BYTES)  # type: ignore[attr-defined]
                if not block:
                    break
                remaining = max(0, maximum_bytes - state.bytes_written)
                if remaining > 0:
                    accepted = block[:remaining]
                    output.write(accepted)
                    state.bytes_written += len(accepted)
                if len(block) > remaining:
                    stop.request(overflow_reason)
    except BaseException as exc:
        state.error = exc
        stop.request(None, exc)
    finally:
        try:
            pipe.close()  # type: ignore[attr-defined]
        except Exception:
            pass


__all__ = [
    "CancellationToken",
    "ExecutionDeadline",
    "ProcessSupervisorError",
    "ProcessTerminationReason",
    "SupervisedCommand",
    "SupervisedProcessResult",
    "SupervisionLimits",
    "WINDOWS_JOB_SUPERVISOR_VERSION",
    "Win32CallError",
    "WindowsJobProcessSupervisor",
]
