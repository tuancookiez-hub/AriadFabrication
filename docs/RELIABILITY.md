# Reliability and validation

## Reliability contract

Reliability means the system can show why an artifact was accepted, reproduce the checks, detect known failure modes, and refuse claims that exceed the available evidence.

It does not mean every passing digital model will print successfully or survive its intended use. Physical fabrication remains the final source of truth.

## Evidence ladder

| Level | Label | Required evidence | Allowed claim |
|---|---|---|---|
| R0 | Parsed | Request conforms to the versioned specification schema | “Requirements were parsed” |
| R1 | CAD generated | CAD source executes and the kernel exports a valid solid | “Parametric geometry was generated” |
| R2 | Geometry verified | Critical dimensions, topology, walls, holes, and clearances pass deterministic checks | “Geometry-verified for the checked rules” |
| R3 | Printability assessed | Orientation, build-volume, nozzle/material, overhang, support, and feature rules evaluated | “Printability-assessed for this profile” |
| R4 | Slicer verified | A real slicer produces a project and G-code that pass preflight | “Slicer-verified for this recorded profile” |
| R5 | Benchmark qualified | The workflow passes the relevant regression families and failure tests | “Qualified within the supported benchmark scope” |
| R6 | Physically measured | A recorded printer/material/profile produced a part with measurements and observations | “Physically validated under the recorded conditions” |
| R7 | Calibrated | Repeated measurements support a per-printer/material compensation profile | “Calibrated for the recorded machine and process” |

No interface should collapse these levels into a single green “printable” badge.

## Stage gates

### Brief gate

- Units and all critical dimensions are explicit.
- Unknowns and assumptions are recorded.
- Mating geometry, clearances, environment, material, and assembly method are present when relevant.
- Unsupported safety-critical intent is blocked or escalated.

### Design gate

- CAD source exits successfully within its declared worker boundary and enforced timeout.
- The result contains the expected number and type of solid bodies.
- STEP and preview exports succeed.
- Parameters and feature intent remain inspectable.

### Geometry gate

- Kernel reports valid solid topology.
- Bounding dimensions match the specification within the declared tolerance.
- Critical holes, slots, walls, radii, and clearances are measured directly.
- No zero-thickness or invalid intersections are accepted.
- Mesh compatibility output is manifold and uses documented tessellation settings.

### Printability gate

- The oriented part fits the selected build volume with margins.
- Minimum walls and features are evaluated against nozzle and process rules.
- Overhang, bridging, support, bed-contact, elephant-foot, and weak layer-direction risks are reported.
- Material and profile limitations are visible.

### Slicer gate

- The approved slicer process exits successfully.
- Slicer and profile versions are recorded.
- Layer count, time, material, temperatures, speeds, and support summary are parsed.
- G-code coordinates remain inside the configured volume.
- Forbidden or unexplained commands fail preflight.
- Exact-CAD mesh repairs, floating bridge anchors under a support-disabled process, and unclassified slicer warnings block R4 under the frozen Golden Part policy.
- Low-bed-adhesion may advance only as a visible warning; a successful slicer exit never erases it.

### Package gate

- Manifest references every artifact by checksum.
- Source, exact geometry, manufacturing package, preview, reports, and profiles are present where applicable.
- Simulated or fixture outputs are prominently labelled.
- Unresolved warnings and approvals remain attached.

## Golden Part

The first qualification part is a parameterized plant-stake electronics clamp. M1 froze its confirmed input in `benchmarks/golden_part/part_spec.json` and its exact feature/count targets in `benchmarks/golden_part/expected.json` before CAD implementation.

It must exercise:

- A cylindrical mating feature.
- A controlled fit or clearance.
- A flat electronics mounting interface.
- Two M3 mounting features.
- A cable-routing feature.
- Fillets or stress-relieving transitions.
- A support-conscious print orientation.
- PETG-oriented manufacturing rules.

The benchmark specification contains expected feature counts and measurements, not only an overall bounding box. M2 executes the copied editable source, canonicalizes and re-imports STEP as one valid solid, and passes 25 frozen OCCT checks. Those checks cover kernel validity, body count and volume, envelope, bore, derived stake clearance, radial wall, split, mounting interface, M3 holes and spacing, cable channel, and transition fillets. The compatibility binary STL separately passes finite/nondegenerate triangle checks and a closed, consistently oriented two-manifold edge test.

M3 preserves those Design artifacts, materializes a deterministic centered Z-up STEP, and evaluates 23 frozen R3 checks against exact generic printer, PETG, process, and orientation profiles. The checks cover profile/spec identity, build-volume margins, on-bed placement, exact bed-contact area, nozzle-relative walls and open features, layer-height ratio, steep downward area outside bed/bridge classifications, bounded horizontal-hole spans, support-disabled consistency, bore direction, and nominal first-layer clearance. All pass for the recorded bundle. Five physical unknowns remain warnings rather than passes: generic calibration, PETG bridge behavior, elephant foot, layer-direction strength, and build-surface compatibility.

The approved disconnected PrusaSlicer 2.9.6 run reports one manifold part, zero mesh repairs, and no slicer warnings; it produces a profile-bearing 3MF project and G-code that pass preflight. The package gate verifies 19 required evidence roles and publishes a 36-artifact manifest. This earns R3 and R4 only for the exact recorded revision and generic profile. It does not establish fit on an unmeasured stake, load capacity, adhesion, dimensional accuracy, weathering, food safety, or physical success.

## External calibration benchmark

The official single-part 3DBenchy is preserved under `benchmarks/3dbenchy/` as a checksum-pinned CC0 external fixture. It benchmarks slicer, printer, material, and profile behavior; it does not qualify Ariad's CAD provider or prove another model will print.

In the first PrusaSlicer 2.9.6 comparison, the official STL was reported as one manifold part after the slicer removed 552 degenerate facets. The source remains unchanged and the repair count is part of the run evidence. A successful digital Benchy slice is R4-shaped compatibility evidence only inside the experiment; a physically measured Benchy is still required to characterize actual hardware.

## Benchmark families

After the Golden Part passes, expand one family at a time:

1. L bracket.
2. Tube or stake clip.
3. Enclosure and lid.
4. N20 motor bracket.
5. SG90 servo mount.
6. Pump and hose-routing bracket.
7. Wheel hub.
8. Camera or sensor mast.
9. M3 heat-set-insert coupon.
10. Clearance and hole-size calibration coupon.

Decorative models do not count toward functional-CAD qualification.

## Test strategy

### Contract tests

- Schema versioning and migrations.
- Required-field and invalid-unit failures.
- Provider input/output contracts.
- Artifact manifest completeness.

### Geometry tests

- Golden dimensions and feature queries.
- Degenerate and self-intersecting fixtures.
- Wall, hole, clearance, and body-count checks.
- Export and re-import consistency where supported.

### Pipeline tests

- Legal and illegal stage transitions.
- Retry, cancellation, `needs_input`, warning, and superseded states.
- Artifact lineage across revisions.
- Failure injection for every external provider.

### Slicer tests

- Known profile and geometry produce a valid slice.
- Oversized parts, unsupported temperatures, invalid profiles, multiple tools, malformed G-code, forbidden commands, timeouts, exact-CAD repairs, and blocking warnings fail.
- Estimates and layer summaries are parsed from real output.

### Security tests

- Generated-code timeouts and resource limits.
- Path traversal and unauthorized file access.
- Oversized or adversarial input files.
- Secret leakage into logs and artifacts.

### Physical tests — later

- Calibration cube and dimensional coupons.
- Hole, clearance, fastener, and heat-set-insert coupons.
- Temperature, flow, retraction, bridge, and overhang tests.
- Repeated measurements by printer, nozzle, material, and profile.

## Failure policy

- Unknown or unavailable evidence is not a pass.
- Warnings may proceed only when the stage policy allows them and the user can inspect the consequence.
- Safety-critical failures are non-retryable without changed input or explicit intervention.
- Automatic repair produces a new revision and reruns affected downstream gates.
- The model may propose remediation but cannot waive deterministic failures.
- A provider outage must not silently switch to a provider with different licensing or evidence semantics.

## Simulation labels

- **Replay:** a record of actual pipeline events.
- **Preview:** a rendering of geometry.
- **Toolpath simulation:** playback of actual slicer output.
- **Estimated:** derived time, material, or risk.
- **Engineering simulation:** model-based analysis with stated assumptions.
- **Measured:** physical observation.

These labels must appear in both reports and the interface.

## Current M4 interface gate

The read-only M4-A through M4-F application slices preserve evidence rather than creating it:

- The API groups stages, events, findings, and artifacts only through IDs already persisted in `journey.json` and `manifest.json`.
- A missing manifest remains `manifest_available: false`; it does not erase an otherwise inspectable incomplete journey or promote it.
- Malformed ownership, unsafe paths, mismatched manifest records, and artifact size/checksum drift fail closed.
- The committed interface family uses `evidence_mode: fixture` at every stage. It includes a complete parent/child comparison pair plus `needs_input`, failed Geometry, failed Printability, and incomplete Package paths, and both complete packages permit only “Interface fixture only — no fabrication evidence.”
- API capabilities and artifact responses explicitly report that hardware actions are unavailable.
- The canonical OpenAPI snapshot contains only GET contracts, marks the read-only capability constants and emitted response fields as required, generates the browser response types, and fails backend or frontend checks when either snapshot or generated code drifts.
- API 1.2.1 parses only the recorded geometry, printability, preflight, printer, material, process, and orientation roles after verifying each file against its persisted size and SHA-256. JSON is capped at 2 MiB, 500 checks, 100 messages/features, 128 top-level inspection fields, depth 16, and 20,000 nodes; missing, oversized, changed, invalid, ambiguous, or unsupported sources become explicit unavailable records rather than pass states.
- The evidence explorer selects persisted requirements and records for explanation only. It does not spatially highlight STEP features, recompute measurements, rerun validators, or turn a selected pass into new evidence.
- Revision comparison is computed from two normalized read views on the server. It omits volatile record IDs and timestamps; compares semantic stage, requirement, feature, report, check, finding, profile, artifact-checksum, and package values; caps each side at 10,000 records, output at 1,000 changes, and each returned value at 64 KiB; and marks the result incomplete when any bound is reached. An unchanged row is not proof of exact geometry or physical equivalence.
- Artifact delivery captures no more than 64 MiB into a byte snapshot, then checks that exact snapshot against the persisted size and SHA-256 before constructing the response. The path is not reopened. Responses expose the recorded evidence mode, verified-snapshot label, strong checksum ETag, ceiling, `no-store`, `nosniff`, RFC 5987 attachment name, and `hardware-action: false`. Invalid media/evidence header values fail closed as revision-integrity conflicts; oversize returns 413.
- The React interface keeps fixture, warning, claim, physical-evidence, and disconnected-hardware boundaries visible and contains no “printable” badge.
- The GLB inspector reads only checksum-verified preview artifacts, caps input at 64 MiB / two million triangles, and states that STEP remains exact geometry.
- The G-code worker caps input at 64 MiB / one million linear segments, samples only oversized display layers, and states that playback is not collision, extrusion, thermal, structural, or physical simulation. Unsupported arc commands are counted and disclosed rather than silently drawn as lines; the current Golden Part contains none.
- Real-artifact integration tests load the recorded GLB through Three.js and parse the recorded 250-layer G-code, while deterministic tests cover layer, mode, feature, travel, extrusion, unit, and omitted-arc behavior.

This establishes interface-contract, parser, renderer-compatibility, semantic-comparison, verified-delivery, and presentation-test evidence. All 84 backend tests, seven deterministic frontend tests, and two real-artifact frontend integration tests pass. Screenshot-level visual/accessibility QA and real end-to-end pipeline execution through the browser remain M4 work; passing these checks still provides no physical fabrication evidence.

## Reliability gaps that remain after digital validation

- FDM strength depends on orientation, adhesion, temperature, moisture, and printer calibration.
- Slicer success does not prove dimensional fit or load capacity.
- Material brand, color, age, and additives can change behavior.
- Warping and first-layer adhesion are not fully predicted by toolpath inspection.
- Food contact, outdoor lifetime, electrical safety, and regulated use need separate evidence.

The product should make those gaps easier to manage, not make them disappear rhetorically.
