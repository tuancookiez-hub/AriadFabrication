"""Generate the Ariad floating air-warship concept as a colored 3D assembly.

This script is deliberately outside the registered fabrication worker. It is
trusted repository-authored experiment code for concept geometry, not a path
for model-generated CAD and not evidence of printability or physical safety.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from math import cos, isfinite, pi, sin, sqrt
from pathlib import Path
import shutil
import struct
import sys
from typing import Any, Callable, Mapping, Sequence
from zipfile import ZipFile, is_zipfile
import xml.etree.ElementTree as ET

import cadquery as cq

from ariad_fabrication.cad.canonical import canonicalize_3mf, canonicalize_step
from ariad_fabrication.cad.stl import inspect_binary_stl


DESIGN_VERSION = "1.1.0"
GENERATOR_ID = "ariad_floating_air_warship_generator"


@dataclass(frozen=True)
class Material:
    name: str
    rgba: tuple[float, float, float, float]
    metallic: float
    roughness: float
    emissive: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Component:
    name: str
    shape: cq.Shape
    material: Material
    category: str


MATERIALS = {
    "hull": Material("midnight_hull", (0.045, 0.085, 0.14, 1.0), 0.82, 0.30),
    "armor": Material("blue_steel_armor", (0.12, 0.24, 0.34, 1.0), 0.72, 0.34),
    "edge": Material("gunmetal", (0.075, 0.10, 0.13, 1.0), 0.88, 0.24),
    "canopy": Material(
        "command_glass",
        (0.035, 0.34, 0.48, 1.0),
        0.42,
        0.16,
        (0.01, 0.13, 0.20),
    ),
    "glow": Material(
        "aether_cyan",
        (0.05, 0.72, 0.92, 1.0),
        0.18,
        0.18,
        (0.05, 0.78, 1.0),
    ),
    "warning": Material(
        "reactor_amber",
        (0.92, 0.40, 0.06, 1.0),
        0.30,
        0.24,
        (1.0, 0.22, 0.01),
    ),
}


def _number(parameters: Mapping[str, Any], key: str) -> float:
    value = parameters.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{key} must be finite and greater than zero")
    return number


def _faceted_profile(half_width: float, half_height: float) -> list[tuple[float, float]]:
    return [
        (0.0, half_height),
        (0.72 * half_width, 0.66 * half_height),
        (half_width, 0.0),
        (0.68 * half_width, -0.64 * half_height),
        (0.0, -half_height),
        (-0.68 * half_width, -0.64 * half_height),
        (-half_width, 0.0),
        (-0.72 * half_width, 0.66 * half_height),
    ]


def _round_profile(
    half_width: float,
    half_height: float,
    *,
    sides: int = 12,
) -> list[tuple[float, float]]:
    return [
        (
            half_width * cos(2.0 * pi * index / sides + pi / sides),
            half_height * sin(2.0 * pi * index / sides + pi / sides),
        )
        for index in range(sides)
    ]


def _loft_along_x(
    stations: Sequence[tuple[float, float, float]],
    *,
    center_y: float = 0.0,
    center_z: float = 0.0,
    rounded: bool = False,
) -> cq.Shape:
    if len(stations) < 2:
        raise ValueError("a loft requires at least two stations")
    first_x, first_width, first_height = stations[0]
    profile = _round_profile if rounded else _faceted_profile
    workplane = (
        cq.Workplane("YZ", origin=(first_x, center_y, center_z))
        .polyline(profile(first_width, first_height))
        .close()
    )
    previous_x = first_x
    for x, half_width, half_height in stations[1:]:
        if x <= previous_x:
            raise ValueError("loft stations must be ordered along positive X")
        workplane = (
            workplane.workplane(offset=x - previous_x)
            .polyline(profile(half_width, half_height))
            .close()
        )
        previous_x = x
    shape = workplane.loft(combine=True).val()
    if not shape.isValid():
        raise ValueError("loft did not produce valid OCCT geometry")
    return shape


def _chamfered_box(
    length: float,
    width: float,
    height: float,
    *,
    center: tuple[float, float, float],
    chamfer: float,
) -> cq.Shape:
    workplane = cq.Workplane("XY").box(length, width, height)
    if chamfer > 0:
        workplane = workplane.edges().chamfer(chamfer)
    return workplane.translate(center).val()


def _horizontal_plate(
    points: Sequence[tuple[float, float]],
    *,
    z: float,
    thickness: float,
) -> cq.Shape:
    return (
        cq.Workplane("XY")
        .polyline(points)
        .close()
        .extrude(thickness / 2.0, both=True)
        .translate((0.0, 0.0, z))
        .val()
    )


def _vertical_fin(
    points: Sequence[tuple[float, float]],
    *,
    y: float,
    thickness: float,
) -> cq.Shape:
    return (
        cq.Workplane("XZ")
        .polyline(points)
        .close()
        .extrude(thickness / 2.0, both=True)
        .translate((0.0, y, 0.0))
        .val()
    )


def _cylinder(
    radius: float,
    length: float,
    start: tuple[float, float, float],
    direction: tuple[float, float, float],
) -> cq.Shape:
    return cq.Solid.makeCylinder(radius, length, cq.Vector(*start), cq.Vector(*direction))


def _torus(
    major_radius: float,
    minor_radius: float,
    center: tuple[float, float, float],
    axis: tuple[float, float, float],
) -> cq.Shape:
    return cq.Solid.makeTorus(
        major_radius,
        minor_radius,
        cq.Vector(*center),
        cq.Vector(*axis),
    )


def _cone(
    start_radius: float,
    end_radius: float,
    length: float,
    start: tuple[float, float, float],
    direction: tuple[float, float, float],
) -> cq.Shape:
    return cq.Solid.makeCone(
        start_radius,
        end_radius,
        length,
        cq.Vector(*start),
        cq.Vector(*direction),
    )


def build_components(parameters: Mapping[str, Any]) -> tuple[Component, ...]:
    hull_length = _number(parameters, "hull_length_mm")
    hull_width = _number(parameters, "hull_half_width_mm")
    hull_height = _number(parameters, "hull_half_height_mm")
    nacelle_y = _number(parameters, "nacelle_offset_y_mm")
    nacelle_radius = _number(parameters, "nacelle_radius_mm")
    nacelle_length = _number(parameters, "nacelle_length_mm")
    deck_z = _number(parameters, "deck_z_mm")
    if nacelle_y <= hull_width:
        raise ValueError("nacelles must sit outside the main hull")

    half_length = hull_length / 2.0
    components: list[Component] = []

    def add(name: str, shape: cq.Shape, material: str, category: str) -> None:
        if not shape.isValid() or shape.Volume() <= 0:
            raise ValueError(f"component {name!r} is not a valid positive-volume shape")
        components.append(Component(name, shape, MATERIALS[material], category))

    hull_stations = (
        (-half_length, 0.28 * hull_width, 0.42 * hull_height),
        (-0.82 * half_length, 0.70 * hull_width, 0.78 * hull_height),
        (-0.30 * half_length, hull_width, hull_height),
        (0.35 * half_length, 0.92 * hull_width, 0.90 * hull_height),
        (0.76 * half_length, 0.58 * hull_width, 0.58 * hull_height),
        (0.96 * half_length, 0.18 * hull_width, 0.24 * hull_height),
        (half_length, 1.2, 1.2),
    )
    add("armored_main_hull", _loft_along_x(hull_stations), "hull", "primary_hull")

    keel_stations = (
        (-0.72 * half_length, 7.0, 3.5),
        (-0.25 * half_length, 13.0, 8.0),
        (0.34 * half_length, 11.0, 7.0),
        (0.72 * half_length, 3.0, 2.0),
    )
    add(
        "ventral_keel",
        _loft_along_x(keel_stations, center_z=-hull_height - 5.0),
        "edge",
        "ventral_structure",
    )

    add(
        "upper_armor_deck",
        _chamfered_box(
            88.0,
            45.0,
            5.0,
            center=(-7.0, 0.0, deck_z + 1.0),
            chamfer=2.2,
        ),
        "armor",
        "deck",
    )
    add(
        "command_block",
        _chamfered_box(
            42.0,
            26.0,
            11.0,
            center=(-2.0, 0.0, deck_z + 8.0),
            chamfer=2.0,
        ),
        "armor",
        "superstructure",
    )
    canopy = _loft_along_x(
        ((-18.0, 10.5, 2.5), (-4.0, 10.0, 6.0), (15.0, 6.5, 3.5), (22.0, 1.0, 1.0)),
        center_z=deck_z + 15.0,
        rounded=True,
    )
    add("command_canopy", canopy, "canopy", "superstructure")

    for side, sign in (("port", 1.0), ("starboard", -1.0)):
        wing_points = (
            (-58.0, sign * 20.0),
            (-38.0, sign * (nacelle_y + 2.0)),
            (28.0, sign * (nacelle_y + 2.0)),
            (48.0, sign * 25.0),
        )
        add(
            f"{side}_flight_deck",
            _horizontal_plate(wing_points, z=7.0, thickness=3.5),
            "armor",
            "lateral_structure",
        )
        nacelle_stations = (
            (-nacelle_length / 2.0, 2.0, 2.0),
            (-0.90 * nacelle_length / 2.0, 0.72 * nacelle_radius, 0.72 * nacelle_radius),
            (-0.55 * nacelle_length / 2.0, nacelle_radius, nacelle_radius),
            (0.45 * nacelle_length / 2.0, nacelle_radius, nacelle_radius),
            (0.86 * nacelle_length / 2.0, 0.62 * nacelle_radius, 0.62 * nacelle_radius),
            (nacelle_length / 2.0, 1.5, 1.5),
        )
        add(
            f"{side}_aether_nacelle",
            _loft_along_x(
                nacelle_stations,
                center_y=sign * nacelle_y,
                center_z=-1.5,
                rounded=True,
            ),
            "hull",
            "lift_nacelle",
        )
        for band_index, x in enumerate((-42.0, 5.0, 47.0), start=1):
            add(
                f"{side}_nacelle_armor_band_{band_index}",
                _cylinder(
                    nacelle_radius + 0.9,
                    3.0,
                    (x - 1.5, sign * nacelle_y, -1.5),
                    (1.0, 0.0, 0.0),
                ),
                "armor",
                "lift_nacelle_detail",
            )
        for ring_index, x in enumerate((-22.0, 29.0), start=1):
            add(
                f"{side}_aether_ring_{ring_index}",
                _torus(
                    nacelle_radius + 1.7,
                    1.0,
                    (x, sign * nacelle_y, -1.5),
                    (1.0, 0.0, 0.0),
                ),
                "glow",
                "lift_field_emitter",
            )
        add(
            f"{side}_rear_thruster_core",
            _cylinder(
                7.0,
                2.4,
                (-nacelle_length / 2.0 - 2.0, sign * nacelle_y, -1.5),
                (1.0, 0.0, 0.0),
            ),
            "warning",
            "propulsion",
        )
        add(
            f"{side}_rear_thruster_ring",
            _torus(
                8.0,
                1.25,
                (-nacelle_length / 2.0 - 2.1, sign * nacelle_y, -1.5),
                (1.0, 0.0, 0.0),
            ),
            "edge",
            "propulsion",
        )

    for side, sign in (("port", 1.0), ("starboard", -1.0)):
        fin_points = (
            (-64.0, 11.0),
            (-50.0, 39.0),
            (-20.0, 27.0),
            (-13.0, 12.0),
        )
        add(
            f"{side}_vertical_stabilizer",
            _vertical_fin(fin_points, y=sign * 20.0, thickness=3.0),
            "armor",
            "stabilizer",
        )

    for index, x in enumerate((-32.0, 30.0), start=1):
        add(
            f"ventral_lift_disc_{index}",
            _cylinder(10.0, 3.0, (x, 0.0, -hull_height - 9.0), (0.0, 0.0, 1.0)),
            "edge",
            "lift_field_emitter",
        )
        add(
            f"ventral_lift_glow_{index}",
            _torus(8.0, 1.1, (x, 0.0, -hull_height - 9.2), (0.0, 0.0, 1.0)),
            "glow",
            "lift_field_emitter",
        )

    def add_turret(prefix: str, x: float, y: float, z: float, scale: float = 1.0) -> None:
        add(
            f"{prefix}_turret_ring",
            _cylinder(5.3 * scale, 2.4 * scale, (x, y, z), (0.0, 0.0, 1.0)),
            "edge",
            "weapon",
        )
        add(
            f"{prefix}_turret_body",
            _chamfered_box(
                10.0 * scale,
                10.5 * scale,
                4.5 * scale,
                center=(x + 1.0 * scale, y, z + 4.0 * scale),
                chamfer=1.2 * scale,
            ),
            "armor",
            "weapon",
        )
        for barrel, offset in (("left", -2.2), ("right", 2.2)):
            add(
                f"{prefix}_{barrel}_barrel",
                _cylinder(
                    0.85 * scale,
                    19.0 * scale,
                    (x + 3.0 * scale, y + offset * scale, z + 5.0 * scale),
                    (1.0, 0.0, 0.0),
                ),
                "edge",
                "weapon",
            )

    add_turret("forward", 43.0, 0.0, deck_z + 3.0, 1.0)
    add_turret("aft_port", -45.0, 15.0, deck_z - 1.0, 0.78)
    add_turret("aft_starboard", -45.0, -15.0, deck_z - 1.0, 0.78)

    add(
        "bow_rail_lance",
        _cone(3.0, 0.35, 24.0, (half_length - 2.0, 0.0, -2.0), (1.0, 0.0, 0.0)),
        "edge",
        "weapon",
    )
    add(
        "sensor_mast",
        _cylinder(1.6, 16.0, (-12.0, 0.0, deck_z + 17.0), (0.0, 0.0, 1.0)),
        "edge",
        "sensor",
    )
    add(
        "sensor_crown",
        _torus(5.0, 0.9, (-12.0, 0.0, deck_z + 31.0), (0.0, 1.0, 0.0)),
        "glow",
        "sensor",
    )
    for index, y in enumerate((-7.5, 0.0, 7.5), start=1):
        add(
            f"central_thruster_{index}",
            _cylinder(3.1, 2.8, (-half_length - 2.0, y, -3.0), (1.0, 0.0, 0.0)),
            "warning",
            "propulsion",
        )
        add(
            f"central_thruster_ring_{index}",
            _torus(3.8, 0.72, (-half_length - 2.1, y, -3.0), (1.0, 0.0, 0.0)),
            "edge",
            "propulsion",
        )

    names = [item.name for item in components]
    if len(names) != len(set(names)):
        raise ValueError("component names must be unique")
    return tuple(components)


def _normal(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    third: tuple[float, float, float],
) -> tuple[float, float, float]:
    one = tuple(second[index] - first[index] for index in range(3))
    two = tuple(third[index] - first[index] for index in range(3))
    cross = (
        one[1] * two[2] - one[2] * two[1],
        one[2] * two[0] - one[0] * two[2],
        one[0] * two[1] - one[1] * two[0],
    )
    magnitude = sqrt(sum(value * value for value in cross))
    if magnitude <= 1e-15:
        raise ValueError("tessellation contains a degenerate triangle")
    return tuple(value / magnitude for value in cross)  # type: ignore[return-value]


def _glb_transform(vector: Any) -> tuple[float, float, float]:
    return (float(vector.x) / 1000.0, float(vector.z) / 1000.0, -float(vector.y) / 1000.0)


def _indexed_tessellation(
    shape: cq.Shape,
    *,
    linear_tolerance_mm: float,
    angular_tolerance_rad: float,
    transform: Callable[[Any], tuple[float, float, float]],
) -> tuple[
    list[tuple[float, float, float]],
    list[tuple[float, float, float]],
    list[int],
    int,
]:
    source_vertices, source_triangles = shape.tessellate(
        linear_tolerance_mm,
        angularTolerance=angular_tolerance_rad,
    )
    if not source_vertices or not source_triangles:
        raise ValueError("shape has no tessellated geometry")
    positions = [transform(vertex) for vertex in source_vertices]
    accumulated = [[0.0, 0.0, 0.0] for _ in positions]
    indices: list[int] = []
    for triangle in source_triangles:
        points = tuple(positions[index] for index in triangle)
        face_normal = _normal(points[0], points[1], points[2])
        for vertex_index in triangle:
            for axis in range(3):
                accumulated[vertex_index][axis] += face_normal[axis]
            indices.append(int(vertex_index))
    normals: list[tuple[float, float, float]] = []
    for vector in accumulated:
        magnitude = sqrt(sum(component * component for component in vector))
        if magnitude <= 1e-15:
            raise ValueError("tessellation contains a vertex without a usable normal")
        normals.append(tuple(component / magnitude for component in vector))  # type: ignore[arg-type]
    return positions, normals, indices, len(source_triangles)


def _pad(data: bytes, byte: bytes = b"\x00") -> bytes:
    return data + byte * ((-len(data)) % 4)


def export_colored_glb(
    components: Sequence[Component],
    path: Path,
    *,
    linear_tolerance_mm: float,
    angular_tolerance_rad: float,
) -> dict[str, Any]:
    materials: list[Material] = []
    material_indices: dict[str, int] = {}
    for component in components:
        if component.material.name not in material_indices:
            material_indices[component.material.name] = len(materials)
            materials.append(component.material)

    binary = bytearray()
    buffer_views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []
    meshes: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    total_triangles = 0
    total_vertices = 0

    def append_buffer(data: bytes, target: int) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(data)
        index = len(buffer_views)
        buffer_views.append(
            {
                "buffer": 0,
                "byteOffset": offset,
                "byteLength": len(data),
                "target": target,
            }
        )
        return index

    for component in components:
        points, point_normals, indices, triangle_count = _indexed_tessellation(
            component.shape,
            linear_tolerance_mm=linear_tolerance_mm,
            angular_tolerance_rad=angular_tolerance_rad,
            transform=_glb_transform,
        )
        positions = [value for point in points for value in point]
        normals = [value for normal in point_normals for value in normal]
        minimum = [min(point[axis] for point in points) for axis in range(3)]
        maximum = [max(point[axis] for point in points) for axis in range(3)]
        position_view = append_buffer(struct.pack(f"<{len(positions)}f", *positions), 34962)
        normal_view = append_buffer(struct.pack(f"<{len(normals)}f", *normals), 34962)
        index_view = append_buffer(struct.pack(f"<{len(indices)}I", *indices), 34963)
        position_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": position_view,
                "componentType": 5126,
                "count": len(points),
                "type": "VEC3",
                "min": minimum,
                "max": maximum,
            }
        )
        normal_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": normal_view,
                "componentType": 5126,
                "count": len(points),
                "type": "VEC3",
            }
        )
        index_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": index_view,
                "componentType": 5125,
                "count": len(indices),
                "type": "SCALAR",
                "min": [0],
                "max": [max(indices)],
            }
        )
        meshes.append(
            {
                "name": component.name,
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": position_accessor,
                            "NORMAL": normal_accessor,
                        },
                        "indices": index_accessor,
                        "material": material_indices[component.material.name],
                        "mode": 4,
                    }
                ],
                "extras": {"category": component.category},
            }
        )
        nodes.append({"name": component.name, "mesh": len(meshes) - 1})
        total_triangles += triangle_count
        total_vertices += len(points)

    material_documents = []
    for material in materials:
        material_documents.append(
            {
                "name": material.name,
                "pbrMetallicRoughness": {
                    "baseColorFactor": list(material.rgba),
                    "metallicFactor": material.metallic,
                    "roughnessFactor": material.roughness,
                },
                "emissiveFactor": list(material.emissive),
            }
        )

    document = {
        "asset": {
            "version": "2.0",
            "generator": f"{GENERATOR_ID} {DESIGN_VERSION}",
        },
        "scene": 0,
        "scenes": [{"name": "Floating Air Warship", "nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": material_documents,
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "extras": {
            "classification": "experimental decorative concept assembly",
            "source_units": "millimetres",
            "gltf_units": "metres",
            "source_coordinate_system": "Z-up",
            "gltf_coordinate_system": "Y-up; (x, y, z) = (x, z, -y)",
            "claim_boundary": "Visual concept only; not printability or physical evidence.",
        },
    }
    json_bytes = _pad(
        json.dumps(document, separators=(",", ":"), ensure_ascii=True).encode("utf-8"),
        b" ",
    )
    binary_bytes = _pad(bytes(binary))
    total_length = 12 + 8 + len(json_bytes) + 8 + len(binary_bytes)
    path.write_bytes(
        b"".join(
            (
                struct.pack("<4sII", b"glTF", 2, total_length),
                struct.pack("<II", len(json_bytes), 0x4E4F534A),
                json_bytes,
                struct.pack("<II", len(binary_bytes), 0x004E4942),
                binary_bytes,
            )
        )
    )
    return {
        "component_count": len(components),
        "material_count": len(materials),
        "triangle_count": total_triangles,
        "indexed_vertex_count": total_vertices,
    }


def inspect_glb(path: Path, expected_components: int) -> dict[str, Any]:
    payload = path.read_bytes()
    if len(payload) < 28:
        raise ValueError("GLB is too small")
    magic, version, total_length = struct.unpack_from("<4sII", payload, 0)
    if magic != b"glTF" or version != 2 or total_length != len(payload):
        raise ValueError("GLB header is invalid")
    json_length, json_type = struct.unpack_from("<II", payload, 12)
    if json_type != 0x4E4F534A:
        raise ValueError("GLB JSON chunk is missing")
    document = json.loads(payload[20 : 20 + json_length].decode("utf-8"))
    binary_offset = 20 + json_length
    binary_length, binary_type = struct.unpack_from("<II", payload, binary_offset)
    if binary_type != 0x004E4942 or binary_offset + 8 + binary_length != len(payload):
        raise ValueError("GLB binary chunk is invalid")
    if len(document.get("meshes", ())) != expected_components:
        raise ValueError("GLB component count does not match the source assembly")
    if not document.get("materials"):
        raise ValueError("GLB contains no materials")
    return {
        "mesh_count": len(document["meshes"]),
        "material_count": len(document["materials"]),
        "node_count": len(document["nodes"]),
        "binary_bytes": binary_length,
    }


def inspect_glb_with_vtk(path: Path, expected_components: int) -> dict[str, Any]:
    """Independently load the emitted GLB through VTK's glTF importer."""

    import vtk

    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    importer = vtk.vtkGLTFImporter()
    importer.SetFileName(str(path))
    importer.SetRenderWindow(window)
    importer.Update()
    actor_count = importer.GetRenderer().GetActors().GetNumberOfItems()
    if actor_count != expected_components:
        raise ValueError(
            f"VTK imported {actor_count} GLB actors; expected {expected_components}"
        )
    return {
        "vtk_roundtrip_loaded": True,
        "vtk_actor_count": actor_count,
    }


def export_colored_obj(
    components: Sequence[Component],
    obj_path: Path,
    mtl_path: Path,
    *,
    linear_tolerance_mm: float,
    angular_tolerance_rad: float,
) -> dict[str, int]:
    materials = {component.material.name: component.material for component in components}
    mtl_lines = ["# Ariad floating air-warship materials"]
    for material in materials.values():
        red, green, blue, alpha = material.rgba
        mtl_lines.extend(
            (
                f"newmtl {material.name}",
                f"Ka {red * 0.25:.6f} {green * 0.25:.6f} {blue * 0.25:.6f}",
                f"Kd {red:.6f} {green:.6f} {blue:.6f}",
                "Ks 0.450000 0.450000 0.450000",
                f"Ke {material.emissive[0]:.6f} {material.emissive[1]:.6f} {material.emissive[2]:.6f}",
                f"d {alpha:.6f}",
                "Ns 96.000000",
                "illum 2",
                "",
            )
        )
    mtl_path.write_text("\n".join(mtl_lines), encoding="utf-8", newline="\n")

    obj_lines = [
        "# Ariad floating air-warship concept",
        "# Coordinates are millimetres; Z is up.",
        f"mtllib {mtl_path.name}",
    ]
    vertex_index = 1
    triangle_count = 0
    for component in components:
        points, normals, indices, component_triangles = _indexed_tessellation(
            component.shape,
            linear_tolerance_mm=linear_tolerance_mm,
            angular_tolerance_rad=angular_tolerance_rad,
            transform=lambda vertex: (
                float(vertex.x),
                float(vertex.y),
                float(vertex.z),
            ),
        )
        obj_lines.extend((f"o {component.name}", f"usemtl {component.material.name}"))
        for point in points:
            obj_lines.append(f"v {point[0]:.7f} {point[1]:.7f} {point[2]:.7f}")
        for normal in normals:
            obj_lines.append(f"vn {normal[0]:.8f} {normal[1]:.8f} {normal[2]:.8f}")
        for offset in range(0, len(indices), 3):
            obj_lines.append(
                "f "
                + " ".join(
                    f"{vertex_index + indices[offset + slot]}//"
                    f"{vertex_index + indices[offset + slot]}"
                    for slot in range(3)
                )
            )
        vertex_index += len(points)
        triangle_count += component_triangles
    obj_path.write_text("\n".join(obj_lines) + "\n", encoding="utf-8", newline="\n")
    return {"triangle_count": triangle_count, "vertex_record_count": vertex_index - 1}


def inspect_3mf(path: Path) -> dict[str, Any]:
    if not is_zipfile(path):
        raise ValueError("3MF is not a ZIP package")
    with ZipFile(path) as archive:
        names = set(archive.namelist())
        required = {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"}
        if not required.issubset(names):
            raise ValueError("3MF is missing required package entries")
        root = ET.fromstring(archive.read("3D/3dmodel.model"))
    namespace = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    vertices = root.findall(".//m:vertex", namespace)
    triangles = root.findall(".//m:triangle", namespace)
    if root.attrib.get("unit") != "millimeter" or not triangles:
        raise ValueError("3MF does not contain millimetre mesh geometry")
    return {
        "unit": "millimeter",
        "vertex_count": len(vertices),
        "triangle_count": len(triangles),
    }


def _vtk_component_assets(
    components: Sequence[Component],
    *,
    linear_tolerance_mm: float,
    angular_tolerance_rad: float,
):
    import vtk

    assets = []
    for component in components:
        vertices, triangles = component.shape.tessellate(
            linear_tolerance_mm,
            angularTolerance=angular_tolerance_rad,
        )
        points = vtk.vtkPoints()
        for vertex in vertices:
            points.InsertNextPoint(float(vertex.x), float(vertex.y), float(vertex.z))
        polys = vtk.vtkCellArray()
        for triangle in triangles:
            cell = vtk.vtkTriangle()
            for slot, value in enumerate(triangle):
                cell.GetPointIds().SetId(slot, int(value))
            polys.InsertNextCell(cell)
        mesh = vtk.vtkPolyData()
        mesh.SetPoints(points)
        mesh.SetPolys(polys)

        normals = vtk.vtkPolyDataNormals()
        normals.SetInputData(mesh)
        normals.ComputePointNormalsOn()
        normals.ConsistencyOn()
        normals.AutoOrientNormalsOn()
        normals.SplittingOn()
        normals.SetFeatureAngle(38)
        surface_mapper = vtk.vtkPolyDataMapper()
        surface_mapper.SetInputConnection(normals.GetOutputPort())
        surface_mapper.ScalarVisibilityOff()

        edges = vtk.vtkFeatureEdges()
        edges.SetInputData(mesh)
        edges.BoundaryEdgesOn()
        edges.FeatureEdgesOn()
        edges.NonManifoldEdgesOn()
        edges.ManifoldEdgesOff()
        edges.SetFeatureAngle(42)
        edge_mapper = vtk.vtkPolyDataMapper()
        edge_mapper.SetInputConnection(edges.GetOutputPort())
        edge_mapper.ScalarVisibilityOff()
        assets.append((component, surface_mapper, edge_mapper))
    return assets


def _populate_renderer(renderer: Any, assets: Sequence[Any], *, edges: bool = True) -> None:
    import vtk

    for component, surface_mapper, edge_mapper in assets:
        actor = vtk.vtkActor()
        actor.SetMapper(surface_mapper)
        red, green, blue, _ = component.material.rgba
        actor.GetProperty().SetColor(red, green, blue)
        if max(component.material.emissive) > 0.5:
            actor.GetProperty().SetAmbient(0.95)
            actor.GetProperty().SetDiffuse(0.15)
            actor.GetProperty().SetSpecular(0.35)
        else:
            actor.GetProperty().SetAmbient(0.20)
            actor.GetProperty().SetDiffuse(0.78)
            actor.GetProperty().SetSpecular(0.28)
            actor.GetProperty().SetSpecularPower(32)
        renderer.AddActor(actor)
        if edges and max(component.material.emissive) <= 0.5:
            edge_actor = vtk.vtkActor()
            edge_actor.SetMapper(edge_mapper)
            edge_actor.GetProperty().SetColor(0.015, 0.025, 0.04)
            edge_actor.GetProperty().SetLineWidth(0.75)
            renderer.AddActor(edge_actor)


def _add_lights(renderer: Any, camera_position: tuple[float, float, float]) -> None:
    import vtk

    key = vtk.vtkLight()
    key.SetPosition(camera_position[0] + 80, camera_position[1] - 30, camera_position[2] + 100)
    key.SetFocalPoint(0, 0, 0)
    key.SetIntensity(1.0)
    renderer.AddLight(key)
    fill = vtk.vtkLight()
    fill.SetPosition(-camera_position[0], -camera_position[1], 30)
    fill.SetFocalPoint(0, 0, 0)
    fill.SetIntensity(0.55)
    renderer.AddLight(fill)


def render_previews(
    components: Sequence[Component],
    output_directory: Path,
    *,
    linear_tolerance_mm: float,
    angular_tolerance_rad: float,
) -> dict[str, Any]:
    import vtk

    assets = _vtk_component_assets(
        components,
        linear_tolerance_mm=linear_tolerance_mm,
        angular_tolerance_rad=angular_tolerance_rad,
    )

    def save_window(window: Any, path: Path) -> None:
        window.Render()
        capture = vtk.vtkWindowToImageFilter()
        capture.SetInput(window)
        capture.SetInputBufferTypeToRGBA()
        capture.ReadFrontBufferOff()
        capture.Update()
        writer = vtk.vtkPNGWriter()
        writer.SetFileName(str(path))
        writer.SetInputConnection(capture.GetOutputPort())
        writer.Write()

    hero_path = output_directory / "air_warship_hero.png"
    hero_window = vtk.vtkRenderWindow()
    hero_window.SetOffScreenRendering(1)
    hero_window.SetSize(1600, 950)
    hero_window.SetMultiSamples(8)
    hero = vtk.vtkRenderer()
    hero.SetBackground(0.015, 0.035, 0.07)
    hero.SetBackground2(0.13, 0.24, 0.36)
    hero.GradientBackgroundOn()
    hero.UseFXAAOn()
    _populate_renderer(hero, assets)
    hero_camera = hero.GetActiveCamera()
    hero_position = (250.0, -285.0, 155.0)
    hero_camera.SetPosition(*hero_position)
    hero_camera.SetFocalPoint(0.0, 0.0, 0.0)
    hero_camera.SetViewUp(0.0, 0.0, 1.0)
    hero_camera.SetViewAngle(27.0)
    _add_lights(hero, hero_position)

    title = vtk.vtkTextActor()
    title.SetInput("Ariad // AETHER DREADNOUGHT")
    title.SetPosition(46, 860)
    title.GetTextProperty().SetFontFamilyToArial()
    title.GetTextProperty().SetFontSize(32)
    title.GetTextProperty().SetBold(True)
    title.GetTextProperty().SetColor(0.76, 0.93, 1.0)
    hero.AddViewProp(title)
    subtitle = vtk.vtkTextActor()
    subtitle.SetInput("FLOATING AIR WARSHIP CONCEPT  |  MULTI-AriadID  |  NOT PRINT-VALIDATED")
    subtitle.SetPosition(50, 825)
    subtitle.GetTextProperty().SetFontFamilyToArial()
    subtitle.GetTextProperty().SetFontSize(16)
    subtitle.GetTextProperty().SetColor(0.38, 0.72, 0.86)
    hero.AddViewProp(subtitle)
    hero_window.AddRenderer(hero)
    save_window(hero_window, hero_path)

    multiview_path = output_directory / "air_warship_multiview.png"
    multi_window = vtk.vtkRenderWindow()
    multi_window.SetOffScreenRendering(1)
    multi_window.SetSize(1800, 1200)
    multi_window.SetMultiSamples(8)
    views = (
        ("BOW / STARBOARD", (250.0, -285.0, 150.0), (0, 0, 1), (0, 0.5, 0.5, 1)),
        ("TOP", (0.0, 0.0, 420.0), (0, 1, 0), (0.5, 0.5, 1, 1)),
        ("BROADSIDE", (0.0, -420.0, 65.0), (0, 0, 1), (0, 0, 0.5, 0.5)),
        ("VENTRAL / AFT", (-240.0, 275.0, -145.0), (0, 0, 1), (0.5, 0, 1, 0.5)),
    )
    backgrounds = (
        ((0.018, 0.040, 0.075), (0.12, 0.22, 0.34)),
        ((0.025, 0.045, 0.075), (0.09, 0.17, 0.27)),
        ((0.020, 0.035, 0.065), (0.11, 0.19, 0.29)),
        ((0.030, 0.025, 0.060), (0.13, 0.12, 0.25)),
    )
    for index, (label, position, view_up, viewport) in enumerate(views):
        renderer = vtk.vtkRenderer()
        renderer.SetViewport(*viewport)
        renderer.SetBackground(*backgrounds[index][0])
        renderer.SetBackground2(*backgrounds[index][1])
        renderer.GradientBackgroundOn()
        renderer.UseFXAAOn()
        _populate_renderer(renderer, assets)
        camera = renderer.GetActiveCamera()
        camera.SetPosition(*position)
        camera.SetFocalPoint(0.0, 0.0, 0.0)
        camera.SetViewUp(*view_up)
        camera.SetParallelProjection(True)
        camera.SetParallelScale(100.0 if index != 2 else 88.0)
        _add_lights(renderer, position)
        text = vtk.vtkTextActor()
        text.SetInput(label)
        text.SetPosition(28, 25)
        text.GetTextProperty().SetFontFamilyToArial()
        text.GetTextProperty().SetFontSize(21)
        text.GetTextProperty().SetBold(True)
        text.GetTextProperty().SetColor(0.72, 0.91, 1.0)
        renderer.AddViewProp(text)
        multi_window.AddRenderer(renderer)
    save_window(multi_window, multiview_path)
    return {
        "hero": hero_path.name,
        "multiview": multiview_path.name,
        "hero_bytes": hero_path.stat().st_size,
        "multiview_bytes": multiview_path.stat().st_size,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def generate(parameters: Mapping[str, Any], output_directory: Path) -> dict[str, Any]:
    output_directory = output_directory.resolve()
    if output_directory.exists():
        raise FileExistsError(f"immutable experiment output already exists: {output_directory}")
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    staging = output_directory.parent / f".{output_directory.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()

    try:
        linear_tolerance = _number(parameters, "linear_tolerance_mm")
        angular_tolerance = _number(parameters, "angular_tolerance_rad")
        components = build_components(parameters)
        solids = [solid for component in components for solid in component.shape.Solids()]
        if not solids:
            raise ValueError("concept assembly produced no solids")
        compound = cq.Compound.makeCompound(solids)
        if not compound.isValid():
            raise ValueError("concept compound is not a valid OCCT shape")

        source_path = staging / "generate.py"
        parameters_path = staging / "parameters.json"
        shutil.copyfile(Path(__file__), source_path)
        _write_json(parameters_path, dict(parameters))

        step_path = staging / "floating_air_warship.step"
        stl_path = staging / "floating_air_warship.stl"
        three_mf_path = staging / "floating_air_warship.3mf"
        glb_path = staging / "floating_air_warship.glb"
        obj_path = staging / "floating_air_warship.obj"
        mtl_path = staging / "floating_air_warship.mtl"

        cq.exporters.export(compound, str(step_path))
        canonicalize_step(step_path)
        imported = cq.importers.importStep(str(step_path))
        imported_solids = imported.solids().vals()
        if not imported_solids or any(not solid.isValid() for solid in imported_solids):
            raise ValueError("STEP did not re-import as valid solids")

        cq.exporters.export(
            compound,
            str(stl_path),
            tolerance=linear_tolerance,
            angularTolerance=angular_tolerance,
        )
        stl_evidence = inspect_binary_stl(stl_path)
        cq.exporters.export(
            compound,
            str(three_mf_path),
            tolerance=linear_tolerance,
            angularTolerance=angular_tolerance,
        )
        canonicalize_3mf(three_mf_path)
        three_mf_evidence = inspect_3mf(three_mf_path)
        glb_evidence = export_colored_glb(
            components,
            glb_path,
            linear_tolerance_mm=linear_tolerance,
            angular_tolerance_rad=angular_tolerance,
        )
        glb_evidence.update(inspect_glb(glb_path, len(components)))
        glb_evidence.update(inspect_glb_with_vtk(glb_path, len(components)))
        obj_evidence = export_colored_obj(
            components,
            obj_path,
            mtl_path,
            linear_tolerance_mm=linear_tolerance,
            angular_tolerance_rad=angular_tolerance,
        )
        render_evidence = render_previews(
            components,
            staging,
            linear_tolerance_mm=linear_tolerance,
            angular_tolerance_rad=angular_tolerance,
        )

        bounds = compound.BoundingBox()
        categories = Counter(component.category for component in components)
        report = {
            "schema_version": "1.0.0",
            "design_id": parameters.get("design_id"),
            "design_version": DESIGN_VERSION,
            "classification": "experimental_decorative_concept_assembly",
            "evidence_level": "concept_only",
            "claim_boundary": (
                "Locally generated and structurally inspected concept geometry. "
                "The assembly contains intentionally overlapping solids and has not been "
                "checked for unionability, self-intersections, wall thickness, supports, "
                "stability, strength, aerodynamics, printability, or physical safety."
            ),
            "component_count": len(components),
            "source_solid_count": len(solids),
            "step_reimport_solid_count": len(imported_solids),
            "all_source_components_valid": all(item.shape.isValid() for item in components),
            "bounds_mm": {
                "x": round(float(bounds.xlen), 6),
                "y": round(float(bounds.ylen), 6),
                "z": round(float(bounds.zlen), 6),
            },
            "component_categories": dict(sorted(categories.items())),
            "exports": {
                "step": {
                    "role": "exact multi-solid concept geometry",
                    "reimport_valid": True,
                    "solid_count": len(imported_solids),
                },
                "stl": stl_evidence,
                "3mf": three_mf_evidence,
                "glb": glb_evidence,
                "obj": obj_evidence,
                "renders": render_evidence,
            },
            "tool_versions": {
                "python": sys.version.split()[0],
                "cadquery": getattr(cq, "__version__", "unknown"),
                "generator": DESIGN_VERSION,
            },
        }
        report_path = staging / "concept_report.json"
        _write_json(report_path, report)

        artifact_paths = tuple(sorted(path for path in staging.iterdir() if path.is_file()))
        manifest = {
            "schema_version": "1.0.0",
            "design_id": parameters.get("design_id"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "classification": "experimental_decorative_concept_assembly",
            "evidence_level": "concept_only",
            "artifacts": [
                {
                    "path": path.name,
                    "size_bytes": path.stat().st_size,
                    "checksum_sha256": _sha256(path),
                }
                for path in artifact_paths
            ],
            "claim_boundary": report["claim_boundary"],
        }
        manifest_path = staging / "manifest.json"
        _write_json(manifest_path, manifest)
        staging.rename(output_directory)
        return {
            "output_directory": str(output_directory),
            "component_count": len(components),
            "solid_count": len(solids),
            "step_reimport_solid_count": len(imported_solids),
            "bounds_mm": report["bounds_mm"],
            "glb_triangles": glb_evidence["triangle_count"],
            "stl_closed_two_manifold": stl_evidence["closed_two_manifold"],
            "hero_render": str(output_directory / render_evidence["hero"]),
            "multiview_render": str(output_directory / render_evidence["multiview"]),
            "manifest": str(output_directory / "manifest.json"),
            "claim_boundary": report["claim_boundary"],
        }
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the Ariad floating air-warship concept")
    parser.add_argument(
        "--parameters",
        type=Path,
        default=Path(__file__).with_name("parameters.json"),
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    parameters = json.loads(args.parameters.read_text(encoding="utf-8"))
    result = generate(parameters, args.output_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
