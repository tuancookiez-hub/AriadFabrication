# Repository guidance

These rules apply to the entire repository.

## Read before changing the project

1. `README.md` for stable scope and current evidence.
2. `NOW.md` for the active milestone.
3. `docs/DECISIONS.md` for accepted direction.
4. `docs/ARCHITECTURE.md` for contracts and boundaries.
5. `docs/RELIABILITY.md` for stage gates and allowed claims.

If a task conflicts with an accepted decision, surface the conflict before implementation or add an explicit superseding decision with the user's agreement.

## Project values

Apply evidence over confidence, reliability by construction, traceability, reproducibility, honest communication, user agency, safety, security and privacy, interoperability, learnability and accessibility, maintainability, completeness through staged evidence, and resource responsibility.

## Truthfulness rules

- Separate current implementation from target architecture.
- Label every provider or artifact as real, simulated, fixture, or unavailable.
- Do not call a part printable, safe, strong, calibrated, or physically validated without the matching evidence level.
- Do not present toolpath playback as engineering simulation or physical proof.
- Never pretend a physical intervention occurred in a simulator.

## Implementation rules

- Build the current milestone's exit gate before adding later-roadmap features.
- Preserve clean boundaries between domain records, model providers, CAD workers, validators, slicers, UI, and printer adapters.
- Generated CAD code must eventually run inside an explicit sandbox boundary.
- Final production G-code must come from an approved slicer adapter, never directly from an LLM.
- Hardware adapters default to disconnected and read-only.
- Keep artifact and schema versions explicit.
- Add or update tests with behavior changes.
- Avoid adding a dependency without documenting the reason, license, runtime impact, and removal path.

## Documentation rules

- `README.md` changes only for stable scope, navigation, or verified status.
- `NOW.md` contains only immediate work, blockers, and the current exit gate.
- `docs/DECISIONS.md` records durable choices and superseding evidence.
- `docs/ROADMAP.md` is milestone-based; do not add deadline-driven shortcuts.
- `docs/RESEARCH.md` records a review date and links to primary sources where possible.
- Update documentation in the same change that makes a status statement obsolete.

## Verification

The baseline test command is:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```

Add narrower checks for the component changed. Once CAD and slicer dependencies exist, record their executable versions in tests and run manifests.

## Generated files

Runtime artifacts belong under `runs/` and are ignored by default. Curated benchmark fixtures may be committed under a future `benchmarks/` directory with provenance and expected results.
