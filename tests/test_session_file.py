"""The intake session sidecar: <tune>.tuner_session.json."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "helix-rew-tuner" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pipeline  # noqa: E402


ANSWERS = {
    "dsp_model": "P SIX DSP MK2",
    "sample_rate_hz": 96000,
    "channel_map": {"0": "front left mid", "1": "front right mid"},
    "listening_seat": "driver",
    "drive_side": "RHD",
    "rear_channel_routing": "discrete",
    "target_curve_path": "resonix.txt",
    "voicing": {"tilt": -0.5},
}


class SessionFileTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.tune = self.root / "mytune.afpx"
        self.tune.write_bytes(b"tune-bytes-v1")
        self.sidecar = self.root / "mytune.afpx.tuner_session.json"

    def test_check_without_sidecar_reports_absent(self):
        report = pipeline.session_check(self.tune)
        self.assertFalse(report["exists"])
        self.assertIsNone(report["hash_matches"])
        self.assertEqual(report["session_path"], str(self.sidecar))

    def test_save_records_hash_and_never_touches_tune(self):
        pipeline.session_save(self.tune, ANSWERS)
        stored = json.loads(self.sidecar.read_text(encoding="utf-8"))
        self.assertEqual(stored["afpx_sha256"],
                         hashlib.sha256(b"tune-bytes-v1").hexdigest())
        self.assertEqual(stored["channel_map"], ANSWERS["channel_map"])
        self.assertEqual(self.tune.read_bytes(), b"tune-bytes-v1")

    def test_check_matching_hash_returns_answers_for_confirmation(self):
        pipeline.session_save(self.tune, ANSWERS)
        report = pipeline.session_check(self.tune)
        self.assertTrue(report["hash_matches"])
        self.assertEqual(report["answers"]["drive_side"], "RHD")
        self.assertNotIn("afpx_sha256", report["answers"])

    def test_check_after_tune_edit_flags_file_derived_answers_stale(self):
        pipeline.session_save(self.tune, ANSWERS)
        self.tune.write_bytes(b"tune-bytes-v2-edited-in-pc-tool")
        report = pipeline.session_check(self.tune)
        self.assertFalse(report["hash_matches"])
        self.assertIn("channel_map", report["stale_fields"])
        self.assertIn("dsp_model", report["stale_fields"])
        self.assertNotIn("listening_seat", report["stale_fields"])

    def test_save_refuses_unknown_fields(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            pipeline.session_save(self.tune, dict(ANSWERS, favourite_band="x"))
        self.assertFalse(self.sidecar.exists())

    def test_save_refuses_caller_supplied_hash(self):
        with self.assertRaisesRegex(ValueError, "afpx_sha256"):
            pipeline.session_save(self.tune, dict(ANSWERS, afpx_sha256="0" * 64))

    def test_missing_fields_are_recorded_as_null(self):
        pipeline.session_save(self.tune, {"drive_side": "LHD"})
        stored = json.loads(self.sidecar.read_text(encoding="utf-8"))
        self.assertIsNone(stored["channel_map"])
        self.assertEqual(stored["drive_side"], "LHD")

    def test_check_rejects_malformed_sidecar(self):
        self.sidecar.write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "session"):
            pipeline.session_check(self.tune)

    def test_cli_save_then_check(self):
        answers = self.root / "answers.json"
        answers.write_text(json.dumps(ANSWERS), encoding="utf-8")
        script = str(SCRIPTS / "pipeline.py")
        save = subprocess.run(
            [sys.executable, script, "session", "save", "--tune", str(self.tune),
             "--answers", str(answers)],
            text=True, capture_output=True, check=False)
        self.assertEqual(0, save.returncode, save.stderr)
        check = subprocess.run(
            [sys.executable, script, "session", "check", "--tune", str(self.tune)],
            text=True, capture_output=True, check=False)
        self.assertEqual(0, check.returncode, check.stderr)
        self.assertTrue(json.loads(check.stdout)["hash_matches"])


if __name__ == "__main__":
    unittest.main()
