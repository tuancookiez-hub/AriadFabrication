# WSL2 Bubblewrap isolation experiment

This experiment tests whether the current Windows host can launch a Linux process with:

- Windows host mounts absent;
- one explicit writable workspace;
- a private network namespace with no external connectivity;
- a short-lived child tied to its parent.

Run it from the repository root:

```powershell
python experiments/wsl_bubblewrap/qualify.py
```

Passing this probe is **not** registered execution evidence. It does not run or qualify the pinned CPython 3.11, CadQuery 2.8.0, OCP 7.9.3.1.1, PrusaSlicer 2.9.6, Ariad import guard, artifact lineage, resource policy, or cancellation behavior. It contacts no printer and performs no hardware action.

The experiment earns consideration as a future isolated lane only if Ariad can reproduce and checksum the complete approved Linux toolchain, apply the existing process/log/memory/workspace/deadline controls outside and inside WSL, and pass the real sealed R2/R4 tests without weakening their evidence contracts.
