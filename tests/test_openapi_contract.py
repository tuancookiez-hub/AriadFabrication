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
        self.assertEqual(health["schema_version"]["const"], "1.1.0")
        self.assertEqual(health["service"]["const"], "ariad-interface-api")
        self.assertEqual(health["status"]["const"], "ok")

    def test_response_models_do_not_hide_guaranteed_fields_as_optional(self):
        schemas = generate_openapi_document()["components"]["schemas"]
        response_models = {
            "ArtifactView",
            "CapabilitiesView",
            "EventView",
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
            "RevisionListResponse",
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
