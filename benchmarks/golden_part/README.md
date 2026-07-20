# Golden Part: OpenGrow stake electronics clamp

This directory freezes the first functional benchmark independently of its CAD implementation.

- `part_spec.json` is the confirmed manufacturing intent and must validate against `schemas/v1/part-spec.schema.json`.
- `expected.json` contains the feature counts and exact measurements that M2 geometry queries must verify.
- `printability_expected.json` freezes the exact M3 profile IDs, deterministic R3 thresholds, and slicer-warning policy.

The benchmark intentionally exercises a cylindrical fit, controlled clearance, flat mounting interface, two M3 holes, cable routing, fillets, and support-conscious FDM design. The registered CadQuery provider earns R1 and R2 by executing editable source, re-importing one valid STEP solid, and passing all 25 frozen geometry checks. The exact centered Z-up STEP then earns R3 for one frozen generic 0.4 mm/PETG/process/orientation bundle through 23 deterministic checks, and a real disconnected PrusaSlicer 2.9.6 run earns R4 after G-code preflight and package completeness checks.

R4 is still digital and profile-specific. The package retains generic-profile, PETG bridging, elephant-foot, layer-strength, and build-surface unknowns; it makes no strength, real-stake fit, weathering, food-safety, or physical-print claim.
