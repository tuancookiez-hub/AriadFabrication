"""Profile-specific real slicer adapters and disconnected G-code preflight."""

from .gcode import GCodePreflightReport, GCodeSummary
from .profiles import (
    PROFILE_CONTRACT_VERSION,
    MaterialProfile,
    OrientationProfile,
    PrinterProfile,
    ProcessProfile,
    ProfileBundle,
)
from .printability import (
    PrintabilityCheck,
    PrintabilityReport,
    VALIDATOR_ID,
    VALIDATOR_VERSION,
    assess_golden_part_printability,
    write_printability_report,
)
from .pipeline import (
    FABRICATION_PIPELINE_VERSION,
    GoldenPartFabricationOutcome,
    GoldenPartFabricationPipeline,
)
from .prusaslicer import (
    ADAPTER_ID,
    ADAPTER_VERSION,
    ModelInfo,
    PrusaSlicerAdapter,
    SliceOutcome,
    SlicerInstallation,
)

__all__ = [
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "GCodePreflightReport",
    "GCodeSummary",
    "FABRICATION_PIPELINE_VERSION",
    "GoldenPartFabricationOutcome",
    "GoldenPartFabricationPipeline",
    "MaterialProfile",
    "ModelInfo",
    "OrientationProfile",
    "PROFILE_CONTRACT_VERSION",
    "PrinterProfile",
    "ProcessProfile",
    "ProfileBundle",
    "PrusaSlicerAdapter",
    "PrintabilityCheck",
    "PrintabilityReport",
    "SliceOutcome",
    "SlicerInstallation",
    "VALIDATOR_ID",
    "VALIDATOR_VERSION",
    "assess_golden_part_printability",
    "write_printability_report",
]
