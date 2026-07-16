"""Traceable records for the Ariad Fabrication Journey.

The records in this module are immutable snapshots. ``FabricationJourney`` is
the small aggregate that appends records and replaces a stage-run snapshot when
its state changes. Events are never replaced or deleted.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .spec import PartSpec


JOURNEY_SCHEMA_VERSION = "1.0.0"
MANIFEST_SCHEMA_VERSION = "1.0.0"


class FabricationStage(str, Enum):
    BRIEF = "brief"
    DESIGN = "design"
    GEOMETRY_VALIDATION = "geometry_validation"
    PRINTABILITY_VALIDATION = "printability_validation"
    SLICING = "slicing"
    FABRICATION_PACKAGE = "fabrication_package"
    MANUFACTURING = "manufacturing"


class StageStatus(str, Enum):
    WAITING = "waiting"
    RUNNING = "running"
    NEEDS_INPUT = "needs_input"
    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class EvidenceLevel(str, Enum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"
    R6 = "R6"
    R7 = "R7"


class EvidenceMode(str, Enum):
    REAL = "real"
    SIMULATED = "simulated"
    FIXTURE = "fixture"
    UNAVAILABLE = "unavailable"


class FindingSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class DecisionActor(str, Enum):
    USER = "user"
    MODEL = "model"
    SYSTEM = "system"


class ApprovalStatus(str, Enum):
    REQUESTED = "requested"
    GRANTED = "granted"
    REJECTED = "rejected"
    REVOKED = "revoked"


class JobStatus(str, Enum):
    ACTIVE = "active"
    NEEDS_INPUT = "needs_input"
    READY_FOR_DESIGN = "ready_for_design"
    DESIGN_GENERATED = "design_generated"
    GEOMETRY_VERIFIED = "geometry_verified"
    PRINTABILITY_ASSESSED = "printability_assessed"
    SLICER_VERIFIED = "slicer_verified"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


_JOB_STATUSES = {status.value for status in JobStatus}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _required_text(value: Any, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        number = int(value)
        numeric_value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not isfinite(numeric_value) or numeric_value != number:
        raise ValueError(f"{name} must be an integer")
    if number < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return number


def _timestamp(value: str | datetime, name: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        normalized = _required_text(value, name)
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _freeze(value: Any) -> Any:
    if isinstance(value, Enum):
        return _freeze(value.value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("record metadata cannot contain non-finite numbers")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key)
            if normalized_key in normalized:
                raise ValueError(f"record metadata contains duplicate key {normalized_key!r}")
            normalized[normalized_key] = _freeze(item)
        return MappingProxyType(normalized)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_freeze(item) for item in value), key=repr))
    raise ValueError(f"record metadata contains unsupported value {type(value).__name__}")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _ids(value: Sequence[Any] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        value = (value,)
    normalized = tuple(_required_text(item, "record id") for item in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError("record id lists cannot contain duplicates")
    return normalized


def _artifact_path(value: Any) -> str:
    normalized = _required_text(value, "artifact path").replace("\\", "/")
    if re.match(r"^[A-Za-z]:", normalized):
        raise ValueError("artifact path must be relative to the revision directory")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or path == PurePosixPath(".")
        or ".." in path.parts
        or any(":" in part for part in path.parts)
    ):
        raise ValueError("artifact path must be a safe relative path")
    return path.as_posix()


@dataclass(frozen=True)
class Job:
    request: str
    title: str = "Untitled fabrication job"
    job_id: str = field(default_factory=lambda: _new_id("job"))
    status: str = "active"
    current_revision_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_id", _required_text(self.job_id, "job_id"))
        object.__setattr__(self, "request", _required_text(self.request, "request"))
        object.__setattr__(self, "title", _required_text(self.title, "title"))
        status = _required_text(self.status, "job status")
        if status not in _JOB_STATUSES:
            raise ValueError(f"unsupported job status {status!r}")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "current_revision_id", _optional_text(self.current_revision_id))
        object.__setattr__(self, "created_at", _timestamp(self.created_at, "created_at"))
        object.__setattr__(self, "updated_at", _timestamp(self.updated_at, "updated_at"))
        object.__setattr__(self, "metadata", _freeze(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "title": self.title,
            "request": self.request,
            "status": self.status,
            "current_revision_id": self.current_revision_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": _thaw(self.metadata),
        }


@dataclass(frozen=True)
class Revision:
    job_id: str
    number: int
    spec: PartSpec
    reason: str
    revision_id: str = field(default_factory=lambda: _new_id("rev"))
    parent_revision_id: str | None = None
    stage_run_ids: tuple[str, ...] = ()
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "revision_id", _required_text(self.revision_id, "revision_id"))
        object.__setattr__(self, "job_id", _required_text(self.job_id, "job_id"))
        object.__setattr__(self, "number", _integer(self.number, "revision number", minimum=1))
        if not isinstance(self.spec, PartSpec):
            raise ValueError("revision spec must be a PartSpec")
        object.__setattr__(self, "reason", _required_text(self.reason, "revision reason"))
        object.__setattr__(self, "parent_revision_id", _optional_text(self.parent_revision_id))
        object.__setattr__(self, "stage_run_ids", _ids(self.stage_run_ids))
        object.__setattr__(self, "created_at", _timestamp(self.created_at, "created_at"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "job_id": self.job_id,
            "number": self.number,
            "parent_revision_id": self.parent_revision_id,
            "reason": self.reason,
            "created_at": self.created_at,
            "stage_run_ids": list(self.stage_run_ids),
            "spec": self.spec.to_dict(),
        }


@dataclass(frozen=True)
class StageRun:
    job_id: str
    stage: FabricationStage
    attempt: int = 1
    revision_id: str | None = None
    stage_run_id: str = field(default_factory=lambda: _new_id("run"))
    status: StageStatus = StageStatus.WAITING
    evidence_mode: EvidenceMode = EvidenceMode.REAL
    evidence_level: EvidenceLevel | None = None
    tool_name: str = "ariad"
    tool_version: str = "0.1.0"
    started_at: str | None = None
    completed_at: str | None = None
    summary: str = ""
    error_message: str | None = None
    input_artifact_ids: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    finding_ids: tuple[str, ...] = ()
    decision_ids: tuple[str, ...] = ()
    approval_ids: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage_run_id", _required_text(self.stage_run_id, "stage_run_id"))
        object.__setattr__(self, "job_id", _required_text(self.job_id, "job_id"))
        object.__setattr__(self, "revision_id", _optional_text(self.revision_id))
        object.__setattr__(self, "stage", FabricationStage(self.stage))
        object.__setattr__(self, "status", StageStatus(self.status))
        object.__setattr__(self, "evidence_mode", EvidenceMode(self.evidence_mode))
        if self.evidence_level is not None:
            object.__setattr__(self, "evidence_level", EvidenceLevel(self.evidence_level))
        object.__setattr__(self, "attempt", _integer(self.attempt, "stage attempt", minimum=1))
        object.__setattr__(self, "tool_name", _required_text(self.tool_name, "tool_name"))
        object.__setattr__(self, "tool_version", _required_text(self.tool_version, "tool_version"))
        if self.started_at is not None:
            object.__setattr__(self, "started_at", _timestamp(self.started_at, "started_at"))
        if self.completed_at is not None:
            object.__setattr__(self, "completed_at", _timestamp(self.completed_at, "completed_at"))
        object.__setattr__(self, "summary", str(self.summary).strip())
        object.__setattr__(self, "error_message", _optional_text(self.error_message))
        if self.status is StageStatus.WAITING and (
            self.started_at is not None or self.completed_at is not None
        ):
            raise ValueError("waiting stage runs cannot contain execution timestamps")
        if self.status in {StageStatus.RUNNING, StageStatus.NEEDS_INPUT}:
            if self.started_at is None or self.completed_at is not None:
                raise ValueError(f"{self.status.value} stage runs require only started_at")
        if self.status in {
            StageStatus.PASSED,
            StageStatus.PASSED_WITH_WARNINGS,
            StageStatus.FAILED,
        } and (self.started_at is None or self.completed_at is None):
            raise ValueError(f"{self.status.value} stage runs require start and completion times")
        if self.status is StageStatus.FAILED and not self.error_message:
            raise ValueError("failed stage runs require an error_message")
        if self.status in {StageStatus.PASSED, StageStatus.PASSED_WITH_WARNINGS}:
            if self.evidence_level is None:
                raise ValueError("passed stage runs require an evidence_level")
            if self.evidence_mode is EvidenceMode.UNAVAILABLE:
                raise ValueError("unavailable evidence cannot produce a passed stage run")
        for name in (
            "input_artifact_ids",
            "artifact_ids",
            "finding_ids",
            "decision_ids",
            "approval_ids",
            "event_ids",
        ):
            object.__setattr__(self, name, _ids(getattr(self, name)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_run_id": self.stage_run_id,
            "job_id": self.job_id,
            "revision_id": self.revision_id,
            "stage": self.stage.value,
            "status": self.status.value,
            "attempt": self.attempt,
            "evidence_mode": self.evidence_mode.value,
            "evidence_level": self.evidence_level.value if self.evidence_level else None,
            "tool": {"name": self.tool_name, "version": self.tool_version},
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "summary": self.summary,
            "error_message": self.error_message,
            "input_artifact_ids": list(self.input_artifact_ids),
            "artifact_ids": list(self.artifact_ids),
            "finding_ids": list(self.finding_ids),
            "decision_ids": list(self.decision_ids),
            "approval_ids": list(self.approval_ids),
            "event_ids": list(self.event_ids),
        }


@dataclass(frozen=True)
class StageEvent:
    stage_run_id: str
    job_id: str
    stage: FabricationStage
    event_type: str
    message: str
    sequence: int
    status: StageStatus
    revision_id: str | None = None
    event_id: str = field(default_factory=lambda: _new_id("evt"))
    timestamp: str = field(default_factory=utc_now)
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _required_text(self.event_id, "event_id"))
        object.__setattr__(self, "stage_run_id", _required_text(self.stage_run_id, "stage_run_id"))
        object.__setattr__(self, "job_id", _required_text(self.job_id, "job_id"))
        object.__setattr__(self, "revision_id", _optional_text(self.revision_id))
        object.__setattr__(self, "stage", FabricationStage(self.stage))
        object.__setattr__(self, "status", StageStatus(self.status))
        object.__setattr__(self, "event_type", _required_text(self.event_type, "event_type"))
        object.__setattr__(self, "message", _required_text(self.message, "event message"))
        object.__setattr__(self, "sequence", _integer(self.sequence, "event sequence", minimum=1))
        object.__setattr__(self, "timestamp", _timestamp(self.timestamp, "timestamp"))
        object.__setattr__(self, "data", _freeze(self.data or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "stage_run_id": self.stage_run_id,
            "job_id": self.job_id,
            "revision_id": self.revision_id,
            "stage": self.stage.value,
            "event_type": self.event_type,
            "status": self.status.value,
            "message": self.message,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "data": _thaw(self.data),
        }


@dataclass(frozen=True)
class Artifact:
    job_id: str
    revision_id: str
    stage_run_id: str
    role: str
    path: str
    media_type: str
    checksum_sha256: str
    producer: str
    producer_version: str
    artifact_id: str = field(default_factory=lambda: _new_id("art"))
    evidence_mode: EvidenceMode = EvidenceMode.REAL
    parent_artifact_ids: tuple[str, ...] = ()
    size_bytes: int | None = None
    created_at: str = field(default_factory=utc_now)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("artifact_id", "job_id", "revision_id", "stage_run_id"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        object.__setattr__(self, "role", _required_text(self.role, "artifact role"))
        object.__setattr__(self, "path", _artifact_path(self.path))
        object.__setattr__(self, "media_type", _required_text(self.media_type, "media_type"))
        checksum = _required_text(self.checksum_sha256, "checksum_sha256").lower()
        if not _SHA256_PATTERN.fullmatch(checksum):
            raise ValueError("checksum_sha256 must contain 64 hexadecimal characters")
        object.__setattr__(self, "checksum_sha256", checksum)
        object.__setattr__(self, "producer", _required_text(self.producer, "producer"))
        object.__setattr__(
            self, "producer_version", _required_text(self.producer_version, "producer_version")
        )
        object.__setattr__(self, "evidence_mode", EvidenceMode(self.evidence_mode))
        object.__setattr__(self, "parent_artifact_ids", _ids(self.parent_artifact_ids))
        if self.size_bytes is not None:
            object.__setattr__(self, "size_bytes", _integer(self.size_bytes, "size_bytes"))
        object.__setattr__(self, "created_at", _timestamp(self.created_at, "created_at"))
        object.__setattr__(self, "metadata", _freeze(self.metadata or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "job_id": self.job_id,
            "revision_id": self.revision_id,
            "stage_run_id": self.stage_run_id,
            "role": self.role,
            "path": self.path,
            "media_type": self.media_type,
            "checksum_sha256": self.checksum_sha256,
            "producer": self.producer,
            "producer_version": self.producer_version,
            "evidence_mode": self.evidence_mode.value,
            "parent_artifact_ids": list(self.parent_artifact_ids),
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "metadata": _thaw(self.metadata),
        }


@dataclass(frozen=True)
class Finding:
    job_id: str
    stage_run_id: str
    code: str
    title: str
    severity: FindingSeverity
    evidence: str
    revision_id: str | None = None
    finding_id: str = field(default_factory=lambda: _new_id("finding"))
    evidence_mode: EvidenceMode = EvidenceMode.REAL
    affected_geometry: str | None = None
    remediation: str | None = None
    resolved: bool = False
    resolution: str | None = None
    created_at: str = field(default_factory=utc_now)
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("finding_id", "job_id", "stage_run_id"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        object.__setattr__(self, "revision_id", _optional_text(self.revision_id))
        object.__setattr__(self, "code", _required_text(self.code, "finding code"))
        object.__setattr__(self, "title", _required_text(self.title, "finding title"))
        object.__setattr__(self, "severity", FindingSeverity(self.severity))
        object.__setattr__(self, "evidence_mode", EvidenceMode(self.evidence_mode))
        object.__setattr__(self, "evidence", _required_text(self.evidence, "finding evidence"))
        object.__setattr__(self, "affected_geometry", _optional_text(self.affected_geometry))
        object.__setattr__(self, "remediation", _optional_text(self.remediation))
        object.__setattr__(self, "resolution", _optional_text(self.resolution))
        if self.resolved and self.resolution is None:
            raise ValueError("resolved findings require a resolution")
        object.__setattr__(self, "created_at", _timestamp(self.created_at, "created_at"))
        object.__setattr__(self, "data", _freeze(self.data or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "job_id": self.job_id,
            "revision_id": self.revision_id,
            "stage_run_id": self.stage_run_id,
            "code": self.code,
            "title": self.title,
            "severity": self.severity.value,
            "evidence_mode": self.evidence_mode.value,
            "evidence": self.evidence,
            "affected_geometry": self.affected_geometry,
            "remediation": self.remediation,
            "resolved": self.resolved,
            "resolution": self.resolution,
            "created_at": self.created_at,
            "data": _thaw(self.data),
        }


@dataclass(frozen=True)
class Decision:
    job_id: str
    revision_id: str
    question: str
    choice: str
    rationale: str
    actor: DecisionActor
    stage_run_id: str | None = None
    decision_id: str = field(default_factory=lambda: _new_id("decision"))
    alternatives: tuple[str, ...] = ()
    created_at: str = field(default_factory=utc_now)
    data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("decision_id", "job_id", "revision_id"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        object.__setattr__(self, "stage_run_id", _optional_text(self.stage_run_id))
        object.__setattr__(self, "question", _required_text(self.question, "decision question"))
        object.__setattr__(self, "choice", _required_text(self.choice, "decision choice"))
        object.__setattr__(self, "rationale", _required_text(self.rationale, "decision rationale"))
        object.__setattr__(self, "actor", DecisionActor(self.actor))
        object.__setattr__(
            self,
            "alternatives",
            tuple(_required_text(item, "decision alternative") for item in self.alternatives),
        )
        object.__setattr__(self, "created_at", _timestamp(self.created_at, "created_at"))
        object.__setattr__(self, "data", _freeze(self.data or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "job_id": self.job_id,
            "revision_id": self.revision_id,
            "stage_run_id": self.stage_run_id,
            "question": self.question,
            "choice": self.choice,
            "rationale": self.rationale,
            "actor": self.actor.value,
            "alternatives": list(self.alternatives),
            "created_at": self.created_at,
            "data": _thaw(self.data),
        }


@dataclass(frozen=True)
class Approval:
    job_id: str
    revision_id: str
    boundary: str
    status: ApprovalStatus = ApprovalStatus.REQUESTED
    requested_by: DecisionActor = DecisionActor.SYSTEM
    stage_run_id: str | None = None
    approval_id: str = field(default_factory=lambda: _new_id("approval"))
    rationale: str = ""
    requested_at: str = field(default_factory=utc_now)
    decided_at: str | None = None
    decided_by: DecisionActor | None = None

    def __post_init__(self) -> None:
        for name in ("approval_id", "job_id", "revision_id"):
            object.__setattr__(self, name, _required_text(getattr(self, name), name))
        object.__setattr__(self, "stage_run_id", _optional_text(self.stage_run_id))
        object.__setattr__(self, "boundary", _required_text(self.boundary, "approval boundary"))
        object.__setattr__(self, "status", ApprovalStatus(self.status))
        object.__setattr__(self, "requested_by", DecisionActor(self.requested_by))
        object.__setattr__(self, "rationale", str(self.rationale).strip())
        object.__setattr__(self, "requested_at", _timestamp(self.requested_at, "requested_at"))
        if self.decided_at is not None:
            object.__setattr__(self, "decided_at", _timestamp(self.decided_at, "decided_at"))
        if self.decided_by is not None:
            object.__setattr__(self, "decided_by", DecisionActor(self.decided_by))
        if self.status is ApprovalStatus.REQUESTED:
            if self.decided_at is not None or self.decided_by is not None:
                raise ValueError("requested approvals cannot contain a decision")
        elif self.decided_at is None or self.decided_by is None:
            raise ValueError("decided approvals require decided_at and decided_by")

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "job_id": self.job_id,
            "revision_id": self.revision_id,
            "stage_run_id": self.stage_run_id,
            "boundary": self.boundary,
            "status": self.status.value,
            "requested_by": self.requested_by.value,
            "rationale": self.rationale,
            "requested_at": self.requested_at,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by.value if self.decided_by else None,
        }


@dataclass(frozen=True)
class ArtifactManifest:
    job_id: str
    revision_id: str
    artifacts: tuple[Artifact, ...]
    stage_run_ids: tuple[str, ...]
    findings: tuple[Finding, ...] = ()
    decisions: tuple[Decision, ...] = ()
    approvals: tuple[Approval, ...] = ()
    schema_version: str = MANIFEST_SCHEMA_VERSION
    generated_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValueError(f"unsupported manifest schema_version {self.schema_version!r}")
        object.__setattr__(self, "job_id", _required_text(self.job_id, "job_id"))
        object.__setattr__(self, "revision_id", _required_text(self.revision_id, "revision_id"))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(self, "stage_run_ids", _ids(self.stage_run_ids))
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(self, "decisions", tuple(self.decisions))
        object.__setattr__(self, "approvals", tuple(self.approvals))
        object.__setattr__(self, "generated_at", _timestamp(self.generated_at, "generated_at"))
        record_groups = (
            (self.artifacts, Artifact, "artifact_id", "artifacts"),
            (self.findings, Finding, "finding_id", "findings"),
            (self.decisions, Decision, "decision_id", "decisions"),
            (self.approvals, Approval, "approval_id", "approvals"),
        )
        for records, expected_type, id_field, name in record_groups:
            if any(not isinstance(record, expected_type) for record in records):
                raise ValueError(f"manifest {name} contain an invalid record type")
            record_ids = tuple(getattr(record, id_field) for record in records)
            if len(record_ids) != len(set(record_ids)):
                raise ValueError(f"manifest {name} cannot contain duplicate records")
        for record in (*self.artifacts, *self.findings, *self.decisions, *self.approvals):
            if record.job_id != self.job_id or record.revision_id != self.revision_id:
                raise ValueError("manifest records must belong to its job and revision")
            if record.stage_run_id is not None and record.stage_run_id not in self.stage_run_ids:
                raise ValueError("manifest records must reference an included stage run")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "revision_id": self.revision_id,
            "generated_at": self.generated_at,
            "stage_run_ids": list(self.stage_run_ids),
            "artifacts": [item.to_dict() for item in self.artifacts],
            "findings": [item.to_dict() for item in self.findings],
            "decisions": [item.to_dict() for item in self.decisions],
            "approvals": [item.to_dict() for item in self.approvals],
        }


@dataclass
class FabricationJourney:
    """In-memory aggregate for one traceable fabrication job."""

    job: Job
    schema_version: str = JOURNEY_SCHEMA_VERSION
    revisions: list[Revision] = field(default_factory=list)
    stage_runs: list[StageRun] = field(default_factory=list)
    events: list[StageEvent] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    approvals: list[Approval] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.schema_version != JOURNEY_SCHEMA_VERSION:
            raise ValueError(f"unsupported journey schema_version {self.schema_version!r}")
        if not isinstance(self.job, Job):
            raise ValueError("job must be a Job record")

    @classmethod
    def create(
        cls,
        request: str,
        *,
        title: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "FabricationJourney":
        normalized_request = _required_text(request, "request")
        fallback_title = normalized_request[:80].rstrip() or "Untitled fabrication job"
        return cls(
            job=Job(
                request=normalized_request,
                title=title or fallback_title,
                metadata=metadata or {},
            )
        )

    @property
    def status(self) -> str:
        return self.job.status

    @property
    def current_revision(self) -> Revision | None:
        if self.job.current_revision_id is None:
            return None
        return self.get_revision(self.job.current_revision_id)

    @property
    def spec(self) -> PartSpec | None:
        revision = self.current_revision
        return revision.spec if revision else None

    @property
    def current_stage(self) -> FabricationStage | None:
        return self.stage_runs[-1].stage if self.stage_runs else None

    def update_status(self, status: str) -> None:
        self.job = replace(self.job, status=status, updated_at=utc_now())

    def add_revision(
        self,
        spec: PartSpec,
        *,
        reason: str,
        parent_revision_id: str | None = None,
        stage_run_ids: Sequence[str] = (),
    ) -> Revision:
        if parent_revision_id is not None:
            self.get_revision(parent_revision_id)
        revision = Revision(
            job_id=self.job.job_id,
            number=len(self.revisions) + 1,
            spec=spec,
            reason=reason,
            parent_revision_id=parent_revision_id,
            stage_run_ids=tuple(stage_run_ids),
        )
        self.revisions.append(revision)
        self.job = replace(
            self.job,
            current_revision_id=revision.revision_id,
            updated_at=utc_now(),
        )
        return revision

    def get_revision(self, revision_id: str) -> Revision:
        for revision in self.revisions:
            if revision.revision_id == revision_id:
                return revision
        raise KeyError(f"unknown revision_id {revision_id!r}")

    def add_stage_run(
        self,
        stage: FabricationStage,
        *,
        attempt: int = 1,
        revision_id: str | None = None,
        evidence_mode: EvidenceMode = EvidenceMode.REAL,
        tool_name: str = "ariad",
        tool_version: str = "0.1.0",
    ) -> StageRun:
        if revision_id is not None:
            self.get_revision(revision_id)
        run = StageRun(
            job_id=self.job.job_id,
            revision_id=revision_id,
            stage=stage,
            attempt=attempt,
            evidence_mode=evidence_mode,
            tool_name=tool_name,
            tool_version=tool_version,
        )
        self.stage_runs.append(run)
        if revision_id is not None:
            revision = self.get_revision(revision_id)
            replacement = replace(
                revision,
                stage_run_ids=(*revision.stage_run_ids, run.stage_run_id),
            )
            index = self.revisions.index(revision)
            self.revisions[index] = replacement
        return run

    def get_stage_run(self, stage_run_id: str) -> StageRun:
        for run in self.stage_runs:
            if run.stage_run_id == stage_run_id:
                return run
        raise KeyError(f"unknown stage_run_id {stage_run_id!r}")

    def replace_stage_run(self, run: StageRun) -> StageRun:
        if run.job_id != self.job.job_id:
            raise ValueError("stage run belongs to another job")
        for index, existing in enumerate(self.stage_runs):
            if existing.stage_run_id == run.stage_run_id:
                self.stage_runs[index] = run
                return run
        raise KeyError(f"unknown stage_run_id {run.stage_run_id!r}")

    def emit_event(
        self,
        stage_run_id: str,
        event_type: str,
        message: str,
        *,
        data: Mapping[str, Any] | None = None,
    ) -> StageEvent:
        run = self.get_stage_run(stage_run_id)
        event = StageEvent(
            stage_run_id=run.stage_run_id,
            job_id=run.job_id,
            revision_id=run.revision_id,
            stage=run.stage,
            event_type=event_type,
            status=run.status,
            message=message,
            sequence=len(self.events) + 1,
            data=data or {},
        )
        if any(item.event_id == event.event_id for item in self.events):
            raise ValueError(f"duplicate event_id {event.event_id!r}")
        self._attach_to_run(stage_run_id, "event_ids", event.event_id)
        self.events.append(event)
        return event

    def add_artifact(self, artifact: Artifact) -> Artifact:
        self._validate_child(artifact.job_id, artifact.revision_id, artifact.stage_run_id)
        if any(item.artifact_id == artifact.artifact_id for item in self.artifacts):
            raise ValueError(f"duplicate artifact_id {artifact.artifact_id!r}")
        known_artifacts = {item.artifact_id: item for item in self.artifacts}
        for parent_id in artifact.parent_artifact_ids:
            if parent_id not in known_artifacts:
                raise ValueError(f"unknown parent artifact_id {parent_id!r}")
            parent = known_artifacts[parent_id]
            if parent.job_id != artifact.job_id or parent.revision_id != artifact.revision_id:
                raise ValueError("artifact parents must belong to the same job and revision")
        self._attach_to_run(artifact.stage_run_id, "artifact_ids", artifact.artifact_id)
        self.artifacts.append(artifact)
        return artifact

    def add_finding(self, finding: Finding) -> Finding:
        self._validate_child(finding.job_id, finding.revision_id, finding.stage_run_id)
        if any(item.finding_id == finding.finding_id for item in self.findings):
            raise ValueError(f"duplicate finding_id {finding.finding_id!r}")
        self._attach_to_run(finding.stage_run_id, "finding_ids", finding.finding_id)
        self.findings.append(finding)
        return finding

    def add_decision(self, decision: Decision) -> Decision:
        self._validate_child(decision.job_id, decision.revision_id, decision.stage_run_id)
        if any(item.decision_id == decision.decision_id for item in self.decisions):
            raise ValueError(f"duplicate decision_id {decision.decision_id!r}")
        if decision.stage_run_id:
            self._attach_to_run(decision.stage_run_id, "decision_ids", decision.decision_id)
        self.decisions.append(decision)
        return decision

    def add_approval(self, approval: Approval) -> Approval:
        self._validate_child(approval.job_id, approval.revision_id, approval.stage_run_id)
        if any(item.approval_id == approval.approval_id for item in self.approvals):
            raise ValueError(f"duplicate approval_id {approval.approval_id!r}")
        if approval.stage_run_id:
            self._attach_to_run(approval.stage_run_id, "approval_ids", approval.approval_id)
        self.approvals.append(approval)
        return approval

    def manifest_for_revision(self, revision_id: str) -> ArtifactManifest:
        revision = self.get_revision(revision_id)
        return ArtifactManifest(
            job_id=self.job.job_id,
            revision_id=revision_id,
            stage_run_ids=revision.stage_run_ids,
            artifacts=tuple(item for item in self.artifacts if item.revision_id == revision_id),
            findings=tuple(item for item in self.findings if item.revision_id == revision_id),
            decisions=tuple(item for item in self.decisions if item.revision_id == revision_id),
            approvals=tuple(item for item in self.approvals if item.revision_id == revision_id),
        )

    def _validate_child(
        self,
        job_id: str,
        revision_id: str | None,
        stage_run_id: str | None,
    ) -> None:
        if job_id != self.job.job_id:
            raise ValueError("record belongs to another job")
        if revision_id is not None:
            self.get_revision(revision_id)
        if stage_run_id is not None:
            run = self.get_stage_run(stage_run_id)
            if revision_id is not None and run.revision_id not in {None, revision_id}:
                raise ValueError("record revision does not match its stage run")

    def _attach_to_run(self, stage_run_id: str, field_name: str, record_id: str) -> None:
        run = self.get_stage_run(stage_run_id)
        values = getattr(run, field_name)
        if record_id in values:
            raise ValueError(f"{record_id!r} is already attached to {stage_run_id!r}")
        self.replace_stage_run(replace(run, **{field_name: (*values, record_id)}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job": self.job.to_dict(),
            "revisions": [item.to_dict() for item in self.revisions],
            "stage_runs": [item.to_dict() for item in self.stage_runs],
            "events": [item.to_dict() for item in self.events],
            "artifacts": [item.to_dict() for item in self.artifacts],
            "findings": [item.to_dict() for item in self.findings],
            "decisions": [item.to_dict() for item in self.decisions],
            "approvals": [item.to_dict() for item in self.approvals],
        }
