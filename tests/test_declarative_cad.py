from pathlib import Path
import tempfile
import unittest

try:
    import cadquery  # noqa: F401

    CAD_AVAILABLE = True
except ImportError:
    CAD_AVAILABLE = False

from ariad_fabrication.cad.declarative import (
    DeclarativeCadDocument,
    build_declarative_parts,
    declarative_artifact_path,
    declarative_cad_agent_schema,
    generate_declarative_cad,
)


def operation(
    operation_id: str,
    combine: str,
    primitive: str,
    **values: float,
) -> dict[str, object]:
    return {
        "operation_id": operation_id,
        "combine": combine,
        "primitive": primitive,
        "size_x_mm": values.get("x", 0),
        "size_y_mm": values.get("y", 0),
        "size_z_mm": values.get("z", 0),
        "radius_mm": values.get("radius", 0),
        "radius2_mm": values.get("radius2", 0),
        "position_x_mm": values.get("px", 0),
        "position_y_mm": values.get("py", 0),
        "position_z_mm": values.get("pz", 0),
        "rotation_x_deg": values.get("rx", 0),
        "rotation_y_deg": values.get("ry", 0),
        "rotation_z_deg": values.get("rz", 0),
    }


def phone_stand_document() -> DeclarativeCadDocument:
    return DeclarativeCadDocument.from_mapping(
        {
            "contract_version": "1.0.0",
            "title": "Phone stand",
            "summary": "A base, backrest, and retaining lip proposed from primitives.",
            "parts": [
                {
                    "part_id": "stand",
                    "name": "Phone stand",
                    "purpose": "Hold a generic phone upright",
                    "operations": [
                        operation("base", "base", "box", x=80, y=60, z=6),
                        operation("back", "union", "box", x=80, y=6, z=80, py=27, pz=37),
                        operation("lip", "union", "box", x=80, y=8, z=14, py=-26, pz=7),
                    ],
                }
            ],
            "assumptions": ["Generic phone width below 76 mm"],
            "warnings": ["Viewing angle and device fit are unverified"],
        }
    )


class DeclarativeCadContractTests(unittest.TestCase):
    def test_agent_schema_and_decoder_share_the_radius_limit(self):
        schema = declarative_cad_agent_schema()
        operation = schema["properties"]["parts"]["items"]["properties"]["operations"]["items"]
        self.assertEqual(operation["properties"]["radius_mm"]["maximum"], 200.0)

    def test_rejects_unknown_fields_and_non_intersecting_multi_solid_parts(self):
        value = phone_stand_document().to_dict()
        value["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "exactly"):
            DeclarativeCadDocument.from_mapping(value)

        disconnected = phone_stand_document().to_dict()
        disconnected["parts"][0]["operations"][1]["position_y_mm"] = 200
        document = DeclarativeCadDocument.from_mapping(disconnected)
        if CAD_AVAILABLE:
            with self.assertRaisesRegex(ValueError, "one kernel-valid solid"):
                build_declarative_parts(document)

    @unittest.skipUnless(CAD_AVAILABLE, "install the cad optional dependency to run CAD tests")
    def test_generates_fresh_exact_artifacts_and_reuses_equal_documents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, reused = generate_declarative_cad(phone_stand_document(), root)
            self.assertFalse(reused)
            self.assertTrue(first["checks"]["all_parts_kernel_valid"])
            self.assertTrue(first["checks"]["all_parts_single_solid"])
            self.assertEqual(first["checks"]["part_count"], 1)
            self.assertEqual(
                {item["role"] for item in first["artifacts"]},
                {"assembly_step", "browser_preview", "part_step", "part_stl"},
            )
            for artifact in first["artifacts"]:
                path = declarative_artifact_path(
                    root,
                    first["generation_id"],
                    artifact["filename"],
                )
                self.assertEqual(path.stat().st_size, artifact["size_bytes"])

            second, reused = generate_declarative_cad(phone_stand_document(), root)
            self.assertTrue(reused)
            self.assertEqual(second["document_sha256"], first["document_sha256"])

            preview = next(item for item in first["artifacts"] if item["role"] == "browser_preview")
            preview_path = root / first["generation_id"] / preview["filename"]
            preview_path.write_bytes(preview_path.read_bytes() + b"tampered")
            with self.assertRaisesRegex(ValueError, "content identity"):
                declarative_artifact_path(root, first["generation_id"], preview["filename"])
            with self.assertRaisesRegex(ValueError, "content identity"):
                generate_declarative_cad(phone_stand_document(), root)


if __name__ == "__main__":
    unittest.main()
