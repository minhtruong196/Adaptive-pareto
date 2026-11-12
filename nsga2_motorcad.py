"""Dedicated direct NSGA-II optimizer. One Motor-CAD session, sequential evaluations."""
import random
import sys
from pathlib import Path
from motorcad_optimize import BudgetExhausted, TimeBudgetExhausted, LIMITS, feasible, objective_values, save_checkpoint

DEFAULT_RUN_SETTINGS = {'population': 24, 'generations': 7, 'budget': 168, 'seed': 17, 'max-minutes': 55}


def run_nsga2(store, evaluator, population, generations, seed, resume=False):
    import dill
    import numpy as np
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.core.problem import Problem
    from pymoo.operators.crossover.sbx import SBX
    from pymoo.operators.mutation.pm import PM
    from pymoo.operators.repair.rounding import RoundingRepair
    from pymoo.operators.sampling.rnd import IntegerRandomSampling
    if population < 4 or generations < 1:
        raise ValueError('population >= 4 and generations >= 1 required')
    path = store.folder / 'nsga2_checkpoint.dill'
    settings = dict(population=population, generations=generations, seed=seed,
                    fingerprint=store.get_meta('fingerprint'))
    if resume:
        if not path.exists(): raise ValueError('No NSGA-II checkpoint to resume')
        # Checkpoints are executable Python serialization: load only your own run files.
        with path.open('rb') as handle: state = dill.load(handle)
        if state['settings'] != settings: raise ValueError('NSGA-II checkpoint settings/fingerprint mismatch')
        np.random.set_state(state['numpy_rng'])
        random.setstate(state['python_rng'])
    else:
        if path.exists() or store.rows(): raise ValueError('Run already contains evaluations; use --resume or a new folder')
        problem = Problem(n_var=7, n_obj=3, n_ieq_constr=1, xl=np.zeros(7), xu=np.array(LIMITS), vtype=int)
        algorithm = NSGA2(pop_size=population, sampling=IntegerRandomSampling(),
                          crossover=SBX(prob=.9, eta=15, vtype=float, repair=RoundingRepair()),
                          mutation=PM(eta=20, vtype=float, repair=RoundingRepair()),
                          eliminate_duplicates=True)
        algorithm.setup(problem, termination=('n_gen', generations), seed=seed, verbose=False)
        state = dict(settings=settings, algorithm=algorithm, pending=None, completed_generations=0)
        save_checkpoint(path, state)
    algorithm = state['algorithm']
    reason = 'generations'
    try:
        while state['pending'] is not None or algorithm.has_next():
            if state['pending'] is None:
                state['pending'] = algorithm.ask()
                save_checkpoint(path, state)  # RNG + exact offspring before any solver call.
            pending = state['pending']
            if pending is None or len(pending) == 0:
                reason = 'no_offspring'
                break
            results = []
            for design in pending.get('X'):
                results.append(evaluator.evaluate(tuple(int(i) for i in design), 'nsga2', algorithm.n_gen))
            # Constraint violation, rather than invented simulation output, excludes failed designs.
            F = np.array([[-v for v in objective_values(row)] if feasible(row) else [0., 0., 0.]
                          for row in results])
            G = np.array([[0.] if feasible(row) else [1.] for row in results])
            pending.set('F', F)
            pending.set('G', G)
            for individual in pending: individual.evaluated.update(['F', 'G'])
            algorithm.evaluator.n_eval += len(pending)
            algorithm.tell(infills=pending)
            state['pending'] = None
            state['completed_generations'] += 1
            save_checkpoint(path, state)
            print(f'Generation {state["completed_generations"]}: solver calls {store.attempts()}/{evaluator.budget}', flush=True)
    except TimeBudgetExhausted:
        reason = 'wall_time'
    except BudgetExhausted:
        reason = 'budget'
    finally:
        # Pending generation is intentionally re-evaluated via the persistent cache after resume.
        save_checkpoint(path, state)
        store.export()
    return dict(stop_reason=reason, completed_generations=state['completed_generations'], solver_attempts=store.attempts())


def main(argv=None):
    from motorcad_optimize import main as shared_main
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        from datetime import datetime, timedelta, timezone
        from uuid import uuid4
        timestamp = datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d_%H%M%S')
        folder = Path(__file__).resolve().parent / 'runs' / f'nsga2_L100_{timestamp}_{uuid4().hex[:6]}'
        argv = ['--run-dir', str(folder)]
        print('Starting direct NSGA-II: population 24, up to 7 generations / 168 FEA calls.', flush=True)
        print('One Motor-CAD session; stop starting new FEA after 55 minutes.', flush=True)
        print(f'Results folder: {folder}', flush=True)
    defaults = [part for key, value in DEFAULT_RUN_SETTINGS.items() for part in ('--' + key, str(value))]
    return shared_main(['nsga2', '--config', str(Path(__file__).with_name('nsga2_config.json'))] + defaults + argv, standalone_nsga=True)


if __name__ == '__main__':
    try:
        # VS Code's Run button may still point to the system interpreter.
        # Forward once to the tested project environment, preserving the output console.
        project_python = Path(__file__).resolve().parent / '.venv' / 'Scripts' / 'python.exe'
        if project_python.is_file() and Path(sys.executable).resolve() != project_python.resolve():
            import subprocess
            sys.exit(subprocess.call([str(project_python), str(Path(__file__).resolve())] + sys.argv[1:]))
        sys.exit(main())
    except KeyboardInterrupt:
        print('Interrupted; use --resume with the same run folder.', file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(2)
