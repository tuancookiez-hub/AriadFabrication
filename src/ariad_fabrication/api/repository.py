"""Fail-closed reader for persisted Fabrication Journey revisions."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping
from urllib.parse import quote

from .comparison import compare_revision_details
from .models import (
    INTERFACE_API_VERSION,
    ArtifactView,
    EventView,
    FindingView,
    GcodeSummaryView,
    HardwareView,
    InspectionArtifactView,
    InspectionCheckView,
    InspectionFeatureView,
    InspectionMessageView,
    InspectionProfileView,
    InspectionReportView,
    InspectionUnavailableView,
    InspectionView,
    JobView,
    PackageView,
    RevisionDetailResponse,
    RevisionComparisonResponse,
    RevisionListResponse,
    RevisionSummary,
    RevisionView,
    SourceView,
    StageView,
    ToolView,
    read_only_capabilities,
)


_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_TYPE_PATTERN = re.compile(
    r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+/[!#$%&'*+\-.^_`|~0-9A-Za-z]+$"
)
_EVIDENCE_MODES = {"real", "simulated", "fixture", "unavailable"}
_MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_ARTIFACT_DOWNLOAD_BYTES = 64 * 1024 * 1024
_MAX_INSPECTION_JSON_BYTES = 2 * 1024 * 1024
_MAX_INSPECTION_CHECKS = 500
_MAX_INSPECTION_FEATURES = 100
_MAX_INSPECTION_MESSAGES = 100
_MAX_INSPECTION_FIELDS = 128
_MAX_INSPECTION_DEPTH = 16
_MAX_INSPECTION_NODES = 20_000
_PHYSICAL_LEVELS = {"R6", "R7"}
_REPORT_ROLES = {
    "geometry_validation_report": ("geometry", "Geometry validation"),
    "printability_report": ("printability", "Printability assessment"),
    "gcode_preflight": ("gcode_preflight", "G-code preflight"),
}
_PROFILE_ROLES = {
    "printer_profile": "printer",
    "material_profile": "material",
    "process_profile": "process",
    "orientation_profile": "orientation",
}
_PROFILE_HEADER_FIELDS = {
    "schema_version",
    "profile_id",
    "orientation_id",
    "name",
    "status",
    "claim_boundary",
}
_INSPECTION_CLAIM_BOUNDARY = (
    "Inspection values are replayed from checksum-verified persisted reports and profiles. "
    "Selection does not rerun validation, inspect exact STEP geometry, or provide physical proof."
)


class JourneyReadError(RuntimeError):
    """Base class for safe persisted-record failures."""


class RevisionNotFoundError(JourneyReadError):
    pass


class InvalidRevisionError(JourneyReadError):
    pass


class ArtifactNotFoundError(JourneyReadError):
    pass


class ArtifactIntegrityError(JourneyReadError):
    pass


class ArtifactTooLargeError(JourneyReadError):
    pass


@dataclass(frozen=True)
class VerifiedArtifactSnapshot:
    content: bytes
    filename: str
    media_type: str
    checksum_sha256: str
    size_bytes: int
    evidence_mode: str


@dataclass(frozen=True)
class _LoadedRevision:
    root: Path
    journey: dict[str, Any]
    manifest: dict[str, Any] | None
    package: dict[str, Any] | None
    fixture: dict[str, Any] | None
    revision: dict[str, Any]
    stage_runs: dict[str, dict[str, Any]]
    events: dict[str, dict[str, Any]]
    artifacts: dict[str, dict[str, Any]]
    findings: dict[str, dict[str, Any]]
    decisions: dict[str, dict[str, Any]]
    approvals: dict[str, dict[str, Any]]


class _InspectionShapeError(ValueError):
    pass


class JourneyRepository:
    """Read one immutable revision tree without offering mutation or hardware actions."""

    def __init__(self, runs_root: Path | str) -> None:
        self.runs_root = Path(runs_root).expanduser().resolve()

    def list_revisions(self) -> RevisionListResponse:
        items: list[RevisionSummary] = []
        if not self.runs_root.is_dir():
            return RevisionListResponse(
                schema_version=INTERFACE_API_VERSION,
                capabilities=read_only_capabilities(),
                revisions=[],
            )
        candidates = sorted(
            (
                revision
                for job in self.runs_root.iterdir()
                if job.is_dir()
                for revision in (job / "revisions").glob("*")
                if revision.is_dir()
            ),
            key=lambda item: (item.parent.parent.name, item.name),
        )
        for revision_root in candidates:
            job_id = revision_root.parent.parent.name
            revision_id = revision_root.name
            try:
                detail = self._get_revision(job_id, revision_id, include_inspection=False)
            except JourneyReadError as exc:
                items.append(
                    RevisionSummary(
                        job_id=job_id,
                        revision_id=revision_id,
                        availability="invalid",
                        title=None,
                        job_status=None,
                        revision_number=None,
                        parent_revision_id=None,
                        stage_count=0,
                        latest_stage=None,
                        latest_status=None,
                        achieved_evidence_level=None,
                        warning_count=0,
                        updated_at=None,
                        source=None,
                        error=str(exc),
                    )
                )
                continue
            latest = detail.stages[-1] if detail.stages else None
            achieved = next(
                (
                    stage.evidence_level
                    for stage in reversed(detail.stages)
                    if stage.evidence_level is not None
                ),
                None,
            )
            warning_count = sum(
                1
                for stage in detail.stages
                for finding in stage.findings
                if not finding.resolved and finding.severity in {"warning", "error", "critical"}
            )
            items.append(
                RevisionSummary(
                    job_id=job_id,
                    revision_id=revision_id,
                    availability="available",
                    title=detail.job.title,
                    job_status=detail.job.status,
                    revision_number=detail.revision.number,
                    parent_revision_id=detail.revision.parent_revision_id,
                    stage_count=len(detail.stages),
                    latest_stage=latest.stage if latest else None,
                    latest_status=latest.status if latest else None,
                    achieved_evidence_level=achieved,
                    warning_count=warning_count,
                    updated_at=detail.job.updated_at,
                    source=detail.source,
                    error=None,
                )
            )
        items.sort(key=lambda item: item.updated_at or "", reverse=True)
        return RevisionListResponse(
            schema_version=INTERFACE_API_VERSION,
            capabilities=read_only_capabilities(),
            revisions=items,
        )

    def get_revision(self, job_id: str, revision_id: str) -> RevisionDetailResponse:
        return self._get_revision(job_id, revision_id, include_inspection=True)

    def compare_revisions(
        self,
        base_job_id: str,
        base_revision_id: str,
        candidate_job_id: str,
        candidate_revision_id: str,
    ) -> RevisionComparisonResponse:
        """Compare two persisted views without mutating or rerunning either revision."""

        base = self.get_revision(base_job_id, base_revision_id)
        candidate = self.get_revision(candidate_job_id, candidate_revision_id)
        return compare_revision_details(base, candidate)

    def _get_revision(
        self,
        job_id: str,
        revision_id: str,
        *,
        include_inspection: bool,
    ) -> RevisionDetailResponse:
        loaded = self._load(job_id, revision_id)
        job = _mapping(loaded.journey.get("job"), "journey.job")
        stage_views = [self._stage_view(loaded, stage_id) for stage_id in loaded.revision["stage_run_ids"]]
        source = self._source_view(loaded, stage_views)
        return RevisionDetailResponse(
            schema_version=INTERFACE_API_VERSION,
            capabilities=read_only_capabilities(),
            source=source,
            manifest_available=loaded.manifest is not None,
            job=JobView(
                job_id=_text(job.get("job_id"), "journey.job.job_id"),
                title=_text(job.get("title"), "journey.job.title"),
                request=_text(job.get("request"), "journey.job.request"),
                status=_text(job.get("status"), "journey.job.status"),
                created_at=_text(job.get("created_at"), "journey.job.created_at"),
                updated_at=_text(job.get("updated_at"), "journey.job.updated_at"),
                metadata=_mapping(job.get("metadata", {}), "journey.job.metadata"),
            ),
            revision=RevisionView(
                revision_id=_text(loaded.revision.get("revision_id"), "revision_id"),
                number=_integer(loaded.revision.get("number"), "revision.number", minimum=1),
                parent_revision_id=_optional_text(loaded.revision.get("parent_revision_id")),
                reason=_text(loaded.revision.get("reason"), "revision.reason"),
                created_at=_text(loaded.revision.get("created_at"), "revision.created_at"),
                spec=_mapping(loaded.revision.get("spec"), "revision.spec"),
            ),
            stages=stage_views,
            package=self._package_view(loaded.package),
            inspection=(
                self._inspection_view(loaded)
                if include_inspection
                else _empty_inspection_view()
            ),
        )

    def get_artifact(
        self,
        job_id: str,
        revision_id: str,
        artifact_id: str,
    ) -> VerifiedArtifactSnapshot:
        loaded = self._load(job_id, revision_id)
        artifact = loaded.artifacts.get(artifact_id)
        if artifact is None:
            raise ArtifactNotFoundError("artifact is not recorded in this revision")
        path = self._artifact_path(loaded.root, artifact)
        if not path.is_file():
            raise ArtifactNotFoundError("recorded artifact file is unavailable")
        media_type = _media_type(artifact.get("media_type"), "artifact.media_type")
        evidence_mode = _evidence_mode(
            artifact.get("evidence_mode"), "artifact.evidence_mode"
        )
        expected_size = artifact.get("size_bytes")
        recorded_size = (
            _integer(expected_size, "artifact.size_bytes")
            if expected_size is not None
            else None
        )
        if recorded_size is not None and recorded_size > MAX_ARTIFACT_DOWNLOAD_BYTES:
            raise ArtifactTooLargeError(
                f"recorded artifact exceeds the {MAX_ARTIFACT_DOWNLOAD_BYTES}-byte "
                "verified-download limit"
            )
        read_size = (
            recorded_size + 1
            if recorded_size is not None
            else MAX_ARTIFACT_DOWNLOAD_BYTES + 1
        )
        try:
            with path.open("rb") as artifact_file:
                content = artifact_file.read(read_size)
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError("recorded artifact file is unavailable") from exc
        except OSError as exc:
            raise ArtifactIntegrityError("recorded artifact file could not be read") from exc
        if len(content) > MAX_ARTIFACT_DOWNLOAD_BYTES:
            raise ArtifactTooLargeError(
                f"artifact exceeds the {MAX_ARTIFACT_DOWNLOAD_BYTES}-byte "
                "verified-download limit"
            )
        if recorded_size is not None and len(content) != recorded_size:
            raise ArtifactIntegrityError("recorded artifact size does not match the file")
        expected_hash = _checksum(artifact.get("checksum_sha256"), "artifact.checksum_sha256")
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != expected_hash:
            raise ArtifactIntegrityError("recorded artifact checksum does not match the file")
        return VerifiedArtifactSnapshot(
            content=content,
            filename=path.name,
            media_type=media_type,
            checksum_sha256=expected_hash,
            size_bytes=len(content),
            evidence_mode=evidence_mode,
        )

    def _load(self, job_id: str, revision_id: str) -> _LoadedRevision:
        revision_root = self._revision_root(job_id, revision_id)
        if not revision_root.is_dir():
            raise RevisionNotFoundError("persisted revision was not found")
        journey = _load_json(
            revision_root / "journey.json", required=True, confined_to=revision_root
        )
        manifest = _load_json(
            revision_root / "manifest.json", required=False, confined_to=revision_root
        )
        package = _load_json(
            revision_root / "fabrication" / "package.json",
            required=False,
            confined_to=revision_root,
        )
        fixture = _load_json(
            revision_root / "fixture.json", required=False, confined_to=revision_root
        )
        if journey.get("schema_version") != "1.0.0":
            raise InvalidRevisionError("unsupported journey schema version")
        job = _mapping(journey.get("job"), "journey.job")
        if job.get("job_id") != job_id:
            raise InvalidRevisionError("journey job id does not match its directory")
        revisions = _indexed(journey.get("revisions"), "revision_id", "journey.revisions")
        revision = revisions.get(revision_id)
        if revision is None:
            raise InvalidRevisionError("journey does not contain the requested revision")
        stage_runs = _indexed(journey.get("stage_runs"), "stage_run_id", "journey.stage_runs")
        events = _indexed(journey.get("events"), "event_id", "journey.events")
        all_journey_artifacts = _indexed(
            journey.get("artifacts"), "artifact_id", "journey.artifacts"
        )
        journey_artifacts = {
            record_id: record
            for record_id, record in all_journey_artifacts.items()
            if record.get("revision_id") == revision_id
        }
        all_findings = _indexed(journey.get("findings"), "finding_id", "journey.findings")
        findings = {
            record_id: record
            for record_id, record in all_findings.items()
            if record.get("revision_id") == revision_id
        }
        decisions = _indexed(journey.get("decisions"), "decision_id", "journey.decisions")
        approvals = _indexed(journey.get("approvals"), "approval_id", "journey.approvals")
        stage_ids = _string_list(revision.get("stage_run_ids"), "revision.stage_run_ids")
        for stage_id in stage_ids:
            stage = stage_runs.get(stage_id)
            if stage is None:
                raise InvalidRevisionError(f"revision references missing stage run {stage_id!r}")
            if stage.get("job_id") != job_id or stage.get("revision_id") != revision_id:
                raise InvalidRevisionError("stage run ownership does not match the revision")
        artifacts = journey_artifacts
        if manifest is not None:
            if manifest.get("schema_version") != "1.0.0":
                raise InvalidRevisionError("unsupported manifest schema version")
            if manifest.get("job_id") != job_id or manifest.get("revision_id") != revision_id:
                raise InvalidRevisionError("manifest ownership does not match the revision")
            if _string_list(manifest.get("stage_run_ids"), "manifest.stage_run_ids") != stage_ids:
                raise InvalidRevisionError("manifest stage runs differ from the revision")
            manifest_artifacts = _indexed(
                manifest.get("artifacts"), "artifact_id", "manifest.artifacts"
            )
            if manifest_artifacts != journey_artifacts:
                raise InvalidRevisionError("journey and manifest artifact records differ")
            manifest_findings = _indexed(
                manifest.get("findings"), "finding_id", "manifest.findings"
            )
            if manifest_findings != findings:
                raise InvalidRevisionError("journey and manifest finding records differ")
            artifacts = manifest_artifacts
        if package is not None:
            if package.get("job_id") != job_id or package.get("revision_id") != revision_id:
                raise InvalidRevisionError("fabrication package ownership does not match the revision")
        if fixture is not None:
            if fixture.get("classification") != "interface_fixture":
                raise InvalidRevisionError("fixture marker has an unsupported classification")
            if fixture.get("physical_validation") is not False:
                raise InvalidRevisionError("interface fixtures must explicitly deny physical validation")
        return _LoadedRevision(
            root=revision_root,
            journey=journey,
            manifest=manifest,
            package=package,
            fixture=fixture,
            revision=revision,
            stage_runs=stage_runs,
            events=events,
            artifacts=artifacts,
            findings=findings,
            decisions=decisions,
            approvals=approvals,
        )

    def _stage_view(self, loaded: _LoadedRevision, stage_id: str) -> StageView:
        stage = loaded.stage_runs[stage_id]
        events = [
            EventView(
                event_id=_text(item.get("event_id"), "event.event_id"),
                event_type=_text(item.get("event_type"), "event.event_type"),
                status=_text(item.get("status"), "event.status"),
                message=_text(item.get("message"), "event.message"),
                sequence=_integer(item.get("sequence"), "event.sequence", minimum=1),
                timestamp=_text(item.get("timestamp"), "event.timestamp"),
                data=_mapping(item.get("data", {}), "event.data"),
            )
            for item in self._records(
                loaded.events,
                stage.get("event_ids"),
                "stage.event_ids",
                expected_stage_id=stage_id,
            )
        ]
        events.sort(key=lambda item: item.sequence)
        findings = [
            FindingView(
                finding_id=_text(item.get("finding_id"), "finding.finding_id"),
                code=_text(item.get("code"), "finding.code"),
                title=_text(item.get("title"), "finding.title"),
                severity=_text(item.get("severity"), "finding.severity"),
                evidence=_text(item.get("evidence"), "finding.evidence"),
                evidence_mode=_evidence_mode(
                    item.get("evidence_mode"), "finding.evidence_mode"
                ),
                remediation=_optional_text(item.get("remediation")),
                affected_geometry=_optional_text(item.get("affected_geometry")),
                resolved=bool(item.get("resolved", False)),
                resolution=_optional_text(item.get("resolution")),
                data=_mapping(item.get("data", {}), "finding.data"),
            )
            for item in self._records(
                loaded.findings,
                stage.get("finding_ids"),
                "stage.finding_ids",
                expected_stage_id=stage_id,
            )
        ]
        artifacts = [
            self._artifact_view(loaded, item)
            for item in self._records(
                loaded.artifacts,
                stage.get("artifact_ids"),
                "stage.artifact_ids",
                expected_stage_id=stage_id,
            )
        ]
        decisions = self._records(
            loaded.decisions,
            stage.get("decision_ids"),
            "stage.decision_ids",
            expected_stage_id=stage_id,
        )
        approvals = self._records(
            loaded.approvals,
            stage.get("approval_ids"),
            "stage.approval_ids",
            expected_stage_id=stage_id,
        )
        tool = _mapping(stage.get("tool"), "stage.tool")
        return StageView(
            stage_run_id=stage_id,
            stage=_text(stage.get("stage"), "stage.stage"),
            status=_text(stage.get("status"), "stage.status"),
            attempt=_integer(stage.get("attempt"), "stage.attempt", minimum=1),
            evidence_mode=_evidence_mode(
                stage.get("evidence_mode"), "stage.evidence_mode"
            ),
            evidence_level=_optional_text(stage.get("evidence_level")),
            tool=ToolView(
                name=_text(tool.get("name"), "stage.tool.name"),
                version=_text(tool.get("version"), "stage.tool.version"),
            ),
            started_at=_optional_text(stage.get("started_at")),
            completed_at=_optional_text(stage.get("completed_at")),
            summary=str(stage.get("summary", "")).strip(),
            error_message=_optional_text(stage.get("error_message")),
            events=events,
            findings=findings,
            artifacts=artifacts,
            decisions=decisions,
            approvals=approvals,
        )

    def _artifact_view(
        self, loaded: _LoadedRevision, artifact: dict[str, Any]
    ) -> ArtifactView:
        artifact_id = _text(artifact.get("artifact_id"), "artifact.artifact_id")
        path = self._artifact_path(loaded.root, artifact)
        expected_size = artifact.get("size_bytes")
        available = path.is_file()
        if available and expected_size is not None:
            available = path.stat().st_size == _integer(expected_size, "artifact.size_bytes")
        return ArtifactView(
            artifact_id=artifact_id,
            role=_text(artifact.get("role"), "artifact.role"),
            media_type=_media_type(artifact.get("media_type"), "artifact.media_type"),
            checksum_sha256=_checksum(
                artifact.get("checksum_sha256"), "artifact.checksum_sha256"
            ),
            size_bytes=(
                _integer(expected_size, "artifact.size_bytes")
                if expected_size is not None
                else None
            ),
            producer=_text(artifact.get("producer"), "artifact.producer"),
            producer_version=_text(
                artifact.get("producer_version"), "artifact.producer_version"
            ),
            evidence_mode=_evidence_mode(
                artifact.get("evidence_mode"), "artifact.evidence_mode"
            ),
            stage_run_id=_text(artifact.get("stage_run_id"), "artifact.stage_run_id"),
            available=available,
            download_url=(
                f"/api/v1/revisions/{quote(loaded.revision['job_id'], safe='')}"
                f"/{quote(loaded.revision['revision_id'], safe='')}/artifacts/"
                f"{quote(artifact_id, safe='')}"
            ),
            metadata=_mapping(artifact.get("metadata", {}), "artifact.metadata"),
        )

    def _source_view(
        self, loaded: _LoadedRevision, stages: list[StageView]
    ) -> SourceView:
        modes = {stage.evidence_mode for stage in stages}
        mode = next(iter(modes)) if len(modes) == 1 else "mixed"
        fixture = loaded.fixture is not None
        physical = any(
            stage.evidence_level in _PHYSICAL_LEVELS and stage.evidence_mode == "real"
            for stage in stages
        )
        label = (
            _text(loaded.fixture.get("label"), "fixture.label")
            if loaded.fixture is not None
            else "Persisted local pipeline revision"
        )
        return SourceView(
            kind="interface_fixture" if fixture else "runtime_revision",
            label=label,
            evidence_mode=mode,
            fixture=fixture,
            physical_evidence_present=physical,
        )

    def _package_view(self, package: dict[str, Any] | None) -> PackageView | None:
        if package is None:
            return None
        hardware = _mapping(package.get("hardware"), "package.hardware")
        gcode = package.get("gcode_summary")
        gcode_view = None
        if gcode is not None:
            gcode = _mapping(gcode, "package.gcode_summary")
            gcode_view = GcodeSummaryView(
                checksum_sha256=_optional_text(gcode.get("checksum_sha256")),
                slicer_version=_optional_text(gcode.get("slicer_version")),
                layer_count=_optional_integer(gcode.get("layer_count"), "gcode.layer_count"),
                estimated_seconds=_optional_integer(
                    gcode.get("estimated_seconds"), "gcode.estimated_seconds"
                ),
                filament_length_mm=_optional_number(gcode.get("filament_length_mm")),
                filament_mass_g=_optional_number(gcode.get("filament_mass_g")),
                motion_bounds_mm=_optional_number_mapping(gcode.get("motion_bounds_mm")),
                temperatures_c=_optional_number_list_mapping(gcode.get("temperatures_c")),
                feature_counts=_optional_integer_mapping(gcode.get("feature_counts")),
            )
        warnings = package.get("unresolved_warning_findings", [])
        if not isinstance(warnings, list):
            raise InvalidRevisionError("package unresolved warnings must be a list")
        return PackageView(
            status=_text(package.get("status"), "package.status"),
            evidence_level=_optional_text(package.get("evidence_level")),
            allowed_claim=_optional_text(package.get("allowed_claim")),
            claim_boundary=_optional_text(package.get("claim_boundary")),
            hardware=HardwareView(
                printer_selected=_boolean(hardware.get("printer_selected"), "hardware.printer_selected"),
                printer_connected=_boolean(
                    hardware.get("printer_connected"), "hardware.printer_connected"
                ),
                gcode_uploaded=_boolean(hardware.get("gcode_uploaded"), "hardware.gcode_uploaded"),
                print_started=_boolean(hardware.get("print_started"), "hardware.print_started"),
            ),
            gcode_summary=gcode_view,
            slicer=_mapping(package.get("slicer", {}), "package.slicer"),
            unresolved_warning_count=len(warnings),
        )

    def _inspection_view(self, loaded: _LoadedRevision) -> InspectionView:
        features: list[InspectionFeatureView] = []
        reports: list[InspectionReportView] = []
        profiles: list[InspectionProfileView] = []
        unavailable: list[InspectionUnavailableView] = []

        is_gate_fixture = loaded.fixture is not None and loaded.fixture.get("scenario") is not None
        if not is_gate_fixture:
            try:
                features = _inspection_feature_views(
                    _mapping(loaded.revision.get("spec"), "revision.spec"),
                    fixture=loaded.fixture is not None,
                )
            except (InvalidRevisionError, _InspectionShapeError):
                unavailable.append(
                    InspectionUnavailableView(
                        role="revision_spec_features",
                        artifact_id=None,
                        checksum_sha256=None,
                        reason="unsupported_shape",
                        message=(
                            "The persisted revision features do not match the bounded inspection shape."
                        ),
                    )
                )

        for role, (report_kind, title) in _REPORT_ROLES.items():
            artifact, value, error = self._read_inspection_json(loaded, role)
            if error is not None:
                unavailable.append(error)
            elif artifact is not None and value is not None:
                try:
                    reports.append(
                        _inspection_report_view(
                            report_kind=report_kind,
                            title=title,
                            artifact=artifact,
                            value=value,
                        )
                    )
                except _InspectionShapeError:
                    unavailable.append(
                        _inspection_unavailable(
                            loaded,
                            role,
                            "unsupported_shape",
                            "The checksum-verified report does not match the bounded inspection shape.",
                        )
                    )

        for role, profile_kind in _PROFILE_ROLES.items():
            artifact, value, error = self._read_inspection_json(loaded, role)
            if error is not None:
                unavailable.append(error)
            elif artifact is not None and value is not None:
                try:
                    profiles.append(
                        _inspection_profile_view(
                            profile_kind=profile_kind,
                            artifact=artifact,
                            value=value,
                        )
                    )
                except _InspectionShapeError:
                    unavailable.append(
                        _inspection_unavailable(
                            loaded,
                            role,
                            "unsupported_shape",
                            "The checksum-verified profile does not match the bounded inspection shape.",
                        )
                    )

        return InspectionView(
            features=features,
            reports=reports,
            profiles=profiles,
            unavailable=unavailable,
            max_json_bytes=_MAX_INSPECTION_JSON_BYTES,
            claim_boundary=_INSPECTION_CLAIM_BOUNDARY,
        )

    def _read_inspection_json(
        self,
        loaded: _LoadedRevision,
        role: str,
    ) -> tuple[
        InspectionArtifactView | None,
        dict[str, Any] | None,
        InspectionUnavailableView | None,
    ]:
        matches = [item for item in loaded.artifacts.values() if item.get("role") == role]
        if not matches:
            return None, None, None
        if len(matches) != 1:
            return (
                None,
                None,
                InspectionUnavailableView(
                    role=role,
                    artifact_id=None,
                    checksum_sha256=None,
                    reason="multiple_records",
                    message="More than one persisted artifact claims this inspection role.",
                ),
            )
        record = matches[0]
        artifact_id = _text(record.get("artifact_id"), "artifact.artifact_id")
        checksum = _checksum(record.get("checksum_sha256"), "artifact.checksum_sha256")
        path = self._artifact_path(loaded.root, record)
        if not path.is_file():
            return None, None, _inspection_unavailable_for_record(
                role, artifact_id, checksum, "file_missing", "The recorded report file is missing."
            )
        actual_size = path.stat().st_size
        if actual_size > _MAX_INSPECTION_JSON_BYTES:
            return None, None, _inspection_unavailable_for_record(
                role,
                artifact_id,
                checksum,
                "size_limit",
                "The recorded report exceeds the bounded inspection size limit.",
            )
        expected_size = record.get("size_bytes")
        if expected_size is not None and actual_size != _integer(
            expected_size, "artifact.size_bytes"
        ):
            return None, None, _inspection_unavailable_for_record(
                role,
                artifact_id,
                checksum,
                "size_mismatch",
                "The recorded report size does not match the persisted artifact record.",
            )
        try:
            payload = path.read_bytes()
        except OSError:
            return None, None, _inspection_unavailable_for_record(
                role, artifact_id, checksum, "file_missing", "The recorded report cannot be read."
            )
        if len(payload) > _MAX_INSPECTION_JSON_BYTES:
            return None, None, _inspection_unavailable_for_record(
                role,
                artifact_id,
                checksum,
                "size_limit",
                "The recorded report exceeds the bounded inspection size limit.",
            )
        if expected_size is not None and len(payload) != _integer(
            expected_size, "artifact.size_bytes"
        ):
            return None, None, _inspection_unavailable_for_record(
                role,
                artifact_id,
                checksum,
                "size_mismatch",
                "The recorded report size changed while it was being read.",
            )
        if hashlib.sha256(payload).hexdigest() != checksum:
            return None, None, _inspection_unavailable_for_record(
                role,
                artifact_id,
                checksum,
                "checksum_mismatch",
                "The recorded report checksum does not match its persisted artifact record.",
            )
        try:
            value = json.loads(
                payload.decode("utf-8"),
                parse_constant=_reject_inspection_json_constant,
            )
        except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
            return None, None, _inspection_unavailable_for_record(
                role,
                artifact_id,
                checksum,
                "invalid_json",
                "The checksum-verified report is not bounded UTF-8 JSON.",
            )
        if not isinstance(value, dict) or not _inspection_json_is_bounded(value):
            return None, None, _inspection_unavailable_for_record(
                role,
                artifact_id,
                checksum,
                "unsupported_shape",
                "The checksum-verified report exceeds the bounded inspection shape.",
            )
        artifact = InspectionArtifactView(
            artifact_id=artifact_id,
            role=role,
            checksum_sha256=checksum,
            size_bytes=actual_size,
            producer=_text(record.get("producer"), "artifact.producer"),
            producer_version=_text(
                record.get("producer_version"), "artifact.producer_version"
            ),
            evidence_mode=_evidence_mode(
                record.get("evidence_mode"), "artifact.evidence_mode"
            ),
            checksum_verified=True,
        )
        return artifact, value, None

    def _records(
        self,
        index: dict[str, dict[str, Any]],
        ids: Any,
        name: str,
        *,
        expected_stage_id: str | None = None,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for record_id in _string_list(ids, name):
            record = index.get(record_id)
            if record is None:
                raise InvalidRevisionError(f"{name} references missing record {record_id!r}")
            if expected_stage_id is not None and record.get("stage_run_id") != expected_stage_id:
                raise InvalidRevisionError(f"{name} references a record owned by another stage")
            records.append(record)
        return records

    def _revision_root(self, job_id: str, revision_id: str) -> Path:
        for value, name in ((job_id, "job id"), (revision_id, "revision id")):
            if not _ID_PATTERN.fullmatch(value):
                raise RevisionNotFoundError(f"invalid {name}")
        candidate = (self.runs_root / job_id / "revisions" / revision_id).resolve()
        if not candidate.is_relative_to(self.runs_root):
            raise RevisionNotFoundError("revision path escapes the configured root")
        return candidate

    def _artifact_path(self, revision_root: Path, artifact: Mapping[str, Any]) -> Path:
        raw = _text(artifact.get("path"), "artifact.path").replace("\\", "/")
        relative = PurePosixPath(raw)
        if relative.is_absolute() or ".." in relative.parts or any(":" in item for item in relative.parts):
            raise InvalidRevisionError("artifact contains an unsafe relative path")
        candidate = (revision_root / Path(*relative.parts)).resolve()
        if not candidate.is_relative_to(revision_root):
            raise InvalidRevisionError("artifact path escapes its revision")
        return candidate


def _empty_inspection_view() -> InspectionView:
    return InspectionView(
        features=[],
        reports=[],
        profiles=[],
        unavailable=[],
        max_json_bytes=_MAX_INSPECTION_JSON_BYTES,
        claim_boundary=_INSPECTION_CLAIM_BOUNDARY,
    )


def _inspection_feature_views(
    spec: dict[str, Any],
    *,
    fixture: bool,
) -> list[InspectionFeatureView]:
    raw_features = spec.get("features", [])
    if not isinstance(raw_features, list) or len(raw_features) > _MAX_INSPECTION_FEATURES:
        raise _InspectionShapeError("inspection features are not bounded")
    features: list[InspectionFeatureView] = []
    for raw in raw_features:
        if not isinstance(raw, dict):
            raise _InspectionShapeError("inspection feature must be an object")
        raw_dimensions = raw.get("dimensions_mm", {})
        if not isinstance(raw_dimensions, dict) or len(raw_dimensions) > 32:
            raise _InspectionShapeError("inspection feature dimensions are not bounded")
        dimensions: dict[str, float] = {}
        for name, value in raw_dimensions.items():
            if not isinstance(name, str) or not name.strip():
                raise _InspectionShapeError("inspection dimension name is invalid")
            number = _inspection_optional_float(value)
            if number is None:
                raise _InspectionShapeError("inspection dimension value is required")
            dimensions[name] = number
        quantity = raw.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise _InspectionShapeError("inspection feature quantity is invalid")
        required = raw.get("required")
        if not isinstance(required, bool):
            raise _InspectionShapeError("inspection feature required state is invalid")
        features.append(
            InspectionFeatureView(
                feature_id=_inspection_text(raw.get("feature_id")),
                kind=_inspection_text(raw.get("kind")),
                dimensions_mm=dimensions,
                quantity=quantity,
                tolerance_mm=_inspection_optional_float(raw.get("tolerance_mm")),
                required=required,
                notes=_inspection_optional_text(raw.get("notes")),
                source="persisted_revision_spec",
                fixture=fixture,
            )
        )
    return features


def _inspection_report_view(
    *,
    report_kind: str,
    title: str,
    artifact: InspectionArtifactView,
    value: dict[str, Any],
) -> InspectionReportView:
    raw_checks = value.get("checks", [])
    if not isinstance(raw_checks, list) or len(raw_checks) > _MAX_INSPECTION_CHECKS:
        raise _InspectionShapeError("inspection report checks are not bounded")
    checks: list[InspectionCheckView] = []
    for raw in raw_checks:
        if not isinstance(raw, dict):
            raise _InspectionShapeError("inspection check must be an object")
        check_id = _inspection_text(raw.get("check_id"))
        passed = raw.get("passed")
        if not isinstance(passed, bool):
            raise _InspectionShapeError("inspection check pass state must be a boolean")
        actual = raw.get("actual") if "actual" in raw else raw.get("measured")
        requirement = raw.get("expected") if "expected" in raw else raw.get("requirement")
        checks.append(
            InspectionCheckView(
                check_id=check_id,
                category=_inspection_optional_text(raw.get("category")),
                description=(
                    _inspection_optional_text(raw.get("description"))
                    or check_id.replace("_", " ")
                ),
                passed=passed,
                actual=actual,
                requirement=requirement,
                tolerance_mm=_inspection_optional_float(raw.get("tolerance_mm")),
                remediation=_inspection_optional_text(raw.get("remediation")),
            )
        )
    raw_measurements = value.get("measurements", {})
    if not isinstance(raw_measurements, dict) or len(raw_measurements) > _MAX_INSPECTION_FIELDS:
        raise _InspectionShapeError("inspection measurements are not bounded")
    raw_passed = value.get("passed")
    if raw_passed is not None and not isinstance(raw_passed, bool):
        raise _InspectionShapeError("inspection report pass state must be a boolean or null")
    messages = [
        *_inspection_messages(value.get("warnings", []), severity="warning"),
        *_inspection_messages(value.get("errors", []), severity="error"),
    ]
    return InspectionReportView(
        report_kind=report_kind,
        title=title,
        artifact=artifact,
        schema_version=_inspection_optional_text(value.get("schema_version")),
        status=_inspection_optional_text(value.get("status")),
        passed=raw_passed,
        evidence_level=_inspection_optional_text(value.get("evidence_level")),
        claim_boundary=_inspection_optional_text(value.get("claim_boundary")),
        measurements=raw_measurements,
        checks=checks,
        messages=messages,
    )


def _inspection_profile_view(
    *,
    profile_kind: str,
    artifact: InspectionArtifactView,
    value: dict[str, Any],
) -> InspectionProfileView:
    values = {key: item for key, item in value.items() if key not in _PROFILE_HEADER_FIELDS}
    if len(values) > _MAX_INSPECTION_FIELDS:
        raise _InspectionShapeError("inspection profile fields are not bounded")
    return InspectionProfileView(
        profile_kind=profile_kind,
        artifact=artifact,
        profile_id=_inspection_text(value.get("profile_id") or value.get("orientation_id")),
        name=_inspection_text(value.get("name")),
        status=_inspection_text(value.get("status")),
        claim_boundary=_inspection_optional_text(value.get("claim_boundary")),
        values=values,
    )


def _inspection_messages(value: Any, *, severity: str) -> list[InspectionMessageView]:
    if not isinstance(value, list) or len(value) > _MAX_INSPECTION_MESSAGES:
        raise _InspectionShapeError("inspection messages are not bounded")
    messages: list[InspectionMessageView] = []
    for item in value:
        if isinstance(item, str):
            message = _inspection_text(item)
            messages.append(
                InspectionMessageView(
                    severity=severity,
                    code=None,
                    title=f"Recorded {severity}",
                    message=message,
                    remediation=None,
                )
            )
            continue
        if not isinstance(item, dict):
            raise _InspectionShapeError("inspection message must be text or an object")
        code = _inspection_optional_text(item.get("code"))
        title = _inspection_optional_text(item.get("title")) or code or f"Recorded {severity}"
        message = (
            _inspection_optional_text(item.get("evidence"))
            or _inspection_optional_text(item.get("message"))
            or title
        )
        messages.append(
            InspectionMessageView(
                severity=severity,
                code=code,
                title=title,
                message=message,
                remediation=(
                    _inspection_optional_text(item.get("physical_resolution"))
                    or _inspection_optional_text(item.get("remediation"))
                ),
            )
        )
    return messages


def _inspection_unavailable(
    loaded: _LoadedRevision,
    role: str,
    reason: str,
    message: str,
) -> InspectionUnavailableView:
    matches = [item for item in loaded.artifacts.values() if item.get("role") == role]
    if len(matches) != 1:
        return InspectionUnavailableView(
            role=role,
            artifact_id=None,
            checksum_sha256=None,
            reason=reason,
            message=message,
        )
    record = matches[0]
    checksum = _inspection_optional_text(record.get("checksum_sha256"))
    if checksum is not None and not _SHA256_PATTERN.fullmatch(checksum.lower()):
        checksum = None
    return InspectionUnavailableView(
        role=role,
        artifact_id=_inspection_optional_text(record.get("artifact_id")),
        checksum_sha256=checksum.lower() if checksum is not None else None,
        reason=reason,
        message=message,
    )


def _inspection_unavailable_for_record(
    role: str,
    artifact_id: str,
    checksum: str,
    reason: str,
    message: str,
) -> InspectionUnavailableView:
    return InspectionUnavailableView(
        role=role,
        artifact_id=artifact_id,
        checksum_sha256=checksum,
        reason=reason,
        message=message,
    )


def _inspection_text(value: Any) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise _InspectionShapeError("inspection text is required")
    return normalized


def _inspection_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _inspection_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise _InspectionShapeError("inspection number cannot be a boolean")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _InspectionShapeError("inspection number is invalid") from exc
    if not math.isfinite(result):
        raise _InspectionShapeError("inspection number must be finite")
    return result


def _reject_inspection_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _inspection_json_is_bounded(value: Any) -> bool:
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_INSPECTION_NODES or depth > _MAX_INSPECTION_DEPTH:
            return False
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                return False
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and not math.isfinite(item):
            return False
        elif item is not None and not isinstance(item, (str, int, float, bool)):
            return False
    return True


def _load_json(
    path: Path,
    *,
    required: bool,
    confined_to: Path,
) -> dict[str, Any] | None:
    resolved = path.resolve()
    if not resolved.is_relative_to(confined_to):
        raise InvalidRevisionError(f"persisted record {path.name!r} escapes its revision")
    if not resolved.is_file():
        if required:
            raise InvalidRevisionError(f"required persisted record {path.name!r} is missing")
        return None
    if resolved.stat().st_size > _MAX_JSON_BYTES:
        raise InvalidRevisionError(f"persisted record {path.name!r} exceeds the size limit")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidRevisionError(f"persisted record {path.name!r} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise InvalidRevisionError(f"persisted record {path.name!r} must contain an object")
    return value


def _indexed(value: Any, id_field: str, name: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise InvalidRevisionError(f"{name} must be a list")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        record = _mapping(item, name)
        record_id = _text(record.get(id_field), f"{name}.{id_field}")
        if record_id in result:
            raise InvalidRevisionError(f"{name} contains duplicate id {record_id!r}")
        result[record_id] = record
    return result


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidRevisionError(f"{name} must be an object")
    return value


def _text(value: Any, name: str) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise InvalidRevisionError(f"{name} is required")
    return normalized


def _evidence_mode(value: Any, name: str) -> str:
    normalized = _text(value, name)
    if normalized not in _EVIDENCE_MODES:
        raise InvalidRevisionError(f"{name} is not a supported evidence mode")
    return normalized


def _media_type(value: Any, name: str) -> str:
    normalized = _text(value, name)
    if not _MEDIA_TYPE_PATTERN.fullmatch(normalized):
        raise InvalidRevisionError(f"{name} is not a valid type/subtype media type")
    return normalized


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise InvalidRevisionError(f"{name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvalidRevisionError(f"{name} must be an integer") from exc
    if number < minimum or number != value:
        raise InvalidRevisionError(f"{name} must be an integer of at least {minimum}")
    return number


def _optional_integer(value: Any, name: str) -> int | None:
    return None if value is None else _integer(value, name)


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise InvalidRevisionError("numeric package fields cannot be booleans")
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvalidRevisionError("numeric package field is invalid") from exc


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidRevisionError(f"{name} must be a boolean")
    return value


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list):
        raise InvalidRevisionError(f"{name} must be a list")
    result = [_text(item, name) for item in value]
    if len(result) != len(set(result)):
        raise InvalidRevisionError(f"{name} cannot contain duplicates")
    return result


def _checksum(value: Any, name: str) -> str:
    checksum = _text(value, name).lower()
    if not _SHA256_PATTERN.fullmatch(checksum):
        raise InvalidRevisionError(f"{name} must contain a SHA-256 checksum")
    return checksum


def _optional_number_mapping(value: Any) -> dict[str, float] | None:
    if value is None:
        return None
    mapping = _mapping(value, "numeric mapping")
    return {str(key): float(item) for key, item in mapping.items()}


def _optional_number_list_mapping(value: Any) -> dict[str, list[float]] | None:
    if value is None:
        return None
    mapping = _mapping(value, "number-list mapping")
    result: dict[str, list[float]] = {}
    for key, items in mapping.items():
        if not isinstance(items, list):
            raise InvalidRevisionError("temperature mapping values must be lists")
        result[str(key)] = [float(item) for item in items]
    return result


def _optional_integer_mapping(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    mapping = _mapping(value, "integer mapping")
    return {str(key): _integer(item, "integer mapping value") for key, item in mapping.items()}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
