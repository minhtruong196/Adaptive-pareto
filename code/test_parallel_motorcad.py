"""Offline parallel scheduling tests; no Motor-CAD processes are started."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import motorcad_optimize as opt
import nsga2_motorcad as runner


class ParallelContracts(unittest.TestCase):
    def test_ctrl_c_during_commit_drains_other_running_results(self):
        import signal
        barrier = threading.Barrier(2)
        class Solver:
            def prepare(self, indices): return {}
            def solve(self):
                barrier.wait(timeout=5)
                return dict(average_torque_nm=10, power_factor=.9, efficiency_pct=85)
        with tempfile.TemporaryDirectory() as tmp, opt.Store(tmp, 'synthetic') as store:
            original_finish = store.finish
            interrupted = []
            def finish(*args):
                row = original_finish(*args)
                if not interrupted:
                    interrupted.append(True)
                    signal.raise_signal(signal.SIGINT)
                return row
            with patch.object(store, 'finish', side_effect=finish):
                with self.assertRaises(KeyboardInterrupt):
                    opt.ParallelEvaluator(store, [Solver(), Solver()], 10).evaluate_many([(0,)*7, (1,)*7], 'nsga2', 1)
            self.assertEqual([r['status'] for r in store.rows()], ['ok', 'ok'])

    def test_model_hash_and_winding_checks_remain_required(self):
        config = opt.load_config(opt.CONFIG_DIR / 'nsga2_config.json')
        config['j_validation']['model_sha256'] = opt.file_hash(config['model'])
        opt.validate_j_scope(dict(WindingConnection=0, NumberOfWireSizes=1), config)
        config['j_validation']['model_sha256'] = 'different'
        with self.assertRaisesRegex(ValueError, 'reverified'):
            opt.validate_j_scope(dict(WindingConnection=0, NumberOfWireSizes=1), config)

    def test_later_worker_startup_failure_closes_all_owned_sessions(self):
        closed, workspaces = [], []
        class Solver:
            def __init__(self, config, workspace, **kwargs):
                self.index = len(workspaces)
                workspaces.append(workspace)
            def check(self): return dict(ready=self.index == 0)
            def close(self): closed.append(self.index)
        with tempfile.TemporaryDirectory() as tmp, patch.object(opt, 'MotorCADSolver', Solver):
            with self.assertRaisesRegex(ValueError, 'worker 2'):
                runner.main(['--workers', '3', '--run-dir', tmp])
        self.assertEqual(set(closed), {0, 1})
        self.assertEqual(len(closed), 2)
        self.assertEqual(len(set(workspaces)), 2)

    def test_prompt_rejects_invalid_counts_and_accepts_default(self):
        with patch('builtins.input', side_effect=['0', '-2', 'abc', '2.5', '3']):
            self.assertEqual(runner.prompt_workers(), 3)
        with patch('builtins.input', return_value=''):
            self.assertEqual(runner.prompt_workers(), 5)

    def test_parallel_overlap_order_duplicates_and_cache(self):
        barrier = threading.Barrier(2)
        class Solver:
            def prepare(self, indices):
                self.x = indices[0]
                return {}
            def solve(self):
                barrier.wait(timeout=5)
                return dict(average_torque_nm=self.x + 10, power_factor=.9, efficiency_pct=85)
        with tempfile.TemporaryDirectory() as tmp, opt.Store(tmp, 'synthetic') as store:
            evaluator = opt.ParallelEvaluator(store, [Solver(), Solver()], 10)
            designs = [(1,)*7, (2,)*7, (1,)*7]
            rows = evaluator.evaluate_many(designs, 'nsga2', 1)
            self.assertEqual([r['average_torque_nm'] for r in rows], [11, 12, 11])
            self.assertEqual(store.attempts(), 2)
            self.assertEqual(evaluator.evaluate_many(designs, 'nsga2', 2)[0]['cache_hit'], 1)
            self.assertEqual(store.attempts(), 2)

    def test_budget_never_overshoots_and_pending_generation_resumes(self):
        class Solver:
            def prepare(self, indices): return {}
            def solve(self): return dict(average_torque_nm=10, power_factor=.9, efficiency_pct=85)
        with tempfile.TemporaryDirectory() as tmp, opt.Store(tmp, 'synthetic') as store:
            first = runner.run_nsga2(store, opt.ParallelEvaluator(store, [Solver() for _ in range(5)], 3), 6, 2, 17)
            self.assertEqual(first['stop_reason'], 'budget')
            self.assertEqual(store.attempts(), 3)
            second = runner.run_nsga2(store, opt.ParallelEvaluator(store, [Solver(), Solver()], 12), 6, 2, 17, resume=True)
            self.assertEqual(second['stop_reason'], 'generations')
            self.assertEqual(store.attempts(), 12)
            self.assertTrue(all(row['status'] == 'ok' for row in store.rows()))

    def test_preparation_and_solve_errors_are_persisted_and_retryable(self):
        class Solver:
            def prepare(self, indices):
                if indices[0] == 0: raise opt.DesignRejected('geometry_check_failed', 'RPC')
                return {}
            def solve(self): raise RuntimeError('solver failure')
        with tempfile.TemporaryDirectory() as tmp, opt.Store(tmp, 'synthetic') as store:
            e = opt.ParallelEvaluator(store, [Solver(), Solver()], 10)
            rows = e.evaluate_many([(0,)*7, (1,)*7], 'nsga2', 1)
            self.assertEqual([r['status'] for r in rows], ['geometry_check_failed', 'calculation_failed'])
            self.assertEqual(store.attempts(), 1)
            e = opt.ParallelEvaluator(store, [Solver(), Solver()], 10, retry_failed=True)
            e.evaluate_many([(0,)*7, (1,)*7], 'nsga2', 1)
            self.assertEqual(store.attempts(), 2)
            self.assertEqual(len(store.rows()), 4)

    def test_deadline_does_not_start_fea(self):
        import time
        class Solver:
            def prepare(self, indices): return {}
            def solve(self): raise AssertionError('must not solve')
        with tempfile.TemporaryDirectory() as tmp, opt.Store(tmp, 'synthetic') as store:
            e = opt.ParallelEvaluator(store, [Solver(), Solver()], 10, deadline=time.monotonic()-1)
            with self.assertRaises(opt.TimeBudgetExhausted):
                e.evaluate_many([(0,)*7, (1,)*7], 'nsga2', 1)
            self.assertEqual(store.attempts(), 0)


if __name__ == '__main__':
    unittest.main()
