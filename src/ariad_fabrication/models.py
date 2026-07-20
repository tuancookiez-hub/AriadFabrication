"""Compatibility exports for the versioned domain contracts.

New code should import from :mod:`ariad_fabrication.domain`. The aliases remain so
the existing fixture adapters can migrate independently during later milestones.
"""

from .domain import (
    Approval,
    Artifact,
    ArtifactManifest,
    Decision,
    FabricationJourney,
    FabricationStage,
    Finding,
    Job,
    PartSpec,
    Revision,
    StageEvent,
    StageRun,
    StageStatus,
)


PipelineStage = FabricationStage
PipelineState = FabricationJourney
PipelineEvent = StageEvent

__all__ = [
    "Approval",
    "Artifact",
    "ArtifactManifest",
    "Decision",
    "FabricationJourney",
    "FabricationStage",
    "Finding",
    "Job",
    "PartSpec",
    "PipelineEvent",
    "PipelineStage",
    "PipelineState",
    "Revision",
    "StageEvent",
    "StageRun",
    "StageStatus",
]
