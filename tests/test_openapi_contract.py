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
        self.assertEqual(health["schema_version"]["const"], "1.3.0")
        self.assertEqual(health["service"]["const"], "ariad-interface-api")
        self.assertEqual(health["status"]["const"], "ok")

    def test_response_models_do_not_hide_guaranteed_fields_as_optional(self):
        schemas = generate_openapi_document()["components"]["schemas"]
        response_models = {
            "ArtifactView",
            "CapabilitiesView",
            "ComparisonAreaSummaryView",
            "ComparisonChangeView",
            "ComparisonRevisionView",
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
