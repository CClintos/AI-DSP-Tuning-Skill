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
import audible_study
import measure
import tunelib


class AudibleStudyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def trace(self, name, hz, db):
        path = self.base / name
        path.write_text('\n'.join('%g %g' % pair for pair in zip(hz, db)), encoding='utf-8')
        return name

    def test_multitone_uses_native_unexcited_bins_and_rejects_missing_bins(self):
        hz = np.arange(100., 2000., 10.)
        base = np.full(len(hz), -50.)
        changed = base.copy()
        changed[(hz >= 400) & (hz <= 800)] -= 6
        self.trace('base.txt', hz, base)
        self.trace('changed.txt', hz, changed)
        f = measure.common_grid(20, 20000, 96)
        self.trace('base-fund.txt', f, np.full(len(f), 70.))
        self.trace('candidate-fund.txt', f, np.full(len(f), 70.))
        trial = {'name': 'lower workload', 'baseline': 'base.txt', 'candidate': 'changed.txt',
                 'band_hz': [400, 800], 'unexcited_hz': list(hz[(hz >= 400) & (hz <= 800)]),
                 'baseline_fundamental': 'base-fund.txt', 'candidate_fundamental': 'candidate-fund.txt',
                 'noise_floor_db': -80}
        result = audible_study.workload({'trials': [trial]}, str(self.base))
        self.assertEqual('improved', result['trials'][0]['status'])
        trial['unexcited_hz'][0] += 1
        with self.assertRaisesRegex(ValueError, 'native capture bins'):
            audible_study.workload({'trials': [trial]}, str(self.base))
        trial['unexcited_hz'][0] -= 1
        self.trace('candidate-fund.txt', f, np.full(len(f), 72.))
        with self.assertRaisesRegex(ValueError, 'matched within 1 dB'):
            audible_study.workload({'trials': [trial]}, str(self.base))

    def test_crossover_needs_measured_gain_and_all_probe_positions(self):
        f = measure.common_grid(20, 20000, 96)
        self.trace('before.txt', f, np.full(len(f), 70.))
        self.trace('after.txt', f, np.full(len(f), 70.))
        (self.base / 'probe.json').write_text(json.dumps({'positions': [[{'name': 'xo', 'recommendation': 'candidate'}],
                                                                       [{'name': 'xo', 'recommendation': 'reject'}]]}), encoding='utf-8')
        spec = {'baseline': 'before.txt', 'candidates': [{'name': 'trial', 'measurement': 'after.txt',
                                                        'probe_report': 'probe.json', 'variant': 'xo'}]}
        report = audible_study.crossover_review(spec, str(self.base))
        self.assertIsNone(report['candidate'])
        self.assertEqual(2, report['trials'][0]['probe_positions'])

    def test_stage_and_volume_require_repeated_blinded_matched_trials(self):
        trial = {'track': 'one', 'preferred': 'candidate', 'level_difference_db': .1}
        rows = [dict(trial), dict(trial, track='two'), dict(trial), dict(trial)]
        self.assertEqual('candidate_preferred', audible_study.stage_votes({'trials': rows})['status'])
        rows[0]['level_difference_db'] = .8
        with self.assertRaisesRegex(ValueError, 'matched levels'):
            audible_study.stage_votes({'trials': rows})

    def test_warm_output_detects_drift_and_recovery(self):
        f = measure.common_grid(20, 20000, 96)
        self.trace('cold.txt', f, np.full(len(f), 80.))
        self.trace('warm.txt', f, np.full(len(f), 79.))
        self.trace('recovered.txt', f, np.full(len(f), 80.))
        report = audible_study.stability({'trials': [{'name': 'xo-a', 'cold': 'cold.txt',
                  'warm': 'warm.txt', 'recovered': 'recovered.txt'}]}, str(self.base))
        row = report['trials'][0]
        self.assertEqual('time_dependent_change', row['status'])
        self.assertAlmostEqual(0, row['recovered_median_change_db'])

    def test_bass_area_requires_both_positions_to_benefit(self):
        f = measure.common_grid(20, 20000, 96)
        low = tunelib.crossover_H(f, 'lp', 'LR', 24, 100)
        high = tunelib.crossover_H(f, 'hp', 'LR', 24, 100)
        positions = []
        for i, delay_ms in enumerate((1, 0)):
            sub = low * np.exp(-2j * np.pi * f * delay_ms / 1000)
            names = {}
            for label, wave in (('sub', sub), ('front', high), ('together', sub+high)):
                name = '%s%d.txt' % (label, i)
                lines = ['* timing reference: Acoustic']
                lines += ['%g %g %g' % (hz, 80+20*np.log10(abs(z)), np.angle(z, deg=True))
                          for hz, z in zip(f, wave)]
                (self.base / name).write_text('\n'.join(lines), encoding='utf-8')
                names[label] = name
            positions.append(names)
        self.trace('target.txt', f, 20*np.log10(abs(low+high)))
        result = audible_study.bass_area({'positions': positions, 'target': 'target.txt',
                                          'delays_ms': [-1, 0, 1], 'gains_db': [0]}, str(self.base))
        self.assertIsNone(result['candidate'])
        self.assertEqual('keep_current', result['status'])

    def test_cli_report_and_protected_input(self):
        spec = self.base / 'study.json'
        spec.write_text(json.dumps({'version': 1, 'rattles': {'events': [{'excitation_hz': 80,
                           'repeat_confirmed': True, 'suspected_location': 'door'}]}}), encoding='utf-8')
        run = subprocess.run([sys.executable, str(SCRIPTS / 'pipeline.py'), 'audible-study',
                              '--spec', str(spec)], capture_output=True, text=True)
        self.assertEqual(0, run.returncode, run.stderr)
        self.assertEqual('inspect', json.loads(run.stdout)['evidence']['rattles']['status'])
        bad = subprocess.run([sys.executable, str(SCRIPTS / 'pipeline.py'), 'audible-study',
                              '--spec', str(spec), '--out', str(spec)], capture_output=True, text=True)
        self.assertEqual(2, bad.returncode)


if __name__ == '__main__':
    unittest.main()
