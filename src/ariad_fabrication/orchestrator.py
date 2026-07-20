"""M1 orchestrator for the Brief stage of the Fabrication Journey."""

from __future__ import annotations

from dataclasses import replace

from .domain import (
    Decision,
    DecisionActor,
    EvidenceLevel,
    EvidenceMode,
    FabricationJourney,
    FabricationStage,
    Finding,
    FindingSeverity,
    PartSpec,
    SpecStatus,
    StageRun,
    StageStatus,
    transition_stage_run,
)
from .intent_parser import IntentParser


class PipelineOrchestrator:
    """Create a traceable job and execute only the implemented Brief gate.

    Design and downstream providers are deliberately absent in M1. A successful
    result means the specification reached R0 and is ready for the Design stage;
    it does not mean geometry or manufacturing output exists.
    """

    def __init__(self, intent_parser: IntentParser, *, max_attempts: int = 2) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.intent_parser = intent_parser
        self.max_attempts = max_attempts

    def run(self, request: str, *, confirm: bool = False) -> FabricationJourney:
        """Parse a request and stop at either R0, needs_input, or failure."""

        journey = FabricationJourney.create(
            request,
            metadata={"input_parser": type(self.intent_parser).__name__},
        )
        for attempt in range(1, self.max_attempts + 1):
            run = journey.add_stage_run(
                FabricationStage.BRIEF,
                attempt=attempt,
                evidence_mode=EvidenceMode.REAL,
                tool_name=type(self.intent_parser).__name__,
                tool_version=self._parser_version(),
            )
            journey.emit_event(
                run.stage_run_id,
                "stage_queued",
                f"Brief attempt {attempt} queued",
            )
            run = self._transition(journey, run.stage_run_id, StageStatus.RUNNING)
            journey.emit_event(
                run.stage_run_id,
                "stage_started",
                f"Brief attempt {attempt} started",
            )

            try:
                spec = self.intent_parser.parse(request)
            except Exception as exc:
                self._record_parse_failure(journey, run.stage_run_id, exc)
                if attempt < self.max_attempts:
                    journey.emit_event(
                        run.stage_run_id,
                        "stage_retry_scheduled",
                        f"A new Brief attempt will follow attempt {attempt}",
                    )
                    continue
                journey.update_status("failed")
                return journey

            return self._complete_brief(journey, run.stage_run_id, spec, confirm=confirm)

        raise RuntimeError("unreachable Brief retry state")

    def run_spec(
        self,
        spec: PartSpec,
        *,
        request: str | None = None,
        confirm: bool = False,
    ) -> FabricationJourney:
        """Run the same Brief gate for a hand-authored PartSpec."""

        if not isinstance(spec, PartSpec):
            raise TypeError("spec must be a PartSpec")
        source_request = request or spec.purpose
        journey = FabricationJourney.create(
            source_request,
            title=spec.name,
            metadata={"input_parser": "hand_authored"},
        )
        run = journey.add_stage_run(
            FabricationStage.BRIEF,
            evidence_mode=EvidenceMode.REAL,
            tool_name="hand_authored_spec",
            tool_version=spec.schema_version,
        )
        journey.emit_event(run.stage_run_id, "stage_queued", "Hand-authored Brief queued")
        run = self._transition(journey, run.stage_run_id, StageStatus.RUNNING)
        journey.emit_event(run.stage_run_id, "stage_started", "Hand-authored Brief started")
        return self._complete_brief(journey, run.stage_run_id, spec, confirm=confirm)

    def _complete_brief(
        self,
        journey: FabricationJourney,
        stage_run_id: str,
        spec: PartSpec,
        *,
        confirm: bool,
    ) -> FabricationJourney:
        explicitly_confirmed = False
        if confirm and spec.status is SpecStatus.DRAFT:
            try:
                spec = spec.confirm()
                explicitly_confirmed = True
            except ValueError:
                # Readiness issues below become visible findings. Confirmation
                # never suppresses unknown requirements.
                pass

        revision = journey.add_revision(
            spec,
            reason="Initial manufacturing brief",
            stage_run_ids=(stage_run_id,),
        )
        current_run = journey.get_stage_run(stage_run_id)
        journey.replace_stage_run(replace(current_run, revision_id=revision.revision_id))
        journey.emit_event(
            stage_run_id,
            "spec_parsed",
            f"Created PartSpec {spec.schema_version} for {spec.name}",
            data={"spec_status": spec.status.value, "revision_id": revision.revision_id},
        )

        if explicitly_confirmed:
            journey.add_decision(
                Decision(
                    job_id=journey.job.job_id,
                    revision_id=revision.revision_id,
                    stage_run_id=stage_run_id,
                    question="Confirm this PartSpec for design?",
                    choice="confirmed",
                    rationale="The user explicitly confirmed the complete draft at intake.",
                    actor=DecisionActor.USER,
                )
            )

        issues = spec.readiness_issues()
        if issues:
            for issue in issues:
                journey.add_finding(
                    Finding(
                        job_id=journey.job.job_id,
                        revision_id=revision.revision_id,
                        stage_run_id=stage_run_id,
                        code="brief.readiness",
                        title="Specification needs input",
                        severity=FindingSeverity.WARNING,
                        evidence=issue,
                        remediation="Resolve the requirement and create a new confirmed revision.",
                        data={"issue": issue},
                    )
                )
            self._transition(
                journey,
                stage_run_id,
                StageStatus.NEEDS_INPUT,
                summary=f"Specification requires {len(issues)} clarification(s)",
            )
            journey.emit_event(
                stage_run_id,
                "spec_needs_input",
                "The Brief stopped before Design because requirements remain unresolved",
                data={"issues": list(issues)},
            )
            journey.update_status("needs_input")
            return journey

        self._transition(
            journey,
            stage_run_id,
            StageStatus.PASSED,
            summary="Confirmed PartSpec passed the Brief gate",
            evidence_level=EvidenceLevel.R0,
        )
        journey.emit_event(
            stage_run_id,
            "spec_validated",
            "Confirmed PartSpec reached R0 and is ready for Design",
            data={"evidence_level": EvidenceLevel.R0.value},
        )
        journey.update_status("ready_for_design")
        return journey

    def _record_parse_failure(
        self,
        journey: FabricationJourney,
        stage_run_id: str,
        error: Exception,
    ) -> None:
        message = str(error) or type(error).__name__
        journey.add_finding(
            Finding(
                job_id=journey.job.job_id,
                stage_run_id=stage_run_id,
                code="brief.parse_failed",
                title="Intent parsing failed",
                severity=FindingSeverity.ERROR,
                evidence=message,
                remediation="Clarify the request or retry with an available parser.",
                data={"exception_type": type(error).__name__},
            )
        )
        self._transition(
            journey,
            stage_run_id,
            StageStatus.FAILED,
            summary="The request could not be converted to a PartSpec",
            error_message=message,
        )
        journey.emit_event(stage_run_id, "spec_parse_failed", message)

    @staticmethod
    def _transition(
        journey: FabricationJourney,
        stage_run_id: str,
        status: StageStatus,
        **changes: object,
    ) -> StageRun:
        current = journey.get_stage_run(stage_run_id)
        updated = transition_stage_run(current, status, **changes)
        return journey.replace_stage_run(updated)

    def _parser_version(self) -> str:
        model = getattr(self.intent_parser, "model", None)
        return str(model) if model else "1.0.0"
