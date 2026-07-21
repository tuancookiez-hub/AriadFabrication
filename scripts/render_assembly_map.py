"""Render a deterministic SVG assembly map from an Ariad AssemblySpec."""

from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path

from ariad_fabrication.domain import AssemblySpec


def _text(x: float, y: float, value: str, *, size: int = 15, css: str = "") -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" class="{css}">'
        f"{escape(value)}</text>"
    )


def render(spec: AssemblySpec) -> str:
    body_ids = {
        "front_shell",
        "electronics_tray",
        "service_panel",
        "camera_bezel",
        "electronics_carrier",
    }
    body_parts = [item for item in spec.parts if item.part_id in body_ids]
    motion_parts = [item for item in spec.parts if item.part_id not in body_ids]
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="1000" viewBox="0 0 1500 1000">',
        "<style>",
        "text{font-family:Inter,Segoe UI,sans-serif;fill:#201d1a}",
        ".title{font-weight:800;letter-spacing:1px}.label{font-weight:700}",
        ".muted{fill:#6d625c}.red{fill:#b4231a}.white{fill:#fff}",
        "</style>",
        '<rect width="1500" height="1000" fill="#f5f0e8"/>',
        '<rect x="34" y="32" width="1432" height="116" rx="22" fill="#171717"/>',
        _text(70, 82, "ARIAD ASSEMBLY-FIRST PLAN", size=30, css="title white"),
        _text(70, 119, spec.name, size=20, css="white"),
        _text(1120, 82, f"{len(spec.parts)} PARTS", size=18, css="label white"),
        _text(1120, 113, f"{len(spec.interfaces)} INTERFACES", size=18, css="label white"),
        _text(70, 184, "ASSEMBLY", size=16, css="label red"),
        '<rect x="55" y="204" width="275" height="122" rx="18" fill="#fff" stroke="#d6cdc3"/>',
        _text(80, 245, spec.assembly_id, size=17, css="label"),
        _text(80, 278, "Draft decomposition", size=15, css="muted"),
        _text(80, 303, "No fabrication evidence", size=15, css="red"),
        '<path d="M330 265 H385 M385 265 V220 M385 265 V535" stroke="#b4231a" stroke-width="3" fill="none"/>',
    ]

    def part_group(x: int, y: int, title: str, parts: list) -> None:
        height = 70 + 58 * len(parts)
        lines.append(
            f'<rect x="{x}" y="{y}" width="390" height="{height}" rx="18" '
            'fill="#fff" stroke="#d6cdc3"/>'
        )
        lines.append(_text(x + 24, y + 38, title, size=17, css="label red"))
        for index, part in enumerate(parts):
            row_y = y + 68 + index * 58
            lines.append(
                f'<rect x="{x + 20}" y="{row_y - 24}" width="350" height="44" '
                'rx="10" fill="#f8f4ee"/>'
            )
            lines.append(_text(x + 36, row_y + 4, part.name, size=15, css="label"))
            lines.append(_text(x + 310, row_y + 4, "FDM", size=12, css="muted"))

    part_group(410, 174, "BODY & SERVICE", body_parts)
    part_group(410, 548, "MOTION", motion_parts)
    lines.extend(
        [
            _text(860, 184, "PURCHASED COMPONENT ENVELOPES", size=16, css="label red"),
            '<rect x="840" y="204" width="590" height="264" rx="18" fill="#fff" stroke="#d6cdc3"/>',
        ]
    )
    for index, component in enumerate(spec.component_envelopes):
        col = index % 2
        row = index // 2
        x = 865 + col * 280
        y = 245 + row * 100
        dims = component.dimensions_mm
        lines.extend(
            [
                f'<rect x="{x}" y="{y - 22}" width="255" height="78" rx="12" fill="#f8f4ee"/>',
                _text(x + 16, y + 3, component.name, size=14, css="label"),
                _text(
                    x + 16,
                    y + 28,
                    f"{dims.length_mm:g} x {dims.width_mm:g} x {dims.height_mm:g} mm",
                    size=13,
                    css="muted",
                ),
                _text(
                    x + 16,
                    y + 48,
                    component.evidence.value.upper()
                    + (" - VERIFY UNIT" if component.evidence.value != "measured" else ""),
                    size=12,
                    css="red",
                ),
            ]
        )
    lines.extend(
        [
            _text(860, 520, "ASSEMBLY INTERFACES", size=16, css="label red"),
            '<rect x="840" y="540" width="590" height="337" rx="18" fill="#fff" stroke="#d6cdc3"/>',
        ]
    )
    for index, interface in enumerate(spec.interfaces):
        y = 575 + index * 40
        lines.append(f'<circle cx="870" cy="{y - 5}" r="6" fill="#b4231a"/>')
        lines.append(_text(890, y, interface.name, size=14, css="label"))
        suffix = interface.kind.value.replace("_", " ")
        if interface.clearance_mm is not None:
            suffix += f" / {interface.clearance_mm:g} mm"
        lines.append(_text(1220, y, suffix, size=12, css="muted"))
    lines.extend(
        [
            '<rect x="55" y="909" width="1375" height="58" rx="14" fill="#fff" stroke="#d6cdc3"/>',
            _text(
                78,
                944,
                "Draft assembly planning only - no CAD, fit, simulation, printability, slicing, or physical evidence.",
                size=14,
                css="red",
            ),
            "</svg>",
        ]
    )
    return "".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = AssemblySpec.from_mapping(json.loads(args.spec.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(spec), encoding="utf-8")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
