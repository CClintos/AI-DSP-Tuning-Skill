"""The probe engine: ask deterministic code "what would this change do?" across
every junction it touches, instead of estimating it (Resonalyze's probes)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "helix-rew-tuner" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import measure  # noqa: E402
import tunelib  # noqa: E402


FREQS = measure.common_grid(20.0, 20000.0, 96)


def _lr4(fc, kind):
    s = 1j * FREQS / fc
    bw2 = 1.0 / (s ** 2 + np.sqrt(2.0) * s + 1.0)
    return bw2 ** 2 if kind == "lp" else ((s ** 2) * bw2) ** 2


def _three_way():
    woofer = _lr4(300.0, "lp")
    mid = _lr4(300.0, "hp") * _lr4(3000.0, "lp")
    tweeter = _lr4(3000.0, "hp")
    drivers = {"woofer": woofer, "mid": mid, "tweeter": tweeter}
    junctions = [("woofer", "mid", 300.0), ("mid", "tweeter", 3000.0)]
    return drivers, junctions


class ChainResponseTests(unittest.TestCase):
    def test_delay_invert_and_gain(self):
        H = tunelib.chain_response(FREQS, delay_ms=0.1, invert=True, gain_db=-6.0)
        expected = -10 ** (-6 / 20) * np.exp(-2j * np.pi * FREQS * 1e-4)
        self.assertTrue(np.allclose(H, expected))

    def test_peq_matches_the_magnitude_model_and_carries_phase(self):
        H = tunelib.chain_response(FREQS, peq=[(1000.0, 2.0, -6.0)])
        self.assertTrue(np.allclose(20 * np.log10(np.abs(H)),
                                    tunelib.peaking_db(FREQS, 1000.0, 2.0, -6.0), atol=1e-9))
        self.assertGreater(np.max(np.abs(np.angle(H))), 0.1)

    def test_phase_control_and_allpass(self):
        H = tunelib.chain_response(FREQS, phase_deg=90.0, phase_reference_hz=2600.0,
                                   allpass=[(400.0, 0.7, 2)])
        expected = (tunelib.helix_phase_rotation_H(FREQS, 90.0, 2600.0, tunelib.FS)
                    * tunelib.allpass_H(FREQS, 400.0, 0.7, order=2))
        self.assertTrue(np.allclose(H, expected))

    def test_phase_control_needs_its_reference(self):
        with self.assertRaises(ValueError):
            tunelib.chain_response(FREQS, phase_deg=90.0)

    def test_unknown_change_is_refused(self):
        drivers, junctions = _three_way()
        with self.assertRaisesRegex(ValueError, "unknown"):
            tunelib.probe_variants(FREQS, drivers, junctions,
                                   [{"name": "x", "changes": {"mid": {"crossover_hz": 500}}}])


class ProbeVariantTests(unittest.TestCase):
    def setUp(self):
        self.drivers, self.junctions = _three_way()

    def test_baseline_comes_first_and_scores_an_aligned_system_high(self):
        out = tunelib.probe_variants(FREQS, self.drivers, self.junctions, [])
        self.assertEqual(out[0]["name"], "baseline")
        for j in out[0]["junctions"]:
            self.assertGreater(j["phase_score"], 0.95)

    def test_a_shared_channel_change_shows_up_at_both_of_its_junctions(self):
        out = tunelib.probe_variants(FREQS, self.drivers, self.junctions,
                                     [{"name": "mid +0.2 ms", "changes": {"mid": {"delay_ms": 0.2}}}])
        variant = out[1]
        self.assertEqual(sorted(variant["touched_junctions"]), ["mid-tweeter", "woofer-mid"])
        for j in variant["junctions"]:
            self.assertLess(j["delta_phase_score"], 0.0)
        self.assertIn("ALL", variant["verdict"])

    def test_an_untouched_junction_does_not_move(self):
        out = tunelib.probe_variants(FREQS, self.drivers, self.junctions,
                                     [{"name": "tweeter +0.05", "changes": {"tweeter": {"delay_ms": 0.05}}}])
        low = [j for j in out[1]["junctions"] if j["id"] == "woofer-mid"][0]
        self.assertEqual(low["delta_phase_score"], 0.0)
        self.assertEqual(low["delta_sum_loss_db"], 0.0)

    def test_a_fix_reads_as_an_improvement(self):
        late = dict(self.drivers, tweeter=self.drivers["tweeter"] * np.exp(-2j * np.pi * FREQS * 0.12e-3))
        out = tunelib.probe_variants(FREQS, late, self.junctions,
                                     [{"name": "advance tweeter", "changes": {"tweeter": {"delay_ms": -0.12}}}])
        top = [j for j in out[1]["junctions"] if j["id"] == "mid-tweeter"][0]
        self.assertGreater(top["delta_phase_score"], 0.05)

    def test_headroom_reports_peq_boost(self):
        out = tunelib.probe_variants(FREQS, self.drivers, self.junctions,
                                     [{"name": "boost", "changes": {"mid": {"peq": [[1000, 1.0, 3.0]]}}}])
        self.assertAlmostEqual(out[1]["max_chain_boost_db"], 3.0, delta=0.05)


class ProbeCliTests(unittest.TestCase):
    def test_probe_cli_reads_exports_and_writes_nothing(self):
        drivers, junctions = _three_way()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = {"dsp_sample_rate_hz": 96000, "drivers": {}, "junctions": [],
                    "variants": [{"name": "mid +0.2 ms", "changes": {"mid": {"delay_ms": 0.2}}}]}
            for name, H in drivers.items():
                path = root / ("%s.txt" % name)
                rows = ["* Freq(Hz) SPL(dB) Phase(degrees)"] + [
                    "%.4f %.4f %.4f" % (f, 80 + 20 * np.log10(abs(h) + 1e-9), np.degrees(np.angle(h)))
                    for f, h in zip(FREQS, H)]
                path.write_text("\n".join(rows) + "\n", encoding="utf-8")
                spec["drivers"][name] = str(path)
            spec["junctions"] = [{"lower": a, "upper": b, "crossover_hz": fc} for a, b, fc in junctions]
            spec_path = root / "probe.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            before = sorted(p.name for p in root.iterdir())
            run = subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), "probe",
                                  "--spec", str(spec_path)],
                                 text=True, capture_output=True, check=False)
            self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            report = json.loads(run.stdout)
            self.assertEqual(before, sorted(p.name for p in root.iterdir()))
            self.assertEqual([v["name"] for v in report["variants"]], ["baseline", "mid +0.2 ms"])


if __name__ == "__main__":
    unittest.main()
