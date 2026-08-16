"""Regression coverage for the source audit, imaging, and reflection mapper.

These three answer questions nothing else in the skill can:
  * is the signal ENTERING the DSP level-independent?
  * where does the image sit as a function of FREQUENCY?
  * what physically CAUSED this dip?

Each test builds ground truth analytically, so a failure means the analysis
moved -- not that a fixture drifted.
"""

import sys
import unittest
from pathlib import Path

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "helix-rew-tuner" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import decay
import tunelib


def _axis():
    return 24000.0 / (tunelib.LOGSTEP ** (1231 - np.arange(1232)))


class SourceAuditTests(unittest.TestCase):
    def setUp(self):
        self.freqs = _axis()
        self.base = 80.0 + tunelib.peaking_db(self.freqs, 900.0, 1.2, -3.0)
        self.cmd = [0.0, -6.0, -12.0, -18.0]

    def test_clean_source_reports_clean(self):
        traces = [self.base + c for c in self.cmd]
        self.assertEqual(
            tunelib.source_level_audit(self.freqs, traces, self.cmd)["verdict"],
            "clean")

    def test_loudness_contour_is_caught_and_localised_to_the_bass(self):
        shelf = tunelib.low_shelf_db(self.freqs, 120.0, 0.7, 6.0)
        traces = [self.base + c + (abs(c) / 18.0) * shelf for c in self.cmd]
        a = tunelib.source_level_audit(self.freqs, traces, self.cmd)
        self.assertEqual(a["verdict"], "level_dependent_shape")
        worst = max(a["steps"], key=lambda s: s["max_shape_db"])
        peak_hz = self.freqs[int(np.argmax(np.abs(worst["shape_delta_db"])))]
        self.assertLess(peak_hz, 300.0)

    def test_compression_is_caught_from_level_tracking(self):
        traces = [self.base + c * 0.85 for c in self.cmd]
        self.assertEqual(
            tunelib.source_level_audit(self.freqs, traces, self.cmd)["verdict"],
            "compression")

    def test_acoustic_capture_refuses_to_blame_the_source(self):
        """Driver compression and a source contour are the same measurement."""
        shelf = tunelib.low_shelf_db(self.freqs, 120.0, 0.7, 6.0)
        traces = [self.base + c + (abs(c) / 18.0) * shelf for c in self.cmd]
        acoustic = tunelib.source_level_audit(self.freqs, traces, self.cmd)
        self.assertEqual(acoustic["attribution"], "source_or_driver_compression")
        self.assertTrue(any("CANNOT ATTRIBUTE" in n for n in acoustic["notes"]))
        electrical = tunelib.source_level_audit(self.freqs, traces, self.cmd,
                                                electrical=True)
        self.assertEqual(electrical["attribution"], "source")

    def test_shape_test_still_runs_without_commanded_levels(self):
        """The more diagnostic half must not require knowing the volume steps."""
        shelf = tunelib.low_shelf_db(self.freqs, 120.0, 0.7, 6.0)
        traces = [self.base + c + (abs(c) / 18.0) * shelf for c in self.cmd]
        a = tunelib.source_level_audit(self.freqs, traces, None)
        self.assertEqual(a["verdict"], "level_dependent_shape")
        self.assertTrue(all(s["tracking_error_db"] is None for s in a["steps"]))

    def test_single_trace_cannot_audit_anything(self):
        a = tunelib.source_level_audit(self.freqs, [self.base], None)
        self.assertEqual(a["verdict"], "insufficient_traces")

    def test_bandwidth_limit_finds_a_built_highpass(self):
        x = (self.freqs / 80.0) ** 2
        hp = 20 * np.log10(x / np.sqrt(1.0 + x ** 2))
        bw = tunelib.source_bandwidth_limits(self.freqs, self.base + hp)
        self.assertTrue(45.0 < bw["low_hz"] < 90.0)


class ImagingTests(unittest.TestCase):
    def setUp(self):
        self.freqs = _axis()
        self.flat = 80.0 * np.ones_like(self.freqs)
        self.zero_ph = np.zeros_like(self.freqs)

    def _rows(self, left_db, right_db, left_ph=None, right_ph=None):
        return tunelib.band_itd_ild(self.freqs, left_db, right_db, left_ph, right_ph)

    def test_recovers_a_known_itd(self):
        lead = 300e-6
        right_ph = np.rad2deg(2 * np.pi * self.freqs * lead)
        rows = self._rows(self.flat, self.flat, self.zero_ph, right_ph)
        low = [r for r in rows if r["f_hi"] <= 400][0]
        self.assertAlmostEqual(low["itd_us"], 300.0, delta=25.0)
        self.assertGreater(low["itd_fit_quality"], 0.95)

    def test_opposing_cues_across_the_duplex_region_read_as_smeared(self):
        """The failure a single delay value cannot represent."""
        right_db = self.flat + tunelib.high_shelf_db(self.freqs, 2000.0, 0.7, 6.0)
        right_ph = np.rad2deg(2 * np.pi * self.freqs * 300e-6)
        pull = tunelib.image_pull(
            self._rows(self.flat, right_db, self.zero_ph, right_ph))
        self.assertEqual(pull["verdict"], "smeared")
        low = [b for b in pull["bands"] if b["f_hi"] <= 400][0]
        high = [b for b in pull["bands"] if b["f_lo"] >= 5000][0]
        self.assertEqual(low["side"], "left")     # time cue wins down low
        self.assertEqual(high["side"], "right")   # level cue wins up high

    def test_centred_system_is_stable(self):
        pull = tunelib.image_pull(
            self._rows(self.flat, self.flat.copy(), self.zero_ph, self.zero_ph.copy()))
        self.assertEqual(pull["verdict"], "stable")

    def test_uniform_offset_is_pulled_not_smeared(self):
        """One delay DOES fix this case, so it must not be called smeared."""
        pull = tunelib.image_pull(
            self._rows(self.flat + 3.0, self.flat, self.zero_ph, self.zero_ph.copy()))
        self.assertEqual(pull["verdict"], "pulled")

    def test_unusable_phase_fit_is_discarded_not_blended(self):
        noise = np.random.default_rng(5).normal(0, 120.0, len(self.freqs))
        pull = tunelib.image_pull(
            self._rows(self.flat, self.flat.copy(), noise, self.zero_ph))
        self.assertTrue(any(b["dominant_cue"].startswith("level (time cue unusable)")
                            for b in pull["bands"]))

    def test_level_only_still_works_without_phase(self):
        """A UNIFORM level offset is the one-fix case, and stays so without phase."""
        rows = self._rows(self.flat + 3.0, self.flat)
        self.assertTrue(all(r["itd_us"] is None for r in rows))
        self.assertEqual(tunelib.image_pull(rows)["verdict"], "pulled")

    def test_frequency_dependent_level_alone_is_smeared(self):
        """A shelf is not an offset: it moves the image with frequency, so a
        single level trim cannot centre it any more than a single delay could."""
        right_db = self.flat + tunelib.high_shelf_db(self.freqs, 2000.0, 0.7, 6.0)
        pull = tunelib.image_pull(self._rows(self.flat, right_db))
        self.assertEqual(pull["verdict"], "smeared")
        low = [b for b in pull["bands"] if b["f_hi"] <= 400][0]
        high = [b for b in pull["bands"] if b["f_lo"] >= 5000][0]
        self.assertEqual(low["side"], "centre")
        self.assertEqual(high["side"], "right")


class ReflectionTests(unittest.TestCase):
    FS = 48000.0
    N = 1 << 16

    def _two_path(self, delay_ms, level_db, noise_db=-70.0, seed=3):
        rng = np.random.default_rng(seed)
        ir = np.zeros(self.N)
        ir[480] = 1.0
        ir[480 + int(round(delay_ms * 1e-3 * self.FS))] = 10 ** (level_db / 20.0)
        return ir + rng.normal(0, 10 ** (noise_db / 20.0), self.N)

    def test_recovers_delay_level_and_geometry(self):
        rep = decay.reflections(self._two_path(1.40, -8.0), self.FS)
        self.assertTrue(rep["arrivals"])
        a = rep["arrivals"][0]
        self.assertAlmostEqual(a["delay_ms"], 1.40, delta=0.06)
        self.assertAlmostEqual(a["level_db"], -8.0, delta=2.5)
        self.assertAlmostEqual(a["path_diff_cm"], 1.40e-3 * 343.0 * 100.0, delta=3.0)
        self.assertAlmostEqual(a["comb_null_hz"], 1.0 / (2 * 1.40e-3), delta=25.0)

    def test_clean_ir_invents_nothing(self):
        rng = np.random.default_rng(3)
        clean = np.zeros(self.N)
        clean[480] = 1.0
        clean += rng.normal(0, 10 ** (-70.0 / 20.0), self.N)
        self.assertEqual(decay.reflections(clean, self.FS)["arrivals"], [])

    def test_comb_prediction_accepts_its_nulls_and_rejects_an_unrelated_dip(self):
        rep = decay.reflections(self._two_path(1.40, -8.0), self.FS)
        first_null = 1.0 / (2 * 1.40e-3)
        m = decay.comb_matches(rep["arrivals"][:1],
                               [first_null, first_null * 3.0, 137.0])[0]
        self.assertEqual(m["match_count"], 2)
        self.assertFalse(any(abs(h["dip_hz"] - 137.0) < 1.0 for h in m["matched"]))

    def test_null_depth_bounds_what_an_arrival_can_explain(self):
        """A quiet reflection cannot produce a deep hole."""
        quiet = decay.reflections(self._two_path(1.40, -20.0), self.FS)["arrivals"][0]
        loud = decay.reflections(self._two_path(1.40, -2.0), self.FS)["arrivals"][0]
        self.assertLess(abs(quiet["null_depth_db"]), abs(loud["null_depth_db"]))


if __name__ == "__main__":
    unittest.main()
