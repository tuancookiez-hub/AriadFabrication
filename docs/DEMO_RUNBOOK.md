# Ariad hackathon demo runbook

This is the operator card for the recorded demo. Target duration: **2:45**.

## Before recording

1. Close unrelated windows and notifications.
2. Ensure `runs/` contains at least one valid real R4 Golden Part revision.
3. Ensure `runs/codex-chat/` exists and is empty.
4. Use a native Codex CLI that Ariad reports as compatible and authenticated.
5. Start the curated showcase:

```powershell
.\scripts\start_demo.ps1 -Evidence showcase -CodexBin "C:\path\to\codex.exe"
```

Without `-CodexBin`, the guided product and evidence demo still works; describe the previously verified Codex/GPT-5.6 integration rather than claiming a live turn.

## Recording path

### 0:00–0:15 — Problem and promise

Start on **Build session** and say:

> A generated mesh is not manufacturing evidence. Ariad gives Codex a reliable fabrication workflow and lets beginners follow the thread from an idea to what was actually checked.

### 0:15–1:35 — One smooth guided build

Use the robot example. Show the concise assumptions, approve the Brief, then pause on the generated interlocking blueprint. Point out the consistent views, exploded tool-less assembly, and explicit “not generated CAD” boundary. Approve it and continue through the real multi-part CAD viewport, Verify, real Slice, Package, and the smaller first-print calibration coupon. Say:

> Codex guides the intent and revisions. The blueprint confirms what I mean, CAD defines the parts, Ariad checks them, and PrusaSlicer produces the manufacturing files.

Do not edit every field on camera. If no Codex proposal is retained, show the labelled local fallback and say so.

### 1:35–2:05 — Real registered benchmark

Return to **Journey** and open the card labelled **Persisted pipeline revision** and **R4**. Show:

- the six-stage fabrication thread;
- Model: orbit the persisted GLB preview;
- Evidence: one geometry check and one physical warning;
- Toolpath: show `Layer 1 / 250`, then advance a layer;
- PrusaSlicer identity, estimated time/material, and the fabrication package.

Say: **“G-code came from the approved slicer, not the model.”**

### 2:05–2:25 — Failure and revision behavior

Open **Ariad gate fixture — geometry failed** and show that the thread stops at Geometry Validation. Return home and compare the two OpenGrow interface fixtures. Explain that a diff is not a validation run and fixture evidence cannot become real evidence.

### 2:25–2:40 — How Codex and GPT-5.6 were used

Show the Codex workspace or a concise repository/test view. Say:

> GPT-5.6 Codex helped design and implement the contracts, UI, CAD experiments, adversarial tests, and evidence boundaries. Inside Ariad, local Codex can call four bounded tools, including an R0-bound Design-plan proposal, but deterministic CAD, OCCT checks, and PrusaSlicer own downstream evidence.

### 2:40–2:45 — Closing line

> Follow the thread from idea to evidence.

## Do not claim

- arbitrary prompts currently generate CAD;
- the robot prototype has verified component fit;
- any part was physically printed;
- R4 guarantees print success, fit, strength, safety, or food contact;
- toolpath playback is engineering simulation;
- fixture records are fabrication evidence.

## Manual items after recording

- Upload a public YouTube video shorter than three minutes.
- Confirm it has clear audio and no unlicensed music, footage, or third-party trademarks.
- Obtain the verified `/feedback` Codex Session ID from the primary build task.
- Add the repository URL and choose public licensing or private judge access.
- Complete and submit the Devpost form yourself in your own voice.
