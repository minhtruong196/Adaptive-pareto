# One-hour NSGA-II settings

User preference: one useful optimization run, about one hour on one license, rather than many small test runs.

Selected engineering compromise: population 24, 7 generations, cap 168 EMag calls, seed 17. Approximate runtime from the only measured design: 168 × 20.343 s = 56.96 min; the 100 mm model and other candidates can differ. This is an estimate, not a convergence guarantee.

Implemented --max-minutes 55 for the dedicated runner defaults. A monotonic deadline counts startup during this invocation and is checked before preparation and again immediately before starting FEA. Cache retrieval is allowed after the deadline; an active solver call is allowed to finish. No hard kill, extra tests or automatic reruns. Checkpoint records pending generation and stop_reason=wall_time.

Verification: two deadline regressions were observed failing before implementation, then passed. Added full NSGA time-stop/resume integration test. Full suite 25/25 passed. Read-only independent reviewer found no material issues; no native applications/FEA were launched for this change.

Existing original model and physical settings are unchanged from the approved 100 mm copy-only policy. No real FEA results for the 100 mm configuration are claimed.
