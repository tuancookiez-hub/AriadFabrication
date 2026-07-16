"""Fail-closed reader for persisted Fabrication Journey revisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Literal, Mapping, TypeVar
from urllib.parse import quote

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
from .bounded_io import (
    BoundedFileMissingError,
    BoundedFileSizeMismatchError,
    BoundedFileTooLargeError,
    BoundedFileUnreadableError,
    read_bounded_bytes,
)
from .comparison import compare_revision_details
from .models import (
    INTERFACE_API_VERSION,
    ApprovalView,
    ArtifactView,
    DecisionView,
    EventView,
    FindingView,
    GcodeSummaryView,
    HardwareView,
    InspectionArtifactView,
    InspectionCheckView,
    InspectionFeatureView,
    InspectionMessageView,
    InspectionProfileStatus,
    InspectionProfileView,
    InspectionReportStatus,
    InspectionReportView,
    InspectionUnavailableView,
    InspectionView,
    JobView,
    PackageView,
    PackageStatus,
    RevisionDetailResponse,
    RevisionComparisonResponse,
    RevisionListResponse,
    RevisionListTruncationReason,
    RevisionListWindowView,
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
_MAX_JSON_BYTES = 32 * 1024 * 1024
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 200_000
MAX_ARTIFACT_DOWNLOAD_BYTES = 64 * 1024 * 1024
DEFAULT_REVISION_LIST_LIMIT = 100
MAX_REVISION_LIST_LIMIT = 200
MAX_REVISION_LIST_OFFSET = 500
MAX_REVISION_DISCOVERY_ENTRIES = 5_000
MAX_REVISION_CANDIDATES = 500
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
_REPORT_EVIDENCE_LEVELS = {
    "geometry": EvidenceLevel.R2,
    "printability": EvidenceLevel.R3,
    "gcode_preflight": EvidenceLevel.R4,
}
_INSPECTION_CLAIM_BOUNDARY = (
    "Inspection values are replayed from checksum-verified persisted reports and profiles. "
    "Selection does not rerun validation, inspect exact STEP geometry, or provide physical proof."
)
_LISTING_CLAIM_BOUNDARY = (
    "This window contains only revision directories observed within the stated discovery and "
    "page limits. Each request re-examines the live local directory, so offset pages are not a "
    "snapshot and may shift if files change. An incomplete discovery is not evidence that "
    "omitted revisions do not exist."
)
_TRUNCATION_ORDER: tuple[RevisionListTruncationReason, ...] = (
    "directory_entry_limit",
    "candidate_limit",
    "window_limit",
    "filesystem_error",
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


@dataclass(frozen=True)
class _RevisionDiscovery:
    roots: tuple[Path, ...]
    directory_entries_examined: int
    complete: bool
    reasons: tuple[RevisionListTruncationReason, ...]
    error: str | None


class _InspectionShapeError(ValueError):
    pass


class JourneyRepository:
    """Read one immutable revision tree without offering mutation or hardware actions."""

    def __init__(self, runs_root: Path | str) -> None:
        self.runs_root = Path(runs_root).expanduser().resolve()

    def list_revisions(
        self,
        *,
        offset: int = 0,
        limit: int = DEFAULT_REVISION_LIST_LIMIT,
    ) -> RevisionListResponse:
        offset = _integer(offset, "revision list offset")
        limit = _integer(limit, "revision list limit", minimum=1)
        if offset > MAX_REVISION_LIST_OFFSET:
            raise ValueError(
                f"revision list offset cannot exceed {MAX_REVISION_LIST_OFFSET}"
            )
        if limit > MAX_REVISION_LIST_LIMIT:
            raise ValueError(
                f"revision list limit cannot exceed {MAX_REVISION_LIST_LIMIT}"
            )
        discovery = self._discover_revision_roots()
        candidates = sorted(
            discovery.roots,
            key=lambda item: (item.parent.parent.name, item.name),
        )
        selected = candidates[offset : offset + limit]
        items: list[RevisionSummary] = []
        for revision_root in selected:
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
        reasons = set(discovery.reasons)
        if len(selected) < len(candidates):
            reasons.add("window_limit")
        next_offset = (
            offset + len(selected)
            if offset + len(selected) < len(candidates)
            else None
        )
        return RevisionListResponse(
            schema_version=INTERFACE_API_VERSION,
            capabilities=read_only_capabilities(),
            revisions=items,
            window=RevisionListWindowView(
                discovery_complete=discovery.complete,
                snapshot_consistent=False,
                ordering="job_id_revision_id_ascending",
                directory_entries_examined=discovery.directory_entries_examined,
                observed_candidate_count=len(candidates),
                offset=offset,
                limit=limit,
                returned_count=len(items),
                observed_omitted_count=len(candidates) - len(selected),
                next_offset=next_offset,
                truncation_reasons=[
                    reason for reason in _TRUNCATION_ORDER if reason in reasons
                ],
                max_directory_entries=MAX_REVISION_DISCOVERY_ENTRIES,
                max_candidates=MAX_REVISION_CANDIDATES,
                error=discovery.error,
                claim_boundary=_LISTING_CLAIM_BOUNDARY,
            ),
        )

    def _discover_revision_roots(self) -> _RevisionDiscovery:
        roots: list[Path] = []
        entries_examined = 0
        reasons: set[RevisionListTruncationReason] = set()
        filesystem_error = False
        stop = False

        try:
            job_entries = os.scandir(self.runs_root)
        except FileNotFoundError:
            return _RevisionDiscovery((), 0, True, (), None)
        except NotADirectoryError:
            return _RevisionDiscovery(
                (),
                0,
                False,
                ("filesystem_error",),
                "The configured runs root is not a directory.",
            )
        except OSError:
            return _RevisionDiscovery(
                (),
                0,
                False,
                ("filesystem_error",),
                "The configured runs root could not be examined.",
            )

        with job_entries:
            for job_entry in job_entries:
                if entries_examined >= MAX_REVISION_DISCOVERY_ENTRIES:
                    reasons.add("directory_entry_limit")
                    break
                entries_examined += 1
                try:
                    if not job_entry.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    filesystem_error = True
                    continue
                revisions_path = Path(job_entry.path) / "revisions"
                if revisions_path.is_symlink():
                    continue
                try:
                    revision_entries = os.scandir(revisions_path)
                except (FileNotFoundError, NotADirectoryError):
                    continue
                except OSError:
                    filesystem_error = True
                    continue
                with revision_entries:
                    for revision_entry in revision_entries:
                        if entries_examined >= MAX_REVISION_DISCOVERY_ENTRIES:
                            reasons.add("directory_entry_limit")
                            stop = True
                            break
                        entries_examined += 1
                        try:
                            if not revision_entry.is_dir(follow_symlinks=False):
                                continue
                        except OSError:
                            filesystem_error = True
                            continue
                        if len(roots) >= MAX_REVISION_CANDIDATES:
                            reasons.add("candidate_limit")
                            stop = True
                            break
                        roots.append(Path(revision_entry.path))
                if stop:
                    break

        if filesystem_error:
            reasons.add("filesystem_error")
        ordered_reasons = tuple(
            reason for reason in _TRUNCATION_ORDER if reason in reasons
        )
        return _RevisionDiscovery(
            roots=tuple(roots),
            directory_entries_examined=entries_examined,
            complete=not reasons,
            reasons=ordered_reasons,
            error=(
                "At least one directory entry could not be examined."
                if filesystem_error
                else None
            ),
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
                status=_enum_value(job.get("status"), JobStatus, "journey.job.status"),
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
            package=self._package_view(
                loaded.package,
                fixture=loaded.fixture is not None,
            ),
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
        try:
            content = read_bounded_bytes(
                path,
                max_bytes=MAX_ARTIFACT_DOWNLOAD_BYTES,
                expected_size=recorded_size,
            )
        except BoundedFileMissingError as exc:
            raise ArtifactNotFoundError("recorded artifact file is unavailable") from exc
        except BoundedFileTooLargeError as exc:
            raise ArtifactTooLargeError(
                f"artifact exceeds the {MAX_ARTIFACT_DOWNLOAD_BYTES}-byte "
                "verified-download limit"
            ) from exc
        except BoundedFileSizeMismatchError as exc:
            raise ArtifactIntegrityError(
                "recorded artifact size does not match the file"
            ) from exc
        except BoundedFileUnreadableError as exc:
            raise ArtifactIntegrityError("recorded artifact file could not be read") from exc
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
        _enum_value(job.get("status"), JobStatus, "journey.job.status")
        revisions = _indexed(journey.get("revisions"), "revision_id", "journey.revisions")
        revision = revisions.get(revision_id)
        if revision is None:
            raise InvalidRevisionError("journey does not contain the requested revision")
        if revision.get("job_id") != job_id:
            raise InvalidRevisionError("revision ownership does not match the job")
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
        all_decisions = _indexed(
            journey.get("decisions"), "decision_id", "journey.decisions"
        )
        decisions = {
            record_id: record
            for record_id, record in all_decisions.items()
            if record.get("revision_id") == revision_id
        }
        all_approvals = _indexed(
            journey.get("approvals"), "approval_id", "journey.approvals"
        )
        approvals = {
            record_id: record
            for record_id, record in all_approvals.items()
            if record.get("revision_id") == revision_id
        }
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
            manifest_decisions = _indexed(
                manifest.get("decisions"), "decision_id", "manifest.decisions"
            )
            if manifest_decisions != decisions:
                raise InvalidRevisionError("journey and manifest decision records differ")
            manifest_approvals = _indexed(
                manifest.get("approvals"), "approval_id", "manifest.approvals"
            )
            if manifest_approvals != approvals:
                raise InvalidRevisionError("journey and manifest approval records differ")
            artifacts = manifest_artifacts
        if package is not None:
            if package.get("job_id") != job_id or package.get("revision_id") != revision_id:
                raise InvalidRevisionError("fabrication package ownership does not match the revision")
        if fixture is not None:
            if fixture.get("classification") != "interface_fixture":
                raise InvalidRevisionError("fixture marker has an unsupported classification")
            if fixture.get("evidence_mode") != EvidenceMode.FIXTURE.value:
                raise InvalidRevisionError("interface fixtures must use fixture evidence mode")
            if fixture.get("physical_validation") is not False:
                raise InvalidRevisionError("interface fixtures must explicitly deny physical validation")
        self._validate_revision_state(
            job_id=job_id,
            revision_id=revision_id,
            stage_ids=stage_ids,
            stage_runs=stage_runs,
            events=events,
            artifacts=artifacts,
            findings=findings,
            decisions=decisions,
            approvals=approvals,
            package=package,
            fixture=fixture is not None,
        )
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

    def _validate_revision_state(
        self,
        *,
        job_id: str,
        revision_id: str,
        stage_ids: list[str],
        stage_runs: dict[str, dict[str, Any]],
        events: dict[str, dict[str, Any]],
        artifacts: dict[str, dict[str, Any]],
        findings: dict[str, dict[str, Any]],
        decisions: dict[str, dict[str, Any]],
        approvals: dict[str, dict[str, Any]],
        package: dict[str, Any] | None,
        fixture: bool,
    ) -> None:
        for artifact in artifacts.values():
            _validate_record_ownership(artifact, job_id, revision_id, "artifact")
            mode = _evidence_mode(
                artifact.get("evidence_mode"), "artifact.evidence_mode"
            )
            if fixture and mode is not EvidenceMode.FIXTURE:
                raise InvalidRevisionError(
                    "interface fixture artifacts must remain fixture evidence"
                )

        for finding in findings.values():
            _validate_record_ownership(finding, job_id, revision_id, "finding")
            _enum_value(
                finding.get("severity"), FindingSeverity, "finding.severity"
            )
            mode = _evidence_mode(
                finding.get("evidence_mode"), "finding.evidence_mode"
            )
            if fixture and mode is not EvidenceMode.FIXTURE:
                raise InvalidRevisionError(
                    "interface fixture findings must remain fixture evidence"
                )
            resolved = _boolean(finding.get("resolved"), "finding.resolved")
            if resolved and _optional_text(finding.get("resolution")) is None:
                raise InvalidRevisionError(
                    "resolved findings require a recorded resolution"
                )

        if package is not None:
            expected_schema = "1.0.0-interface-fixture" if fixture else "1.0.0"
            expected_classification = (
                "interface_fixture_package"
                if fixture
                else "printer_independent_fabrication_package"
            )
            if package.get("schema_version") != expected_schema:
                raise InvalidRevisionError("package schema does not match its evidence class")
            if package.get("classification") != expected_classification:
                raise InvalidRevisionError(
                    "package classification does not match its evidence class"
                )
            self._package_view(package, fixture=fixture)

        for stage_id in stage_ids:
            stage = stage_runs[stage_id]
            stage_kind = _enum_value(
                stage.get("stage"), FabricationStage, "stage.stage"
            )
            status = _enum_value(stage.get("status"), StageStatus, "stage.status")
            mode = _evidence_mode(stage.get("evidence_mode"), "stage.evidence_mode")
            evidence_level = _optional_enum_value(
                stage.get("evidence_level"), EvidenceLevel, "stage.evidence_level"
            )
            _integer(stage.get("attempt"), "stage.attempt", minimum=1)
            started_at = _optional_text(stage.get("started_at"))
            completed_at = _optional_text(stage.get("completed_at"))
            error_message = _optional_text(stage.get("error_message"))
            if status is StageStatus.WAITING and (
                started_at is not None or completed_at is not None
            ):
                raise InvalidRevisionError(
                    "waiting stage runs cannot contain execution timestamps"
                )
            if status in {StageStatus.RUNNING, StageStatus.NEEDS_INPUT} and (
                started_at is None or completed_at is not None
            ):
                raise InvalidRevisionError(
                    f"{status.value} stage runs require only a start timestamp"
                )
            if status in {
                StageStatus.PASSED,
                StageStatus.PASSED_WITH_WARNINGS,
                StageStatus.FAILED,
            } and (started_at is None or completed_at is None):
                raise InvalidRevisionError(
                    f"{status.value} stage runs require start and completion timestamps"
                )
            if status is StageStatus.FAILED and error_message is None:
                raise InvalidRevisionError("failed stage runs require an error message")
            if status in {StageStatus.PASSED, StageStatus.PASSED_WITH_WARNINGS}:
                if evidence_level is None:
                    raise InvalidRevisionError(
                        "passed stage runs require a recorded evidence level"
                    )
                if mode is EvidenceMode.UNAVAILABLE:
                    raise InvalidRevisionError(
                        "unavailable evidence cannot produce a passed stage run"
                    )
            if fixture and mode is not EvidenceMode.FIXTURE:
                raise InvalidRevisionError(
                    "interface fixture stages must remain fixture evidence"
                )

            event_records = self._records(
                events,
                stage.get("event_ids"),
                "stage.event_ids",
                expected_stage_id=stage_id,
                expected_job_id=job_id,
                expected_revision_id=revision_id,
                allow_unscoped_revision=True,
            )
            sequences: list[int] = []
            for event in event_records:
                event_stage = _enum_value(
                    event.get("stage"), FabricationStage, "event.stage"
                )
                if event_stage is not stage_kind:
                    raise InvalidRevisionError(
                        "event stage does not match its owning stage run"
                    )
                _enum_value(event.get("status"), StageStatus, "event.status")
                sequences.append(
                    _integer(event.get("sequence"), "event.sequence", minimum=1)
                )
            if len(sequences) != len(set(sequences)):
                raise InvalidRevisionError(
                    "stage events cannot contain duplicate sequence numbers"
                )

            self._records(
                artifacts,
                stage.get("input_artifact_ids"),
                "stage.input_artifact_ids",
                expected_job_id=job_id,
                expected_revision_id=revision_id,
            )
            self._records(
                artifacts,
                stage.get("artifact_ids"),
                "stage.artifact_ids",
                expected_stage_id=stage_id,
                expected_job_id=job_id,
                expected_revision_id=revision_id,
            )
            self._records(
                findings,
                stage.get("finding_ids"),
                "stage.finding_ids",
                expected_stage_id=stage_id,
                expected_job_id=job_id,
                expected_revision_id=revision_id,
            )
            decision_records = self._records(
                decisions,
                stage.get("decision_ids"),
                "stage.decision_ids",
                expected_stage_id=stage_id,
                expected_job_id=job_id,
                expected_revision_id=revision_id,
            )
            for decision in decision_records:
                _enum_value(
                    decision.get("actor"), DecisionActor, "decision.actor"
                )
                _text_list(decision.get("alternatives"), "decision.alternatives")

            approval_records = self._records(
                approvals,
                stage.get("approval_ids"),
                "stage.approval_ids",
                expected_stage_id=stage_id,
                expected_job_id=job_id,
                expected_revision_id=revision_id,
            )
            for approval in approval_records:
                approval_status = _enum_value(
                    approval.get("status"), ApprovalStatus, "approval.status"
                )
                _enum_value(
                    approval.get("requested_by"),
                    DecisionActor,
                    "approval.requested_by",
                )
                decided_at = _optional_text(approval.get("decided_at"))
                decided_by = _optional_enum_value(
                    approval.get("decided_by"),
                    DecisionActor,
                    "approval.decided_by",
                )
                if approval_status is ApprovalStatus.REQUESTED:
                    if decided_at is not None or decided_by is not None:
                        raise InvalidRevisionError(
                            "requested approvals cannot contain a decision"
                        )
                elif decided_at is None or decided_by is None:
                    raise InvalidRevisionError(
                        "decided approvals require decision time and actor"
                    )

    def _stage_view(self, loaded: _LoadedRevision, stage_id: str) -> StageView:
        stage = loaded.stage_runs[stage_id]
        stage_kind = _enum_value(stage.get("stage"), FabricationStage, "stage.stage")
        events = [
            EventView(
                event_id=_text(item.get("event_id"), "event.event_id"),
                stage=_enum_value(item.get("stage"), FabricationStage, "event.stage"),
                event_type=_text(item.get("event_type"), "event.event_type"),
                status=_enum_value(item.get("status"), StageStatus, "event.status"),
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
                severity=_enum_value(
                    item.get("severity"), FindingSeverity, "finding.severity"
                ),
                evidence=_text(item.get("evidence"), "finding.evidence"),
                evidence_mode=_evidence_mode(
                    item.get("evidence_mode"), "finding.evidence_mode"
                ),
                remediation=_optional_text(item.get("remediation")),
                affected_geometry=_optional_text(item.get("affected_geometry")),
                resolved=_boolean(item.get("resolved", False), "finding.resolved"),
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
        decisions = [
            DecisionView(
                decision_id=_text(item.get("decision_id"), "decision.decision_id"),
                job_id=_text(item.get("job_id"), "decision.job_id"),
                revision_id=_text(item.get("revision_id"), "decision.revision_id"),
                stage_run_id=_optional_text(item.get("stage_run_id")),
                question=_text(item.get("question"), "decision.question"),
                choice=_text(item.get("choice"), "decision.choice"),
                rationale=_text(item.get("rationale"), "decision.rationale"),
                actor=_enum_value(item.get("actor"), DecisionActor, "decision.actor"),
                alternatives=_text_list(
                    item.get("alternatives"), "decision.alternatives"
                ),
                created_at=_text(item.get("created_at"), "decision.created_at"),
                data=_mapping(item.get("data", {}), "decision.data"),
            )
            for item in self._records(
                loaded.decisions,
                stage.get("decision_ids"),
                "stage.decision_ids",
                expected_stage_id=stage_id,
            )
        ]
        approvals = [
            ApprovalView(
                approval_id=_text(item.get("approval_id"), "approval.approval_id"),
                job_id=_text(item.get("job_id"), "approval.job_id"),
                revision_id=_text(item.get("revision_id"), "approval.revision_id"),
                stage_run_id=_optional_text(item.get("stage_run_id")),
                boundary=_text(item.get("boundary"), "approval.boundary"),
                status=_enum_value(
                    item.get("status"), ApprovalStatus, "approval.status"
                ),
                requested_by=_enum_value(
                    item.get("requested_by"), DecisionActor, "approval.requested_by"
                ),
                rationale=str(item.get("rationale", "")).strip(),
                requested_at=_text(item.get("requested_at"), "approval.requested_at"),
                decided_at=_optional_text(item.get("decided_at")),
                decided_by=_optional_enum_value(
                    item.get("decided_by"), DecisionActor, "approval.decided_by"
                ),
            )
            for item in self._records(
                loaded.approvals,
                stage.get("approval_ids"),
                "stage.approval_ids",
                expected_stage_id=stage_id,
            )
        ]
        tool = _mapping(stage.get("tool"), "stage.tool")
        return StageView(
            stage_run_id=stage_id,
            stage=stage_kind,
            status=_enum_value(stage.get("status"), StageStatus, "stage.status"),
            attempt=_integer(stage.get("attempt"), "stage.attempt", minimum=1),
            evidence_mode=_evidence_mode(
                stage.get("evidence_mode"), "stage.evidence_mode"
            ),
            evidence_level=_optional_enum_value(
                stage.get("evidence_level"), EvidenceLevel, "stage.evidence_level"
            ),
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

    def _package_view(
        self,
        package: dict[str, Any] | None,
        *,
        fixture: bool,
    ) -> PackageView | None:
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
        evidence_level = _optional_enum_value(
            package.get("evidence_level"), EvidenceLevel, "package.evidence_level"
        )
        if evidence_level is not None and evidence_level is not EvidenceLevel.R4:
            raise InvalidRevisionError("package.evidence_level must be R4 or null")
        if fixture != (evidence_level is None):
            raise InvalidRevisionError(
                "fixture packages require null evidence; runtime packages require R4"
            )
        package_status = _enum_value(
            package.get("status"), PackageStatus, "package.status"
        )
        if fixture != (package_status is PackageStatus.FIXTURE):
            raise InvalidRevisionError(
                "fixture and runtime package status classifications cannot be mixed"
            )
        return PackageView(
            status=package_status,
            evidence_level=evidence_level,
            allowed_claim=_text(package.get("allowed_claim"), "package.allowed_claim"),
            claim_boundary=_text(
                package.get("claim_boundary"), "package.claim_boundary"
            ),
            hardware=HardwareView(
                printer_selected=_false_boolean(
                    hardware.get("printer_selected"), "hardware.printer_selected"
                ),
                printer_connected=_false_boolean(
                    hardware.get("printer_connected"), "hardware.printer_connected"
                ),
                gcode_uploaded=_false_boolean(
                    hardware.get("gcode_uploaded"), "hardware.gcode_uploaded"
                ),
                print_started=_false_boolean(
                    hardware.get("print_started"), "hardware.print_started"
                ),
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
        expected_size = record.get("size_bytes")
        recorded_size = (
            _integer(expected_size, "artifact.size_bytes")
            if expected_size is not None
            else None
        )
        try:
            payload = read_bounded_bytes(
                path,
                max_bytes=_MAX_INSPECTION_JSON_BYTES,
                expected_size=recorded_size,
            )
        except BoundedFileMissingError:
            return None, None, _inspection_unavailable_for_record(
                role,
                artifact_id,
                checksum,
                "file_missing",
                "The recorded report file is missing.",
            )
        except BoundedFileTooLargeError:
            return None, None, _inspection_unavailable_for_record(
                role,
                artifact_id,
                checksum,
                "size_limit",
                "The recorded report exceeds the bounded inspection size limit.",
            )
        except BoundedFileSizeMismatchError:
            return None, None, _inspection_unavailable_for_record(
                role,
                artifact_id,
                checksum,
                "size_mismatch",
                "The recorded report size does not match the persisted artifact record.",
            )
        except BoundedFileUnreadableError:
            return None, None, _inspection_unavailable_for_record(
                role,
                artifact_id,
                checksum,
                "file_missing",
                "The recorded report cannot be read.",
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
                parse_constant=_reject_json_constant,
                object_pairs_hook=_reject_duplicate_json_object,
            )
        except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError):
            return None, None, _inspection_unavailable_for_record(
                role,
                artifact_id,
                checksum,
                "invalid_json",
                "The checksum-verified report is not bounded UTF-8 JSON.",
            )
        if not isinstance(value, dict) or not _json_is_bounded(
            value,
            max_nodes=_MAX_INSPECTION_NODES,
            max_depth=_MAX_INSPECTION_DEPTH,
        ):
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
            size_bytes=len(payload),
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
        expected_job_id: str | None = None,
        expected_revision_id: str | None = None,
        allow_unscoped_revision: bool = False,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for record_id in _string_list(ids, name):
            record = index.get(record_id)
            if record is None:
                raise InvalidRevisionError(f"{name} references missing record {record_id!r}")
            if expected_stage_id is not None and record.get("stage_run_id") != expected_stage_id:
                raise InvalidRevisionError(f"{name} references a record owned by another stage")
            if expected_job_id is not None and record.get("job_id") != expected_job_id:
                raise InvalidRevisionError(f"{name} references a record owned by another job")
            if expected_revision_id is not None:
                record_revision_id = record.get("revision_id")
                if record_revision_id != expected_revision_id and not (
                    allow_unscoped_revision and record_revision_id is None
                ):
                    raise InvalidRevisionError(
                        f"{name} references a record owned by another revision"
                    )
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
    status = _inspection_optional_enum_value(
        value.get("status"), InspectionReportStatus, "inspection report status"
    )
    evidence_level = _inspection_optional_enum_value(
        value.get("evidence_level"), EvidenceLevel, "inspection report evidence level"
    )
    expected_level = _REPORT_EVIDENCE_LEVELS[report_kind]
    if evidence_level is not None and evidence_level is not expected_level:
        raise _InspectionShapeError(
            f"{report_kind} reports may record only {expected_level.value} evidence"
        )
    if raw_passed is False and evidence_level is not None:
        raise _InspectionShapeError("failed inspection reports cannot record evidence")
    if raw_passed is True and status is InspectionReportStatus.FAILED:
        raise _InspectionShapeError("a passing inspection report cannot have failed status")
    if raw_passed is False and status in {
        InspectionReportStatus.PASSED,
        InspectionReportStatus.PASSED_WITH_WARNINGS,
    }:
        raise _InspectionShapeError("a failed inspection report cannot have passing status")
    if raw_passed is True and any(not check.passed for check in checks):
        raise _InspectionShapeError("a passing inspection report contains a failed check")
    messages = [
        *_inspection_messages(value.get("warnings", []), severity="warning"),
        *_inspection_messages(value.get("errors", []), severity="error"),
    ]
    return InspectionReportView(
        report_kind=report_kind,
        title=title,
        artifact=artifact,
        schema_version=_inspection_optional_text(value.get("schema_version")),
        status=status,
        passed=raw_passed,
        evidence_level=evidence_level,
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
    status = _inspection_enum_value(
        value.get("status"), InspectionProfileStatus, "inspection profile status"
    )
    fixture_status = status in {
        InspectionProfileStatus.INTERFACE_FIXTURE,
        InspectionProfileStatus.INTERFACE_FIXTURE_UNCALIBRATED,
    }
    if (artifact.evidence_mode is EvidenceMode.FIXTURE) != fixture_status:
        raise _InspectionShapeError(
            "inspection profile status does not match its evidence mode"
        )
    return InspectionProfileView(
        profile_kind=profile_kind,
        artifact=artifact,
        profile_id=_inspection_text(value.get("profile_id") or value.get("orientation_id")),
        name=_inspection_text(value.get("name")),
        status=status,
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


def _inspection_enum_value(
    value: Any,
    enum_type: type[EnumValue],
    name: str,
) -> EnumValue:
    normalized = _inspection_text(value)
    try:
        return enum_type(normalized)
    except ValueError as exc:
        raise _InspectionShapeError(
            f"{name} has unsupported value {normalized!r}"
        ) from exc


def _inspection_optional_enum_value(
    value: Any,
    enum_type: type[EnumValue],
    name: str,
) -> EnumValue | None:
    return None if value is None else _inspection_enum_value(value, enum_type, name)


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


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _reject_duplicate_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key is not allowed: {key!r}")
        value[key] = item
    return value


def _json_is_bounded(value: Any, *, max_nodes: int, max_depth: int) -> bool:
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
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
    try:
        payload = read_bounded_bytes(resolved, max_bytes=_MAX_JSON_BYTES)
    except BoundedFileMissingError:
        if required:
            raise InvalidRevisionError(f"required persisted record {path.name!r} is missing")
        return None
    except BoundedFileTooLargeError as exc:
        raise InvalidRevisionError(
            f"persisted record {path.name!r} exceeds the size limit"
        ) from exc
    except BoundedFileUnreadableError as exc:
        raise InvalidRevisionError(f"persisted record {path.name!r} cannot be read") from exc
    except BoundedFileSizeMismatchError as exc:  # No expected size is supplied here.
        raise InvalidRevisionError(f"persisted record {path.name!r} changed size") from exc
    try:
        value = json.loads(
            payload.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_json_object,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise InvalidRevisionError(
            f"persisted record {path.name!r} is not bounded UTF-8 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise InvalidRevisionError(f"persisted record {path.name!r} must contain an object")
    if not _json_is_bounded(
        value,
        max_nodes=_MAX_JSON_NODES,
        max_depth=_MAX_JSON_DEPTH,
    ):
        raise InvalidRevisionError(
            f"persisted record {path.name!r} exceeds the JSON complexity limit"
        )
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


def _validate_record_ownership(
    record: Mapping[str, Any],
    job_id: str,
    revision_id: str,
    name: str,
) -> None:
    if record.get("job_id") != job_id or record.get("revision_id") != revision_id:
        raise InvalidRevisionError(f"{name} ownership does not match the revision")


def _text(value: Any, name: str) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise InvalidRevisionError(f"{name} is required")
    return normalized


EnumValue = TypeVar("EnumValue", bound=Enum)


def _enum_value(value: Any, enum_type: type[EnumValue], name: str) -> EnumValue:
    normalized = _text(value, name)
    try:
        return enum_type(normalized)
    except ValueError as exc:
        raise InvalidRevisionError(
            f"{name} has unsupported value {normalized!r}"
        ) from exc


def _optional_enum_value(
    value: Any,
    enum_type: type[EnumValue],
    name: str,
) -> EnumValue | None:
    return None if value is None else _enum_value(value, enum_type, name)


def _evidence_mode(value: Any, name: str) -> EvidenceMode:
    return _enum_value(value, EvidenceMode, name)


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
    return None if value is None else _number(value, "numeric package field")


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidRevisionError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise InvalidRevisionError(f"{name} must be finite")
    return result


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidRevisionError(f"{name} must be a boolean")
    return value


def _false_boolean(value: Any, name: str) -> Literal[False]:
    if _boolean(value, name):
        raise InvalidRevisionError(f"{name} must remain false in the read-only package")
    return False


def _text_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list):
        raise InvalidRevisionError(f"{name} must be a list")
    return [_text(item, name) for item in value]


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
    return {
        str(key): _number(item, "numeric mapping value")
        for key, item in mapping.items()
    }


def _optional_number_list_mapping(value: Any) -> dict[str, list[float]] | None:
    if value is None:
        return None
    mapping = _mapping(value, "number-list mapping")
    result: dict[str, list[float]] = {}
    for key, items in mapping.items():
        if not isinstance(items, list):
            raise InvalidRevisionError("temperature mapping values must be lists")
        result[str(key)] = [
            _number(item, "temperature mapping value") for item in items
        ]
    return result


def _optional_integer_mapping(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    mapping = _mapping(value, "integer mapping")
    return {str(key): _integer(item, "integer mapping value") for key, item in mapping.items()}
