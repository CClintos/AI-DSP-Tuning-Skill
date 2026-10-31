"""Counterexamples for one-pass provenance and MMM pooling authority."""
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / 'helix-rew-tuner' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import pipeline
import tunelib


class MeasurementAuthorityTests(unittest.TestCase):
    def test_power_pool_preserves_absolute_level_and_differs_from_db_mean(self):
        runs = np.array([[70., 70.], [80., 70.]])
        pooled = tunelib.mmm_power_pool(runs)
        self.assertAlmostEqual(77.4036, pooled[0], places=3)
        self.assertAlmostEqual(70., pooled[1], places=3)
        self.assertGreater(pooled[0], np.mean(runs[:, 0]) + 2)

    def test_two_halves_of_one_recording_cannot_claim_repeatability(self):
        with tempfile.TemporaryDirectory() as td:
            paths = []
            for name in ('half1', 'half2'):
                path = Path(td) / (name + '.txt')
                path.write_text('* capture_id: abc123\n* evidence_role: within_capture_half\n20 70\n100 70\n',
                                encoding='utf-8')
                paths.append(str(path))
            with self.assertRaisesRegex(ValueError, 'SAME MMM recording'):
                pipeline._independent_capture_paths(paths)
            self.assertEqual('abc123', pipeline._capture_id(paths[0]))

    def test_independent_full_passes_remain_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            paths = []
            for i in range(2):
                path = Path(td) / ('pass%d.txt' % i)
                path.write_text('* capture_id: distinct%d\n20 70\n100 70\n' % i,
                                encoding='utf-8')
                paths.append(str(path))
            pipeline._independent_capture_paths(paths)


if __name__ == '__main__':
    unittest.main()
