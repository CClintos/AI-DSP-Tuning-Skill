"""Behavior tests for install preflight and optimizer benchmarks."""

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "helix-rew-tuner" / "scripts"
PREFLIGHT = SCRIPTS / "preflight.py"
BENCHMARK = SCRIPTS / "benchmark.py"


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PreflightTests(unittest.TestCase):
    def test_json_reports_runtime_dependencies_paths_and_readiness(self):
        """Dropping a required readiness check must make preflight incomplete."""
        run = subprocess.run(
            [sys.executable, str(PREFLIGHT), "--json"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )

        self.assertEqual(0, run.returncode, run.stderr)
        report = json.loads(run.stdout)
        self.assertTrue(report["ready"])
        self.assertEqual("helix-rew-tuner", report["skill"])
        self.assertEqual({"python", "numpy", "scipy"},
                         set(report["runtime"]))
        self.assertEqual({"skill_root", "scripts", "references"},
                         set(report["paths"]))
        for section in (report["runtime"], report["paths"]):
            for check in section.values():
                self.assertIsInstance(check["ok"], bool)
                self.assertTrue(check["message"])
        self.assertEqual([], report["failures"])

    def test_missing_dependency_reports_an_actionable_install_command(self):
        """A bare import error must not leave the user without a remedy."""
        preflight = load_script("preflight_for_test", PREFLIGHT)

        def missing_scipy(name):
            if name == "scipy":
                raise ImportError("simulated missing scipy")
            return __import__(name)

        report = preflight.collect_preflight(module_loader=missing_scipy)

        self.assertFalse(report["ready"])
        self.assertFalse(report["runtime"]["scipy"]["ok"])
        self.assertIn("python -m pip install -r", report["runtime"]["scipy"]["message"])
        self.assertTrue(any("SciPy" in failure for failure in report["failures"]))

    def test_old_dependency_version_is_not_reported_ready(self):
        """Ignoring the minimum version must allow an incompatible import."""
        preflight = load_script("preflight_old_version_test", PREFLIGHT)

        def old_scipy(name):
            if name == "scipy":
                return types.SimpleNamespace(__version__="0.1.0")
            return __import__(name)

        report = preflight.collect_preflight(module_loader=old_scipy)

        self.assertFalse(report["ready"])
        self.assertFalse(report["runtime"]["scipy"]["ok"])
        self.assertIn("too old", report["runtime"]["scipy"]["message"])
        self.assertIn("python -m pip install -r", report["runtime"]["scipy"]["message"])

    def test_prerelease_dependency_versions_are_not_reported_ready(self):
        """Flattening PEP 440 suffixes must not admit prereleases as finals."""
        preflight = load_script("preflight_prerelease_test", PREFLIGHT)

        for version in ("1.9.0rc1", "1.9.0.dev0"):
            with self.subTest(version=version):
                def prerelease_scipy(name, injected=version):
                    if name == "scipy":
                        return types.SimpleNamespace(__version__=injected)
                    return __import__(name)

                report = preflight.collect_preflight(
                    module_loader=prerelease_scipy)

                self.assertFalse(report["ready"])
                self.assertFalse(report["runtime"]["scipy"]["ok"])
                self.assertIn("final release", report["runtime"]["scipy"]["message"])
                self.assertIn("python -m pip install -r",
                              report["runtime"]["scipy"]["message"])

    def test_newer_final_dependency_version_is_reported_ready(self):
        """Rejecting suffixes must not reject a newer ordinary final release."""
        preflight = load_script("preflight_newer_final_test", PREFLIGHT)

        def newer_scipy(name):
            if name == "scipy":
                return types.SimpleNamespace(__version__="1.10.0")
            return __import__(name)

        report = preflight.collect_preflight(module_loader=newer_scipy)

        self.assertTrue(report["ready"])
        self.assertTrue(report["runtime"]["scipy"]["ok"])


class BenchmarkTests(unittest.TestCase):
    def test_missing_stable_peak_filter_is_reported_as_a_failed_guard(self):
        """An empty robust fit must produce a guard failure, not crash JSON."""
        benchmark = load_script("benchmark_empty_fit_test", BENCHMARK)

        def empty_fit(*_args, **_kwargs):
            return [], {
                "bands_used": 0,
                "position_scores_before": [2.0, 2.0, 2.0],
                "position_scores_after": [2.0, 2.0, 2.0],
            }

        case = benchmark.stable_peaks_case(fitter=empty_fit)

        self.assertFalse(all(guard["passed"] for guard in case["guards"]))
        self.assertEqual("shared peak receives a filter", case["guards"][0]["name"])

    def test_json_runs_all_cases_and_reports_every_declared_guard(self):
        """Removing a required synthetic scenario must fail the benchmark contract."""
        run = subprocess.run(
            [sys.executable, str(BENCHMARK), "--json"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )

        self.assertEqual(0, run.returncode, run.stderr)
        report = json.loads(run.stdout)
        self.assertTrue(report["deterministic"])
        self.assertTrue(report["passed"])
        self.assertEqual(
            {"stable_peaks", "wandering_nulls", "level_offsets",
             "confidence_blocked_lr_matching", "worst_position_harm"},
            {case["id"] for case in report["cases"]},
        )
        self.assertEqual(5, report["summary"]["total"])
        self.assertEqual(5, report["summary"]["passed"])
        self.assertEqual(0, report["summary"]["failed"])
        for case in report["cases"]:
            self.assertTrue(case["passed"], case)
            self.assertTrue(case["guards"])
            for guard in case["guards"]:
                self.assertEqual(
                    {"name", "passed", "actual", "operator", "expected"},
                    set(guard),
                )

    def test_failed_guard_makes_main_return_nonzero_and_names_the_failure(self):
        """Ignoring a false guard must not produce a successful process status."""
        benchmark = load_script("benchmark_for_test", BENCHMARK)

        def failing_case():
            return {
                "id": "forced_failure",
                "metrics": {"loss_db": 0.5},
                "guards": [benchmark.make_guard(
                    "worst-position loss", 0.5, "<=", 0.25)],
            }

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = benchmark.main(["--json"], case_runners=[failing_case])

        report = json.loads(stdout.getvalue())
        self.assertEqual(1, exit_code)
        self.assertFalse(report["passed"])
        self.assertEqual(1, report["summary"]["failed"])
        self.assertEqual("worst-position loss", report["failures"][0]["guard"])

    def test_json_output_is_deterministic(self):
        """Introducing randomness must change repeated benchmark output."""
        command = [sys.executable, str(BENCHMARK), "--json"]
        first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True,
                               check=False)
        second = subprocess.run(command, cwd=ROOT, text=True, capture_output=True,
                                check=False)

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(first.stdout, second.stdout)


if __name__ == "__main__":
    unittest.main()
