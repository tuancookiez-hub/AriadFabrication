"""Versioned manufacturing-intent contracts."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping, Sequence


SPEC_SCHEMA_VERSION = "1.0.0"


class SpecStatus(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"


class SupportPolicy(str, Enum):
    AVOID = "avoid"
    ALLOWED = "allowed"
    REQUIRED = "required"
    UNKNOWN = "unknown"


class SafetyClass(str, Enum):
    GENERAL = "general"
    CAUTION = "caution"
    SAFETY_CRITICAL = "safety_critical"


def _required_text(value: Any, name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _optional_float(value: Any, name: str, *, minimum: float | None = None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not isfinite(number):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return number


def _positive_optional_float(value: Any, name: str) -> float | None:
    number = _optional_float(value, name)
    if number is not None and number <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return number


def _integer(
    value: Any,
    name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        number = int(value)
        numeric_value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not isfinite(numeric_value) or numeric_value != number:
        raise ValueError(f"{name} must be an integer")
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return number


def _float_mapping(value: Mapping[str, Any] | None, name: str) -> Mapping[str, float]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    normalized: dict[str, float] = {}
    for raw_key, raw_value in value.items():
        key = _required_text(raw_key, f"{name} key")
        number = _optional_float(raw_value, f"{name}.{key}")
        if number is None:
            raise ValueError(f"{name}.{key} is required")
        normalized[key] = number
    return MappingProxyType(normalized)


def _strings(value: Sequence[Any] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        value = (value,)
    elif not isinstance(value, Sequence):
        raise ValueError("expected a list of strings")
    normalized = tuple(str(item).strip() for item in value if str(item).strip())
    return tuple(dict.fromkeys(normalized))


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _boolean(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    raise ValueError(f"{name} must be a boolean")


def _string_mapping(value: Mapping[str, Any] | None, name: str) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _required_text(raw_key, f"{name} key")
        normalized[key] = _required_text(raw_value, f"{name}.{key}")
    return MappingProxyType(normalized)


def _mapping_records(value: Any, name: str) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be an array")
    records = tuple(value)
    if any(not isinstance(item, Mapping) for item in records):
        raise ValueError(f"{name} must contain objects")
    return records


@dataclass(frozen=True)
class BoundingBox:
    length_mm: float
    width_mm: float
    height_mm: float

    def __post_init__(self) -> None:
        for name in ("length_mm", "width_mm", "height_mm"):
            value = _optional_float(getattr(self, name), name)
            if value is None or value <= 0:
                raise ValueError(f"{name} must be a finite value greater than zero")
            object.__setattr__(self, name, value)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | Sequence[Any]) -> "BoundingBox":
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, Mapping)):
            if len(value) != 3:
                raise ValueError("bounding box sequences must contain three values")
            return cls(float(value[0]), float(value[1]), float(value[2]))
        if not isinstance(value, Mapping):
            raise ValueError("bounding_box_mm must be an object or three-number list")
        return cls(
            length_mm=float(value.get("length", value.get("length_mm", 0))),
            width_mm=float(value.get("width", value.get("width_mm", 0))),
            height_mm=float(value.get("height", value.get("height_mm", 0))),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "length": self.length_mm,
            "width": self.width_mm,
            "height": self.height_mm,
        }


@dataclass(frozen=True)
class FeatureRequirement:
    feature_id: str
    kind: str
    quantity: int = 1
    dimensions_mm: Mapping[str, float] = field(default_factory=dict)
    tolerance_mm: float | None = None
    required: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature_id", _required_text(self.feature_id, "feature_id"))
        object.__setattr__(self, "kind", _required_text(self.kind, "feature kind"))
        object.__setattr__(self, "quantity", _integer(self.quantity, "feature quantity", minimum=1))
        dimensions = _float_mapping(self.dimensions_mm, "feature dimensions_mm")
        if any(value <= 0 for value in dimensions.values()):
            raise ValueError("feature dimensions must be greater than zero")
        object.__setattr__(self, "dimensions_mm", dimensions)
        object.__setattr__(
            self,
            "tolerance_mm",
            _positive_optional_float(self.tolerance_mm, "feature tolerance_mm"),
        )
        object.__setattr__(self, "notes", str(self.notes).strip())
        object.__setattr__(self, "required", _boolean(self.required, "feature required"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FeatureRequirement":
        return cls(
            feature_id=value.get("feature_id", value.get("id", "")),
            kind=value.get("kind", ""),
            quantity=value.get("quantity", 1),
            dimensions_mm=value.get("dimensions_mm", {}),
            tolerance_mm=value.get("tolerance_mm"),
            required=_boolean(value.get("required", True), "feature required"),
            notes=value.get("notes", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "kind": self.kind,
            "quantity": self.quantity,
            "dimensions_mm": dict(self.dimensions_mm),
            "tolerance_mm": self.tolerance_mm,
            "required": self.required,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class MatingRequirement:
    component: str
    interface: str
    nominal_dimensions_mm: Mapping[str, float]
    clearance_mm: float = 0.0
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "component", _required_text(self.component, "mating component"))
        object.__setattr__(self, "interface", _required_text(self.interface, "mating interface"))
        dimensions = _float_mapping(self.nominal_dimensions_mm, "nominal_dimensions_mm")
        if not dimensions or any(value <= 0 for value in dimensions.values()):
            raise ValueError("mating dimensions must contain positive values")
        object.__setattr__(self, "nominal_dimensions_mm", dimensions)
        object.__setattr__(
            self,
            "clearance_mm",
            _optional_float(self.clearance_mm, "clearance_mm", minimum=0.0) or 0.0,
        )
        object.__setattr__(self, "notes", str(self.notes).strip())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MatingRequirement":
        return cls(
            component=value.get("component", ""),
            interface=value.get("interface", ""),
            nominal_dimensions_mm=value.get("nominal_dimensions_mm", {}),
            clearance_mm=value.get("clearance_mm", 0.0),
            notes=value.get("notes", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "interface": self.interface,
            "nominal_dimensions_mm": dict(self.nominal_dimensions_mm),
            "clearance_mm": self.clearance_mm,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class LoadCase:
    name: str
    description: str
    force_n: float | None = None
    direction: str = "unspecified"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "load case name"))
        object.__setattr__(self, "description", _required_text(self.description, "load description"))
        object.__setattr__(self, "force_n", _optional_float(self.force_n, "force_n", minimum=0.0))
        object.__setattr__(self, "direction", _required_text(self.direction, "load direction"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LoadCase":
        return cls(
            name=value.get("name", ""),
            description=value.get("description", ""),
            force_n=value.get("force_n"),
            direction=value.get("direction", "unspecified"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "force_n": self.force_n,
            "direction": self.direction,
        }


@dataclass(frozen=True)
class EnvironmentSpec:
    location: str = "indoor"
    moisture_exposure: bool = False
    uv_exposure: bool = False
    min_temp_c: float | None = None
    max_temp_c: float | None = None
    food_contact: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "location", _required_text(self.location, "environment location"))
        object.__setattr__(
            self,
            "moisture_exposure",
            _boolean(self.moisture_exposure, "moisture_exposure"),
        )
        object.__setattr__(self, "uv_exposure", _boolean(self.uv_exposure, "uv_exposure"))
        object.__setattr__(self, "food_contact", _boolean(self.food_contact, "food_contact"))
        minimum = _optional_float(self.min_temp_c, "min_temp_c")
        maximum = _optional_float(self.max_temp_c, "max_temp_c")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("min_temp_c cannot exceed max_temp_c")
        object.__setattr__(self, "min_temp_c", minimum)
        object.__setattr__(self, "max_temp_c", maximum)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "EnvironmentSpec":
        value = value or {}
        if not isinstance(value, Mapping):
            raise ValueError("environment must be an object")
        return cls(
            location=value.get("location", "indoor"),
            moisture_exposure=_boolean(
                value.get("moisture_exposure", False), "moisture_exposure"
            ),
            uv_exposure=_boolean(value.get("uv_exposure", False), "uv_exposure"),
            min_temp_c=value.get("min_temp_c"),
            max_temp_c=value.get("max_temp_c"),
            food_contact=_boolean(value.get("food_contact", False), "food_contact"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "location": self.location,
            "moisture_exposure": self.moisture_exposure,
            "uv_exposure": self.uv_exposure,
            "min_temp_c": self.min_temp_c,
            "max_temp_c": self.max_temp_c,
            "food_contact": self.food_contact,
        }


@dataclass(frozen=True)
class PrinterConstraints:
    profile_id: str
    build_volume_mm: BoundingBox
    nozzle_diameter_mm: float
    layer_height_mm: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _required_text(self.profile_id, "printer profile_id"))
        nozzle = _optional_float(self.nozzle_diameter_mm, "nozzle_diameter_mm", minimum=0.01)
        layer = _optional_float(self.layer_height_mm, "layer_height_mm", minimum=0.01)
        if nozzle is None:
            raise ValueError("nozzle_diameter_mm is required")
        if layer is not None and nozzle is not None and layer > nozzle:
            raise ValueError("layer_height_mm cannot exceed nozzle_diameter_mm")
        object.__setattr__(self, "nozzle_diameter_mm", nozzle)
        object.__setattr__(self, "layer_height_mm", layer)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "PrinterConstraints | None":
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValueError("printer_constraints must be an object or null")
        return cls(
            profile_id=value.get("profile_id", ""),
            build_volume_mm=BoundingBox.from_mapping(value.get("build_volume_mm", {})),
            nozzle_diameter_mm=value.get("nozzle_diameter_mm", 0),
            layer_height_mm=value.get("layer_height_mm"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "build_volume_mm": self.build_volume_mm.to_dict(),
            "nozzle_diameter_mm": self.nozzle_diameter_mm,
            "layer_height_mm": self.layer_height_mm,
        }


@dataclass(frozen=True)
class PartSpec:
    """Versioned, immutable representation of manufacturing intent."""

    name: str
    purpose: str
    part_type: str
    bounding_box: BoundingBox
    material: str
    status: SpecStatus = SpecStatus.DRAFT
    schema_version: str = SPEC_SCHEMA_VERSION
    units: str = "mm"
    manufacturing_process: str = "FDM"
    tolerance_mm: float | None = None
    infill_pct: int = 20
    support_policy: SupportPolicy = SupportPolicy.UNKNOWN
    safety_class: SafetyClass = SafetyClass.GENERAL
    features: tuple[FeatureRequirement, ...] = ()
    mating_requirements: tuple[MatingRequirement, ...] = ()
    load_cases: tuple[LoadCase, ...] = ()
    environment: EnvironmentSpec = field(default_factory=EnvironmentSpec)
    printer_constraints: PrinterConstraints | None = None
    datums: Mapping[str, str] = field(default_factory=dict)
    assembly_method: str | None = None
    expected_lifetime_months: int | None = None
    preferred_orientation: str | None = None
    surface_requirements: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    notes: str = ""
    source: str = "user"

    def __post_init__(self) -> None:
        if self.schema_version != SPEC_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported PartSpec schema_version {self.schema_version!r}; "
                f"expected {SPEC_SCHEMA_VERSION!r}"
            )
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        object.__setattr__(self, "purpose", _required_text(self.purpose, "purpose"))
        object.__setattr__(self, "part_type", _required_text(self.part_type, "part_type"))
        if not isinstance(self.bounding_box, BoundingBox):
            raise ValueError("bounding_box must be a BoundingBox")
        object.__setattr__(self, "material", _required_text(self.material, "material").upper())
        units = _required_text(self.units, "units").lower()
        if units != "mm":
            raise ValueError("PartSpec 1.0.0 supports millimetres only")
        object.__setattr__(self, "units", units)
        object.__setattr__(
            self,
            "manufacturing_process",
            _required_text(self.manufacturing_process, "manufacturing_process").upper(),
        )
        object.__setattr__(self, "status", SpecStatus(self.status))
        object.__setattr__(self, "support_policy", SupportPolicy(self.support_policy))
        object.__setattr__(self, "safety_class", SafetyClass(self.safety_class))
        object.__setattr__(
            self,
            "tolerance_mm",
            _positive_optional_float(self.tolerance_mm, "tolerance_mm"),
        )
        object.__setattr__(
            self,
            "infill_pct",
            _integer(self.infill_pct, "infill_pct", minimum=0, maximum=100),
        )
        features = tuple(self.features)
        mating_requirements = tuple(self.mating_requirements)
        load_cases = tuple(self.load_cases)
        if any(not isinstance(item, FeatureRequirement) for item in features):
            raise ValueError("features must contain FeatureRequirement records")
        if any(not isinstance(item, MatingRequirement) for item in mating_requirements):
            raise ValueError("mating_requirements must contain MatingRequirement records")
        if any(not isinstance(item, LoadCase) for item in load_cases):
            raise ValueError("load_cases must contain LoadCase records")
        if not isinstance(self.environment, EnvironmentSpec):
            raise ValueError("environment must be an EnvironmentSpec")
        if self.printer_constraints is not None and not isinstance(
            self.printer_constraints, PrinterConstraints
        ):
            raise ValueError("printer_constraints must be PrinterConstraints or None")
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "mating_requirements", mating_requirements)
        object.__setattr__(self, "load_cases", load_cases)
        object.__setattr__(self, "datums", _string_mapping(self.datums, "datums"))
        object.__setattr__(self, "assembly_method", _optional_text(self.assembly_method))
        if self.expected_lifetime_months is not None:
            lifetime = _integer(
                self.expected_lifetime_months,
                "expected_lifetime_months",
                minimum=1,
            )
            object.__setattr__(self, "expected_lifetime_months", lifetime)
        object.__setattr__(self, "preferred_orientation", _optional_text(self.preferred_orientation))
        object.__setattr__(self, "surface_requirements", _strings(self.surface_requirements))
        object.__setattr__(self, "assumptions", _strings(self.assumptions))
        object.__setattr__(self, "unresolved_questions", _strings(self.unresolved_questions))
        object.__setattr__(self, "notes", str(self.notes).strip())
        object.__setattr__(self, "source", _required_text(self.source, "source"))
        if self.status is SpecStatus.CONFIRMED:
            issues = self.readiness_issues()
            if issues:
                raise ValueError("a confirmed PartSpec must be design-ready: " + "; ".join(issues))

    @property
    def dimensions_mm(self) -> dict[str, float]:
        """Compatibility view used by the current mesh and slicer fixtures."""

        return self.bounding_box.to_dict()

    @property
    def supports(self) -> bool:
        return self.support_policy is SupportPolicy.REQUIRED

    def validate(self) -> None:
        """Compatibility hook; construction already performs structural validation."""

    def readiness_issues(self) -> tuple[str, ...]:
        issues: list[str] = []
        if self.status is not SpecStatus.CONFIRMED:
            issues.append("specification requires explicit confirmation")
        issues.extend(self.unresolved_questions)
        unresolved_text = " ".join(self.unresolved_questions).lower()
        if self.tolerance_mm is None and "tolerance" not in unresolved_text:
            issues.append("a default or critical tolerance must be confirmed")
        if self.material in {"UNKNOWN", "UNSPECIFIED"} and "material" not in unresolved_text:
            issues.append("material must be confirmed")
        if self.support_policy is SupportPolicy.UNKNOWN and "support" not in unresolved_text:
            issues.append("support policy must be confirmed")
        return tuple(dict.fromkeys(issues))

    def assert_ready_for_design(self) -> None:
        issues = self.readiness_issues()
        if issues:
            raise ValueError("PartSpec is not ready for design: " + "; ".join(issues))

    def confirm(self) -> "PartSpec":
        issues = tuple(
            issue
            for issue in self.readiness_issues()
            if issue != "specification requires explicit confirmation"
        )
        if issues:
            raise ValueError("cannot confirm PartSpec: " + "; ".join(issues))
        return replace(self, status=SpecStatus.CONFIRMED)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PartSpec":
        if not isinstance(value, Mapping):
            raise ValueError("PartSpec input must be an object")
        part_type = str(value.get("part_type", "")).strip()
        notes = str(value.get("notes", "")).strip()
        box_value = value.get("bounding_box_mm", value.get("dimensions_mm"))
        if box_value is None:
            raise ValueError("bounding_box_mm is required")

        raw_features = _mapping_records(value.get("features", ()), "features")
        raw_mating = _mapping_records(
            value.get("mating_requirements", ()), "mating_requirements"
        )
        raw_loads = _mapping_records(value.get("load_cases", ()), "load_cases")
        support_value = value.get("support_policy")
        if support_value is None and "supports" in value:
            support_value = (
                SupportPolicy.REQUIRED.value
                if _boolean(value.get("supports"), "supports")
                else SupportPolicy.AVOID.value
            )

        return cls(
            schema_version=str(value.get("schema_version", SPEC_SCHEMA_VERSION)),
            name=value.get("name", part_type or "custom part"),
            purpose=value.get("purpose", notes or part_type or "custom fabrication part"),
            part_type=part_type,
            bounding_box=BoundingBox.from_mapping(box_value),
            material=value.get("material", "UNKNOWN"),
            status=SpecStatus(value.get("status", SpecStatus.DRAFT.value)),
            units=value.get("units", "mm"),
            manufacturing_process=value.get("manufacturing_process", "FDM"),
            tolerance_mm=value.get("tolerance_mm"),
            infill_pct=value.get("infill_pct", 20),
            support_policy=SupportPolicy(support_value or SupportPolicy.UNKNOWN.value),
            safety_class=SafetyClass(value.get("safety_class", SafetyClass.GENERAL.value)),
            features=tuple(FeatureRequirement.from_mapping(item) for item in raw_features),
            mating_requirements=tuple(MatingRequirement.from_mapping(item) for item in raw_mating),
            load_cases=tuple(LoadCase.from_mapping(item) for item in raw_loads),
            environment=EnvironmentSpec.from_mapping(value.get("environment")),
            printer_constraints=PrinterConstraints.from_mapping(value.get("printer_constraints")),
            datums=value.get("datums", {}),
            assembly_method=value.get("assembly_method"),
            expected_lifetime_months=value.get("expected_lifetime_months"),
            preferred_orientation=value.get("preferred_orientation"),
            surface_requirements=_strings(value.get("surface_requirements")),
            assumptions=_strings(value.get("assumptions")),
            unresolved_questions=_strings(value.get("unresolved_questions")),
            notes=notes,
            source=value.get("source", "user"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "name": self.name,
            "purpose": self.purpose,
            "part_type": self.part_type,
            "bounding_box_mm": self.bounding_box.to_dict(),
            "material": self.material,
            "units": self.units,
            "manufacturing_process": self.manufacturing_process,
            "tolerance_mm": self.tolerance_mm,
            "infill_pct": self.infill_pct,
            "support_policy": self.support_policy.value,
            "safety_class": self.safety_class.value,
            "features": [item.to_dict() for item in self.features],
            "mating_requirements": [item.to_dict() for item in self.mating_requirements],
            "load_cases": [item.to_dict() for item in self.load_cases],
            "environment": self.environment.to_dict(),
            "printer_constraints": (
                self.printer_constraints.to_dict() if self.printer_constraints else None
            ),
            "datums": dict(self.datums),
            "assembly_method": self.assembly_method,
            "expected_lifetime_months": self.expected_lifetime_months,
            "preferred_orientation": self.preferred_orientation,
            "surface_requirements": list(self.surface_requirements),
            "assumptions": list(self.assumptions),
            "unresolved_questions": list(self.unresolved_questions),
            "notes": self.notes,
            "source": self.source,
        }
