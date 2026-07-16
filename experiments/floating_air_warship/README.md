# Floating Air Warship concept

This is a separate procedural concept-art experiment. It does not enter the registered Golden Part worker, the M3 critical path, or the R0-R7 qualification ladder.

The design uses CadQuery/OCCT for a multi-solid assembly and VTK for local renders. It exports:

- Colored GLB for the primary interactive preview.
- Colored OBJ/MTL for broad DCC compatibility.
- STEP for exact multi-solid component geometry.
- 3MF and STL compatibility meshes.
- Hero and multi-view PNG renders.
- A JSON manifest with checksums and structural observations.

The solids intentionally overlap to form a visual kit-bashed airship. Closed component meshes do not prove that the combined assembly is self-intersection-free, support-free, structurally sound, or printable as one object.

Run from the repository root after installing the optional CAD environment:

```powershell
uv sync --extra cad
.\.venv\Scripts\python.exe experiments\floating_air_warship\generate.py `
  --output-dir runs\experiments\floating_air_warship\v1
```

Edit `parameters.json` or the procedural component recipes in `generate.py` to create another revision. Use a new output directory because generated concept revisions are immutable by default.
