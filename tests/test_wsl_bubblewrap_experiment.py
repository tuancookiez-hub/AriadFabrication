from pathlib import Path
import unittest

from experiments.wsl_bubblewrap.qualify import QualificationReport, _wsl_path


class WslBubblewrapExperimentTests(unittest.TestCase):
    def test_windows_paths_translate_without_invoking_a_shell(self):
        translated = _wsl_path(Path("F:/HermesVision/OpenAIBuildWeek"))
        self.assertEqual(translated, "/mnt/f/HermesVision/OpenAIBuildWeek")

    def test_report_cannot_imply_registered_or_hardware_execution(self):
        report = QualificationReport(
            qualification_version="0.1.0",
            wsl_available=True,
            bubblewrap_available=True,
            host_mount_hidden=True,
            workspace_write_allowed=True,
            external_network_denied=True,
            exit_code=0,
        )
        self.assertEqual(report.evidence_mode, "experiment")
        self.assertFalse(report.cad_runtime_qualified)
        self.assertFalse(report.slicer_runtime_qualified)
        self.assertFalse(report.registered_execution_ready)
        self.assertFalse(report.hardware_actions)


if __name__ == "__main__":
    unittest.main()
