"""Behavior tests for canonical workflow generation and skill packaging."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "tools" / "build_skill.py"


VALID_SKILL = """\
---
name: helix-rew-tuner
description: >-
  Diagnose and tune supported car DSP systems from REW measurements.
---

# Helix REW tuner

Read `references/core_workflow.md` before proposing changes.
"""

VALID_OPENAI_METADATA = """\
interface:
  display_name: "Helix REW Tuner"
  short_description: "Diagnose and tune car DSPs from REW data"
  default_prompt: "Use $helix-rew-tuner to diagnose my measurements."
"""

VALID_METHODOLOGY = """\
# Methodology

## Contents

- [Measurement setup](#measurement-setup)
- [Verification and honesty](#verification-and-honesty)

## Measurement setup

Keep the microphone fixed.

## Verification and honesty

Re-measure after changes.
"""


class RepositoryReleaseContractsTests(unittest.TestCase):
    def test_afpx_write_guidance_routes_through_plan_apply_and_generated_doctrine(self):
        core = (REPO_ROOT / "helix-rew-tuner" / "references" / "core_workflow.md").read_text(
            encoding="utf-8")
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        required = (
            "pipeline.py plan", "pipeline.py apply", "tune_plan_schema.md",
            "source_sha256", "output_path", "confirmations", "verification manifest",
            "Direct `afpx.py` write helpers are implementation/reference only",
        )
        for token in required:
            with self.subTest(document="core_workflow", token=token):
                self.assertIn(token, core)
            with self.subTest(document="README", token=token):
                self.assertIn(token, readme)
        self.assertIn(core.strip(), agents)

    def test_readme_records_both_verified_pct6_versions_with_caveat(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        pct6 = readme[readme.index("## Beta: `.pct6`"):readme.index("## Beta: Alpine")]
        self.assertIn("6.01.08", pct6)
        self.assertIn("6.03.04", pct6)
        self.assertIn("version-fragile", pct6)

    def test_ci_whitespace_gate_checks_a_committed_change(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "validate.yml").read_text(
            encoding="utf-8")
        self.assertIn("git show --check --oneline HEAD", workflow)


class BuildSkillTests(unittest.TestCase):
    """Run the real build CLI against controlled repository fixtures."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        skill = self.root / "helix-rew-tuner"
        (skill / "agents").mkdir(parents=True)
        (skill / "references").mkdir()
        (skill / "scripts").mkdir()
        (skill / "assets").mkdir()
        (skill / "SKILL.md").write_text(VALID_SKILL, encoding="utf-8")
        (skill / "agents" / "openai.yaml").write_text(
            VALID_OPENAI_METADATA, encoding="utf-8"
        )
        (skill / "references" / "core_workflow.md").write_text(
            "# Canonical workflow\n\nClassify before correcting.\n", encoding="utf-8"
        )
        (skill / "references" / "methodology.md").write_text(
            VALID_METHODOLOGY, encoding="utf-8"
        )
        (skill / "scripts" / "example.py").write_text(
            "print('example')\n", encoding="utf-8"
        )
        (skill / "assets" / "target.txt").write_text("20 0\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_build(self, mode: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(BUILD_SCRIPT), mode, "--root", str(self.root)],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def write_outputs(self) -> None:
        result = self.run_build("--write")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_check_detects_stale_generated_agents_without_mutating_it(self) -> None:
        """Skipping wrapper comparison must allow hand-edited doctrine to drift."""
        self.write_outputs()
        agents = self.root / "AGENTS.md"
        agents.write_text(agents.read_text(encoding="utf-8") + "stale\n", encoding="utf-8")
        before = agents.read_bytes()

        result = self.run_build("--check")

        self.assertEqual(1, result.returncode)
        self.assertIn("AGENTS.md is stale", result.stdout + result.stderr)
        self.assertEqual(before, agents.read_bytes())

    def test_check_detects_stale_archive_contents_without_mutating_it(self) -> None:
        """Ignoring source/package parity must accept an archive with obsolete code."""
        self.write_outputs()
        archive = self.root / "helix-rew-tuner.skill"
        before = archive.read_bytes()
        script = self.root / "helix-rew-tuner" / "scripts" / "example.py"
        script.write_text("print('changed')\n", encoding="utf-8")

        result = self.run_build("--check")

        self.assertEqual(1, result.returncode)
        self.assertIn("helix-rew-tuner.skill is stale", result.stdout + result.stderr)
        self.assertEqual(before, archive.read_bytes())

    def test_unexpected_skill_metadata_key_is_rejected_without_mutation(self) -> None:
        """Accepting extra frontmatter keys must let unsupported metadata ship."""
        self.write_outputs()
        skill_md = self.root / "helix-rew-tuner" / "SKILL.md"
        skill_md.write_text(
            skill_md.read_text(encoding="utf-8").replace(
                "---\n\n# Helix", "unexpected_key: true\n---\n\n# Helix"
            ),
            encoding="utf-8",
        )
        before = skill_md.read_bytes()

        result = self.run_build("--check")

        self.assertEqual(1, result.returncode)
        self.assertIn("SKILL.md is stale", result.stdout + result.stderr)
        self.assertEqual(before, skill_md.read_bytes())

    def test_malformed_openai_metadata_is_rejected_without_mutation(self) -> None:
        """Checking only required fields must accept otherwise malformed YAML."""
        self.write_outputs()
        metadata = self.root / "helix-rew-tuner" / "agents" / "openai.yaml"
        metadata.write_text(
            metadata.read_text(encoding="utf-8") + "broken: [\n", encoding="utf-8"
        )
        before = metadata.read_bytes()

        result = self.run_build("--check")

        self.assertEqual(1, result.returncode)
        self.assertIn("agents/openai.yaml is stale", result.stdout + result.stderr)
        self.assertEqual(before, metadata.read_bytes())

    def test_skill_without_canonical_workflow_route_is_rejected(self) -> None:
        """Valid frontmatter alone must not allow a wrapper to bypass doctrine."""
        self.write_outputs()
        skill_md = self.root / "helix-rew-tuner" / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        self.assertIn("references/core_workflow.md", text)
        skill_md.write_text(
            text.replace("references/core_workflow.md", "references/methodology.md"),
            encoding="utf-8",
        )

        result = self.run_build("--check")

        self.assertEqual(1, result.returncode)
        self.assertIn("SKILL.md is stale", result.stdout + result.stderr)

    def test_unresolved_methodology_anchor_is_rejected(self) -> None:
        """Dropping anchor validation must let broken navigation ship."""
        methodology = self.root / "helix-rew-tuner" / "references" / "methodology.md"
        methodology.write_text(
            VALID_METHODOLOGY.replace("#measurement-setup", "#missing-section"),
            encoding="utf-8",
        )

        result = self.run_build("--check")

        self.assertEqual(1, result.returncode)
        self.assertIn("unresolved Markdown anchor #missing-section", result.stdout + result.stderr)

    def test_write_is_byte_deterministic_and_normalizes_zip_metadata(self) -> None:
        """Using filesystem order or mtimes must change package bytes across builds."""
        self.write_outputs()
        archive = self.root / "helix-rew-tuner.skill"
        first = archive.read_bytes()
        source = self.root / "helix-rew-tuner" / "scripts" / "example.py"
        os.utime(source, (2_000_000_000, 2_000_000_000))

        self.write_outputs()

        self.assertEqual(first, archive.read_bytes())
        with zipfile.ZipFile(archive) as package:
            infos = package.infolist()
            names = [info.filename for info in infos]
            self.assertEqual(sorted(names), names)
            self.assertTrue(names)
            self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in infos))
            self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in infos))
            self.assertTrue(all(name.startswith("helix-rew-tuner/") for name in names))

    def test_archive_is_independent_of_text_checkout_line_endings(self) -> None:
        """Packaging raw checkout bytes must drift between Windows and Linux."""
        self.write_outputs()
        archive = self.root / "helix-rew-tuner.skill"
        first = archive.read_bytes()
        script = self.root / "helix-rew-tuner" / "scripts" / "example.py"
        lf_bytes = script.read_bytes().replace(b"\r\n", b"\n")
        script.write_bytes(lf_bytes.replace(b"\n", b"\r\n"))

        self.write_outputs()

        self.assertEqual(first, archive.read_bytes())

    def test_check_accepts_platform_line_endings_in_generated_text(self) -> None:
        """Raw wrapper comparison must report a CRLF checkout as stale."""
        self.write_outputs()
        generated_text = (
            self.root / "AGENTS.md",
            self.root / "helix-rew-tuner" / "SKILL.md",
            self.root / "helix-rew-tuner" / "agents" / "openai.yaml",
        )
        for path in generated_text:
            lf_bytes = path.read_bytes().replace(b"\r\n", b"\n")
            path.write_bytes(lf_bytes.replace(b"\n", b"\r\n"))

        result = self.run_build("--check")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_check_accepts_fresh_generated_outputs(self) -> None:
        """A checker that cannot accept its own build output is unusable in CI."""
        self.write_outputs()

        result = self.run_build("--check")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("generated files and package are current", result.stdout)


if __name__ == "__main__":
    unittest.main()
