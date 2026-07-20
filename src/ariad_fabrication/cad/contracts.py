"""Versioned JSON contracts for the out-of-process CAD worker."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from uuid import uuid4


CAD_CONTRACT_VERSION = "1.0.0"


class CadArtifactFormat(str, Enum):
    JSON = "json"
    PYTHON = "python"
    STEP = "step"
    STL = "stl"
    THREEMF = "3mf"
    GLB = "glb"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required_text(value: Any, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _timestamp(value: Any, name: str) -> str:
    normalized = _required_text(value, name)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _freeze(value: Any) -> Any:
    if isinstance(value, Enum):
        return _freeze(value.value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("CAD contract data cannot contain non-finite numbers")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key)
            if normalized_key in normalized:
                raise ValueError(f"duplicate JSON key {normalized_key!r}")
            normalized[normalized_key] = _freeze(item)
        return MappingProxyType(normalized)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    raise ValueError(f"unsupported CAD contract value {type(value).__name__}")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _positive_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return number


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _relative_artifact_path(value: Any) -> str:
    normalized = _required_text(value, "artifact path")
    if "\\" in normalized:
        raise ValueError("CAD artifact path must use forward slashes")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or path == PurePosixPath(".")
        or ".." in path.parts
        or any(":" in part for part in path.parts)
    ):
        raise ValueError("CAD artifact path must be a safe relative path")
    return path.as_posix()


@dataclass(frozen=True)
class CadBuildRequest:
    job_id: str
    revision_id: str
    provider_id: str
    spec: Mapping[str, Any]
    expected: Mapping[str, Any]
    request_id: str = field(default_factory=lambda: f"cadreq_{uuid4().hex}")
    schema_version: str = CAD_CONTRACT_VERSION
    requested_formats: tuple[CadArtifactFormat, ...] = (
        CadArtifactFormat.STEP,
        CadArtifactFormat.STL,
        CadArtifactFormat.THREEMF,
        CadArtifactFormat.GLB,
    )
    linear_tolerance_mm: float = 0.02
    angular_tolerance_rad: float = 0.1

    def __post_init__(self) -> None:
        if self.schema_version != CAD_CONTRACT_VERSION:
            raise ValueError(f"unsupported CAD request schema {self.schema_version!r}")
        for name in ("request_id", "job_id", "revision_id", "provider_id"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        object.__setattr__(self, "spec", _freeze(self.spec))
        object.__setattr__(self, "expected", _freeze(self.expected))
        formats = tuple(CadArtifactFormat(item) for item in self.requested_formats)
        if not formats:
            raise ValueError("at least one CAD artifact format is required")
        if len(formats) != len(set(formats)):
            raise ValueError("requested CAD formats cannot contain duplicates")
        if CadArtifactFormat.STEP not in formats:
            raise ValueError("STEP is required as the exact geometry artifact")
        object.__setattr__(self, "requested_formats", formats)
        object.__setattr__(
            self,
            "linear_tolerance_mm",
            _positive_float(self.linear_tolerance_mm, "linear_tolerance_mm"),
        )
        object.__setattr__(
            self,
            "angular_tolerance_rad",
            _positive_float(self.angular_tolerance_rad, "angular_tolerance_rad"),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CadBuildRequest":
        if not isinstance(value, Mapping):
            raise ValueError("CAD request must be an object")
        return cls(
            schema_version=value.get("schema_version", CAD_CONTRACT_VERSION),
            request_id=value.get("request_id", f"cadreq_{uuid4().hex}"),
            job_id=value.get("job_id", ""),
            revision_id=value.get("revision_id", ""),
            provider_id=value.get("provider_id", ""),
            spec=value.get("spec", {}),
            expected=value.get("expected", {}),
            requested_formats=tuple(value.get("requested_formats", ("step",))),
            linear_tolerance_mm=value.get("linear_tolerance_mm", 0.02),
            angular_tolerance_rad=value.get("angular_tolerance_rad", 0.1),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "job_id": self.job_id,
            "revision_id": self.revision_id,
            "provider_id": self.provider_id,
            "spec": _thaw(self.spec),
            "expected": _thaw(self.expected),
            "requested_formats": [item.value for item in self.requested_formats],
            "linear_tolerance_mm": self.linear_tolerance_mm,
            "angular_tolerance_rad": self.angular_tolerance_rad,
        }


@dataclass(frozen=True)
class CadArtifactDescriptor:
    role: str
    path: str
    media_type: str
    format: CadArtifactFormat
    checksum_sha256: str
    size_bytes: int
    producer: str
    producer_version: str

    def __post_init__(self) -> None:
        for name in ("role", "media_type", "producer", "producer_version"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        object.__setattr__(self, "path", _relative_artifact_path(self.path))
        object.__setattr__(self, "format", CadArtifactFormat(self.format))
        checksum = _required_text(self.checksum_sha256, "checksum_sha256").lower()
        if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
            raise ValueError("checksum_sha256 must be 64 lowercase hexadecimal characters")
        object.__setattr__(self, "checksum_sha256", checksum)
        size = int(self.size_bytes)
        if isinstance(self.size_bytes, bool) or size < 0 or float(self.size_bytes) != size:
            raise ValueError("size_bytes must be a non-negative integer")
        object.__setattr__(self, "size_bytes", size)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CadArtifactDescriptor":
        return cls(
            role=value.get("role", ""),
            path=value.get("path", ""),
            media_type=value.get("media_type", ""),
            format=value.get("format", "json"),
            checksum_sha256=value.get("checksum_sha256", ""),
            size_bytes=value.get("size_bytes", -1),
            producer=value.get("producer", ""),
            producer_version=value.get("producer_version", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "path": self.path,
            "media_type": self.media_type,
            "format": self.format.value,
            "checksum_sha256": self.checksum_sha256,
            "size_bytes": self.size_bytes,
            "producer": self.producer,
            "producer_version": self.producer_version,
        }


@dataclass(frozen=True)
class CadBuildResult:
    request_id: str
    provider_id: str
    success: bool
    started_at: str
    completed_at: str
    artifacts: tuple[CadArtifactDescriptor, ...] = ()
    validation_passed: bool = False
    evidence_level: str | None = None
    tool_versions: Mapping[str, Any] = field(default_factory=dict)
    measurements: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    schema_version: str = CAD_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CAD_CONTRACT_VERSION:
            raise ValueError(f"unsupported CAD result schema {self.schema_version!r}")
        object.__setattr__(self, "request_id", _required_text(self.request_id, "request_id"))
        object.__setattr__(self, "provider_id", _required_text(self.provider_id, "provider_id"))
        object.__setattr__(self, "started_at", _timestamp(self.started_at, "started_at"))
        object.__setattr__(self, "completed_at", _timestamp(self.completed_at, "completed_at"))
        object.__setattr__(self, "success", _boolean(self.success, "success"))
        object.__setattr__(
            self,
            "validation_passed",
            _boolean(self.validation_passed, "validation_passed"),
        )
        artifacts = tuple(self.artifacts)
        if any(not isinstance(item, CadArtifactDescriptor) for item in artifacts):
            raise ValueError("artifacts must contain CadArtifactDescriptor records")
        paths = tuple(item.path for item in artifacts)
        if len(paths) != len(set(paths)):
            raise ValueError("CAD result artifact paths must be unique")
        roles = tuple(item.role for item in artifacts)
        if len(roles) != len(set(roles)):
            raise ValueError("CAD result artifact roles must be unique")
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "tool_versions", _freeze(self.tool_versions))
        object.__setattr__(self, "measurements", _freeze(self.measurements))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "errors", tuple(str(item) for item in self.errors))
        if self.success and self.errors:
            raise ValueError("successful CAD results cannot contain errors")
        if self.evidence_level not in {None, "R1", "R2"}:
            raise ValueError("CAD result evidence_level must be R1, R2, or null")
        if not self.success:
            if self.artifacts:
                raise ValueError("failed CAD results cannot publish artifacts")
            if self.validation_passed:
                raise ValueError("failed CAD results cannot pass geometry validation")
            if self.evidence_level is not None:
                raise ValueError("failed CAD results cannot claim an evidence level")
        else:
            if self.evidence_level is None:
                raise ValueError("successful CAD results must claim R1 or R2")
            if self.validation_passed != (self.evidence_level == "R2"):
                raise ValueError("R2 requires passed validation; an unverified design is R1")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CadBuildResult":
        if not isinstance(value, Mapping):
            raise ValueError("CAD result must be an object")
        raw_artifacts = value.get("artifacts", ())
        if not isinstance(raw_artifacts, Sequence) or isinstance(raw_artifacts, (str, bytes)):
            raise ValueError("CAD result artifacts must be an array")
        return cls(
            schema_version=value.get("schema_version", CAD_CONTRACT_VERSION),
            request_id=value.get("request_id", ""),
            provider_id=value.get("provider_id", ""),
            success=value.get("success", False),
            started_at=value.get("started_at", ""),
            completed_at=value.get("completed_at", ""),
            artifacts=tuple(CadArtifactDescriptor.from_mapping(item) for item in raw_artifacts),
            validation_passed=value.get("validation_passed", False),
            evidence_level=value.get("evidence_level"),
            tool_versions=value.get("tool_versions", {}),
            measurements=value.get("measurements", {}),
            warnings=tuple(value.get("warnings", ())),
            errors=tuple(value.get("errors", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "provider_id": self.provider_id,
            "success": self.success,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "validation_passed": self.validation_passed,
            "evidence_level": self.evidence_level,
            "tool_versions": _thaw(self.tool_versions),
            "measurements": _thaw(self.measurements),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }
