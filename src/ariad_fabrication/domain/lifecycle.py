"""Pure transition rules for fabrication stage runs."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from .journey import EvidenceLevel, FabricationStage, StageRun, StageStatus


FABRICATION_STAGES = (
    FabricationStage.BRIEF,
    FabricationStage.DESIGN,
    FabricationStage.GEOMETRY_VALIDATION,
    FabricationStage.PRINTABILITY_VALIDATION,
    FabricationStage.SLICING,
    FabricationStage.FABRICATION_PACKAGE,
    FabricationStage.MANUFACTURING,
)


_ALLOWED_TRANSITIONS: dict[StageStatus, frozenset[StageStatus]] = {
    StageStatus.WAITING: frozenset(
        {StageStatus.RUNNING, StageStatus.CANCELLED, StageStatus.SUPERSEDED}
    ),
    StageStatus.RUNNING: frozenset(
        {
            StageStatus.NEEDS_INPUT,
            StageStatus.PASSED,
            StageStatus.PASSED_WITH_WARNINGS,
            StageStatus.FAILED,
            StageStatus.CANCELLED,
        }
    ),
    StageStatus.NEEDS_INPUT: frozenset(
        {StageStatus.RUNNING, StageStatus.CANCELLED, StageStatus.SUPERSEDED}
    ),
    StageStatus.PASSED: frozenset({StageStatus.SUPERSEDED}),
    StageStatus.PASSED_WITH_WARNINGS: frozenset({StageStatus.SUPERSEDED}),
    StageStatus.FAILED: frozenset(),
    StageStatus.CANCELLED: frozenset(),
    StageStatus.SUPERSEDED: frozenset(),
}


class StageTransitionError(ValueError):
    """Raised when a stage run attempts an illegal state transition."""


def previous_stage(stage: FabricationStage) -> FabricationStage | None:
    normalized = FabricationStage(stage)
    index = FABRICATION_STAGES.index(normalized)
    return FABRICATION_STAGES[index - 1] if index > 0 else None


def next_stage(stage: FabricationStage) -> FabricationStage | None:
    normalized = FabricationStage(stage)
    index = FABRICATION_STAGES.index(normalized)
    return FABRICATION_STAGES[index + 1] if index + 1 < len(FABRICATION_STAGES) else None


def transition_stage_run(
    run: StageRun,
    status: StageStatus,
    *,
    summary: str | None = None,
    error_message: str | None = None,
    evidence_level: EvidenceLevel | None = None,
    at: str | None = None,
) -> StageRun:
    """Return a new StageRun snapshot after validating the transition.

    A failed run cannot be restarted. A retry is represented by a new run with
    an incremented ``attempt`` value.
    """

    target = StageStatus(status)
    if target not in _ALLOWED_TRANSITIONS[run.status]:
        raise StageTransitionError(
            f"cannot transition {run.stage.value} from {run.status.value} to {target.value}"
        )

    timestamp = at or datetime.now(timezone.utc).isoformat()
    started_at = run.started_at
    completed_at = run.completed_at
    if target is StageStatus.RUNNING:
        started_at = started_at or timestamp
        completed_at = None
        if run.status is StageStatus.NEEDS_INPUT:
            error_message = None
    elif target in {
        StageStatus.PASSED,
        StageStatus.PASSED_WITH_WARNINGS,
        StageStatus.FAILED,
        StageStatus.CANCELLED,
        StageStatus.SUPERSEDED,
    }:
        completed_at = timestamp

    if target is StageStatus.FAILED and not (error_message or run.error_message):
        raise StageTransitionError("failed stage runs require an error_message")
    if target not in {StageStatus.FAILED, StageStatus.NEEDS_INPUT} and error_message is None:
        error_message = run.error_message if target is StageStatus.SUPERSEDED else None

    return replace(
        run,
        status=target,
        started_at=started_at,
        completed_at=completed_at,
        summary=run.summary if summary is None else summary,
        error_message=error_message,
        evidence_level=evidence_level if evidence_level is not None else run.evidence_level,
    )
