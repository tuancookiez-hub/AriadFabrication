"""Export the nine-part Ariad robot prototype and a visual contact sheet."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ariad_fabrication.cad.robot_casing_design import DESIGN_SOURCE_VERSION, build_parts


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "runs" / "concepts" / "robot-parts-v1")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    parameters_path = ROOT / "benchmarks" / "robot_casing" / "parameters.json"
    parameters = json.loads(parameters_path.read_text(encoding="utf-8"))
    parts = build_parts(parameters)

    from cadquery import exporters

    records = []
    for name, part in parts.items():
        step_path = output / f"{name}.step"
        stl_path = output / f"{name}.stl"
        svg_path = output / f"{name}.svg"
        exporters.export(part, str(step_path))
        exporters.export(part, str(stl_path), tolerance=0.08, angularTolerance=0.12)
        exporters.export(part, str(svg_path), opt={"width": 480, "height": 360, "showAxes": False})
        records.append(
            {
                "part_id": name,
                "step": step_path.name,
                "step_sha256": hashlib.sha256(step_path.read_bytes()).hexdigest(),
                "stl": stl_path.name,
                "stl_sha256": hashlib.sha256(stl_path.read_bytes()).hexdigest(),
                "preview": svg_path.name,
                "kernel_valid": bool(part.val().isValid()),
                "solid_count": len(part.solids().vals()),
                "volume_mm3": round(part.val().Volume(), 3),
            }
        )

    manifest = {
        "artifact_kind": "prototype_geometry",
        "design_source_version": DESIGN_SOURCE_VERSION,
        "part_count": len(records),
        "parts": records,
        "claim_boundary": (
            "Digitally valid prototype solids only. Component fit, tolerances, slicing, "
            "strength, motion, safety, and physical print success are unverified."
        ),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    cards = "\n".join(
        f'<article><img src="{record["preview"]}" alt="{record["part_id"]}">'
        f'<h2>{record["part_id"].replace("_", " ")}</h2>'
        f'<p>{record["volume_mm3"]:,.0f} mm³ · one valid solid</p></article>'
        for record in records
    )
    (output / "index.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Ariad robot prototype parts</title>"
        "<style>body{margin:0;padding:42px;background:#eee7dc;color:#191715;font-family:Arial,sans-serif}"
        "header{background:#171616;color:#fff;padding:28px 32px;border-radius:18px;margin-bottom:22px}"
        "h1{margin:0 0 8px;font-size:38px}header p{margin:0;color:#e25b50}main{display:grid;"
        "grid-template-columns:repeat(3,1fr);gap:16px}article{background:#fffdfa;border:1px solid #d8cec1;"
        "border-radius:14px;padding:14px}img{display:block;width:100%;height:220px;object-fit:contain;background:#f7f3ed}"
        "h2{font-size:18px;text-transform:capitalize;margin:12px 0 5px}article p{margin:0;color:#756b60;font-size:13px}"
        "footer{margin-top:20px;border-left:4px solid #c92f26;padding:12px 16px;background:#fff8ec;color:#5b5045}</style>"
        "<header><h1>ARIAD ROBOT · PROTOTYPE PARTS V1</h1><p>9 separate STEP + STL solids</p></header>"
        f"<main>{cards}</main><footer>{manifest['claim_boundary']}</footer>",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
