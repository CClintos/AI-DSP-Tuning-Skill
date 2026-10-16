"""Lessons from tuning one real car, made into rules the pipeline enforces:
band-limited solos anchored inside their own passband, held-out validation
by sitting, and per-vehicle guards recorded once in the session sidecar."""

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
import pipeline  # noqa: E402
import tunelib  # noqa: E402


FREQS = measure.common_grid(20.0, 20000.0, 96)
FS = 96000.0
GUARDS = {"max_boost_q": 3.0, "no_boost": [
    {"lo_hz": 380, "hi_hz": 540, "channels": [0], "reason": "seated-listener null"}]}


def _target():
    return measure.load_target(SCRIPTS.parent / "assets" / "default_incar_target.txt", FREQS)


def _lr4_db(kind, fc):
    """Linkwitz-Riley 24 dB/oct magnitude: a squared 2nd-order Butterworth."""
    x = (FREQS / fc) ** 2 if kind == "hp" else (fc / FREQS) ** 2
    return 2 * 20 * np.log10(x / np.sqrt(1 + x ** 2))


def _channel(bank, hp=None, lp=None):
    fils = []
    if hp:
        fils.append('<Fil T="16" F="%.2f" Q="0.7" G="-24" dF="%d" FN="1" I="0" FilBy="0"/>'
                    % (hp, int(hp)))
    if lp:
        fils.append('<Fil T="15" F="%.2f" Q="0.7" G="-24" dF="%d" FN="2" I="0" FilBy="0"/>'
                    % (lp, int(lp)))
    for k, (F, Q, G) in enumerate(bank):
        fils.append('<Fil T="17" F="%.2f" Q="%g" G="%g" dF="%d" FN="%d" I="0" FilBy="0"/>'
                    % (F, Q, G, int(F), 3 + k))
    fils += ['<Fil T="1" F="200.00" Q="1" G="0" dF="200" FN="10" I="0" FilBy="0"/>',
             '<Fil T="1" F="800.00" Q="1" G="0" dF="800" FN="11" I="0" FilBy="0"/>',
             '<Fil T="1" F="25.00" Q="1" G="0" dF="25" FN="12" I="0" FilBy="0"/>',
             '<Fil T="1" F="20000.00" Q="1" G="0" dF="20000" FN="13" I="0" FilBy="0"/>']
    return ('<OC ON="1" CINV="0">' + "".join(fils) + '<Vol T="15" L="1.0" i="0"/>'
            + '<T PM="1" P="0" T="0"/></OC>')


def _export(path, spl):
    rows = ["* Freq(Hz) SPL(dB)"] + ["%.4f %.4f" % (f, s) for f, s in zip(FREQS, spl)]
    Path(path).write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(path)


class CliCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def cli(self, *args, ok=True):
        if args[0] == "propose" and "--dsp-rate" not in args:
            args = (*args, "--dsp-rate", "96000")
        run = subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), *args],
                             text=True, capture_output=True, check=False, cwd=self.root)
        if not ok:
            self.assertNotEqual(0, run.returncode, run.stdout)
            return run.stderr
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        return json.loads(run.stdout)

    def tune(self, name, channel_xml):
        path = self.root / name
        afpx._encode_unchecked("<ATF>" + channel_xml + "</ATF>", str(path))
        return str(path)

    def solos(self, shape, n=3, seed=5, prefix="pos"):
        rng = np.random.default_rng(seed)
        return [_export(self.root / ("%s%d.txt" % (prefix, i)),
                        80 + i + _target() + shape + rng.normal(0, 0.3, len(FREQS)))
                for i in range(n)]


# ------------------------------------------------------------ band-limited anchor
class BandLimitedAnchorTests(CliCase):
    def test_a_tweeter_solo_is_judged_on_shape_not_on_its_stopband(self):
        bank = [(6000.0, 2.0, -4.0)]               # already cancels the real 6 kHz peak
        tune = self.tune("tw.afpx", _channel(bank, hp=3500.0))
        shape = (_lr4_db("hp", 3500.0) + tunelib.peaking_db(FREQS, 6000.0, 2.0, 4.0)
                 + tunelib.cascade_db(FREQS, bank, fs=FS))
        r = self.cli("refine", "--afpx", tune, "--channels", "0", "--dsp-rate", "96000",
                     "--positions", *self.solos(shape), "--target", "default")
        # Anchored at 300-3000 Hz this read ~15 dB of error and cut -15 dB at Q0.5.
        self.assertLess(r["baseline"]["mean_score_db"], 2.0, r["baseline"])
        self.assertFalse([e for e in r["edits"] if e["new"] and e["new"][2] <= -8.0], r["edits"])
        self.assertTrue(any("anchored inside the judged band" in n for n in r["notes"]))

    def test_a_sub_channel_is_judged_from_20_hz_not_from_60(self):
        bank = [(45.0, 3.0, -4.0)]
        tune = self.tune("sub.afpx", _channel(bank, lp=80.0))
        shape = (_lr4_db("lp", 80.0) + tunelib.peaking_db(FREQS, 45.0, 3.0, 4.0)
                 + tunelib.cascade_db(FREQS, bank, fs=FS))
        r = self.cli("refine", "--afpx", tune, "--channels", "0", "--dsp-rate", "96000",
                     "--positions", *self.solos(shape), "--target", "default")
        self.assertLess(r["meta"]["judged_band_hz"][0], 30.0)
        self.assertLess(r["baseline"]["mean_score_db"], 2.0, r["baseline"])

    def test_propose_on_a_tweeter_fit_band_cuts_the_peak_not_the_level(self):
        shape = _lr4_db("hp", 3500.0) + tunelib.peaking_db(FREQS, 6000.0, 2.0, 4.0)
        r = self.cli("propose", "--positions", *self.solos(shape), "--target", "default",
                     "--fit-band", "4500", "12000")
        self.assertTrue(any("level anchored inside" in n for n in r["notes"]))
        bands = r["proposal"]["bands"] + r["proposal"]["rejected"]
        self.assertTrue(bands)
        near = min(bands, key=lambda b: abs(np.log2(b["f_hz"] / 6000.0)))
        self.assertLess(abs(np.log2(near["f_hz"] / 6000.0)), 0.3)
        self.assertGreater(near["gain_db"], -7.0)
        self.assertIsNone(r["bass_balance"])       # a tweeter says nothing about the bass

    def test_a_full_range_fit_band_keeps_the_session_anchor(self):
        self.assertFalse(pipeline._outside_anchor((60.0, 12000.0)))
        self.assertTrue(pipeline._outside_anchor((3300.0, 12000.0)))
        self.assertTrue(pipeline._outside_anchor((20.0, 80.0)))


# ------------------------------------------------------------ sittings
class SittingTests(CliCase):
    def test_folds_withhold_whole_sittings(self):
        rng = np.random.default_rng(1)
        shared = tunelib.cascade_db(FREQS, [(300.0, 1.4, 6.0)])
        devs = np.vstack([shared + rng.normal(0, 0.3, len(FREQS)) for _ in range(6)])
        rep = tunelib.held_out_band_validation(FREQS, devs, (60.0, 12000.0),
                                               groups=["a", "a", "b", "b", "c", "c"])
        self.assertEqual([f["held_out_group"] for f in rep["folds"]], ["a", "b", "c"])
        self.assertEqual(rep["folds"][1]["held_out_position"], [2, 3])
        self.assertEqual(rep["verdict"], "validated")

    def test_groups_must_name_every_position_and_reach_three_sittings(self):
        devs = np.zeros((4, len(FREQS)))
        with self.assertRaisesRegex(ValueError, "one label per position"):
            tunelib.held_out_band_validation(FREQS, devs, (60.0, 12000.0), groups=["a", "b"])
        with self.assertRaisesRegex(ValueError, "three sittings"):
            tunelib.held_out_band_validation(FREQS, devs, (60.0, 12000.0),
                                             groups=["a", "a", "b", "b"])

    def test_propose_with_two_sittings_does_not_claim_held_out_validation(self):
        shape = tunelib.peaking_db(FREQS, 300.0, 1.4, 5.0)
        paths = self.solos(shape, n=4)
        r = self.cli("propose", "--positions", *paths, "--target", "default",
                     "--sittings", "aug8", "aug8", "aug10", "aug10")
        self.assertIsNone(r["held_out_validation"])
        self.assertEqual(r["meta"]["sittings_used"], 2)
        self.assertTrue(any("only 2 sitting" in n for n in r["notes"]))
        err = self.cli("propose", "--positions", *paths, "--target", "default",
                       "--sittings", "aug8", "aug10", ok=False)
        self.assertIn("one label per --positions file", err)

    def test_unlabelled_positions_get_a_prompt_to_label_them(self):
        r = self.cli("propose", "--positions",
                     *self.solos(tunelib.peaking_db(FREQS, 300.0, 1.4, 5.0)),
                     "--target", "default")
        self.assertTrue(any("--sittings" in n for n in r["notes"]))


# ------------------------------------------------------------ vehicle guards
class VehicleGuardTests(CliCase):
    def test_guards_are_validated_before_they_are_recorded(self):
        tune = self.root / "t.afpx"
        tune.write_bytes(b"x")
        for bad in ({"no_boost": [{"lo_hz": 380, "hi_hz": 540}]},          # no reason
                    {"no_boost": [{"lo_hz": 540, "hi_hz": 380, "reason": "r"}]},
                    {"no_boost": [{"lo_hz": 1, "hi_hz": 2, "channels": [], "reason": "r"}]},
                    {"max_boost_q": -1},
                    {"boost_everything": True}):
            with self.assertRaises(ValueError, msg=bad):
                pipeline.session_save(tune, {"guards": bad})
        pipeline.session_save(tune, {"guards": GUARDS})
        stored = json.loads((self.root / "t.afpx.tuner_session.json").read_text("utf-8"))
        self.assertEqual(stored["guards"], GUARDS)

    def test_a_boost_into_a_zone_or_above_the_q_cap_is_blocked_a_cut_never(self):
        check = pipeline.guard_check(GUARDS, channels=[0])
        self.assertIn("seated-listener null", check(450.0, 2.0, 2.0))
        self.assertIn("max_boost_q", check(2000.0, 5.0, 1.0))
        self.assertIsNone(check(450.0, 2.0, -6.0))
        self.assertIsNone(check(2000.0, 2.0, 2.0))
        self.assertIsNone(pipeline.guard_check(GUARDS, channels=[1])(450.0, 2.0, 2.0))

    def test_guards_outlive_a_tune_edit(self):
        tune = self.root / "t.afpx"
        tune.write_bytes(b"v1")
        pipeline.session_save(tune, {"guards": GUARDS})
        tune.write_bytes(b"v2")
        notes = []
        self.assertEqual(pipeline.load_guards(tune, notes), GUARDS)
        self.assertTrue(any("describe the car" in n for n in notes))

    def test_propose_rejects_a_guarded_boost_with_its_reason(self):
        dip = tunelib.peaking_db(FREQS, 450.0, 1.5, -5.0)
        paths = self.solos(dip)
        free = self.cli("propose", "--positions", *paths, "--target", "default")
        boosts = [b for b in free["proposal"]["bands"]
                  if b["gain_db"] > 0 and abs(np.log2(b["f_hz"] / 450.0)) < 0.5]
        self.assertTrue(boosts, free["proposal"])
        tune = self.root / "car.afpx"
        tune.write_bytes(b"car")
        pipeline.session_save(tune, {"guards": GUARDS})
        r = self.cli("propose", "--positions", *paths, "--target", "default",
                     "--session-tune", str(tune), "--channels", "0")
        self.assertFalse([b for b in r["proposal"]["bands"]
                          if b["gain_db"] > 0 and abs(np.log2(b["f_hz"] / 450.0)) < 0.5])
        self.assertTrue(any("vehicle guard" in b.get("reason", "")
                            for b in r["proposal"]["rejected"]), r["proposal"])

    def test_refine_will_not_raise_a_boost_into_a_guarded_zone(self):
        bank = [(450.0, 2.0, 1.0)]
        tune = self.tune("mid.afpx", _channel(bank, hp=80.0, lp=3000.0))
        shape = (_lr4_db("hp", 80.0) + _lr4_db("lp", 3000.0)
                 + tunelib.peaking_db(FREQS, 450.0, 2.0, -4.0)
                 + tunelib.cascade_db(FREQS, bank, fs=FS))
        paths = self.solos(shape)
        args = ("refine", "--afpx", tune, "--channels", "0", "--dsp-rate", "96000",
                "--positions", *paths, "--target", "default")
        free = self.cli(*args)
        raised = [e for e in free["edits"] if e["new"] and e["new"][2] > 1.0]
        self.assertTrue(raised, free["edits"])
        pipeline.session_save(tune, {"guards": GUARDS})
        r = self.cli(*args)
        self.assertFalse([e for e in r["edits"] if e["new"] and e["new"][2] > 1.0], r["edits"])
        self.assertTrue(any("vehicle guard blocked" in n for n in r["notes"]))


if __name__ == "__main__":
    unittest.main()
