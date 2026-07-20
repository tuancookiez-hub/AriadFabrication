# 3DBenchy external calibration benchmark

This directory preserves the official single-part 3DBenchy STL as an external
calibration fixture. 3DBenchy was created by Daniel Noree while at Creative
Tools to test and compare 3D printers. It is not a Ariad-generated design and it
does not qualify Ariad's functional-CAD provider.

The source file is pinned to the official `CreativeTools/3DBenchy` repository
commit recorded in `provenance.json`. The current official license page states
that 3DBenchy is available under CC0 1.0 Universal. Attribution is not required,
but Ariad retains the original name, author, source, and license URL.

Use the original STL unchanged when comparing slicers, printers, materials, or
profiles. Its nominal reference envelope is 60 x 31 x 48 mm and the official
generic FFF comparison settings use a 0.4 mm nozzle, 0.2 mm layers, 10% infill,
and no supports.

Important evidence boundary:

- A successful slice proves only that the recorded slicer/profile produced a
  toolpath that passed the recorded digital checks.
- A physically printed Benchy characterizes that printer/material/profile; it
  does not prove another model will print successfully.
- The official high-resolution STL contains zero-area facets at binary STL
  precision. PrusaSlicer 2.9.6 reports the mesh as manifold after removing those
  facets. Ariad preserves the source unchanged and records the repair count per
  slicer run.

Sources:

- https://www.3dbenchy.com/about/
- https://www.3dbenchy.com/3d-print/
- https://www.3dbenchy.com/license/
- https://github.com/CreativeTools/3DBenchy
