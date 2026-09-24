"""Byte-integrity of tune codecs and input validation of measurement loaders."""

import hashlib
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "helix-rew-tuner" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import afpx  # noqa: E402
import measure  # noqa: E402
import pct6  # noqa: E402
import pipeline  # noqa: E402


# An untouched attribute carrying a byte that is not valid UTF-8 (a cp1252
# "smart quote"), as a Windows path or binary field in a real tune could.
NON_UTF8_AFPX = (
    b'<ATF FN="C:\\Users\\\x93me\x94\\tune.afpx"><OC ON="1" CINV="0">'
    b'<Fil T="16" F="80.00" Q="0.7" G="-24" dF="80" FN="1" I="0" FilBy="0"/>'
    b'<Fil T="17" F="100.00" Q="1" G="-2" dF="100" FN="2" I="0" FilBy="0"/>'
    b'<Vol T="15" L="1.0" i="0"/>'
    b'<T PM="1" P="0" T="0"/>'
    b'</OC></ATF>'
)


def _write_raw_afpx(payload, path):
    path.write_bytes(struct.pack('>I', len(payload)) + zlib.compress(payload, 9))


def _afpx_payload(path):
    return zlib.decompress(path.read_bytes()[4:])


class AfpxByteIntegrityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / "source.afpx"
        self.output = self.root / "output.afpx"
        _write_raw_afpx(NON_UTF8_AFPX, self.source)

    def test_apply_preserves_non_utf8_bytes_in_untouched_fields(self):
        plan = {
            "version": 1,
            "source_path": str(self.source),
            "source_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
            "format": "afpx",
            "output_path": str(self.output),
            "edits": [{"id": "peq-1", "kind": "filter_slot",
                       "channel": 0, "slot": 1, "G": -3.0}],
            "confirmations": {"peq-1": True},
        }
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")

        pipeline.apply_plan(plan_path)

        expected = NON_UTF8_AFPX.replace(b'G="-2"', b'G="-3"', 1)
        self.assertEqual(_afpx_payload(self.output), expected)

    def test_source_bound_writer_round_trips_non_utf8_bytes_exactly(self):
        xml = afpx.decode(self.source)
        afpx.write_preserving_crossovers(self.source, xml, self.output)
        self.assertEqual(_afpx_payload(self.output), NON_UTF8_AFPX)

    def test_header_length_matches_payload_after_round_trip(self):
        xml = afpx.decode(self.source)
        afpx.write_preserving_crossovers(self.source, xml, self.output)
        raw = self.output.read_bytes()
        declared = struct.unpack('>I', raw[:4])[0]
        self.assertEqual(declared, len(zlib.decompress(raw[4:])))


class Pct6ErrorTests(unittest.TestCase):
    def test_undecodable_container_raises_clear_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "locked.pct6"
            path.write_bytes(bytes(range(256)) * 4)
            with self.assertRaisesRegex(ValueError, "password-protected"):
                pct6.decode_bytes(path)


class MeasurementLoaderValidationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_text_export_reads_decimal_comma_columns(self):
        # A comma-decimal locale export: "20,508  72,3  -45,2" silently
        # became freq=20, SPL=508 before.
        path = self.root / "comma.txt"
        rows = ["* Freq(Hz) SPL(dB) Phase(degrees)"]
        freqs = [20.0 * 2 ** (i / 4.0) for i in range(40)]
        for i, f in enumerate(freqs):
            rows.append(("%.3f  %.1f  %.1f" % (f, 70 + i % 3, -45.0)).replace(".", ","))
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        f, spl, phase, _ = measure.load_text_export(path)
        np.testing.assert_allclose(f, freqs, atol=1e-3)
        np.testing.assert_allclose(spl[:3], [70.0, 71.0, 72.0])
        np.testing.assert_allclose(phase, -45.0)

    def test_text_export_still_reads_comma_separated_values(self):
        path = self.root / "csv.txt"
        rows = ["%g,%g,%g" % (20 * 2 ** i, 70 + i, -10) for i in range(10)]
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        f, spl, _, _ = measure.load_text_export(path)
        self.assertEqual(f[1], 40.0)
        self.assertEqual(spl[1], 71.0)

    def test_text_export_rejects_non_increasing_frequency(self):
        path = self.root / "unsorted.txt"
        rows = ["%g 70 0" % (20 * 2 ** i) for i in range(10)]
        rows[3], rows[4] = rows[4], rows[3]
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "increasing"):
            measure.load_text_export(path)

    def test_text_export_rejects_non_positive_frequency(self):
        path = self.root / "zero.txt"
        rows = ["0 70 0"] + ["%g 70 0" % (20 * 2 ** i) for i in range(10)]
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "positive"):
            measure.load_text_export(path)

    def test_target_listed_high_to_low_interpolates_correctly(self):
        path = self.root / "target.txt"
        path.write_text("20000 -3\n1000 0\n20 10\n", encoding="utf-8")
        freqs = np.array([20.0, 1000.0, 20000.0])
        np.testing.assert_allclose(measure.load_target(path, freqs), [10.0, 0.0, -3.0])

    def test_target_rejects_duplicate_frequencies(self):
        path = self.root / "target.txt"
        path.write_text("20 10\n1000 0\n1000 2\n20000 -3\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            measure.load_target(path, np.array([100.0]))


if __name__ == "__main__":
    unittest.main()
