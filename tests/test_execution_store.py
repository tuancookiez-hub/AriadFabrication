from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from ariad_fabrication.execution import (
    AdmissionDecision,
    CadRuntimeSnapshot,
    ExecutionControlStore,
    ExecutionEventType,
    ExecutionFailure,
    ExecutionFailureCode,
    ExecutionNotFoundError,
    ExecutionPlan,
    ExecutionRequest,
    ExecutionStatus,
    ExecutionStoreIntegrityError,
    ExecutionTarget,
    ExecutionTransitionError,
    HostRuntimeSnapshot,
    MAX_EVENT_JSON_BYTES,
    R4ProfileSnapshot,
    SlicerSnapshot,
    STORE_SCHEMA_VERSION,
)


HASHES = tuple(f"{number:x}" * 64 for number in range(1, 10))


def execution_request(
    key: str,
    target: ExecutionTarget = ExecutionTarget.GOLDEN_PART_R2,
) -> ExecutionRequest:
    return ExecutionRequest(idempotency_key=key, target=target)


def cad_runtime() -> CadRuntimeSnapshot:
    return CadRuntimeSnapshot(
        python_version="3.11.15",
        python_executable_sha256=HASHES[0],
        cad_runtime_manifest_sha256=HASHES[1],
        python_runtime_sha256=HASHES[2],
        dependency_environment_sha256=HASHES[3],
        host=HostRuntimeSnapshot(
            system="Windows",
            release="11",
            version="10.0.26100",
            machine="AMD64",
        ),
    )


def r2_plan() -> ExecutionPlan:
    return ExecutionPlan(
        target=ExecutionTarget.GOLDEN_PART_R2,
        part_spec_sha256=HASHES[1],
        geometry_expectations_sha256=HASHES[2],
        cad_source_sha256=HASHES[3],
        dependency_lock_sha256=HASHES[4],
        application_bundle_sha256=HASHES[5],
        cad_runtime=cad_runtime(),
    )


def r4_plan() -> ExecutionPlan:
    return ExecutionPlan(
        target=ExecutionTarget.GOLDEN_PART_R4,
        part_spec_sha256=HASHES[1],
        geometry_expectations_sha256=HASHES[2],
        cad_source_sha256=HASHES[3],
        dependency_lock_sha256=HASHES[4],
        application_bundle_sha256=HASHES[5],
        cad_runtime=cad_runtime(),
        printability_validator_version="1.0.0",
        fabrication_pipeline_version="1.0.0",
        printability_expectations_sha256=HASHES[5],
        profiles=R4ProfileSnapshot(
            printer_profile_sha256=HASHES[0],
            material_profile_sha256=HASHES[1],
            process_profile_sha256=HASHES[2],
            orientation_sha256=HASHES[3],
            slicer_config_sha256=HASHES[4],
        ),
        slicer=SlicerSnapshot(
            executable_sha256=HASHES[5],
            portable_archive_sha256=HASHES[6],
            installation_manifest_sha256=HASHES[7],
            installation_tree_sha256=HASHES[8],
        ),
    )


class ExecutionControlStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "execution-control.sqlite3"
        self.store = ExecutionControlStore(self.path)

    def tearDown(self):
        self.temporary.cleanup()

    def admit_r2(self, key: str, *, second: int = 0):
        return self.store.admit(
            execution_request(key),
            r2_plan(),
            accepted_at=f"2026-07-16T00:00:{second:02d}+00:00",
        )

    def test_admission_is_idempotent_bounded_and_survives_reopen(self):
        first = self.admit_r2("stable-key")

        self.assertEqual(first.decision, AdmissionDecision.ACCEPT)
        self.assertTrue(first.accepted)
        self.assertEqual(first.snapshot.record.accepted_sequence, 1)
        self.assertEqual(len(first.snapshot.events), 1)
        self.assertFalse(first.snapshot.record.hardware_actions)

        replay = self.store.admit(
            execution_request("stable-key"),
            r4_plan(),
            accepted_at="2026-07-16T00:00:01+00:00",
        )
        self.assertEqual(replay.decision, AdmissionDecision.IDEMPOTENT_REPLAY)
        self.assertEqual(replay.execution_id, first.execution_id)
        self.assertEqual(replay.snapshot.record.plan.target, ExecutionTarget.GOLDEN_PART_R2)

        conflict = self.store.admit(
            execution_request("stable-key", ExecutionTarget.GOLDEN_PART_R4),
            r4_plan(),
            accepted_at="2026-07-16T00:00:01+00:00",
        )
        self.assertEqual(conflict.decision, AdmissionDecision.IDEMPOTENCY_CONFLICT)
        self.assertEqual(conflict.execution_id, first.execution_id)

        for index in range(2, 5):
            accepted = self.admit_r2(f"queue-{index}", second=index)
            self.assertEqual(accepted.snapshot.record.accepted_sequence, index)
        full = self.admit_r2("queue-overflow", second=5)
        self.assertEqual(full.decision, AdmissionDecision.QUEUE_FULL)
        self.assertIsNone(full.snapshot)

        reopened = ExecutionControlStore(self.path)
        replayed = reopened.get(first.execution_id)
        self.assertEqual(replayed, first.snapshot)
        self.assertEqual(
            [record.accepted_sequence for record in reopened.list_records()],
            [4, 3, 2, 1],
        )

    def test_fifo_lifecycle_fencing_and_event_projection(self):
        first = self.admit_r2("first")
        second = self.admit_r2("second")

        active = self.store.start_next(
            runner_instance_id="runner_primary",
            at="2026-07-16T00:00:01+00:00",
        )
        self.assertEqual(active.record.execution_id, first.execution_id)
        self.assertEqual(active.record.lease.generation, 1)
        self.assertIsNone(
            self.store.start_next(
                runner_instance_id="runner_other",
                at="2026-07-16T00:00:02+00:00",
            )
        )

        active = self.store.bind_identity(
            first.execution_id,
            job_id="job_first",
            revision_id="rev_first",
            runner_instance_id="runner_primary",
            generation=1,
            at="2026-07-16T00:00:02+00:00",
        )
        active = self.store.append_stage_snapshot(
            first.execution_id,
            runner_instance_id="runner_primary",
            generation=1,
            at="2026-07-16T00:00:03+00:00",
            message="Design stage snapshot persisted",
            data={"stage": "design", "artifact_count": 3},
        )
        active = self.store.renew_lease(
            first.execution_id,
            runner_instance_id="runner_primary",
            generation=1,
            at="2026-07-16T00:00:10+00:00",
        )
        self.assertEqual(active.record.lease.expires_at, "2026-07-16T00:00:40+00:00")
        self.assertEqual(len(active.events), 4)

        completed = self.store.finish(
            first.execution_id,
            ExecutionStatus.SUCCEEDED,
            runner_instance_id="runner_primary",
            generation=1,
            at="2026-07-16T00:00:20+00:00",
        )
        self.assertEqual(completed.record.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(
            [event.event_type for event in completed.events],
            [
                ExecutionEventType.REQUEST_ACCEPTED,
                ExecutionEventType.EXECUTION_STARTED,
                ExecutionEventType.EXECUTION_IDENTITY_BOUND,
                ExecutionEventType.STAGE_SNAPSHOT_PERSISTED,
                ExecutionEventType.EXECUTION_SUCCEEDED,
            ],
        )
        self.assertEqual(
            [event.sequence for event in self.store.events_after(first.execution_id, after_sequence=2)],
            [3, 4, 5],
        )

        next_active = self.store.start_next(
            runner_instance_id="runner_primary",
            at="2026-07-16T00:00:21+00:00",
        )
        self.assertEqual(next_active.record.execution_id, second.execution_id)
        self.assertEqual(next_active.record.lease.generation, 2)

    def test_queued_and_active_cancellation_are_atomic_and_idempotent(self):
        queued = self.admit_r2("queued-cancel")
        cancelled = self.store.cancel(
            queued.execution_id,
            at="2026-07-16T00:00:01+00:00",
        )
        self.assertEqual(cancelled.record.status, ExecutionStatus.CANCELLED)
        self.assertEqual(
            [event.event_type for event in cancelled.events],
            [
                ExecutionEventType.REQUEST_ACCEPTED,
                ExecutionEventType.CANCELLATION_REQUESTED,
                ExecutionEventType.EXECUTION_CANCELLED,
            ],
        )
        repeated = self.store.cancel(
            queued.execution_id,
            at="2026-07-16T00:00:02+00:00",
        )
        self.assertEqual(repeated, cancelled)

        active_admission = self.admit_r2("active-cancel", second=2)
        active = self.store.start_next(
            runner_instance_id="runner_cancel",
            at="2026-07-16T00:00:03+00:00",
        )
        self.assertEqual(active.record.execution_id, active_admission.execution_id)
        requested = self.store.cancel(
            active.record.execution_id,
            at="2026-07-16T00:00:04+00:00",
        )
        self.assertEqual(
            requested.record.status, ExecutionStatus.CANCELLATION_REQUESTED
        )
        with self.assertRaisesRegex(ExecutionTransitionError, "cannot transition"):
            self.store.finish(
                active.record.execution_id,
                ExecutionStatus.SUCCEEDED,
                runner_instance_id="runner_cancel",
                generation=1,
                at="2026-07-16T00:00:05+00:00",
            )
        self.assertEqual(
            self.store.get(active.record.execution_id).record.status,
            ExecutionStatus.CANCELLATION_REQUESTED,
        )
        terminal = self.store.finish(
            active.record.execution_id,
            ExecutionStatus.CANCELLED,
            runner_instance_id="runner_cancel",
            generation=1,
            at="2026-07-16T00:00:05+00:00",
        )
        self.assertEqual(terminal.record.status, ExecutionStatus.CANCELLED)

    def test_expired_lease_interrupts_without_resume_and_unblocks_fifo(self):
        first = self.admit_r2("stale-first")
        second = self.admit_r2("stale-second")
        active = self.store.start_next(
            runner_instance_id="runner_stale",
            at="2026-07-16T00:00:01+00:00",
        )

        self.assertEqual(
            self.store.reconcile_stale(observed_at="2026-07-16T00:00:30+00:00"),
            (),
        )
        interrupted = self.store.reconcile_stale(
            observed_at="2026-07-16T00:00:31+00:00"
        )
        self.assertEqual(len(interrupted), 1)
        self.assertEqual(interrupted[0].record.execution_id, first.execution_id)
        self.assertEqual(interrupted[0].record.status, ExecutionStatus.INTERRUPTED)
        self.assertFalse(interrupted[0].record.policy.automatic_resume)

        with self.assertRaisesRegex(ExecutionTransitionError, "terminal"):
            self.store.finish(
                active.record.execution_id,
                ExecutionStatus.SUCCEEDED,
                runner_instance_id="runner_stale",
                generation=1,
                at="2026-07-16T00:00:32+00:00",
            )
        next_active = self.store.start_next(
            runner_instance_id="runner_new",
            at="2026-07-16T00:00:32+00:00",
        )
        self.assertEqual(next_active.record.execution_id, second.execution_id)
        self.assertEqual(next_active.record.lease.generation, 2)

    def test_cancellation_timeout_cannot_skip_the_grace_period(self):
        admission = self.admit_r2("cancel-timeout")
        active = self.store.start_next(
            runner_instance_id="runner_timeout",
            at="2026-07-16T00:00:01+00:00",
        )
        self.store.cancel(admission.execution_id, at="2026-07-16T00:00:05+00:00")
        failure = ExecutionFailure(
            code=ExecutionFailureCode.CANCELLATION_TIMEOUT,
            message="Process tree did not stop during the cancellation grace period",
            retryable=False,
        )
        with self.assertRaisesRegex(ExecutionTransitionError, "grace ends"):
            self.store.finish(
                active.record.execution_id,
                ExecutionStatus.FAILED,
                runner_instance_id="runner_timeout",
                generation=1,
                at="2026-07-16T00:00:14+00:00",
                failure=failure,
            )
        failed = self.store.finish(
            active.record.execution_id,
            ExecutionStatus.FAILED,
            runner_instance_id="runner_timeout",
            generation=1,
            at="2026-07-16T00:00:15+00:00",
            failure=failure,
        )
        self.assertEqual(failed.record.failure.code, ExecutionFailureCode.CANCELLATION_TIMEOUT)
        self.assertEqual(failed.events[-1].event_type, ExecutionEventType.EXECUTION_FAILED)

    def test_concurrent_same_key_admission_creates_one_execution(self):
        request = execution_request("concurrent-key")
        plan = r2_plan()

        def admit_once(_index: int):
            return self.store.admit(
                request,
                plan,
                accepted_at="2026-07-16T00:00:00+00:00",
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = tuple(executor.map(admit_once, range(8)))

        decisions = [result.decision for result in results]
        self.assertEqual(decisions.count(AdmissionDecision.ACCEPT), 1)
        self.assertEqual(decisions.count(AdmissionDecision.IDEMPOTENT_REPLAY), 7)
        self.assertEqual(len({result.execution_id for result in results}), 1)
        records = self.store.list_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(len(self.store.get(records[0].execution_id).events), 1)

    def test_concurrent_store_open_is_idempotent(self):
        concurrent_path = Path(self.temporary.name) / "concurrent-open.sqlite3"

        def open_store(_index: int):
            return ExecutionControlStore(concurrent_path)

        with ThreadPoolExecutor(max_workers=4) as executor:
            stores = tuple(executor.map(open_store, range(4)))

        self.assertEqual(len(stores), 4)
        self.assertTrue(all(store.path == concurrent_path for store in stores))

    def test_concurrent_cancel_and_success_linearize_to_one_legal_outcome(self):
        admission = self.admit_r2("terminal-race")
        active = self.store.start_next(
            runner_instance_id="runner_race",
            at="2026-07-16T00:00:01+00:00",
        )
        self.store.bind_identity(
            admission.execution_id,
            job_id="job_race",
            revision_id="rev_race",
            runner_instance_id="runner_race",
            generation=active.record.lease.generation,
            at="2026-07-16T00:00:02+00:00",
        )
        barrier = Barrier(2)

        def cancel_once():
            barrier.wait()
            return self.store.cancel(
                admission.execution_id,
                at="2026-07-16T00:00:05+00:00",
            ).record.status

        def succeed_once():
            barrier.wait()
            try:
                return self.store.finish(
                    admission.execution_id,
                    ExecutionStatus.SUCCEEDED,
                    runner_instance_id="runner_race",
                    generation=active.record.lease.generation,
                    at="2026-07-16T00:00:05+00:00",
                ).record.status
            except ExecutionTransitionError:
                return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            cancel_future = executor.submit(cancel_once)
            finish_future = executor.submit(succeed_once)
            cancel_result = cancel_future.result()
            finish_result = finish_future.result()

        final = self.store.get(admission.execution_id)
        if final.record.status is ExecutionStatus.SUCCEEDED:
            self.assertEqual(cancel_result, ExecutionStatus.SUCCEEDED)
            self.assertEqual(finish_result, ExecutionStatus.SUCCEEDED)
            self.assertEqual(
                final.events[-1].event_type,
                ExecutionEventType.EXECUTION_SUCCEEDED,
            )
        else:
            self.assertEqual(
                final.record.status,
                ExecutionStatus.CANCELLATION_REQUESTED,
            )
            self.assertEqual(cancel_result, ExecutionStatus.CANCELLATION_REQUESTED)
            self.assertEqual(finish_result, "rejected")
            self.assertEqual(
                final.events[-1].event_type,
                ExecutionEventType.CANCELLATION_REQUESTED,
            )

    def test_record_listing_is_bounded_and_does_not_load_event_histories(self):
        admission = self.admit_r2("record-list")
        records = self.store.list_records(limit=1)

        self.assertEqual(records, (admission.snapshot.record,))
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            self.store.list_records(limit=True)
        with self.assertRaisesRegex(ValueError, "cannot exceed 100"):
            self.store.list_records(limit=101)

    def test_backdated_update_and_event_log_limit_roll_back(self):
        admission = self.admit_r2("bounded-log")
        active = self.store.start_next(
            runner_instance_id="runner_bounds",
            at="2026-07-16T00:00:01+00:00",
        )
        self.store.bind_identity(
            admission.execution_id,
            job_id="job_bounds",
            revision_id="rev_bounds",
            runner_instance_id="runner_bounds",
            generation=active.record.lease.generation,
            at="2026-07-16T00:00:02+00:00",
        )
        baseline = self.store.append_stage_snapshot(
            admission.execution_id,
            runner_instance_id="runner_bounds",
            generation=active.record.lease.generation,
            at="2026-07-16T00:00:10+00:00",
            message="Latest persisted stage",
            data={"stage": "design"},
        )

        with self.assertRaisesRegex(ExecutionStoreIntegrityError, "moved backwards"):
            self.store.renew_lease(
                admission.execution_id,
                runner_instance_id="runner_bounds",
                generation=active.record.lease.generation,
                at="2026-07-16T00:00:05+00:00",
            )
        self.assertEqual(self.store.get(admission.execution_id), baseline)

        with closing(sqlite3.connect(self.path)) as connection:
            current_bytes = int(
                connection.execute(
                    """
                    SELECT SUM(length(CAST(event_json AS BLOB)))
                    FROM execution_events WHERE execution_id = ?
                    """,
                    (admission.execution_id,),
                ).fetchone()[0]
            )
        with patch(
            "ariad_fabrication.execution.store.MAX_EVENT_LOG_JSON_BYTES",
            current_bytes + 1,
        ):
            with self.assertRaisesRegex(ExecutionStoreIntegrityError, "byte limit"):
                self.store.append_stage_snapshot(
                    admission.execution_id,
                    runner_instance_id="runner_bounds",
                    generation=active.record.lease.generation,
                    at="2026-07-16T00:00:11+00:00",
                    message="This event cannot fit",
                    data={"stage": "design"},
                )
        self.assertEqual(self.store.get(admission.execution_id), baseline)

        with patch(
            "ariad_fabrication.execution.store.MAX_EVENT_LOG_JSON_BYTES",
            current_bytes + MAX_EVENT_JSON_BYTES,
        ):
            completed = self.store.finish(
                admission.execution_id,
                ExecutionStatus.SUCCEEDED,
                runner_instance_id="runner_bounds",
                generation=active.record.lease.generation,
                at="2026-07-16T00:00:12+00:00",
            )
        self.assertEqual(completed.record.status, ExecutionStatus.SUCCEEDED)

    def test_plan_index_and_schema_sql_drift_fail_closed(self):
        admission = self.admit_r2("plan-integrity")
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                "SELECT record_json FROM executions WHERE execution_id = ?",
                (admission.execution_id,),
            ).fetchone()
            value = json.loads(row[0])
            value["plan"]["cad_source_sha256"] = HASHES[8]
            changed = json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            connection.execute(
                """
                UPDATE executions SET record_json = ?, record_sha256 = ?
                WHERE execution_id = ?
                """,
                (
                    changed,
                    sha256(changed.encode("utf-8")).hexdigest(),
                    admission.execution_id,
                ),
            )
            connection.commit()
        with self.assertRaisesRegex(ExecutionStoreIntegrityError, "plan_sha256"):
            self.store.get(admission.execution_id)

        schema_path = Path(self.temporary.name) / "schema-drift.sqlite3"
        ExecutionControlStore(schema_path)
        with closing(sqlite3.connect(schema_path)) as connection:
            connection.execute("DROP TRIGGER executions_no_delete")
            connection.execute(
                """
                CREATE TRIGGER executions_no_delete
                BEFORE DELETE ON executions
                BEGIN
                    SELECT RAISE(ABORT, 'different guard');
                END
                """
            )
            connection.commit()
        with self.assertRaisesRegex(ExecutionStoreIntegrityError, "schema SQL drifted"):
            ExecutionControlStore(schema_path)

        foreign_path = Path(self.temporary.name) / "foreign.sqlite3"
        with closing(sqlite3.connect(foreign_path)) as connection:
            connection.execute("PRAGMA application_id = 123")
        with self.assertRaisesRegex(ExecutionStoreIntegrityError, "another application"):
            ExecutionControlStore(foreign_path)

    def test_store_schema_two_rejects_legacy_schema_one_without_migration(self):
        self.assertEqual(STORE_SCHEMA_VERSION, 2)
        legacy_path = Path(self.temporary.name) / "legacy-schema-one.sqlite3"
        ExecutionControlStore(legacy_path)
        with closing(sqlite3.connect(legacy_path)) as connection:
            connection.execute("PRAGMA user_version = 1")
        with self.assertRaisesRegex(
            ExecutionStoreIntegrityError, "unsupported execution store schema version 1"
        ):
            ExecutionControlStore(legacy_path)

    def test_terminal_event_semantic_drift_fails_closed(self):
        admission = self.admit_r2("terminal-event-integrity")
        active = self.store.start_next(
            runner_instance_id="runner_terminal",
            at="2026-07-16T00:00:01+00:00",
        )
        self.store.bind_identity(
            admission.execution_id,
            job_id="job_terminal",
            revision_id="rev_terminal",
            runner_instance_id="runner_terminal",
            generation=active.record.lease.generation,
            at="2026-07-16T00:00:02+00:00",
        )
        completed = self.store.finish(
            admission.execution_id,
            ExecutionStatus.SUCCEEDED,
            runner_instance_id="runner_terminal",
            generation=active.record.lease.generation,
            at="2026-07-16T00:00:03+00:00",
        )
        terminal = completed.events[-1].to_dict()
        terminal["data"]["target"] = ExecutionTarget.GOLDEN_PART_R4.value
        changed = json.dumps(
            terminal,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("DROP TRIGGER execution_events_no_update")
            connection.execute(
                """
                UPDATE execution_events SET event_json = ?, event_sha256 = ?
                WHERE execution_id = ? AND sequence = ?
                """,
                (
                    changed,
                    sha256(changed.encode("utf-8")).hexdigest(),
                    admission.execution_id,
                    terminal["sequence"],
                ),
            )
            connection.execute(
                """
                CREATE TRIGGER execution_events_no_update
                BEFORE UPDATE ON execution_events
                BEGIN
                    SELECT RAISE(ABORT, 'execution events are append-only');
                END
                """
            )
            connection.commit()
        with self.assertRaisesRegex(ExecutionStoreIntegrityError, "terminal.*data"):
            self.store.get(admission.execution_id)

    def test_counter_guard_and_live_schema_revalidation_fail_closed(self):
        self.admit_r2("counter-guard")
        with closing(sqlite3.connect(self.path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    UPDATE execution_counters
                    SET next_accepted_sequence = next_accepted_sequence
                    WHERE singleton = 1
                    """
                )

            connection.execute("DROP TRIGGER executions_queue_limit")
            connection.commit()
        with self.assertRaisesRegex(
            ExecutionStoreIntegrityError, "unexpected trigger objects"
        ):
            self.store.get("exec_missing")

    def test_event_append_guard_and_lifecycle_replay_fail_closed(self):
        admission = self.admit_r2("event-integrity")
        duplicate = admission.snapshot.events[0].to_dict()
        duplicate["event_id"] = "exevt_duplicate_origin"

        with closing(sqlite3.connect(self.path)) as connection:
            duplicate["sequence"] = 3
            gap_json = json.dumps(
                duplicate,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO execution_events(
                        execution_id, sequence, event_id, event_type, status,
                        occurred_at, event_json, event_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        admission.execution_id,
                        3,
                        duplicate["event_id"],
                        duplicate["event_type"],
                        duplicate["status"],
                        duplicate["occurred_at"],
                        gap_json,
                        sha256(gap_json.encode("utf-8")).hexdigest(),
                    ),
                )
            connection.rollback()

            duplicate["sequence"] = 2
            repeated_json = json.dumps(
                duplicate,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            connection.execute(
                """
                INSERT INTO execution_events(
                    execution_id, sequence, event_id, event_type, status,
                    occurred_at, event_json, event_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    admission.execution_id,
                    2,
                    duplicate["event_id"],
                    duplicate["event_type"],
                    duplicate["status"],
                    duplicate["occurred_at"],
                    repeated_json,
                    sha256(repeated_json.encode("utf-8")).hexdigest(),
                ),
            )
            connection.commit()
        with self.assertRaisesRegex(ExecutionStoreIntegrityError, "origin event"):
            self.store.get(admission.execution_id)

    def test_database_guards_and_checksum_replay_fail_closed(self):
        admission = self.admit_r2("integrity")
        for index in range(1, 4):
            self.admit_r2(f"integrity-queue-{index}", second=index)
        with closing(sqlite3.connect(self.path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM executions WHERE execution_id = ?",
                    (admission.execution_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE execution_events SET status = status WHERE execution_id = ?",
                    (admission.execution_id,),
                )
            orphan_json = "{}"
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO execution_events(
                        execution_id, sequence, event_id, event_type, status,
                        occurred_at, event_json, event_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "exec_missing_owner",
                        1,
                        "exevt_missing_owner",
                        "request_accepted",
                        "queued",
                        "2026-07-16T00:00:00+00:00",
                        orphan_json,
                        sha256(orphan_json.encode("utf-8")).hexdigest(),
                    ),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    UPDATE executions SET updated_at = '2025-01-01T00:00:00+00:00'
                    WHERE execution_id = ?
                    """,
                    (admission.execution_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO executions(
                        execution_id, idempotency_key, request_sha256, plan_sha256,
                        accepted_sequence, status, accepted_at, updated_at,
                        job_id, revision_id, lease_runner_instance_id,
                        lease_generation, lease_heartbeat_at, lease_expires_at,
                        record_json, record_sha256
                    )
                    SELECT
                        'exec_raw_overflow', 'raw-overflow', request_sha256,
                        plan_sha256, 99, status, accepted_at, updated_at,
                        job_id, revision_id, lease_runner_instance_id,
                        lease_generation, lease_heartbeat_at, lease_expires_at,
                        record_json, record_sha256
                    FROM executions WHERE execution_id = ?
                    """,
                    (admission.execution_id,),
                )
            connection.execute(
                """
                UPDATE executions SET record_json = record_json || ' '
                WHERE execution_id = ?
                """,
                (admission.execution_id,),
            )
            connection.commit()

        with self.assertRaisesRegex(ExecutionStoreIntegrityError, "checksum"):
            self.store.get(admission.execution_id)

        metadata_path = Path(self.temporary.name) / "metadata-drift.sqlite3"
        ExecutionControlStore(metadata_path)
        with closing(sqlite3.connect(metadata_path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO execution_control_metadata(key, value)
                    VALUES ('unexpected', 'other')
                    """
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    UPDATE execution_control_metadata SET value = 'other'
                    WHERE key = 'policy_version'
                    """
                )
            connection.rollback()
            connection.execute("DROP TRIGGER execution_metadata_no_update")
            connection.execute(
                """
                UPDATE execution_control_metadata SET value = 'other'
                WHERE key = 'policy_version'
                """
            )
            connection.commit()
        with self.assertRaisesRegex(ExecutionStoreIntegrityError, "metadata drifted"):
            ExecutionControlStore(metadata_path)

    def test_failed_stage_event_rolls_back_record_touch_and_append(self):
        admission = self.admit_r2("atomic-event")
        active = self.store.start_next(
            runner_instance_id="runner_atomic",
            at="2026-07-16T00:00:01+00:00",
        )
        baseline = self.store.get(active.record.execution_id)

        with self.assertRaisesRegex(ValueError, "requires journey identity"):
            self.store.append_stage_snapshot(
                active.record.execution_id,
                runner_instance_id="runner_atomic",
                generation=1,
                at="2026-07-16T00:00:02+00:00",
                message="Snapshot without identity",
                data={"stage": "design"},
            )
        self.assertEqual(self.store.get(active.record.execution_id), baseline)

        self.store.bind_identity(
            admission.execution_id,
            job_id="job_atomic",
            revision_id="rev_atomic",
            runner_instance_id="runner_atomic",
            generation=1,
            at="2026-07-16T00:00:02+00:00",
        )
        before_invalid_data = self.store.get(admission.execution_id)
        with self.assertRaisesRegex(ValueError, "progress_percent"):
            self.store.append_stage_snapshot(
                admission.execution_id,
                runner_instance_id="runner_atomic",
                generation=1,
                at="2026-07-16T00:00:03+00:00",
                message="Invented progress",
                data={"progress_percent": 50},
            )
        self.assertEqual(self.store.get(admission.execution_id), before_invalid_data)

        with self.assertRaises(ExecutionNotFoundError):
            self.store.get("exec_missing")


if __name__ == "__main__":
    unittest.main()
