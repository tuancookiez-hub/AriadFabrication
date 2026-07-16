# Roadmap

## Planning model

The roadmap is milestone-gated rather than deadline-driven. A milestone completes when its evidence exists and its tests pass. Time estimates may be added for short implementation work, but dates do not waive exit criteria.

## M0 — Foundation and documentation

**Goal:** Establish one coherent product contract and remove stale, overclaimed plans.

**Exit criteria:**

- Stable overview, product principles, architecture, reliability ladder, decisions, research references, and current-work file exist.
- Current implementation and target architecture are clearly separated.
- Generated caches and local artifacts are excluded from version control.

**Status:** Complete.

## M1 — Contracts and Golden Part specification

**Status:** Complete (2026-07-16).

**Goal:** Define the data and lifecycle foundation used by every later component.

**Work:**

- Versioned `PartSpec`.
- `Job`, `Revision`, `StageRun`, `StageEvent`, `Artifact`, `Finding`, `Decision`, and `Approval` records.
- Accepted seven-stage lifecycle and transition rules.
- Artifact manifest contract.
- Golden Part specification and expected measurements.
- Contract, transition, and serialization tests.

**Exit evidence:**

- `schemas/v1/` contains valid PartSpec, StageEvent, and ArtifactManifest schemas.
- `benchmarks/golden_part/` contains the confirmed input and exact expected measurements.
- Runtime contracts block incomplete specifications before Design and preserve immutable lineage.
- Contract, transition, retry, serialization, schema, and path-safety tests pass.

## M2 — Deterministic parametric CAD vertical slice

**Status:** Complete on 2026-07-16.

**Goal:** Produce the Golden Part from a hand-authored specification without model assistance.

**Work:**

- Pin a supported Python/CadQuery environment.
- Implement a process-isolated CAD-worker boundary for registered repository source; require a hardened sandbox before untrusted generated code.
- Build parameterized Golden Part source.
- Export STEP, 3MF, GLB, and compatibility STL.
- Query expected features and dimensions from exact geometry.

**Exit criteria:**

- CAD source is editable and repeatable.
- Exact geometry passes the R1 and R2 requirements relevant to the part.
- A failed or malformed specification produces no production-labelled geometry.

**Recorded evidence:** The pinned worker produces deterministic editable source, STEP, 3MF geometry, GLB, and STL; re-imported STEP passes 25 frozen checks; STL passes a closed two-manifold test; repeated design artifacts have identical hashes; and the persistent journey records R0, R1, R2, 15 artifacts, and negative fixtures. The worker remains restricted to registered repository source until a hardened untrusted-code sandbox exists.

## M3 — Printability and real slicing

**Status:** Complete on 2026-07-16.

**Goal:** Replace simulation-shaped manufacturing output with real, profile-based evidence.

**Work:**

- Printer and material profile schemas.
- Build-volume, wall, hole, clearance, orientation, overhang, and support checks.
- PrusaSlicer and/or OrcaSlicer CLI adapter.
- G-code parser and command policy.
- Reproducible fabrication package and report.

**Exit criteria:**

- Golden Part reaches R4 for at least one recorded generic or real printer profile.
- Failure fixtures demonstrate that invalid volume, profile, temperatures, and G-code are rejected.

**Recorded evidence:** The exact R2 STEP is materialized into a deterministic centered Z-up manufacturing orientation and passes 23 frozen R3 checks against a snapshotted generic 220 mm / 0.4 mm nozzle / PETG / 0.20 mm layer / 30% infill / support-disabled profile bundle. A real disconnected PrusaSlicer 2.9.6 process then produces a profile-bearing 3MF and G-code with zero reported repairs or slicer warnings; G-code preflight passes; and the Fabrication Journey completes a 36-artifact R4 package while retaining five physical unknowns as warnings. Oversized volume, profile drift, unsafe temperature, multiple tools, malformed G-code, timeout, repair, and warning-policy failures are covered. Both the 54-test lightweight suite and the full pinned CAD/slicer suite pass.

## M4 — Fabrication Journey interface

**Status:** Current.

**Goal:** Let a user inspect and control the real pipeline without using Codex.

**Progress:** M4-K provides a loopback-only read API, six deterministic non-evidentiary journey fixtures, work-bounded revision discovery/pages, bounded persisted-file snapshots, verified artifact delivery, strict persisted lifecycle/scalar/temporal/schema/lineage/package validation, and a React/TypeScript journey shell. The interface renders real GLB previews through a bounded Three.js inspector, parses real G-code in a bounded Web Worker, and lets users select persisted specification features, evidence records, and semantic revision differences. API 1.6.0 examines no more than 5,000 revision-directory entries, retains at most 500 candidates, loads at most a requested 200-summary page, and discloses observed omissions, truncation reasons, fixed ordering, and live-page non-snapshot behavior. It routes root records, inspection JSON, and artifacts through allocation-capped readers; rejects duplicate JSON keys, non-finite constants, excessive node/depth complexity, invalid header metadata, scalar coercion, unsupported lifecycle/evidence values, ownership drift, inconsistent stage/event state, reversed job/revision/stage/event/approval/manifest chronology, fixture/runtime mixing, enabled package hardware state, and manifest decision/approval drift; enforces packaged PartSpec/event/manifest/production-package/interface-package schemas plus exhaustive stage ownership, acyclic lineage, exact package role/descriptor/input/warning/report/G-code parity; computes bounded server-owned diffs without rerunning stages; and serves no more than 64 MiB from the exact artifact snapshot whose recorded size and SHA-256 passed. Binary/error/header/list-window, closed enum/literal-false, and date-time semantics are generated into the client contract. The committed parent/child pair produces exactly 12 meaningful changes across seven evidence areas while generated IDs and timestamps produce none. All 116 backend tests pass in the pinned CAD/slicer environment. Seven ignored real revisions are discovered: six remain available with ten reports and eight profiles, while one stale R2 trace with an orphaned R4 package is correctly invalid. Frontend type-check, lint, eight deterministic tests, production build, clean-wheel schema resolution, and live HTTP checks pass; two environment-gated real-artifact tests retain separate recorded passes. Automated visual-browser evidence, complete report/profile value schemas, event streaming, and pipeline mutation remain incomplete.

**Work:**

- Local application API.
- React/TypeScript application shell.
- Job and revision views.
- Stage timeline and event streaming.
- Interactive GLB viewer, dimensions, cross-sections, and findings.
- Layer/toolpath viewer based on real slicer output.
- Artifact downloads and comparison between revisions.

**Exit criteria:**

- A user can run and inspect the deterministic Golden Part path through the browser.
- The UI never advances a stage without corresponding backend evidence.

## M5 — OpenAI-assisted intake and revision

**Goal:** Add natural-language value without weakening deterministic boundaries.

**Work:**

- Strict structured output for `PartSpec` proposals.
- Material clarification policy.
- Tool calls for design, validation, and revision operations.
- Natural-language revision diff.
- Model and prompt evaluation set.
- Cost and token telemetry.

**Exit criteria:**

- Ambiguous prompts request clarification rather than inventing critical dimensions.
- Confirmed AI-created specifications pass the same deterministic pipeline as hand-authored specifications.
- Model changes are evaluated against a frozen prompt/spec corpus.

## M6 — Functional breadth and qualification

**Goal:** Establish a measured supported scope rather than claiming arbitrary CAD generation.

**Work:**

- Add benchmark families one at a time.
- Parametric component and fastener library.
- Design recipes plus constrained free-form CAD generation.
- Repair and revision benchmarks.
- Golden regression artifacts where stable and legally appropriate.

**Exit criteria:**

- Each advertised part family has positive, negative, and revision tests.
- R5 claims identify the benchmark scope and tool versions.

## M7 — Physical calibration and optional manufacturing

**Goal:** Close the digital-to-physical loop without making hardware a prerequisite.

**Work:**

- Use a local print service or later printer for calibration coupons and benchmark parts.
- Record photographs, measurements, failures, and process parameters.
- Build per-printer/material/nozzle compensation profiles.
- Audit inexpensive printer options, local support, parts, licensing, and safety before purchase.
- Introduce a read-only printer adapter, then separately review any dispatch capability.

**Exit criteria:**

- At least one part reaches R6 with reproducible records.
- Remote physical actions remain disabled unless a separate safety decision accepts them.

## M8 — Advanced lanes

These are independent expansions, not prerequisites:

- Organic mesh generation and Blender workflow.
- Assembly reasoning and tolerance stacks.
- Experimental FEA, thermal, or fluid analysis.
- Robot kinematics and ROS/Webots integration.
- Print-service and multi-printer orchestration.
- Optional Go control plane or printer-side agent.

Each advanced lane requires its own evidence model and cannot inherit functional-CAD reliability by association.

## Cross-cutting gaps

| Gap | Closure milestone |
|---|---|
| Only one functional part family has R4 evidence | M6 |
| Golden Part evidence currently stops at digital R4 | M7 for physical R6 |
| No end-user interface | M4 |
| AI output is not strict-schema or evaluated | M5 |
| Supported part scope is unknown | M6 |
| No physical calibration | M7 |
| Printer and open-source requirements unresolved | M7 |
| Project license unresolved | Before public release |

## Scope discipline

When a tempting feature appears, ask:

1. Does it improve the current milestone's exit evidence?
2. Does it preserve the accepted product principles?
3. Can it be added behind an existing contract?
4. What new failure modes and tests does it create?

If it does not help the current gate, record it under a later milestone rather than inserting it into the critical path.
