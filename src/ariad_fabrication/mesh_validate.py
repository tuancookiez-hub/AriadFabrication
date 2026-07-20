"""Dependency-free mesh checks for the local demo."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from .model_gen import MeshArtifact
from .models import PartSpec


@dataclass(frozen=True)
class MeshValidationReport:
    passed: bool
    triangle_count: int
    dimensions_mm: dict[str, float]
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "triangle_count": self.triangle_count,
            "dimensions_mm": dict(self.dimensions_mm),
            "errors": list(self.errors),
        }


_VERTEX = re.compile(
    r"^\s*vertex\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)


def validate_mesh(mesh: MeshArtifact, spec: PartSpec) -> MeshValidationReport:
    vertices = [match.groups() for line in mesh.content.splitlines() if (match := _VERTEX.match(line))]
    points = [tuple(round(float(value), 6) for value in vertex) for vertex in vertices]
    errors: list[str] = []

    if len(points) % 3 != 0 or not points:
        errors.append("STL does not contain complete triangle facets")
    triangles = [points[index : index + 3] for index in range(0, len(points) - 2, 3)]

    if triangles:
        dimensions = {
            "length": round(max(point[0] for point in points) - min(point[0] for point in points), 6),
            "width": round(max(point[1] for point in points) - min(point[1] for point in points), 6),
            "height": round(max(point[2] for point in points) - min(point[2] for point in points), 6),
        }
        tolerance = spec.tolerance_mm or 0.01
        for axis in ("length", "width", "height"):
            if abs(dimensions[axis] - spec.dimensions_mm[axis]) > tolerance:
                errors.append(f"{axis} differs from requested dimension")

        edge_counts: Counter[tuple[tuple[float, float, float], tuple[float, float, float]]] = Counter()
        for triangle in triangles:
            for first, second in ((triangle[0], triangle[1]), (triangle[1], triangle[2]), (triangle[2], triangle[0])):
                edge_counts[tuple(sorted((first, second)))] += 1
        if any(count != 2 for count in edge_counts.values()):
            errors.append("mesh is not watertight: every edge must belong to two facets")
    else:
        dimensions = {"length": 0.0, "width": 0.0, "height": 0.0}

    return MeshValidationReport(
        passed=not errors,
        triangle_count=len(triangles),
        dimensions_mm=dimensions,
        errors=tuple(errors),
    )
