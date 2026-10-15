"""MMM decisions must improve tone, not just matching or a summary score."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'helix-rew-tuner/scripts'))
import measure
import tunelib as t

F = measure.common_grid()
TARGET = measure.load_target(Path(__file__).resolve().parents[1] /
                             'helix-rew-tuner/assets/default_incar_target.txt', F)
BASE = 80 + TARGET


class MatchProtection(unittest.TestCase):
    def test_good_side_is_not_cut_to_copy_other_sides_hole(self):
        for bad_side in ('left', 'right'):
            dip = BASE + t.peaking_db(F, 1500, 2, -6)
            left, right = (dip, BASE) if bad_side == 'left' else (BASE, dip)
            r = t.lr_match_cuts(F, left, right, target_db=TARGET)
            self.assertEqual(r['cuts'], [])
            self.assertTrue(r['unresolved_regions'])

    def test_real_excess_is_still_corrected(self):
        left = BASE + t.peaking_db(F, 1500, 2, 4)
        r = t.lr_match_cuts(F, left, BASE, target_db=TARGET)
        self.assertTrue(r['cuts'])
        self.assertTrue(all(b['side'] == 'left' for b in r['cuts']))
        self.assertLess(r['target_error_after_db']['left'], r['target_error_before_db']['left'])
        self.assertLess(r['wrms_after_db'], r['wrms_before_db'])

    def test_missing_target_is_diagnostic_not_permission_to_cut(self):
        r = t.lr_match_cuts(F, BASE, BASE+t.peaking_db(F, 1500, 2, -6))
        self.assertEqual(r['cuts'], [])
        self.assertTrue(r['notes'])

    def test_subthreshold_offset_is_not_silently_removed(self):
        r = t.lr_match_cuts(F, BASE+.3, BASE, target_db=TARGET)
        self.assertIsNone(r['trim'])
        self.assertAlmostEqual(r['wrms_after_db'], .3, places=2)


class Repeatability(unittest.TestCase):
    def test_bass_uncertainty_cannot_disappear_in_midrange_median(self):
        repeat = BASE.copy()
        repeat[F < 100] += 2
        r = t.capture_repeatability(F, [BASE, repeat])
        self.assertGreater(t.repeatability_noise(r, (30, 70)), 1)
        self.assertLess(t.repeatability_noise(r, (1000, 3000)), .2)
        self.assertGreater(r['noise_db'], .5)

    def test_unsupported_bins_do_not_supply_false_confidence(self):
        support = (F >= 200) & (F <= 6000)
        other = BASE.copy()
        other[~support] += 50
        r = t.capture_repeatability(F, [BASE, other], support=support)
        self.assertIsNone(t.repeatability_noise(r, (30, 80)))
        self.assertLess(t.repeatability_noise(r, (500, 3000)), .2)

    def test_verification_uses_noise_at_the_filter(self):
        other = BASE.copy()
        other[F < 100] += 2
        profile = t.capture_repeatability(F, [BASE, other])
        for freq, verdict in ((50, 'inconclusive'), (1500, 'confirmed')):
            bands = [(freq, 1, -1.5)]
            r = t.predicted_vs_measured(F, BASE, BASE+t.cascade_db(F, bands), bands,
                                       repeatability=profile)
            self.assertEqual(r['bands'][0]['verdict'], verdict)
            if verdict == 'confirmed':
                self.assertTrue(r['trace_changed'])
                self.assertFalse(any('no resolved change' in n for n in r['notes']))


class CompareProtection(unittest.TestCase):
    def test_equal_errors_do_not_mean_repeat_traces_agree(self):
        ripple = 2*np.sin(2*np.pi*np.log2(F/1000))
        r = t.compare_captures(F, {'now':BASE+ripple, 'trial':BASE+.7*ripple},
                               TARGET, (300, 6000), 'now', repeat_db=BASE-ripple)
        self.assertEqual(r['choice'], 'now')
        self.assertGreater(r['resolution']['shape_error_db'], 2)

    def test_louder_hump_cannot_win(self):
        for objective in ('level', 'balanced'):
            r = t.compare_captures(F, {'now':BASE, 'hump':BASE+t.peaking_db(F,80,2,6)},
                                   TARGET, (40,160), 'now', repeat_db=BASE, objective=objective)
            self.assertEqual(r['choice'], 'now')
            self.assertTrue(next(c for c in r['captures'] if c['label']=='hump')['rejection_reasons'])

    def test_repairing_a_bass_hole_still_wins(self):
        now = BASE+t.peaking_db(F,80,1.5,-6)
        trial = BASE+t.peaking_db(F,80,1.5,-2)
        r = t.compare_captures(F, {'now':now,'trial':trial}, TARGET,(40,160),'now',
                               repeat_db=now, objective='balanced')
        self.assertEqual(r['choice'], 'trial')

    def test_bass_level_and_playback_gain_are_not_improvements(self):
        for trial in (BASE+3, BASE+3*(F<200)):
            r = t.compare_captures(F, {'now':BASE,'trial':trial}, TARGET,(40,160),'now',
                                   repeat_db=BASE, objective='balanced')
            self.assertEqual(r['choice'], 'now')

    def test_missing_reference_is_reported_not_invented(self):
        support = (F>=40)&(F<=160)
        r = t.compare_captures(F, {'now':BASE,'trial':BASE+2}, TARGET,(40,160),'now',
                               support=support, objective='balanced')
        self.assertEqual(r['choice'], 'now')
        self.assertIsNone(r['reference_band_hz'])

    def test_partial_reference_is_not_reported_as_fully_measured(self):
        support = F < 1000
        r = t.compare_captures(F, {'now':BASE,'trial':BASE+2}, TARGET,(40,160),'now',
                               support=support, objective='balanced')
        self.assertEqual(r['choice'], 'now')
        self.assertIsNone(r['reference_band_hz'])

    def test_repeat_gain_drift_is_not_shape_uncertainty(self):
        now = BASE+t.peaking_db(F, 1500, 2, 5)
        r = t.compare_captures(F, {'now':now,'trial':BASE}, TARGET,(300,6000),'now',
                               repeat_db=now+3, objective='shape')
        self.assertEqual(r['choice'], 'trial')
        self.assertLess(r['resolution']['shape_error_db'], .2)

    def test_existing_deep_hole_cannot_hide_a_new_hole(self):
        now = BASE+t.peaking_db(F, 50, 2, -10)
        trial = BASE+t.peaking_db(F, 50, 2, -2)+t.peaking_db(F, 140, 3, -5)
        r = t.compare_captures(F, {'now':now,'trial':trial}, TARGET,(30,200),'now',
                               repeat_db=now, objective='balanced')
        self.assertEqual(r['choice'], 'now')
        reasons = next(c['rejection_reasons'] for c in r['captures'] if c['label']=='trial')
        self.assertIn('a local hole or hump became worse', reasons)


if __name__ == '__main__':
    unittest.main()
