"""Versioned read models exposed to the M4 browser interface."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from ..domain import (
    ApprovalStatus,
    DecisionActor,
    EvidenceLevel,
    EvidenceMode,
    FabricationStage,
    FindingSeverity,
    JobStatus,
    StageStatus,
)


InterfaceApiVersion = Literal["1.4.0"]
INTERFACE_API_VERSION: InterfaceApiVersion = "1.4.0"


class PackageStatus(str, Enum):
    SLICER_VERIFIED = "slicer_verified"
    SLICER_VERIFIED_WITH_PHYSICAL_UNKNOWNS = "slicer_verified_with_physical_unknowns"
    FIXTURE = "fixture"


class InspectionReportStatus(str, Enum):
    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED = "failed"


class InspectionProfileStatus(str, Enum):
    EXPERIMENTAL_ANALYSIS_ONLY = "experimental_analysis_only"
    EXPERIMENTAL_UNCALIBRATED = "experimental_uncalibrated"
    INTERFACE_FIXTURE = "interface_fixture"
    INTERFACE_FIXTURE_UNCALIBRATED = "interface_fixture_uncalibrated"


PackageEvidenceLevel = Literal["R4"]
InspectionEvidenceLevel = Literal["R2", "R3", "R4"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CapabilitiesView(ApiModel):
    read_only: Literal[True]
    hardware_actions: Literal[False]


class SourceView(ApiModel):
    kind: Literal["interface_fixture", "runtime_revision"]
    label: str
    evidence_mode: Literal["real", "simulated", "fixture", "unavailable", "mixed"]
    fixture: bool
    physical_evidence_present: bool


class HealthResponse(ApiModel):
    schema_version: InterfaceApiVersion
    service: Literal["ariad-interface-api"]
    status: Literal["ok"]
    capabilities: CapabilitiesView


class ErrorResponse(ApiModel):
    detail: str


class ToolView(ApiModel):
    name: str
    version: str


class EventView(ApiModel):
    event_id: str
    stage: FabricationStage
    event_type: str
    status: StageStatus
    message: str
    sequence: int
    timestamp: str
    data: dict[str, Any]


class FindingView(ApiModel):
    finding_id: str
    code: str
    title: str
    severity: FindingSeverity
    evidence: str
    evidence_mode: EvidenceMode
    remediation: str | None
    affected_geometry: str | None
    resolved: bool
    resolution: str | None
    data: dict[str, Any]


class ArtifactView(ApiModel):
    artifact_id: str
    role: str
    media_type: str
    checksum_sha256: str
    size_bytes: int | None
    producer: str
    producer_version: str
    evidence_mode: EvidenceMode
    stage_run_id: str
    available: bool
    download_url: str
    metadata: dict[str, Any]


class DecisionView(ApiModel):
    decision_id: str
    job_id: str
    revision_id: str
    stage_run_id: str | None
    question: str
    choice: str
    rationale: str
    actor: DecisionActor
    alternatives: list[str]
    created_at: str
    data: dict[str, Any]


class ApprovalView(ApiModel):
    approval_id: str
    job_id: str
    revision_id: str
    stage_run_id: str | None
    boundary: str
    status: ApprovalStatus
    requested_by: DecisionActor
    rationale: str
    requested_at: str
    decided_at: str | None
    decided_by: DecisionActor | None


class StageView(ApiModel):
    stage_run_id: str
    stage: FabricationStage
    status: StageStatus
    attempt: int
    evidence_mode: EvidenceMode
    evidence_level: EvidenceLevel | None
    tool: ToolView
    started_at: str | None
    completed_at: str | None
    summary: str
    error_message: str | None
    events: list[EventView]
    findings: list[FindingView]
    artifacts: list[ArtifactView]
    decisions: list[DecisionView]
    approvals: list[ApprovalView]


class HardwareView(ApiModel):
    printer_selected: Literal[False]
    printer_connected: Literal[False]
    gcode_uploaded: Literal[False]
    print_started: Literal[False]


class GcodeSummaryView(ApiModel):
    checksum_sha256: str | None
    slicer_version: str | None
    layer_count: int | None
    estimated_seconds: int | None
    filament_length_mm: float | None
    filament_mass_g: float | None
    motion_bounds_mm: dict[str, float] | None
    temperatures_c: dict[str, list[float]] | None
    feature_counts: dict[str, int] | None


class PackageView(ApiModel):
    status: PackageStatus
    evidence_level: PackageEvidenceLevel | None
    allowed_claim: str
    claim_boundary: str
    hardware: HardwareView
    gcode_summary: GcodeSummaryView | None
    slicer: dict[str, Any]
    unresolved_warning_count: int


class InspectionArtifactView(ApiModel):
    artifact_id: str
    role: str
    checksum_sha256: str
    size_bytes: int
    producer: str
    producer_version: str
    evidence_mode: EvidenceMode
    checksum_verified: Literal[True]


class InspectionCheckView(ApiModel):
    check_id: str
    category: str | None
    description: str
    passed: bool
    actual: Any
    requirement: Any
    tolerance_mm: float | None
    remediation: str | None


class InspectionMessageView(ApiModel):
    severity: Literal["warning", "error"]
    code: str | None
    title: str
    message: str
    remediation: str | None


class InspectionFeatureView(ApiModel):
    feature_id: str
    kind: str
    dimensions_mm: dict[str, float]
    quantity: int
    tolerance_mm: float | None
    required: bool
    notes: str | None
    source: Literal["persisted_revision_spec"]
    fixture: bool


class InspectionReportView(ApiModel):
    report_kind: Literal["geometry", "printability", "gcode_preflight"]
    title: str
    artifact: InspectionArtifactView
    schema_version: str | None
    status: InspectionReportStatus | None
    passed: bool | None
    evidence_level: InspectionEvidenceLevel | None
    claim_boundary: str | None
    measurements: dict[str, Any]
    checks: list[InspectionCheckView]
    messages: list[InspectionMessageView]


class InspectionProfileView(ApiModel):
    profile_kind: Literal["printer", "material", "process", "orientation"]
    artifact: InspectionArtifactView
    profile_id: str
    name: str
    status: InspectionProfileStatus
    claim_boundary: str | None
    values: dict[str, Any]


class InspectionUnavailableView(ApiModel):
    role: str
    artifact_id: str | None
    checksum_sha256: str | None
    reason: Literal[
        "multiple_records",
        "file_missing",
        "size_limit",
        "size_mismatch",
        "checksum_mismatch",
        "invalid_json",
        "unsupported_shape",
    ]
    message: str


class InspectionView(ApiModel):
    features: list[InspectionFeatureView]
    reports: list[InspectionReportView]
    profiles: list[InspectionProfileView]
    unavailable: list[InspectionUnavailableView]
    max_json_bytes: int
    claim_boundary: str


ComparisonArea = Literal[
    "stage",
    "requirement",
    "feature",
    "report",
    "check",
    "finding",
    "profile",
    "artifact",
    "package",
]
ComparisonChangeKind = Literal["added", "removed", "changed"]
ComparisonRelationship = Literal[
    "same_revision",
    "parent_to_child",
    "child_to_parent",
    "same_job",
    "unrelated",
]


class ComparisonRevisionView(ApiModel):
    job_id: str
    revision_id: str
    revision_number: int
    parent_revision_id: str | None
    title: str
    job_status: JobStatus
    source_kind: Literal["interface_fixture", "runtime_revision"]
    source_label: str
    fixture: bool
    physical_evidence_present: bool
    achieved_evidence_level: EvidenceLevel | None
    package_status: PackageStatus | None
    package_evidence_level: PackageEvidenceLevel | None
    allowed_claim: str | None
    normalized_record_count: int
    compared_record_count: int
    omitted_record_count: int


class ComparisonChangeView(ApiModel):
    area: ComparisonArea
    record_key: str
    label: str
    change: ComparisonChangeKind
    base_value: dict[str, Any] | None
    candidate_value: dict[str, Any] | None
    detail_complete: bool
    boundary: str | None


class ComparisonAreaSummaryView(ApiModel):
    area: ComparisonArea
    added: int
    removed: int
    changed: int


class RevisionComparisonResponse(ApiModel):
    schema_version: InterfaceApiVersion
    capabilities: CapabilitiesView
    base: ComparisonRevisionView
    candidate: ComparisonRevisionView
    relationship: ComparisonRelationship
    complete: bool
    total_change_count: int
    returned_change_count: int
    omitted_change_count: int
    incomplete_value_count: int
    summaries: list[ComparisonAreaSummaryView]
    changes: list[ComparisonChangeView]
    max_changes: int
    max_value_bytes: int
    max_records_per_revision: int
    claim_boundary: str


class RevisionSummary(ApiModel):
    job_id: str
    revision_id: str
    availability: Literal["available", "invalid"]
    title: str | None
    job_status: JobStatus | None
    revision_number: int | None
    parent_revision_id: str | None
    stage_count: int
    latest_stage: FabricationStage | None
    latest_status: StageStatus | None
    achieved_evidence_level: EvidenceLevel | None
    warning_count: int
    updated_at: str | None
    source: SourceView | None
    error: str | None


RevisionListTruncationReason = Literal[
    "directory_entry_limit",
    "candidate_limit",
    "window_limit",
    "filesystem_error",
]


class RevisionListWindowView(ApiModel):
    discovery_complete: bool
    snapshot_consistent: Literal[False]
    ordering: Literal["job_id_revision_id_ascending"]
    directory_entries_examined: int
    observed_candidate_count: int
    offset: int
    limit: int
    returned_count: int
    observed_omitted_count: int
    next_offset: int | None
    truncation_reasons: list[RevisionListTruncationReason]
    max_directory_entries: int
    max_candidates: int
    error: str | None
    claim_boundary: str


class RevisionListResponse(ApiModel):
    schema_version: InterfaceApiVersion
    capabilities: CapabilitiesView
    revisions: list[RevisionSummary]
    window: RevisionListWindowView


class JobView(ApiModel):
    job_id: str
    title: str
    request: str
    status: JobStatus
    created_at: str
    updated_at: str
    metadata: dict[str, Any]


class RevisionView(ApiModel):
    revision_id: str
    number: int
    parent_revision_id: str | None
    reason: str
    created_at: str
    spec: dict[str, Any]


class RevisionDetailResponse(ApiModel):
    schema_version: InterfaceApiVersion
    capabilities: CapabilitiesView
    source: SourceView
    manifest_available: bool
    job: JobView
    revision: RevisionView
    stages: list[StageView]
    package: PackageView | None
    inspection: InspectionView


def read_only_capabilities() -> CapabilitiesView:
    """Return the explicit, schema-visible boundary for the local interface."""

    return CapabilitiesView(read_only=True, hardware_actions=False)
