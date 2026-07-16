"""Optional deterministic CAD worker contracts.

This package keeps CadQuery imports behind worker functions so the R0 contract
and Brief workflow continue to run without the ``cad`` optional dependency.
"""

from .contracts import (
    CAD_CONTRACT_VERSION,
    CadArtifactDescriptor,
    CadArtifactFormat,
    CadBuildRequest,
    CadBuildResult,
)
from .pipeline import CadPipelineOutcome, GoldenPartCadPipeline

__all__ = [
    "CAD_CONTRACT_VERSION",
    "CadArtifactDescriptor",
    "CadArtifactFormat",
    "CadBuildRequest",
    "CadBuildResult",
    "CadPipelineOutcome",
    "GoldenPartCadPipeline",
]
