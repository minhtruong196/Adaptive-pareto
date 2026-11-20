"""Direct Vernier NSGA-II: same physical domain/FEA as ANN and adaptive.

VS Code Run: 800 unique slots, population40, seed17, five workers. Failed slots
are consumed without refill. Export the exact first300 archive mid-generation.
Use --dry-run for synthetic orchestration without COM/Ansys or solver calls.
"""
import argparse
from collections import Counter
from contextlib import closing
import csv
import hashlib
import json
import random
import sqlite3
import sys
from pathlib import Path

import dill
import numpy as np
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import Problem
from pymoo.core.repair import Repair
from pymoo.indicators.hv import HV
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM

from vernier_model import (BOUNDS, source_variables, model_identity, margins,
                           atomic_json, K_FILL, CONSTRAINTS_VERSION, MESH_POLICY_VERSION)
from vernier_optimize import (Ledger, run as run_fea, export_results,
                              pareto_rows, run_lock)
from vernier_protocol import OBJECTIVES, point_key, sample_points

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT/'inspection'/'vernier_pilot_20261113'/'work'/'test_point'/'base_half.aedt'
HV_SCALE = [10., 1., 100.]


def settings(run_dir=None, budget=800, dry_run=False):
    suffix = '_dry_run' if dry_run else ''
    return dict(source=SOURCE,
                run_dir=Path(run_dir) if run_dir else PROJECT_ROOT/'runs'/f'vernier_nsga2_narrow_{budget}_v1{suffix}',
                workers=5, worker_pool_dir=PROJECT_ROOT/'runs'/'vernier_narrow_workers_v1',
                worker_prefix='vernier_narrow', design='VM_6_28', timeout_minutes=30,
                mode='fea', samples=budget, max_fea_calls=budget, seed=17,
                bounds=dict(BOUNDS), retry_failed=False, dry_run=dry_run, milestones=[300])


class FeasibleRepair(Repair):
    """Keep feasible offspring; rejection-resample invalid geometry before FEA.

    This changes proposals only, never refills failed physical evaluations.
    """
    def _do(self, problem, X, **kwargs):
        X = np.round(np.clip(X, problem.xl, problem.xu), 8)
        for i in range(len(X)):
            for _ in range(10000):
                if min(margins(dict(zip(problem.names, X[i])), problem.base).values()) > 1e-8:
                    break
                X[i] = np.round(np.random.uniform(problem.xl, problem.xu), 8)
            else:
                raise ValueError('Cannot generate feasible offspring; no FEA launched')
        return X


class Vernier13Problem(Problem):
    def __init__(self, base_variables, bounds_dict):
        self.base, self.names = base_variables, list(bounds_dict)
        super().__init__(n_var=len(self.names), n_obj=3, n_ieq_constr=1,
                         xl=np.array([v[0] for v in bounds_dict.values()]),
                         xu=np.array([v[1] for v in bounds_dict.values()]))

    def _evaluate(self, X, out, *args, **kwargs):
        raise RuntimeError('Use the persistent FEA evaluator through ask/tell')


def objective_values(row):
    if row.get('status') != 'ok':
        return None
    values = [row.get(k, row.get('raw_metrics', {}).get(k)) for k in OBJECTIVES]
    if all(v is not None and np.isfinite(v) for v in values):
        return tuple(float(v) for v in values)
    return None


def save_checkpoint(path, state):
    tmp = path.with_suffix('.tmp')
    with tmp.open('wb') as handle:
        dill.dump(dict(state, numpy_rng=np.random.get_state(), python_rng=random.getstate()), handle)
    tmp.replace(path)


class VernierStore:
    def __init__(self, folder, config):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.source, self.config = Path(config['source']).resolve(), config
        self.spec = dict(protocol='vernier_direct_nsga2_v1', model_identity=model_identity(self.source),
                         n=config['samples'], seed=config['seed'], bounds=config['bounds'],
                         design=config['design'], metrics_version=1, kfill=K_FILL,
                         constraints_version=CONSTRAINTS_VERSION, mesh_policy_version=MESH_POLICY_VERSION,
                         synthetic=config['dry_run'], hv_scale=HV_SCALE)
        self.fingerprint = hashlib.sha256(json.dumps(self.spec, sort_keys=True).encode()).hexdigest()
        path = self.folder/'plan.json'
        self.points = []
        if path.exists():
            plan = json.loads(path.read_text(encoding='utf-8'))
            if plan['fingerprint'] != self.fingerprint or plan['settings'] != json.loads(json.dumps(self.spec)):
                raise ValueError('Run fingerprint mismatch; restore settings or select another folder')
            self.points = plan['points']

    def plan(self):
        return dict(fingerprint=self.fingerprint, settings=self.spec, points=self.points,
                    sampling='Filtered LHS initial; SBX/PM with rejection repair; no failed-slot refill')

    def _db(self):
        return sqlite3.connect((self.folder/'evaluations.sqlite').resolve().as_uri()+'?mode=ro', uri=True)

    def attempts(self):
        if not (self.folder/'evaluations.sqlite').exists():
            return 0
        with closing(self._db()) as db:
            return int(db.execute('SELECT COALESCE(SUM(fea_started),0) FROM attempts').fetchone()[0])

    def rows(self):
        if not (self.folder/'evaluations.sqlite').exists():
            return {}
        with closing(self._db()) as db:
            return {i: dict(json.loads(data or '{}'), point_id=i, point=json.loads(raw), status=status)
                    for i, raw, status, data in db.execute('SELECT * FROM points ORDER BY id')}

    def report(self, destination=None, limit=None):
        destination = self.folder if destination is None else Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        rows = [r for i, r in self.rows().items() if limit is None or i <= limit]
        valid = [dict(r, **dict(zip(OBJECTIVES, objective_values(r)))) for r in rows if objective_values(r)]
        front = pareto_rows(valid)
        calls = 0
        if (self.folder/'evaluations.sqlite').exists():
            with closing(self._db()) as db:
                calls = int(db.execute('SELECT COALESCE(SUM(fea_started),0) FROM attempts WHERE point_id<=?',
                                       (limit if limit is not None else len(self.points),)).fetchone()[0])
        y = np.array([[r[k] for k in OBJECTIVES] for r in valid])
        volume = float(HV(ref_point=np.zeros(3))(-y/np.array(HV_SCALE))) if len(y) else 0.
        result = dict(method='nsga2', synthetic=self.config['dry_run'], evaluation_slots=len(rows),
                      actual_solver_calls=calls, valid_designs=len(valid), pareto_designs=len(front),
                      statuses=dict(Counter(r['status'] for r in rows)),
                      hv=dict(scale=dict(zip(OBJECTIVES, HV_SCALE)), reference=[0, 0, 0], archive=volume),
                      best_objectives={k: max((r[k] for r in valid), default=None) for k in OBJECTIVES},
                      note='SYNTHETIC; no physical FEA evidence.' if self.config['dry_run'] else
                           'Actual valid FEA archive only. Failed slots consumed; no retry/refill.')
        atomic_json(destination/'pareto.json', dict(synthetic=self.config['dry_run'], pareto=front))
        fields = ['point_id', 'status', *self.config['bounds'], *OBJECTIVES, 'error']
        for filename, part in [('results.csv', rows), ('pareto.csv', front)]:
            if filename == 'results.csv' and destination == self.folder:
                continue  # Preserve the shared adapter's full current/area/timing columns.
            tmp = destination/(filename+'.tmp')
            with tmp.open('w', newline='', encoding='utf-8-sig') as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(dict(r, **r['point']) for r in part)
            tmp.replace(destination/filename)
        self.compare(destination, result)
        # Written last: its existence marks a complete resumable milestone export.
        atomic_json(destination/'performance.json', result)
        return result

    def compare(self, destination, result):
        """Read-only comparison with compatible completed physical campaigns."""
        if self.config['dry_run']:
            return
        comparison = [dict(method='nsga2', **{k: result[k] for k in
                          ['evaluation_slots', 'actual_solver_calls', 'valid_designs']},
                           archive_hv=result['hv']['archive'])]
        for method in ['static', 'adaptive']:
            folder = PROJECT_ROOT/'runs'/f'vernier_{method}_narrow_300_txt_v3'
            summary_path, plan_path = folder/'campaign_summary.json', folder/'plan.json'
            if not summary_path.exists() or not plan_path.exists():
                continue
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
            spec = json.loads(plan_path.read_text(encoding='utf-8'))['settings']
            spec = dict(spec, model_identity=spec.get('model_identity', spec.get('source_identity')))
            keys = ['model_identity', 'bounds', 'kfill', 'constraints_version', 'mesh_policy_version']
            own = json.loads(json.dumps(self.spec))
            if (summary.get('synthetic') or spec.get('design') != own['design']
                    or any(spec.get(k) != own[k] for k in keys)
                    or summary['hv']['scale'] != result['hv']['scale']
                    or summary['hv']['reference'] != result['hv']['reference']):
                continue
            comparison.append(dict(method='ann' if method == 'static' else method,
                                   evaluation_slots=summary['evaluation_slots'],
                                   actual_solver_calls=summary['actual_solver_calls'],
                                   valid_designs=sum(summary['roles_valid'].values()),
                                   archive_hv=summary['hv']['archive']))
        atomic_json(destination/'comparison.json', dict(rows=comparison,
                    note='Compare archive HV at equal actual solver calls. NSGA-II800 vs baselines300 is a budget tradeoff.'))

    def export(self):
        if (self.folder/'evaluations.sqlite').exists():
            self.report()

    def export_milestones(self):
        rows = self.rows()
        for count in self.config['milestones']:
            dest = self.folder/'checkpoints'/f'{count:03d}'
            if ((dest/'performance.json').exists() or count > len(rows)
                    or any(rows[i]['status'] in ['pending', 'preparing', 'solving'] for i in range(1, count+1))):
                continue
            self.report(dest, limit=count)
            print(f'CHECKPOINT {count}: {dest}', flush=True)


class VernierEvaluator:
    def __init__(self, config, store, evaluate_batch=None):
        self.settings, self.store = config, store
        self.budget, self.evaluate_batch = config['max_fea_calls'], evaluate_batch

    def _run(self):
        if not self.settings['dry_run']:
            return run_fea(dict(self.settings, samples=len(self.store.points)), plan_override=self.store.plan())
        atomic_json(self.store.folder/'plan.json', self.store.plan())
        from vernier_campaign import synthetic_values
        ledger = Ledger(self.store.folder, self.store.fingerprint, self.store.points)
        try:
            pending = ledger.pending()
            if pending:
                points = [self.store.points[i-1] for i in pending]
                values = (self.evaluate_batch(points) if self.evaluate_batch else
                          [dict(status='ok', **dict(zip(OBJECTIVES, y.tolist())))
                           for y in synthetic_values(points, self.settings['bounds'])])
                if len(values) != len(pending):
                    raise ValueError('Synthetic evaluator size mismatch')
                for i, row in zip(pending, values):
                    aid = ledger.start(i, 0, dict(synthetic=True))
                    ledger.finish(i, row['status'], dict(row, synthetic=True), aid)
            export_results(ledger)
        finally:
            ledger.close()
        return dict(stopped=False)

    def evaluate_many(self, designs, context, generation):
        self.store.export_milestones()  # Recover a report interrupted just after FEA.
        keys = {point_key(p): i for i, p in enumerate(self.store.points, 1)}
        ids = []
        def flush():
            outcome = self._run()
            if outcome.get('stopped'):
                raise KeyboardInterrupt
            self.store.export_milestones()
        for design in designs:
            key = point_key(design)
            if key not in keys:
                if len(self.store.points) >= self.budget:
                    raise ValueError('Generation exceeds remaining evaluation slots')
                self.store.points.append(design)
                keys[key] = len(self.store.points)
                if len(self.store.points) in self.settings['milestones']:
                    flush()
            ids.append(keys[key])
        flush()
        rows = self.store.rows()
        result = [rows[i] for i in ids]
        if any(r['status'] in ['pending', 'preparing', 'solving'] for r in result):
            raise RuntimeError('Generation contains unfinished FEA points')
        return result


def run_nsga2(store, evaluator, population=40, generations=None, seed=17, resume=False):
    if population < 4 or (generations is not None and generations < 1):
        raise ValueError('population >=4 and generations >=1 required')
    path = store.folder/'nsga2_checkpoint.dill'
    config = dict(population=population, generations=generations, seed=seed, fingerprint=store.fingerprint)
    if resume:
        if not path.exists():
            raise ValueError('No NSGA-II checkpoint to resume')
        with path.open('rb') as handle:  # Load only your own runner checkpoints.
            state = dill.load(handle)
        if state['settings'] != config:
            raise ValueError('NSGA-II checkpoint settings/fingerprint mismatch')
        np.random.set_state(state['numpy_rng'])
        random.setstate(state['python_rng'])
    else:
        if path.exists() or store.points or store.rows():
            raise ValueError('Run already contains evaluations; use --resume or a new folder')
        problem = Vernier13Problem(source_variables(store.source), store.config['bounds'])
        initial = sample_points(min(population, evaluator.budget), store.config['bounds'], problem.base, seed)
        algorithm = NSGA2(pop_size=population, sampling=np.array([[p[k] for k in problem.names] for p in initial]),
                          crossover=SBX(prob=.9, eta=15), mutation=PM(eta=20),
                          repair=FeasibleRepair(), eliminate_duplicates=True)
        # Default fills unique-slot budget; --generations is an optional early cap.
        algorithm.setup(problem, termination=('n_gen', generations or max(20, evaluator.budget*10)),
                        seed=seed, verbose=False)
        state = dict(settings=config, algorithm=algorithm, pending=None, completed_generations=0)
        save_checkpoint(path, state)
    algorithm, reason = state['algorithm'], 'generations'
    try:
        while state['pending'] is not None or algorithm.has_next():
            if state['pending'] is None:
                remaining = evaluator.budget-len(store.points)
                if remaining <= 0:
                    reason = 'budget'
                    break
                state['pending'] = algorithm.ask()
                if state['pending'] is not None:
                    state['pending'] = state['pending'][:remaining]
                save_checkpoint(path, state)
            pending = state['pending']
            if pending is None or not len(pending):
                reason = 'no_offspring'
                break
            names = algorithm.problem.names
            designs = [dict(zip(names, map(float, x))) for x in np.round(pending.get('X'), 8)]
            results = evaluator.evaluate_many(designs, 'nsga2', algorithm.n_gen)
            pending.set('F', np.array([[-v for v in objective_values(r)] if objective_values(r) else [0., 0., 0.]
                                       for r in results]))
            pending.set('G', np.array([[0.] if objective_values(r) else [1.] for r in results]))
            for individual in pending:
                individual.evaluated.update(['F', 'G'])
            algorithm.evaluator.n_eval += len(pending)
            algorithm.tell(infills=pending)
            state['pending'] = None
            state['completed_generations'] += 1
            save_checkpoint(path, state)
            store.export()
            print(f'Generation {state["completed_generations"]}: slots {len(store.points)}/{evaluator.budget}; '
                  f'actual FEA calls {store.attempts()}', flush=True)
        if len(store.points) >= evaluator.budget:
            reason = 'budget'
    finally:
        save_checkpoint(path, state)
        store.export()
    result = dict(stop_reason=reason, completed_generations=state['completed_generations'],
                  evaluation_slots=len(store.points), solver_attempts=store.attempts(), synthetic=store.config['dry_run'])
    atomic_json(store.folder/'nsga2_summary.json', result)
    return result


def main(argv=None, *, config=None, population=40, generations=None, resume=False, evaluate_batch=None):
    if config is None:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--run-dir', type=Path)
        parser.add_argument('--workers', type=int, default=5)
        parser.add_argument('--population', type=int, default=40)
        parser.add_argument('--generations', type=int, help='Optional early generation cap; default fills budget')
        parser.add_argument('--budget', type=int, default=800, help='Unique slots; failed slots are not refilled')
        parser.add_argument('--seed', type=int, default=17)
        parser.add_argument('--resume', action='store_true')
        parser.add_argument('--dry-run', action='store_true', help='Synthetic only; never launch Ansys')
        args = parser.parse_args(argv)
        config = settings(args.run_dir, args.budget, args.dry_run)
        config.update(workers=args.workers, seed=args.seed)
        population, generations, resume = args.population, args.generations, args.resume
    if not 1 <= config['workers'] <= 5 or config['max_fea_calls'] < 1:
        raise ValueError('Use 1..5 workers and a positive budget')
    if config['samples'] != config['max_fea_calls']:
        raise ValueError('samples and max_fea_calls must use the same fixed slot budget')
    if evaluate_batch is not None and not config['dry_run']:
        raise ValueError('Custom evaluator is available only for synthetic dry-run')
    folder = Path(config['run_dir'])
    print(f'Vernier direct NSGA-II: {config["samples"]} slots, population {population}, seed {config["seed"]}; '
          f'{"SYNTHETIC (no Ansys)" if config["dry_run"] else str(config["workers"])+" FEA workers"}\nOutput: {folder}', flush=True)
    with run_lock(folder, '.nsga2.lock'):
        store = VernierStore(folder, config)
        return run_nsga2(store, VernierEvaluator(config, store, evaluate_batch),
                         population, generations, config['seed'], resume)


if __name__ == '__main__':
    try:
        project_python = PROJECT_ROOT/'.venv'/'Scripts'/'python.exe'
        if project_python.is_file() and Path(sys.executable).resolve() != project_python.resolve():
            import subprocess
            sys.exit(subprocess.call([str(project_python), str(Path(__file__).resolve()), *sys.argv[1:]]))
        print(json.dumps(main(), indent=2))
    except KeyboardInterrupt:
        print('Interrupted; resume with --resume and the same settings/run folder.', file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(2)
