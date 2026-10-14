"""Refining an existing tune, level-matched blind A/B, advisory crossover
what-ifs, and the bass/handover checks that judge fronts and sub together."""

import hashlib
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
FS = 96000.0


def _channel(bank, vol="1.0"):
    """One mid channel: HP 80 / LP 3000 LR24, the given PEQ bank, two free slots."""
    fils = ['<Fil T="16" F="80.00" Q="0.7" G="-24" dF="80" FN="1" I="0" FilBy="0"/>',
            '<Fil T="15" F="3000.00" Q="0.7" G="-24" dF="3000" FN="2" I="0" FilBy="0"/>']
    for k, (F, Q, G) in enumerate(bank):
        fils.append('<Fil T="17" F="%.2f" Q="%g" G="%g" dF="%d" FN="%d" I="0" FilBy="0"/>'
                    % (F, Q, G, int(F), 3 + k))
    fils += ['<Fil T="1" F="200.00" Q="1" G="0" dF="200" FN="10" I="0" FilBy="0"/>',
             '<Fil T="1" F="800.00" Q="1" G="0" dF="800" FN="11" I="0" FilBy="0"/>',
             '<Fil T="1" F="25.00" Q="1" G="0" dF="25" FN="12" I="0" FilBy="0"/>',
             '<Fil T="1" F="20000.00" Q="1" G="0" dF="20000" FN="13" I="0" FilBy="0"/>']
    return ('<OC ON="1" CINV="0">' + "".join(fils) + '<Vol T="15" L="%s" i="0"/>' % vol
            + '<T PM="1" P="0" T="0"/></OC>')


def _afpx(path, banks):
    afpx._encode_unchecked("<ATF>" + "".join(_channel(b) for b in banks) + "</ATF>", str(path))
    return str(path)


def _target():
    return measure.load_target(SCRIPTS.parent / "assets" / "default_incar_target.txt", FREQS)


def _export(path, spl, phase=None):
    rows = ["* timing reference: Acoustic"]
    if phase is None:
        rows += ["%.4f %.4f" % (f, s) for f, s in zip(FREQS, spl)]
    else:
        rows += ["%.4f %.4f %.4f" % (f, s, p) for f, s, p in zip(FREQS, spl, phase)]
    Path(path).write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(path)


def _cexport(path, H):
    return _export(path, 20 * np.log10(np.abs(H) + 1e-12), np.degrees(np.angle(H)))


class CliCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def cli(self, *args, ok=True):
        run = subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), *args],
                             text=True, capture_output=True, check=False, cwd=self.root)
        if not ok:
            self.assertNotEqual(0, run.returncode, run.stdout)
            return run.stderr
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        return json.loads(run.stdout)

    def positions(self, room, bank, n=3, seed=4):
        rng = np.random.default_rng(seed)
        paths = []
        for i in range(n):
            spl = (80 + _target() + room + tunelib.cascade_db(FREQS, bank, fs=FS)
                   + rng.normal(0, 0.3, len(FREQS)))
            paths.append(_export(self.root / ("pos%d.txt" % i), spl))
        return paths


# ------------------------------------------------------------------ refine
class RefineTests(CliCase):
    good = (500.0, 2.0, -5.0)
    harmful = (1000.0, 2.0, -4.0)            # a cut where the car has no peak

    def test_removes_a_harmful_filter_keeps_a_good_one_and_predicts_new_minus_old(self):
        bank = [self.good, self.harmful]
        tune = _afpx(self.root / "tune.afpx", [bank, bank])
        room = tunelib.peaking_db(FREQS, 500.0, 2.0, 5.0)
        r = self.cli("refine", "--afpx", tune, "--channels", "0", "1", "--dsp-rate", "96000",
                     "--positions", *self.positions(room, bank), "--target", "default")
        self.assertEqual([e["action"] for e in r["edits"]], ["remove"], r["edits"])
        self.assertEqual(r["edits"][0]["old"], list(self.harmful))
        self.assertLess(r["refined"]["mean_score_db"], r["baseline"]["mean_score_db"] - 0.5)
        self.assertEqual({e["channel"] for e in r["plan_edits"]}, {0, 1})
        self.assertTrue(all(e["G"] == 0.0 for e in r["plan_edits"]))
        # removing a cut makes it louder: the comparison must say so
        self.assertGreater(r["comparison"]["loudness_change_db"], 0.0)
        self.assertEqual(r["comparison"]["louder_version"], "refined")
        self.assertEqual(r["verify_with"]["old_bands"], [list(self.good), list(self.harmful)])

        # and the plan edits it emits go straight through the verified write path
        plan = self.cli("plan", "--source", tune, "--output", str(self.root / "out.afpx"))
        plan["edits"] = r["plan_edits"]
        plan["confirmations"] = {e["id"]: True for e in r["plan_edits"]}
        (self.root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        self.cli("apply", "--plan", str(self.root / "plan.json"))
        out = afpx.channels(afpx.decode(str(self.root / "out.afpx")))
        for ch in out:
            self.assertEqual(sorted(ch["peqs"]), [self.good])

    def test_a_bank_that_already_earns_its_place_is_left_alone(self):
        bank = [self.good]
        tune = _afpx(self.root / "tune.afpx", [bank])
        room = tunelib.peaking_db(FREQS, 500.0, 2.0, 5.0)
        r = self.cli("refine", "--afpx", tune, "--channels", "0", "--dsp-rate", "96000",
                     "--positions", *self.positions(room, bank), "--target", "default")
        self.assertEqual(r["edits"], [])
        self.assertIsNone(r["comparison"])
        self.assertTrue(any("already earns its place" in n for n in r["notes"]))

    def test_an_over_cut_is_relaxed_in_place_not_stacked(self):
        bank = [(500.0, 2.0, -6.0)]
        tune = _afpx(self.root / "tune.afpx", [bank])
        room = tunelib.peaking_db(FREQS, 500.0, 2.0, 3.0)
        r = self.cli("refine", "--afpx", tune, "--channels", "0", "--dsp-rate", "96000",
                     "--positions", *self.positions(room, bank), "--target", "default")
        self.assertEqual(len(r["edits"]), 1, r["edits"])
        self.assertIn(r["edits"][0]["action"], ("relax", "refit"))
        self.assertAlmostEqual(r["edits"][0]["new"][2], -3.0, delta=0.75)
        self.assertNotIn("type_code", r["plan_edits"][0])      # same slot, not a new band

    def test_unequal_banks_cannot_share_one_measurement(self):
        tune = _afpx(self.root / "tune.afpx", [[self.good], [self.harmful]])
        err = self.cli("refine", "--afpx", tune, "--channels", "0", "1", "--dsp-rate", "96000",
                       "--positions", *self.positions(0 * FREQS, []), "--target", "default",
                       ok=False)
        self.assertIn("different PEQ banks", err)


# ------------------------------------------------------------------ A/B
class BlindAbTests(CliCase):
    def setUp(self):
        super().setUp()
        self.a = _afpx(self.root / "current.afpx", [[(500.0, 2.0, -5.0)], [(500.0, 2.0, -5.0)]])
        self.b = _afpx(self.root / "refined.afpx", [[(500.0, 2.0, -3.0)], [(500.0, 2.0, -3.0)]])

    def test_the_louder_copy_is_trimmed_only_after_confirmation(self):
        err = self.cli("ab-make", "--a", self.a, "--b", self.b, "--loudness-db", "1.5",
                       "--out-dir", str(self.root / "ab"), ok=False)
        self.assertIn("--confirm-trim", err)
        r = self.cli("ab-make", "--a", self.a, "--b", self.b, "--loudness-db", "1.5",
                     "--out-dir", str(self.root / "ab"), "--confirm-trim", "--seed", "3")
        key = json.loads(Path(r["key"]).read_text(encoding="utf-8"))
        by_role = {v["is"]: lab for lab, v in key["labels"].items()}
        b_file = Path(r["files"][by_role["B"]])
        a_file = Path(r["files"][by_role["A"]])
        self.assertEqual(a_file.read_bytes(), Path(self.a).read_bytes())
        levels = afpx.read_output_levels(afpx.decode(str(b_file)))
        for lvl in levels.values():
            self.assertAlmostEqual(lvl["db"], -1.5, delta=0.01)
        self.assertEqual(Path(self.b).read_bytes(),
                         Path(self.root / "refined.afpx").read_bytes())   # original untouched

        # a consistent preference for B is revealed and logged
        choices = [by_role["B"]] * 6
        res = self.cli("ab-result", "--key", r["key"], "--choices", *choices)
        self.assertEqual(res["preferred"], "B")
        self.assertLess(res["p_chance"], 0.05)
        self.assertTrue(Path(res["log"]).exists())

    def test_a_split_vote_is_no_preference(self):
        r = self.cli("ab-make", "--a", self.a, "--b", self.b, "--loudness-db", "0.05",
                     "--out-dir", str(self.root / "ab2"), "--seed", "1")
        res = self.cli("ab-result", "--key", r["key"], "--choices", "X", "Y", "X", "Y", "same")
        self.assertIsNone(res["preferred"])
        self.assertIn("no reliable preference", res["verdict"])
        self.assertIn("caution", res)


class LoudnessTests(unittest.TestCase):
    def test_a_uniform_lift_is_that_lift(self):
        base = 80 + _target()
        self.assertAlmostEqual(tunelib.loudness_change_db(FREQS, base, base + 2.0), 2.0, places=6)

    def test_a_cut_makes_it_quieter(self):
        base = 80 + _target()
        cut = base + tunelib.peaking_db(FREQS, 1000.0, 1.0, -4.0)
        self.assertLess(tunelib.loudness_change_db(FREQS, base, cut), -0.3)


# ------------------------------------------------------------------ crossover what-if
def _lr(kind, fc, slope=24):
    return tunelib.crossover_H(FREQS, kind, "LR", slope, fc, fs=FS)


class CrossoverModelTests(unittest.TestCase):
    def test_section_shapes(self):
        i = int(np.argmin(np.abs(FREQS - 2500.0)))
        lr = _lr("hp", FREQS[i])
        bw = tunelib.crossover_H(FREQS, "hp", "BW", 12, FREQS[i], fs=FS)
        self.assertAlmostEqual(20 * np.log10(abs(lr[i])), -6.02, delta=0.05)
        self.assertAlmostEqual(20 * np.log10(abs(bw[i])), -3.01, delta=0.05)
        with self.assertRaises(ValueError):
            tunelib.crossover_H(FREQS, "hp", "LR", 18, 2500.0, fs=FS)
        with self.assertRaisesRegex(ValueError, "unverified"):
            tunelib.crossover_H(FREQS, "hp", "Bessel", 24, 2500.0, fs=FS)

    def test_an_unchanged_crossover_changes_nothing(self):
        same = {"family": "LR", "slope_db_oct": 24, "hz": 2500}
        H, lift = tunelib.crossover_change_H(FREQS, {"kind": "hp", "from": same, "to": same})
        np.testing.assert_allclose(H, 1.0, atol=1e-9)
        self.assertAlmostEqual(lift, 0.0, places=6)


class CrossoverProbeTests(CliCase):
    """Tweeters measured through a 4 kHz high-pass against mids low-passed at
    2.5 kHz leave a hole; moving the high-pass down to 2.5 kHz closes it."""

    def spec(self, variants, positions=None, pairs=None):
        drivers = positions or [{
            "mid_L": _cexport(self.root / "midL.txt", _lr("lp", 2500.0)),
            "tw_L": _cexport(self.root / "twL.txt", _lr("hp", 4000.0)),
            "mid_R": _cexport(self.root / "midR.txt", _lr("lp", 2500.0)),
            "tw_R": _cexport(self.root / "twR.txt", _lr("hp", 4000.0))}]
        spec = {"dsp_sample_rate_hz": 96000,
                "junctions": [{"lower": "mid_L", "upper": "tw_L", "crossover_hz": 2500},
                              {"lower": "mid_R", "upper": "tw_R", "crossover_hz": 2500}],
                "variants": variants}
        if positions:
            spec["positions"] = drivers
        else:
            spec["drivers"] = drivers[0]
        if pairs:
            spec["pairs"] = pairs
        path = self.root / "spec.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        return str(path)

    move = {"kind": "hp", "from": {"family": "LR", "slope_db_oct": 24, "hz": 4000},
            "to": {"family": "LR", "slope_db_oct": 24, "hz": 2500}}

    def test_moving_the_tweeter_high_pass_closes_the_hole_on_both_sides(self):
        both = {"name": "tweeters to 2.5 kHz",
                "changes": {"tw_L": {"crossover": [self.move]}, "tw_R": {"crossover": [self.move]}}}
        r = self.cli("probe", "--spec", self.spec([both], pairs=[["tw_L", "tw_R"]]))
        v = r["variants"][1]
        self.assertEqual(v["recommendation"], "candidate", v["verdict"])
        self.assertTrue(v["crossover_advisory"])
        self.assertTrue(any("ADVISORY" in n for n in r["notes"]))
        for row in v["junctions"]:
            self.assertGreater(row["delta_sum_loss_db"], 0.0)

    def test_a_better_handover_that_unbalances_left_and_right_is_a_tradeoff(self):
        one = {"name": "left tweeter only", "changes": {"tw_L": {"crossover": [self.move]}}}
        r = self.cli("probe", "--spec", self.spec([one], pairs=[["tw_L", "tw_R"]]))
        v = r["variants"][1]
        self.assertEqual(v["recommendation"], "tradeoff", v)
        self.assertGreater(v["lr_balance"][0]["delta_db"], 0.5)

    def test_positions_must_all_agree(self):
        def pos(tag, tw_gain):
            return {"mid_L": _cexport(self.root / ("mL%s.txt" % tag), _lr("lp", 2500.0)),
                    "tw_L": _cexport(self.root / ("tL%s.txt" % tag), tw_gain * _lr("hp", 4000.0)),
                    "mid_R": _cexport(self.root / ("mR%s.txt" % tag), _lr("lp", 2500.0)),
                    "tw_R": _cexport(self.root / ("tR%s.txt" % tag), tw_gain * _lr("hp", 4000.0))}
        both = {"name": "tweeters to 2.5 kHz",
                "changes": {"tw_L": {"crossover": [self.move]}, "tw_R": {"crossover": [self.move]}}}
        r = self.cli("probe", "--spec", self.spec([both], positions=[pos("a", 1.0), pos("b", 0.8)]))
        self.assertEqual(r["meta"]["positions"], 2)
        self.assertEqual(r["robust"][1]["robust_recommendation"], "candidate", r["robust"])

    def test_aggregate_rejects_what_any_position_rejects(self):
        mk = lambda rec: [{"name": "baseline", "recommendation": "reference"},
                          {"name": "v", "recommendation": rec}]
        agg = tunelib.aggregate_probe_positions([mk("candidate"), mk("candidate"), mk("reject")])
        self.assertEqual(agg[1]["robust_recommendation"], "reject")
        agg = tunelib.aggregate_probe_positions([mk("candidate"), mk("no gain")])
        self.assertEqual(agg[1]["robust_recommendation"], "candidate")


# ------------------------------------------------------------------ bass
class BassBalanceTests(CliCase):
    def test_a_hot_sub_region_is_called_a_level_question(self):
        heavy = 80 + _target() + tunelib.low_shelf_db(FREQS, 70.0, 0.7, 6.0)
        p = _export(self.root / "heavy.txt", heavy)
        a = self.cli("analyze", "--measurement", p, "--target", "default")
        self.assertEqual(a["bass_balance"]["verdict"], "bass_heavy")
        self.assertTrue(any("LEVEL question" in n for n in a["notes"]), a["notes"])
        pr = self.cli("propose", "--measurement", p, "--target", "default")
        self.assertTrue(any("below the fit band" in n for n in pr["notes"]), pr["notes"])
        self.assertEqual(pr["bass_balance"]["verdict"], "bass_heavy")

    def test_a_balanced_low_end_is_quiet(self):
        p = _export(self.root / "ok.txt", 80 + _target())
        a = self.cli("analyze", "--measurement", p, "--target", "default")
        self.assertEqual(a["bass_balance"]["verdict"], "balanced")
        self.assertFalse(any("LEVEL question" in n for n in a["notes"]))


if __name__ == "__main__":
    unittest.main()
