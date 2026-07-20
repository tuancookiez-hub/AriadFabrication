"""Versioned printer, material, process, and orientation profile contracts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import isclose, isfinite
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ..schema_validation import (
    MATERIAL_PROFILE_SCHEMA,
    ORIENTATION_PROFILE_SCHEMA,
    PRINTER_PROFILE_SCHEMA,
    PROCESS_PROFILE_SCHEMA,
    validate_persisted_instance,
)


PROFILE_CONTRACT_VERSION = "1.0.0"


def _text(value: Any, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _number(value: Any, name: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not isfinite(number) or (number < 0 if allow_zero else number <= 0):
        qualifier = "non-negative" if allow_zero else "greater than zero"
        raise ValueError(f"{name} must be finite and {qualifier}")
    return number


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _integer(value: Any, name: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if number < minimum or float(value) != number:
        raise ValueError(f"{name} must be an integer greater than or equal to {minimum}")
    return number


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_json_object,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ValueError(f"{path} must contain strict UTF-8 JSON") from exc
    return _mapping(value, str(path))


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _reject_duplicate_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key is not allowed: {key!r}")
        value[key] = item
    return value


def _version(value: Mapping[str, Any]) -> None:
    if value.get("schema_version") != PROFILE_CONTRACT_VERSION:
        raise ValueError(f"unsupported profile schema {value.get('schema_version')!r}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class PrinterProfile:
    profile_id: str
    profile_family_id: str
    name: str
    status: str
    technology: str
    build_volume_mm: tuple[float, float, float]
    bed_origin: str
    bed_shape_mm: tuple[tuple[float, float], ...]
    nozzle_diameter_mm: float
    filament_diameter_mm: float
    extruder_count: int
    firmware_flavor: str
    maximum_nozzle_temperature_c: float
    maximum_bed_temperature_c: float
    source: str
    claim_boundary: str
    schema_version: str = PROFILE_CONTRACT_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PrinterProfile":
        validate_persisted_instance(
            dict(value),
            PRINTER_PROFILE_SCHEMA,
            record_name="printer profile",
        )
        _version(value)
        volume = _mapping(value.get("build_volume_mm"), "build_volume_mm")
        raw_shape = value.get("bed_shape_mm")
        if not isinstance(raw_shape, Sequence) or isinstance(raw_shape, (str, bytes)):
            raise ValueError("bed_shape_mm must be an array")
        shape: list[tuple[float, float]] = []
        for index, point in enumerate(raw_shape):
            if not isinstance(point, Sequence) or isinstance(point, (str, bytes)) or len(point) != 2:
                raise ValueError(f"bed_shape_mm[{index}] must contain X and Y")
            shape.append(
                (
                    _number(point[0], f"bed_shape_mm[{index}].x", allow_zero=True),
                    _number(point[1], f"bed_shape_mm[{index}].y", allow_zero=True),
                )
            )
        if len(shape) < 3:
            raise ValueError("bed_shape_mm must contain at least three points")
        technology = _text(value.get("technology"), "technology")
        if technology != "FFF":
            raise ValueError("the current slicer profile contract supports FFF only")
        return cls(
            profile_id=_text(value.get("profile_id"), "profile_id"),
            profile_family_id=_text(
                value.get("profile_family_id", value.get("profile_id")),
                "profile_family_id",
            ),
            name=_text(value.get("name"), "name"),
            status=_text(value.get("status"), "status"),
            technology=technology,
            build_volume_mm=tuple(
                _number(volume.get(axis), f"build_volume_mm.{axis}") for axis in "xyz"
            ),
            bed_origin=_text(value.get("bed_origin"), "bed_origin"),
            bed_shape_mm=tuple(shape),
            nozzle_diameter_mm=_number(value.get("nozzle_diameter_mm"), "nozzle_diameter_mm"),
            filament_diameter_mm=_number(
                value.get("filament_diameter_mm"), "filament_diameter_mm"
            ),
            extruder_count=_integer(value.get("extruder_count"), "extruder_count"),
            firmware_flavor=_text(value.get("firmware_flavor"), "firmware_flavor"),
            maximum_nozzle_temperature_c=_number(
                value.get("maximum_nozzle_temperature_c"), "maximum_nozzle_temperature_c"
            ),
            maximum_bed_temperature_c=_number(
                value.get("maximum_bed_temperature_c"), "maximum_bed_temperature_c"
            ),
            source=_text(value.get("source"), "source"),
            claim_boundary=_text(value.get("claim_boundary"), "claim_boundary"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "profile_family_id": self.profile_family_id,
            "name": self.name,
            "status": self.status,
            "technology": self.technology,
            "build_volume_mm": dict(zip("xyz", self.build_volume_mm, strict=True)),
            "bed_origin": self.bed_origin,
            "bed_shape_mm": [list(point) for point in self.bed_shape_mm],
            "nozzle_diameter_mm": self.nozzle_diameter_mm,
            "filament_diameter_mm": self.filament_diameter_mm,
            "extruder_count": self.extruder_count,
            "firmware_flavor": self.firmware_flavor,
            "maximum_nozzle_temperature_c": self.maximum_nozzle_temperature_c,
            "maximum_bed_temperature_c": self.maximum_bed_temperature_c,
            "source": self.source,
            "claim_boundary": self.claim_boundary,
        }


@dataclass(frozen=True)
class MaterialProfile:
    profile_id: str
    name: str
    status: str
    material_type: str
    filament_diameter_mm: float
    density_g_cm3: float
    selected_nozzle_temperature_c: float
    first_layer_nozzle_temperature_c: float
    allowed_nozzle_temperature_c: tuple[float, float]
    selected_bed_temperature_c: float
    first_layer_bed_temperature_c: float
    allowed_bed_temperature_c: tuple[float, float]
    maximum_volumetric_speed_mm3_s: float
    fan_percent: tuple[float, float]
    source: str
    claim_boundary: str
    schema_version: str = PROFILE_CONTRACT_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MaterialProfile":
        validate_persisted_instance(
            dict(value),
            MATERIAL_PROFILE_SCHEMA,
            record_name="material profile",
        )
        _version(value)

        def numeric_range(key: str, *, allow_zero: bool = False) -> tuple[float, float]:
            item = _mapping(value.get(key), key)
            minimum = _number(item.get("minimum"), f"{key}.minimum", allow_zero=allow_zero)
            maximum = _number(item.get("maximum"), f"{key}.maximum")
            if minimum > maximum:
                raise ValueError(f"{key}.minimum cannot exceed maximum")
            return minimum, maximum

        fan = numeric_range("fan_percent", allow_zero=True)
        if fan[1] > 100:
            raise ValueError("fan_percent.maximum cannot exceed 100")
        nozzle_range = numeric_range("allowed_nozzle_temperature_c")
        bed_range = numeric_range("allowed_bed_temperature_c", allow_zero=True)
        selected_nozzle = _number(
            value.get("selected_nozzle_temperature_c"), "selected_nozzle_temperature_c"
        )
        selected_bed = _number(
            value.get("selected_bed_temperature_c"),
            "selected_bed_temperature_c",
            allow_zero=True,
        )
        if not nozzle_range[0] <= selected_nozzle <= nozzle_range[1]:
            raise ValueError("selected nozzle temperature is outside the material range")
        if not bed_range[0] <= selected_bed <= bed_range[1]:
            raise ValueError("selected bed temperature is outside the material range")
        first_layer_nozzle = _number(
            value.get("first_layer_nozzle_temperature_c", selected_nozzle),
            "first_layer_nozzle_temperature_c",
        )
        first_layer_bed = _number(
            value.get("first_layer_bed_temperature_c", selected_bed),
            "first_layer_bed_temperature_c",
            allow_zero=True,
        )
        if not nozzle_range[0] <= first_layer_nozzle <= nozzle_range[1]:
            raise ValueError("first-layer nozzle temperature is outside the material range")
        if not bed_range[0] <= first_layer_bed <= bed_range[1]:
            raise ValueError("first-layer bed temperature is outside the material range")
        return cls(
            profile_id=_text(value.get("profile_id"), "profile_id"),
            name=_text(value.get("name"), "name"),
            status=_text(value.get("status"), "status"),
            material_type=_text(value.get("material_type"), "material_type"),
            filament_diameter_mm=_number(
                value.get("filament_diameter_mm"), "filament_diameter_mm"
            ),
            density_g_cm3=_number(value.get("density_g_cm3"), "density_g_cm3"),
            selected_nozzle_temperature_c=selected_nozzle,
            first_layer_nozzle_temperature_c=first_layer_nozzle,
            allowed_nozzle_temperature_c=nozzle_range,
            selected_bed_temperature_c=selected_bed,
            first_layer_bed_temperature_c=first_layer_bed,
            allowed_bed_temperature_c=bed_range,
            maximum_volumetric_speed_mm3_s=_number(
                value.get("maximum_volumetric_speed_mm3_s"),
                "maximum_volumetric_speed_mm3_s",
            ),
            fan_percent=fan,
            source=_text(value.get("source"), "source"),
            claim_boundary=_text(value.get("claim_boundary"), "claim_boundary"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "name": self.name,
            "status": self.status,
            "material_type": self.material_type,
            "filament_diameter_mm": self.filament_diameter_mm,
            "density_g_cm3": self.density_g_cm3,
            "selected_nozzle_temperature_c": self.selected_nozzle_temperature_c,
            "first_layer_nozzle_temperature_c": self.first_layer_nozzle_temperature_c,
            "allowed_nozzle_temperature_c": {
                "minimum": self.allowed_nozzle_temperature_c[0],
                "maximum": self.allowed_nozzle_temperature_c[1],
            },
            "selected_bed_temperature_c": self.selected_bed_temperature_c,
            "first_layer_bed_temperature_c": self.first_layer_bed_temperature_c,
            "allowed_bed_temperature_c": {
                "minimum": self.allowed_bed_temperature_c[0],
                "maximum": self.allowed_bed_temperature_c[1],
            },
            "maximum_volumetric_speed_mm3_s": self.maximum_volumetric_speed_mm3_s,
            "fan_percent": {"minimum": self.fan_percent[0], "maximum": self.fan_percent[1]},
            "source": self.source,
            "claim_boundary": self.claim_boundary,
        }


@dataclass(frozen=True)
class ProcessProfile:
    profile_id: str
    name: str
    status: str
    layer_height_mm: float
    first_layer_height_mm: float
    perimeters: int
    top_solid_layers: int
    bottom_solid_layers: int
    infill_percent: float
    infill_pattern: str
    support_policy: str
    skirts: int
    brim_width_mm: float
    speeds_mm_s: Mapping[str, float]
    claim_boundary: str
    schema_version: str = PROFILE_CONTRACT_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProcessProfile":
        validate_persisted_instance(
            dict(value),
            PROCESS_PROFILE_SCHEMA,
            record_name="process profile",
        )
        _version(value)
        speeds = _mapping(value.get("speeds_mm_s"), "speeds_mm_s")
        required_speeds = (
            "perimeter",
            "external_perimeter",
            "small_perimeter",
            "infill",
            "solid_infill",
            "top_solid_infill",
            "bridge",
            "first_layer",
            "travel",
        )
        normalized_speeds = {
            key: _number(speeds.get(key), f"speeds_mm_s.{key}") for key in required_speeds
        }
        support_policy = _text(value.get("support_policy"), "support_policy")
        if support_policy not in {"disabled", "enabled", "build_plate_only"}:
            raise ValueError("unsupported support_policy")
        infill = _number(value.get("infill_percent"), "infill_percent", allow_zero=True)
        if infill > 100:
            raise ValueError("infill_percent cannot exceed 100")
        return cls(
            profile_id=_text(value.get("profile_id"), "profile_id"),
            name=_text(value.get("name"), "name"),
            status=_text(value.get("status"), "status"),
            layer_height_mm=_number(value.get("layer_height_mm"), "layer_height_mm"),
            first_layer_height_mm=_number(
                value.get("first_layer_height_mm"), "first_layer_height_mm"
            ),
            perimeters=_integer(value.get("perimeters"), "perimeters"),
            top_solid_layers=_integer(value.get("top_solid_layers"), "top_solid_layers"),
            bottom_solid_layers=_integer(
                value.get("bottom_solid_layers"), "bottom_solid_layers"
            ),
            infill_percent=infill,
            infill_pattern=_text(value.get("infill_pattern"), "infill_pattern"),
            support_policy=support_policy,
            skirts=_integer(value.get("skirts"), "skirts", minimum=0),
            brim_width_mm=_number(value.get("brim_width_mm"), "brim_width_mm", allow_zero=True),
            speeds_mm_s=MappingProxyType(normalized_speeds),
            claim_boundary=_text(value.get("claim_boundary"), "claim_boundary"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "name": self.name,
            "status": self.status,
            "layer_height_mm": self.layer_height_mm,
            "first_layer_height_mm": self.first_layer_height_mm,
            "perimeters": self.perimeters,
            "top_solid_layers": self.top_solid_layers,
            "bottom_solid_layers": self.bottom_solid_layers,
            "infill_percent": self.infill_percent,
            "infill_pattern": self.infill_pattern,
            "support_policy": self.support_policy,
            "skirts": self.skirts,
            "brim_width_mm": self.brim_width_mm,
            "speeds_mm_s": dict(self.speeds_mm_s),
            "claim_boundary": self.claim_boundary,
        }


@dataclass(frozen=True)
class OrientationProfile:
    orientation_id: str
    name: str
    status: str
    source_up_axis: str
    transform_4x4: tuple[tuple[float, ...], ...]
    placement: str
    ensure_on_bed: bool
    claim_boundary: str
    schema_version: str = PROFILE_CONTRACT_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OrientationProfile":
        validate_persisted_instance(
            dict(value),
            ORIENTATION_PROFILE_SCHEMA,
            record_name="orientation profile",
        )
        _version(value)
        raw_matrix = value.get("transform_4x4")
        if not isinstance(raw_matrix, Sequence) or len(raw_matrix) != 4:
            raise ValueError("transform_4x4 must contain four rows")
        matrix = []
        for row_index, row in enumerate(raw_matrix):
            if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != 4:
                raise ValueError(f"transform_4x4[{row_index}] must contain four numbers")
            matrix.append(
                tuple(
                    _finite_number(item, f"transform_4x4[{row_index}]")
                    for item in row
                )
            )
        ensure_on_bed = value.get("ensure_on_bed")
        if not isinstance(ensure_on_bed, bool):
            raise ValueError("ensure_on_bed must be a boolean")
        return cls(
            orientation_id=_text(value.get("orientation_id"), "orientation_id"),
            name=_text(value.get("name"), "name"),
            status=_text(value.get("status"), "status"),
            source_up_axis=_text(value.get("source_up_axis"), "source_up_axis"),
            transform_4x4=tuple(matrix),
            placement=_text(value.get("placement"), "placement"),
            ensure_on_bed=ensure_on_bed,
            claim_boundary=_text(value.get("claim_boundary"), "claim_boundary"),
        )

    def is_identity(self) -> bool:
        expected = tuple(
            tuple(1.0 if row == column else 0.0 for column in range(4)) for row in range(4)
        )
        return self.transform_4x4 == expected

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "orientation_id": self.orientation_id,
            "name": self.name,
            "status": self.status,
            "source_up_axis": self.source_up_axis,
            "transform_4x4": [list(row) for row in self.transform_4x4],
            "placement": self.placement,
            "ensure_on_bed": self.ensure_on_bed,
            "claim_boundary": self.claim_boundary,
        }


def read_prusaslicer_ini(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError(f"invalid PrusaSlicer config line {line_number}")
        normalized = key.strip()
        if normalized in values:
            raise ValueError(f"duplicate PrusaSlicer config key {normalized!r}")
        values[normalized] = value.strip()
    return values


def _config_number(values: Mapping[str, str], key: str) -> float:
    raw = _text(values.get(key), f"PrusaSlicer {key}")
    return _number(raw.removesuffix("%"), f"PrusaSlicer {key}", allow_zero=True)


@dataclass(frozen=True)
class ProfileBundle:
    printer: PrinterProfile
    material: MaterialProfile
    process: ProcessProfile
    orientation: OrientationProfile
    slicer_config_path: Path
    source_paths: tuple[Path, ...]

    @classmethod
    def from_paths(
        cls,
        *,
        printer_path: Path,
        material_path: Path,
        process_path: Path,
        orientation_path: Path,
        slicer_config_path: Path,
    ) -> "ProfileBundle":
        paths = tuple(
            path.resolve()
            for path in (
                printer_path,
                material_path,
                process_path,
                orientation_path,
                slicer_config_path,
            )
        )
        if any(not path.is_file() for path in paths):
            raise FileNotFoundError("every profile bundle path must be an existing file")
        bundle = cls(
            printer=PrinterProfile.from_mapping(_load_json(paths[0])),
            material=MaterialProfile.from_mapping(_load_json(paths[1])),
            process=ProcessProfile.from_mapping(_load_json(paths[2])),
            orientation=OrientationProfile.from_mapping(_load_json(paths[3])),
            slicer_config_path=paths[4],
            source_paths=paths,
        )
        bundle.validate()
        return bundle

    def validate(self) -> tuple[dict[str, Any], ...]:
        if not isclose(
            self.printer.filament_diameter_mm,
            self.material.filament_diameter_mm,
            abs_tol=1e-9,
        ):
            raise ValueError("printer and material filament diameters do not match")
        if self.material.selected_nozzle_temperature_c > self.printer.maximum_nozzle_temperature_c:
            raise ValueError("material nozzle temperature exceeds printer maximum")
        if self.material.first_layer_nozzle_temperature_c > self.printer.maximum_nozzle_temperature_c:
            raise ValueError("material first-layer nozzle temperature exceeds printer maximum")
        if self.material.selected_bed_temperature_c > self.printer.maximum_bed_temperature_c:
            raise ValueError("material bed temperature exceeds printer maximum")
        if self.material.first_layer_bed_temperature_c > self.printer.maximum_bed_temperature_c:
            raise ValueError("material first-layer bed temperature exceeds printer maximum")
        if self.orientation.source_up_axis != "Z" or not self.orientation.is_identity():
            raise ValueError("the first adapter supports only identity Z-up orientation")
        if self.orientation.placement != "center_xy" or not self.orientation.ensure_on_bed:
            raise ValueError("the first adapter requires centered, ensure-on-bed placement")

        values = read_prusaslicer_ini(self.slicer_config_path)
        expected_bed = ",".join(
            f"{point[0]:g}x{point[1]:g}" for point in self.printer.bed_shape_mm
        )
        checks: list[tuple[str, bool, Any, Any]] = [
            ("bed_shape", values.get("bed_shape") == expected_bed, values.get("bed_shape"), expected_bed),
            ("build_height", isclose(_config_number(values, "max_print_height"), self.printer.build_volume_mm[2]), values.get("max_print_height"), self.printer.build_volume_mm[2]),
            ("nozzle", isclose(_config_number(values, "nozzle_diameter"), self.printer.nozzle_diameter_mm), values.get("nozzle_diameter"), self.printer.nozzle_diameter_mm),
            ("filament_diameter", isclose(_config_number(values, "filament_diameter"), self.material.filament_diameter_mm), values.get("filament_diameter"), self.material.filament_diameter_mm),
            ("firmware", values.get("gcode_flavor") == self.printer.firmware_flavor, values.get("gcode_flavor"), self.printer.firmware_flavor),
            ("filament_type", values.get("filament_type") == self.material.material_type, values.get("filament_type"), self.material.material_type),
            ("nozzle_temperature", isclose(_config_number(values, "temperature"), self.material.selected_nozzle_temperature_c), values.get("temperature"), self.material.selected_nozzle_temperature_c),
            ("first_layer_nozzle_temperature", isclose(_config_number(values, "first_layer_temperature"), self.material.first_layer_nozzle_temperature_c), values.get("first_layer_temperature"), self.material.first_layer_nozzle_temperature_c),
            ("bed_temperature", isclose(_config_number(values, "bed_temperature"), self.material.selected_bed_temperature_c), values.get("bed_temperature"), self.material.selected_bed_temperature_c),
            ("first_layer_bed_temperature", isclose(_config_number(values, "first_layer_bed_temperature"), self.material.first_layer_bed_temperature_c), values.get("first_layer_bed_temperature"), self.material.first_layer_bed_temperature_c),
            ("density", isclose(_config_number(values, "filament_density"), self.material.density_g_cm3), values.get("filament_density"), self.material.density_g_cm3),
            ("maximum_volumetric_speed", isclose(_config_number(values, "filament_max_volumetric_speed"), self.material.maximum_volumetric_speed_mm3_s), values.get("filament_max_volumetric_speed"), self.material.maximum_volumetric_speed_mm3_s),
            ("minimum_fan_speed", isclose(_config_number(values, "min_fan_speed"), self.material.fan_percent[0]), values.get("min_fan_speed"), self.material.fan_percent[0]),
            ("maximum_fan_speed", isclose(_config_number(values, "max_fan_speed"), self.material.fan_percent[1]), values.get("max_fan_speed"), self.material.fan_percent[1]),
            ("layer_height", isclose(_config_number(values, "layer_height"), self.process.layer_height_mm), values.get("layer_height"), self.process.layer_height_mm),
            ("first_layer_height", isclose(_config_number(values, "first_layer_height"), self.process.first_layer_height_mm), values.get("first_layer_height"), self.process.first_layer_height_mm),
            ("perimeters", isclose(_config_number(values, "perimeters"), self.process.perimeters), values.get("perimeters"), self.process.perimeters),
            ("top_solid_layers", isclose(_config_number(values, "top_solid_layers"), self.process.top_solid_layers), values.get("top_solid_layers"), self.process.top_solid_layers),
            ("bottom_solid_layers", isclose(_config_number(values, "bottom_solid_layers"), self.process.bottom_solid_layers), values.get("bottom_solid_layers"), self.process.bottom_solid_layers),
            ("infill", isclose(_config_number(values, "fill_density"), self.process.infill_percent), values.get("fill_density"), self.process.infill_percent),
            ("infill_pattern", values.get("fill_pattern") == self.process.infill_pattern, values.get("fill_pattern"), self.process.infill_pattern),
            ("skirts", isclose(_config_number(values, "skirts"), self.process.skirts), values.get("skirts"), self.process.skirts),
            ("brim", isclose(_config_number(values, "brim_width"), self.process.brim_width_mm), values.get("brim_width"), self.process.brim_width_mm),
        ]
        support_expected = {"disabled": 0.0, "enabled": 1.0, "build_plate_only": 1.0}[
            self.process.support_policy
        ]
        checks.append(
            (
                "support_policy",
                isclose(_config_number(values, "support_material"), support_expected),
                values.get("support_material"),
                support_expected,
            )
        )
        for name, expected in self.process.speeds_mm_s.items():
            key = name + "_speed"
            checks.append(
                (
                    f"speed_{name}",
                    isclose(_config_number(values, key), expected),
                    values.get(key),
                    expected,
                )
            )
        failed = [name for name, passed, _, _ in checks if not passed]
        if failed:
            raise ValueError("PrusaSlicer profile differs from contracts: " + ", ".join(failed))
        return tuple(
            {
                "check_id": name,
                "passed": passed,
                "actual": actual,
                "expected": expected,
            }
            for name, passed, actual, expected in checks
        )

    def to_dict(self, *, relative_to: Path | None = None) -> dict[str, Any]:
        base = relative_to.resolve() if relative_to is not None else None

        def display_path(path: Path) -> str:
            if base is None:
                return path.as_posix()
            try:
                return Path(os.path.relpath(path, start=base)).as_posix()
            except ValueError:
                return path.as_posix()

        return {
            "schema_version": PROFILE_CONTRACT_VERSION,
            "printer": self.printer.to_dict(),
            "material": self.material.to_dict(),
            "process": self.process.to_dict(),
            "orientation": self.orientation.to_dict(),
            "slicer_config": {
                "filename": self.slicer_config_path.name,
                "checksum_sha256": _sha256(self.slicer_config_path),
            },
            "source_files": [
                {
                    "path": display_path(path),
                    "size_bytes": path.stat().st_size,
                    "checksum_sha256": _sha256(path),
                }
                for path in self.source_paths
            ],
            "config_checks": list(self.validate()),
        }
