"""Synthetic, solver-free checks of the Vernier surrogate protocol."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch

if importlib.util.find_spec('vernier_mlp'):
    import vernier_mlp as mlp
else:
    mlp = None


BOUNDS = {'a': (0., 10.), 'b': (-2., 2.)}


def rows(n=10):
    return [dict(point_id=i + 1, point={'a': float(i), 'b': 0.}, status='ok',
                 average_torque_nm=float(i + 1), power_factor=.7 + .01*i,
                 efficiency_pct=70. + i) for i in range(n)]


class VernierMLPTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(mlp, 'solver-free Vernier MLP implementation is required')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def fit(self, train, val=(), **kwargs):
        return mlp.fit_model(train, val, BOUNDS, self.folder,
                             epochs=6, min_checkpoint_epoch=3, **kwargs)

    def test_training_matches_plain_adam_with_constant_lr_and_no_weight_decay(self):
        train, val = rows(8), rows(10)[8:]
        y = np.array([[r[k] for k in mlp.OBJECTIVES] for r in train])
        mean, scale = y.mean(0), y.std(0)
        x = torch.tensor([[r['point']['a']/10., .5] for r in train], dtype=torch.float32)
        target = torch.tensor((y-mean)/scale, dtype=torch.float32)
        for merged in (False, True):
            with self.subTest(merged=merged):
                folder = self.folder/('merged' if merged else 'stage')
                model = mlp.fit_model(train, [] if merged else val, BOUNDS, folder,
                                      epochs=6, min_checkpoint_epoch=3, merged=merged)
                self.assertEqual([r['learning_rate'] for r in model['record']['curve']], [.003]*6)
                self.assertEqual(model['record']['settings']['weight_decay'], 0.)
                self.assertIsNone(model['record']['settings']['scheduler'])
                # Compare actual final weights against an independent plain-Adam fit.
                torch.manual_seed(17)
                reference = mlp._network(2)
                optimizer = torch.optim.Adam(reference.parameters(), lr=.003)
                for _ in range(6):
                    optimizer.zero_grad()
                    loss = ((reference(x)-target)**2).mean()
                    loss.backward()
                    optimizer.step()
                final = torch.load(folder/'final_epoch.pt', weights_only=True)
                for key, value in reference.state_dict().items():
                    torch.testing.assert_close(final['state'][key], value, rtol=0., atol=0.)

    def test_validation_never_fits_output_scaler_or_input_bounds(self):
        train = rows(4)
        val = rows(5)[4:]
        val[0]['average_torque_nm'] = 100000.
        model = self.fit(train, val)
        np.testing.assert_allclose(model['mean'], [2.5, .715, 71.5])
        np.testing.assert_allclose(model['scale'],
                                   [np.sqrt(1.25), np.sqrt(.000125), np.sqrt(1.25)])
        np.testing.assert_allclose(model['lo'], [0., -2.])
        np.testing.assert_allclose(model['span'], [10., 4.])
        self.assertEqual(model['record']['fit_ids'], [1, 2, 3, 4])
        self.assertEqual(model['record']['validation_ids'], [5])
        self.assertEqual(mlp.predict(model, [[4., 0.]]).shape, (1, 3))

    def test_checkpoint_floor_excludes_better_early_validation_weights(self):
        train = rows(8)
        val = rows(9)[8:]
        for name in ('average_torque_nm', 'power_factor', 'efficiency_pct'):
            val[0][name] = -1000.
        early = mlp.fit_model(train, val, BOUNDS, self.folder/'early',
                              epochs=20, min_checkpoint_epoch=1)
        late = mlp.fit_model(train, val, BOUNDS, self.folder/'late',
                             epochs=20, min_checkpoint_epoch=10)
        self.assertLess(early['record']['selected_epoch'], 10)
        self.assertGreaterEqual(late['record']['selected_epoch'], 10)
        self.assertNotEqual(early['record']['selected_epoch'], late['record']['selected_epoch'])
        self.assertEqual(late['record']['epochs_completed'], 20)
        curve = late['record']['curve']
        eligible = min(curve[9:], key=lambda r: r['validation_loss'])
        self.assertEqual(late['record']['selected_epoch'], eligible['epoch'])
        self.assertEqual(len(curve[-1]['train_target_loss']), 3)
        self.assertEqual(len(curve[-1]['validation_target_loss']), 3)

    def test_merge_uses_final_epoch_weights_and_saves_both_checkpoints(self):
        train = rows(8)
        merged = self.fit(train, merged=True)
        last = mlp.fit_model(train, rows(9)[8:], BOUNDS, self.folder/'last',
                             epochs=6, min_checkpoint_epoch=6)
        self.assertEqual(merged['record']['selected_epoch'], 6)
        for key, weight in merged['net'].state_dict().items():
            torch.testing.assert_close(weight, last['net'].state_dict()[key])
        self.assertTrue((self.folder/'ann.pt').is_file())
        self.assertTrue((self.folder/'final_epoch.pt').is_file())
        self.assertTrue((self.folder/'scalers.json').is_file())
        saved = json.loads((self.folder/'training.json').read_text())
        self.assertEqual(saved['checkpoint_selection'], 'final_epoch')

    def test_default_merge_reaches_epoch_500(self):
        model = mlp.fit_model(rows(5), [], BOUNDS, self.folder, merged=True)
        self.assertEqual(model['record']['selected_epoch'], 500)
        self.assertEqual(model['record']['epochs_completed'], 500)
        self.assertEqual(len(model['record']['curve']), 500)

    def test_default_stage_keeps_historical_validation_and_final_500_checkpoint(self):
        model = mlp.fit_model(rows(8), rows(10)[8:], BOUNDS, self.folder)
        self.assertGreaterEqual(model['record']['selected_epoch'], 300)
        self.assertLessEqual(model['record']['selected_epoch'], 500)
        final = torch.load(self.folder/'final_epoch.pt', weights_only=True)
        self.assertEqual(final['epoch'], 500)
        historical_path = self.folder/'premerge_validation.json'
        historical = historical_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            mlp.fit_model(rows(10), [], BOUNDS, self.folder, merged=True)
        self.assertEqual(historical_path.read_bytes(), historical)

    def test_cross_validation_each_id_is_held_out_once_with_fold_only_scalers(self):
        report = mlp.cross_validate(rows(), BOUNDS, self.folder, epochs=6)
        json.dumps(report, allow_nan=False)
        self.assertEqual(sorted(p['point_id'] for p in report['oof_predictions']), list(range(1, 11)))
        seen = []
        for fold in report['folds']:
            self.assertFalse(set(fold['fit_ids']) & set(fold['test_ids']))
            self.assertEqual(fold['selected_epoch'], 6)
            self.assertEqual(fold['validation_ids'], [])
            seen.extend(fold['test_ids'])
            expected = np.mean([i for i in fold['fit_ids']])
            self.assertAlmostEqual(fold['scaler_mean'][0], expected)
        self.assertEqual(sorted(seen), list(range(1, 11)))
        self.assertIn('sample_sd', report['summary']['average_torque_nm']['rmse'])
        self.assertTrue((self.folder/'oof_predictions.csv').is_file())

    def test_resume_requires_identical_data_settings_and_preserves_checkpoint(self):
        model = self.fit(rows(8), rows(10)[8:])
        stamp = (self.folder/'ann.pt').stat().st_mtime_ns
        resumed = self.fit(rows(8), rows(10)[8:])
        self.assertEqual((self.folder/'ann.pt').stat().st_mtime_ns, stamp)
        np.testing.assert_array_equal(mlp.predict(model, [[1., 0.]]),
                                      mlp.predict(resumed, [[1., 0.]]))
        changed = rows(8)
        changed[0]['average_torque_nm'] += 1.
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            self.fit(changed, rows(10)[8:])
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            self.fit(rows(8), rows(10)[8:], seed=18)
        val = rows(10)[8:]
        val[-1]['efficiency_pct'] += 1.
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            self.fit(rows(8), val)

    def test_rejects_overlap_invalid_epoch_floor_and_merge_validation(self):
        with self.assertRaisesRegex(ValueError, 'overlap'):
            self.fit(rows(8), rows(2))
        with self.assertRaisesRegex(ValueError, 'checkpoint'):
            mlp.fit_model(rows(8), rows(10)[8:], BOUNDS, self.folder, epochs=6)
        with self.assertRaisesRegex(ValueError, 'merged'):
            self.fit(rows(8), rows(10)[8:], merged=True)

    def test_metrics_reports_signed_bias_and_overprediction_counts(self):
        actual = np.array([[10., .5, 80.], [20., 1., 100.]])
        predicted = np.array([[12., .4, 84.], [18., 1.2, 98.]])
        report = mlp.metrics(actual, predicted)
        torque = report['objectives']['average_torque_nm']
        self.assertEqual(report['n'], 2)
        self.assertEqual(torque['mae'], 2.)
        self.assertEqual(torque['rmse'], 2.)
        self.assertEqual(torque['mape'], 15.)
        self.assertAlmostEqual(torque['r2'], .84)
        self.assertEqual(torque['bias'], 0.)
        self.assertEqual(torque['overpredicted_n'], 1)
        self.assertEqual(report['objectives']['efficiency_pct']['bias'], 1.)


if __name__ == '__main__':
    unittest.main()
