# Vernier pilot implementation plan

**Goal:** Verify the corrected Vernier solver workflow, then run five independent workers and consolidate their actual results.

**Architecture:** Keep source base.aedt unchanged. Initialize each working-copy model once by deleting CylindricalGap1, update coupled geometry and shared RMS current from actual coil areas, solve Setup1, read SI waveforms and evaluate the last electrical cycle. Keep a central ledger and one workbook for the pilot.

**Tech stack:** AEDT 2024.1, native API/COM or independently addressed gRPC sessions, Python, SQLite, artifact-tool XLSX export.

**Spec:** Vernier_Model_Constraints.txt and user decisions in README.md. User authorized execution and prioritizes five simultaneous workers.

## Constraints

- kfill=0.4; both stator current densities <=5.5 A/mm2, with shared RMS current.
- Keep existing instantaneous efficiency expression including 2% excess loss; average over the last cycle.
- Voltage is recorded, not constrained for this performance pilot.
- Delete only CylindricalGap1 once per working-copy initialization.
- No SPM solver runs or source model modifications.

## Tasks

- [x] Run the existing one-point diagnostic after the recorded mesh cleanup; verify solver completion and waveform/J consistency.
- [x] Establish independent solver ownership for five workers; never let workers change the same design concurrently. Ruling: use five separate projects and the supported nonblocking Analyze API in one desktop, avoiding shared design mutations and unnecessary GUI sessions/dependencies. Native profiles prove overlapping execution.
- [x] Run five distinct pilot designs with bounded FEA budget, retaining failures and actual solver-call counts. Read geometry areas again after each parameter change.
- [x] Consolidate summary and waveform data into one workbook, verify values and source preservation, and report whether broader DOE is ready.

## Review focus

Check missing open project, unsaved source differences, absent automatic mesh operation, COM/SI display units, and accidentally shared solver sessions. Do not treat mesh errors as physical infeasibility or convert failed objectives to zero. Any repeated baseline failure is diagnosed before launching five workers.

## User correction: Direct NSGA-II first

The next study is Direct NSGA-II with real FEA, used as an independent Pareto baseline before any ANN campaign, following the Motor-CAD order. The user runs it manually from code/run_vernier_nsga2.py. Default population 40, generations 20, maximum 800 cumulative solver calls, five reused workers, seed 17. Geometry checks occur inside candidate evaluation; no standalone ANN initial-DOE campaign is started. Existing DOE-only entry/controller names are replaced, not retained as extra runnable files. Offline checks cover objective signs, failure exclusion, FEA-only Pareto and exact pending-population resume. No real FEA is authorized for this code-preparation turn.
