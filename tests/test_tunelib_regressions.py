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
        partner = tunelib.peaking_db(freqs, 3000.0, 8.0, 4.0)
        zero_confidence = np.ones_like(freqs)
        zero_confidence[(freqs >= 2000.0) & (freqs <= 4500.0)] = 0.0

        bands, report = tunelib.fit_peq(
            freqs, target, (200.0, 8000.0), n_bands_max=3,
            partner_target_db=partner, partner_weight=3.0,
            partner_band=(700.0, 5000.0), conf=zero_confidence,
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

    def test_alignment_band_without_samples_is_rejected(self):
        """Alignment must not turn a non-overlapping band into NaN confidence."""
        freqs = np.geomspace(20.0, 80.0, 101)
        traces = [np.zeros_like(freqs), np.ones_like(freqs), -np.ones_like(freqs)]

        with self.assertRaisesRegex(ValueError, "alignment_band.*no finite samples"):
            tunelib.spatial_consistency(freqs, traces)


class RobustPeqTests(unittest.TestCase):
    def test_masked_nonfinite_samples_are_excluded_from_robust_fit(self):
        """Masked non-finite samples must be safely excluded from fitting."""
        freqs = np.geomspace(100.0, 10000.0, 401)
        shared_peak = tunelib.peaking_db(freqs, 800.0, 0.8, 4.0)
        deviations = np.vstack([shared_peak, shared_peak, shared_peak])
        mask = np.ones_like(deviations, dtype=bool)
        for position, index, value in (
                (0, 100, np.nan), (1, 200, np.inf), (2, 300, -np.inf)):
            deviations[position, index] = value
            mask[position, index] = False

        bands, report = tunelib.fit_peq_robust(
            freqs, deviations, (200.0, 6000.0), mask=mask,
            n_bands_max=1, improve_pct=3.0,
        )

        self.assertTrue(any(500.0 <= f <= 1300.0 and gain <= -1.0
                            for f, _q, gain in bands))
        self.assertTrue(all(np.isfinite(report[key]) for key in (
            "score_before", "score_after", "worst_position_loss_db")))
        self.assertTrue(all(np.isfinite(report[key]).all() for key in (
            "position_scores_before", "position_scores_after")))

    def test_shared_broad_peak_is_cut_for_every_position(self):
        """Removing robust fitting must leave a shared peak uncorrected."""
        freqs = np.geomspace(100.0, 10000.0, 401)
        shared_peak = tunelib.peaking_db(freqs, 800.0, 0.8, 4.0)
        deviations = np.vstack([
            shared_peak,
            0.9 * shared_peak,
            1.1 * shared_peak,
        ])

        bands, report = tunelib.fit_peq_robust(
            freqs, deviations, (200.0, 6000.0), n_bands_max=2,
            improve_pct=3.0,
        )

        self.assertTrue(any(500.0 <= f <= 1300.0 and gain <= -1.0
                            for f, _q, gain in bands))
        self.assertTrue(all(after < before for before, after in zip(
            report["position_scores_before"], report["position_scores_after"])))

    def test_position_specific_notch_does_not_attract_a_boost(self):
        """Changing the seed from a positional median can boost a one-seat null."""
        freqs = np.geomspace(100.0, 10000.0, 401)
        flat = np.zeros_like(freqs)
        one_seat_notch = tunelib.peaking_db(freqs, 3200.0, 5.0, -10.0)

        bands, _report = tunelib.fit_peq_robust(
            freqs, np.vstack([flat, flat, one_seat_notch]),
            (200.0, 6000.0), n_bands_max=2, improve_pct=3.0,
        )

        self.assertEqual([], bands)

    def test_worst_position_guard_rejects_mean_improving_candidate(self):
        """Removing the guard must allow a majority-helping cut to harm one seat."""
        freqs = np.geomspace(100.0, 10000.0, 401)
        peak = tunelib.peaking_db(freqs, 1000.0, 1.0, 4.0)
        shallow_dip = tunelib.peaking_db(freqs, 1000.0, 1.0, -1.0)
        deviations = np.vstack([peak, peak, shallow_dip])

        permissive, _ = tunelib.fit_peq_robust(
            freqs, deviations, (200.0, 6000.0), n_bands_max=1,
            improve_pct=3.0, max_worst_loss_db=10.0,
        )
        guarded, report = tunelib.fit_peq_robust(
            freqs, deviations, (200.0, 6000.0), n_bands_max=1,
            improve_pct=3.0, max_worst_loss_db=0.25,
        )

        self.assertNotEqual([], permissive)
        self.assertEqual([], guarded)
        self.assertTrue(report["rejected_worst_position"])
        self.assertEqual(0.0, report["worst_position_loss_db"])


class ConfidenceAwareScorecardTests(unittest.TestCase):
    def test_mask_and_confidence_exclude_untrusted_outliers_from_metrics(self):
        """Ignoring mask/conf must let synthetic outliers inflate the scorecard."""
        freqs = np.geomspace(100.0, 8000.0, 601)
        system_sum = np.full_like(freqs, 2.0)
        system_sum[(freqs >= 400.0) & (freqs <= 500.0)] = 42.0
        system_sum[(freqs >= 1400.0) & (freqs <= 1600.0)] = 32.0
        mask = np.ones_like(freqs, dtype=bool)
        mask[(freqs >= 300.0) & (freqs <= 650.0)] = False
        conf = np.ones_like(freqs)
        conf[(freqs >= 1000.0) & (freqs <= 2200.0)] = 0.0
        traces = {
            "System Sum": system_sum,
            "FL Low": np.ones_like(freqs),
            "FR Low": np.zeros_like(freqs),
            "FL High": -np.ones_like(freqs),
            "FR High": np.zeros_like(freqs),
        }

        scorecard = tunelib.tune_scorecard(
            freqs, traces, np.zeros_like(freqs), mask=mask, conf=conf,
        )

        self.assertEqual(2.0, scorecard["sum_rms_db"])
        self.assertEqual(2.0, scorecard["sum_wrms_img_db"])
        self.assertEqual(2.0, scorecard["worst_dev_db"])
        self.assertEqual(1.0, scorecard["mid_balance_db"])
        self.assertEqual(1.0, scorecard["mid_balance_abs_rms_db"])
        self.assertEqual(-1.0, scorecard["tweeter_balance_db"])
        self.assertEqual(1.0, scorecard["tweeter_balance_abs_rms_db"])


if __name__ == "__main__":
    unittest.main()
