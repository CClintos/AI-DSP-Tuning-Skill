"""Reading everything a single MMM capture carries: REW .mdat files by
structure, the whole REW header, a capture audit, the moving-mic floor, and
the decisions they enable (summation coherence, four-capture alignment, peak
stability, crossover checks, listening-level and road-noise voicing, learned
preferences, per-block statistics and the experimental test signals).

The .mdat fixtures are written here by a small Java-serialization writer, so
no real file (with its local paths) is ever committed."""

import argparse
import json
import math
import struct
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
import capture_audit  # noqa: E402
import frames  # noqa: E402
import loudness  # noqa: E402
import mdat  # noqa: E402
import measure  # noqa: E402
import mmm  # noqa: E402
import rew_api  # noqa: E402
import signals  # noqa: E402
import tunelib  # noqa: E402


# ---------------------------------------------------------------- .mdat writer
class _JavaWriter:
    """Just enough of java.io.ObjectOutputStream for REW-shaped fixtures."""

    def __init__(self):
        self.b = bytearray(b"\xac\xed\x00\x05")

    @staticmethod
    def _utf(text):
        raw = text.encode("utf-8")
        return struct.pack(">H", len(raw)) + raw

    def string(self, text):
        self.b += b"\x74" + self._utf(text)

    def block(self, data):
        self.b += b"\x77" + bytes([len(data)]) + data

    def _classdesc(self, name, fields):
        self.b += b"\x72" + self._utf(name) + struct.pack(">q", 1) + b"\x02"
        self.b += struct.pack(">H", len(fields))
        for kind, fname, cls in fields:
            self.b += kind.encode() + self._utf(fname)
            if kind in "L[":
                self.string(cls)
        self.b += b"\x78\x70"            # no annotations, no superclass

    def value(self, kind, v):
        if kind == "I":
            self.b += struct.pack(">i", v)
        elif kind == "J":
            self.b += struct.pack(">q", v)
        elif kind == "D":
            self.b += struct.pack(">d", v)
        elif kind == "Z":
            self.b += b"\x01" if v else b"\x00"
        elif v is None:
            self.b += b"\x70"
        elif isinstance(v, str):
            self.string(v)
        elif isinstance(v, np.ndarray):
            self.b += b"\x75"
            self._classdesc("[F", [])
            self.b += struct.pack(">i", len(v)) + v.astype(">f4").tobytes()
        else:
            self.obj(*v)

    def obj(self, name, fields):
        """fields: [(kind, name, java class, value)]"""
        self.b += b"\x73"
        self._classdesc(name, [(k, n, c) for k, n, c, _v in fields])
        for kind, _n, _c, v in fields:
            self.value(kind, v)


def _meas_fields(name, spl, raw=None, start=10.0, ppo=96, fmt="", notes="", source="",
                 output="", rta=True, when_ms=1783156452910, serial=7000001, smoothing=48.0):
    n = len(spl)
    f_end = start * 2 ** ((n - 1) / ppo)
    cal = ("roomeqwizard.CalData", [
        ("I", "serialNum", None, serial),
        ("L", "sourceName", "Ljava/lang/String;", "%d_90deg.txt" % serial),
        ("D", "sensitivitydB", None, -1.5),
        ("[", "freqArray", "[F", np.array([10.0, 1000.0, 20000.0])),
        ("[", "gainArray", "[F", np.array([-5.0, 0.0, 1.0]))])
    return ("roomeqwizard.MeasData", [
        ("L", "shortDesc", "Ljava/lang/String;", name),
        ("J", "sourceFileDate", None, when_ms),
        ("I", "dataLength", None, n),
        ("D", "startFreq", None, start),
        ("D", "endFreq", None, f_end),
        ("D", "logStep", None, 2 ** (1.0 / ppo)),
        ("I", "ppo", None, ppo),
        ("Z", "isLogSpaced", None, True),
        ("Z", "isFromRTA", None, rta),
        ("D", "octaveFrac", None, smoothing),
        ("D", "sampleRate", None, 48000.0),
        ("D", "validStartFreq", None, start),
        ("D", "validEndFreq", None, f_end),
        ("I", "rewVersion", None, 5),
        ("I", "rewSubVersion", None, 40),
        ("L", "versionSt", "Ljava/lang/String;", " beta 127"),
        ("L", "sourceFileFormat", "Ljava/lang/String;", fmt),
        ("L", "measNotes", "Ljava/lang/String;", notes),
        ("L", "sourceFileName", "Ljava/lang/String;", source),
        ("L", "outputName", "Ljava/lang/String;", output),
        ("[", "splValues", "[F", np.asarray(spl, dtype=float)),
        ("[", "rawValues", "[F", np.asarray(raw if raw is not None else spl, dtype=float)),
        ("L", "meterCal", "Lroomeqwizard/CalData;", cal)])


def write_mdat(path, measurements, file_notes="test session"):
    w = _JavaWriter()
    w.string("REW Measurement Data File V2")
    w.block(struct.pack(">ii", 5, 40))
    w.string("Notes:" + file_notes)
    w.block(struct.pack(">i", len(measurements)))
    for m in measurements:
        w.block(struct.pack(">i", 3))
        w.string("<HTML>preview</HTML>")
        w.obj(*m)
    Path(path).write_bytes(bytes(w.b))
    return str(path)


RTA_FMT = "65536-point 1/24 octave RTA using Hann window, no smoothing and %d averages"
NOTES = "%s\n\nInput RMS %.2f dB\n%.1f dB C, %.1f dB A\n%.1f dB 22 - 22k UNW\n%.1f dB >22k\n"
SOURCE = "EXCL: Microphone (Umik-1  Gain: 18dB  ), MICROPHONE (Master Volume), L, volume: %.3f"
OUTPUT = "Output device not selected, no output selected, L, volume: no control"


def rew_text(path, freqs, spl, name, averages=120, rms=70.0, dbc=65.0, dba=62.0, unw=66.0,
             above=25.0, smoothing="None", volume=1.0, when="Jul 14, 2026, 8:34:16 PM"):
    """A text export with REW 5.40's own header."""
    fmt = RTA_FMT % averages
    lines = ["* Measurement data measured by REW V5.40 beta 127",
             "* Source: " + SOURCE % volume,
             "* Format: " + fmt + " ",
             "* Dated: " + when,
             "* Note: ; %s  Input RMS %.2f dB %.1f dB C, %.1f dB A %.1f dB 22 - 22k UNW %.1f dB >22k "
             % (fmt, rms, dbc, dba, unw, above),
             "* Measurement: " + name,
             "* Smoothing: " + smoothing,
             "* Frequency Step: 96 ppo",
             "* Start Frequency: %.7g Hz" % freqs[0],
             "*", "* Freq(Hz) SPL(dB)"]
    lines += ["%.6f %.3f" % (f, s) for f, s in zip(freqs, spl)]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def _lr4(freqs, fc, kind):
    s = 1j * np.asarray(freqs) / fc
    bw2 = 1.0 / (s ** 2 + np.sqrt(2) * s + 1.0)
    return bw2 ** 2 if kind == "lp" else bw2 ** 2 * s ** 4


def _lr4_db(freqs, fc, kind):
    return 20 * np.log10(np.abs(_lr4(freqs, fc, kind)))


GRID = measure.common_grid(10.0, 23000.0, 96)


class _Tmp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.rng = np.random.default_rng(11)

    def run_cli(self, *args, ok=True, script="pipeline.py"):
        run = subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                             text=True, capture_output=True, check=False, cwd=self.root)
        if not ok:
            self.assertNotEqual(0, run.returncode, run.stdout)
            return run.stderr
        self.assertEqual(0, run.returncode, run.stdout + run.stderr)
        return json.loads(run.stdout)


# ---------------------------------------------------------------- A1
class MdatReader(_Tmp):
    def session(self):
        n = 1229
        tw = 40 + _lr4_db(3.2959 * 2 ** (np.arange(n) / 96), 2600, "hp")
        tw = np.maximum(tw, 15)
        sub = np.maximum(70 + _lr4_db(3.2959 * 2 ** (np.arange(n) / 96), 80, "lp"), 12)
        meas = [_meas_fields("Front L Tweeter", tw + 0.3, tw, start=3.2958984375,
                             fmt=RTA_FMT % 31,
                             notes=NOTES % (RTA_FMT % 31, 67.82, 57.8, 57.2, 58.6, 29.0),
                             source=SOURCE % 0.95, output=OUTPUT),
                _meas_fields("Sub", sub, start=3.2958984375, fmt=RTA_FMT % 25,
                             notes=NOTES % (RTA_FMT % 25, 73.56, 68.2, 40.7, 70.2, 22.9),
                             source=SOURCE % 0.95, output=OUTPUT, serial=7000002)]
        return write_mdat(self.root / "session.mdat", meas), tw, sub

    def test_the_axis_is_the_one_rew_states_and_values_are_unsmoothed(self):
        path, tw, _sub = self.session()
        f, s, ph, coh = measure.load_text_export(path + "::Front L Tweeter")
        self.assertAlmostEqual(f[0], 3.2958984375, places=6)
        self.assertAlmostEqual(f[1] / f[0], 2 ** (1 / 96), places=9)
        self.assertEqual(len(f), 1229)
        np.testing.assert_allclose(s, tw, atol=1e-4)      # rawValues, not the +0.3 smoothed copy
        self.assertIsNone(ph)
        self.assertIsNone(coh)

    def test_select_by_index_and_refuse_ambiguity(self):
        path, _tw, sub = self.session()
        self.assertEqual(mdat.select(path + "::#2")["name"], "Sub")
        self.assertEqual(mdat.select(path + "::sub")["name"], "Sub")     # case-insensitive
        with self.assertRaisesRegex(ValueError, "holds 2 measurements"):
            measure.load_text_export(path)
        with self.assertRaisesRegex(ValueError, "no measurement named"):
            mdat.select(path + "::Midbass")

    def test_header_reads_mic_levels_and_settings(self):
        path, _tw, _sub = self.session()
        hdr = measure.read_export_header(path + "::Front L Tweeter")
        rew = hdr["rew"]
        self.assertTrue(hdr["unsmoothed"])
        self.assertEqual(rew["mic_serial"], "7000001")
        self.assertEqual(rew["format"]["rta_fraction"], 24)
        self.assertEqual(rew["format"]["averages"], 31)
        self.assertEqual(rew["source"]["gain_db"], 18.0)
        self.assertAlmostEqual(rew["source"]["input_volume"], 0.95)
        self.assertAlmostEqual(rew["levels"]["below_22_db"], 67.3, places=1)
        self.assertEqual(rew["version"], "5.40 beta 127")

    def test_distortion_arrays_put_the_fundamental_second(self):
        # REW's harmData: an unidentified first array, then the fundamental,
        # then H2, H3 ... (checked against the measured SPL on real files)
        dist = mdat.JObject("roomeqwizard.DistortionData")
        fund, h2, h3 = np.full(4, 100.0), np.full(4, 68.0), np.full(4, 63.0)
        dist.fields["harmData"] = [np.full(4, -42.0), fund, h2, h3]
        h = mdat._harmonics(dist)
        np.testing.assert_array_equal(h["fundamental"], fund)
        np.testing.assert_array_equal(h[2], h2)
        np.testing.assert_array_equal(h[3], h3)
        self.assertEqual(sorted(k for k in h if k != "fundamental"), [2, 3])

    def test_not_an_mdat_and_truncated_files_fail_in_one_line(self):
        bad = self.root / "x.mdat"
        bad.write_bytes(b"not java at all")
        with self.assertRaisesRegex(ValueError, "not a Java serialization stream"):
            mdat.load(str(bad))
        path, _tw, _sub = self.session()
        data = Path(path).read_bytes()
        cut = self.root / "cut.mdat"
        cut.write_bytes(data[:len(data) // 2])
        with self.assertRaisesRegex(ValueError, "truncated|ends inside"):
            mdat.load(str(cut))

    def test_a_claimed_array_longer_than_the_file_is_refused_before_allocating(self):
        w = _JavaWriter()
        w.string("REW Measurement Data File V2")
        w.b += b"\x75"
        w._classdesc("[F", [])
        w.b += struct.pack(">i", 2_000_000_000)
        bad = self.root / "huge.mdat"
        bad.write_bytes(bytes(w.b))
        with self.assertRaisesRegex(ValueError, "ends inside"):
            mdat.load(str(bad))

    def test_cli_lists_and_exports_a_text_file_every_tool_reads(self):
        path, tw, _sub = self.session()
        out = self.root / "tw.txt"
        run = subprocess.run([sys.executable, str(SCRIPTS / "mdat.py"), "export",
                              path + "::Front L Tweeter", "--out", str(out)],
                             text=True, capture_output=True, cwd=self.root)
        self.assertEqual(0, run.returncode, run.stderr)
        f, s, _p, _c = measure.load_text_export(str(out))
        np.testing.assert_allclose(s, tw, atol=1e-3)
        hdr = measure.read_export_header(str(out))
        self.assertEqual(hdr["rew"]["mic_serial"], "7000001")
        listing = subprocess.run([sys.executable, str(SCRIPTS / "mdat.py"), "list", path, "--json"],
                                 text=True, capture_output=True, cwd=self.root)
        rows = json.loads(listing.stdout)
        self.assertEqual([r["name"] for r in rows], ["Front L Tweeter", "Sub"])

    def test_pipeline_analyze_takes_an_mdat_measurement(self):
        path, _tw, _sub = self.session()
        r = self.run_cli("analyze", "--measurement", path + "::Sub", "--target", "default",
                         "--capture", "mmm")
        self.assertIn("auto_profile", r["capture"])
        self.assertEqual(r["capture"]["auto_profile"]["stated_by_files"]["mic_serial"], "7000002")


# ---------------------------------------------------------------- A2
class RewHeader(unittest.TestCase):
    def test_format_line_smoothing_is_not_the_export_smoothing(self):
        lines = ["Format: 65536-point 1/24 octave RTA using Hann window, no smoothing and 31 averages",
                 "Note: ; 65536-point 1/24 octave RTA using Hann window, no smoothing and 31 averages",
                 "Smoothing: 1/48 octave"]
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.txt"
            p.write_text("\n".join("* " + ln for ln in lines) + "\n"
                         + "\n".join("%.3f 50" % f for f in GRID[::10]) + "\n", encoding="utf-8")
            hdr = measure.read_export_header(str(p))
        self.assertEqual(hdr["smoothing"], "1/48 octave")
        self.assertFalse(hdr["unsmoothed"])

    def test_rew_531_format_and_sweep_format(self):
        rta = measure.parse_rew_format("65536-point 1/48 octave RTA using Hann window and 46 averages")
        self.assertEqual((rta["kind"], rta["rta_fraction"], rta["averages"], rta["rta_smoothing"]),
                         ("rta", 48, 46, None))
        sw = measure.parse_rew_format("256k Log Swept Sine, 2 sweeps at -12.0 dBFS using a loopback "
                                      "as a timing reference")
        self.assertEqual((sw["kind"], sw["sweep_length"], sw["sweeps"], sw["level_dbfs"],
                          sw["timing_reference"]), ("sweep", 262144, 2, -12.0, "loopback"))

    def test_levels_and_source(self):
        lv = measure.parse_level_notes("Input RMS 108.08 dB 105.0 dB C, 78.8 dB A 106.5 dB 22 - 22k "
                                       "UNW 29.3 dB >22k")
        self.assertEqual((lv["input_rms_db"], lv["dbc"], lv["dba"], lv["unw_22_22k_db"],
                          lv["above_22k_db"]), (108.08, 105.0, 78.8, 106.5, 29.3))
        self.assertAlmostEqual(lv["below_22_db"], 102.9, places=1)
        src = measure.parse_source(SOURCE % 0.88)
        self.assertEqual((src["mic_model"], src["gain_db"], src["channel"], src["input_volume"],
                          src["exclusive"]), ("UMIK-1", 18.0, "L", 0.88, True))
        self.assertEqual(measure.parse_rew_date("Jul 14, 2026, 8:34:16 PM"), "2026-07-14T20:34:16")


# ---------------------------------------------------------------- A3 / A4
class CaptureAudit(_Tmp):
    def solo(self, name, fc, kind, level=60.0, floor=20.0, **kw):
        if kind == "bp":
            db = level + _lr4_db(GRID, fc[0], "hp") + _lr4_db(GRID, fc[1], "lp")
        else:
            db = level + _lr4_db(GRID, fc, kind)
        db = db + self.rng.normal(0, 0.2, len(GRID))
        db = 10 * np.log10(10 ** (db / 10) + 10 ** (floor / 10))
        return rew_text(self.root / (name + ".txt"), GRID, db, name, **kw)

    def test_the_problems_of_a_real_set_are_found(self):
        files = [
            self.solo("Front Left Tweeter", 2600, "hp", unw=58.6, rms=67.8, smoothing="1/48 octave",
                      averages=31, volume=0.95),
            self.solo("Front Right Tweeter", 2600, "hp", floor=34.0, unw=62.0, rms=62.5, averages=32,
                      volume=0.95),
            self.solo("Subwoofer", 80, "lp", level=75, rms=73.6, unw=70.2, dba=40.7, averages=25,
                      volume=0.95),
        ]
        r = self.run_cli("capture-audit", "--captures", *files)
        by = {c["name"]: c for c in r["captures"]}
        codes = lambda n: {f["code"] for f in by[n]["flags"]}
        self.assertIn("handling_noise", codes("Front Left Tweeter"))       # 67.3 below 22 vs 58.6
        self.assertIn("short_capture", codes("Front Left Tweeter"))        # 31 averages ~6 s
        self.assertIn("infrasound", codes("Subwoofer"))
        self.assertNotIn("handling_noise", codes("Subwoofer"))
        set_codes = {f["code"] for f in r["set"]["flags"]}
        self.assertIn("mixed_export_smoothing", set_codes)
        self.assertIn("twin_floor_mismatch", set_codes)                    # 14 dB apart
        self.assertEqual(by["Subwoofer"]["usable_for"]["bass_decisions"], "no: infrasound")
        self.assertIsNotNone(r["set"]["moving_floor"])

    def test_capture_length_from_averages(self):
        secs, notes = capture_audit.capture_length_s({"kind": "rta", "fft_length": 65536,
                                                      "averages": 32}, 48000.0)
        self.assertAlmostEqual(secs, (65536 + 31 * 8192) / 48000.0)
        self.assertTrue(any("overlap" in n for n in notes))

    def test_triple_level_is_checked_against_the_power_sum(self):
        a = self.solo("Front Left Mid", (80, 2600), "bp", dba=58.2, dbc=68.5, unw=69.0, rms=69.5,
                      averages=200)
        b = self.solo("Front Right Mid", (80, 2600), "bp", dba=59.2, dbc=65.3, unw=66.0, rms=66.5,
                      averages=200)
        both = self.solo("Both Mids", (80, 2600), "bp", dba=62.0, dbc=70.8, unw=71.0, rms=71.5,
                         averages=200)
        r = self.run_cli("capture-audit", "--captures", a, b, both)
        tri = r["set"]["triples"][0]
        self.assertTrue(tri["consistent"])
        dba = next(c for c in tri["checks"] if c["weighting"] == "dba")
        self.assertAlmostEqual(dba["power_sum_db"], 61.7, places=1)
        louder = self.solo("Both Mids", (80, 2600), "bp", dba=66.0, dbc=74.0, unw=74.0, rms=74.5,
                           averages=200)
        r = self.run_cli("capture-audit", "--captures", a, b, louder)
        self.assertFalse(r["set"]["triples"][0]["consistent"])

    def test_mic_clip_risk_on_a_loud_sub(self):
        p = self.solo("Sub RAW", 80, "lp", level=105, rms=108.1, unw=106.5, averages=60)
        r = self.run_cli("capture-audit", "--captures", p)
        flags = {f["code"]: f for f in r["captures"][0]["flags"]}
        self.assertEqual(flags["mic_clip_risk"]["level"], "problem")

    def test_stopband_floor_is_read_only_far_from_the_passband(self):
        files = [self.solo("Left Tweeter", 3000, "hp", floor=30.0),
                 self.solo("Right Tweeter", 3000, "hp", floor=40.0)]
        caps = [capture_audit.load_capture(p) for p in files]
        fl = capture_audit.stopband_floor(GRID, caps)
        at = lambda hz: fl["floor_db"][np.argmin(np.abs(GRID - hz))]
        self.assertAlmostEqual(at(100.0), 40.0, delta=0.6)       # the higher floor gates
        self.assertTrue(np.isnan(at(2000.0)))                    # inside the transition: not floor
        self.assertAlmostEqual(np.nanmax(fl["spread_db"][GRID < 300]), 10.0, delta=1.0)

    def test_the_moving_floor_gates_a_session(self):
        tw = self.solo("Left Tweeter", 3000, "hp", floor=55.0)
        car = 50 + measure.load_target(SCRIPTS.parent / "assets" / "default_incar_target.txt", GRID)
        car[GRID < 60] -= 25                       # a deep bass shortfall the noise would fill
        m = rew_text(self.root / "System Sum.txt", GRID, car, "System Sum")
        r = self.run_cli("analyze", "--measurement", m, "--target", "default", "--capture", "mmm",
                         "--noise-floor", tw)
        amb = r["capture"]["ambient"]
        self.assertEqual(amb["moving_floor_files"], [tw])
        self.assertTrue(amb["excluded_hz"])


# ---------------------------------------------------------------- B1 / B2
class Coherence(_Tmp):
    def triple(self, rho, la=60.0, lb=60.0):
        pa, pb = 10 ** (la / 10), 10 ** (lb / 10)
        pab = pa + pb + 2 * rho * np.sqrt(pa * pb)
        return [np.full_like(GRID, x) for x in (la, lb, 10 * np.log10(pab))]

    def test_rho_is_recovered_and_classified(self):
        for rho, verdict in ((0.95, "coherent"), (0.0, "power_sum"), (-0.6, "cancelling")):
            rows = mmm.summation_coherence(GRID, *self.triple(rho))
            mid = [r for r in rows if 200 <= r["hz"] <= 2000]
            self.assertTrue(all(abs(r["rho"] - rho) < 0.02 for r in mid), (rho, mid[:2]))
            self.assertTrue(all(r["verdict"] == verdict for r in mid))

    def test_unequal_parts_and_impossible_sums_are_not_read(self):
        rows = mmm.summation_coherence(GRID, *self.triple(0.5, la=60, lb=45))
        self.assertTrue(all(r["verdict"] == "not_reported" for r in rows))
        pa = np.full_like(GRID, 60.0)
        rows = mmm.summation_coherence(GRID, pa, pa, pa + 8.0)     # +8 dB cannot happen
        self.assertTrue(all(r["verdict"] == "inconsistent" for r in rows))

    def test_noise_only_bands_are_not_read_as_cancellation(self):
        # Three captures of noise alone read rho = -0.5 exactly; outside the
        # mids' passband that is all a band-limited triple holds.
        def mid(level):
            db = level + _lr4_db(GRID, 80, "hp") + _lr4_db(GRID, 2600, "lp")
            return 10 * np.log10(10 ** (db / 10) + 10 ** (20 / 10))
        a, b = mid(60.0), mid(60.0)
        ab = 10 * np.log10(10 ** ((a - 0) / 10) + 10 ** (b / 10))       # power sum in band
        paths = [rew_text(self.root / ("%s.txt" % n), GRID, d, n)
                 for n, d in (("Front Left Mid", a), ("Front Right Mid", b), ("Both Mids", ab))]
        r = self.run_cli("coherence", "--a", paths[0], "--b", paths[1], "--together", paths[2])
        read = [x for x in r["bands"] if x["rho"] is not None]
        self.assertTrue(read)
        self.assertTrue(all(60 <= x["hz"] <= 5000 for x in read), read)   # -20 dB passband edges
        self.assertNotIn("cancelling", {x["verdict"] for x in read})

    def test_cli(self):
        a, b, ab = self.triple(0.9)
        paths = [rew_text(self.root / ("%s.txt" % n), GRID, d, n)
                 for n, d in (("Front Left Mid", a), ("Front Right Mid", b), ("Both Mids", ab))]
        r = self.run_cli("coherence", "--a", paths[0], "--b", paths[1], "--together", paths[2])
        self.assertGreater(r["verdict_counts"].get("coherent", 0), 20)


class AlignFour(_Tmp):
    """A coherent bass junction: sub and midbass with a known timing error."""
    F = measure.common_grid(30.0, 300.0, 96)

    def captures(self, true_delay_ms, tau1_ms, invert=False):
        f = self.F
        a = _lr4(f, 80, "lp") * np.exp(-2j * np.pi * f * 0.004)
        b = _lr4(f, 80, "hp") * np.exp(-2j * np.pi * f * (0.004 + true_delay_ms / 1e3))
        b = -b if invert else b

        def p(x):
            return 80 + 10 * np.log10(np.abs(x) ** 2 + 1e-12)
        rot = np.exp(-2j * np.pi * f * tau1_ms / 1e3)
        return {"A": p(a), "B": p(b), "AB": p(a + b), "AB1": p(a + b * rot),
                "AmB": p(a - b), "AmB1": p(a - b * rot)}

    def write(self, caps):
        return {k: rew_text(self.root / ("%s.txt" % k), self.F, v, k) for k, v in caps.items()}

    def best(self, r):
        return r["best"]["delay_change_ms"], r["best"]["invert_b"]

    def test_four_captures_find_the_delay_that_fixes_the_handover(self):
        tau1 = 1e3 / (4 * math.sqrt(50 * 130))
        p = self.write(self.captures(true_delay_ms=4.0, tau1_ms=tau1))
        r = self.run_cli("mmm-align", "--a", p["A"], "--b", p["B"], "--together", p["AB"],
                         "--together-delayed", p["AB1"], "--tau1-ms", "%.4f" % tau1,
                         "--band", "50", "130", "--dsp-rate", "96000")
        self.assertEqual(r["verdict"], "candidate")
        delay, inverted = self.best(r)
        self.assertFalse(inverted)
        self.assertAlmostEqual(delay, -4.0, delta=0.25)        # B is late by 4 ms: advance it
        self.assertIn("delay_change_samples", r["best"])
        self.assertGreater(r["head_area_coherence"], 0.9)

    def test_flip_form_needs_no_solos(self):
        tau1 = 3.0
        p = self.write(self.captures(true_delay_ms=3.0, tau1_ms=tau1))
        r = self.run_cli("mmm-align", "--sum", p["AB"], "--diff", p["AmB"], "--sum-delayed", p["AB1"],
                         "--diff-delayed", p["AmB1"], "--tau1-ms", "3", "--band", "50", "130")
        delay, inverted = self.best(r)
        self.assertAlmostEqual(delay, -3.0, delta=0.3)
        self.assertFalse(inverted)

    def test_an_aligned_junction_keeps_its_setting(self):
        tau1 = 3.0
        p = self.write(self.captures(true_delay_ms=0.0, tau1_ms=tau1))
        r = self.run_cli("mmm-align", "--a", p["A"], "--b", p["B"], "--together", p["AB"],
                         "--together-delayed", p["AB1"], "--tau1-ms", "3", "--band", "50", "130")
        self.assertEqual(r["verdict"], "keep_current")


# ---------------------------------------------------------------- B3 / B4
class StabilityAndCrossover(_Tmp):
    def test_peak_trace_marks_moving_bass(self):
        avg = np.full_like(GRID, 70.0)
        peak = avg + 3.0
        moving = (GRID > 90) & (GRID < 130)
        peak[moving] += 6.0
        w, _gap, _ref = mmm.stability_weights(GRID, avg, peak)
        self.assertLess(np.mean(w[(GRID > 100) & (GRID < 120)]), 0.5)
        self.assertGreater(np.mean(w[(GRID > 30) & (GRID < 60)]), 0.9)
        self.assertTrue(np.all(w[GRID > 300] == 1.0))

    def test_stability_reads_captures_that_start_above_ten_hz(self):
        # 1.21.0-1.23.0: the smoother carried the empty bins below a 20 Hz
        # export into every band, and the map read "stable" everywhere
        f = measure.common_grid(20.0, 20000.0, 96)
        avg = np.full_like(f, 70.0)
        peak = avg + 3.0
        peak[(f > 90) & (f < 130)] += 6.0
        r = self.run_cli("stability", "--average", rew_text(self.root / "Avg.txt", f, avg, "System Sum"),
                         "--peak", rew_text(self.root / "Peak.txt", f, peak, "System Sum peak"))
        reads = {round(b["hz"]): b["reads"] for b in r["bands"]}
        self.assertEqual(reads[99], "moves with head position")
        self.assertEqual(reads[50], "stable")

    def test_xo_check_reads_the_applied_crossover(self):
        raw = 80 + self.rng.normal(0, 0.15, len(GRID))
        xo = raw + _lr4_db(GRID, 80, "hp")
        p_raw = rew_text(self.root / "Mid RAW.txt", GRID, raw, "Mid RAW")
        p_xo = rew_text(self.root / "Mid XO.txt", GRID, xo, "Mid XO")
        r = self.run_cli("xo-check", "--raw", p_raw, "--xo", p_xo, "--hp", "80,24",
                         "--dsp-rate", "96000")
        hp = r["crossover"][0]
        self.assertEqual(hp["verdict"], "matches", hp)
        self.assertEqual(hp["measured"]["slope_db_oct"], 24)
        r = self.run_cli("xo-check", "--raw", p_raw, "--xo", p_xo, "--hp", "120,24",
                         "--dsp-rate", "96000")
        self.assertEqual(r["crossover"][0]["verdict"], "corner_differs")
        p_same = rew_text(self.root / "Mid XO2.txt", GRID, raw + 0.1, "Mid XO2")
        r = self.run_cli("xo-check", "--raw", p_raw, "--xo", p_same, "--hp", "80,24",
                         "--dsp-rate", "96000")
        self.assertEqual(r["crossover"][0]["verdict"], "not_applied")

    def test_xo_check_eq_against_the_stated_bank(self):
        raw = 80 + self.rng.normal(0, 0.1, len(GRID))
        xo = raw + _lr4_db(GRID, 80, "hp")
        eq = xo + tunelib.cascade_db(GRID, [(1000.0, 2.0, -4.0)], fs=96000.0)
        paths = [rew_text(self.root / ("%s.txt" % n), GRID, d, n)
                 for n, d in (("RAW", raw), ("XO", xo), ("EQ", eq))]
        r = self.run_cli("xo-check", "--raw", paths[0], "--xo", paths[1], "--eq", paths[2],
                         "--hp", "80,24", "--peq", "1000,2,-4", "--dsp-rate", "96000")
        self.assertEqual(r["eq"]["verdict"], "matches")
        r = self.run_cli("xo-check", "--raw", paths[0], "--xo", paths[1], "--eq", paths[1],
                         "--hp", "80,24", "--peq", "1000,2,-4", "--dsp-rate", "96000")
        self.assertEqual(r["eq"]["verdict"], "not_applied")

    def test_afpx_reports_crossover_slopes(self):
        blk = ('<OC ON="1" CINV="0"><Fil T="16" F="80.00" Q="0.7" G="-24" dF="80" FN="1" I="0" '
               'FilBy="0"/><Fil T="15" F="3000.00" Q="0.7" G="-12" dF="3000" FN="2" I="0" FilBy="0"/>'
               '<Vol T="15" L="1.0" i="0"/><T PM="1" P="0" T="0"/></OC>')
        ch = afpx.channels("<ATF>" + blk + "</ATF>")[0]
        self.assertEqual((ch["hp_slope_db_oct"], ch["lp_slope_db_oct"]), (24.0, 12.0))


# ---------------------------------------------------------------- C1 / C2 / C3
class Voicing(_Tmp):
    def test_iso226_reference_values(self):
        c40 = loudness.contour_table(40.0)
        self.assertAlmostEqual(c40[0], 99.85, delta=0.1)          # 20 Hz
        self.assertAlmostEqual(c40[17], 40.0, delta=0.05)         # 1 kHz
        self.assertAlmostEqual(loudness.threshold_db([20.0])[0], 78.5)
        comp = loudness.compensation_db([30.0, 1000.0], 65.0, 85.0)
        self.assertGreater(comp[0], 5.0)
        self.assertAlmostEqual(comp[1], 0.0, places=2)

    def test_listening_level_offers_a_shelf_not_a_correction(self):
        cap = rew_text(self.root / "System Sum.txt", GRID, np.full_like(GRID, 60.0), "System Sum",
                       dbc=64.0, dba=62.0)
        r = self.run_cli("listening-level", "--capture", cap, "--reference-phon", "83")
        shelf = r["voicing_option"]["low_shelf"]
        self.assertGreater(shelf["gain_db"], 2.0)
        self.assertLessEqual(shelf["gain_db"], 6.0)
        self.assertEqual(r["meta"]["listening_phon"], 64.0)
        self.assertIn("below_threshold_hz", r)
        same = self.run_cli("listening-level", "--listening-db", "83", "--reference-phon", "83")
        self.assertAlmostEqual(same["voicing_option"]["low_shelf"]["gain_db"], 0.0)

    def test_road_noise_lifts_only_masked_bass(self):
        music = rew_text(self.root / "music.txt", GRID, np.full_like(GRID, 60.0), "System Sum")
        road = np.where(GRID < 150, 62.0, 30.0)
        noise = rew_text(self.root / "road.txt", GRID, road, "Road noise ambient")
        r = self.run_cli("road-noise", "--noise", noise, "--music", music)
        self.assertGreater(r["driving_variant"]["low_shelf"]["gain_db"], 1.0)
        self.assertTrue(all(h < 200 for h in r["masked_bands_hz"]))
        quiet = rew_text(self.root / "quiet.txt", GRID, np.full_like(GRID, 20.0), "Road noise quiet")
        r = self.run_cli("road-noise", "--noise", quiet, "--music", music)
        self.assertAlmostEqual(r["driving_variant"]["low_shelf"]["gain_db"], 0.0)

    def test_preferences_are_learned_from_blind_choices(self):
        rng = np.random.default_rng(5)
        out = self.root / "v"
        out.mkdir()
        base = self.root / "base.afpx"
        levels = [-2.0, -1.0, 1.0, 2.0, 3.0, 4.0]
        variants = []
        for g in levels:
            variants.append({"file": str(out / ("bass%+.2fdB.afpx" % g)), "knobs": {"bass": g}})
        (out / "voice_variants.json").write_text(json.dumps({"version": 1, "variants": variants}))
        log = []
        util = lambda x: -0.5 * (x - 2.0) ** 2           # this listener likes +2 dB
        for _ in range(40):
            i, j = rng.choice(len(levels) + 1, 2, replace=False)
            xa = 0.0 if i == len(levels) else levels[i]
            xb = 0.0 if j == len(levels) else levels[j]
            pa = str(base) if i == len(levels) else variants[i]["file"]
            pb = str(base) if j == len(levels) else variants[j]["file"]
            p_a = 1 / (1 + math.exp(-(util(xa) - util(xb))))
            wins_a = int(rng.binomial(6, p_a))
            log.append({"counts": {"X": wins_a, "Y": 6 - wins_a}, "reveal": {"X": "A", "Y": "B"},
                        "sources": {"A": pa, "B": pb}})
        (self.root / "ab_log.json").write_text(json.dumps(log))
        r = self.run_cli("prefs", "--log", str(self.root / "ab_log.json"), "--base", str(base))
        bass = r["preferences"]["bass"]
        self.assertAlmostEqual(bass["preferred_db"], 2.0, delta=0.8)
        lo, hi = bass["interval_80_db"]
        self.assertLess(lo, bass["median_db"])
        self.assertLess(bass["median_db"], hi)
        self.assertEqual(r["next_test"]["knob"], "bass")

    def test_voice_variants_record_their_knobs(self):
        blk = ('<OC ON="1" CINV="0"><Fil T="16" F="80.00" Q="0.7" G="-24" dF="80" FN="1" I="0" '
               'FilBy="0"/><Fil T="1" F="25.00" Q="1" G="0" dF="25" FN="12" I="0" FilBy="0"/>'
               '<Fil T="1" F="20000.00" Q="1" G="0" dF="20000" FN="13" I="0" FilBy="0"/>'
               '<Vol T="15" L="1.0" i="0"/><T PM="1" P="0" T="0"/></OC>')
        tune = self.root / "t.afpx"
        afpx._encode_unchecked("<ATF>" + blk + "</ATF>", str(tune))
        r = self.run_cli("voice-variants", "--afpx", str(tune), "--out-dir", str(self.root / "vv"),
                         "--bass-channels", "0", "--bass-db", "1.5", "--confirm")
        man = json.loads((self.root / "vv" / "voice_variants.json").read_text())
        self.assertEqual(man["variants"][0]["knobs"], {"bass": 1.5})
        self.assertEqual(r["variants"][0]["knobs"], {"bass": 1.5})
        self.assertEqual(mmm.knobs_for(man["variants"][0]["file"])["bass"], 1.5)

    def test_height_and_distance_are_knobs_prefs_can_learn(self):
        free = "".join('<Fil T="1" F="1000.00" Q="1" G="0" dF="1000" FN="%d" I="0" FilBy="0"/>' % n
                       for n in (2, 3, 4))
        blk = ('<OC ON="1" CINV="0"><Fil T="16" F="2600.00" Q="0.7" G="-24" dF="2600" FN="1" I="0" '
               'FilBy="0"/>' + free + '<Vol T="15" L="1.0" i="0"/><T PM="1" P="0" T="0"/></OC>')
        tune = self.root / "t.afpx"
        afpx._encode_unchecked("<ATF>" + blk + "</ATF>", str(tune))
        r = self.run_cli("voice-variants", "--afpx", str(tune), "--out-dir", str(self.root / "vv"),
                         "--height-channels", "0", "--height-db", "-1", "1", "2", "3",
                         "--distance-channels", "0", "--distance-db", "-1", "--confirm")
        by = {v["variant"]: v for v in r["variants"]}
        self.assertEqual(set(by), {"height-1.00dB", "height+1.00dB", "height+2.00dB",
                                   "height+3.00dB", "distance-1.00dB"})
        h = by["height+2.00dB"]["edits"][0]
        self.assertEqual((h["F"], h["Q"], h["G"], h["type_code"]), (8000.0, 1.4, 2.0, "17"))
        d = by["distance-1.00dB"]["edits"][0]
        self.assertEqual((d["F"], d["Q"], d["G"]), (4000.0, 1.0, -1.0))
        self.assertEqual(mmm.knobs_for(by["height+2.00dB"]["file"])["height"], 2.0)
        self.assertEqual(mmm.knobs_for(str(self.root / "x" / "distance-1.5dB.afpx"))["distance"], -1.5)
        # a listener who likes the stage lifted by +1 dB, judged blind
        rng = np.random.default_rng(4)
        files = [(0.0, str(tune))] + [(by[n]["knobs"]["height"], by[n]["file"])
                                       for n in by if n.startswith("height")]
        log = []
        for _ in range(40):
            i, j = rng.choice(len(files), 2, replace=False)
            (xa, pa), (xb, pb) = files[i], files[j]
            p_a = 1 / (1 + math.exp(-(-0.5 * (xa - 1.0) ** 2 + 0.5 * (xb - 1.0) ** 2)))
            wins = int(rng.binomial(6, p_a))
            log.append({"counts": {"X": wins, "Y": 6 - wins}, "reveal": {"X": "A", "Y": "B"},
                        "sources": {"A": pa, "B": pb}})
        (self.root / "ab_log.json").write_text(json.dumps(log))
        p = self.run_cli("prefs", "--log", str(self.root / "ab_log.json"), "--base", str(tune))
        self.assertIn("height", p["preferences"])
        self.assertNotIn("distance", p["preferences"])
        self.assertAlmostEqual(p["preferences"]["height"]["preferred_db"], 1.0, delta=0.9)


# ---------------------------------------------------------------- D1 / D2 / API
class FramesAndSignals(_Tmp):
    def test_wav_round_trip(self):
        x = np.stack([np.sin(np.arange(4800) / 7.0) * 0.5, np.zeros(4800)], axis=1)
        for bits in (16, 24):
            p = self.root / ("t%d.wav" % bits)
            frames.write_wav(str(p), x, 48000, bits)
            y, rate = frames.read_wav(str(p))
            self.assertEqual(rate, 48000.0)
            np.testing.assert_allclose(y, x, atol=2.0 / 2 ** (bits - 1))

    def test_one_run_gives_its_own_repeatability(self):
        rate, secs = 48000, 24
        t = np.arange(rate * secs) / rate
        noise = self.rng.normal(0, 0.05, len(t))
        sine = 10 ** (-20 / 20) * np.sin(2 * np.pi * 1000 * t)      # -20 dBFS
        p = self.root / "pass.wav"
        frames.write_wav(str(p), (noise + sine)[:, None], rate, 24)
        r = self.run_cli("frames", "--wav", str(p), "--fft", "16384", "--out-dir", str(self.root / "fr"))
        f, s, _p, _c = measure.load_text_export(r["files"]["mean"])
        at = s[np.argmin(np.abs(f - 1000))]
        self.assertAlmostEqual(at, -20.0, delta=0.6)
        self.assertIsNotNone(r["split_half_repeatability"]["noise_db"])
        for k in ("half1", "half2", "peak", "robust"):
            self.assertTrue(Path(r["files"][k]).exists())

    def test_a_handling_bump_is_dropped_from_the_robust_mean(self):
        freqs = measure.common_grid(20.0, 20000.0, 6)
        db = np.full((40, len(freqs)), 60.0) + self.rng.normal(0, 0.3, (40, len(freqs)))
        db[17] += 15.0
        st = frames.analyze_frames(freqs, db)
        self.assertEqual(st["bump_blocks"], [17])
        self.assertLess(np.max(np.abs(st["robust_db"] - 60.0)), 0.5)
        self.assertGreater(np.max(st["mean_db"] - 60.0), 1.0)

    def test_interleaved_signal_recovers_left_right_and_their_sum(self):
        x, spec = signals.make("lr-interleaved", fft=16384, seconds=6.0, level_dbfs=-18, lead_in_s=1.0)
        rate = 48000
        n = x.shape[0]
        f = np.fft.rfftfreq(n, 1 / rate)

        def path(sig, d, g):
            return np.fft.irfft(np.fft.rfft(sig) * g * np.exp(-2j * np.pi * f * d), n)
        mic = path(x[:, 0], 0.0030, 1.0) + path(x[:, 1], 0.0036, 0.7)
        from scipy import signal as ss
        m = int(round(n * (1 + 30e-6)))
        rec = ss.resample(mic, m) + self.rng.normal(0, 1e-5, m)
        res = signals.analyze(rec, rate, spec)
        self.assertAlmostEqual(res["clock_ppm"], (m / n - 1) * 1e6, delta=0.5)
        rows = [r for r in res["bands"] if "ild_db" in r and 100 < r["hz"] < 8000]
        self.assertTrue(all(abs(r["ild_db"] - 3.10) < 0.15 for r in rows))
        for r in rows:
            ff = np.linspace(r["hz"] / 2 ** (1 / 12), r["hz"] * 2 ** (1 / 12), 400)
            true = 10 * np.log10(np.mean(np.abs(np.exp(-2j * np.pi * ff * 0.003)
                                                + 0.7 * np.exp(-2j * np.pi * ff * 0.0036)) ** 2))
            self.assertAlmostEqual(r["predicted_sum_db"] - r["left_db"], true, delta=0.5)

    def test_empty_bins_show_distortion_and_doppler_limit(self):
        x, spec = signals.make("multitone-empty", fft=16384, seconds=6.0, level_dbfs=-12, lead_in_s=1.0)
        m = x[:, 0]
        pk = np.max(np.abs(m))
        noisy = m + self.rng.normal(0, 1e-5, len(m))
        clean = signals.analyze(noisy, 48000, spec)
        dist = signals.analyze(noisy + 0.01 * (m / pk) ** 3 * pk, 48000, spec)
        mid = lambda res: [r["empty_over_silence_db"] for r in res["bands"]
                           if 150 < r["hz"] < 2000 and "empty_over_silence_db" in r]
        self.assertLess(float(np.median(mid(clean))), 2.0)     # static: empty bins = the floor
        self.assertGreater(min(mid(dist)), 15.0)
        self.assertLess(dist["doppler_limit_hz"], 1000)

    def test_test_signal_cli_writes_wav_and_spec_once(self):
        out = self.root / "sig.wav"
        r = self.run_cli("test-signal", "--kind", "pink-periodic", "--seconds", "2", "--fft", "16384",
                         "--wav-out", str(out))
        self.assertTrue(out.exists() and Path(r["spec"]).exists())
        err = self.run_cli("test-signal", "--kind", "pink-periodic", "--seconds", "2",
                           "--wav-out", str(out), ok=False)
        self.assertIn("already exists", err)


class RewApiRta(unittest.TestCase):
    class Fake:
        def __init__(self, responses):
            self.responses = responses
            self.calls = []

        def _get(self, path, query=None):
            self.calls.append(path)
            r = self.responses[path]
            if isinstance(r, list):
                return r.pop(0) if len(r) > 1 else r[0]
            return r

    @staticmethod
    def fr(count, level=60.0):
        mag = np.full(8, level, dtype=">f4").tobytes()
        import base64
        return {"startFreq": 20.0, "ppo": 1, "magnitude": base64.b64encode(mag).decode(),
                "sampleCount": count, "timestamp": count * 10, "smoothing": "None"}

    def test_captured_data_and_frames_are_get_only_and_deduplicated(self):
        frs = [self.fr(c) for c in (100, 100, 200, 300, 300, 400)]
        fake = self.Fake({"/rta/captured-data": frs})
        reader = rew_api.RtaReader(fake)
        ticks = iter(range(100))
        f, got = rew_api.poll_frames(reader, seconds=10, interval=0, sleep=lambda s: None,
                                     clock=lambda: next(ticks))
        self.assertEqual([g["sample_count"] for g in got], [100, 200, 300, 400])
        self.assertAlmostEqual(f[1], 40.0)
        self.assertTrue(all(c.startswith("/rta/") for c in fake.calls))

    def test_settings_are_found_whatever_rew_calls_them(self):
        cfg = {"analyser": {"averaging": "None", "fftLength": 65536, "maxOverlap": "93.75%"}}
        keys = dict(rew_api.find_setting(cfg, "averag"))
        self.assertEqual(keys, {"analyser.averaging": "None"})


if __name__ == "__main__":
    unittest.main()
