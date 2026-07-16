# Research and references

**Last reviewed:** 2026-07-16

This is a curated reference index, not a list of dependencies or purchase recommendations. Prices, licenses, availability, APIs, and model capabilities can change; re-verify them before integration or spending money.

## OpenAI application architecture

- [Responses API migration guide](https://developers.openai.com/api/docs/guides/migrate-to-responses) — recommended application primitive for new tool-using projects.
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) — schema-constrained model output for proposed specifications.
- [Function calling](https://developers.openai.com/api/docs/guides/function-calling) — model-to-tool contracts.
- [Model catalog and pricing](https://developers.openai.com/api/docs/models) — re-check model selection and cost when M5 begins.

Research conclusion: the model should create or revise structured intent and call tools. Deterministic workers continue to own geometry, validation, slicing, and hardware boundaries.

## Functional CAD

- [CadQuery installation guide](https://cadquery.readthedocs.io/en/stable/installation.html) — official Windows, Conda, pip, virtual-environment, and installation-test guidance.
- [CadQuery 2.8.0 on PyPI](https://pypi.org/project/cadquery/) — release metadata, Python requirement, Apache-2.0 metadata, and package files.
- [CadQuery documentation](https://cadquery.readthedocs.io/en/stable/) — Python parametric CAD with STEP, 3MF, STL, and glTF-related export paths.
- [CadQuery repository](https://github.com/CadQuery/cadquery) — current source, installation constraints, and OCCT/OCP relationship.
- [Open CASCADE Technology](https://dev.opencascade.org/doc/overview/html/index.html) — underlying C++ solid-modeling and CAD-exchange kernel.
- [Zoo MCP](https://docs.zoo.dev/docs/developer-tools/mcp) and [KCL](https://docs.zoo.dev/docs/kcl) — text-parametric alternative to benchmark later; service and licensing terms require review.
- [FreeCAD MCP](https://github.com/contextform/freecad-mcp) — emerging community integration to benchmark, not a committed dependency.
- [AgentCAD](https://agentcad.dev/) — another agent/CAD workflow reference.

M2 spike evidence on 2026-07-16: CadQuery 2.8.0 with cadquery-ocp 7.9.3.1.1 passed solid validity, STEP export, STL export, STEP re-import, solid-count, and exact-bound checks on CPython 3.11.15 / Windows AMD64. CadQuery also exposes a 3MF exporter in this environment; it does not expose direct GLB export. The isolated environment resolves 44 packages and occupies approximately 1.0 GiB, largely because CAD and visualization binaries are included.

M2 completion evidence: the registered Golden Part source creates one valid solid; canonicalized STEP re-imports and passes 25 frozen OCCT checks; binary STL passes a closed two-manifold topology test; the 3MF package contains millimetre mesh geometry and required package entries; and the in-repository GLB writer produces a structurally valid glTF 2.0 preview from CadQuery tessellation. Repeated runs produce identical hashes for all ten design artifacts. The 3MF is geometry only, not yet a slicer project or R4 manufacturing package.

Research conclusion: CadQuery is the first functional path because it is local, scriptable, parametric, and aligned with the existing Python code. It remains an optional dependency so contract-only development stays lightweight. STEP is the exact artifact and source for R2 measurement, STL is topology-checked compatibility output, 3MF is the current manufacturing-geometry carrier, and GLB is explicitly a tessellated preview. Provider benchmarks remain useful when expanding beyond the supported Golden Part recipe.

## Browser geometry and toolpath inspection

- [Three.js installation and addons](https://threejs.org/manual/en/installation.html) — official import pattern for Three.js, `GLTFLoader`, and `OrbitControls`.
- [Three.js GLTFLoader](https://threejs.org/docs/pages/GLTFLoader.html) — glTF 2.0 loader behavior and explicit resource-disposal warning.
- [Three.js WebGLRenderer](https://threejs.org/docs/pages/WebGLRenderer.html) — WebGL 2 renderer capabilities and lifecycle surface.
- [React Three Fiber installation](https://r3f.docs.pmnd.rs/getting-started/installation) — reviewed React 19-compatible abstraction; not selected for the first single-viewport slice.
- [`<model-viewer>` camera controls](https://modelviewer.dev/examples/stagingandcameras/) — reviewed accessible custom-element alternative; not selected because Ariad needs direct lifecycle, bounds, triangle, and evidence-control behavior without another rendering wrapper.

M4-B evidence on 2026-07-16: direct Three.js 0.185.1 loads the actual 241,324-byte Golden Part GLB and reports finite geometry through the selected GLTF parser. A dedicated Web Worker parses the actual 5,182,593-byte, 250-layer PrusaSlicer G-code with more than 100,000 recorded linear moves. Live Vite-proxied reads preserve `evidence-mode: real` and `hardware-action: false`. Screenshot-level browser QA remains unavailable because of a local runner conflict outside the repository, so renderer compatibility and build evidence must not be described as completed visual QA.

Research conclusion: direct Three.js is sufficient for the first bounded GLB viewport and avoids adding a second React renderer. Toolpath parsing remains project-owned because it must preserve Ariad's exact playback/simulation language and resource ceilings. Reconsider a higher-level library only if measured accessibility or lifecycle maintenance outweighs its additional dependency and abstraction cost.

## Interface contract generation

- [openapi-typescript CLI](https://openapi-ts.dev/cli) — official generation and `--check` behavior for converting an OpenAPI document into TypeScript definitions.
- [openapi-typescript repository](https://github.com/openapi-ts/openapi-typescript) — source, release history, compatibility, and MIT license.

M4-C evidence on 2026-07-16: FastAPI deterministically emits a committed 30,128-byte OpenAPI 3.1 snapshot with four application paths and 18 schemas. `openapi-typescript` 7.13.0 produces a 16,155-byte browser contract from that snapshot. Backend tests require all emitted response fields plus the API-version, health-identity, `read_only: true`, and `hardware_actions: false` constants; CI independently checks the Python snapshot and generated TypeScript for drift. TypeScript is pinned to 5.9.3 because it is in the generator's supported peer range, and the full frontend peer check passes.

Research conclusion: one canonical generated contract is safer than parallel handwritten response interfaces. The generated file remains a build-time artifact; it adds no browser runtime code and does not require exposing FastAPI's documentation or OpenAPI routes at runtime.

## Persisted evidence inspection

M4-D local evidence on 2026-07-16: API 1.1 read an existing ignored R4 revision and replayed 25 geometry checks, 23 printability checks, 13 G-code preflight checks, five retained physical warnings, four profile snapshots, and seven specification features. Every report/profile file was matched to its persisted size and SHA-256 before parsing. The compact JSON response measured 81,588 bytes and approximately 39.9 ms for one local cold read; the deterministic interface fixture measured 22,952 bytes and approximately 16.6 ms. These are development-machine observations, not service-level guarantees.

The committed interface fixture now includes eight artifacts: one explanatory note plus seven fixture-only report/profile shapes. Tests prove deterministic regeneration, reject checksum drift, reject valid-checksum invalid JSON, enforce the 2 MiB ceiling before parsing, and keep listing cards independent from detail-report reads. The current API snapshot is 42,933 bytes with SHA-256 `ae0d99263ecb847c2a4991166a18069aa467db68d8c6beb0b5b787c644734218`, four paths, and 26 schemas; generated TypeScript is 21,636 bytes.

Research conclusion: report inspection should remain a bounded replay layer over immutable evidence, not another validator. A selected row explains the persisted requirement/result pair; it cannot spatially identify exact STEP topology, rerun a kernel query, or improve the revision's evidence level.

## Persisted revision comparison

M4-E local evidence on 2026-07-16: API 1.2 normalizes 66 records on each side of the committed parent/child fixture. The deliberately revised bore and process request yields 12 semantic changes across stage, requirement, feature, report, check, profile, and artifact areas. Generated IDs, paths used only for downloads, and timestamps do not appear as changes. A same-revision comparison returns zero rows; unrelated jobs are identified rather than presented as lineage.

The comparison is bounded at 10,000 normalized records per revision, 1,000 returned changes, and 64 KiB of value detail per side. Tests force each ceiling and require explicit omission or canonical hash metadata plus `complete: false`. The endpoint is GET-only and reads both inputs through the same fail-closed detail contract. The browser renders the server response and does not rerun CAD, validation, slicing, G-code preflight, simulation, or physical work.

The current canonical API snapshot is 54,318 bytes with SHA-256 `1f177747402776e8bcb71715707c908eb14314f4a722310b5141368e2e200cb0`, five paths, and 30 schemas; generated TypeScript is 27,578 bytes. The pinned backend suite passes 80 tests, and the frontend passes seven deterministic tests plus two real-artifact integration tests.

Research conclusion: revision comparison should remain a semantic lens over persisted evidence, not an equivalence checker. A zero-row result can support traceability and review, but it cannot establish identical B-rep topology, manufacturing behavior, or physical performance.

## Verified artifact delivery

M4-F local evidence on 2026-07-16: API 1.2.1 captures an artifact into memory under a 64 MiB ceiling, verifies the captured bytes against the persisted size and SHA-256, and constructs the HTTP response from that same snapshot. A forced mutation of the backing path after verification no longer changes response content. The fixture note returned 178 bytes with the exact expected hash plus explicit verified-snapshot, evidence-mode, ceiling, no-cache, no-sniff, attachment, and disconnected-hardware headers.

OpenAPI now describes the artifact success body as binary rather than JSON, declares 404/409/413 error bodies, and records the integrity and safety headers. Media type and evidence mode are validated before header construction; CR/LF-bearing values fail as revision-integrity errors. The current snapshot is 58,589 bytes with SHA-256 `a98aff4a7b609536a08b85bea5d11919a20210daccfd90427bd68b39415cff38`, five paths, and 31 schemas; generated TypeScript is 30,693 bytes.

Research conclusion: checksum verification and response streaming must share one immutable byte identity. The in-memory snapshot is appropriate for the loopback M4 ceiling; a larger or multi-user deployment should move to content-addressed immutable storage or sealed temporary snapshots rather than restoring a mutable path race.

## Bounded persisted-file parsing

M4-G local evidence on 2026-07-16: one standard-library reader now supplies journey, manifest, package, fixture, inspection, and downloadable artifact snapshots. Tests instrument the reader and show an unrecorded input receives a `ceiling + 1` byte request, while a recorded input receives `expected size + 1`; a recorded size already beyond the ceiling is rejected without reading content. Repository detail/artifact tests succeed while `Path.read_text` and `Path.read_bytes` are forced to raise.

Root JSON is limited to 32 MiB, depth 32, and 200,000 nodes; inspection JSON remains limited to 2 MiB, depth 16, and 20,000 nodes before its role-specific list/field ceilings. Duplicate object keys, non-finite constants, and invalid UTF-8 are rejected. Strict boolean and finite-number helpers prevent JSON strings such as `"false"` and `"NaN"` from becoming positive or numeric evidence through Python coercion.

The API 1.2.2 OpenAPI snapshot remains 58,589 bytes with five paths and 31 schemas; its SHA-256 is `fbda3cf6e28f68bbe5a0fae9865d976c571d44b5beea5b2924ea070bf32da06d`. Generated TypeScript remains 30,693 bytes. The full pinned backend suite passes 91 tests.

Research conclusion: a pre-read `stat()` is not an allocation bound. Positive-size reads plus a detection byte make file capture bounded, while byte ceilings remain necessary because the standard JSON decoder materializes objects before post-parse depth/node checks. Stronger adversarial parsing would require a streaming parser or process-level memory isolation and should be justified by deployment risk rather than implied today.

## Bounded revision discovery and live listing windows

M4-H local evidence on 2026-07-16: revision discovery now uses non-symlink-following directory scans, examines at most 5,000 job/revision entries, and retains at most 500 observed candidates. Requests accept offsets only through 500 and page sizes from 1 through 200; repository instrumentation proves only the selected page loads revision JSON. Candidate and directory ceilings produce explicit incomplete-discovery reasons, while an ordinary page reports observed, returned, omitted, and next-offset values.

The response also fixes lexical job/revision ordering and declares `snapshot_consistent: false`. This matters because each request rescans a live local directory: a changed run tree can move offset boundaries between page requests even when each individual response is internally deterministic. The browser repeats that claim boundary, distinguishes an observed count from an exact global total, and does not show an empty-root claim after an incomplete discovery.

API 1.3.0 has five GET paths and 32 schemas. Its canonical OpenAPI snapshot is 62,597 bytes with SHA-256 `2425427793d2a6d88e408efb17b8af05b5d1c225bd03ab6d51a37efe1c2fc974`; generated TypeScript is 32,529 bytes with SHA-256 `2ffb742b31be693178d3127a4b96926e1f1339c569a72afef4891dee7b7241da`. The full pinned backend suite passes 96 tests. Frontend contract/type checks, eight deterministic tests, lint, and production build pass. A live loopback request for offset 2 / limit 2 returned two records, six observed candidates, next offset 4, `window_limit`, and `hardware_actions: false`.

Research conclusion: bounded filesystem discovery prevents one listing request from scaling with an arbitrary local tree, but offset pagination over a changing directory is not snapshot isolation. Stable multi-request pages would require an immutable index, content-addressed catalog, or database snapshot; until such a component is justified, the interface must preserve the explicit live-window limitation.

## Persisted lifecycle and evidence-state integrity

M4-I local evidence on 2026-07-16: the read repository now validates job, stage, event, finding, decision, approval, package, inspection, evidence, and fixture/runtime vocabularies before presentation. It also checks revision/job/stage ownership, unique per-stage event sequences, lifecycle timestamp/evidence/error combinations, decision and approval semantics, manifest parity, fixture/runtime package classification, R4 package evidence, and literal-false hardware state. Unsupported checksum-verified report/profile states become explicit unavailable records rather than pass records. The same repository load precedes artifact delivery, so malformed parent lifecycle state also blocks downloads.

API 1.4.0 has five GET paths and 45 schemas. Its canonical OpenAPI snapshot is 68,528 bytes with SHA-256 `69b53bcdbcf8471b5d1d1465843582b1df5e5203131dd3e3cf846ed0b3242b2d`; generated TypeScript is 35,921 bytes with SHA-256 `839c63852b3527eaf6ff681af25a855115aa4d5689d4c93c12de758c22403963`. The full pinned backend suite passes 101 tests. Frontend contract/type checks, eight deterministic tests, lint, and production build pass. All seven ignored real R2/R4 revisions remain available under the stricter reader. A live loopback request returned API 1.4.0, two of six observed fixture revisions with next offset 4 and `snapshot_consistent: false`, plus the exact checksum-matched 178-byte artifact snapshot; both capability and artifact headers retained `hardware_actions: false`.

Research conclusion: a schema-valid enum is necessary but not sufficient for trustworthy lifecycle presentation. Ownership and cross-field relationships must be checked at the read boundary, and unsupported inspection content must not be normalized into success. Timestamps and remaining generic text fields still need strict type, timezone, and chronology validation in a subsequent slice.

## Persisted scalar and temporal integrity

M4-J local evidence on 2026-07-16: journey-domain records and the read repository no longer stringify non-string scalar values into identifiers, labels, messages, summaries, or optional text. Typed inspection numeric fields reject strings rather than converting them. Persisted timestamps are parsed as timezone-aware ISO 8601 values and checked across job creation/update, revision creation, ordered stage start/completion, bounded event time and global sequence order, final-event state, approval request/decision, revision-owned record creation, and manifest generation. Cancelled and superseded stages require completion timestamps. Brief is intentionally bounded by job creation rather than revision creation because one real trace proved that the Brief stage starts and then materializes its first revision one millisecond later.

API 1.5.0 has five GET paths and 45 schemas with ten date-time format occurrences. Its canonical OpenAPI snapshot is 68,894 bytes with SHA-256 `cfa1bbc5561905501a206d298498b4a2a4e58786ddd760c45460e1c0ce88faf6`; generated TypeScript is 36,287 bytes with SHA-256 `54f2e34d3adf39075e77bf09c55691e63d244d1d526de96fa35fce4fdd36f6ca`. The full pinned backend suite passes 108 tests. Frontend contract/type checks, eight deterministic tests, lint, and production build pass. All seven ignored real revisions remain available and expose 11 reports plus eight profiles. A live loopback request returned canonical timezone-aware job/event strings, two of six observed fixture revisions with next offset 4 and `snapshot_consistent: false`, and the exact checksum-matched 178-byte artifact snapshot while every hardware-action indicator remained false.

Research conclusion: temporal validation must reflect actual lifecycle causality rather than assume every stage begins after revision materialization. The remaining read-integrity gap is complete conformance and cross-file parity for raw PartSpec, manifest, fabrication-package, report, and profile dictionaries; bounded parsing and selected-field checks do not yet prove those complete shapes.

## Organic meshes and Blender

- [Blender MCP](https://github.com/ahujasid/blender-mcp) — Blender scene, mesh, material, and Python control through MCP.
- [Hunyuan3D 2.1](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1) — local image-to-mesh/PBR reference with substantial GPU requirements.
- [Meshy API pricing](https://docs.meshy.ai/en/api/pricing) — re-check only if the organic lane begins.

Research conclusion: Blender is valuable for inspection, cleanup, organic assets, and presentation. It is not the dimensional source of truth for the first functional parts.

## Evaluation research

- [MUSE: CAD generation evaluation](https://arxiv.org/abs/2605.28579)
- [Text2CAD-Bench](https://arxiv.org/abs/2605.18430)

Research conclusion: code generation, valid geometry, and engineering readiness are distinct evaluation layers. Ariad therefore measures feature correctness, manufacturability, revisions, and eventual physical outcomes separately.

## Comparable systems and positioning

This review compares public documentation and visible source structure. The projects were not installed, benchmarked, or physically exercised, so their stated capabilities are not treated as independently verified evidence.

- [Kiln](https://github.com/codeofaxel/Kiln) — the closest stated full-lifecycle project: agent-facing model generation, mesh printability checks, PrusaSlicer/OrcaSlicer integration, G-code checks, printer adapters, monitoring, and recovery. Its public core is AGPL-3.0, so it is a benchmark and possible later adapter reference rather than an assumed dependency.
- [AgentSCAD](https://github.com/Kevoyuan/AgentSCAD) — a persistent full-stack workspace that turns requests into editable OpenSCAD, STL and preview artifacts, deterministic mesh/manufacturing validation, repair attempts, parameters, and job history. Its documented primary path does not include a recorded real-slicer fabrication package.
- [CADSmith](https://github.com/jabarkle/CADSmith) and its [paper](https://arxiv.org/abs/2603.26512) — the closest research overlap with Ariad's CAD core: planning, CadQuery generation, OCCT measurements, visual review, and iterative refinement over a 100-prompt benchmark.
- [AgentsCAD](https://arxiv.org/abs/2607.02448) — the closest overlap with the planned R3 stage: it parses STEP, detects FDM overhang risks, and proposes geometry or orientation changes. It begins with existing geometry rather than owning the complete requirements-to-package chain.
- [PartCAD](https://partcad.readthedocs.io/en/latest/features.html) — open-source product/package infrastructure with AI-generated OpenSCAD, CadQuery, and build123d source, assemblies, and repository-oriented lifecycle information.
- [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad) — agent skills and a local harness for source-controlled CAD, inspection, exports, robot descriptions, and geometry-aware revision workflows.
- [Zoo MCP](https://docs.zoo.dev/docs/developer-tools/mcp) — a commercial editable-parametric CAD provider and agent integration that remains a possible future benchmark, not the default local path.

Research conclusion: natural-language CAD and generic prompt-to-print orchestration are active, increasingly crowded areas. Ariad should not claim novelty from connecting those nouns. Its defensible product contract is the beginner-readable **Fabrication Journey** for functional B-rep parts: explicit intent, exact feature evidence, immutable revisions and checksums, profile-specific real-slicer evidence, and claim language that remains useful without owning or operating a printer.

The exact phrase **Ariad Fabrication** did not surface as a CAD or 3D-printing product in the 2026-07-16 preliminary search. The bare name is used in unrelated fields, including [Ariad Group](https://www.ariadgroup.com/en), so a legal and domain review remains required before public commercial use.

## Manufacturing formats and slicing

- [3MF specification](https://3mf.io/spec/) — manufacturing package format; preferred over STL when supported.
- [PrusaSlicer 2.9.6](https://github.com/prusa3d/PrusaSlicer/releases/tag/version_2.9.6) — selected first adapter; stable official release reviewed 2026-07-16, AGPL-3.0 repository license, dedicated Windows console executable, portable ZIP.
- [PrusaSlicer CLI documentation](https://github.com/prusa3d/PrusaSlicer/wiki/Command-Line-Interface) — Windows uses `prusa-slicer-console.exe`; explicit profile files and command-line overrides are supported.
- [OrcaSlicer 2.4.2](https://github.com/OrcaSlicer/OrcaSlicer/releases/tag/v2.4.2) — reviewed replaceable alternative with broad printer support and an official portable Windows build; not selected first because the package is larger and the initial CLI evidence was less mature.
- [3DBenchy official download](https://www.3dbenchy.com/download/) and [license](https://www.3dbenchy.com/license/) — external calibration fixture; the official site states CC0 1.0 and asks comparisons to preserve the original STL.
- [Moonraker](https://moonraker.readthedocs.io/) — Klipper API server for a later printer adapter.

M3 compatibility evidence on 2026-07-16: the official portable PrusaSlicer 2.9.6 archive is 106,598,059 bytes and 261,683,165 bytes extracted. Its console inspected, repaired where reported, sliced, and exported profile-bearing 3MF projects for official 3DBenchy and Ariad's conventional warship. Both G-code files passed disconnected bounds, temperature, units/modes, tool, support-feature, layer-height, and forbidden-command preflight. Benchy retained a low-bed-adhesion warning; the warship retained a floating-bridge-anchor warning and is therefore not accepted as a clean support-free candidate.

M3 Golden Part completion evidence on 2026-07-16: the same official console consumed Ariad's deterministic centered Z-up STEP through a snapshotted generic 220 mm printer / PETG / 0.20 mm / 30% infill / support-disabled profile. PrusaSlicer reported one manifold part, 1,826 facets, zero repairs, and no slicer warnings; produced 250 layers with an 82 minute 2 second estimate and 15.96 g estimated material; and emitted a profile-bearing 3MF plus 5,182,593-byte G-code file. Disconnected preflight passed all recorded checks. The complete immutable journey contains 36 checksummed artifacts and five unresolved physical warnings. These are local digital measurements, not print results.

Research conclusion: begin with PrusaSlicer through a replaceable adapter and record exact executable/profile versions and checksums. Slicer success does not waive warnings or establish physical success. Keep OrcaSlicer as the next compatibility target, and do not bind the product to Moonraker because inexpensive or strictly open printers may use different control paths.

## Printer watchlist — purchase deferred

“Open source” must be audited at several layers: firmware, electronics, mechanical CAD, editable source, bill of materials, manufacturing data, license, offline operation, and repairability.

- [Original Ender-3 source](https://github.com/Creality3DPrinting/Ender-3) — firmware plus mechanical, PCB, and wiring files; older hardware and more manual tuning.
- [Ender-3 V3 series comparison](https://www.creality.com/compare/compare-ender-3-v3-series) — V3 SE and KE are inexpensive practical candidates; firmware availability does not by itself establish fully open hardware.
- [Ender-3 V3 SE firmware](https://github.com/CrealityOfficial/Ender-3V3-SE)
- [Ender-3 V3 KE Klipper source](https://github.com/CrealityOfficial/Ender-3_V3_KE_Klipper)
- [Sovol SV06 ACE](https://www.sovol3d.com/products/sovol-sv06-ace) — practical Klipper candidate whose source/license completeness must be audited.
- [Elegoo Neptune 4](https://us.elegoo.com/products/elegoo-neptune-4-fdm-3d-printer) — inexpensive Klipper-family candidate requiring openness and maintenance review.
- [Original Prusa MINI hardware](https://github.com/prusa3d/Original-Prusa-MINI) — strong source-completeness reference but not the assumed purchase because of cost.
- [Voron hardware guide](https://docs.vorondesign.com/hardware.html) — future open build path, not an initial beginner purchase.

No printer is required through M6. Before M7, collect Malaysian landed prices, 230 V compatibility, local replacement-part availability, warranty/support, noise, ventilation requirements, and exact source licenses.

## Materials and design guidance

- [Prusa PETG guidance](https://help.prusa3d.com/article/petg_2059) - regular/first-layer temperatures, build-surface caution, cooling, bridging/overhang limitations, and functional-part context.

- [Prusa material guide](https://help.prusa3d.com/filament-material-guide) — comparative FDM material behavior.
- [Modeling with 3D printing in mind](https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135) — orientation, overhang, and feature-design guidance.

The M3 generic PETG profile records 240 C for regular and first-layer nozzle temperature, 90 C regular / 85 C first-layer bed temperature, 1.27 g/cm3 density, 8 mm3/s maximum volumetric speed, and 30-50% fan. Temperature/cooling direction comes from the official PETG article; density, volumetric speed, and fan values are transcribed from the Generic PETG base preset shipped inside the exact pinned PrusaSlicer 2.9.6 portable release. The material guide's broader 215-270 C / 70-90 C PETG range remains bounded by the generic printer profile's 260 C hotend maximum. No value is a machine- or filament-specific calibration.

The R3 overhang and bridge rules intentionally distinguish source guidance from Ariad policy. Prusa states conventional desktop FDM overhangs can generally fall in a 45-60 degree range and that short horizontal bridges may work, while its PETG page says PETG's bridging/overhang behavior is usually worse. Ariad therefore freezes the conservative 45 degree endpoint and a 5 mm bounded-hole span for this benchmark. The 5 mm value is an analysis threshold, not an externally established or physically measured PETG capability.

Initial material direction:

- PLA for easy concept prototypes.
- PETG as the initial functional indoor/planting default.
- TPU later for grips, tires, and compliant parts.
- ASA, nylon, and filled materials only after ventilation, drying, nozzle, enclosure, and profile requirements are understood.

## Health, safety, and food contact

- [NIOSH additive manufacturing resources](https://www.cdc.gov/niosh/manufacturing/additive/index.html)
- [NIOSH 3D-printing controls bulletin](https://www.cdc.gov/niosh/bulletin/2018/3d-printing.html)
- [Prusa food-safe FDM guidance](https://help.prusa3d.com/article/food-safe-fdm-printing_112313)

Research conclusion: day-one parts should avoid direct food contact. For edible-plant systems, keep printed mounts outside the fluid path and use certified reservoirs and tubing. A future food-related workflow should prefer printing a master for a certified food-safe mold rather than treating a general FDM printer as food-grade.

## Research discipline

For every later provider or purchase decision, record:

1. The exact problem it solves.
2. Current primary documentation.
3. License and data-handling terms.
4. Local/offline fallback.
5. Cost under a representative workload.
6. Benchmark evidence against the existing path.
7. New failure modes and exit strategy.

A tool is adopted because it improves measured project evidence, not because it produces the most impressive demo clip.
