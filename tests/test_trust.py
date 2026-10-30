"""trust-check: one validation evening decides how far to trust mmm-align, the
peak-trace stability map, frames and the interleaved test signal. Each check is
run against synthetic captures with a known answer, both ways round."""

import json
import math
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

import measure  # noqa: E402
import trust  # noqa: E402
from test_capture_intelligence import _lr4, rew_text  # noqa: E402

GRID = measure.common_grid(15.0, 22000.0, 96)


def _timed(path, freqs, h, name):
    lines = ["* Measurement: %s" % name, "* timing reference: Acoustic",
             "* Freq(Hz) SPL(dB) Phase(degrees)"]
    db = 80 + 20 * np.log10(np.abs(h) + 1e-12)
    ph = np.degrees(np.angle(h))
    lines += ["%.6f %.4f %.4f" % (f, s, p) for f, s, p in zip(freqs, db, ph)]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


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

    def run_out(self, *args):
        run = subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), *args],
                             text=True, capture_output=True, check=False, cwd=self.root)
        self.assertEqual(0, run.returncode, run.stderr)

    def fails(self, *args):
        run = subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), *args],
                             text=True, capture_output=True, check=False, cwd=self.root)
        self.assertEqual(2, run.returncode, run.stdout)
        return run.stderr


class AlignAgainstSweeps(_Tmp):
    """The same sub/midbass junction measured two ways: four MMM captures and
    timed sweeps. The midbass arrives 4 ms late."""

    def evening(self):
        f = measure.common_grid(30.0, 300.0, 96)
        a = _lr4(f, 80, "lp") * np.exp(-2j * np.pi * f * 0.004)
        b = _lr4(f, 80, "hp") * np.exp(-2j * np.pi * f * 0.008)
        tau1 = 1e3 / (4 * math.sqrt(50 * 130))
        rot = np.exp(-2j * np.pi * f * tau1 / 1e3)
        caps = {"Sub": a, "Midbass Both": b, "Sub Midbass Both": a + b, "Sub Midbass Both T1": a + b * rot}
        p = {k: rew_text(self.root / ("%s.txt" % k), f, 80 + 10 * np.log10(np.abs(v) ** 2 + 1e-12), k)
             for k, v in caps.items()}
        self.run_out("mmm-align", "--a", p["Sub"], "--b", p["Midbass Both"], "--together", p["Sub Midbass Both"],
                 "--together-delayed", p["Sub Midbass Both T1"], "--tau1-ms", "%.4f" % tau1,
                 "--band", "50", "130", "--out", str(self.root / "align.json"))
        sf = measure.common_grid(15.0, 1000.0, 96)
        sub = _timed(self.root / "Sub sweep.txt", sf, _lr4(sf, 80, "lp") * np.exp(-2j * np.pi * sf * 0.004),
                     "Sub sweep")
        mid = _timed(self.root / "Midbass sweep.txt", sf,
                     _lr4(sf, 80, "hp") * np.exp(-2j * np.pi * sf * 0.008), "Midbass sweep")
        self.run_out("junction", "--lower", sub, "--upper", mid, "--crossover", "80",
                 "--out", str(self.root / "junction.json"))
        return str(self.root / "align.json"), str(self.root / "junction.json")

    def test_two_methods_that_agree_are_trusted(self):
        align, junction = self.evening()
        r = self.cli("trust-check", "--align", align, "--junction", junction)
        m = r["tools"]["mmm-align"]
        self.assertEqual(m["verdict"], "trusted", m)
        self.assertAlmostEqual(m["mmm_align"]["midbass_delay_change_ms"], -4.0, delta=0.3)
        self.assertAlmostEqual(m["midbass_delay_from_sweeps_ms"], -4.0, delta=0.3)
        self.assertEqual(r["tools"]["stability"]["verdict"], "not_run")

    def test_a_disagreement_is_caught(self):
        align, junction = self.evening()
        r = json.loads(Path(align).read_text())
        r["best"]["delay_change_ms"] += 5.0                 # 0.4 of a period at 80 Hz
        Path(align).write_text(json.dumps(r))
        self.assertEqual(self.cli("trust-check", "--align", align, "--junction", junction)
                         ["tools"]["mmm-align"]["verdict"], "remove")
        r["best"]["delay_change_ms"] -= 5.0
        r["best"]["invert_b"] = not r["best"]["invert_b"]
        Path(align).write_text(json.dumps(r))
        out = self.cli("trust-check", "--align", align, "--junction", junction)["tools"]["mmm-align"]
        self.assertEqual((out["verdict"], out["same_polarity"]), ("remove", False))

    def test_quarter_period_is_advisory_and_a_doubtful_reference_is_not_run(self):
        align = {"meta": {"band_hz": [50, 130]}, "verdict": "candidate",
                 "best": {"delay_change_ms": -1.5, "invert_b": False}}
        junction = {"meta": {"crossover_hz": 80.0},
                    "delay_consensus": {"crossover_hz": 80.0, "extra_delay_lower_ms": -1.5 + 2.4,
                                        "invert": False, "confidence": "high"}}
        self.assertEqual(trust.align_check(align, junction)["verdict"], "trusted")
        junction["delay_consensus"]["extra_delay_lower_ms"] = 1.5 + 2.4      # 2.4 ms out
        self.assertEqual(trust.align_check(align, junction)["verdict"], "advisory")
        junction["delay_consensus"]["confidence"] = "low"
        self.assertEqual(trust.align_check(align, junction)["verdict"], "not_run")
        junction["delay_consensus"].update(confidence="high", crossover_hz=200.0)
        self.assertEqual(trust.align_check(align, junction)["verdict"], "not_run")


class StabilityAgainstRepeats(_Tmp):
    def runs(self, moving_differs):
        avg = 75 + self.rng.normal(0, 0.05, len(GRID))
        peak = avg + 2.0
        moving = (GRID > 90) & (GRID < 135)
        peak[moving] += 6.0
        diff = np.where(moving if moving_differs else (GRID > 160) & (GRID < 240), 2.5, 0.1)
        rep = avg + diff + self.rng.normal(0, 0.05, len(GRID))
        return [rew_text(self.root / ("%s.txt" % n), GRID, d, n)
                for n, d in (("System Sum run 1", avg), ("System Sum run 1 peak", peak),
                             ("System Sum run 2", rep))]

    def test_bands_marked_moving_are_the_ones_two_runs_disagree_on(self):
        a, p, b = self.runs(moving_differs=True)
        s = self.cli("trust-check", "--average", a, "--peak", p, "--repeat", b)["tools"]["stability"]
        self.assertEqual(s["verdict"], "trusted", s)
        self.assertGreater(s["moving_bands_mean_db"], s["stable_bands_mean_db"])

    def test_a_map_that_marks_the_wrong_bands_is_removed(self):
        a, p, b = self.runs(moving_differs=False)
        s = self.cli("trust-check", "--average", a, "--peak", p, "--repeat", b)["tools"]["stability"]
        self.assertEqual(s["verdict"], "remove", s)

    def test_identical_runs_are_inconclusive(self):
        a, p, _b = self.runs(moving_differs=True)
        s = self.cli("trust-check", "--average", a, "--peak", p, "--repeat", a)["tools"]["stability"]
        self.assertEqual(s["verdict"], "inconclusive")


class FramesAndSignals(_Tmp):
    def test_frames_against_rew_on_the_same_pass(self):
        base = 70 - 3 * np.log2(GRID / 1000.0) / 10
        rew = rew_text(self.root / "System Sum run 1.txt", GRID, base, "System Sum run 1")
        same = rew_text(self.root / "mean.txt", GRID, base - 12 + self.rng.normal(0, 0.1, len(GRID)), "mean")
        self.assertEqual(self.cli("trust-check", "--frames-mean", same, "--average", rew)
                         ["tools"]["frames"]["verdict"], "trusted")
        bent = rew_text(self.root / "bent.txt", GRID, base + np.where(GRID > 3000, 3.0, 0.0), "bent")
        out = self.cli("trust-check", "--frames-mean", bent, "--average", rew)["tools"]["frames"]
        self.assertEqual(out["verdict"], "remove")
        self.assertGreater(out["worst_hz"], 3000)

    def test_one_interleaved_pass_against_separate_captures(self):
        l_db = 75 + 2 * np.sin(np.log2(GRID / 100.0))
        r_db = 74 + 1.5 * np.cos(np.log2(GRID / 100.0))
        left = rew_text(self.root / "Front L.txt", GRID, l_db, "Front L")
        right = rew_text(self.root / "Front R.txt", GRID, r_db, "Front R")
        hz = measure.common_grid(100.0, 10000.0, 6)

        def report(err):
            ild = np.interp(np.log(hz), np.log(GRID), l_db - r_db) + err
            rows = [{"hz": round(float(h), 1), "left_db": -20.0, "right_db": round(-20.0 - float(i), 2),
                     "ild_db": round(float(i), 2)} for h, i in zip(hz, ild)]
            path = self.root / "signal.json"
            path.write_text(json.dumps({"bands": rows, "meta": {"kind": "lr-interleaved"}}))
            return str(path)
        good = self.cli("trust-check", "--signal", report(0.0), "--front-l", left, "--front-r", right)
        self.assertEqual(good["tools"]["test-signals"]["verdict"], "trusted")
        bad = self.cli("trust-check", "--signal", report(np.where(hz > 1000, 4.0, -2.0)),
                       "--front-l", left, "--front-r", right)
        self.assertEqual(bad["tools"]["test-signals"]["verdict"], "remove")

    def test_inputs_go_in_sets(self):
        self.assertIn("go together", self.fails("trust-check", "--align", "a.json"))
        self.assertIn("give at least one check", self.fails("trust-check"))
        self.assertIn("--average", self.fails("trust-check", "--frames-mean", "m.txt"))


if __name__ == "__main__":
    unittest.main()
