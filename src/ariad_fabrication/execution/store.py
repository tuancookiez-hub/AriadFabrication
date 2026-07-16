"""Transactional SQLite control store for no-hardware executions.

The store implements the frozen execution semantics.  It does not launch a
worker, expose HTTP, stream SSE, inspect repository inputs, or contact hardware.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re
import sqlite3
from time import monotonic, sleep
from typing import Any, Iterator, Mapping

from .contracts import (
    AdmissionDecision,
    EXECUTION_SCHEMA_VERSION,
    ExecutionEvent,
    ExecutionEventType,
    ExecutionFailure,
    ExecutionLease,
    ExecutionPlan,
    ExecutionRecord,
    ExecutionRequest,
    ExecutionStatus,
    NO_HARDWARE_RUNNER_POLICY,
    POLICY_VERSION,
    RunnerPolicy,
    assess_admission,
    bind_execution_identity,
    interrupt_stale_execution,
    renew_execution_lease,
    request_cancellation,
    start_execution,
    transition_execution,
    validate_execution_fence,
)


STORE_SCHEMA_VERSION = 2
STORE_APPLICATION_ID = 0x41524944  # "ARID"
MAX_RECORD_JSON_BYTES = 256 * 1024
MAX_EVENT_JSON_BYTES = 128 * 1024
MAX_EVENT_LOG_JSON_BYTES = 8 * 1024 * 1024
MAX_LIST_EXECUTIONS = 100
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 100_000
_EXECUTION_ID = re.compile(r"^exec_[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_TERMINAL_EVENT = {
    ExecutionStatus.SUCCEEDED: ExecutionEventType.EXECUTION_SUCCEEDED,
    ExecutionStatus.FAILED: ExecutionEventType.EXECUTION_FAILED,
    ExecutionStatus.CANCELLED: ExecutionEventType.EXECUTION_CANCELLED,
    ExecutionStatus.INTERRUPTED: ExecutionEventType.EXECUTION_INTERRUPTED,
}
_TERMINAL_EVENT_TYPES = frozenset(_TERMINAL_EVENT.values())
_TERMINAL_EVENT_RESERVE_BYTES = MAX_EVENT_JSON_BYTES

_DDL = (
    """
    CREATE TABLE execution_control_metadata (
        key TEXT PRIMARY KEY NOT NULL CHECK (
            key IN ('store_schema_version', 'execution_schema_version', 'policy_version')
        ),
        value TEXT NOT NULL CHECK (length(value) BETWEEN 1 AND 128)
    ) STRICT
    """,
    """
    CREATE TABLE execution_counters (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        next_accepted_sequence INTEGER NOT NULL CHECK (next_accepted_sequence >= 1),
        next_lease_generation INTEGER NOT NULL CHECK (next_lease_generation >= 1)
    ) STRICT
    """,
    f"""
    CREATE TABLE executions (
        execution_id TEXT PRIMARY KEY NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE,
        request_sha256 TEXT NOT NULL CHECK (
            length(request_sha256) = 64
            AND request_sha256 NOT GLOB '*[^0-9a-f]*'
        ),
        plan_sha256 TEXT NOT NULL CHECK (
            length(plan_sha256) = 64
            AND plan_sha256 NOT GLOB '*[^0-9a-f]*'
        ),
        accepted_sequence INTEGER NOT NULL UNIQUE CHECK (accepted_sequence >= 1),
        status TEXT NOT NULL CHECK (
            status IN (
                'queued', 'running', 'cancellation_requested', 'succeeded',
                'failed', 'cancelled', 'interrupted'
            )
        ),
        accepted_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        job_id TEXT,
        revision_id TEXT,
        lease_runner_instance_id TEXT,
        lease_generation INTEGER,
        lease_heartbeat_at TEXT,
        lease_expires_at TEXT,
        record_json TEXT NOT NULL CHECK (
            length(CAST(record_json AS BLOB)) <= {MAX_RECORD_JSON_BYTES}
        ),
        record_sha256 TEXT NOT NULL CHECK (
            length(record_sha256) = 64
            AND record_sha256 NOT GLOB '*[^0-9a-f]*'
        ),
        CHECK ((job_id IS NULL) = (revision_id IS NULL)),
        CHECK (
            (
                status IN ('running', 'cancellation_requested')
                AND lease_runner_instance_id IS NOT NULL
                AND lease_generation IS NOT NULL
                AND lease_heartbeat_at IS NOT NULL
                AND lease_expires_at IS NOT NULL
            ) OR (
                status NOT IN ('running', 'cancellation_requested')
                AND lease_runner_instance_id IS NULL
                AND lease_generation IS NULL
                AND lease_heartbeat_at IS NULL
                AND lease_expires_at IS NULL
            )
        )
    ) STRICT
    """,
    f"""
    CREATE TABLE execution_events (
        execution_id TEXT NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence >= 1 AND sequence <= 10000),
        event_id TEXT NOT NULL UNIQUE,
        event_type TEXT NOT NULL CHECK (
            event_type IN (
                'request_accepted', 'execution_started',
                'execution_identity_bound', 'stage_snapshot_persisted',
                'cancellation_requested', 'execution_succeeded',
                'execution_failed', 'execution_cancelled',
                'execution_interrupted'
            )
        ),
        status TEXT NOT NULL CHECK (
            status IN (
                'queued', 'running', 'cancellation_requested', 'succeeded',
                'failed', 'cancelled', 'interrupted'
            )
        ),
        occurred_at TEXT NOT NULL,
        event_json TEXT NOT NULL CHECK (
            length(CAST(event_json AS BLOB)) <= {MAX_EVENT_JSON_BYTES}
        ),
        event_sha256 TEXT NOT NULL CHECK (
            length(event_sha256) = 64
            AND event_sha256 NOT GLOB '*[^0-9a-f]*'
        ),
        PRIMARY KEY (execution_id, sequence),
        FOREIGN KEY (execution_id) REFERENCES executions(execution_id)
            ON UPDATE RESTRICT ON DELETE RESTRICT
    ) STRICT
    """,
    """
    CREATE INDEX executions_fifo_index
        ON executions(status, accepted_sequence)
    """,
    """
    CREATE UNIQUE INDEX executions_one_active_index
        ON executions((1))
        WHERE status IN ('running', 'cancellation_requested')
    """,
    """
    CREATE TRIGGER executions_no_delete
    BEFORE DELETE ON executions
    BEGIN
        SELECT RAISE(ABORT, 'execution records cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER execution_metadata_no_update
    BEFORE UPDATE ON execution_control_metadata
    BEGIN
        SELECT RAISE(ABORT, 'execution metadata is immutable');
    END
    """,
    """
    CREATE TRIGGER execution_metadata_no_delete
    BEFORE DELETE ON execution_control_metadata
    BEGIN
        SELECT RAISE(ABORT, 'execution metadata cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER executions_queue_limit
    BEFORE INSERT ON executions
    WHEN
        NEW.status = 'queued'
        AND (SELECT COUNT(*) FROM executions WHERE status = 'queued') >= 4
    BEGIN
        SELECT RAISE(ABORT, 'execution queue limit reached');
    END
    """,
    """
    CREATE TRIGGER execution_events_no_update
    BEFORE UPDATE ON execution_events
    BEGIN
        SELECT RAISE(ABORT, 'execution events are append-only');
    END
    """,
    """
    CREATE TRIGGER execution_events_no_delete
    BEFORE DELETE ON execution_events
    BEGIN
        SELECT RAISE(ABORT, 'execution events cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER execution_events_owner_guard
    BEFORE INSERT ON execution_events
    WHEN NOT EXISTS (
        SELECT 1 FROM executions WHERE execution_id = NEW.execution_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'execution event owner does not exist');
    END
    """,
    f"""
    CREATE TRIGGER execution_events_insert_guard
    BEFORE INSERT ON execution_events
    WHEN
        NEW.sequence != COALESCE(
            (
                SELECT MAX(sequence) + 1 FROM execution_events
                WHERE execution_id = NEW.execution_id
            ),
            1
        )
        OR (
            NEW.event_type NOT IN (
                'execution_succeeded', 'execution_failed',
                'execution_cancelled', 'execution_interrupted'
            )
            AND NEW.sequence >= {NO_HARDWARE_RUNNER_POLICY.max_events}
        )
        OR length(CAST(NEW.event_json AS BLOB)) > {MAX_EVENT_JSON_BYTES}
        OR COALESCE(
            (
                SELECT SUM(length(CAST(event_json AS BLOB)))
                FROM execution_events WHERE execution_id = NEW.execution_id
            ),
            0
        ) + length(CAST(NEW.event_json AS BLOB)) > CASE
            WHEN NEW.event_type IN (
                'execution_succeeded', 'execution_failed',
                'execution_cancelled', 'execution_interrupted'
            ) THEN {MAX_EVENT_LOG_JSON_BYTES}
            ELSE {MAX_EVENT_LOG_JSON_BYTES - _TERMINAL_EVENT_RESERVE_BYTES}
        END
    BEGIN
        SELECT RAISE(ABORT, 'execution event append invariant failed');
    END
    """,
    """
    CREATE TRIGGER executions_identity_immutable
    BEFORE UPDATE ON executions
    WHEN
        NEW.execution_id IS NOT OLD.execution_id OR
        NEW.idempotency_key IS NOT OLD.idempotency_key OR
        NEW.request_sha256 IS NOT OLD.request_sha256 OR
        NEW.plan_sha256 IS NOT OLD.plan_sha256 OR
        NEW.accepted_sequence IS NOT OLD.accepted_sequence OR
        NEW.accepted_at IS NOT OLD.accepted_at
    BEGIN
        SELECT RAISE(ABORT, 'execution identity is immutable');
    END
    """,
    """
    CREATE TRIGGER executions_updated_at_monotonic
    BEFORE UPDATE OF updated_at ON executions
    WHEN NEW.updated_at < OLD.updated_at
    BEGIN
        SELECT RAISE(ABORT, 'execution updated_at cannot move backwards');
    END
    """,
    """
    CREATE TRIGGER execution_counters_monotonic
    BEFORE UPDATE ON execution_counters
    WHEN NOT (
        NEW.singleton = OLD.singleton
        AND (
            (
                NEW.next_accepted_sequence = OLD.next_accepted_sequence + 1
                AND NEW.next_lease_generation = OLD.next_lease_generation
            ) OR (
                NEW.next_accepted_sequence = OLD.next_accepted_sequence
                AND NEW.next_lease_generation = OLD.next_lease_generation + 1
            )
        )
    )
    BEGIN
        SELECT RAISE(ABORT, 'execution counters must advance exactly once');
    END
    """,
    """
    CREATE TRIGGER execution_counters_no_delete
    BEFORE DELETE ON execution_counters
    BEGIN
        SELECT RAISE(ABORT, 'execution counters cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER executions_terminal_immutable
    BEFORE UPDATE ON executions
    WHEN OLD.status IN ('succeeded', 'failed', 'cancelled', 'interrupted')
    BEGIN
        SELECT RAISE(ABORT, 'terminal execution records are immutable');
    END
    """,
    """
    CREATE TRIGGER executions_transition_guard
    BEFORE UPDATE OF status ON executions
    WHEN NOT (
        NEW.status = OLD.status OR
        (OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled')) OR
        (
            OLD.status = 'running'
            AND NEW.status IN (
                'cancellation_requested', 'succeeded', 'failed', 'interrupted'
            )
        ) OR
        (
            OLD.status = 'cancellation_requested'
            AND NEW.status IN ('cancelled', 'failed', 'interrupted')
        )
    )
    BEGIN
        SELECT RAISE(ABORT, 'illegal execution status transition');
    END
    """,
)

_REQUIRED_OBJECTS = {
    "table": {
        "execution_control_metadata",
        "execution_counters",
        "executions",
        "execution_events",
    },
    "index": {"executions_fifo_index", "executions_one_active_index"},
    "trigger": {
        "executions_no_delete",
        "executions_queue_limit",
        "execution_metadata_no_update",
        "execution_metadata_no_delete",
        "execution_events_no_update",
        "execution_events_no_delete",
        "execution_events_owner_guard",
        "execution_events_insert_guard",
        "executions_identity_immutable",
        "executions_updated_at_monotonic",
        "executions_terminal_immutable",
        "executions_transition_guard",
        "execution_counters_monotonic",
        "execution_counters_no_delete",
    },
    "view": set(),
}
_EXPECTED_COLUMNS = {
    "execution_control_metadata": ("key", "value"),
    "execution_counters": (
        "singleton",
        "next_accepted_sequence",
        "next_lease_generation",
    ),
    "executions": (
        "execution_id",
        "idempotency_key",
        "request_sha256",
        "plan_sha256",
        "accepted_sequence",
        "status",
        "accepted_at",
        "updated_at",
        "job_id",
        "revision_id",
        "lease_runner_instance_id",
        "lease_generation",
        "lease_heartbeat_at",
        "lease_expires_at",
        "record_json",
        "record_sha256",
    ),
    "execution_events": (
        "execution_id",
        "sequence",
        "event_id",
        "event_type",
        "status",
        "occurred_at",
        "event_json",
        "event_sha256",
    ),
}


def _normalize_schema_sql(value: str) -> str:
    return " ".join(value.split()).casefold()


def _ddl_identity(statement: str) -> tuple[str, str]:
    match = re.search(
        r"CREATE\s+(?:UNIQUE\s+)?(TABLE|INDEX|TRIGGER)\s+([A-Za-z_][A-Za-z0-9_]*)",
        statement,
        re.IGNORECASE,
    )
    if match is None:  # pragma: no cover - module-owned constants
        raise RuntimeError("execution store DDL has no object identity")
    return match.group(1).lower(), match.group(2)


_EXPECTED_SCHEMA_SQL = {
    _ddl_identity(statement): _normalize_schema_sql(statement) for statement in _DDL
}


class ExecutionStoreError(RuntimeError):
    """The execution control store could not safely complete an operation."""


class ExecutionStoreIntegrityError(ExecutionStoreError):
    """Persisted control state is malformed, inconsistent, or corrupted."""


class ExecutionNotFoundError(ExecutionStoreError):
    """The requested execution does not exist."""


@dataclass(frozen=True)
class ExecutionSnapshot:
    record: ExecutionRecord
    events: tuple[ExecutionEvent, ...]


@dataclass(frozen=True)
class StoreAdmissionResult:
    decision: AdmissionDecision
    snapshot: ExecutionSnapshot | None
    reason: str

    @property
    def accepted(self) -> bool:
        return self.decision in {
            AdmissionDecision.ACCEPT,
            AdmissionDecision.IDEMPOTENT_REPLAY,
        }

    @property
    def execution_id(self) -> str | None:
        if self.snapshot is None:
            return None
        return self.snapshot.record.execution_id


def _strict_integer(
    value: Any,
    name: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} cannot exceed {maximum}")
    return value


def _timestamp(value: str | datetime, name: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{name} is required")
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    else:
        raise ValueError(f"{name} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _timestamp_value(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ExecutionStoreIntegrityError(f"persisted {name} is not a timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExecutionStoreIntegrityError(f"persisted {name} has no timezone")
    return parsed.astimezone(timezone.utc)


def _execution_id(value: Any) -> str:
    if not isinstance(value, str) or not _EXECUTION_ID.fullmatch(value):
        raise ValueError("execution_id has an invalid format")
    return value


def _canonical_json(value: Any, *, maximum: int, name: str) -> tuple[str, str]:
    try:
        text = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError(f"{name} is not bounded JSON") from exc
    payload = text.encode("utf-8")
    if len(payload) > maximum:
        raise ValueError(f"{name} exceeds its {maximum}-byte store limit")
    return text, sha256(payload).hexdigest()


def _decode_json(
    text: Any,
    expected_sha256: Any,
    *,
    maximum: int,
    name: str,
) -> Mapping[str, Any]:
    if not isinstance(text, str) or not isinstance(expected_sha256, str):
        raise ExecutionStoreIntegrityError(f"persisted {name} columns have invalid types")
    payload = text.encode("utf-8")
    if len(payload) > maximum:
        raise ExecutionStoreIntegrityError(f"persisted {name} exceeds its byte limit")
    if sha256(payload).hexdigest() != expected_sha256:
        raise ExecutionStoreIntegrityError(f"persisted {name} checksum does not match")
    try:
        value = json.loads(
            text,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_object,
        )
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise ExecutionStoreIntegrityError(f"persisted {name} is invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise ExecutionStoreIntegrityError(f"persisted {name} must contain an object")
    _check_json_shape(value, name=name)
    canonical, _ = _canonical_json(value, maximum=maximum, name=name)
    if canonical != text:
        raise ExecutionStoreIntegrityError(f"persisted {name} is not canonical JSON")
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _reject_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key is forbidden: {key!r}")
        value[key] = item
    return value


def _check_json_shape(value: Any, *, name: str) -> None:
    nodes = 0
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            raise ExecutionStoreIntegrityError(f"persisted {name} has too many JSON nodes")
        if depth > _MAX_JSON_DEPTH:
            raise ExecutionStoreIntegrityError(f"persisted {name} is too deeply nested")
        if isinstance(item, Mapping):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and not isfinite(item):
            raise ExecutionStoreIntegrityError(
                f"persisted {name} contains a non-finite number"
            )


class ExecutionControlStore:
    """A bounded, append-only SQLite control plane with no execution adapter."""

    def __init__(
        self,
        path: Path,
        *,
        busy_timeout_seconds: float = 5.0,
        policy: RunnerPolicy = NO_HARDWARE_RUNNER_POLICY,
    ) -> None:
        if not isinstance(path, Path):
            raise TypeError("execution store path must be a pathlib.Path")
        if isinstance(busy_timeout_seconds, bool) or not isinstance(
            busy_timeout_seconds, (int, float)
        ):
            raise ValueError("busy_timeout_seconds must be a number")
        timeout = float(busy_timeout_seconds)
        if not isfinite(timeout) or timeout <= 0 or timeout > 30:
            raise ValueError("busy_timeout_seconds must be in (0, 30]")
        if not isinstance(policy, RunnerPolicy):
            raise ValueError("policy must be a RunnerPolicy")
        self.path = path.absolute()
        self.busy_timeout_seconds = timeout
        self.policy = policy
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ExecutionStoreIntegrityError("execution store cannot be a symlink")
        if self.path.exists() and not self.path.is_file():
            raise ExecutionStoreIntegrityError("execution store path is not a regular file")
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_seconds,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(
            f"PRAGMA busy_timeout = {int(self.busy_timeout_seconds * 1000)}"
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("PRAGMA recursive_triggers = ON")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _enable_wal(self, connection: sqlite3.Connection) -> None:
        deadline = monotonic() + self.busy_timeout_seconds
        retry_milliseconds = min(
            100,
            max(1, int(self.busy_timeout_seconds * 1000)),
        )
        connection.execute(f"PRAGMA busy_timeout = {retry_milliseconds}")
        try:
            while True:
                try:
                    journal_mode = connection.execute(
                        "PRAGMA journal_mode = WAL"
                    ).fetchone()[0]
                    break
                except sqlite3.OperationalError as exc:
                    error_code = getattr(exc, "sqlite_errorcode", None)
                    if (
                        error_code is None
                        or error_code & 0xFF
                        not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
                        or monotonic() >= deadline
                    ):
                        raise
                    sleep(min(0.025, max(0.0, deadline - monotonic())))
        finally:
            connection.execute(
                f"PRAGMA busy_timeout = {int(self.busy_timeout_seconds * 1000)}"
            )
        if str(journal_mode).lower() != "wal":
            raise ExecutionStoreIntegrityError("execution store could not enable WAL")

    def _initialize(self) -> None:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            self._enable_wal(connection)
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("BEGIN EXCLUSIVE")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            application_id = int(
                connection.execute("PRAGMA application_id").fetchone()[0]
            )
            if version == 0:
                if application_id not in {0, STORE_APPLICATION_ID}:
                    raise ExecutionStoreIntegrityError(
                        "unversioned SQLite file belongs to another application"
                    )
                existing = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchone()[0]
                if existing:
                    raise ExecutionStoreIntegrityError(
                        "unversioned execution store contains unknown objects"
                    )
                for statement in _DDL:
                    connection.execute(statement)
                connection.executemany(
                    "INSERT INTO execution_control_metadata(key, value) VALUES (?, ?)",
                    (
                        ("store_schema_version", str(STORE_SCHEMA_VERSION)),
                        ("execution_schema_version", EXECUTION_SCHEMA_VERSION),
                        ("policy_version", POLICY_VERSION),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO execution_counters(
                        singleton, next_accepted_sequence, next_lease_generation
                    ) VALUES (1, 1, 1)
                    """
                )
                connection.execute(f"PRAGMA user_version = {STORE_SCHEMA_VERSION}")
                connection.execute(f"PRAGMA application_id = {STORE_APPLICATION_ID}")
            elif version != STORE_SCHEMA_VERSION:
                raise ExecutionStoreIntegrityError(
                    f"unsupported execution store schema version {version}"
                )
            connection.commit()
            self._assert_schema(connection)
            integrity_check = connection.execute(
                "PRAGMA integrity_check(1)"
            ).fetchone()[0]
            if integrity_check != "ok":
                raise ExecutionStoreIntegrityError(
                    "execution store integrity_check failed"
                )
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ExecutionStoreIntegrityError(
                    "execution store foreign_key_check failed"
                )
        except ExecutionStoreError:
            if connection is not None and connection.in_transaction:
                connection.rollback()
            raise
        except sqlite3.Error as exc:
            if connection is not None and connection.in_transaction:
                connection.rollback()
            raise ExecutionStoreIntegrityError(
                "execution store initialization failed"
            ) from exc
        finally:
            if connection is not None:
                connection.close()

    def _assert_schema(self, connection: sqlite3.Connection) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != STORE_SCHEMA_VERSION:
            raise ExecutionStoreIntegrityError("execution store user_version drifted")
        application_id = int(
            connection.execute("PRAGMA application_id").fetchone()[0]
        )
        if application_id != STORE_APPLICATION_ID:
            raise ExecutionStoreIntegrityError("execution store application_id drifted")
        metadata_rows = connection.execute(
            "SELECT key, value FROM execution_control_metadata"
        ).fetchall()
        metadata = {row["key"]: row["value"] for row in metadata_rows}
        expected_metadata = {
            "store_schema_version": str(STORE_SCHEMA_VERSION),
            "execution_schema_version": EXECUTION_SCHEMA_VERSION,
            "policy_version": POLICY_VERSION,
        }
        if metadata != expected_metadata:
            raise ExecutionStoreIntegrityError("execution store metadata drifted")
        objects: dict[str, set[str]] = {kind: set() for kind in _REQUIRED_OBJECTS}
        schema_sql: dict[tuple[str, str], str] = {}
        for row in connection.execute(
            """
            SELECT type, name, sql FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            """
        ):
            if row["type"] in objects:
                objects[row["type"]].add(row["name"])
                if row["sql"] is not None:
                    schema_sql[(row["type"], row["name"])] = _normalize_schema_sql(
                        row["sql"]
                    )
        for kind, expected in _REQUIRED_OBJECTS.items():
            if objects[kind] != expected:
                raise ExecutionStoreIntegrityError(
                    f"execution store has unexpected {kind} objects"
                )
        if schema_sql != _EXPECTED_SCHEMA_SQL:
            raise ExecutionStoreIntegrityError("execution store schema SQL drifted")
        for table, expected in _EXPECTED_COLUMNS.items():
            columns = tuple(
                row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
            )
            if columns != expected:
                raise ExecutionStoreIntegrityError(
                    f"execution store table {table!r} has unexpected columns"
                )
        counter = connection.execute(
            """
            SELECT next_accepted_sequence, next_lease_generation
            FROM execution_counters WHERE singleton = 1
            """
        ).fetchall()
        if len(counter) != 1 or any(type(counter[0][name]) is not int for name in counter[0].keys()):
            raise ExecutionStoreIntegrityError("execution store counters are invalid")
        maximum_accepted = int(
            connection.execute(
                "SELECT COALESCE(MAX(accepted_sequence), 0) FROM executions"
            ).fetchone()[0]
        )
        if counter[0]["next_accepted_sequence"] <= maximum_accepted:
            raise ExecutionStoreIntegrityError("accepted sequence counter moved backwards")

    @contextmanager
    def _transaction(self, *, immediate: bool) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            self._assert_schema(connection)
            yield connection
            connection.commit()
        except ExecutionStoreError:
            if connection.in_transaction:
                connection.rollback()
            raise
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.rollback()
            raise ExecutionStoreIntegrityError(
                "execution store transaction failed"
            ) from exc
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def admit(
        self,
        request: ExecutionRequest,
        plan: ExecutionPlan,
        *,
        accepted_at: str | datetime,
        execution_id: str | None = None,
    ) -> StoreAdmissionResult:
        if not isinstance(request, ExecutionRequest):
            raise ValueError("request must be an ExecutionRequest")
        if not isinstance(plan, ExecutionPlan):
            raise ValueError("plan must be an ExecutionPlan")
        accepted = _timestamp(accepted_at, "accepted_at")
        with self._transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT execution_id FROM executions WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            existing = (
                self._load_snapshot(connection, row["execution_id"])
                if row is not None
                else None
            )
            active_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM executions
                    WHERE status IN ('running', 'cancellation_requested')
                    """
                ).fetchone()[0]
            )
            queued_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM executions WHERE status = 'queued'"
                ).fetchone()[0]
            )
            assessment = assess_admission(
                request,
                existing=existing.record if existing else None,
                active_count=active_count,
                queued_count=queued_count,
                policy=self.policy,
            )
            if assessment.decision is not AdmissionDecision.ACCEPT:
                return StoreAdmissionResult(
                    assessment.decision,
                    existing,
                    assessment.reason,
                )
            counter = connection.execute(
                """
                SELECT next_accepted_sequence FROM execution_counters
                WHERE singleton = 1
                """
            ).fetchone()
            if counter is None:
                raise ExecutionStoreIntegrityError("accepted sequence counter is missing")
            sequence = int(counter["next_accepted_sequence"])
            connection.execute(
                """
                UPDATE execution_counters
                SET next_accepted_sequence = next_accepted_sequence + 1
                WHERE singleton = 1
                """
            )
            record = ExecutionRecord.queued(
                request,
                plan,
                accepted_sequence=sequence,
                accepted_at=accepted,
                execution_id=execution_id,
                policy=self.policy,
            )
            self._insert_record(connection, record, updated_at=accepted)
            self._append_event(
                connection,
                record,
                event_type=ExecutionEventType.REQUEST_ACCEPTED,
                status=ExecutionStatus.QUEUED,
                occurred_at=accepted,
                message="No-hardware execution request accepted",
                data={
                    "accepted_sequence": sequence,
                    "target": record.request.target.value,
                },
            )
            snapshot = self._load_snapshot(connection, record.execution_id)
            return StoreAdmissionResult(
                AdmissionDecision.ACCEPT,
                snapshot,
                assessment.reason,
            )

    def get(self, execution_id: str) -> ExecutionSnapshot:
        normalized = _execution_id(execution_id)
        with self._transaction(immediate=False) as connection:
            return self._load_snapshot(connection, normalized)

    def lookup_request(self, request: ExecutionRequest) -> ExecutionSnapshot | None:
        """Return the immutable original for an idempotency key, if one exists."""

        if not isinstance(request, ExecutionRequest):
            raise ValueError("request must be an ExecutionRequest")
        with self._transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT execution_id FROM executions WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is None:
                return None
            return self._load_snapshot(connection, row["execution_id"])

    def list_records(
        self,
        *,
        limit: int = MAX_LIST_EXECUTIONS,
    ) -> tuple[ExecutionRecord, ...]:
        bounded_limit = _strict_integer(
            limit,
            "limit",
            minimum=1,
            maximum=MAX_LIST_EXECUTIONS,
        )
        with self._transaction(immediate=False) as connection:
            rows = connection.execute(
                """
                SELECT execution_id FROM executions
                ORDER BY accepted_sequence DESC LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
            return tuple(self._load_record(connection, row["execution_id"]) for row in rows)

    def events_after(
        self,
        execution_id: str,
        *,
        after_sequence: int,
        limit: int = 100,
    ) -> tuple[ExecutionEvent, ...]:
        normalized = _execution_id(execution_id)
        after = _strict_integer(after_sequence, "after_sequence")
        bounded_limit = _strict_integer(limit, "limit", minimum=1, maximum=500)
        snapshot = self.get(normalized)
        return tuple(
            event for event in snapshot.events if event.sequence > after
        )[:bounded_limit]

    def start_next(
        self,
        *,
        runner_instance_id: str,
        at: str | datetime,
    ) -> ExecutionSnapshot | None:
        started = _timestamp(at, "started_at")
        with self._transaction(immediate=True) as connection:
            self._reconcile_stale_locked(connection, observed_at=started)
            active = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM executions
                    WHERE status IN ('running', 'cancellation_requested')
                    """
                ).fetchone()[0]
            )
            if active > 1:
                raise ExecutionStoreIntegrityError("more than one execution is active")
            if active == 1:
                return None
            row = connection.execute(
                """
                SELECT execution_id FROM executions
                WHERE status = 'queued'
                ORDER BY accepted_sequence ASC LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            snapshot = self._load_snapshot(connection, row["execution_id"])
            counter = connection.execute(
                """
                SELECT next_lease_generation FROM execution_counters
                WHERE singleton = 1
                """
            ).fetchone()
            if counter is None:
                raise ExecutionStoreIntegrityError("lease generation counter is missing")
            generation = int(counter["next_lease_generation"])
            connection.execute(
                """
                UPDATE execution_counters
                SET next_lease_generation = next_lease_generation + 1
                WHERE singleton = 1
                """
            )
            lease = ExecutionLease.acquire(
                runner_instance_id,
                generation,
                at=started,
            )
            record = start_execution(snapshot.record, lease, at=started)
            self._update_record(connection, snapshot.record, record, updated_at=started)
            self._append_event(
                connection,
                record,
                event_type=ExecutionEventType.EXECUTION_STARTED,
                status=ExecutionStatus.RUNNING,
                occurred_at=started,
                message="No-hardware execution lease acquired",
                data={"lease_generation": generation},
            )
            return self._load_snapshot(connection, record.execution_id)

    def bind_identity(
        self,
        execution_id: str,
        *,
        job_id: str,
        revision_id: str,
        runner_instance_id: str,
        generation: int,
        at: str | datetime,
    ) -> ExecutionSnapshot:
        normalized = _execution_id(execution_id)
        with self._transaction(immediate=True) as connection:
            snapshot = self._load_snapshot(connection, normalized)
            record = bind_execution_identity(
                snapshot.record,
                job_id=job_id,
                revision_id=revision_id,
                runner_instance_id=runner_instance_id,
                generation=generation,
                at=at,
            )
            if record is snapshot.record:
                return snapshot
            occurred = _timestamp(at, "identity bind time")
            self._update_record(connection, snapshot.record, record, updated_at=occurred)
            self._append_event(
                connection,
                record,
                event_type=ExecutionEventType.EXECUTION_IDENTITY_BOUND,
                status=record.status,
                occurred_at=occurred,
                message="Fabrication Journey identity bound",
                data={},
            )
            return self._load_snapshot(connection, normalized)

    def append_stage_snapshot(
        self,
        execution_id: str,
        *,
        runner_instance_id: str,
        generation: int,
        at: str | datetime,
        message: str,
        data: Mapping[str, Any],
    ) -> ExecutionSnapshot:
        normalized = _execution_id(execution_id)
        with self._transaction(immediate=True) as connection:
            snapshot = self._load_snapshot(connection, normalized)
            occurred = validate_execution_fence(
                snapshot.record,
                runner_instance_id=runner_instance_id,
                generation=generation,
                at=at,
                name="stage snapshot time",
            )
            self._update_record(
                connection,
                snapshot.record,
                snapshot.record,
                updated_at=occurred,
            )
            self._append_event(
                connection,
                snapshot.record,
                event_type=ExecutionEventType.STAGE_SNAPSHOT_PERSISTED,
                status=snapshot.record.status,
                occurred_at=occurred,
                message=message,
                data=data,
            )
            return self._load_snapshot(connection, normalized)

    def renew_lease(
        self,
        execution_id: str,
        *,
        runner_instance_id: str,
        generation: int,
        at: str | datetime,
    ) -> ExecutionSnapshot:
        normalized = _execution_id(execution_id)
        with self._transaction(immediate=True) as connection:
            record = self._load_record(connection, normalized)
            renewed = renew_execution_lease(
                record,
                runner_instance_id=runner_instance_id,
                generation=generation,
                at=at,
            )
            if renewed is not record:
                self._update_record(
                    connection,
                    record,
                    renewed,
                    updated_at=renewed.lease.heartbeat_at,
                )
            return self._load_snapshot(connection, normalized)

    def cancel(
        self,
        execution_id: str,
        *,
        at: str | datetime,
    ) -> ExecutionSnapshot:
        normalized = _execution_id(execution_id)
        with self._transaction(immediate=True) as connection:
            snapshot = self._load_snapshot(connection, normalized)
            record = request_cancellation(snapshot.record, at=at)
            if record is snapshot.record:
                return snapshot
            occurred = record.cancellation_requested_at
            if occurred is None:  # pragma: no cover - guaranteed by contract
                raise ExecutionStoreIntegrityError("cancellation timestamp is missing")
            self._update_record(connection, snapshot.record, record, updated_at=occurred)
            self._append_event(
                connection,
                record,
                event_type=ExecutionEventType.CANCELLATION_REQUESTED,
                status=record.status,
                occurred_at=occurred,
                message="Execution cancellation requested",
                data={},
            )
            if record.status is ExecutionStatus.CANCELLED:
                self._append_event(
                    connection,
                    record,
                    event_type=ExecutionEventType.EXECUTION_CANCELLED,
                    status=ExecutionStatus.CANCELLED,
                    occurred_at=occurred,
                    message="Queued execution cancelled before start",
                    data={},
                )
            return self._load_snapshot(connection, normalized)

    def finish(
        self,
        execution_id: str,
        target: ExecutionStatus,
        *,
        runner_instance_id: str,
        generation: int,
        at: str | datetime,
        failure: ExecutionFailure | None = None,
    ) -> ExecutionSnapshot:
        normalized = _execution_id(execution_id)
        with self._transaction(immediate=True) as connection:
            snapshot = self._load_snapshot(connection, normalized)
            record = transition_execution(
                snapshot.record,
                target,
                at=at,
                runner_instance_id=runner_instance_id,
                generation=generation,
                failure=failure,
            )
            occurred = record.completed_at
            if occurred is None:  # pragma: no cover - guaranteed by contract
                raise ExecutionStoreIntegrityError("terminal timestamp is missing")
            event_type = _TERMINAL_EVENT.get(record.status)
            if event_type is None:
                raise ExecutionStoreIntegrityError("finish did not produce a terminal state")
            data: dict[str, Any] = {"target": record.request.target.value}
            message = f"Execution {record.status.value}"
            if record.failure is not None:
                data.update(
                    {
                        "failure_code": record.failure.code.value,
                        "retryable": record.failure.retryable,
                        "stage": record.failure.stage.value if record.failure.stage else None,
                    }
                )
                message = record.failure.message
            self._update_record(connection, snapshot.record, record, updated_at=occurred)
            self._append_event(
                connection,
                record,
                event_type=event_type,
                status=record.status,
                occurred_at=occurred,
                message=message,
                data=data,
            )
            return self._load_snapshot(connection, normalized)

    def reconcile_stale(
        self,
        *,
        observed_at: str | datetime,
    ) -> tuple[ExecutionSnapshot, ...]:
        observed = _timestamp(observed_at, "observed_at")
        with self._transaction(immediate=True) as connection:
            execution_ids = self._reconcile_stale_locked(
                connection,
                observed_at=observed,
            )
            return tuple(
                self._load_snapshot(connection, execution_id)
                for execution_id in execution_ids
            )

    def _reconcile_stale_locked(
        self,
        connection: sqlite3.Connection,
        *,
        observed_at: str,
    ) -> tuple[str, ...]:
        rows = connection.execute(
            """
            SELECT execution_id FROM executions
            WHERE status IN ('running', 'cancellation_requested')
            ORDER BY accepted_sequence
            """
        ).fetchall()
        if len(rows) > 1:
            raise ExecutionStoreIntegrityError("more than one execution is active")
        interrupted: list[str] = []
        observed_value = _timestamp_value(observed_at, "observed_at")
        for row in rows:
            snapshot = self._load_snapshot(connection, row["execution_id"])
            lease = snapshot.record.lease
            if lease is None:
                raise ExecutionStoreIntegrityError("active execution has no lease")
            if observed_value < _timestamp_value(lease.expires_at, "lease expires_at"):
                continue
            record = interrupt_stale_execution(snapshot.record, observed_at=observed_at)
            self._update_record(
                connection,
                snapshot.record,
                record,
                updated_at=observed_at,
            )
            self._append_event(
                connection,
                record,
                event_type=ExecutionEventType.EXECUTION_INTERRUPTED,
                status=ExecutionStatus.INTERRUPTED,
                occurred_at=observed_at,
                message=record.failure.message,
                data={
                    "failure_code": record.failure.code.value,
                    "retryable": record.failure.retryable,
                },
            )
            interrupted.append(record.execution_id)
        return tuple(interrupted)

    def _insert_record(
        self,
        connection: sqlite3.Connection,
        record: ExecutionRecord,
        *,
        updated_at: str,
    ) -> None:
        text, digest = _canonical_json(
            record.to_dict(),
            maximum=MAX_RECORD_JSON_BYTES,
            name="execution record",
        )
        _, plan_digest = _canonical_json(
            record.plan.to_dict(),
            maximum=MAX_RECORD_JSON_BYTES,
            name="execution plan",
        )
        lease = record.lease
        connection.execute(
            """
            INSERT INTO executions(
                execution_id, idempotency_key, request_sha256, plan_sha256,
                accepted_sequence,
                status, accepted_at, updated_at, job_id, revision_id,
                lease_runner_instance_id, lease_generation, lease_heartbeat_at,
                lease_expires_at, record_json, record_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.execution_id,
                record.request.idempotency_key,
                record.request_sha256,
                plan_digest,
                record.accepted_sequence,
                record.status.value,
                record.accepted_at,
                updated_at,
                record.job_id,
                record.revision_id,
                lease.runner_instance_id if lease else None,
                lease.generation if lease else None,
                lease.heartbeat_at if lease else None,
                lease.expires_at if lease else None,
                text,
                digest,
            ),
        )

    def _update_record(
        self,
        connection: sqlite3.Connection,
        previous: ExecutionRecord,
        record: ExecutionRecord,
        *,
        updated_at: str,
    ) -> None:
        if record.execution_id != previous.execution_id:
            raise ExecutionStoreIntegrityError("execution identity changed during update")
        previous_text, previous_digest = _canonical_json(
            previous.to_dict(),
            maximum=MAX_RECORD_JSON_BYTES,
            name="previous execution record",
        )
        del previous_text
        text, digest = _canonical_json(
            record.to_dict(),
            maximum=MAX_RECORD_JSON_BYTES,
            name="execution record",
        )
        current = connection.execute(
            """
            SELECT updated_at FROM executions
            WHERE execution_id = ? AND record_sha256 = ?
            """,
            (record.execution_id, previous_digest),
        ).fetchone()
        if current is None:
            raise ExecutionStoreIntegrityError("execution compare-and-swap failed")
        normalized_update = _timestamp(updated_at, "updated_at")
        if _timestamp_value(normalized_update, "updated_at") < _timestamp_value(
            current["updated_at"], "current updated_at"
        ):
            raise ExecutionStoreIntegrityError("execution updated_at moved backwards")
        lease = record.lease
        result = connection.execute(
            """
            UPDATE executions SET
                status = ?, updated_at = ?, job_id = ?, revision_id = ?,
                lease_runner_instance_id = ?, lease_generation = ?,
                lease_heartbeat_at = ?, lease_expires_at = ?,
                record_json = ?, record_sha256 = ?
            WHERE execution_id = ? AND record_sha256 = ?
            """,
            (
                record.status.value,
                normalized_update,
                record.job_id,
                record.revision_id,
                lease.runner_instance_id if lease else None,
                lease.generation if lease else None,
                lease.heartbeat_at if lease else None,
                lease.expires_at if lease else None,
                text,
                digest,
                record.execution_id,
                previous_digest,
            ),
        )
        if result.rowcount != 1:
            raise ExecutionStoreIntegrityError("execution compare-and-swap failed")

    def _append_event(
        self,
        connection: sqlite3.Connection,
        record: ExecutionRecord,
        *,
        event_type: ExecutionEventType,
        status: ExecutionStatus,
        occurred_at: str,
        message: str,
        data: Mapping[str, Any],
    ) -> ExecutionEvent:
        aggregate = connection.execute(
            """
            SELECT
                COUNT(*) AS count,
                MIN(sequence) AS minimum,
                MAX(sequence) AS maximum,
                COALESCE(SUM(length(CAST(event_json AS BLOB))), 0) AS total_bytes
            FROM execution_events WHERE execution_id = ?
            """,
            (record.execution_id,),
        ).fetchone()
        count = int(aggregate["count"])
        if count:
            if aggregate["minimum"] != 1 or aggregate["maximum"] != count:
                raise ExecutionStoreIntegrityError("execution event sequence has a gap")
        sequence = count + 1
        if sequence > record.policy.max_events:
            raise ExecutionStoreIntegrityError("execution event limit is exhausted")
        if event_type not in _TERMINAL_EVENT_TYPES and sequence >= record.policy.max_events:
            raise ExecutionStoreIntegrityError(
                "execution event limit reached its reserved terminal slot"
            )
        identity_forbidden = {
            ExecutionEventType.REQUEST_ACCEPTED,
            ExecutionEventType.EXECUTION_STARTED,
        }
        event = ExecutionEvent(
            execution_id=record.execution_id,
            sequence=sequence,
            event_type=event_type,
            status=status,
            occurred_at=occurred_at,
            message=message,
            job_id=(None if event_type in identity_forbidden else record.job_id),
            revision_id=(
                None if event_type in identity_forbidden else record.revision_id
            ),
            data=data,
        )
        text, digest = _canonical_json(
            event.to_dict(),
            maximum=MAX_EVENT_JSON_BYTES,
            name="execution event",
        )
        byte_ceiling = MAX_EVENT_LOG_JSON_BYTES
        if event_type not in _TERMINAL_EVENT_TYPES:
            byte_ceiling -= _TERMINAL_EVENT_RESERVE_BYTES
        if int(aggregate["total_bytes"]) + len(text.encode("utf-8")) > byte_ceiling:
            raise ExecutionStoreIntegrityError(
                "execution event log byte limit or terminal reserve is exhausted"
            )
        connection.execute(
            """
            INSERT INTO execution_events(
                execution_id, sequence, event_id, event_type, status,
                occurred_at, event_json, event_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.execution_id,
                event.sequence,
                event.event_id,
                event.event_type.value,
                event.status.value,
                event.occurred_at,
                text,
                digest,
            ),
        )
        return event

    def _load_record(
        self,
        connection: sqlite3.Connection,
        execution_id: str,
    ) -> ExecutionRecord:
        row = connection.execute(
            "SELECT * FROM executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        if row is None:
            raise ExecutionNotFoundError("execution record was not found")
        value = _decode_json(
            row["record_json"],
            row["record_sha256"],
            maximum=MAX_RECORD_JSON_BYTES,
            name="execution record",
        )
        try:
            record = ExecutionRecord.from_mapping(value)
        except ValueError as exc:
            raise ExecutionStoreIntegrityError(
                "persisted execution record violates its contract"
            ) from exc
        expected = {
            "execution_id": record.execution_id,
            "idempotency_key": record.request.idempotency_key,
            "request_sha256": record.request_sha256,
            "accepted_sequence": record.accepted_sequence,
            "status": record.status.value,
            "accepted_at": record.accepted_at,
            "job_id": record.job_id,
            "revision_id": record.revision_id,
            "lease_runner_instance_id": (
                record.lease.runner_instance_id if record.lease else None
            ),
            "lease_generation": record.lease.generation if record.lease else None,
            "lease_heartbeat_at": (
                record.lease.heartbeat_at if record.lease else None
            ),
            "lease_expires_at": record.lease.expires_at if record.lease else None,
        }
        _, plan_digest = _canonical_json(
            record.plan.to_dict(),
            maximum=MAX_RECORD_JSON_BYTES,
            name="execution plan",
        )
        expected["plan_sha256"] = plan_digest
        for name, expected_value in expected.items():
            if row[name] != expected_value:
                raise ExecutionStoreIntegrityError(
                    f"execution record index column {name!r} drifted"
                )
        updated = _timestamp_value(row["updated_at"], "updated_at")
        if updated < _timestamp_value(record.accepted_at, "accepted_at"):
            raise ExecutionStoreIntegrityError("execution updated_at precedes accepted_at")
        return record

    def _load_events(
        self,
        connection: sqlite3.Connection,
        execution_id: str,
        *,
        record: ExecutionRecord,
    ) -> tuple[ExecutionEvent, ...]:
        aggregate = connection.execute(
            """
            SELECT
                COUNT(*) AS count,
                COALESCE(SUM(length(CAST(event_json AS BLOB))), 0) AS total_bytes
            FROM execution_events WHERE execution_id = ?
            """,
            (execution_id,),
        ).fetchone()
        event_count = int(aggregate["count"])
        total_bytes = int(aggregate["total_bytes"])
        if event_count > self.policy.max_events:
            raise ExecutionStoreIntegrityError("execution event count exceeds policy")
        if total_bytes > MAX_EVENT_LOG_JSON_BYTES:
            raise ExecutionStoreIntegrityError("execution event log exceeds its byte limit")
        if record.status not in _TERMINAL_EVENT:
            if event_count >= self.policy.max_events:
                raise ExecutionStoreIntegrityError(
                    "active execution consumed its reserved terminal event slot"
                )
            if total_bytes > MAX_EVENT_LOG_JSON_BYTES - _TERMINAL_EVENT_RESERVE_BYTES:
                raise ExecutionStoreIntegrityError(
                    "execution event log byte limit consumed its terminal reserve"
                )
        rows = connection.execute(
            """
            SELECT * FROM execution_events
            WHERE execution_id = ? ORDER BY sequence ASC
            """,
            (execution_id,),
        ).fetchall()
        events: list[ExecutionEvent] = []
        for row in rows:
            value = _decode_json(
                row["event_json"],
                row["event_sha256"],
                maximum=MAX_EVENT_JSON_BYTES,
                name="execution event",
            )
            try:
                event = ExecutionEvent.from_mapping(value)
            except ValueError as exc:
                raise ExecutionStoreIntegrityError(
                    "persisted execution event violates its contract"
                ) from exc
            expected = {
                "execution_id": event.execution_id,
                "sequence": event.sequence,
                "event_id": event.event_id,
                "event_type": event.event_type.value,
                "status": event.status.value,
                "occurred_at": event.occurred_at,
            }
            for name, expected_value in expected.items():
                if row[name] != expected_value:
                    raise ExecutionStoreIntegrityError(
                        f"execution event index column {name!r} drifted"
                    )
            events.append(event)
        return tuple(events)

    def _load_snapshot(
        self,
        connection: sqlite3.Connection,
        execution_id: str,
    ) -> ExecutionSnapshot:
        record = self._load_record(connection, execution_id)
        events = self._load_events(connection, execution_id, record=record)
        self._validate_event_log(record, events)
        updated_row = connection.execute(
            "SELECT updated_at FROM executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        if updated_row is None:  # pragma: no cover - record loaded in this transaction
            raise ExecutionStoreIntegrityError("execution record disappeared")
        if _timestamp_value(
            updated_row["updated_at"], "updated_at"
        ) < _timestamp_value(events[-1].occurred_at, "last event occurred_at"):
            raise ExecutionStoreIntegrityError("execution updated_at precedes its event tail")
        return ExecutionSnapshot(record, events)

    @staticmethod
    def _validate_event_log(
        record: ExecutionRecord,
        events: tuple[ExecutionEvent, ...],
    ) -> None:
        if not events:
            raise ExecutionStoreIntegrityError("execution event log is empty")
        if len(events) > record.policy.max_events:
            raise ExecutionStoreIntegrityError("execution event log exceeds policy")
        first = events[0]
        if (
            first.sequence != 1
            or first.event_type is not ExecutionEventType.REQUEST_ACCEPTED
            or first.status is not ExecutionStatus.QUEUED
            or first.occurred_at != record.accepted_at
        ):
            raise ExecutionStoreIntegrityError("execution event log has no valid origin")
        if dict(first.data) != {
            "accepted_sequence": record.accepted_sequence,
            "target": record.request.target.value,
        }:
            raise ExecutionStoreIntegrityError("execution origin data drifted")
        previous_time = _timestamp_value(first.occurred_at, "event occurred_at")
        previous_status = first.status
        event_counts = {event_type: 0 for event_type in ExecutionEventType}
        identity_seen = False
        allowed_statuses = {
            ExecutionStatus.QUEUED: {
                ExecutionStatus.QUEUED,
                ExecutionStatus.RUNNING,
                ExecutionStatus.CANCELLED,
            },
            ExecutionStatus.RUNNING: {
                ExecutionStatus.RUNNING,
                ExecutionStatus.CANCELLATION_REQUESTED,
                ExecutionStatus.SUCCEEDED,
                ExecutionStatus.FAILED,
                ExecutionStatus.INTERRUPTED,
            },
            ExecutionStatus.CANCELLATION_REQUESTED: {
                ExecutionStatus.CANCELLATION_REQUESTED,
                ExecutionStatus.CANCELLED,
                ExecutionStatus.FAILED,
                ExecutionStatus.INTERRUPTED,
            },
            ExecutionStatus.SUCCEEDED: {ExecutionStatus.SUCCEEDED},
            ExecutionStatus.FAILED: {ExecutionStatus.FAILED},
            ExecutionStatus.CANCELLED: {ExecutionStatus.CANCELLED},
            ExecutionStatus.INTERRUPTED: {ExecutionStatus.INTERRUPTED},
        }
        for expected_sequence, event in enumerate(events, start=1):
            if event.execution_id != record.execution_id:
                raise ExecutionStoreIntegrityError("execution event ownership drifted")
            if event.sequence != expected_sequence:
                raise ExecutionStoreIntegrityError("execution event sequence is not contiguous")
            occurred = _timestamp_value(event.occurred_at, "event occurred_at")
            if occurred < previous_time:
                raise ExecutionStoreIntegrityError("execution event time moved backwards")
            if event.status not in allowed_statuses[previous_status]:
                raise ExecutionStoreIntegrityError("execution event status moved illegally")
            event_counts[event.event_type] += 1
            if event.event_type is ExecutionEventType.REQUEST_ACCEPTED:
                if event.sequence != 1:
                    raise ExecutionStoreIntegrityError("execution origin event was repeated")
            elif event.event_type is ExecutionEventType.EXECUTION_STARTED:
                if event.sequence != 2 or event.occurred_at != record.started_at:
                    raise ExecutionStoreIntegrityError("execution start event drifted")
                lease_generation = event.data.get("lease_generation")
                if (
                    set(event.data) != {"lease_generation"}
                    or type(lease_generation) is not int
                    or lease_generation < 1
                ):
                    raise ExecutionStoreIntegrityError("execution start data drifted")
                if (
                    record.lease is not None
                    and lease_generation != record.lease.generation
                ):
                    raise ExecutionStoreIntegrityError(
                        "execution start lease generation drifted"
                    )
            elif event.event_type is ExecutionEventType.EXECUTION_IDENTITY_BOUND:
                if identity_seen:
                    raise ExecutionStoreIntegrityError(
                        "execution identity event was repeated"
                    )
                identity_seen = True
                if event.data:
                    raise ExecutionStoreIntegrityError("execution identity data drifted")
                if (
                    event.job_id != record.job_id
                    or event.revision_id != record.revision_id
                ):
                    raise ExecutionStoreIntegrityError(
                        "execution identity event disagrees with its record"
                    )
            elif event.event_type is ExecutionEventType.STAGE_SNAPSHOT_PERSISTED:
                if not identity_seen:
                    raise ExecutionStoreIntegrityError(
                        "stage snapshot precedes execution identity"
                    )
            elif event.event_type is ExecutionEventType.CANCELLATION_REQUESTED:
                if event.occurred_at != record.cancellation_requested_at:
                    raise ExecutionStoreIntegrityError(
                        "execution cancellation event drifted"
                    )
                if event.data:
                    raise ExecutionStoreIntegrityError(
                        "execution cancellation data drifted"
                    )
            if event.event_type not in {
                ExecutionEventType.REQUEST_ACCEPTED,
                ExecutionEventType.EXECUTION_STARTED,
                ExecutionEventType.EXECUTION_IDENTITY_BOUND,
            }:
                expected_job_id = record.job_id if identity_seen else None
                expected_revision_id = record.revision_id if identity_seen else None
                if (
                    event.job_id != expected_job_id
                    or event.revision_id != expected_revision_id
                ):
                    raise ExecutionStoreIntegrityError(
                        "execution event journey identity drifted"
                    )
            previous_time = occurred
            previous_status = event.status
        expected_lifecycle_counts = {
            ExecutionEventType.REQUEST_ACCEPTED: 1,
            ExecutionEventType.EXECUTION_STARTED: int(record.started_at is not None),
            ExecutionEventType.EXECUTION_IDENTITY_BOUND: int(record.job_id is not None),
            ExecutionEventType.CANCELLATION_REQUESTED: int(
                record.cancellation_requested_at is not None
            ),
        }
        for event_type, expected_count in expected_lifecycle_counts.items():
            if event_counts[event_type] != expected_count:
                raise ExecutionStoreIntegrityError(
                    f"execution lifecycle event {event_type.value!r} count drifted"
                )
        last = events[-1]
        if last.status is not record.status:
            raise ExecutionStoreIntegrityError("execution event tail disagrees with record")
        terminal_event = _TERMINAL_EVENT.get(record.status)
        terminal_count = sum(
            event_counts[event_type] for event_type in _TERMINAL_EVENT.values()
        )
        if terminal_event is None:
            if terminal_count:
                raise ExecutionStoreIntegrityError("non-terminal execution has a terminal event")
        elif terminal_count != 1 or last.event_type is not terminal_event:
            raise ExecutionStoreIntegrityError("terminal execution event is missing")
        if terminal_event is not None:
            expected_terminal_data: dict[str, Any]
            if record.status is ExecutionStatus.INTERRUPTED:
                if record.failure is None:  # pragma: no cover - record contract
                    raise ExecutionStoreIntegrityError(
                        "interrupted execution has no failure"
                    )
                expected_terminal_data = {
                    "failure_code": record.failure.code.value,
                    "retryable": record.failure.retryable,
                }
            elif record.status is ExecutionStatus.FAILED:
                if record.failure is None:  # pragma: no cover - record contract
                    raise ExecutionStoreIntegrityError("failed execution has no failure")
                expected_terminal_data = {
                    "failure_code": record.failure.code.value,
                    "retryable": record.failure.retryable,
                    "stage": (
                        record.failure.stage.value if record.failure.stage else None
                    ),
                    "target": record.request.target.value,
                }
            elif (
                record.status is ExecutionStatus.CANCELLED
                and record.started_at is None
            ):
                expected_terminal_data = {}
            else:
                expected_terminal_data = {"target": record.request.target.value}
            if dict(last.data) != expected_terminal_data:
                raise ExecutionStoreIntegrityError("terminal execution event data drifted")
            if record.failure is not None and last.message != record.failure.message:
                raise ExecutionStoreIntegrityError(
                    "terminal execution event failure message drifted"
                )
        if record.completed_at is not None and last.occurred_at != record.completed_at:
            raise ExecutionStoreIntegrityError(
                "terminal event time disagrees with execution completion"
            )


__all__ = [
    "ExecutionControlStore",
    "ExecutionNotFoundError",
    "ExecutionSnapshot",
    "ExecutionStoreError",
    "ExecutionStoreIntegrityError",
    "MAX_EVENT_LOG_JSON_BYTES",
    "MAX_EVENT_JSON_BYTES",
    "MAX_LIST_EXECUTIONS",
    "MAX_RECORD_JSON_BYTES",
    "STORE_APPLICATION_ID",
    "STORE_SCHEMA_VERSION",
    "StoreAdmissionResult",
]
