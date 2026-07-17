import json
from pathlib import Path
import unittest

from ariad_fabrication.api.agent_tool_runtime import AgentToolCallError, ReadOnlyAgentToolRuntime
from ariad_fabrication.api.repository import JourneyRepository


class ReadOnlyAgentToolRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = ReadOnlyAgentToolRuntime(JourneyRepository(Path("benchmarks/interface")))

    def test_publishes_exactly_three_closed_function_specs(self):
        specs = self.runtime.tool_specs
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["name"], "ariad")
        self.assertEqual(
            {item["name"] for item in specs[0]["tools"]},
            {"capture_idea", "list_evidence", "read_evidence"},
        )
        self.assertEqual(
            {f"ariad.{item['name']}" for item in specs[0]["tools"]},
            {"ariad.capture_idea", "ariad.list_evidence", "ariad.read_evidence"},
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
        listing = json.loads(
            self.runtime.execute("ariad.list_evidence", {"offset": 0, "limit": 2})
        )
        self.assertEqual(len(listing["revisions"]), 2)
        detail = json.loads(
            self.runtime.execute(
                "ariad.read_evidence",
                {"job_id": "job_interface_fixture", "revision_id": "rev_interface_fixture"},
            )
        )
        self.assertEqual(detail["job"]["job_id"], "job_interface_fixture")
        self.assertTrue(detail["source"]["fixture"])

    def test_rejects_unknown_tools_widened_arguments_and_wrong_scalar_types(self):
        calls = (
            ("ariad.unknown", {}),
            ("ariad.list_evidence", {"offset": 0, "limit": 1, "path": "secret"}),
            ("ariad.list_evidence", {"offset": False, "limit": 1}),
        )
        for name, arguments in calls:
            with self.subTest(name=name, arguments=arguments), self.assertRaises(AgentToolCallError):
                self.runtime.execute(name, arguments)


if __name__ == "__main__":
    unittest.main()
