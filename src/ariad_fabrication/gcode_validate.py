"""Pre-flight checks for generated G-code."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .models import PartSpec
from .slicer import GCodeArtifact, SliceConfig


@dataclass(frozen=True)
class GCodeValidationReport:
    passed: bool
    bounds_mm: dict[str, float]
    temperatures_c: dict[str, float]
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "bounds_mm": dict(self.bounds_mm),
            "temperatures_c": dict(self.temperatures_c),
            "errors": list(self.errors),
        }


_COORDINATE = re.compile(r"\b([XYZ])(-?\d+(?:\.\d+)?)\b", re.IGNORECASE)
_TEMP = re.compile(r"^M(?:104|109)\s+S(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_BED_TEMP = re.compile(r"^M(?:140|190)\s+S(-?\d+(?:\.\d+)?)", re.IGNORECASE)


def validate_gcode(gcode: GCodeArtifact, spec: PartSpec, config: SliceConfig | None = None) -> GCodeValidationReport:
    config = config or SliceConfig()
    coordinates: dict[str, list[float]] = {axis: [] for axis in "XYZ"}
    nozzle_temps: list[float] = []
    bed_temps: list[float] = []
    errors: list[str] = []
    for raw_line in gcode.content.splitlines():
        line = raw_line.split(";", 1)[0].strip()
        for axis, value in _COORDINATE.findall(line):
            coordinates[axis.upper()].append(float(value))
        if match := _TEMP.match(line):
            nozzle_temps.append(float(match.group(1)))
        if match := _BED_TEMP.match(line):
            bed_temps.append(float(match.group(1)))

    bounds = {
        axis: round(max(values) if values else 0.0, 3)
        for axis, values in coordinates.items()
    }
    minimums = {
        axis: round(min(values) if values else 0.0, 3)
        for axis, values in coordinates.items()
    }
    limits = {"X": config.bed_x_mm, "Y": config.bed_y_mm, "Z": config.build_height_mm}
    for axis, values in coordinates.items():
        if values and (min(values) < 0 or max(values) > limits[axis]):
            errors.append(f"{axis} moves outside the configured print volume")
    if nozzle_temps and max(nozzle_temps) > 260:
        errors.append("nozzle temperature exceeds the demo safety limit")
    if bed_temps and max(bed_temps) > 120:
        errors.append("bed temperature exceeds the demo safety limit")
    if not nozzle_temps or not bed_temps:
        errors.append("G-code is missing heater commands")
    return GCodeValidationReport(
        passed=not errors,
        bounds_mm={**bounds, "min_x": minimums["X"], "min_y": minimums["Y"], "min_z": minimums["Z"]},
        temperatures_c={"nozzle_max": max(nozzle_temps, default=0.0), "bed_max": max(bed_temps, default=0.0)},
        errors=tuple(errors),
    )
