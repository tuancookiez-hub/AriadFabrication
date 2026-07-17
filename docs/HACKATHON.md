# OpenAI Build Week submission workspace

**Status:** working draft, not a claim that the submission is complete  
**Track:** Developer Tools  
**Official deadline:** July 21, 2026 at 5:00 PM Pacific Time

This file translates the official submission requirements into evidence Ariad
must actually provide. The authoritative event page is the
[OpenAI Build Week Devpost page](https://openai.devpost.com/).

## One-sentence project

**Ariad Fabrication turns a fabrication idea into an inspectable journey from
requirements to editable CAD and real slicer evidence, while clearly separating
digital checks from physical proof.**

## Submission description draft

Most prompt-to-3D demos stop when a plausible mesh appears. That is not enough
for a functional part: beginners still need to understand assumptions,
dimensions, geometry failures, printer-profile constraints, slicer warnings,
and what has not been physically tested.

Ariad Fabrication is a local-first developer tool that makes this workflow
auditable. Its Fabrication Journey records each stage—Brief, Design, Geometry
Validation, Printability Validation, Slicing, and Package—as immutable evidence
with checksums, events, findings, and explicit claim boundaries. The current
registered benchmark produces editable CadQuery source, exact STEP, a browser
GLB preview, profile-specific printability findings, real PrusaSlicer G-code,
and a reproducible R4 fabrication package without connecting to a printer.

Codex helped build and repeatedly audit the architecture, contracts, failure
paths, Windows process supervision, evidence replay, React interface, and test
suite. GPT-5.6 is intended to convert broad user ideas into a strict intent
proposal and capability route. The model is not allowed to declare geometry,
printability, slicing, or physical success; deterministic tools and persisted
artifacts own those claims.

The long-term product accepts many fabrication ideas and routes them to
functional parametric CAD, organic mesh generation, clarification, or an
unsupported state. Today, only the fixed Golden Part is executable. The UI must
say so plainly rather than pretending every prompt generated the benchmark.

## What judges can run today

Supported platform: Windows 11 x64 with Python 3.11, Node.js, `uv`, and the
documented PrusaSlicer 2.9.6 portable toolchain for the full R4 path.

```powershell
uv sync --extra test --extra cad
pnpm --dir web install --frozen-lockfile

# One-command fixture demo (hardware remains disabled)
.\scripts\start_demo.ps1

# Terminal 1: read-only local API over existing evidence
.\.venv\Scripts\ariad-interface-api.exe --runs-root runs

# Terminal 2: React interface
pnpm --dir web dev
```

For a lightweight UI-only evaluation, use `benchmarks/interface` as the API
runs root. Those records are visibly marked as fixtures and provide no
fabrication evidence.

For the real disconnected benchmark:

```powershell
.\.venv\Scripts\python.exe -m ariad_fabrication.cli --golden-part --runs-root runs
```

No command uploads G-code, heats a tool, moves a printer, or claims a successful
physical print.

## Under-three-minute demo script

Target duration: **2:40–2:55**. Keep the video public and make the working
software—not slides—the primary visual.

### 0:00–0:20 — Problem

Show one sentence on screen, then the Ariad dashboard:

> A generated mesh is not manufacturing evidence. Ariad shows beginners the
> thread from an idea to what has actually been checked.

### 0:20–0:45 — Universal intake and honest routing

Enter two contrasting prompts:

1. “Design a weather-resistant enclosure for a soil sensor.”
2. “Create a decorative floating air warship.”

Show that both ideas are captured and that GPT-5.6 is explicitly unavailable
when no API credential is configured. Point to the intended functional-CAD and
organic-mesh lanes in the capability panel, but do not claim the model selected
either route. Then open the existing registered Golden Part evidence from the
Journey page. Do not imply either free-form prompt generated the benchmark.

### 0:45–1:35 — Fabrication Journey

Open the real Golden Part revision and move across the shipment-style stages:

- Brief: inspect requirements and visible assumptions.
- Design: show editable CadQuery source and exact STEP lineage.
- Geometry: show deterministic checks and the GLB preview.
- Printability: show profile-specific passes and unresolved physical warnings.

Say “digital evidence” once. Avoid “guaranteed printable.”

### 1:35–2:05 — Real slicer and package

Show the real G-code layer player, PrusaSlicer identity, profile snapshot,
estimated material/time, package artifacts, and checksums. Point out that G-code
came from the approved slicer, not GPT-5.6.

### 2:05–2:30 — Failure and revision evidence

Open one failed fixture and the parent/child comparison. Explain that stages stop
at the failed gate and that fixture evidence can never be promoted to real.

### 2:30–2:50 — Codex and GPT-5.6

Show the repository test result and one concise architecture view. Explain:

- Codex accelerated implementation, audits, adversarial tests, and UI iteration.
- GPT-5.6 proposes structured intent and routing only.
- CAD, OCCT validation, PrusaSlicer, and persisted checks own downstream claims.

End on: **“Follow the thread from idea to evidence.”**

## Official requirement checklist

The event requires a working project, category, project description, a public
YouTube demo shorter than three minutes, repository access, README setup/sample
data, explanation of Codex and GPT-5.6 use, a `/feedback` Codex session ID, and
developer-tool installation/testing instructions.

| Requirement | Evidence | State |
|---|---|---|
| Working project | Real R2/R4 benchmark plus React intake/evidence explorer | Partial: intake works; browser execution remains locked |
| Category | Developer Tools | Ready |
| Project description | Draft above | Draft |
| Public demo under 3 minutes | Script above | Not recorded |
| Repository URL and judge access | Must be supplied in Devpost | Missing |
| Public license or private judge sharing | Durable decision required | Missing |
| README setup instructions | Root README | Present; final clean-machine audit pending |
| Sample data | `benchmarks/interface/` and Golden Part benchmark | Present |
| Codex contribution explanation | Description and demo script | Draft |
| GPT-5.6 working use | Structured intent provider | Blocked by missing API credential |
| `/feedback` session ID | Submission form field | Missing; do not substitute a thread ID without verification |
| Judge test path without rebuild | `scripts/start_demo.ps1` with fixture evidence | Ready on documented Windows environment; clean-machine audit pending |

## Claims allowed in the submission

- Real editable parametric source and exact-geometry evidence exist for the
  registered Golden Part.
- Real PrusaSlicer output exists for the pinned generic profile bundle.
- The package is traceable and reproducible under the recorded local toolchain.
- The interface distinguishes real, simulated, fixture, and unavailable state.
- No printer is required to inspect the workflow.

## Claims prohibited without new evidence

- “Any prompt becomes printable CAD.”
- “Ariad proves a part is safe, strong, food-grade, or weatherproof.”
- “The Golden Part was physically printed or fit-tested.”
- “Toolpath playback is engineering or printer simulation.”
- “Browser Run is safe” before its operating-system and authentication gates pass.
- “Open source” until a repository license is selected and committed.

## Final submission blockers

1. Configure an OpenAI API credential and validate the GPT-5.6 structured-intent
   path against a frozen prompt corpus.
2. Finish the coherent browser intake/run experience or explicitly package the
   verified runner as a local-only demo with no unsafe mutation endpoint.
3. Perform screenshot-level browser and assistive-technology checks.
4. Select a repository license or configure private judge access.
5. Record/upload the demo, obtain the verified `/feedback` session ID, and enter
   repository/video URLs in Devpost.
