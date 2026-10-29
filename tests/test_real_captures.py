"""Regression tests on real REW files from one car (tests/fixtures/real).

Synthetic fixtures encode what we believe REW writes. These do not: they are
REW's own output. 1.20.0 passed 423 synthetic tests while reading every one of
these RTA exports as smoothed ("...no smoothing and 31 averages" read as the
smoothing) and picking the mic calibration curve out of the .mdat. Each test
below pins a fact that was checked by hand against the files."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "helix-rew-tuner" / "scripts"
REAL = ROOT / "tests" / "fixtures" / "real"
JULY14 = REAL / "2026-07-14"
MDAT = REAL / "2026-07-04 front left tweeter.mdat"
sys.path.insert(0, str(SCRIPTS))

import capture_audit  # noqa: E402
import mdat  # noqa: E402
import measure  # noqa: E402
import mmm  # noqa: E402


def _f(name):
    return str(JULY14 / ("%s.txt" % name))


def _cli(*args):
    run = subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), *args],
                         text=True, capture_output=True, check=False, cwd=JULY14)
    if run.returncode:
        raise AssertionError(run.stderr)
    return json.loads(run.stdout)


class RealHeaders(unittest.TestCase):
    def test_export_smoothing_is_read_from_the_smoothing_line(self):
        tweeter = measure.read_export_header(_f("Front Left Tweeter"))
        self.assertEqual(tweeter["smoothing"], "1/48 octave")
        self.assertFalse(tweeter["unsmoothed"])
        for name in ("Front Right Tweeter", "Subwoofer", "System Sum"):
            with self.subTest(name=name):
                self.assertTrue(measure.read_export_header(_f(name))["unsmoothed"])

    def test_rew_header_fields(self):
        rew = measure.read_export_header(_f("Front Left Tweeter"))["rew"]
        self.assertEqual(rew["version"], "5.40 beta 127")
        self.assertEqual((rew["format"]["fft_length"], rew["format"]["rta_fraction"],
                          rew["format"]["averages"], rew["format"]["window"]),
                         (65536, 24, 31, "Hann"))
        self.assertEqual((rew["source"]["mic_model"], rew["source"]["gain_db"],
                          rew["source"]["input_volume"]), ("UMIK-1", 18.0, 0.95))
        self.assertEqual(rew["date"], "2026-07-14T20:34:16")
        self.assertAlmostEqual(rew["levels"]["below_22_db"], 67.3, places=1)
        self.assertEqual(rew["levels"]["unw_22_22k_db"], 58.6)


class RealMdat(unittest.TestCase):
    def test_reader_takes_rews_own_axis_and_unsmoothed_values(self):
        meas = mdat.load(str(MDAT))
        self.assertEqual(len(meas), 1)
        m = meas[0]
        self.assertEqual((m["name"], m["kind"], len(m["freqs"])), ("Front L Tweeter", "rta", 1229))
        self.assertAlmostEqual(m["freqs"][0], 3.2958984375, places=6)
        self.assertAlmostEqual(m["freqs"][-1] / 23374.912, 1.0, delta=0.005)
        self.assertEqual(m["mic"]["serial"], "7065357")
        self.assertEqual(m["rew_version"], "5.40 beta 127")
        f, s, _p, _c = measure.load_text_export(str(MDAT))
        at = lambda hz: s[np.argmin(np.abs(f - hz))]
        self.assertGreater(at(4000) - at(500), 15.0)        # a tweeter, not a cal curve
        self.assertLess(np.ptp(s[(f > 1000) & (f < 20000)]), 60.0)

    def test_the_header_matches_the_capture(self):
        rew = measure.read_export_header(str(MDAT))["rew"]
        self.assertEqual(rew["levels"]["dba"], 66.9)
        self.assertEqual(rew["source"]["input_volume"], 0.9)
        self.assertEqual(rew["mic_cal_file"], "7065357_90deg.txt")


class RealAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = capture_audit.audit(sorted(str(p) for p in JULY14.glob("*.txt")))
        cls.by = {c["name"]: c for c in cls.report["captures"]}

    def codes(self, name):
        return {f["code"] for f in self.by[name]["flags"]}

    def test_the_problems_found_by_hand_are_found(self):
        set_codes = {f["code"] for f in self.report["set"]["flags"]}
        self.assertIn("mixed_export_smoothing", set_codes)
        self.assertIn("twin_floor_mismatch", set_codes)
        self.assertIn("infrasound", self.codes("Subwoofer"))
        for name in self.by:
            with self.subTest(name=name):
                self.assertIn("short_capture", self.codes(name))        # 25-32 averages: ~5-7 s
        self.assertIn("handling_noise", self.codes("Front Left Tweeter"))
        self.assertIn("below_hearing_threshold", self.codes("System Sum"))

    def test_no_false_alarms_on_normal_floors(self):
        for name in ("Front Left Mid", "Front Right Mid", "Both Mids", "Subwoofer"):
            with self.subTest(name=name):
                self.assertNotIn("hf_artefact", self.codes(name))
        for name in ("Front Left Tweeter", "Front Right Tweeter", "Both Tweeters"):
            with self.subTest(name=name):
                self.assertNotIn("stopband_excess", self.codes(name))

    def test_triples_and_their_playback_level(self):
        tri = {tuple(t["files"]): t for t in self.report["set"]["triples"]}
        mids = tri[("Front Left Mid", "Front Right Mid", "Both Mids")]
        self.assertTrue(mids["consistent"])
        dba = next(c for c in mids["checks"] if c["weighting"] == "dba")
        self.assertEqual((dba["power_sum_db"], dba["both_db"]), (61.7, 62.0))
        tweeters = tri[("Front Left Tweeter", "Front Right Tweeter", "Both Tweeters")]
        self.assertFalse(tweeters["consistent"])
        self.assertEqual(tweeters["smoothing_mismatch"], ["1/48 octave", "none"])

    def test_twin_tweeter_floors_differ_by_more_than_ten_db(self):
        tw = next(t for t in self.report["set"]["twin_floors"] if "Tweeter" in t["a"])
        self.assertGreater(tw["max_difference_db"], 10.0)


class RealCoherence(unittest.TestCase):
    def test_mids_add_coherently_low_and_as_power_sum_in_the_midrange(self):
        rows, _floor, band = mmm.triple_rows(
            [_f("Front Left Mid"), _f("Front Right Mid"), _f("Both Mids")],
            [_f("Front Left Tweeter"), _f("Front Right Tweeter")])
        read = {r["hz"]: r for r in rows if r["rho"] is not None}
        self.assertGreater(read[125.0]["rho"], 0.9)
        for hz in (630.0, 793.7, 1000.0):
            self.assertEqual(read[hz]["verdict"], "power_sum", read[hz])
        self.assertTrue(all(hz < 5000 for hz in read))            # noise-only bands not read
        self.assertGreater(band[1], 2000)


class RealNext(unittest.TestCase):
    def test_next_routes_the_set(self):
        r = _cli("next", "--captures", ".")
        cmds = [row["command"] for row in r["run"]]
        self.assertTrue(cmds[0].startswith("pipeline.py analyze --measurement"))
        self.assertIn("System Sum", cmds[0])
        self.assertTrue(any(c.startswith("pipeline.py coherence") and "Both Mids" in c for c in cmds))
        blocked = " ".join(b["what"] for b in r["blocked"])
        self.assertIn("Both Tweeters", blocked)


if __name__ == "__main__":
    unittest.main()
