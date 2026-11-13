# Parallel Motor-CAD implementation plan

**Goal:** Repair installation paths, remove the default time cap, and evaluate NSGA-II generations across a user-selected number of private Motor-CAD sessions.

**Design:** Keep pymoo ask/tell and SQLite/checkpoints on the main thread. A thread pool prepares and solves designs on independent solver instances and work directories. The coordinator reserves each FEA attempt before dispatch, preserves input order, drains active work before stopping, and resumes partial generations through the existing cache. Open sessions sequentially to avoid launch races. Existing interactive Motor-CAD sessions must remain untouched.

**Defaults (implementation choice):** 60 individuals, 30 generations, budget 1800, seed 17, no wall-time limit. Prompt for positive worker count (blank = 5) only on no-argument Run; CLI uses --workers. Keep optional --max-minutes.

**Model migration:** User confirmed a newly created model with unchanged parameters. Store its approved SHA256 in config rather than replacing the winding-scope checks or silently trusting any model. Validate actual J after every successful FEA.

- [x] Add failing offline tests for concurrent overlap, ordering/cache, strict budget/resume, solver failures, deadlines and input validation.
- [x] Add coordinator and per-worker startup checks/cleanup; preserve original single-session mode for check/DoE.
- [x] Update runner, configs, launch profile and README.
- [x] Run offline suite and a small real parallel smoke campaign if the environment permits.

**Verification:** 34 offline tests pass. Real `inspection/parallel_smoke_20261112` ran 5 private workers, population 5, one generation, budget 5: all 5 FEA successful, actual J approximately 7 A/mm², no remaining Motor-CAD processes. Original model hash unchanged. Review found an interrupt-during-commit issue, reproduced with real SIGINT in a test and fixed by deferring SIGINT across coordinator persistence while draining active work.
