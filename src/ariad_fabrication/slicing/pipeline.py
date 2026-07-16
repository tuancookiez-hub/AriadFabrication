"""Golden Part R3/R4 journey integration for printability and real slicing."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from ..cad.pipeline import CadPipelineOutcome
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
from .printability import (
    PrintabilityReport,
    VALIDATOR_ID,
    VALIDATOR_VERSION,
    assess_golden_part_printability,
    write_printability_report,
)
from .profiles import ProfileBundle
from .prusaslicer import ADAPTER_ID, ADAPTER_VERSION, PrusaSlicerAdapter, SliceOutcome


FABRICATION_PIPELINE_VERSION = "1.0.0"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class GoldenPartFabricationOutcome:
    journey: FabricationJourney
    printability_report: PrintabilityReport | None
    slice_outcome: SliceOutcome | None
    revision_directory: Path
    journey_path: Path
    manifest_path: Path
    package_report_path: Path | None


class GoldenPartFabricationPipeline:
    """Advance one existing R2 Golden Part revision through R3 and R4.

    Hardware is never contacted.  The real slicer runs locally against a
    snapshot of explicit generic profiles, and every output remains scoped to
    the existing immutable revision directory.
    """

    def __init__(
        self,
        profiles: ProfileBundle,
        printability_expected: Mapping[str, Any],
        slicer: PrusaSlicerAdapter,
    ) -> None:
        if not isinstance(profiles, ProfileBundle):
            raise TypeError("profiles must be a ProfileBundle")
        if not isinstance(printability_expected, Mapping):
            raise TypeError("printability_expected must be a mapping")
        if not isinstance(slicer, PrusaSlicerAdapter):
            raise TypeError("slicer must be a PrusaSlicerAdapter")
        profiles.validate()
        self.profiles = profiles
        self.expected = json.loads(
            json.dumps(printability_expected, ensure_ascii=False, allow_nan=False)
        )
        risk_policy = self.expected.get("risk_policy")
        if not isinstance(risk_policy, Mapping):
            raise ValueError("printability_expected.risk_policy must be an object")
        required_risks = {
            "unknown_slicer_warning",
            "floating_bridge_anchor_warning",
            "low_bed_adhesion_warning",
            "slicer_mesh_repair",
        }
        if set(risk_policy) != required_risks:
            raise ValueError("risk_policy must define every supported slicer finding exactly once")
        if any(
            value not in {"block_r4", "allow_r4_with_warning"}
            for value in risk_policy.values()
        ):
            raise ValueError("unsupported risk_policy disposition")
        self.slicer = slicer

    def run(self, cad_outcome: CadPipelineOutcome) -> GoldenPartFabricationOutcome:
        if not isinstance(cad_outcome, CadPipelineOutcome):
            raise TypeError("cad_outcome must be a CadPipelineOutcome")
        journey = cad_outcome.journey
        revision = journey.current_revision
        if revision is None:
            raise ValueError("journey has no current revision")
        revision_directory = cad_outcome.revision_directory.resolve()
        if not revision_directory.is_dir():
            raise FileNotFoundError(revision_directory)
        self._require_r2(journey, revision.revision_id)
        if any(
            item.revision_id == revision.revision_id
            and item.stage
            in {
                FabricationStage.PRINTABILITY_VALIDATION,
                FabricationStage.SLICING,
                FabricationStage.FABRICATION_PACKAGE,
            }
            for item in journey.stage_runs
        ):
            raise ValueError("this revision already contains an R3/R4 manufacturing run")

        exact = self._artifact_by_role(journey, revision.revision_id, "exact_geometry")
        geometry_report_artifact = self._artifact_by_role(
            journey,
            revision.revision_id,
            "geometry_validation_report",
        )
        part_spec_artifact = self._artifact_by_role(
            journey,
            revision.revision_id,
            "part_spec",
        )
        exact_path = self._verified_artifact_path(revision_directory, exact)
        geometry_report_path = self._verified_artifact_path(
            revision_directory,
            geometry_report_artifact,
        )
        part_spec_path = self._verified_artifact_path(revision_directory, part_spec_artifact)

        printability_run = journey.add_stage_run(
            FabricationStage.PRINTABILITY_VALIDATION,
            revision_id=revision.revision_id,
            evidence_mode=EvidenceMode.REAL,
            tool_name=VALIDATOR_ID,
            tool_version=VALIDATOR_VERSION,
        )
        journey.emit_event(
            printability_run.stage_run_id,
            "stage_queued",
            "Profile-specific Golden Part printability checks queued",
        )
        self._transition(journey, printability_run.stage_run_id, StageStatus.RUNNING)
        journey.emit_event(
            printability_run.stage_run_id,
            "stage_started",
            "Orientation materialization and deterministic OCCT printability assessment started",
        )

        printability_report: PrintabilityReport | None = None
        slice_outcome: SliceOutcome | None = None
        package_report_path: Path | None = None
        profile_artifacts: dict[str, Artifact] = {}
        try:
            snapshot_bundle, profile_artifacts = self._snapshot_profiles(
                journey,
                printability_run.stage_run_id,
                revision.revision_id,
                revision_directory,
            )
            policy_path = revision_directory / "printability" / "policy.json"
            self._write_json_new(policy_path, self.expected)
            policy_artifact = self._record_file(
                journey,
                printability_run.stage_run_id,
                revision.revision_id,
                revision_directory,
                policy_path,
                role="printability_policy",
                media_type="application/json",
                producer="ariad_benchmark_policy",
                producer_version=FABRICATION_PIPELINE_VERSION,
            )
            oriented_path = revision_directory / "printability" / "oriented.step"
            printability_report = assess_golden_part_printability(
                exact_path,
                oriented_path,
                geometry_report=json.loads(geometry_report_path.read_text(encoding="utf-8")),
                part_spec=json.loads(part_spec_path.read_text(encoding="utf-8")),
                profiles=snapshot_bundle,
                expected=self.expected,
            )
            oriented_artifact = self._record_file(
                journey,
                printability_run.stage_run_id,
                revision.revision_id,
                revision_directory,
                oriented_path,
                role="oriented_geometry",
                media_type="model/step",
                producer=VALIDATOR_ID,
                producer_version=VALIDATOR_VERSION,
                parent_artifact_ids=(
                    exact.artifact_id,
                    profile_artifacts["orientation_profile"].artifact_id,
                ),
            )
            report_path = revision_directory / "printability" / "report.json"
            write_printability_report(report_path, printability_report)
            report_artifact = self._record_file(
                journey,
                printability_run.stage_run_id,
                revision.revision_id,
                revision_directory,
                report_path,
                role="printability_report",
                media_type="application/json",
                producer=VALIDATOR_ID,
                producer_version=VALIDATOR_VERSION,
                parent_artifact_ids=(
                    exact.artifact_id,
                    geometry_report_artifact.artifact_id,
                    part_spec_artifact.artifact_id,
                    profile_artifacts["profile_bundle"].artifact_id,
                    policy_artifact.artifact_id,
                    oriented_artifact.artifact_id,
                ),
            )
            input_ids = (
                exact.artifact_id,
                geometry_report_artifact.artifact_id,
                part_spec_artifact.artifact_id,
                policy_artifact.artifact_id,
                *(item.artifact_id for item in profile_artifacts.values()),
            )
            journey.replace_stage_run(
                replace(
                    journey.get_stage_run(printability_run.stage_run_id),
                    input_artifact_ids=tuple(dict.fromkeys(input_ids)),
                )
            )
            for check in printability_report.checks:
                journey.emit_event(
                    printability_run.stage_run_id,
                    "printability_check_completed",
                    check.description,
                    data={
                        "check_id": check.check_id,
                        "category": check.category,
                        "passed": check.passed,
                        "actual": check.actual,
                        "requirement": check.requirement,
                    },
                )
                if not check.passed:
                    journey.add_finding(
                        Finding(
                            job_id=journey.job.job_id,
                            revision_id=revision.revision_id,
                            stage_run_id=printability_run.stage_run_id,
                            code=f"printability.{check.check_id}",
                            title=check.description,
                            severity=FindingSeverity.ERROR,
                            evidence=f"Measured {check.actual!r}; required {check.requirement!r}.",
                            remediation=check.remediation,
                            data=check.to_dict(),
                        )
                    )
            for warning in printability_report.warnings:
                journey.add_finding(
                    Finding(
                        job_id=journey.job.job_id,
                        revision_id=revision.revision_id,
                        stage_run_id=printability_run.stage_run_id,
                        code=str(warning["code"]),
                        title=str(warning["title"]),
                        severity=FindingSeverity.WARNING,
                        evidence=str(warning["evidence"]),
                        remediation=str(warning["physical_resolution"]),
                        data=dict(warning),
                    )
                )
        except Exception as exc:
            self._fail_stage(
                journey,
                printability_run.stage_run_id,
                revision.revision_id,
                code="printability.execution_failed",
                title="Printability assessment could not complete",
                message=f"{type(exc).__name__}: {exc}",
            )
            return self._persist(
                journey,
                revision_directory,
                printability_report,
                slice_outcome,
                package_report_path,
            )

        if not printability_report.passed:
            self._transition(
                journey,
                printability_run.stage_run_id,
                StageStatus.FAILED,
                summary=f"{len(printability_report.failed_checks)} deterministic printability check(s) failed",
                error_message="The Golden Part did not satisfy the frozen R3 gate",
            )
            journey.emit_event(
                printability_run.stage_run_id,
                "printability_validation_failed",
                "The revision remains R2 because profile-specific printability checks failed",
                data={"failed_check_count": len(printability_report.failed_checks)},
            )
            journey.update_status("failed")
            return self._persist(
                journey,
                revision_directory,
                printability_report,
                slice_outcome,
                package_report_path,
            )

        printability_status = (
            StageStatus.PASSED_WITH_WARNINGS
            if printability_report.warnings
            else StageStatus.PASSED
        )
        self._transition(
            journey,
            printability_run.stage_run_id,
            printability_status,
            summary=(
                f"All {len(printability_report.checks)} deterministic checks passed; "
                f"{len(printability_report.warnings)} physical unknown(s) remain visible"
            ),
            evidence_level=EvidenceLevel.R3,
        )
        journey.emit_event(
            printability_run.stage_run_id,
            "printability_validation_completed",
            "Golden Part reached profile-specific R3 printability assessment",
            data={
                "evidence_level": "R3",
                "status": printability_report.status,
                "profile_ids": dict(printability_report.profile_ids),
                "claim_boundary": printability_report.claim_boundary,
            },
        )
        journey.update_status("printability_assessed")

        slicing_run = journey.add_stage_run(
            FabricationStage.SLICING,
            revision_id=revision.revision_id,
            evidence_mode=EvidenceMode.REAL,
            tool_name=ADAPTER_ID,
            tool_version=ADAPTER_VERSION,
        )
        slicing_input_ids = (
            oriented_artifact.artifact_id,
            profile_artifacts["profile_bundle"].artifact_id,
            report_artifact.artifact_id,
        )
        journey.replace_stage_run(
            replace(slicing_run, input_artifact_ids=slicing_input_ids)
        )
        journey.emit_event(
            slicing_run.stage_run_id,
            "stage_queued",
            "Approved disconnected PrusaSlicer run queued",
            data={"slicer_version": self.slicer.installation.version},
        )
        self._transition(journey, slicing_run.stage_run_id, StageStatus.RUNNING)
        journey.emit_event(
            slicing_run.stage_run_id,
            "stage_started",
            "Real local slicer process started with no printer adapter",
        )
        slicing_directory = revision_directory / "slicing"
        try:
            slice_outcome = self.slicer.slice_model(
                oriented_path,
                slicing_directory,
                snapshot_bundle,
            )
            slicer_artifacts = self._record_slicer_artifacts(
                journey,
                slicing_run.stage_run_id,
                revision.revision_id,
                revision_directory,
                slice_outcome,
                common_parent_ids=slicing_input_ids,
            )
        except Exception as exc:
            self._record_existing_slicer_attempt(
                journey,
                slicing_run.stage_run_id,
                revision.revision_id,
                revision_directory,
                slicing_directory,
                common_parent_ids=slicing_input_ids,
            )
            self._fail_stage(
                journey,
                slicing_run.stage_run_id,
                revision.revision_id,
                code="slicing.execution_failed",
                title="Real slicer run could not complete",
                message=f"{type(exc).__name__}: {exc}",
            )
            return self._persist(
                journey,
                revision_directory,
                printability_report,
                slice_outcome,
                package_report_path,
            )

        blockers, advisories = self._evaluate_slicer_gate(slice_outcome)
        for warning in advisories:
            journey.add_finding(
                Finding(
                    job_id=journey.job.job_id,
                    revision_id=revision.revision_id,
                    stage_run_id=slicing_run.stage_run_id,
                    code="slicing.advisory",
                    title="Slicer advisory remains visible",
                    severity=FindingSeverity.WARNING,
                    evidence=warning,
                    remediation="Resolve on the selected physical machine or retain the warning in the package.",
                )
            )
        for blocker in blockers:
            journey.add_finding(
                Finding(
                    job_id=journey.job.job_id,
                    revision_id=revision.revision_id,
                    stage_run_id=slicing_run.stage_run_id,
                    code="slicing.blocking_finding",
                    title="Slicer evidence did not satisfy the R4 policy",
                    severity=FindingSeverity.ERROR,
                    evidence=blocker,
                    remediation="Revise geometry/profile and create a new immutable revision before retrying.",
                )
            )
        journey.emit_event(
            slicing_run.stage_run_id,
            "gcode_preflight_completed",
            "Disconnected G-code preflight and warning policy evaluated",
            data={
                "preflight_passed": slice_outcome.preflight.passed,
                "blockers": blockers,
                "advisories": advisories,
            },
        )
        if blockers:
            self._transition(
                journey,
                slicing_run.stage_run_id,
                StageStatus.FAILED,
                summary=f"Real slicer completed but {len(blockers)} R4 blocker(s) remain",
                error_message="Slicer/preflight policy blocked R4 evidence",
            )
            journey.emit_event(
                slicing_run.stage_run_id,
                "slicing_gate_failed",
                "G-code was retained as evidence but the revision did not advance to R4",
                data={"blockers": blockers},
            )
            journey.update_status("failed")
            return self._persist(
                journey,
                revision_directory,
                printability_report,
                slice_outcome,
                package_report_path,
            )

        slicing_status = (
            StageStatus.PASSED_WITH_WARNINGS if advisories else StageStatus.PASSED
        )
        self._transition(
            journey,
            slicing_run.stage_run_id,
            slicing_status,
            summary=(
                "PrusaSlicer produced a profile-bearing 3MF and G-code that passed disconnected preflight"
            ),
            evidence_level=EvidenceLevel.R4,
        )
        journey.emit_event(
            slicing_run.stage_run_id,
            "slicing_completed",
            "Golden Part reached R4 slicer verification for the recorded profile",
            data={
                "evidence_level": "R4",
                "slicer_version": slice_outcome.installation.version,
                "gcode_checksum_sha256": slicer_artifacts["gcode"].checksum_sha256,
                "physical_validation": False,
            },
        )
        journey.update_status("slicer_verified")

        package_report_path = self._build_package(
            journey,
            revision.revision_id,
            revision_directory,
            printability_report,
            slice_outcome,
        )
        return self._persist(
            journey,
            revision_directory,
            printability_report,
            slice_outcome,
            package_report_path,
        )

    @staticmethod
    def _require_r2(journey: FabricationJourney, revision_id: str) -> None:
        if journey.status != "geometry_verified":
            raise ValueError("journey must be geometry_verified before R3")
        matches = [
            item
            for item in journey.stage_runs
            if item.revision_id == revision_id
            and item.stage is FabricationStage.GEOMETRY_VALIDATION
            and item.status in {StageStatus.PASSED, StageStatus.PASSED_WITH_WARNINGS}
            and item.evidence_level is EvidenceLevel.R2
        ]
        if len(matches) != 1:
            raise ValueError("current revision must contain exactly one passed R2 geometry run")

    @staticmethod
    def _artifact_by_role(
        journey: FabricationJourney,
        revision_id: str,
        role: str,
    ) -> Artifact:
        matches = [
            item
            for item in journey.artifacts
            if item.revision_id == revision_id and item.role == role
        ]
        if len(matches) != 1:
            raise ValueError(f"revision must contain exactly one {role!r} artifact")
        return matches[0]

    @staticmethod
    def _verified_artifact_path(revision_directory: Path, artifact: Artifact) -> Path:
        path = (revision_directory / artifact.path).resolve()
        if not path.is_relative_to(revision_directory) or not path.is_file():
            raise ValueError(f"artifact path is missing or escapes the revision: {artifact.path}")
        if path.stat().st_size != artifact.size_bytes or _sha256(path) != artifact.checksum_sha256:
            raise ValueError(f"artifact checksum mismatch: {artifact.role}")
        return path

    def _snapshot_profiles(
        self,
        journey: FabricationJourney,
        stage_run_id: str,
        revision_id: str,
        revision_directory: Path,
    ) -> tuple[ProfileBundle, dict[str, Artifact]]:
        profile_directory = revision_directory / "profiles"
        if profile_directory.exists():
            raise FileExistsError("immutable profile snapshot already exists")
        profile_directory.mkdir(parents=True)
        destinations = {
            "printer_profile": profile_directory / "printer.json",
            "material_profile": profile_directory / "material.json",
            "process_profile": profile_directory / "process.json",
            "orientation_profile": profile_directory / "orientation.json",
            "slicer_profile": profile_directory / "prusaslicer.ini",
        }
        sources = {
            "printer_profile": self.profiles.source_paths[0],
            "material_profile": self.profiles.source_paths[1],
            "process_profile": self.profiles.source_paths[2],
            "orientation_profile": self.profiles.source_paths[3],
            "slicer_profile": self.profiles.slicer_config_path,
        }
        artifacts: dict[str, Artifact] = {}
        for role, destination in destinations.items():
            shutil.copyfile(sources[role], destination)
            artifacts[role] = self._record_file(
                journey,
                stage_run_id,
                revision_id,
                revision_directory,
                destination,
                role=role,
                media_type="application/json" if destination.suffix == ".json" else "text/plain",
                producer="ariad_profile_snapshot",
                producer_version=FABRICATION_PIPELINE_VERSION,
            )
        bundle = ProfileBundle.from_paths(
            printer_path=destinations["printer_profile"],
            material_path=destinations["material_profile"],
            process_path=destinations["process_profile"],
            orientation_path=destinations["orientation_profile"],
            slicer_config_path=destinations["slicer_profile"],
        )
        bundle_path = profile_directory / "bundle.json"
        self._write_json_new(bundle_path, bundle.to_dict(relative_to=revision_directory))
        artifacts["profile_bundle"] = self._record_file(
            journey,
            stage_run_id,
            revision_id,
            revision_directory,
            bundle_path,
            role="profile_bundle",
            media_type="application/json",
            producer="ariad_profile_snapshot",
            producer_version=FABRICATION_PIPELINE_VERSION,
            parent_artifact_ids=tuple(item.artifact_id for item in artifacts.values()),
        )
        return bundle, artifacts

    def _evaluate_slicer_gate(self, outcome: SliceOutcome) -> tuple[list[str], list[str]]:
        risk_policy = self.expected["risk_policy"]
        blockers: list[str] = []
        advisories: list[str] = []

        def apply(disposition_key: str, message: str) -> None:
            if risk_policy[disposition_key] == "block_r4":
                blockers.append(message)
            else:
                advisories.append(message)

        if not outcome.preflight.passed:
            blockers.append(
                "Disconnected G-code preflight failed: " + ", ".join(outcome.preflight.errors)
            )
        if outcome.model_info.degenerate_facets or outcome.model_info.facets_removed:
            apply(
                "slicer_mesh_repair",
                "PrusaSlicer reported mesh repair for exact CAD input "
                f"({outcome.model_info.degenerate_facets} degenerate, "
                f"{outcome.model_info.facets_removed} removed).",
            )
        for warning in outcome.slicer_warnings:
            normalized = warning.casefold()
            if "low bed adhesion" in normalized:
                apply("low_bed_adhesion_warning", warning)
            elif "floating bridge" in normalized:
                apply("floating_bridge_anchor_warning", warning)
            else:
                apply("unknown_slicer_warning", "Unclassified slicer warning: " + warning)
        return blockers, advisories

    def _record_slicer_artifacts(
        self,
        journey: FabricationJourney,
        stage_run_id: str,
        revision_id: str,
        revision_directory: Path,
        outcome: SliceOutcome,
        *,
        common_parent_ids: tuple[str, ...],
    ) -> dict[str, Artifact]:
        recorded: dict[str, Artifact] = {}
        recorded["slicer_installation"] = self._record_file(
            journey,
            stage_run_id,
            revision_id,
            revision_directory,
            outcome.installation_path,
            role="slicer_installation",
            media_type="application/json",
            producer=ADAPTER_ID,
            producer_version=ADAPTER_VERSION,
        )
        for command_index, command in enumerate(outcome.commands, start=1):
            for stream, path in (("stdout", command.stdout_path), ("stderr", command.stderr_path)):
                role = f"slicer_command_{command_index}_{stream}"
                recorded[role] = self._record_file(
                    journey,
                    stage_run_id,
                    revision_id,
                    revision_directory,
                    path,
                    role=role,
                    media_type="text/plain",
                    producer=ADAPTER_ID,
                    producer_version=ADAPTER_VERSION,
                    parent_artifact_ids=common_parent_ids,
                )
        production_parents = (
            *common_parent_ids,
            recorded["slicer_installation"].artifact_id,
        )
        recorded["slicer_project"] = self._record_file(
            journey,
            stage_run_id,
            revision_id,
            revision_directory,
            outcome.project_path,
            role="slicer_project",
            media_type="model/3mf",
            producer=ADAPTER_ID,
            producer_version=ADAPTER_VERSION,
            parent_artifact_ids=production_parents,
        )
        recorded["gcode"] = self._record_file(
            journey,
            stage_run_id,
            revision_id,
            revision_directory,
            outcome.gcode_path,
            role="gcode",
            media_type="text/x.gcode",
            producer=ADAPTER_ID,
            producer_version=ADAPTER_VERSION,
            parent_artifact_ids=production_parents,
        )
        recorded["gcode_preflight"] = self._record_file(
            journey,
            stage_run_id,
            revision_id,
            revision_directory,
            outcome.preflight_path,
            role="gcode_preflight",
            media_type="application/json",
            producer="ariad_gcode_preflight",
            producer_version=FABRICATION_PIPELINE_VERSION,
            parent_artifact_ids=(
                recorded["gcode"].artifact_id,
                common_parent_ids[1],
            ),
        )
        recorded["slicer_run_report"] = self._record_file(
            journey,
            stage_run_id,
            revision_id,
            revision_directory,
            outcome.report_path,
            role="slicer_run_report",
            media_type="application/json",
            producer=ADAPTER_ID,
            producer_version=ADAPTER_VERSION,
            parent_artifact_ids=(
                recorded["slicer_installation"].artifact_id,
                recorded["slicer_project"].artifact_id,
                recorded["gcode"].artifact_id,
                recorded["gcode_preflight"].artifact_id,
            ),
        )
        return recorded

    def _record_existing_slicer_attempt(
        self,
        journey: FabricationJourney,
        stage_run_id: str,
        revision_id: str,
        revision_directory: Path,
        slicing_directory: Path,
        *,
        common_parent_ids: tuple[str, ...],
    ) -> None:
        if not slicing_directory.is_dir():
            return
        known = {
            "slicer_installation.json": ("slicer_installation_attempt", "application/json"),
            "model_info.stdout.log": ("slicer_model_info_stdout_attempt", "text/plain"),
            "model_info.stderr.log": ("slicer_model_info_stderr_attempt", "text/plain"),
            "project.stdout.log": ("slicer_project_stdout_attempt", "text/plain"),
            "project.stderr.log": ("slicer_project_stderr_attempt", "text/plain"),
            "slice.stdout.log": ("slicer_slice_stdout_attempt", "text/plain"),
            "slice.stderr.log": ("slicer_slice_stderr_attempt", "text/plain"),
        }
        existing_roles = {item.role for item in journey.artifacts}
        existing_paths = {
            item.path
            for item in journey.artifacts
            if item.revision_id == revision_id
        }
        for filename, (role, media_type) in known.items():
            path = slicing_directory / filename
            relative_path = path.resolve().relative_to(revision_directory).as_posix()
            if (
                path.is_file()
                and role not in existing_roles
                and relative_path not in existing_paths
            ):
                self._record_file(
                    journey,
                    stage_run_id,
                    revision_id,
                    revision_directory,
                    path,
                    role=role,
                    media_type=media_type,
                    producer=ADAPTER_ID,
                    producer_version=ADAPTER_VERSION,
                    parent_artifact_ids=common_parent_ids,
                )

    def _build_package(
        self,
        journey: FabricationJourney,
        revision_id: str,
        revision_directory: Path,
        printability: PrintabilityReport,
        slicing: SliceOutcome,
    ) -> Path:
        package_run = journey.add_stage_run(
            FabricationStage.FABRICATION_PACKAGE,
            revision_id=revision_id,
            evidence_mode=EvidenceMode.REAL,
            tool_name="ariad_fabrication_packager",
            tool_version=FABRICATION_PIPELINE_VERSION,
        )
        journey.emit_event(
            package_run.stage_run_id,
            "stage_queued",
            "R4 fabrication package completeness check queued",
        )
        self._transition(journey, package_run.stage_run_id, StageStatus.RUNNING)
        required_roles = (
            "part_spec",
            "cad_parameters",
            "cad_source",
            "exact_geometry",
            "geometry_validation_report",
            "printer_profile",
            "material_profile",
            "process_profile",
            "orientation_profile",
            "slicer_profile",
            "profile_bundle",
            "printability_policy",
            "oriented_geometry",
            "printability_report",
            "slicer_installation",
            "slicer_project",
            "gcode",
            "gcode_preflight",
            "slicer_run_report",
        )
        required_artifacts = [
            self._artifact_by_role(journey, revision_id, role) for role in required_roles
        ]
        for artifact in required_artifacts:
            self._verified_artifact_path(revision_directory, artifact)
        journey.replace_stage_run(
            replace(
                journey.get_stage_run(package_run.stage_run_id),
                input_artifact_ids=tuple(item.artifact_id for item in required_artifacts),
            )
        )
        warning_findings = [
            item
            for item in journey.findings
            if item.revision_id == revision_id
            and item.severity is FindingSeverity.WARNING
            and not item.resolved
        ]
        package_directory = revision_directory / "fabrication"
        package_directory.mkdir(parents=True, exist_ok=False)
        report_path = package_directory / "package.json"
        report = {
            "schema_version": "1.0.0",
            "classification": "printer_independent_fabrication_package",
            "status": "slicer_verified_with_physical_unknowns"
            if warning_findings
            else "slicer_verified",
            "evidence_level": "R4",
            "job_id": journey.job.job_id,
            "revision_id": revision_id,
            "profile_ids": dict(printability.profile_ids),
            "slicer": slicing.installation.to_dict(),
            "gcode_summary": slicing.summary.to_dict(),
            "preflight": slicing.preflight.to_dict(),
            "slicer_warnings": list(slicing.slicer_warnings),
            "required_artifacts": [
                {
                    "artifact_id": item.artifact_id,
                    "role": item.role,
                    "path": item.path,
                    "size_bytes": item.size_bytes,
                    "checksum_sha256": item.checksum_sha256,
                }
                for item in required_artifacts
            ],
            "unresolved_warning_findings": [item.to_dict() for item in warning_findings],
            "hardware": {
                "printer_selected": False,
                "printer_connected": False,
                "gcode_uploaded": False,
                "print_started": False,
            },
            "allowed_claim": "Slicer-verified for this recorded generic profile (R4).",
            "claim_boundary": (
                "The exact oriented CAD passed the recorded deterministic R3 rules and a real "
                "PrusaSlicer process produced G-code that passed disconnected preflight. No "
                "printer was selected, connected, heated, moved, or physically tested; adhesion, "
                "fit, strength, accuracy, weathering, food safety, and print success remain unknown."
            ),
            "manifest_note": (
                "manifest.json and journey.json are generated package indexes and are excluded "
                "from their own checksummed artifact graph to avoid self-reference."
            ),
        }
        self._write_json_new(report_path, report)
        package_artifact = self._record_file(
            journey,
            package_run.stage_run_id,
            revision_id,
            revision_directory,
            report_path,
            role="fabrication_package_report",
            media_type="application/json",
            producer="ariad_fabrication_packager",
            producer_version=FABRICATION_PIPELINE_VERSION,
            parent_artifact_ids=tuple(item.artifact_id for item in required_artifacts),
        )
        package_status = (
            StageStatus.PASSED_WITH_WARNINGS if warning_findings else StageStatus.PASSED
        )
        self._transition(
            journey,
            package_run.stage_run_id,
            package_status,
            summary=(
                f"R4 package contains {len(required_artifacts)} required evidence artifacts "
                f"plus package report {package_artifact.artifact_id}"
            ),
            evidence_level=EvidenceLevel.R4,
        )
        journey.emit_event(
            package_run.stage_run_id,
            "fabrication_package_completed",
            "Printer-independent R4 fabrication package completed",
            data={
                "evidence_level": "R4",
                "required_artifact_count": len(required_artifacts),
                "warning_count": len(warning_findings),
                "physical_validation": False,
            },
        )
        journey.update_status("completed")
        return report_path

    @staticmethod
    def _record_file(
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
        path = path.resolve()
        if not path.is_relative_to(revision_directory) or not path.is_file():
            raise ValueError(f"artifact path is outside the revision or missing: {path}")
        if any(item.role == role and item.revision_id == revision_id for item in journey.artifacts):
            raise ValueError(f"duplicate artifact role in revision: {role}")
        artifact = Artifact(
            job_id=journey.job.job_id,
            revision_id=revision_id,
            stage_run_id=stage_run_id,
            role=role,
            path=path.relative_to(revision_directory).as_posix(),
            media_type=media_type,
            checksum_sha256=_sha256(path),
            producer=producer,
            producer_version=producer_version,
            evidence_mode=EvidenceMode.REAL,
            parent_artifact_ids=parent_artifact_ids,
            size_bytes=path.stat().st_size,
        )
        journey.add_artifact(artifact)
        return artifact

    @staticmethod
    def _fail_stage(
        journey: FabricationJourney,
        stage_run_id: str,
        revision_id: str,
        *,
        code: str,
        title: str,
        message: str,
    ) -> None:
        journey.add_finding(
            Finding(
                job_id=journey.job.job_id,
                revision_id=revision_id,
                stage_run_id=stage_run_id,
                code=code,
                title=title,
                severity=FindingSeverity.ERROR,
                evidence=message,
                remediation="Inspect the recorded artifacts and create a new immutable revision.",
            )
        )
        GoldenPartFabricationPipeline._transition(
            journey,
            stage_run_id,
            StageStatus.FAILED,
            summary=title,
            error_message=message,
        )
        journey.emit_event(
            stage_run_id,
            "stage_failed",
            title,
            data={"error": message},
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
    def _write_json_new(path: Path, value: Mapping[str, Any]) -> None:
        if path.exists():
            raise FileExistsError(f"immutable JSON artifact already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

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
        printability_report: PrintabilityReport | None,
        slice_outcome: SliceOutcome | None,
        package_report_path: Path | None,
    ) -> GoldenPartFabricationOutcome:
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
        return GoldenPartFabricationOutcome(
            journey=journey,
            printability_report=printability_report,
            slice_outcome=slice_outcome,
            revision_directory=revision_directory,
            journey_path=journey_path,
            manifest_path=manifest_path,
            package_report_path=package_report_path,
        )
