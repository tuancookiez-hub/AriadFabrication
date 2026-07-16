"""Fail-closed reader for persisted Fabrication Journey revisions."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping
from urllib.parse import quote

from .models import (
    INTERFACE_API_VERSION,
    ArtifactView,
    EventView,
    FindingView,
    GcodeSummaryView,
    HardwareView,
    JobView,
    PackageView,
    RevisionDetailResponse,
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
_MAX_JSON_BYTES = 32 * 1024 * 1024
_PHYSICAL_LEVELS = {"R6", "R7"}


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


@dataclass(frozen=True)
class ArtifactFile:
    path: Path
    filename: str
    media_type: str
    checksum_sha256: str
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
                detail = self.get_revision(job_id, revision_id)
            except JourneyReadError as exc:
                items.append(
                    RevisionSummary(
                        job_id=job_id,
                        revision_id=revision_id,
                        availability="invalid",
                        title=None,
                        job_status=None,
                        revision_number=None,
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
        )

    def get_artifact(self, job_id: str, revision_id: str, artifact_id: str) -> ArtifactFile:
        loaded = self._load(job_id, revision_id)
        artifact = loaded.artifacts.get(artifact_id)
        if artifact is None:
            raise ArtifactNotFoundError("artifact is not recorded in this revision")
        path = self._artifact_path(loaded.root, artifact)
        if not path.is_file():
            raise ArtifactNotFoundError("recorded artifact file is unavailable")
        expected_size = artifact.get("size_bytes")
        if expected_size is not None and path.stat().st_size != _integer(
            expected_size, "artifact.size_bytes"
        ):
            raise ArtifactIntegrityError("recorded artifact size does not match the file")
        expected_hash = _checksum(artifact.get("checksum_sha256"), "artifact.checksum_sha256")
        actual_hash = _file_sha256(path)
        if actual_hash != expected_hash:
            raise ArtifactIntegrityError("recorded artifact checksum does not match the file")
        return ArtifactFile(
            path=path,
            filename=path.name,
            media_type=_text(artifact.get("media_type"), "artifact.media_type"),
            checksum_sha256=expected_hash,
            evidence_mode=_text(artifact.get("evidence_mode"), "artifact.evidence_mode"),
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
                evidence_mode=_text(item.get("evidence_mode"), "finding.evidence_mode"),
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
            evidence_mode=_text(stage.get("evidence_mode"), "stage.evidence_mode"),
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
            media_type=_text(artifact.get("media_type"), "artifact.media_type"),
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
            evidence_mode=_text(artifact.get("evidence_mode"), "artifact.evidence_mode"),
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
