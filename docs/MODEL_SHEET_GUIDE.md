# Ariad model-sheet visual guide

Reviewed: 2026-07-20

Concept imagery in Ariad is a communication aid for planning. It is never CAD, dimensional evidence, simulation, or proof of manufacturability. A concept must look like a working model sheet rather than a promotional render.

## Required sheet

Every generated concept sheet should contain:

1. Front, side, and rear orthographic views at a consistent scale.
2. One three-quarter view for silhouette and form readability.
3. One exploded assembly view showing intended part separation.
4. Numbered part callouts and a compact parts legend.
5. Major envelope dimensions in millimetres, marked **provisional** until confirmed.
6. Visible mechanical interfaces: pivots, fasteners, service openings, component envelopes, and cable paths.
7. Material and manufacturing assumptions in a small specification block.
8. A permanent label: **CONCEPT MODEL SHEET · NOT GENERATED CAD**.

## Visual language

- Neutral studio or drafting background; no cinematic scene.
- Orthographic or low-perspective views; no dramatic wide-angle lens.
- Consistent object proportions, colors, and details across every view.
- Matte prototype materials, restrained lighting, and readable edges.
- Technical annotations outside the object silhouette.
- No hands, people, workshop scenery, sparks, printer action, or fake software chrome.
- No unsupported claims such as printable, tested, safe, calibrated, or production-ready.

## Prompt template

```text
Create a professional 3D product model sheet for [OBJECT]. Show the same design consistently in front, left-side, rear, three-quarter, and exploded assembly views. Use a neutral drafting background, orthographic projection where possible, matte prototype materials, numbered part callouts, provisional envelope dimensions in millimetres, visible joints and service interfaces, and a compact parts legend. Preserve [KEY SILHOUETTE / FUNCTIONAL REQUIREMENTS] in every view. Add the exact label “CONCEPT MODEL SHEET · NOT GENERATED CAD”. Do not show a cinematic environment, printer, person, hands, or manufacturing claims.
```

## Admission rule

Reject or regenerate a sheet when views disagree about part count, limb placement, joint axis, openings, proportions, or assembly direction. Ariad may use an accepted sheet to discuss intent, but deterministic CAD and evidence stages must reconstruct the design from confirmed specifications rather than trace the image blindly.
