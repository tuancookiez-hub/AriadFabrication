# Ariad web interface

This is the M4 read-only Fabrication Journey client. It renders persisted API records and contains no printer, upload, heat, motion, recovery, or print-start action.

The M4-B inspector can orbit a checksum-verified GLB preview and replay the linear moves in a real G-code artifact by layer. GLB is labelled as tessellated preview rather than exact geometry; G-code is labelled as manufacturing playback rather than engineering or physical simulation. The toolpath parser runs in a Web Worker, fetches the file once, and enforces 64 MiB / one-million-segment limits. The GLB path enforces 64 MiB / two-million-triangle limits.

## Local development

Run the API from the repository root:

```powershell
.\.venv\Scripts\ariad-interface-api.exe --runs-root runs
```

Or use the deterministic non-evidentiary interface fixture:

```powershell
.\.venv\Scripts\ariad-interface-api.exe --runs-root benchmarks/interface
```

In another terminal:

```powershell
pnpm --dir web install --frozen-lockfile
pnpm --dir web dev
```

The Vite development server proxies `/api` to the loopback-only API on port 8000.

## Verification

```powershell
pnpm --dir web lint
pnpm --dir web test
pnpm --dir web build
```

Two environment-gated integration tests additionally parse the actual ignored Golden Part artifacts through the selected Three.js GLTF loader and Ariad toolpath parser:

```powershell
$env:ARIAD_REAL_GLB = "<revision>\design\preview.glb"
$env:ARIAD_REAL_GCODE = "<revision>\slicing\toolpath.gcode"
pnpm --dir web test
```

## Visual references deferred for review

The owner identified the following as interesting references. They are **not selected dependencies** and have not yet passed license, accessibility, maintenance, bundle-size, overlap, or removal-path review:

- anime.js — animation reference.
- Motion.dev — animation and interaction reference.
- Kokonut UI — component and visual-treatment reference.
- Bklit UI — name recorded as supplied; source and spelling still require verification.
- Manus.im — product interaction and presentation reference, not assumed to be a component library.

M4 keeps stage truth, fixture labelling, reduced-motion support, and evidence boundaries independent from any future visual library.
