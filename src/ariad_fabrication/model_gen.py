"""Mesh-generation adapters used by the demo pipeline.

The production boundary is intentionally small: a hosted provider can replace
``DeterministicModelProvider`` without changing the orchestrator. The local
provider creates a valid ASCII STL so the entire workflow is runnable without
API keys, a 3D printer, or network access.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .models import PartSpec


@dataclass(frozen=True)
class MeshArtifact:
    """A generated mesh kept in memory and optionally written to disk."""

    provider: str
    filename: str
    content: str
    dimensions_mm: dict[str, float]

    def write(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / self.filename
        path.write_text(self.content, encoding="utf-8")
        return path


class ModelProvider(Protocol):
    def generate(self, spec: PartSpec) -> MeshArtifact:
        ...


class DeterministicModelProvider:
    """Offline stand-in for a text-to-3D provider.

    It generates a watertight rectangular fixture with the requested bounding
    dimensions. This is deliberately transparent in the demo output: it proves
    the downstream pipeline and validation contracts without pretending that a
    hosted 3D model service was called.
    """

    def __init__(self, provider_name: str = "LocalDemoModel") -> None:
        self.provider_name = provider_name

    def generate(self, spec: PartSpec) -> MeshArtifact:
        length = spec.dimensions_mm["length"]
        width = spec.dimensions_mm["width"]
        height = spec.dimensions_mm["height"]
        stl = _box_stl(length, width, height)
        safe_name = "".join(char if char.isalnum() else "_" for char in spec.part_type)
        safe_name = safe_name.strip("_") or "custom_part"
        return MeshArtifact(
            provider=self.provider_name,
            filename=f"{safe_name}.stl",
            content=stl,
            dimensions_mm={"length": length, "width": width, "height": height},
        )


def _box_stl(length: float, width: float, height: float) -> str:
    """Return a closed ASCII STL cuboid with deterministic facet ordering."""

    vertices = (
        (0.0, 0.0, 0.0),
        (length, 0.0, 0.0),
        (length, width, 0.0),
        (0.0, width, 0.0),
        (0.0, 0.0, height),
        (length, 0.0, height),
        (length, width, height),
        (0.0, width, height),
    )
    faces = (
        (0, 2, 1), (0, 3, 2),  # bottom
        (4, 5, 6), (4, 6, 7),  # top
        (0, 1, 5), (0, 5, 4),  # front
        (1, 2, 6), (1, 6, 5),  # right
        (2, 3, 7), (2, 7, 6),  # back
        (3, 0, 4), (3, 4, 7),  # left
    )

    lines = ["solid ariad_demo_mesh"]
    for first, second, third in faces:
        lines.extend(
            [
                "  facet normal 0 0 0",
                "    outer loop",
                *[f"      vertex {vertices[index][0]:.6f} {vertices[index][1]:.6f} {vertices[index][2]:.6f}" for index in (first, second, third)],
                "    endloop",
                "  endfacet",
            ]
        )
    lines.extend(["endsolid ariad_demo_mesh", ""])
    return "\n".join(lines)
