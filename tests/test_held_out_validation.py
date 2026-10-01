"""Leave-one-position-out validation of a multi-position PEQ proposal.

The idea, from audio-calibration-mcp and autoeq's room-EQ acceptance policy:
a correction must help positions it was NOT fitted on, and each band must be
one the fitter finds again when any single position is withheld."""

import sys
import unittest
from pathlib import Path

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "helix-rew-tuner" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import measure  # noqa: E402
import tunelib  # noqa: E402


FREQS = measure.common_grid(20.0, 20000.0, 96)
BAND = (60.0, 12000.0)


def _positions(shared, extras, seed=3):
    rng = np.random.default_rng(seed)
    return np.vstack([shared + extra + rng.normal(0.0, 0.3, len(FREQS)) for extra in extras])


class HeldOutValidationTests(unittest.TestCase):
    def setUp(self):
        self.shared = tunelib.cascade_db(FREQS, [(300.0, 1.4, 6.0), (2500.0, 2.0, 4.0)])
        self.flat = np.zeros_like(FREQS)

    def test_a_fault_every_position_shares_is_validated_and_applied(self):
        devs = _positions(self.shared, [self.flat] * 4)
        report = tunelib.held_out_band_validation(FREQS, devs, BAND)
        self.assertEqual(report["verdict"], "validated")
        self.assertEqual(len(report["folds"]), 4)
        self.assertTrue(all(f["held_out_gain_db"] > 0.2 for f in report["folds"]))
        actions = {round(b["f_hz"], -2): b["action"] for b in report["bands"]}
        near_300 = [b for b in report["bands"] if abs(np.log2(b["f_hz"] / 300.0)) < 0.3]
        self.assertTrue(near_300, report["bands"])
        self.assertEqual(near_300[0]["action"], "APPLY", actions)
        self.assertEqual(near_300[0]["confidence"], "high")
        self.assertGreaterEqual(near_300[0]["stability"], 0.75)

    def test_a_feature_only_some_positions_show_is_not_high_confidence(self):
        local = tunelib.peaking_db(FREQS, 1200.0, 3.0, 7.0)
        devs = _positions(self.shared, [local, local, self.flat, self.flat])
        report = tunelib.held_out_band_validation(FREQS, devs, BAND)
        for band in report["bands"]:
            if abs(np.log2(band["f_hz"] / 1200.0)) < 0.25:
                self.assertNotEqual(band["confidence"], "high", band)

    def test_no_shared_fault_gives_nothing_to_validate_or_rejection(self):
        # Each position has its own feature, at a different frequency and sign:
        # nothing is common, so nothing should earn an APPLY.
        extras = [tunelib.peaking_db(FREQS, f, 4.0, g)
                  for f, g in ((500.0, 6.0), (1500.0, -8.0), (4000.0, 6.0), (9000.0, -8.0))]
        devs = _positions(self.flat, extras)
        report = tunelib.held_out_band_validation(FREQS, devs, BAND)
        self.assertIn(report["verdict"], ("nothing_to_validate", "not_validated"))
        self.assertFalse(any(b["action"] == "APPLY" for b in report["bands"]))

    def test_needs_three_positions(self):
        with self.assertRaises(ValueError):
            tunelib.held_out_band_validation(FREQS, _positions(self.shared, [self.flat] * 2), BAND)


if __name__ == "__main__":
    unittest.main()
