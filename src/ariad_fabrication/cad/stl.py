"""Deterministic structural and manifold checks for binary STL exports."""

from __future__ import annotations

from collections import Counter
from math import isfinite, sqrt
from pathlib import Path
import struct
from typing import Any


def _edge_key(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    return tuple(sorted((first, second)))  # type: ignore[return-value]


def inspect_binary_stl(path: Path) -> dict[str, Any]:
    """Validate one OCCT binary STL and return recorded mesh statistics.

    STL does not encode units. This checker verifies topology only; the worker
    records that coordinates inherit millimetres from the source CAD model.
    """

    payload = path.read_bytes()
    if len(payload) < 84:
        raise ValueError("STL export is too small to contain a binary header")
    triangle_count = struct.unpack_from("<I", payload, 80)[0]
    expected_size = 84 + triangle_count * 50
    if triangle_count == 0 or len(payload) != expected_size:
        raise ValueError("STL export is not a complete binary triangle stream")

    edges: Counter[
        tuple[tuple[float, float, float], tuple[float, float, float]]
    ] = Counter()
    directed_edges: Counter[
        tuple[tuple[float, float, float], tuple[float, float, float]]
    ] = Counter()
    vertices: set[tuple[float, float, float]] = set()
    minimum_area_mm2 = float("inf")

    for index in range(triangle_count):
        values = struct.unpack_from("<12fH", payload, 84 + index * 50)
        triangle = tuple(tuple(values[offset : offset + 3]) for offset in (3, 6, 9))
        if any(not isfinite(component) for vertex in triangle for component in vertex):
            raise ValueError(f"STL triangle {index} contains a non-finite coordinate")
        if len(set(triangle)) != 3:
            raise ValueError(f"STL triangle {index} is degenerate")

        first = tuple(triangle[1][axis] - triangle[0][axis] for axis in range(3))
        second = tuple(triangle[2][axis] - triangle[0][axis] for axis in range(3))
        cross = (
            first[1] * second[2] - first[2] * second[1],
            first[2] * second[0] - first[0] * second[2],
            first[0] * second[1] - first[1] * second[0],
        )
        area = 0.5 * sqrt(sum(component * component for component in cross))
        if area <= 1e-12:
            raise ValueError(f"STL triangle {index} has effectively zero area")
        minimum_area_mm2 = min(minimum_area_mm2, area)

        vertices.update(triangle)
        for start, end in (
            (triangle[0], triangle[1]),
            (triangle[1], triangle[2]),
            (triangle[2], triangle[0]),
        ):
            edges[_edge_key(start, end)] += 1
            directed_edges[(start, end)] += 1

    nonmanifold_edges = sum(count != 2 for count in edges.values())
    orientation_mismatches = sum(
        directed_edges[(start, end)] != directed_edges[(end, start)]
        for start, end in directed_edges
    )
    if nonmanifold_edges:
        raise ValueError(f"STL mesh contains {nonmanifold_edges} non-manifold boundary edges")
    if orientation_mismatches:
        raise ValueError(
            f"STL mesh contains {orientation_mismatches} directed-edge orientation mismatches"
        )

    return {
        "encoding": "binary_stl",
        "unit_semantics": "unitless STL coordinates inherited as millimetres from CAD source",
        "triangle_count": triangle_count,
        "unique_vertex_count": len(vertices),
        "unique_edge_count": len(edges),
        "nonmanifold_edge_count": nonmanifold_edges,
        "orientation_mismatch_count": orientation_mismatches,
        "minimum_triangle_area_mm2": round(minimum_area_mm2, 9),
        "closed_two_manifold": True,
    }
