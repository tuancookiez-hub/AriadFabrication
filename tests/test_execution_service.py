from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest

from ariad_fabrication.execution import (
    CadRuntimeSnapshot,
    ExecutionControlStore,
    ExecutionEventType,
    ExecutionPlan,
    ExecutionRequest,
    ExecutionStatus,
    ExecutionTarget,
    HostRuntimeSnapshot,
    PersistedJourneyEvidence,
    RegisteredExecutionService,
)


HASHES = tuple(f"{number:x}" * 64 for number in range(1, 7))


def r2_plan() -> ExecutionPlan:
    return ExecutionPlan(
        target=ExecutionTarget.GOLDEN_PART_R2,
        part_spec_sha256=HASHES[0],
        geometry_expectations_sha256=HASHES[1],
        cad_source_sha256=HASHES[2],
        dependency_lock_sha256=HASHES[3],
        application_bundle_sha256=HASHES[4],
        cad_runtime=CadRuntimeSnapshot(
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
        ),
    )


class SuccessfulExecutor:
    def __init__(self, root: Path) -> None:
        self.root = root

    def execute(self, plan, callbacks, cancellation, deadline):
        job_id = "job_service"
        revision_id = "rev_service"
        callbacks.bind_identity(job_id, revision_id)
        self.root.mkdir(parents=True)
        journey = self.root / "journey.json"
        manifest = self.root / "manifest.json"
        journey.write_text(
            json.dumps(
                {
                    "job": {
                        "job_id": job_id,
                        "current_revision_id": revision_id,
                        "status": "geometry_verified",
                    },
                    "revisions": [{"revision_id": revision_id}],
                }
            ),
            encoding="utf-8",
        )
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "job_id": job_id,
                    "revision_id": revision_id,
                    "generated_at": "2026-07-17T00:00:00+00:00",
                    "stage_run_ids": [],
                    "artifacts": [],
                    "findings": [],
                    "decisions": [],
                    "approvals": [],
                }
            ),
            encoding="utf-8",
        )
        evidence = PersistedJourneyEvidence(
            job_id,
            revision_id,
            journey,
            manifest,
            "R2",
            "geometry_verified",
        )
        callbacks.snapshot_persisted(evidence)
        return evidence


class WaitingExecutor:
    def __init__(self) -> None:
        self.started = Event()

    def execute(self, plan, callbacks, cancellation, deadline):
        callbacks.bind_identity("job_cancel", "rev_cancel")
        self.started.set()
        if not cancellation.wait(2):
            raise TimeoutError("test cancellation was not propagated")
        raise RuntimeError("sealed worker stopped at cancelled")


class ExecutionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = ExecutionControlStore(self.root / "control.sqlite3")

    def tearDown(self):
        self.temporary.cleanup()

    def admit(self, key: str):
        return self.store.admit(
            ExecutionRequest(idempotency_key=key, target=ExecutionTarget.GOLDEN_PART_R2),
            r2_plan(),
            accepted_at="2026-07-17T00:00:00+00:00",
        )

    def test_success_publishes_snapshot_only_after_files_exist(self):
        admission = self.admit("service-success")
        service = RegisteredExecutionService(
            self.store,
            SuccessfulExecutor(self.root / "evidence"),
            runner_instance_id="runner_service",
            heartbeat_seconds=0.05,
        )
        result = service.run_next()

        self.assertEqual(result.record.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(result.record.job_id, "job_service")
        event_types = [event.event_type for event in result.events]
        self.assertEqual(
            event_types,
            [
                ExecutionEventType.REQUEST_ACCEPTED,
                ExecutionEventType.EXECUTION_STARTED,
                ExecutionEventType.EXECUTION_IDENTITY_BOUND,
                ExecutionEventType.STAGE_SNAPSHOT_PERSISTED,
                ExecutionEventType.EXECUTION_SUCCEEDED,
            ],
        )
        stage_event = result.events[-2]
        self.assertEqual(stage_event.data["evidence_level"], "R2")
        self.assertEqual(len(stage_event.data["journey_sha256"]), 64)
        self.assertEqual(admission.execution_id, result.record.execution_id)

    def test_active_cancellation_reaches_executor_and_finishes_cancelled(self):
        admission = self.admit("service-cancel")
        executor = WaitingExecutor()
        service = RegisteredExecutionService(
            self.store,
            executor,
            runner_instance_id="runner_cancel_service",
            heartbeat_seconds=0.2,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(service.run_next)
            self.assertTrue(executor.started.wait(1))
            self.store.cancel(admission.execution_id, at=datetime.now(timezone.utc))
            result = future.result(timeout=3)

        self.assertEqual(result.record.status, ExecutionStatus.CANCELLED)
        self.assertIn(
            ExecutionEventType.CANCELLATION_REQUESTED,
            [event.event_type for event in result.events],
        )

    def test_missing_evidence_is_a_stage_failure(self):
        self.admit("service-failure")

        class EmptyExecutor:
            def execute(self, plan, callbacks, cancellation, deadline):
                return None

        result = RegisteredExecutionService(
            self.store,
            EmptyExecutor(),
            runner_instance_id="runner_failure",
            heartbeat_seconds=0.05,
        ).run_next()
        self.assertEqual(result.record.status, ExecutionStatus.FAILED)
        self.assertEqual(result.record.failure.code.value, "stage_failed")


if __name__ == "__main__":
    unittest.main()
