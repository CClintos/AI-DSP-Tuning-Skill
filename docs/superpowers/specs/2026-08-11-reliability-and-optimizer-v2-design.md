# Reliability and Optimizer V2 Design

## Goal

Make the existing single `helix-rew-tuner` skill safer to install and use, more robust across repeated and multi-position measurements, and deterministic from analysis through verified tune-file output while retaining Alpine support in the same skill.

## Boundaries

- Keep Helix `.afpx`, beta Helix `.pct6`, and beta Alpine `.jssh` support in one installable skill.
- Keep Helix limits as the default only for Helix files; Alpine validation remains format-specific.
- Do not claim real-hardware validation from synthetic tests.
- Do not add crossover writes.
- Continue requiring explicit confirmation for delay, polarity, output-trim, shelf, and all-pass changes.
- Do not choose or add an open-source license without the repository owner's explicit license choice.

## Architecture

### Measurement and optimization

`tunelib.py` remains the numerical core. Partner matching will obey confidence weights from both channels. Spatial consistency will optionally align broadband capture level before measuring frequency-dependent variance, while reporting the removed offsets separately. A new robust multi-position PEQ fitter will optimize one filter set across all supplied traces with a median objective plus a worst-position tail penalty, while retaining the existing filter, boost, Q, mask, and confidence constraints.

### Deterministic plan and apply path

`pipeline.py analyze` remains read-only. New `plan` and `apply` commands will consume a versioned JSON plan. The plan records the source SHA-256, format, channel/slot edits, confirmation flags, and output path. Apply refuses stale input hashes, invalid limits, mixed phase/EQ edits in one crossover-adjacent region, and unconfirmed protected changes. It writes to a new file, decodes it, verifies the intended semantic differences, and emits a JSON verification manifest.

### Skill packaging

The skill remains one package. Alpine-specific detail moves from the core workflow into the existing Alpine reference, with concise routing rules retained in `SKILL.md`. `AGENTS.md` becomes a generated artifact sourced from the same canonical workflow content used by the skill. A build script validates metadata, checks documentation anchors, runs tests, regenerates `AGENTS.md`, and creates the `.skill` archive deterministically.

### Validation and release

Unit and regression tests cover the two reproduced optimizer failures, robust optimization, plan/apply refusal paths, successful verified writes, package parity, and benchmark behavior. GitHub Actions runs these checks on pushes and pull requests. `agents/openai.yaml` supplies Codex UI metadata. A dependency preflight reports Python, NumPy, and SciPy readiness without silently installing packages.

## Benchmark

A deterministic synthetic benchmark will compare the legacy mean/confidence PEQ path with robust multi-position fitting across stable peaks, wandering nulls, level-offset captures, L/R confidence gaps, and a worst-position harm case. It will report median improvement, worst-position change, bands used, headroom cost, and refusal outcomes. Real-car fixtures can be added later only when they are safe to publish.

## Success criteria

- The skill validator passes.
- The existing seven self-test surfaces still pass.
- A zero-confidence L/R mismatch cannot attract a filter.
- Level-only offsets do not make otherwise identical spatial traces inconsistent.
- Robust fitting cannot report a win when its worst-position loss exceeds the configured guard.
- Plan application refuses stale inputs and unconfirmed protected edits.
- Successful plan application changes only intended fields and produces a verification manifest.
- `AGENTS.md` and the `.skill` archive cannot drift silently from their canonical sources.
- CI reproduces all checks on a clean Python environment.
