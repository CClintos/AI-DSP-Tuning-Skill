# Final Review Safety Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every final-review serialization, phase/EQ, routing, benchmark, runtime, CI, documentation, and reference-validation blocker without weakening PEQ or confirmed-delay writes.

**Architecture:** File-producing tune codecs expose only source-bound writers: each writer decodes the immutable source, compares a channel-and-slot-aware whole-file crossover signature, and creates a distinct output exclusively. Raw codec functions become private implementation details used only for synthetic fixtures and internal verification. AFPX user writes route through the versioned `pipeline.py` plan/apply boundary, whose validator separates all phase-domain edits from all EQ-domain edits.

**Tech Stack:** Python 3.10+, stdlib `unittest`, NumPy/SciPy, JSON tune plans, GitHub Actions, deterministic ZIP packaging.

## Global Constraints

- Crossovers are repository-wide read-only and must preserve complete state at the same channel and slot.
- Every public or CLI file-producing boundary must be source-bound and use exclusive output creation.
- AFPX writes must use `pipeline.py` with `tune_plan_schema.json`, source hash, distinct new output, confirmations, and verification manifest.
- Any plan mixing phase-domain edits (delay or T=19/20 APF) with EQ-domain edits (PEQ or shelves) must be rejected until remeasurement.
- Preserve supported PEQ, shelf, output-trim, and explicitly confirmed delay behavior when they are not mixed with phase-domain edits.
- Keep five deterministic benchmark cases and run both legacy and robust fitters on every applicable fitting fixture.
- Minimum supported Python is 3.10.
- Regenerate `AGENTS.md`, `SKILL.md` metadata outputs, and `helix-rew-tuner.skill` deterministically.
- Do not push or merge; the controller owns final review and release.

---

### Task 1: Source-bound tune serialization

**Files:**
- Modify: `helix-rew-tuner/scripts/afpx.py`
- Modify: `helix-rew-tuner/scripts/pct6.py`
- Modify: `helix-rew-tuner/scripts/alpine_jssh.py`
- Modify: `helix-rew-tuner/scripts/pipeline.py`
- Test: `tests/test_pipeline_apply.py`

**Interfaces:**
- Consumes: decoded source tune plus intended edited representation.
- Produces: `afpx.write_preserving_crossovers(source_path, xml, output_path)`, `pct6.write_preserving_crossovers(source_path, xml, output_path)`, and `alpine_jssh.write_preserving_crossovers(source_path, obj, output_path)`; each returns only after safe exclusive creation.

- [ ] Add regressions proving `semantic_xover_key` distinguishes channel/slot relocation and swaps.
- [ ] Add adversarial regressions proving raw public AFPX, PCT6, and Alpine encoders cannot create tune files and safe writers reject crossover edits without creating output.
- [ ] Add CLI regressions proving PCT6/Alpine encode commands require a source tune, reject changed crossovers, and refuse existing outputs.
- [ ] Run the new tests and record expected failures from the current raw writer surfaces.
- [ ] Include `(channel_index, slot_index, state)` in AFPX crossover signatures; add the equivalent fixed-channel crossover key for Alpine.
- [ ] Rename unchecked byte/container encoders with private `_` names and implement public source-bound writers using exclusive `xb` creation.
- [ ] Update `pipeline.apply_plan` to use the AFPX source-bound writer and retain source-hash and emitted-content verification.
- [ ] Run focused codec and apply tests to GREEN.

### Task 2: Phase-domain and EQ-domain plan isolation

**Files:**
- Modify: `helix-rew-tuner/scripts/pipeline.py`
- Test: `tests/test_pipeline_apply.py`

**Interfaces:**
- Consumes: normalized plan edits and the effective filter type after each edit.
- Produces: deterministic rejection when a plan contains at least one phase-domain and at least one EQ-domain edit.

- [ ] Add a failing cross-channel delay-plus-PEQ test.
- [ ] Add a failing same-channel APF-plus-PEQ test and passing classification coverage for PEQ and shelves as EQ-domain.
- [ ] Track delay and T=19/20 edits as phase-domain; track T=17 and T=3/4 edits as EQ-domain.
- [ ] Reject any nonempty phase/EQ intersection at plan scope with a remeasurement message.
- [ ] Run focused plan-validation tests to GREEN.

### Task 3: Canonical routing, CI, runtime, and documentation contracts

**Files:**
- Modify: `helix-rew-tuner/references/core_workflow.md`
- Modify: `README.md`
- Modify: `helix-rew-tuner/scripts/pipeline.py`
- Modify: `helix-rew-tuner/scripts/preflight.py`
- Modify: `.github/workflows/validate.yml`
- Test: `tests/test_pipeline_apply.py`
- Test: `tests/test_preflight_and_benchmark.py`
- Test: `tests/test_build_skill.py`

**Interfaces:**
- Consumes: canonical workflow Markdown, schema path, runtime version tuple, and CI checkout history.
- Produces: generated routing parity assertions, Python 3.10 readiness, committed-diff whitespace checks, and non-vacuous Markdown reference validation.

- [ ] Add failing tests requiring all AFPX write guidance to route through `pipeline.py plan/apply` and `tune_plan_schema.json` with hash/output/confirmation/manifest requirements.
- [ ] Add a failing Python 3.9/3.10 boundary test using an injectable runtime version.
- [ ] Add a failing CI contract test requiring `git show --check --oneline HEAD`.
- [ ] Add a failing `check_doc_refs` test proving references are scanned from `core_workflow.md` and Markdown anchors are resolved.
- [ ] Update canonical routing copy, README PCT6 verified versions including 6.03.04 caveat, Python floor, CI whitespace command, and reference checker.
- [ ] Run focused contract tests to GREEN.

### Task 4: Comparative legacy-versus-robust benchmark

**Files:**
- Modify: `helix-rew-tuner/scripts/benchmark.py`
- Test: `tests/test_preflight_and_benchmark.py`

**Interfaces:**
- Consumes: the same applicable multi-position fixture inputs for `tunelib.fit_peq` and `tunelib.fit_peq_robust`.
- Produces: each applicable case has `legacy_vs_robust` fields for median improvement, worst-position change, bands used, headroom cost, and refusal outcomes.

- [ ] Add a failing JSON contract test for comparative fields and safety thresholds while retaining exactly five cases.
- [ ] Refactor applicable fitting fixtures to invoke both fitters deterministically.
- [ ] Compute comparable post-fit position scores and headroom cost from returned bands.
- [ ] Emit explicit refusal outcomes and guards that robust fitting does not breach declared worst-position/headroom safety.
- [ ] Run benchmark tests and `benchmark.py --json` to GREEN.

### Task 5: Regeneration, complete verification, and handoff

**Files:**
- Regenerate: `AGENTS.md`
- Regenerate: `helix-rew-tuner/SKILL.md`
- Regenerate: `helix-rew-tuner/agents/openai.yaml`
- Regenerate: `helix-rew-tuner.skill`
- Update: `.superpowers/sdd/2026-08-11-reliability-and-optimizer-v2/task-6-report.md`

**Interfaces:**
- Consumes: all canonical source and test changes.
- Produces: deterministic generated artifacts, one committed final-fix round, and exact verification evidence.

- [ ] Run all focused tests and inspect failures before the full gate.
- [ ] Run `python tools/build_skill.py --write` and `python tools/build_skill.py --check`.
- [ ] Run all unit tests and all seven script self-tests.
- [ ] Run preflight, benchmark, skill validator, compileall, working-tree and staged diff checks.
- [ ] Review the complete diff for scope and preservation behavior.
- [ ] Commit with a final-review safety message, append exact SHA/evidence to the task report, and hand off without push or merge.
