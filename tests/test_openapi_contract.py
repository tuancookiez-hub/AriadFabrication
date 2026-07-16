import json
from pathlib import Path
import tempfile
import unittest

from ariad_fabrication.api.openapi import (
    canonical_openapi_bytes,
    check_openapi_snapshot,
    generate_openapi_document,
    write_openapi_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "schemas" / "v1" / "interface-api.openapi.json"


class OpenApiContractTests(unittest.TestCase):
    def test_committed_snapshot_matches_the_application(self):
        check_openapi_snapshot(SNAPSHOT)
        self.assertEqual(SNAPSHOT.read_bytes(), canonical_openapi_bytes())

    def test_schema_exposes_only_the_read_contract(self):
        document = generate_openapi_document()
        self.assertEqual(
            set(document["paths"]),
            {
                "/api/v1/health",
                "/api/v1/revision-comparison",
                "/api/v1/revisions",
                "/api/v1/revisions/{job_id}/{revision_id}",
                "/api/v1/revisions/{job_id}/{revision_id}/artifacts/{artifact_id}",
            },
        )
        for path in document["paths"].values():
            self.assertEqual(set(path) - {"parameters"}, {"get"})

        capabilities = document["components"]["schemas"]["CapabilitiesView"]
        self.assertEqual(capabilities["properties"]["read_only"]["const"], True)
        self.assertEqual(capabilities["properties"]["hardware_actions"]["const"], False)

        health = document["components"]["schemas"]["HealthResponse"]["properties"]
        self.assertEqual(health["schema_version"]["const"], "1.6.0")
        self.assertEqual(health["service"]["const"], "ariad-interface-api")
        self.assertEqual(health["status"]["const"], "ok")

    def test_response_models_do_not_hide_guaranteed_fields_as_optional(self):
        schemas = generate_openapi_document()["components"]["schemas"]
        response_models = {
            "ApprovalView",
            "ArtifactView",
            "CapabilitiesView",
            "ComparisonAreaSummaryView",
            "ComparisonChangeView",
            "ComparisonRevisionView",
            "DecisionView",
            "EventView",
            "ErrorResponse",
            "FindingView",
            "GcodeSummaryView",
            "HardwareView",
            "HealthResponse",
            "InspectionArtifactView",
            "InspectionCheckView",
            "InspectionFeatureView",
            "InspectionMessageView",
            "InspectionProfileView",
            "InspectionReportView",
            "InspectionUnavailableView",
            "InspectionView",
            "JobView",
            "PackageView",
            "RevisionDetailResponse",
            "RevisionComparisonResponse",
            "RevisionListResponse",
            "RevisionListWindowView",
            "RevisionSummary",
            "RevisionView",
            "SourceView",
            "StageView",
            "ToolView",
        }
        for model_name in response_models:
            with self.subTest(model=model_name):
                schema = schemas[model_name]
                self.assertEqual(set(schema["required"]), set(schema["properties"]))

    def test_persisted_state_vocabularies_and_hardware_boundaries_are_explicit(self):
        schemas = generate_openapi_document()["components"]["schemas"]
        expected_enums = {
            "ApprovalStatus": {"requested", "granted", "rejected", "revoked"},
            "DecisionActor": {"user", "model", "system"},
            "EvidenceLevel": {"R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7"},
            "EvidenceMode": {"real", "simulated", "fixture", "unavailable"},
            "FabricationStage": {
                "brief",
                "design",
                "geometry_validation",
                "printability_validation",
                "slicing",
                "fabrication_package",
                "manufacturing",
            },
            "FindingSeverity": {"info", "warning", "error", "critical"},
            "InspectionProfileStatus": {
                "experimental_analysis_only",
                "experimental_uncalibrated",
                "interface_fixture",
                "interface_fixture_uncalibrated",
            },
            "InspectionReportStatus": {"passed", "passed_with_warnings", "failed"},
            "JobStatus": {
                "active",
                "needs_input",
                "ready_for_design",
                "design_generated",
                "geometry_verified",
                "printability_assessed",
                "slicer_verified",
                "failed",
                "completed",
                "cancelled",
            },
            "PackageStatus": {
                "slicer_verified",
                "slicer_verified_with_physical_unknowns",
                "fixture",
            },
            "StageStatus": {
                "waiting",
                "running",
                "needs_input",
                "passed",
                "passed_with_warnings",
                "failed",
                "cancelled",
                "superseded",
            },
        }
        for name, values in expected_enums.items():
            with self.subTest(enum=name):
                self.assertEqual(set(schemas[name]["enum"]), values)

        hardware = schemas["HardwareView"]["properties"]
        self.assertTrue(all(field["const"] is False for field in hardware.values()))
        stage = schemas["StageView"]["properties"]
        self.assertEqual(stage["stage"]["$ref"], "#/components/schemas/FabricationStage")
        self.assertEqual(stage["status"]["$ref"], "#/components/schemas/StageStatus")
        self.assertEqual(
            stage["decisions"]["items"]["$ref"],
            "#/components/schemas/DecisionView",
        )
        self.assertEqual(
            stage["approvals"]["items"]["$ref"],
            "#/components/schemas/ApprovalView",
        )

    def test_persisted_timestamps_are_explicit_date_time_contracts(self):
        schemas = generate_openapi_document()["components"]["schemas"]
        timestamp_fields = {
            "ApprovalView": {"requested_at", "decided_at"},
            "DecisionView": {"created_at"},
            "EventView": {"timestamp"},
            "JobView": {"created_at", "updated_at"},
            "RevisionSummary": {"updated_at"},
            "RevisionView": {"created_at"},
            "StageView": {"started_at", "completed_at"},
        }
        for model_name, field_names in timestamp_fields.items():
            for field_name in field_names:
                with self.subTest(model=model_name, field=field_name):
                    field = schemas[model_name]["properties"][field_name]
                    choices = field.get("anyOf", [field])
                    string_choice = next(
                        item for item in choices if item.get("type") == "string"
                    )
                    self.assertEqual(string_choice["format"], "date-time")

    def test_revision_listing_contract_discloses_and_bounds_its_window(self):
        document = generate_openapi_document()
        operation = document["paths"]["/api/v1/revisions"]["get"]
        parameters = {item["name"]: item for item in operation["parameters"]}

        self.assertEqual(set(parameters), {"offset", "limit"})
        self.assertEqual(parameters["offset"]["schema"]["default"], 0)
        self.assertEqual(parameters["offset"]["schema"]["minimum"], 0)
        self.assertEqual(parameters["offset"]["schema"]["maximum"], 500)
        self.assertEqual(parameters["limit"]["schema"]["default"], 100)
        self.assertEqual(parameters["limit"]["schema"]["minimum"], 1)
        self.assertEqual(parameters["limit"]["schema"]["maximum"], 200)

        window = document["components"]["schemas"]["RevisionListWindowView"]
        self.assertEqual(set(window["required"]), set(window["properties"]))
        self.assertEqual(window["properties"]["snapshot_consistent"]["const"], False)
        self.assertEqual(
            window["properties"]["ordering"]["const"],
            "job_id_revision_id_ascending",
        )
        self.assertEqual(
            set(window["properties"]["truncation_reasons"]["items"]["enum"]),
            {
                "directory_entry_limit",
                "candidate_limit",
                "window_limit",
                "filesystem_error",
            },
        )

    def test_artifact_contract_is_binary_bounded_and_integrity_labelled(self):
        document = generate_openapi_document()
        operation = document["paths"][
            "/api/v1/revisions/{job_id}/{revision_id}/artifacts/{artifact_id}"
        ]["get"]
        responses = operation["responses"]

        self.assertEqual(set(responses), {"200", "404", "409", "413", "422"})
        binary = responses["200"]["content"]["application/octet-stream"]["schema"]
        self.assertEqual(binary, {"type": "string", "format": "binary"})
        headers = responses["200"]["headers"]
        self.assertEqual(
            headers["X-Ariad-Integrity"]["schema"]["const"],
            "sha256-verified-snapshot",
        )
        self.assertEqual(
            headers["X-Ariad-Hardware-Action"]["schema"]["const"],
            "false",
        )
        self.assertEqual(
            headers["X-Ariad-Max-Artifact-Bytes"]["schema"]["const"],
            64 * 1024 * 1024,
        )
        for status in ("404", "409", "413"):
            with self.subTest(status=status):
                schema = responses[status]["content"]["application/json"]["schema"]
                self.assertEqual(schema["$ref"], "#/components/schemas/ErrorResponse")

    def test_writer_is_canonical_and_check_detects_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "openapi.json"
            write_openapi_snapshot(output)
            check_openapi_snapshot(output)
            parsed = json.loads(output.read_text(encoding="utf-8"))
            parsed["info"]["title"] = "drifted"
            output.write_text(json.dumps(parsed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "stale"):
                check_openapi_snapshot(output)


if __name__ == "__main__":
    unittest.main()
