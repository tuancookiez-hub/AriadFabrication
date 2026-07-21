# Ariad Fabrication submission facts

Use this as a factual worksheet. Rewrite the final Devpost description in your own voice; do not paste this file as-is.

## Submission identity

- Project: **Ariad Fabrication**
- Short name: **Ariad**
- Track: **Developer Tools**
- Tagline: **Follow the thread from idea to evidence.**
- Supported judge platform: **Windows 11 x64**
- Deadline: **July 21, 2026 at 5:00 PM PDT / July 22 at 8:00 AM MYT**

## Problem in plain facts

- A visually plausible generated mesh is not proof that a functional part has correct dimensions, valid geometry, usable tolerances, appropriate print orientation, valid slicer output, or physical safety.
- Beginners should not need to understand every engineering subsystem before starting.
- Existing confidence must remain separate from evidence.

## What the working demo does

1. Accepts a fabrication prompt in one Guided Build Session.
2. Presents editable defaults, assumptions, and blocking product decisions.
3. Persists a project draft only after the user chooses to save it.
4. Creates R0 Brief evidence only after a separate explicit approval.
5. Retrieves an R0-bound Codex Design-plan proposal when available, with a labelled editable local fallback.
6. Shows a generated interlocking visual blueprint for approval while explicitly separating concept imagery from CAD evidence.
7. Continues into a nine-part tool-less robot CAD set using snap, slide, dovetail, press-fit, and keyed interfaces, then performs real disconnected slicing and builds a downloadable warned prototype package.
8. Provides a much smaller first-print calibration coupon for five dovetail clearances and three snap engagements before the user risks the complete robot.
9. Replays a persisted real Golden Part journey through editable CadQuery source, exact STEP lineage, OCCT geometry checks, profile-specific printability checks, real PrusaSlicer G-code, and a checksummed R4 package.
10. Displays failed and incomplete fixtures at their actual stopping gates and compares persisted revisions without pretending the comparison reran validation.

## How Codex and GPT-5.6 were used

- GPT-5.6 Codex was the primary collaborator used to plan, implement, test, audit, research, and visually rehearse Ariad during the submission period.
- Real locally authenticated Codex turns called Ariad's bounded idea-capture and R0-bound Design-proposal tools.
- Ariad exposes four non-mutating Codex tools. Codex cannot persist the Design plan, execute generated CAD, produce production G-code, or contact hardware through those tools.
- Deterministic CadQuery/OCCT code owns geometry evidence. PrusaSlicer owns G-code generation. Ariad records the evidence chain.
- Preserve the primary build task's verified `/feedback` Session ID in the Devpost form.

## New work to highlight

- Guided prompt → editable defaults → explicit R0 → generated visual blueprint → editable multi-part CAD user experience.
- Local Codex conversation and bounded tool integration.
- Evidence-replay API and React Journey explorer.
- Real GLB model inspection and worker-isolated 250-layer toolpath playback.
- Assembly-first robot decomposition, nine-part interlocking prototype CAD, and real per-part PrusaSlicer handoff.
- Six-part clearance/snap calibration coupon with a measurement protocol and no fabricated physical results.
- Revision comparison, failure fixtures, artifact integrity checks, and explicit claim boundaries.
- No-hardware execution controls, sealed target identity, runtime manifests, and adversarial tests.

## Verified state

- Backend verification: the current lightweight suite runs **270 tests successfully** with 23 optional CAD/slicer skips; the coupon's six focused tests also pass fully in the pinned CAD environment. The previously recorded sealed R4 integrations remain separate evidence.
- Frontend: **24 deterministic tests passed**, with two optional real-artifact tests skipped when their local artifacts are absent.
- Generated OpenAPI types, TypeScript, ESLint, production build, and live browser rehearsals pass.
- A valid local real R4 Golden Part revision contains a browser model, 250-layer slicer toolpath, profile evidence, and fabrication package.

## Limitations to state directly

- Arbitrary prompts do not yet trigger browser-side CAD execution.
- Robot CAD and slicing are prototype evidence; interlock fit, latch life, component fit, collision, balance, motion, and physical printing are not proven.
- No printer has been selected, connected, heated, moved, or started.
- R4 is digital, profile-specific slicer evidence—not guaranteed print success.
- Toolpath playback is not engineering simulation.
- The judge fixture path contains explicitly non-fabrication fixtures when local real artifacts are unavailable.

## URLs and external fields

- Repository URL: **TODO**
- Public YouTube URL: **TODO**
- `/feedback` Session ID: **TODO**
- Devpost project URL: **TODO**
- Repository access: **private; share with testing@devpost.com and build-week-event@openai.com**, unless the owner deliberately selects a public license.

## Prompts for your own final description

- What personally made you care about fabrication reliability?
- What surprised you when the first generated robot or ship models were not actually manufacturing-ready?
- Why did you choose “evidence over confidence” as Ariad's core value?
- Which demo moment best represents what you built?
- What would you build next after obtaining a printer and measuring real components?
