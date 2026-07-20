"""Generate a one-piece, conventional warship display-model experiment.

This is trusted repository-authored CadQuery code outside Ariad's registered CAD
worker. Its outputs are geometry-checked experimental artifacts, not R3/R4
printability evidence and not proof of a successful physical print.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from math import isfinite, sqrt
from pathlib import Path
import shutil
import struct
import sys
from typing import Any, Mapping, Sequence
import xml.etree.ElementTree as ET
from zipfile import ZipFile, is_zipfile

import cadquery as cq

from ariad_fabrication.cad.canonical import canonicalize_3mf, canonicalize_step
from ariad_fabrication.cad.stl import inspect_binary_stl


DESIGN_VERSION = "1.0.0"
GENERATOR_ID = "ariad_conventional_warship_display_generator"
CLAIM_BOUNDARY = (
    "One connected valid solid, measured envelope, flat bed datum/contact, STEP "
    "re-import, and closed two-manifold STL were checked. Upright FDM suitability "
    "is a design intention only: orientation risks, overhangs, supports, nozzle and "
    "material rules, real slicing, strength, flotation, and physical printing remain "
    "unverified."
)


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


def _hull_profile(half_width: float, height: float) -> list[tuple[float, float]]:
    """Return a faceted Y/Z hull section with a broad planar keel."""

    bottom = 0.60 * half_width
    shoulder = 0.91 * half_width
    return [
        (-bottom, 0.0),
        (bottom, 0.0),
        (half_width, 0.42 * height),
        (shoulder, height),
        (-shoulder, height),
        (-half_width, 0.42 * height),
    ]


def _loft_hull(stations: Sequence[tuple[float, float, float]]) -> cq.Shape:
    if len(stations) < 2:
        raise ValueError("the hull loft requires at least two stations")
    first_x, first_width, first_height = stations[0]
    workplane = (
        cq.Workplane("YZ", origin=(first_x, 0.0, 0.0))
        .polyline(_hull_profile(first_width, first_height))
        .close()
    )
    previous_x = first_x
    for x, half_width, height in stations[1:]:
        if x <= previous_x:
            raise ValueError("hull stations must increase along X")
        workplane = (
            workplane.workplane(offset=x - previous_x)
            .polyline(_hull_profile(half_width, height))
            .close()
        )
        previous_x = x
    # A ruled loft preserves the station envelope exactly. A smooth B-spline
    # loft can overshoot the narrow bow section, which would make the declared
    # length and beam differ from the exported geometry.
    shape = workplane.loft(combine=True, ruled=True).val()
    if not shape.isValid() or shape.Volume() <= 0:
        raise ValueError("the hull loft is not a valid positive-volume shape")
    return shape


def _plan_plate(
    points: Sequence[tuple[float, float]],
    *,
    z: float,
    thickness: float,
) -> cq.Shape:
    return (
        cq.Workplane("XY", origin=(0.0, 0.0, z))
        .polyline(points)
        .close()
        .extrude(thickness)
        .val()
    )


def _tapered_block(
    *,
    center_x: float,
    base_z: float,
    height: float,
    base_length: float,
    base_width: float,
    top_length: float,
    top_width: float,
) -> cq.Shape:
    return (
        cq.Workplane("XY", origin=(center_x, 0.0, base_z))
        .rect(base_length, base_width)
        .workplane(offset=height)
        .rect(top_length, top_width)
        .loft(combine=True)
        .val()
    )


def _cylinder(
    radius: float,
    height: float,
    *,
    center_x: float,
    center_y: float,
    base_z: float,
) -> cq.Shape:
    return cq.Solid.makeCylinder(
        radius,
        height,
        cq.Vector(center_x, center_y, base_z),
        cq.Vector(0.0, 0.0, 1.0),
    )


def _cone(
    bottom_radius: float,
    top_radius: float,
    height: float,
    *,
    center_x: float,
    center_y: float,
    base_z: float,
) -> cq.Shape:
    return cq.Solid.makeCone(
        bottom_radius,
        top_radius,
        height,
        cq.Vector(center_x, center_y, base_z),
        cq.Vector(0.0, 0.0, 1.0),
    )


def _vertical_xz_plate(
    points: Sequence[tuple[float, float]],
    *,
    center_y: float,
    thickness: float,
) -> cq.Shape:
    return (
        cq.Workplane("XZ", origin=(0.0, center_y, 0.0))
        .polyline(points)
        .close()
        .extrude(thickness / 2.0, both=True)
        .val()
    )


def _supported_gun(
    *,
    center_x: float,
    center_y: float,
    deck_z: float,
    facing: float,
    thickness: float,
) -> cq.Shape:
    """Create an integrated elevated gun silhouette with a supported underside."""

    local_points = (
        (-2.2, deck_z + 0.4),
        (4.0, deck_z + 0.4),
        (12.0, deck_z + 8.4),
        (12.0, deck_z + 10.9),
        (1.0, deck_z + 5.7),
    )
    points = [(center_x + facing * distance, z) for distance, z in local_points]
    return _vertical_xz_plate(points, center_y=center_y, thickness=thickness)


def _fuse_connected(shapes: Sequence[cq.Shape]) -> cq.Shape:
    if not shapes:
        raise ValueError("at least one shape is required")
    result = shapes[0]
    for shape in shapes[1:]:
        if not shape.isValid() or shape.Volume() <= 0:
            raise ValueError("a source feature is not valid positive-volume geometry")
        result = result.fuse(shape)
    result = result.clean()
    solids = result.Solids()
    if len(solids) != 1:
        raise ValueError(f"warship features produced {len(solids)} solids; expected one")
    if not result.isValid() or result.Volume() <= 0:
        raise ValueError("fused warship is not a valid positive-volume solid")
    return result


def build_model(parameters: Mapping[str, Any]) -> cq.Shape:
    length = _number(parameters, "length_mm")
    beam = _number(parameters, "beam_mm")
    hull_height = _number(parameters, "hull_height_mm")
    minimum_feature = _number(parameters, "minimum_nominal_feature_mm")
    nozzle = _number(parameters, "reference_nozzle_mm")
    if parameters.get("units") != "mm":
        raise ValueError("this experiment currently requires millimetres")
    if length < 120.0 or length > 220.0:
        raise ValueError("length_mm must be between 120 and 220 for this recipe")
    if beam < 0.16 * length or beam > 0.28 * length:
        raise ValueError("beam_mm must be between 16% and 28% of length_mm")
    if hull_height < 0.06 * length or hull_height > 0.12 * length:
        raise ValueError("hull_height_mm must be between 6% and 12% of length_mm")
    if minimum_feature < 4.0 * nozzle:
        raise ValueError("minimum nominal feature must be at least four nozzle widths")

    sx = length / 160.0
    sy = beam / 32.0
    sz = hull_height / 13.5
    half_length = length / 2.0
    half_beam = beam / 2.0

    shapes: list[cq.Shape] = []
    shapes.append(
        _loft_hull(
            (
                (-half_length, 0.69 * half_beam, 0.76 * hull_height),
                (-0.43 * length, 0.92 * half_beam, 0.93 * hull_height),
                (-0.16 * length, half_beam, hull_height),
                (0.24 * length, 0.96 * half_beam, hull_height),
                (0.40 * length, 0.62 * half_beam, 0.84 * hull_height),
                (0.485 * length, 0.15 * half_beam, 0.54 * hull_height),
                (half_length, max(0.8, 0.05 * half_beam), 0.35 * hull_height),
            )
        )
    )

    deck_base_z = hull_height - 2.2 * sz
    deck_thickness = 2.8 * sz
    deck_top_z = deck_base_z + deck_thickness
    shapes.append(
        _plan_plate(
            (
                (-0.43 * length, -0.84 * half_beam),
                (-0.10 * length, -0.93 * half_beam),
                (0.25 * length, -0.84 * half_beam),
                (0.40 * length, -0.44 * half_beam),
                (0.44 * length, 0.0),
                (0.40 * length, 0.44 * half_beam),
                (0.25 * length, 0.84 * half_beam),
                (-0.10 * length, 0.93 * half_beam),
                (-0.43 * length, 0.84 * half_beam),
            ),
            z=deck_base_z,
            thickness=deck_thickness,
        )
    )

    lower_base_z = deck_top_z - 0.9 * sz
    shapes.append(
        _tapered_block(
            center_x=-10.0 * sx,
            base_z=lower_base_z,
            height=7.4 * sz,
            base_length=48.0 * sx,
            base_width=20.0 * sy,
            top_length=42.0 * sx,
            top_width=17.0 * sy,
        )
    )
    bridge_base_z = lower_base_z + 6.5 * sz
    shapes.append(
        _tapered_block(
            center_x=5.0 * sx,
            base_z=bridge_base_z,
            height=9.5 * sz,
            base_length=28.0 * sx,
            base_width=16.0 * sy,
            top_length=21.0 * sx,
            top_width=12.5 * sy,
        )
    )
    shapes.append(
        _tapered_block(
            center_x=28.0 * sx,
            base_z=deck_top_z - 0.8 * sz,
            height=5.2 * sz,
            base_length=22.0 * sx,
            base_width=13.5 * sy,
            top_length=18.0 * sx,
            top_width=11.0 * sy,
        )
    )
    shapes.append(
        _tapered_block(
            center_x=-48.0 * sx,
            base_z=deck_top_z - 0.8 * sz,
            height=4.7 * sz,
            base_length=20.0 * sx,
            base_width=14.0 * sy,
            top_length=16.0 * sx,
            top_width=11.5 * sy,
        )
    )

    funnel_base_z = lower_base_z + 5.5 * sz
    shapes.extend(
        (
            _cylinder(
                5.4 * sy,
                15.0 * sz,
                center_x=-25.0 * sx,
                center_y=0.0,
                base_z=funnel_base_z,
            ),
            _cylinder(
                6.2 * sy,
                2.2 * sz,
                center_x=-25.0 * sx,
                center_y=0.0,
                base_z=funnel_base_z,
            ),
            _cylinder(
                5.9 * sy,
                2.0 * sz,
                center_x=-25.0 * sx,
                center_y=0.0,
                base_z=funnel_base_z + 13.3 * sz,
            ),
        )
    )

    mast_base_z = bridge_base_z + 8.0 * sz
    shapes.append(
        _cylinder(
            1.8 * min(sx, sy),
            16.2 * sz,
            center_x=7.0 * sx,
            center_y=0.0,
            base_z=mast_base_z,
        )
    )
    shapes.append(
        _vertical_xz_plate(
            (
                (1.5 * sx, mast_base_z + 9.2 * sz),
                (12.5 * sx, mast_base_z + 9.2 * sz),
                (10.5 * sx, mast_base_z + 14.0 * sz),
                (3.5 * sx, mast_base_z + 14.0 * sz),
            ),
            center_y=0.0,
            thickness=max(minimum_feature, 2.4 * sy),
        )
    )
    shapes.append(
        _cone(
            2.6 * min(sx, sy),
            0.8 * min(sx, sy),
            3.0 * sz,
            center_x=7.0 * sx,
            center_y=0.0,
            base_z=mast_base_z + 15.0 * sz,
        )
    )

    turret_base_z = deck_top_z - 0.7 * sz
    for center_x, facing in ((48.0 * sx, 1.0), (-56.0 * sx, -1.0)):
        shapes.append(
            _cone(
                6.0 * min(sx, sy),
                4.5 * min(sx, sy),
                5.2 * sz,
                center_x=center_x,
                center_y=0.0,
                base_z=turret_base_z,
            )
        )
        for center_y in (-2.0 * sy, 2.0 * sy):
            shapes.append(
                _supported_gun(
                    center_x=center_x,
                    center_y=center_y,
                    deck_z=turret_base_z,
                    facing=facing,
                    thickness=max(minimum_feature, 2.4 * sy),
                )
            )

    shape = _fuse_connected(shapes)
    return shape


def _check(
    check_id: str,
    passed: bool,
    measured: Any,
    requirement: str,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "passed": bool(passed),
        "measured": measured,
        "requirement": requirement,
    }


def validate_geometry(shape: cq.Shape, parameters: Mapping[str, Any]) -> dict[str, Any]:
    length = _number(parameters, "length_mm")
    beam = _number(parameters, "beam_mm")
    minimum_feature = _number(parameters, "minimum_nominal_feature_mm")
    nozzle = _number(parameters, "reference_nozzle_mm")
    solids = shape.Solids()
    bounds = shape.BoundingBox()
    base_faces = []
    for face in shape.Faces():
        face_bounds = face.BoundingBox()
        if abs(float(face_bounds.zmin)) <= 0.01 and abs(float(face_bounds.zmax)) <= 0.01:
            base_faces.append(face)
    base_area = sum(float(face.Area()) for face in base_faces)
    checks = [
        _check("kernel_valid", shape.isValid(), shape.isValid(), "OCCT shape is valid"),
        _check("single_connected_solid", len(solids) == 1, len(solids), "exactly one solid"),
        _check("positive_volume", shape.Volume() > 1000.0, round(float(shape.Volume()), 3), "> 1000 mm^3"),
        _check("length", abs(float(bounds.xlen) - length) <= 0.05, round(float(bounds.xlen), 4), f"{length} +/- 0.05 mm"),
        _check("beam", abs(float(bounds.ylen) - beam) <= 0.05, round(float(bounds.ylen), 4), f"{beam} +/- 0.05 mm"),
        _check("flat_keel_datum", abs(float(bounds.zmin)) <= 0.01, round(float(bounds.zmin), 5), "Z minimum is 0 +/- 0.01 mm"),
        _check("flat_bed_contact", base_area >= 800.0, round(base_area, 3), ">= 800 mm^2 coplanar contact"),
        _check("desktop_height", float(bounds.zlen) <= 55.0, round(float(bounds.zlen), 4), "<= 55 mm"),
        _check("nominal_feature_rule", minimum_feature >= 4.0 * nozzle, round(minimum_feature / nozzle, 3), ">= 4 nozzle widths by declared recipe"),
    ]
    return {
        "schema_version": "1.0.0",
        "classification": "experimental_print_oriented_display_model",
        "evidence_label": "geometry_checked_experiment",
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
        "bounds_mm": {
            "x": round(float(bounds.xlen), 6),
            "y": round(float(bounds.ylen), 6),
            "z": round(float(bounds.zlen), 6),
            "z_min": round(float(bounds.zmin), 6),
        },
        "volume_mm3": round(float(shape.Volume()), 6),
        "flat_contact_area_mm2": round(base_area, 6),
        "claim_boundary": CLAIM_BOUNDARY,
    }


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


def export_glb(
    shape: cq.Shape,
    path: Path,
    *,
    linear_tolerance_mm: float,
    angular_tolerance_rad: float,
) -> dict[str, Any]:
    source_vertices, source_triangles = shape.tessellate(
        linear_tolerance_mm,
        angularTolerance=angular_tolerance_rad,
    )
    if not source_vertices or not source_triangles:
        raise ValueError("shape has no tessellated geometry")

    positions: list[tuple[float, float, float]] = [
        (float(vertex.x) / 1000.0, float(vertex.z) / 1000.0, -float(vertex.y) / 1000.0)
        for vertex in source_vertices
    ]
    accumulated = [[0.0, 0.0, 0.0] for _ in positions]
    indices: list[int] = []
    for triangle in source_triangles:
        points = tuple(positions[index] for index in triangle)
        face_normal = _normal(points[0], points[1], points[2])
        for vertex_index in triangle:
            for axis in range(3):
                accumulated[vertex_index][axis] += face_normal[axis]
            indices.append(int(vertex_index))
    normals = []
    for vector in accumulated:
        magnitude = sqrt(sum(component * component for component in vector))
        if magnitude <= 1e-15:
            raise ValueError("tessellation contains an unusable vertex normal")
        normals.append(tuple(component / magnitude for component in vector))

    binary = bytearray()
    buffer_views: list[dict[str, Any]] = []

    def append_buffer(data: bytes, target: int) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(data)
        buffer_views.append(
            {"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": target}
        )
        return len(buffer_views) - 1

    flat_positions = [value for point in positions for value in point]
    flat_normals = [value for normal in normals for value in normal]
    position_view = append_buffer(struct.pack(f"<{len(flat_positions)}f", *flat_positions), 34962)
    normal_view = append_buffer(struct.pack(f"<{len(flat_normals)}f", *flat_normals), 34962)
    index_view = append_buffer(struct.pack(f"<{len(indices)}I", *indices), 34963)
    minimum = [min(point[axis] for point in positions) for axis in range(3)]
    maximum = [max(point[axis] for point in positions) for axis in range(3)]
    document = {
        "asset": {"version": "2.0", "generator": f"{GENERATOR_ID} {DESIGN_VERSION}"},
        "scene": 0,
        "scenes": [{"name": "Conventional warship display model", "nodes": [0]}],
        "nodes": [{"name": "one_piece_warship", "mesh": 0}],
        "meshes": [
            {
                "name": "one_piece_warship",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1},
                        "indices": 2,
                        "material": 0,
                        "mode": 4,
                    }
                ],
            }
        ],
        "materials": [
            {
                "name": "naval_blue_preview",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.10, 0.32, 0.42, 1.0],
                    "metallicFactor": 0.38,
                    "roughnessFactor": 0.38,
                },
            }
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": [
            {
                "bufferView": position_view,
                "componentType": 5126,
                "count": len(positions),
                "type": "VEC3",
                "min": minimum,
                "max": maximum,
            },
            {
                "bufferView": normal_view,
                "componentType": 5126,
                "count": len(normals),
                "type": "VEC3",
            },
            {
                "bufferView": index_view,
                "componentType": 5125,
                "count": len(indices),
                "type": "SCALAR",
                "min": [0],
                "max": [max(indices)],
            },
        ],
        "extras": {
            "classification": "experimental print-oriented display model",
            "source_units": "millimetres",
            "gltf_units": "metres",
            "source_coordinate_system": "Z-up",
            "gltf_coordinate_system": "Y-up; (x, y, z) = (x, z, -y)",
            "claim_boundary": CLAIM_BOUNDARY,
        },
    }
    json_bytes = json.dumps(document, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    json_bytes += b" " * ((-len(json_bytes)) % 4)
    binary_bytes = bytes(binary) + b"\x00" * ((-len(binary)) % 4)
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
        "mesh_count": 1,
        "source_vertex_count": len(positions),
        "triangle_count": len(source_triangles),
        "indexed_vertex_count": len(indices),
    }


def inspect_glb(path: Path) -> dict[str, Any]:
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
    if len(document.get("meshes", ())) != 1 or not document.get("materials"):
        raise ValueError("GLB does not contain the expected single colored mesh")
    return {"structurally_valid": True, "binary_bytes": binary_length}


def inspect_glb_with_vtk(path: Path) -> dict[str, Any]:
    import vtk

    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    importer = vtk.vtkGLTFImporter()
    importer.SetFileName(str(path))
    importer.SetRenderWindow(window)
    importer.Update()
    actor_count = importer.GetRenderer().GetActors().GetNumberOfItems()
    if actor_count != 1:
        raise ValueError(f"VTK imported {actor_count} GLB actors; expected one")
    return {"vtk_roundtrip_loaded": True, "vtk_actor_count": actor_count}


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


def _vtk_mesh(shape: cq.Shape, *, linear_tolerance_mm: float, angular_tolerance_rad: float):
    import vtk

    vertices, triangles = shape.tessellate(
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
    normals.SetFeatureAngle(42)
    surface_mapper = vtk.vtkPolyDataMapper()
    surface_mapper.SetInputConnection(normals.GetOutputPort())
    surface_mapper.ScalarVisibilityOff()

    edges = vtk.vtkFeatureEdges()
    edges.SetInputData(mesh)
    edges.BoundaryEdgesOn()
    edges.FeatureEdgesOn()
    edges.NonManifoldEdgesOn()
    edges.ManifoldEdgesOff()
    edges.SetFeatureAngle(38)
    edge_mapper = vtk.vtkPolyDataMapper()
    edge_mapper.SetInputConnection(edges.GetOutputPort())
    edge_mapper.ScalarVisibilityOff()
    return surface_mapper, edge_mapper


def _populate_renderer(renderer: Any, surface_mapper: Any, edge_mapper: Any) -> None:
    import vtk

    surface = vtk.vtkActor()
    surface.SetMapper(surface_mapper)
    surface.GetProperty().SetColor(0.075, 0.39, 0.48)
    surface.GetProperty().SetAmbient(0.22)
    surface.GetProperty().SetDiffuse(0.72)
    surface.GetProperty().SetSpecular(0.34)
    surface.GetProperty().SetSpecularPower(42)
    renderer.AddActor(surface)
    edge = vtk.vtkActor()
    edge.SetMapper(edge_mapper)
    edge.GetProperty().SetColor(0.01, 0.035, 0.05)
    edge.GetProperty().SetLineWidth(0.85)
    renderer.AddActor(edge)


def _add_lights(renderer: Any, camera_position: tuple[float, float, float]) -> None:
    import vtk

    key = vtk.vtkLight()
    key.SetPosition(camera_position[0] + 90, camera_position[1] - 50, camera_position[2] + 120)
    key.SetFocalPoint(0, 0, 12)
    key.SetIntensity(1.0)
    renderer.AddLight(key)
    fill = vtk.vtkLight()
    fill.SetPosition(-camera_position[0], -camera_position[1], 90)
    fill.SetFocalPoint(0, 0, 12)
    fill.SetIntensity(0.48)
    renderer.AddLight(fill)


def render_previews(
    shape: cq.Shape,
    output_directory: Path,
    *,
    linear_tolerance_mm: float,
    angular_tolerance_rad: float,
    bounds: Mapping[str, float],
) -> dict[str, Any]:
    import vtk

    surface_mapper, edge_mapper = _vtk_mesh(
        shape,
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

    hero_path = output_directory / "conventional_warship_hero.png"
    hero_window = vtk.vtkRenderWindow()
    hero_window.SetOffScreenRendering(1)
    hero_window.SetSize(1600, 950)
    hero_window.SetMultiSamples(8)
    hero = vtk.vtkRenderer()
    hero.SetBackground(0.012, 0.028, 0.045)
    hero.SetBackground2(0.075, 0.18, 0.24)
    hero.GradientBackgroundOn()
    hero.UseFXAAOn()
    _populate_renderer(hero, surface_mapper, edge_mapper)
    camera = hero.GetActiveCamera()
    position = (225.0, -235.0, 115.0)
    camera.SetPosition(*position)
    camera.SetFocalPoint(0.0, 0.0, 15.0)
    camera.SetViewUp(0.0, 0.0, 1.0)
    camera.SetViewAngle(27.0)
    _add_lights(hero, position)

    title = vtk.vtkTextActor()
    title.SetInput("Ariad // CONVENTIONAL WARSHIP")
    title.SetPosition(46, 860)
    title.GetTextProperty().SetFontFamilyToArial()
    title.GetTextProperty().SetFontSize(32)
    title.GetTextProperty().SetBold(True)
    title.GetTextProperty().SetColor(0.76, 0.95, 1.0)
    hero.AddViewProp(title)
    subtitle = vtk.vtkTextActor()
    subtitle.SetInput(
        "ONE-PIECE DISPLAY CAD  |  UPRIGHT FLAT KEEL  |  GEOMETRY-CHECKED  |  NOT SLICER-VERIFIED"
    )
    subtitle.SetPosition(50, 825)
    subtitle.GetTextProperty().SetFontFamilyToArial()
    subtitle.GetTextProperty().SetFontSize(16)
    subtitle.GetTextProperty().SetColor(0.38, 0.78, 0.86)
    hero.AddViewProp(subtitle)
    dimensions = vtk.vtkTextActor()
    dimensions.SetInput(
        f"ENVELOPE  {bounds['x']:.1f} x {bounds['y']:.1f} x {bounds['z']:.1f} mm"
    )
    dimensions.SetPosition(50, 60)
    dimensions.GetTextProperty().SetFontFamilyToArial()
    dimensions.GetTextProperty().SetFontSize(17)
    dimensions.GetTextProperty().SetColor(0.64, 0.88, 0.92)
    hero.AddViewProp(dimensions)
    hero_window.AddRenderer(hero)
    save_window(hero_window, hero_path)

    multiview_path = output_directory / "conventional_warship_multiview.png"
    multi_window = vtk.vtkRenderWindow()
    multi_window.SetOffScreenRendering(1)
    multi_window.SetSize(1800, 1200)
    multi_window.SetMultiSamples(8)
    views = (
        ("PRINT ORIENTATION", (225.0, -235.0, 115.0), (0, 0, 1), (0, 0.5, 0.5, 1), 105.0),
        ("TOP", (0.0, 0.0, 420.0), (0, 1, 0), (0.5, 0.5, 1, 1), 92.0),
        ("STARBOARD", (0.0, -420.0, 45.0), (0, 0, 1), (0, 0, 0.5, 0.5), 92.0),
        ("BOW", (420.0, 0.0, 55.0), (0, 0, 1), (0.5, 0, 1, 0.5), 45.0),
    )
    backgrounds = (
        ((0.012, 0.030, 0.050), (0.07, 0.17, 0.23)),
        ((0.015, 0.035, 0.055), (0.06, 0.14, 0.20)),
        ((0.014, 0.028, 0.045), (0.08, 0.16, 0.21)),
        ((0.018, 0.030, 0.050), (0.06, 0.15, 0.20)),
    )
    for index, (label, position, view_up, viewport, parallel_scale) in enumerate(views):
        renderer = vtk.vtkRenderer()
        renderer.SetViewport(*viewport)
        renderer.SetBackground(*backgrounds[index][0])
        renderer.SetBackground2(*backgrounds[index][1])
        renderer.GradientBackgroundOn()
        renderer.UseFXAAOn()
        _populate_renderer(renderer, surface_mapper, edge_mapper)
        camera = renderer.GetActiveCamera()
        camera.SetPosition(*position)
        camera.SetFocalPoint(0.0, 0.0, 15.0)
        camera.SetViewUp(*view_up)
        camera.SetParallelProjection(True)
        camera.SetParallelScale(parallel_scale)
        _add_lights(renderer, position)
        label_actor = vtk.vtkTextActor()
        label_actor.SetInput(label)
        label_actor.SetPosition(28, 25)
        label_actor.GetTextProperty().SetFontFamilyToArial()
        label_actor.GetTextProperty().SetFontSize(21)
        label_actor.GetTextProperty().SetBold(True)
        label_actor.GetTextProperty().SetColor(0.72, 0.94, 1.0)
        renderer.AddViewProp(label_actor)
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
        model = build_model(parameters)

        source_path = staging / "generate.py"
        parameters_path = staging / "parameters.json"
        shutil.copyfile(Path(__file__), source_path)
        _write_json(parameters_path, dict(parameters))

        step_path = staging / "conventional_warship.step"
        stl_path = staging / "conventional_warship.stl"
        three_mf_path = staging / "conventional_warship.3mf"
        glb_path = staging / "conventional_warship.glb"
        cq.exporters.export(model, str(step_path))
        canonicalize_step(step_path)
        imported = cq.importers.importStep(str(step_path))
        imported_shape = imported.val()
        if not imported_shape.isValid() or len(imported.solids().vals()) != 1:
            raise ValueError("STEP did not re-import as one valid solid")

        geometry_report = validate_geometry(imported_shape, parameters)
        if not geometry_report["passed"]:
            failed = [item["check_id"] for item in geometry_report["checks"] if not item["passed"]]
            raise ValueError(f"geometry checks failed: {', '.join(failed)}")

        cq.exporters.export(
            model,
            str(stl_path),
            tolerance=linear_tolerance,
            angularTolerance=angular_tolerance,
        )
        stl_evidence = inspect_binary_stl(stl_path)
        cq.exporters.export(
            model,
            str(three_mf_path),
            tolerance=linear_tolerance,
            angularTolerance=angular_tolerance,
        )
        canonicalize_3mf(three_mf_path)
        three_mf_evidence = inspect_3mf(three_mf_path)
        glb_evidence = export_glb(
            model,
            glb_path,
            linear_tolerance_mm=linear_tolerance,
            angular_tolerance_rad=angular_tolerance,
        )
        glb_evidence.update(inspect_glb(glb_path))
        glb_evidence.update(inspect_glb_with_vtk(glb_path))
        render_evidence = render_previews(
            model,
            staging,
            linear_tolerance_mm=linear_tolerance,
            angular_tolerance_rad=angular_tolerance,
            bounds=geometry_report["bounds_mm"],
        )

        report = dict(geometry_report)
        report.update(
            {
                "design_id": parameters.get("design_id"),
                "design_version": DESIGN_VERSION,
                "intended_process": parameters.get("intended_process"),
                "intended_orientation": parameters.get("intended_orientation"),
                "exports": {
                    "step": {"role": "exact one-solid CAD geometry", "reimport_valid": True},
                    "stl": stl_evidence,
                    "3mf": three_mf_evidence,
                    "glb": glb_evidence,
                    "renders": render_evidence,
                },
                "tool_versions": {
                    "python": sys.version.split()[0],
                    "cadquery": getattr(cq, "__version__", "unknown"),
                    "generator": DESIGN_VERSION,
                },
            }
        )
        report_path = staging / "geometry_report.json"
        _write_json(report_path, report)

        artifact_paths = tuple(sorted(path for path in staging.iterdir() if path.is_file()))
        manifest = {
            "schema_version": "1.0.0",
            "design_id": parameters.get("design_id"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "classification": "experimental_print_oriented_display_model",
            "evidence_label": "geometry_checked_experiment",
            "artifacts": [
                {
                    "path": path.name,
                    "size_bytes": path.stat().st_size,
                    "checksum_sha256": _sha256(path),
                }
                for path in artifact_paths
            ],
            "claim_boundary": CLAIM_BOUNDARY,
        }
        manifest_path = staging / "manifest.json"
        _write_json(manifest_path, manifest)
        staging.rename(output_directory)
        return {
            "output_directory": str(output_directory),
            "solid_count": 1,
            "bounds_mm": geometry_report["bounds_mm"],
            "flat_contact_area_mm2": geometry_report["flat_contact_area_mm2"],
            "stl_closed_two_manifold": stl_evidence["closed_two_manifold"],
            "hero_render": str(output_directory / render_evidence["hero"]),
            "multiview_render": str(output_directory / render_evidence["multiview"]),
            "manifest": str(output_directory / "manifest.json"),
            "claim_boundary": CLAIM_BOUNDARY,
        }
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a one-piece conventional warship display-model experiment"
    )
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
