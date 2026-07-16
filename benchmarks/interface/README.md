# Fabrication Journey interface fixture

This directory contains a deterministic **interface fixture family**, not fabrication runs.

Every stage, event, finding, and artifact uses `evidence_mode: fixture`. The family contains:

- A complete R0–R4-shaped presentation fixture whose compact package permits only “Interface fixture only — no fabrication evidence.”
- A Brief fixture that stops at `needs_input` before R0.
- A Geometry fixture that stops at `failed` before R2.
- A Printability fixture that stops at `failed` before R3.
- A Package fixture that remains `running` with no manifest or package record.

These records prove that M4 presents completed, failed, paused, warning, manifest, and claim states without inventing later stages. They provide no CAD, slicing, printability, physical, or safety evidence and must never advance a production claim.

Regenerate it from the frozen Golden Part specification with:

```powershell
.\.venv\Scripts\ariad-interface-fixture.exe --output benchmarks/interface
```

The generator uses fixed IDs, timestamps, content, and checksums. Tests compare a fresh generation with every committed fixture and prove that each journey stops at its persisted gate.
