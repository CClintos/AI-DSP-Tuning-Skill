"""Calibration cases with known right answers (the research note's case list).
Each one drives the same functions a tuning session uses, so an algorithm
change that turns a right decision into a wrong one fails here."""

import json
import subprocess
import sys
import tempfile
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


def _target():
    return measure.load_target(SCRIPTS.parent / "assets" / "default_incar_target.txt", FREQS)


def _export(path, spl_db, phase_deg=None):
    rows = ["* Freq(Hz) SPL(dB)" + (" Phase(degrees)" if phase_deg is not None else "")]
    for i, f in enumerate(FREQS):
        rows.append("%.4f %.4f" % (f, spl_db[i]) +
                    (" %.4f" % phase_deg[i] if phase_deg is not None else ""))
    Path(path).write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(path)


def _propose(*args):
    run = subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), "propose", *args,
                          "--target", "default"], text=True, capture_output=True, check=False)
    if run.returncode != 0:
        raise AssertionError(run.stdout + run.stderr)
    return json.loads(run.stdout)


def _near(bands, hz, oct_=0.33):
    return [b for b in bands if abs(np.log2(b["f_hz"] / hz)) < oct_]


class CalibrationCases(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_case_001_detects_a_mid_delayed_by_0_40_ms(self):
        mid = _lr4(800.0, "lp") * np.exp(-2j * np.pi * FREQS * 0.40e-3)
        tweeter = _lr4(800.0, "hp")
        r = tunelib.delay_consensus(FREQS, mid, tweeter, 800.0)
        # the MID is late, so the fix is 0.40 ms more on the tweeter (= -0.40 on the mid)
        self.assertAlmostEqual(r["recommended_extra_delay_lower_ms"], -0.40, delta=0.02)
        self.assertEqual(r["confidence"], "high")

    def test_case_002_a_crossover_cancellation_is_a_polarity_job_not_a_boost(self):
        mid, tweeter = _lr4(2000.0, "lp"), -_lr4(2000.0, "hp")
        r = tunelib.delay_consensus(FREQS, mid, tweeter, 2000.0)
        self.assertTrue(r["invert"])
        total = mid + tweeter
        spl = 80 + _target() + 20 * np.log10(np.abs(total) + 1e-6)
        report = _propose("--measurement", _export(self.root / "sum.txt", spl,
                                                   np.degrees(np.angle(total))))
        boosts = [b for b in _near(report["proposal"]["bands"], 2000.0) if b["gain_db"] > 0]
        self.assertEqual(boosts, [], report["proposal"])

    def test_case_003_a_broad_8_db_resonance_gets_a_cut(self):
        spl = 80 + _target() + tunelib.peaking_db(FREQS, 400.0, 1.0, 8.0)
        report = _propose("--measurement", _export(self.root / "res.txt", spl))
        near = _near(report["proposal"]["bands"], 400.0)
        self.assertTrue(near, report["proposal"])
        self.assertLessEqual(min(b["gain_db"] for b in near), -4.0)

    def test_case_004_a_deep_narrow_null_at_one_position_is_not_boosted(self):
        paths = []
        for i in range(3):
            null = tunelib.peaking_db(FREQS, 1000.0, 8.0, -15.0) if i == 0 else 0.0
            paths.append(_export(self.root / ("p%d.txt" % i), 80 + _target() + null))
        report = _propose("--positions", *paths)
        self.assertEqual([b for b in _near(report["proposal"]["bands"], 1000.0) if b["gain_db"] > 0], [])

    def test_case_005_a_7_ms_timing_reference_error_is_flagged(self):
        mid, tweeter = _lr4(2000.0, "lp"), _lr4(2000.0, "hp") * np.exp(-2j * np.pi * FREQS * 7e-3)
        r = tunelib.delay_consensus(FREQS, mid, tweeter, 2000.0)
        self.assertTrue(r["timing_suspect"])
        self.assertIsNone(r["recommended_extra_delay_lower_ms"])

    def test_case_006_a_peak_that_moves_between_positions_is_not_applied(self):
        paths = []
        for i, f0 in enumerate((215.0, 250.0, 290.0)):
            paths.append(_export(self.root / ("m%d.txt" % i),
                                 80 + _target() + tunelib.peaking_db(FREQS, f0, 6.0, 7.0)))
        report = _propose("--positions", *paths)
        # A gentle broad trim of the averaged hump is fine; a deep or narrow
        # notch aimed at one seat's peak is the failure (it was -12.5 dB Q8).
        for b in _near(report["proposal"]["bands"], 250.0, 0.25):
            self.assertGreater(b["gain_db"], -3.0, b)
            self.assertLess(b["q"], 3.0, b)


if __name__ == "__main__":
    unittest.main()
