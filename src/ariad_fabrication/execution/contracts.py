"""Frozen no-hardware execution records and pure lifecycle operations.

This module defines the control-plane contract that a future local job runner
must satisfy.  It does not launch CAD, slicer, browser, or hardware processes.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import json
from math import isfinite
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from uuid import uuid4

from ..schema_validation import (
    EXECUTION_EVENT_SCHEMA,
    EXECUTION_RECORD_SCHEMA,
    EXECUTION_REQUEST_SCHEMA,
    validate_persisted_instance,
)


EXECUTION_SCHEMA_VERSION = "1.0.0"
POLICY_VERSION = "1.0.0"
GOLDEN_PART_BENCHMARK_ID = "opengrow_stake_electronics_clamp_v1"
GOLDEN_PART_PROVIDER_ID = GOLDEN_PART_BENCHMARK_ID
CAD_WORKER_VERSION = "1.0.0"
CADQUERY_VERSION = "2.8.0"
OCP_VERSION = "7.9.3.1.1"
PRINTABILITY_VALIDATOR_VERSION = "1.0.0"
FABRICATION_PIPELINE_VERSION = "1.0.0"
EXECUTION_CLAIM_BOUNDARY = (
    "Digital execution only. No printer was selected or contacted, no G-code was "
    "uploaded, and no physical action occurred. Success records only the requested "
    "R2 or R4 software evidence gate."
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ID_PATTERNS = {
    "execution_id": re.compile(r"^exec_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"),
    "event_id": re.compile(r"^exevt_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"),
    "job_id": re.compile(r"^job_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"),
    "revision_id": re.compile(r"^rev_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"),
    "runner_instance_id": re.compile(
        r"^runner_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
    ),
    "detail_artifact_id": re.compile(
        r"^art_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
    ),
}


class ExecutionTarget(str, Enum):
    GOLDEN_PART_R2 = "golden_part_r2"
    GOLDEN_PART_R4 = "golden_part_r4"


class ExecutionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLATION_REQUESTED = "cancellation_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class ExecutionEventType(str, Enum):
    REQUEST_ACCEPTED = "request_accepted"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_IDENTITY_BOUND = "execution_identity_bound"
    STAGE_SNAPSHOT_PERSISTED = "stage_snapshot_persisted"
    CANCELLATION_REQUESTED = "cancellation_requested"
    EXECUTION_SUCCEEDED = "execution_succeeded"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_CANCELLED = "execution_cancelled"
    EXECUTION_INTERRUPTED = "execution_interrupted"


class ExecutionFailureCode(str, Enum):
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    INPUT_INTEGRITY_FAILED = "input_integrity_failed"
    WORKER_TIMEOUT = "worker_timeout"
    RESOURCE_LIMIT = "resource_limit"
    STAGE_FAILED = "stage_failed"
    PERSISTENCE_FAILED = "persistence_failed"
    CANCELLATION_TIMEOUT = "cancellation_timeout"
    RUNNER_INTERRUPTED = "runner_interrupted"
    INTERNAL_ERROR = "internal_error"


class ExecutionStage(str, Enum):
    BRIEF = "brief"
    DESIGN = "design"
    GEOMETRY_VALIDATION = "geometry_validation"
    PRINTABILITY_VALIDATION = "printability_validation"
    SLICING = "slicing"
    FABRICATION_PACKAGE = "fabrication_package"


class AdmissionDecision(str, Enum):
    ACCEPT = "accept"
    IDEMPOTENT_REPLAY = "idempotent_replay"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    REQUEST_TOO_LARGE = "request_too_large"
    QUEUE_FULL = "queue_full"


class ExecutionTransitionError(ValueError):
    """The requested execution lifecycle operation is not legal."""


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _required_text(value: Any, name: str, *, maximum: int | None = None) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    if maximum is not None and len(normalized) > maximum:
        raise ValueError(f"{name} cannot exceed {maximum} characters")
    return normalized


def _strict_integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _strict_boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _enum_value(value: Any, enum_type: type[Enum], name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"unsupported {name} {value!r}") from exc


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _identifier(value: Any, name: str) -> str:
    normalized = _required_text(value, name)
    pattern = _ID_PATTERNS[name]
    if not pattern.fullmatch(normalized):
        raise ValueError(f"{name} has an invalid format")
    return normalized


def _optional_identifier(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, name)


def _timestamp_value(value: str | datetime, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        normalized = _required_text(value, name)
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    else:
        raise ValueError(f"{name} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _timestamp(value: str | datetime, name: str) -> str:
    return _timestamp_value(value, name).isoformat()


def _optional_timestamp(value: str | datetime | None, name: str) -> str | None:
    if value is None:
        return None
    return _timestamp(value, name)


def _exact_keys(value: Any, expected: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    keys = set(value)
    if any(not isinstance(key, str) for key in keys):
        raise ValueError(f"{name} keys must be strings")
    missing = expected - keys
    extra = keys - expected
    if missing:
        raise ValueError(f"{name} is missing {sorted(missing)[0]!r}")
    if extra:
        raise ValueError(f"{name} contains unsupported field {sorted(extra)[0]!r}")
    return value


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if value is None or type(value) in {str, bool, int}:
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("event data cannot contain non-finite numbers")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("event data keys must be strings")
            if len(key) > 128:
                raise ValueError("event data keys cannot exceed 128 characters")
            if key == "progress_percent":
                raise ValueError("execution events cannot invent progress_percent")
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError(f"event data contains unsupported value {type(value).__name__}")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _json_shape(value: Any, *, max_depth: int, max_nodes: int) -> None:
    nodes = 0
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes:
            raise ValueError(f"event data cannot exceed {max_nodes} JSON nodes")
        if depth > max_depth:
            raise ValueError(f"event data cannot exceed depth {max_depth}")
        if isinstance(item, Mapping):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, tuple):
            stack.extend((child, depth + 1) for child in item)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class ExecutionRequest:
    idempotency_key: str
    target: ExecutionTarget
    schema_version: str = EXECUTION_SCHEMA_VERSION
    benchmark_id: str = GOLDEN_PART_BENCHMARK_ID
    requested_by: str = "local_user"
    hardware_actions: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_SCHEMA_VERSION:
            raise ValueError("unsupported execution request schema_version")
        key = _required_text(self.idempotency_key, "idempotency_key", maximum=128)
        if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
            raise ValueError("idempotency_key has an invalid format")
        object.__setattr__(self, "idempotency_key", key)
        object.__setattr__(
            self, "target", _enum_value(self.target, ExecutionTarget, "execution target")
        )
        if self.benchmark_id != GOLDEN_PART_BENCHMARK_ID:
            raise ValueError("only the frozen Golden Part benchmark may execute")
        if self.requested_by != "local_user":
            raise ValueError("requested_by must be local_user")
        if _strict_boolean(self.hardware_actions, "hardware_actions"):
            raise ValueError("hardware_actions must remain false")
        validate_persisted_instance(
            self._mapping(), EXECUTION_REQUEST_SCHEMA, record_name="execution request"
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "ExecutionRequest":
        validate_persisted_instance(
            value, EXECUTION_REQUEST_SCHEMA, record_name="execution request"
        )
        mapping = _exact_keys(
            value,
            {
                "schema_version",
                "idempotency_key",
                "target",
                "benchmark_id",
                "requested_by",
                "hardware_actions",
            },
            "execution request",
        )
        return cls(
            idempotency_key=mapping["idempotency_key"],
            target=mapping["target"],
            schema_version=mapping["schema_version"],
            benchmark_id=mapping["benchmark_id"],
            requested_by=mapping["requested_by"],
            hardware_actions=mapping["hardware_actions"],
        )

    def _mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "idempotency_key": self.idempotency_key,
            "target": self.target.value,
            "benchmark_id": self.benchmark_id,
            "requested_by": self.requested_by,
            "hardware_actions": self.hardware_actions,
        }

    def to_dict(self) -> dict[str, Any]:
        return self._mapping()

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self._mapping())

    def canonical_sha256(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class R4ProfileSnapshot:
    printer_profile_sha256: str
    material_profile_sha256: str
    process_profile_sha256: str
    orientation_sha256: str
    slicer_config_sha256: str
    printer_profile_id: str = "generic_open_fdm_220_v1"
    material_profile_id: str = "generic_petg_175_v1"
    process_profile_id: str = "golden_part_020_no_support_v1"
    orientation_id: str = "upright_source_z_centered_v1"

    def __post_init__(self) -> None:
        expected_ids = {
            "printer_profile_id": "generic_open_fdm_220_v1",
            "material_profile_id": "generic_petg_175_v1",
            "process_profile_id": "golden_part_020_no_support_v1",
            "orientation_id": "upright_source_z_centered_v1",
        }
        for name, expected in expected_ids.items():
            if getattr(self, name) != expected:
                raise ValueError(f"{name} must be {expected!r}")
        for name in (
            "printer_profile_sha256",
            "material_profile_sha256",
            "process_profile_sha256",
            "orientation_sha256",
            "slicer_config_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))

    @classmethod
    def from_mapping(cls, value: Any) -> "R4ProfileSnapshot":
        names = {
            "printer_profile_id",
            "printer_profile_sha256",
            "material_profile_id",
            "material_profile_sha256",
            "process_profile_id",
            "process_profile_sha256",
            "orientation_id",
            "orientation_sha256",
            "slicer_config_sha256",
        }
        mapping = _exact_keys(value, names, "R4 profile snapshot")
        return cls(**{name: mapping[name] for name in names})

    def to_dict(self) -> dict[str, Any]:
        return {
            "printer_profile_id": self.printer_profile_id,
            "printer_profile_sha256": self.printer_profile_sha256,
            "material_profile_id": self.material_profile_id,
            "material_profile_sha256": self.material_profile_sha256,
            "process_profile_id": self.process_profile_id,
            "process_profile_sha256": self.process_profile_sha256,
            "orientation_id": self.orientation_id,
            "orientation_sha256": self.orientation_sha256,
            "slicer_config_sha256": self.slicer_config_sha256,
        }


@dataclass(frozen=True)
class SlicerSnapshot:
    executable_sha256: str
    adapter_id: str = "prusaslicer_cli"
    adapter_version: str = "1.0.0"
    slicer_version: str = "2.9.6"

    def __post_init__(self) -> None:
        expected = {
            "adapter_id": "prusaslicer_cli",
            "adapter_version": "1.0.0",
            "slicer_version": "2.9.6",
        }
        for name, value in expected.items():
            if getattr(self, name) != value:
                raise ValueError(f"{name} must be {value!r}")
        object.__setattr__(
            self,
            "executable_sha256",
            _sha256(self.executable_sha256, "executable_sha256"),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "SlicerSnapshot":
        names = {"adapter_id", "adapter_version", "slicer_version", "executable_sha256"}
        mapping = _exact_keys(value, names, "slicer snapshot")
        return cls(**{name: mapping[name] for name in names})

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "slicer_version": self.slicer_version,
            "executable_sha256": self.executable_sha256,
        }


@dataclass(frozen=True)
class CadRuntimeSnapshot:
    python_version: str
    python_executable_sha256: str
    cadquery_version: str = CADQUERY_VERSION
    ocp_version: str = OCP_VERSION

    def __post_init__(self) -> None:
        python_version = _required_text(
            self.python_version, "python_version", maximum=32
        )
        if not re.fullmatch(r"3\.11\.[0-9]+", python_version):
            raise ValueError("python_version must identify a CPython 3.11 patch release")
        object.__setattr__(self, "python_version", python_version)
        object.__setattr__(
            self,
            "python_executable_sha256",
            _sha256(self.python_executable_sha256, "python_executable_sha256"),
        )
        if self.cadquery_version != CADQUERY_VERSION:
            raise ValueError(f"cadquery_version must be {CADQUERY_VERSION!r}")
        if self.ocp_version != OCP_VERSION:
            raise ValueError(f"ocp_version must be {OCP_VERSION!r}")

    @classmethod
    def from_mapping(cls, value: Any) -> "CadRuntimeSnapshot":
        names = {
            "python_version",
            "python_executable_sha256",
            "cadquery_version",
            "ocp_version",
        }
        mapping = _exact_keys(value, names, "CAD runtime snapshot")
        return cls(**{name: mapping[name] for name in names})

    def to_dict(self) -> dict[str, Any]:
        return {
            "python_version": self.python_version,
            "python_executable_sha256": self.python_executable_sha256,
            "cadquery_version": self.cadquery_version,
            "ocp_version": self.ocp_version,
        }


@dataclass(frozen=True)
class ExecutionPlan:
    target: ExecutionTarget
    part_spec_sha256: str
    geometry_expectations_sha256: str
    cad_source_sha256: str
    dependency_lock_sha256: str
    cad_runtime: CadRuntimeSnapshot
    printability_validator_version: str | None = None
    fabrication_pipeline_version: str | None = None
    printability_expectations_sha256: str | None = None
    profiles: R4ProfileSnapshot | None = None
    slicer: SlicerSnapshot | None = None
    benchmark_id: str = GOLDEN_PART_BENCHMARK_ID
    provider_id: str = GOLDEN_PART_PROVIDER_ID
    cad_worker_version: str = CAD_WORKER_VERSION
    hardware_actions: bool = False

    def __post_init__(self) -> None:
        target = _enum_value(self.target, ExecutionTarget, "execution target")
        object.__setattr__(self, "target", target)
        if self.benchmark_id != GOLDEN_PART_BENCHMARK_ID:
            raise ValueError("execution plan benchmark_id is not approved")
        if self.provider_id != GOLDEN_PART_PROVIDER_ID:
            raise ValueError("execution plan provider_id is not approved")
        if self.cad_worker_version != CAD_WORKER_VERSION:
            raise ValueError("execution plan cad_worker_version is not approved")
        if not isinstance(self.cad_runtime, CadRuntimeSnapshot):
            raise ValueError("execution plan requires a CAD runtime snapshot")
        if _strict_boolean(self.hardware_actions, "hardware_actions"):
            raise ValueError("hardware_actions must remain false")
        object.__setattr__(
            self, "part_spec_sha256", _sha256(self.part_spec_sha256, "part_spec_sha256")
        )
        object.__setattr__(
            self,
            "cad_source_sha256",
            _sha256(self.cad_source_sha256, "cad_source_sha256"),
        )
        object.__setattr__(
            self,
            "dependency_lock_sha256",
            _sha256(self.dependency_lock_sha256, "dependency_lock_sha256"),
        )
        object.__setattr__(
            self,
            "geometry_expectations_sha256",
            _sha256(
                self.geometry_expectations_sha256,
                "geometry_expectations_sha256",
            ),
        )
        if target is ExecutionTarget.GOLDEN_PART_R2:
            if any(
                item is not None
                for item in (
                    self.printability_expectations_sha256,
                    self.printability_validator_version,
                    self.fabrication_pipeline_version,
                    self.profiles,
                    self.slicer,
                )
            ):
                raise ValueError("R2 execution plans cannot contain R4 identities")
        else:
            if self.printability_expectations_sha256 is None:
                raise ValueError("R4 execution plans require printability expectations")
            if self.printability_validator_version != PRINTABILITY_VALIDATOR_VERSION:
                raise ValueError("R4 execution plans require the approved printability validator")
            if self.fabrication_pipeline_version != FABRICATION_PIPELINE_VERSION:
                raise ValueError("R4 execution plans require the approved fabrication pipeline")
            object.__setattr__(
                self,
                "printability_expectations_sha256",
                _sha256(
                    self.printability_expectations_sha256,
                    "printability_expectations_sha256",
                ),
            )
            if not isinstance(self.profiles, R4ProfileSnapshot):
                raise ValueError("R4 execution plans require a profile snapshot")
            if not isinstance(self.slicer, SlicerSnapshot):
                raise ValueError("R4 execution plans require a slicer snapshot")

    @classmethod
    def from_mapping(cls, value: Any) -> "ExecutionPlan":
        names = {
            "target",
            "benchmark_id",
            "provider_id",
            "cad_worker_version",
            "cad_source_sha256",
            "dependency_lock_sha256",
            "cad_runtime",
            "part_spec_sha256",
            "geometry_expectations_sha256",
            "printability_validator_version",
            "fabrication_pipeline_version",
            "printability_expectations_sha256",
            "profiles",
            "slicer",
            "hardware_actions",
        }
        mapping = _exact_keys(value, names, "execution plan")
        return cls(
            target=mapping["target"],
            benchmark_id=mapping["benchmark_id"],
            provider_id=mapping["provider_id"],
            cad_worker_version=mapping["cad_worker_version"],
            cad_source_sha256=mapping["cad_source_sha256"],
            dependency_lock_sha256=mapping["dependency_lock_sha256"],
            cad_runtime=CadRuntimeSnapshot.from_mapping(mapping["cad_runtime"]),
            part_spec_sha256=mapping["part_spec_sha256"],
            geometry_expectations_sha256=mapping["geometry_expectations_sha256"],
            printability_validator_version=mapping[
                "printability_validator_version"
            ],
            fabrication_pipeline_version=mapping["fabrication_pipeline_version"],
            printability_expectations_sha256=mapping[
                "printability_expectations_sha256"
            ],
            profiles=(
                R4ProfileSnapshot.from_mapping(mapping["profiles"])
                if mapping["profiles"] is not None
                else None
            ),
            slicer=(
                SlicerSnapshot.from_mapping(mapping["slicer"])
                if mapping["slicer"] is not None
                else None
            ),
            hardware_actions=mapping["hardware_actions"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.value,
            "benchmark_id": self.benchmark_id,
            "provider_id": self.provider_id,
            "cad_worker_version": self.cad_worker_version,
            "cad_source_sha256": self.cad_source_sha256,
            "dependency_lock_sha256": self.dependency_lock_sha256,
            "cad_runtime": self.cad_runtime.to_dict(),
            "part_spec_sha256": self.part_spec_sha256,
            "geometry_expectations_sha256": self.geometry_expectations_sha256,
            "printability_validator_version": self.printability_validator_version,
            "fabrication_pipeline_version": self.fabrication_pipeline_version,
            "printability_expectations_sha256": self.printability_expectations_sha256,
            "profiles": self.profiles.to_dict() if self.profiles else None,
            "slicer": self.slicer.to_dict() if self.slicer else None,
            "hardware_actions": self.hardware_actions,
        }


_POLICY_VALUES: dict[str, Any] = {
    "policy_version": POLICY_VERSION,
    "max_request_bytes": 16 * 1024,
    "max_wall_seconds": 900,
    "cad_timeout_seconds": 120,
    "slicer_command_timeout_seconds": 180,
    "cancellation_grace_seconds": 10,
    "lease_seconds": 30,
    "heartbeat_seconds": 10,
    "max_events": 10_000,
    "max_event_data_bytes": 64 * 1024,
    "max_log_stream_bytes": 8 * 1024 * 1024,
    "max_workspace_bytes": 512 * 1024 * 1024,
    "max_memory_bytes": 4 * 1024 * 1024 * 1024,
    "max_child_processes": 1,
    "slicer_threads": 4,
    "max_active_executions": 1,
    "max_queued_executions": 4,
    "network_access": False,
    "hardware_actions": False,
    "automatic_resume": False,
}


@dataclass(frozen=True)
class RunnerPolicy:
    policy_version: str = POLICY_VERSION
    max_request_bytes: int = 16 * 1024
    max_wall_seconds: int = 900
    cad_timeout_seconds: int = 120
    slicer_command_timeout_seconds: int = 180
    cancellation_grace_seconds: int = 10
    lease_seconds: int = 30
    heartbeat_seconds: int = 10
    max_events: int = 10_000
    max_event_data_bytes: int = 64 * 1024
    max_log_stream_bytes: int = 8 * 1024 * 1024
    max_workspace_bytes: int = 512 * 1024 * 1024
    max_memory_bytes: int = 4 * 1024 * 1024 * 1024
    max_child_processes: int = 1
    slicer_threads: int = 4
    max_active_executions: int = 1
    max_queued_executions: int = 4
    network_access: bool = False
    hardware_actions: bool = False
    automatic_resume: bool = False

    def __post_init__(self) -> None:
        for name, expected in _POLICY_VALUES.items():
            value = getattr(self, name)
            if type(value) is not type(expected) or value != expected:
                raise ValueError(f"runner policy {name} must remain {expected!r}")

    @classmethod
    def from_mapping(cls, value: Any) -> "RunnerPolicy":
        mapping = _exact_keys(value, set(_POLICY_VALUES), "runner policy")
        return cls(**{name: mapping[name] for name in _POLICY_VALUES})

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _POLICY_VALUES}


NO_HARDWARE_RUNNER_POLICY = RunnerPolicy()


@dataclass(frozen=True)
class ExecutionFailure:
    code: ExecutionFailureCode
    message: str
    retryable: bool
    stage: ExecutionStage | None = None
    detail_artifact_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "code", _enum_value(self.code, ExecutionFailureCode, "failure code")
        )
        object.__setattr__(
            self, "message", _required_text(self.message, "failure message", maximum=512)
        )
        object.__setattr__(self, "retryable", _strict_boolean(self.retryable, "retryable"))
        if self.stage is not None:
            object.__setattr__(
                self, "stage", _enum_value(self.stage, ExecutionStage, "failure stage")
            )
        object.__setattr__(
            self,
            "detail_artifact_id",
            _optional_identifier(self.detail_artifact_id, "detail_artifact_id"),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "ExecutionFailure":
        names = {"code", "message", "retryable", "stage", "detail_artifact_id"}
        mapping = _exact_keys(value, names, "execution failure")
        return cls(**{name: mapping[name] for name in names})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "stage": self.stage.value if self.stage else None,
            "detail_artifact_id": self.detail_artifact_id,
        }


@dataclass(frozen=True)
class ExecutionLease:
    runner_instance_id: str
    generation: int
    acquired_at: str
    heartbeat_at: str
    expires_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "runner_instance_id",
            _identifier(self.runner_instance_id, "runner_instance_id"),
        )
        object.__setattr__(
            self, "generation", _strict_integer(self.generation, "lease generation", minimum=1)
        )
        acquired = _timestamp(self.acquired_at, "lease acquired_at")
        heartbeat = _timestamp(self.heartbeat_at, "lease heartbeat_at")
        expires = _timestamp(self.expires_at, "lease expires_at")
        acquired_value = _timestamp_value(acquired, "lease acquired_at")
        heartbeat_value = _timestamp_value(heartbeat, "lease heartbeat_at")
        expires_value = _timestamp_value(expires, "lease expires_at")
        if heartbeat_value < acquired_value:
            raise ValueError("lease heartbeat_at cannot precede acquired_at")
        if expires_value != heartbeat_value + timedelta(seconds=30):
            raise ValueError("lease expires_at must be exactly 30 seconds after heartbeat_at")
        object.__setattr__(self, "acquired_at", acquired)
        object.__setattr__(self, "heartbeat_at", heartbeat)
        object.__setattr__(self, "expires_at", expires)

    @classmethod
    def acquire(
        cls,
        runner_instance_id: str,
        generation: int,
        *,
        at: str | datetime,
    ) -> "ExecutionLease":
        acquired = _timestamp(at, "lease acquired_at")
        expires = (
            _timestamp_value(acquired, "lease acquired_at") + timedelta(seconds=30)
        ).isoformat()
        return cls(
            runner_instance_id=runner_instance_id,
            generation=generation,
            acquired_at=acquired,
            heartbeat_at=acquired,
            expires_at=expires,
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "ExecutionLease":
        names = {
            "runner_instance_id",
            "generation",
            "acquired_at",
            "heartbeat_at",
            "expires_at",
        }
        mapping = _exact_keys(value, names, "execution lease")
        return cls(**{name: mapping[name] for name in names})

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner_instance_id": self.runner_instance_id,
            "generation": self.generation,
            "acquired_at": self.acquired_at,
            "heartbeat_at": self.heartbeat_at,
            "expires_at": self.expires_at,
        }


_TERMINAL_STATUSES = frozenset(
    {
        ExecutionStatus.SUCCEEDED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.INTERRUPTED,
    }
)
_ACTIVE_STATUSES = frozenset(
    {ExecutionStatus.RUNNING, ExecutionStatus.CANCELLATION_REQUESTED}
)


@dataclass(frozen=True)
class ExecutionRecord:
    request: ExecutionRequest
    plan: ExecutionPlan
    accepted_sequence: int
    accepted_at: str
    execution_id: str = field(default_factory=lambda: _new_id("exec"))
    request_sha256: str | None = None
    policy: RunnerPolicy = field(default_factory=RunnerPolicy)
    status: ExecutionStatus = ExecutionStatus.QUEUED
    started_at: str | None = None
    cancellation_requested_at: str | None = None
    completed_at: str | None = None
    job_id: str | None = None
    revision_id: str | None = None
    lease: ExecutionLease | None = None
    failure: ExecutionFailure | None = None
    hardware_actions: bool = False
    physical_evidence: bool = False
    claim_boundary: str = EXECUTION_CLAIM_BOUNDARY
    schema_version: str = EXECUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.request, ExecutionRequest):
            raise ValueError("execution record request must be an ExecutionRequest")
        if not isinstance(self.plan, ExecutionPlan):
            raise ValueError("execution record plan must be an ExecutionPlan")
        if not isinstance(self.policy, RunnerPolicy):
            raise ValueError("execution record policy must be a RunnerPolicy")
        if self.schema_version != EXECUTION_SCHEMA_VERSION:
            raise ValueError("unsupported execution record schema_version")
        if self.request.target is not self.plan.target:
            raise ValueError("execution request and plan targets must agree")
        if self.request.benchmark_id != self.plan.benchmark_id:
            raise ValueError("execution request and plan benchmarks must agree")
        object.__setattr__(
            self, "execution_id", _identifier(self.execution_id, "execution_id")
        )
        object.__setattr__(
            self,
            "accepted_sequence",
            _strict_integer(self.accepted_sequence, "accepted_sequence", minimum=1),
        )
        accepted = _timestamp(self.accepted_at, "accepted_at")
        object.__setattr__(self, "accepted_at", accepted)
        request_digest = self.request.canonical_sha256()
        if self.request_sha256 is None:
            object.__setattr__(self, "request_sha256", request_digest)
        else:
            digest = _sha256(self.request_sha256, "request_sha256")
            if digest != request_digest:
                raise ValueError("request_sha256 does not match the canonical request")
            object.__setattr__(self, "request_sha256", digest)
        status = _enum_value(self.status, ExecutionStatus, "execution status")
        object.__setattr__(self, "status", status)
        for name in ("started_at", "cancellation_requested_at", "completed_at"):
            object.__setattr__(
                self, name, _optional_timestamp(getattr(self, name), name)
            )
        object.__setattr__(self, "job_id", _optional_identifier(self.job_id, "job_id"))
        object.__setattr__(
            self,
            "revision_id",
            _optional_identifier(self.revision_id, "revision_id"),
        )
        if (self.job_id is None) != (self.revision_id is None):
            raise ValueError("job_id and revision_id must bind together")
        if self.lease is not None and not isinstance(self.lease, ExecutionLease):
            raise ValueError("execution record lease must be an ExecutionLease")
        if self.failure is not None and not isinstance(self.failure, ExecutionFailure):
            raise ValueError("execution record failure must be an ExecutionFailure")
        if _strict_boolean(self.hardware_actions, "hardware_actions"):
            raise ValueError("hardware_actions must remain false")
        if _strict_boolean(self.physical_evidence, "physical_evidence"):
            raise ValueError("physical_evidence must remain false")
        if self.claim_boundary != EXECUTION_CLAIM_BOUNDARY:
            raise ValueError("execution claim_boundary does not match the frozen boundary")
        if self.failure is not None:
            if (
                self.failure.code is ExecutionFailureCode.RUNNER_INTERRUPTED
                and self.status is not ExecutionStatus.INTERRUPTED
            ):
                raise ValueError("runner_interrupted is reserved for interrupted records")
            if (
                self.failure.code is ExecutionFailureCode.CANCELLATION_TIMEOUT
                and (
                    self.status is not ExecutionStatus.FAILED
                    or self.cancellation_requested_at is None
                )
            ):
                raise ValueError(
                    "cancellation_timeout requires a failed cancellation request"
                )
            if self.failure.detail_artifact_id is not None and self.job_id is None:
                raise ValueError("failure detail artifacts require a bound journey identity")
        self._validate_chronology()
        self._validate_state()
        validate_persisted_instance(
            self._mapping(), EXECUTION_RECORD_SCHEMA, record_name="execution record"
        )

    @classmethod
    def queued(
        cls,
        request: ExecutionRequest,
        plan: ExecutionPlan,
        *,
        accepted_sequence: int,
        accepted_at: str | datetime,
        execution_id: str | None = None,
        policy: RunnerPolicy = NO_HARDWARE_RUNNER_POLICY,
    ) -> "ExecutionRecord":
        values: dict[str, Any] = {
            "request": request,
            "plan": plan,
            "accepted_sequence": accepted_sequence,
            "accepted_at": accepted_at,
            "policy": policy,
        }
        if execution_id is not None:
            values["execution_id"] = execution_id
        return cls(**values)

    @classmethod
    def from_mapping(cls, value: Any) -> "ExecutionRecord":
        validate_persisted_instance(
            value, EXECUTION_RECORD_SCHEMA, record_name="execution record"
        )
        names = {
            "schema_version",
            "execution_id",
            "accepted_sequence",
            "request",
            "request_sha256",
            "plan",
            "policy",
            "status",
            "accepted_at",
            "started_at",
            "cancellation_requested_at",
            "completed_at",
            "job_id",
            "revision_id",
            "lease",
            "failure",
            "hardware_actions",
            "physical_evidence",
            "claim_boundary",
        }
        mapping = _exact_keys(value, names, "execution record")
        return cls(
            schema_version=mapping["schema_version"],
            execution_id=mapping["execution_id"],
            accepted_sequence=mapping["accepted_sequence"],
            request=ExecutionRequest.from_mapping(mapping["request"]),
            request_sha256=mapping["request_sha256"],
            plan=ExecutionPlan.from_mapping(mapping["plan"]),
            policy=RunnerPolicy.from_mapping(mapping["policy"]),
            status=mapping["status"],
            accepted_at=mapping["accepted_at"],
            started_at=mapping["started_at"],
            cancellation_requested_at=mapping["cancellation_requested_at"],
            completed_at=mapping["completed_at"],
            job_id=mapping["job_id"],
            revision_id=mapping["revision_id"],
            lease=(
                ExecutionLease.from_mapping(mapping["lease"])
                if mapping["lease"] is not None
                else None
            ),
            failure=(
                ExecutionFailure.from_mapping(mapping["failure"])
                if mapping["failure"] is not None
                else None
            ),
            hardware_actions=mapping["hardware_actions"],
            physical_evidence=mapping["physical_evidence"],
            claim_boundary=mapping["claim_boundary"],
        )

    def _validate_chronology(self) -> None:
        accepted = _timestamp_value(self.accepted_at, "accepted_at")
        timestamps = {
            name: (
                _timestamp_value(value, name) if value is not None else None
            )
            for name, value in {
                "started_at": self.started_at,
                "cancellation_requested_at": self.cancellation_requested_at,
                "completed_at": self.completed_at,
            }.items()
        }
        for name, value in timestamps.items():
            if value is not None and value < accepted:
                raise ValueError(f"{name} cannot precede accepted_at")
        started = timestamps["started_at"]
        cancelled = timestamps["cancellation_requested_at"]
        completed = timestamps["completed_at"]
        if started is not None and cancelled is not None and cancelled < started:
            raise ValueError("cancellation_requested_at cannot precede started_at")
        if started is not None and completed is not None and completed < started:
            raise ValueError("completed_at cannot precede started_at")
        if cancelled is not None and completed is not None and completed < cancelled:
            raise ValueError("completed_at cannot precede cancellation_requested_at")

    def _validate_state(self) -> None:
        if self.status is ExecutionStatus.QUEUED:
            if any(
                item is not None
                for item in (
                    self.started_at,
                    self.cancellation_requested_at,
                    self.completed_at,
                    self.job_id,
                    self.revision_id,
                    self.lease,
                    self.failure,
                )
            ):
                raise ValueError("queued executions cannot contain runtime state")
        elif self.status is ExecutionStatus.RUNNING:
            if (
                self.started_at is None
                or self.cancellation_requested_at is not None
                or self.completed_at is not None
                or self.lease is None
                or self.failure is not None
            ):
                raise ValueError("running execution state is incomplete")
            if self.lease.acquired_at != self.started_at:
                raise ValueError("active lease acquired_at must equal started_at")
        elif self.status is ExecutionStatus.CANCELLATION_REQUESTED:
            if (
                self.started_at is None
                or self.cancellation_requested_at is None
                or self.completed_at is not None
                or self.lease is None
                or self.failure is not None
            ):
                raise ValueError("cancellation_requested execution state is incomplete")
            if self.lease.acquired_at != self.started_at:
                raise ValueError("active lease acquired_at must equal started_at")
        elif self.status is ExecutionStatus.SUCCEEDED:
            if (
                self.started_at is None
                or self.cancellation_requested_at is not None
                or self.completed_at is None
                or self.job_id is None
                or self.revision_id is None
                or self.lease is not None
                or self.failure is not None
            ):
                raise ValueError("succeeded execution state is incomplete")
        elif self.status is ExecutionStatus.FAILED:
            if (
                self.started_at is None
                or self.completed_at is None
                or self.lease is not None
                or self.failure is None
            ):
                raise ValueError("failed execution state is incomplete")
        elif self.status is ExecutionStatus.CANCELLED:
            if (
                self.cancellation_requested_at is None
                or self.completed_at is None
                or self.lease is not None
                or self.failure is not None
            ):
                raise ValueError("cancelled execution state is incomplete")
        elif self.status is ExecutionStatus.INTERRUPTED:
            if (
                self.started_at is None
                or self.completed_at is None
                or self.lease is not None
                or self.failure is None
                or self.failure.code is not ExecutionFailureCode.RUNNER_INTERRUPTED
            ):
                raise ValueError("interrupted execution state is incomplete")

    def _mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "execution_id": self.execution_id,
            "accepted_sequence": self.accepted_sequence,
            "request": self.request.to_dict(),
            "request_sha256": self.request_sha256,
            "plan": self.plan.to_dict(),
            "policy": self.policy.to_dict(),
            "status": self.status.value,
            "accepted_at": self.accepted_at,
            "started_at": self.started_at,
            "cancellation_requested_at": self.cancellation_requested_at,
            "completed_at": self.completed_at,
            "job_id": self.job_id,
            "revision_id": self.revision_id,
            "lease": self.lease.to_dict() if self.lease else None,
            "failure": self.failure.to_dict() if self.failure else None,
            "hardware_actions": self.hardware_actions,
            "physical_evidence": self.physical_evidence,
            "claim_boundary": self.claim_boundary,
        }

    def to_dict(self) -> dict[str, Any]:
        return self._mapping()


@dataclass(frozen=True)
class ExecutionEvent:
    execution_id: str
    sequence: int
    event_type: ExecutionEventType
    status: ExecutionStatus
    occurred_at: str
    message: str
    job_id: str | None = None
    revision_id: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: _new_id("exevt"))
    hardware_action: bool = False
    schema_version: str = EXECUTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_SCHEMA_VERSION:
            raise ValueError("unsupported execution event schema_version")
        object.__setattr__(
            self, "event_id", _identifier(self.event_id, "event_id")
        )
        object.__setattr__(
            self, "execution_id", _identifier(self.execution_id, "execution_id")
        )
        sequence = _strict_integer(self.sequence, "event sequence", minimum=1)
        if sequence > NO_HARDWARE_RUNNER_POLICY.max_events:
            raise ValueError("event sequence exceeds the runner policy")
        object.__setattr__(self, "sequence", sequence)
        event_type = _enum_value(self.event_type, ExecutionEventType, "event type")
        status = _enum_value(self.status, ExecutionStatus, "execution status")
        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "occurred_at", _timestamp(self.occurred_at, "occurred_at"))
        object.__setattr__(
            self, "message", _required_text(self.message, "event message", maximum=512)
        )
        object.__setattr__(self, "job_id", _optional_identifier(self.job_id, "job_id"))
        object.__setattr__(
            self,
            "revision_id",
            _optional_identifier(self.revision_id, "revision_id"),
        )
        if (self.job_id is None) != (self.revision_id is None):
            raise ValueError("event job_id and revision_id must bind together")
        if not isinstance(self.data, Mapping):
            raise ValueError("event data must be an object")
        if len(self.data) > 32:
            raise ValueError("event data cannot exceed 32 top-level properties")
        frozen = _freeze_json(self.data)
        _json_shape(frozen, max_depth=16, max_nodes=20_000)
        serialized = _canonical_json_bytes(_thaw_json(frozen))
        if len(serialized) > NO_HARDWARE_RUNNER_POLICY.max_event_data_bytes:
            raise ValueError("event data exceeds the 65536-byte runner policy")
        object.__setattr__(self, "data", frozen)
        if _strict_boolean(self.hardware_action, "hardware_action"):
            raise ValueError("hardware_action must remain false")
        self._validate_pair()
        validate_persisted_instance(
            self._mapping(), EXECUTION_EVENT_SCHEMA, record_name="execution event"
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "ExecutionEvent":
        validate_persisted_instance(
            value, EXECUTION_EVENT_SCHEMA, record_name="execution event"
        )
        names = {
            "schema_version",
            "event_id",
            "execution_id",
            "sequence",
            "event_type",
            "status",
            "occurred_at",
            "message",
            "job_id",
            "revision_id",
            "data",
            "hardware_action",
        }
        mapping = _exact_keys(value, names, "execution event")
        return cls(**{name: mapping[name] for name in names})

    def _validate_pair(self) -> None:
        allowed: dict[ExecutionEventType, frozenset[ExecutionStatus]] = {
            ExecutionEventType.REQUEST_ACCEPTED: frozenset({ExecutionStatus.QUEUED}),
            ExecutionEventType.EXECUTION_STARTED: frozenset({ExecutionStatus.RUNNING}),
            ExecutionEventType.EXECUTION_IDENTITY_BOUND: frozenset(_ACTIVE_STATUSES),
            ExecutionEventType.STAGE_SNAPSHOT_PERSISTED: frozenset(_ACTIVE_STATUSES),
            ExecutionEventType.CANCELLATION_REQUESTED: frozenset(
                {ExecutionStatus.CANCELLATION_REQUESTED, ExecutionStatus.CANCELLED}
            ),
            ExecutionEventType.EXECUTION_SUCCEEDED: frozenset(
                {ExecutionStatus.SUCCEEDED}
            ),
            ExecutionEventType.EXECUTION_FAILED: frozenset({ExecutionStatus.FAILED}),
            ExecutionEventType.EXECUTION_CANCELLED: frozenset(
                {ExecutionStatus.CANCELLED}
            ),
            ExecutionEventType.EXECUTION_INTERRUPTED: frozenset(
                {ExecutionStatus.INTERRUPTED}
            ),
        }
        if self.status not in allowed[self.event_type]:
            raise ValueError(
                f"event type {self.event_type.value!r} cannot report {self.status.value!r}"
            )
        identity_required = {
            ExecutionEventType.EXECUTION_IDENTITY_BOUND,
            ExecutionEventType.STAGE_SNAPSHOT_PERSISTED,
            ExecutionEventType.EXECUTION_SUCCEEDED,
        }
        if self.event_type in identity_required and self.job_id is None:
            raise ValueError(f"event type {self.event_type.value!r} requires journey identity")
        identity_forbidden = {
            ExecutionEventType.REQUEST_ACCEPTED,
            ExecutionEventType.EXECUTION_STARTED,
        }
        if self.event_type in identity_forbidden and self.job_id is not None:
            raise ValueError(
                f"event type {self.event_type.value!r} precedes journey identity"
            )

    def _mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "execution_id": self.execution_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "status": self.status.value,
            "occurred_at": self.occurred_at,
            "message": self.message,
            "job_id": self.job_id,
            "revision_id": self.revision_id,
            "data": _thaw_json(self.data),
            "hardware_action": self.hardware_action,
        }

    def to_dict(self) -> dict[str, Any]:
        return self._mapping()


@dataclass(frozen=True)
class AdmissionResult:
    decision: AdmissionDecision
    execution_id: str | None
    reason: str

    @property
    def accepted(self) -> bool:
        return self.decision in {
            AdmissionDecision.ACCEPT,
            AdmissionDecision.IDEMPOTENT_REPLAY,
        }


def assess_admission(
    request: ExecutionRequest,
    *,
    existing: ExecutionRecord | None,
    active_count: int,
    queued_count: int,
    policy: RunnerPolicy = NO_HARDWARE_RUNNER_POLICY,
) -> AdmissionResult:
    """Evaluate bounded queue and idempotency rules without changing state."""

    if not isinstance(request, ExecutionRequest):
        raise ValueError("request must be an ExecutionRequest")
    if not isinstance(policy, RunnerPolicy):
        raise ValueError("policy must be a RunnerPolicy")
    active = _strict_integer(active_count, "active_count")
    queued = _strict_integer(queued_count, "queued_count")
    if active > policy.max_active_executions:
        raise ValueError("persisted active_count violates the runner invariant")
    if queued > policy.max_queued_executions:
        raise ValueError("persisted queued_count violates the runner invariant")
    if len(request.canonical_bytes()) > policy.max_request_bytes:
        return AdmissionResult(
            AdmissionDecision.REQUEST_TOO_LARGE,
            None,
            "request exceeds the frozen request byte limit",
        )
    if existing is not None:
        if not isinstance(existing, ExecutionRecord):
            raise ValueError("existing must be an ExecutionRecord")
        if existing.request.idempotency_key != request.idempotency_key:
            raise ValueError("existing record does not match the idempotency key")
        if existing.request_sha256 == request.canonical_sha256():
            return AdmissionResult(
                AdmissionDecision.IDEMPOTENT_REPLAY,
                existing.execution_id,
                "same idempotency key and canonical request; replay existing execution",
            )
        return AdmissionResult(
            AdmissionDecision.IDEMPOTENCY_CONFLICT,
            existing.execution_id,
            "idempotency key was already used for a different canonical request",
        )
    if queued >= policy.max_queued_executions:
        return AdmissionResult(
            AdmissionDecision.QUEUE_FULL,
            None,
            "the bounded FIFO queue already contains four executions",
        )
    return AdmissionResult(
        AdmissionDecision.ACCEPT,
        None,
        "request may be accepted into the bounded FIFO queue",
    )


def start_execution(
    record: ExecutionRecord,
    lease: ExecutionLease,
    *,
    at: str | datetime,
) -> ExecutionRecord:
    if record.status is not ExecutionStatus.QUEUED:
        raise ExecutionTransitionError("only queued executions may start")
    if not isinstance(lease, ExecutionLease):
        raise ValueError("lease must be an ExecutionLease")
    started_at = _timestamp(at, "started_at")
    if lease.acquired_at != started_at or lease.heartbeat_at != started_at:
        raise ExecutionTransitionError(
            "initial lease acquired_at and heartbeat_at must equal started_at"
        )
    return replace(
        record,
        status=ExecutionStatus.RUNNING,
        started_at=started_at,
        lease=lease,
    )


def _fenced_active_time(
    record: ExecutionRecord,
    *,
    runner_instance_id: str,
    generation: int,
    at: str | datetime,
    name: str,
) -> str:
    if record.status not in _ACTIVE_STATUSES or record.lease is None:
        raise ExecutionTransitionError("operation requires an active execution lease")
    runner = _identifier(runner_instance_id, "runner_instance_id")
    token = _strict_integer(generation, "lease generation", minimum=1)
    if (
        runner != record.lease.runner_instance_id
        or token != record.lease.generation
    ):
        raise ExecutionTransitionError("lease fencing identity does not match")
    normalized = _timestamp(at, name)
    moment = _timestamp_value(normalized, name)
    heartbeat = _timestamp_value(record.lease.heartbeat_at, "lease heartbeat_at")
    expiry = _timestamp_value(record.lease.expires_at, "lease expires_at")
    if moment < heartbeat:
        raise ExecutionTransitionError(f"{name} cannot precede lease heartbeat_at")
    if moment >= expiry:
        raise ExecutionTransitionError("execution lease has expired")
    return normalized


def bind_execution_identity(
    record: ExecutionRecord,
    *,
    job_id: str,
    revision_id: str,
    runner_instance_id: str,
    generation: int,
    at: str | datetime,
) -> ExecutionRecord:
    _fenced_active_time(
        record,
        runner_instance_id=runner_instance_id,
        generation=generation,
        at=at,
        name="identity bind time",
    )
    normalized_job = _identifier(job_id, "job_id")
    normalized_revision = _identifier(revision_id, "revision_id")
    if record.job_id is None and record.revision_id is None:
        return replace(record, job_id=normalized_job, revision_id=normalized_revision)
    if record.job_id == normalized_job and record.revision_id == normalized_revision:
        return record
    raise ExecutionTransitionError("execution identity is already bound differently")


def request_cancellation(
    record: ExecutionRecord,
    *,
    at: str | datetime,
) -> ExecutionRecord:
    """Linearize cancellation; terminal completion always remains immutable."""

    if record.status in _TERMINAL_STATUSES:
        return record
    if record.status is ExecutionStatus.CANCELLATION_REQUESTED:
        return record
    requested_at = _timestamp(at, "cancellation_requested_at")
    if record.status is ExecutionStatus.QUEUED:
        return replace(
            record,
            status=ExecutionStatus.CANCELLED,
            cancellation_requested_at=requested_at,
            completed_at=requested_at,
        )
    if record.status is ExecutionStatus.RUNNING:
        return replace(
            record,
            status=ExecutionStatus.CANCELLATION_REQUESTED,
            cancellation_requested_at=requested_at,
        )
    raise ExecutionTransitionError(f"cannot cancel execution in {record.status.value}")


def transition_execution(
    record: ExecutionRecord,
    target: ExecutionStatus,
    *,
    at: str | datetime,
    runner_instance_id: str,
    generation: int,
    failure: ExecutionFailure | None = None,
) -> ExecutionRecord:
    """Commit one terminal result under the frozen cancellation race rules."""

    if record.status in _TERMINAL_STATUSES:
        raise ExecutionTransitionError("terminal execution records are immutable")
    target_status = _enum_value(target, ExecutionStatus, "execution status")
    allowed = {
        ExecutionStatus.RUNNING: {
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.FAILED,
        },
        ExecutionStatus.CANCELLATION_REQUESTED: {
            ExecutionStatus.CANCELLED,
            ExecutionStatus.FAILED,
        },
    }
    if target_status not in allowed.get(record.status, set()):
        raise ExecutionTransitionError(
            f"cannot transition execution from {record.status.value} to {target_status.value}"
        )
    completed_at = _fenced_active_time(
        record,
        runner_instance_id=runner_instance_id,
        generation=generation,
        at=at,
        name="completed_at",
    )
    if target_status is ExecutionStatus.SUCCEEDED:
        if failure is not None:
            raise ExecutionTransitionError("succeeded executions cannot contain a failure")
        if record.job_id is None or record.revision_id is None:
            raise ExecutionTransitionError("success requires a bound journey identity")
    elif target_status is ExecutionStatus.FAILED:
        if not isinstance(failure, ExecutionFailure):
            raise ExecutionTransitionError("failed executions require a structured failure")
        if failure.code is ExecutionFailureCode.RUNNER_INTERRUPTED:
            raise ExecutionTransitionError(
                "runner_interrupted is committed only by stale-lease reconciliation"
            )
        if failure.code is ExecutionFailureCode.CANCELLATION_TIMEOUT:
            if record.cancellation_requested_at is None:
                raise ExecutionTransitionError(
                    "cancellation_timeout requires a cancellation request"
                )
            grace_ends = _timestamp_value(
                record.cancellation_requested_at,
                "cancellation_requested_at",
            ) + timedelta(seconds=record.policy.cancellation_grace_seconds)
            if _timestamp_value(completed_at, "completed_at") < grace_ends:
                raise ExecutionTransitionError(
                    "cancellation_timeout cannot commit before the cancellation grace ends"
                )
    elif failure is not None:
        raise ExecutionTransitionError("cancelled executions cannot contain a failure")
    return replace(
        record,
        status=target_status,
        completed_at=completed_at,
        lease=None,
        failure=failure,
    )


def renew_execution_lease(
    record: ExecutionRecord,
    *,
    runner_instance_id: str,
    generation: int,
    at: str | datetime,
) -> ExecutionRecord:
    heartbeat = _fenced_active_time(
        record,
        runner_instance_id=runner_instance_id,
        generation=generation,
        at=at,
        name="lease heartbeat_at",
    )
    if record.lease is None:  # pragma: no cover - narrowed by _fenced_active_time
        raise ExecutionTransitionError("active execution is missing its lease")
    if heartbeat == record.lease.heartbeat_at:
        return record
    expiry = (
        _timestamp_value(heartbeat, "lease heartbeat_at")
        + timedelta(seconds=record.policy.lease_seconds)
    ).isoformat()
    lease = replace(record.lease, heartbeat_at=heartbeat, expires_at=expiry)
    return replace(record, lease=lease)


def interrupt_stale_execution(
    record: ExecutionRecord,
    *,
    observed_at: str | datetime,
) -> ExecutionRecord:
    if record.status not in _ACTIVE_STATUSES or record.lease is None:
        raise ExecutionTransitionError("only active executions can have stale leases")
    observed = _timestamp(observed_at, "observed_at")
    if _timestamp_value(observed, "observed_at") < _timestamp_value(
        record.lease.expires_at, "lease expires_at"
    ):
        raise ExecutionTransitionError("execution lease has not expired")
    failure = ExecutionFailure(
        code=ExecutionFailureCode.RUNNER_INTERRUPTED,
        message=(
            "The runner lease expired. Partial artifacts and events are retained; "
            "automatic resume is forbidden."
        ),
        retryable=True,
    )
    return replace(
        record,
        status=ExecutionStatus.INTERRUPTED,
        completed_at=observed,
        lease=None,
        failure=failure,
    )


__all__ = [
    "AdmissionDecision",
    "AdmissionResult",
    "CADQUERY_VERSION",
    "CAD_WORKER_VERSION",
    "CadRuntimeSnapshot",
    "EXECUTION_CLAIM_BOUNDARY",
    "EXECUTION_SCHEMA_VERSION",
    "ExecutionEvent",
    "ExecutionEventType",
    "ExecutionFailure",
    "ExecutionFailureCode",
    "ExecutionLease",
    "ExecutionPlan",
    "ExecutionRecord",
    "ExecutionRequest",
    "ExecutionStage",
    "ExecutionStatus",
    "ExecutionTarget",
    "ExecutionTransitionError",
    "FABRICATION_PIPELINE_VERSION",
    "GOLDEN_PART_BENCHMARK_ID",
    "GOLDEN_PART_PROVIDER_ID",
    "NO_HARDWARE_RUNNER_POLICY",
    "OCP_VERSION",
    "POLICY_VERSION",
    "PRINTABILITY_VALIDATOR_VERSION",
    "R4ProfileSnapshot",
    "RunnerPolicy",
    "SlicerSnapshot",
    "assess_admission",
    "bind_execution_identity",
    "interrupt_stale_execution",
    "renew_execution_lease",
    "request_cancellation",
    "start_execution",
    "transition_execution",
]
