"""One delay recommendation from several independent estimators, with an
explicit agreement measure -- the research note's "confidence: evidence"
format, built from estimators the skill already has."""

import sys
import unittest
from pathlib import Path

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "helix-rew-tuner" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import measure  # noqa: E402
import tunelib  # noqa: E402


FREQS = measure.common_grid(20.0, 20000.0, 96)


def _lr4(fc, kind):
    s = 1j * FREQS / fc
    bw2 = 1.0 / (s ** 2 + np.sqrt(2.0) * s + 1.0)
    return bw2 ** 2 if kind == "lp" else ((s ** 2) * bw2) ** 2


class DelayConsensusTests(unittest.TestCase):
    def setUp(self):
        self.lower = _lr4(2000.0, "lp")
        self.upper = _lr4(2000.0, "hp")

    def test_estimators_agree_on_a_clean_late_tweeter(self):
        late = self.upper * np.exp(-2j * np.pi * FREQS * 0.10e-3)
        r = tunelib.delay_consensus(FREQS, self.lower, late, 2000.0)
        self.assertAlmostEqual(r["extra_delay_lower_ms"], 0.10, delta=0.015)
        self.assertEqual(r["confidence"], "high")
        self.assertGreaterEqual(len([e for e in r["estimates"] if e["agrees"]]), 3)
        self.assertFalse(r["invert"])

    def test_an_aligned_pair_recommends_nothing(self):
        r = tunelib.delay_consensus(FREQS, self.lower, self.upper, 2000.0)
        self.assertAlmostEqual(r["extra_delay_lower_ms"], 0.0, delta=0.01)

    def test_polarity_is_agreed_when_the_tweeter_is_inverted(self):
        r = tunelib.delay_consensus(FREQS, self.lower, -self.upper, 2000.0)
        self.assertTrue(r["invert"])
        self.assertIn(r["confidence"], ("high", "medium"))

    def test_garbage_phase_is_low_confidence_and_withholds_a_number(self):
        rng = np.random.default_rng(4)
        noisy = np.abs(self.upper) * np.exp(1j * rng.uniform(-np.pi, np.pi, len(FREQS)))
        r = tunelib.delay_consensus(FREQS, self.lower, noisy, 2000.0)
        self.assertEqual(r["confidence"], "low")
        self.assertIsNone(r["recommended_extra_delay_lower_ms"])

    def test_tolerance_scales_with_the_crossover_period(self):
        hi = tunelib.delay_consensus(FREQS, self.lower, self.upper, 2000.0)
        lo = tunelib.delay_consensus(FREQS, _lr4(80.0, "lp"), _lr4(80.0, "hp"), 80.0)
        self.assertGreater(lo["agreement_tolerance_ms"], hi["agreement_tolerance_ms"] * 10)

    def test_a_gross_timing_error_is_flagged_not_aliased_onto_a_lobe(self):
        """Research case 005: a 7 ms timing-reference error is 14 periods at
        2 kHz. Phase tools see only the nearest lobe and would report a small,
        confident-looking delay; the envelope correlation sees where the energy
        really arrives and the consensus must refuse."""
        broken = self.upper * np.exp(-2j * np.pi * FREQS * 7.0e-3)
        r = tunelib.delay_consensus(FREQS, self.lower, broken, 2000.0)
        self.assertTrue(r["timing_suspect"])
        self.assertEqual(r["confidence"], "low")
        self.assertIsNone(r["recommended_extra_delay_lower_ms"])
        self.assertAlmostEqual(r["gross_offset_ms"], 7.0, delta=0.2)

    def test_a_normal_pair_is_not_timing_suspect(self):
        r = tunelib.delay_consensus(FREQS, self.lower, self.upper, 2000.0)
        self.assertFalse(r["timing_suspect"])


if __name__ == "__main__":
    unittest.main()
