import json
from pathlib import Path
import tempfile
import unittest

from ariad_fabrication.api.project_store import ProjectIntentStore, ProjectStoreError


class ProjectIntentStoreTests(unittest.TestCase):
    def test_create_and_list_preserve_user_confirmation_without_r0_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ProjectIntentStore(Path(temporary) / "projects")
            created = store.create(title="Floating airship", prompt="A 120 mm display model")
            self.assertEqual(created.status, "intent_confirmed")
            self.assertIsNone(created.brief_evidence_level)
            self.assertFalse(created.fabrication_started)
            self.assertFalse(created.hardware_actions)
            self.assertEqual(store.list(), (created,))

    def test_persisted_prompt_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ProjectIntentStore(Path(temporary) / "projects")
            created = store.create(title="Airship", prompt="Original")
            path = Path(temporary) / "projects" / created.project_id / "project.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["prompt"] = "Changed"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ProjectStoreError, "checksum"):
                store.list()

    def test_empty_and_oversized_values_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ProjectIntentStore(Path(temporary) / "projects")
            for title, prompt in (("", "Idea"), ("Title", ""), ("x" * 121, "Idea")):
                with self.subTest(title=title), self.assertRaises(ProjectStoreError):
                    store.create(title=title, prompt=prompt)

    def test_nullable_clarification_draft_becomes_ready_only_when_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ProjectIntentStore(Path(temporary) / "projects")
            project = store.create(title="Airship", prompt="A display model")
            values = {
                "name": "Airship model",
                "purpose": "Desk display",
                "part_type": "decorative model",
                "size_x_mm": 120.0,
                "size_y_mm": None,
                "size_z_mm": None,
                "material": None,
                "tolerance_mm": None,
                "support_policy": None,
                "manufacturing_process": "FDM",
                "safety_class": "general",
            }
            incomplete = store.save_draft(project.project_id, values)
            self.assertEqual(incomplete.status, "needs_input")
            self.assertIn("size_y_mm", incomplete.missing_fields)
            complete = store.save_draft(
                project.project_id,
                {
                    **values,
                    "size_y_mm": 45.0,
                    "size_z_mm": 35.0,
                    "material": "PLA",
                    "tolerance_mm": 0.2,
                    "support_policy": "allowed",
                },
            )
            self.assertEqual(complete.status, "ready_for_confirmation")
            self.assertEqual(complete.missing_fields, ())
            self.assertEqual(store.get_draft(project.project_id), complete)

    def test_tampered_clarification_readiness_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ProjectIntentStore(Path(temporary) / "projects")
            project = store.create(title="Airship", prompt="A display model")
            store.save_draft(
                project.project_id,
                {
                    "name": None,
                    "purpose": None,
                    "part_type": None,
                    "size_x_mm": None,
                    "size_y_mm": None,
                    "size_z_mm": None,
                    "material": None,
                    "tolerance_mm": None,
                    "support_policy": None,
                    "manufacturing_process": None,
                    "safety_class": None,
                },
            )
            path = Path(temporary) / "projects" / project.project_id / "draft.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["status"] = "ready_for_confirmation"
            value["missing_fields"] = []
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ProjectStoreError, "readiness"):
                store.get_draft(project.project_id)

    def test_complete_draft_confirmation_persists_one_r0_journey(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ProjectIntentStore(root / "projects")
            project = store.create(title="Airship", prompt="A display model")
            store.save_draft(
                project.project_id,
                {
                    "name": "Airship",
                    "purpose": "Desk display",
                    "part_type": "decorative model",
                    "size_x_mm": 120.0,
                    "size_y_mm": 45.0,
                    "size_z_mm": 35.0,
                    "material": "PLA",
                    "tolerance_mm": 0.2,
                    "support_policy": "allowed",
                    "manufacturing_process": "FDM",
                    "safety_class": "general",
                },
            )
            brief = store.confirm_brief(project.project_id, runs_root=root / "runs")
            self.assertEqual(brief.evidence_level, "R0")
            self.assertEqual(brief.status, "ready_for_design")
            self.assertFalse(brief.fabrication_started)
            revision_root = root / "runs" / brief.job_id / "revisions" / brief.revision_id
            journey = json.loads((revision_root / "journey.json").read_text(encoding="utf-8"))
            self.assertEqual(journey["job"]["status"], "ready_for_design")
            self.assertEqual(journey["revisions"][0]["spec"]["status"], "confirmed")
            self.assertEqual(journey["stage_runs"][0]["evidence_level"], "R0")
            self.assertEqual(
                store.confirm_brief(project.project_id, runs_root=root / "runs"), brief
            )
            with self.assertRaisesRegex(ProjectStoreError, "immutable"):
                store.save_draft(
                    project.project_id,
                    {
                        "name": "Changed",
                        "purpose": "Desk display",
                        "part_type": "decorative model",
                        "size_x_mm": 120.0,
                        "size_y_mm": 45.0,
                        "size_z_mm": 35.0,
                        "material": "PLA",
                        "tolerance_mm": 0.2,
                        "support_policy": "allowed",
                        "manufacturing_process": "FDM",
                        "safety_class": "general",
                    },
                )

    def test_design_plan_is_bound_to_r0_and_remains_planning_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ProjectIntentStore(root / "projects")
            project = store.create(title="Sensor enclosure", prompt="Protect a garden sensor")
            store.save_draft(
                project.project_id,
                {
                    "name": "Sensor enclosure",
                    "purpose": "Protect a garden sensor",
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
            with self.assertRaisesRegex(ProjectStoreError, "R0 Brief"):
                store.save_design_plan(
                    project.project_id,
                    {
                        "lane": "functional_parametric",
                        "geometry_strategy": "Shell and lid",
                        "critical_features": [],
                        "assembly_interfaces": [],
                        "constraints": [],
                        "unresolved_questions": [],
                    },
                )
            brief = store.confirm_brief(project.project_id, runs_root=root / "runs")
            plan = store.save_design_plan(
                project.project_id,
                {
                    "lane": "functional_parametric",
                    "geometry_strategy": "Parametric shell and removable lid with explicit wall thickness.",
                    "critical_features": ["Cable entry", "Four lid fasteners"],
                    "assembly_interfaces": ["55 x 30 mm sensor board"],
                    "constraints": ["Avoid supports", "Fit inside the confirmed envelope"],
                    "unresolved_questions": ["Required ingress protection"],
                },
            )
            self.assertEqual(plan.brief_draft_sha256, brief.draft_sha256)
            self.assertEqual(plan.status, "needs_input")
            self.assertEqual(plan.evidence_mode, "planning_only")
            self.assertIsNone(plan.design_evidence_level)
            self.assertFalse(plan.cad_generated)
            self.assertFalse(plan.fabrication_started)
            self.assertEqual(store.get_design_plan(project.project_id), plan)

            undecided = store.save_design_plan(
                project.project_id,
                {
                    "lane": "undecided",
                    "geometry_strategy": "Choose a representation before geometry work.",
                    "critical_features": [],
                    "assembly_interfaces": [],
                    "constraints": [],
                    "unresolved_questions": [],
                },
            )
            self.assertEqual(undecided.status, "needs_input")

            path = root / "projects" / project.project_id / "design-plan.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["cad_generated"] = True
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ProjectStoreError, "claim boundary"):
                store.get_design_plan(project.project_id)


if __name__ == "__main__":
    unittest.main()
