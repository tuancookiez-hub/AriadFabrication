"""Small deterministic GLB preview exporter for CadQuery shapes.

STEP remains the exact geometry artifact. This module tessellates a shape and
creates a glTF 2.0 binary preview without introducing another runtime dependency.
Ariad's Z-up coordinates are transformed to glTF's conventional Y-up view.
"""

from __future__ import annotations

import json
from math import sqrt
from pathlib import Path
import struct
from typing import Any


_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942


def _pad(data: bytes, byte: bytes) -> bytes:
    return data + byte * ((-len(data)) % 4)


def _transform(vector: Any) -> tuple[float, float, float]:
    return (float(vector.x), float(vector.z), -float(vector.y))


def _subtract(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return tuple(left[index] - right[index] for index in range(3))  # type: ignore[return-value]


def _normal(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    third: tuple[float, float, float],
) -> tuple[float, float, float]:
    one = _subtract(second, first)
    two = _subtract(third, first)
    cross = (
        one[1] * two[2] - one[2] * two[1],
        one[2] * two[0] - one[0] * two[2],
        one[0] * two[1] - one[1] * two[0],
    )
    magnitude = sqrt(sum(value * value for value in cross))
    if magnitude <= 1e-15:
        raise ValueError("cannot export a degenerate preview triangle")
    return tuple(value / magnitude for value in cross)  # type: ignore[return-value]


def export_glb(
    shape: Any,
    path: Path,
    *,
    linear_tolerance_mm: float,
    angular_tolerance_rad: float,
) -> dict[str, int]:
    """Write a flat-shaded GLB preview and return mesh statistics."""

    vertices, triangles = shape.tessellate(
        linear_tolerance_mm,
        angularTolerance=angular_tolerance_rad,
    )
    if not vertices or not triangles:
        raise ValueError("CadQuery tessellation returned no preview geometry")

    positions: list[float] = []
    normals: list[float] = []
    indices: list[int] = []
    for triangle in triangles:
        points = tuple(_transform(vertices[index]) for index in triangle)
        normal = _normal(points[0], points[1], points[2])
        for point in points:
            positions.extend(point)
            normals.extend(normal)
            indices.append(len(indices))

    position_tuples = tuple(zip(*(iter(positions),) * 3, strict=True))
    minimum = [min(point[index] for point in position_tuples) for index in range(3)]
    maximum = [max(point[index] for point in position_tuples) for index in range(3)]
    position_bytes = struct.pack(f"<{len(positions)}f", *positions)
    normal_bytes = struct.pack(f"<{len(normals)}f", *normals)
    index_bytes = struct.pack(f"<{len(indices)}I", *indices)
    position_offset = 0
    normal_offset = len(position_bytes)
    index_offset = normal_offset + len(normal_bytes)
    binary = _pad(position_bytes + normal_bytes + index_bytes, b"\x00")

    document = {
        "asset": {
            "version": "2.0",
            "generator": "Ariad deterministic CadQuery preview exporter 1.0.0",
        },
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "OpenGrow Golden Part"}],
        "meshes": [
            {
                "name": "OpenGrow Golden Part preview",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1},
                        "indices": 2,
                        "mode": 4,
                    }
                ],
            }
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": position_offset,
                "byteLength": len(position_bytes),
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": normal_offset,
                "byteLength": len(normal_bytes),
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": index_offset,
                "byteLength": len(index_bytes),
                "target": 34963,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(indices),
                "type": "VEC3",
                "min": minimum,
                "max": maximum,
            },
            {
                "bufferView": 1,
                "componentType": 5126,
                "count": len(indices),
                "type": "VEC3",
            },
            {
                "bufferView": 2,
                "componentType": 5125,
                "count": len(indices),
                "type": "SCALAR",
                "min": [0],
                "max": [len(indices) - 1],
            },
        ],
        "extras": {
            "source_coordinate_system": "Ariad Z-up millimetres",
            "preview_coordinate_system": "glTF Y-up; (x, y, z) = (x, z, -y)",
            "evidence_note": "Tessellated preview only; STEP is the exact geometry artifact.",
        },
    }
    json_bytes = _pad(
        json.dumps(document, separators=(",", ":"), ensure_ascii=True).encode("utf-8"),
        b" ",
    )
    total_length = 12 + 8 + len(json_bytes) + 8 + len(binary)
    payload = b"".join(
        (
            struct.pack("<4sII", b"glTF", 2, total_length),
            struct.pack("<II", len(json_bytes), _JSON_CHUNK),
            json_bytes,
            struct.pack("<II", len(binary), _BIN_CHUNK),
            binary,
        )
    )
    path.write_bytes(payload)
    return {
        "source_vertex_count": len(vertices),
        "triangle_count": len(triangles),
        "preview_vertex_count": len(indices),
    }


def inspect_glb(path: Path) -> dict[str, Any]:
    """Perform structural checks without relying on a viewer library."""

    payload = path.read_bytes()
    if len(payload) < 28:
        raise ValueError("GLB file is too small")
    magic, version, total_length = struct.unpack_from("<4sII", payload, 0)
    if magic != b"glTF" or version != 2 or total_length != len(payload):
        raise ValueError("invalid glTF 2.0 binary header")
    json_length, json_type = struct.unpack_from("<II", payload, 12)
    if json_type != _JSON_CHUNK:
        raise ValueError("GLB first chunk must contain JSON")
    document = json.loads(payload[20 : 20 + json_length].decode("utf-8"))
    binary_header_offset = 20 + json_length
    binary_length, binary_type = struct.unpack_from("<II", payload, binary_header_offset)
    if binary_type != _BIN_CHUNK:
        raise ValueError("GLB second chunk must contain binary geometry")
    if binary_header_offset + 8 + binary_length != len(payload):
        raise ValueError("GLB binary chunk length does not match the file")
    if document.get("asset", {}).get("version") != "2.0":
        raise ValueError("GLB JSON does not declare glTF 2.0")
    primitive = document["meshes"][0]["primitives"][0]
    if "POSITION" not in primitive.get("attributes", {}) or "indices" not in primitive:
        raise ValueError("GLB preview is missing indexed position geometry")
    return document
