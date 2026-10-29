"""finish: what still decides the sound once the system sum is on the target.
Each section is checked against a synthetic case with a known answer, and the
whole report against the real 14 July captures."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "helix-rew-tuner" / "scripts"
JULY14 = ROOT / "tests" / "fixtures" / "real" / "2026-07-14"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

import afpx  # noqa: E402
import finish  # noqa: E402
import frames  # noqa: E402
import measure  # noqa: E402
import tunelib  # noqa: E402
from test_capture_intelligence import _lr4_db, rew_text  # noqa: E402

F = measure.common_grid(15.0, 22000.0, 96)


def _target():
    return measure.load_target(SCRIPTS.parent / "assets" / "default_incar_target.txt", F)


def _with_phase(path, freqs, spl, phase_deg, name):
    lines = ["* Measurement: %s" % name, "* timing reference: Acoustic",
             "* Freq(Hz) SPL(dB) Phase(degrees)"]
    lines += ["%.6f %.4f %.4f" % (f, s, p) for f, s, p in zip(freqs, spl, phase_deg)]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


class _Tmp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.rng = np.random.default_rng(9)

    def cli(self, *args, cwd=None):
        run = subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), *args],
                             text=True, capture_output=True, check=False, cwd=cwd or self.root)
        self.assertEqual(0, run.returncode, run.stderr)
        return json.loads(run.stdout)


class Tone(_Tmp):
    def test_a_broad_peak_is_a_cut_and_a_narrow_dip_is_left_alone(self):
        sys_db = 80 + _target() + tunelib.peaking_db(F, 1000.0, 2.0, 3.0) \
            + tunelib.peaking_db(F, 437.0, 8.0, -8.0) + self.rng.normal(0, 0.05, len(F))
        path = rew_text(self.root / "System Sum.txt", F, sys_db, "System Sum")
        r = self.cli("finish", "--system", path)
        peak = r["tone"]["residual_peaks"][0]
        self.assertLess(abs(np.log2(peak["hz"] / 1000.0)), 1 / 12)
        self.assertTrue(1.0 <= peak["q"] <= 3.5, peak)
        self.assertTrue(-3.0 <= peak["suggested_cut"]["gain_db"] < 0)
        self.assertTrue(peak["fit_band_hz"][0] < 1000 < peak["fit_band_hz"][1])
        self.assertFalse(any(abs(np.log2(p["hz"] / 437.0)) < 0.1 for p in r["tone"]["residual_peaks"]))
        self.assertTrue(any(abs(np.log2(d["hz"] / 437.0)) < 0.1 for d in r["tone"]["leave_alone_dips"]))

    def test_nearby_peaks_are_one_feature(self):
        rows = [{"hz": 1346, "height_db": 2.4}, {"hz": 1289, "height_db": 2.0}, {"hz": 622, "height_db": 4.1}]
        merged = finish._merge(sorted(rows, key=lambda r: -r["height_db"]), "height_db")
        self.assertEqual([r["hz"] for r in merged], [622, 1346])


class Imaging(_Tmp):
    def side(self, extra=None):
        mid = 80 + _lr4_db(F, 80, "hp") + _lr4_db(F, 2600, "lp")
        tw = 80 + _lr4_db(F, 2600, "hp")
        if extra is not None:
            mid = mid + extra
        return mid, tw

    def write(self, side, name):
        mid, tw = side
        return [rew_text(self.root / ("%s Mid.txt" % name), F, mid, "%s Mid" % name),
                rew_text(self.root / ("%s Tweeter.txt" % name), F, tw, "%s Tweeter" % name)]

    def test_a_band_lit_on_one_side_is_smeared_and_the_rest_stays_focused(self):
        bump = np.where((F > 135) & (F < 175), 14.0, 0.0)
        left = self.write(self.side(), "Left")
        right = self.write(self.side(bump), "Right")
        r = self.cli("finish", "--left", *left, "--right", *right)
        by = {b["instrument"]: b for b in r["imaging"]["bands"]}
        self.assertEqual(by["electric guitar"]["focus"], "smeared")
        self.assertEqual(by["celesta"]["focus"], "focused")
        self.assertEqual(by["celesta"]["centre"], "centred")
        self.assertEqual(by["electronic bass"]["verdict"], "not_covered")   # solos play from 80 Hz
        self.assertFalse(r["imaging"]["time_cue"])

    def test_timed_captures_add_the_time_cue(self):
        level = 80 + _lr4_db(F, 300, "hp")
        left = _with_phase(self.root / "L.txt", F, level, np.zeros_like(F), "Left")
        late = -360.0 * F * 0.0005                        # right arrives 0.5 ms later
        right = _with_phase(self.root / "R.txt", F, level, (late + 180) % 360 - 180, "Right")
        r = self.cli("finish", "--left", left, "--right", right)
        self.assertTrue(r["imaging"]["time_cue"])
        tri = next(b for b in r["imaging"]["bands"] if b["instrument"] == "triangle")
        self.assertTrue(tri["time_cue_used"])
        self.assertEqual(tri["centre"], "pulled left")
        self.assertAlmostEqual(tri["mean_pull"], 0.5, delta=0.1)


class Height(_Tmp):
    def tune(self):
        def oc(hp, lp):
            fils = ['<Fil T="16" F="%.2f" Q="0.7" G="-24" dF="%d" FN="1" I="0" FilBy="0"/>' % (hp, hp)]
            if lp:
                fils.append('<Fil T="15" F="%.2f" Q="0.7" G="-24" dF="%d" FN="2" I="0" FilBy="0"/>' % (lp, lp))
            return ('<OC ON="1" CINV="0">' + "".join(fils) + '<Vol T="15" L="1.0" i="0"/>'
                    '<T PM="1" P="0" T="0"/></OC>')
        path = self.root / "t.afpx"
        blocks = [oc(2600, None), oc(2600, None), oc(80, 2600), oc(80, 2600), oc(300, 2600), oc(300, 2600)]
        afpx._encode_unchecked("<ATF>" + "".join(blocks) + "</ATF>", str(path))
        return str(path)

    def test_an_overlap_is_a_question_until_heights_are_given(self):
        tune = self.tune()
        r = self.cli("finish", "--afpx", tune)
        over = [o for o in r["height"]["overlaps"] if o["overlap_hz"] == [300, 2600]]
        self.assertEqual(over[0]["verdict"], "question")
        r = self.cli("finish", "--afpx", tune, "--low", "2", "3", "--high", "4", "5")
        over = [o for o in r["height"]["overlaps"] if o["overlap_hz"] == [300, 2600]]
        self.assertEqual(over[0]["verdict"], "height_risk")
        self.assertIn("probe", over[0]["advice"])
        self.assertIn("8000", r["height"]["voicing_option"])


class Sub(_Tmp):
    def test_output_above_120_hz_is_leakage(self):
        clean = 95 + _lr4_db(F, 60, "lp")
        leaky = 10 * np.log10(10 ** (clean / 10) + 10 ** ((85 - 0.0 * F) / 10)
                              * np.exp(-((np.log2(F / 200.0)) / 0.3) ** 2))
        c = self.cli("finish", "--sub", rew_text(self.root / "Sub.txt", F, np.maximum(clean, 20), "Sub"))
        self.assertEqual(c["sub"]["stopband"]["verdict"], "clean")
        l = self.cli("finish", "--sub", rew_text(self.root / "Sub2.txt", F, np.maximum(leaky, 20), "Sub"))
        self.assertEqual(l["sub"]["stopband"]["verdict"], "leaking")

    def test_harmonics_against_fielder_and_benjamin(self):
        df = measure.common_grid(15.0, 400.0, 24)
        fund = np.full_like(df, 100.0)
        h2 = fund + 20 * np.log10(0.02)                # 2%: under the ~3% limit
        h3 = fund + 20 * np.log10(np.where((df > 40) & (df < 70), 0.015, 0.005))   # 1.5% at 50 Hz
        r = finish.sub_harmonics(df, {"fundamental": fund, 2: h2, 3: h3})
        self.assertEqual(r["verdict"], "over_limit")
        self.assertIn("H3", r["worst"])
        self.assertIn("located", r["worst"])
        row = next(b for b in r["bands"] if abs(b["hz"] - 50) < 3)
        self.assertEqual(row["over_limit"][0]["order"], 3)
        self.assertTrue(all(o["order"] != 2 for b in r["bands"] for o in b["over_limit"]))


class Decay(_Tmp):
    def ir(self, name, t60, f0=100.0):
        fs = 48000
        t = np.arange(int(1.5 * fs)) / fs
        x = np.zeros_like(t)
        start = int(0.05 * fs)
        tail = np.exp(-6.91 * t[: len(t) - start] / t60) * np.sin(2 * np.pi * f0 * t[: len(t) - start])
        x[start:] = 0.5 * tail
        x[start] += 0.4
        x += np.random.default_rng(1).normal(0, 1e-6, len(x))
        path = self.root / name
        frames.write_wav(str(path), x, fs, 24)
        return str(path)

    def test_a_long_mode_is_audible_and_a_short_one_is_not(self):
        r = self.cli("finish", "--ir", self.ir("ring.wav", 0.8), self.ir("tight.wav", 0.08))
        ring = {b["hz"]: b for b in r["bass_decay"][str(self.root / "ring.wav")]["bands"]}
        tight = {b["hz"]: b for b in r["bass_decay"][str(self.root / "tight.wav")]["bands"]}
        self.assertEqual(ring[100]["verdict"], "audible")
        self.assertIn(tight[100]["verdict"], ("inaudible", "not_resolvable"))
        self.assertAlmostEqual(finish.fazenda_threshold(63), 0.51, places=2)
        self.assertAlmostEqual(finish.fazenda_threshold(250), 0.12, places=2)


class RealSet(_Tmp):
    def test_the_july_set(self):
        names = lambda *n: [str(JULY14 / ("%s.txt" % x)) for x in n]
        r = self.cli("finish", "--system", *names("System Sum"),
                     "--left", *names("Front Left Mid", "Front Left Tweeter"),
                     "--right", *names("Front Right Mid", "Front Right Tweeter"),
                     "--sub", *names("Subwoofer"),
                     "--floor", *names("Front Left Tweeter", "Front Right Tweeter"), cwd=JULY14)
        self.assertTrue(any(abs(np.log2(p["hz"] / 622.0)) < 0.1 for p in r["tone"]["residual_peaks"]))
        by = {b["instrument"]: b for b in r["imaging"]["bands"]}
        self.assertEqual(by["celesta"]["focus"], "focused")
        self.assertIn(by["flute"]["focus"], ("loose", "smeared"))
        self.assertEqual(by["electronic bass"]["verdict"], "not_covered")

    def test_next_suggests_finish(self):
        r = self.cli("next", "--captures", ".", cwd=JULY14)
        cmd = next(row["command"] for row in r["run"] if row["command"].startswith("pipeline.py finish"))
        self.assertIn("--system", cmd)
        self.assertIn("--left", cmd)
        self.assertIn("--sub", cmd)


if __name__ == "__main__":
    unittest.main()
