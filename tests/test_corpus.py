import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / 'helix-rew-tuner' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import corpus
import measure


class CorpusTests(unittest.TestCase):
    def test_replay_and_group_leak_guard(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = measure.common_grid(20, 20000, 96)
            def trace(name, db):
                path = root / name
                path.write_text('\n'.join('%g %g' % (x, y) for x, y in zip(f, db)), encoding='utf-8')
                return {'file': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'capture_id': name}
            before = trace('before.txt', np.full(len(f), 80.))
            after = trace('after.txt', np.full(len(f), 80.1))
            target = trace('target.txt', np.zeros(len(f)))
            case = {'session_id': 's1', 'vehicle_id': 'v1', 'listener_id': 'l1',
                    'split': 'development', 'before': [before], 'after': [after],
                    'target': 'target.txt', 'target_sha256': target['sha256'],
                    'blind_trials': [{'track': 'song', 'preferred': 'tie'}]}
            out = corpus.replay({'version': 1, 'sessions': [case]}, td)
            self.assertEqual('tie', out['sessions'][0]['verdict'])
            self.assertTrue(out['sessions'][0]['objective_blind_agreement'])
            self.assertEqual(1, out['by_split']['development']['agreement'])
            with self.assertRaisesRegex(ValueError, 'recording was counted'):
                corpus.replay({'version': 1, 'sessions': [dict(case, after=[before])]}, td)
            with self.assertRaisesRegex(ValueError, 'leaks across'):
                corpus.replay({'version': 1, 'sessions': [case, dict(case, session_id='s2', split='held_out')]}, td)
            with self.assertRaisesRegex(ValueError, 'hash changed'):
                corpus.replay({'version': 1, 'sessions': [dict(case, before=[dict(before, sha256='0'*64)])]}, td)
