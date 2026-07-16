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

### D-023 — Add bounded persisted-evidence inspection without revalidation

**Status:** Accepted for M4-D on 2026-07-16.

**Decision:** Advance the read API to 1.1.0 and expose a normalized inspection view over persisted specification features plus the known `geometry_validation_report`, `printability_report`, `gcode_preflight`, `printer_profile`, `material_profile`, `process_profile`, and `orientation_profile` roles. Verify report/profile size and SHA-256 before parsing. Keep revision listings lightweight and parse detail evidence only when a revision is opened.

**Evidence boundary:** The browser may select requirements, checks, findings, profiles, measurements, and artifact records for explanation. It must not imply that selection spatially identifies STEP topology, rerun geometry or printability code, alter a finding, promote an evidence level, or provide physical proof. General artifact checksums remain recorded values until the checksum-verifying open/download route is used; report/profile sources explicitly state when verification occurred before parsing.

**Resource and failure policy:** Known JSON inputs are capped at 2 MiB, 500 checks, 100 messages, 100 specification features, 128 inspection fields, nesting depth 16, and 20,000 nodes. Missing files, duplicate roles, size drift, checksum drift, invalid JSON, non-finite values, or unsupported shapes produce explicit unavailable records and no parsed pass state. Gate fixtures expose no complete-feature inspection data.

**Evidence:** The deterministic complete fixture contains eight artifacts and yields three reports with nine fixture checks, four fixture profiles, and seven fixture-labelled requirements. An existing real R4 revision yielded 61 persisted checks, five physical-warning messages, four profiles, and seven requirements with no unavailable source. Tests cover deterministic fixture bytes, checksum mutation, valid-checksum invalid JSON, the size ceiling, generated contract drift, unavailable presentation, and lightweight listings. The current OpenAPI snapshot is 42,933 bytes with SHA-256 `ae0d99263ecb847c2a4991166a18069aa467db68d8c6beb0b5b787c644734218`, four paths, and 26 schemas.

**Dependency reason:** No runtime or development dependency was added. The parser uses the existing Python standard library and Pydantic response boundary; the React explorer uses existing application primitives.

**Runtime impact:** One local cold read of the existing R4 detail produced an 81,588-byte compact JSON response in approximately 39.9 ms; the fixture detail produced 22,952 bytes in approximately 16.6 ms. These observations are not latency guarantees. The production application entry is approximately 100.4 KB gzip and CSS is approximately 4.3 KB gzip; the previously lazy Three.js path is unchanged.

**Removal path:** Remove the inspection models/parser, API 1.1 field, fixture report/profile artifacts, `EvidenceInspector.tsx`, and the Evidence tab. Artifact downloads, stage records, GLB preview, toolpath playback, and R0–R4 pipeline evidence remain intact.

**Consequence:** Future report types must earn an explicit role adapter, bound, corruption tests, generated-contract update, and claim language. Do not pass arbitrary artifact JSON directly through to the browser as trusted evidence.

### D-024 — Compare normalized persisted revisions on the server

**Status:** Accepted for M4-E on 2026-07-16.

**Decision:** Advance the read API to 1.2.0 and add one GET-only revision-comparison contract. The server loads both revisions through the existing fail-closed repository, normalizes semantic records, and returns only added, removed, or changed rows. The browser selects revisions and renders this response; it does not independently derive evidence differences.

**Semantic boundary:** Compare stage state, selected top-level requirements, specification features, report summaries/measurements/messages, checks, findings, profiles, persisted artifact checksums/metadata, and package state. Match records by stable semantic keys and omit generated revision, stage, event, artifact, finding, decision, and approval IDs plus timestamps and download availability. A comparison does not rerun CAD, geometry validation, printability assessment, slicing, G-code preflight, simulation, or physical work. “Unchanged” means only that the normalized persisted values matched; it does not prove exact geometric or physical equivalence.

**Resource and failure policy:** Normalize at most 10,000 records per revision, return at most 1,000 changed rows, and include at most 64 KiB of canonical JSON detail per side of a row. Oversized values are replaced by their canonical byte count and SHA-256. Record omissions, output omissions, and oversized values are counted explicitly, and `complete` is false whenever any bound prevents complete detail.

**Evidence:** The new deterministic child fixture is revision 2 of the same fixture job and names revision 1 as its parent. Both sides expose 66 normalized records. A revised bore and infill request produces exactly 12 semantic changes: one stage, four requirements, one feature, one report, one check, one profile, and three artifact checksums. Tests prove same-revision emptiness, parent/child and unrelated relationships, volatile-field exclusion, large-value hashing, change and input-record limits, GET-only behavior, missing-revision failure, deterministic fixture bytes, and no journey mutation. The full pinned suite passes 80 backend tests; the frontend passes seven deterministic tests plus two real-artifact integration tests.

**Contract evidence:** The canonical OpenAPI snapshot is 54,318 bytes with SHA-256 `1f177747402776e8bcb71715707c908eb14314f4a722310b5141368e2e200cb0`, five GET paths, and 30 schemas. Generated TypeScript is 27,578 bytes with SHA-256 `2fc169828fcd8f0ef34d1dcbd2df9375c97de668c9f473948852dcba65fd1d44`. Backend and frontend drift checks pass.

**Dependency and runtime impact:** No dependency was added. Comparison uses the Python standard library and existing Pydantic/FastAPI boundary; the browser uses existing React and Router primitives. The production application entry is approximately 102.1 KB gzip and CSS is approximately 5.3 KB gzip. The existing lazy Three.js chunk remains approximately 184.7 KB gzip.

**Removal path:** Remove `api/comparison.py`, the comparison models/repository/GET route, the child fixture, `ComparisonView.tsx`, the index picker and comparison route, and regenerate OpenAPI/TypeScript. Revision detail, evidence inspection, artifact reads, visualization, and the R0–R4 pipeline remain intact.

**Consequence:** Future comparison areas must define a stable semantic key, exclude runtime noise, preserve claim boundaries, and earn explicit resource/failure tests. Do not move the authoritative diff into the browser or interpret a zero-row result as equivalence proof.

### D-025 — Serve bounded verified artifact snapshots

**Status:** Accepted for M4-F on 2026-07-16.

**Decision:** Advance the read API to 1.2.1 and replace path-backed `FileResponse` delivery with one bounded in-memory snapshot. Read at most the recorded size plus one byte, never more than 64 MiB plus one byte, and construct the response only from the bytes whose size and SHA-256 were accepted. Do not reopen the filesystem path after verification.

**Integrity and transport boundary:** A recorded artifact larger than 64 MiB or an unrecorded-size artifact that crosses the same ceiling returns 413. Missing files return 404; malformed revisions, size/checksum drift, unreadable files, invalid evidence modes, and invalid type/subtype media values return 409. Successful responses use the validated recorded media type, RFC 5987 attachment filename, checksum ETag, `sha256-verified-snapshot`, evidence mode, 64 MiB ceiling, `no-store`, `nosniff`, and `hardware-action: false` headers. The generic OpenAPI content schema is binary `application/octet-stream`; runtime `Content-Type` remains the validated recorded type.

**Evidence:** A regression test mutates the backing file after repository verification but before response construction and proves that HTTP still returns the original byte-identical snapshot and matching checksum. Additional tests enforce the 413 ceiling, reject CR/LF-bearing media/evidence metadata before header construction, require binary/error/header OpenAPI semantics, and preserve existing checksum-drift failures. A live loopback HTTP check returned the 178-byte fixture snapshot with its exact recorded SHA-256 and every required boundary header. The full pinned suite passes 84 backend tests; frontend contract generation, seven deterministic tests, two real-artifact integration tests, lint, and production build pass.

**Contract evidence:** The canonical OpenAPI snapshot is 58,589 bytes with SHA-256 `a98aff4a7b609536a08b85bea5d11919a20210daccfd90427bd68b39415cff38`, five GET paths, and 31 schemas. Generated TypeScript is 30,693 bytes with SHA-256 `737b3ffc3a0ed0144ced4d1dbbf61850a247669e0967c14e360ca5a2cde37d1f`.

**Resource and dependency impact:** No dependency was added. Each concurrent artifact response may retain up to 64 MiB until Starlette finishes constructing/sending the response; the ceiling matches the existing GLB and G-code browser input limits and is acceptable for the loopback-only M4 service. Production frontend bundle sizes are unchanged.

**Removal path:** Reverting to path-backed streaming removes the per-response memory snapshot but reintroduces the verify-then-send race. A future replacement must preserve snapshot identity, resource limits, headers, and tests, for example through an immutable content-addressed store or a sealed temporary snapshot.

**Consequence:** Every claim that an artifact download is checksum-verified now applies to the bytes actually returned. Other persisted file readers must adopt bounded snapshot reads before their size ceilings can be described as allocation bounds.

### D-026 — Use one bounded snapshot reader for persisted files

**Status:** Accepted for M4-G on 2026-07-16.

**Decision:** Advance the read API to 1.2.2 and route root persisted records, inspection report/profile JSON, and artifact downloads through `api/bounded_io.py`. With no recorded size, request at most the ceiling plus one byte. With a recorded size at or below the ceiling, request at most that size plus one byte. Distinguish missing, unreadable, oversized, and size-mismatched files so each caller can preserve its public failure semantics.

**JSON boundary:** Root `journey.json`, optional manifest/package/fixture records are capped at 32 MiB plus one detection byte, then at depth 32 and 200,000 nodes. Inspection JSON retains 2 MiB plus one detection byte, depth 16, and 20,000 nodes before role-specific field/list limits. Both parsers reject duplicate object keys, non-finite JSON constants, invalid UTF-8, recursion failures, and non-object roots. Finding resolution must be an actual JSON boolean; package measurements and numeric mappings must be actual finite JSON numbers rather than coercible strings.

**Evidence:** Tests prove the primitive requests only ceiling-plus-one or expected-size-plus-one, rejects an expected size above the ceiling before reading content, distinguishes missing from unreadable paths, and identifies size mismatch. Repository tests prohibit `Path.read_text` and `Path.read_bytes`, force root byte/node limits, reject duplicate keys and NaN, reject duplicate inspection keys after checksum verification, and reject string values that previously could become `True` or non-finite floats. Existing artifact snapshot, inspection integrity, comparison, real CAD, and real slicer tests remain green. The full pinned suite passes 91 backend tests; all frontend contract, test, lint, and build gates pass.

**Contract evidence:** The canonical OpenAPI snapshot remains 58,589 bytes with five GET paths and 31 schemas; API-version drift changes its SHA-256 to `fbda3cf6e28f68bbe5a0fae9865d976c571d44b5beea5b2924ea070bf32da06d`. Generated TypeScript remains 30,693 bytes with SHA-256 `541d2e55c4a021aec44e3e62d32887060e26c316a6fda3432cbc49c300ee8b4c`.

**Resource and limitation boundary:** No dependency was added. Byte allocation during file capture is explicitly capped, but Python's standard JSON decoder still materializes a parsed value before the post-parse node/depth walk. The 32 MiB/2 MiB byte ceilings are therefore also the primary parser-amplification controls; this is not an operating-system memory sandbox.

**Removal path:** Remove `api/bounded_io.py` and restore per-call reads only if every replacement preserves a positive read size, oversize detection byte, missing/unreadable/size-drift distinctions, duplicate/non-finite rejection, complexity checks, and the regression tests. Unbounded convenience reads are not an acceptable removal path.

**Consequence:** Persisted-file size limits now constrain the bytes requested from the filesystem rather than checking only before or after an unbounded allocation. Revision discovery/listing still needs its own work-count and truncation contract.

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
