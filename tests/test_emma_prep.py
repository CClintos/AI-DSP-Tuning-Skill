"""EMMA preparation: the judges' four tonal bands, the 6 dB-louder spectral
balance pass, system noise, and imaging in the technical tracks' bands."""

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
    return measure.load_target(SCRIPTS.parent / "assets" / "default_incar_target.txt", FREQS)


def _rta(path, spl):
    rows = ["* RTA 1/48 octave"] + ["%.4f %.4f" % (f, s) for f, s in zip(FREQS, spl)]
    Path(path).write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(path)


class Cli(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.rng = np.random.default_rng(13)

    def run_cli(self, *args):
        run = subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), *args],
                             text=True, capture_output=True, check=False, cwd=self.root)
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        return json.loads(run.stdout)

    def car(self, extra=0.0):
        return 80 + _target() + extra + self.rng.normal(0, 0.1, len(FREQS))


class EmmaBandTests(Cli):
    def test_analyze_reports_the_four_judged_bands(self):
        p = _rta(self.root / "m.txt", self.car(tunelib.low_shelf_db(FREQS, 60.0, 0.7, 4.0)))
        a = self.run_cli("analyze", "--capture", "mmm", "--measurement", p, "--target", "default")
        bands = {b["band"]: b for b in a["emma_bands"]["bands"]}
        self.assertEqual(set(bands), {"sub_bass", "mid_bass", "midrange", "high"})
        self.assertGreater(bands["sub_bass"]["median_db"], 2.5)
        self.assertLess(abs(bands["midrange"]["median_db"]), 0.5)
        self.assertTrue(a["emma_bands"]["verdict"].startswith("uneven"))

    def test_a_balanced_car_is_balanced(self):
        p = _rta(self.root / "ok.txt", self.car())
        a = self.run_cli("analyze", "--capture", "mmm", "--measurement", p, "--target", "default")
        self.assertEqual(a["emma_bands"]["verdict"], "balanced")


class HigherVolumeTests(Cli):
    def test_sub_compression_at_six_db_louder_is_named(self):
        normal = self.car()
        loud = normal + 6.0 - 2.5 * (FREQS < 60)
        r = self.run_cli("emma-volume", "--normal", _rta(self.root / "n.txt", normal),
                         "--loud", _rta(self.root / "l.txt", loud))
        self.assertEqual(r["verdict"], "changes_balance")
        states = {b["band"]: b["state"] for b in r["bands"]}
        self.assertEqual(states["sub_bass"], "compressing")
        self.assertEqual(states["midrange"], "tracks")
        self.assertTrue(any("compressing" in n for n in r["notes"]))

    def test_a_system_that_cannot_play_six_db_louder_is_flagged(self):
        normal = self.car()
        r = self.run_cli("emma-volume", "--normal", _rta(self.root / "n.txt", normal),
                         "--loud", _rta(self.root / "l.txt", normal + 4.0))
        self.assertEqual(r["verdict"], "cannot_reach_step")
        self.assertTrue(any("12 points" in n for n in r["notes"]))

    def test_loudness_processing_shows_as_a_band_rising_faster(self):
        normal = self.car()
        loud = normal + 6.0 + 2.0 * (FREQS < 60)
        r = tunelib.emma_volume_check(FREQS, normal, loud)
        self.assertEqual({b["band"]: b["state"] for b in r["bands"]}["sub_bass"], "rising_faster")

    def test_a_clean_system_holds(self):
        normal = self.car()
        r = tunelib.emma_volume_check(FREQS, normal, normal + 6.0)
        self.assertEqual(r["verdict"], "holds")


class NoiseTests(Cli):
    def test_hiss_above_the_cabin_is_audible_and_hum_free_bands_are_quiet(self):
        off = 30.0 + 0 * FREQS
        on = off + 5.0 * ((FREQS > 3000) & (FREQS < 9000))
        r = self.run_cli("noise-check", "--off", _rta(self.root / "off.txt", off),
                         "--on", _rta(self.root / "on.txt", on))
        states = {b["band"]: b["state"] for b in r["bands"]}
        self.assertEqual(states["hiss"], "audible")
        self.assertEqual(states["hum"], "quiet")
        self.assertEqual(r["verdict"], "audible")

    def test_a_quiet_system_is_quiet(self):
        off = 30.0 + 0 * FREQS
        r = tunelib.system_noise_check(FREQS, off, off + 0.3)
        self.assertEqual(r["verdict"], "quiet")


class EmmaImagingTests(Cli):
    def test_imaging_in_the_technical_track_bands(self):
        left = _rta(self.root / "L.txt", self.car())
        right = _rta(self.root / "R.txt", self.car(3.0 * ((FREQS > 1000) & (FREQS < 2000))))
        r = self.run_cli("imaging", "--solo-l", left, "--solo-r", right, "--bands", "emma")
        names = [b["instrument"] for b in r["bands"]]
        self.assertEqual(names, list(tunelib.EMMA_IMAGING_INSTRUMENTS))
        celesta = [b for b in r["bands"] if b["instrument"] == "celesta"][0]
        others = [b for b in r["bands"] if b["instrument"] != "celesta"]
        self.assertEqual(celesta["side"], "right")
        self.assertTrue(all(abs(b["pull"]) < 0.1 for b in others), others)


if __name__ == "__main__":
    unittest.main()
