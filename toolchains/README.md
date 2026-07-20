# Toolchain identity manifests

This directory stores versioned, generated content manifests for Ariad's registered no-hardware execution targets. It does not store Python, CadQuery, OCCT, PrusaSlicer, or other toolchain binaries.

## Current manifests

- `v1/cad-runtime-cpython-3.11-windows-x64.json` records the curated CPython base runtime, the locked dependency files observed by the registered Golden Part R4 Python lane, active environment bootstrap files, `pyvenv.cfg`, and trace evidence bound to the current Ariad application bundle.
- `v1/prusaslicer-2.9.6-windows-x64.json` records the approved upstream portable archive identity and every file in the extracted PrusaSlicer installation.

The manifests establish reproducible content identity for one registered digital lane. They are not signatures, an operating-system sandbox, network denial, physical evidence, or proof that an unmanifested Python import is impossible. Windows system DLL bytes are outside the manifests.

## Regeneration

Use the pinned CAD environment from the repository root:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\generate_cad_runtime_manifest.py --check
.\.venv\Scripts\python.exe scripts\generate_prusaslicer_manifest.py --check
```

Omit `--check` only when intentionally regenerating after an approved source, schema, lock, runtime, archive, or installation change. The CAD trace runs the registered R4 Python lane into a temporary directory and performs no slicing or hardware action. Because its trace is bound to the Ariad source/schema bundle, regenerate it after relevant application changes have settled. Review all resulting identity changes; never update a digest only to make a failing check green.

The repository enforces LF for text through `.gitattributes`; this is part of making exact content hashes reproducible across Windows and non-Windows Git configurations.

The PrusaSlicer generator expects the ignored archive and extracted installation under `runs/tools/prusaslicer/2.9.6/`. The archive provenance URL is recorded in the manifest. Public redistribution of the binary is a separate licensing decision.
