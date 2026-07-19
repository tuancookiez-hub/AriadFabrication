import unittest

from ariad_fabrication.agent_tools import (
    AGENT_TOOL_CONTRACT_VERSION,
    AgentToolDescriptor,
    ToolAvailability,
    current_agent_tool_catalog,
    exposed_codex_tools,
)


class AgentToolContractTests(unittest.TestCase):
    def test_catalog_is_namespaced_closed_and_never_hardware_capable(self):
        catalog = current_agent_tool_catalog()
        self.assertEqual(len(catalog), 7)
        self.assertEqual(len({item.name for item in catalog}), len(catalog))
        for item in catalog:
            self.assertEqual(item.contract_version, AGENT_TOOL_CONTRACT_VERSION)
            self.assertTrue(item.name.startswith("ariad."))
            self.assertFalse(item.hardware_actions)
            self.assertEqual(item.input_schema["type"], "object")
            self.assertFalse(item.input_schema["additionalProperties"])
            self.assertEqual(
                set(item.input_schema["required"]),
                set(item.input_schema["properties"]),
            )

    def test_only_current_read_and_stateless_tools_are_exposed_to_codex(self):
        exposed = exposed_codex_tools()
        self.assertEqual(
            {item.name for item in exposed},
            {
                "ariad.capture_idea",
                "ariad.list_evidence",
                "ariad.read_evidence",
                "ariad.propose_design_plan",
            },
        )
        self.assertTrue(all(not item.mutates_state for item in exposed))
        self.assertTrue(all(item.availability is ToolAvailability.AVAILABLE for item in exposed))

    def test_mutating_and_generated_source_tools_disclose_their_blockers(self):
        by_name = {item.name: item for item in current_agent_tool_catalog()}
        for name in (
            "ariad.run_registered_target",
            "ariad.cancel_execution",
            "ariad.submit_cad_source",
        ):
            self.assertTrue(by_name[name].mutates_state)
            self.assertTrue(by_name[name].blocked_reason)
            self.assertNotIn(by_name[name], exposed_codex_tools())

    def test_descriptor_schema_cannot_be_widened_after_construction(self):
        descriptor = exposed_codex_tools()[0]
        with self.assertRaises(TypeError):
            descriptor.input_schema["properties"]["prompt"]["maxLength"] = 999999
        serialized = descriptor.to_dict()
        serialized["input_schema"]["properties"]["prompt"]["maxLength"] = 1
        self.assertEqual(
            descriptor.input_schema["properties"]["prompt"]["maxLength"],
            16384,
        )

    def test_invalid_descriptor_cannot_widen_input_or_hardware_authority(self):
        with self.assertRaisesRegex(ValueError, "closed objects"):
            AgentToolDescriptor(
                name="ariad.bad",
                description="Bad schema",
                input_schema={"type": "object", "properties": {}, "required": []},
                availability=ToolAvailability.AVAILABLE,
            )
        with self.assertRaisesRegex(ValueError, "hardware"):
            AgentToolDescriptor(
                name="ariad.bad",
                description="Bad authority",
                input_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                    "required": [],
                },
                availability=ToolAvailability.AVAILABLE,
                hardware_actions=True,
            )


if __name__ == "__main__":
    unittest.main()
