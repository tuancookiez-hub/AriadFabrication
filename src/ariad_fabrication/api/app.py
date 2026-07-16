"""FastAPI entry point for the local read-only Fabrication Journey API."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Response

from .models import (
    ErrorResponse,
    INTERFACE_API_VERSION,
    HealthResponse,
    RevisionComparisonResponse,
    RevisionDetailResponse,
    RevisionListResponse,
    read_only_capabilities,
)
from .repository import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactTooLargeError,
    InvalidRevisionError,
    JourneyRepository,
    MAX_ARTIFACT_DOWNLOAD_BYTES,
    RevisionNotFoundError,
)


_REVISION_ERROR_RESPONSES = {
    404: {"model": ErrorResponse, "description": "Persisted revision was not found."},
    409: {"model": ErrorResponse, "description": "Persisted revision failed integrity checks."},
}
_ARTIFACT_RESPONSES = {
    200: {
        "description": "Bounded binary snapshot whose bytes passed recorded size and SHA-256 checks.",
        "content": {
            "application/octet-stream": {
                "schema": {"type": "string", "format": "binary"}
            }
        },
        "headers": {
            "ETag": {
                "description": "Quoted recorded SHA-256 of the returned snapshot.",
                "schema": {"type": "string"},
            },
            "Content-Disposition": {
                "description": "Attachment filename encoded according to RFC 5987.",
                "schema": {"type": "string"},
            },
            "X-Ariad-Evidence-Mode": {
                "schema": {
                    "type": "string",
                    "enum": ["real", "simulated", "fixture", "unavailable"],
                }
            },
            "X-Ariad-Integrity": {
                "schema": {"type": "string", "const": "sha256-verified-snapshot"}
            },
            "X-Ariad-Hardware-Action": {
                "schema": {"type": "string", "const": "false"}
            },
            "X-Ariad-Max-Artifact-Bytes": {
                "schema": {"type": "integer", "const": MAX_ARTIFACT_DOWNLOAD_BYTES}
            },
            "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
            "X-Content-Type-Options": {
                "schema": {"type": "string", "const": "nosniff"}
            },
        },
    },
    **_REVISION_ERROR_RESPONSES,
    413: {
        "model": ErrorResponse,
        "description": "Artifact exceeds the verified-download resource ceiling.",
    },
}


def create_app(runs_root: Path | str = Path("runs")) -> FastAPI:
    repository = JourneyRepository(runs_root)
    app = FastAPI(
        title="Ariad Fabrication Journey API",
        summary="Read-only access to persisted fabrication evidence.",
        description=(
            "This API replays persisted records. It cannot upload G-code, select a printer, "
            "heat hardware, move hardware, or start manufacturing."
        ),
        version=INTERFACE_API_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.repository = repository

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            schema_version=INTERFACE_API_VERSION,
            service="ariad-interface-api",
            status="ok",
            capabilities=read_only_capabilities(),
        )

    @app.get("/api/v1/revisions", response_model=RevisionListResponse)
    def revisions() -> RevisionListResponse:
        return repository.list_revisions()

    @app.get(
        "/api/v1/revision-comparison",
        response_model=RevisionComparisonResponse,
        responses=_REVISION_ERROR_RESPONSES,
    )
    def revision_comparison(
        base_job_id: str,
        base_revision_id: str,
        candidate_job_id: str,
        candidate_revision_id: str,
    ) -> RevisionComparisonResponse:
        try:
            return repository.compare_revisions(
                base_job_id,
                base_revision_id,
                candidate_job_id,
                candidate_revision_id,
            )
        except RevisionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InvalidRevisionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/api/v1/revisions/{job_id}/{revision_id}",
        response_model=RevisionDetailResponse,
        responses=_REVISION_ERROR_RESPONSES,
    )
    def revision(job_id: str, revision_id: str) -> RevisionDetailResponse:
        try:
            return repository.get_revision(job_id, revision_id)
        except RevisionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InvalidRevisionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/api/v1/revisions/{job_id}/{revision_id}/artifacts/{artifact_id}",
        response_class=Response,
        responses=_ARTIFACT_RESPONSES,
    )
    def artifact(job_id: str, revision_id: str, artifact_id: str) -> Response:
        try:
            item = repository.get_artifact(job_id, revision_id, artifact_id)
        except (RevisionNotFoundError, ArtifactNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (InvalidRevisionError, ArtifactIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ArtifactTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        encoded_filename = quote(item.filename, safe="")
        return Response(
            content=item.content,
            media_type=item.media_type,
            headers={
                "ETag": f'"{item.checksum_sha256}"',
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
                "X-Ariad-Evidence-Mode": item.evidence_mode,
                "X-Ariad-Integrity": "sha256-verified-snapshot",
                "X-Ariad-Hardware-Action": "false",
                "X-Ariad-Max-Artifact-Bytes": str(MAX_ARTIFACT_DOWNLOAD_BYTES),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serve Ariad's local read-only journey API.")
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("the M4 API is local-only and may bind only to a loopback host")
    import uvicorn

    uvicorn.run(create_app(args.runs_root), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
