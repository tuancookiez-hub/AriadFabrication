"""Versioned read models exposed to the M4 browser interface."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


InterfaceApiVersion = Literal["1.0.0"]
INTERFACE_API_VERSION: InterfaceApiVersion = "1.0.0"


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
    data: dict[str, Any]


class FindingView(ApiModel):
    finding_id: str
    code: str
    title: str
    severity: str
    evidence: str
    evidence_mode: Literal["real", "simulated", "fixture", "unavailable"]
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
    evidence_mode: Literal["real", "simulated", "fixture", "unavailable"]
    stage_run_id: str
    available: bool
    download_url: str
    metadata: dict[str, Any]


class StageView(ApiModel):
    stage_run_id: str
    stage: str
    status: str
    attempt: int
    evidence_mode: Literal["real", "simulated", "fixture", "unavailable"]
    evidence_level: str | None
    tool: ToolView
    started_at: str | None
    completed_at: str | None
    summary: str
    error_message: str | None
    events: list[EventView]
    findings: list[FindingView]
    artifacts: list[ArtifactView]
    decisions: list[dict[str, Any]]
    approvals: list[dict[str, Any]]


class HardwareView(ApiModel):
    printer_selected: bool
    printer_connected: bool
    gcode_uploaded: bool
    print_started: bool


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
    status: str
    evidence_level: str | None
    allowed_claim: str | None
    claim_boundary: str | None
    hardware: HardwareView
    gcode_summary: GcodeSummaryView | None
    slicer: dict[str, Any]
    unresolved_warning_count: int


class RevisionSummary(ApiModel):
    job_id: str
    revision_id: str
    availability: Literal["available", "invalid"]
    title: str | None
    job_status: str | None
    revision_number: int | None
    stage_count: int
    latest_stage: str | None
    latest_status: str | None
    achieved_evidence_level: str | None
    warning_count: int
    updated_at: str | None
    source: SourceView | None
    error: str | None


class RevisionListResponse(ApiModel):
    schema_version: InterfaceApiVersion
    capabilities: CapabilitiesView
    revisions: list[RevisionSummary]


class JobView(ApiModel):
    job_id: str
    title: str
    request: str
    status: str
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


def read_only_capabilities() -> CapabilitiesView:
    """Return the explicit, schema-visible boundary for the local interface."""

    return CapabilitiesView(read_only=True, hardware_actions=False)
