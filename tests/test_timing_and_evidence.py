"""Timing signs, phase interpolation, measurement evidence and verification.

Every fixture here is built from physics (a causal delay is phase
-360*f*tau, wrapped the way REW exports it), never from the implementation's
own sign conventions, so a convention error cannot hide behind a test that
shares it. These cases fail on 1.8.1 unless noted as guards."""

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

import measure  # noqa: E402
import tunelib  # noqa: E402


FREQS = measure.common_grid(20.0, 20000.0, 96)
LINEAR = np.arange(1, 8192) * (48000.0 / 16384.0)        # REW's linear FFT grid


def _wrap(deg):
    return (np.asarray(deg) + 180.0) % 360.0 - 180.0


def _late_deg(freqs, seconds):
    """Phase of a channel arriving `seconds` late, as REW exports it."""
    return _wrap(-360.0 * freqs * seconds)


def _lr4(freqs, fc, kind):
    s = 1j * freqs / fc
    bw2 = 1.0 / (s ** 2 + np.sqrt(2.0) * s + 1.0)
    return bw2 ** 2 if kind == "lp" else ((s ** 2) * bw2) ** 2


def _target():
    return measure.load_target(SCRIPTS.parent / "assets" / "default_incar_target.txt", FREQS)


def _export(path, freqs, spl, phase=None, header=("timing reference: Acoustic",)):
    rows = ["* %s" % h for h in header]
    if phase is None:
        rows += ["%.4f %.4f" % (f, s) for f, s in zip(freqs, spl)]
    else:
        rows += ["%.4f %.4f %.4f" % (f, s, p) for f, s, p in zip(freqs, spl, phase)]
    Path(path).write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(path)


def _complex_export(path, freqs, H, **kw):
    return _export(path, freqs, 20 * np.log10(np.abs(H) + 1e-12),
                   np.degrees(np.angle(H)), **kw)


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


# ------------------------------------------------------------------ timing sign
class TimingSignTests(unittest.TestCase):
    flat = 80.0 * np.ones_like(FREQS)
    zero = np.zeros_like(FREQS)

    def rows(self, left_late_s, right_late_s):
        return tunelib.band_itd_ild(FREQS, self.flat, self.flat,
                                    _late_deg(FREQS, left_late_s),
                                    _late_deg(FREQS, right_late_s))

    def test_left_leading_reads_positive_and_pulls_left(self):
        rows = self.rows(0.0, 300e-6)
        for r in rows:
            self.assertAlmostEqual(r["itd_us"], 300.0, delta=10.0, msg=r)
        self.assertTrue(all(b["side"] == "left" for b in tunelib.image_pull(rows)["bands"]))

    def test_right_leading_reads_negative_and_pulls_right(self):
        rows = self.rows(300e-6, 0.0)
        for r in rows:
            self.assertAlmostEqual(r["itd_us"], -300.0, delta=10.0, msg=r)
        self.assertTrue(all(b["side"] == "right" for b in tunelib.image_pull(rows)["bands"]))

    def test_swapping_channels_flips_the_sign(self):
        a = [r["itd_us"] for r in self.rows(0.0, 200e-6)]
        b = [r["itd_us"] for r in self.rows(200e-6, 0.0)]
        np.testing.assert_allclose(a, -np.asarray(b), atol=1.0)

    def test_equal_arrival_is_a_confident_zero_not_unusable(self):
        rows = self.rows(1.2e-3, 1.2e-3)       # both late by the same flight time
        for r in rows:
            self.assertAlmostEqual(r["itd_us"], 0.0, delta=5.0)
            self.assertGreaterEqual(r["itd_fit_quality"], 0.9, r)
        self.assertEqual(tunelib.image_pull(rows)["verdict"], "stable")

    def test_rhd_delaying_the_near_right_side_moves_the_image_left(self):
        # RHD driver's seat: the right (near) side arrives 0.5 ms early.
        before = tunelib.image_pull(self.rows(0.5e-3, 0.0))["mean_pull"]
        after = tunelib.image_pull(self.rows(0.5e-3, 0.5e-3))["mean_pull"]
        self.assertLess(before, -0.3)            # pulled right, toward the near side
        self.assertAlmostEqual(after, 0.0, delta=0.05)
        # centre_steering agrees: more far(left) lead = image further left
        plan = tunelib.centre_steering(self.rows(0.5e-3, 0.0), "right")
        trims = [o["near_side_trim_db"] for o in sorted(plan["options"],
                                                        key=lambda o: o["far_lead_ms"])]
        self.assertEqual(trims, sorted(trims, reverse=True))


# ------------------------------------------------------------------ phase interpolation
class PhaseInterpolationTests(unittest.TestCase):
    def test_wrap_midpoint_is_180_not_0(self):
        mid = measure.resample_phase(np.array([1000.0, 1100.0]), np.array([179.0, -179.0]),
                                     np.array([np.sqrt(1000.0 * 1100.0)]))
        self.assertAlmostEqual(abs(_wrap(mid[0])), 180.0, delta=0.5)

    def test_resampled_complex_matches_the_true_delay_across_grids(self):
        tau = 0.8e-3
        got = measure.resample_phase(LINEAR, _late_deg(LINEAR, tau), FREQS)
        want = -360.0 * FREQS * tau
        sel = (FREQS > LINEAR[0]) & (FREQS < 20000)
        np.testing.assert_allclose(got[sel] - got[sel][0], want[sel] - want[sel][0], atol=1.0)

    def test_a_null_jump_is_not_mistaken_for_aliasing(self):
        H = _lr4(FREQS, 2000.0, "lp") - _lr4(FREQS, 2000.0, "hp")
        self.assertTrue(measure.phase_step_check(FREQS, np.degrees(np.angle(H)))["ok"])

    def test_sustained_aliasing_sets_a_phase_limit(self):
        coarse = measure.common_grid(20.0, 20000.0, 24)
        chk = measure.phase_step_check(coarse, _late_deg(coarse, 5e-3))
        self.assertFalse(chk["ok"])
        self.assertLess(chk["first_bad_hz"], 5000.0)


class CrossCommandAgreementTests(CliCase):
    """analyze, junction and imaging must agree on the same physical captures."""

    def test_junction_and_imaging_read_the_same_delay_from_linear_grid_exports(self):
        tau = 0.4e-3
        lower = _lr4(LINEAR, 2000.0, "lp")
        upper = _lr4(LINEAR, 2000.0, "hp") * np.exp(-2j * np.pi * LINEAR * tau)
        lo = _complex_export(self.root / "lo.txt", LINEAR, lower)
        up = _complex_export(self.root / "up.txt", LINEAR, upper)
        j = self.cli("junction", "--lower", lo, "--upper", up, "--crossover", "2000")
        self.assertAlmostEqual(j["delay_consensus"]["recommended_extra_delay_lower_ms"],
                               0.4, delta=0.03, msg=j["delay_consensus"])

        left = _export(self.root / "l.txt", LINEAR, 80 + 0 * LINEAR, _late_deg(LINEAR, 0.0))
        right = _export(self.root / "r.txt", LINEAR, 80 + 0 * LINEAR, _late_deg(LINEAR, tau))
        im = self.cli("imaging", "--solo-l", left, "--solo-r", right)
        for b in im["bands"]:
            self.assertAlmostEqual(b["itd_us"], tau * 1e6, delta=10.0, msg=b)
            self.assertEqual(b["side"], "left")

    def test_analyze_crossover_confidence_survives_wrap_crossings(self):
        # Solos on a coarser grid than the analysis grid, so interpolation
        # lands between wrapped points; 5 ms wraps every 200 Hz.
        coarse = measure.common_grid(20.0, 20000.0, 48)
        tau = 5e-3
        A = np.ones_like(coarse) * 10 ** (50 / 20.0)
        B = 10 ** (50 / 20.0) * np.exp(-2j * np.pi * coarse * tau)
        a = _complex_export(self.root / "a.txt", coarse, A)
        b = _complex_export(self.root / "b.txt", coarse, B)
        true_sum = np.abs(10 ** (50 / 20.0) * (1 + np.exp(-2j * np.pi * FREQS * tau)))
        t = _export(self.root / "t.txt", FREQS, 20 * np.log10(true_sum + 1e-9))
        meas = _export(self.root / "m.txt", FREQS, 80 + _target())
        r = self.cli("analyze", "--measurement", meas, "--target", "default",
                     "--solo-a", a, "--solo-b", b, "--together", t,
                     "--pair-band", "300", "600")
        pconf = r["crossover_confidence"]["prediction_confidence"]
        self.assertTrue(pconf["usable_for_phase_decisions"], pconf)
        self.assertLess(pconf["rms_err_db"], 1.5, pconf)


# ------------------------------------------------------------------ evidence
class MeasurementEvidenceTests(CliCase):
    def test_no_timing_reference_refuses_relative_phase_work(self):
        hdr = ("timing reference: NONE -- no shared time base",)
        left = _export(self.root / "l.txt", FREQS, 80 + 0 * FREQS, _late_deg(FREQS, 0.0), header=hdr)
        right = _export(self.root / "r.txt", FREQS, 80 + 0 * FREQS, _late_deg(FREQS, 3e-4), header=hdr)
        im = self.cli("imaging", "--solo-l", left, "--solo-r", right)
        self.assertFalse(im["meta"]["phase_available"])
        self.assertTrue(any("no timing reference" in n for n in im["notes"]), im["notes"])
        err = self.cli("junction", "--lower", left, "--upper", right, "--crossover", "2000", ok=False)
        self.assertIn("no timing reference", err)

    def test_header_is_read_not_discarded(self):
        p = _export(self.root / "x.txt", FREQS, 80 + 0 * FREQS,
                    header=("REW API export: FL (abc)", "smoothing 1/48, unit SPL",
                            "timing reference: NONE -- no shared time base"))
        h = measure.read_export_header(p)
        self.assertIs(h["timing_reference"], False)
        self.assertEqual(h["smoothing"], "1/48")
        self.assertIs(h["unsmoothed"], False)
        q = _export(self.root / "y.txt", FREQS, 80 + 0 * FREQS, header=("Smoothing: None",))
        self.assertIs(measure.read_export_header(q)["unsmoothed"], True)
        self.assertIsNone(measure.read_export_header(q)["timing_reference"])

    def test_incomplete_phase_column_is_rejected(self):
        rows = ["%.3f 80.0 %s" % (f, "-10.0" if i % 7 else "") for i, f in enumerate(FREQS)]
        p = self.root / "holes.txt"
        p.write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "phase column is incomplete"):
            measure.load_text_export(str(p))

    def test_out_of_range_bins_are_not_data(self):
        band = (FREQS >= 200) & (FREQS <= 2000)
        spl = (80 + _target() + tunelib.peaking_db(FREQS, 600.0, 2.0, 6.0))[band]
        p = _export(self.root / "narrow.txt", FREQS[band], spl)
        a = self.cli("analyze", "--measurement", p, "--target", "default")
        lo, hi = a["meta"]["measured_range_hz"]
        self.assertGreaterEqual(lo, 199.0)
        self.assertLessEqual(hi, 2001.0)
        for r in a["deviation_regions"]:
            self.assertTrue(lo <= r["f_lo"] and r["f_hi"] <= hi, r)
        pr = self.cli("propose", "--measurement", p, "--target", "default")
        self.assertGreaterEqual(pr["meta"]["fit_band_hz"][0], 199.0)
        self.assertLessEqual(pr["meta"]["fit_band_hz"][1], 2001.0)
        for b in pr["proposal"]["bands"]:
            self.assertTrue(200 <= b["f_hz"] <= 2000, b)

    def test_propose_inherits_the_gate_trust_floor(self):
        spl = 80 + _target() + tunelib.peaking_db(FREQS, 65.0, 2.0, -6.0) \
            + tunelib.peaking_db(FREQS, 1500.0, 2.0, 5.0)
        p = _export(self.root / "gated.txt", FREQS, spl)
        ungated = self.cli("propose", "--measurement", p, "--target", "default")
        self.assertTrue(any(b["f_hz"] < 500 for b in ungated["proposal"]["bands"]))
        gated = self.cli("propose", "--measurement", p, "--target", "default", "--gate-ms", "2")
        self.assertEqual(gated["meta"]["gate_floor_hz"], 500.0)
        self.assertTrue(gated["proposal"]["bands"])
        for b in gated["proposal"]["bands"] + gated["proposal"]["rejected"]:
            self.assertGreaterEqual(b["f_hz"], 500.0, b)

    def test_three_copies_of_one_trace_are_one_position(self):
        p = _export(self.root / "p.txt", FREQS, 80 + _target())
        copies = []
        for i in range(3):
            c = self.root / ("copy%d.txt" % i)
            c.write_text(Path(p).read_text(encoding="utf-8"), encoding="utf-8")
            copies.append(str(c))
        r = self.cli("analyze", "--positions", *copies, "--target", "default")
        self.assertEqual(r["meta"]["positions_used"], 1)
        self.assertEqual(r["meta"]["deviation_source"], "single position")
        self.assertEqual(len(r["meta"]["duplicate_positions"]), 1)
        self.assertNotIn("spatial_consistency", r)


# ------------------------------------------------------------------ verification
class VerificationTests(unittest.TestCase):
    rng = np.random.default_rng(7)
    before = 80 + rng.normal(0, 0.3, len(FREQS))

    def verdict(self, after, bands, **kw):
        r = tunelib.predicted_vs_measured(FREQS, self.before, after, bands, **kw)
        return r, [b["verdict"] for b in r["bands"]]

    def test_unchanged_remeasure_never_confirms_a_resolved_change(self):
        for band in [(1000.0, 1.0, -1.5), (300.0, 2.0, -3.0), (4000.0, 0.7, -1.0)]:
            r, v = self.verdict(self.before.copy(), [band])
            self.assertNotIn("confirmed", v, (band, r))
            self.assertFalse(r["trace_changed"])

    def test_an_applied_filter_with_capture_noise_confirms(self):
        band = (1000.0, 1.0, -1.5)
        after = (self.before + tunelib.cascade_db(FREQS, [band]) + 0.8
                 + self.rng.normal(0, 0.3, len(FREQS)))
        r, v = self.verdict(after, [band])
        self.assertEqual(v, ["confirmed"], r)
        self.assertAlmostEqual(r["level_offset_db"], 0.8, delta=0.2)

    def test_a_change_below_resolution_is_inconclusive(self):
        band = (1000.0, 1.0, -0.4)
        after = self.before + tunelib.cascade_db(FREQS, [band])
        _r, v = self.verdict(after, [band])
        self.assertEqual(v, ["inconclusive"])

    def test_removing_a_filter_predicts_its_inverse(self):
        old = [(500.0, 2.0, -4.0)]
        after = self.before - tunelib.cascade_db(FREQS, old)       # the cut is gone
        r, v = self.verdict(after, [], old_bands=old)
        self.assertEqual(v, ["confirmed"], r)
        self.assertGreater(r["bands"][0]["predicted_change_db"], 2.0)
        self.assertEqual(r["bands"][0]["change"], "removed")

    def test_an_edited_filter_predicts_the_difference_not_another_cascade(self):
        old, new = [(500.0, 2.0, -4.0)], [(500.0, 2.0, -2.0)]
        after = (self.before + tunelib.cascade_db(FREQS, new)
                 - tunelib.cascade_db(FREQS, old))
        r, _v = self.verdict(after, new, old_bands=old)
        added = [b for b in r["bands"] if b["change"] == "added"][0]
        self.assertGreater(added["predicted_change_db"], 0.8)       # +2 dB less cut
        self.assertEqual(added["verdict"], "confirmed", r)

    def test_an_unchanged_bank_predicts_nothing(self):
        bank = [(500.0, 2.0, -4.0), (2000.0, 1.0, -2.0)]
        r, v = self.verdict(self.before.copy(), bank, old_bands=bank)
        self.assertEqual(v, [])
        self.assertFalse(r["trace_changed"])


if __name__ == "__main__":
    unittest.main()
