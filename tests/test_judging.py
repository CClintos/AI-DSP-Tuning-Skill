import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'helix-rew-tuner' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import judging
import measure

F = measure.common_grid(20, 20000, 96)
LIVE = np.ones(len(F), bool)


class JudgingTests(unittest.TestCase):
    def test_regional_regression_vetoes_average_gain(self):
        before = np.full(len(F), 5.0)
        after = np.zeros(len(F))
        after[(F >= 80) & (F < 250)] = 7
        report = judging.scorecard(F, before, after, LIVE)
        self.assertLess(report['after']['total'], report['before']['total'])
        self.assertEqual('regressed', report['verdict'])

    def test_tie_prefers_existing_tune(self):
        report = judging.scorecard(F, np.ones(len(F)), np.full(len(F), .9), LIVE)
        self.assertEqual('tie', report['verdict'])
        self.assertIn('existing', report['tie_action'])

    def test_missing_band_is_unknown(self):
        report = judging.scorecard(F, F * 0, F * 0, F >= 300)
        self.assertEqual('unknown', report['bands'][0]['status'])

    def test_compression_is_not_removed_by_alignment(self):
        low = F * 0 + 80
        report = judging.compression(F, low, low + 4, 6, LIVE)
        self.assertTrue(all(b['status'] == 'compression' for b in report['bands']))
        self.assertEqual(-2, report['bands'][0]['median_tracking_error_db'])

    def test_frequency_specific_compression(self):
        low = F * 0 + 80
        high = low + 6
        high[F < 250] -= 2
        report = judging.compression(F, low, high, 6, LIVE)
        self.assertEqual('compression', report['bands'][0]['status'])
        self.assertEqual('tracks', report['bands'][2]['status'])

    def test_distortion_noise_floor_is_not_zero_distortion(self):
        report = judging.distortion(F, F * 0 + 80, {'h2': F * 0 + 30}, F * 0 + 25, LIVE)
        self.assertIsNone(report['bands'][0]['harmonics']['h2']['max_percent'])
        self.assertEqual('not_assessed', report['audibility_verdict'])

    def test_harmonic_absolute_level_survives_fundamental_null(self):
        fundamental = F * 0 + 80
        fundamental[F < 80] = 60
        report = judging.distortion(F, fundamental, {'h3': F * 0 + 40}, F * 0 + 10, LIVE)
        bass, mid = report['bands'][0], report['bands'][2]
        self.assertEqual(40, bass['harmonics']['h3']['max_absolute_db'])
        self.assertGreater(bass['harmonics']['h3']['max_percent'], mid['harmonics']['h3']['max_percent'])

    def test_invalid_inputs_rejected(self):
        for step in (0, -1, float('nan'), True):
            with self.assertRaises(ValueError):
                judging.compression(F, F * 0, F * 0, step, LIVE)
        with self.assertRaises(ValueError):
            judging.scorecard(F, F * np.nan, F * 0, LIVE)
        with self.assertRaises(ValueError):
            judging.load_spec({'version': True}, '.')


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def trace(self, name, db):
        p = self.root / name
        p.write_text('\n'.join('%g %g' % (f, s) for f, s in zip(F, db)), encoding='utf-8')
        return name

    def tone(self, repeated=True):
        baseline = [self.trace('b1.txt', F * 0 + 85)]
        candidate = [self.trace('a1.txt', F * 0 + 80)]
        # Shape improvement, with an unchanged anchor region.
        b = F * 0 + 80
        b[(F > 80) & (F < 250)] = 87
        self.trace('b1.txt', b)
        if repeated:
            baseline.append(self.trace('b2.txt', b + .05 * np.sin(np.log(F))))
            candidate.append(self.trace('a2.txt', F * 0 + 80 + .05 * np.cos(np.log(F))))
        (self.root / 'target.txt').write_text('20000 0\n20 0\n')
        return {'version': 1, 'baseline': baseline, 'candidate': candidate, 'target': 'target.txt'}

    def test_independent_repeats_and_sparse_descending_target(self):
        report = judging.load_spec(self.tone(), self.root)
        self.assertEqual('improved', report['evidence']['tone']['status'])
        self.assertEqual('unknown', report['evidence']['decay']['status'])
        self.assertEqual('incomplete', report['overall'])
        json.dumps(report, allow_nan=False)

    def test_single_capture_cannot_confirm_improvement(self):
        report = judging.load_spec(self.tone(False), self.root)
        self.assertEqual('unconfirmed', report['evidence']['tone']['status'])

    def test_duplicate_repeats_rejected(self):
        spec = self.tone(False)
        spec['baseline'] *= 2
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            judging.load_spec(spec, self.root)

    def test_no_extrapolated_compression_bands(self):
        f = np.geomspace(300, 3000, 100)
        for name, level in [('low', 80), ('high', 86)]:
            (self.root / (name + '.txt')).write_text('\n'.join('%g %g' % (x, level) for x in f))
        report = judging.load_spec({'version': 1, 'level_steps': [
            {'path': 'low.txt', 'level_db': 0}, {'path': 'high.txt', 'level_db': 6}]}, self.root)
        self.assertEqual('unknown', report['evidence']['compression']['steps'][0]['bands'][0]['status'])

    def test_stereo_regression_and_headroom_hold(self):
        a = self.trace('a.txt', F * 0 + 80)
        b = self.trace('b.txt', F * 0 + 83)
        h = self.trace('transfer.txt', F * 0 + 4)
        report = judging.load_spec({'version': 1, 'stereo': {
            'before_left': a, 'before_right': a, 'after_left': a, 'after_right': b},
            'headroom': {'transfer': h, 'input_peak_dbfs': -2}}, self.root)
        self.assertEqual('hold_for_review', report['overall'])
        self.assertEqual(-2, report['evidence']['headroom']['spectral_margin_db'])
        self.assertEqual('unknown', report['evidence']['headroom']['internal_clipping'])

    def test_cli_protects_nested_capture_and_target_inputs(self):
        spec = self.tone()
        manifest = self.root / 'spec.json'
        manifest.write_text(json.dumps(spec))
        for out in ('b1.txt', 'target.txt', 'spec.json'):
            p = self.root / out
            original = p.read_bytes()
            run = subprocess.run([sys.executable, str(SCRIPTS / 'pipeline.py'), 'quality-check',
                                  '--spec', str(manifest), '--out', str(p)], capture_output=True, text=True)
            self.assertEqual(2, run.returncode, run.stderr)
            self.assertEqual(original, p.read_bytes())
        run = subprocess.run([sys.executable, str(SCRIPTS / 'pipeline.py'), 'quality-check',
                              '--spec', str(manifest)], capture_output=True, text=True)
        self.assertEqual(0, run.returncode, run.stderr)
        self.assertEqual('improved', json.loads(run.stdout)['evidence']['tone']['status'])


if __name__ == '__main__':
    unittest.main()
