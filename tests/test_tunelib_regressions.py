"""Regression coverage for confidence-aware DSP fitting."""

import sys
import unittest
from pathlib import Path

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "helix-rew-tuner" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import tunelib


class PartnerConfidenceTests(unittest.TestCase):
    def test_zero_confidence_3khz_partner_mismatch_does_not_add_filter(self):
        """A zero-confidence partner mismatch must not spend a boost band."""
        freqs = np.geomspace(100.0, 10000.0, 401)
        target = np.zeros_like(freqs)
        partner = tunelib.peaking_db(freqs, 3000.0, 2.0, 4.0)
        zero_confidence = np.zeros_like(freqs)

        bands, report = tunelib.fit_peq(
            freqs, target, (200.0, 8000.0), n_bands_max=3,
            partner_target_db=partner, partner_weight=3.0,
            partner_band=(700.0, 5000.0), partner_conf=zero_confidence,
        )

        self.assertEqual([], bands)
        self.assertLessEqual(report["score_after"], report["score_before"])


class SpatialConsistencyTests(unittest.TestCase):
    def test_alignment_recognizes_identical_shapes_at_different_levels(self):
        """Broadband level offsets must not make identical shapes inconsistent."""
        freqs = np.geomspace(20.0, 20000.0, 601)
        shape = (tunelib.peaking_db(freqs, 300.0, 1.2, -4.0)
                 + tunelib.peaking_db(freqs, 2500.0, 1.8, 3.0))

        result = tunelib.spatial_consistency(
            freqs, [shape - 2.0, shape, shape + 2.0],
            alignment_band=(100.0, 10000.0),
        )

        self.assertGreaterEqual(float(np.mean(result["mask"])), 0.99)
        np.testing.assert_allclose(result["level_offsets_db"], [-2.0, 0.0, 2.0],
                                   atol=0.05)


if __name__ == "__main__":
    unittest.main()
