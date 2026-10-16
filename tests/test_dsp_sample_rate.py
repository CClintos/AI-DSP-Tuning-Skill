"""A confirmed DSP rate must control fitting, validation and filter footprints."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "helix-rew-tuner" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import measure
import pipeline
import tunelib


class DspSampleRateTests(unittest.TestCase):
    def setUp(self):
        self.freqs = np.geomspace(100.0, 20000.0, 400)
        self.band = (6000.0, 15000.0)
        self.peak = tunelib.peaking_db(self.freqs, 11000.0, 1.3, 6.0, fs=48000.0)

    def assert_cancels_48khz_peak(self, bands):
        self.assertEqual(len(bands), 1)
        np.testing.assert_allclose(bands[0], (11000.0, 1.3, -6.0), atol=0.01)
        actual = self.peak + tunelib.cascade_db(self.freqs, bands, fs=48000.0)
        wrong_rate = self.peak + tunelib.cascade_db(self.freqs, bands, fs=96000.0)
        self.assertLess(tunelib.audibility_score(self.freqs, actual, band=self.band), 0.01)
        self.assertGreater(tunelib.audibility_score(self.freqs, wrong_rate, band=self.band), 0.1)

    def test_single_position_fits_the_confirmed_48khz_filter_shape(self):
        bands, report = tunelib.fit_peq(
            self.freqs, self.peak, self.band, n_bands_max=1, fs=48000.0)
        self.assert_cancels_48khz_peak(bands)
        self.assertLess(report["score_after"], 0.01)

    def test_robust_fit_uses_48khz_for_selection_and_position_scores(self):
        bands, report = tunelib.fit_peq_robust(
            self.freqs, np.vstack([self.peak] * 3), self.band,
            n_bands_max=1, fs=48000.0)
        self.assert_cancels_48khz_peak(bands)
        self.assertTrue(all(v < 0.01 for v in report["position_scores_after"]))

    def test_held_out_folds_are_scored_at_the_same_rate_as_their_fit(self):
        report = tunelib.held_out_band_validation(
            self.freqs, np.vstack([self.peak] * 3), self.band,
            fitter_kwargs={"n_bands_max": 1}, fs=48000.0)
        bands = [(r["f_hz"], r["q"], r["gain_db"]) for r in report["bands"]]
        before = tunelib.audibility_score(self.freqs, self.peak, band=self.band)
        after = tunelib.audibility_score(
            self.freqs, self.peak + tunelib.cascade_db(self.freqs, bands, fs=48000.0),
            band=self.band)
        self.assertEqual(report["verdict"], "validated")
        for fold in report["folds"]:
            self.assertAlmostEqual(fold["held_out_gain_db"], before - after, places=3)

    def test_refinement_adds_a_filter_with_the_confirmed_48khz_shape(self):
        report = tunelib.refine_bank(
            self.freqs, [self.peak], [], (100.0, 15000.0),
            fs=48000.0, max_edits=1, free_slots=1)
        self.assertEqual([e["action"] for e in report["edits"]], ["add"])
        self.assertAlmostEqual(report["bank"][0][1], 1.3, delta=0.05)
        residual = self.peak + tunelib.cascade_db(self.freqs, report["bank"], fs=48000.0)
        wrong_rate = self.peak + tunelib.cascade_db(self.freqs, report["bank"], fs=96000.0)
        self.assertLess(tunelib.audibility_score(self.freqs, residual, band=self.band), 0.03)
        self.assertGreater(tunelib.audibility_score(self.freqs, wrong_rate, band=self.band), 0.1)

    def test_headroom_uses_the_confirmed_overlap_between_high_frequency_boosts(self):
        bands = [(12000.0, 1.0, 3.0), (16000.0, 1.0, 3.0)]
        actual = tunelib.headroom_report(self.freqs, bands, fs=48000.0)
        wrong_rate = tunelib.headroom_report(self.freqs, bands, fs=96000.0)
        self.assertAlmostEqual(actual["peak_cascade_gain_db"], 4.57, places=2)
        self.assertEqual(actual["recommended_trim_db"], -4.57)
        self.assertGreater(wrong_rate["peak_cascade_gain_db"] - actual["peak_cascade_gain_db"], 0.8)

    def test_phase_boost_gate_uses_the_confirmed_filter_footprint(self):
        # At 16 kHz the 48 kHz filter has fallen below half its peak gain;
        # the wider 96 kHz realization still reaches the phase anomaly.
        fields = {"g": np.array([12000.0, 16000.0]),
                  "s": np.array([0.0, 12.0]), "dip_db": np.array([0.0, 8.0])}
        band = [(12000.0, 1.0, 3.0)]
        rows48, _ = tunelib.gate_boost_bands(fields, band, fs=48000.0)
        rows96, _ = tunelib.gate_boost_bands(fields, band, fs=96000.0)
        self.assertEqual(rows48[0]["verdict"], "ALLOW")
        self.assertEqual(rows96[0]["verdict"], "BLOCK")

    def test_vehicle_guard_uses_the_confirmed_filter_skirt(self):
        guards = {"no_boost": [{"lo_hz": 16400.0, "hi_hz": 16600.0,
                                "channels": None, "reason": "measured null"}]}
        f = np.array([16500.0])
        self.assertIsNone(pipeline.guard_check(guards, freqs=f, fs=48000.0)(12000.0, 4.0, 3.0))
        self.assertIn("measured null", pipeline.guard_check(
            guards, freqs=f, fs=96000.0)(12000.0, 4.0, 3.0))


class ProposeSampleRateCliTests(unittest.TestCase):
    def test_missing_or_invalid_rate_is_refused_before_loading_measurements(self):
        base = [sys.executable, str(SCRIPTS / "pipeline.py"), "propose",
                "--measurement", "does-not-exist.txt", "--target", "default"]
        for tail, message in (([], "--dsp-rate"), (["--dsp-rate", "nan"], "finite and positive"),
                              (["--dsp-rate", "0"], "finite and positive"),
                              (["--dsp-rate", "40000"], "highest modeled frequency")):
            with self.subTest(arguments=tail):
                run = subprocess.run(base + tail, text=True, capture_output=True)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn(message, run.stderr)
                self.assertNotIn("No such file", run.stderr)

    def test_one_two_and_three_position_reports_predict_at_48khz(self):
        freqs = measure.common_grid(20.0, 20000.0, 96)
        target = measure.load_target(SCRIPTS.parent / "assets" / "default_incar_target.txt", freqs)
        shape = tunelib.peaking_db(freqs, 11000.0, 1.3, 6.0, fs=48000.0)
        with tempfile.TemporaryDirectory() as tmp:
            paths, captures = [], []
            for i in range(3):
                capture = 80.0 + target + shape + np.random.default_rng(i).normal(0, 0.005, len(freqs))
                path = Path(tmp) / ("position%d.txt" % i)
                path.write_text("\n".join("%.8f %.8f" % (f, s) for f, s in zip(freqs, capture)),
                                encoding="utf-8")
                paths.append(str(path))
                captures.append(capture)
            for n in (1, 2, 3):
                with self.subTest(positions=n):
                    inputs = ["--measurement", paths[0]] if n == 1 else ["--positions", *paths[:n]]
                    run = subprocess.run(
                        [sys.executable, str(SCRIPTS / "pipeline.py"), "propose", *inputs,
                         "--target", "default", "--dsp-rate", "48000", "--max-bands", "1"],
                        text=True, capture_output=True)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    report = json.loads(run.stdout)
                    self.assertEqual(report["meta"]["dsp_sample_rate_hz"], 48000.0)
                    bands = [(r["f_hz"], r["q"], r["gain_db"])
                             for r in report["proposal"]["bands"]]
                    self.assertTrue(bands)
                    dev = np.mean(captures[:n], axis=0) - target - report["meta"]["anchor_offset_db"]
                    score48 = tunelib.audibility_score(
                        freqs, dev + tunelib.cascade_db(freqs, bands, fs=48000.0), band=(60.0, 12000.0))
                    score96 = tunelib.audibility_score(
                        freqs, dev + tunelib.cascade_db(freqs, bands, fs=96000.0), band=(60.0, 12000.0))
                    self.assertAlmostEqual(report["prediction"]["score_after_db"], score48, delta=0.01)
                    self.assertGreater(abs(score48 - score96), 0.01)


if __name__ == "__main__":
    unittest.main()
