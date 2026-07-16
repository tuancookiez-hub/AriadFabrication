"""Runtime validation against Ariad's committed JSON Schema assets."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import json
from pathlib import Path
import re
import sysconfig
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError


_MAX_SCHEMA_BYTES = 1024 * 1024
_MAX_ERROR_MESSAGE_CHARS = 512
_SIMPLE_PATH_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RFC3339_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_FORMAT_CHECKER = FormatChecker()

PART_SPEC_SCHEMA = "part-spec.schema.json"
JOURNEY_EVENT_SCHEMA = "journey-event.schema.json"
ARTIFACT_MANIFEST_SCHEMA = "artifact-manifest.schema.json"
FABRICATION_PACKAGE_SCHEMA = "fabrication-package.schema.json"
INTERFACE_FABRICATION_PACKAGE_SCHEMA = (
    "interface-fabrication-package.schema.json"
)
PRINTABILITY_REPORT_SCHEMA = "printability-report.schema.json"
GEOMETRY_VALIDATION_REPORT_SCHEMA = "geometry-validation-report.schema.json"
GCODE_PREFLIGHT_REPORT_SCHEMA = "gcode-preflight-report.schema.json"
PRINTER_PROFILE_SCHEMA = "printer-profile.schema.json"
MATERIAL_PROFILE_SCHEMA = "material-profile.schema.json"
PROCESS_PROFILE_SCHEMA = "process-profile.schema.json"
ORIENTATION_PROFILE_SCHEMA = "orientation-profile.schema.json"
INTERFACE_GEOMETRY_VALIDATION_REPORT_SCHEMA = (
    "interface-geometry-validation-report.schema.json"
)
INTERFACE_PRINTABILITY_REPORT_SCHEMA = "interface-printability-report.schema.json"
INTERFACE_GCODE_PREFLIGHT_REPORT_SCHEMA = (
    "interface-gcode-preflight-report.schema.json"
)
INTERFACE_PRINTER_PROFILE_SCHEMA = "interface-printer-profile.schema.json"
INTERFACE_MATERIAL_PROFILE_SCHEMA = "interface-material-profile.schema.json"
INTERFACE_PROCESS_PROFILE_SCHEMA = "interface-process-profile.schema.json"
INTERFACE_ORIENTATION_PROFILE_SCHEMA = "interface-orientation-profile.schema.json"

PERSISTED_SCHEMA_FILENAMES = frozenset(
    {
        PART_SPEC_SCHEMA,
        JOURNEY_EVENT_SCHEMA,
        ARTIFACT_MANIFEST_SCHEMA,
        FABRICATION_PACKAGE_SCHEMA,
        INTERFACE_FABRICATION_PACKAGE_SCHEMA,
        PRINTABILITY_REPORT_SCHEMA,
        GEOMETRY_VALIDATION_REPORT_SCHEMA,
        GCODE_PREFLIGHT_REPORT_SCHEMA,
        PRINTER_PROFILE_SCHEMA,
        MATERIAL_PROFILE_SCHEMA,
        PROCESS_PROFILE_SCHEMA,
        ORIENTATION_PROFILE_SCHEMA,
        INTERFACE_GEOMETRY_VALIDATION_REPORT_SCHEMA,
        INTERFACE_PRINTABILITY_REPORT_SCHEMA,
        INTERFACE_GCODE_PREFLIGHT_REPORT_SCHEMA,
        INTERFACE_PRINTER_PROFILE_SCHEMA,
        INTERFACE_MATERIAL_PROFILE_SCHEMA,
        INTERFACE_PROCESS_PROFILE_SCHEMA,
        INTERFACE_ORIENTATION_PROFILE_SCHEMA,
    }
)


class PersistedSchemaValidationError(ValueError):
    """A trusted schema is unavailable or a persisted value violates it."""


@_FORMAT_CHECKER.checks("date-time")
def _is_timezone_aware_rfc3339(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if not _RFC3339_DATE_TIME.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def schema_asset_path(schema_name: str) -> Path:
    """Resolve one allowlisted schema in a checkout or installed wheel."""

    if schema_name not in PERSISTED_SCHEMA_FILENAMES:
        raise PersistedSchemaValidationError(
            f"unsupported persisted schema asset {schema_name!r}"
        )
    candidates = (
        Path(__file__).resolve().parents[2] / "schemas" / "v1" / schema_name,
        Path(sysconfig.get_path("data"))
        / "share"
        / "ariad-fabrication"
        / "schemas"
        / "v1"
        / schema_name,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise PersistedSchemaValidationError(
        f"required persisted schema asset {schema_name!r} is unavailable"
    )


@lru_cache(maxsize=None)
def _validator(schema_name: str) -> Draft202012Validator:
    path = schema_asset_path(schema_name)
    try:
        with path.open("rb") as handle:
            payload = handle.read(_MAX_SCHEMA_BYTES + 1)
    except OSError as exc:
        raise PersistedSchemaValidationError(
            f"required persisted schema asset {schema_name!r} cannot be read"
        ) from exc
    if len(payload) > _MAX_SCHEMA_BYTES:
        raise PersistedSchemaValidationError(
            f"required persisted schema asset {schema_name!r} exceeds the size limit"
        )
    try:
        schema = json.loads(
            payload.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_object,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise PersistedSchemaValidationError(
            f"required persisted schema asset {schema_name!r} is invalid JSON"
        ) from exc
    if not isinstance(schema, dict):
        raise PersistedSchemaValidationError(
            f"required persisted schema asset {schema_name!r} must contain an object"
        )
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise PersistedSchemaValidationError(
            f"required persisted schema asset {schema_name!r} is not a valid schema"
        ) from exc
    return Draft202012Validator(schema, format_checker=_FORMAT_CHECKER)


def validate_persisted_instance(
    instance: Any,
    schema_name: str,
    *,
    record_name: str,
) -> None:
    """Fail on the first deterministic, bounded schema violation."""

    error = min(
        _validator(schema_name).iter_errors(instance),
        key=_error_key,
        default=None,
    )
    if error is None:
        return
    location = _instance_path(error)
    message = " ".join(error.message.split())
    if len(message) > _MAX_ERROR_MESSAGE_CHARS:
        message = message[: _MAX_ERROR_MESSAGE_CHARS - 1] + "…"
    raise PersistedSchemaValidationError(
        f"{record_name} violates {schema_name} at {location}: {message}"
    )


def check_persisted_schema_asset(schema_name: str) -> None:
    """Load and meta-validate one trusted schema without validating an instance."""

    _validator(schema_name)


def _error_key(error: ValidationError) -> tuple[tuple[str, ...], str, str]:
    return (
        tuple(str(item) for item in error.absolute_path),
        str(error.validator),
        error.message[:_MAX_ERROR_MESSAGE_CHARS],
    )


def _instance_path(error: ValidationError) -> str:
    result = "$"
    for item in error.absolute_path:
        if isinstance(item, int):
            result += f"[{item}]"
        else:
            text = str(item)
            if _SIMPLE_PATH_SEGMENT.fullmatch(text):
                result += f".{text}"
            else:
                result += f"[{text!r}]"
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _reject_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key is not allowed: {key!r}")
        value[key] = item
    return value
