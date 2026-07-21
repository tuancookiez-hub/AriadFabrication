# OpenAI Build Week submission workspace

**Status:** submitted; local guided-build, bounded live-CAD, and full-evidence demo gates exercised
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
suite. A locally authenticated GPT-5.6 Codex session also works inside Ariad's
conversation surface and has called Ariad's bounded idea-capture tool. Codex is
not allowed to declare geometry, printability, slicing, or physical success;
deterministic tools and persisted artifacts own those claims.

The long-term product accepts many fabrication ideas and routes them to
functional parametric CAD, organic mesh generation, clarification, or an
unsupported state. Today, one bounded seven-parameter L-bracket family generates
fresh CAD from judge-entered dimensions, while the robot and Golden Part provide
prepared multi-part and full-evidence reference journeys. The UI says which path
is live rather than pretending every prompt generated the prepared references.

## What judges can run today

Supported platform: Windows 11 x64 with Python 3.11, Node.js, `uv`, and the
documented PrusaSlicer 2.9.6 portable toolchain for the full R4 path.

```powershell
uv sync --frozen --extra test --extra cad
pnpm --dir web install --frozen-lockfile

# One-command curated demo: one local real R4 revision when available plus fixtures.
.\scripts\start_demo.ps1

# Live project clarification and R0 confirmation use the mutable runs workspace.
.\scripts\start_demo.ps1 -Evidence runs

# Optional: show sanitized local Codex authentication status. Pass the native
# codex.exe from the installed Codex package, never auth.json or a token.
.\scripts\start_demo.ps1 -CodexBin "C:\path\to\codex.exe"

# Terminal 1: read-only local API over existing evidence
.\.venv\Scripts\ariad-interface-api.exe --runs-root runs

# Terminal 2: React interface
pnpm --dir web dev
```

The default `showcase` mode prepares ignored `runs/showcase/` with one valid real R4 revision when available and all six committed fixtures. It allows the live project-to-R0 flow and removes duplicate/invalid development runs from the recording surface. For a lightweight UI-only evaluation, use `benchmarks/interface` as the API
runs root. Those records are visibly marked as fixtures and provide no
fabrication evidence. R0 project confirmation is disabled in this mode so the
committed fixture cannot be mutated; use `-Evidence runs` for the live project flow.

To prove the browser is not replaying a pre-generated bracket, open **Build
session**, choose **Use live bracket example**, change `60 x 40 x 45 mm` to a
different in-range size such as `72 x 44 x 50 mm`, and approve the Brief. Ariad
will display a new parameter hash and generation ID and serve the resulting STEP,
STL, and GLB. This test proves bounded digital CAD generation only; it does not
claim slicing, printability, or physical success for that parameter set.

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

### 0:20–1:05 — Codex, clarification, and the R0 Brief

Ask Codex for a small fabrication idea, then use the separate confirmation
action to save it as a project. Open Projects and show:

- unknown dimensions remain visibly blank rather than being invented;
- completing the clarification form still creates no evidence;
- checking the approval statement and confirming creates one real R0 Brief;
- the new “Open the R0 Journey” link shows the persisted Brief trace.

Say plainly that R0 proves confirmed requirements only. It does not mean the
free-form prompt generated CAD. Then open the separately registered Golden Part
evidence from the Journey page.

### 1:05–1:45 — Fabrication Journey

Open the real Golden Part revision and move across the shipment-style stages:

- Brief: inspect requirements and visible assumptions.
- Design: show editable CadQuery source and exact STEP lineage.
- Geometry: show deterministic checks and the GLB preview.
- Printability: show profile-specific passes and unresolved physical warnings.

Say “digital evidence” once. Avoid “guaranteed printable.”

### 1:45–2:15 — Real slicer and package

Show the real G-code layer player, PrusaSlicer identity, profile snapshot,
estimated material/time, package artifacts, and checksums. Point out that G-code
came from the approved slicer, not GPT-5.6.

### 2:15–2:35 — Failure and revision evidence

Open one failed fixture and the parent/child comparison. Explain that stages stop
at the failed gate and that fixture evidence can never be promoted to real.

### 2:35–2:50 — What Codex did

Show the repository test result and one concise architecture view. Explain:

- Codex accelerated implementation, audits, adversarial tests, and UI iteration.
- GPT-5.6 Codex converses through Ariad and can call four bounded,
  non-mutating Ariad tools, including an R0-bound Design-plan proposal tool.
- CAD, OCCT validation, PrusaSlicer, and persisted checks own downstream claims.

End on: **“Follow the thread from idea to evidence.”**

## Official requirement checklist

The event requires a working project, category, project description, a public
YouTube demo shorter than three minutes, repository access, README setup/sample
data, explanation of Codex and GPT-5.6 use, a `/feedback` Codex session ID, and
developer-tool installation/testing instructions.

| Requirement | Evidence | State |
|---|---|---|
| Working project | Guided prompt-to-R0-to-Design flow, live bounded L-bracket CAD, robot assembly foundation, real R2/R4 benchmark, React evidence explorer, curated showcase | Live full-demo rehearsal passed; arbitrary generated-code CAD remains unavailable |
| Category | Developer Tools | Ready |
| Project description | Draft above | Draft |
| Public demo under 3 minutes | Script and `DEMO_RUNBOOK.md` | Not recorded |
| Repository URL and judge access | Public repository: `tuancookiez-hub/AriadFabrication` | Ready |
| Public license or private judge sharing | Apache-2.0 repository license | Ready |
| README setup instructions | Root README | Present; final clean-machine audit pending |
| Sample data | `benchmarks/interface/` and Golden Part benchmark | Present |
| Codex contribution explanation | Factual description and timed demo narration | Ready for owner rewrite/rehearsal |
| GPT-5.6 working use | Real local Codex turns called `ariad.capture_idea` and the R0-bound `ariad.propose_design_plan` without persisting CAD or plan state | Ready on the builder's authenticated machine; judges use their own Codex authentication |
| `/feedback` session ID | Submission form field | Missing; do not substitute a task/thread ID without verification |
| Judge test path without rebuilding artifacts | README judge quickstart, live bracket instructions above, and `scripts/start_demo.ps1`; fixture fallback when no local R4 exists | Local showcase and live-CAD rehearsals passed; clean-machine audit pending |

Live rehearsal evidence through 2026-07-20: authenticated Codex completed real `ariad.capture_idea` and R0-bound Design-proposal turns; the Guided Build Session passed prompt → draft → explicit R0 → editable Design planning; the curated catalog contained one real R4 and six valid fixtures; the real GLB viewport and 250-layer G-code player loaded without browser errors; failed Geometry stopped at its gate; and revision comparison returned 12 bounded changes. The backend passes 264 tests: 262 ordinary/contract tests plus two separately run sealed R4 integrations. Twenty-four deterministic frontend tests, generated-type drift, lint, and production build pass.

## Claims allowed in the submission

- Real editable parametric source and exact-geometry evidence exist for the
  registered Golden Part.
- The registered L-bracket family generates parameter-bound STEP, STL, and GLB
  artifacts live, with kernel checks and content identities.
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

1. Run the documented setup on a clean Windows checkout.
2. Share the private GitHub repository with `testing@devpost.com` and `build-week-event@openai.com`, or explicitly select and commit a public license.
3. Create the Ariad Devpost draft. The authenticated account is registered for OpenAI Build Week but had no Ariad project draft when audited on 2026-07-19.
4. Add and confirm any teammates and verify judge access.
5. Record/upload the demo, obtain the verified `/feedback` session ID, and enter
   repository/video URLs in Devpost.
6. Complete assistive-technology checks after the submission-critical path; current keyboard, contrast, reduced-motion, desktop, and mobile checks already pass their stated bounds.
