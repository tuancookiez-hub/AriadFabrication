"""Moonraker-compatible printer boundary plus a deterministic simulator."""

from __future__ import annotations

from dataclasses import dataclass

from .models import PartSpec
from .slicer import GCodeArtifact


@dataclass(frozen=True)
class PrinterSnapshot:
    state: str
    progress_pct: float
    message: str
    fault: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "progress_pct": self.progress_pct,
            "message": self.message,
            "fault": self.fault,
        }


class SimulatedMoonraker:
    """Fake printer that exercises dispatch, polling, and recovery logic."""

    def __init__(self, *, inject_fault: bool = True) -> None:
        self.inject_fault = inject_fault
        self.uploaded_filename: str | None = None
        self.poll_count = 0
        self.recovered = False
        self.started = False

    def preflight(self, spec: PartSpec) -> PrinterSnapshot:
        return PrinterSnapshot("ready", 0.0, f"Bed mesh calibrated; {spec.material} profile ready")

    def upload(self, gcode: GCodeArtifact) -> PrinterSnapshot:
        self.uploaded_filename = gcode.filename
        return PrinterSnapshot("ready", 0.0, f"Uploaded {gcode.filename}")

    def start(self) -> PrinterSnapshot:
        if not self.uploaded_filename:
            raise RuntimeError("cannot start before uploading G-code")
        self.started = True
        return PrinterSnapshot("printing", 0.0, "Print started")

    def poll(self) -> PrinterSnapshot:
        if not self.started:
            raise RuntimeError("cannot monitor before starting the print")
        self.poll_count += 1
        if self.inject_fault and not self.recovered and self.poll_count == 2:
            return PrinterSnapshot("error", 25.0, "Filament sensor reported a runout", "filament_runout")
        if self.recovered and self.poll_count == 3:
            return PrinterSnapshot("printing", 50.0, "Print resumed after recovery")
        if self.poll_count >= 5:
            return PrinterSnapshot("complete", 100.0, "Simulated print completed")
        return PrinterSnapshot("printing", float(self.poll_count * 25), "Temperatures stable")

    def recover(self, fault: str) -> PrinterSnapshot:
        if fault != "filament_runout":
            raise RuntimeError(f"unsupported printer fault: {fault}")
        self.recovered = True
        return PrinterSnapshot(
            "printing",
            25.0,
            "Simulated recovery acknowledged; simulated print resumed",
        )
