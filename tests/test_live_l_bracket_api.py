from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

try:
    import cadquery  # noqa: F401

    CAD_AVAILABLE = True
except ImportError:
    CAD_AVAILABLE = False

from ariad_fabrication.api import create_app


ROOT = Path(__file__).resolve().parents[1]


class LiveLBracketApiTests(unittest.TestCase):
    @unittest.skipUnless(
        CAD_AVAILABLE,
        "install the cad optional dependency to run live CAD generation tests",
    )
    def test_confirmed_prompt_generates_parameter_bound_cad_and_downloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = TestClient(
                create_app(
                    runs_root=root / "runs",
                    projects_root=root / "projects",
                    assembly_spec_path=ROOT / "benchmarks/robot_casing/assembly_spec.json",
                )
            )
            token = client.get("/api/v1/session").json()["session_token"]
            headers = {"X-Ariad-Session": token}
            project = client.post(
                "/api/v1/projects",
                headers=headers,
                json={
                    "title": "Live bracket",
                    "prompt": "Make a 60 x 40 x 45 mm L bracket",
                    "confirmed": True,
                },
            ).json()
            project_id = project["project_id"]
            draft = {
                "name": "Live bracket",
                "purpose": "Mount a small controller",
                "part_type": "L bracket",
                "size_x_mm": 60,
                "size_y_mm": 40,
                "size_z_mm": 45,
                "material": "PETG",
                "tolerance_mm": 0.3,
                "support_policy": "avoid",
                "manufacturing_process": "FDM",
                "safety_class": "general",
            }
            self.assertEqual(
                client.put(
                    f"/api/v1/projects/{project_id}/draft",
                    headers=headers,
                    json=draft,
                ).status_code,
                200,
            )
            self.assertEqual(
                client.post(
                    f"/api/v1/projects/{project_id}/brief-confirmation",
                    headers=headers,
                    json={"confirmed": True},
                ).status_code,
                201,
            )
            request = {
                "project_id": project_id,
                "width_mm": 60,
                "base_depth_mm": 40,
                "upright_height_mm": 45,
                "thickness_mm": 4,
                "hole_diameter_mm": 4.2,
                "hole_spacing_mm": 36,
                "edge_margin_mm": 5,
            }
            response = client.post("/api/v1/live-cad/l-bracket", headers=headers, json=request)
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertFalse(body["cache_reused"])
            self.assertEqual(body["parameters"]["width_mm"], 60)
            self.assertTrue(body["checks"]["kernel_valid"])
            self.assertEqual(body["checks"]["solid_count"], 1)
            self.assertEqual({item["role"] for item in body["artifacts"]}, {
                "editable_step", "compatibility_stl", "browser_preview"
            })
            for artifact in body["artifacts"]:
                download = client.get(artifact["download_url"])
                self.assertEqual(download.status_code, 200)
                self.assertGreater(len(download.content), 100)
                self.assertEqual(download.headers["x-ariad-hardware-action"], "false")

            repeated = client.post("/api/v1/live-cad/l-bracket", headers=headers, json=request)
            self.assertEqual(repeated.status_code, 200)
            self.assertTrue(repeated.json()["cache_reused"])
            self.assertEqual(repeated.json()["generation_id"], body["generation_id"])

    def test_generation_requires_an_existing_confirmed_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = TestClient(
                create_app(
                    runs_root=root / "runs",
                    projects_root=root / "projects",
                    assembly_spec_path=ROOT / "benchmarks/robot_casing/assembly_spec.json",
                )
            )
            token = client.get("/api/v1/session").json()["session_token"]
            response = client.post(
                "/api/v1/live-cad/l-bracket",
                headers={"X-Ariad-Session": token},
                json={
                    "project_id": "missing",
                    "width_mm": 20,
                    "base_depth_mm": 20,
                    "upright_height_mm": 20,
                    "thickness_mm": 4,
                    "hole_diameter_mm": 10,
                    "hole_spacing_mm": 18,
                    "edge_margin_mm": 5,
                },
            )
            self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
