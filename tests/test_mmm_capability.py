"""MMM capability: the recorded REW setup, an EQ policy judged against the
repeatability where each filter acts, the verify step after a write, and
blind voicing variants."""

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
GOOD_PROFILE = {"analyzer": "rta 1/48", "noise": "pink periodic", "fft_length": 65536,
                "sequence_length": 65536, "sample_rate_hz": 48000, "playback": "rew",
                "window": "rectangular", "averaging": "forever", "rms_level_dbfs": -12,
                "mic_cal": "90deg", "mic_aim": "up", "engine": "off"}


def _target():
    return measure.load_target(SCRIPTS.parent / "assets" / "default_incar_target.txt", FREQS)


def _rta(path, spl):
    rows = ["* RTA 1/48 octave"] + ["%.4f %.4f" % (f, s) for f, s in zip(FREQS, spl)]
    Path(path).write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(path)


def _channel(bank, low_shelf=None):
    fils = ['<Fil T="16" F="80.00" Q="0.7" G="-24" dF="80" FN="1" I="0" FilBy="0"/>',
            '<Fil T="15" F="3000.00" Q="0.7" G="-24" dF="3000" FN="2" I="0" FilBy="0"/>']
    for k, (F, Q, G) in enumerate(bank):
        fils.append('<Fil T="17" F="%.2f" Q="%g" G="%g" dF="%d" FN="%d" I="0" FilBy="0"/>'
                    % (F, Q, G, int(F), 3 + k))
    fils += ['<Fil T="1" F="200.00" Q="1" G="0" dF="200" FN="10" I="0" FilBy="0"/>',
             '<Fil T="1" F="800.00" Q="1" G="0" dF="800" FN="11" I="0" FilBy="0"/>']
    if low_shelf:
        fils.append('<Fil T="3" F="%.2f" Q="0.7" G="%g" dF="25" FN="12" I="0" FilBy="0"/>'
                    % low_shelf)
    else:
        fils.append('<Fil T="1" F="25.00" Q="1" G="0" dF="25" FN="12" I="0" FilBy="0"/>')
    fils.append('<Fil T="1" F="20000.00" Q="1" G="0" dF="20000" FN="13" I="0" FilBy="0"/>')
    return ('<OC ON="1" CINV="0">' + "".join(fils) + '<Vol T="15" L="1.0" i="0"/>'
            '<T PM="1" P="0" T="0"/></OC>')


class Cli(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.rng = np.random.default_rng(7)

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

    def wobble(self, amp_db):
        """How two MMM runs really differ: a slightly different mic path moves
        the response in broad, smooth swings, not independent per-bin noise."""
        x = np.log2(FREQS)
        return sum(self.rng.normal(0, amp_db) * np.sin(2 * np.pi * x * k / 3.0
                                                       + self.rng.uniform(0, 2 * np.pi))
                   for k in (1, 2, 3)) / np.sqrt(1.5)

    def runs(self, extra, n=2, noise=0.15, tag="r", bank=(), wobble_db=0.0):
        paths = []
        for i in range(n):
            spl = (80 + _target() + extra + tunelib.cascade_db(FREQS, list(bank))
                   + self.rng.normal(0, noise, len(FREQS))
                   + (self.wobble(wobble_db) if wobble_db else 0.0))
            paths.append(_rta(self.root / ("%s%d.txt" % (tag, i)), spl))
        return paths

    def profile(self, **changes):
        prof = dict(GOOD_PROFILE, **changes)
        path = self.root / "profile.json"
        path.write_text(json.dumps(prof), encoding="utf-8")
        return str(path)


class ReportSizeTests(Cli):
    def test_repeatability_is_summarised_not_dumped(self):
        a = self.run_cli("analyze", "--capture", "mmm", "--positions", *self.runs(0.0),
                         "--target", "default")
        rep = a["capture"]["repeatability"]
        self.assertNotIn("noise_by_frequency_db", rep)
        self.assertNotIn("frequency_hz", rep)
        self.assertEqual(len(rep["bands"]), 3)
        self.assertLess(len(json.dumps(a["capture"])), 2500)


class CaptureProfileTests(Cli):
    def test_rew_rule_violations_are_refused(self):
        p = self.runs(0.0, n=1)[0]
        for bad, word in (({"analyzer": "spectrum"}, "Spectrum"),
                          ({"noise": "white periodic"}, "rising"),
                          ({"sequence_length": 32768}, "sequence length"),
                          ({"engine": "on"}, "engine off")):
            err = self.run_cli("analyze", "--capture", "mmm", "--measurement", p,
                               "--target", "default", "--capture-profile", self.profile(**bad),
                               ok=False)
            self.assertIn(word, err)

    def test_a_car_source_on_a_separate_clock_is_flagged(self):
        p = self.runs(0.0, n=1)[0]
        a = self.run_cli("analyze", "--capture", "mmm", "--measurement", p, "--target", "default",
                         "--capture-profile", self.profile(playback="file",
                                                           test_file_sample_rate_hz=48000,
                                                           test_file_fft_length=65536))
        self.assertTrue(any("separate clocks" in n for n in a["notes"]), a["notes"])
        self.assertIsNotNone(a["capture"]["profile"]["id"])

    def test_a_recorded_correct_setup_turns_the_tilt_refusal_into_a_check(self):
        steep = self.runs(-3.0 * np.log2(FREQS / 1000.0), n=1)[0]
        self.run_cli("propose", "--capture", "mmm", "--measurement", steep, "--target", "default",
                     ok=False)
        r = self.run_cli("propose", "--capture", "mmm", "--measurement", steep,
                         "--target", "default", "--capture-profile", self.profile())
        self.assertTrue(any("recorded capture profile says" in n for n in r["notes"]))


class MmmEqPolicyTests(Cli):
    def test_a_band_smaller_than_the_local_repeatability_is_not_proposed(self):
        room = tunelib.peaking_db(FREQS, 2000.0, 2.0, 1.3)
        noisy = self.runs(room, n=3, tag="n", wobble_db=1.2)
        r = self.run_cli("propose", "--capture", "mmm", "--positions", *noisy,
                         "--target", "default")
        near = [b for b in r["proposal"]["bands"] if 1400 < b["f_hz"] < 2900]
        self.assertEqual(near, [], r["proposal"])

    def test_a_real_band_well_above_repeatability_is_kept_and_says_so(self):
        room = tunelib.peaking_db(FREQS, 2000.0, 2.0, 6.0)
        r = self.run_cli("propose", "--capture", "mmm", "--positions", *self.runs(room),
                         "--target", "default")
        near = [b for b in r["proposal"]["bands"] if 1400 < b["f_hz"] < 2900]
        self.assertTrue(near, r["proposal"])
        self.assertEqual(near[0]["repeatability"]["status"], "supported")

    def test_one_run_keeps_filters_broad(self):
        room = tunelib.peaking_db(FREQS, 3000.0, 8.0, 6.0)
        r = self.run_cli("propose", "--capture", "mmm", "--measurement",
                         self.runs(room, n=1)[0], "--target", "default")
        for b in r["proposal"]["bands"] + r["proposal"]["rejected"]:
            self.assertLessEqual(b["q"], 4.0, b)

    def test_refine_without_cancellation_evidence_adds_no_boost(self):
        tune = self.root / "t.afpx"
        afpx._encode_unchecked("<ATF>" + _channel([]) + "</ATF>", str(tune))
        room = tunelib.peaking_db(FREQS, 700.0, 1.5, -5.0)
        r = self.run_cli("refine", "--afpx", str(tune), "--channels", "0", "--dsp-rate",
                         "96000", "--capture", "mmm", "--positions", *self.runs(room),
                         "--target", "default")
        self.assertFalse([e for e in r["edits"] if e["new"] and e["new"][2] > 0], r["edits"])
        self.assertTrue(any("no --cancel-check" in n for n in r["notes"]))

    def test_refine_vetoes_an_edit_inside_the_repeatability(self):
        bank = [(500.0, 2.0, -3.5)]
        tune = self.root / "t.afpx"
        afpx._encode_unchecked("<ATF>" + _channel(bank) + "</ATF>", str(tune))
        room = tunelib.peaking_db(FREQS, 500.0, 2.0, 3.0)        # 0.5 dB over-cut
        r = self.run_cli("refine", "--afpx", str(tune), "--channels", "0", "--dsp-rate",
                         "96000", "--capture", "mmm",
                         "--positions", *self.runs(room, n=3, bank=bank, wobble_db=1.0),
                         "--target", "default")
        self.assertEqual(r["edits"], [], r["edits"])


class VerifyTests(Cli):
    old, new = [(500.0, 2.0, -6.0)], [(500.0, 2.0, -3.0)]
    room = None

    def captures(self, bank, tag):
        return self.runs(tunelib.peaking_db(FREQS, 500.0, 2.0, 3.0), n=2, tag=tag, bank=bank)

    def test_a_change_that_landed_is_confirmed(self):
        before, after = self.captures(self.old, "b"), self.captures(self.new, "a")
        r = self.run_cli("verify", "--before", *before, "--after", *after, "--dsp-rate", "96000",
                         "--bands", "500,2,-3", "--old-bands", "500,2,-6")
        self.assertEqual([b["verdict"] for b in r["bands"]].count("confirmed"), 2, r["bands"])
        self.assertLess(r["target_error_db"]["after"], r["target_error_db"]["before"])
        self.assertTrue(r["trace_changed"])

    def test_an_unloaded_write_is_not_confirmed(self):
        before, after = self.captures(self.old, "b"), self.captures(self.old, "a")
        r = self.run_cli("verify", "--before", *before, "--after", *after, "--dsp-rate", "96000",
                         "--bands", "500,2,-3", "--old-bands", "500,2,-6")
        self.assertNotIn("confirmed", [b["verdict"] for b in r["bands"]])
        self.assertTrue(all(b["advice"] for b in r["bands"]))

    def test_it_reads_a_propose_report(self):
        report = {"proposal": {"bands": [{"f_hz": 500.0, "q": 2.0, "gain_db": -3.0}]}}
        path = self.root / "propose.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        room = tunelib.peaking_db(FREQS, 500.0, 2.0, 3.0)
        before = self.runs(room, tag="b")
        after = self.runs(room + tunelib.peaking_db(FREQS, 500.0, 2.0, -3.0), tag="a")
        r = self.run_cli("verify", "--before", *before, "--after", *after, "--dsp-rate", "96000",
                         "--report", str(path))
        self.assertEqual(r["bands"][0]["verdict"], "confirmed", r["bands"])


class IdenticalChannelWriteTests(unittest.TestCase):
    def test_an_edit_lands_on_its_own_channel_when_two_channels_are_identical(self):
        blk = ('<OC ON="1" CINV="0"><Fil T="17" F="100.00" Q="1" G="-2" dF="100" FN="1" '
               'I="0" FilBy="0"/></OC>')
        new = afpx.write_filter_slot('<ATF>' + blk + blk + '</ATF>', 1, 0, G=-4)
        gains = [afpx.attrs(f)['G'] for b in afpx.channel_blocks(new) for f in afpx.filters(b)]
        self.assertEqual(gains, ['-2', '-4'])


class VoiceVariantTests(Cli):
    def setUp(self):
        super().setUp()
        self.tune = self.root / "tuned.afpx"
        afpx._encode_unchecked("<ATF>" + _channel([]) + _channel([], low_shelf=(90.0, 2.0))
                               + _channel([]) + "</ATF>", str(self.tune))

    def test_dry_run_writes_nothing_then_confirm_writes_one_change_per_variant(self):
        args = ("voice-variants", "--afpx", str(self.tune), "--out-dir", str(self.root / "v"),
                "--bass-channels", "0", "1", "--treble-channels", "2",
                "--bass-db", "1", "--treble-db", "-1")
        dry = self.run_cli(*args)
        self.assertFalse(dry["meta"]["written"])
        self.assertFalse(any(Path(v["file"]).exists() for v in dry["variants"]))
        r = self.run_cli(*args, "--confirm")
        by = {v["variant"]: v for v in r["variants"]}
        bass = afpx.channels(afpx.decode(by["bass+1.00dB"]["file"]))
        self.assertEqual(bass[0]["shelves"], [("low_shelf", 120.0, 0.7, 1.0)])
        self.assertEqual(bass[1]["shelves"], [("low_shelf", 90.0, 0.7, 3.0)])  # existing +2 -> +3
        self.assertEqual(bass[2]["shelves"], [])
        treble = afpx.channels(afpx.decode(by["treble-1.00dB"]["file"]))
        self.assertEqual(treble[2]["shelves"], [("high_shelf", 6000.0, 0.7, -1.0)])
        self.assertEqual(treble[0]["shelves"], [])
        self.assertGreater(by["bass+1.00dB"]["predicted_loudness_change_db"], 0)
        self.assertLess(by["treble-1.00dB"]["predicted_loudness_change_db"], 0)
        self.assertIn("ab-make", by["bass+1.00dB"]["ab_make"])


if __name__ == "__main__":
    unittest.main()
