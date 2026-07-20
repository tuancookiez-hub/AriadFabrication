"""Generate the deterministic, explicitly non-evidentiary M4 interface fixture."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any


JOB_ID = "job_interface_fixture"
REVISION_ID = "rev_interface_fixture"
COMPARISON_REVISION_ID = "rev_interface_fixture_v2"
FIXTURE_TIMESTAMP = "2026-07-16T08:00:00+00:00"
COMPARISON_TIMESTAMP = "2026-07-16T08:05:00+00:00"
STAGES = (
    ("brief", "passed", "R0", "Confirmed fixture specification passed the Brief shape"),
    ("design", "passed", "R1", "Fixture design stage exposes editable-source metadata"),
    (
        "geometry_validation",
        "passed",
        "R2",
        "Fixture geometry stage exposes deterministic check events",
    ),
    (
        "printability_validation",
        "passed_with_warnings",
        "R3",
        "Fixture printability stage retains unresolved physical unknowns",
    ),
    ("slicing", "passed", "R4", "Fixture slicing stage exposes toolpath metadata"),
    (
        "fabrication_package",
        "passed_with_warnings",
        "R4",
        "Fixture package stage demonstrates the final digital handoff shape",
    ),
)

GATE_SCENARIOS = (
    {
        "slug": "needs_input",
        "job_status": "needs_input",
        "prior_stage_count": 0,
        "stage": "brief",
        "status": "needs_input",
        "summary": "Fixture Brief stopped because a critical mating dimension is missing",
        "error_message": "Stake diameter is required before the specification can reach R0.",
        "finding_code": "fixture.brief.missing_stake_diameter",
        "finding_title": "Critical dimension needs confirmation",
        "finding_severity": "warning",
        "finding_evidence": "The fixture request deliberately omits the mating stake diameter.",
        "remediation": "Confirm the measured stake diameter and desired clearance.",
        "manifest_available": True,
    },
    {
        "slug": "geometry_failed",
        "job_status": "failed",
        "prior_stage_count": 2,
        "stage": "geometry_validation",
        "status": "failed",
        "summary": "Fixture Geometry validation rejected an undersized radial wall",
        "error_message": "The measured radial wall is below the frozen minimum.",
        "finding_code": "fixture.geometry.radial_wall_below_minimum",
        "finding_title": "Radial wall is too thin",
        "finding_severity": "error",
        "finding_evidence": "Fixture measurement: 0.70 mm; required minimum: 1.20 mm.",
        "remediation": "Increase the body diameter or reduce the mating bore, then create a new revision.",
        "manifest_available": True,
    },
    {
        "slug": "printability_failed",
        "job_status": "failed",
        "prior_stage_count": 3,
        "stage": "printability_validation",
        "status": "failed",
        "summary": "Fixture Printability assessment rejected a build-volume overflow",
        "error_message": "The oriented model exceeds the selected fixture build volume.",
        "finding_code": "fixture.printability.outside_build_volume",
        "finding_title": "Oriented model exceeds the profile volume",
        "finding_severity": "error",
        "finding_evidence": "Fixture X extent: 228 mm; fixture profile limit: 220 mm.",
        "remediation": "Choose a compatible profile or revise and reorient the design.",
        "manifest_available": True,
    },
    {
        "slug": "package_incomplete",
        "job_status": "active",
        "prior_stage_count": 5,
        "stage": "fabrication_package",
        "status": "running",
        "summary": "Fixture Package assembly stopped before manifest publication",
        "error_message": None,
        "finding_code": "fixture.package.manifest_not_published",
        "finding_title": "Package manifest is not available",
        "finding_severity": "warning",
        "finding_evidence": "The fixture journey was persisted before package assembly completed.",
        "remediation": "Resume package assembly and publish a complete checksummed manifest.",
        "manifest_available": False,
    },
)

FIXTURE_INSPECTION_BOUNDARY = (
    "Interface fixture values demonstrate evidence presentation only. They are not CAD, "
    "slicer, manufacturing, or physical evidence."
)


def _complete_fixture_evidence() -> tuple[dict[str, Any], ...]:
    return (
        {
            "artifact_id": "art_fixture_geometry_report",
            "role": "geometry_validation_report",
            "path": "design/geometry_validation.json",
            "stage_run_id": "run_fixture_geometry_validation",
            "value": {
                "schema_version": "1.0.0-interface-fixture",
                "status": "passed",
                "passed": True,
                "evidence_level": "R2",
                "claim_boundary": FIXTURE_INSPECTION_BOUNDARY,
                "measurements": {
                    "design_envelope": {"x": 30.0, "y": 24.49, "z": 50.0},
                    "solid_body_count": 1,
                    "stake_bore_diameter": 12.6,
                },
                "checks": [
                    {
                        "check_id": "kernel_valid",
                        "description": "Fixture kernel-validity row",
                        "actual": True,
                        "expected": True,
                        "passed": True,
                        "tolerance_mm": None,
                    },
                    {
                        "check_id": "stake_bore_diameter",
                        "description": "Fixture stake bore matches the frozen target",
                        "actual": 12.6,
                        "expected": 12.6,
                        "passed": True,
                        "tolerance_mm": 0.2,
                    },
                    {
                        "check_id": "solid_body_count",
                        "description": "Fixture shape contains one body",
                        "actual": 1,
                        "expected": 1,
                        "passed": True,
                        "tolerance_mm": None,
                    },
                ],
                "warnings": [],
                "errors": [],
            },
        },
        {
            "artifact_id": "art_fixture_printer_profile",
            "role": "printer_profile",
            "path": "profiles/printer.json",
            "stage_run_id": "run_fixture_printability_validation",
            "value": {
                "schema_version": "1.0.0-interface-fixture",
                "profile_id": "fixture_open_fdm_220_v1",
                "name": "Fixture 220 mm FDM envelope",
                "status": "interface_fixture",
                "technology": "FDM",
                "build_volume_mm": {"x": 220.0, "y": 220.0, "z": 250.0},
                "nozzle_diameter_mm": 0.4,
                "extruder_count": 1,
                "claim_boundary": FIXTURE_INSPECTION_BOUNDARY,
            },
        },
        {
            "artifact_id": "art_fixture_material_profile",
            "role": "material_profile",
            "path": "profiles/material.json",
            "stage_run_id": "run_fixture_printability_validation",
            "value": {
                "schema_version": "1.0.0-interface-fixture",
                "profile_id": "fixture_petg_v1",
                "name": "Fixture PETG values",
                "status": "interface_fixture_uncalibrated",
                "material_type": "PETG",
                "selected_nozzle_temperature_c": 240.0,
                "selected_bed_temperature_c": 90.0,
                "fan_percent": {"minimum": 30, "maximum": 50},
                "claim_boundary": FIXTURE_INSPECTION_BOUNDARY,
            },
        },
        {
            "artifact_id": "art_fixture_process_profile",
            "role": "process_profile",
            "path": "profiles/process.json",
            "stage_run_id": "run_fixture_printability_validation",
            "value": {
                "schema_version": "1.0.0-interface-fixture",
                "profile_id": "fixture_020_no_support_v1",
                "name": "Fixture 0.20 mm process",
                "status": "interface_fixture",
                "layer_height_mm": 0.2,
                "perimeters": 3,
                "infill_percent": 30,
                "infill_pattern": "gyroid",
                "support_policy": "disabled",
                "claim_boundary": FIXTURE_INSPECTION_BOUNDARY,
            },
        },
        {
            "artifact_id": "art_fixture_orientation_profile",
            "role": "orientation_profile",
            "path": "profiles/orientation.json",
            "stage_run_id": "run_fixture_printability_validation",
            "value": {
                "schema_version": "1.0.0-interface-fixture",
                "orientation_id": "fixture_upright_centered_v1",
                "name": "Fixture upright centered orientation",
                "status": "interface_fixture",
                "source_up_axis": "Z",
                "ensure_on_bed": True,
                "placement": "centered",
                "claim_boundary": FIXTURE_INSPECTION_BOUNDARY,
            },
        },
        {
            "artifact_id": "art_fixture_printability_report",
            "role": "printability_report",
            "path": "printability/report.json",
            "stage_run_id": "run_fixture_printability_validation",
            "value": {
                "schema_version": "1.0.0-interface-fixture",
                "status": "passed_with_warnings",
                "passed": True,
                "evidence_level": "R3",
                "claim_boundary": FIXTURE_INSPECTION_BOUNDARY,
                "measurements": {
                    "bed_contact_area_mm2": 339.29,
                    "minimum_wall_mm": 4.0,
                    "oriented_size_mm": {"x": 30.0, "y": 24.49, "z": 50.0},
                },
                "checks": [
                    {
                        "check_id": "build_volume",
                        "category": "volume",
                        "description": "Fixture model fits the fixture profile envelope",
                        "actual": {"x": 30.0, "y": 24.49, "z": 50.0},
                        "requirement": {"x": 220.0, "y": 220.0, "z": 250.0},
                        "passed": True,
                        "remediation": "Select a compatible profile or revise the design.",
                    },
                    {
                        "check_id": "minimum_wall",
                        "category": "feature",
                        "description": "Fixture minimum wall exceeds the fixture rule",
                        "actual": 4.0,
                        "requirement": 1.2,
                        "passed": True,
                        "remediation": "Increase the wall in a new revision.",
                    },
                    {
                        "check_id": "support_policy",
                        "category": "process",
                        "description": "Fixture process keeps generated supports disabled",
                        "actual": "disabled",
                        "requirement": "disabled",
                        "passed": True,
                        "remediation": "Revise orientation or explicitly change the process.",
                    },
                ],
                "warnings": [
                    {
                        "code": "fixture.physical_behavior_unknown",
                        "title": "Physical behavior remains unknown",
                        "evidence": "These values are interface fixtures and were never printed.",
                        "physical_resolution": "Print and measure a separately recorded revision later.",
                    }
                ],
                "errors": [],
            },
        },
        {
            "artifact_id": "art_fixture_gcode_preflight",
            "role": "gcode_preflight",
            "path": "slicing/gcode_preflight.json",
            "stage_run_id": "run_fixture_slicing",
            "value": {
                "schema_version": "1.0.0-interface-fixture",
                "status": "passed",
                "passed": True,
                "evidence_level": "R4",
                "claim_boundary": FIXTURE_INSPECTION_BOUNDARY,
                "measurements": {},
                "checks": [
                    {
                        "check_id": "has_layers",
                        "measured": 250,
                        "requirement": "> 0 fixture layers",
                        "passed": True,
                    },
                    {
                        "check_id": "forbidden_commands",
                        "measured": [],
                        "requirement": "no forbidden commands",
                        "passed": True,
                    },
                    {
                        "check_id": "profile_layer_height",
                        "measured": "0.2",
                        "requirement": "0.2 mm",
                        "passed": True,
                    },
                ],
                "warnings": ["Fixture preflight is presentation data, not parsed G-code."],
                "errors": [],
            },
        },
    )


def generate_interface_fixture(output_root: Path, golden_spec_path: Path) -> Path:
    output_root = output_root.expanduser().resolve()
    golden_spec_path = golden_spec_path.expanduser().resolve()
    spec = json.loads(golden_spec_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError("Golden Part specification must contain a JSON object")
    revision_root = output_root / JOB_ID / "revisions" / REVISION_ID
    notes_dir = revision_root / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    note = (
        "ARIAD INTERFACE FIXTURE\n"
        "This file exists only to test artifact presentation and checksum-verified download.\n"
        "It is fixture evidence, not a fabrication package or physical result.\n"
    ).encode("utf-8")
    note_path = notes_dir / "interface-fixture.txt"
    note_path.write_bytes(note)
    stage_ids = [f"run_fixture_{stage}" for stage, *_ in STAGES]
    event_ids = [f"evt_fixture_{stage}" for stage, *_ in STAGES]
    finding_ids = [
        "finding_fixture_generic_profile",
        "finding_fixture_physical_unknowns",
    ]
    artifact = {
        "artifact_id": "art_fixture_note",
        "checksum_sha256": hashlib.sha256(note).hexdigest(),
        "created_at": FIXTURE_TIMESTAMP,
        "evidence_mode": "fixture",
        "job_id": JOB_ID,
        "media_type": "text/plain",
        "metadata": {"classification": "interface_fixture"},
        "parent_artifact_ids": [],
        "path": "notes/interface-fixture.txt",
        "producer": "ariad_interface_fixture_generator",
        "producer_version": "1.0.0",
        "revision_id": REVISION_ID,
        "role": "interface_fixture_note",
        "size_bytes": len(note),
        "stage_run_id": "run_fixture_fabrication_package",
    }
    artifacts = [artifact]
    artifacts.extend(
        _write_fixture_json_artifact(revision_root, descriptor)
        for descriptor in _complete_fixture_evidence()
    )
    artifact_ids_by_stage: dict[str, list[str]] = {}
    for item in artifacts:
        artifact_ids_by_stage.setdefault(str(item["stage_run_id"]), []).append(
            str(item["artifact_id"])
        )
    findings = [
        {
            "affected_geometry": None,
            "code": "fixture.generic_profile_uncalibrated",
            "created_at": FIXTURE_TIMESTAMP,
            "data": {"classification": "interface_fixture"},
            "evidence": "The displayed profile is fixture data and is not calibrated to hardware.",
            "evidence_mode": "fixture",
            "finding_id": finding_ids[0],
            "job_id": JOB_ID,
            "remediation": "Use a real recorded profile and physical measurements before R6.",
            "resolution": None,
            "resolved": False,
            "revision_id": REVISION_ID,
            "severity": "warning",
            "stage_run_id": "run_fixture_printability_validation",
            "title": "Fixture profile is not calibrated",
        },
        {
            "affected_geometry": None,
            "code": "fixture.physical_result_unavailable",
            "created_at": FIXTURE_TIMESTAMP,
            "data": {"classification": "interface_fixture"},
            "evidence": "No printer, material batch, photograph, or measurement belongs to this fixture.",
            "evidence_mode": "fixture",
            "finding_id": finding_ids[1],
            "job_id": JOB_ID,
            "remediation": "Record an actual print and measurements in a separate R6 revision.",
            "resolution": None,
            "resolved": False,
            "revision_id": REVISION_ID,
            "severity": "warning",
            "stage_run_id": "run_fixture_printability_validation",
            "title": "Physical behavior remains unknown",
        },
    ]
    events: list[dict[str, Any]] = []
    stage_runs: list[dict[str, Any]] = []
    for sequence, ((stage, status, evidence_level, summary), stage_id, event_id) in enumerate(
        zip(STAGES, stage_ids, event_ids, strict=True), start=1
    ):
        events.append(
            {
                "data": {"classification": "interface_fixture"},
                "event_id": event_id,
                "event_type": "fixture_stage_replayed",
                "job_id": JOB_ID,
                "message": summary,
                "revision_id": REVISION_ID,
                "sequence": sequence,
                "stage": stage,
                "stage_run_id": stage_id,
                "status": status,
                "timestamp": FIXTURE_TIMESTAMP,
            }
        )
        stage_runs.append(
            {
                "approval_ids": [],
                "artifact_ids": artifact_ids_by_stage.get(stage_id, []),
                "attempt": 1,
                "completed_at": FIXTURE_TIMESTAMP,
                "decision_ids": [],
                "error_message": None,
                "event_ids": [event_id],
                "evidence_level": evidence_level,
                "evidence_mode": "fixture",
                "finding_ids": finding_ids if stage == "printability_validation" else [],
                "input_artifact_ids": [],
                "job_id": JOB_ID,
                "revision_id": REVISION_ID,
                "stage": stage,
                "stage_run_id": stage_id,
                "started_at": FIXTURE_TIMESTAMP,
                "status": status,
                "summary": summary,
                "tool": {"name": "ariad_interface_fixture", "version": "1.0.0"},
            }
        )
    fixture_spec = deepcopy(spec)
    fixture_spec["name"] = "OpenGrow Stake Electronics Clamp — interface fixture"
    fixture_spec["source"] = "benchmarks/interface (fixture; not manufacturing evidence)"
    fixture_spec["notes"] = (
        "Deterministic UI shape fixture. No stage in this record establishes fabrication evidence."
    )
    journey = {
        "approvals": [],
        "artifacts": artifacts,
        "decisions": [],
        "events": events,
        "findings": findings,
        "job": {
            "created_at": FIXTURE_TIMESTAMP,
            "current_revision_id": REVISION_ID,
            "job_id": JOB_ID,
            "metadata": {
                "classification": "interface_fixture",
                "input_parser": "fixture",
                "physical_validation": False,
            },
            "request": "Replay the Golden Part stage shape for interface development only.",
            "status": "completed",
            "title": "OpenGrow Stake Electronics Clamp — interface fixture",
            "updated_at": FIXTURE_TIMESTAMP,
        },
        "revisions": [
            {
                "created_at": FIXTURE_TIMESTAMP,
                "job_id": JOB_ID,
                "number": 1,
                "parent_revision_id": None,
                "reason": "Deterministic M4 interface fixture",
                "revision_id": REVISION_ID,
                "spec": fixture_spec,
                "stage_run_ids": stage_ids,
            }
        ],
        "schema_version": "1.0.0",
        "stage_runs": stage_runs,
    }
    manifest = {
        "approvals": [],
        "artifacts": artifacts,
        "decisions": [],
        "findings": findings,
        "generated_at": FIXTURE_TIMESTAMP,
        "job_id": JOB_ID,
        "revision_id": REVISION_ID,
        "schema_version": "1.0.0",
        "stage_run_ids": stage_ids,
    }
    marker = {
        "allowed_claim": "Interface behavior demonstrated with fixture data only.",
        "classification": "interface_fixture",
        "evidence_mode": "fixture",
        "generated_at": FIXTURE_TIMESTAMP,
        "label": "INTERFACE FIXTURE — no fabrication or physical evidence",
        "physical_validation": False,
        "source_spec": golden_spec_path.name,
    }
    package = {
        "allowed_claim": "Interface fixture only — no fabrication evidence.",
        "claim_boundary": (
            "This compact record exercises package and evidence-inspector presentation. It "
            "contains fixture-shaped reports and profiles but no real CAD, slicer output, "
            "G-code, physical observation, or manufacturing authority."
        ),
        "classification": "interface_fixture_package",
        "evidence_level": None,
        "hardware": {
            "gcode_uploaded": False,
            "print_started": False,
            "printer_connected": False,
            "printer_selected": False,
        },
        "job_id": JOB_ID,
        "revision_id": REVISION_ID,
        "schema_version": "1.0.0-interface-fixture",
        "slicer": {},
        "status": "fixture",
        "unresolved_warning_findings": finding_ids,
    }
    _write_json(revision_root / "journey.json", journey)
    _write_json(revision_root / "manifest.json", manifest)
    _write_json(revision_root / "fixture.json", marker)
    _write_json(revision_root / "fabrication" / "package.json", package)
    return revision_root


def generate_interface_fixtures(output_root: Path, golden_spec_path: Path) -> tuple[Path, ...]:
    """Generate the complete deterministic M4 interface fixture family."""

    primary = generate_interface_fixture(output_root, golden_spec_path)
    comparison = _generate_comparison_fixture(primary)
    gates = tuple(
        _generate_gate_fixture(output_root, golden_spec_path, scenario)
        for scenario in GATE_SCENARIOS
    )
    return (primary, comparison, *gates)


def _generate_comparison_fixture(primary_root: Path) -> Path:
    """Create a deterministic child revision with a small, coherent persisted delta."""

    child_root = primary_root.parent / COMPARISON_REVISION_ID
    shutil.copytree(primary_root, child_root, dirs_exist_ok=True)

    journey = _read_json_object(primary_root / "journey.json")
    original_revision = deepcopy(journey["revisions"][0])
    original_stages = deepcopy(journey["stage_runs"])
    original_events = deepcopy(journey["events"])
    original_artifacts = deepcopy(journey["artifacts"])
    original_findings = deepcopy(journey["findings"])
    original_decisions = deepcopy(journey["decisions"])
    original_approvals = deepcopy(journey["approvals"])

    stage_ids = {
        str(item["stage_run_id"]): f"{item['stage_run_id']}_v2"
        for item in original_stages
    }
    event_ids = {
        str(item["event_id"]): f"{item['event_id']}_v2"
        for item in original_events
    }
    artifact_ids = {
        str(item["artifact_id"]): f"{item['artifact_id']}_v2"
        for item in original_artifacts
    }
    finding_ids = {
        str(item["finding_id"]): f"{item['finding_id']}_v2"
        for item in original_findings
    }
    decision_ids = {
        str(item["decision_id"]): f"{item['decision_id']}_v2"
        for item in original_decisions
    }
    approval_ids = {
        str(item["approval_id"]): f"{item['approval_id']}_v2"
        for item in original_approvals
    }

    child_events = deepcopy(original_events)
    for item in child_events:
        item["event_id"] = event_ids[str(item["event_id"])]
        item["revision_id"] = COMPARISON_REVISION_ID
        item["stage_run_id"] = stage_ids[str(item["stage_run_id"])]
        item["timestamp"] = COMPARISON_TIMESTAMP
        if item["stage"] == "design":
            item["message"] = "Fixture child revision records the revised bore and process request"

    child_findings = deepcopy(original_findings)
    for item in child_findings:
        item["finding_id"] = finding_ids[str(item["finding_id"])]
        item["revision_id"] = COMPARISON_REVISION_ID
        item["stage_run_id"] = stage_ids[str(item["stage_run_id"])]
        item["created_at"] = COMPARISON_TIMESTAMP

    child_decisions = deepcopy(original_decisions)
    for item in child_decisions:
        item["decision_id"] = decision_ids[str(item["decision_id"])]
        item["revision_id"] = COMPARISON_REVISION_ID
        if item.get("stage_run_id") is not None:
            item["stage_run_id"] = stage_ids[str(item["stage_run_id"])]
        item["created_at"] = COMPARISON_TIMESTAMP

    child_approvals = deepcopy(original_approvals)
    for item in child_approvals:
        item["approval_id"] = approval_ids[str(item["approval_id"])]
        item["revision_id"] = COMPARISON_REVISION_ID
        if item.get("stage_run_id") is not None:
            item["stage_run_id"] = stage_ids[str(item["stage_run_id"])]
        item["requested_at"] = COMPARISON_TIMESTAMP
        if item.get("decided_at") is not None:
            item["decided_at"] = COMPARISON_TIMESTAMP

    child_stages = deepcopy(original_stages)
    for item in child_stages:
        old_stage_id = str(item["stage_run_id"])
        item["stage_run_id"] = stage_ids[old_stage_id]
        item["revision_id"] = COMPARISON_REVISION_ID
        item["event_ids"] = [event_ids[str(value)] for value in item["event_ids"]]
        item["artifact_ids"] = [artifact_ids[str(value)] for value in item["artifact_ids"]]
        item["input_artifact_ids"] = [
            artifact_ids.get(str(value), str(value)) for value in item["input_artifact_ids"]
        ]
        item["finding_ids"] = [finding_ids[str(value)] for value in item["finding_ids"]]
        item["decision_ids"] = [decision_ids[str(value)] for value in item["decision_ids"]]
        item["approval_ids"] = [approval_ids[str(value)] for value in item["approval_ids"]]
        item["started_at"] = COMPARISON_TIMESTAMP
        if item.get("completed_at") is not None:
            item["completed_at"] = COMPARISON_TIMESTAMP
        if item["stage"] == "design":
            item["summary"] = "Fixture design stage records the revised bore and process request"

    note = (
        "ARIAD INTERFACE COMPARISON FIXTURE\n"
        "This child revision demonstrates persisted diffs only.\n"
        "It is fixture evidence, not a fabrication package or physical result.\n"
    ).encode("utf-8")
    (child_root / "notes" / "interface-fixture.txt").write_bytes(note)

    geometry_path = child_root / "design" / "geometry_validation.json"
    geometry = _read_json_object(geometry_path)
    geometry["measurements"]["stake_bore_diameter"] = 12.8
    for check in geometry["checks"]:
        if check["check_id"] == "stake_bore_diameter":
            check["actual"] = 12.8
            check["expected"] = 12.8
    _write_json(geometry_path, geometry)

    process_path = child_root / "profiles" / "process.json"
    process = _read_json_object(process_path)
    process["infill_percent"] = 35
    process["name"] = "Fixture 0.20 mm / 35% infill process"
    _write_json(process_path, process)

    child_artifacts = deepcopy(original_artifacts)
    for item in child_artifacts:
        item["artifact_id"] = artifact_ids[str(item["artifact_id"])]
        item["revision_id"] = COMPARISON_REVISION_ID
        item["stage_run_id"] = stage_ids[str(item["stage_run_id"])]
        item["parent_artifact_ids"] = [
            artifact_ids.get(str(value), str(value))
            for value in item["parent_artifact_ids"]
        ]
        item["created_at"] = COMPARISON_TIMESTAMP
        payload = (child_root / str(item["path"])).read_bytes()
        item["checksum_sha256"] = hashlib.sha256(payload).hexdigest()
        item["size_bytes"] = len(payload)

    child_spec = deepcopy(original_revision["spec"])
    child_spec["name"] = "OpenGrow Stake Electronics Clamp — comparison fixture v2"
    child_spec["infill_pct"] = 35
    child_spec["notes"] = (
        "Deterministic child fixture with a revised bore and process request. No stage in this "
        "record establishes fabrication evidence."
    )
    for feature in child_spec["features"]:
        if feature["feature_id"] == "stake_bore":
            feature["dimensions_mm"]["diameter"] = 12.8
            feature["notes"] = (
                "Fixture child request uses 0.8 mm nominal diametral clearance over a 12 mm stake."
            )
    child_spec["mating_requirements"][0]["clearance_mm"] = 0.8

    child_revision = deepcopy(original_revision)
    child_revision["created_at"] = COMPARISON_TIMESTAMP
    child_revision["number"] = 2
    child_revision["parent_revision_id"] = REVISION_ID
    child_revision["reason"] = "Deterministic M4 revision-comparison fixture"
    child_revision["revision_id"] = COMPARISON_REVISION_ID
    child_revision["spec"] = child_spec
    child_revision["stage_run_ids"] = [
        stage_ids[str(value)] for value in original_revision["stage_run_ids"]
    ]

    journey["approvals"] = [*original_approvals, *child_approvals]
    journey["artifacts"] = [*original_artifacts, *child_artifacts]
    journey["decisions"] = [*original_decisions, *child_decisions]
    journey["events"] = [*original_events, *child_events]
    journey["findings"] = [*original_findings, *child_findings]
    journey["revisions"] = [original_revision, child_revision]
    journey["stage_runs"] = [*original_stages, *child_stages]
    journey["job"]["current_revision_id"] = COMPARISON_REVISION_ID
    journey["job"]["title"] = "OpenGrow Stake Electronics Clamp — comparison fixture"
    journey["job"]["updated_at"] = COMPARISON_TIMESTAMP

    manifest = {
        "approvals": child_approvals,
        "artifacts": child_artifacts,
        "decisions": child_decisions,
        "findings": child_findings,
        "generated_at": COMPARISON_TIMESTAMP,
        "job_id": JOB_ID,
        "revision_id": COMPARISON_REVISION_ID,
        "schema_version": "1.0.0",
        "stage_run_ids": child_revision["stage_run_ids"],
    }
    marker = _read_json_object(primary_root / "fixture.json")
    marker["generated_at"] = COMPARISON_TIMESTAMP
    marker["label"] = "INTERFACE COMPARISON FIXTURE — child revision; no fabrication evidence"
    marker["comparison_fixture"] = True
    package = _read_json_object(primary_root / "fabrication" / "package.json")
    package["revision_id"] = COMPARISON_REVISION_ID
    package["unresolved_warning_findings"] = [
        finding_ids[str(value)] for value in package["unresolved_warning_findings"]
    ]

    _write_json(child_root / "journey.json", journey)
    _write_json(child_root / "manifest.json", manifest)
    _write_json(child_root / "fixture.json", marker)
    _write_json(child_root / "fabrication" / "package.json", package)
    return child_root


def _generate_gate_fixture(
    output_root: Path,
    golden_spec_path: Path,
    scenario: dict[str, Any],
) -> Path:
    output_root = output_root.expanduser().resolve()
    golden_spec_path = golden_spec_path.expanduser().resolve()
    spec = json.loads(golden_spec_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError("Golden Part specification must contain a JSON object")

    slug = str(scenario["slug"])
    job_id = f"job_interface_{slug}"
    revision_id = f"rev_interface_{slug}"
    revision_root = output_root / job_id / "revisions" / revision_id
    revision_root.mkdir(parents=True, exist_ok=True)

    prior_stages = list(STAGES[: int(scenario["prior_stage_count"])])
    stop_stage = str(scenario["stage"])
    stop_status = str(scenario["status"])
    stage_rows = [*prior_stages, (stop_stage, stop_status, None, str(scenario["summary"]))]
    stage_ids = [f"run_fixture_{slug}_{stage}" for stage, *_ in stage_rows]
    finding_id = f"finding_fixture_{slug}"
    events: list[dict[str, Any]] = []
    stage_runs: list[dict[str, Any]] = []

    for sequence, ((stage, status, evidence_level, summary), stage_id) in enumerate(
        zip(stage_rows, stage_ids, strict=True), start=1
    ):
        event_id = f"evt_fixture_{slug}_{stage}"
        is_stop = stage == stop_stage
        events.append(
            {
                "data": {"classification": "interface_fixture", "scenario": slug},
                "event_id": event_id,
                "event_type": "fixture_gate_stopped" if is_stop else "fixture_stage_replayed",
                "job_id": job_id,
                "message": summary,
                "revision_id": revision_id,
                "sequence": sequence,
                "stage": stage,
                "stage_run_id": stage_id,
                "status": status,
                "timestamp": FIXTURE_TIMESTAMP,
            }
        )
        completed_at = FIXTURE_TIMESTAMP if status in {"passed", "passed_with_warnings", "failed"} else None
        stage_runs.append(
            {
                "approval_ids": [],
                "artifact_ids": [],
                "attempt": 1,
                "completed_at": completed_at,
                "decision_ids": [],
                "error_message": scenario["error_message"] if is_stop else None,
                "event_ids": [event_id],
                "evidence_level": evidence_level,
                "evidence_mode": "fixture",
                "finding_ids": [finding_id] if is_stop else [],
                "input_artifact_ids": [],
                "job_id": job_id,
                "revision_id": revision_id,
                "stage": stage,
                "stage_run_id": stage_id,
                "started_at": FIXTURE_TIMESTAMP,
                "status": status,
                "summary": summary,
                "tool": {"name": "ariad_interface_fixture", "version": "1.0.0"},
            }
        )

    finding = {
        "affected_geometry": None,
        "code": scenario["finding_code"],
        "created_at": FIXTURE_TIMESTAMP,
        "data": {"classification": "interface_fixture", "scenario": slug},
        "evidence": scenario["finding_evidence"],
        "evidence_mode": "fixture",
        "finding_id": finding_id,
        "job_id": job_id,
        "remediation": scenario["remediation"],
        "resolution": None,
        "resolved": False,
        "revision_id": revision_id,
        "severity": scenario["finding_severity"],
        "stage_run_id": stage_ids[-1],
        "title": scenario["finding_title"],
    }
    fixture_spec = deepcopy(spec)
    fixture_spec["name"] = f"OpenGrow gate fixture — {slug.replace('_', ' ')}"
    fixture_spec["source"] = "benchmarks/interface (fixture; not manufacturing evidence)"
    fixture_spec["notes"] = (
        f"Deterministic {slug} interface fixture. No stage establishes fabrication evidence."
    )
    journey = {
        "approvals": [],
        "artifacts": [],
        "decisions": [],
        "events": events,
        "findings": [finding],
        "job": {
            "created_at": FIXTURE_TIMESTAMP,
            "current_revision_id": revision_id,
            "job_id": job_id,
            "metadata": {
                "classification": "interface_fixture",
                "physical_validation": False,
                "scenario": slug,
            },
            "request": f"Demonstrate the {slug.replace('_', ' ')} interface gate with fixture data.",
            "status": scenario["job_status"],
            "title": f"Ariad gate fixture — {slug.replace('_', ' ')}",
            "updated_at": FIXTURE_TIMESTAMP,
        },
        "revisions": [
            {
                "created_at": FIXTURE_TIMESTAMP,
                "job_id": job_id,
                "number": 1,
                "parent_revision_id": None,
                "reason": f"Deterministic M4 {slug} fixture",
                "revision_id": revision_id,
                "spec": fixture_spec,
                "stage_run_ids": stage_ids,
            }
        ],
        "schema_version": "1.0.0",
        "stage_runs": stage_runs,
    }
    marker = {
        "allowed_claim": "Interface gate behavior demonstrated with fixture data only.",
        "classification": "interface_fixture",
        "evidence_mode": "fixture",
        "generated_at": FIXTURE_TIMESTAMP,
        "label": f"INTERFACE FIXTURE — {slug.replace('_', ' ')}; no fabrication evidence",
        "physical_validation": False,
        "scenario": slug,
        "source_spec": golden_spec_path.name,
    }
    _write_json(revision_root / "journey.json", journey)
    _write_json(revision_root / "fixture.json", marker)
    if bool(scenario["manifest_available"]):
        manifest = {
            "approvals": [],
            "artifacts": [],
            "decisions": [],
            "findings": [finding],
            "generated_at": FIXTURE_TIMESTAMP,
            "job_id": job_id,
            "revision_id": revision_id,
            "schema_version": "1.0.0",
            "stage_run_ids": stage_ids,
        }
        _write_json(revision_root / "manifest.json", manifest)
    return revision_root


def _write_fixture_json_artifact(
    revision_root: Path,
    descriptor: dict[str, Any],
) -> dict[str, Any]:
    relative_path = str(descriptor["path"])
    output = revision_root / relative_path
    value = descriptor["value"]
    if not isinstance(value, dict):
        raise ValueError("Fixture inspection artifact must contain a JSON object")
    _write_json(output, value)
    payload = output.read_bytes()
    return {
        "artifact_id": str(descriptor["artifact_id"]),
        "checksum_sha256": hashlib.sha256(payload).hexdigest(),
        "created_at": FIXTURE_TIMESTAMP,
        "evidence_mode": "fixture",
        "job_id": JOB_ID,
        "media_type": "application/json",
        "metadata": {
            "classification": "interface_fixture",
            "format": "json",
        },
        "parent_artifact_ids": [],
        "path": relative_path,
        "producer": "ariad_interface_fixture_generator",
        "producer_version": "1.0.0",
        "revision_id": REVISION_ID,
        "role": str(descriptor["role"]),
        "size_bytes": len(payload),
        "stage_run_id": str(descriptor["stage_run_id"]),
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"fixture source must contain a JSON object: {path}")
    return value


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Generate Ariad's deterministic, non-evidentiary M4 interface fixture."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--golden-spec",
        type=Path,
        default=Path("benchmarks/golden_part/part_spec.json"),
    )
    args = parser.parse_args(argv)
    for revision_root in generate_interface_fixtures(args.output, args.golden_spec):
        print(revision_root)


if __name__ == "__main__":
    main()
