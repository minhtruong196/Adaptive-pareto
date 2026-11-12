# Motor-CAD Direct Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver a runnable, conservative Motor-CAD LHS/NSGA-II CLI with persistent real evaluations and offline analysis.

**Architecture:** One Python module with grid utilities, a SQLite ledger, a Motor-CAD adapter, and CLI orchestration. Tests exercise persistence and optimizer contracts with an external-solver double; actual Motor-CAD checks remain separate artifacts.

**Tech Stack:** Python 3.9.7 (project .venv), PyMotorCAD 0.7.4, SciPy, NumPy, pymoo 0.6.x, Matplotlib, SQLite, unittest.

**Spec:** ../specs/2026-11-12-motorcad-direct-design.md

## Global Constraints

- Exactly seven grid variables; preserve original model and physical inputs.
- check/doe/nsga2/analyze; no implicit FEA; no ANN or surrogate.
- Maximize real Average Torque, PF, Efficiency; no fabricated CSV objectives.
- Cache only within fingerprint; budget counts calls to EMag, including failed/interrupted calls.
- User explicitly authorized implementation without further process approval on 12/11/2026.

## Review Focus

- Crash between solver start and final persistence must consume budget and never yield a feasible output.
- Rounded duplicates must not consume solver budget twice.
- Missing/mismatched/stale output must never enter Pareto.
- Resume after a partial generation must preserve RNG/population and reuse completed calls.
- Model/config/version changes must reject resume and mixed dataset analysis.

### Task 1: Discrete space and durable evaluations

Files: motorcad_optimize.py; test_motorcad_optimize.py.
Interfaces: encode/decode grid indices; nondominated(rows); Store(path, fingerprint); Evaluator(store, solver, budget).

- [x] Write failing unittest cases for grid boundary rounding, dominated/invalid rows, cache reuse, failure output clearing, crash budget and fingerprint mismatch.
- [x] Run `python -m unittest -v`; confirmed seven missing-implementation failures.
- [x] Implement utilities, SQLite evaluations/requests and evaluator with started-before-solve accounting.
- [x] Run unittest suite; seven Task 1 cases pass in .venv.

### Task 2: Motor-CAD adapter and check

Files: same implementation/test files; motorcad_config.json.
Interfaces: MotorCADSolver(config, workspace).prepare(indices), solve(), check(); configuration requires evidence-backed objective mappings.

- [x] Write adapter tests for immutable inputs, changed readback and J drift; confirmed missing-adapter failures.
- [x] Implement own-instance load-copy, verified names, get/set/readback, geometry no-edit check, mandatory finite output validation, optional output reads, script-auto-run guard.
- [x] Resolve automation names using installed executable's exact-name resource descriptions and direct API reads; evidence saved.
- [x] Run tests and check without FEA; report ready, original hash unchanged.

### Task 3: LHS, NSGA-II, resume and analysis

Files: same implementation/test files; requirements.txt; README.md.
Interfaces: run_doe; run_nsga2 via pymoo ask/tell; analyze_csv; main(argv=None).

- [x] Write failing tests for LHS determinism/uniqueness, optimizer cache/budget, resumed population and offline CSV filtering.
- [x] Implement saved DoE plan, atomic pending-generation checkpoint, NSGA-II integer repair, strict solve budget, CSV/summary export and pairwise/3D plots.
- [x] Install dependencies into workspace-local environment/target; bundled Motor-CAD Python unchanged.
- [x] Run full unittest suite and CLI help/analyze; lazy Motor-CAD import, analyze succeeds offline.
- [x] Run exactly one actual design after check passed: torque 8.70066939994197 Nm, PF 0.989817602426816, motor efficiency 84.5216846555276%, independent J 7.000000000000005 A/mm2.
- [x] Document exact commands, output definitions, retry/resume semantics and limitations.

### Task 4: Final review and verification

- [x] Independent whole-program review completed by fresh reviewer.
- [x] Address three material findings with four RED-to-GREEN regression tests; 18/18 suite passed.
- [x] Verify original .mot/.bak/reference script hashes unchanged; remaining live-validation limits documented in README and inspection/VALIDATION.md.

## Execution ledger

- Ruling: No git repository exists, so implement in the supplied workspace; no worktree, commits, or git-only bookkeeping. This preserves the user's file locations.
- Ruling: User opted out of further approval gates; implement inline and use one final reviewer as required by executing-plans.
- Task 1 complete: 7/7 unittest cases passed; .venv contains PyMotorCAD 0.7.4 and pymoo 0.6.1.5.
- Ruling: Bundled Python has no venv module; use project-local Python 3.9 venv with installed host scientific packages, without changing bundled Python. README will specify the tested interpreter.
- Task 2 complete: API confirmed all mapped output names; get/set/readback and 25 fixed inputs passed; geometry validity checked with RPC success 1, no auto-repair.
- Task 3 complete: 14/14 offline tests passed, pip check clean, analysis generated genuine one-point pairwise/3D plots. Upstream pymoo emits a NumPy row_stack deprecation warning; tests pass.
- Ruling: Current values may update only during solver execution; preserve native current-density mode and verify actual J after every FEA from calculated RMS current and actual copper area, restricted to the exact original round-wire star model. This avoids silently assuming target J equals actual J.
- Ruling: Keep baseline loss flags false and explicitly qualify efficiency as the original loss model. No additional loss/thermal FEA is enabled; scientific interpretation remains limited by those settings.
- Final review fixed: geometry RPC failures remain manually retryable (`test_geometry_transport_failure_can_be_retried_without_spending_fea_first`); missing/mixed provenance and cross-run ID collisions are rejected or disambiguated (`test_analysis_requires_provenance_and_checks_adjacent_manifest`, `test_analysis_keeps_independent_runs_with_same_local_evaluation_id`); empty analysis removes obsolete plots (`test_empty_analysis_removes_previously_generated_plots`). All four were observed RED, then GREEN; full suite 18/18.
- Final review scope: independent reviewer did not certify native solver freshness, loss completeness, or convergence. Native one-design run verifies API/result/J flow; loss completeness and numerical convergence remain research validation limits, explicitly documented. No broad FEA validation is claimed.
- Final verification: 18/18 tests passed after fixes; read-only/live check rerun reused cached evaluation 1; total solver attempts remains 1, cache hits 1. Offline analyze regenerated CSV/PNG correctly; pip check reports no broken requirements. No Git integration operations apply because the supplied workspace has no repository.
