"""Layer-1 skill evals (see evals/README.md): end-to-end known answers, write
safety, CLI error shape, loader robustness, docs <-> CLI agreement, package
hygiene and the eval data itself. Everything is synthetic and deterministic."""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "helix-rew-tuner"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

import alpine_jssh  # noqa: E402
import measure  # noqa: E402
import pct6  # noqa: E402
import pipeline  # noqa: E402
import tunelib  # noqa: E402


GRID = 20 * (2 ** (np.arange(0, 10 * 48 + 1) / 48.0))
GRID = GRID[GRID <= 20000]


def _target_on_grid():
    tf, tdb = np.loadtxt(SKILL / "assets" / "default_incar_target.txt", unpack=True,
                         comments="*")
    return np.interp(np.log10(GRID), np.log10(tf), tdb)


def _write_export(path, spl):
    rows = "\n".join("%.3f %.3f" % (f, s) for f, s in zip(GRID, spl))
    Path(path).write_text("* Freq(Hz) SPL(dB)\n" + rows + "\n", encoding="utf-8")


def _run(*args, cwd=None):
    env = dict(os.environ)
    env.pop("HELIX_TUNER_DEBUG", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True,
                          text=True, cwd=cwd, env=env)


class KnownAnswerProposeTests(unittest.TestCase):
    """propose on synthetic systems whose right answer is known."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.base = _target_on_grid() + 80.0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def propose(self, name, faults_per_position, seed=7, extra=(), full=False):
        rng = np.random.default_rng(seed)
        files = []
        for i, faults in enumerate(faults_per_position):
            path = self.dir / ("%s_%d.txt" % (name, i))
            _write_export(path, self.base + tunelib.cascade_db(GRID, faults)
                          + rng.normal(0.0, 0.3, GRID.size))
            files.append(path)
        flag = ["--measurement", files[0]] if len(files) == 1 else ["--positions", *files]
        run = _run(SCRIPTS / "pipeline.py", "propose", *flag, "--target", "default", *extra)
        self.assertEqual(0, run.returncode, run.stderr)
        report = json.loads(run.stdout)
        return report if full else report["proposal"]

    def assert_one_cut_near(self, proposal, hz):
        bands = proposal["bands"]
        near = [b for b in bands if abs(np.log2(b["f_hz"] / hz)) <= 1 / 3]
        self.assertTrue(near, bands)
        self.assertTrue(all(b["gain_db"] < 0 for b in near), bands)
        self.assertTrue(-6.5 <= sum(b["gain_db"] for b in near) <= -3.0, bands)
        self.assertFalse([b for b in bands if b["gain_db"] > 0], bands)

    def test_a_single_position_peak_is_cut(self):
        self.assert_one_cut_near(self.propose("a", [[(500.0, 2.0, 5.0)]]), 500.0)

    def test_b_a_peak_shared_by_three_positions_is_cut(self):
        self.assert_one_cut_near(self.propose("b", [[(500.0, 2.0, 5.0)]] * 3), 500.0)

    def test_e_a_low_shared_peak_is_cut(self):
        self.assert_one_cut_near(self.propose("e", [[(150.0, 3.0, 6.0)]] * 3), 150.0)

    def test_s01_a_shared_peak_survives_notches_that_move_between_seats(self):
        """The realistic case: every cabin seat has its own comb notches."""
        seats = [[(150.0, 3.0, 6.0), (notch, 8.0, -9.0)] for notch in (1200.0, 1300.0, 1450.0)]
        proposal = self.propose("s01", seats)
        self.assert_one_cut_near(proposal, 150.0)
        kept = [b for b in proposal["bands"] if abs(np.log2(b["f_hz"] / 150.0)) <= 1 / 3]
        self.assertIn(kept[0].get("action"), ("APPLY", "REVIEW"), kept)

    def test_m1_one_mmm_run_still_cuts_a_peak_behind_a_narrow_dip(self):
        """One moving-mic run: a narrow dip that outranks the peak used to end the fit."""
        proposal = self.propose("m1", [[(150.0, 3.0, 4.0), (3000.0, 15.0, -10.0)]],
                                extra=("--capture", "mmm"))
        self.assert_one_cut_near(proposal, 150.0)

    def test_m2_one_mmm_run_notch_draws_one_trial_not_a_stack(self):
        """Three stacked +3 dB trials into one notch is one trial and two rejections."""
        proposal = self.propose("m2", [[(150.0, 3.0, 5.0), (900.0, 3.0, -8.0)]],
                                extra=("--capture", "mmm"))
        self.assert_one_cut_near(proposal, 150.0)
        near = [b for b in proposal["needs_trial"] if abs(np.log2(b["f_hz"] / 900.0)) <= 1 / 3]
        self.assertLessEqual(len(near), 1, proposal["needs_trial"])
        self.assertTrue([r for r in proposal["rejected"] if "stacks" in r.get("reason", "")]
                        or len(near) <= 1)

    def test_m3_a_single_sweep_never_proposes_stacked_boosts(self):
        """Without phase a boost is ungated: the cascade must still respect +3 dB."""
        report = self.propose("m3", [[(150.0, 3.0, 5.0), (900.0, 3.0, -8.0)]], full=True)
        self.assertLessEqual(report["prediction"]["max_cascade_boost_db"], 3.25)
        boosts = [b["f_hz"] for b in report["proposal"]["bands"] if b["gain_db"] > 0]
        for i, a in enumerate(boosts):
            for b in boosts[i + 1:]:
                self.assertGreater(abs(np.log2(a / b)), 1 / 3, boosts)

    def test_c_known_gap_two_peaks_draw_no_compensating_boost(self):
        """Independent references must prevent peak-biased compensating boosts."""
        proposal = self.propose("c", [[(500.0, 2.0, 5.0), (2500.0, 1.5, 3.0)]] * 3)
        self.assertFalse([b for b in proposal["bands"] if b["gain_db"] > 0], proposal)

    def test_d_known_gap_two_peaks_and_notches_keep_the_500hz_cut(self):
        """A stable 500 Hz excess must still earn its cut with moving notches."""
        seats = [[(500.0, 2.0, 5.0), (2500.0, 1.5, 3.0), (notch, 8.0, -9.0)]
                 for notch in (900.0, 1300.0, 1800.0)]
        self.assert_one_cut_near(self.propose("d", seats), 500.0)


class CliSafetyAndErrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.meas = self.dir / "meas.txt"
        _write_export(self.meas, _target_on_grid() + 80.0)

    def assert_one_line_error(self, run):
        self.assertNotEqual(0, run.returncode)
        self.assertNotIn("Traceback", run.stderr)
        lines = [ln for ln in run.stderr.splitlines() if ln.strip()]
        self.assertEqual(1, len(lines), run.stderr)
        self.assertTrue(lines[0].startswith("error: "), run.stderr)

    def test_report_out_cannot_overwrite_an_input(self):
        before = self.meas.read_bytes()
        run = _run(SCRIPTS / "pipeline.py", "analyze", "--measurement", self.meas,
                   "--target", "default", "--out", self.meas)
        self.assert_one_line_error(run)
        self.assertIn("inputs", run.stderr)
        self.assertEqual(before, self.meas.read_bytes())

    def test_report_out_cannot_take_a_tune_extension(self):
        tune = self.dir / "mytune.afpx"
        tune.write_bytes(b"not touched")
        run = _run(SCRIPTS / "pipeline.py", "analyze", "--measurement", self.meas,
                   "--target", "default", "--out", tune)
        self.assert_one_line_error(run)
        self.assertEqual(b"not touched", tune.read_bytes())

    def test_report_out_still_writes_a_new_json(self):
        out = self.dir / "report.json"
        run = _run(SCRIPTS / "pipeline.py", "analyze", "--measurement", self.meas,
                   "--target", "default", "--out", out)
        self.assertEqual(0, run.returncode, run.stderr)
        self.assertIn("tilt", json.loads(out.read_text(encoding="utf-8")))

    def test_missing_input_is_one_line_not_a_traceback(self):
        run = _run(SCRIPTS / "pipeline.py", "analyze", "--measurement",
                   self.dir / "nope.txt", "--target", "default")
        self.assert_one_line_error(run)
        self.assertIn("nope.txt", run.stderr)

    def test_a_file_that_is_not_an_export_is_one_line(self):
        junk = self.dir / "junk.txt"
        junk.write_text("hello\nworld\n", encoding="utf-8")
        run = _run(SCRIPTS / "pipeline.py", "propose", "--measurement", junk,
                   "--target", "default")
        self.assert_one_line_error(run)

    def test_debug_variable_restores_the_traceback(self):
        env = dict(os.environ, HELIX_TUNER_DEBUG="1", PYTHONDONTWRITEBYTECODE="1")
        run = subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), "analyze",
                              "--measurement", str(self.dir / "nope.txt"),
                              "--target", "default"], capture_output=True, text=True,
                             env=env)
        self.assertNotEqual(0, run.returncode)
        self.assertIn("Traceback", run.stderr)

    def test_pct6_decode_never_replaces_an_existing_decode(self):
        src = self.dir / "tune.pct6"
        pct6._encode_bytes_unchecked(b'<ATF><OC ON="1"></OC></ATF>', src)
        first = _run(SCRIPTS / "pct6.py", "decode", src)
        self.assertEqual(0, first.returncode, first.stderr)
        decoded = self.dir / "tune.decoded.xml"
        decoded.write_text("my edits", encoding="utf-8")
        second = _run(SCRIPTS / "pct6.py", "decode", src)
        self.assertNotEqual(0, second.returncode)
        self.assertEqual("my edits", decoded.read_text(encoding="utf-8"))

    def test_alpine_decode_never_replaces_an_existing_decode(self):
        src = self.dir / "preset.jssh"
        alpine_jssh._encode_unchecked(alpine_jssh._make_synthetic_preset(), src)
        first = _run(SCRIPTS / "alpine_jssh.py", "decode", src)
        self.assertEqual(0, first.returncode, first.stderr)
        decoded = self.dir / "preset.decoded.json"
        decoded.write_text("my edits", encoding="utf-8")
        second = _run(SCRIPTS / "alpine_jssh.py", "decode", src)
        self.assertNotEqual(0, second.returncode)
        self.assertEqual("my edits", decoded.read_text(encoding="utf-8"))

    def test_decay_fdw_cannot_overwrite_its_input(self):
        ir = self.dir / "ir.txt"
        t = np.arange(4096) / 48000.0
        x = np.exp(-t * 400.0) * np.sin(2 * np.pi * 1000.0 * t)
        ir.write_text("* IR\n" + "\n".join("%.8f %.8e" % p for p in zip(t, x)) + "\n",
                      encoding="utf-8")
        before = ir.read_bytes()
        run = _run(SCRIPTS / "decay.py", "fdw", ir, "--out", ir)
        self.assertNotEqual(0, run.returncode)
        self.assertEqual(before, ir.read_bytes())


class LoaderRobustnessTests(unittest.TestCase):
    """The file shapes a Windows user's tools actually produce."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.f = GRID[::4]
        self.spl = 75.0 + 3.0 * np.sin(np.log2(self.f))
        self.text = ("* Measurement: Front L\n* Smoothing: 1/48 octave\n"
                     "* Freq(Hz), SPL(dB), Phase(degrees)\n"
                     + "".join("%.3f, %.3f, %.3f\n" % (a, b, -a / 100.0)
                               for a, b in zip(self.f, self.spl)))

    def check(self, name, data):
        path = self.dir / name
        path.write_bytes(data)
        f, s, ph, _coh = measure.load_text_export(str(path))
        np.testing.assert_allclose(f, np.round(self.f, 3), atol=1e-3)
        np.testing.assert_allclose(s, np.round(self.spl, 3), atol=1e-3)
        self.assertIsNotNone(ph)
        return measure.read_export_header(str(path))

    def test_utf16_le_with_bom(self):
        hdr = self.check("le.txt", ("﻿" + self.text).encode("utf-16-le"))
        self.assertEqual("1/48 octave", hdr["smoothing"])

    def test_utf16_be_with_bom(self):
        self.check("be.txt", ("﻿" + self.text).encode("utf-16-be"))

    def test_utf16_le_without_bom(self):
        self.check("le_nobom.txt", self.text.encode("utf-16-le"))

    def test_utf8_with_bom(self):
        hdr = self.check("bom.txt", ("﻿" + self.text).encode("utf-8"))
        self.assertEqual("1/48 octave", hdr["smoothing"])

    def test_spreadsheet_quoted_csv(self):
        quoted = '"Freq","SPL","Phase"\n' + "".join(
            '"%.3f","%.3f","%.3f"\n' % (a, b, -a / 100.0) for a, b in zip(self.f, self.spl))
        self.check("quoted.csv", quoted.encode("utf-8"))

    def test_quoted_decimal_comma_semicolon_csv(self):
        rows = "".join(('"%.3f";"%.3f";"%.3f"\n' % (a, b, -a / 100.0)).replace(".", ",")
                       for a, b in zip(self.f, self.spl))
        self.check("eu.csv", ('"Frequenz";"SPL";"Phase"\n' + rows).encode("utf-8"))

    def test_quoted_target_curve(self):
        path = self.dir / "target.csv"
        path.write_text('"Hz","dB"\n"20","9"\n"1000","0"\n"20000","-7"\n', encoding="utf-8")
        t = measure.load_target(str(path), np.array([20.0, 1000.0, 20000.0]))
        np.testing.assert_allclose(t, [9.0, 0.0, -7.0])


def _pipeline_parser():
    """The real argparse parser pipeline.main() builds."""
    captured = {}
    original = argparse.ArgumentParser.parse_args

    class _Stop(Exception):
        pass

    def grab(self, *args, **kwargs):
        captured.setdefault("parser", self)
        raise _Stop()

    argparse.ArgumentParser.parse_args = grab
    old_argv = sys.argv
    sys.argv = ["pipeline.py"]
    try:
        pipeline.main()
    except _Stop:
        pass
    finally:
        argparse.ArgumentParser.parse_args = original
        sys.argv = old_argv
    return captured["parser"]


def _commands(parser, prefix=""):
    out = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                key = (prefix + " " + name).strip()
                out[key] = {o for a in sub._actions for o in a.option_strings}
                out.update(_commands(sub, key))
    return out


class DocsCliAgreementTests(unittest.TestCase):
    """Every documented pipeline.py command and flag must exist."""

    @classmethod
    def setUpClass(cls):
        cls.commands = _commands(_pipeline_parser())
        cls.top = {c.split()[0] for c in cls.commands}
        cls.all_flags = set().union(*cls.commands.values())
        cls.docs = {p: p.read_text(encoding="utf-8")
                    for p in [*sorted(SKILL.rglob("*.md")), ROOT / "README.md"]}

    # A command is written after one space, or after a line wrap. Wider gaps
    # are column alignment (README's file tree), where the next word is prose.
    MENTION = re.compile(r"pipeline\.py`?(?: |\r?\n[ \t]*)`?([a-z][a-z-]*)")
    PROSE = {"now", "and", "or", "to", "the", "with", "is", "for", "in", "on", "as", "a"}

    def test_every_documented_subcommand_exists(self):
        for path, text in self.docs.items():
            for match in self.MENTION.finditer(text):
                word = match.group(1)
                if word in self.top or word in self.PROSE:
                    continue
                line = text.count("\n", 0, match.start()) + 1
                self.fail("%s:%d mentions pipeline.py %s, which is not a command"
                          % (path.name, line, word))

    def test_every_flag_near_a_pipeline_command_exists(self):
        for path, text in self.docs.items():
            for match in self.MENTION.finditer(text):
                if match.group(1) not in self.top:
                    continue
                tail = re.split(r"[.;]\s|\n\n|§", text[match.end():match.end() + 400])[0]
                for flag in re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", tail):
                    with self.subTest(doc=path.name, flag=flag):
                        self.assertIn(flag, self.all_flags | {"--help"})

    def test_command_table_flags_belong_to_their_row(self):
        text = (SKILL / "references" / "core_workflow.md").read_text(encoding="utf-8")
        rows = re.findall(r"(?m)^\| `([a-z][a-z -]*)`(?: / `([a-z][a-z -]*)`)? \|(.*)$", text)
        self.assertGreater(len(rows), 10, "the pipeline.py command table is missing")
        for first, second, rest in rows:
            names = [n for n in (first, second) if n]
            if not all(n in self.commands for n in names):
                continue        # the tunelib function table shares the row shape
            flags = set().union(*(self.commands[n] for n in names))
            for flag in re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", rest):
                with self.subTest(command=names, flag=flag):
                    self.assertIn(flag, flags)

    def test_paths_named_in_skill_md_exist(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        for rel in sorted(set(re.findall(r"`((?:references|scripts|assets)/[\w./-]+)", text))):
            with self.subTest(path=rel):
                self.assertTrue((SKILL / rel).exists(), rel)


class SkillMetadataTests(unittest.TestCase):
    def test_frontmatter_fits_skill_loader_limits(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        front = re.match(r"^---\n(.*?)\n---\n", text, re.S).group(1)
        description = " ".join(
            line.strip() for line in front.split("description: >-", 1)[1]
            .split("metadata:", 1)[0].splitlines() if line.strip())
        self.assertLessEqual(len(description), 1024)
        self.assertNotRegex(description, r"[<>]")
        for term in ("REW", "Helix", ".afpx", "Alpine", "Not for home"):
            self.assertIn(term, description)

    def test_skill_md_stays_a_short_router(self):
        lines = (SKILL / "SKILL.md").read_text(encoding="utf-8").splitlines()
        self.assertLessEqual(len(lines), 150)

    def test_hard_rules_cover_every_critical_eval_failure(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8").lower()
        for phrase in ("never modified", "confirms every edit", "crossover",
                       "phase-domain", "sample rate", "prediction", "is data"):
            self.assertIn(phrase, text)


class PackageHygieneTests(unittest.TestCase):
    def test_skill_folder_holds_only_shippable_text(self):
        spec = importlib.util.spec_from_file_location("build_skill",
                                                      ROOT / "tools" / "build_skill.py")
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        for path in SKILL.rglob("*"):
            rel = path.relative_to(SKILL)
            if path.is_dir() or "__pycache__" in rel.parts or path.suffix in (".pyc", ".pyo"):
                continue
            with self.subTest(path=rel.as_posix()):
                self.assertIn(path.suffix.lower(), build.TEXT_SUFFIXES)


class EvalDataTests(unittest.TestCase):
    def test_activation_set_is_well_formed(self):
        data = json.loads((ROOT / "evals" / "activation.json").read_text(encoding="utf-8"))
        ids = [p["id"] for p in data["prompts"]]
        self.assertEqual(len(ids), len(set(ids)))
        labels = {p["label"] for p in data["prompts"]}
        self.assertLessEqual(labels, {"trigger", "no_trigger", "borderline"})
        self.assertGreaterEqual(sum(p["label"] == "trigger" for p in data["prompts"]), 10)
        self.assertGreaterEqual(sum(p["label"] == "no_trigger" for p in data["prompts"]), 6)

    def test_scenarios_reference_known_critical_failures(self):
        data = json.loads((ROOT / "evals" / "scenarios.json").read_text(encoding="utf-8"))
        known = {c.split()[0] for c in data["critical_failures"]}
        ids = [s["id"] for s in data["scenarios"]]
        self.assertEqual(len(ids), len(set(ids)))
        for scenario in data["scenarios"]:
            with self.subTest(scenario=scenario["id"]):
                self.assertTrue(scenario["must"])
                self.assertLessEqual(set(scenario["critical"]), known)

    def test_fixture_generator_builds_loadable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = _run(ROOT / "evals" / "make_fixtures.py", tmp)
            self.assertEqual(0, run.returncode, run.stderr)
            names = {p.name for p in Path(tmp).iterdir()}
            for name in ("mytune.afpx", "pos1.txt", "pos2.txt", "pos3.txt", "single.txt",
                         "after1.txt", "mmm_full.txt", "solo_l.txt", "solo_r.txt",
                         "utf16_export.txt", "injected.txt", "locked.pct6", "preset.jssh"):
                self.assertIn(name, names)
            f, s, ph, _ = measure.load_text_export(os.path.join(tmp, "utf16_export.txt"))
            self.assertGreater(len(f), 400)
            self.assertIsNotNone(ph)
            inspect = _run(SCRIPTS / "afpx.py", "inspect", Path(tmp) / "mytune.afpx")
            self.assertEqual(0, inspect.returncode, inspect.stderr)
            self.assertIn("4 output channels", inspect.stdout)


if __name__ == "__main__":
    unittest.main()
