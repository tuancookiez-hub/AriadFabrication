"""Versioned read models exposed to the M4 browser interface."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


INTERFACE_API_VERSION = "1.0.0"


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CapabilitiesView(ApiModel):
    read_only: bool = True
    hardware_actions: bool = False


class SourceView(ApiModel):
    kind: str
    label: str
    evidence_mode: str
    fixture: bool
    physical_evidence_present: bool


class HealthResponse(ApiModel):
    schema_version: str = INTERFACE_API_VERSION
    service: str = "ariad-interface-api"
    status: str = "ok"
    capabilities: CapabilitiesView = Field(default_factory=CapabilitiesView)


class ToolView(ApiModel):
    name: str
    version: str


class EventView(ApiModel):
    event_id: str
    event_type: str
    status: str
    message: str
    sequence: int
    timestamp: str
    data: dict[str, Any] = Field(default_factory=dict)


class FindingView(ApiModel):
    finding_id: str
    code: str
    title: str
    severity: str
    evidence: str
    evidence_mode: str
    remediation: str | None = None
    affected_geometry: str | None = None
    resolved: bool
    resolution: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ArtifactView(ApiModel):
    artifact_id: str
    role: str
    media_type: str
    checksum_sha256: str
    size_bytes: int | None = None
    producer: str
    producer_version: str
    evidence_mode: str
    stage_run_id: str
    available: bool
    download_url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class StageView(ApiModel):
    stage_run_id: str
    stage: str
    status: str
    attempt: int
    evidence_mode: str
    evidence_level: str | None = None
    tool: ToolView
    started_at: str | None = None
    completed_at: str | None = None
    summary: str
    error_message: str | None = None
    events: list[EventView] = Field(default_factory=list)
    findings: list[FindingView] = Field(default_factory=list)
    artifacts: list[ArtifactView] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    approvals: list[dict[str, Any]] = Field(default_factory=list)


class HardwareView(ApiModel):
    printer_selected: bool
    printer_connected: bool
    gcode_uploaded: bool
    print_started: bool


class GcodeSummaryView(ApiModel):
    checksum_sha256: str | None = None
    slicer_version: str | None = None
    layer_count: int | None = None
    estimated_seconds: int | None = None
    filament_length_mm: float | None = None
    filament_mass_g: float | None = None
    motion_bounds_mm: dict[str, float] | None = None
    temperatures_c: dict[str, list[float]] | None = None
    feature_counts: dict[str, int] | None = None


class PackageView(ApiModel):
    status: str
    evidence_level: str | None = None
    allowed_claim: str | None = None
    claim_boundary: str | None = None
    hardware: HardwareView
    gcode_summary: GcodeSummaryView | None = None
    slicer: dict[str, Any] = Field(default_factory=dict)
    unresolved_warning_count: int = 0


class RevisionSummary(ApiModel):
    job_id: str
    revision_id: str
    availability: str
    title: str | None = None
    job_status: str | None = None
    revision_number: int | None = None
    stage_count: int = 0
    latest_stage: str | None = None
    latest_status: str | None = None
    achieved_evidence_level: str | None = None
    warning_count: int = 0
    updated_at: str | None = None
    source: SourceView | None = None
    error: str | None = None


class RevisionListResponse(ApiModel):
    schema_version: str = INTERFACE_API_VERSION
    capabilities: CapabilitiesView = Field(default_factory=CapabilitiesView)
    revisions: list[RevisionSummary] = Field(default_factory=list)


class JobView(ApiModel):
    job_id: str
    title: str
    request: str
    status: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RevisionView(ApiModel):
    revision_id: str
    number: int
    parent_revision_id: str | None = None
    reason: str
    created_at: str
    spec: dict[str, Any]


class RevisionDetailResponse(ApiModel):
    schema_version: str = INTERFACE_API_VERSION
    capabilities: CapabilitiesView = Field(default_factory=CapabilitiesView)
    source: SourceView
    manifest_available: bool
    job: JobView
    revision: RevisionView
    stages: list[StageView]
    package: PackageView | None = None
