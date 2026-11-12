# Dedicated NSGA-II runner and fixed lengths

User authorized immediate implementation: separate NSGA-II file; DoE and Motor-CAD checking are support tools; choose rounded fixed lengths; one license, sequential calls only. No new FEA campaign authorized.

- [x] Add failing regressions for fixed length overrides across model reloads and exclusion of concurrent Motor-CAD sessions.
- [x] Extract actual pymoo NSGA-II implementation into nsga2_motorcad.py with its own CLI, preserving cache/checkpoints and old CLI compatibility.
- [x] Create dedicated config: stator/rotor/magnet lengths 100 mm, outer stator diameter unchanged. Only these three physical values may be overridden, with readback guards and fingerprint changes.
- [x] Apply a cross-run Motor-CAD session lock; fail clearly if an existing instance holds the sole license. Do not attach to/overwrite the user's current model or open a second instance.
- [x] Use input/output check in the same optimizer session; do not require a separate DOE or smoke-FEA campaign as an optimization prerequisite. Preserve validation and independent J check on each actual evaluation.
- [x] Run offline suite and standalone help; no live Motor-CAD invocation in this change. Document that old 8.70 Nm result belongs to old lengths and cannot be reused.

Implementation choices: three lengths = 100 mm as authorized, operating/material/winding/loss settings retained. Single-license operation remains sequential even if more licenses become available; no automatic timed mode switch.

Final independent review: no import/reload/cache blockers. Fixed session cleanup on persistence failure with a failing regression then passing suite. Final suite: 22/22 tests pass; native FEA calls added in this update: 0. Original .mot/.bak/reference script hashes unchanged.
