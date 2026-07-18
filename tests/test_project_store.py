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
                "name": "Airship model", "purpose": "Desk display", "part_type": "decorative model",
                "size_x_mm": 120.0, "size_y_mm": None, "size_z_mm": None,
                "material": None, "tolerance_mm": None, "support_policy": None,
                "manufacturing_process": "FDM", "safety_class": "general",
            }
            incomplete = store.save_draft(project.project_id, values)
            self.assertEqual(incomplete.status, "needs_input")
            self.assertIn("size_y_mm", incomplete.missing_fields)
            complete = store.save_draft(
                project.project_id,
                {**values, "size_y_mm": 45.0, "size_z_mm": 35.0, "material": "PLA", "tolerance_mm": 0.2, "support_policy": "allowed"},
            )
            self.assertEqual(complete.status, "ready_for_confirmation")
            self.assertEqual(complete.missing_fields, ())
            self.assertEqual(store.get_draft(project.project_id), complete)

    def test_tampered_clarification_readiness_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ProjectIntentStore(Path(temporary) / "projects")
            project = store.create(title="Airship", prompt="A display model")
            store.save_draft(project.project_id, {
                "name": None, "purpose": None, "part_type": None,
                "size_x_mm": None, "size_y_mm": None, "size_z_mm": None,
                "material": None, "tolerance_mm": None, "support_policy": None,
                "manufacturing_process": None, "safety_class": None,
            })
            path = Path(temporary) / "projects" / project.project_id / "draft.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["status"] = "ready_for_confirmation"
            value["missing_fields"] = []
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ProjectStoreError, "readiness"):
                store.get_draft(project.project_id)


if __name__ == "__main__":
    unittest.main()
