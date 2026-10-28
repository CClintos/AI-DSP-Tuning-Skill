"""Fixes found re-running the skill on a real car: bass trials judged against
their own unchanged model, single-driver MMM captures not refused by the
full-system tilt guard, vehicle guards on every refine move, and a
headroom-only quality check."""

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
import judging  # noqa: E402
import measure  # noqa: E402
import pipeline  # noqa: E402
import tunelib  # noqa: E402


F = measure.common_grid(20.0, 20000.0, 96)
FS = 96000.0


def _lr4_db(kind, fc):
    x = (F / fc) ** 2 if kind == "hp" else (fc / F) ** 2
    return 2 * 20 * np.log10(x / np.sqrt(1 + x ** 2))


def _channel(bank, hp=None, lp=None):
    fils = []
    if hp:
        fils.append('<Fil T="16" F="%.2f" Q="0.7" G="-24" dF="%d" FN="1" I="0" FilBy="0"/>' % (hp, int(hp)))
    if lp:
        fils.append('<Fil T="15" F="%.2f" Q="0.7" G="-24" dF="%d" FN="2" I="0" FilBy="0"/>' % (lp, int(lp)))
    for k, (Fc, Q, G) in enumerate(bank):
        fils.append('<Fil T="17" F="%.2f" Q="%g" G="%g" dF="%d" FN="%d" I="0" FilBy="0"/>'
                    % (Fc, Q, G, int(Fc), 3 + k))
    fils += ['<Fil T="1" F="200.00" Q="1" G="0" dF="200" FN="10" I="0" FilBy="0"/>',
             '<Fil T="1" F="800.00" Q="1" G="0" dF="800" FN="11" I="0" FilBy="0"/>',
             '<Fil T="1" F="25.00" Q="1" G="0" dF="25" FN="12" I="0" FilBy="0"/>',
             '<Fil T="1" F="20000.00" Q="1" G="0" dF="20000" FN="13" I="0" FilBy="0"/>']
    return ('<OC ON="1" CINV="0">' + "".join(fils) + '<Vol T="15" L="1.0" i="0"/>'
            + '<T PM="1" P="0" T="0"/></OC>')


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def trace(self, name, db, phase=None, timed=True):
        head = "* timing reference: Acoustic\n" if timed else "* no timing metadata\n"
        rows = ["%g %g" % (x, y) + ("" if phase is None else " %g" % z)
                for x, y, z in zip(F, db, np.zeros(len(F)) if phase is None else phase)]
        p = self.root / name
        p.write_text(head + "\n".join(rows), encoding="utf-8")
        return str(p)

    def cli(self, *args, ok=True):
        run = subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), *args],
                             text=True, capture_output=True, cwd=self.root)
        if ok:
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            return json.loads(run.stdout) if run.stdout.strip().startswith("{") else run
        return run

    def tune(self, xml):
        path = self.root / "tune.afpx"
        afpx._encode_unchecked("<ATF>" + xml + "</ATF>", str(path))
        return str(path)


class BassTrialBaselineTests(Case):
    def test_zero_change_is_judged_against_the_model_not_the_capture(self):
        # The together capture sits 0.6 dB above the solo model (a legal model
        # error): the unchanged trial must still score 0 and pass every guard.
        low = tunelib.crossover_H(F, "lp", "LR", 24, 100)
        high = tunelib.crossover_H(F, "hp", "LR", 24, 100)
        sub = low * np.exp(-2j * np.pi * F * 0.001)
        paths = [self.trace("sub.txt", 80 + 20 * np.log10(abs(sub)), np.angle(sub, deg=True)),
                 self.trace("front.txt", 80 + 20 * np.log10(abs(high)), np.angle(high, deg=True)),
                 self.trace("sum.txt", 80.6 + 20 * np.log10(abs(sub + high)))]
        target = self.trace("target.txt", 20 * np.log10(abs(low + high)))
        r = self.cli("bass-trials", "--sub", paths[0], "--front", paths[1], "--together", paths[2],
                     "--target", target, "--delays-ms", "-1", "0", "1", "--gains-db", "0")
        zero = [t for t in r["trials"] if t["delay_change_ms"] == 0 and not t["invert_sub"]][0]
        self.assertEqual(zero["improvement_db"], 0.0)
        self.assertEqual(zero["rejection_reasons"], [])
        self.assertEqual(r["candidate"]["delay_change_ms"], -1)
        self.assertIn("measured_baseline_score_db", r)


class SoloTiltTests(Case):
    def test_refine_on_a_midbass_solo_is_not_refused_for_its_tilt(self):
        bank = [(500.0, 2.0, -3.0)]
        tune = self.tune(_channel(bank, hp=80.0, lp=2600.0))
        target = measure.load_target(SCRIPTS.parent / "assets" / "default_incar_target.txt", F)
        solo = (75 + target + _lr4_db("hp", 80.0) + _lr4_db("lp", 2600.0)
                + tunelib.peaking_db(F, 500.0, 2.0, 3.0) + tunelib.cascade_db(F, bank, fs=FS))
        self.assertIsNotNone(tunelib.rta_tilt_check(tunelib.measure_tilt(F, solo)["tilt_db_per_oct"]))
        r = self.cli("refine", "--afpx", tune, "--channels", "0", "--dsp-rate", "96000",
                     "--measurement", self.trace("mid.txt", solo, timed=False),
                     "--target", "default", "--capture", "mmm")
        self.assertTrue(any("single-driver capture" in n for n in r["notes"]))

    def test_a_full_range_channel_still_gets_the_tilt_refusal(self):
        bank = [(500.0, 2.0, -3.0)]
        tune = self.tune(_channel(bank))
        spectrum_mode = 75 - 3.0 * np.log2(F / 1000.0)          # pink noise in Spectrum mode
        run = self.cli("refine", "--afpx", tune, "--channels", "0", "--dsp-rate", "96000",
                       "--measurement", self.trace("sum.txt", spectrum_mode, timed=False),
                       "--target", "default", "--capture", "mmm", ok=False)
        self.assertNotEqual(0, run.returncode)
        self.assertIn("tilt", run.stderr)


class MoveGuardTests(Case):
    GUARDS = {"max_boost_q": 3.0, "no_boost": [
        {"lo_hz": 380, "hi_hz": 540, "channels": None, "reason": "seated null"}]}

    def test_relaxing_moving_or_removing_a_cut_into_a_zone_is_refused(self):
        check = pipeline.guard_move_check(self.GUARDS)
        self.assertIn("seated null", check((450.0, 2.0, -4.0), (450.0, 2.0, -2.0)))
        self.assertIn("seated null", check((450.0, 2.0, -4.0), None))
        self.assertIn("seated null", check((450.0, 2.0, -4.0), (700.0, 2.0, -4.0)))
        self.assertIsNone(check((450.0, 2.0, -4.0), (450.0, 2.0, -6.0)))     # deeper is fine
        self.assertIsNone(check((2000.0, 2.0, -4.0), None))                   # far from the zone

    def test_narrowing_a_boost_past_the_q_cap_is_refused(self):
        check = pipeline.guard_move_check(self.GUARDS)
        self.assertIn("max_boost_q", check((8000.0, 1.95, 3.0), (7659.0, 3.34, 3.0)))
        self.assertIsNone(check((8000.0, 1.95, 3.0), (8000.0, 1.95, 2.0)))

    def test_refine_will_not_lift_a_guarded_zone_by_relaxing_a_cut(self):
        bank = [(450.0, 2.0, -4.0)]                    # a cut the room no longer needs
        tune = self.tune(_channel(bank, hp=80.0, lp=3000.0))
        target = measure.load_target(SCRIPTS.parent / "assets" / "default_incar_target.txt", F)
        rng = np.random.default_rng(3)
        paths = [self.trace("p%d.txt" % i, 80 + target + _lr4_db("hp", 80.0) + _lr4_db("lp", 3000.0)
                            + tunelib.cascade_db(F, bank, fs=FS) + rng.normal(0, 0.3, len(F)), timed=False)
                 for i in range(3)]
        args = ("refine", "--afpx", tune, "--channels", "0", "--dsp-rate", "96000",
                "--positions", *paths, "--target", "default")
        free = self.cli(*args)
        self.assertTrue([e for e in free["edits"] if e["old"] == [450.0, 2.0, -4.0]], free["edits"])
        pipeline.session_save(tune, {"guards": self.GUARDS})
        r = self.cli(*args)
        self.assertFalse([e for e in r["edits"] if e["old"] == [450.0, 2.0, -4.0]], r["edits"])
        self.assertTrue(any("vehicle guard blocked a candidate" in n for n in r["notes"]))


class HeadroomOnlyTests(Case):
    def test_quality_check_accepts_a_headroom_only_manifest(self):
        transfer = self.trace("transfer.txt", F * 0 - 6.0, timed=False)
        spec = self.root / "q.json"
        spec.write_text(json.dumps({"version": 1, "headroom": {"transfer": "transfer.txt",
                                                               "input_peak_dbfs": 0}}), encoding="utf-8")
        r = self.cli("quality-check", "--spec", str(spec))
        self.assertEqual(r["evidence"]["headroom"]["spectral_margin_db"], 6.0)
        self.assertEqual(r["overall"], "incomplete")


if __name__ == "__main__":
    unittest.main()
