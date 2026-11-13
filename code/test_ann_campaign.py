import unittest
import numpy as np
import ann_campaign as a


class Essential(unittest.TestCase):
    def test_pool60_ver20_accounting(self):
        c=a.read_settings('ann_pool60_ver20_config.json')
        self.assertEqual(a.validate_settings(c),(20,60))
        self.assertEqual(c['conventional_doe_n'],60)
        self.assertEqual(20+sum(c['stage_doe_counts'])+3*c['verify_n'],60)
        self.assertEqual(c['stage_pool_targets'],[27,38,49,60])
        self.assertEqual(c['pool_n']+c['final_verify_n'],80)

    def test_pool100_ver20_accounting(self):
        c=a.read_settings('ann_pool100_ver20_config.json')
        self.assertEqual(a.validate_settings(c),(40,80))
        self.assertEqual(c['conventional_doe_n'],100)
        self.assertEqual(40+sum(c['stage_doe_counts'])+3*c['verify_n'],100)
        self.assertEqual(c['stage_pool_targets'],[52,68,84,100])
        self.assertEqual(c['pool_n']+c['final_verify_n'],120)

    def test_verification_reports_mean_and_worst_errors_separately(self):
        e=a.errors(np.array([[10.,.9,80.],[20.,.95,90.]]),
                   np.array([[11.,.91,81.],[24.,.97,92.]]))['average_torque_nm']
        self.assertEqual(e['n'],2)
        self.assertAlmostEqual(e['mean_relative_error_pct'],15.)
        self.assertAlmostEqual(e['max_relative_error_pct'],20.)
        self.assertAlmostEqual(e['max_absolute_error'],4.)



    def test_budget_and_schedule(self):
        c = a.read_settings()
        self.assertEqual(c['initial_n']+sum(c['stage_doe_counts'])+3*c['verify_n'],c['pool_n'])
        self.assertEqual(c['conventional_doe_n']+c['final_verify_n'],c['budget'])
        self.assertEqual(a.ORDERS['sequential'],['G','G','L','L'])
        self.assertEqual(a.ORDERS['alternating'],['G','L','G','L'])

    def test_sampling_and_verification(self):
        x=a.sample_box(40, np.zeros(7),np.array(a.opt.LIMITS),set(),17)
        self.assertEqual(len(set(x)),40)
        extra=a.sample_box(10,np.zeros(7),np.array(a.opt.LIMITS),set(x),18)
        self.assertFalse(set(x)&set(extra))
        y=np.array([[10,.9,80],[8,.99,85],[7,.95,95],[9,.93,90],[6,.98,92],[5,.99,94]])
        chosen=a.select_verify(y,5)
        self.assertEqual(len(set(chosen)),5)
        self.assertTrue({0,1,2}.issubset(chosen))

    def test_validation_excluded_from_scaling_and_fit(self):
        c=a.read_settings();c['epochs']=2
        rows=[]
        for i in range(12):
            ix=(i,i,i,i,0,0,0)
            rows.append(dict(design_key=a.key(ix),status='ok',
                             **dict(zip(a.opt.NAMES,a.opt.decode(ix))),
                             average_torque_nm=float(i),power_factor=.9,efficiency_pct=80.))
        held={r['design_key'] for r in rows[-2:]}
        rows[-1]['average_torque_nm']=10000.
        model,record=a.fit_ann(rows,held,c)
        self.assertEqual(record['fit_n'],10)
        self.assertEqual(record['validation_n'],2)
        self.assertAlmostEqual(float(model['mean'][0]),4.5)
        self.assertFalse(set(record['fit_keys']) & held)


if __name__=='__main__': unittest.main()
