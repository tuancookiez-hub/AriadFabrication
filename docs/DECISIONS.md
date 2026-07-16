# Decision log

This file records accepted project-level decisions. Change an accepted decision only through an explicit follow-up entry that states what new evidence changed the direction.

## Accepted decisions

### D-001 — Build a durable product, not a deadline-shaped demo

**Status:** Accepted  
**Decision:** Milestone evidence determines progress. A hackathon submission is an optional checkpoint.  
**Consequence:** Hardware, UI polish, and provider breadth cannot bypass core reliability gates.

### D-002 — Functional parametric CAD is the primary lane

**Status:** Accepted  
**Decision:** Dimension-critical parts use editable B-rep CAD. CadQuery/OCCT is the first implementation path.  
**Consequence:** Hosted text-to-mesh providers are not the default for brackets, clamps, enclosures, mounts, or robotics parts.

### D-003 — Organic generation is a separate lane

**Status:** Accepted  
**Decision:** Organic/decorative models may later use mesh-generation providers and Blender, with separate validation and claim language.  
**Consequence:** Mesh-provider success does not qualify the functional-CAD pipeline.

### D-004 — Use Python for the CAD core and TypeScript for the interface

**Status:** Accepted  
**Decision:** Continue the current Python package for orchestration, CAD, validation, and slicer workers. Build the browser interface with React/TypeScript.  
**Consequence:** The system is not forced into one language. Go may be introduced later for a control plane or printer-side service only when it solves a measured need.

### D-005 — Local-first and printer-independent

**Status:** Accepted  
**Decision:** The complete digital pipeline must run without owning a printer and without a mandatory cloud mesh provider.  
**Consequence:** The package/export stage is a valid terminal state. Hardware purchase is deferred until the pipeline produces trustworthy evidence.

### D-006 — Fabrication Journey is the primary UX model

**Status:** Accepted  
**Decision:** Present jobs as an inspectable stage journey with immutable revisions, real events, findings, decisions, artifacts, and approvals.  
**Consequence:** The UI cannot use fake progress or hide stage failures behind a chat transcript.

### D-007 — Evidence-gated reliability claims

**Status:** Accepted  
**Decision:** Use the R0–R7 evidence ladder from `RELIABILITY.md`.  
**Consequence:** “Printable,” “safe,” “strong,” and “validated” require qualification. Simulation and physical measurement remain distinct.

### D-008 — Deterministic tools own validation and G-code

**Status:** Accepted  
**Decision:** The model can parse, plan, call tools, explain, and propose repair. Exact geometry queries and a real slicer own manufacturing evidence.  
**Consequence:** An LLM never directly authors final production G-code or waives deterministic failures.

### D-009 — Open formats and replaceable adapters

**Status:** Accepted  
**Decision:** Preserve parametric source; use STEP for exact interchange, 3MF for manufacturing packages, GLB for browser visualization, and STL only for compatibility.  
**Consequence:** CAD, slicer, model, and printer providers remain replaceable behind versioned contracts.

### D-010 — Human approval before physical action

**Status:** Accepted  
**Decision:** Hardware adapters default to disconnected/read-only. Heating, motion, upload/start, or recovery requires explicit policy and approval.  
**Consequence:** Printer automation is not part of the early critical path, and simulated recovery cannot pretend physical work occurred.

### D-011 — Golden Part before interface breadth

**Status:** Accepted  
**Decision:** First prove one deterministic plant-stake electronics clamp from specification through real slicing.  
**Consequence:** AI intake and the full interface are built around real artifacts rather than placeholders.

### D-012 — OpenGrow is the reference application, not the platform boundary

**Status:** Accepted  
**Decision:** Planting and robotics provide coherent benchmark parts while Ariad Fabrication remains a general fabrication developer tool.  
**Consequence:** Domain examples guide the roadmap without hardcoding agricultural concepts into core contracts.

### D-013 - Pin CadQuery 2.8.0 and OCP 7.9.3.1.1 for M2

**Status:** Accepted from the M2 installation spike on 2026-07-16.  
**Decision:** Use CPython 3.11 with optional dependencies `cadquery==2.8.0` and `cadquery-ocp==7.9.3.1.1` for the deterministic CAD worker. Lock transitive packages with `uv.lock`; keep CAD optional so the R0 Brief workflow remains lightweight.  
**Evidence:** On Windows AMD64, the isolated environment created one valid solid, exported STEP and STL, re-imported STEP as one valid solid, and preserved exact 20 x 10 x 5 mm bounds.  
**Dependency reason:** CadQuery provides editable Python parametric source while OCP exposes the OCCT solid-modeling and exchange kernel required for deterministic geometry queries.  
**License:** CadQuery and cadquery-ocp report Apache-2.0; VTK, a transitive visualization dependency, reports BSD. A complete distribution-license audit remains required before public release.  
**Runtime impact:** The resolved environment contains 44 packages, occupies approximately 1.0 GiB, and measured about 3.3 seconds for a cold CadQuery import on the development machine.  
**Removal path:** Remove the `cad` optional dependency, `uv.lock`, and CAD worker modules. Existing PartSpec and Fabrication Journey contracts remain usable, with the CAD provider reported as unavailable rather than simulated.

### D-014 - Restrict M2 CAD execution to registered repository source

**Status:** Accepted from the M2 implementation on 2026-07-16.  
**Decision:** The M2 worker may execute only an explicitly registered, hand-authored provider shipped with the repository. Its separate process, timeout, environment allowlist, path confinement, atomic publication, checksum verification, and quarantine behavior are an isolation boundary, not a hardened sandbox for arbitrary Python.  
**Consequence:** No model-generated or user-supplied CAD program may enter this worker. Network denial, enforceable memory/process limits, and stronger operating-system confinement must be implemented and tested before untrusted generated code is enabled. Deterministic recipe parameters can still pass through the versioned request contract.

### D-015 - Pin PrusaSlicer 2.9.6 for the first real slicer adapter

**Status:** Accepted from the M3 compatibility spike on 2026-07-16.  
**Decision:** Use the official portable PrusaSlicer 2.9.6 Windows release as the first disconnected real-slicer adapter. Keep OrcaSlicer behind the same future provider boundary rather than coupling profile contracts to one executable.  
**Evidence:** The dedicated `prusa-slicer-console.exe` inspected the official 3DBenchy and Ariad conventional-warship STLs, exported profile-bearing 3MF projects, produced G-code for both under one profile, and exposed model-repair and print-stability warnings in headless logs. Both G-code files passed the new profile-specific preflight; the warnings remained findings rather than being converted into passes.  
**Dependency reason:** PrusaSlicer has a documented Windows console path, accepts explicit INI profiles, emits inspectable text G-code, and can export a configuration-bearing 3MF project without a printer connection.  
**License:** The PrusaSlicer repository identifies AGPL-3.0. A distribution audit remains required before bundling its binaries with a public Ariad Fabrication release.  
**Runtime impact:** The official archive is 106,598,059 bytes with SHA-256 `5aaf22e42f95accecfa122d23a835911f289ecc2ff606db3e83d637ddcc0a209`; the extracted portable tree is 261,683,165 bytes across 1,119 files. Median local console help startup was approximately 389 ms across three warm runs.  
**Boundary:** The adapter uses an explicit executable, profile, local data directory, timeout, minimal inherited environment, and disconnected artifacts. It does not yet enforce network denial or operating-system memory/process limits and cannot dispatch hardware.  
**Removal path:** Delete the ignored portable runtime under `runs/tools/prusaslicer`, remove this adapter selection, and retain the versioned profile contracts, G-code parser, benchmark fixture, and replaceable provider boundary.

### D-016 - Adopt Ariad Fabrication and evidence-first positioning

**Status:** Accepted from the user naming decision and landscape review on 2026-07-16.  
**Decision:** The official product name is **Ariad Fabrication**, shortened to **Ariad**. **Fabrication Journey** remains the primary experience and **OpenGrow** remains the first reference application. The product is positioned around trustworthy functional-CAD evidence and a printer-independent fabrication package, not around being the first generic prompt-to-print agent.  
**Evidence:** A primary-source review found substantial overlap at individual stages and one close full-lifecycle project: Kiln covers agent-driven generation, printability, slicing, printer control, and monitoring; AgentSCAD covers a persistent text-to-OpenSCAD validation workspace; CADSmith covers CadQuery generation with OCCT-grounded refinement; and AgentsCAD covers FDM-oriented B-rep modification. None of that evidence changes Ariad's accepted focus on exact feature checks, immutable lineage, explicit evidence levels, no-printer usefulness, and fail-closed claims.  
**Name boundary:** `Ariad` is a coined shortening of Ariadne and provides the thread-through-the-labyrinth metaphor. A preliminary collision search found unrelated existing uses of the bare word, so **Ariad Fabrication** is the public lockup. This is not trademark clearance.  
**Consequence:** Rename repository-owned package, command, schema-title, profile-author, and artifact-producer identifiers from the unpublished SOL working name. Do not rewrite ignored historical run artifacts, change evidence semantics, or advance an evidence level as part of the rename. Avoid first/only claims in product messaging.  

### D-017 - Freeze the first R3 profile and conservative printability policy

**Status:** Accepted from the M3 Golden Part implementation on 2026-07-16.  
**Decision:** Assess the first Golden Part orientation against the exact `generic_open_fdm_220_v1`, `generic_petg_175_v1`, `golden_part_020_no_support_v1`, and `upright_source_z_centered_v1` bundle. Freeze the policy in `benchmarks/golden_part/printability_expected.json` instead of hiding thresholds in validator code. Use 5 mm build margins, a three-nozzle wall rule, a two-nozzle open-feature rule, a 0.8 maximum layer/nozzle ratio, 100 mm2 minimum digital bed contact, a conservative 45 degree overhang threshold, a 5 mm bounded internal-bridge limit, and one-nozzle nominal elephant-foot clearance.  
**Evidence:** Prusa's official modeling guidance describes conventional 0.4 mm desktop-FDM overhang capability in the 45 to 60 degree range and says short horizontal bridges may work; its PETG guidance states PETG bridging and overhang behavior is generally worse. The 45 degree and 5 mm values are therefore Ariad screening thresholds, not universal PETG capability claims. The exact Golden Part passes all 23 checks; its three horizontal holes measure 3.4, 3.4, and 4.0 mm, and unresolved steep area outside bed/bridge classifications is zero.  
**Profile boundary:** Generic PETG values derive from the official Prusa PETG guidance and the Generic PETG preset bundled with the pinned PrusaSlicer 2.9.6 release. They are not calibrated to a filament brand, batch, printer, hotend, or build surface.  
**Consequence:** R3 permits the claim “printability-assessed for this profile” while retaining five physical unknowns. A different orientation, nozzle, material, process, printer, or threshold policy requires a new assessed revision or superseding frozen benchmark policy.

### D-018 - Require fail-closed slicer findings and a printer-independent R4 package

**Status:** Accepted from the M3 vertical slice on 2026-07-16.  
**Decision:** A real slicer exit is necessary but insufficient for R4. G-code preflight must pass; any repair reported for exact CAD, any floating-bridge-anchor warning under the support-disabled process, and any unclassified slicer warning block R4. Low-bed-adhesion may advance only as an unresolved warning. A passing run must then satisfy the package-role and checksum gate.  
**Evidence:** The accepted Golden Part run used the pinned PrusaSlicer 2.9.6 console, reported one manifold part with zero repairs and no slicer warnings, produced 250 layers and profile-bearing 3MF/G-code artifacts, passed disconnected preflight, and completed a 36-artifact manifest. Oversized volume, profile drift, unsupported temperature, multiple tools, malformed G-code, timeout, repair, and warning-policy tests fail closed.  
**Hardware boundary:** The package records `printer_selected`, `printer_connected`, `gcode_uploaded`, and `print_started` as false. R4 is a valid terminal digital state and provides no authority to dispatch G-code.  
**Consequence:** The only allowed current manufacturing claim is “slicer-verified for this recorded profile.” Physical printing, measurements, and repeated calibration remain R6/R7 work.

### D-019 - Adopt the user-approved Ariad Fabrication logo

**Status:** Accepted from the user's explicit visual-identity decision on 2026-07-16.  
**Decision:** The exact user-supplied raster preserved as `assets/ariad-fabrication-official-logo.jpg` is the primary official logo for Ariad Fabrication. Preserve its bytes and composition as the source master unless the user explicitly approves a replacement.  
**Provenance:** The imported 1280 x 720 JPEG is 112,016 bytes with SHA-256 `aca34f265b9d0600bf0f0bde4afa78616d0bb412dee53dbddf99d9e4712b7821`. The repository copy matches the supplied attachment byte-for-byte.  
**Identity boundary:** `assets/ariad-fabrication-journey-banner.png` remains explanatory product-story artwork, not the project logo. Transparent, square, monochrome, vector, favicon, and other derived variants are not official until reviewed and approved.  
**Rights boundary:** Project adoption records the user's branding choice; it is not trademark clearance or a documented public-redistribution license.  
**Consequence:** Use the official logo at project entry points. Do not silently redraw, crop, recolor, recompress, or present a generated approximation as the master.

### D-020 - Use a local FastAPI boundary and Vite React client for M4

**Status:** Accepted from the first M4 vertical slice on 2026-07-16.  
**Decision:** Implement the first application boundary with FastAPI 0.139.1 and Uvicorn 0.51.0, and implement the separate browser client with React 19.2.7, React Router 7.18.1, Vite 8.1.4, and TypeScript 6.0.3. The initial API reads immutable filesystem revisions and binds to loopback only. The Vite development server proxies `/api`; no Node server owns domain state. Vite is exactly pinned to 8.1.4 because 8.1.5 was only hours old during implementation and failed pnpm's minimum-release-age policy.  
**Contract boundary:** M4-A exposes revision lists, grouped persisted stages, events, findings, artifacts, compact package evidence, and checksum-verified downloads. It offers no mutation or printer endpoint. Missing manifests remain visibly absent, malformed records fail closed, and interface fixtures remain `fixture` evidence even when they demonstrate an R0-R4-shaped timeline.  
**Dependency reason:** FastAPI publishes explicit OpenAPI response contracts around the existing Python domain. Uvicorn provides the local ASGI process. React and React Router provide the stateful journey and revision surfaces, while Vite supplies the development/build boundary and Vitest/Testing Library/ESLint provide frontend checks. Ruff provides a fast Python static-analysis gate. TypeScript 6.0.3 is deliberately selected instead of 7.0.2 because the current TypeScript-ESLint 8.64.0 support range is below 6.1.  
**License:** FastAPI, React, React DOM, React Router, Vite, Vitest, ESLint, and Ruff report MIT. Uvicorn and HTTPX2 report BSD-3-Clause. TypeScript reports Apache-2.0. A complete transitive and distribution audit remains required before public release.  
**Runtime impact:** Before M4-B visualization, the locked frontend development tree contained 240 installed package directories, approximately 138.7 MB across 9,208 files. The Python lock adds the FastAPI/Pydantic/Uvicorn application stack while keeping CadQuery optional. M4-B visualization impact is recorded separately in D-021.  
**Visual boundary:** anime.js, Motion.dev, Kokonut UI, Bklit UI, and Manus.im are recorded as inspiration only. None is an installed dependency or accepted design-system choice.  
**Removal path:** Delete `web/`, the `ariad_fabrication.api` package, the two interface console scripts, FastAPI/Uvicorn/HTTPX2 dependencies, the interface benchmark, and M4 workflow checks. The R0-R4 domain, CAD, slicer, package, and persisted-record contracts continue to work through the CLI.  
**Consequence:** Continue M4 against this read-only boundary. Add 3D inspection, toolpath playback, streaming, and visual libraries only when they preserve the same evidence semantics and earn their own tests.

### D-021 — Use direct Three.js inspection and a worker-owned G-code parser

**Status:** Accepted for M4-B on 2026-07-16.  
**Decision:** Pin Three.js and its type definitions to 0.185.1 for the GLB inspection surface. Use Three.js directly with `GLTFLoader` and `OrbitControls`; do not add React Three Fiber or `<model-viewer>` for the first viewport. Parse the already-approved G-code artifact in a dedicated browser Web Worker rather than the UI thread or a new server mutation surface.  
**Evidence boundary:** The GLB is a tessellated preview; STEP remains exact geometry. Toolpath playback covers recorded linear G0/G1 XY moves by layer. It is not collision, extrusion, thermal, structural, fluid, or physical simulation. Unsupported arcs are counted and disclosed. Both inputs are served only after repository checksum verification and are capped at 64 MiB; the viewport also caps models at two million triangles and the parser caps toolpaths at one million segments.  
**Dependency reason:** Direct Three.js supplies the maintained glTF 2.0 loader, camera, WebGL renderer, and controls without adding another React renderer. The custom worker parser keeps the 5.18 MB Golden Part G-code and its approximately 176 thousand linear commands off the UI thread while avoiding another runtime dependency.  
**License:** Three.js and `@types/three` report MIT. A complete transitive and distribution audit remains required before public release.  
**Runtime impact:** The locked frontend tree now contains 248 installed package directories, approximately 176.0 MB across 11,443 files. The production build keeps the approximately 98 KB gzip application entry separate from a 4.9 KB worker and a lazy Three.js/GLTFLoader/OrbitControls path of approximately 202 KB gzip. Vite reports the 724 KB minified Three.js module chunk as larger than its default warning threshold; the chunk is loaded only when a GLB inspector mounts.  
**Removal path:** Remove `three`, `@types/three`, `ModelInspector.tsx`, and the model integration test to return to artifact downloads only. Remove `ToolpathInspector.tsx`, `toolpath.ts`, `toolpath.worker.ts`, and their tests to remove playback. Persisted R0–R4 artifacts and the read API remain unchanged.  
**Consequence:** Keep richer dimensions, cross-sections, feature selection, and comparison behind the same preview boundary. Reassess a higher-level renderer only if direct Three.js lifecycle or accessibility costs exceed the measured benefit.

### D-022 — Generate the browser API contract from canonical OpenAPI

**Status:** Accepted for M4-C on 2026-07-16.

**Decision:** Generate and commit a canonical OpenAPI 3.1 snapshot from FastAPI, then generate the browser response definitions with exactly `openapi-typescript` 7.13.0. Pin TypeScript to 5.9.3, the newest selected compiler in the generator's supported peer range. This supersedes only D-020's TypeScript 6.0.3 compiler selection; the Python/React application boundary remains unchanged.

**Contract boundary:** Every field emitted by the read API is required in OpenAPI even when its value is nullable or an empty collection. `read_only` is the literal `true`, `hardware_actions` is the literal `false`, and only the four GET application paths enter the snapshot. Runtime `/docs`, `/redoc`, and `/openapi.json` routes are disabled. The frontend imports schema aliases from the generated file instead of maintaining parallel handwritten response interfaces.

**Evidence:** The canonical snapshot is 30,128 bytes with SHA-256 `27b274641a4a0184824d583a710074ab2cdd6063287e2a611a2dd08a86c4dfa4`, four paths, and 18 schemas. Backend tests detect snapshot, route, API-version, health-identity, capability-constant, required-field, and writer drift. Frontend tests run the generator's `--check` before TypeScript and component tests. Both checks run independently in CI, and `pnpm peers check` reports no issue.

**Dependency reason:** Generated definitions make a backend response change fail close at the contract boundary before it can become an unchecked browser assumption. The generator is development-only and contributes no browser runtime code.

**License:** `openapi-typescript` reports MIT; TypeScript reports Apache-2.0. A full transitive and distribution-license audit remains required before public release.

**Runtime impact:** The locked frontend development tree contains 294 package directories, approximately 226.7 MiB across 15,057 files after adding the generator. Production bundle sizes are unchanged because the generator and types are development-only.

**Removal path:** Remove `openapi-typescript`, the two `api:types` scripts, `web/src/generated/`, the interface snapshot generator and snapshot, and restore manually maintained browser response interfaces. The runtime API and persisted evidence remain functional, but automated cross-language drift detection is lost.

**Consequence:** Treat `src/ariad_fabrication/api/models.py` as the response-model source, regenerate the snapshot and TypeScript in the same change, and reject unexplained generated-file differences.

## Deferred decisions

These require later evidence and should not be decided through preference alone:

- Physical stake fit and printer/material compensation — M7 measurements.
- Job runner, event transport, and production frontend serving — later M4 work.
- Exact OpenAI model routing and cost policy — M5 evaluation.
- First printer purchase and strict definition of open hardware — M7 procurement audit.
- Whether a Go control plane is operationally justified — M7 or later.
- Organic mesh provider — M8 provider benchmark.
- FEA/robot simulation stack — M8 with calibration evidence.
- Public repository license — before public release.

## Rejected assumptions

- “Zero CAD” is not the product claim; users may avoid manually authoring CAD, but the system relies on real editable CAD.
- A successful STL export is not evidence of printability.
- A successful slice is not evidence of physical fit or strength.
- Open-source firmware alone does not establish that an entire printer is open-source hardware.
- A single implementation language is not a product objective.
- A camera or model-based monitor is not a safety system.
