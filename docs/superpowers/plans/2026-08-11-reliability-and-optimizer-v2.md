# Reliability and Optimizer V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing single DSP-tuning skill with corrected confidence handling, level-robust spatial analysis, robust multi-position PEQ fitting, deterministic plan/apply writes, generated packaging, CI, metadata, and benchmarks.

**Architecture:** Keep numerical behavior in `tunelib.py`, tune-file semantics in the existing format modules, and orchestration in `pipeline.py`. Add focused build, preflight, benchmark, and test modules rather than expanding the already-large workflow files further; retain Alpine in the same skill through routed reference instructions and format-specific validators.

**Tech Stack:** Python 3.10+, NumPy, SciPy, standard-library `unittest`, JSON, YAML metadata, PowerShell-compatible CLIs, GitHub Actions.

## Global Constraints

- Keep Alpine `.jssh` support inside `helix-rew-tuner`.
- Keep `.pct6` and `.jssh` explicitly beta and require real-file round-trip preflight before writes.
- Never write crossovers.
- Require per-change confirmation for delay, polarity, output trim, shelf, and all-pass edits.
- Preserve source files and write generated tunes to new paths.
- Do not add a license until the owner chooses one explicitly.
- Use test-first red-green cycles for every behavior change.

---

### Task 1: Confidence-safe partner matching and level-aligned spatial consistency

**Files:**
- Create: `tests/test_tunelib_regressions.py`
- Modify: `helix-rew-tuner/scripts/tunelib.py`

**Interfaces:**
- `fit_peq(..., partner_conf=None)` combines `conf` and `partner_conf` in the partner objective.
- `spatial_consistency(..., align_levels=True, alignment_band=(100.0, 10000.0))` returns `level_offsets_db` in addition to existing keys.

- [ ] Write a failing test proving a zero-confidence 3 kHz partner mismatch produces no filter and does not worsen the target score.
- [ ] Run `python -m unittest tests.test_tunelib_regressions.PartnerConfidenceTests -v` and confirm the existing implementation fails by producing a boost.
- [ ] Apply confidence to partner residuals, mismatch scoring, and reported selection baselines; handle an all-zero partner weight without division errors.
- [ ] Run the partner-confidence test and the complete `tunelib.py` self-test.
- [ ] Write a failing test using three identical curve shapes at -2/0/+2 dB and assert at least 99% consistency after alignment plus reported offsets near -2/0/+2 dB.
- [ ] Run the spatial test and confirm the existing implementation rejects most bins.
- [ ] Add robust weighted-median level alignment before spread calculation, retaining `align_levels=False` for absolute-SPL use.
- [ ] Run regression tests and commit with `fix: honor confidence in partner and spatial fitting`.

### Task 2: Robust multi-position optimizer and confidence-aware scorecard

**Files:**
- Modify: `tests/test_tunelib_regressions.py`
- Modify: `helix-rew-tuner/scripts/tunelib.py`

**Interfaces:**
- `fit_peq_robust(freqs, deviations_db, fit_band, ..., tail_weight=0.75, max_worst_loss_db=0.25)` returns `(bands, report)`.
- `tune_scorecard(..., mask=None, conf=None)` applies the same measurement authority to aggregate metrics.

- [ ] Write failing tests for a shared broad peak corrected across three positions and a position-specific notch that must not attract a boost.
- [ ] Write a failing test where mean-error improvement harms one position beyond `max_worst_loss_db` and require the candidate to be rejected.
- [ ] Implement a joint residual using per-position weighted errors, median performance, and a smooth upper-tail penalty while reusing existing PEQ bounds and filter taxes.
- [ ] Quantize candidate filters before final acceptance and recheck every position after quantization.
- [ ] Extend `tune_scorecard` with mask/conf weighting and literal expected metrics.
- [ ] Run the focused tests, all `tunelib.py` self-tests, and commit with `feat: add robust multi-position PEQ fitting`.

### Task 3: Versioned deterministic plan/apply pipeline

**Files:**
- Create: `tests/test_pipeline_apply.py`
- Create: `helix-rew-tuner/references/tune_plan_schema.md`
- Modify: `helix-rew-tuner/scripts/pipeline.py`
- Modify: `helix-rew-tuner/scripts/afpx.py`

**Interfaces:**
- Plan schema version `1` with `source_sha256`, `format`, `output_path`, `edits`, and `confirmations`.
- `validate_plan(plan, source_path) -> dict` returns normalized plan metadata or raises `ValueError`.
- `apply_plan(plan_path) -> dict` writes a new tune and returns a verification manifest.

- [ ] Write failing integration tests for source-hash mismatch, output equal to source, illegal PEQ limits, crossover edit requests, and unconfirmed protected edits.
- [ ] Implement schema parsing and fail-closed validation without writing files.
- [ ] Write a failing positive test using synthetic AFPX XML with one slot edit and a new output path.
- [ ] Implement AFPX plan application through `write_filter_slot`, `write_delay_samples`, and `write_output_trim`, followed by the matching verify function and `roundtrip_lint`.
- [ ] Emit a manifest containing source/output hashes, normalized edits, verification results, and `predicted_not_measured: true`.
- [ ] Add `pipeline.py plan` and `pipeline.py apply --plan <json>` CLI commands.
- [ ] Run integration and existing pipeline/AFPX self-tests; commit with `feat: add verified tune plan application`.

### Task 4: Dependency preflight, benchmarks, and install metadata

**Files:**
- Create: `helix-rew-tuner/scripts/preflight.py`
- Create: `helix-rew-tuner/scripts/benchmark.py`
- Create: `helix-rew-tuner/requirements.txt`
- Create: `helix-rew-tuner/agents/openai.yaml`
- Create: `tests/test_preflight_and_benchmark.py`
- Modify: `helix-rew-tuner/SKILL.md`

**Interfaces:**
- `preflight.py --json` reports Python, NumPy, SciPy, skill paths, and overall readiness without installing anything.
- `benchmark.py --json` runs deterministic synthetic cases and exits nonzero when robust fitting violates a declared guard.

- [ ] Write failing tests for structured preflight output and benchmark guard reporting.
- [ ] Implement preflight version/import checks with actionable failure messages.
- [ ] Implement benchmark cases for stable peaks, wandering nulls, level offsets, confidence-blocked L/R matching, and worst-position harm.
- [ ] Shorten the skill description below 1024 characters while retaining Helix, REW, `.afpx`, `.pct6`, diagnosis, tuning, and verification triggers.
- [ ] Keep Alpine routing in the same skill body and move detailed operating constraints to `references/alpine_jssh_format.md`.
- [ ] Add quoted `agents/openai.yaml` interface values and a `$helix-rew-tuner` default prompt.
- [ ] Run tests and the skill validator; commit with `feat: add preflight benchmark and Codex metadata`.

### Task 5: Canonical workflow generation and deterministic packaging

**Files:**
- Create: `helix-rew-tuner/references/core_workflow.md`
- Create: `tools/build_skill.py`
- Create: `tests/test_build_skill.py`
- Modify: `AGENTS.md`
- Modify: `helix-rew-tuner/SKILL.md`
- Modify: `README.md`
- Modify: `helix-rew-tuner/references/methodology.md`
- Modify: `helix-rew-tuner.skill`

**Interfaces:**
- `python tools/build_skill.py --check` validates generated files and package parity without mutation.
- `python tools/build_skill.py --write` regenerates `AGENTS.md` and `helix-rew-tuner.skill` deterministically.

- [ ] Write failing tests proving stale `AGENTS.md`, stale archive contents, invalid metadata, and unresolved methodology anchors are detected.
- [ ] Extract shared workflow doctrine into `core_workflow.md`; keep platform-specific routing in the two wrappers.
- [ ] Implement deterministic wrapper/archive generation with sorted paths and fixed ZIP timestamps.
- [ ] Replace methodology line-number navigation with Markdown anchor links and validate destinations.
- [ ] Correct the stale non-negotiable cross-reference and README script/test inventory.
- [ ] Run `build_skill.py --write`, then `--check`, tests, and validator; commit with `build: generate instructions and skill package`.

### Task 6: Continuous integration and final verification

**Files:**
- Create: `.github/workflows/validate.yml`
- Modify: `README.md`

**Interfaces:**
- CI runs dependency installation, unit tests, script self-tests, validator, benchmark, and package drift checks on Windows and Linux.

- [ ] Add a workflow using Python 3.10 and 3.13 with `pip install -r helix-rew-tuner/requirements.txt`.
- [ ] Run unit tests, all seven script self-tests, preflight, benchmark, skill validator, and `tools/build_skill.py --check` locally.
- [ ] Confirm `git diff --check` and review the complete staged diff.
- [ ] Commit with `ci: validate tuner skill and generated package`.
- [ ] Push `codex/reliability-and-optimizer-v2` to `origin` and report the exact remote branch and any authentication outcome.
