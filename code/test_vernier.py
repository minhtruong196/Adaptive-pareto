import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vernier_model import BOUNDS, make_plan, margins, design_values,clear_auto_mesh
from vernier_optimize import Ledger,run_lock,export_results,objective_arrays,pareto_rows,run_direct,new_messages


BASE=dict(Dshaft='27.6mm',Dsin='72.6mm',Dsout='94.6mm',sta_yoke_thickin='6.1mm',
          slot_d_axin='3.5mm',slot_tipin='4.6mm',slot_d_axout='3.9mm',slot_tipout='3.6mm',
          slot_thickin='7mm',slot_thickout='16.8mm',g='0.7mm',pm_bridin='0.3mm',
          pm_bridout='0.1mm',Ns='6',p='28',Dsout_out='138mm')


class VernierTests(unittest.TestCase):
    def test_negative_torque_is_an_operating_point_rejection_not_a_read_error(self):
        from vernier_model import check_operating_metrics,InvalidOperatingPoint
        with self.assertRaisesRegex(InvalidOperatingPoint,'torque'):
            check_operating_metrics(-.562386,-2.63876,.065285)
        check_operating_metrics(9.6,.864,.352)

    def test_new_campaign_overrides_saved_fill_and_manual_rejects_old_fill(self):
        from apply_vernier_point import build_values
        base=dict(BASE,kfill='0.4')
        self.assertEqual(design_values(base,{})['kfill'],'0.3')
        self.assertEqual(build_values({},base)['kfill'],'0.3')
        with self.assertRaises(ValueError):build_values({'kfill':.4},base)

    def test_preparation_applies_fill_and_computes_current_at_new_density_limit(self):
        from unittest.mock import Mock
        from vernier_model import prepare,number
        base={n:f'{(lo+hi)/2}{unit}' for n,(lo,hi,unit) in BOUNDS.items()}
        base.update(BASE,kfill='0.4',I_rms='1A',Ntc='28',Ntc_out='34')
        live=dict(base)
        design=Mock()
        design.GetVariables.side_effect=lambda:list(live)
        design.GetVariableValue.side_effect=lambda n:live[n]
        def apply(props):
            for item in props[1][2][1:]:live[item[0][5:]]=item[2]
        design.ChangeProperty.side_effect=apply
        design.ValidateDesign.return_value=1
        design.GetChildObject.return_value.GetChildNames.return_value=[]
        editor=design.SetActiveEditor.return_value
        editor.GetModelUnits.return_value='mm'
        editor.GetFaceIDs.return_value=[1]
        editor.GetFaceArea.return_value=100
        desktop=Mock();desktop.GetProjectList.return_value=[]
        project=desktop.OpenProject.return_value
        project.SetActiveDesign.return_value=design
        with tempfile.TemporaryDirectory() as tmp:
            project.GetPath.return_value=tmp
            worker=dict(model=str(Path(tmp)/'worker.aedt'),initialized=True)
            _,_,record=prepare(desktop,worker,dict(base_variables=base),tmp,{},'VM_6_28')
        self.assertEqual(live['kfill'],'0.3')
        self.assertAlmostEqual(number(live['I_rms']),5.5*.3*300/(2*34))
        self.assertAlmostEqual(record['j_out_a_mm2'],5.5)
        self.assertLessEqual(record['j_in_a_mm2'],5.5)
        self.assertEqual(record['kfill'],.3)
        design.Analyze.assert_not_called()

    def test_project_lookup_ignores_global_active_project(self):
        from unittest.mock import Mock
        from vernier_model import open_project
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'worker.aedt'
            desktop=Mock();desktop.GetProjectList.return_value=['worker']
            project=desktop.GetChildObject.return_value
            project.GetPath.return_value=str(target.parent)
            self.assertIs(open_project(desktop,target),project)
            desktop.GetActiveProject.assert_not_called()
            desktop.SetActiveProject.assert_not_called()
            project.GetPath.return_value=str(target.parent/'wrong')
            with self.assertRaisesRegex(ValueError,'expected'):
                open_project(desktop,target)

    def test_operating_limits_are_strict(self):
        from vernier_model import check_operating_metrics,InvalidOperatingPoint
        for torque,eta,pf in [(0,.8,.4),(-1,.8,.4),(1,1,.4),(1,1.2,.4),
                              (1,.8,1),(1,.8,1.1),(1,0,.4),(1,.8,0)]:
            with self.subTest(torque=torque,eta=eta,pf=pf):
                with self.assertRaises(InvalidOperatingPoint):
                    check_operating_metrics(torque,eta,pf)
        check_operating_metrics(.001,.999999,.999999)

    def test_manual_apply_targets_disposable_half_model(self):
        import apply_vernier_point as manual
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'base_half.aedt';target.write_text('half')
            with patch.object(manual,'TARGET_MODEL',target):
                self.assertEqual(manual.target_model(),target.resolve())
            self.assertFalse(manual.RUN_FEA)
            self.assertFalse(manual.SAVE_MODEL)

    def test_half_pool_clones_once_and_reuses_across_campaigns(self):
        from vernier_model import worker_pool,digest
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'base_half.aedt';source.write_text('half model')
            old=root/'worker_01.aedt';old.write_text('old untouched')
            shared=root/'half_pool';shared.mkdir()
            first=worker_pool(shared,source,digest(source),shared/'workers.json',prefix='half_worker')
            second=worker_pool(shared,source,digest(source),shared/'workers.json',prefix='half_worker')
            self.assertEqual(first,second)
            self.assertEqual(len(first['workers']),5)
            self.assertEqual(old.read_text(),'old untouched')
            for w in first['workers']:
                self.assertTrue(Path(w['model']).stem.startswith('half_worker_'))
                self.assertEqual(Path(w['model']).read_text(),'half model')

    def test_manual_point_fills_dependents_and_accepts_partial_input(self):
        from apply_vernier_point import build_values
        values=build_values(dict(Dshaft=32,slot_d_axin=5),BASE)
        self.assertEqual(values['slot_thickin'],'7mm')
        self.assertAlmostEqual(float(values['sta_yoke_thickin'][:-2]),3.9)
        self.assertAlmostEqual(float(values['slot_tipin'][:-2]),3.1)

    def test_manual_point_allows_explicit_dependent_override_but_rejects_typos(self):
        from apply_vernier_point import build_values
        values=build_values(dict(Dshaft=32,sta_yoke_thickin=4,I_rms='7.5A'),BASE)
        self.assertEqual(values['sta_yoke_thickin'],'4mm')
        self.assertEqual(values['I_rms'],'7.5A')
        with self.assertRaises(ValueError):build_values({'Dshfat':32},BASE)
        with self.assertRaises(ValueError):build_values({'Dshaft':'32deg'},BASE)

    def test_ten_point_check_replays_failed_campaign_without_starting_nsga(self):
        import run_vernier_nsga2 as entry
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'base.aedt';source.write_text('test model')
            points=make_plan(12,17,BOUNDS,BASE)
            (root/'plan.json').write_text(json.dumps(dict(settings=dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()),points=points)))
            with patch.object(entry,'MODE','fea_check'),patch.object(entry,'SOURCE_MODEL',source),patch.object(entry,'DIAGNOSTIC_SOURCE_DIR',root),patch('vernier_optimize.run') as run,patch('vernier_optimize.run_direct') as direct:
                entry.main()
                settings=run.call_args.args[0];plan=run.call_args.kwargs['plan_override']
                self.assertEqual(settings['max_fea_calls'],10)
                self.assertTrue(settings['retry_failed'])
                self.assertEqual(settings['mode'],'fea')
                self.assertEqual(plan['points'],points[:10])
                direct.assert_not_called()

    def test_mesh_cleanup_checks_actual_operations_even_after_previous_cleanup(self):
        from unittest.mock import Mock
        design=Mock();mesh=design.GetChildObject.return_value
        mesh.GetChildNames.side_effect=[['Length1','Length2','CylindricalGap1'],['Length1','Length2']]
        self.assertTrue(clear_auto_mesh(design))
        design.GetModule.return_value.DeleteOp.assert_called_once_with(['CylindricalGap1'])

    def test_mesh_cleanup_does_not_delete_unrelated_operations(self):
        from unittest.mock import Mock
        design=Mock();design.GetChildObject.return_value.GetChildNames.return_value=['Length1','Length2']
        self.assertFalse(clear_auto_mesh(design))
        design.GetModule.return_value.DeleteOp.assert_not_called()

    def test_inner_winding_requires_more_than_one_mm(self):
        p={n:(lo+hi)/2 for n,(lo,hi,_) in BOUNDS.items()}
        # 29 - 8.1 - (13.8 + 6.1) = 1 mm; shaft/yoke coupling preserves the sum.
        p['Dsin']=58
        self.assertAlmostEqual(margins(p,BASE)['inner_winding_mm'],0)
        p['Dsin']=57
        self.assertLess(margins(p,BASE)['inner_winding_mm'],0)
        p['Dsin']=59
        self.assertGreater(margins(p,BASE)['inner_winding_mm'],0)

    def test_outer_winding_requires_more_than_one_mm(self):
        p={n:(lo+hi)/2 for n,(lo,hi,_) in BOUNDS.items()}
        p.update(Dsout=108,sta_yoke_thickout=6.5)
        # 69 - 6.5 - 54 - 7.5 = 1 mm: equality must be rejected.
        self.assertAlmostEqual(margins(p,BASE)['outer_winding_mm'],0)
        p['Dsout']=109
        self.assertLess(margins(p,BASE)['outer_winding_mm'],0)
        p['Dsout']=107
        self.assertGreater(margins(p,BASE)['outer_winding_mm'],0)

    def test_inner_winding_does_not_intrude_into_split_tooth(self):
        p={n:(lo+hi)/2 for n,(lo,hi,_) in BOUNDS.items()}
        p.update(Dsin=90,Dsout=105,slot_d_axin=7.1,slot_ang_axin=29)
        m=margins(p,BASE)
        self.assertLess(m['inner_split_tooth_clearance_mm'],0)
        self.assertTrue(all(v>0 for n,v in m.items() if n!='inner_split_tooth_clearance_mm'))
        p['slot_ang_axin']=5
        self.assertGreater(margins(p,BASE)['inner_split_tooth_clearance_mm'],0)

    def test_split_tooth_cosine_uses_degrees_and_correct_parentheses(self):
        p={n:(lo+hi)/2 for n,(lo,hi,_) in BOUNDS.items()}
        p.update(Dsin=72.6,slot_d_axin=3.5,slot_ang_axin=14.8)
        expected=72.6/2-(72.6/2-3.5-4.6)/math.cos(math.radians(14.8))-3.5
        self.assertAlmostEqual(margins(p,BASE)['inner_split_tooth_clearance_mm'],expected)

    def test_geometry_mode_does_not_start_nsga_or_fea(self):
        import run_vernier_nsga2 as entry
        with patch.object(entry,'MODE','geometry'),patch('vernier_optimize.run') as geometry,patch('vernier_optimize.run_direct') as direct:
            entry.main()
            settings=geometry.call_args.args[0]
            self.assertEqual(settings['mode'],'geometry')
            self.assertEqual(settings['samples'],100)
            self.assertEqual(settings['run_dir'].name,'vernier_half_geometry_kfill03')
            direct.assert_not_called()

    def test_reused_worker_does_not_reuse_old_completion_or_lose_new_errors(self):
        old=['old warning','old completion','another old warning']
        self.assertEqual(new_messages(old+['new completion'],old),['new completion'])
        self.assertEqual(new_messages(['new error'],old),['new error'])

    def test_direct_checkpoint_resume_keeps_exact_pending_population(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'base.aedt'
            source.write_text('\n'.join(f"VariableProp('{n}', 'UD', '', '{v}')" for n,v in BASE.items()))
            settings=dict(source=source,run_dir=root/'direct',bounds=BOUNDS,population=6,
                          generations=3,seed=17,max_fea_calls=18,workers=5)
            seen=[]
            def interrupted(points):
                seen.extend(points);raise KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):run_direct(settings,interrupted)
            first=[]
            def fake(points):
                if not first:first.extend(points)
                return [dict(status='ok',average_torque_nm=10+p['d_pm'],
                    power_factor=.3+p['k_w_axin']/10,efficiency_pct=80+p['k_w_axout']) for p in points]
            result=run_direct(settings,fake)
            self.assertEqual(seen,first)
            self.assertEqual(result['completed_generations'],3)
            with patch('vernier_optimize.run',side_effect=AssertionError('must not evaluate a completed run')):
                resumed=run_direct(settings,lambda _:self.fail('completed run evaluated again'))
            self.assertEqual(resumed['completed_generations'],3)

    def test_direct_nsga_uses_fea_objectives_and_excludes_failures(self):
        rows=[dict(status='ok',average_torque_nm=9,power_factor=.4,efficiency_pct=87),
              dict(status='solve_failed',error='mesh')]
        f,g=objective_arrays(rows)
        self.assertEqual(f[0].tolist(),[-9,-.4,-87])
        self.assertEqual(g[:,0].tolist(),[0,1])
        self.assertNotIn('average_torque_nm',rows[1])

    def test_baseline_pareto_is_only_nondominated_valid_fea(self):
        rows=[dict(id=1,status='ok',average_torque_nm=9,power_factor=.4,efficiency_pct=87),
              dict(id=2,status='ok',average_torque_nm=8,power_factor=.3,efficiency_pct=86),
              dict(id=3,status='ok',average_torque_nm=7,power_factor=.5,efficiency_pct=89),
              dict(id=4,status='solve_failed')]
        self.assertEqual([r['id'] for r in pareto_rows(rows)],[1,3])

    def test_vscode_entry_passes_settings_without_starting_ansys_on_import(self):
        import run_vernier_nsga2 as entry
        with patch.object(entry,'MODE','nsga2'),patch('vernier_optimize.run_direct') as launch:
            entry.main()
            settings=launch.call_args.args[0]
            self.assertEqual(settings['workers'],5)
            self.assertEqual(settings['population'],40)
            self.assertEqual(settings['generations'],20)
            self.assertEqual(settings['max_fea_calls'],800)
            self.assertEqual(settings['run_dir'].name,'nsga2_vernier_half_kfill03')
            self.assertEqual(settings['source'].name,'base_half.aedt')
            self.assertEqual(settings['worker_prefix'],'half_worker_v5')
            self.assertNotIn('vernier_pilot',str(settings['legacy_workers']))

    def test_excel_export_preserves_numeric_results_and_failure_blanks(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Ledger(Path(tmp),'same',[{'slot_thickin':3.0},{'slot_thickin':12.0}])
            ledger.finish(1,'ok',dict(average_torque_nm=9.5,power_factor=.35,efficiency_pct=86.4))
            ledger.finish(2,'preparation_failed',dict(error='bad geometry'))
            export_results(ledger)
            wb=load_workbook(Path(tmp)/'results.xlsx',read_only=True,data_only=True)
            rows=list(wb['Results'].values);head=rows[0]
            self.assertEqual(wb.sheetnames,['Results','Waveforms'])
            self.assertEqual(rows[1][head.index('average_torque_nm')],9.5)
            self.assertIsNone(rows[2][head.index('average_torque_nm')])
            wb.close();ledger.close()

    def test_second_runner_cannot_acquire_same_pool(self):
        with tempfile.TemporaryDirectory() as tmp:
            with run_lock(tmp):
                with self.assertRaises(RuntimeError):
                    with run_lock(tmp):pass

    def test_doe_reproducible_unique_and_feasible(self):
        points=make_plan(50,17,BOUNDS,BASE)
        self.assertEqual(points,make_plan(50,17,BOUNDS,BASE))
        self.assertEqual(len({json.dumps(p,sort_keys=True) for p in points}),50)
        self.assertTrue(all(min(margins(p,BASE).values())>0 for p in points))

    def test_reset_and_reference_coupling(self):
        first=design_values(BASE,{'Dshaft':'32mm','slot_thickin':'3mm'})
        next_point=design_values(BASE,{'slot_thickout':'5mm'})
        self.assertAlmostEqual(float(first['sta_yoke_thickin'][:-2]),3.9)
        self.assertEqual(next_point['slot_thickin'],'7mm')
        self.assertEqual(next_point['Dshaft'],'27.6mm')
        self.assertAlmostEqual(float(next_point['slot_tipin'][:-2]),4.6)

    def test_magnet_overlap_rejected(self):
        p={n:(lo+hi)/2 for n,(lo,hi,_) in BOUNDS.items()}
        p.update(Dsin=90,Dsout=80)
        self.assertLess(margins(p,BASE)['magnet_radial_mm'],0)

    def test_resume_does_not_queue_success_or_failure_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Ledger(Path(tmp),'same', [{'x':1},{'x':2},{'x':3}])
            ledger.finish(1,'ok',{'average_torque_nm':9.0})
            ledger.finish(2,'solve_failed',{'error':'mesh'})
            ledger.close()
            again=Ledger(Path(tmp),'same',[{'x':1},{'x':2},{'x':3}])
            self.assertEqual(again.pending(),[3])
            self.assertEqual(again.pending(retry_failed=True),[2,3])
            again.close()

    def test_changed_settings_refuse_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            Ledger(Path(tmp),'old',[{'x':1}]).close()
            with self.assertRaisesRegex(ValueError,'fingerprint'):
                Ledger(Path(tmp),'changed',[{'x':1}])

    def test_interrupted_attempt_is_retained_and_queued(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Ledger(Path(tmp),'same',[{'x':1}])
            attempt=ledger.start(1,1,{'point':1})
            ledger.mark_solving(attempt)
            ledger.close()
            again=Ledger(Path(tmp),'same',[{'x':1}])
            self.assertEqual(again.pending(),[1])
            self.assertEqual(again.db.execute('SELECT status FROM attempts').fetchone()[0],'interrupted')
            self.assertEqual(again.solver_calls(),1)
            again.close()


if __name__=='__main__':unittest.main()
