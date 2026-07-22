import json
from pathlib import Path
import tempfile
import unittest

from ariad_fabrication.api.agent_tool_runtime import AgentToolCallError, ReadOnlyAgentToolRuntime
from ariad_fabrication.api.repository import JourneyRepository
from ariad_fabrication.api.project_store import ProjectIntentStore


class ReadOnlyAgentToolRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        cls.project_store = ProjectIntentStore(root / "projects")
        cls.runtime = ReadOnlyAgentToolRuntime(
            JourneyRepository(Path("benchmarks/interface")), cls.project_store
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_publishes_exactly_five_closed_function_specs(self):
        specs = self.runtime.tool_specs
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["name"], "ariad")
        self.assertEqual(
            {item["name"] for item in specs[0]["tools"]},
            {"capture_idea", "list_evidence", "read_evidence", "propose_design_plan", "propose_cad_document"},
        )
        self.assertEqual(
            {f"ariad.{item['name']}" for item in specs[0]["tools"]},
            {
                "ariad.capture_idea",
                "ariad.list_evidence",
                "ariad.read_evidence",
                "ariad.propose_design_plan",
                "ariad.propose_cad_document",
            },
        )
        for item in specs[0]["tools"]:
            self.assertEqual(item["type"], "function")
            self.assertFalse(item["inputSchema"]["additionalProperties"])

    def test_capture_is_stateless_and_discloses_claim_boundary(self):
        result = json.loads(
            self.runtime.execute("ariad.capture_idea", {"prompt": "A small floating airship"})
        )
        self.assertFalse(result["persisted"])
        self.assertFalse(result["executed"])
        self.assertFalse(result["hardware_actions"])
        self.assertIn("no CAD", result["claim_boundary"])

    def test_lists_and_reads_checksum_validated_fixture_evidence(self):
        listing = json.loads(self.runtime.execute("ariad.list_evidence", {"offset": 0, "limit": 2}))
        self.assertEqual(len(listing["revisions"]), 2)
        detail = json.loads(
            self.runtime.execute(
                "ariad.read_evidence",
                {"job_id": "job_interface_fixture", "revision_id": "rev_interface_fixture"},
            )
        )
        self.assertEqual(detail["job"]["job_id"], "job_interface_fixture")
        self.assertTrue(detail["source"]["fixture"])

    def test_design_plan_proposal_requires_r0_and_remains_unpersisted(self):
        project = self.project_store.create(title="Enclosure", prompt="Protect a sensor")
        arguments = {
            "project_id": project.project_id,
            "lane": "functional_parametric",
            "geometry_strategy": "Dimension-driven shell and removable lid.",
            "critical_features": ["Cable entry"],
            "assembly_interfaces": ["Sensor board"],
            "constraints": ["Avoid supports"],
            "unresolved_questions": ["Ingress protection target"],
        }
        with self.assertRaisesRegex(AgentToolCallError, "R0 Brief"):
            self.runtime.execute("ariad.propose_design_plan", arguments)
        self.project_store.save_draft(
            project.project_id,
            {
                "name": "Enclosure",
                "purpose": "Protect a sensor",
                "part_type": "enclosure",
                "size_x_mm": 80.0,
                "size_y_mm": 55.0,
                "size_z_mm": 35.0,
                "material": "PETG",
                "tolerance_mm": 0.25,
                "support_policy": "avoid",
                "manufacturing_process": "FDM",
                "safety_class": "general",
            },
        )
        brief = self.project_store.confirm_brief(
            project.project_id, runs_root=Path(self.temporary.name) / "runs"
        )
        result = json.loads(self.runtime.execute("ariad.propose_design_plan", arguments))
        self.assertEqual(result["brief_draft_sha256"], brief.draft_sha256)
        self.assertEqual(result["evidence_mode"], "model_proposal")
        self.assertEqual(result["status"], "needs_input")
        self.assertFalse(result["persisted"])
        self.assertFalse(result["cad_generated"])
        self.assertIsNone(self.project_store.get_design_plan(project.project_id))
        self.assertEqual(
            self.runtime.latest_design_proposal(project.project_id)["proposal"],
            result["proposal"],
        )

    def test_design_proposal_snapshot_is_defensive_and_project_scoped(self):
        self.assertIsNone(
            self.runtime.latest_design_proposal("project_00000000000000000000000000000000")
        )
        existing = next(
            project.project_id
            for project in self.project_store.list()
            if self.runtime.latest_design_proposal(project.project_id) is not None
        )
        snapshot = self.runtime.latest_design_proposal(existing)
        self.assertIsNotNone(snapshot)
        snapshot["proposal"]["geometry_strategy"] = "mutated by caller"
        self.assertNotEqual(
            self.runtime.latest_design_proposal(existing)["proposal"]["geometry_strategy"],
            "mutated by caller",
        )

    def test_declarative_cad_proposal_is_closed_r0_bound_and_unexecuted(self):
        project = self.project_store.create(title="Phone stand", prompt="Make a phone stand")
        self.project_store.save_draft(
            project.project_id,
            {
                "name": "Phone stand", "purpose": "Hold a phone", "part_type": "stand",
                "size_x_mm": 80.0, "size_y_mm": 60.0, "size_z_mm": 80.0,
                "material": "PETG", "tolerance_mm": 0.3, "support_policy": "avoid",
                "manufacturing_process": "FDM", "safety_class": "general",
            },
        )
        brief = self.project_store.confirm_brief(
            project.project_id, runs_root=Path(self.temporary.name) / "runs-csg"
        )
        operation = {
            "operation_id": "base", "combine": "base", "primitive": "box",
            "size_x_mm": 80, "size_y_mm": 60, "size_z_mm": 6,
            "radius_mm": 0, "radius2_mm": 0,
            "position_x_mm": 0, "position_y_mm": 0, "position_z_mm": 0,
            "rotation_x_deg": 0, "rotation_y_deg": 0, "rotation_z_deg": 0,
        }
        arguments = {
            "project_id": project.project_id,
            "contract_version": "1.0.0",
            "title": "Phone stand",
            "summary": "One-piece bounded CSG stand proposal.",
            "parts": [{"part_id": "stand", "name": "Stand", "purpose": "Hold phone", "operations": [operation]}],
            "assumptions": ["Generic phone dimensions"],
            "warnings": ["Device fit is unverified"],
        }
        result = json.loads(self.runtime.execute("ariad.propose_cad_document", arguments))
        self.assertEqual(result["brief_draft_sha256"], brief.draft_sha256)
        self.assertFalse(result["executed"])
        self.assertEqual(result["document"]["parts"][0]["part_id"], "stand")
        result["document"]["title"] = "mutated"
        self.assertEqual(
            self.runtime.latest_cad_proposal(project.project_id)["document"]["title"],
            "Phone stand",
        )

    def test_rejects_unknown_tools_widened_arguments_and_wrong_scalar_types(self):
        calls = (
            ("ariad.unknown", {}),
            ("ariad.list_evidence", {"offset": 0, "limit": 1, "path": "secret"}),
            ("ariad.list_evidence", {"offset": False, "limit": 1}),
        )
        for name, arguments in calls:
            with (
                self.subTest(name=name, arguments=arguments),
                self.assertRaises(AgentToolCallError),
            ):
                self.runtime.execute(name, arguments)


if __name__ == "__main__":
    unittest.main()
