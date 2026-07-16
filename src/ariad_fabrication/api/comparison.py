"""Bounded, read-only comparison of normalized persisted revision records."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

from .models import (
    INTERFACE_API_VERSION,
    ComparisonArea,
    ComparisonAreaSummaryView,
    ComparisonChangeKind,
    ComparisonChangeView,
    ComparisonRelationship,
    ComparisonRevisionView,
    RevisionComparisonResponse,
    RevisionDetailResponse,
    read_only_capabilities,
)


MAX_COMPARISON_CHANGES = 1_000
MAX_COMPARISON_VALUE_BYTES = 64 * 1024
MAX_COMPARISON_RECORDS_PER_REVISION = 10_000
_AREA_ORDER: tuple[ComparisonArea, ...] = (
    "stage",
    "requirement",
    "feature",
    "report",
    "check",
    "finding",
    "profile",
    "artifact",
    "package",
)
_AREA_RANK = {area: index for index, area in enumerate(_AREA_ORDER)}
_SPEC_FIELDS = (
    "schema_version",
    "name",
    "part_type",
    "purpose",
    "material",
    "manufacturing_process",
    "units",
    "tolerance_mm",
    "bounding_box_mm",
    "infill_pct",
    "support_policy",
    "preferred_orientation",
    "printer_constraints",
    "datums",
    "environment",
    "mating_requirements",
    "load_cases",
    "surface_requirements",
    "assembly_method",
    "expected_lifetime_months",
    "safety_class",
    "assumptions",
    "unresolved_questions",
    "notes",
    "status",
    "source",
)
_DECISION_FIELDS = (
    "question",
    "choice",
    "rationale",
    "actor",
    "alternatives",
    "data",
)
_APPROVAL_FIELDS = (
    "boundary",
    "status",
    "requested_by",
    "rationale",
    "decided_by",
)
_CLAIM_BOUNDARY = (
    "This comparison diffs normalized values already persisted in two revisions. It does not "
    "rerun CAD, validation, slicing, simulation, or physical work; unchanged records do not "
    "prove geometric or physical equivalence. Record, change, and value limits are explicit, "
    "and complete is false whenever any limit prevents full detail."
)


@dataclass(frozen=True)
class _ComparisonRecord:
    area: ComparisonArea
    key: str
    label: str
    value: dict[str, Any]


@dataclass
class _RecordCollector:
    records: list[_ComparisonRecord] = field(default_factory=list)
    total_count: int = 0
    _key_counts: dict[tuple[ComparisonArea, str], int] = field(default_factory=dict)

    def append(
        self,
        *,
        area: ComparisonArea,
        key: str,
        label: str,
        value: dict[str, Any],
    ) -> None:
        self.total_count += 1
        if len(self.records) >= MAX_COMPARISON_RECORDS_PER_REVISION:
            return
        logical_key = (area, key)
        occurrence = self._key_counts.get(logical_key, 0) + 1
        self._key_counts[logical_key] = occurrence
        unique_key = key if occurrence == 1 else f"{key}#{occurrence}"
        self.records.append(
            _ComparisonRecord(area=area, key=unique_key, label=label, value=value)
        )

    @property
    def omitted_count(self) -> int:
        return self.total_count - len(self.records)


@dataclass(frozen=True)
class _ChangeDraft:
    area: ComparisonArea
    record_key: str
    label: str
    change: ComparisonChangeKind
    base_value: dict[str, Any] | None
    candidate_value: dict[str, Any] | None
    detail_complete: bool
    boundary: str | None


def compare_revision_details(
    base: RevisionDetailResponse,
    candidate: RevisionDetailResponse,
) -> RevisionComparisonResponse:
    """Compare only normalized persisted values exposed by the read contract."""

    base_collection = _comparison_records(base)
    candidate_collection = _comparison_records(candidate)
    base_records = {
        (item.area, item.key): item for item in base_collection.records
    }
    candidate_records = {
        (item.area, item.key): item for item in candidate_collection.records
    }
    keys = sorted(
        set(base_records) | set(candidate_records),
        key=lambda item: (_AREA_RANK[item[0]], item[1]),
    )
    drafts: list[_ChangeDraft] = []
    for area, key in keys:
        base_record = base_records.get((area, key))
        candidate_record = candidate_records.get((area, key))
        if base_record is not None and candidate_record is not None:
            if base_record.value == candidate_record.value:
                continue
            change: ComparisonChangeKind = "changed"
        elif base_record is None:
            change = "added"
        else:
            change = "removed"
        base_value, base_complete = _bounded_value(
            base_record.value if base_record is not None else None
        )
        candidate_value, candidate_complete = _bounded_value(
            candidate_record.value if candidate_record is not None else None
        )
        detail_complete = base_complete and candidate_complete
        display_record = candidate_record if candidate_record is not None else base_record
        if display_record is None:  # Defensive: every key comes from at least one record map.
            continue
        drafts.append(
            _ChangeDraft(
                area=area,
                record_key=key,
                label=display_record.label,
                change=change,
                base_value=base_value,
                candidate_value=candidate_value,
                detail_complete=detail_complete,
                boundary=(
                    None
                    if detail_complete
                    else "At least one normalized value exceeds or violates the detail limit."
                ),
            )
        )

    total = len(drafts)
    returned = drafts[:MAX_COMPARISON_CHANGES]
    omitted_changes = total - len(returned)
    incomplete_values = sum(not item.detail_complete for item in drafts)
    input_omissions = base_collection.omitted_count + candidate_collection.omitted_count
    return RevisionComparisonResponse(
        schema_version=INTERFACE_API_VERSION,
        capabilities=read_only_capabilities(),
        base=_revision_view(base, base_collection),
        candidate=_revision_view(candidate, candidate_collection),
        relationship=_relationship(base, candidate),
        complete=(
            omitted_changes == 0
            and incomplete_values == 0
            and input_omissions == 0
        ),
        total_change_count=total,
        returned_change_count=len(returned),
        omitted_change_count=omitted_changes,
        incomplete_value_count=incomplete_values,
        summaries=_summaries(drafts),
        changes=[
            ComparisonChangeView(
                area=item.area,
                record_key=item.record_key,
                label=item.label,
                change=item.change,
                base_value=item.base_value,
                candidate_value=item.candidate_value,
                detail_complete=item.detail_complete,
                boundary=item.boundary,
            )
            for item in returned
        ],
        max_changes=MAX_COMPARISON_CHANGES,
        max_value_bytes=MAX_COMPARISON_VALUE_BYTES,
        max_records_per_revision=MAX_COMPARISON_RECORDS_PER_REVISION,
        claim_boundary=_CLAIM_BOUNDARY,
    )


def _comparison_records(detail: RevisionDetailResponse) -> _RecordCollector:
    records = _RecordCollector()
    stage_names = {stage.stage_run_id: stage.stage for stage in detail.stages}

    for stage in detail.stages:
        records.append(
            area="stage",
            key=f"{stage.stage}:{stage.attempt}",
            label=stage.stage.replace("_", " "),
            value={
                "stage": stage.stage,
                "status": stage.status,
                "attempt": stage.attempt,
                "evidence_mode": stage.evidence_mode,
                "evidence_level": stage.evidence_level,
                "tool": stage.tool.model_dump(mode="json"),
                "summary": stage.summary,
                "error_message": stage.error_message,
                "events": [
                    {
                        "event_type": event.event_type,
                        "status": event.status,
                        "message": event.message,
                        "sequence": event.sequence,
                        "data": event.data,
                    }
                    for event in stage.events
                ],
                "decisions": _project_records(stage.decisions, _DECISION_FIELDS),
                "approvals": _project_records(stage.approvals, _APPROVAL_FIELDS),
            },
        )

    for field_name in _SPEC_FIELDS:
        if field_name in detail.revision.spec:
            records.append(
                area="requirement",
                key=field_name,
                label=field_name.replace("_", " "),
                value={"value": detail.revision.spec[field_name]},
            )

    for feature in detail.inspection.features:
        records.append(
            area="feature",
            key=feature.feature_id,
            label=feature.feature_id.replace("_", " "),
            value=feature.model_dump(mode="json", exclude={"source", "fixture"}),
        )

    for report in detail.inspection.reports:
        records.append(
            area="report",
            key=report.report_kind,
            label=report.title,
            value={
                "report_kind": report.report_kind,
                "schema_version": report.schema_version,
                "status": report.status,
                "passed": report.passed,
                "evidence_level": report.evidence_level,
                "claim_boundary": report.claim_boundary,
                "measurements": report.measurements,
                "messages": [item.model_dump(mode="json") for item in report.messages],
            },
        )
        for check in report.checks:
            records.append(
                area="check",
                key=f"{report.report_kind}:{check.check_id}",
                label=f"{report.title}: {check.check_id.replace('_', ' ')}",
                value={
                    "report_kind": report.report_kind,
                    **check.model_dump(mode="json"),
                },
            )

    for unavailable in detail.inspection.unavailable:
        records.append(
            area="report",
            key=f"unavailable:{unavailable.role}",
            label=f"Unavailable inspection source: {unavailable.role.replace('_', ' ')}",
            value={
                "role": unavailable.role,
                "checksum_sha256": unavailable.checksum_sha256,
                "reason": unavailable.reason,
                "message": unavailable.message,
            },
        )

    for stage in detail.stages:
        for finding in stage.findings:
            records.append(
                area="finding",
                key=f"{stage.stage}:{finding.code}",
                label=finding.title,
                value={
                    "stage": stage.stage,
                    "code": finding.code,
                    "title": finding.title,
                    "severity": finding.severity,
                    "evidence": finding.evidence,
                    "evidence_mode": finding.evidence_mode,
                    "remediation": finding.remediation,
                    "affected_geometry": finding.affected_geometry,
                    "resolved": finding.resolved,
                    "resolution": finding.resolution,
                    "data": finding.data,
                },
            )

    for profile in detail.inspection.profiles:
        records.append(
            area="profile",
            key=profile.profile_kind,
            label=f"{profile.profile_kind} profile",
            value={
                "profile_kind": profile.profile_kind,
                "profile_id": profile.profile_id,
                "name": profile.name,
                "status": profile.status,
                "claim_boundary": profile.claim_boundary,
                "values": profile.values,
            },
        )

    for stage in detail.stages:
        for artifact in stage.artifacts:
            records.append(
                area="artifact",
                key=artifact.role,
                label=artifact.role.replace("_", " "),
                value={
                    "role": artifact.role,
                    "stage": stage_names.get(artifact.stage_run_id),
                    "media_type": artifact.media_type,
                    "checksum_sha256": artifact.checksum_sha256,
                    "size_bytes": artifact.size_bytes,
                    "producer": artifact.producer,
                    "producer_version": artifact.producer_version,
                    "evidence_mode": artifact.evidence_mode,
                    "metadata": artifact.metadata,
                },
            )

    if detail.package is not None:
        records.append(
            area="package",
            key="fabrication_package",
            label="fabrication package",
            value=detail.package.model_dump(mode="json"),
        )
    return records


def _project_records(
    values: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    return [
        {field_name: value[field_name] for field_name in fields if field_name in value}
        for value in values
    ]


def _bounded_value(value: dict[str, Any] | None) -> tuple[dict[str, Any] | None, bool]:
    if value is None:
        return None, True
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        return (
            {"comparison_unavailable": "normalized record is not bounded JSON"},
            False,
        )
    if len(encoded) <= MAX_COMPARISON_VALUE_BYTES:
        return value, True
    return (
        {
            "comparison_unavailable": "normalized record exceeds the detail limit",
            "canonical_size_bytes": len(encoded),
            "canonical_sha256": hashlib.sha256(encoded).hexdigest(),
        },
        False,
    )


def _summaries(drafts: list[_ChangeDraft]) -> list[ComparisonAreaSummaryView]:
    counts = {
        area: {"added": 0, "removed": 0, "changed": 0}
        for area in _AREA_ORDER
    }
    for item in drafts:
        counts[item.area][item.change] += 1
    return [
        ComparisonAreaSummaryView(
            area=area,
            added=counts[area]["added"],
            removed=counts[area]["removed"],
            changed=counts[area]["changed"],
        )
        for area in _AREA_ORDER
        if sum(counts[area].values()) > 0
    ]


def _revision_view(
    detail: RevisionDetailResponse,
    records: _RecordCollector,
) -> ComparisonRevisionView:
    achieved = next(
        (
            stage.evidence_level
            for stage in reversed(detail.stages)
            if stage.evidence_level is not None
        ),
        None,
    )
    return ComparisonRevisionView(
        job_id=detail.job.job_id,
        revision_id=detail.revision.revision_id,
        revision_number=detail.revision.number,
        parent_revision_id=detail.revision.parent_revision_id,
        title=detail.job.title,
        job_status=detail.job.status,
        source_kind=detail.source.kind,
        source_label=detail.source.label,
        fixture=detail.source.fixture,
        physical_evidence_present=detail.source.physical_evidence_present,
        achieved_evidence_level=achieved,
        package_status=detail.package.status if detail.package is not None else None,
        package_evidence_level=(
            detail.package.evidence_level if detail.package is not None else None
        ),
        allowed_claim=detail.package.allowed_claim if detail.package is not None else None,
        normalized_record_count=records.total_count,
        compared_record_count=len(records.records),
        omitted_record_count=records.omitted_count,
    )


def _relationship(
    base: RevisionDetailResponse,
    candidate: RevisionDetailResponse,
) -> ComparisonRelationship:
    if (
        base.job.job_id == candidate.job.job_id
        and base.revision.revision_id == candidate.revision.revision_id
    ):
        return "same_revision"
    if base.job.job_id != candidate.job.job_id:
        return "unrelated"
    if candidate.revision.parent_revision_id == base.revision.revision_id:
        return "parent_to_child"
    if base.revision.parent_revision_id == candidate.revision.revision_id:
        return "child_to_parent"
    return "same_job"
