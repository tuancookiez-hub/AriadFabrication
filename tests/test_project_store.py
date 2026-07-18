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


if __name__ == "__main__":
    unittest.main()
