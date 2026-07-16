# Product and principles

## Product identity

**Ariad Fabrication** is the product name and **Ariad** is the short name. **Fabrication Journey** is the primary user experience. **OpenGrow** is the first reference application, not the boundary of the platform.

The guiding line is **follow the thread from idea to evidence**. Ariad is a deliberate shortening of Ariadne: the product should guide a beginner through a fabrication labyrinth while preserving the thread that explains how every artifact and decision came to exist.

## Vision

Make functional digital fabrication understandable and testable for people who can describe what they need but cannot yet author production CAD or safely configure a manufacturing workflow.

## One-line contract

Ariad turns plain-language requirements into editable functional CAD and a reproducible, profile-specific fabrication package while showing exactly what has and has not been proven.

## Initial user

The first user is a beginner maker building functional FDM parts for planting, electronics, and small robotics. They need guidance without losing control over dimensions, assumptions, materials, and risk.

The architecture should remain useful to experienced makers who want inspectable source, repeatable jobs, and automation boundaries.

## Jobs to be done

- Turn an imprecise idea into explicit, editable requirements.
- Identify missing dimensions or unsafe assumptions before generating geometry.
- Produce a source-controlled parametric design rather than an opaque mesh alone.
- Explain why a part passed or failed each manufacturing stage.
- Revise one requirement without restarting the project or losing history.
- Compare alternatives by size, material, support need, print time, and risk.
- Export a package that another person or print service can reproduce.
- Learn the fabrication process while using it.

## Governing values

Organization supports the work, but these values decide how the product behaves.

### 1. Evidence over confidence

No model, agent, or UI message can declare a part reliable by assertion. Every claim must identify its evidence level: schema, CAD kernel, geometry checks, printability checks, slicer, benchmark, or physical measurement.

### 2. Reliability by construction

Reliability is built through versioned contracts, deterministic checks, stage exit gates, regression fixtures, and fail-closed behavior. It is not a final cleanup step.

### 3. Traceability

Every revision records its request, confirmed specification, generated source, tool versions, profiles, findings, decisions, approvals, and outputs. A user can answer, "How did this file come to exist?"

### 4. Reproducibility

A fabrication package contains enough source and configuration to rerun or inspect the job. Nondeterministic model behavior is isolated from deterministic geometry and manufacturing evidence.

### 5. Honest communication

Unknowns, assumptions, simulations, warnings, and unsupported checks remain visible. Workflow replay, G-code playback, engineering simulation, and physical validation are never presented as equivalent.

### 6. User agency

The user can edit the specification, inspect decisions, compare revisions, and approve consequential actions. The system asks when missing information would materially change the part.

### 7. Safety before autonomy

Software may prepare and inspect a job without hardware. Any future action involving heat, motion, pressure, electricity, or unattended operation requires explicit safety rules and human approval. Fault recovery must never pretend a physical intervention occurred.

### 8. Security and privacy

Generated code and untrusted files are isolated, secrets remain server-side, and data leaves the machine only through an explicit provider choice. Convenience does not justify an invisible trust boundary.

### 9. Interoperability and local ownership

Use open formats and replaceable adapters. Prefer local execution and user-owned artifacts. Cloud models and proprietary services may be optional providers, never the only route to the user's design history.

### 10. Learnability and accessibility

The product should explain manufacturing concepts in plain language while preserving detailed evidence for advanced users. Beginner-friendly does not mean hiding risk.

### 11. Maintainability

Keep domain contracts independent of UI, model provider, CAD engine, slicer, and printer. Add complexity only after a measured need appears.

### 12. Completeness through staged evidence

The architecture accounts for the complete lifecycle, including simulation, manufacturing, measurement, and calibration. Implementation proceeds through narrow vertical slices so unfinished stages are visible rather than faked.

### 13. Resource responsibility

Use validation, comparison, and virtual manufacturing to reduce failed prints, wasted material, unnecessary cloud calls, and premature hardware purchases.

## Product boundaries

Ariad is not:

- A claim to be the first or only prompt-to-print agent.
- A promise that arbitrary text can become an engineering-ready object.
- A replacement for every CAD workflow.
- A decorative text-to-mesh generator presented as mechanical CAD.
- A physics oracle or certification authority.
- A system that writes final G-code directly with an LLM.
- An unattended printer controller by default.
- A printer-fleet automation product in its initial milestones.
- A source of food-safety, medical, load-bearing, or regulatory certification.

## Design lanes

### Functional lane — primary

Parametric, dimensioned parts such as brackets, clamps, enclosures, mounts, adapters, jigs, hubs, and chassis components. The editable CAD program and exact geometry are first-class artifacts.

### Organic lane — deferred

Decorative or organic objects may use image/text-to-mesh providers and Blender-based cleanup. Their validation, licensing, and dimensional claims remain separate from the functional lane.

## Reference application: OpenGrow

OpenGrow grows in stages:

1. Passive planting parts: labels, trellis connectors, stake clamps, and tube guides.
2. Smart planter parts: ESP32 enclosures, sensor holders, pump mounts, and cable routing.
3. Robotics parts: motor mounts, wheel hubs, chassis modules, battery trays, and sensor masts.
4. Calibration loop: measured prints update printer/material compensation profiles.

Electronics, pumps, food-contact tubing, reservoirs, fasteners, and safety-critical components should generally be purchased as certified components rather than printed.

## Product success

The project succeeds when a new user can understand what is known, what is assumed, what was tested, and what still requires physical proof—and can produce a reproducible package without depending on this Codex task.
