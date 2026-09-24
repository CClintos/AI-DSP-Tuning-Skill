"""pipeline.py propose: one deterministic EQ proposal instead of ad-hoc fitting."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "helix-rew-tuner" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import measure  # noqa: E402
import tunelib  # noqa: E402


FREQS = measure.common_grid(20.0, 20000.0, 96)


def _target():
    return measure.load_target(
        SCRIPTS.parent / "assets" / "default_incar_target.txt", FREQS)


def _write_export(path, spl_db):
    rows = ["* Freq(Hz) SPL(dB)"]
    rows += ["%.4f %.3f" % (f, s) for f, s in zip(FREQS, spl_db)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


class ProposeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def run_cli(self, *args):
        run = subprocess.run(
            [sys.executable, str(SCRIPTS / "pipeline.py"), *args],
            text=True, capture_output=True, check=False, cwd=self.root)
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        return json.loads(run.stdout)

    def test_single_position_proposes_cuts_on_real_peaks_and_writes_nothing(self):
        spl = 80 + _target() + tunelib.cascade_db(
            FREQS, [(180.0, 1.5, 5.0), (2600.0, 2.0, 4.0)])
        meas = self.root / "sum.txt"
        _write_export(meas, spl)
        before = sorted(p.name for p in self.root.iterdir())

        report = self.run_cli("propose", "--measurement", str(meas),
                              "--target", "default")

        self.assertEqual(before, sorted(p.name for p in self.root.iterdir()))
        bands = report["proposal"]["bands"]
        self.assertGreaterEqual(len(bands), 2)
        centres = [b["f_hz"] for b in bands]
        for real in (180.0, 2600.0):
            nearest = min(centres, key=lambda f: abs(np.log2(f / real)))
            self.assertLess(abs(np.log2(nearest / real)), 0.25)
        for band in bands:
            self.assertLess(band["gain_db"], 0.0)
            tunelib.validate_peq_band(band["f_hz"], band["q"], band["gain_db"])
        pred = report["prediction"]
        self.assertLess(pred["score_after_db"], pred["score_before_db"])
        self.assertTrue(report["predicted_not_measured"])
        self.assertEqual(report["meta"]["deviation_source"], "single position")

    def test_multi_position_fixes_shared_peak_and_ignores_seat_specific_null(self):
        shared = tunelib.cascade_db(FREQS, [(300.0, 1.5, 5.0)])
        null_1k = tunelib.peaking_db(FREQS, 1000.0, 6.0, -12.0)
        paths = []
        for i, extra in enumerate((null_1k, np.zeros_like(FREQS), np.zeros_like(FREQS))):
            path = self.root / ("pos%d.txt" % i)
            _write_export(path, 78 + i + _target() + shared + extra)
            paths.append(str(path))

        report = self.run_cli("propose", "--positions", *paths, "--target", "default")

        self.assertEqual(report["meta"]["deviation_source"], "mean of 3 positions")
        bands = report["proposal"]["bands"]
        self.assertTrue(any(abs(np.log2(b["f_hz"] / 300.0)) < 0.25 and b["gain_db"] < 0
                            for b in bands))
        for band in bands:
            if band["gain_db"] > 0:
                self.assertGreater(abs(np.log2(band["f_hz"] / 1000.0)), 0.5)
        self.assertEqual(len(report["prediction"]["position_scores_after_db"]), 3)

    def test_boosts_without_phase_are_reported_as_ungated(self):
        spl = 80 + _target() + tunelib.cascade_db(FREQS, [(1200.0, 1.0, -4.0)])
        meas = self.root / "dip.txt"
        _write_export(meas, spl)

        report = self.run_cli("propose", "--measurement", str(meas),
                              "--target", "default")

        if any(b["gain_db"] > 0 for b in report["proposal"]["bands"]):
            self.assertTrue(any("boost gate" in n for n in report["notes"]))

    def test_analyze_uses_position_average_for_deviation(self):
        shared = tunelib.cascade_db(FREQS, [(300.0, 1.5, 5.0)])
        paths = []
        for i in range(3):
            extra = tunelib.peaking_db(FREQS, 1000.0, 6.0, -12.0) if i == 0 else 0.0
            path = self.root / ("p%d.txt" % i)
            _write_export(path, 80 + _target() + shared + extra)
            paths.append(str(path))

        report = self.run_cli("analyze", "--positions", *paths, "--target", "default")

        self.assertEqual(report["meta"]["deviation_source"], "mean of 3 positions")
        near_1k = [r for r in report["deviation_regions"]
                   if r["f_lo"] <= 1000.0 <= r["f_hi"]]
        self.assertTrue(all(abs(r["peak_db"]) < 6.0 for r in near_1k))


if __name__ == "__main__":
    unittest.main()
