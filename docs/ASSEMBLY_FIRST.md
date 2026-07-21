# Assembly-first fabrication

**Status:** accepted product direction; contract implemented, UI integration pending
**Reviewed:** 2026-07-19

## What the robot experiment taught us

The early robot iterations exposed two distinct failures. First, generating geometry before approving multiview intent caused repeated spatial misunderstandings. Second, treating the result as one model hid the actual manufacturing problem: a robot is an assembly of printable parts, purchased components, joints, fasteners, clearances, and service operations.

The corrected order is:

```text
Prompt
-> visual intent and orthographic approval
-> assembly decomposition
-> purchased-component envelopes
-> part and interface specifications
-> simplified assembly layout
-> per-part CAD
-> assembly fit, access, collision, and motion checks
-> per-part printability and slicing
-> assembly package and instructions
```

Visual approval does not establish dimensions. Assembly planning does not establish CAD. Valid parts do not establish a valid assembly. Simulation does not establish physical operation.

## Implemented contract

`AssemblySpec` 1.0.0 records:

- separately manufactured parts and their roles;
- purchased-component envelopes and whether each is placeholder, manufacturer-sourced, or measured;
- interfaces between parts and components;
- rotating axes, running clearances, service requirements, and unresolved questions;
- literal-false hardware-action and physical-validation fields.

The first fixture decomposes the Ariad robot into nine printed parts, two manufacturer-sourced component envelopes, two supplier-dependent reservations, and seven interfaces. Rev A selects a Pi Zero 2 W and two SCS0009 servos before shaping the shell, uses external regulated power, and contains no battery. Printed parts use slide, dovetail, press-fit, keyed, and releasable snap interfaces; the Pi uses M2.5 nylon hardware and servo horns may use their manufacturer hardware. Camera/IMU variants, horn fit, calibrated interlocks, mass distribution, motion, and physical behavior remain unresolved.

## Required final-app experience

The app should add an **Assembly** stage between Design and per-part CAD. Its primary surfaces are:

1. Assembly tree with printable parts and purchased components.
2. Interface table showing participants, type, axis, clearance, requirements, and evidence.
3. Placeholder warnings for every unverified component envelope.
4. Exploded and assembled view modes.
5. Per-part Journey status and artifacts.
6. Assembly-level fit, collision, access, mass-property, and simulation results.
7. Package contents grouped by part, followed by assembly instructions.

Codex may propose decomposition and interfaces, but the user approves them. A provider cannot silently merge parts, invent purchased-component dimensions, or promote placeholder envelopes to measured evidence.

## Evidence gates

- **A0 — Assembly intent:** decomposition, components, and interfaces approved.
- **A1 — Part geometry:** every required part has editable exact geometry.
- **A2 — Assembly geometry:** transforms and interfaces are dimensionally consistent with no forbidden overlap.
- **A3 — Assembly simulation:** named collision/motion scenarios run with recorded assumptions.
- **A4 — Fabrication set:** every printable part passes its own approved slicing lane and the package contains assembly instructions.
- **A5 — Physical assembly:** later measurements and observed operation; unavailable without hardware.

These assembly levels complement rather than replace Ariad's existing R0-R5 evidence levels.

## Hackathon consequence

Ariad remains a **Developer Tools** submission. The product is an agentic development and validation environment for people building physical projects. The robot is a memorable example that demonstrates why the tool needs assembly decomposition; it is not the entire product and does not change the submission into a consumer robot app.
