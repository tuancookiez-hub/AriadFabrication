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

### D-027 — Bound revision discovery and disclose live listing windows

**Status:** Accepted for M4-H on 2026-07-16.

**Decision:** Advance the read API to 1.3.0. Discover revisions with non-symlink-following directory scans that examine at most 5,000 job/revision entries and retain at most 500 candidates. Sort the observed set by job ID then revision ID, accept offsets only through 500 and page sizes from 1 through 200, and load root JSON only for the selected page.

**Truth boundary:** Every list response includes discovery completeness, entries examined, observed candidate count, returned and observed-omitted counts, next offset, truncation reasons, fixed ordering, active ceilings, and a claim boundary. `snapshot_consistent` is always false because each request rescans the live local directory. An incomplete discovery is not an exact total, and records may shift between offset pages if files change.

**Evidence:** Repository tests prove a two-record page performs exactly two revision loads, candidate and directory ceilings produce explicit incomplete results, and default fixture discovery returns six observed candidates without truncation. HTTP tests prove offset/page limits return 422 before discovery. The React status region exposes incomplete discovery, reasons, non-snapshot language, and bounded Previous/Next offsets. A live loopback request for offset 2 / limit 2 returned API 1.3.0, two records, six observed candidates, next offset 4, `window_limit`, and `hardware_actions: false`. The full pinned suite passes 96 backend tests; generated-type drift, eight deterministic frontend tests, lint, and production build pass.

**Contract evidence:** The canonical OpenAPI snapshot is 62,597 bytes with SHA-256 `2425427793d2a6d88e408efb17b8af05b5d1c225bd03ab6d51a37efe1c2fc974`, five GET paths, and 32 schemas. Generated TypeScript is 32,529 bytes with SHA-256 `2ffb742b31be693178d3127a4b96926e1f1339c569a72afef4891dee7b7241da`.

**Resource and dependency impact:** No dependency was added. Filesystem metadata work is bounded per request, and at most 200 selected root records are parsed. Directory ordering is normalized after discovery rather than trusted from the operating system. The bound is a service-safety limit, not proof that the run tree contains no additional revisions.

**Removal path:** A database, immutable content-addressed index, or sealed catalog snapshot may replace live scanning if it preserves path confinement, bounded work, exact completeness semantics, deterministic ordering, and tests. Returning to recursive unbounded enumeration or silently truncated totals is not acceptable.

**Consequence:** Read-only listing can no longer perform work proportional to an arbitrary run tree or imply that a bounded observation is globally complete. Stable multi-request snapshot pagination remains deferred and explicitly unclaimed. The next integrity gap is strict validation of persisted lifecycle/status/evidence vocabularies before presentation.

### D-028 — Fail closed on unsupported persisted lifecycle and evidence state

**Status:** Accepted for M4-I on 2026-07-16.

**Decision:** Advance the read API to 1.4.0. Use the domain enums for job, fabrication-stage, stage-status, evidence-level/mode, finding-severity, decision-actor, and approval-status fields, and API-specific closed enums for package and inspection state. Publish those closed values into OpenAPI-generated browser types. Package hardware fields remain literal `false`, not general booleans.

**Integrity boundary:** Before returning revision detail or any artifact, validate revision/job ownership; every referenced record's job/revision/stage ownership; unique event sequence numbers within a stage; stage status against required start/completion timestamps, evidence, and errors; decision/approval state; fixture-only evidence modes; runtime/fixture package schema, classification, status, and R4 evidence; manifest decision/approval parity; and disabled package hardware fields. Unsupported checksum-verified inspection status/evidence/profile shapes become `unsupported_shape` unavailable records rather than plausible passes. This is persisted-record integrity validation, not rerunning CAD, validators, slicing, simulation, or physical work.

**Evidence:** Mutation tests reject unsupported job/stage/event/finding/package/evidence values, foreign revision ownership, cross-stage references, duplicate per-stage event sequences, invalid terminal-stage combinations, mixed fixture/runtime evidence, enabled hardware flags, invalid decision actors, and inconsistent approvals. Tests prove artifact reads inherit the same fail-closed lifecycle load and that unsupported inspection states remain unavailable. The full pinned suite passes 101 backend tests; all seven ignored real R2/R4 revisions remain available. Generated-contract drift, eight deterministic frontend tests, lint, and production build pass. A live loopback check returned API 1.4.0, a bounded two-of-six revision page with `snapshot_consistent: false`, and a byte-identical 178-byte artifact whose checksum matched its ETag while all hardware-action indicators remained false.

**Contract evidence:** The canonical OpenAPI snapshot is 68,528 bytes with SHA-256 `69b53bcdbcf8471b5d1d1465843582b1df5e5203131dd3e3cf846ed0b3242b2d`, five GET paths, and 45 schemas. Generated TypeScript is 35,921 bytes with SHA-256 `839c63852b3527eaf6ff681af25a855115aa4d5689d4c93c12de758c22403963`.

**Resource and dependency impact:** No dependency was added. Validation is linear in records already admitted by the existing bounded JSON and comparison/list ceilings. The stricter model adds enum schemas and approximately 3.4 KiB to generated TypeScript; production frontend bundle sizes are unchanged.

**Removal path:** A future persisted-schema migration may replace individual checks only if it preserves closed vocabularies, ownership and cross-field validation, literal-false hardware state, inspection-unavailable semantics, and regression coverage. Widening generated types back to arbitrary strings or booleans is not acceptable.

**Consequence:** Unsupported lifecycle language can no longer become a credible UI status, and fixture/package state cannot silently imply real or physical progress. Generic scalar-text coercion, timezone-aware timestamp parsing, and temporal ordering remain the next persisted-integrity gap.

### D-029 — Preserve scalar types and validate persisted chronology

**Status:** Accepted for M4-J on 2026-07-16.

**Decision:** Advance the read API to 1.5.0. Journey-domain and read-repository text fields accept only actual strings; optional text accepts only strings or null. Typed inspection numerics accept only finite JSON numbers. Parse persisted lifecycle timestamps as timezone-aware ISO 8601 values, emit canonical UTC strings, and mark every exposed timestamp as OpenAPI `date-time`.

**Temporal boundary:** Require job update at or after job creation; revision creation within the job window; stage timestamps within the job window and nondecreasing persisted stage order; completion at or after start; completion for cancelled/superseded stages; event timestamps within job/stage bounds, globally unique sequence numbers, nondecreasing sequence time, and a final event matching current stage state; approval decisions at or after requests; revision-owned record creation within revision/job bounds; and manifest generation at or after job update and all manifest records. Brief stages and their events may begin after job creation but before revision materialization, because the first revision is an output of Brief.

**Evidence:** Adversarial tests reject numbers, booleans, arrays, and objects in required/optional journey text; numeric and naive/invalid timestamps; reversed job, revision, stage, event, approval, and manifest times; duplicate global event sequences; final-event drift; missing cancelled-stage completion; non-string metadata keys; and numeric strings in typed inspection fields. Unsupported checksum-verified inspection scalar shapes become unavailable. A replay of all seven ignored real revisions initially exposed one legitimate Brief-before-revision trace, which refined the lower temporal bound from revision creation to job creation for stages/events; all seven then pass with 11 reports and eight profiles. The full pinned suite passes 108 backend tests; generated-contract drift, eight deterministic frontend tests, lint, and production build pass. A live loopback check returned API 1.5.0, canonical timezone-aware job/event values, a bounded two-of-six revision page, and the checksum-matched 178-byte artifact with hardware actions false.

**Contract evidence:** The canonical OpenAPI snapshot is 68,894 bytes with SHA-256 `cfa1bbc5561905501a206d298498b4a2a4e58786ddd760c45460e1c0ce88faf6`, five GET paths, 45 schemas, and ten date-time format occurrences. Generated TypeScript is 36,287 bytes with SHA-256 `54f2e34d3adf39075e77bf09c55691e63d244d1d526de96fa35fce4fdd36f6ca`.

**Resource and dependency impact:** No dependency was added. Timestamp parsing and chronology checks are linear in the revision records already admitted by existing byte/node/record ceilings. Production frontend bundle sizes are unchanged.

**Removal path:** A future typed persistence layer may replace these helpers only if it preserves strict scalar types, timezone-aware parsing, all causal ordering checks, date-time contract formats, fixture/real behavior, and adversarial tests. Returning to `str(value)` or numeric-string conversion at the evidence boundary is not acceptable.

**Consequence:** A malformed scalar can no longer become plausible text or numeric evidence, and impossible lifecycle timing cannot be presented or downloaded as a coherent trace. Complete schema conformance and cross-file parity for raw PartSpec, manifest, fabrication-package, report, and profile dictionaries remain the next read-integrity gap.

### D-030 â€” Enforce packaged schemas, record graphs, and fabrication-package parity

**Status:** Accepted for M4-K on 2026-07-16.

**Decision:** Advance the read API to 1.6.0. Treat the committed Draft 2020-12 PartSpec, StageEvent, ArtifactManifest, and production FabricationPackage schemas as runtime read-boundary contracts, and add a separate closed schema for the deliberately compact interface-only package fixture. Ship the allowlisted schema assets in the Python wheel and resolve them from either a source checkout or the installation data directory.

**Integrity boundary:** Before returning detail or any artifact, require every current-revision PartSpec, relevant event, manifest, and production/fixture package to pass its schema. Require the revision stage list to cover every owned stage; every stage-owned event/artifact/finding/decision/approval to be referenced exactly; artifact paths to be unique; parent artifacts to exist in the same revision, never come from a later stage or time, and form an acyclic graph; and stage inputs not to come from later stages. A persisted package requires exactly one successful latest Package attempt at R4. Production packages additionally require the exact 19 roles, exact manifest descriptor and Package-stage input parity, real evidence modes, exact unresolved-warning objects and status, one checksum-matched `fabrication_package_report` over the exact parsed bytes, and G-code summary checksum/size/filename parity. These checks validate recorded relationships only; they do not rerun CAD, geometry validation, printability rules, slicing, simulation, or hardware.

**Evidence:** Eight new adversarial tests reject schema additions and malformed timezone values, oversized schema-error text, unreferenced records, duplicate paths, missing parents, lineage cycles, stale package stages, warning drift, missing package artifacts, descriptor drift, package-report checksum drift, and G-code summary drift. The full pinned suite passes 116 backend tests; generated-contract drift, eight deterministic frontend tests, lint, and production build pass. A clean wheel installation outside the checkout resolves and meta-validates all six allowlisted persisted schemas. Seven ignored real revisions are discovered: six remain available with ten reports and eight profiles; one R2 trace is now correctly invalid because a stale R4 package file has no successful Slicing/Package lifecycle and names fourteen artifacts absent from its 15-artifact manifest. Direct schema replay passes seven PartSpecs, 307 relevant events, seven manifests, three production package files, and two production printability reports. A live loopback check returned API 1.6.0, two of six observed fixtures with next offset 4 and `snapshot_consistent: false`, and the exact 178-byte checksum-matched artifact while every hardware-action indicator remained false.

**Contract evidence:** The canonical OpenAPI snapshot remains 68,894 bytes with five GET paths, 45 schemas, and ten date-time format occurrences; its API-version SHA-256 is `2a87af7b378b54058b44deef0ae3bc586e8dc5faae69901e5e129344f1ae7229`. Generated TypeScript remains 36,287 bytes with SHA-256 `87705ed63c19145de5748d1699e46399de4f087b32ba8a8d3fbaeaa23821237f`. Production frontend bundles remain 333.49 KiB application JavaScript / 102.71 KiB gzip, 24.85 KiB CSS / 5.47 KiB gzip, and a separately emitted 724.46 KiB Three.js chunk / 184.72 KiB gzip with the existing size warning.

**Resource and dependency impact:** `jsonschema>=4.23,<5` moves from the test extra to the core runtime because handwritten partial checks cannot truthfully claim conformance to the committed schemas. The locked implementation is jsonschema 4.26.0 under the MIT license; its locked runtime dependencies are attrs, jsonschema-specifications, referencing, and rpds-py. Validators and schema assets are cached per process, each schema read is capped at 1 MiB, validation is linear in records already admitted by existing byte/node/page ceilings, and error text derived from untrusted values is capped at 512 characters. Wheel data grows only by the existing schema/OpenAPI files; browser bundles are unchanged.

**Removal path:** A generated typed persistence layer or native validator may replace `jsonschema` only if it consumes the same versioned contracts, preserves strict timezone formats and bounded deterministic errors, works in both checkout and installed-wheel layouts, retains all graph/package parity tests, and documents an equivalent migration path. Returning to selected-field checks while claiming complete root-schema conformance is not acceptable.

**Consequence:** Root specifications, events, manifests, and packages can no longer acquire undeclared fields or contradict their recorded graph while still appearing coherent. Complete geometry/preflight report and profile value schemas, package-to-profile identity parity, packaged-PartSpec content parity, and browser-level visual/accessibility evidence remain the next read-only integrity work.

### D-031 â€” Enforce report/profile schemas and cross-artifact content identity

**Status:** Accepted for M4-L on 2026-07-16.

**Decision:** Advance the read API to 1.7.0. Add distinct production and explicitly non-evidentiary interface-fixture Draft 2020-12 contracts for geometry validation, printability, G-code preflight, printer, material, process, and orientation values. Keep each role explicit instead of accepting one permissive common report/profile shape. Validate production profiles before typed construction; validate geometry, printability, and preflight values before publication; and validate persisted role content again only after its bounded size and SHA-256 pass.

**Identity boundary:** For a production R4 package, compare the checksum-verified packaged PartSpec value with the revision PartSpec; package profile IDs with printer/material/process/orientation content; printer-family identity; printability profile IDs; printability source/oriented geometry filename, size, and checksum with package descriptors; geometry/printability benchmark identity; and G-code preflight artifact value with package preflight. A valid schema with contradictory identity invalidates detail. A missing, changed, malformed, or role-schema-invalid inspection artifact remains explicitly unavailable rather than becoming a pass. Direct report/profile/PartSpec artifact reads repeat their applicable schema and identity checks. Revision listing intentionally does not parse detail artifacts and remains a bounded root-availability view.

**Evidence:** The allowlist now contains 19 meta-valid schema assets. Direct replay passes six canonical production profiles, both complete fixture revisions across 14 report/profile files, and 25 ignored production report/profile snapshots. New adversarial tests reject profile scalar coercion, unknown fields, duplicate JSON keys, duplicate/inconsistent preflight checks, invalid report/profile role shapes on both detail and direct artifact reads, and valid-shaped package/content identity drift. Producer integration tests exercise schema-gated geometry, printability, and preflight publication. All 122 backend tests pass. Six of seven ignored real revisions remain available with ten reports, eight profiles, and zero unavailable inspection records; the known orphaned-package revision remains correctly invalid. A clean 168,400-byte wheel resolves and meta-validates all 19 installed schemas. Live loopback checks returned API 1.7.0, a complete fixture with three reports/four profiles/zero unavailable records, the bounded two-of-six live list window, and the exact 178-byte verified artifact while all hardware indicators remained false.

**Contract evidence:** The canonical OpenAPI snapshot remains 68,894 bytes with five GET paths, 45 schemas, and ten date-time occurrences; its API-version SHA-256 is `7de17348d277fd09da0eaa4cf6b3b4962696d9b24749952a173b0d58111f2f6d`. Generated TypeScript remains 36,287 bytes with SHA-256 `7f744f89ce6ba02931a8761a11e52d2b2844ba15f656fc1af9a269789761837b`. Production frontend bundles remain 333.49 KiB application JavaScript / 102.71 KiB gzip, 24.85 KiB CSS / 5.47 KiB gzip, and a separately emitted 724.46 KiB Three.js chunk / 184.72 KiB gzip with the existing size warning.

**Resource and dependency impact:** No dependency was added. Thirteen new schema files plus the tightened existing printability schema increase wheel data only; validators remain cached and each schema remains capped at 1 MiB. Detail validation reads at most the existing 2 MiB-per-inspection-artifact bound. Direct reads of known semantic JSON roles perform a second bounded checksum/schema capture after the 64 MiB response snapshot; this favors fail-closed identity over one-read efficiency on the current loopback-only service. A future immutable content-addressed store can eliminate that duplicate capture while preserving identical-byte semantics.

**Removal path:** Generated typed persistence, a schema registry, or a sealed content-addressed index may replace these validators only if it retains separate fixture/production roles, strict JSON/profile behavior, producer and replay checks, every package/content identity comparison, explicit unavailable behavior, direct-read enforcement, installed-wheel operation, and adversarial tests. Returning to selected-field parsing or checksum-only claims is not acceptable.

**Consequence:** Persisted report/profile bytes can no longer acquire undeclared shapes or contradict the package identities they are used to explain. Browser-level visual/accessibility evidence and frozen no-hardware job execution semantics remain the next M4 work.

### D-032 — Establish an accessible interaction baseline and preserve React renderer ownership

**Status:** Accepted for M4-M on 2026-07-16.

**Decision:** Keep the existing dependency-free React interaction layer and establish an explicit accessibility baseline before adding animation libraries, component kits, or mutation controls. Provide skip navigation, a single main landmark, route-specific document titles, route-change focus transfer, ordered card headings, polite loading status, explicit artifact link names, and a WAI-ARIA-style inspection tablist with Arrow, Home, and End keyboard behavior. Render unavailable artifacts as non-actions. Pair report pass/fail color with text and toolpath color with solid/dashed line semantics. Observe reduced-motion preference changes for the lifetime of the page, stop automatic playback when reduction is requested, retain manual layer controls, and expose the reason visibly.

**Visual evidence boundary:** Raise the red foreground so the common dark-panel normal-text pair exceeds 4.5:1, use dark text on the red primary action, and use a dedicated focus color whose common dark-panel pair exceeds 3:1. Enforce those selected pairs with a formula-based stylesheet regression test. This proves only the frozen color pairs and component semantics under test; it is not a claim of complete WCAG conformance, screen-reader compatibility, zoom/reflow success, or visual-browser approval.

**Renderer ownership boundary:** Three.js may replace children only inside a dedicated React-owned-empty canvas host. Loading and error overlays remain React-owned siblings. The previous implementation imperatively replaced the viewport's React-managed child, which could race reconciliation and remove or corrupt status content. The canvas now has an accessible region name, visible keyboard/pointer instructions, and a checksum-specific artifact link.

**Evidence:** Component tests verify skip/main/title/heading semantics, route focus transfer, report pass text, keyboard tab selection and focus, and that an unavailable artifact has no actionable link. Stylesheet tests enforce four common normal-text contrast pairs, a focus-indicator pair, skip-link exposure, reduced-motion coverage, and dark primary-button text. Explicit test cleanup prevents one rendered component from contaminating the next assertion. Frontend generated-contract drift, test TypeScript, twelve deterministic tests, ESLint, production TypeScript, and Vite build pass; two real-artifact tests remain environment-gated. The application bundle is 337.16 KiB / 103.68 KiB gzip, CSS is 26.07 KiB / 5.76 KiB gzip, and the lazy Three.js chunk remains 724.46 KiB / 184.72 KiB gzip. The unchanged backend suite passes 122 tests.

**Resource and dependency impact:** No dependency was added. Route and media-query effects are event-driven; the Three.js viewer remains event-rendered rather than continuously animated. The semantic and focus code adds approximately 0.97 KiB gzip to the application entry and 0.29 KiB gzip to CSS compared with M4-L. The existing Three.js size warning is unchanged.

**Removal path:** A future design system or accessibility framework may replace these primitives only if it preserves route focus/title behavior, semantic landmarks and tab keyboard behavior, non-actionable unavailable records, non-color cues, live reduced-motion handling, contrast/focus regression coverage, dedicated renderer ownership, and component tests. Removing individual visual treatments is acceptable only after equivalent evidence replaces them.

**Consequence:** The interface now has a testable keyboard, focus, motion, contrast, and renderer-ownership foundation without pretending static tests equal human browser or assistive-technology review. Screenshot-level and assistive-technology QA remain blocked by the recorded local browser-runner conflict. Frozen no-hardware job-runner, event, cancellation, idempotency, concurrency, resource, and failure semantics are the next M4 work.

### D-033 — Freeze no-hardware execution semantics before mutation

**Status:** Accepted for M4-N on 2026-07-16.

**Decision:** Define execution control as a separate versioned state machine rather than overloading Journey `StageStatus`. Admit only the registered `opengrow_stake_electronics_clamp_v1` path to `golden_part_r2` or `golden_part_r4`; reject caller-selected paths, providers, profiles, tools, commands, environments, and all hardware actions. Snapshot the canonical request hash and exact benchmark, provider, CAD source, dependency lock, Python executable/runtime, worker, expectation, validator/pipeline, profile, slicer-config, adapter, slicer-version, and slicer-executable identities required by the target before acceptance.

**Scheduling and race boundary:** Use one active execution, a four-record FIFO queue ordered by a transactional accepted sequence, and canonical idempotency semantics: same key/same request replays the original while same key/different request conflicts. Freeze statuses as `queued`, `running`, `cancellation_requested`, `succeeded`, `failed`, `cancelled`, and `interrupted`. Queued cancellation prevents launch; active cancellation prevents any later success or next-stage start; a terminal commit that wins first remains unchanged. Retain partial Journey evidence and never roll it back. Use 30-second fenced leases with ten-second heartbeats; acquisition, latest heartbeat, and exact expiry are persisted. Every active identity/evidence/terminal write checks owner, generation, and unexpired lease in the same transaction. An expired active lease becomes `interrupted`, cannot commit late success, and never resumes automatically.

**Resource and event boundary:** Freeze a 16 KiB request, 900-second total wall deadline, 120-second CAD deadline, 180-second slicer-command deadline, ten-second cancellation grace, 10,000 events, 64 KiB event data, 8 MiB per log stream, 512 MiB workspace, 4 GiB process-tree memory, one concurrent child process, four slicer threads, network denial, and literal-false hardware behavior. Persist events before projecting them; use monotonic sequence IDs and at-least-once SSE replay; forbid invented `progress_percent`. Structured failure stages stop at Fabrication Package and cannot name Manufacturing.

**Persistence and security direction:** Use Python's standard-library SQLite as the first transactional control store while Journey artifacts remain on the filesystem. A future browser mutation boundary must be JSON-only and enforce exact loopback/same-origin checks plus an unpredictable anti-CSRF capability. Missing approved dependencies or inability to enforce the selected target's policy rejects admission before an execution record is accepted.

**M4-N implementation boundary:** Three Draft 2020-12 schemas plus immutable Python records and pure operations implement and test the contract. At M4-N, the existing CAD and slicer wrappers remained blocking subprocess calls and no persistent store, event transport, or crash recovery existed. API 1.7.0 therefore remained GET-only and the browser had no Run control. D-034 records the later internal store implementation without changing that HTTP boundary.

**Evidence:** Fourteen execution-contract tests cover closed requests, canonical hashes, R2/R4 identity and CAD-runtime separation, fixed resource policy, lifecycle and chronology, paired Journey identity, terminal immutability, queued/active cancellation, both cancellation/completion race outcomes, cancellation grace, structured failures, identity rebinding, idempotent replay/conflict, queue bounds, exact lease duration, fencing/renewal/expiry, stale-terminal rejection, no automatic resume, event/status/identity compatibility, event immutability/complexity/byte limits, invented-percentage rejection, and schema packaging/meta-validation. The full pinned environment passes 136 backend tests; the unchanged frontend drift/type/lint/twelve-test/build gates pass. The schema allowlist and installed wheel contain 22 assets: 19 evidence schemas plus three execution-control schemas.

**Resource and dependency impact:** No dependency was added. The contract uses dataclasses, enums, SHA-256, and the existing JSON Schema runtime. SQLite remains in the Python standard library. The schemas and pure records do not start a process, open a database, expose a socket, or alter browser bundles.

**Removal path:** A different control store, queue, or event transport may replace the proposed implementation only if it preserves canonical idempotency, transactional FIFO/lease/cancellation linearization, immutable identity, bounded resources/events, retained partial evidence, no automatic resume, literal-false hardware state, closed failure semantics, and replay tests. A background task launched directly from an HTTP handler is not an equivalent replacement.

**Consequence:** The next implementation slice can build a store and adapter against a fixed safety contract instead of inventing behavior in the UI. The contract itself does not make synchronous wrappers safe or authorize a mutation endpoint.

### D-034 - Implement the transactional control store before any execution adapter

**Status:** Accepted for M4-O on 2026-07-16.

**Decision:** Implement the M4-N persistence boundary as an internal Python standard-library SQLite store before adding a process runner, HTTP mutation, SSE transport, or browser control. Store schema 1 uses Ariad application ID `0x41524944`, WAL journaling, `synchronous=FULL`, strict tables, immutable policy/schema metadata, exact DDL fingerprints, startup `integrity_check` and `foreign_key_check`, and schema revalidation before every public operation. Journey artifacts remain on the filesystem and remain the fabrication evidence source.

**Transaction boundary:** Admit the idempotency key, canonical request hash, accepted-plan hash, monotonic accepted sequence, queued record, and origin event in one immediate transaction. Start only the oldest queued sequence while atomically allocating a globally increasing lease generation. Bind Journey identity once. Require the current runner owner, generation, and unexpired 30-second lease for active stage snapshots, heartbeat renewal, and terminal commits. Linearize queued/active cancellation and completion on the same row. Reconcile an expired active lease to `interrupted` before starting the next FIFO record; never resume it automatically.

**Integrity and resource boundary:** Persist canonical record/event JSON with SHA-256 and duplicate index columns that must replay to the same values. Database constraints and triggers enforce one active record, four queued records, immutable accepted identity and terminal state, legal status transitions, monotonic counters and update time, immutable metadata, event ownership, contiguous append order, and no event update/delete. Cap record JSON at 256 KiB, individual event JSON at 128 KiB, aggregate event JSON at 8 MiB, full event count at 10,000, and record-only lists at 100. Reserve one event slot and one 128 KiB event budget for the terminal event so ordinary snapshots cannot strand an active execution without room to fail, cancel, succeed, or interrupt. Concurrent first-open WAL negotiation uses a bounded retry rather than an unbounded wait.

**Security and evidence boundary:** The store is not imported by the FastAPI application, exposes no socket, launches no process, accepts no path/command/provider/profile choice from a browser, and cannot contact hardware. Checksums and semantic replay detect accidental corruption, torn/inconsistent application state, and the tested coherent field drift; they are not signatures against a privileged local actor able to replace both database content and schema. Append-only terminal retention preserves idempotency but has no global archive or database disk quota yet. Filesystem Journey publication and SQLite event publication also lack a cross-resource atomic coordinator. These remain blockers for browser mutation.

**Evidence:** Sixteen store tests cover idempotent/conflicting admission, four-record queue rejection, FIFO and lease generation, identity binding, stage snapshots, heartbeat fencing, success/failure/cancellation/interruption, cancellation grace, stale-run startup reconciliation, no automatic resume, event projection, same-key concurrency, real cancellation/completion contention, concurrent initialization, bounded record listing, timestamp rollback, event-log and terminal reserves, database queue/counter/metadata/owner/append/terminal guards, exact schema/application identity, record/plan/event checksum and semantic drift, transaction rollback, and missing-record behavior. The full pinned suite passes 152 backend tests. Frontend generated-contract/type/twelve-test/lint/build gates remain green. A clean wheel resolves all 22 schemas, imports the store from `site-packages`, and creates/reopens store schema 1 on SQLite 3.50.4.

**Resource and dependency impact:** No dependency was added; SQLite, hashing, JSON, threading coordination, and time primitives are from Python 3.11's standard library. Each full execution snapshot may allocate at most the 8 MiB persisted-event JSON ceiling plus decoded objects; each record list loads at most 100 records of 256 KiB each and deliberately omits event histories. Terminal history remains unbounded across distinct executions until an archive/capacity design is accepted.

**Removal path:** Another local database, queue, or control service may replace this store only if it preserves M4-N's canonical idempotency and immutable accepted plan, transactional FIFO/lease/cancellation semantics, stale-owner fencing, no automatic resume, atomic record/event publication, bounded replay with terminal reserve, fail-closed schema/data integrity, retained partial evidence, literal-false hardware state, concurrent and crash tests, and an explicit migration/versioning path. Deleting terminal history or launching work directly from an HTTP handler is not equivalent.

**Consequence:** The next M4 slice is the trusted target registry and policy-enforcing no-hardware adapter. It may use the store only after it can re-verify accepted identities, enforce process/log/workspace/deadline/network limits, and coordinate Journey snapshots. The GET-only API and browser remain unchanged.

### D-035 - Seal registered execution targets before launching any process

**Status:** Accepted for M4-P on 2026-07-16. This supersedes D-033 only where its initial identity list was incomplete and D-034 only where it named store schema 1; their scheduling, cancellation, lease, retention, and no-hardware decisions remain unchanged.

**Decision:** Advance the execution contract to 1.1.0 and the internal store to schema 2. Resolve a new request only through a sealed registry whose public input is the closed R2/R4 target enum. Internally select the fixed benchmark, provider source, expectations, profiles, slicer configuration, CAD runtime manifest, PrusaSlicer archive, installation, and executable. Persist their content identities as one immutable plan before transactional admission. Do not accept caller-selected paths, providers, profiles, commands, tools, environments, or hardware behavior.

**Identity boundary:** In addition to D-033's fixed assets, content-identify the Ariad `pyproject.toml` plus complete `src/ariad_fabrication` and `schemas/v1` trees; the active CPython executable; a curated CPython runtime tree; the trace-selected locked dependency tree including active `.pth`/virtual-environment bootstrap files and `pyvenv.cfg`; and the active Windows system, release, version, and x86-64 machine identity. For R4, separately pin the upstream portable archive and a manifest covering every installed PrusaSlicer file. Keep the PrusaSlicer manifest SHA-256 in the static approval. Keep the CAD runtime manifest at a fixed repository path and persist its exact digest in each plan, but bind its trace to the current application-bundle digest instead of hardcoding its own digest into registry source; hardcoding both sides would create an unsatisfiable self-reference because registry source belongs to that application bundle. Freeze repository text checkouts to LF through `.gitattributes` so exact source, schema, lock, profile, and manifest hashes do not vary with a developer's `core.autocrlf` setting.

**Admission and replay boundary:** `RegisteredTargetAdmission` first looks up the idempotency key. Existing same-request replay and different-request conflict return the immutable original without requiring today's runtime or slicer to remain available. Only a genuinely new key performs the comparatively expensive target resolution, after which the store atomically arbitrates queue capacity and same-key races. The runner must call registry re-verification against the accepted plan immediately before launch; no identity is silently rebound.

**Evidence and limitation boundary:** The committed CAD manifest records 613 curated CPython files (34,534,219 bytes) and 1,058 traced environment files (634,371,928 bytes); its current trees are reproducibly generated and its trace is bound to the Ariad application bundle. The PrusaSlicer manifest records 1,119 installation files (261,683,165 bytes) plus the separately pinned 106,598,059-byte archive. Tests reject fixed-asset, application, accepted-plan, Python, dependency, `pyvenv.cfg`, startup-hook, lock, archive, slicer-tree, and unsafe-manifest drift. The full pinned suite passes 163 backend tests and both generators reproduce the committed manifests byte for byte. This proves content identity for the registered digital lane; it does not prove OS sandboxing, deny network access, enforce memory/process limits, prevent an unmanifested import, or content-hash Windows system DLLs. Host fields detect named OS-version drift only.

**Version and migration boundary:** Execution request/record/event schemas are all 1.1.0 and old 1.0.0 values fail closed. Store schema 2 rejects schema 1 rather than guessing a migration. This is acceptable only because the store remained unreachable from HTTP and had no production records; any future deployed schema change requires an explicit migration or export/import decision.

**Resource and dependency impact:** No dependency was added. Registry hashing and manifest generation use Python 3.11 standard-library facilities plus the already locked CAD environment. The committed manifests add roughly 0.53 MiB of text and commit no toolchain binary. Resolution hashes hundreds of megabytes and is intentionally outside an HTTP handler; observed local timings are development evidence, not an SLA. The registry is checkout-local because approved assets and toolchain manifests are repository inputs.

**Removal path:** A signed release bundle, hermetic environment image, content-addressed artifact service, or native policy launcher may replace these manifests only if it retains closed target selection, exact accepted-plan replay, launch-time re-verification, full slicer-installation identity, application/runtime/lock/profile identity, bounded parsing, drift tests, honest host limitations, and literal-false hardware state. Checking only an executable filename/version or trusting the current virtual environment is not equivalent.

**Consequence:** The next M4 slice is the cancellable policy adapter. It must consume only a registry-sealed target, enforce the frozen wall/log/workspace/process/memory/network/import policy, and coordinate partial Journey evidence with the control store before any mutation endpoint, SSE transport, or browser Run control is added.

### D-036 - Permit monitored workspace enforcement for sealed local targets

**Status:** Accepted by the project owner on 2026-07-17. This supersedes D-033 and D-035 only where they required the 512 MiB workspace ceiling to be an operating-system hard quota.

**Decision:** For the two registry-sealed, content-verified Golden Part R2/R4 targets only, permit the Windows supervisor to enforce the 512 MiB workspace ceiling by bounded recursive observation, immediate process-tree termination when the threshold is observed, and a mandatory final scan before success. The adapter must disclose that a fast writer can temporarily exceed the threshold between observations. This exception does not authorize caller-selected commands, paths, providers, generated code, arbitrary Python, or any hardware action.

**Remaining security boundary:** Filesystem isolation, network denial, manifest-backed Python import enforcement, launch-time accepted-plan re-verification, and target-specific command construction remain mandatory before browser mutation. The monitored workspace exception cannot be generalized to an organic-model provider or other untrusted executable without a new decision and stronger containment evidence.

**Evidence:** The Windows Job Object supervisor tests cover periodic and final workspace-overflow detection, bounded logs, aggregate memory, active-process limits, cancellation, shared deadlines, suspended launch, and descendant cleanup. The full backend suite passes 178 tests after the supervisor source bundle and CAD runtime manifest update. This is software-control evidence only and does not prove a hard disk quota.

**Removal path:** Replace monitored enforcement with a fixed-size isolated volume, operating-system quota, disposable VM/container, or equivalent hard storage boundary when a supported implementation is available. That replacement must retain the same 512 MiB policy, complete process-tree cleanup, and overflow tests.

**Consequence:** Workspace polling is no longer the sole blocker for the sealed R2/R4 adapter. Browser Run remains unavailable until every remaining security and persistence boundary above is implemented and tested.

### D-037 - Seal and supervise the registered R2 Python lane

**Status:** Accepted as implemented evidence on 2026-07-17.

**Decision:** Launch the registry-reverified R2 CAD worker through a standalone `python -I -B -S` bootstrap before importing the registered module. Replace `sys.path` with four approved roots and permit only built-in/frozen modules or files whose absolute path and SHA-256 appear in the parent-built configuration. Include every importable Python/native module and DLL owned by a distribution observed in the approved trace, rather than only the exact modules loaded by one trace. Reject duplicate/open configuration shapes, unlisted origins, bytecode substitutions, changed bytes, escaping namespace locations, arbitrary module targets, ambient environment secrets, non-empty workspaces, and all hardware behavior.

**Process boundary:** Run the bootstrap under the Windows Job Object supervisor with the frozen CAD deadline, aggregate memory, process-tree, log, cancellation, and D-036 workspace policy. Redirect home, temporary, and application-data directories into the execution workspace. Disable `COMSPEC` so dependency font discovery cannot invoke `cmd.exe`; the real R2 worker remains successful without that host probe. Record process image basenames and accounting for diagnosis without exposing full host paths. Windows may account short-lived Console Host infrastructure separately from the application child ceiling; the dedicated process-limit test remains the evidence that an attempted application child is rejected.

**Evidence:** Standalone bootstrap tests prove registered success, arbitrary-target rejection, unlisted-import rejection, byte-drift rejection, and correct `SystemExit(0)` handling. Registry configuration tests prove immutable closed output and a current allowlist over 613 curated CPython files plus 2,285 dependency files. Real integration runs produce ten verified worker artifacts; the existing Golden Part pipeline consumes the sealed result, reaches persisted `geometry_verified` R2, writes Journey and manifest records, records 15 artifacts, and contains no Manufacturing stage. The persisted-pipeline integration passed three consecutive repetitions after shell suppression.

**Limitation:** Exact import identity and Job supervision do not prevent approved native modules from reading arbitrary host files or opening a socket. Filesystem isolation and network denial remain mandatory before HTTP mutation. R4 PrusaSlicer execution is not covered by this decision.

**Removal path:** A signed hermetic environment, disposable VM/container, or supported Windows sandbox launcher may replace the bootstrap and Job adapter only if it preserves accepted-plan re-verification, exact code identity, bounded resources/logs, cancellation and descendant cleanup, no ambient secrets or command shell, persisted R2 integration, and adversarial tests.

**Consequence:** The R2 execution implementation is no longer a parallel proof-of-concept worker; it feeds the existing evidence-producing pipeline. Browser Run remains locked while OS filesystem/network isolation, R4 conversion, store coordination, and HTTP/SSE controls are incomplete.

### D-038 - Supervise the complete registered R4 slicer lane

**Status:** Accepted as implemented evidence on 2026-07-17.

**Decision:** Construct PrusaSlicer only from a launch-reverified `golden_part_r4` plan. Bypass the legacy constructor's unsupervised `--help` process because the registry already verifies the complete approved installation, executable SHA-256, version, archive, and adapter identity. Require the exact registered executable, keep the model and output directory inside the execution workspace, force the frozen four-thread setting, redirect environment state into that workspace, suppress `COMSPEC`, and run model inspection, 3MF export, and G-code export as three separately bounded Windows Job commands sharing the execution deadline and cancellation token.

**Evidence:** A real sealed R4 integration first reaches persisted R2 through the sealed CAD adapter, passes deterministic R3, then executes all three supervised PrusaSlicer commands successfully. The test verifies three zero return codes, literal-false hardware behavior, no observed `cmd.exe`, explicit `--threads 4` on both export commands, 36 persisted artifacts, an R4 package, and false printer-connected/print-started fields. A separate test rejects an R2 plan before slicer construction.

**Limitation:** This establishes process/resource/identity evidence for the approved local slicer, not OS filesystem or network isolation and not physical print evidence. PrusaSlicer remains a native AGPL tool with host read/network capability until the remaining OS boundary is implemented. The adapter is still internal and unreachable from HTTP.

**Removal path:** A different slicer or containerized execution service may replace this adapter only if it preserves fixed profile/tool identity, real slicer output, four-thread/resource controls, shared cancellation/deadline behavior, bounded logs, workspace confinement, complete package lineage, and disconnected hardware semantics.

**Consequence:** Both registered digital targets now have real supervised execution paths. The remaining pre-HTTP work is OS filesystem/network isolation and transactional coordination between the execution store, persisted Journey snapshots, and event projection.

### D-039 - Coordinate registered execution with persisted Journey evidence

**Status:** Accepted as implemented evidence on 2026-07-17.

**Decision:** Run at most the control store's oldest queued immutable R2/R4 plan through an internal service. The service owns one fenced lease, shared execution deadline, and cancellation token; reuses the sealed CAD and slicer adapters; and binds the generated job/revision identity exactly once. A control event may claim a persisted snapshot only after the Journey and manifest files exist, remain under a 16 MiB ceiling, match the bound job/revision and reported status, pass the committed manifest schema, and have their bytes hashed. A filesystem snapshot is written before its SQLite projection, so a projection failure retains inspectable partial evidence rather than creating an event for absent bytes.

**Evidence:** Service tests prove successful identity/event projection, missing-evidence failure, and propagation of an active cancellation request to the shared token. The pinned CAD/slicer environment passes all 197 backend tests, including the real sealed R2 and R4 integrations. The regenerated CAD runtime manifest binds the new coordinator source.

**Limitation:** Filesystem plus SQLite publication is ordered and recoverable, not a distributed atomic transaction. The service is internal and has no HTTP, SSE, browser, network, or hardware surface. Exact-import enforcement does not isolate approved native code from host files or sockets.

**Consequence:** Store/Journey coordination is no longer a pre-HTTP blocker. Enforceable filesystem isolation and network denial remain mandatory before browser mutation; authenticated same-origin POST/cancel/SSE contracts come after that boundary.

### D-040 - Accept broad prompts without pretending broad execution

**Status:** Accepted as implemented foundation on 2026-07-17.

**Decision:** Separate universal prompt capture, semantic intent proposal, capability policy, and execution admission. Intake accepts any bounded non-empty UTF-8 fabrication idea and records its digest with literal-false hardware behavior. A semantic provider may propose the registered benchmark, functional parametric CAD, organic mesh, planning-only, or unsupported lane, plus questions, assumptions, and a draft PartSpec. That proposal remains `model_proposal` evidence and cannot choose commands, paths, providers, profiles, or hardware.

**Current capability boundary:** Only the exact `opengrow_stake_electronics_clamp_v1` benchmark may expose the closed `golden_part_r2` and `golden_part_r4` demo targets. The route must disclose that running the benchmark does not mean the user's free-form prompt became CAD. General functional CAD is `needs_input` or `provider_unavailable`; organic mesh is `provider_unavailable`; unsupported requests remain unsupported. Every route fixes hardware and physical-validation claims false.

**Evidence:** Routing tests cover arbitrary Unicode prompt capture, UTF-8 byte ceilings, exact benchmark allowlisting, invented benchmark rejection, unresolved functional requirements, provider-unavailable functional and organic lanes, planning-only and unsupported states, bounded proposal fields, and rejection of a semantic proposal that claims real evidence.

**Consequence:** Ariad's entry point can honestly begin with “describe anything” without changing the execution allowlist. A future GPT-5.6 provider supplies schema-constrained intent proposals only; capability policy and deterministic evidence gates remain authoritative.

### D-041 - Make local Codex the conversational fabrication agent

**Status:** Accepted by the project owner on 2026-07-17. This supersedes the proposed user-facing Hermes-agent story, but does not replace Ariad's deterministic orchestration, evidence, or safety boundaries.

**Decision:** The user talks to a locally authenticated Codex agent through Ariad's React interface. Ariad is the product and supervised fabrication system: it exposes versioned, closed tools; controls workflow state; executes CAD and slicer adapters; verifies evidence; and owns every downstream claim. Codex may converse, request Ariad tools, and propose editable CAD revisions, but it cannot skip gates, declare its own geometry or printability success, write trusted production G-code, contact hardware, or receive unrestricted access to the Ariad repository or host.

**Integration boundary:** Prefer the supported Codex SDK/app-server protocol over scraping terminal output from `codex exec`. The local backend may use the operator's existing Codex authentication; browser code must never read, copy, return, log, or persist Codex credentials. Another operator or judge must authenticate their own installation. Fixture evidence remains available without Codex authentication.

**Current tool authority:** Version 1.0.0 exposes only stateless idea capture and bounded evidence reads. Registered execution and cancellation remain internal; generated CAD submission remains blocked. A tool is not registered with Codex until its implementation, authentication, isolation, cancellation, and evidence gates pass. Hardware authority is always false.

**Consequence:** Remove Hermes from current product language rather than presenting a second general agent. Existing Python orchestration remains Ariad's workflow engine. The architecture can be integrated incrementally without rewriting the sealed R2/R4 pipeline or React evidence explorer.

## Deferred decisions

These require later evidence and should not be decided through preference alone:

- Physical stake fit and printer/material compensation — M7 measurements.
- Policy-enforcing runner adapter, SSE transport, mutation endpoint, and production frontend serving — later M4 work.
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
