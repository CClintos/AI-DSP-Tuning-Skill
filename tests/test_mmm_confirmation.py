"""A final MMM touch-up must survive independent captures of BOTH settings."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / 'helix-rew-tuner' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import measure
import tunelib as t

F = measure.common_grid(20, 20000, 96)
TARGET = measure.load_target(SCRIPTS.parent / 'assets/default_incar_target.txt', F)
BASE = 80 + TARGET + t.peaking_db(F, 80, 1.5, -4)
TRIAL = 80 + TARGET + t.peaking_db(F, 80, 1.5, -2)
WOBBLE = .015 * np.sin(np.log2(F) * 3)


class ConfirmationTests(unittest.TestCase):
    def compare(self, trial_repeat, baseline_repeat=None, **kw):
        return t.compare_captures(
            F, {'now': BASE, 'trial': TRIAL}, TARGET, (40, 160), 'now',
            repeat_db=BASE+WOBBLE if baseline_repeat is None else baseline_repeat,
            candidate_repeats={'trial': trial_repeat}, objective='balanced', **kw)

    def test_repeatable_improvement_survives(self):
        r = self.compare(TRIAL-WOBBLE)
        self.assertEqual(r['choice'], 'trial')
        self.assertFalse(r['requires_confirmation_capture'])
        self.assertTrue(next(c for c in r['captures'] if c['label'] == 'trial')['repeat_supported'])

    def test_lucky_first_capture_does_not_win(self):
        self.assertEqual(self.compare(BASE-WOBBLE)['choice'], 'now')

    def test_noisy_candidate_increases_its_own_resolution(self):
        r = self.compare(TRIAL + t.peaking_db(F, 80, 2, 3))
        row = next(c for c in r['captures'] if c['label'] == 'trial')
        self.assertGreater(row['resolution']['target_error_db'], r['resolution']['target_error_db'])
        self.assertFalse(row['eligible'])

    def test_candidate_must_beat_the_second_baseline_too(self):
        self.assertEqual(self.compare(TRIAL-WOBBLE, TRIAL+WOBBLE)['choice'], 'now')

    def test_changed_reference_in_second_candidate_blocks_it(self):
        r = self.compare(TRIAL + 2*((F >= 300) & (F <= 3000)))
        self.assertEqual(r['choice'], 'now')

    def test_same_export_is_not_independent_evidence(self):
        self.assertEqual(self.compare(TRIAL)['choice'], 'now')
        self.assertEqual(self.compare(TRIAL-WOBBLE, BASE)['choice'], 'now')

    def test_candidate_repeat_without_baseline_repeat_stays_provisional(self):
        r = t.compare_captures(F, {'now': BASE, 'trial': TRIAL}, TARGET, (40, 160), 'now',
                               candidate_repeats={'trial': TRIAL-WOBBLE}, objective='balanced')
        self.assertEqual(r['choice'], 'trial')
        self.assertTrue(r['requires_confirmation_capture'])

    def test_missing_reference_cannot_confirm_balance(self):
        self.assertEqual(self.compare(TRIAL-WOBBLE, support=F < 200)['choice'], 'now')

    def test_unknown_or_baseline_repeat_label_is_rejected(self):
        for label in ('missing', 'now'):
            with self.subTest(label=label), self.assertRaises(ValueError):
                t.compare_captures(F, {'now': BASE, 'trial': TRIAL}, TARGET, (40, 160), 'now',
                                   candidate_repeats={label: TRIAL})

    def test_cli_loads_repeat_and_keeps_tonal_claim_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = {}
            for name, curve in [('a1', BASE), ('a2', BASE+WOBBLE),
                                ('b1', TRIAL), ('b2', TRIAL-WOBBLE)]:
                p = Path(tmp) / (name + '.txt')
                p.write_text('\n'.join('%g %.6f' % (f, s) for f, s in zip(F, curve)))
                files[name] = str(p)
            proc = subprocess.run([sys.executable, str(SCRIPTS/'pipeline.py'), 'mmm-compare',
                '--captures', 'now='+files['a1'], 'trial='+files['b1'], '--repeat', files['a2'],
                '--candidate-repeat', 'trial='+files['b2'], '--band', '40', '160'],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertEqual(report['choice'], 'trial')
            self.assertIn('no phase', report['claim'])
            self.assertEqual(report['repeat_files']['candidates']['trial'], files['b2'])


if __name__ == '__main__':
    unittest.main()
