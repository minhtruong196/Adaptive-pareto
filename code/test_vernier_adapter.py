"""Offline FEA-adapter regression tests: no COM server or solver is started."""
import json
import sqlite3
from contextlib import closing
import math
import tempfile
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

import vernier_model as model
import vernier_optimize as adapter


BASE = dict(Dshaft='27.6mm', Dsin='72.6mm', Dsout='94.6mm',
            sta_yoke_thickin='6.1mm', slot_d_axin='3.5mm', slot_tipin='4.6mm',
            slot_d_axout='3.9mm', slot_tipout='3.6mm', slot_thickin='7mm',
            slot_thickout='16.8mm', sta_yoke_thickout='6mm', k_w_axin='.5',
            k_w_axout='.3', slot_ang_axin='16deg', slot_ang_axout='49deg',
            d_pm='4mm', g='.7mm', pm_bridin='.2mm', pm_bridout='.2mm',
            Ns='6', p='28', Dsout_out='138mm', kfill='.4', I_rms='1A',
            Ntc='28', Ntc_out='34', fs='210Hz', Ip='I_rms * sqrt(2)')


def write_source(path, values=None):
    values = BASE if values is None else values
    path.write_text("Product='ElectronicsDesktop'\nVersion(2024, 1)\nName='VM_6_28'\n" +
                    '\n'.join(f"VariableProp('{n}', 'UD', '', '{v}')" for n, v in values.items()),
                    encoding='utf-8')
    return path


class GeometryTests(unittest.TestCase):
    def test_point_resets_fill_and_preserves_three_coupling_anchors(self):
        values = model.design_values(BASE, dict(Dshaft=32, slot_d_axin=5, slot_d_axout=6))
        self.assertEqual(values['kfill'], '0.3')
        self.assertAlmostEqual(model.number(values['sta_yoke_thickin']), 3.9)
        self.assertAlmostEqual(model.number(values['slot_tipin']), 3.1)
        self.assertAlmostEqual(model.number(values['slot_tipout']), 1.5)
        self.assertEqual(model.design_values(BASE, {})['Dshaft'], '27.6mm')

    def test_magnet_width_reserve_is_point_one_mm_in_d_pm(self):
        point = dict(Dsin=72.6, d_pm=8.237797552608217)
        self.assertAlmostEqual(model.margins(point, BASE)['magnet_width_reserve_mm'], 0, places=10)
        point['d_pm'] += .01
        self.assertLess(model.margins(point, BASE)['magnet_width_reserve_mm'], 0)

    def test_winding_clearance_strictly_exceeds_one_mm(self):
        self.assertAlmostEqual(model.margins(dict(Dsin=58), BASE)['inner_winding_mm'], 0)
        self.assertAlmostEqual(model.margins(dict(Dsout=108, sta_yoke_thickout=6.5), BASE)['outer_winding_mm'], 0)
        self.assertLess(model.margins(dict(Dsin=57), BASE)['inner_winding_mm'], 0)

    def test_feasible_doe_is_deterministic_unique_and_in_narrow_domain(self):
        points = model.make_plan(40, 17, model.BOUNDS, BASE)
        self.assertEqual(points, model.make_plan(40, 17, model.BOUNDS, BASE))
        self.assertEqual(len({json.dumps(p, sort_keys=True) for p in points}), 40)
        for point in points:
            self.assertTrue(all(lo <= point[n] <= hi for n, (lo, hi, _) in model.BOUNDS.items()))
            self.assertTrue(.30 <= point['k_w_axin'] <= .80)
            self.assertTrue(66 <= point['Dsin'] <= 80)
            self.assertGreater(min(model.margins(point, BASE).values()), 0)

    def test_identity_ignores_saved_point_but_detects_fixed_and_anchor_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = write_source(Path(tmp) / 'source.aedt')
            initial = model.model_identity(source)
            changed = dict(BASE, **model.design_values(BASE, dict(Dshaft=32, slot_d_axin=5, d_pm=6)))
            write_source(source, changed)
            self.assertEqual(model.model_identity(source), initial)
            changed['g'] = '.8mm'
            write_source(source, changed)
            self.assertNotEqual(model.model_identity(source), initial)
            changed = dict(BASE, slot_tipin='4.7mm')
            write_source(source, changed)
            self.assertNotEqual(model.model_identity(source), initial)

    def test_new_worker_pool_clones_source_and_reuses_configuration_not_raw_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = write_source(root / 'source.aedt')
            raw = source.read_bytes()
            pool = model.worker_pool(root / 'pool', source, model.digest(source), root / 'legacy.json')
            self.assertEqual(len(pool['workers']), 5)
            self.assertTrue(all(Path(w['model']).read_bytes() == raw for w in pool['workers']))
            write_source(source, dict(BASE, **model.design_values(BASE, dict(Dshaft=32))))
            reused = model.worker_pool(root / 'pool', source, model.digest(source), root / 'legacy.json')
            self.assertEqual(reused, pool)
            self.assertTrue(all(Path(w['model']).read_bytes() == raw for w in pool['workers']))
            write_source(source, dict(BASE, g='.8mm'))
            with self.assertRaisesRegex(ValueError, 'configuration'):
                model.worker_pool(root / 'pool', source, model.digest(source), root / 'legacy.json')

    def test_project_path_binding_rejects_same_name_owned_elsewhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'worker.aedt'
            desktop = Mock()
            desktop.GetProjectList.return_value = ['worker']
            project = desktop.GetChildObject.return_value
            project.GetPath.return_value = tmp
            self.assertIs(model.open_project(desktop, target), project)
            project.GetPath.return_value = str(Path(tmp) / 'another')
            with self.assertRaisesRegex(ValueError, 'path mismatch'):
                model.open_project(desktop, target)
            desktop.GetActiveProject.assert_not_called()

    def test_mesh_cleanup_uses_presence_and_preserves_other_operations(self):
        design = Mock()
        design.GetChildObject.return_value.GetChildNames.side_effect = [
            ['Length1', 'CylindricalGap1'], ['Length1']]
        self.assertTrue(model.clear_auto_mesh(design))
        design.GetModule.return_value.DeleteOp.assert_called_once_with(['CylindricalGap1'])
        design.GetChildObject.return_value.GetChildNames.side_effect = None
        design.GetChildObject.return_value.GetChildNames.return_value = ['Length1']
        self.assertFalse(model.clear_auto_mesh(design))

    def test_preparation_recomputes_cad_area_and_enforces_fill_and_current_density(self):
        live = dict(BASE)
        design = Mock()
        design.GetVariables.side_effect = lambda: list(live)
        design.GetVariableValue.side_effect = lambda n: live[n]
        def change(properties):
            for entry in properties[1][2][1:]:
                live[entry[0][5:]] = entry[2]
        design.ChangeProperty.side_effect = change
        design.ValidateDesign.return_value = 1
        design.GetChildObject.return_value.GetChildNames.return_value = []
        editor = design.SetActiveEditor.return_value
        editor.GetModelUnits.return_value = 'mm'
        editor.GetFaceIDs.return_value = [1]
        editor.GetFaceArea.return_value = 100
        desktop = Mock()
        desktop.GetProjectList.return_value = []
        project = desktop.OpenProject.return_value
        project.SetActiveDesign.return_value = design
        with tempfile.TemporaryDirectory() as tmp:
            project.GetPath.return_value = tmp
            worker = dict(model=str(Path(tmp) / 'worker.aedt'), initialized=True)
            _, _, record = model.prepare(desktop, worker, dict(base_variables=BASE), tmp, {}, 'VM_6_28')
        self.assertEqual(live['kfill'], '0.3')
        self.assertAlmostEqual(record['i_rms_a'], 5.5 * .3 * 300 / 68)
        self.assertAlmostEqual(record['j_out_a_mm2'], 5.5)
        self.assertLess(record['j_in_a_mm2'], 5.5)
        design.Analyze.assert_not_called()


class LedgerTests(unittest.TestCase):
    def test_growing_plan_is_append_only_and_points_stay_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = adapter.Ledger(tmp, 'fp', [{'x': 1}])
            ledger.finish(1, 'ok', {'average_torque_nm': 2})
            ledger.close()
            ledger = adapter.Ledger(tmp, 'fp', [{'x': 1}, {'x': 2}])
            self.assertEqual(ledger.pending(), [2])
            self.assertEqual(json.loads(ledger.db.execute('SELECT point FROM points WHERE id=1').fetchone()[0]), {'x': 1})
            ledger.close()
            with self.assertRaisesRegex(ValueError, 'plan'):
                adapter.Ledger(tmp, 'fp', [{'x': 1}])
            with self.assertRaisesRegex(ValueError, 'plan'):
                adapter.Ledger(tmp, 'fp', [{'x': 3}, {'x': 2}])

    def test_interrupted_preparation_and_solve_are_terminal_even_with_retry_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = adapter.Ledger(tmp, 'fp', [{'x': 1}, {'x': 2}, {'x': 3}])
            ledger.start(1, 1, {})
            aid = ledger.start(2, 2, {})
            ledger.mark_solving(aid)
            ledger.close()
            ledger = adapter.Ledger(tmp, 'fp', [{'x': 1}, {'x': 2}, {'x': 3}])
            self.assertEqual(ledger.pending(retry_failed=True), [3])
            self.assertEqual(ledger.solver_calls(), 1)
            self.assertEqual(ledger.db.execute('SELECT status FROM points ORDER BY id').fetchall(),
                             [('interrupted',), ('interrupted',), ('pending',)])
            ledger.close()

    def test_solver_budget_and_duplicate_starts_are_rejected_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = adapter.Ledger(tmp, 'fp', [{'x': 1}, {'x': 2}])
            aid = ledger.start(1, 1, {})
            ledger.mark_solving(aid, max_calls=1)
            with self.assertRaises(ValueError):
                ledger.mark_solving(aid, max_calls=2)
            with self.assertRaises(ValueError):
                ledger.start(1, 2, {})
            second = ledger.start(2, 2, {})
            with self.assertRaisesRegex(RuntimeError, 'budget'):
                ledger.mark_solving(second, max_calls=1)
            self.assertEqual(ledger.solver_calls(), 1)
            ledger.close()

    def test_second_runner_cannot_acquire_same_pool_and_release_allows_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            with adapter.run_lock(tmp):
                with self.assertRaises(RuntimeError):
                    with adapter.run_lock(tmp):
                        self.fail('duplicate lock acquired')
            with adapter.run_lock(tmp):
                pass

    def test_export_keeps_failures_blank_and_pareto_uses_actual_valid_only(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as tmp:
            ledger = adapter.Ledger(tmp, 'fp', [{'x': 1}, {'x': 2}, {'x': 3}])
            ledger.finish(1, 'ok', dict(average_torque_nm=9, power_factor=.4, efficiency_pct=87))
            ledger.finish(2, 'preparation_failed', {'error': 'CAD'})
            ledger.finish(3, 'ok', dict(average_torque_nm=8, power_factor=.3, efficiency_pct=86))
            adapter.export_results(ledger)
            adapter.export_pareto(tmp)
            wb = load_workbook(Path(tmp) / 'results.xlsx', read_only=True, data_only=True)
            rows = list(wb['Results'].values)
            self.assertIsNone(rows[2][rows[0].index('average_torque_nm')])
            self.assertEqual(json.loads((Path(tmp) / 'pareto.json').read_text())['pareto'][0]['point_id'], 1)
            self.assertEqual(len(json.loads((Path(tmp) / 'pareto.json').read_text())['pareto']), 1)
            wb.close()
            ledger.close()


class WaveformTests(unittest.TestCase):
    def test_postprocessing_uses_si_last_cycle_and_time_mean_efficiency(self):
        # First cycle differs deliberately; angular speed is 20 rad/s, not rpm.
        times = np.linspace(0, .02, 401)
        phase = 2 * np.pi * 100 * times
        currents = 2 ** .5 * 2 * np.sin(phase)
        voltage = 2 ** .5 * 100 * np.sin(phase)
        torque = np.where(times < .01, 50., 4. + np.sin(phase))
        pout = torque * 20
        eff = .7 + .1 * np.cos(phase)
        traces = {'Moving1.Torque': torque, 'Moving1.Speed': times * 0 + 20,
                  'eff': eff, 'PF': times * 0 + .5, 'Pin': times * 0 + 300,
                  'Pout': pout, 'p_cu': times * 0 + 5, 'CoreLoss': times * 0 + 2,
                  'SolidLoss': times * 0 + 1, 'Js_in': times * 0 + 5,
                  'Js_out': times * 0 + 5.5}
        for index, phase_name in enumerate('ABC', 1):
            traces[f'U_ter{index}'] = voltage
            traces[f'InputCurrent(Phase_{phase_name})'] = currents
        data = Mock()
        data.GetSweepValues.return_value = times
        data.GetRealDataValues.side_effect = lambda name, si: traces[name] if si else self.fail('non-SI request')
        data.GetDataUnits.return_value = 'SI'
        design = Mock()
        design.GetVariableValue.return_value = '100Hz'
        design.GetModule.return_value.GetSolutionDataPerVariation.return_value = [data]
        record = dict(i_rms_a=2, j_in_a_mm2=5, j_out_a_mm2=5.5)
        model.read_solution(design, record)
        self.assertAlmostEqual(record['average_torque_nm'], 4)
        self.assertAlmostEqual(record['power_factor'], .5)
        self.assertAlmostEqual(record['efficiency_pct'], 70)
        self.assertAlmostEqual(record['speed_rad_s'], 20)
        self.assertAlmostEqual(record['time_start_s'], .01)
        self.assertNotAlmostEqual(record['efficiency_ratio_of_means_pct'], 70)
        with self.assertRaises(model.InvalidOperatingPoint):
            model.check_operating_metrics(0, .7, .5)


class ControllerTests(unittest.TestCase):
    def fixture(self, root, count=5, budget=3):
        source = write_source(root / 'source.aedt')
        points = model.make_plan(count, 17, model.BOUNDS, BASE)
        settings = dict(source=source, run_dir=root / 'run', worker_pool_dir=root / 'pool',
                        workers=2, mode='fea', samples=count, seed=17, bounds=model.BOUNDS,
                        design='VM_6_28', max_fea_calls=budget, timeout_minutes=1)
        plan = dict(fingerprint='fp', settings={'fixed_protocol': 1}, points=points)
        desktop = Mock()
        desktop.AreThereSimulationsRunning.return_value = False
        desktop.GetMessages.side_effect = lambda name, design, level: (
            [] if name not in launched else ['Normal completion of simulation'])
        launched = set()
        def prepare(desktop, worker, pool, pool_folder, point, design_name):
            project = Mock()
            name = Path(worker['model']).stem
            project.GetName.return_value = name
            design = Mock()
            design.Analyze.side_effect = lambda setup, blocking: launched.add(name)
            # Real Ansys queues are per-project: old messages are captured first.
            launched.discard(name)
            return project, design, dict(i_rms_a=2)
        def read(design, record):
            record.update(average_torque_nm=4, power_factor=.5, efficiency_pct=70)
            names = ['Moving1.Torque', 'Moving1.Speed', 'eff', 'PF', 'Pin', 'Pout',
                     'p_cu', 'CoreLoss', 'SolidLoss', 'U_ter1', 'U_ter2', 'U_ter3',
                     'InputCurrent(Phase_A)', 'InputCurrent(Phase_B)', 'InputCurrent(Phase_C)',
                     'Js_in', 'Js_out']
            return np.array([0, 1]), {n: np.array([1., 1.]) for n in names}
        client = types.ModuleType('win32com.client')
        client.Dispatch = Mock()
        client.Dispatch.return_value.GetAppDesktop.return_value = desktop
        package = types.ModuleType('win32com')
        package.client = client
        return settings, plan, client, {'win32com': package, 'win32com.client': client}, prepare, read

    def test_run_budget_is_cumulative_and_completed_or_budget_resume_never_dispatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings, plan, client, modules, prepare, read = self.fixture(Path(tmp))
            with patch.dict(sys.modules, modules), patch.object(adapter, 'prepare', prepare), patch.object(adapter, 'read_solution', read):
                outcome = adapter.run(settings, plan)
                self.assertEqual(outcome, dict(stopped=True, reason='budget'))
                client.Dispatch.reset_mock()
                self.assertEqual(adapter.run(settings, plan), outcome)
                client.Dispatch.assert_not_called()
            ledger = adapter.Ledger(settings['run_dir'], 'fp', plan['points'])
            self.assertEqual(ledger.solver_calls(), 3)
            self.assertEqual(ledger.pending(), [4, 5])
            ledger.close()

    def test_complete_plan_accepts_new_raw_source_provenance_but_rejects_configuration_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings, plan, client, modules, prepare, read = self.fixture(Path(tmp), 1, 1)
            plan['settings']['source_sha256'] = 'old-source-bytes'
            settings['run_dir'].mkdir(parents=True)
            model.atomic_json(settings['run_dir'] / 'plan.json', plan)
            ledger = adapter.Ledger(settings['run_dir'], 'fp', plan['points'])
            ledger.finish(1, 'ok', dict(average_torque_nm=4, power_factor=.5, efficiency_pct=70))
            ledger.close()
            resumed = dict(plan, settings=dict(plan['settings'], source_sha256='new-source-bytes'))
            with patch.dict(sys.modules, modules):
                self.assertEqual(adapter.run(settings, resumed), dict(stopped=False, reason=None))
                client.Dispatch.assert_not_called()
                changed = dict(resumed, settings=dict(resumed['settings'], fixed_protocol=2))
                with self.assertRaisesRegex(ValueError, 'archive changed'):
                    adapter.run(settings, changed)
                client.Dispatch.assert_not_called()

    def test_real_adapter_appends_stage_after_json_roundtrip_of_tuple_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings, plan, client, modules, prepare, read = self.fixture(Path(tmp), 3, 3)
            plan['settings']['bounds'] = dict(model.BOUNDS)
            first = dict(plan, points=plan['points'][:1])
            with patch.dict(sys.modules, modules), patch.object(adapter, 'prepare', prepare), patch.object(adapter, 'read_solution', read):
                adapter.run(settings, first)
                adapter.run(settings, plan)
                client.Dispatch.reset_mock()
                adapter.run(settings, plan)
                client.Dispatch.assert_not_called()
                changed = dict(plan, settings=dict(plan['settings'], bounds=dict(model.BOUNDS, d_pm=(3, 6, 'mm'))))
                with self.assertRaisesRegex(ValueError, 'archive changed'):
                    adapter.run(settings, changed)
            with closing(sqlite3.connect(settings['run_dir']/'evaluations.sqlite')) as db:
                self.assertEqual(db.execute('SELECT SUM(fea_started) FROM attempts').fetchone()[0], 3)
                self.assertEqual(db.execute('SELECT point_id,COUNT(*) FROM attempts GROUP BY point_id').fetchall(), [(1,1),(2,1),(3,1)])

    def test_keyboard_interrupt_during_preparation_consumes_slot_without_solver_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings, plan, client, modules, prepare, read = self.fixture(Path(tmp), 2, 2)
            with patch.dict(sys.modules, modules), patch.object(adapter, 'prepare', side_effect=KeyboardInterrupt):
                self.assertEqual(adapter.run(settings, plan), dict(stopped=True, reason='user'))
            ledger = adapter.Ledger(settings['run_dir'], 'fp', plan['points'])
            self.assertEqual(ledger.pending(retry_failed=True), [2])
            self.assertEqual(ledger.solver_calls(), 0)
            self.assertEqual(ledger.db.execute('SELECT status FROM points WHERE id=1').fetchone()[0], 'interrupted')
            ledger.close()

    def test_second_interrupt_terminalizes_active_attempt_without_closing_owned_solve(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings, plan, client, modules, prepare, read = self.fixture(Path(tmp), 2, 2)
            desktop = client.Dispatch.return_value.GetAppDesktop.return_value
            desktop.GetMessages.side_effect = [[], KeyboardInterrupt()]
            def interrupted(*args):
                project, design, extra = prepare(*args)
                design.Analyze.side_effect = KeyboardInterrupt
                return project, design, extra
            with patch.dict(sys.modules, modules), patch.object(adapter, 'prepare', interrupted):
                with self.assertRaises(KeyboardInterrupt):
                    adapter.run(settings, plan)
            desktop.CloseProject.assert_not_called()
            ledger = adapter.Ledger(settings['run_dir'], 'fp', plan['points'])
            self.assertEqual(ledger.pending(), [2])
            self.assertEqual(ledger.solver_calls(), 1)
            self.assertEqual(ledger.db.execute('SELECT status FROM attempts').fetchone()[0], 'interrupted')
            ledger.close()


if __name__ == '__main__':
    unittest.main()
