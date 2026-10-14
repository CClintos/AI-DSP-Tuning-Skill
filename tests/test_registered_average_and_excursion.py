"""Multi-position complex averaging must register arrivals first, and an
Fs-only excursion check may warn but never clear a driver as safe."""

import sys
import unittest
from pathlib import Path

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "helix-rew-tuner" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import measure  # noqa: E402
import tunelib  # noqa: E402


FREQS = measure.common_grid(20.0, 20000.0, 96)


def _lr4_hp(fc):
    s = 1j * FREQS / fc
    return ((s ** 2) / (s ** 2 + np.sqrt(2.0) * s + 1.0)) ** 2


class RegisteredAverageTests(unittest.TestCase):
    def setUp(self):
        self.driver = _lr4_hp(1500.0)
        # the same driver at three head positions: extra path 0, 5, 10 cm
        self.traces = [self.driver * np.exp(-2j * np.pi * FREQS * t)
                       for t in (0.0, 0.15e-3, 0.30e-3)]

    def test_unregistered_averaging_is_refused_by_default(self):
        with self.assertRaisesRegex(ValueError, "register"):
            tunelib.complex_vector_average(self.traces)

    def test_the_old_behaviour_invents_a_notch(self):
        avg = tunelib.complex_vector_average(self.traces, allow_unregistered=True)
        i = int(np.argmin(np.abs(FREQS - 2500.0)))
        self.assertLess(20 * np.log10(abs(avg[i]) / abs(self.driver[i])), -10.0)

    def test_registered_average_keeps_the_driver_and_the_first_arrival(self):
        avg, info = tunelib.complex_vector_average(self.traces, freqs=FREQS, return_details=True)
        sel = (FREQS > 1000.0) & (FREQS < 16000.0)
        err_db = 20 * np.log10(np.abs(avg[sel]) / np.abs(self.driver[sel]))
        self.assertLess(float(np.max(np.abs(err_db))), 0.2)
        self.assertLess(float(np.max(np.abs(np.angle(avg[sel] / self.driver[sel])))), np.radians(5))
        self.assertAlmostEqual(info["delays_ms"][1], 0.15, delta=0.005)
        self.assertAlmostEqual(info["delays_ms"][2], 0.30, delta=0.005)

    def test_explicit_delays_are_used_as_given(self):
        avg = tunelib.complex_vector_average(self.traces, freqs=FREQS,
                                             delays_s=[0.0, 0.15e-3, 0.30e-3])
        self.assertTrue(np.allclose(avg, self.driver, atol=1e-9))

    def test_position_specific_combs_still_cancel_after_registration(self):
        combs = [self.traces[k] * (1 + 0.3 * np.exp(1j * (FREQS / 200.0 + 2.1 * k)))
                 for k in range(3)]
        avg, info = tunelib.complex_vector_average(combs, freqs=FREQS, return_details=True)
        sel = (FREQS > 2000.0) & (FREQS < 12000.0)
        self.assertLess(float(np.mean(np.abs(np.abs(avg[sel]) - np.abs(self.driver[sel])))), 0.12)
        self.assertEqual(len(info["coherence"]), len(FREQS))


class ExcursionAdvisoryTests(unittest.TestCase):
    def test_flags_a_steep_hpf_near_fs(self):
        r = tunelib.hpf_excursion_risk(35.0, 24.0, driver_fs_hz=32.0)
        self.assertTrue(r["excursion_risk"])

    def test_never_clears_a_driver_from_fs_alone(self):
        r = tunelib.hpf_excursion_risk(80.0, 24.0, driver_fs_hz=32.0)
        self.assertIsNone(r["excursion_risk"])
        self.assertFalse(r["cleared"])
        self.assertIn("Xmax", r["note"])


if __name__ == "__main__":
    unittest.main()
