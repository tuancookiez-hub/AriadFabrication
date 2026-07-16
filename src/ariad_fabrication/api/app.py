"""FastAPI entry point for the local read-only Fabrication Journey API."""

from __future__ import annotations

import argparse
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .models import (
    INTERFACE_API_VERSION,
    HealthResponse,
    RevisionDetailResponse,
    RevisionListResponse,
    read_only_capabilities,
)
from .repository import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    InvalidRevisionError,
    JourneyRepository,
    RevisionNotFoundError,
)


def create_app(runs_root: Path | str = Path("runs")) -> FastAPI:
    repository = JourneyRepository(runs_root)
    app = FastAPI(
        title="Ariad Fabrication Journey API",
        summary="Read-only access to persisted fabrication evidence.",
        description=(
            "This API replays persisted records. It cannot upload G-code, select a printer, "
            "heat hardware, move hardware, or start manufacturing."
        ),
        version="1.0.0",
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
        "/api/v1/revisions/{job_id}/{revision_id}",
        response_model=RevisionDetailResponse,
    )
    def revision(job_id: str, revision_id: str) -> RevisionDetailResponse:
        try:
            return repository.get_revision(job_id, revision_id)
        except RevisionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InvalidRevisionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/revisions/{job_id}/{revision_id}/artifacts/{artifact_id}")
    def artifact(job_id: str, revision_id: str, artifact_id: str) -> FileResponse:
        try:
            item = repository.get_artifact(job_id, revision_id, artifact_id)
        except (RevisionNotFoundError, ArtifactNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (InvalidRevisionError, ArtifactIntegrityError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return FileResponse(
            item.path,
            media_type=item.media_type,
            filename=item.filename,
            headers={
                "ETag": f'"{item.checksum_sha256}"',
                "X-Ariad-Evidence-Mode": item.evidence_mode,
                "X-Ariad-Hardware-Action": "false",
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
