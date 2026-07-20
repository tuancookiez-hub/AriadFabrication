"""Generate and verify Ariad's deterministic M4 OpenAPI snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .app import create_app


DEFAULT_OPENAPI_PATH = Path("schemas/v1/interface-api.openapi.json")


def generate_openapi_document() -> dict[str, Any]:
    """Return the application contract without reading or mutating journey records."""

    return create_app().openapi()


def canonical_openapi_bytes(document: dict[str, Any] | None = None) -> bytes:
    value = document if document is not None else generate_openapi_document()
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def write_openapi_snapshot(path: Path) -> Path:
    output = path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_openapi_bytes())
    return output


def check_openapi_snapshot(path: Path) -> None:
    snapshot = path.expanduser().resolve()
    if not snapshot.is_file():
        raise ValueError(f"OpenAPI snapshot is missing: {snapshot}")
    expected = canonical_openapi_bytes()
    if snapshot.read_bytes() != expected:
        raise ValueError(
            "OpenAPI snapshot is stale; run ariad-interface-openapi and regenerate frontend types"
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate Ariad's deterministic interface OpenAPI schema.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OPENAPI_PATH)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        try:
            check_openapi_snapshot(args.output)
        except ValueError as exc:
            parser.error(str(exc))
        print(args.output.expanduser().resolve())
        return
    print(write_openapi_snapshot(args.output))


if __name__ == "__main__":
    main()
