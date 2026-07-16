# Current work

**Updated:** 2026-07-16  
**Current milestone:** M4 - Fabrication Journey interface  
**Project state:** M3 complete; the Golden Part reaches a printer-independent, profile-specific R4 package

## Immediate objective

Finish hardening the read-only Fabrication Journey before adding mutation or model-driven generation. Contract drift, detailed evidence replay, and persisted revision comparison now fail closed; the next slice should remove the artifact verify-then-send race, then close browser-level visual and interaction verification without weakening the M4 evidence contract.

## M4-A through M4-E implemented

- Added a FastAPI 0.139.1 / Uvicorn 0.51.0 application boundary that binds to loopback and exposes only health, revision-list, revision-detail, revision-comparison, and checksum-verified artifact reads.
- Added a fail-closed repository reader with ID/path confinement, optional-manifest handling for incomplete journeys, ownership checks, manifest/journey consistency checks, compact package summaries, and no hardware endpoint.
- Added a deterministic committed interface family with fixed IDs and timestamps: complete, parent/child comparison, Brief `needs_input`, failed Geometry, failed Printability, and incomplete Package records. Each stops at its persisted gate, and both complete revisions permit only “Interface fixture only — no fabrication evidence.”
- Added a Vite 8.1.4, React 19.2.7, React Router 7.18.1, and TypeScript 5.9.3 client with job/revision cards, a shipment-style timeline, events, warnings, artifact links, fixture labelling, claim boundaries, disconnected-hardware messaging, responsive layout, and reduced-motion behavior. Vite is exactly pinned to the newest release that passes the active minimum-release-age policy; TypeScript 5.9.3 is pinned to the supported peer range of the contract generator.
- Added a bounded direct Three.js 0.185.1 GLB inspector with orbit/reset controls, keyboard panning, checksum/size metadata, a 64 MiB / two-million-triangle ceiling, and an explicit tessellated-preview boundary.
- Added a bounded Web Worker G-code parser and top-down layer player with manual/reduced-motion controls, travel/extrusion distinction, 64 MiB / one-million-segment ceilings, layer sampling, omitted-arc disclosure, and an explicit manufacturing-playback boundary.
- Added separate production/test TypeScript configurations, frontend lint, deterministic component/parser tests, environment-gated real GLB/G-code integration tests, production build, backend API/fixture/integrity tests, and lightweight GitHub Actions jobs.
- Added a canonical committed OpenAPI 3.1 snapshot, exact `openapi-typescript` 7.13.0 generation, generated response aliases in the browser, required-field and read-only contract tests, and backend/frontend CI drift checks. The runtime API does not expose documentation, schema, or mutation routes.
- Added API 1.2 bounded evidence replay for persisted specification features, geometry/printability/preflight checks, four profile types, report messages, measurements, source checksums, and explicit unavailable reasons. Known JSON reports are capped at 2 MiB, 500 checks, 100 messages/features, 128 fields, depth 16, and 20,000 nodes; listing cards do not parse detail reports.
- Added a browser evidence explorer with selectable feature, check, finding, profile, and artifact records. It exposes full recorded SHA-256 values and distinguishes checks verified before parsing from artifacts verified when opened; it explicitly does not spatially inspect STEP or rerun validation.
- Added a read-only server-owned revision comparison over normalized stages, requirements, features, reports, checks, findings, profiles, artifacts, and package state. It omits volatile IDs/timestamps, caps each side at 10,000 normalized records, returns at most 1,000 changes and 64 KiB per value, marks every omission, and states that unchanged records do not prove geometric or physical equivalence.
- Added a React comparison picker and parent-to-child evidence-diff view. The deterministic child fixture changes exactly 12 semantic records across seven areas while remaining fixture-only and performing no CAD, validation, slicing, simulation, or hardware action.
- Verified the API reads the existing ignored real R2/R4 revisions without changing their evidence and serves the compact fixture over HTTP with `hardware_actions: false`.
- Verified all 80 backend tests pass in the pinned CAD/slicer environment. The frontend lockfile passes its release-age and peer policies; OpenAPI-generated-type drift, test and production TypeScript checks, ESLint, seven deterministic tests, two real-artifact integration tests, and the Vite production build pass. The evidence reader replayed 61 real checks plus four profiles from an existing ignored R4 revision, and live Vite-proxied HTTP reads returned the real 241,324-byte GLB and 5,182,593-byte G-code with `evidence-mode: real` and `hardware-action: false`.
- Recorded anime.js, Motion.dev, Kokonut UI, Bklit UI, and Manus.im as deferred visual references rather than installed dependencies.

## M3 completed

- Added a provenance-complete generic uncalibrated 1.75 mm PETG profile, the Golden Part's 0.20 mm / 30% gyroid / support-disabled process, and a matching PrusaSlicer 2.9.6 composite INI.
- Extended profile validation to cover exact printer family, filament type, regular and first-layer temperatures, density, volumetric speed, fan range, top/bottom layers, infill, support, and every recorded speed.
- Froze `benchmarks/golden_part/printability_expected.json` with exact profile IDs, R3 rules, risk policy, and claim boundary.
- Materialized the accepted orientation as a deterministic centered Z-up STEP derived from the exact R2 STEP; repeated runs produce the same oriented-STEP hash and report.
- Passed 23 deterministic R3 checks covering profile/spec agreement, build-volume margins, on-bed placement, 339.290412 mm2 exact bottom-face contact, nozzle-relative wall/open-feature rules, layer-height ratio, unresolved steep overhang area, three bounded horizontal-hole bridges (3.4, 3.4, and 4.0 mm), disabled-support consistency, build-axis bore direction, and digital first-layer clearance.
- Preserved five physical unknowns as warnings: generic profile calibration, PETG bridging, elephant foot, layer-direction strength, and actual PETG build-surface compatibility.
- Integrated the approved real PrusaSlicer 2.9.6 console into the same immutable Golden Part journey. The accepted run reported one manifold part, zero mesh repairs, zero slicer warnings, 250 layers, an 82 minute 2 second estimate, and 15.96 g estimated material.
- Passed disconnected G-code preflight for layers, units/modes, bounds, temperatures, single-tool use, forbidden commands, disabled supports, and profile layer height.
- Applied an explicit warning policy: exact-CAD mesh repair, floating bridge anchors, and unknown slicer warnings block R4; low-bed-adhesion may advance only as a visible warning.
- Assembled a 36-artifact R4 package with profile snapshots, oriented STEP, R3 report, slicer installation provenance, all command logs, profile-bearing 3MF, G-code, preflight, package report, checksums, and lineage. Hardware fields explicitly remain false.
- Added oversized-volume, profile-drift, unsupported-temperature, multi-tool, malformed-G-code, timeout, mesh-repair, and slicer-warning failure coverage.
- Verified 54 lightweight tests pass with 10 optional CAD/slicer skips, and all 54 tests pass in the pinned CAD environment.
- Updated `--golden-part` to run the complete disconnected R4 path; `--golden-part-r2` remains available for geometry-only evidence.

## Next actions

1. Remove the artifact verify-then-`FileResponse` race so the bytes sent are the same bounded bytes whose size and SHA-256 were accepted.
2. Perform visual browser QA across desktop/mobile widths and keyboard/reduced-motion paths once the local in-app browser runtime conflict is resolved.
3. Freeze job-runner, event-stream, cancellation, idempotency, concurrency, and failure semantics before adding browser-triggered Golden Part execution.
4. Evaluate the deferred animation/component references against accessibility, maintenance, bundle size, overlap, license, and removal criteria before adopting any.

## Exit gate for M4

- A user can run or load the deterministic Golden Part and inspect Brief through Package in a browser.
- Every displayed status, event, warning, artifact, and evidence level comes from the persisted backend records.
- The oriented model and real toolpath can be inspected without implying structural, thermal, or physical proof.
- Failed and incomplete fixture journeys visibly stop at their actual gate.
- The first UI remains printer-independent and cannot upload, heat, move, or start hardware.
- Current backend and interface tests pass.

## Not now

- Do not purchase, connect, or control a printer.
- Do not implement remote start, heating, motion, or automatic hardware recovery.
- Do not add model-driven CAD generation before the deterministic interface has real contracts to call.
- Do not add hosted mesh providers, Blender, FEA, or robotics simulation to the critical path.
- Do not call R4 “physically printable,” “strong,” “safe,” calibrated, or physically validated.
- Do not optimize for a submission date.

## Known gaps

- The registered CAD worker is a separate, confined process, not a hardened no-network, memory-limited sandbox for untrusted generated code.
- The real slicer process uses explicit paths, a timeout, a minimal inherited environment, and disconnected output, but does not yet enforce network denial or operating-system memory/process limits.
- The generic PETG and printer profiles are analysis inputs, not machine-, filament-, batch-, hotend-, or build-surface calibration.
- Slicer verification does not establish adhesion, dimensional accuracy, real-stake fit, load capacity, weathering, food safety, or physical success.
- The ignored PrusaSlicer binary must be installed separately; AGPL distribution implications still require review before public bundling.
- Only one functional part family has R4 evidence.
- There is no persistent database, job runner/event transport, physical calibration data, selected printer, or selected project license. The current API and interface remain read-only M4 foundations.
- Artifact downloads verify the file before returning a path-backed `FileResponse`; a local file mutation between verification and response streaming could change the bytes sent. This race is the next read-boundary hardening task.
- The GLB surface is a bounded tessellated preview, not exact STEP inspection. The toolpath surface draws linear G0/G1 moves and discloses omitted arcs; it does not model collisions, extrusion, adhesion, heat, strength, or printer behavior.
- Automated in-app-browser visual QA is locally blocked by a user-level Node ESM configuration conflict outside this repository; compiler, lint, component, production-build, and HTTP checks pass without modifying that unrelated configuration.
- The older fixture slicer and Klipper simulator remain in the repository but are outside the evidence-gated path.
- The OpenAI adapter does not yet use strict structured responses or a frozen evaluation set.

## Sources of truth

1. [README.md](README.md) - stable overview and current evidence.
2. [docs/DECISIONS.md](docs/DECISIONS.md) - accepted direction.
3. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - system contracts and boundaries.
4. [docs/RELIABILITY.md](docs/RELIABILITY.md) - required evidence and allowed claims.
5. [docs/ROADMAP.md](docs/ROADMAP.md) - milestone order and exit gates.
6. This file - immediate work, blockers, and the current exit gate.
