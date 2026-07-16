from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tomllib
import unittest

from ariad_fabrication.execution import (
    AdmissionDecision,
    CadRuntimeSnapshot,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionFailure,
    ExecutionFailureCode,
    ExecutionLease,
    ExecutionPlan,
    ExecutionRecord,
    ExecutionRequest,
    ExecutionStage,
    ExecutionStatus,
    ExecutionTarget,
    ExecutionTransitionError,
    NO_HARDWARE_RUNNER_POLICY,
    R4ProfileSnapshot,
    RunnerPolicy,
    SlicerSnapshot,
    assess_admission,
    bind_execution_identity,
    interrupt_stale_execution,
    renew_execution_lease,
    request_cancellation,
    start_execution,
    transition_execution,
)
from ariad_fabrication.schema_validation import (
    EXECUTION_EVENT_SCHEMA,
    EXECUTION_RECORD_SCHEMA,
    EXECUTION_REQUEST_SCHEMA,
    PERSISTED_SCHEMA_FILENAMES,
    PersistedSchemaValidationError,
    check_persisted_schema_asset,
)
from ariad_fabrication.cad.golden_part import PROVIDER_ID as ACTUAL_PROVIDER_ID
from ariad_fabrication.cad.worker import WORKER_VERSION as ACTUAL_WORKER_VERSION
from ariad_fabrication.slicing.pipeline import (
    FABRICATION_PIPELINE_VERSION as ACTUAL_FABRICATION_PIPELINE_VERSION,
)
from ariad_fabrication.slicing.printability import (
    VALIDATOR_VERSION as ACTUAL_PRINTABILITY_VALIDATOR_VERSION,
)
from ariad_fabrication.slicing.prusaslicer import (
    ADAPTER_ID as ACTUAL_SLICER_ADAPTER_ID,
    ADAPTER_VERSION as ACTUAL_SLICER_ADAPTER_VERSION,
)


ZERO = "0" * 64
ONE = "1" * 64
TWO = "2" * 64
THREE = "3" * 64
FOUR = "4" * 64
FIVE = "5" * 64
SIX = "6" * 64
SEVEN = "7" * 64
EIGHT = "8" * 64
ROOT = Path(__file__).resolve().parents[1]


def cad_runtime() -> CadRuntimeSnapshot:
    return CadRuntimeSnapshot(
        python_version="3.11.15",
        python_executable_sha256=EIGHT,
    )


def request(
    target: ExecutionTarget = ExecutionTarget.GOLDEN_PART_R2,
    *,
    key: str = "test-request-1",
) -> ExecutionRequest:
    return ExecutionRequest(idempotency_key=key, target=target)


def r2_plan() -> ExecutionPlan:
    return ExecutionPlan(
        target=ExecutionTarget.GOLDEN_PART_R2,
        part_spec_sha256=ZERO,
        geometry_expectations_sha256=ONE,
        cad_source_sha256=TWO,
        dependency_lock_sha256=THREE,
        cad_runtime=cad_runtime(),
    )


def r4_plan() -> ExecutionPlan:
    return ExecutionPlan(
        target=ExecutionTarget.GOLDEN_PART_R4,
        part_spec_sha256=ZERO,
        geometry_expectations_sha256=ONE,
        cad_source_sha256=TWO,
        dependency_lock_sha256=THREE,
        cad_runtime=cad_runtime(),
        printability_validator_version="1.0.0",
        fabrication_pipeline_version="1.0.0",
        printability_expectations_sha256=TWO,
        profiles=R4ProfileSnapshot(
            printer_profile_sha256=THREE,
            material_profile_sha256=FOUR,
            process_profile_sha256=FIVE,
            orientation_sha256=SIX,
            slicer_config_sha256=SEVEN,
        ),
        slicer=SlicerSnapshot(executable_sha256=EIGHT),
    )


def queued_record(
    target: ExecutionTarget = ExecutionTarget.GOLDEN_PART_R2,
    *,
    key: str = "test-request-1",
) -> ExecutionRecord:
    plan = r2_plan() if target is ExecutionTarget.GOLDEN_PART_R2 else r4_plan()
    return ExecutionRecord.queued(
        request(target, key=key),
        plan,
        accepted_sequence=1,
        accepted_at="2026-07-16T00:00:00+00:00",
        execution_id="exec_test",
    )


def lease() -> ExecutionLease:
    return ExecutionLease.acquire(
        "runner_test",
        1,
        at="2026-07-16T00:00:01+00:00",
    )


def running_record() -> ExecutionRecord:
    return start_execution(
        queued_record(),
        lease(),
        at="2026-07-16T00:00:01+00:00",
    )


def bind_identity(
    record: ExecutionRecord,
    *,
    job_id: str = "job_test",
    revision_id: str = "rev_test",
    at: str = "2026-07-16T00:00:02+00:00",
) -> ExecutionRecord:
    return bind_execution_identity(
        record,
        job_id=job_id,
        revision_id=revision_id,
        runner_instance_id="runner_test",
        generation=1,
        at=at,
    )


def finish_execution(
    record: ExecutionRecord,
    target: ExecutionStatus,
    *,
    at: str,
    failure: ExecutionFailure | None = None,
) -> ExecutionRecord:
    return transition_execution(
        record,
        target,
        at=at,
        runner_instance_id="runner_test",
        generation=1,
        failure=failure,
    )


class ExecutionRequestAndPlanTests(unittest.TestCase):
    def test_request_is_closed_canonical_and_hardware_disabled(self):
        value = request().to_dict()
        reordered = {name: value[name] for name in reversed(tuple(value))}

        self.assertEqual(
            ExecutionRequest.from_mapping(reordered).canonical_sha256(),
            request().canonical_sha256(),
        )
        self.assertFalse(value["hardware_actions"])
        self.assertNotIn("path", value)
        self.assertNotIn("profile", value)
        self.assertNotIn("provider", value)

        value["slicer_path"] = "C:/unapproved.exe"
        with self.assertRaises(PersistedSchemaValidationError):
            ExecutionRequest.from_mapping(value)
        with self.assertRaisesRegex(ValueError, "must remain false"):
            ExecutionRequest(
                idempotency_key="unsafe",
                target=ExecutionTarget.GOLDEN_PART_R2,
                hardware_actions=True,
            )

    def test_request_rejects_scalar_coercion_and_non_golden_benchmark(self):
        with self.assertRaisesRegex(ValueError, "must be a string"):
            ExecutionRequest(
                idempotency_key=1,  # type: ignore[arg-type]
                target=ExecutionTarget.GOLDEN_PART_R2,
            )
        with self.assertRaisesRegex(ValueError, "only the frozen Golden Part"):
            ExecutionRequest(
                idempotency_key="other",
                target=ExecutionTarget.GOLDEN_PART_R2,
                benchmark_id="other",
            )

    def test_r2_and_r4_plans_have_disjoint_identity_requirements(self):
        self.assertIsNone(r2_plan().profiles)
        self.assertEqual(r4_plan().slicer.slicer_version, "2.9.6")

        with self.assertRaisesRegex(ValueError, "cannot contain R4"):
            ExecutionPlan(
                target=ExecutionTarget.GOLDEN_PART_R2,
                part_spec_sha256=ZERO,
                geometry_expectations_sha256=ONE,
                cad_source_sha256=TWO,
                dependency_lock_sha256=THREE,
                cad_runtime=cad_runtime(),
                printability_expectations_sha256=TWO,
            )
        with self.assertRaisesRegex(ValueError, "require printability"):
            ExecutionPlan(
                target=ExecutionTarget.GOLDEN_PART_R4,
                part_spec_sha256=ZERO,
                geometry_expectations_sha256=ONE,
                cad_source_sha256=TWO,
                dependency_lock_sha256=THREE,
                cad_runtime=cad_runtime(),
            )
        with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
            SlicerSnapshot(executable_sha256="A" * 64)
        with self.assertRaisesRegex(ValueError, "CPython 3.11"):
            CadRuntimeSnapshot(
                python_version="3.12.0",
                python_executable_sha256=EIGHT,
            )

        plan = r4_plan()
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        cad_dependencies = project["project"]["optional-dependencies"]["cad"]
        self.assertEqual(plan.provider_id, ACTUAL_PROVIDER_ID)
        self.assertEqual(plan.cad_worker_version, ACTUAL_WORKER_VERSION)
        self.assertEqual(
            plan.printability_validator_version,
            ACTUAL_PRINTABILITY_VALIDATOR_VERSION,
        )
        self.assertEqual(
            plan.fabrication_pipeline_version,
            ACTUAL_FABRICATION_PIPELINE_VERSION,
        )
        self.assertEqual(plan.slicer.adapter_id, ACTUAL_SLICER_ADAPTER_ID)
        self.assertEqual(plan.slicer.adapter_version, ACTUAL_SLICER_ADAPTER_VERSION)
        self.assertIn(f"cadquery=={plan.cad_runtime.cadquery_version}", cad_dependencies)
        self.assertIn(f"cadquery-ocp=={plan.cad_runtime.ocp_version}", cad_dependencies)

    def test_policy_is_fixed_and_excludes_network_hardware_and_resume(self):
        policy = NO_HARDWARE_RUNNER_POLICY

        self.assertEqual(policy.max_active_executions, 1)
        self.assertEqual(policy.max_queued_executions, 4)
        self.assertEqual(policy.max_wall_seconds, 900)
        self.assertEqual(policy.max_memory_bytes, 4 * 1024 * 1024 * 1024)
        self.assertFalse(policy.network_access)
        self.assertFalse(policy.hardware_actions)
        self.assertFalse(policy.automatic_resume)
        with self.assertRaisesRegex(ValueError, "must remain"):
            RunnerPolicy(network_access=True)
        with self.assertRaisesRegex(ValueError, "exactly 30 seconds"):
            ExecutionLease(
                runner_instance_id="runner_test",
                generation=1,
                acquired_at="2026-07-16T00:00:01+00:00",
                heartbeat_at="2026-07-16T00:00:01+00:00",
                expires_at="2026-07-16T00:00:32+00:00",
            )

class ExecutionLifecycleTests(unittest.TestCase):
    def test_legal_lifecycle_round_trips_and_terminal_is_immutable(self):
        record = running_record()
        record = bind_identity(record)
        completed = finish_execution(
            record,
            ExecutionStatus.SUCCEEDED,
            at="2026-07-16T00:00:10+00:00",
        )

        self.assertEqual(completed.status, ExecutionStatus.SUCCEEDED)
        self.assertIsNone(completed.lease)
        self.assertFalse(completed.physical_evidence)
        self.assertEqual(ExecutionRecord.from_mapping(completed.to_dict()), completed)
        json.dumps(completed.to_dict())
        with self.assertRaises(ExecutionTransitionError):
            finish_execution(
                completed,
                ExecutionStatus.FAILED,
                at="2026-07-16T00:00:11+00:00",
                failure=ExecutionFailure(
                    ExecutionFailureCode.INTERNAL_ERROR,
                    "late failure",
                    False,
                ),
            )
        with self.assertRaises(FrozenInstanceError):
            completed.status = ExecutionStatus.FAILED

    def test_success_requires_bound_job_and_revision(self):
        with self.assertRaisesRegex(ExecutionTransitionError, "bound journey identity"):
            finish_execution(
                running_record(),
                ExecutionStatus.SUCCEEDED,
                at="2026-07-16T00:00:10+00:00",
            )

    def test_queued_cancellation_prevents_start_and_is_idempotent(self):
        record = queued_record()
        cancelled = request_cancellation(
            record, at="2026-07-16T00:00:01+00:00"
        )

        self.assertEqual(cancelled.status, ExecutionStatus.CANCELLED)
        self.assertIsNone(cancelled.started_at)
        self.assertEqual(cancelled.completed_at, cancelled.cancellation_requested_at)
        self.assertIs(request_cancellation(cancelled, at="2026-07-16T00:00:02Z"), cancelled)
        with self.assertRaisesRegex(ExecutionTransitionError, "only queued"):
            start_execution(
                cancelled,
                lease(),
                at="2026-07-16T00:00:01+00:00",
            )

    def test_cancellation_and_completion_race_has_one_winner(self):
        running = bind_identity(running_record())

        completion_wins = finish_execution(
            running,
            ExecutionStatus.SUCCEEDED,
            at="2026-07-16T00:00:05+00:00",
        )
        self.assertIs(
            request_cancellation(completion_wins, at="2026-07-16T00:00:06+00:00"),
            completion_wins,
        )

        cancellation_wins = request_cancellation(
            running, at="2026-07-16T00:00:05+00:00"
        )
        self.assertEqual(
            cancellation_wins.status, ExecutionStatus.CANCELLATION_REQUESTED
        )
        with self.assertRaisesRegex(ExecutionTransitionError, "cannot transition"):
            finish_execution(
                cancellation_wins,
                ExecutionStatus.SUCCEEDED,
                at="2026-07-16T00:00:06+00:00",
            )
        cancelled = finish_execution(
            cancellation_wins,
            ExecutionStatus.CANCELLED,
            at="2026-07-16T00:00:06+00:00",
        )
        self.assertEqual(cancelled.status, ExecutionStatus.CANCELLED)

    def test_failed_state_requires_structured_non_manufacturing_failure(self):
        with self.assertRaisesRegex(ExecutionTransitionError, "structured failure"):
            finish_execution(
                running_record(),
                ExecutionStatus.FAILED,
                at="2026-07-16T00:00:10+00:00",
            )
        with self.assertRaisesRegex(ValueError, "unsupported failure stage"):
            ExecutionFailure(
                ExecutionFailureCode.STAGE_FAILED,
                "hardware stage is outside scope",
                False,
                stage="manufacturing",  # type: ignore[arg-type]
            )

        failed = finish_execution(
            running_record(),
            ExecutionStatus.FAILED,
            at="2026-07-16T00:00:10+00:00",
            failure=ExecutionFailure(
                ExecutionFailureCode.STAGE_FAILED,
                "geometry validation failed",
                False,
                stage=ExecutionStage.GEOMETRY_VALIDATION,
            ),
        )
        self.assertEqual(failed.failure.stage, ExecutionStage.GEOMETRY_VALIDATION)

        cancellation = request_cancellation(
            running_record(), at="2026-07-16T00:00:05+00:00"
        )
        cancellation_timeout = ExecutionFailure(
            ExecutionFailureCode.CANCELLATION_TIMEOUT,
            "process tree did not stop",
            False,
        )
        with self.assertRaisesRegex(ExecutionTransitionError, "grace ends"):
            finish_execution(
                cancellation,
                ExecutionStatus.FAILED,
                at="2026-07-16T00:00:14+00:00",
                failure=cancellation_timeout,
            )
        timed_out = finish_execution(
            cancellation,
            ExecutionStatus.FAILED,
            at="2026-07-16T00:00:15+00:00",
            failure=cancellation_timeout,
        )
        self.assertEqual(
            timed_out.failure.code, ExecutionFailureCode.CANCELLATION_TIMEOUT
        )

    def test_chronology_and_identity_rebinding_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "cannot precede accepted_at"):
            start_execution(
                queued_record(),
                ExecutionLease.acquire(
                    "runner_test",
                    1,
                    at="2026-07-15T23:59:59+00:00",
                ),
                at="2026-07-15T23:59:59+00:00",
            )

        record = bind_identity(running_record())
        self.assertIs(
            bind_identity(record),
            record,
        )
        with self.assertRaisesRegex(ExecutionTransitionError, "bound differently"):
            bind_identity(
                record,
                job_id="job_other",
                revision_id="rev_other",
            )

        partial_identity = running_record().to_dict()
        partial_identity["job_id"] = "job_test"
        with self.assertRaises(PersistedSchemaValidationError):
            ExecutionRecord.from_mapping(partial_identity)

        mismatched_lease = running_record().to_dict()
        mismatched_lease["lease"]["acquired_at"] = "2026-07-16T00:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "acquired_at must equal started_at"):
            ExecutionRecord.from_mapping(mismatched_lease)


class AdmissionAndLeaseTests(unittest.TestCase):
    def test_idempotent_replay_conflict_and_queue_bound_are_explicit(self):
        existing = queued_record(key="stable-key")

        replay = assess_admission(
            request(key="stable-key"),
            existing=existing,
            active_count=0,
            queued_count=1,
        )
        self.assertEqual(replay.decision, AdmissionDecision.IDEMPOTENT_REPLAY)
        self.assertEqual(replay.execution_id, existing.execution_id)

        conflict = assess_admission(
            request(ExecutionTarget.GOLDEN_PART_R4, key="stable-key"),
            existing=existing,
            active_count=0,
            queued_count=1,
        )
        self.assertEqual(conflict.decision, AdmissionDecision.IDEMPOTENCY_CONFLICT)

        full = assess_admission(
            request(key="new-key"),
            existing=None,
            active_count=1,
            queued_count=4,
        )
        self.assertEqual(full.decision, AdmissionDecision.QUEUE_FULL)
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            assess_admission(
                request(key="other-key"),
                existing=None,
                active_count=False,  # type: ignore[arg-type]
                queued_count=0,
            )
        with self.assertRaisesRegex(ValueError, "queued_count violates"):
            assess_admission(
                request(key="overflow-key"),
                existing=None,
                active_count=0,
                queued_count=5,
            )

    def test_lease_is_fenced_renewable_and_stale_execution_is_not_resumed(self):
        running = running_record()

        renewed = renew_execution_lease(
            running,
            runner_instance_id="runner_test",
            generation=1,
            at="2026-07-16T00:00:20+00:00",
        )
        self.assertEqual(renewed.lease.heartbeat_at, "2026-07-16T00:00:20+00:00")
        self.assertEqual(renewed.lease.expires_at, "2026-07-16T00:00:50+00:00")
        with self.assertRaisesRegex(ExecutionTransitionError, "fencing identity"):
            renew_execution_lease(
                running,
                runner_instance_id="runner_other",
                generation=1,
                at="2026-07-16T00:00:20+00:00",
            )
        with self.assertRaisesRegex(ExecutionTransitionError, "has not expired"):
            interrupt_stale_execution(
                renewed, observed_at="2026-07-16T00:00:49+00:00"
            )

        with self.assertRaisesRegex(ExecutionTransitionError, "has expired"):
            transition_execution(
                bind_identity(running),
                ExecutionStatus.SUCCEEDED,
                at="2026-07-16T00:00:50+00:00",
                runner_instance_id="runner_test",
                generation=1,
            )

        interrupted = interrupt_stale_execution(
            renewed, observed_at="2026-07-16T00:00:50+00:00"
        )
        self.assertEqual(interrupted.status, ExecutionStatus.INTERRUPTED)
        self.assertEqual(
            interrupted.failure.code, ExecutionFailureCode.RUNNER_INTERRUPTED
        )
        self.assertTrue(interrupted.failure.retryable)
        self.assertFalse(interrupted.policy.automatic_resume)
        self.assertIsNone(interrupted.lease)


class ExecutionEventAndSchemaTests(unittest.TestCase):
    def test_event_is_bounded_immutable_schema_valid_and_never_hardware(self):
        event = ExecutionEvent(
            execution_id="exec_test",
            sequence=1,
            event_type=ExecutionEventType.REQUEST_ACCEPTED,
            status=ExecutionStatus.QUEUED,
            occurred_at="2026-07-16T00:00:00Z",
            message="Request accepted",
            data={"queue_position": 1},
            event_id="exevt_test",
        )

        self.assertEqual(ExecutionEvent.from_mapping(event.to_dict()), event)
        self.assertFalse(event.hardware_action)
        with self.assertRaises(TypeError):
            event.data["queue_position"] = 2
        with self.assertRaisesRegex(ValueError, "cannot report"):
            ExecutionEvent(
                execution_id="exec_test",
                sequence=2,
                event_type=ExecutionEventType.EXECUTION_SUCCEEDED,
                status=ExecutionStatus.RUNNING,
                occurred_at="2026-07-16T00:00:01Z",
                message="false success",
            )
        with self.assertRaisesRegex(ValueError, "requires journey identity"):
            ExecutionEvent(
                execution_id="exec_test",
                sequence=2,
                event_type=ExecutionEventType.EXECUTION_SUCCEEDED,
                status=ExecutionStatus.SUCCEEDED,
                occurred_at="2026-07-16T00:00:01Z",
                message="identity-free success",
            )
        with self.assertRaisesRegex(ValueError, "progress_percent"):
            ExecutionEvent(
                execution_id="exec_test",
                sequence=2,
                event_type=ExecutionEventType.EXECUTION_STARTED,
                status=ExecutionStatus.RUNNING,
                occurred_at="2026-07-16T00:00:01Z",
                message="started",
                data={"nested": {"progress_percent": 50}},
            )
        with self.assertRaisesRegex(ValueError, "65536-byte"):
            ExecutionEvent(
                execution_id="exec_test",
                sequence=2,
                event_type=ExecutionEventType.EXECUTION_STARTED,
                status=ExecutionStatus.RUNNING,
                occurred_at="2026-07-16T00:00:01Z",
                message="started",
                data={"log": "x" * (64 * 1024)},
            )

        partial_identity = event.to_dict()
        partial_identity["job_id"] = "job_test"
        with self.assertRaises(PersistedSchemaValidationError):
            ExecutionEvent.from_mapping(partial_identity)

    def test_all_execution_schemas_are_packaged_and_meta_valid(self):
        execution_schemas = {
            EXECUTION_REQUEST_SCHEMA,
            EXECUTION_RECORD_SCHEMA,
            EXECUTION_EVENT_SCHEMA,
        }

        self.assertTrue(execution_schemas <= PERSISTED_SCHEMA_FILENAMES)
        self.assertEqual(len(PERSISTED_SCHEMA_FILENAMES), 22)
        for schema_name in execution_schemas:
            check_persisted_schema_asset(schema_name)


if __name__ == "__main__":
    unittest.main()
