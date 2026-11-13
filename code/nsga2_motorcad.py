"""Direct NSGA-II optimizer with independent parallel Motor-CAD sessions."""
import random
import sys
from pathlib import Path
from motorcad_optimize import BudgetExhausted, TimeBudgetExhausted, LIMITS, feasible, objective_values, save_checkpoint
from motorcad_optimize import PROJECT_ROOT, CONFIG_DIR

DEFAULT_RUN_SETTINGS = {'population': 40, 'generations': 20, 'budget': 800, 'seed': 17}


def prompt_workers():
    while True:
        try:
            value = input('Muon chay bao nhieu Motor-CAD song song? [5]: ').strip()
            workers = int(value) if value else 5
            if workers >= 1:
                return workers
        except ValueError:
            pass
        except EOFError as exc:
            raise ValueError('Run in a terminal to enter workers, or pass --workers N --run-dir PATH') from exc
        print('Vui long nhap so nguyen duong (1, 2, 3, ...).', flush=True)


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
            designs = [tuple(int(i) for i in design) for design in pending.get('X')]
            if hasattr(evaluator, 'evaluate_many'):
                results = evaluator.evaluate_many(designs, 'nsga2', algorithm.n_gen)
            else:
                results = [evaluator.evaluate(design, 'nsga2', algorithm.n_gen) for design in designs]
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
        workers = prompt_workers()
        timestamp = datetime.now(timezone(timedelta(hours=7))).strftime('%Y%m%d_%H%M%S')
        folder = PROJECT_ROOT / 'runs' / f'nsga2_L100_{timestamp}_{uuid4().hex[:6]}'
        argv = ['--run-dir', str(folder), '--workers', str(workers)]
        print('Starting direct NSGA-II: population 40, up to 20 generations / 800 FEA calls.', flush=True)
        print(f'{workers} private Motor-CAD sessions; no wall-time limit.', flush=True)
        print(f'Results folder: {folder}', flush=True)
    defaults = [part for key, value in DEFAULT_RUN_SETTINGS.items() for part in ('--' + key, str(value))]
    return shared_main(['nsga2', '--config', str(CONFIG_DIR / 'nsga2_config.json')] + defaults + argv, standalone_nsga=True)


if __name__ == '__main__':
    try:
        # VS Code's Run button may still point to the system interpreter.
        # Forward once to the tested project environment, preserving the output console.
        project_python = PROJECT_ROOT / '.venv' / 'Scripts' / 'python.exe'
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
