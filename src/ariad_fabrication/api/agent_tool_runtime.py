"""Bounded, read-only execution for the Codex-facing Ariad tool catalog."""

from __future__ import annotations

import json
from typing import Any, Mapping

from ..agent_tools import exposed_codex_tools
from ..intake import CapabilityLane, CurrentCapabilityRouter, IntentProposal, PromptIntake
from .project_store import ProjectIntentStore, ProjectStoreError
from .repository import InvalidRevisionError, JourneyRepository, RevisionNotFoundError


MAX_AGENT_TOOL_OUTPUT_BYTES = 256 * 1024


class AgentToolCallError(RuntimeError):
    """A safe, user-presentable failure at the closed tool boundary."""


class ReadOnlyAgentToolRuntime:
    """Execute the bounded non-mutating tools in the published catalog."""

    def __init__(self, repository: JourneyRepository, project_store: ProjectIntentStore):
        self._repository = repository
        self._project_store = project_store
        self._descriptors = {item.name: item for item in exposed_codex_tools()}

    @property
    def tool_specs(self) -> tuple[dict[str, Any], ...]:
        return (
            {
                "type": "namespace",
                "name": "ariad",
                "description": "Read-only Ariad fabrication intake, planning, and evidence tools.",
                "tools": [
                    {
                        "type": "function",
                        "name": item.name.removeprefix("ariad."),
                        "description": item.description,
                        "inputSchema": item.to_dict()["input_schema"],
                    }
                    for item in self._descriptors.values()
                ],
            },
        )

    def execute(self, name: str, arguments: Mapping[str, Any]) -> str:
        descriptor = self._descriptors.get(name)
        if descriptor is None:
            raise AgentToolCallError("Ariad refused an unknown or unavailable tool.")
        properties = descriptor.input_schema["properties"]
        if set(arguments) != set(properties):
            raise AgentToolCallError("Ariad refused arguments outside the closed tool contract.")
        try:
            if name == "ariad.capture_idea":
                result = self._capture_idea(arguments)
            elif name == "ariad.list_evidence":
                result = self._list_evidence(arguments)
            elif name == "ariad.read_evidence":
                result = self._read_evidence(arguments)
            elif name == "ariad.propose_design_plan":
                result = self._propose_design_plan(arguments)
            else:  # pragma: no cover - catalog and dispatch are asserted together
                raise AgentToolCallError("Ariad tool dispatch is unavailable.")
        except AgentToolCallError:
            raise
        except (InvalidRevisionError, ProjectStoreError, RevisionNotFoundError, ValueError) as exc:
            raise AgentToolCallError(str(exc)) from exc
        rendered = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if len(rendered.encode("utf-8")) > MAX_AGENT_TOOL_OUTPUT_BYTES:
            raise AgentToolCallError("Ariad refused a tool result above the output ceiling.")
        return rendered

    @staticmethod
    def _capture_idea(arguments: Mapping[str, Any]) -> dict[str, Any]:
        prompt = arguments.get("prompt")
        if not isinstance(prompt, str):
            raise AgentToolCallError("The fabrication idea must be text.")
        intake = PromptIntake(prompt)
        proposal = IntentProposal(
            lane=CapabilityLane.PLANNING_ONLY,
            summary=" ".join(intake.prompt.split())[:512],
            questions=("Confirm purpose, dimensions, constraints, and intended process.",),
        )
        route = CurrentCapabilityRouter().route(intake, proposal)
        return {
            "tool_contract": "1.0.0",
            "intake": intake.to_dict(),
            "route": route.to_dict(),
            "persisted": False,
            "executed": False,
            "hardware_actions": False,
            "claim_boundary": "Intent captured only; no CAD, validation, slicing, or printing occurred.",
        }

    def _list_evidence(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        offset = arguments.get("offset")
        limit = arguments.get("limit")
        if type(offset) is not int or not 0 <= offset <= 500:
            raise AgentToolCallError("Evidence offset must be an integer from 0 through 500.")
        if type(limit) is not int or not 1 <= limit <= 200:
            raise AgentToolCallError("Evidence limit must be an integer from 1 through 200.")
        return self._repository.list_revisions(offset=offset, limit=limit).model_dump(mode="json")

    def _read_evidence(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        job_id = arguments.get("job_id")
        revision_id = arguments.get("revision_id")
        if not isinstance(job_id, str) or not 1 <= len(job_id) <= 128:
            raise AgentToolCallError("Evidence job_id is invalid.")
        if not isinstance(revision_id, str) or not 1 <= len(revision_id) <= 128:
            raise AgentToolCallError("Evidence revision_id is invalid.")
        return self._repository.get_revision(job_id, revision_id).model_dump(mode="json")

    def _propose_design_plan(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        project_id = arguments.get("project_id")
        if (
            not isinstance(project_id, str)
            or not project_id.startswith("project_")
            or len(project_id) != 40
        ):
            raise AgentToolCallError("Design-plan project_id is invalid.")
        brief = self._project_store.get_brief(project_id)
        if brief is None:
            raise AgentToolCallError("An R0 Brief is required before Design planning.")
        lane = arguments.get("lane")
        if lane not in {"functional_parametric", "organic_mesh", "hybrid", "undecided"}:
            raise AgentToolCallError("Design-plan lane is invalid.")
        strategy = arguments.get("geometry_strategy")
        if not isinstance(strategy, str) or not strategy.strip() or len(strategy.strip()) > 2_000:
            raise AgentToolCallError("Design-plan geometry strategy is invalid.")
        proposal: dict[str, Any] = {
            "lane": lane,
            "geometry_strategy": strategy.strip(),
        }
        for field_name in (
            "critical_features",
            "assembly_interfaces",
            "constraints",
            "unresolved_questions",
        ):
            items = arguments.get(field_name)
            if not isinstance(items, list) or len(items) > 20:
                raise AgentToolCallError(f"Design-plan {field_name} is invalid.")
            cleaned: list[str] = []
            for item in items:
                if not isinstance(item, str) or not item.strip() or len(item.strip()) > 512:
                    raise AgentToolCallError(f"Design-plan {field_name} is invalid.")
                cleaned.append(item.strip())
            proposal[field_name] = cleaned
        status = (
            "needs_input"
            if lane == "undecided" or proposal["unresolved_questions"]
            else "planning_complete"
        )
        return {
            "tool_contract": "1.1.0",
            "project_id": project_id,
            "job_id": brief.job_id,
            "revision_id": brief.revision_id,
            "brief_draft_sha256": brief.draft_sha256,
            "proposal": proposal,
            "status": status,
            "persisted": False,
            "evidence_mode": "model_proposal",
            "design_evidence_level": None,
            "cad_generated": False,
            "fabrication_started": False,
            "hardware_actions": False,
            "claim_boundary": "Codex proposed Design-plan fields only; the user must review and save them in Ariad. No CAD or R1 evidence exists.",
        }


__all__ = [
    "AgentToolCallError",
    "MAX_AGENT_TOOL_OUTPUT_BYTES",
    "ReadOnlyAgentToolRuntime",
]
