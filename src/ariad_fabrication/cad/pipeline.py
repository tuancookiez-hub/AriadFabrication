"""M2 Golden Part Design and Geometry Validation journey service."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ..domain import (
    Artifact,
    EvidenceLevel,
    EvidenceMode,
    FabricationJourney,
    FabricationStage,
    Finding,
    FindingSeverity,
    StageRun,
    StageStatus,
    transition_stage_run,
)
from .contracts import CadArtifactDescriptor, CadBuildRequest
from .golden_part import PROVIDER_ID
from .runner import CadRunOutcome, CadWorkerRunner
from .worker import WORKER_VERSION


PIPELINE_VERSION = "1.0.0"


@dataclass(frozen=True)
class CadPipelineOutcome:
    journey: FabricationJourney
    cad_run: CadRunOutcome | None
    revision_directory: Path
    journey_path: Path
    manifest_path: Path


class GoldenPartCadPipeline:
    """Advance one confirmed Golden Part revision from R0 through R1/R2.

    This service is intentionally benchmark-specific. It records a real worker
    attempt and deterministic geometry evidence; it does not assess printability
    or make physical-performance claims.
    """

    def __init__(
        self,
        runner: CadWorkerRunner,
        expected: Mapping[str, Any],
        *,
        provider_id: str = PROVIDER_ID,
    ) -> None:
        if not isinstance(runner, CadWorkerRunner):
            raise TypeError("runner must be a CadWorkerRunner")
        if not isinstance(expected, Mapping):
            raise TypeError("expected must be a mapping")
        self.runner = runner
        self.expected = json.loads(
            json.dumps(expected, ensure_ascii=False, allow_nan=False)
        )
        self.provider_id = str(provider_id).strip()
        if not self.provider_id:
            raise ValueError("provider_id is required")

    def run(self, journey: FabricationJourney) -> CadPipelineOutcome:
        revision = self._require_ready_revision(journey)
        if any(
            item.revision_id == revision.revision_id
            and item.stage in {FabricationStage.DESIGN, FabricationStage.GEOMETRY_VALIDATION}
            for item in journey.stage_runs
        ):
            raise ValueError("this revision already contains a CAD or geometry-validation run")

        request = CadBuildRequest(
            job_id=journey.job.job_id,
            revision_id=revision.revision_id,
            provider_id=self.provider_id,
            spec=revision.spec.to_dict(),
            expected=self.expected,
        )
        design_run = journey.add_stage_run(
            FabricationStage.DESIGN,
            revision_id=revision.revision_id,
            evidence_mode=EvidenceMode.REAL,
            tool_name="ariad_cad_worker",
            tool_version=WORKER_VERSION,
        )
        journey.emit_event(
            design_run.stage_run_id,
            "stage_queued",
            "Golden Part Design queued for the registered CAD worker",
            data={"provider_id": self.provider_id, "request_id": request.request_id},
        )
        design_run = self._transition(journey, design_run.stage_run_id, StageStatus.RUNNING)
        journey.emit_event(
            design_run.stage_run_id,
            "stage_started",
            "CAD worker process started",
        )

        cad_run: CadRunOutcome | None = None
        try:
            cad_run = self.runner.run(request)
            revision_directory = cad_run.revision_directory
        except Exception as exc:
            revision_directory = self._revision_directory(request)
            revision_directory.mkdir(parents=True, exist_ok=True)
            self._write_request_text(revision_directory, journey.job.request)
            self._record_design_failure(
                journey,
                design_run.stage_run_id,
                revision.revision_id,
                f"{type(exc).__name__}: {exc}",
                code="design.runner_failed",
            )
            return self._persist(journey, revision_directory, cad_run)

        try:
            self._write_request_text(revision_directory, journey.job.request)
            control_artifacts = self._record_control_artifacts(
                journey,
                design_run.stage_run_id,
                revision.revision_id,
                cad_run,
            )
            current_design = journey.get_stage_run(design_run.stage_run_id)
            if "cad_worker_request" in control_artifacts:
                journey.replace_stage_run(
                    replace(
                        current_design,
                        input_artifact_ids=(
                            control_artifacts["cad_worker_request"].artifact_id,
                        ),
                    )
                )
        except Exception as exc:
            self._record_design_failure(
                journey,
                design_run.stage_run_id,
                revision.revision_id,
                f"Artifact recording failed: {type(exc).__name__}: {exc}",
                code="design.artifact_recording_failed",
            )
            return self._persist(journey, revision_directory, cad_run)

        if not cad_run.result.success:
            message = "; ".join(cad_run.result.errors) or "CAD worker failed without an error"
            self._record_design_failure(
                journey,
                design_run.stage_run_id,
                revision.revision_id,
                message,
                code="design.worker_failed",
            )
            return self._persist(journey, revision_directory, cad_run)

        try:
            worker_artifacts = self._record_worker_artifacts(
                journey,
                design_run.stage_run_id,
                revision.revision_id,
                cad_run,
                control_artifacts,
            )
            exact = worker_artifacts["exact_geometry"]
            expected_artifact = worker_artifacts["benchmark_expectations"]
            report_descriptor = next(
                item
                for item in cad_run.result.artifacts
                if item.role == "geometry_validation_report"
            )
        except Exception as exc:
            self._record_design_failure(
                journey,
                design_run.stage_run_id,
                revision.revision_id,
                f"Worker artifact contract failed: {type(exc).__name__}: {exc}",
                code="design.artifact_contract_failed",
            )
            return self._persist(journey, revision_directory, cad_run)

        self._transition(
            journey,
            design_run.stage_run_id,
            StageStatus.PASSED,
            summary="Editable source executed and exact STEP re-imported as one valid solid",
            evidence_level=EvidenceLevel.R1,
        )
        journey.emit_event(
            design_run.stage_run_id,
            "design_completed",
            "Golden Part Design reached R1",
            data={
                "evidence_level": "R1",
                "exact_geometry_artifact_id": exact.artifact_id,
                "artifact_count": len(journey.get_stage_run(design_run.stage_run_id).artifact_ids),
            },
        )
        journey.update_status("design_generated")

        geometry_run = journey.add_stage_run(
            FabricationStage.GEOMETRY_VALIDATION,
            revision_id=revision.revision_id,
            evidence_mode=EvidenceMode.REAL,
            tool_name="ariad_occt_geometry_validator",
            tool_version=WORKER_VERSION,
        )
        journey.replace_stage_run(
            replace(
                geometry_run,
                input_artifact_ids=(exact.artifact_id, expected_artifact.artifact_id),
            )
        )
        journey.emit_event(
            geometry_run.stage_run_id,
            "stage_queued",
            "Deterministic STEP geometry checks queued",
        )
        self._transition(journey, geometry_run.stage_run_id, StageStatus.RUNNING)
        journey.emit_event(
            geometry_run.stage_run_id,
            "stage_started",
            "OCCT geometry validation started against the frozen benchmark",
        )

        report_artifact = self._artifact_from_descriptor(
            journey,
            geometry_run.stage_run_id,
            revision.revision_id,
            cad_run,
            report_descriptor,
            parent_artifact_ids=(exact.artifact_id, expected_artifact.artifact_id),
        )
        journey.add_artifact(report_artifact)
        try:
            report = json.loads(
                (revision_directory / report_descriptor.path).read_text(encoding="utf-8")
            )
            checks = report["checks"]
            if not isinstance(checks, list) or not checks:
                raise ValueError("geometry report contains no checks")
            report_passed = report.get("passed")
            if not isinstance(report_passed, bool):
                raise ValueError("geometry report passed field must be boolean")
            if report_passed != cad_run.result.validation_passed:
                raise ValueError("geometry report outcome does not match the worker result")
        except Exception as exc:
            self._record_geometry_failure(
                journey,
                geometry_run.stage_run_id,
                revision.revision_id,
                code="geometry.report_invalid",
                title="Geometry report could not be trusted",
                evidence=f"{type(exc).__name__}: {exc}",
                data={},
            )
            return self._persist(journey, revision_directory, cad_run)

        failed_checks = []
        for item in checks:
            if not isinstance(item, Mapping) or not isinstance(item.get("passed"), bool):
                self._record_geometry_failure(
                    journey,
                    geometry_run.stage_run_id,
                    revision.revision_id,
                    code="geometry.check_invalid",
                    title="Geometry check record is malformed",
                    evidence=repr(item),
                    data={},
                )
                return self._persist(journey, revision_directory, cad_run)
            journey.emit_event(
                geometry_run.stage_run_id,
                "geometry_check_completed",
                str(item.get("description") or item.get("check_id") or "Geometry check"),
                data={
                    "check_id": item.get("check_id"),
                    "passed": item["passed"],
                    "expected": item.get("expected"),
                    "actual": item.get("actual"),
                    "tolerance_mm": item.get("tolerance_mm"),
                },
            )
            if not item["passed"]:
                failed_checks.append(item)

        if failed_checks:
            for item in failed_checks:
                journey.add_finding(
                    Finding(
                        job_id=journey.job.job_id,
                        revision_id=revision.revision_id,
                        stage_run_id=geometry_run.stage_run_id,
                        code=f"geometry.{item.get('check_id', 'failed_check')}",
                        title=str(item.get("description") or "Geometry check failed"),
                        severity=FindingSeverity.ERROR,
                        evidence=(
                            f"Expected {item.get('expected')!r}; measured {item.get('actual')!r}."
                        ),
                        remediation="Revise the parametric design and create a new immutable revision.",
                        data=dict(item),
                    )
                )
            self._transition(
                journey,
                geometry_run.stage_run_id,
                StageStatus.FAILED,
                summary=f"{len(failed_checks)} deterministic geometry check(s) failed",
                error_message="The Golden Part did not satisfy the frozen R2 geometry gate",
            )
            journey.emit_event(
                geometry_run.stage_run_id,
                "geometry_validation_failed",
                "The revision remains R1 because deterministic geometry checks failed",
                data={"failed_check_count": len(failed_checks)},
            )
            journey.update_status("failed")
            return self._persist(journey, revision_directory, cad_run)

        self._transition(
            journey,
            geometry_run.stage_run_id,
            StageStatus.PASSED,
            summary=f"All {len(checks)} frozen Golden Part geometry checks passed",
            evidence_level=EvidenceLevel.R2,
        )
        journey.emit_event(
            geometry_run.stage_run_id,
            "geometry_validation_completed",
            "Golden Part Geometry Validation reached R2",
            data={
                "evidence_level": "R2",
                "check_count": len(checks),
                "claim_boundary": report.get("claim_boundary"),
            },
        )
        journey.update_status("geometry_verified")
        return self._persist(journey, revision_directory, cad_run)

    @staticmethod
    def _require_ready_revision(journey: FabricationJourney):
        if not isinstance(journey, FabricationJourney):
            raise TypeError("journey must be a FabricationJourney")
        revision = journey.current_revision
        if revision is None:
            raise ValueError("journey has no current revision")
        revision.spec.assert_ready_for_design()
        brief_runs = [
            item
            for item in journey.stage_runs
            if item.revision_id == revision.revision_id and item.stage is FabricationStage.BRIEF
        ]
        if not any(
            item.status is StageStatus.PASSED and item.evidence_level is EvidenceLevel.R0
            for item in brief_runs
        ):
            raise ValueError("current revision has not passed the R0 Brief gate")
        if journey.status != "ready_for_design":
            raise ValueError("journey is not ready_for_design")
        return revision

    def _revision_directory(self, request: CadBuildRequest) -> Path:
        directory = (
            self.runner.artifact_root / request.job_id / "revisions" / request.revision_id
        ).resolve()
        if not directory.is_relative_to(self.runner.artifact_root):
            raise ValueError("revision directory escapes the configured artifact root")
        return directory

    @staticmethod
    def _write_request_text(revision_directory: Path, request: str) -> None:
        path = revision_directory / "request.txt"
        payload = request.rstrip() + "\n"
        if path.exists():
            if path.read_text(encoding="utf-8") != payload:
                raise FileExistsError("immutable request.txt already contains different content")
            return
        path.write_text(payload, encoding="utf-8")

    def _record_control_artifacts(
        self,
        journey: FabricationJourney,
        stage_run_id: str,
        revision_id: str,
        outcome: CadRunOutcome,
    ) -> dict[str, Artifact]:
        paths = (
            ("user_request", outcome.revision_directory / "request.txt", "text/plain"),
            ("cad_worker_request", outcome.request_path, "application/json"),
            ("cad_worker_stdout", outcome.stdout_path, "text/plain"),
            ("cad_worker_stderr", outcome.stderr_path, "text/plain"),
            ("cad_worker_result", outcome.result_path, "application/json"),
        )
        artifacts: dict[str, Artifact] = {}
        for role, path, media_type in paths:
            if not path.exists():
                continue
            parents: tuple[str, ...] = ()
            if role != "user_request" and "cad_worker_request" in artifacts:
                parents = (artifacts["cad_worker_request"].artifact_id,)
            artifact = self._artifact_from_path(
                journey,
                stage_run_id,
                revision_id,
                outcome.revision_directory,
                path,
                role=role,
                media_type=media_type,
                producer="ariad_cad_runner",
                producer_version=PIPELINE_VERSION,
                parent_artifact_ids=parents,
            )
            journey.add_artifact(artifact)
            artifacts[role] = artifact
        return artifacts

    def _record_worker_artifacts(
        self,
        journey: FabricationJourney,
        stage_run_id: str,
        revision_id: str,
        outcome: CadRunOutcome,
        control: Mapping[str, Artifact],
    ) -> dict[str, Artifact]:
        descriptors = {
            item.role: item
            for item in outcome.result.artifacts
            if item.role != "geometry_validation_report"
        }
        recorded: dict[str, Artifact] = {}
        request_parent = (
            (control["cad_worker_request"].artifact_id,)
            if "cad_worker_request" in control
            else ()
        )
        order = (
            "part_spec",
            "benchmark_expectations",
            "cad_parameters",
            "cad_source",
            "exact_geometry",
            "cad_environment",
            "compatibility_mesh",
            "manufacturing_model",
            "preview_model",
        )
        for role in order:
            descriptor = descriptors.get(role)
            if descriptor is None:
                continue
            parents = request_parent
            if role == "cad_parameters" and {
                "part_spec",
                "benchmark_expectations",
            }.issubset(recorded):
                parents = (
                    recorded["part_spec"].artifact_id,
                    recorded["benchmark_expectations"].artifact_id,
                )
            elif role == "exact_geometry" and {"cad_source", "cad_parameters"}.issubset(
                recorded
            ):
                parents = (
                    recorded["cad_source"].artifact_id,
                    recorded["cad_parameters"].artifact_id,
                )
            elif role in {"compatibility_mesh", "manufacturing_model", "preview_model"} and {
                "cad_source",
                "cad_parameters",
            }.issubset(recorded):
                parents = (
                    recorded["cad_source"].artifact_id,
                    recorded["cad_parameters"].artifact_id,
                )
            artifact = self._artifact_from_descriptor(
                journey,
                stage_run_id,
                revision_id,
                outcome,
                descriptor,
                parent_artifact_ids=parents,
            )
            journey.add_artifact(artifact)
            recorded[role] = artifact

        required = {
            "part_spec",
            "benchmark_expectations",
            "cad_parameters",
            "cad_source",
            "exact_geometry",
            "cad_environment",
        }
        missing = required - recorded.keys()
        if missing:
            raise ValueError(f"successful CAD result is missing required roles: {sorted(missing)}")
        return recorded

    @staticmethod
    def _artifact_from_descriptor(
        journey: FabricationJourney,
        stage_run_id: str,
        revision_id: str,
        outcome: CadRunOutcome,
        descriptor: CadArtifactDescriptor,
        *,
        parent_artifact_ids: tuple[str, ...] = (),
    ) -> Artifact:
        path = (outcome.revision_directory / descriptor.path).resolve()
        if not path.is_relative_to(outcome.revision_directory):
            raise ValueError("CAD descriptor escapes the revision directory")
        return Artifact(
            job_id=journey.job.job_id,
            revision_id=revision_id,
            stage_run_id=stage_run_id,
            role=descriptor.role,
            path=descriptor.path,
            media_type=descriptor.media_type,
            checksum_sha256=descriptor.checksum_sha256,
            producer=descriptor.producer,
            producer_version=descriptor.producer_version,
            evidence_mode=EvidenceMode.REAL,
            parent_artifact_ids=parent_artifact_ids,
            size_bytes=descriptor.size_bytes,
            metadata={"format": descriptor.format.value},
        )

    @staticmethod
    def _artifact_from_path(
        journey: FabricationJourney,
        stage_run_id: str,
        revision_id: str,
        revision_directory: Path,
        path: Path,
        *,
        role: str,
        media_type: str,
        producer: str,
        producer_version: str,
        parent_artifact_ids: tuple[str, ...] = (),
    ) -> Artifact:
        resolved = path.resolve()
        if not resolved.is_relative_to(revision_directory):
            raise ValueError("control artifact escapes the revision directory")
        payload = resolved.read_bytes()
        return Artifact(
            job_id=journey.job.job_id,
            revision_id=revision_id,
            stage_run_id=stage_run_id,
            role=role,
            path=resolved.relative_to(revision_directory).as_posix(),
            media_type=media_type,
            checksum_sha256=hashlib.sha256(payload).hexdigest(),
            producer=producer,
            producer_version=producer_version,
            evidence_mode=EvidenceMode.REAL,
            parent_artifact_ids=parent_artifact_ids,
            size_bytes=len(payload),
        )

    @staticmethod
    def _record_design_failure(
        journey: FabricationJourney,
        stage_run_id: str,
        revision_id: str,
        message: str,
        *,
        code: str,
    ) -> None:
        journey.add_finding(
            Finding(
                job_id=journey.job.job_id,
                revision_id=revision_id,
                stage_run_id=stage_run_id,
                code=code,
                title="CAD Design stage failed",
                severity=FindingSeverity.ERROR,
                evidence=message,
                remediation="Inspect the recorded worker request, result, and logs before retrying.",
            )
        )
        GoldenPartCadPipeline._transition(
            journey,
            stage_run_id,
            StageStatus.FAILED,
            summary="No R1 design evidence was accepted",
            error_message=message,
        )
        journey.emit_event(
            stage_run_id,
            "design_failed",
            "The Design stage failed without advancing the evidence level",
            data={"error": message},
        )
        journey.update_status("failed")

    @staticmethod
    def _record_geometry_failure(
        journey: FabricationJourney,
        stage_run_id: str,
        revision_id: str,
        *,
        code: str,
        title: str,
        evidence: str,
        data: Mapping[str, Any],
    ) -> None:
        journey.add_finding(
            Finding(
                job_id=journey.job.job_id,
                revision_id=revision_id,
                stage_run_id=stage_run_id,
                code=code,
                title=title,
                severity=FindingSeverity.ERROR,
                evidence=evidence,
                remediation="Inspect the report and rerun validation in a new revision.",
                data=data,
            )
        )
        GoldenPartCadPipeline._transition(
            journey,
            stage_run_id,
            StageStatus.FAILED,
            summary="Geometry report validation failed",
            error_message=evidence,
        )
        journey.emit_event(
            stage_run_id,
            "geometry_validation_failed",
            "Geometry Validation failed without an R2 claim",
            data={"error": evidence},
        )
        journey.update_status("failed")

    @staticmethod
    def _transition(
        journey: FabricationJourney,
        stage_run_id: str,
        status: StageStatus,
        **changes: object,
    ) -> StageRun:
        updated = transition_stage_run(
            journey.get_stage_run(stage_run_id),
            status,
            **changes,
        )
        return journey.replace_stage_run(updated)

    @staticmethod
    def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _persist(
        self,
        journey: FabricationJourney,
        revision_directory: Path,
        cad_run: CadRunOutcome | None,
    ) -> CadPipelineOutcome:
        revision = journey.current_revision
        if revision is None:
            raise RuntimeError("cannot persist a journey without a current revision")
        journey_path = revision_directory / "journey.json"
        manifest_path = revision_directory / "manifest.json"
        self._write_json_atomic(journey_path, journey.to_dict())
        self._write_json_atomic(
            manifest_path,
            journey.manifest_for_revision(revision.revision_id).to_dict(),
        )
        return CadPipelineOutcome(
            journey=journey,
            cad_run=cad_run,
            revision_directory=revision_directory,
            journey_path=journey_path,
            manifest_path=manifest_path,
        )
