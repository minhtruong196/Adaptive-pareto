import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np


class CampaignTests(unittest.TestCase):
    def test_frozen_role_or_prediction_change_is_rejected(self):
        import vernier_campaign as vc
        with tempfile.TemporaryDirectory() as tmp:
            state=dict(records=[dict(point={'x':1.},role='val',phase='Initial_doe')],steps={},models={})
            vc.save_state(Path(tmp)/'state.json',state);vc.verify_state(state)
            state['records'][0]['role']='train'
            with self.assertRaisesRegex(ValueError,'Frozen'):vc.verify_state(state)

    def test_cached_front_predictions_must_match_model(self):
        import vernier_campaign as vc
        c=vc.settings();base=vc.source_variables(c['source'])
        point=vc.sample_points(1,c['bounds'],base,17)[0]
        front=[dict(point=point,prediction=[4.,.5,80.])]
        with patch.object(vc,'predict',return_value=np.array([[5.,.5,80.]])):
            with self.assertRaisesRegex(ValueError,'do not match'):vc.validate_front({},c,base,front)

    def exercise(self,method,total=300,fail_every=0):
        import vernier_campaign as vc
        import vernier_protocol as protocol
        with tempfile.TemporaryDirectory() as tmp:
            c=vc.settings(method);c.update(run_dir=Path(tmp)/'run',dry_run=True,evaluations=total)
            fit_calls=[];batches=[];calls=[0]
            def fit(train,val,bounds,folder,**kwargs):
                fit_calls.append((len(train),len(val),kwargs['merged']))
                self.assertFalse({r['point_id'] for r in train}&{r['point_id'] for r in val})
                self.assertTrue(all(r['role']=='train' for r in train) or kwargs['merged'])
                return dict(record=dict(fit_ids=[r['point_id'] for r in train],validation_ids=[r['point_id'] for r in val]))
            def search(model,bounds,base,seed=17,population=100,generations=100,seen=()):
                points=protocol.sample_points(100,bounds,base,seed+999,seen)
                ys=vc.synthetic_values(points,bounds)
                return [dict(point=p,prediction=y.tolist()) for p,y in zip(points,ys)]
            def predict(model,x):
                return vc.synthetic_values([dict(zip(c['bounds'],row)) for row in x],c['bounds'])
            def evaluate(points):
                batches.append(len(points));output=[]
                for p in points:
                    calls[0]+=1
                    output.append(dict(status='solve_failed',error='synthetic failure') if fail_every and calls[0]%fail_every==0
                                  else dict(status='ok',**dict(zip(vc.OBJECTIVES,vc.synthetic_values([p],c['bounds'])[0]))))
                return output
            with patch.object(vc,'fit_model',side_effect=fit),patch.object(vc,'search_pareto',side_effect=search),patch.object(vc,'predict',side_effect=predict),patch.object(vc,'cross_validate',return_value={'folds':5}):
                result=vc.main(c,evaluate)
                again=vc.main(c,lambda _:self.fail('completed run must not repeat evaluations'))
            self.assertEqual(result,again)
            self.assertEqual(calls[0],total)
            self.assertEqual(result['actual_solver_calls'],0)
            self.assertEqual(result['evaluation_slots'],total)
            self.assertEqual(result['final_outcomes']['planned'],protocol.allocation(total,method)['test'])
            self.assertTrue(result['final_never_trained'])
            self.assertTrue((c['run_dir']/'state.json').exists())
            records=json.loads((c['run_dir']/'state.json').read_text())['records']
            self.assertEqual(sum(r['role']=='test' for r in records),protocol.allocation(total,method)['test'])
            return fit_calls,batches,result

    def test_txt_order_doe_fit_verify_complete300_and_resume(self):
        fits,batches,_=self.exercise('adaptive')
        self.assertEqual(fits,[(70,20,False),(100,30,False),(135,40,False),(170,50,False),(205,60,False),(270,0,True)])
        self.assertEqual(batches,[90,40,5,40,5,40,5,40,5,30])

    def test_static270_then_final30(self):
        fits,batches,_=self.exercise('static')
        self.assertEqual(fits,[(210,60,False),(270,0,True)])
        self.assertEqual(batches,[270,30])

    def test_failed_slots_not_refilled_or_promoted_between_roles(self):
        fits,batches,result=self.exercise('adaptive',111,11)
        self.assertEqual(sum(batches),111)
        self.assertEqual(result['statuses']['solve_failed'],10)
        self.assertLess(result['pool_valid'],100)
        self.assertEqual(result['roles_planned'],{'train':78,'val':22,'test':11})


if __name__=='__main__':unittest.main()
