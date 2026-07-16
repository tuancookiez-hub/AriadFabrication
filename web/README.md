# Ariad web interface

This is the M4 read-only Fabrication Journey client. It renders persisted API records and contains no printer, upload, heat, motion, recovery, or print-start action.

The M4-K inspector can orbit a checksum-verified GLB preview, replay the linear moves in a real G-code artifact by layer, select persisted features, checks, findings, profiles, measurements, and artifact records, and compare two normalized persisted revisions. GLB is labelled as tessellated preview rather than exact geometry; G-code is labelled as manufacturing playback rather than engineering or physical simulation. Evidence selection and comparison never rerun validation or pretend to spatially inspect STEP. The toolpath parser runs in a Web Worker, fetches the file once, and enforces 64 MiB / one-million-segment limits. The GLB path enforces 64 MiB / two-million-triangle limits; report/profile JSON is checksum-verified by API 1.6.0 before bounded parsing. Root records, inspection JSON, and artifact GETs use allocation-capped snapshots; artifact responses return the exact snapshot whose size and SHA-256 passed rather than reopening a mutable path. Persisted lifecycle, evidence, package, decision, approval, and hardware fields cross a closed typed contract before the browser can render them; journey text and inspection numbers cannot be coerced from other JSON scalar types, and exposed timestamps carry date-time formats after timezone/chronology validation. PartSpec, StageEvent, ArtifactManifest, and production/fixture package roots also pass packaged JSON Schemas, stage-owned records and artifact lineage must be exhaustive and coherent, and production package roles/descriptors/warnings/G-code metadata must match the manifest. Unsupported report/profile states become explicit unavailable records. Server-owned comparison caps each revision at 10,000 normalized records, output at 1,000 changes, and each returned value at 64 KiB. Revision discovery examines at most 5,000 entries, retains at most 500 candidates, and loads at most 200 summaries; the list UI exposes observed omissions and explicitly warns that live offset pages are not snapshot-consistent.

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

## API contract generation

The browser response types are generated from the committed FastAPI OpenAPI snapshot. Do not edit `src/generated/interface-api.ts` directly.

```powershell
uv run ariad-interface-openapi
pnpm --dir web api:types
```

Use the paired checks without rewriting files:

```powershell
uv run ariad-interface-openapi --check
pnpm --dir web api:types:check
```

Backend models, the canonical snapshot, generated TypeScript, and UI aliases are one fail-closed contract chain. The runtime API itself does not expose OpenAPI or documentation routes.

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
