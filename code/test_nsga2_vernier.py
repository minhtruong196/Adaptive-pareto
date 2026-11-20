"""Offline NSGA-II orchestration checks; never launch Ansys."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import nsga2_vernier as nsga
from vernier_optimize import Ledger
from vernier_model import BOUNDS, margins, source_variables
from vernier_protocol import point_key


class NsgaVernierTests(unittest.TestCase):
    def config(self, folder, budget=13):
        return nsga.settings(run_dir=Path(folder)/'run', budget=budget, dry_run=True)

    def test_default_matches_campaign_domain_and_has_separate_dry_folder(self):
        c=nsga.settings()
        self.assertEqual(c['bounds'], BOUNDS)
        self.assertEqual(c['max_fea_calls'],800)
        self.assertNotEqual(c['run_dir'],nsga.settings(dry_run=True)['run_dir'])

    def test_nondivisible_budget_feasible_unique_and_idempotent_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=self.config(tmp)
            result=nsga.main(config=c, population=4)
            self.assertEqual(result['evaluation_slots'],13)
            self.assertEqual(result['solver_attempts'],0)
            plan=json.loads((c['run_dir']/'plan.json').read_text())
            self.assertEqual(len({point_key(p) for p in plan['points']}),13)
            base=source_variables(c['source'])
            self.assertTrue(all(min(margins(p,base).values())>1e-8 for p in plan['points']))
            again=nsga.main(config=c,population=4,resume=True)
            self.assertEqual(result,again)
            with self.assertRaisesRegex(ValueError,'mismatch|fingerprint'):
                nsga.main(config=dict(c,max_fea_calls=14,samples=14),population=4,resume=True)

    def test_exact_milestone_does_not_change_ga_trajectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=self.config(Path(tmp)/'a',17);b=self.config(Path(tmp)/'b',17)
            a['milestones']=[6];b['milestones']=[]
            nsga.main(config=a,population=4)
            nsga.main(config=b,population=4)
            snap=json.loads((a['run_dir']/'checkpoints'/'006'/'performance.json').read_text())
            self.assertEqual(snap['evaluation_slots'],6)
            self.assertTrue(snap['synthetic'])
            self.assertEqual(snap['actual_solver_calls'],0)
            self.assertEqual(json.loads((a['run_dir']/'plan.json').read_text())['points'],
                             json.loads((b['run_dir']/'plan.json').read_text())['points'])

    def test_interrupted_pending_generation_resumes_without_repeating(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=self.config(Path(tmp)/'a');b=self.config(Path(tmp)/'b')
            original=nsga.VernierEvaluator.evaluate_many
            calls=[0]
            def interrupted(evaluator,*args):
                rows=original(evaluator,*args);calls[0]+=1
                if calls[0]==2:raise KeyboardInterrupt
                return rows
            with patch.object(nsga.VernierEvaluator,'evaluate_many',interrupted):
                with self.assertRaises(KeyboardInterrupt):nsga.main(config=a,population=4)
            nsga.main(config=a,population=4,resume=True)
            nsga.main(config=b,population=4)
            self.assertEqual(json.loads((a['run_dir']/'plan.json').read_text())['points'],
                             json.loads((b['run_dir']/'plan.json').read_text())['points'])

    def test_failed_slots_are_not_refilled_or_used_in_hv(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=self.config(tmp)
            def fail(points):return [dict(status='solve_failed') for p in points]
            result=nsga.main(config=c,population=4,evaluate_batch=fail)
            self.assertEqual(result['evaluation_slots'],13)
            report=json.loads((c['run_dir']/'performance.json').read_text())
            self.assertEqual(report['valid_designs'],0)
            self.assertEqual(report['hv']['archive'],0)
            self.assertEqual(report['statuses'],{'solve_failed':13})

    def test_physical_adapter_batches_stop_exactly_at_milestone_and_count_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=self.config(tmp);c.update(dry_run=False,milestones=[6])
            sizes=[]
            def fake_fea(config,plan_override):
                sizes.append(len(plan_override['points']))
                ledger=Ledger(config['run_dir'],plan_override['fingerprint'],plan_override['points'])
                try:
                    for i in ledger.pending():
                        aid=ledger.start(i,1,{})
                        ledger.mark_solving(aid,max_calls=config['max_fea_calls'])
                        ledger.finish(i,'ok',dict(average_torque_nm=4.,power_factor=.7,efficiency_pct=90.),aid)
                    nsga.export_results(ledger)
                finally:ledger.close()
                return dict(stopped=False)
            with patch.object(nsga,'run_fea',side_effect=fake_fea):
                result=nsga.main(config=c,population=4)
            self.assertEqual(result['solver_attempts'],13)
            self.assertIn(6,sizes)
            snap=json.loads((c['run_dir']/'checkpoints'/'006'/'performance.json').read_text())
            self.assertEqual(snap['actual_solver_calls'],6)
            comparison=json.loads((c['run_dir']/'comparison.json').read_text())['rows']
            self.assertEqual({r['method'] for r in comparison},{'ann','adaptive','nsga2'})
            self.assertAlmostEqual(snap['hv']['archive'],.4*.7*.9)

    def test_resume_recovers_snapshot_after_interruption_at_milestone(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=self.config(tmp);c['milestones']=[6]
            original=nsga.VernierStore.report
            def interrupt(store,destination=None,limit=None):
                if limit==6:raise KeyboardInterrupt
                return original(store,destination,limit)
            with patch.object(nsga.VernierStore,'report',interrupt):
                with self.assertRaises(KeyboardInterrupt):nsga.main(config=c,population=4)
            nsga.main(config=c,population=4,resume=True)
            snap=c['run_dir']/'checkpoints'/'006'/'performance.json'
            self.assertTrue(snap.exists())
            self.assertEqual(json.loads(snap.read_text())['evaluation_slots'],6)

    def test_resume_finishes_all_snapshot_files_after_partial_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=self.config(tmp);c['milestones']=[6]
            original=nsga.atomic_json
            def interrupt(path,data):
                if Path(path).parent.name=='006' and Path(path).name=='pareto.json':
                    raise KeyboardInterrupt
                return original(path,data)
            with patch.object(nsga,'atomic_json',interrupt):
                with self.assertRaises(KeyboardInterrupt):nsga.main(config=c,population=4)
            nsga.main(config=c,population=4,resume=True)
            snap=c['run_dir']/'checkpoints'/'006'
            for name in ['performance.json','pareto.json','results.csv','pareto.csv']:
                self.assertTrue((snap/name).exists(),name)


if __name__=='__main__':unittest.main()
