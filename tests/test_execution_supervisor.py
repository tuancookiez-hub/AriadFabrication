from datetime import datetime
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import tempfile
from threading import Timer
import time
import unittest
from unittest.mock import patch

from ariad_fabrication.execution import (
    CancellationToken,
    ExecutionDeadline,
    NO_HARDWARE_RUNNER_POLICY,
    PolicyControl,
    PolicyUnavailableError,
    ProcessSupervisorError,
    ProcessTerminationReason,
    SupervisedCommand,
    SupervisionLimits,
    WindowsJobProcessSupervisor,
    probe_policy_capabilities,
)


WINDOWS_X64 = os.name == "nt" and ctypes.sizeof(ctypes.c_void_p) == 8
BASE_PYTHON = Path(getattr(sys, "_base_executable", sys.executable))


def _isolated_environment() -> dict[str, str]:
    result = {
        name: os.environ[name]
        for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if name in os.environ
    }
    result["PYTHONIOENCODING"] = "utf-8"
    return result


def _process_is_running(process_id: int) -> bool:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    wait = kernel.WaitForSingleObject
    wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait.restype = wintypes.DWORD
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = open_process(0x00100000, False, process_id)  # SYNCHRONIZE
    if not handle:
        return False
    try:
        return wait(handle, 0) == 258  # WAIT_TIMEOUT
    finally:
        close(handle)


class PolicyCapabilityTests(unittest.TestCase):
    def test_capability_report_is_closed_honest_and_fail_closed(self):
        report = probe_policy_capabilities()

        self.assertFalse(report.hardware_actions)
        self.assertEqual(
            tuple(item.control for item in report.controls), tuple(PolicyControl)
        )
        self.assertFalse(report.registered_execution_ready)
        if WINDOWS_X64:
            self.assertTrue(report.job_object_api_available)
            self.assertEqual(
                report.missing_controls,
                (
                    PolicyControl.FILESYSTEM_ISOLATION,
                    PolicyControl.NETWORK_DENIAL,
                ),
            )
        else:
            self.assertFalse(report.job_object_api_available)
            self.assertIn(PolicyControl.PROCESS_TREE, report.missing_controls)
        with self.assertRaisesRegex(
            PolicyUnavailableError, "registered execution remains unavailable"
        ):
            report.require_registered_execution()

    def test_frozen_child_limit_becomes_root_plus_one_job_process(self):
        limits = SupervisionLimits.from_policy(
            NO_HARDWARE_RUNNER_POLICY,
            command_timeout_seconds=NO_HARDWARE_RUNNER_POLICY.cad_timeout_seconds,
        )

        self.assertEqual(limits.max_active_processes, 2)
        self.assertEqual(
            limits.max_job_memory_bytes, NO_HARDWARE_RUNNER_POLICY.max_memory_bytes
        )
        self.assertEqual(
            limits.max_log_stream_bytes,
            NO_HARDWARE_RUNNER_POLICY.max_log_stream_bytes,
        )


@unittest.skipUnless(WINDOWS_X64, "Windows x64 Job Object integration test")
class WindowsJobProcessSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ariad-supervisor-test-")
        self.workspace = Path(self.temporary.name).resolve()
        self.supervisor = WindowsJobProcessSupervisor()

    def tearDown(self):
        self.temporary.cleanup()

    def command(
        self,
        code: str,
        *,
        executable: Path = BASE_PYTHON,
        stdout_name: str = "stdout.log",
        stderr_name: str = "stderr.log",
    ) -> SupervisedCommand:
        return SupervisedCommand(
            executable=executable,
            arguments=("-I", "-S", "-c", code),
            cwd=self.workspace,
            environment=_isolated_environment(),
            workspace=self.workspace,
            stdout_path=self.workspace / stdout_name,
            stderr_path=self.workspace / stderr_name,
        )

    def limits(self, **overrides: object) -> SupervisionLimits:
        values: dict[str, object] = {
            "wall_seconds": 3.0,
            "cancellation_grace_seconds": 0.15,
            "max_log_stream_bytes": 64 * 1024,
            "max_workspace_bytes": 2 * 1024 * 1024,
            "max_job_memory_bytes": 256 * 1024 * 1024,
            "max_active_processes": 1,
            "workspace_poll_seconds": 0.01,
        }
        values.update(overrides)
        return SupervisionLimits(**values)  # type: ignore[arg-type]

    def test_success_streams_bounded_logs_and_reports_no_hardware(self):
        command = self.command(
            "import sys; print('bounded-out'); print('bounded-err', file=sys.stderr)"
        )

        result = self.supervisor.run(command, self.limits())

        self.assertEqual(result.reason, ProcessTerminationReason.EXITED)
        self.assertEqual(result.return_code, 0)
        self.assertFalse(result.forced_termination)
        self.assertFalse(result.hardware_actions)
        self.assertEqual(command.stdout_path.read_text().strip(), "bounded-out")
        self.assertEqual(command.stderr_path.read_text().strip(), "bounded-err")
        self.assertEqual(result.stdout_bytes, command.stdout_path.stat().st_size)
        self.assertEqual(result.stderr_bytes, command.stderr_path.stat().st_size)
        self.assertGreater(result.peak_job_memory_bytes, 0)
        self.assertGreaterEqual(result.total_processes_observed, 1)
        # Windows may account one Console Host infrastructure process even
        # under CREATE_NO_WINDOW; the Job's active-process limit still rejects
        # an attempted application child in the dedicated limit test below.
        self.assertLessEqual(result.peak_active_processes_observed, 2)
        self.assertIn(BASE_PYTHON.name, result.process_image_names)
        self.assertNotIn("cmd.exe", result.process_image_names)
        self.assertGreaterEqual(
            result.peak_workspace_bytes_observed,
            result.stdout_bytes + result.stderr_bytes,
        )
        self.assertIsNotNone(datetime.fromisoformat(result.started_at).utcoffset())
        self.assertIsNotNone(datetime.fromisoformat(result.completed_at).utcoffset())

    def test_pre_cancelled_command_never_launches(self):
        command = self.command("open('launched.txt', 'w').write('bad')")
        cancellation = CancellationToken()
        cancellation.request()

        with self.assertRaisesRegex(ProcessSupervisorError, "already requested"):
            self.supervisor.run(
                command,
                self.limits(),
                cancellation=cancellation,
            )

        self.assertFalse((self.workspace / "launched.txt").exists())
        self.assertFalse(command.stdout_path.exists())
        self.assertFalse(command.stderr_path.exists())

    def test_assignment_failure_does_not_leave_the_suspended_root_alive(self):
        captured: list[object] = []
        real_popen = __import__("subprocess").Popen

        def capture_process(*args: object, **kwargs: object):
            process = real_popen(*args, **kwargs)
            captured.append(process)
            return process

        with (
            patch(
                "ariad_fabrication.execution.windows_job.subprocess.Popen",
                side_effect=capture_process,
            ),
            patch(
                "ariad_fabrication.execution.windows_job._WindowsJob.assign_suspended",
                side_effect=ProcessSupervisorError("injected assignment failure"),
            ),
            self.assertRaisesRegex(ProcessSupervisorError, "injected assignment failure"),
        ):
            self.supervisor.run(self.command("import time; time.sleep(10)"), self.limits())

        self.assertEqual(len(captured), 1)
        process = captured[0]
        self.assertIsNotNone(process.poll())  # type: ignore[union-attr]

    def test_cancellation_token_terminates_within_its_cleanup_grace(self):
        command = self.command("import time; time.sleep(10)")
        cancellation = CancellationToken()
        request_timer = Timer(0.15, cancellation.request)
        request_timer.start()
        try:
            result = self.supervisor.run(
                command,
                self.limits(cancellation_grace_seconds=0.5),
                cancellation=cancellation,
            )
        finally:
            request_timer.join(timeout=1)

        self.assertEqual(result.reason, ProcessTerminationReason.CANCELLED)
        self.assertTrue(result.forced_termination)
        self.assertLess(result.elapsed_seconds, 2)

    def test_wall_deadline_terminates_the_job(self):
        result = self.supervisor.run(
            self.command("import time; time.sleep(10)"),
            self.limits(wall_seconds=0.15),
        )

        self.assertEqual(result.reason, ProcessTerminationReason.WALL_TIMEOUT)
        self.assertTrue(result.forced_termination)
        self.assertLess(result.elapsed_seconds, 2)

    def test_execution_wide_deadline_is_shared_and_blocks_expired_launch(self):
        result = self.supervisor.run(
            self.command("import time; time.sleep(10)"),
            self.limits(wall_seconds=3),
            execution_deadline=ExecutionDeadline.start(0.15),
        )
        self.assertEqual(result.reason, ProcessTerminationReason.WALL_TIMEOUT)
        self.assertTrue(result.forced_termination)

        expired = ExecutionDeadline.start(0.01)
        time.sleep(0.02)
        command = self.command(
            "open('late-launch.txt', 'w').write('bad')",
            stdout_name="late-stdout.log",
            stderr_name="late-stderr.log",
        )
        with self.assertRaisesRegex(ProcessSupervisorError, "expired before process launch"):
            self.supervisor.run(
                command,
                self.limits(),
                execution_deadline=expired,
            )
        self.assertFalse((self.workspace / "late-launch.txt").exists())
        self.assertFalse(command.stdout_path.exists())
        self.assertFalse(command.stderr_path.exists())

    def test_stdout_overflow_is_truncated_and_terminates_the_job(self):
        result = self.supervisor.run(
            self.command("import os\nwhile True: os.write(1, b'x' * 4096)"),
            self.limits(max_log_stream_bytes=1024),
        )

        self.assertEqual(result.reason, ProcessTerminationReason.STDOUT_LIMIT)
        self.assertEqual(result.stdout_bytes, 1024)
        self.assertEqual((self.workspace / "stdout.log").stat().st_size, 1024)
        self.assertTrue(result.forced_termination)

    def test_stderr_has_an_independent_hard_ceiling(self):
        result = self.supervisor.run(
            self.command("import os\nwhile True: os.write(2, b'e' * 4096)"),
            self.limits(max_log_stream_bytes=1536),
        )

        self.assertEqual(result.reason, ProcessTerminationReason.STDERR_LIMIT)
        self.assertEqual(result.stderr_bytes, 1536)
        self.assertEqual((self.workspace / "stderr.log").stat().st_size, 1536)
        self.assertTrue(result.forced_termination)

    def test_fast_workspace_overflow_is_caught_by_final_scan(self):
        result = self.supervisor.run(
            self.command("open('payload.bin', 'wb').write(b'x' * 32768)"),
            self.limits(max_workspace_bytes=4096),
        )

        self.assertEqual(result.reason, ProcessTerminationReason.WORKSPACE_LIMIT)
        self.assertGreater(result.peak_workspace_bytes_observed, 4096)

    def test_process_limit_notification_is_classified(self):
        code = (
            "import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, '-I', '-S', '-c', "
            "'import time; time.sleep(10)'])\n"
            "time.sleep(10)"
        )

        result = self.supervisor.run(
            self.command(code),
            self.limits(max_active_processes=1),
        )

        self.assertEqual(result.reason, ProcessTerminationReason.PROCESS_LIMIT)
        # Windows can enforce the active-process ceiling and terminate the root
        # before the parent observes it and calls TerminateJobObject.  The
        # safety property is the classified limit exit and an empty Job, not
        # which side won that race.
        self.assertLess(result.elapsed_seconds, 2)
        self.assertFalse(result.hardware_actions)

    def test_job_memory_limit_notification_is_classified(self):
        result = self.supervisor.run(
            self.command("value = bytearray(64 * 1024 * 1024); print(len(value))"),
            self.limits(max_job_memory_bytes=32 * 1024 * 1024),
        )

        self.assertEqual(result.reason, ProcessTerminationReason.MEMORY_LIMIT)
        self.assertGreater(result.peak_job_memory_bytes, 0)

    def test_natural_root_exit_cannot_leave_a_child_running(self):
        code = (
            "import subprocess, sys\n"
            "child = subprocess.Popen([sys.executable, '-I', '-S', '-c', "
            "'import time; time.sleep(10)'])\n"
            "open('child.pid', 'w').write(str(child.pid))"
        )

        result = self.supervisor.run(
            self.command(code),
            self.limits(max_active_processes=2),
        )
        child_id = int((self.workspace / "child.pid").read_text())

        self.assertEqual(result.reason, ProcessTerminationReason.EXITED)
        self.assertTrue(result.forced_termination)
        self.assertFalse(_process_is_running(child_id))

    def test_command_paths_environment_and_hardware_are_closed(self):
        outside = self.workspace.parent / "outside.log"
        occupied = self.workspace / "occupied.log"
        occupied.touch()
        valid = {
            "executable": BASE_PYTHON,
            "arguments": ("-I", "-S", "-c", "pass"),
            "cwd": self.workspace,
            "environment": _isolated_environment(),
            "workspace": self.workspace,
            "stdout_path": self.workspace / "stdout.log",
            "stderr_path": self.workspace / "stderr.log",
        }

        for change, message in (
            ({"stdout_path": outside}, "inside the workspace"),
            ({"cwd": self.workspace.parent}, "cwd must remain inside"),
            ({"stdout_path": occupied}, "must identify a new regular file"),
            ({"stdout_path": self.workspace / "CON.log"}, "unsafe Windows filename"),
            ({"stdout_path": self.workspace / "base.txt:stream"}, "unsafe Windows filename"),
            ({"hardware_actions": True}, "cannot enable hardware"),
        ):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, message):
                SupervisedCommand(**(valid | change))  # type: ignore[arg-type]

        duplicate_environment = _isolated_environment() | {"Path": "one", "PATH": "two"}
        with self.assertRaisesRegex(ValueError, "case-insensitive duplicate"):
            SupervisedCommand(
                **(valid | {"environment": duplicate_environment})  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
