"""Internal coordinator for registered, no-hardware R2/R4 executions.

This module deliberately exposes no HTTP surface.  It connects the durable
control store to the sealed CAD/slicer adapters while preserving the evidence
ordering rule: a control-plane event may reference a Journey snapshot only
after both snapshot files exist and have been hashed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Callable, Protocol

from ..cad import GoldenPartCadPipeline
from ..domain import FabricationJourney, PartSpec, StageStatus
from ..intent_parser import RuleBasedIntentParser
from ..orchestrator import PipelineOrchestrator
from ..slicing import GoldenPartFabricationPipeline, ProfileBundle
from ..schema_validation import ARTIFACT_MANIFEST_SCHEMA, validate_persisted_instance
from .cad_adapter import SealedCadPipelineRunner
from .contracts import (
    ExecutionFailure,
    ExecutionFailureCode,
    ExecutionPlan,
    ExecutionStatus,
    ExecutionTarget,
)
from .registry import TrustedTargetRegistry
from .slicer_adapter import SealedPrusaSlicerAdapter
from .store import ExecutionControlStore, ExecutionSnapshot
from .windows_job import CancellationToken, ExecutionDeadline


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


def _file_digest(path: Path) -> tuple[str, int]:
    if path.stat().st_size > _MAX_SNAPSHOT_BYTES:
        raise ValueError("Journey snapshot exceeds its byte ceiling")
    payload = path.read_bytes()
    return sha256(payload).hexdigest(), len(payload)


def _snapshot_json(path: Path) -> dict:
    if path.stat().st_size > _MAX_SNAPSHOT_BYTES:
        raise ValueError("Journey snapshot exceeds its byte ceiling")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Journey snapshot must contain a JSON object")
    return value


@dataclass(frozen=True)
class PersistedJourneyEvidence:
    job_id: str
    revision_id: str
    journey_path: Path
    manifest_path: Path
    evidence_level: str
    journey_status: str


class ExecutionCallbacks(Protocol):
    def bind_identity(self, job_id: str, revision_id: str) -> None: ...

    def snapshot_persisted(self, evidence: PersistedJourneyEvidence) -> None: ...


class RegisteredPlanExecutor(Protocol):
    def execute(
        self,
        plan: ExecutionPlan,
        callbacks: ExecutionCallbacks,
        cancellation: CancellationToken,
        deadline: ExecutionDeadline,
    ) -> PersistedJourneyEvidence: ...


class GoldenPartPlanExecutor:
    """Execute only a registry-approved Golden Part plan under sealed adapters."""

    def __init__(
        self,
        registry: TrustedTargetRegistry,
        artifact_root: Path,
    ) -> None:
        self.registry = registry
        self.artifact_root = Path(artifact_root).resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _json(path: Path) -> dict:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"registered JSON asset must be an object: {path.name}")
        return value

    @staticmethod
    def _evidence_level(journey: FabricationJourney) -> str:
        levels = [
            run.evidence_level.value
            for run in journey.stage_runs
            if run.status in {StageStatus.PASSED, StageStatus.PASSED_WITH_WARNINGS}
            and run.evidence_level is not None
        ]
        if not levels:
            raise RuntimeError("persisted Journey contains no passed evidence gate")
        return max(levels, key=lambda value: int(value[1:]))

    def execute(
        self,
        plan: ExecutionPlan,
        callbacks: ExecutionCallbacks,
        cancellation: CancellationToken,
        deadline: ExecutionDeadline,
    ) -> PersistedJourneyEvidence:
        resolved = self.registry.reverify(plan)
        spec = PartSpec.from_mapping(self._json(resolved.part_spec_path))
        journey = PipelineOrchestrator(RuleBasedIntentParser()).run_spec(spec)
        revision = journey.current_revision
        if revision is None:
            raise RuntimeError("confirmed Golden Part journey has no revision")
        callbacks.bind_identity(journey.job.job_id, revision.revision_id)

        cad = GoldenPartCadPipeline(
            SealedCadPipelineRunner(
                self.artifact_root,
                self.registry,
                plan,
                cancellation=cancellation,
                execution_deadline=deadline,
            ),
            self._json(resolved.geometry_expectations_path),
        ).run(journey)
        r2 = PersistedJourneyEvidence(
            job_id=journey.job.job_id,
            revision_id=revision.revision_id,
            journey_path=cad.journey_path,
            manifest_path=cad.manifest_path,
            evidence_level=self._evidence_level(journey),
            journey_status=journey.status,
        )
        callbacks.snapshot_persisted(r2)
        if journey.status != "geometry_verified":
            return r2
        if plan.target is ExecutionTarget.GOLDEN_PART_R2:
            return r2

        if resolved.printability_expectations_path is None:
            raise RuntimeError("registered R4 target has no printability expectations")
        paths = resolved.profile_paths
        profiles = ProfileBundle.from_paths(
            printer_path=paths[0],
            material_path=paths[1],
            process_path=paths[2],
            orientation_path=paths[3],
            slicer_config_path=paths[4],
        )
        slicer = SealedPrusaSlicerAdapter(
            self.registry,
            plan,
            cad.revision_directory,
            cancellation=cancellation,
            execution_deadline=deadline,
        )
        fabrication = GoldenPartFabricationPipeline(
            profiles,
            self._json(resolved.printability_expectations_path),
            slicer,
        ).run(cad)
        r4 = PersistedJourneyEvidence(
            job_id=journey.job.job_id,
            revision_id=revision.revision_id,
            journey_path=fabrication.journey_path,
            manifest_path=fabrication.manifest_path,
            evidence_level=self._evidence_level(journey),
            journey_status=journey.status,
        )
        callbacks.snapshot_persisted(r4)
        return r4


class _BoundCallbacks:
    def __init__(
        self,
        store: ExecutionControlStore,
        execution_id: str,
        runner_instance_id: str,
        generation: int,
        now: Callable[[], datetime],
        operation_lock: Lock,
    ) -> None:
        self.store = store
        self.execution_id = execution_id
        self.runner_instance_id = runner_instance_id
        self.generation = generation
        self.now = now
        self.identity: tuple[str, str] | None = None
        self.published_snapshots: set[tuple[str, str, str, str]] = set()
        self._lock = operation_lock

    def bind_identity(self, job_id: str, revision_id: str) -> None:
        with self._lock:
            identity = (job_id, revision_id)
            if self.identity is not None and self.identity != identity:
                raise ValueError("execution identity cannot change")
            self.store.bind_identity(
                self.execution_id,
                job_id=job_id,
                revision_id=revision_id,
                runner_instance_id=self.runner_instance_id,
                generation=self.generation,
                at=self.now(),
            )
            self.identity = identity

    def snapshot_persisted(self, evidence: PersistedJourneyEvidence) -> None:
        with self._lock:
            if self.identity != (evidence.job_id, evidence.revision_id):
                raise ValueError("Journey snapshot identity does not match execution")
            journey = evidence.journey_path.resolve(strict=True)
            manifest = evidence.manifest_path.resolve(strict=True)
            if journey.parent != manifest.parent:
                raise ValueError("Journey and manifest snapshots must share a directory")
            journey_value = _snapshot_json(journey)
            manifest_value = _snapshot_json(manifest)
            validate_persisted_instance(
                manifest_value,
                ARTIFACT_MANIFEST_SCHEMA,
                record_name="execution artifact manifest",
            )
            job = journey_value.get("job")
            revisions = journey_value.get("revisions")
            if not isinstance(job, dict) or job.get("job_id") != evidence.job_id:
                raise ValueError("Journey snapshot contains the wrong job identity")
            if (
                job.get("current_revision_id") != evidence.revision_id
                or job.get("status") != evidence.journey_status
            ):
                raise ValueError("Journey snapshot contains the wrong revision or status")
            if not isinstance(revisions, list) or not any(
                isinstance(item, dict) and item.get("revision_id") == evidence.revision_id
                for item in revisions
            ):
                raise ValueError("Journey snapshot does not contain the bound revision")
            if (
                manifest_value.get("job_id") != evidence.job_id
                or manifest_value.get("revision_id") != evidence.revision_id
            ):
                raise ValueError("artifact manifest identity does not match the execution")
            journey_digest, journey_size = _file_digest(journey)
            manifest_digest, manifest_size = _file_digest(manifest)
            snapshot_identity = (
                evidence.evidence_level,
                evidence.journey_status,
                journey_digest,
                manifest_digest,
            )
            if snapshot_identity in self.published_snapshots:
                raise ValueError("identical Journey snapshot was already published")
            self.store.append_stage_snapshot(
                self.execution_id,
                runner_instance_id=self.runner_instance_id,
                generation=self.generation,
                at=self.now(),
                message=f"{evidence.evidence_level} Journey snapshot persisted",
                data={
                    "evidence_level": evidence.evidence_level,
                    "journey_status": evidence.journey_status,
                    "journey_sha256": journey_digest,
                    "journey_size_bytes": journey_size,
                    "manifest_sha256": manifest_digest,
                    "manifest_size_bytes": manifest_size,
                },
            )
            self.published_snapshots.add(snapshot_identity)


class RegisteredExecutionService:
    """Run at most one queued plan and durably project its honest outcome."""

    def __init__(
        self,
        store: ExecutionControlStore,
        executor: RegisteredPlanExecutor,
        *,
        runner_instance_id: str,
        now: Callable[[], datetime] = _utc_now,
        heartbeat_seconds: float = 5.0,
    ) -> None:
        if heartbeat_seconds <= 0 or heartbeat_seconds >= 30:
            raise ValueError("heartbeat_seconds must be between zero and the lease duration")
        self.store = store
        self.executor = executor
        self.runner_instance_id = runner_instance_id
        self.now = now
        self.heartbeat_seconds = float(heartbeat_seconds)

    def run_next(self) -> ExecutionSnapshot | None:
        active = self.store.start_next(
            runner_instance_id=self.runner_instance_id,
            at=self.now(),
        )
        if active is None:
            return None
        lease = active.record.lease
        if lease is None:  # pragma: no cover - guaranteed by store contract
            raise RuntimeError("started execution has no lease")
        execution_id = active.record.execution_id
        generation = lease.generation
        cancellation = CancellationToken()
        deadline = ExecutionDeadline.start(active.record.policy.max_wall_seconds)
        stop = Event()
        operation_lock = Lock()
        monitor_errors: list[Exception] = []

        def monitor() -> None:
            while not stop.wait(self.heartbeat_seconds):
                try:
                    with operation_lock:
                        snapshot = self.store.get(execution_id)
                        if snapshot.record.status is ExecutionStatus.CANCELLATION_REQUESTED:
                            cancellation.request()
                        if snapshot.record.status not in {
                            ExecutionStatus.RUNNING,
                            ExecutionStatus.CANCELLATION_REQUESTED,
                        }:
                            return
                        self.store.renew_lease(
                            execution_id,
                            runner_instance_id=self.runner_instance_id,
                            generation=generation,
                            at=self.now(),
                        )
                except Exception as exc:  # fail closed; main thread records the failure
                    monitor_errors.append(exc)
                    cancellation.request()
                    return

        thread = Thread(target=monitor, name=f"ariad-{execution_id}", daemon=True)
        thread.start()
        callbacks = _BoundCallbacks(
            self.store,
            execution_id,
            self.runner_instance_id,
            generation,
            self.now,
            operation_lock,
        )
        evidence: PersistedJourneyEvidence | None = None
        failure: ExecutionFailure | None = None
        try:
            evidence = self.executor.execute(
                active.record.plan,
                callbacks,
                cancellation,
                deadline,
            )
        except Exception as exc:
            failure = ExecutionFailure(
                code=ExecutionFailureCode.INTERNAL_ERROR,
                message=f"{type(exc).__name__}: {exc}"[:512],
                retryable=False,
            )
        finally:
            stop.set()
            thread.join(timeout=max(1.0, self.heartbeat_seconds * 2))

        current = self.store.get(execution_id)
        if monitor_errors:
            failure = ExecutionFailure(
                code=ExecutionFailureCode.PERSISTENCE_FAILED,
                message=f"Lease monitor failed: {type(monitor_errors[0]).__name__}: {monitor_errors[0]}"[
                    :512
                ],
                retryable=False,
            )
        if current.record.status is ExecutionStatus.CANCELLATION_REQUESTED:
            return self.store.finish(
                execution_id,
                ExecutionStatus.CANCELLED,
                runner_instance_id=self.runner_instance_id,
                generation=generation,
                at=self.now(),
            )
        expected = "R4" if active.record.plan.target is ExecutionTarget.GOLDEN_PART_R4 else "R2"
        if failure is None and (
            evidence is None
            or evidence.evidence_level != expected
            or evidence.journey_status != ("completed" if expected == "R4" else "geometry_verified")
        ):
            failure = ExecutionFailure(
                code=ExecutionFailureCode.STAGE_FAILED,
                message=f"Registered {expected} evidence gate did not pass",
                retryable=False,
            )
        return self.store.finish(
            execution_id,
            ExecutionStatus.FAILED if failure else ExecutionStatus.SUCCEEDED,
            runner_instance_id=self.runner_instance_id,
            generation=generation,
            at=self.now(),
            failure=failure,
        )


__all__ = [
    "ExecutionCallbacks",
    "GoldenPartPlanExecutor",
    "PersistedJourneyEvidence",
    "RegisteredExecutionService",
    "RegisteredPlanExecutor",
]
