# Benchy and conventional-warship real-slicer comparison

This experiment runs the official 3DBenchy fixture and Ariad's conventional
warship through the same pinned PrusaSlicer executable, profile bundle, and
identity Z-up orientation.

It records:

- Exact input, profile, executable, and archive checksums.
- PrusaSlicer's model inspection and mesh-repair report.
- A profile-bearing 3MF slicer project.
- Real slicer-produced G-code.
- Layer, time, filament, feature, temperature, command, and motion summaries.
- Disconnected G-code preflight results.
- Slicer stability/support warnings and a side-by-side comparison.

The experiment never connects to or controls a printer. A successful run is
real slicer evidence, not a physical-print claim. Warnings are findings rather
than passes and must remain visible.

Example from the repository root:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe experiments\slicer_benchmark\run.py `
  --output-dir runs\experiments\slicer_benchmark\v1
```

The default slicer discovery expects the official portable PrusaSlicer 2.9.6
release under `runs/tools/prusaslicer/2.9.6`. Override it with `--slicer` and
record the new executable and archive provenance if the version changes.
