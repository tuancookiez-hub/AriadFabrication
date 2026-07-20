"""A deterministic PrusaSlicer-shaped adapter for offline demonstrations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .model_gen import MeshArtifact
from .models import PartSpec


@dataclass(frozen=True)
class SliceConfig:
    printer_name: str = "Demo Klipper Printer"
    bed_x_mm: float = 220.0
    bed_y_mm: float = 220.0
    build_height_mm: float = 250.0
    layer_height_mm: float = 0.2
    nozzle_temp_c: int = 210
    bed_temp_c: int = 60


@dataclass(frozen=True)
class GCodeArtifact:
    slicer: str
    filename: str
    content: str
    layer_count: int
    estimated_seconds: int

    def write(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / self.filename
        path.write_text(self.content, encoding="utf-8")
        return path


class DemoSlicer:
    """Generate simple perimeter G-code with a real slicer-like contract."""

    def __init__(self, config: SliceConfig | None = None) -> None:
        self.config = config or SliceConfig()

    def slice(self, mesh: MeshArtifact, spec: PartSpec) -> GCodeArtifact:
        length = mesh.dimensions_mm["length"]
        width = mesh.dimensions_mm["width"]
        height = mesh.dimensions_mm["height"]
        layers = max(1, int(round(height / self.config.layer_height_mm)))
        lines = [
            "; Ariad offline slicer output",
            f"; printer={self.config.printer_name}",
            f"; material={spec.material}",
            f"; layer_height={self.config.layer_height_mm}",
            f"M104 S{self.config.nozzle_temp_c}",
            f"M140 S{self.config.bed_temp_c}",
            "G28",
            f"M109 S{self.config.nozzle_temp_c}",
            f"M190 S{self.config.bed_temp_c}",
            "G90",
            "M82",
        ]
        extrusion = 0.0
        for layer in range(layers):
            z = min((layer + 1) * self.config.layer_height_mm, height)
            lines.append(f"G1 Z{z:.3f} F900")
            lines.append("G1 X0.000 Y0.000 F6000")
            for x, y in ((length, 0.0), (length, width), (0.0, width), (0.0, 0.0)):
                extrusion += (length + width) / 2000
                lines.append(f"G1 X{x:.3f} Y{y:.3f} E{extrusion:.5f} F1800")
        lines.extend(["M104 S0", "M140 S0", "M84", ""])
        return GCodeArtifact(
            slicer="DemoPrusaSlicer",
            filename=mesh.filename.rsplit(".", 1)[0] + ".gcode",
            content="\n".join(lines),
            layer_count=layers,
            estimated_seconds=max(30, layers * 12),
        )
