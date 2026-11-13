"""Direct Motor-CAD DoE / NSGA-II. No simulation is run on import or without a subcommand."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / 'config'

VARIABLES = (
    ('Ratio_Bore', .5, .8, .0001),
    ('Ratio_SlotDepth_ParallelTooth', .5, .8, .0001),
    ('Ratio_ToothWidth', .3, .65, .0001),
    ('Ratio_ShaftD', .5, .8, .0001),
    ('Ratio_MagnetArc', .7, .9, .05),
    ('Magnet_Thickness', 3., 5., .5),
    ('Slot_Corner_Radius', 0., 2., .5),
)
NAMES = [v[0] for v in VARIABLES]
LIMITS = (3000, 3000, 3500, 3000, 4, 4, 4)
OBJECTIVES = ('average_torque_nm', 'power_factor', 'efficiency_pct')
SCHEMA = 1


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def encode(values):
    if len(values) != 7:
        raise ValueError('Expected exactly seven design values')
    result = []
    for value, (_, lower, upper, step), limit in zip(values, VARIABLES, LIMITS):
        if not math.isfinite(float(value)):
            raise ValueError('Design contains NaN/Inf')
        scaled = (Decimal(str(value)) - Decimal(str(lower))) / Decimal(str(step))
        result.append(max(0, min(limit, int(scaled.quantize(Decimal('1'), rounding=ROUND_HALF_UP)))))
    return tuple(result)


def decode(indices):
    if len(indices) != 7:
        raise ValueError('Expected exactly seven grid indices')
    result = []
    for index, (_, lower, upper, step), limit in zip(indices, VARIABLES, LIMITS):
        if int(index) != index or not 0 <= index <= limit:
            raise ValueError('Grid index outside bounds')
        result.append(float(Decimal(str(lower)) + int(index) * Decimal(str(step))))
    return result


def lhs_designs(count, seed):
    import numpy as np
    from scipy.stats import qmc
    if count < 1:
        raise ValueError('DoE sample count must be positive')
    sampler = qmc.LatinHypercube(d=7, seed=seed)
    unique = {}
    # Equal-width cells in the discrete domain; retain only unique rounded designs.
    while len(unique) < count:
        for point in sampler.random(count - len(unique)):
            key = tuple(np.minimum(np.floor(point * (np.array(LIMITS) + 1)).astype(int), LIMITS))
            unique.setdefault(tuple(int(i) for i in key), None)
    return list(unique)


def objective_values(row):
    values = [float(row[k]) for k in OBJECTIVES]
    if not all(math.isfinite(v) for v in values):
        raise ValueError('Non-finite objective')
    if not -1 <= values[1] <= 1 or not 0 <= values[2] <= 100:
        raise ValueError('PF or efficiency outside its physical range')
    return values


def feasible(row):
    try:
        return row.get('status') == 'ok' and bool(objective_values(row))
    except (KeyError, TypeError, ValueError):
        return False


def nondominated(rows):
    valid = [row for row in rows if feasible(row)]
    points = [objective_values(row) for row in valid]
    return [row for i, row in enumerate(valid)
            if not any(all(a >= b for a, b in zip(other, points[i])) and
                       any(a > b for a, b in zip(other, points[i]))
                       for j, other in enumerate(points) if j != i)]


class BudgetExhausted(Exception):
    pass


class TimeBudgetExhausted(BudgetExhausted):
    pass


class DesignRejected(Exception):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status


class Store:
    """One run owns its ledger/cache. A file lock excludes concurrent writers."""
    def __init__(self, folder, fingerprint):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.lock_handle = (self.folder / '.writer.lock').open('a+b')
        try:
            self.lock_handle.seek(0)
            if self.lock_handle.read(1) == b'':
                self.lock_handle.write(b'0')
                self.lock_handle.flush()
            self.lock_handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock_handle.close()
            raise RuntimeError('Run folder is already in use')
        self.db = sqlite3.connect(str(self.folder / 'evaluations.sqlite'))
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evaluations (
                id INTEGER PRIMARY KEY, design_key TEXT, indices TEXT, source TEXT,
                generation INTEGER, status TEXT, reason TEXT, fea_started INTEGER,
                started_at_utc TEXT, finished_at_utc TEXT, elapsed_s REAL, data TEXT);
            CREATE INDEX IF NOT EXISTS design_lookup ON evaluations(design_key);
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY, evaluation_id INTEGER, source TEXT,
                generation INTEGER, cache_hit INTEGER, requested_at_utc TEXT);
        ''')
        existing = self.get_meta('fingerprint')
        if existing and existing != fingerprint:
            self.close()
            raise ValueError('Run fingerprint mismatch: use a new run folder')
        self.set_meta('fingerprint', fingerprint)
        if not self.get_meta('run_id'):
            self.set_meta('run_id', str(uuid.uuid4()))
        self.db.execute("UPDATE evaluations SET status='interrupted', reason='Process ended before result was committed', finished_at_utc=? WHERE status='started'", (utcnow(),))
        self.db.commit()

    def __enter__(self): return self

    def __exit__(self, *args): self.close()

    def close(self):
        self.db.close()
        self.lock_handle.close()

    def get_meta(self, key):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_meta(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value)))
        self.db.commit()

    def attempts(self):
        return self.db.execute('SELECT COALESCE(SUM(fea_started),0) FROM evaluations').fetchone()[0]

    def lookup(self, indices):
        row = self.db.execute('SELECT id FROM evaluations WHERE design_key=? ORDER BY id DESC LIMIT 1', (','.join(map(str, indices)),)).fetchone()
        return self.row(row[0]) if row else None

    def start(self, indices, source, generation, fea_started=1):
        key = ','.join(map(str, indices))
        cursor = self.db.execute('INSERT INTO evaluations (design_key,indices,source,generation,status,reason,fea_started,started_at_utc,data) VALUES (?,?,?,?,?,?,?,?,?)',
                                 (key, json.dumps(list(indices)), source, generation, 'started', '', fea_started, utcnow(), '{}'))
        self.db.commit()  # Must persist before invoking an external solver.
        return cursor.lastrowid

    def finish(self, evaluation_id, status, reason, data, elapsed):
        self.db.execute('UPDATE evaluations SET status=?,reason=?,data=?,elapsed_s=?,finished_at_utc=? WHERE id=?',
                        (status, reason, json.dumps(data, allow_nan=False), elapsed, utcnow(), evaluation_id))
        self.db.commit()
        return self.row(evaluation_id)

    def row(self, evaluation_id):
        raw = dict(self.db.execute('SELECT * FROM evaluations WHERE id=?', (evaluation_id,)).fetchone())
        data = json.loads(raw.pop('data'))
        indices = json.loads(raw.pop('indices'))
        raw['evaluation_id'] = raw.pop('id')
        return dict(schema_version=SCHEMA, run_id=self.get_meta('run_id'),
                    config_fingerprint=self.get_meta('fingerprint'), **raw,
                    **dict(zip(NAMES, decode(indices))), **data)

    def rows(self):
        return [self.row(row[0]) for row in self.db.execute('SELECT id FROM evaluations ORDER BY id')]

    def request(self, row, source, generation, cache_hit):
        self.db.execute('INSERT INTO requests (evaluation_id,source,generation,cache_hit,requested_at_utc) VALUES (?,?,?,?,?)',
                        (row['evaluation_id'], source, generation, cache_hit, utcnow()))
        self.db.commit()
        return dict(row, cache_hit=cache_hit, request_source=source, request_generation=generation)

    def export(self):
        write_csv(self.folder / 'evaluations.csv', self.rows())
        requests = []
        for record in self.db.execute('SELECT * FROM requests ORDER BY id'):
            requests.append(dict(self.row(record['evaluation_id']), request_id=record['id'],
                                 request_source=record['source'], request_generation=record['generation'],
                                 cache_hit=record['cache_hit'], requested_at_utc=record['requested_at_utc']))
        write_csv(self.folder / 'history.csv', requests)
        rows = self.rows()
        summary = dict(run_id=self.get_meta('run_id'), config_fingerprint=self.get_meta('fingerprint'),
                       solver_attempts=self.attempts(), successful_solves=sum(feasible(r) for r in rows),
                       interrupted_attempts=sum(r['status'] == 'interrupted' for r in rows),
                       cache_hits=sum(r['cache_hit'] for r in requests), requests=len(requests),
                       distinct_designs=len({r['design_key'] for r in rows}),
                       evaluation_elapsed_s=sum(r['elapsed_s'] or 0 for r in rows),
                       wall_time_s=self.get_meta('wall_time_s') or 0,
                       budget_unit='one do_magnetic_calculation call, not internal FEA sub-solves',
                       statuses={s: sum(r['status'] == s for r in rows) for s in sorted({r['status'] for r in rows})})
        atomic_json(self.folder / 'summary.json', summary)
        return summary


class Evaluator:
    def __init__(self, store, solver, budget, retry_failed=False, deadline=None):
        if budget < 1:
            raise ValueError('FEA budget must be positive')
        self.store, self.solver, self.budget = store, solver, budget
        self.retry_failed = retry_failed
        self.deadline = deadline
        self.retried = set()

    def evaluate(self, indices, source, generation=None):
        indices = tuple(int(i) for i in indices)
        decode(indices)
        cached = self.store.lookup(indices)
        retryable = cached and cached['status'] in ('interrupted', 'calculation_failed', 'preparation_failed', 'geometry_check_failed')
        retry = self.retry_failed and retryable and indices not in self.retried
        if cached and not retry:
            return self.store.request(cached, source, generation, 1)
        if self.store.attempts() >= self.budget:
            raise BudgetExhausted('Total E-Magnetic solver-call budget exhausted')
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TimeBudgetExhausted('Time limit reached; no further FEA will be started')
        if retry:
            self.retried.add(indices)
        started = time.monotonic()
        try:
            extra = self.solver.prepare(indices)
        except Exception as exc:
            eid = self.store.start(indices, source, generation, fea_started=0)
            status = exc.status if isinstance(exc, DesignRejected) else 'preparation_failed'
            row = self.store.finish(eid, status, str(exc), {}, time.monotonic() - started)
        else:
            if self.deadline is not None and time.monotonic() >= self.deadline:
                raise TimeBudgetExhausted('Time limit reached during preparation; FEA not started')
            eid = self.store.start(indices, source, generation)
            try:
                data = self.solver.solve()
            except Exception as exc:
                status = exc.status if isinstance(exc, DesignRejected) else 'calculation_failed'
                row = self.store.finish(eid, status, str(exc), extra, time.monotonic() - started)
            else:
                try:
                    objective_values(data)
                    data = dict(extra, **data)
                    json.dumps(data, allow_nan=False)
                except (KeyError, TypeError, ValueError) as exc:
                    row = self.store.finish(eid, 'output_invalid', str(exc), extra, time.monotonic() - started)
                else:
                    row = self.store.finish(eid, 'ok', '', data, time.monotonic() - started)
        self.store.export()
        return self.store.request(row, source, generation, 0)


class ParallelEvaluator(Evaluator):
    """Only solver RPCs run in threads; all ledger/cache/budget writes stay here."""
    def __init__(self, store, solvers, budget, retry_failed=False, deadline=None):
        super().__init__(store, None, budget, retry_failed, deadline)
        if not solvers:
            raise ValueError('At least one solver is required')
        self.solvers = solvers

    def evaluate_many(self, designs, source, generation=None):
        from collections import deque
        from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
        from contextlib import ExitStack
        import signal
        import threading
        designs = [tuple(int(i) for i in x) for x in designs]
        results, jobs = {}, deque()
        for indices in dict.fromkeys(designs):
            decode(indices)
            cached = self.store.lookup(indices)
            retry = (self.retry_failed and cached and
                     cached['status'] in ('interrupted', 'calculation_failed', 'preparation_failed', 'geometry_check_failed')
                     and indices not in self.retried)
            if cached and not retry:
                results[indices] = self.store.request(cached, source, generation, 1)
            else:
                jobs.append((indices, retry))

        def check_limits():
            if self.deadline is not None and time.monotonic() >= self.deadline:
                raise TimeBudgetExhausted('Time limit reached; no further FEA will be started')
            if self.store.attempts() >= self.budget:
                raise BudgetExhausted('Total E-Magnetic solver-call budget exhausted')

        def finish(indices, eid, status, reason, data, started):
            row = self.store.finish(eid, status, reason, data, time.monotonic() - started)
            results[indices] = self.store.request(row, source, generation, 0)
            self.store.export()

        active, failure = {}, None
        with ExitStack() as cleanup, ThreadPoolExecutor(max_workers=len(self.solvers)) as pool:
            if threading.current_thread() is threading.main_thread():
                # Defer Ctrl+C across persistence/dispatch too, not only during wait().
                # A signal must never interrupt a commit and strand another worker's result.
                def interrupt(signum, frame):
                    nonlocal failure
                    failure = KeyboardInterrupt()
                previous_handler = signal.signal(signal.SIGINT, interrupt)
                cleanup.callback(signal.signal, signal.SIGINT, previous_handler)
            def dispatch(solver):
                nonlocal failure
                if failure is not None or not jobs:
                    return
                try:
                    check_limits()
                except BudgetExhausted as exc:
                    failure = exc
                    return
                indices, retry = jobs.popleft()
                if retry:
                    self.retried.add(indices)
                future = pool.submit(solver.prepare, indices)
                active[future] = (solver, indices, time.monotonic(), None, None)

            for solver in self.solvers:
                dispatch(solver)
            while active:
                try:
                    done, _ = wait(active, return_when=FIRST_COMPLETED)
                except KeyboardInterrupt as exc:
                    # Drain and commit active FEA before the caller saves its checkpoint.
                    failure = exc
                    continue
                for future in done:
                    solver, indices, started, eid, extra = active.pop(future)
                    if eid is None:
                        try:
                            extra = future.result()
                        except Exception as exc:
                            eid = self.store.start(indices, source, generation, fea_started=0)
                            status = exc.status if isinstance(exc, DesignRejected) else 'preparation_failed'
                            finish(indices, eid, status, str(exc), {}, started)
                            dispatch(solver)
                            continue
                        if failure is not None:
                            continue
                        try:
                            check_limits()
                        except BudgetExhausted as exc:
                            failure = exc
                            continue
                        eid = self.store.start(indices, source, generation)
                        active[pool.submit(solver.solve)] = (solver, indices, started, eid, extra)
                    else:
                        try:
                            data = future.result()
                        except Exception as exc:
                            status = exc.status if isinstance(exc, DesignRejected) else 'calculation_failed'
                            finish(indices, eid, status, str(exc), extra, started)
                        else:
                            try:
                                objective_values(data)
                                data = dict(extra, **data)
                                json.dumps(data, allow_nan=False)
                            except (KeyError, TypeError, ValueError) as exc:
                                finish(indices, eid, 'output_invalid', str(exc), extra, started)
                            else:
                                finish(indices, eid, 'ok', '', data, started)
                        dispatch(solver)
        if failure is not None:
            raise failure
        ordered, seen = [], set()
        for indices in designs:
            row = results[indices]
            ordered.append(self.store.request(row, source, generation, 1) if indices in seen else row)
            seen.add(indices)
        return ordered


def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    base = ['schema_version', 'run_id', 'evaluation_id', 'source', 'generation', 'design_key',
            'config_fingerprint'] + NAMES + list(OBJECTIVES) + ['status', 'reason', 'fea_started',
            'started_at_utc', 'finished_at_utc', 'elapsed_s']
    columns = base + sorted({key for row in rows for key in row} - set(base))
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def validate_j_scope(fixed, config):
    if config.get('j_validation'):
        if fixed.get('WindingConnection') != 0 or fixed.get('NumberOfWireSizes') != 1:
            raise ValueError('J validation supports only the verified star winding with one wire size')
        # Limit the independent copper-area formula to the supplied, verified round-wire model.
        approved_hash = config['j_validation'].get('model_sha256',
            '1cfee7718f933e65908a5df30da9003786bd7886edc13f0c6db62a0816a41811')
        if file_hash(config['model']) != approved_hash:
            raise ValueError('J validation formula must be reverified for a different baseline model')


class MotorCADLease:
    """Cross-run process lock: one local Motor-CAD session for this tool family."""
    def __init__(self, path=None):
        import tempfile
        self.path = Path(path) if path is not None else Path(tempfile.gettempdir()) / 'motorcad_optimizer_session.lock'
        self.handle = None

    def __enter__(self):
        self.handle = self.path.open('a+b')
        try:
            self.handle.seek(0)
            if not self.handle.read(1):
                self.handle.write(b'0')
                self.handle.flush()
            self.handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise RuntimeError('Another Motor-CAD task is already using the single session') from exc
        return self

    def __exit__(self, *args):
        if self.handle is not None:
            self.handle.close()
            self.handle = None


class MotorCADSolver:
    """One private Motor-CAD session with explicitly authorized fixed length overrides."""
    def __init__(self, config, workspace, mc=None, single_session=True):
        import shutil
        self.config = config
        self.original = Path(config['model']).resolve()
        self.original_hash = file_hash(self.original)
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.baseline = self.workspace / 'baseline.mot'
        if self.original == self.baseline:
            raise ValueError('Working model must differ from original')
        shutil.copy2(self.original, self.baseline)
        self.owned = mc is None
        self.mc = mc
        self.lease = None
        try:
            if mc is None:
                if single_session:
                    self.lease = MotorCADLease().__enter__()
                    import psutil
                    running = [p.info['pid'] for p in psutil.process_iter(['pid', 'name'])
                               if (p.info['name'] or '').lower().startswith(('motor-cad', 'motorcad'))]
                    if running:
                        raise RuntimeError('Motor-CAD is already open. Save and close it before this single-license run; no second instance was opened.')
                import ansys.motorcad.core as pymotorcad
                if config.get('motorcad_exe'):
                    pymotorcad.set_motorcad_exe(config['motorcad_exe'])
                self.mc = pymotorcad.MotorCAD(open_new_instance=True, enable_exceptions=True)
                self.mc.set_variable('MessageDisplayState', 2)
            self.load_working_model(self.baseline)
            self.fixed = {name: self.mc.get_variable(name) for name in config['fixed_parameters']}
            validate_j_scope(self.fixed, config)
            self.expected = None
            self.guard()
        except BaseException:
            self.close()
            raise

    def close(self):
        try:
            if self.owned and self.mc is not None:
                try:
                    self.mc.quit()
                finally:
                    self.mc = None
        finally:
            if self.lease is not None:
                self.lease.__exit__()
                self.lease = None
        if file_hash(self.original) != self.original_hash:
            raise RuntimeError('Original model changed externally during this run')

    def load_working_model(self, path):
        overrides = self.config.get('fixed_overrides', {})
        allowed = {'Stator_Lam_Length', 'Rotor_Lam_Length', 'Magnet_Length'}
        if set(overrides) - allowed or set(overrides) - set(self.config['fixed_parameters']):
            raise ValueError('Fixed overrides may only set protected stator, rotor and magnet lengths')
        self.mc.load_from_file(str(path))
        for name, value in overrides.items():
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f'Invalid fixed length: {name}')
            self.mc.set_variable(name, value)
        for name, value in overrides.items():
            if not self.equal(self.mc.get_variable(name), value):
                raise DesignRejected('invariant_violation', f'Fixed length override not applied: {name}')
        if overrides:
            self.mc.save_to_file(str(path))

    @staticmethod
    def equal(actual, wanted, tolerance=1e-8):
        if isinstance(wanted, (int, float)):
            return math.isfinite(float(actual)) and math.isclose(float(actual), float(wanted), rel_tol=1e-9, abs_tol=tolerance)
        return actual == wanted

    def guard(self):
        for name, value in self.fixed.items():
            if not self.equal(self.mc.get_variable(name), value):
                raise DesignRejected('invariant_violation', f'Fixed parameter changed: {name}')
        for name in ('ScriptAutoRun', 'ScriptAutoRun_PythonClasses'):
            if self.mc.get_variable(name) != 0:
                raise DesignRejected('invariant_violation', f'Embedded script autorun enabled: {name}')
        if self.mc.get_variable('CurrentDefinition') != self.config['expected_current_definition']:
            raise DesignRejected('invariant_violation', 'CurrentDefinition differs from verified current-density mode')
        j = float(self.mc.get_variable('RMSCurrentDensity'))
        if not math.isclose(j, self.config['target_j'], rel_tol=0, abs_tol=self.config['j_tolerance']):
            raise DesignRejected('current_density_violation', f'RMS current density is {j}; target is {self.config["target_j"]}')
        if self.expected is not None:
            for name, value in zip(NAMES, self.expected):
                actual = self.mc.get_variable(name)
                if not self.equal(actual, value):
                    raise DesignRejected('readback_mismatch', f'Motor-CAD adjusted {name}: requested {value}, actual {actual}')

    def prepare(self, indices):
        # Unique sidecar directory prevents auto-loading prior result files as current outputs.
        # Reloading a clean baseline also avoids accumulated automatic geometry edits.
        import shutil
        attempt_folder = self.workspace / 'designs' / uuid.uuid4().hex
        attempt_folder.mkdir(parents=True)
        working_model = attempt_folder / 'model.mot'
        shutil.copy2(self.baseline, working_model)
        self.load_working_model(working_model)
        self.expected = None
        self.guard()
        values = decode(indices)
        for name, value in zip(NAMES, values):
            self.mc.set_variable(name, value)
        self.expected = values
        try:
            # PyMotorCAD checks RPC success==1 for this specific method and raises on invalid
            # geometry. Its output is NOT a Boolean validity value (it concerns auto-repair).
            self.mc.check_if_geometry_is_valid(0)
        except Exception as exc:
            # A failed RPC may be geometric, transport, licensing, or process-related.
            # Without an explicit geometric diagnosis it must remain eligible for a manual retry.
            raise DesignRejected('geometry_check_failed', str(exc)) from exc
        self.guard()
        result = {'model_sha256': self.original_hash,
                  'working_model_path': str(working_model),
                  'readback_json': json.dumps(dict(zip(NAMES, values)))}
        for name in ('RMSCurrentDensity', 'RMSCurrent', 'PeakCurrent'):
            try:
                result[name] = float(self.mc.get_variable(name))
            except Exception:
                if name == 'RMSCurrentDensity': raise
        return result

    def solve(self):
        self.mc.do_magnetic_calculation()  # Exceptions enabled: never consume old outputs after failure.
        self.guard()
        results = {}
        j_spec = self.config.get('j_validation')
        if j_spec:
            # This formula is restricted to this model's single-size round copper,
            # star winding; config also locks its connection, paths and strand count.
            current = float(self.mc.get_variable(j_spec['current_parameter']))
            diameter = float(self.mc.get_variable('Copper_Diameter'))
            paths = float(self.mc.get_variable('ParallelPaths'))
            strands = float(self.mc.get_variable('NumberStrandsHand'))
            if min(diameter, paths, strands) <= 0:
                raise DesignRejected('current_density_violation', 'Invalid conductor area or parallel paths')
            actual_j = current / (paths * strands * math.pi * diameter**2 / 4)
            if not math.isclose(actual_j, self.config['target_j'], rel_tol=0,
                                abs_tol=j_spec.get('tolerance_a_per_mm2', .001)):
                raise DesignRejected('current_density_violation', f'Calculated current density {actual_j} A/mm2 is not target J')
            results.update(actual_j_a_per_mm2=actual_j, calculated_rms_line_current_a=current,
                           copper_diameter_mm=diameter)
        for column, spec in self.config['objectives'].items():
            results[column] = float(self.mc.get_variable(spec['parameter']))
        objective_values(results)
        missing_optional = {}
        for column, spec in self.config.get('optional_outputs', {}).items():
            try:
                value = float(self.mc.get_variable(spec['parameter']))
                if not math.isfinite(value): raise ValueError('NaN/Inf')
                results[column] = value
            except Exception as exc:
                missing_optional[column] = str(exc)
        results['optional_output_errors'] = json.dumps(missing_optional)
        results['RMSCurrentDensity'] = float(self.mc.get_variable('RMSCurrentDensity'))
        return results

    def check(self):
        report = {'checked_at_utc': utcnow(), 'model_sha256': self.original_hash,
                  'fea_calls': 0, 'fixed_parameters': self.fixed, 'parameters': {},
                  'warnings': [], 'errors': []}
        for name in NAMES + ['CurrentDefinition', 'RMSCurrentDensity', 'RMSCurrent', 'PeakCurrent']:
            try:
                value = self.mc.get_variable(name)
                if name in NAMES:
                    self.mc.set_variable(name, value)
                readback = self.mc.get_variable(name)
                if not self.equal(readback, value): raise ValueError('get/set/readback differs')
                report['parameters'][name] = readback
            except Exception as exc:
                report['errors'].append(f'{name}: {exc}')
        for column in OBJECTIVES:
            try:
                spec = self.config['objectives'][column]
                if not spec.get('evidence') or not spec.get('definition') or not spec.get('unit'):
                    raise ValueError('mapping needs evidence, definition, and unit')
                value = float(self.mc.get_variable(spec['parameter']))
                report['parameters'][spec['parameter']] = value
            except Exception as exc:
                report['errors'].append(f'{column}: {exc}')
        try:
            self.mc.check_if_geometry_is_valid(0)
            self.guard()
            # Small reversible perturbation tests native current-density-to-current conversion.
            current0 = float(self.mc.get_variable('RMSCurrent'))
            tooth0 = float(self.mc.get_variable('Ratio_ToothWidth'))
            changed = .35 if not math.isclose(tooth0, .35) else .36
            self.mc.set_variable('Ratio_ToothWidth', changed)
            j = float(self.mc.get_variable('RMSCurrentDensity'))
            current1 = float(self.mc.get_variable('RMSCurrent'))
            self.mc.check_if_geometry_is_valid(0)
            self.guard()
            report['current_density_test'] = {'parameter': 'Ratio_ToothWidth', 'before': tooth0,
                                             'after': changed, 'current_before_a': current0,
                                             'current_after_a': current1, 'j_after_a_per_mm2': j}
            if math.isclose(current0, current1, rel_tol=1e-7, abs_tol=1e-9):
                report['warnings'].append('Current did not update immediately after geometry edit; actual J must be verified after FEA using calculated current and copper area.')
        except Exception as exc:
            report['errors'].append(f'geometry/current-density probe: {exc}')
        finally:
            self.load_working_model(self.baseline)
            self.expected = None
        for name in ('OnLoadLossCalculation', 'BackEMFLossCalculation'):
            value = self.mc.get_variable(name)
            report['parameters'][name] = value
            if not value:
                report['warnings'].append(f'{name}=False: preserved baseline loss settings; efficiency reflects this loss model')
        report['warnings'].append('Output reads without FEA establish availability only; they are not simulated designs.')
        report['ready'] = not report['errors']
        report['config_sha256'] = digest(self.config)
        return report


def save_checkpoint(path, state):
    import dill
    import numpy as np
    state['numpy_rng'] = np.random.get_state()
    state['python_rng'] = random.getstate()
    temp = path.with_suffix('.tmp')
    with temp.open('wb') as handle:
        dill.dump(state, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def run_nsga2(store, evaluator, population, generations, seed, resume=False):
    # Compatibility entry for the original helper CLI and existing callers.
    from nsga2_motorcad import run_nsga2 as optimize
    return optimize(store, evaluator, population, generations, seed, resume)


def run_doe(store, evaluator, samples, seed, resume=False):
    settings = dict(samples=samples, seed=seed)
    path = store.folder / 'doe_plan.json'
    if resume:
        plan = json.loads(path.read_text(encoding='utf-8'))
        if plan['settings'] != settings: raise ValueError('DoE resume settings mismatch')
    else:
        if path.exists() or store.rows(): raise ValueError('Run exists; use --resume or a new folder')
        plan = dict(settings=settings, designs=lhs_designs(samples, seed))
        atomic_json(path, plan)
    reason = 'samples'
    try:
        for number, indices in enumerate(plan['designs'], 1):
            result = evaluator.evaluate(indices, 'doe')
            print(f'DoE {number}/{samples}: {result["status"]}, solver calls {store.attempts()}/{evaluator.budget}', flush=True)
    except BudgetExhausted:
        reason = 'budget'
    finally:
        store.export()
    return dict(stop_reason=reason, solver_attempts=store.attempts())


def analyze_csv(path, output, labels=None):
    with Path(path).open('r', encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    fingerprints = {r.get('config_fingerprint') for r in rows}
    if rows and any(not fp for fp in fingerprints):
        raise ValueError('CSV is missing config fingerprint provenance')
    if len(fingerprints) > 1:
        raise ValueError('CSV contains mixed config fingerprints; analyze separate experiments')
    manifest_path = Path(path).parent / 'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if rows and manifest.get('fingerprint') not in fingerprints:
            raise ValueError('CSV fingerprint differs from adjacent manifest')
    # history.csv may repeat cached requests; retain one row per true evaluation/design.
    unique = {}
    for i, row in enumerate(rows):
        if feasible(row) and (row.get('schema_version') != str(SCHEMA) or not row.get('run_id')):
            raise ValueError('Feasible CSV rows need supported schema_version and run_id provenance')
        local_key = row.get('evaluation_id') or row.get('design_key') or str(i)
        key = (row.get('run_id'), local_key)
        unique[key] = row
    rows = list(unique.values())
    valid = [r for r in rows if feasible(r)]
    pareto = nondominated(rows)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / 'pareto.csv', pareto)
    result = dict(total=len(rows), feasible=len(valid), pareto=len(pareto),
                  label='Best-known Pareto Reference', excluded=len(rows)-len(valid))
    if valid:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np
        points = np.array([objective_values(r) for r in valid])
        front = np.array([objective_values(r) for r in pareto])
        labels = labels or ['Average electromagnetic torque (Nm)', 'Power factor', 'Motor efficiency (%)']
        fig, axes = plt.subplots(1, 3, figsize=(15, 4.3), constrained_layout=True)
        for axis, (a, b) in zip(axes, [(0, 1), (0, 2), (1, 2)]):
            axis.scatter(points[:, a], points[:, b], s=24, alpha=.45, label='Feasible Motor-CAD')
            axis.scatter(front[:, a], front[:, b], s=36, facecolors='none', edgecolors='crimson', label='Nondominated in 3D')
            axis.set(xlabel=labels[a], ylabel=labels[b])
            axis.grid(alpha=.2)
        axes[0].legend(fontsize=8)
        fig.suptitle('Best-known Pareto Reference')
        fig.savefig(output / 'objective_pairs.png', dpi=180)
        plt.close(fig)
        fig = plt.figure(figsize=(8, 6), layout='constrained')
        axis = fig.add_subplot(111, projection='3d')
        axis.scatter(*points.T, alpha=.4, s=20, label='Feasible Motor-CAD')
        axis.scatter(*front.T, color='crimson', s=40, label='Best-known Pareto Reference')
        axis.set(xlabel=labels[0], ylabel=labels[1], zlabel=labels[2])
        axis.legend(fontsize=8)
        fig.savefig(output / 'pareto_3d.png', dpi=180)
        plt.close(fig)
    else:
        # These two files are derived artifacts owned by this analysis operation.
        for name in ('objective_pairs.png', 'pareto_3d.png'):
            (output / name).unlink(missing_ok=True)
    atomic_json(output / 'analysis.json', result)
    return result


def environment_signature(config):
    from importlib.metadata import version
    return dict(schema_version=SCHEMA, model_sha256=file_hash(config['model']), config=config,
                variables=VARIABLES, python=sys.version.split()[0],
                motorcad_exe_sha256=file_hash(config['motorcad_exe']),
                packages={name: version(name) for name in ['ansys-motorcad-core', 'pymoo', 'scipy', 'numpy']})


def load_config(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding='utf-8'))
    for key in ('model', 'motorcad_exe'):
        target = Path(config[key])
        config[key] = str((path.parent / target).resolve() if not target.is_absolute() else target)
    if set(config['objectives']) != set(OBJECTIVES):
        raise ValueError('Config must define exactly the three objective columns')
    for column in OBJECTIVES:
        spec = config['objectives'][column]
        if not all(spec.get(k) for k in ('parameter', 'definition', 'unit', 'evidence')):
            raise ValueError(f'Unconfirmed objective mapping: {column}')
    return config


def main(argv=None, standalone_nsga=False):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode')
    for mode in ('check', 'doe', 'nsga2'):
        p = sub.add_parser(mode)
        if standalone_nsga and mode == 'nsga2':
            p.prog = 'nsga2_motorcad.py'
        p.add_argument('--config', default=str(CONFIG_DIR / ('nsga2_config.json' if mode == 'nsga2' else 'motorcad_config.json')))
        p.add_argument('--run-dir', default=str(PROJECT_ROOT / 'inspection' / 'check') if mode == 'check' else None, required=mode != 'check')
        if mode != 'nsga2':
            p.add_argument('--verification', default=str(PROJECT_ROOT / 'inspection' / 'check' / 'check_report.json'))
        if mode == 'check':
            p.add_argument('--smoke-fea', action='store_true', help='explicitly run at most ONE snapped baseline design')
        else:
            p.add_argument('--budget', type=int, required=True, help='total EMag calls including earlier attempts on resume')
            p.add_argument('--seed', type=int, default=17)
            p.add_argument('--resume', action='store_true')
            p.add_argument('--retry-failed', action='store_true', help='retry each cached transient/interrupted design at most once this invocation')
        if mode == 'doe': p.add_argument('--samples', type=int, default=40)
        if mode == 'nsga2':
            p.add_argument('--workers', type=int, default=1, help='number of independent parallel Motor-CAD sessions')
            p.add_argument('--population', type=int, default=40)
            p.add_argument('--generations', type=int, default=30)
            p.add_argument('--max-minutes', type=float, help='stop starting new FEA after this invocation duration; finish the active solver call')
    p = sub.add_parser('analyze')
    p.add_argument('--csv', required=True)
    p.add_argument('--out-dir', required=True)
    if argv is None and len(sys.argv) == 1:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    if args.mode == 'nsga2' and (args.workers < 1 or args.population < 4 or args.generations < 1 or args.budget < 1):
        parser.error('workers >= 1, population >= 4, generations >= 1 and budget >= 1 required')
    if args.mode == 'nsga2' and args.max_minutes is not None:
        if not math.isfinite(args.max_minutes) or args.max_minutes <= 0:
            parser.error('--max-minutes must be finite and positive')
    if args.mode is None:
        parser.print_help()
        return 0
    if args.mode == 'analyze':
        result = analyze_csv(args.csv, args.out_dir)
        print(json.dumps(result, indent=2))
        return 0
    config = load_config(args.config)
    signature = environment_signature(config)
    fingerprint = digest(signature)
    folder = Path(args.run_dir).resolve()
    if args.mode == 'doe':
        report = json.loads(Path(args.verification).read_text(encoding='utf-8'))
        if not report.get('ready') or report.get('fingerprint') != fingerprint or report.get('smoke_status') != 'ok':
            raise ValueError('Run check --smoke-fea successfully with this exact config/environment before a campaign')
    folder.mkdir(parents=True, exist_ok=True)
    solver = None
    solvers = []
    started = time.monotonic()
    with Store(folder, fingerprint) as store:
        manifest_path = folder / 'manifest.json'
        if not manifest_path.exists():
            atomic_json(manifest_path, dict(run_id=store.get_meta('run_id'), created_at_utc=utcnow(),
                                           source=args.mode, fingerprint=fingerprint, signature=signature))
        previous_mode = store.get_meta('mode')
        if previous_mode and previous_mode != args.mode:
            raise ValueError('Each mode needs a separate run folder')
        store.set_meta('mode', args.mode)
        try:
            if args.mode == 'nsga2':
                from contextlib import ExitStack
                # ExitStack closes every owned session even if a later launch/check fails.
                sessions = ExitStack()
                try:
                    for worker in range(args.workers):
                        instance = MotorCADSolver(config, folder / 'work' / f'worker_{worker+1:02d}', single_session=False)
                        sessions.callback(instance.close)
                        solvers.append(instance)
                        report = instance.check()
                        report['fingerprint'] = fingerprint
                        atomic_json(folder / f'startup_check_worker_{worker+1:02d}.json', report)
                        if worker == 0:
                            atomic_json(folder / 'startup_check.json', report)
                        if not report['ready']:
                            raise ValueError(f'Motor-CAD worker {worker+1} startup check failed; see startup_check_worker_{worker+1:02d}.json')
                        print(f'Motor-CAD worker {worker+1}/{args.workers} ready.', flush=True)
                except BaseException:
                    sessions.close()
                    raise
                solver = solvers[0]
                store.set_meta('workers', args.workers)
            else:
                solver = MotorCADSolver(config, folder / 'work')
            if args.mode == 'check':
                report = solver.check()
                report['fingerprint'] = fingerprint
                atomic_json(folder / 'check_report.json', report)
                if args.smoke_fea:
                    if not report['ready']: raise ValueError('Read-only check failed; see check_report.json')
                    values = [solver.mc.get_variable(name) for name in NAMES]
                    row = Evaluator(store, solver, 1).evaluate(encode(values), 'check')
                    report['smoke_status'] = row['status']
                    report['smoke_evaluation_id'] = row['evaluation_id']
                    report['fea_calls'] = store.attempts()
                atomic_json(folder / 'check_report.json', report)
                result = report
            else:
                deadline = started + args.max_minutes * 60 if args.mode == 'nsga2' and args.max_minutes is not None else None
                if args.mode == 'nsga2':
                    evaluator = ParallelEvaluator(store, solvers, args.budget, args.retry_failed, deadline=deadline)
                else:
                    evaluator = Evaluator(store, solver, args.budget, args.retry_failed, deadline=deadline)
                if args.mode == 'doe':
                    result = run_doe(store, evaluator, args.samples, args.seed, args.resume)
                else:
                    result = run_nsga2(store, evaluator, args.population, args.generations, args.seed, args.resume)
            print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
        finally:
            try:
                store.set_meta('wall_time_s', (store.get_meta('wall_time_s') or 0) + time.monotonic() - started)
                store.export()
            finally:
                if solvers:
                    sessions.close()
                elif solver is not None:
                    solver.close()
            analyze_csv(folder / 'evaluations.csv', folder / 'analysis')
    if args.mode == 'check':
        return 0 if result['ready'] and (not args.smoke_fea or result.get('smoke_status') == 'ok') else 2
    return 0


if __name__ == '__main__':
    sys.modules.setdefault('motorcad_optimize', sys.modules[__name__])
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('Interrupted. Completed evaluations are saved; resume with the same run folder.', file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(2)
