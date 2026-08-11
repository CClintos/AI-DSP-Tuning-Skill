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

    def test_invalid_skill_metadata_is_rejected(self) -> None:
        """Failing open on malformed frontmatter must not publish an invalid skill."""
        skill_md = self.root / "helix-rew-tuner" / "SKILL.md"
        skill_md.write_text(
            VALID_SKILL.replace("name: helix-rew-tuner", "name: Wrong Name"),
            encoding="utf-8",
        )

        result = self.run_build("--check")

        self.assertEqual(1, result.returncode)
        self.assertIn("invalid SKILL.md metadata", result.stdout + result.stderr)
        self.assertFalse((self.root / "AGENTS.md").exists())
        self.assertFalse((self.root / "helix-rew-tuner.skill").exists())

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

    def test_check_accepts_fresh_generated_outputs(self) -> None:
        """A checker that cannot accept its own build output is unusable in CI."""
        self.write_outputs()

        result = self.run_build("--check")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("generated files and package are current", result.stdout)


if __name__ == "__main__":
    unittest.main()
