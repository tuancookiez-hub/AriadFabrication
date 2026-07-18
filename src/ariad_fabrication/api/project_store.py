"""Small durable store for user-confirmed project intents.

These records are not Journey revisions and do not claim R0 evidence. They only
prove that a user explicitly chose to preserve an idea for later clarification.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from threading import Lock
from uuid import uuid4


PROJECT_INTENT_SCHEMA_VERSION = "1.0.0"
MAX_PROJECT_INTENTS = 500
MAX_PROJECT_RECORD_BYTES = 64 * 1024
PROJECT_DRAFT_SCHEMA_VERSION = "1.0.0"
PROJECT_DRAFT_FIELDS = (
    "material",
    "manufacturing_process",
    "name",
    "part_type",
    "purpose",
    "safety_class",
    "size_x_mm",
    "size_y_mm",
    "size_z_mm",
    "support_policy",
    "tolerance_mm",
)


class ProjectStoreError(RuntimeError):
    pass


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ProjectStoreError("persisted project record contains a duplicate key")
        value[key] = item
    return value


@dataclass(frozen=True)
class ProjectIntent:
    schema_version: str
    project_id: str
    title: str
    prompt: str
    prompt_sha256: str
    confirmed_at: str
    confirmed_by: str
    status: str
    evidence_mode: str
    brief_evidence_level: None
    fabrication_started: bool
    hardware_actions: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectDraft:
    schema_version: str
    project_id: str
    name: str | None
    purpose: str | None
    part_type: str | None
    size_x_mm: float | None
    size_y_mm: float | None
    size_z_mm: float | None
    material: str | None
    tolerance_mm: float | None
    support_policy: str | None
    manufacturing_process: str | None
    safety_class: str | None
    updated_at: str
    status: str
    missing_fields: tuple[str, ...]
    brief_evidence_level: None
    fabrication_started: bool
    hardware_actions: bool

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["missing_fields"] = list(self.missing_fields)
        return value


class ProjectIntentStore:
    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()
        self._lock = Lock()

    def create(self, *, title: str, prompt: str) -> ProjectIntent:
        title = self._bounded_text(title, "project title", 120)
        prompt = self._bounded_text(prompt, "project prompt", 16_384)
        if len(prompt.encode("utf-8")) > 16 * 1024:
            raise ProjectStoreError("project prompt exceeds the UTF-8 byte ceiling")
        record = ProjectIntent(
            schema_version=PROJECT_INTENT_SCHEMA_VERSION,
            project_id=f"project_{uuid4().hex}",
            title=title,
            prompt=prompt,
            prompt_sha256=sha256(prompt.encode("utf-8")).hexdigest(),
            confirmed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            confirmed_by="user",
            status="intent_confirmed",
            evidence_mode="user_confirmed",
            brief_evidence_level=None,
            fabrication_started=False,
            hardware_actions=False,
        )
        rendered = (json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            directory = self.root / record.project_id
            directory.mkdir(exist_ok=False)
            temporary = directory / "project.json.tmp"
            destination = directory / "project.json"
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(rendered)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
            except Exception:
                temporary.unlink(missing_ok=True)
                try:
                    directory.rmdir()
                except OSError:
                    pass
                raise
        return record

    def list(self, *, limit: int = 100) -> tuple[ProjectIntent, ...]:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ProjectStoreError("project list limit must be from 1 through 200")
        if not self.root.is_dir():
            return ()
        records: list[ProjectIntent] = []
        with os.scandir(self.root) as entries:
            candidates = sorted(
                (entry.name for entry in entries if entry.is_dir(follow_symlinks=False)),
                reverse=True,
            )[:MAX_PROJECT_INTENTS]
        for project_id in candidates[:limit]:
            records.append(self._read(project_id))
        return tuple(records)

    def get(self, project_id: str) -> ProjectIntent:
        return self._read(project_id)

    def save_draft(self, project_id: str, values: dict[str, object]) -> ProjectDraft:
        self._read(project_id)
        normalized = self._normalize_draft_values(values)
        missing = tuple(name for name in PROJECT_DRAFT_FIELDS if normalized[name] is None)
        draft = ProjectDraft(
            schema_version=PROJECT_DRAFT_SCHEMA_VERSION,
            project_id=project_id,
            **normalized,
            updated_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            status="needs_input" if missing else "ready_for_confirmation",
            missing_fields=missing,
            brief_evidence_level=None,
            fabrication_started=False,
            hardware_actions=False,
        )
        rendered = (json.dumps(draft.to_dict(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        directory = self.root / project_id
        temporary = directory / "draft.json.tmp"
        destination = directory / "draft.json"
        with self._lock:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(rendered)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        return draft

    def get_draft(self, project_id: str) -> ProjectDraft | None:
        self._read(project_id)
        path = self.root / project_id / "draft.json"
        if not path.exists():
            return None
        if not path.is_file() or path.is_symlink():
            raise ProjectStoreError("clarification draft is unavailable")
        with path.open("rb") as stream:
            raw = stream.read(MAX_PROJECT_RECORD_BYTES + 1)
        if len(raw) > MAX_PROJECT_RECORD_BYTES:
            raise ProjectStoreError("clarification draft exceeds the read ceiling")
        try:
            value = json.loads(raw, object_pairs_hook=_strict_object)
            value["missing_fields"] = tuple(value["missing_fields"])
            draft = ProjectDraft(**value)
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ProjectStoreError("clarification draft is invalid") from exc
        if draft.project_id != project_id or draft.schema_version != PROJECT_DRAFT_SCHEMA_VERSION:
            raise ProjectStoreError("clarification draft identity is inconsistent")
        if draft.brief_evidence_level is not None or draft.fabrication_started or draft.hardware_actions:
            raise ProjectStoreError("clarification draft claim boundary is inconsistent")
        normalized = self._normalize_draft_values(
            {field_name: getattr(draft, field_name) for field_name in PROJECT_DRAFT_FIELDS}
        )
        missing = tuple(name for name in PROJECT_DRAFT_FIELDS if normalized[name] is None)
        expected_status = "needs_input" if missing else "ready_for_confirmation"
        if draft.missing_fields != missing or draft.status != expected_status:
            raise ProjectStoreError("clarification draft readiness is inconsistent")
        if not isinstance(draft.updated_at, str):
            raise ProjectStoreError("clarification draft timestamp is invalid")
        try:
            updated_at = datetime.fromisoformat(draft.updated_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ProjectStoreError("clarification draft timestamp is invalid") from exc
        if updated_at.tzinfo is None:
            raise ProjectStoreError("clarification draft timestamp must include a timezone")
        return draft

    @staticmethod
    def _normalize_draft_values(values: dict[str, object]) -> dict[str, object]:
        if set(values) != set(PROJECT_DRAFT_FIELDS):
            raise ProjectStoreError("clarification draft fields do not match the closed contract")
        normalized: dict[str, object] = dict(values)
        for field_name in ("name", "purpose", "part_type", "material", "manufacturing_process"):
            value = normalized[field_name]
            if value is not None:
                if not isinstance(value, str) or not value.strip() or len(value.strip()) > 512:
                    raise ProjectStoreError(f"clarification field {field_name} is invalid")
                normalized[field_name] = value.strip()
        for field_name in ("size_x_mm", "size_y_mm", "size_z_mm", "tolerance_mm"):
            value = normalized[field_name]
            if value is not None and (
                type(value) not in {int, float} or not math.isfinite(value) or value <= 0
            ):
                raise ProjectStoreError(f"clarification field {field_name} must be positive and finite")
        if normalized["support_policy"] not in {None, "avoid", "allowed", "required"}:
            raise ProjectStoreError("clarification support policy is invalid")
        if normalized["safety_class"] not in {None, "general", "caution", "safety_critical"}:
            raise ProjectStoreError("clarification safety class is invalid")
        return normalized

    def _read(self, project_id: str) -> ProjectIntent:
        if not project_id.startswith("project_") or len(project_id) != 40:
            raise ProjectStoreError("persisted project identifier is invalid")
        path = self.root / project_id / "project.json"
        if not path.is_file() or path.is_symlink():
            raise ProjectStoreError("persisted project record is unavailable")
        with path.open("rb") as stream:
            raw = stream.read(MAX_PROJECT_RECORD_BYTES + 1)
        if len(raw) > MAX_PROJECT_RECORD_BYTES:
            raise ProjectStoreError("persisted project record exceeds the read ceiling")
        try:
            value = json.loads(raw, object_pairs_hook=_strict_object)
            record = ProjectIntent(**value)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise ProjectStoreError("persisted project record is invalid") from exc
        if record.project_id != project_id or record.schema_version != PROJECT_INTENT_SCHEMA_VERSION:
            raise ProjectStoreError("persisted project identity is inconsistent")
        if not isinstance(record.title, str) or not isinstance(record.prompt, str):
            raise ProjectStoreError("persisted project text is invalid")
        if not isinstance(record.confirmed_at, str):
            raise ProjectStoreError("persisted project timestamp is invalid")
        try:
            confirmed_at = datetime.fromisoformat(record.confirmed_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ProjectStoreError("persisted project timestamp is invalid") from exc
        if confirmed_at.tzinfo is None:
            raise ProjectStoreError("persisted project timestamp must include a timezone")
        if record.prompt_sha256 != sha256(record.prompt.encode("utf-8")).hexdigest():
            raise ProjectStoreError("persisted project prompt checksum is inconsistent")
        if (
            record.confirmed_by != "user"
            or record.status != "intent_confirmed"
            or record.evidence_mode != "user_confirmed"
            or record.brief_evidence_level is not None
            or record.fabrication_started is not False
            or record.hardware_actions is not False
        ):
            raise ProjectStoreError("persisted project claim boundary is inconsistent")
        return record

    @staticmethod
    def _bounded_text(value: str, label: str, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ProjectStoreError(f"{label} is required")
        value = value.strip()
        if len(value) > maximum:
            raise ProjectStoreError(f"{label} exceeds its character ceiling")
        return value


__all__ = ["ProjectDraft", "ProjectIntent", "ProjectIntentStore", "ProjectStoreError"]
