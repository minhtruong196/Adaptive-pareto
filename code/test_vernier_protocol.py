import hashlib
import json
import unittest
from unittest.mock import patch
import numpy as np


class ProtocolTests(unittest.TestCase):
    def test_initial_doe_matches_deleted_narrow_runner_sampling(self):
        import vernier_protocol as p
        from vernier_model import BOUNDS,make_plan
        from test_vernier_adapter import BASE
        self.assertEqual(p.sample_points(90,BOUNDS,BASE,17),make_plan(90,17,BOUNDS,BASE))

    def test_global_and_local_doe_match_recovered_old_runner(self):
        import vernier_protocol as p
        from vernier_model import BOUNDS,make_plan
        from test_vernier_adapter import BASE
        initial=make_plan(90,17,BOUNDS,BASE)
        guide=[dict(point=point,prediction=[2.+i,.9-.03*i,80.+.5*i])
               for i,point in enumerate(initial[:12])]
        # Golden batches generated directly from deleted runner blob 733602e,
        # with its companion ANN/model blobs 4ff5076/ad15562 and this fixed BASE.
        expected={'G':'fa8791c5ff2e972259d5e7788755dc5979015b39758aee2bad4b6ffe06d62b4f',
                  'L':'f7e419701de91af5fc4d24a80492d50e9ac2ab9916891fb2c2798cdbd6bcf068'}
        for kind,seed in [('G',117),('L',217)]:
            with self.subTest(kind=kind):
                boxes=p.local_boxes(guide,BOUNDS,kind)
                points=p.sample_points(40,BOUNDS,BASE,seed,initial,boxes)
                self.assertEqual(hashlib.sha256(json.dumps(points,sort_keys=True).encode()).hexdigest(),expected[kind])

    def test_old_train_doe_does_not_expand_guidance_but_val_still_participates(self):
        import vernier_protocol as p
        predicted=[dict(point={'x':1.},prediction=[5.,.5,80.]),
                   dict(point={'x':2.},prediction=[4.,.8,85.]),
                   dict(point={'x':4.},prediction=[6.,.6,86.])]
        actual=[dict(point={'x':1.},status='ok',role='train',average_torque_nm=1.,power_factor=.1,efficiency_pct=50.),
                dict(point={'x':4.},status='solve_failed',role='train'),
                dict(point={'x':99.},status='ok',role='train',average_torque_nm=100.,power_factor=.99,efficiency_pct=100.),
                dict(point={'x':3.},status='ok',role='val',average_torque_nm=3.,power_factor=.9,efficiency_pct=86.)]
        guide=p.corrected_guide(predicted,actual)
        self.assertEqual({r['point']['x'] for r in guide},{2.,3.})
        left,right=p.local_boxes(guide,{'x':(0.,100.,'')},'G')[0]
        np.testing.assert_array_equal(left,[2.])
        np.testing.assert_array_equal(right,[3.])

    def test_nsga_initial_sampling_keeps_old_seed_offset(self):
        import vernier_protocol as p
        from vernier_model import BOUNDS
        from test_vernier_adapter import BASE
        def prediction(model,x):
            return np.column_stack([1+x[:,0],1-.5*x[:,0],80+x[:,1]])
        with patch.object(p,'sample_points',wraps=p.sample_points) as sample,patch('vernier_mlp.predict',side_effect=prediction):
            p.search_pareto({},BOUNDS,BASE,seed=17,population=20,generations=1)
        self.assertEqual(sample.call_args.args[3],118)

    def test_budget300_reserves_verify_within_train_quota(self):
        import vernier_protocol as p
        b=p.allocation(300,'adaptive')
        self.assertEqual((b['train'],b['val'],b['test']),(210,60,30))
        self.assertEqual([(s['doe_train'],s['val'],s['verify']) for s in b['stages']],
                         [(70,20,0),(30,10,5),(30,10,5),(30,10,5),(30,10,5)])
        self.assertEqual([s['cumulative_train'] for s in b['stages']],[70,105,140,175,210])
        self.assertEqual(sum(s['doe_train']+s['val']+s['verify'] for s in b['stages'])+b['test'],300)

    def test_rounding_and_static_keep_total(self):
        import vernier_protocol as p
        for n,expected in [(111,(78,22,11)),(222,(156,44,22)),(300,(210,60,30))]:
            for method in ['adaptive','static']:
                b=p.allocation(n,method)
                self.assertEqual((b['train'],b['val'],b['test']),expected)
                self.assertEqual(sum(s['doe_train']+s['val']+s['verify'] for s in b['stages'])+b['test'],n)

    def test_guidance_uses_fea_val_and_corrects_or_removes_verified_predictions(self):
        import vernier_protocol as p
        predicted=[dict(point={'x':1.},prediction=[9.,.9,99.]),
                   dict(point={'x':2.},prediction=[8.,.8,98.]),
                   dict(point={'x':3.},prediction=[7.,.7,97.])]
        actual=[dict(point={'x':1.},status='ok',role='train',average_torque_nm=1.,power_factor=.1,efficiency_pct=50.),
                dict(point={'x':2.},status='solve_failed'),
                dict(point={'x':4.},status='ok',role='val',average_torque_nm=10.,power_factor=.95,efficiency_pct=99.5)]
        guide=p.corrected_guide(predicted,actual)
        self.assertEqual([r['point']['x'] for r in guide],[4.])
        self.assertTrue(guide[0]['verified'])

    def test_verification_is_extremes_then_maximin_and_never_old_points(self):
        import vernier_protocol as p
        candidates=[dict(point={'x':float(i)},prediction=y) for i,y in enumerate(
            [[10.,.2,80.],[3.,.99,81.],[4.,.5,99.],[6.,.7,90.],[8.,.4,85.],[5.,.8,92.]])]
        chosen=p.choose_checks(candidates,[],5)
        self.assertEqual([r['point']['x'] for r in chosen[:3]],[0.,1.,2.])
        self.assertEqual(len({p.point_key(r['point']) for r in chosen}),5)
        self.assertNotIn(0.,[r['point']['x'] for r in p.choose_checks(candidates,[{'x':0.}],5)])
        with self.assertRaisesRegex(ValueError,'Pareto'):
            p.choose_checks(candidates,[{'x':float(i)} for i in range(3)],5)


if __name__=='__main__':unittest.main()
