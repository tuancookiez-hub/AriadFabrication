"""Intent parsing adapters for the Brief stage."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from .domain import BoundingBox, PartSpec, SpecStatus, SupportPolicy


class IntentParser(Protocol):
    """Interface implemented by deterministic and model-backed parsers."""

    def parse(self, prompt: str) -> PartSpec:
        ...


class IntentParseError(ValueError):
    """Raised when a natural-language request cannot become a valid PartSpec."""


class RuleBasedIntentParser:
    """Narrow offline parser for local development and deterministic tests.

    It extracts only explicit facts and records important omissions as unresolved
    questions. It never silently chooses material, tolerance, or support policy.
    """

    _dimension_pattern = re.compile(
        r"(?P<a>\d+(?:\.\d+)?)\s*(?:mm\s*)?"
        r"(?:x|\u00d7|by)\s*"
        r"(?P<b>\d+(?:\.\d+)?)\s*(?:mm\s*)?"
        r"(?:x|\u00d7|by)\s*"
        r"(?P<c>\d+(?:\.\d+)?)\s*mm?",
        re.IGNORECASE,
    )
    _tolerance_pattern = re.compile(
        r"toleranc\w*\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?)\s*mm",
        re.IGNORECASE,
    )
    _infill_pattern = re.compile(
        r"(?:(\d+(?:\.\d+)?)\s*%\s*infill|infill\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?)\s*%)",
        re.IGNORECASE,
    )
    _materials = ("PLA", "PETG", "ABS", "TPU", "ASA", "NYLON")
    _part_keywords = (
        "mounting bracket",
        "phone stand",
        "enclosure",
        "adapter",
        "bracket",
        "spacer",
        "gear",
        "hook",
        "case",
        "box",
        "stand",
        "fixture",
    )

    def parse(self, prompt: str) -> PartSpec:
        if not prompt or not prompt.strip():
            raise IntentParseError("A part description is required")

        text = " ".join(prompt.split())
        dimensions_match = self._dimension_pattern.search(text)
        if dimensions_match is None:
            raise IntentParseError(
                "Include three dimensions in millimetres, for example 40 x 20 x 5 mm"
            )

        part_type = self._find_part_type(text)
        material = next(
            (
                candidate
                for candidate in self._materials
                if re.search(rf"\b{candidate}\b", text, re.IGNORECASE)
            ),
            "UNKNOWN",
        )
        infill_match = self._infill_pattern.search(text)
        infill_pct = 20
        if infill_match is not None:
            infill_pct = int(float(infill_match.group(1) or infill_match.group(2)))

        tolerance_match = self._tolerance_pattern.search(text)
        tolerance_mm = (
            float(tolerance_match.group(1)) if tolerance_match is not None else None
        )
        if re.search(r"\b(?:without|avoid|no)\s+supports?\b", text, re.I):
            support_policy = SupportPolicy.AVOID
        elif re.search(
            r"\b(?:with|requires?|needs?)\s+supports?\b|"
            r"\bsupports?\s+required\b|\band\s+supports?\b",
            text,
            re.I,
        ):
            support_policy = SupportPolicy.REQUIRED
        else:
            support_policy = SupportPolicy.UNKNOWN

        dimensions = {
            "length": float(dimensions_match.group("a")),
            "width": float(dimensions_match.group("b")),
            "height": float(dimensions_match.group("c")),
        }
        unresolved_questions: list[str] = []
        if material == "UNKNOWN":
            unresolved_questions.append("Which printing material should be used?")
        if tolerance_mm is None:
            unresolved_questions.append("What dimensional tolerance should be used?")
        if support_policy is SupportPolicy.UNKNOWN:
            unresolved_questions.append("Should the design avoid, allow, or require supports?")

        return PartSpec(
            name=part_type.title(),
            purpose=text,
            part_type=part_type,
            bounding_box=BoundingBox.from_mapping(dimensions),
            material=material,
            status=SpecStatus.DRAFT,
            tolerance_mm=tolerance_mm,
            infill_pct=infill_pct,
            support_policy=support_policy,
            assumptions=(
                "The three supplied dimensions were interpreted as length x width x height.",
            ),
            unresolved_questions=tuple(unresolved_questions),
            notes=text,
            source="rule_based_parser",
        )

    def _find_part_type(self, text: str) -> str:
        lowered = text.lower()
        for keyword in self._part_keywords:
            if keyword in lowered:
                return keyword

        match = re.search(
            r"(?:make|create|print|build)\s+(?:a|an)\s+(.+?)(?:\s+\d|\s+using\b|\s+with\b|$)",
            text,
            re.IGNORECASE,
        )
        return match.group(1).strip(" .") if match else "custom part"


class OpenAIIntentParser:
    """Model-backed parser with an SDK-independent client boundary.

    Strict SDK schema enforcement is intentionally deferred to M5, but this
    adapter already consumes the same versioned runtime contract as every other
    intake provider.
    """

    def __init__(self, client: Any, model: str = "gpt-5.6") -> None:
        self.client = client
        self.model = model

    def parse(self, prompt: str) -> PartSpec:
        if not prompt or not prompt.strip():
            raise IntentParseError("A part description is required")

        response = self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Propose a draft manufacturing specification as JSON only. "
                        "Use schema_version '1.0.0', status 'draft', name, purpose, "
                        "part_type, bounding_box_mm, material, units, manufacturing_process, "
                        "tolerance_mm, infill_pct, support_policy, safety_class, features, "
                        "mating_requirements, load_cases, environment, printer_constraints, "
                        "datums, assembly_method, expected_lifetime_months, "
                        "preferred_orientation, surface_requirements, assumptions, "
                        "unresolved_questions, notes, and source. "
                        "bounding_box_mm must contain length, width, and height in mm. "
                        "Do not invent critical requirements: use UNKNOWN or null and add a "
                        "plain-language unresolved question."
                    ),
                },
                {"role": "user", "content": prompt.strip()},
            ],
        )
        raw = getattr(response, "output_text", None)
        if not raw:
            raise IntentParseError("The model returned no structured intent")

        try:
            value = json.loads(raw)
            if not isinstance(value, Mapping):
                raise TypeError("model output is not an object")
            return PartSpec.from_mapping(value)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise IntentParseError(f"Invalid structured intent: {exc}") from exc


def parser_from_callable(
    complete: Callable[[str], str | Mapping[str, Any]],
) -> IntentParser:
    """Create a parser adapter around any JSON-returning completion function."""

    class CallableIntentParser:
        def parse(self, prompt: str) -> PartSpec:
            result = complete(prompt)
            value = json.loads(result) if isinstance(result, str) else result
            if not isinstance(value, Mapping):
                raise IntentParseError("Completion must return a JSON object")
            try:
                return PartSpec.from_mapping(value)
            except (TypeError, ValueError) as exc:
                raise IntentParseError(str(exc)) from exc

    return CallableIntentParser()
