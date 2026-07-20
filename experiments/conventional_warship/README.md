# Conventional warship display model

This experiment creates a conventional, destroyer-inspired desk model for the
Ariad fabrication workflow. It is deliberately separate from the floating
air-warship concept and from the registered Golden Part provider.

The default design is a 160 mm long, one-piece model intended to be evaluated
in an upright, flat-keel FDM orientation. It uses a broad flat contact surface,
sloped hull sides, connected superstructure, thick masts and radar details, and
supported gun silhouettes instead of fragile horizontal barrels.

The generator exports:

- Editable CadQuery source and parameters.
- STEP exact geometry.
- 3MF manufacturing geometry.
- STL compatibility geometry.
- GLB browser preview.
- Hero and four-view PNG renders.
- A geometry report and checksum manifest.

The checks prove only the recorded digital facts: one valid connected solid,
the measured envelope, a flat bed datum/contact area, STEP re-import, and a
closed two-manifold STL. They do not prove slicer success, support-free
printing, strength, watertight flotation, or physical print quality. The model
must still pass Ariad's future R3 printability and R4 real-slicer gates for a
specific printer, nozzle, material, orientation, and profile.

Run from the repository root after installing the optional CAD environment:

```powershell
uv sync --extra cad
.\.venv\Scripts\python.exe experiments\conventional_warship\generate.py `
  --output-dir runs\experiments\conventional_warship\v1
```

Generated revisions are immutable. Change `parameters.json` or the procedural
recipe and choose a new output directory for each revision.
