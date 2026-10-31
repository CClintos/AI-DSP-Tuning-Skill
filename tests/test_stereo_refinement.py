import json
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'helix-rew-tuner'/'scripts'))
import stereo_refine as sr
import tunelib as t
import measure
import mmm


class JointTests(unittest.TestCase):
    def test_cli_reads_real_banks_and_holds_missing_junction_evidence(self):
        import afpx
        from tests.test_mmm_capability import _channel
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tune = root/'current.afpx'
            channel = _channel([(2500, 2, -6)]).replace('F="3000.00"', 'F="8000.00"')
            afpx._encode_unchecked('<ATF>'+channel+channel+'</ATF>', str(tune))
            original = tune.read_bytes()
            f = measure.common_grid(20, 20000, 96)
            target = root/'target.txt'
            np.savetxt(target, np.column_stack([f, np.zeros(len(f))]))
            paths = []
            for i in range(4):
                path = root/('pass%d.txt' % i)
                db = 80+t.peaking_db(f, 2500, 2, -6, fs=48000)+.01*np.sin(np.log(f)*(i+2))
                np.savetxt(path, np.column_stack([f, db]), header='capture_id: pass%d' % i)
                paths.append(str(path))
            script = Path(sr.__file__).with_name('pipeline.py')
            proc = subprocess.run([sys.executable, str(script), 'stereo-refine', '--afpx', str(tune),
                '--left-channel', '0', '--right-channel', '1', '--left', *paths[:2], '--right', *paths[2:],
                '--dsp-rate', '48000', '--target', str(target)], capture_output=True, text=True)
            self.assertEqual(0, proc.returncode, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertTrue(report['edits'])
            self.assertEqual('hold_for_review', report['apply_recommendation'])
            self.assertTrue(all('slot_index' in e for e in report['edits']))
            self.assertEqual(original, tune.read_bytes())

    def run_pair(self, bank, dev, ceilings=None):
        f = measure.common_grid(20, 20000, 24)
        wobble = .01*np.sin(np.log(f)*4)
        runs = [[80+dev(f)+wobble, 80+dev(f)-wobble] for _ in range(2)]
        return sr.refine_pair(f, runs, np.zeros(len(f)), [bank, bank], np.ones(len(f), bool),
                              (700, 5000), 48000, max_edits=2, ceilings=ceilings)

    def test_correct_tune_keeps_banks(self):
        r = self.run_pair([(1800, 1, -3)], lambda f: np.zeros(len(f)))
        self.assertTrue(r['unchanged'])

    def test_joint_relaxation_repairs_shared_overcut(self):
        r = self.run_pair([(2500, 2, -6)], lambda f: t.peaking_db(f, 2500, 2, -6, fs=48000))
        self.assertFalse(r['unchanged'])
        self.assertEqual({'left', 'right'}, {e['side'] for e in r['edits']})
        self.assertLessEqual(r['final_lr_mismatch_db'], r['baseline_lr_mismatch_db']+.25)
        self.assertTrue(all(c['verdict'] != 'regressed' for c in r['judging']))

    def test_compression_ceiling_blocks_removing_cut(self):
        f = measure.common_grid(20, 20000, 24)
        r = self.run_pair([(1800, 1, -6)], lambda f: t.peaking_db(f, 1800, 1, -3, fs=48000),
                          ceilings=[np.zeros(len(f)), np.zeros(len(f))])
        self.assertTrue(r['unchanged'])


class ContextTests(unittest.TestCase):
    def test_contexts_cannot_be_silently_pooled(self):
        a = {'listener': 'one', 'baseline_sha256': 'a'*64, 'level_db': 80, 'environment': 'parked'}
        b = dict(a, environment='driving')
        with tempfile.TemporaryDirectory() as td:
            log = Path(td)/'ab_log.json'
            entry = {'sources': {'A': 'bass+1dB.afpx', 'B': 'bass-1dB.afpx'},
                     'reveal': {'X': 'A', 'Y': 'B'}, 'counts': {'X': 3, 'Y': 1}}
            log.write_text(json.dumps([dict(entry, context=a), dict(entry, context=b)]))
            with self.assertRaisesRegex(ValueError, 'mix listening contexts'):
                mmm._trials([str(log)], {}, None)
            trials, skipped = mmm._trials([str(log)], {}, None, a)
            self.assertEqual(1, len(trials))
            self.assertEqual(1, len(skipped))
