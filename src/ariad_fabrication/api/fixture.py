"""Generate the deterministic, explicitly non-evidentiary M4 interface fixture."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any


JOB_ID = "job_interface_fixture"
REVISION_ID = "rev_interface_fixture"
FIXTURE_TIMESTAMP = "2026-07-16T08:00:00+00:00"
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
                "artifact_ids": [artifact["artifact_id"]]
                if stage == "fabrication_package"
                else [],
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
        "artifacts": [artifact],
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
        "artifacts": [artifact],
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
            "This compact record exercises package presentation. It contains no real CAD, "
            "slicer output, printer profile, G-code, physical observation, or manufacturing authority."
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
    gates = tuple(
        _generate_gate_fixture(output_root, golden_spec_path, scenario)
        for scenario in GATE_SCENARIOS
    )
    return (primary, *gates)


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


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


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
