"""Offline contract tests. Synthetic solver values never enter real run folders."""
import tempfile
import unittest
from pathlib import Path

try:
    import motorcad_optimize as opt
except ImportError:
    opt = None


class Contracts(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(opt, 'motorcad_optimize implementation is missing')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def test_grid_rounds_and_clips_without_float_cache_duplicates(self):
        x = [.50005, .8, .65, .499, .749999999, 4.76, 2.1]
        indices = opt.encode(x)
        self.assertEqual(indices, (1, 3000, 3500, 0, 1, 4, 4))
        self.assertEqual(opt.decode(indices), [.5001, .8, .65, .5, .75, 5., 2.])
        self.assertEqual(opt.encode(opt.decode(indices)), indices)

    def test_lhs_is_reproducible_unique_and_on_grid(self):
        samples = opt.lhs_designs(40, 17)
        self.assertEqual(samples, opt.lhs_designs(40, 17))
        self.assertEqual(len(samples), 40)
        self.assertEqual(len(set(samples)), 40)
        self.assertTrue(all(opt.encode(opt.decode(i)) == i for i in samples))

    def test_pareto_excludes_failed_missing_and_nonfinite_outputs(self):
        rows = [dict(status='ok', average_torque_nm=10, power_factor=.8, efficiency_pct=90),
                dict(status='ok', average_torque_nm=9, power_factor=.7, efficiency_pct=89),
                dict(status='failed', average_torque_nm=100, power_factor=1, efficiency_pct=100),
                dict(status='ok', average_torque_nm=11, power_factor=.7, efficiency_pct=91),
                dict(status='ok', average_torque_nm=float('nan'), power_factor=.9, efficiency_pct=95)]
        self.assertEqual(opt.nondominated(rows), [rows[0], rows[3]])

    def test_cache_and_failure_never_reuse_previous_success_outputs(self):
        class Solver:
            def prepare(self, indices):
                return {}
            def solve(self):
                if store.attempts() == 2:
                    raise RuntimeError('solver failed')
                return dict(average_torque_nm=12, power_factor=.82, efficiency_pct=91)
        with opt.Store(self.folder, 'abc') as store:
            e = opt.Evaluator(store, Solver(), 2)
            a = e.evaluate((0,)*7, 'doe')
            b = e.evaluate((0,)*7, 'doe')
            bad = e.evaluate((1,)*7, 'doe')
            self.assertEqual(a['status'], 'ok')
            self.assertEqual(b['cache_hit'], 1)
            self.assertEqual(store.attempts(), 2)
            self.assertEqual(bad['status'], 'calculation_failed')
            self.assertIsNone(bad.get('average_torque_nm'))
            with self.assertRaises(opt.BudgetExhausted):
                e.evaluate((2,)*7, 'nsga2')

    def test_crash_is_counted_after_reopen_and_fingerprint_is_strict(self):
        with opt.Store(self.folder, 'abc') as store:
            store.start((0,)*7, 'doe', None)
        with opt.Store(self.folder, 'abc') as store:
            self.assertEqual(store.attempts(), 1)
            self.assertEqual(store.rows()[0]['status'], 'interrupted')
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            opt.Store(self.folder, 'different')

    def test_geometry_rejection_consumes_no_solver_budget(self):
        class Solver:
            def prepare(self, indices):
                raise opt.DesignRejected('geometry_invalid', 'overlapping regions')
            def solve(self):
                raise AssertionError('must not run')
        with opt.Store(self.folder, 'abc') as store:
            result = opt.Evaluator(store, Solver(), 1).evaluate((0,)*7, 'doe')
            self.assertEqual(result['status'], 'geometry_invalid')
            self.assertEqual(store.attempts(), 0)

    def test_missing_objective_clears_all_objectives(self):
        class Solver:
            def prepare(self, indices): return {}
            def solve(self): return dict(average_torque_nm=5, power_factor=.7)
        with opt.Store(self.folder, 'abc') as store:
            result = opt.Evaluator(store, Solver(), 1).evaluate((0,)*7, 'doe')
            self.assertEqual(result['status'], 'output_invalid')
            self.assertIsNone(result.get('average_torque_nm'))

    def test_adapter_rejects_changed_fixed_dimension_or_j(self):
        class Motor:
            def __init__(self):
                self.values = dict(zip(opt.NAMES, opt.decode((0,)*7)))
                self.values.update(Stator_Lam_Dia=129.772, Stator_Lam_Length=117.839,
                                   Rotor_Lam_Length=83.472, Magnet_Length=83.472,
                                   CurrentDefinition=2, RMSCurrentDensity=7,
                                   ScriptAutoRun=0, ScriptAutoRun_PythonClasses=0)
                self.drift = None
            def load_from_file(self, path): pass
            def get_variable(self, name): return self.values[name]
            def set_variable(self, name, value):
                self.values[name] = value
                if name == 'Slot_Corner_Radius' and self.drift:
                    self.values[self.drift] += 1
            def check_if_geometry_is_valid(self, edit):
                if edit != 0: raise AssertionError('must not repair geometry')
        config = dict(model=str(Path('Basic_Model.mot').resolve()), target_j=7,
                      j_tolerance=1e-6, fixed_parameters=['Stator_Lam_Dia', 'Stator_Lam_Length',
                      'Rotor_Lam_Length', 'Magnet_Length'], expected_current_definition=2,
                      objectives={}, optional_outputs={})
        mc = Motor()
        solver = opt.MotorCADSolver(config, self.folder, mc=mc)
        mc.drift = 'Stator_Lam_Dia'
        with self.assertRaisesRegex(opt.DesignRejected, 'Stator_Lam_Dia'):
            solver.prepare((0,)*7)
        mc.values['Stator_Lam_Dia'] = 129.772
        mc.drift = 'RMSCurrentDensity'
        with self.assertRaisesRegex(opt.DesignRejected, 'current density'):
            solver.prepare((0,)*7)

    def test_adapter_rejects_motorcad_adjusting_requested_geometry(self):
        class Motor:
            def __init__(self): self.values = dict(CurrentDefinition=2, RMSCurrentDensity=7, ScriptAutoRun=0, ScriptAutoRun_PythonClasses=0)
            def load_from_file(self, path): pass
            def get_variable(self, name): return self.values[name]
            def set_variable(self, name, value): self.values[name] = value + .01 if name == 'Ratio_Bore' else value
            def check_if_geometry_is_valid(self, edit): pass
        config = dict(model=str(Path('Basic_Model.mot').resolve()), target_j=7,
                      j_tolerance=1e-6, fixed_parameters=[], expected_current_definition=2,
                      objectives={}, optional_outputs={})
        solver = opt.MotorCADSolver(config, self.folder, mc=Motor())
        with self.assertRaisesRegex(opt.DesignRejected, 'Ratio_Bore'):
            solver.prepare((0,)*7)

    def test_nsga_resume_matches_uninterrupted_design_sequence(self):
        class Solver:
            def prepare(self, indices): self.indices = indices; return {}
            def solve(self):
                x = self.indices
                return dict(average_torque_nm=1+x[0]/1000, power_factor=.5+x[4]/10, efficiency_pct=80+x[5])
        seqs = []
        for name, split in [('full', False), ('resumed', True)]:
            folder = self.folder / name
            with opt.Store(folder, 'synthetic-only') as store:
                e = opt.Evaluator(store, Solver(), 3 if split else 100)
                first = opt.run_nsga2(store, e, population=6, generations=3, seed=19, resume=False)
                if split:
                    self.assertEqual(first['stop_reason'], 'budget')
                    self.assertEqual(store.attempts(), 3)
            if split:
                with opt.Store(folder, 'synthetic-only') as store:
                    opt.run_nsga2(store, opt.Evaluator(store, Solver(), 100), 6, 3, 19, resume=True)
            with opt.Store(folder, 'synthetic-only') as store:
                seqs.append([r['design_key'] for r in store.rows()])
                self.assertTrue(all(r['status'] == 'ok' for r in store.rows()))
        self.assertEqual(seqs[0], seqs[1])
        self.assertGreater(len(seqs[0]), 6)

    def test_analyze_refuses_mixed_fingerprints_and_creates_empty_pareto(self):
        path = self.folder / 'input.csv'
        opt.write_csv(path, [dict(status='failed', config_fingerprint='a'), dict(status='failed', config_fingerprint='b')])
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            opt.analyze_csv(path, self.folder / 'analysis')
        opt.write_csv(path, [dict(status='failed', config_fingerprint='a')])
        result = opt.analyze_csv(path, self.folder / 'analysis')
        self.assertEqual(result['feasible'], 0)
        self.assertTrue((self.folder / 'analysis' / 'pareto.csv').exists())

    def test_doe_resume_preserves_plan_and_total_budget(self):
        class Solver:
            def prepare(self, indices): return {}
            def solve(self): return dict(average_torque_nm=5, power_factor=.9, efficiency_pct=85)
        with opt.Store(self.folder, 'synthetic-only') as store:
            result = opt.run_doe(store, opt.Evaluator(store, Solver(), 2), 5, 17)
            self.assertEqual(result['stop_reason'], 'budget')
            self.assertEqual(store.attempts(), 2)
        with opt.Store(self.folder, 'synthetic-only') as store:
            result = opt.run_doe(store, opt.Evaluator(store, Solver(), 5), 5, 17, resume=True)
            self.assertEqual(result['stop_reason'], 'samples')
            self.assertEqual(store.attempts(), 5)
            self.assertEqual(len(store.rows()), 5)
            with self.assertRaisesRegex(ValueError, 'settings mismatch'):
                opt.run_doe(store, opt.Evaluator(store, Solver(), 5), 6, 17, resume=True)

    def test_actual_j_is_verified_after_solver_not_only_target_input(self):
        import math
        class Motor:
            def __init__(self):
                self.current = 7
                self.values = dict(CurrentDefinition=2, RMSCurrentDensity=7,
                                   ScriptAutoRun=0, ScriptAutoRun_PythonClasses=0,
                                   RmsCurrentCalc=7, Copper_Diameter=2/math.sqrt(math.pi),
                                   ParallelPaths=1, NumberStrandsHand=1, WindingConnection=0, NumberOfWireSizes=1,
                                   torque=10, pf=.9, eff=85)
            def load_from_file(self, path): pass
            def get_variable(self, name): return self.values[name]
            def do_magnetic_calculation(self): self.values['RmsCurrentCalc'] = self.current
        config = dict(model=str(Path('Basic_Model.mot').resolve()), target_j=7,
                      j_tolerance=1e-6, fixed_parameters=['WindingConnection', 'NumberOfWireSizes'], expected_current_definition=2,
                      j_validation=dict(current_parameter='RmsCurrentCalc', tolerance_a_per_mm2=.001),
                      objectives={name: dict(parameter=p) for name, p in zip(opt.OBJECTIVES, ['torque', 'pf', 'eff'])},
                      optional_outputs={})
        mc = Motor()
        solver = opt.MotorCADSolver(config, self.folder, mc=mc)
        result = solver.solve()
        self.assertAlmostEqual(result['actual_j_a_per_mm2'], 7)
        mc.current = 14
        with self.assertRaisesRegex(opt.DesignRejected, 'Calculated current density'):
            solver.solve()

    def test_current_density_validation_refuses_wrong_winding_scope(self):
        config = opt.load_config('motorcad_config.json')
        config['j_validation']['scope'] = 'unsupported delta winding'
        with self.assertRaisesRegex(ValueError, 'J validation'):
            opt.validate_j_scope(dict(WindingConnection=1, NumberOfWireSizes=1), config)

    def test_geometry_transport_failure_can_be_retried_without_spending_fea_first(self):
        class Motor:
            def __init__(self):
                self.fail = True
                self.values = dict(CurrentDefinition=2, RMSCurrentDensity=7, ScriptAutoRun=0,
                                   ScriptAutoRun_PythonClasses=0, torque=10, pf=.9, eff=85)
            def load_from_file(self, path): pass
            def get_variable(self, name): return self.values[name]
            def set_variable(self, name, value): self.values[name] = value
            def do_magnetic_calculation(self): pass
            def check_if_geometry_is_valid(self, edit):
                if self.fail:
                    self.fail = False
                    raise RuntimeError('RPC connection lost')
        config = dict(model=str(Path('Basic_Model.mot').resolve()), target_j=7,
                      j_tolerance=1e-6, fixed_parameters=[], expected_current_definition=2,
                      objectives={name: dict(parameter=p) for name, p in zip(opt.OBJECTIVES, ['torque', 'pf', 'eff'])},
                      optional_outputs={})
        solver = opt.MotorCADSolver(config, self.folder / 'work', mc=Motor())
        with opt.Store(self.folder / 'run', 'synthetic-only') as store:
            first = opt.Evaluator(store, solver, 1).evaluate((0,)*7, 'doe')
            self.assertEqual(first['status'], 'geometry_check_failed')
            self.assertEqual(store.attempts(), 0)
            second = opt.Evaluator(store, solver, 1, retry_failed=True).evaluate((0,)*7, 'doe')
            self.assertEqual(second['status'], 'ok')
            self.assertEqual(store.attempts(), 1)
            self.assertEqual(len(store.rows()), 2)

    def test_analysis_keeps_independent_runs_with_same_local_evaluation_id(self):
        path = self.folder / 'combined.csv'
        rows = [dict(schema_version=1, run_id='run-a', evaluation_id=1, config_fingerprint='same',
                     status='ok', average_torque_nm=10, power_factor=.8, efficiency_pct=90),
                dict(schema_version=1, run_id='run-b', evaluation_id=1, config_fingerprint='same',
                     status='ok', average_torque_nm=11, power_factor=.7, efficiency_pct=91)]
        opt.write_csv(path, rows)
        result = opt.analyze_csv(path, self.folder / 'analysis')
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['pareto'], 2)

    def test_analysis_requires_provenance_and_checks_adjacent_manifest(self):
        import json
        path = self.folder / 'evaluations.csv'
        row = dict(schema_version=1, run_id='a', evaluation_id=1, status='ok',
                   average_torque_nm=10, power_factor=.8, efficiency_pct=90)
        opt.write_csv(path, [row])
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            opt.analyze_csv(path, self.folder / 'analysis')
        row['config_fingerprint'] = 'a'
        opt.write_csv(path, [row])
        (self.folder / 'manifest.json').write_text(json.dumps(dict(fingerprint='other')), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'manifest'):
            opt.analyze_csv(path, self.folder / 'analysis')

    def test_empty_analysis_removes_previously_generated_plots(self):
        path = self.folder / 'evaluations.csv'
        output = self.folder / 'analysis'
        output.mkdir()
        for name in ['objective_pairs.png', 'pareto_3d.png']:
            (output / name).write_bytes(b'old output')
        unrelated = output / 'notes.txt'
        unrelated.write_text('keep this', encoding='utf-8')
        opt.write_csv(path, [dict(schema_version=1, status='failed', config_fingerprint='a')])
        result = opt.analyze_csv(path, output)
        self.assertEqual(result['feasible'], 0)
        self.assertFalse((output / 'objective_pairs.png').exists())
        self.assertFalse((output / 'pareto_3d.png').exists())
        self.assertTrue(unrelated.exists())

    def test_fixed_length_overrides_survive_every_reload(self):
        class Motor:
            def __init__(self): self.values = {}
            def load_from_file(self, path):
                self.values = dict(Stator_Lam_Length=117.839, Rotor_Lam_Length=83.472,
                                   Magnet_Length=83.472, CurrentDefinition=2, RMSCurrentDensity=7,
                                   ScriptAutoRun=0, ScriptAutoRun_PythonClasses=0)
            def save_to_file(self, path): pass
            def get_variable(self, name): return self.values[name]
            def set_variable(self, name, value): self.values[name] = value
            def check_if_geometry_is_valid(self, edit): pass
        lengths = dict(Stator_Lam_Length=100., Rotor_Lam_Length=100., Magnet_Length=100.)
        config = dict(model=str(Path('Basic_Model.mot').resolve()), target_j=7,
                      j_tolerance=1e-6, fixed_parameters=list(lengths), fixed_overrides=lengths,
                      expected_current_definition=2, objectives={}, optional_outputs={})
        mc = Motor()
        solver = opt.MotorCADSolver(config, self.folder, mc=mc)
        self.assertEqual(solver.fixed, lengths)
        for indices in [(0,)*7, (1,)*7]:
            solver.prepare(indices)
            self.assertEqual({key: mc.values[key] for key in lengths}, lengths)
        self.assertEqual(opt.file_hash('Basic_Model.mot'), '1cfee7718f933e65908a5df30da9003786bd7886edc13f0c6db62a0816a41811')

    def test_single_license_lock_excludes_other_run_folders(self):
        path = self.folder / 'shared-license.lock'
        with opt.MotorCADLease(path):
            with self.assertRaisesRegex(RuntimeError, 'Motor-CAD'):
                with opt.MotorCADLease(path): pass
        with opt.MotorCADLease(path): pass

    def test_dedicated_nsga_module_contains_optimizer_and_help_has_no_fea(self):
        import importlib
        import subprocess
        module = importlib.import_module('nsga2_motorcad')
        self.assertEqual(module.run_nsga2.__module__, 'nsga2_motorcad')
        result = subprocess.run([__import__('sys').executable, 'nsga2_motorcad.py', '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--population', result.stdout)

    def test_export_failure_still_closes_owned_motorcad_session(self):
        from unittest.mock import patch
        closed = []
        class Solver:
            def __init__(self, *args): pass
            def check(self): return dict(ready=True)
            def close(self): closed.append(True)
        with patch.object(opt, 'MotorCADSolver', Solver), \
             patch.object(opt, 'environment_signature', return_value={'offline_test': True}), \
             patch.object(opt.Store, 'export', side_effect=OSError('CSV file locked')):
            with self.assertRaisesRegex(OSError, 'CSV file locked'):
                opt.main(['check', '--run-dir', str(self.folder)])
        self.assertEqual(closed, [True])

    def test_time_limit_blocks_new_fea_but_still_allows_cache(self):
        import time
        class Solver:
            def prepare(self, indices): return {}
            def solve(self): return dict(average_torque_nm=10, power_factor=.9, efficiency_pct=85)
        with opt.Store(self.folder, 'synthetic-only') as store:
            opt.Evaluator(store, Solver(), 10).evaluate((0,)*7, 'nsga2')
            e = opt.Evaluator(store, Solver(), 10, deadline=time.monotonic()-1)
            self.assertEqual(e.evaluate((0,)*7, 'nsga2')['cache_hit'], 1)
            with self.assertRaises(opt.TimeBudgetExhausted):
                e.evaluate((1,)*7, 'nsga2')
            self.assertEqual(store.attempts(), 1)

    def test_time_limit_is_rechecked_after_preparation_before_solver(self):
        import time
        class Solver:
            def prepare(self, indices):
                evaluator.deadline = time.monotonic()-1
                return {}
            def solve(self): raise AssertionError('Must not start FEA after deadline')
        with opt.Store(self.folder, 'synthetic-only') as store:
            evaluator = opt.Evaluator(store, Solver(), 10, deadline=time.monotonic()+60)
            with self.assertRaises(opt.TimeBudgetExhausted):
                evaluator.evaluate((0,)*7, 'nsga2')
            self.assertEqual(store.attempts(), 0)

    def test_nsga_time_stop_checkpoints_and_resumes_without_lost_calls(self):
        import time
        class Solver:
            def prepare(self, indices): return {}
            def solve(self): return dict(average_torque_nm=10, power_factor=.9, efficiency_pct=85)
        with opt.Store(self.folder, 'synthetic-only') as store:
            first = opt.run_nsga2(store, opt.Evaluator(store, Solver(), 10, deadline=time.monotonic()-1), 4, 1, 17)
            self.assertEqual(first['stop_reason'], 'wall_time')
            self.assertEqual(store.attempts(), 0)
            second = opt.run_nsga2(store, opt.Evaluator(store, Solver(), 10), 4, 1, 17, resume=True)
            self.assertEqual(second['stop_reason'], 'generations')
            self.assertEqual(store.attempts(), 4)

    def test_vscode_run_without_arguments_starts_optimizer_with_unique_output_folder(self):
        from unittest.mock import patch
        import nsga2_motorcad as runner
        captured = []
        def shared(args, **kwargs):
            captured.append(args)
            return 0
        with patch.object(opt, 'main', side_effect=shared):
            self.assertEqual(runner.main([]), 0)
            self.assertEqual(runner.main([]), 0)
        paths = []
        for args in captured:
            self.assertNotIn('--help', args)
            self.assertEqual(args[args.index('--population')+1], '24')
            self.assertEqual(args[args.index('--max-minutes')+1], '55')
            path = Path(args[args.index('--run-dir')+1])
            self.assertTrue(path.is_absolute())
            self.assertEqual(path.parent, Path(runner.__file__).resolve().parent / 'runs')
            paths.append(path)
        self.assertNotEqual(paths[0], paths[1])


if __name__ == '__main__':
    unittest.main()
