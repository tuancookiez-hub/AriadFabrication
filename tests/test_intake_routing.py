import unittest

from ariad_fabrication.intake import (
    CapabilityLane,
    CurrentCapabilityRouter,
    EvidenceMode,
    IntentProposal,
    MAX_PROMPT_BYTES,
    PromptIntake,
    RouteStatus,
)


class PromptIntakeTests(unittest.TestCase):
    def test_any_bounded_nonempty_utf8_prompt_is_captured_without_hardware(self):
        prompts = (
            "Make a robot gripper",
            "Design a decorative dragon airship ✨",
            "I only know that I need something to hold a plant sensor",
        )
        for index, prompt in enumerate(prompts):
            intake = PromptIntake(prompt, intake_id=f"intake_{index}")
            self.assertEqual(intake.prompt, prompt)
            self.assertEqual(len(intake.prompt_sha256), 64)
            self.assertFalse(intake.to_dict()["hardware_actions"])

    def test_empty_oversized_and_hardware_enabled_intake_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "prompt is required"):
            PromptIntake("  ")
        with self.assertRaisesRegex(ValueError, "UTF-8 bytes"):
            PromptIntake("é" * (MAX_PROMPT_BYTES // 2 + 1))
        with self.assertRaisesRegex(ValueError, "hardware"):
            PromptIntake("Make a planter", hardware_actions=True)


class CapabilityRouterTests(unittest.TestCase):
    def setUp(self):
        self.router = CurrentCapabilityRouter()
        self.intake = PromptIntake("Make something useful", intake_id="intake_route")

    def route(self, lane, **changes):
        proposal = IntentProposal(
            lane=lane,
            summary=changes.pop("summary", "A proposed fabrication idea"),
            **changes,
        )
        return self.router.route(self.intake, proposal)

    def test_only_exact_registered_benchmark_exposes_real_execution_targets(self):
        route = self.route(
            CapabilityLane.REGISTERED_BENCHMARK,
            benchmark_id=CurrentCapabilityRouter.GOLDEN_PART_BENCHMARK_ID,
        )
        self.assertEqual(route.status, RouteStatus.DEMO_AVAILABLE)
        self.assertEqual(route.evidence_mode, EvidenceMode.REAL)
        self.assertEqual(route.available_targets, ("golden_part_r2", "golden_part_r4"))
        self.assertFalse(route.hardware_actions)
        self.assertFalse(route.physical_validation)

        rejected = self.route(
            CapabilityLane.REGISTERED_BENCHMARK,
            benchmark_id="invented_benchmark",
        )
        self.assertEqual(rejected.status, RouteStatus.UNSUPPORTED)
        self.assertEqual(rejected.available_targets, ())

    def test_general_functional_route_never_becomes_executable(self):
        needs_input = self.route(
            CapabilityLane.FUNCTIONAL_PARAMETRIC_CAD,
            questions=("What shaft diameter must it fit?",),
        )
        self.assertEqual(needs_input.status, RouteStatus.NEEDS_INPUT)
        self.assertEqual(needs_input.evidence_mode, EvidenceMode.MODEL_PROPOSAL)
        self.assertEqual(needs_input.available_targets, ())

        unavailable = self.route(CapabilityLane.FUNCTIONAL_PARAMETRIC_CAD)
        self.assertEqual(unavailable.status, RouteStatus.PROVIDER_UNAVAILABLE)
        self.assertEqual(unavailable.available_targets, ())

    def test_organic_planning_and_unsupported_routes_are_explicit(self):
        organic = self.route(CapabilityLane.ORGANIC_MESH)
        planning = self.route(CapabilityLane.PLANNING_ONLY)
        unsupported = self.route(CapabilityLane.UNSUPPORTED)
        self.assertEqual(organic.status, RouteStatus.PROVIDER_UNAVAILABLE)
        self.assertEqual(organic.evidence_mode, EvidenceMode.UNAVAILABLE)
        self.assertEqual(planning.status, RouteStatus.NEEDS_INPUT)
        self.assertEqual(unsupported.status, RouteStatus.UNSUPPORTED)
        self.assertTrue(
            all(
                not item.to_dict()["physical_validation"]
                for item in (organic, planning, unsupported)
            )
        )

    def test_proposals_remain_non_evidentiary_and_bounded(self):
        with self.assertRaisesRegex(ValueError, "model_proposal"):
            IntentProposal(
                lane=CapabilityLane.FUNCTIONAL_PARAMETRIC_CAD,
                summary="Functional part",
                evidence_mode=EvidenceMode.REAL,
            )
        with self.assertRaisesRegex(ValueError, "more than 12"):
            IntentProposal(
                lane=CapabilityLane.PLANNING_ONLY,
                summary="Idea",
                questions=tuple(f"Question {index}" for index in range(13)),
            )


if __name__ == "__main__":
    unittest.main()
