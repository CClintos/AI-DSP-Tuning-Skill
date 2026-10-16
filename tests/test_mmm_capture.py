"""Moving-mic (MMM) RTA captures: magnitude only, already spatially averaged,
no noise rejection. The checks here are the ones that matter for that method:
RTA mode, background noise, cancellation without phase, repeatability, and
choosing a setting or an L/R match from magnitude alone."""

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

import afpx  # noqa: E402
import measure  # noqa: E402
import tunelib  # noqa: E402


FREQS = measure.common_grid(20.0, 20000.0, 96)


def _target():
    return measure.load_target(SCRIPTS.parent / "assets" / "default_incar_target.txt", FREQS)


def _rta(path, spl, phase=None):
    rows = ["* RTA 1/48 octave, pink periodic noise"]
    if phase is None:
        rows += ["%.4f %.4f" % (f, s) for f, s in zip(FREQS, spl)]
    else:
        rows += ["%.4f %.4f %.4f" % (f, s, p) for f, s, p in zip(FREQS, spl, phase)]
    Path(path).write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(path)


class Cli(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.rng = np.random.default_rng(21)

    def run_cli(self, *args, ok=True):
        if args[0] == "propose" and "--dsp-rate" not in args:
            args = (*args, "--dsp-rate", "96000")
        run = subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), *args],
                             text=True, capture_output=True, check=False, cwd=self.root)
        if not ok:
            self.assertNotEqual(0, run.returncode, run.stdout)
            return run.stderr
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        return json.loads(run.stdout)

    def car(self, extra=0.0, noise=0.15):
        return 80 + _target() + extra + self.rng.normal(0, noise, len(FREQS))


class RtaModeTests(Cli):
    def test_a_spectrum_mode_capture_is_refused_before_it_tilts_the_tune(self):
        spectrum = self.car() - 3.0 * np.log2(FREQS / 1000.0)
        p = _rta(self.root / "mmm.txt", spectrum)
        err = self.run_cli("propose", "--capture", "mmm", "--measurement", p,
                           "--target", "default", ok=False)
        self.assertIn("Spectrum", err)
        forced = self.run_cli("propose", "--capture", "mmm", "--measurement", p,
                              "--target", "default", "--accept-tilt")
        self.assertIn("Spectrum", forced["meta"]["capture"]["rta_tilt"]["problem"])
        a = self.run_cli("analyze", "--capture", "mmm", "--measurement", p, "--target", "default")
        self.assertTrue(any("Spectrum" in n for n in a["notes"]))

    def test_white_noise_rising_tilt_is_caught_too(self):
        white = self.car() + 3.0 * np.log2(FREQS / 1000.0)
        p = _rta(self.root / "w.txt", white)
        err = self.run_cli("propose", "--capture", "mmm", "--measurement", p,
                           "--target", "default", ok=False)
        self.assertIn("PINK", err)

    def test_a_real_car_tilt_passes_and_a_sweep_is_not_judged(self):
        p = _rta(self.root / "ok.txt", self.car())
        r = self.run_cli("propose", "--capture", "mmm", "--measurement", p, "--target", "default")
        self.assertIsNone(r["meta"]["capture"]["rta_tilt"]["problem"])
        steep = _rta(self.root / "steep.txt", self.car() - 3.0 * np.log2(FREQS / 1000.0))
        s = self.run_cli("propose", "--measurement", steep, "--target", "default")
        self.assertIsNone(s["meta"]["capture"]["rta_tilt"])


class MmmSemanticsTests(Cli):
    def test_one_run_is_a_spatial_average_not_one_mic_spot(self):
        p = _rta(self.root / "run1.txt", self.car(tunelib.peaking_db(FREQS, 400, 2, 4)))
        r = self.run_cli("propose", "--capture", "mmm", "--measurement", p, "--target", "default")
        self.assertEqual(r["meta"]["deviation_source"], "MMM average (one run)")
        self.assertFalse(any("single position" in n for n in r["notes"]))
        self.assertTrue(any("one MMM run" in n for n in r["notes"]))

    def test_two_runs_give_repeatability_for_verification(self):
        runs = [_rta(self.root / ("r%d.txt" % i), self.car(noise=0.3)) for i in range(2)]
        a = self.run_cli("analyze", "--capture", "mmm", "--positions", *runs, "--target", "default")
        cap = a["capture"]
        self.assertEqual(cap["runs"], 2)
        self.assertGreater(cap["verification_noise_db"], 0.05)
        self.assertLess(cap["verification_noise_db"], 0.5)
        self.assertEqual(a["meta"]["deviation_source"], "mean of 2 MMM runs")
        self.assertFalse(any("spatial_consistency" in n for n in a["notes"]))

    def test_a_phase_column_on_an_mmm_capture_is_ignored(self):
        p = _rta(self.root / "ph.txt", self.car(), phase=np.zeros_like(FREQS))
        a = self.run_cli("analyze", "--capture", "mmm", "--measurement", p, "--target", "default")
        self.assertTrue(any("phase column ignored" in n for n in a["notes"]))
        self.assertNotIn("boost_gate", a)


class AmbientTests(Cli):
    def test_bins_buried_in_cabin_noise_are_not_data(self):
        p = _rta(self.root / "m.txt", self.car(tunelib.peaking_db(FREQS, 45, 2, -8)))
        ambient = 40.0 + 45.0 * ((FREQS > 30) & (FREQS < 60))
        amb = _rta(self.root / "amb.txt", ambient)
        a = self.run_cli("analyze", "--capture", "mmm", "--measurement", p, "--target", "default",
                         "--ambient", amb)
        lost = a["capture"]["ambient"]["excluded_hz"]
        self.assertTrue(lost, a["capture"])
        lo, hi = (float(x) for x in lost[0].split(" Hz")[0].split("-"))
        self.assertTrue(28 <= lo <= 35 and 55 <= hi <= 62, lost)
        r = self.run_cli("propose", "--capture", "mmm", "--measurement", p, "--target", "default",
                         "--ambient", amb, "--fit-band", "25", "200")
        for b in r["proposal"]["bands"] + r["proposal"]["rejected"]:
            self.assertFalse(30 < b["f_hz"] < 60, b)


class CancellationWithoutPhaseTests(Cli):
    dip = None

    def pair(self, cancelling):
        dip = tunelib.peaking_db(FREQS, 1000.0, 2.0, -6.0)
        base = 80 + _target()
        half = base - 3.01 + (0.0 if cancelling else dip)
        left = _rta(self.root / "L.txt", half)
        right = _rta(self.root / "R.txt", half)
        both = _rta(self.root / "both.txt", base + dip)
        return left, right, both

    def boosts_near_1k(self, report, key):
        return [b for b in report["proposal"][key] if b["gain_db"] > 0 and 700 < b["f_hz"] < 1400]

    def test_a_dip_the_pair_creates_together_is_not_boosted(self):
        left, right, both = self.pair(cancelling=True)
        ungated = self.run_cli("propose", "--capture", "mmm", "--measurement", both,
                               "--target", "default")
        # With no evidence either way the boost is not an ordinary correction:
        # it is held back as a measured trial.
        self.assertFalse(self.boosts_near_1k(ungated, "bands"), ungated["proposal"])
        self.assertTrue(self.boosts_near_1k(ungated, "needs_trial"), ungated["proposal"])
        self.assertTrue(any("--cancel-check" in n for n in ungated["notes"]))
        gated = self.run_cli("propose", "--capture", "mmm", "--measurement", both,
                             "--target", "default", "--cancel-check", left, right, both)
        self.assertFalse(self.boosts_near_1k(gated, "bands"), gated["proposal"])
        self.assertTrue(self.boosts_near_1k(gated, "rejected"))

    def test_a_dip_both_halves_share_may_still_be_filled(self):
        left, right, both = self.pair(cancelling=False)
        r = self.run_cli("propose", "--capture", "mmm", "--measurement", both,
                         "--target", "default", "--cancel-check", left, right, both)
        kept = self.boosts_near_1k(r, "bands")
        self.assertTrue(kept, r["proposal"])
        self.assertEqual(kept[0]["boost_gate"], "ALLOW")

    def test_analyze_maps_the_cancellation(self):
        left, right, both = self.pair(cancelling=True)
        a = self.run_cli("analyze", "--capture", "mmm", "--measurement", both,
                         "--target", "default", "--cancel-check", left, right, both)
        region = a["cancellation"][0]["cancellation_hz"]
        self.assertTrue(region)
        lo, hi = (float(x) for x in region[0].split(" Hz")[0].split("-"))
        self.assertTrue(lo < 1000 < hi)


class CompareSettingsTests(Cli):
    def test_default_rejects_louder_hump(self):
        caps = [self.capture('now', 0), self.capture('hump', 6)]
        r = self.run_cli('mmm-compare', '--captures', *caps, '--band', '40', '160')
        self.assertEqual(r['objective'], 'balanced')
        self.assertEqual(r['choice'], 'now')

    def test_ambient_export_cannot_supply_unmeasured_reference(self):
        caps = [self.capture('now', -6), self.capture('trial', -2)]
        amb = self.root / 'ambient.txt'
        amb.write_text('\n'.join('%.4f 30' % f for f in FREQS if f < 200), encoding='utf-8')
        r = self.run_cli('mmm-compare', '--captures', *caps, '--band', '40', '160',
                         '--ambient', str(amb))
        self.assertEqual(r['choice'], 'now')
        self.assertIsNone(r['reference_band_hz'])

    def capture(self, name, dip_db, noise=0.05):
        spl = (80 + _target() + tunelib.peaking_db(FREQS, 80.0, 1.5, dip_db)
               + self.rng.normal(0, noise, len(FREQS)))
        return "%s=%s" % (name, _rta(self.root / (name + ".txt"), spl))

    def test_the_setting_that_fills_the_handover_wins(self):
        caps = [self.capture("now", -6.0), self.capture("d0.5ms", -2.0),
                self.capture("invert", -9.0)]
        rep = _rta(self.root / "now2.txt",
                   80 + _target() + tunelib.peaking_db(FREQS, 80.0, 1.5, -6.0)
                   + self.rng.normal(0, 0.05, len(FREQS)))
        r = self.run_cli("mmm-compare", "--captures", *caps, "--repeat", rep, "--band", "40", "160")
        self.assertEqual(r["choice"], "d0.5ms", r)
        self.assertIn("measured", r["resolution_source"])
        lvl = self.run_cli("mmm-compare", "--captures", *caps, "--repeat", rep,
                           "--band", "40", "160", "--objective", "level")
        self.assertEqual(lvl["choice"], "d0.5ms")

    def test_a_difference_inside_the_repeatability_keeps_the_current_setting(self):
        caps = [self.capture("now", -6.0, noise=0.4), self.capture("d0.1ms", -5.8, noise=0.4)]
        rep = _rta(self.root / "now2.txt",
                   80 + _target() + tunelib.peaking_db(FREQS, 80.0, 1.5, -6.0)
                   + self.rng.normal(0, 0.4, len(FREQS)))
        r = self.run_cli("mmm-compare", "--captures", *caps, "--repeat", rep, "--band", "40", "160")
        self.assertEqual(r["choice"], "now", r)
        self.assertIn("no setting is distinguishably better", r["verdict"])


class LrMatchTests(Cli):
    def test_custom_target_protects_correct_side(self):
        target = _target()+tunelib.peaking_db(FREQS, 1500, 2, 4)
        target_file = _rta(self.root / 'target.txt', target)
        left = _rta(self.root / 'L.txt', 80+target)
        right = _rta(self.root / 'R.txt', 80+target+tunelib.peaking_db(FREQS,1500,2,-6))
        r = self.run_cli('lr-match', '--left', left, '--right', right, '--target', target_file)
        self.assertEqual(r['cuts'], [])
        self.assertTrue(r['unresolved_regions'])

    def test_trim_the_louder_side_then_cut_each_side_only_where_it_is_louder(self):
        left = _rta(self.root / "L.txt", 80 + _target() + tunelib.peaking_db(FREQS, 1500, 2, 3) + 1.0)
        right = _rta(self.root / "R.txt", 80 + _target() + tunelib.peaking_db(FREQS, 4000, 3, 2.5))
        r = self.run_cli("lr-match", "--left", left, "--right", right)
        self.assertEqual(r["trim"]["side"], "left")
        self.assertAlmostEqual(r["trim"]["trim_db"], -1.0, delta=0.3)
        sides = {(c["side"], round(c["f_hz"], -2)) for c in r["cuts"]}
        self.assertIn("left", {s for s, _f in sides})
        self.assertIn("right", {s for s, _f in sides})
        self.assertTrue(all(c["gain_db"] < 0 for c in r["cuts"]))
        self.assertLess(r["wrms_after_db"], r["wrms_before_db"] / 3)


class RefineWithMmmTests(Cli):
    def test_refine_reads_one_mmm_run_as_an_average(self):
        bank = [(500.0, 2.0, -5.0)]
        xml = ('<ATF><OC ON="1" CINV="0">'
               '<Fil T="16" F="80.00" Q="0.7" G="-24" dF="80" FN="1" I="0" FilBy="0"/>'
               '<Fil T="15" F="3000.00" Q="0.7" G="-24" dF="3000" FN="2" I="0" FilBy="0"/>'
               '<Fil T="17" F="500.00" Q="2" G="-5" dF="500" FN="3" I="0" FilBy="0"/>'
               '<Fil T="1" F="200.00" Q="1" G="0" dF="200" FN="4" I="0" FilBy="0"/>'
               '<Vol T="15" L="1.0" i="0"/><T PM="1" P="0" T="0"/></OC></ATF>')
        tune = self.root / "t.afpx"
        afpx._encode_unchecked(xml, str(tune))
        spl = self.car(tunelib.peaking_db(FREQS, 500, 2, 5) + tunelib.cascade_db(FREQS, bank))
        p = _rta(self.root / "m.txt", spl)
        r = self.run_cli("refine", "--afpx", str(tune), "--channels", "0", "--dsp-rate", "96000",
                         "--capture", "mmm", "--measurement", p, "--target", "default")
        self.assertTrue(any("one MMM run" in n for n in r["notes"]))
        self.assertEqual(r["capture"]["method"], "mmm")


if __name__ == "__main__":
    unittest.main()
