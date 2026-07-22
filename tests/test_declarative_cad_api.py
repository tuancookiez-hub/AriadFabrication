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


def proposal_arguments(project_id: str) -> dict[str, object]:
    return {
        "project_id": project_id,
        "contract_version": "1.0.0",
        "title": "Controller tray",
        "summary": "A low tray with four mounting holes.",
        "parts": [
            {
                "part_id": "tray",
                "name": "Controller tray",
                "purpose": "Hold a small controller board",
                "operations": [
                    {
                        "operation_id": "base",
                        "combine": "base",
                        "primitive": "box",
                        "size_x_mm": 80,
                        "size_y_mm": 55,
                        "size_z_mm": 4,
                        "radius_mm": 0,
                        "radius2_mm": 0,
                        "position_x_mm": 0,
                        "position_y_mm": 0,
                        "position_z_mm": 0,
                        "rotation_x_deg": 0,
                        "rotation_y_deg": 0,
                        "rotation_z_deg": 0,
                    }
                ],
            }
        ],
        "assumptions": ["Generic board footprint"],
        "warnings": ["Mounting pattern is not based on a measured board"],
    }


class DeclarativeCadApiTests(unittest.TestCase):
    @unittest.skipUnless(CAD_AVAILABLE, "install the cad optional dependency to run CAD tests")
    def test_codex_proposal_can_be_explicitly_generated_and_downloaded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = create_app(
                runs_root=root / "runs",
                projects_root=root / "projects",
                assembly_spec_path=ROOT / "benchmarks/robot_casing/assembly_spec.json",
            )
            client = TestClient(app)
            token = client.get("/api/v1/session").json()["session_token"]
            headers = {"X-Ariad-Session": token}
            project_id = client.post(
                "/api/v1/projects",
                headers=headers,
                json={"title": "Tray", "prompt": "Make a controller tray", "confirmed": True},
            ).json()["project_id"]
            client.put(
                f"/api/v1/projects/{project_id}/draft",
                headers=headers,
                json={
                    "name": "Tray", "purpose": "Hold controller", "part_type": "tray",
                    "size_x_mm": 80, "size_y_mm": 55, "size_z_mm": 10,
                    "material": "PETG", "tolerance_mm": 0.3,
                    "support_policy": "avoid", "manufacturing_process": "FDM",
                    "safety_class": "general",
                },
            )
            client.post(
                f"/api/v1/projects/{project_id}/brief-confirmation",
                headers=headers,
                json={"confirmed": True},
            )
            self.assertEqual(
                client.get(f"/api/v1/projects/{project_id}/cad-proposal", headers=headers).status_code,
                404,
            )
            app.state.agent_tool_runtime.execute(
                "ariad.propose_cad_document",
                proposal_arguments(project_id),
            )
            proposal = client.get(
                f"/api/v1/projects/{project_id}/cad-proposal",
                headers=headers,
            )
            self.assertEqual(proposal.status_code, 200, proposal.text)
            self.assertFalse(proposal.json()["executed"])

            generated = client.post(
                f"/api/v1/projects/{project_id}/generate-cad",
                headers=headers,
            )
            self.assertEqual(generated.status_code, 200, generated.text)
            body = generated.json()
            self.assertEqual(body["checks"]["part_count"], 1)
            self.assertTrue(body["checks"]["all_parts_kernel_valid"])
            self.assertEqual(body["document"]["title"], "Controller tray")
            for artifact in body["artifacts"]:
                response = client.get(artifact["download_url"])
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["x-ariad-hardware-action"], "false")
                self.assertGreater(len(response.content), 100)


if __name__ == "__main__":
    unittest.main()
