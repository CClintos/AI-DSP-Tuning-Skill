#!/usr/bin/env python3
"""Generate the Codex wrapper and deterministic ``.skill`` package."""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
import re
import sys
import unicodedata
import zipfile


SKILL_DIR_NAME = "helix-rew-tuner"
ARCHIVE_NAME = f"{SKILL_DIR_NAME}.skill"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
TEXT_SUFFIXES = {".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}


class BuildError(ValueError):
    """Raised when source inputs cannot produce a valid skill."""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise BuildError(f"cannot read {path}: {exc}") from exc


def _frontmatter(skill_md: Path) -> dict[str, str]:
    text = _read_text(skill_md)
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise BuildError("invalid SKILL.md metadata: missing opening frontmatter delimiter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise BuildError("invalid SKILL.md metadata: missing closing frontmatter delimiter") from exc

    metadata: dict[str, str] = {}
    current: str | None = None
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*):(?:\s*(.*))?", line)
        if match:
            current = match.group(1)
            value = (match.group(2) or "").strip()
            if current in metadata:
                raise BuildError(f"invalid SKILL.md metadata: duplicate field {current!r}")
            metadata[current] = "" if value in {">", ">-", "|", "|-"} else value
            continue
        if line.startswith((" ", "\t")) and current:
            metadata[current] = " ".join(
                part for part in (metadata[current], line.strip()) if part
            )
            continue
        raise BuildError(f"invalid SKILL.md metadata line: {line!r}")

    name = metadata.get("name", "")
    description = metadata.get("description", "")
    if name != SKILL_DIR_NAME or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise BuildError(
            f"invalid SKILL.md metadata: name must be {SKILL_DIR_NAME!r}"
        )
    if not description:
        raise BuildError("invalid SKILL.md metadata: description is required")
    if len(description) > 1024:
        raise BuildError("invalid SKILL.md metadata: description exceeds 1024 characters")
    return metadata


def _validate_openai_metadata(path: Path) -> None:
    text = _read_text(path)
    required = {
        "display_name": r'\s*"[^"\r\n]+"\s*',
        "short_description": r'\s*"[^"\r\n]+"\s*',
        "default_prompt": r'\s*"[^"\r\n]*\$helix-rew-tuner[^"\r\n]*"\s*',
    }
    if not re.search(r"(?m)^interface:\s*$", text):
        raise BuildError("invalid agents/openai.yaml metadata: missing interface mapping")
    for field, value_pattern in required.items():
        matches = re.findall(rf"(?m)^\s{{2}}{field}:({value_pattern})$", text)
        if len(matches) != 1:
            raise BuildError(
                f"invalid agents/openai.yaml metadata: {field} must be present once and quoted"
            )


def _heading_slug(heading: str) -> str:
    heading = re.sub(r"<[^>]+>", "", heading)
    heading = heading.replace("`", "").strip().lower()
    kept: list[str] = []
    for char in heading:
        category = unicodedata.category(char)
        if char in {" ", "-", "_"} or category[0] in {"L", "N"}:
            kept.append(char)
    return re.sub(r"[\s-]+", "-", "".join(kept)).strip("-")


def _validate_methodology_anchors(path: Path) -> None:
    text = _read_text(path)
    counts: dict[str, int] = {}
    anchors: set[str] = set()
    for match in re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", text):
        base = _heading_slug(match.group(1))
        if not base:
            continue
        count = counts.get(base, 0)
        counts[base] = count + 1
        anchors.add(base if count == 0 else f"{base}-{count}")

    for target in re.findall(r"\[[^\]\r\n]+\]\(#([^)\s]+)\)", text):
        if target not in anchors:
            raise BuildError(f"unresolved Markdown anchor #{target} in {path}")


def _validate_sources(root: Path) -> None:
    skill = root / SKILL_DIR_NAME
    required = (
        skill / "SKILL.md",
        skill / "agents" / "openai.yaml",
        skill / "references" / "core_workflow.md",
        skill / "references" / "methodology.md",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise BuildError("missing required skill file(s): " + ", ".join(missing))
    _frontmatter(skill / "SKILL.md")
    _validate_openai_metadata(skill / "agents" / "openai.yaml")
    _validate_methodology_anchors(skill / "references" / "methodology.md")


def _agents_bytes(root: Path) -> bytes:
    core = _read_text(root / SKILL_DIR_NAME / "references" / "core_workflow.md")
    core = core.rstrip() + "\n"
    wrapper = f"""\
<!-- Generated by tools/build_skill.py from helix-rew-tuner/references/core_workflow.md. -->
<!-- Do not edit AGENTS.md directly; run: python tools/build_skill.py --write -->

This repository contains the `$helix-rew-tuner` skill. Apply it when the user
asks to diagnose, tune, or verify a supported Helix or Alpine car-audio DSP
from REW measurements or supported tune files. Trigger on that intent even if
the user does not name the skill or file formats explicitly.

Repository paths in the canonical workflow are relative to
`helix-rew-tuner/`. Use the scripts there as the deterministic layer, and read
the routed references before proposing or writing a change.

{core}"""
    return wrapper.encode("utf-8")


def _package_paths(skill_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for path in skill_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(skill_dir)
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        paths.append(path)
    return sorted(paths, key=lambda path: path.relative_to(skill_dir).as_posix())


def _packaged_file_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return data


def _archive_bytes(root: Path) -> bytes:
    skill_dir = root / SKILL_DIR_NAME
    output = BytesIO()
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as package:
        for path in _package_paths(skill_dir):
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            package.writestr(
                info,
                _packaged_file_bytes(path),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    return output.getvalue()


def write(root: Path) -> None:
    root = root.resolve()
    _validate_sources(root)
    (root / "AGENTS.md").write_bytes(_agents_bytes(root))
    (root / ARCHIVE_NAME).write_bytes(_archive_bytes(root))


def check(root: Path) -> list[str]:
    root = root.resolve()
    _validate_sources(root)
    failures: list[str] = []
    agents = root / "AGENTS.md"
    archive = root / ARCHIVE_NAME
    if not agents.is_file() or agents.read_bytes() != _agents_bytes(root):
        failures.append("AGENTS.md is stale; run python tools/build_skill.py --write")
    if not archive.is_file() or archive.read_bytes() != _archive_bytes(root):
        failures.append(
            f"{ARCHIVE_NAME} is stale; run python tools/build_skill.py --write"
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="validate without writing")
    mode.add_argument("--write", action="store_true", help="regenerate build outputs")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    try:
        if args.write:
            write(args.root)
            print("generated AGENTS.md and helix-rew-tuner.skill")
            return 0
        failures = check(args.root)
    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print("generated files and package are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
