"""Universal prompt capture and honest current-capability routing.

Prompt acceptance is deliberately broader than execution.  A semantic provider
may propose a lane and a draft PartSpec, but this policy layer owns what Ariad
can honestly do today.  It never launches CAD, slicing, network, or hardware.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .domain import PartSpec


INTAKE_SCHEMA_VERSION = "1.0.0"
MAX_PROMPT_BYTES = 16 * 1024
MAX_SUMMARY_CHARS = 512
MAX_REASON_CHARS = 512
MAX_QUESTIONS = 12
MAX_QUESTION_CHARS = 256
MAX_ASSUMPTIONS = 12
MAX_ASSUMPTION_CHARS = 256
MAX_INTENT_PROPOSAL_BYTES = 16 * 1024


class CapabilityLane(str, Enum):
    REGISTERED_BENCHMARK = "registered_benchmark"
    FUNCTIONAL_PARAMETRIC_CAD = "functional_parametric_cad"
    ORGANIC_MESH = "organic_mesh"
    PLANNING_ONLY = "planning_only"
    UNSUPPORTED = "unsupported"


class RouteStatus(str, Enum):
    DEMO_AVAILABLE = "demo_available"
    NEEDS_INPUT = "needs_input"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    UNSUPPORTED = "unsupported"


class EvidenceMode(str, Enum):
    REAL = "real"
    MODEL_PROPOSAL = "model_proposal"
    UNAVAILABLE = "unavailable"


INTENT_PROPOSAL_JSON_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "lane",
            "summary",
            "questions",
            "assumptions",
            "benchmark_id",
            "part_spec",
        ],
        "properties": {
            "lane": {"type": "string", "enum": [item.value for item in CapabilityLane]},
            "summary": {"type": "string", "minLength": 1, "maxLength": MAX_SUMMARY_CHARS},
            "questions": {
                "type": "array",
                "maxItems": MAX_QUESTIONS,
                "items": {"type": "string", "minLength": 1, "maxLength": MAX_QUESTION_CHARS},
            },
            "assumptions": {
                "type": "array",
                "maxItems": MAX_ASSUMPTIONS,
                "items": {"type": "string", "minLength": 1, "maxLength": MAX_ASSUMPTION_CHARS},
            },
            "benchmark_id": {"type": ["string", "null"], "maxLength": 128},
            # Classification and clarification only. A separately versioned PartSpec
            # schema is required before model-authored specifications can cross here.
            "part_spec": {"type": "null"},
        },
    }
)


def _text(value: Any, name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{name} is required")
    if len(normalized) > maximum:
        raise ValueError(f"{name} cannot exceed {maximum} characters")
    return normalized


def _text_items(
    value: Sequence[str],
    name: str,
    *,
    maximum_items: int,
    maximum_chars: int,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be an array")
    if len(value) > maximum_items:
        raise ValueError(f"{name} cannot contain more than {maximum_items} items")
    result = tuple(_text(item, f"{name} item", maximum=maximum_chars) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} cannot contain duplicates")
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"intent proposal contains duplicate key {key!r}")
        result[key] = value
    return result


def decode_intent_proposal(raw: str | bytes) -> "IntentProposal":
    """Decode one bounded strict Structured Output into an untrusted proposal.

    This function performs no network call and grants no execution capability.
    It is the local acceptance boundary for a future GPT-5.6 Responses provider.
    """

    if isinstance(raw, str):
        encoded = raw.encode("utf-8")
    elif isinstance(raw, bytes):
        encoded = raw
    else:
        raise ValueError("intent proposal must be UTF-8 JSON text")
    if len(encoded) > MAX_INTENT_PROPOSAL_BYTES:
        raise ValueError(
            f"intent proposal cannot exceed {MAX_INTENT_PROPOSAL_BYTES} UTF-8 bytes"
        )
    try:
        text = encoded.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"intent proposal contains non-finite value {item}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("intent proposal must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("intent proposal must be an object")
    required = set(INTENT_PROPOSAL_JSON_SCHEMA["required"])
    if set(value) != required:
        missing = sorted(required - set(value))
        extra = sorted(set(value) - required)
        raise ValueError(f"intent proposal fields do not match schema; missing={missing}, extra={extra}")
    if value["part_spec"] is not None:
        raise ValueError("model-authored part_spec is not accepted by this provider boundary")
    if value["benchmark_id"] is not None and not isinstance(value["benchmark_id"], str):
        raise ValueError("benchmark_id must be a string or null")
    try:
        return IntentProposal(
            lane=CapabilityLane(value["lane"]),
            summary=value["summary"],
            questions=value["questions"],
            assumptions=value["assumptions"],
            benchmark_id=value["benchmark_id"],
            part_spec=None,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"intent proposal violates the strict contract: {exc}") from exc


def openai_intent_text_format() -> dict[str, Any]:
    """Return a fresh Responses API ``text.format`` strict-schema value."""

    return {
        "type": "json_schema",
        "name": "ariad_intent_proposal_v1",
        "strict": True,
        "schema": deepcopy(dict(INTENT_PROPOSAL_JSON_SCHEMA)),
    }


@dataclass(frozen=True)
class PromptIntake:
    prompt: str
    intake_id: str = ""
    schema_version: str = INTAKE_SCHEMA_VERSION
    hardware_actions: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != INTAKE_SCHEMA_VERSION:
            raise ValueError("unsupported intake schema_version")
        if not isinstance(self.prompt, str):
            raise ValueError("prompt must be a string")
        prompt = self.prompt.strip()
        if not prompt:
            raise ValueError("prompt is required")
        if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise ValueError(f"prompt cannot exceed {MAX_PROMPT_BYTES} UTF-8 bytes")
        object.__setattr__(self, "prompt", prompt)
        intake_id = self.intake_id or f"intake_{uuid4().hex}"
        if not intake_id.startswith("intake_") or len(intake_id) > 135:
            raise ValueError("intake_id has an invalid format")
        object.__setattr__(self, "intake_id", intake_id)
        if self.hardware_actions is not False:
            raise ValueError("prompt intake cannot enable hardware actions")

    @property
    def prompt_sha256(self) -> str:
        return sha256(self.prompt.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "intake_id": self.intake_id,
            "prompt": self.prompt,
            "prompt_sha256": self.prompt_sha256,
            "hardware_actions": False,
        }


@dataclass(frozen=True)
class IntentProposal:
    """Untrusted semantic-provider output before capability policy is applied."""

    lane: CapabilityLane
    summary: str
    questions: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    part_spec: PartSpec | None = None
    benchmark_id: str | None = None
    evidence_mode: EvidenceMode = EvidenceMode.MODEL_PROPOSAL

    def __post_init__(self) -> None:
        object.__setattr__(self, "lane", CapabilityLane(self.lane))
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", maximum=MAX_SUMMARY_CHARS)
        )
        object.__setattr__(
            self,
            "questions",
            _text_items(
                self.questions,
                "questions",
                maximum_items=MAX_QUESTIONS,
                maximum_chars=MAX_QUESTION_CHARS,
            ),
        )
        object.__setattr__(
            self,
            "assumptions",
            _text_items(
                self.assumptions,
                "assumptions",
                maximum_items=MAX_ASSUMPTIONS,
                maximum_chars=MAX_ASSUMPTION_CHARS,
            ),
        )
        if self.part_spec is not None and not isinstance(self.part_spec, PartSpec):
            raise ValueError("part_spec must be a PartSpec")
        if self.benchmark_id is not None:
            object.__setattr__(
                self,
                "benchmark_id",
                _text(self.benchmark_id, "benchmark_id", maximum=128),
            )
        object.__setattr__(self, "evidence_mode", EvidenceMode(self.evidence_mode))
        if self.evidence_mode is not EvidenceMode.MODEL_PROPOSAL:
            raise ValueError("semantic intent proposals must remain model_proposal evidence")


@dataclass(frozen=True)
class CapabilityRoute:
    intake_id: str
    prompt_sha256: str
    lane: CapabilityLane
    status: RouteStatus
    summary: str
    reason: str
    questions: tuple[str, ...]
    assumptions: tuple[str, ...]
    part_spec: PartSpec | None
    available_targets: tuple[str, ...]
    evidence_mode: EvidenceMode
    hardware_actions: bool = False
    physical_validation: bool = False
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not self.intake_id.startswith("intake_"):
            raise ValueError("route intake_id is invalid")
        if len(self.prompt_sha256) != 64:
            raise ValueError("route prompt_sha256 is invalid")
        object.__setattr__(self, "lane", CapabilityLane(self.lane))
        object.__setattr__(self, "status", RouteStatus(self.status))
        object.__setattr__(self, "evidence_mode", EvidenceMode(self.evidence_mode))
        object.__setattr__(
            self, "summary", _text(self.summary, "summary", maximum=MAX_SUMMARY_CHARS)
        )
        object.__setattr__(self, "reason", _text(self.reason, "reason", maximum=MAX_REASON_CHARS))
        if self.hardware_actions or self.physical_validation:
            raise ValueError("capability routes cannot claim hardware or physical validation")
        if not isinstance(self.metadata, Mapping) or any(
            not isinstance(key, str) for key in self.metadata
        ):
            raise ValueError("route metadata must be a string-keyed object")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        if self.status is RouteStatus.DEMO_AVAILABLE:
            if self.lane is not CapabilityLane.REGISTERED_BENCHMARK:
                raise ValueError("only the registered benchmark may be demo_available")
            if self.available_targets != ("golden_part_r2", "golden_part_r4"):
                raise ValueError("registered demo targets are closed")
            if self.evidence_mode is not EvidenceMode.REAL:
                raise ValueError("registered benchmark route must identify real evidence")
        elif self.available_targets:
            raise ValueError("unavailable routes cannot expose execution targets")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": INTAKE_SCHEMA_VERSION,
            "intake_id": self.intake_id,
            "prompt_sha256": self.prompt_sha256,
            "lane": self.lane.value,
            "status": self.status.value,
            "summary": self.summary,
            "reason": self.reason,
            "questions": list(self.questions),
            "assumptions": list(self.assumptions),
            "part_spec": self.part_spec.to_dict() if self.part_spec else None,
            "available_targets": list(self.available_targets),
            "evidence_mode": self.evidence_mode.value,
            "hardware_actions": False,
            "physical_validation": False,
            "metadata": dict(self.metadata),
        }


class CurrentCapabilityRouter:
    """Apply Ariad's current implementation boundary to a semantic proposal."""

    GOLDEN_PART_BENCHMARK_ID = "opengrow_stake_electronics_clamp_v1"

    def route(self, intake: PromptIntake, proposal: IntentProposal) -> CapabilityRoute:
        if not isinstance(intake, PromptIntake):
            raise TypeError("intake must be a PromptIntake")
        if not isinstance(proposal, IntentProposal):
            raise TypeError("proposal must be an IntentProposal")

        common = {
            "intake_id": intake.intake_id,
            "prompt_sha256": intake.prompt_sha256,
            "lane": proposal.lane,
            "summary": proposal.summary,
            "questions": proposal.questions,
            "assumptions": proposal.assumptions,
            "part_spec": proposal.part_spec,
            "hardware_actions": False,
            "physical_validation": False,
        }
        if proposal.lane is CapabilityLane.REGISTERED_BENCHMARK:
            if proposal.benchmark_id != self.GOLDEN_PART_BENCHMARK_ID:
                return CapabilityRoute(
                    **common,
                    status=RouteStatus.UNSUPPORTED,
                    reason="The requested benchmark is not in the executable allowlist.",
                    available_targets=(),
                    evidence_mode=EvidenceMode.UNAVAILABLE,
                    metadata={"requested_benchmark_id": proposal.benchmark_id},
                )
            return CapabilityRoute(
                **common,
                status=RouteStatus.DEMO_AVAILABLE,
                reason=(
                    "Ariad can run the fixed registered Golden Part through real R2 or R4 "
                    "digital evidence. This does not mean the prompt itself was converted to CAD."
                ),
                available_targets=("golden_part_r2", "golden_part_r4"),
                evidence_mode=EvidenceMode.REAL,
                metadata={"benchmark_id": self.GOLDEN_PART_BENCHMARK_ID},
            )
        if proposal.lane is CapabilityLane.FUNCTIONAL_PARAMETRIC_CAD:
            status = (
                RouteStatus.NEEDS_INPUT if proposal.questions else RouteStatus.PROVIDER_UNAVAILABLE
            )
            reason = (
                "Critical requirements remain unresolved before a CAD provider can be selected."
                if proposal.questions
                else "General prompt-to-parametric-CAD generation is planned but not executable yet."
            )
            return CapabilityRoute(
                **common,
                status=status,
                reason=reason,
                available_targets=(),
                evidence_mode=EvidenceMode.MODEL_PROPOSAL,
                metadata={"target_architecture": "editable_brep"},
            )
        if proposal.lane is CapabilityLane.ORGANIC_MESH:
            return CapabilityRoute(
                **common,
                status=RouteStatus.PROVIDER_UNAVAILABLE,
                reason=(
                    "Organic mesh generation and Blender cleanup are a separate planned lane; "
                    "no provider is connected."
                ),
                available_targets=(),
                evidence_mode=EvidenceMode.UNAVAILABLE,
                metadata={"target_architecture": "mesh_provider_then_cleanup"},
            )
        if proposal.lane is CapabilityLane.PLANNING_ONLY:
            return CapabilityRoute(
                **common,
                status=RouteStatus.NEEDS_INPUT,
                reason="The idea was captured, but it is not specific enough to select a design lane.",
                available_targets=(),
                evidence_mode=EvidenceMode.MODEL_PROPOSAL,
                metadata={},
            )
        return CapabilityRoute(
            **common,
            status=RouteStatus.UNSUPPORTED,
            reason="Ariad cannot safely route this request into its fabrication workflow.",
            available_targets=(),
            evidence_mode=EvidenceMode.UNAVAILABLE,
            metadata={},
        )


__all__ = [
    "CapabilityLane",
    "CapabilityRoute",
    "CurrentCapabilityRouter",
    "EvidenceMode",
    "INTAKE_SCHEMA_VERSION",
    "INTENT_PROPOSAL_JSON_SCHEMA",
    "IntentProposal",
    "MAX_INTENT_PROPOSAL_BYTES",
    "MAX_PROMPT_BYTES",
    "PromptIntake",
    "RouteStatus",
    "decode_intent_proposal",
    "openai_intent_text_format",
]
