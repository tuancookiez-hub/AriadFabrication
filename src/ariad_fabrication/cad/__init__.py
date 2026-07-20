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
__all__ = [
    "CAD_CONTRACT_VERSION",
    "CadArtifactDescriptor",
    "CadArtifactFormat",
    "CadBuildRequest",
    "CadBuildResult",
    "CadPipelineOutcome",
    "GoldenPartCadPipeline",
]


def __getattr__(name: str):
    if name in {"CadPipelineOutcome", "GoldenPartCadPipeline"}:
        from .pipeline import CadPipelineOutcome, GoldenPartCadPipeline

        return {
            "CadPipelineOutcome": CadPipelineOutcome,
            "GoldenPartCadPipeline": GoldenPartCadPipeline,
        }[name]
    raise AttributeError(name)
