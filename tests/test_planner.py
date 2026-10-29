"""capture-plan and next: the plan's capture names must be the ones the audit
and `next` recognise, and every command `next` prints must run as printed."""

import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "helix-rew-tuner" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

import afpx  # noqa: E402
import measure  # noqa: E402
import planner  # noqa: E402
from test_capture_intelligence import _lr4, _lr4_db, rew_text  # noqa: E402

GRID = measure.common_grid(10.0, 23000.0, 96)


def _oc(hp=None, lp=None):
    fils = []
    if hp:
        fils.append('<Fil T="16" F="%.2f" Q="0.7" G="-24" dF="%d" FN="1" I="0" FilBy="0"/>' % (hp, hp))
    if lp:
        fils.append('<Fil T="15" F="%.2f" Q="0.7" G="-24" dF="%d" FN="2" I="0" FilBy="0"/>' % (lp, lp))
    fils += ['<Fil T="1" F="25.00" Q="1" G="0" dF="25" FN="12" I="0" FilBy="0"/>',
             '<Fil T="1" F="20000.00" Q="1" G="0" dF="20000" FN="13" I="0" FilBy="0"/>']
    return ('<OC ON="1" CINV="0">' + ''.join(fils) + '<Vol T="15" L="1.0" i="0"/>'
            '<T PM="1" P="0" T="0"/></OC>')


class _Tmp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.rng = np.random.default_rng(3)

    def cli(self, *args):
        run = subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), *args],
                             text=True, capture_output=True, check=False, cwd=self.root)
        self.assertEqual(0, run.returncode, run.stderr)
        return json.loads(run.stdout)

    def tune(self):
        path = self.root / "car.afpx"
        blocks = [_oc(hp=2600), _oc(hp=2600), _oc(hp=80, lp=2600), _oc(hp=80, lp=2600),
                  _oc(hp=20, lp=80), _oc(hp=20, lp=80)]
        afpx._encode_unchecked("<ATF>" + "".join(blocks) + "</ATF>", str(path))
        return path


class CapturePlan(_Tmp):
    def test_the_plan_follows_the_tune(self):
        r = self.cli("capture-plan", "--goal", "all", "--afpx", str(self.tune()), "--dsp-rate", "96000")
        self.assertEqual(r["averages"], planner.averages_for(25.0, 65536, 48000.0))
        self.assertEqual(r["averages"], 140)
        self.assertIn("100 dB SPL", r["levels"]["mic_ceiling"])
        names = [c["name"] for c in r["captures"]]
        t1 = next(c for c in r["captures"] if c["name"].startswith("Sub Midbass Both T1"))
        self.assertIn("3.12 ms", t1["name"].replace("ms", " ms") + " " + t1["what"])
        self.assertIn("300 samples at 96000 Hz", t1["how"])
        # tweeters: never RAW (the high-pass stays); midbass RAW keeps its high-pass
        self.assertFalse(any(n.startswith("ch0") and n.endswith("RAW") for n in names))
        raw = next(c for c in r["captures"] if c["name"] == "ch2 midbass RAW")
        self.assertIn("high-pass kept", raw["what"])
        self.assertTrue(any("never bypass a tweeter" in s for s in r["safety"]))
        self.assertIn(["Front L", "Front R", "Front Both"], r["cancel_check_sets"])

    def test_unknown_goal_is_one_line(self):
        run = subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), "capture-plan", "--goal",
                              "everything"], text=True, capture_output=True, cwd=self.root)
        self.assertNotEqual(0, run.returncode)
        self.assertIn("error: unknown goal", run.stderr)


class NextSteps(_Tmp):
    def session(self):
        """Captures named exactly as capture-plan names them."""
        f = GRID
        sub = _lr4(f, 80, "lp") * np.exp(-2j * np.pi * f * 0.004)
        mb = _lr4(f, 80, "hp") * np.exp(-2j * np.pi * f * 0.006)      # 2 ms late
        tau1 = 3.12
        rot = np.exp(-2j * np.pi * f * tau1 / 1e3)
        db = lambda x: 80 + 10 * np.log10(np.abs(x) ** 2 + 1e-12) + self.rng.normal(0, 0.05, len(f))
        tw = 70 + _lr4_db(f, 2600, "hp")
        side = 75 + _lr4_db(f, 80, "hp")
        files = {
            "System Sum": db(sub + mb) + 0.0, "Sub": db(sub), "Midbass Both": db(mb),
            "Sub Midbass Both": db(sub + mb), "Sub Midbass Both T1 3.12ms": db(sub + mb * rot),
            "Front L": side, "Front R": side + 0.5, "Front Both": side + 3.2,
            "Left Tweeter": np.maximum(tw, 20), "Right Tweeter": np.maximum(tw + 0.3, 20),
        }
        # level notes as REW would write them for one playback level: the two
        # halves at 62 dBA, both together at their power sum
        both_names = ("Front Both", "System Sum", "Sub Midbass Both", "Sub Midbass Both T1 3.12ms")
        for name, spl in files.items():
            dba = 65.0 if name in both_names else 62.0
            rew_text(self.root / ("%s.txt" % name), f, spl, name, averages=140, dba=dba,
                     dbc=dba + 3, unw=dba + 4, rms=dba + 4.2)
        return self.root

    def test_next_assembles_the_four_capture_alignment_and_the_rest(self):
        self.session()
        r = self.cli("next", "--captures", ".")
        cmds = [row["command"] for row in r["run"]]
        align = [c for c in cmds if c.startswith("pipeline.py mmm-align")]
        self.assertEqual(len(align), 1, cmds)
        self.assertIn("--tau1-ms 3.12", align[0])
        self.assertIn('Midbass Both.txt', align[0])
        self.assertTrue(any(c.startswith("pipeline.py analyze") and "System Sum" in c for c in cmds))
        self.assertTrue(any(c.startswith("pipeline.py coherence") and "Front Both" in c for c in cmds))

    def test_every_printed_command_runs(self):
        self.session()
        r = self.cli("next", "--captures", ".")
        ran = 0
        for row in r["run"]:
            words = [w.strip('"\'') for w in shlex.split(row["command"], posix=False)]
            if any("<" in w for w in words):
                continue
            with self.subTest(command=words[1]):
                out = self.cli(*words[1:])
                self.assertIsInstance(out, dict)
                ran += 1
        self.assertGreaterEqual(ran, 5)

    def test_the_alignment_it_suggests_finds_the_late_midbass(self):
        self.session()
        r = self.cli("next", "--captures", ".")
        cmd = next(row["command"] for row in r["run"] if row["command"].startswith("pipeline.py mmm-align"))
        words = [w.strip('"\'') for w in shlex.split(cmd, posix=False)][1:]
        out = self.cli(*words)
        self.assertEqual(out["verdict"], "candidate")
        self.assertAlmostEqual(out["best"]["delay_change_ms"], -2.0, delta=0.3)


if __name__ == "__main__":
    unittest.main()
