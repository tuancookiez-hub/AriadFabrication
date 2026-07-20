"""Dependency-light constants shared by fabrication-package writers and readers."""

from __future__ import annotations


PRODUCTION_PACKAGE_REQUIRED_ROLES = (
    "part_spec",
    "cad_parameters",
    "cad_source",
    "exact_geometry",
    "geometry_validation_report",
    "printer_profile",
    "material_profile",
    "process_profile",
    "orientation_profile",
    "slicer_profile",
    "profile_bundle",
    "printability_policy",
    "oriented_geometry",
    "printability_report",
    "slicer_installation",
    "slicer_project",
    "gcode",
    "gcode_preflight",
    "slicer_run_report",
)

PRODUCTION_PACKAGE_REQUIRED_ROLE_SET = frozenset(
    PRODUCTION_PACKAGE_REQUIRED_ROLES
)
