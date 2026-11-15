"""One Run entry: geometry-only DOE first, then Direct NSGA-II + real FEA.

First obtain an independent FEA Pareto baseline, as for Motor-CAD.
This entry does not train ANN. Select the project's .venv interpreter.
"""
from pathlib import Path
from vernier_model import BOUNDS,K_FILL

ROOT=Path(__file__).resolve().parents[1]

# ---------------- EDIT HERE, SAVE, THEN PRESS RUN ----------------
MODE='nsga2'               # Direct NSGA-II; up to 800 cumulative FEA calls.
FEA_CHECK_SAMPLES=10
FEA_CHECK_RUN_DIR=ROOT/'runs'/'vernier_half_fea_check_kfill03'
DIAGNOSTIC_SOURCE_DIR=ROOT/'runs'/'nsga2_vernier_half_kfill03' # Reproduce this campaign's points.
GEOMETRY_SAMPLES=100         # Geometry screening in the agreed bounds; no FEA.
GEOMETRY_RUN_DIR=ROOT/'runs'/'vernier_half_geometry_kfill03'  # Half-model geometry check.
POPULATION=40
GENERATIONS=20
MAX_FEA_CALLS=800          # Hard cumulative budget, including failed/interrupted calls.
N_WORKERS=5               # Reuse five isolated half_worker models.
SEED=17
TIMEOUT_MINUTES=30        # Per solver job; not a total campaign time limit.
RUN_DIR=ROOT/'runs'/'nsga2_vernier_half_kfill03' # Separate archive for the half model.
SOURCE_MODEL=ROOT/'inspection'/'vernier_pilot_20261113'/'work'/'test_point'/'base_half.aedt'
WORKER_POOL_DIR=ROOT/'runs'/'vernier_half_workers_v5' # Shared by all three modes; old workers untouched.
VARIABLE_BOUNDS=dict(BOUNDS)        # 13 continuous Vernier variables.
# -----------------------------------------------------------------


def main():
    from vernier_optimize import run,run_direct
    if MODE=='fea_check':
        import json,hashlib
        from vernier_model import make_plan,source_variables,digest,CONSTRAINTS_VERSION,MESH_POLICY_VERSION
        old=DIAGNOSTIC_SOURCE_DIR/'plan.json'
        if old.exists():
            previous=json.loads(old.read_text(encoding='utf-8'))
            if previous['settings']['source_sha256']!=digest(SOURCE_MODEL):
                raise ValueError('Diagnostic source model differs from failed campaign')
            points=previous['points'][:FEA_CHECK_SAMPLES]
            if len(points)!=FEA_CHECK_SAMPLES:raise ValueError('Not enough saved diagnostic points')
        else:points=make_plan(FEA_CHECK_SAMPLES,SEED,VARIABLE_BOUNDS,source_variables(SOURCE_MODEL))
        spec=dict(source_sha256=digest(SOURCE_MODEL),kfill=K_FILL,points=points,constraints_version=CONSTRAINTS_VERSION,
                  mesh_policy_version=MESH_POLICY_VERSION,purpose='reproduce FEA failures')
        fp=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
        return run(dict(samples=len(points),workers=N_WORKERS,seed=SEED,mode='fea',
          retry_failed=True,max_fea_calls=FEA_CHECK_SAMPLES,timeout_minutes=TIMEOUT_MINUTES,
          run_dir=FEA_CHECK_RUN_DIR,source=SOURCE_MODEL,design='VM_6_28',bounds=VARIABLE_BOUNDS,
          legacy_workers=WORKER_POOL_DIR/'workers.json',
          worker_pool_dir=WORKER_POOL_DIR,worker_prefix='half_worker_v5'),
          plan_override=dict(fingerprint=fp,settings=spec,points=points))
    if MODE=='geometry':
        return run(dict(samples=GEOMETRY_SAMPLES,workers=N_WORKERS,seed=SEED,
          mode='geometry',retry_failed=False,timeout_minutes=TIMEOUT_MINUTES,
          run_dir=GEOMETRY_RUN_DIR,source=SOURCE_MODEL,design='VM_6_28',bounds=VARIABLE_BOUNDS,
          legacy_workers=WORKER_POOL_DIR/'workers.json',
          worker_pool_dir=WORKER_POOL_DIR,worker_prefix='half_worker_v5'))
    if MODE!='nsga2':raise ValueError("MODE must be 'geometry', 'fea_check' or 'nsga2'")
    return run_direct(dict(population=POPULATION,generations=GENERATIONS,
      max_fea_calls=MAX_FEA_CALLS,workers=N_WORKERS,seed=SEED,
      timeout_minutes=TIMEOUT_MINUTES,run_dir=RUN_DIR,source=SOURCE_MODEL,
      design='VM_6_28',bounds=VARIABLE_BOUNDS,
      legacy_workers=WORKER_POOL_DIR/'workers.json',
      worker_pool_dir=WORKER_POOL_DIR,worker_prefix='half_worker_v5'))


if __name__=='__main__':
    try:print(main())
    except ImportError as exc:
        raise SystemExit(f'Missing dependency: {exc}. Install code/requirements.txt into the selected .venv.')
    except KeyboardInterrupt:
        print('Stopped. Run this same file again to resume from its checkpoint.')
