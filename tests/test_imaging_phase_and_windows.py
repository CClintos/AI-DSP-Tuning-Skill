"""Phantom-image model, centre steering, Helix phase control, junction phase
score, junction sum loss, and the direct-sound (frequency-dependent) window."""

import sys
import unittest
from pathlib import Path

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "helix-rew-tuner" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import decay  # noqa: E402
import measure  # noqa: E402
import tunelib  # noqa: E402


FREQS = measure.common_grid(20.0, 20000.0, 96)


def _row(ild_db, ictd_us, quality=1.0, lo=630.0, hi=1250.0):
    return {"f_lo": lo, "f_hi": hi, "bins": 50, "ild_db": ild_db,
            "itd_us": ictd_us, "itd_fit_quality": quality}


class PhantomImageScalingTests(unittest.TestCase):
    """Inter-CHANNEL cues between two loudspeakers, not interaural ones:
    about 1 ms or about 15-17 dB moves a phantom image fully to one speaker
    (Lee & Rumsey 2013), and the two cues trade additively."""

    def test_one_millisecond_alone_is_a_full_shift(self):
        pull = tunelib.image_pull([_row(0.0, 1000.0)])
        self.assertAlmostEqual(pull["bands"][0]["pull"], 1.0, places=2)

    def test_650_us_is_not_a_full_shift_between_loudspeakers(self):
        pull = tunelib.image_pull([_row(0.0, 650.0)])
        self.assertLess(pull["bands"][0]["pull"], 0.75)

    def test_sixteen_db_alone_is_a_full_shift(self):
        pull = tunelib.image_pull([_row(-16.0, 0.0)])
        self.assertAlmostEqual(pull["bands"][0]["pull"], -1.0, places=2)

    def test_time_and_level_trade_additively_at_low_frequency_too(self):
        low = tunelib.image_pull([_row(4.0, 250.0, lo=160.0, hi=315.0)])
        self.assertAlmostEqual(low["bands"][0]["pull"], 0.5, places=2)

    def test_level_difference_still_moves_the_image_in_the_bass(self):
        """Blumlein: between loudspeakers, a level difference becomes a time
        difference at the ears, so ICLD is fully effective at low frequency."""
        low = tunelib.image_pull([_row(8.0, 0.0, lo=160.0, hi=315.0)])
        self.assertAlmostEqual(low["bands"][0]["pull"], 0.5, places=2)


class CentreSteeringTests(unittest.TestCase):
    def setUp(self):
        # Right-hand-drive seat: the right (near) side arrives 0.2 ms early and
        # 6 dB loud in every band, so the image collapses toward the right door.
        self.rows = [_row(-6.0, -200.0, lo=lo, hi=hi)
                     for lo, hi in ((315, 630), (630, 1250), (1250, 2500), (2500, 5000))]

    def test_level_only_option_needs_the_whole_equivalent_trim(self):
        plan = tunelib.centre_steering(self.rows, near_side="right")
        level_only = [o for o in plan["options"] if o["far_lead_ms"] == 0.0][0]
        self.assertAlmostEqual(level_only["near_side_trim_db"], 6.0 + 0.2 * 16.0, delta=0.05)
        self.assertAlmostEqual(level_only["mean_pull_after"], 0.0, delta=0.01)

    def test_a_far_side_lead_buys_the_same_centre_for_less_level(self):
        plan = tunelib.centre_steering(self.rows, near_side="right")
        trims = [o["near_side_trim_db"] for o in
                 sorted(plan["options"], key=lambda o: o["far_lead_ms"])]
        self.assertTrue(all(b < a for a, b in zip(trims, trims[1:])))

    def test_recommendation_stays_inside_the_fragile_time_zone(self):
        plan = tunelib.centre_steering(self.rows, near_side="right")
        self.assertLessEqual(plan["recommended"]["far_lead_ms"], 0.3)
        self.assertIn("head", plan["robustness_note"])

    def test_left_hand_drive_mirrors_the_signs(self):
        mirrored = [dict(r, ild_db=-r["ild_db"], itd_us=-r["itd_us"]) for r in self.rows]
        plan = tunelib.centre_steering(mirrored, near_side="left")
        level_only = [o for o in plan["options"] if o["far_lead_ms"] == 0.0][0]
        self.assertAlmostEqual(level_only["near_side_trim_db"], 9.2, delta=0.05)

    def test_bands_without_a_usable_time_cue_are_steered_by_level_only(self):
        rows = [_row(-6.0, None, quality=None)]
        plan = tunelib.centre_steering(rows, near_side="right")
        self.assertEqual([o["far_lead_ms"] for o in plan["options"]], [0.0])
        self.assertAlmostEqual(plan["options"][0]["near_side_trim_db"], 6.0, delta=0.05)


class HelixPhaseControlTests(unittest.TestCase):
    """Measured on a DSP ULTRA S by Resonalyze (issue #88): one RBJ AP2, Q=1,
    whose phase at the channel's configured crossover equals the dialled
    angle; 64 steps of 5.625 deg; corner capped at 3/16 of the rate."""

    def test_reproduces_the_bench_corners_at_96k(self):
        for angle, expected in ((90.0, 7977.0), (180.0, 5000.0), (270.0, 3107.0)):
            got = tunelib.helix_phase_rotation(angle, 5000.0, 96000.0)
            self.assertAlmostEqual(got["corner_hz"], expected, delta=expected * 0.003)
            self.assertEqual(got["q"], 1.0)

    def test_same_angle_differs_at_48k(self):
        got = tunelib.helix_phase_rotation(90.0, 5000.0, 48000.0)
        self.assertAlmostEqual(got["corner_hz"], 7674.0, delta=25.0)

    def test_snaps_to_the_64_step_grid(self):
        got = tunelib.helix_phase_rotation(50.0, 500.0, 96000.0)
        self.assertAlmostEqual(got["angle_deg"], 50.625, places=3)

    def test_small_angle_at_a_high_crossover_is_capped(self):
        got = tunelib.helix_phase_rotation(5.625, 5000.0, 96000.0)
        self.assertTrue(got["capped"])
        self.assertAlmostEqual(got["corner_hz"], 18000.0, delta=1.0)
        self.assertGreater(got["delivered_deg"], 25.0)

    def test_zero_is_transparent(self):
        got = tunelib.helix_phase_rotation(0.0, 2000.0, 96000.0)
        self.assertIsNone(got["corner_hz"])
        H = tunelib.helix_phase_rotation_H(FREQS, 0.0, 2000.0, 96000.0)
        self.assertTrue(np.allclose(H, 1.0))

    def test_response_delivers_the_angle_at_the_reference(self):
        H = tunelib.helix_phase_rotation_H(FREQS, 90.0, 2000.0, 96000.0)
        i = int(np.argmin(np.abs(FREQS - 2000.0)))
        lag = (-np.degrees(np.angle(H[i]))) % 360.0
        self.assertAlmostEqual(lag, 90.0, delta=1.5)
        self.assertTrue(np.allclose(np.abs(H), 1.0))


def _lr4(freqs, fc, kind):
    s = 1j * freqs / fc
    bw2 = 1.0 / (s ** 2 + np.sqrt(2.0) * s + 1.0)
    if kind == "lp":
        return bw2 ** 2
    hp = (s ** 2) * bw2
    return hp ** 2


class JunctionToolsTests(unittest.TestCase):
    def setUp(self):
        self.lower = _lr4(FREQS, 2000.0, "lp")
        self.upper = _lr4(FREQS, 2000.0, "hp")

    def test_aligned_lr4_pair_scores_near_one(self):
        r = tunelib.junction_phase_score(FREQS, self.lower, self.upper, 2000.0)
        self.assertGreater(r["current_score"], 0.97)
        self.assertFalse(r["recommend_invert"])
        self.assertLess(abs(r["best_extra_delay_ms"]), 0.02)

    def test_finds_the_delay_the_upper_driver_is_late_by(self):
        late = self.upper * np.exp(-2j * np.pi * FREQS * 0.10e-3)
        r = tunelib.junction_phase_score(FREQS, self.lower, late, 2000.0)
        self.assertAlmostEqual(r["best_extra_delay_ms"], 0.10, delta=0.01)
        self.assertGreater(r["best_score"], r["current_score"])

    def test_recommends_a_flip_only_for_a_real_inversion(self):
        r = tunelib.junction_phase_score(FREQS, self.lower, -self.upper, 2000.0)
        self.assertTrue(r["recommend_invert"])
        self.assertLess(r["current_score"], -0.9)
        self.assertGreater(r["lobe_margin"], 0.0)

    def test_sum_loss_is_zero_in_phase_and_deep_when_cancelling(self):
        flat = np.ones_like(FREQS, dtype=complex)
        same = tunelib.junction_sum_loss(FREQS, flat, flat, (1000.0, 4000.0))
        self.assertAlmostEqual(same["average_db"], 0.0, places=6)
        opposite = tunelib.junction_sum_loss(FREQS, flat, -0.9 * flat, (1000.0, 4000.0))
        self.assertLess(opposite["dip_db"], -20.0)

    def test_sum_loss_of_aligned_lr4_is_small(self):
        r = tunelib.junction_sum_loss(FREQS, self.lower, self.upper, (1000.0, 4000.0))
        self.assertGreater(r["average_db"], -0.5)


class DirectSoundWindowTests(unittest.TestCase):
    """8 cycles per frequency from the arrival keeps a 3 ms reflection OUT of
    the treble reading and IN the bass one, like the ear's precedence window."""

    def setUp(self):
        self.fs = 48000
        n = int(0.5 * self.fs)
        self.t0 = 0.004
        ir = np.zeros(n)
        i0 = int(round(self.t0 * self.fs))
        ir[i0] = 1.0
        ir[i0 + int(round(0.003 * self.fs))] = 0.5        # -6 dB, 3 ms later
        self.ir = ir

    def test_treble_excludes_the_reflection_bass_includes_it(self):
        f = np.array([150.0, 160.0, 4000.0, 4166.7])
        spl, _phase = decay.fdw_response(self.ir, self.fs, f, cycles=8.0)
        treble_ripple = abs(spl[2] - spl[3])
        self.assertLess(treble_ripple, 0.5)
        full = np.fft.rfft(self.ir)
        full_db = 20 * np.log10(np.abs(full[[int(round(x * len(self.ir) / self.fs))
                                             for x in (4000.0, 4166.7)]]))
        self.assertGreater(abs(full_db[0] - full_db[1]), 6.0)

    def test_phase_keeps_the_absolute_arrival_time(self):
        f = np.arange(1000.0, 8000.0, 25.0)      # fine enough to unwrap 4 ms
        _spl, phase = decay.fdw_response(self.ir, self.fs, f, cycles=8.0)
        slope = np.polyfit(2 * np.pi * f, np.unwrap(np.radians(phase)), 1)[0]
        self.assertAlmostEqual(-slope, self.t0, delta=2e-5)



class PipelineCommandTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def _export(self, name, H):
        path = self.root / name
        rows = ["* Freq(Hz) SPL(dB) Phase(degrees)"]
        rows += ["%.4f %.4f %.4f" % (f, 80 + 20 * np.log10(abs(h) + 1e-12),
                                     np.degrees(np.angle(h))) for f, h in zip(FREQS, H)]
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return str(path)

    def _run(self, *args):
        import json
        import subprocess
        run = subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), *args],
                             text=True, capture_output=True, check=False)
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        return json.loads(run.stdout)

    def test_imaging_reports_centre_steering_for_the_near_side(self):
        flat = np.ones_like(FREQS, dtype=complex)
        left = self._export("L.txt", flat)
        right = self._export("R.txt", 2.0 * flat * np.exp(-2j * np.pi * FREQS * -0.2e-3))
        report = self._run("imaging", "--solo-l", left, "--solo-r", right,
                           "--near-side", "right")
        self.assertIn("centre_steering", report)
        rec = report["centre_steering"]["recommended"]
        self.assertGreaterEqual(rec["near_side_trim_db"], 0.0)

    def test_junction_command_reports_score_and_sum_loss(self):
        lower = self._export("mid.txt", _lr4(FREQS, 2000.0, "lp"))
        upper = self._export("tw.txt", -_lr4(FREQS, 2000.0, "hp"))
        report = self._run("junction", "--lower", lower, "--upper", upper,
                           "--crossover", "2000")
        self.assertTrue(report["phase"]["recommend_invert"])
        self.assertIn("average_db", report["sum_loss"])
        self.assertIn("window", report["meta"])


if __name__ == "__main__":
    unittest.main()
