"""FastAPI entry point for Ariad evidence replay and confirmed intent persistence."""

from __future__ import annotations

import argparse
from hmac import compare_digest
import json
from pathlib import Path
from secrets import token_urlsafe
from threading import Lock
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response

from ..codex_conversation import LocalCodexConversation
from ..intake import CapabilityLane, CurrentCapabilityRouter, IntentProposal, PromptIntake
from ..local_codex import LocalCodexSnapshot, LocalCodexStatus, probe_local_codex
from ..domain import AssemblySpec
from ..cad.declarative import (
    DeclarativeCadDocument,
    declarative_artifact_path,
    generate_declarative_cad,
)
from ..cad.live_l_bracket import generate_l_bracket, live_artifact_path
from .agent_tool_runtime import ReadOnlyAgentToolRuntime

from .models import (
    BrowserSessionResponse,
    AssemblySpecResponse,
    ConversationCancelResponse,
    ConversationEventsResponse,
    ConversationTurnRequest,
    ConversationTurnResponse,
    DeclarativeCadResponse,
    ErrorResponse,
    INTERFACE_API_VERSION,
    HealthResponse,
    IntakeRequest,
    IntakeResponse,
    LocalCodexStatusResponse,
    LiveLBracketRequest,
    LiveLBracketResponse,
    ProjectIntentCreateRequest,
    ProjectDetailResponse,
    ProjectBriefConfirmRequest,
    ProjectBriefView,
    ProjectDraftRequest,
    ProjectDraftView,
    ProjectDesignPlanRequest,
    ProjectDesignPlanView,
    ProjectDesignProposalView,
    ProjectCadProposalView,
    ProjectIntentListResponse,
    ProjectIntentView,
    RevisionComparisonResponse,
    RevisionDetailResponse,
    RevisionListResponse,
    read_only_capabilities,
)
from .project_store import ProjectIntentStore, ProjectStoreError
from .repository import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactTooLargeError,
    DEFAULT_REVISION_LIST_LIMIT,
    InvalidRevisionError,
    JourneyRepository,
    MAX_ARTIFACT_DOWNLOAD_BYTES,
    MAX_REVISION_LIST_LIMIT,
    MAX_REVISION_LIST_OFFSET,
    RevisionNotFoundError,
)


_REVISION_ERROR_RESPONSES = {
    404: {"model": ErrorResponse, "description": "Persisted revision was not found."},
    409: {"model": ErrorResponse, "description": "Persisted revision failed integrity checks."},
}
_ARTIFACT_RESPONSES = {
    200: {
        "description": "Bounded binary snapshot whose bytes passed recorded size and SHA-256 checks.",
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
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
            "X-Ariad-Hardware-Action": {"schema": {"type": "string", "const": "false"}},
            "X-Ariad-Max-Artifact-Bytes": {
                "schema": {"type": "integer", "const": MAX_ARTIFACT_DOWNLOAD_BYTES}
            },
            "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
            "X-Content-Type-Options": {"schema": {"type": "string", "const": "nosniff"}},
        },
    },
    **_REVISION_ERROR_RESPONSES,
    413: {
        "model": ErrorResponse,
        "description": "Artifact exceeds the verified-download resource ceiling.",
    },
}


def create_app(
    runs_root: Path | str = Path("runs"),
    *,
    codex_executable: Path | None = None,
    codex_workspace: Path | None = None,
    projects_root: Path | str = Path("runs/projects"),
    assembly_spec_path: Path | str = Path("benchmarks/robot_casing/assembly_spec.json"),
) -> FastAPI:
    repository = JourneyRepository(runs_root)
    app = FastAPI(
        title="Ariad Fabrication Journey API",
        summary="Evidence replay, conversation, project clarification, R0 confirmation, and Design planning.",
        description=(
            "This API replays persisted records, captures bounded ideas, and may save a "
            "user-confirmed project intent, explicitly confirm a complete PartSpec through the existing R0 Brief gate, and persist a planning-only Design plan. It cannot execute arbitrary generated CAD code, upload G-code, select a printer, heat hardware, move hardware, or start manufacturing. Codex may propose a closed declarative CSG document that Ariad validates and interprets as bounded digital CAD."
        ),
        version=INTERFACE_API_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.repository = repository
    app.state.runs_root = Path(runs_root).expanduser().resolve()
    app.state.project_confirmation_enabled = not (
        app.state.runs_root.name == "interface" and app.state.runs_root.parent.name == "benchmarks"
    )
    app.state.project_store = ProjectIntentStore(projects_root)
    app.state.live_cad_root = Path(projects_root).expanduser().resolve().parent / "live-cad"
    app.state.agent_tool_runtime = ReadOnlyAgentToolRuntime(repository, app.state.project_store)
    app.state.codex_executable = codex_executable
    app.state.codex_snapshot = None
    app.state.codex_probe_lock = Lock()
    app.state.codex_workspace = codex_workspace
    app.state.codex_conversation = None
    app.state.codex_conversation_lock = Lock()
    app.state.browser_session_token = token_urlsafe(32)
    try:
        assembly_value = json.loads(
            Path(assembly_spec_path).read_text(encoding="utf-8")
        )
        app.state.assembly_spec = AssemblySpec.from_mapping(assembly_value)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("The configured AssemblySpec is unavailable or invalid.") from exc

    def configured_codex_snapshot() -> LocalCodexSnapshot:
        snapshot: LocalCodexSnapshot | None = app.state.codex_snapshot
        if snapshot is None:
            with app.state.codex_probe_lock:
                snapshot = app.state.codex_snapshot
                if snapshot is None:
                    configured: Path | None = app.state.codex_executable
                    snapshot = (
                        probe_local_codex(configured)
                        if configured is not None
                        else LocalCodexSnapshot(
                            status=LocalCodexStatus.UNAVAILABLE,
                            cli_version=None,
                            authentication=None,
                            reason="No trusted local Codex executable is configured.",
                        )
                    )
                    app.state.codex_snapshot = snapshot
        return snapshot

    def require_browser_session(x_ariad_session: str | None = Header(default=None)) -> None:
        expected: str = app.state.browser_session_token
        if x_ariad_session is None or not compare_digest(x_ariad_session, expected):
            raise HTTPException(status_code=403, detail="A valid local Ariad session is required.")

    def configured_conversation() -> LocalCodexConversation:
        snapshot = configured_codex_snapshot()
        if not snapshot.conversation_available:
            raise HTTPException(status_code=503, detail=snapshot.reason)
        executable: Path | None = app.state.codex_executable
        workspace: Path | None = app.state.codex_workspace
        if executable is None or workspace is None:
            raise HTTPException(
                status_code=503,
                detail="A trusted Codex executable and empty conversation workspace are required.",
            )
        conversation: LocalCodexConversation | None = app.state.codex_conversation
        if conversation is None:
            with app.state.codex_conversation_lock:
                conversation = app.state.codex_conversation
                if conversation is None:
                    try:
                        runtime: ReadOnlyAgentToolRuntime = app.state.agent_tool_runtime
                        conversation = LocalCodexConversation(
                            executable,
                            workspace,
                            tool_specs=runtime.tool_specs,
                            tool_executor=runtime.execute,
                        )
                    except (OSError, RuntimeError, ValueError) as exc:
                        raise HTTPException(
                            status_code=503,
                            detail=f"Local Codex conversation could not start: {type(exc).__name__}.",
                        ) from exc
                    app.state.codex_conversation = conversation
        return conversation

    def close_conversation() -> None:
        conversation: LocalCodexConversation | None = app.state.codex_conversation
        if conversation is not None:
            conversation.close()

    app.router.add_event_handler("shutdown", close_conversation)

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            schema_version=INTERFACE_API_VERSION,
            service="ariad-interface-api",
            status="ok",
            capabilities=read_only_capabilities(),
        )

    @app.get("/api/v1/assemblies/robot-concept", response_model=AssemblySpecResponse)
    def robot_concept_assembly() -> AssemblySpecResponse:
        assembly: AssemblySpec = app.state.assembly_spec
        value = assembly.to_dict()
        value.pop("schema_version")
        return AssemblySpecResponse(
            schema_version=INTERFACE_API_VERSION,
            contract_version="1.0.0",
            **value,
            evidence_mode="planning_fixture",
            cad_generated=False,
            simulation_run=False,
        )

    @app.get("/api/v1/codex/status", response_model=LocalCodexStatusResponse)
    def codex_status() -> LocalCodexStatusResponse:
        snapshot = configured_codex_snapshot()
        return LocalCodexStatusResponse(
            schema_version=INTERFACE_API_VERSION,
            **snapshot.to_dict(),
        )

    @app.get("/api/v1/session", response_model=BrowserSessionResponse)
    def browser_session(response: Response) -> BrowserSessionResponse:
        response.headers["Cache-Control"] = "no-store"
        return BrowserSessionResponse(
            schema_version=INTERFACE_API_VERSION,
            session_token=app.state.browser_session_token,
            expires_on_restart=True,
            codex_credentials_exposed=False,
        )

    @app.post(
        "/api/v1/codex/turns",
        response_model=ConversationTurnResponse,
    )
    def start_codex_turn(
        request: ConversationTurnRequest,
        _: None = Depends(require_browser_session),
    ) -> ConversationTurnResponse:
        conversation = configured_conversation()
        try:
            turn_id = conversation.start_turn(request.prompt)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ConversationTurnResponse(
            schema_version=INTERFACE_API_VERSION,
            turn_id=turn_id,
            accepted=True,
            tools_registered=5,
            workspace_mutation_enabled=False,
            hardware_actions=False,
        )

    @app.get("/api/v1/codex/events", response_model=ConversationEventsResponse)
    def codex_events(
        after: int = Query(0, ge=0),
        _: None = Depends(require_browser_session),
    ) -> ConversationEventsResponse:
        conversation = configured_conversation()
        events = conversation.events_after(after)
        next_sequence = events[-1].sequence if events else after
        return ConversationEventsResponse(
            schema_version=INTERFACE_API_VERSION,
            events=[event.to_dict() for event in events],
            active_turn_id=conversation.active_turn_id,
            next_sequence=next_sequence,
            tools_registered=5,
            workspace_mutation_enabled=False,
            hardware_actions=False,
        )

    @app.post("/api/v1/codex/cancel", response_model=ConversationCancelResponse)
    def cancel_codex_turn(
        _: None = Depends(require_browser_session),
    ) -> ConversationCancelResponse:
        conversation = configured_conversation()
        return ConversationCancelResponse(
            schema_version=INTERFACE_API_VERSION,
            accepted=conversation.cancel_active_turn(),
            hardware_actions=False,
        )

    @app.get("/api/v1/projects", response_model=ProjectIntentListResponse)
    def projects(
        limit: int = Query(100, ge=1, le=200),
        _: None = Depends(require_browser_session),
    ) -> ProjectIntentListResponse:
        store: ProjectIntentStore = app.state.project_store
        try:
            records = store.list(limit=limit)
        except ProjectStoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ProjectIntentListResponse(
            schema_version=INTERFACE_API_VERSION,
            projects=[ProjectIntentView(**record.to_dict()) for record in records],
            fabrication_started=False,
            hardware_actions=False,
        )

    @app.post("/api/v1/projects", response_model=ProjectIntentView, status_code=201)
    def create_project(
        request: ProjectIntentCreateRequest,
        _: None = Depends(require_browser_session),
    ) -> ProjectIntentView:
        store: ProjectIntentStore = app.state.project_store
        try:
            record = store.create(title=request.title, prompt=request.prompt)
        except ProjectStoreError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ProjectIntentView(**record.to_dict())

    @app.get("/api/v1/projects/{project_id}", response_model=ProjectDetailResponse)
    def project_detail(
        project_id: str,
        _: None = Depends(require_browser_session),
    ) -> ProjectDetailResponse:
        store: ProjectIntentStore = app.state.project_store
        try:
            project = store.get(project_id)
            draft = store.get_draft(project_id)
            brief = store.get_brief(project_id)
            design_plan = store.get_design_plan(project_id)
        except ProjectStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return ProjectDetailResponse(
            schema_version=INTERFACE_API_VERSION,
            project=ProjectIntentView(**project.to_dict()),
            draft=ProjectDraftView(**draft.to_dict()) if draft else None,
            brief=ProjectBriefView(**brief.to_dict()) if brief else None,
            design_plan=ProjectDesignPlanView(**design_plan.to_dict()) if design_plan else None,
            fabrication_started=False,
            hardware_actions=False,
        )

    @app.post("/api/v1/live-cad/l-bracket", response_model=LiveLBracketResponse)
    def generate_live_l_bracket(
        request: LiveLBracketRequest,
        _: None = Depends(require_browser_session),
    ) -> LiveLBracketResponse:
        store: ProjectIntentStore = app.state.project_store
        try:
            store.get(request.project_id)
            if store.get_brief(request.project_id) is None:
                raise ProjectStoreError("A confirmed R0 Brief is required before CAD generation.")
            manifest, cache_reused = generate_l_bracket(
                request.model_dump(exclude={"project_id"}),
                app.state.live_cad_root,
            )
        except ProjectStoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ImportError as exc:
            raise HTTPException(
                status_code=503,
                detail="The optional pinned CAD environment is not installed. Run uv sync --frozen --extra test --extra cad.",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=409, detail=f"Live CAD generation failed: {type(exc).__name__}.") from exc
        artifacts = [
            {
                **artifact,
                "download_url": (
                    f"/api/v1/live-cad/{manifest['generation_id']}/{artifact['filename']}"
                ),
            }
            for artifact in manifest["artifacts"]
        ]
        response_value = dict(manifest)
        response_value.pop("artifacts", None)
        response_value.pop("schema_version", None)
        return LiveLBracketResponse(
            schema_version=INTERFACE_API_VERSION,
            **response_value,
            artifacts=artifacts,
            cache_reused=cache_reused,
        )

    @app.get("/api/v1/live-cad/{generation_id}/{filename}")
    def live_cad_artifact(generation_id: str, filename: str) -> Response:
        try:
            path = live_artifact_path(app.state.live_cad_root, generation_id, filename)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        media_types = {
            ".step": "model/step",
            ".stl": "model/stl",
            ".glb": "model/gltf-binary",
            ".json": "application/json",
        }
        response = Response(content=path.read_bytes(), media_type=media_types[path.suffix])
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Disposition"] = f'attachment; filename="{path.name}"'
        response.headers["X-Ariad-Evidence-Mode"] = "live-digital-generation"
        response.headers["X-Ariad-Hardware-Action"] = "false"
        return response

    @app.get(
        "/api/v1/projects/{project_id}/cad-proposal",
        response_model=ProjectCadProposalView,
    )
    def project_cad_proposal(
        project_id: str,
        _: None = Depends(require_browser_session),
    ) -> ProjectCadProposalView:
        runtime: ReadOnlyAgentToolRuntime = app.state.agent_tool_runtime
        proposal = runtime.latest_cad_proposal(project_id)
        if proposal is None:
            raise HTTPException(
                status_code=404,
                detail="No current Codex declarative-CAD proposal exists for this R0 Brief.",
            )
        return ProjectCadProposalView(**proposal)

    @app.post(
        "/api/v1/projects/{project_id}/generate-cad",
        response_model=DeclarativeCadResponse,
    )
    def generate_project_declarative_cad(
        project_id: str,
        _: None = Depends(require_browser_session),
    ) -> DeclarativeCadResponse:
        store: ProjectIntentStore = app.state.project_store
        runtime: ReadOnlyAgentToolRuntime = app.state.agent_tool_runtime
        try:
            store.get(project_id)
            if store.get_brief(project_id) is None:
                raise ProjectStoreError("A confirmed R0 Brief is required before CAD generation.")
            proposal = runtime.latest_cad_proposal(project_id)
            if proposal is None:
                raise ProjectStoreError(
                    "Ask Codex to propose a declarative CAD document for this project first."
                )
            document = DeclarativeCadDocument.from_mapping(proposal["document"])
            manifest, cache_reused = generate_declarative_cad(
                document,
                app.state.live_cad_root,
            )
        except ProjectStoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ImportError as exc:
            raise HTTPException(
                status_code=503,
                detail="The optional pinned CAD environment is not installed. Run uv sync --frozen --extra test --extra cad.",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Declarative CAD generation failed: {type(exc).__name__}.",
            ) from exc
        artifacts = [
            {
                **artifact,
                "download_url": (
                    f"/api/v1/live-cad/declarative/{manifest['generation_id']}/{artifact['filename']}"
                ),
            }
            for artifact in manifest["artifacts"]
        ]
        response_value = dict(manifest)
        response_value.pop("artifacts", None)
        response_value.pop("schema_version", None)
        return DeclarativeCadResponse(
            schema_version=INTERFACE_API_VERSION,
            **response_value,
            artifacts=artifacts,
            cache_reused=cache_reused,
        )

    @app.get("/api/v1/live-cad/declarative/{generation_id}/{filename}")
    def declarative_cad_artifact(generation_id: str, filename: str) -> Response:
        try:
            path = declarative_artifact_path(
                app.state.live_cad_root,
                generation_id,
                filename,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        media_types = {
            ".step": "model/step",
            ".stl": "model/stl",
            ".glb": "model/gltf-binary",
        }
        response = Response(content=path.read_bytes(), media_type=media_types[path.suffix])
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Disposition"] = f'attachment; filename="{path.name}"'
        response.headers["X-Ariad-Evidence-Mode"] = "model-proposed-live-digital-generation"
        response.headers["X-Ariad-Hardware-Action"] = "false"
        return response

    @app.put("/api/v1/projects/{project_id}/draft", response_model=ProjectDraftView)
    def save_project_draft(
        project_id: str,
        request: ProjectDraftRequest,
        _: None = Depends(require_browser_session),
    ) -> ProjectDraftView:
        store: ProjectIntentStore = app.state.project_store
        try:
            draft = store.save_draft(project_id, request.model_dump())
        except ProjectStoreError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ProjectDraftView(**draft.to_dict())

    @app.post(
        "/api/v1/projects/{project_id}/brief-confirmation",
        response_model=ProjectBriefView,
        status_code=201,
    )
    def confirm_project_brief(
        project_id: str,
        request: ProjectBriefConfirmRequest,
        _: None = Depends(require_browser_session),
    ) -> ProjectBriefView:
        del request
        if not app.state.project_confirmation_enabled:
            raise HTTPException(
                status_code=409,
                detail="R0 confirmation is disabled while replaying the committed interface fixture.",
            )
        store: ProjectIntentStore = app.state.project_store
        try:
            brief = store.confirm_brief(project_id, runs_root=app.state.runs_root)
        except ProjectStoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ProjectBriefView(**brief.to_dict())

    @app.put(
        "/api/v1/projects/{project_id}/design-plan",
        response_model=ProjectDesignPlanView,
    )
    def save_project_design_plan(
        project_id: str,
        request: ProjectDesignPlanRequest,
        _: None = Depends(require_browser_session),
    ) -> ProjectDesignPlanView:
        store: ProjectIntentStore = app.state.project_store
        try:
            plan = store.save_design_plan(project_id, request.model_dump())
        except ProjectStoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ProjectDesignPlanView(**plan.to_dict())

    @app.get(
        "/api/v1/projects/{project_id}/design-proposal",
        response_model=ProjectDesignProposalView,
    )
    def project_design_proposal(
        project_id: str,
        _: None = Depends(require_browser_session),
    ) -> ProjectDesignProposalView:
        runtime: ReadOnlyAgentToolRuntime = app.state.agent_tool_runtime
        proposal = runtime.latest_design_proposal(project_id)
        if proposal is None:
            raise HTTPException(
                status_code=404,
                detail="No current Codex Design proposal is available for this R0 Brief.",
            )
        return ProjectDesignProposalView(**proposal)

    @app.post(
        "/api/v1/intake",
        response_model=IntakeResponse,
        responses={
            422: {
                "model": ErrorResponse,
                "description": "The prompt is empty or exceeds the bounded intake contract.",
            }
        },
    )
    def capture_intake(request: IntakeRequest) -> IntakeResponse:
        """Capture one idea without persistence, model inference, or execution."""

        try:
            intake = PromptIntake(request.prompt)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        summary = " ".join(intake.prompt.split())[:512]
        proposal = IntentProposal(
            lane=CapabilityLane.PLANNING_ONLY,
            summary=summary,
            questions=(
                "Configure the GPT-5.6 intent provider to classify this idea and propose requirements.",
            ),
        )
        route = CurrentCapabilityRouter().route(intake, proposal)
        return IntakeResponse(
            schema_version=INTERFACE_API_VERSION,
            intake=intake.to_dict(),
            provider={
                "provider_id": "openai_gpt_5_6_intent",
                "model": "gpt-5.6-sol",
                "configured": False,
                "evidence_mode": "unavailable",
                "reason": "No OpenAI API credential is configured for this local service.",
            },
            route=route.to_dict(),
            persisted=False,
            executed=False,
            claim_boundary=(
                "Intent captured only. No model inference, CAD generation, validation, slicing, "
                "hardware action, or physical validation occurred."
            ),
        )

    @app.get("/api/v1/revisions", response_model=RevisionListResponse)
    def revisions(
        offset: int = Query(0, ge=0, le=MAX_REVISION_LIST_OFFSET),
        limit: int = Query(
            DEFAULT_REVISION_LIST_LIMIT,
            ge=1,
            le=MAX_REVISION_LIST_LIMIT,
        ),
    ) -> RevisionListResponse:
        return repository.list_revisions(offset=offset, limit=limit)

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
    parser = argparse.ArgumentParser(description="Serve Ariad's local evidence and intent API.")
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--codex-bin",
        type=Path,
        default=None,
        help="Explicit native codex.exe used only for the bounded local account probe.",
    )
    parser.add_argument(
        "--codex-workspace",
        type=Path,
        default=None,
        help="Existing empty directory used by the read-only local Codex conversation.",
    )
    parser.add_argument("--projects-root", type=Path, default=Path("runs/projects"))
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("the M4 API is local-only and may bind only to a loopback host")
    import uvicorn

    uvicorn.run(
        create_app(
            args.runs_root,
            codex_executable=args.codex_bin,
            codex_workspace=args.codex_workspace,
            projects_root=args.projects_root,
        ),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
