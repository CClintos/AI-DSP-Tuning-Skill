# Skill audit — helix-rew-tuner 1.15.0 (2026-10-22)

An independent audit of the whole repository (SKILL.md, generated AGENTS.md,
references, scripts, assets, tests, build tool and CI), done before any edit,
followed by the improvements implemented on branch `skill-audit-2026-10-22`.

## Method

1. Read SKILL.md, core_workflow.md, the build tool, CI, the plan schema and the
   README in full. Sampled methodology.md (171 KB) by section and size.
2. Ran the full release gate on Python 3.12 / NumPy 2.5.4 / SciPy 1.18.1.
3. Cross-checked every documented `pipeline.py <command> --flag` against the
   real argparse parsers.
4. Ran a simulated session the way an agent would: `afpx.py inspect` →
   `analyze` → `propose` on a synthetic 4-channel tune and three REW-style
   exports with known faults, measuring output size and correctness.
5. Ran known-answer `propose` cases (A–F below), fed the loader the file
   shapes real users produce, and timed and sized each step.
6. Built the agent-eval fixtures (`evals/make_fixtures.py`). Checking their
   known answer surfaced F0, the most consequential defect found.

## Baseline (before any change)

| Gate | Result |
|---|---|
| Unit/integration tests | 336 passed (77.8 s) |
| Script self-tests (7) | all passed |
| Preflight / benchmark (6 scenarios) | ready / all passed |
| Package parity (`build_skill.py --check`) | current |
| Docs ↔ CLI flags | consistent (0 real mismatches) |
| `analyze` / `propose` JSON size | 4.2 KB / 3.8 KB (compact, agent-friendly) |

The deterministic layer is strong: hash-bound plan/apply, exclusive output
creation, whole-file crossover preservation, mixed-domain refusal, and
deterministic packaging are all tested. These are preserved unchanged.

## Findings

Severity reflects the effect on a real user's tune or on agent reliability.

### F0 — High, functional: a notch that moves between seats makes `propose` reject a real shared peak (fixed)

Fixture: three seats sharing a +6 dB peak at 150 Hz (Q 3), each with a −9 dB
Q8 notch in a different place (1.2 / 1.3 / 1.45 kHz). Every real cabin has
seat-specific combs like these. Before the fix, `propose` returned **no
band**: the 150 Hz cut was rejected as DO NOT APPLY, and held-out validation
reported `not_validated`.

Root cause: with three positions, every held-out fold fits only two. Two
positions get no spatial mask, so the fold's greedy fitter seeds its first
band on the notch average, the largest audibility-weighted residual. That
boost fails the worst-position or parsimony gate, and in `fit_peq_robust` a
failed gate **ends the fit**. The 150 Hz peak is never tried, two of three
folds find nothing, stability is 0.33, and the band is rejected. Three
positions is the documented minimum, which makes this the most common
multi-position case.

Fix: in `fit_peq_robust`, a rejected **boost** seed now blocks its ±⅓-octave
region, and the search continues with **cut seeds only**. A rejected cut
still ends the fit, and boosts are never retried. That deliberately avoids
the failure the author measured for `fit_peq`'s opt-in `seed_retries`
("mostly via boosts"). `cut_seed_retry=False` restores the old rule. Evidence:

| Check | Before | After |
|---|---|---|
| S01 fixture via `propose` | no band (DO NOT APPLY) | −5.25 dB @ 150 Hz, APPLY (stability 1.0) |
| Benchmark held-out quality, 6 cars: unseen-seat gain | 0.531 dB | 0.799 dB |
| Same, worst car / total boost | 0.0 / 0.0 dB | 0.0 / 0.0 dB (unchanged) |
| 30 cars × 8 unseen seats: unseen-seat gain | 0.663 dB | 0.787 dB |
| 30 cars: cars changed / improved / worsened | — | 5 / 5 / 0; no seat newly made worse |
| Benchmark "real shared fault" metric (6 / 30 cars) | 0.853 / 0.604 dB | 0.634 / 0.583 dB |

The fault metric dips because the extra cuts land on low-frequency
reflection gain (about +4.6 to +5.9 dB at every unseen seat near 90 Hz).
The synthetic generator files that gain under "position", not "fault", but
every listener hears it. All benchmark guards still pass.

### F1 — High, functional: level-anchor bias produces spurious boosts or rejects a real cut (not fixed — follow-up)

Known-answer `propose` cases. The synthetic system is the default target
plus the listed faults, at 80 dB, with 0.3 dB noise. "Ideal" means the faults
are cut and nothing is boosted.

| Case | Input | Anchor error | Result |
|---|---|---|---|
| A | +5 dB @ 500 Hz Q2, 1 position | +0.66 dB | −4.25 dB @ 496 Hz ✔ |
| B | same, 3 positions | +0.64 dB | −4.5 dB @ 499 Hz ✔ |
| C | +5 @ 500 and +3 @ 2.5 kHz, 3 positions | +1.80 dB | both cuts **plus three broad boosts** (+1.75 @ 85 Hz, +2.75 @ 557 Hz, +1.75 @ 8.4 kHz, all Q 0.5) ✘ |
| D | C plus one Q8 −9 dB notch per seat | +2.10 dB | **no band at all**: the 500 Hz cut is rejected as "fitted to particular seats" ✘ |
| E | +6 dB @ 150 Hz Q3, 3 positions | +0.06 dB | two cuts at 139/161 Hz ✔ |

Root cause: `target_anchor_offset` fixes the level with a weighted median over
300–3000 Hz *before* fitting. When peaks occupy most of that band, the median
sits on them, so everything else reads low. The fitter then spends bands and
headroom on what is only a level offset (C), or the shifted deviations no
longer validate (D). With the true anchor, `fit_peq_robust` and
`held_out_band_validation` handle case D correctly: the 500 Hz cut is APPLY
in every fold, even with per-seat notches.

A spread-across-anchor-bands warning was tested and rejected. Clean but
rippled or tilted responses spread *more* (1.7–4.1 dB) than the biased cases
(1.3–1.5 dB), so it would mostly misfire. The real fix is letting level float
inside the fitter (a free, unwritten offset in the least-squares objective,
carried through scoring and held-out validation). That changes every analysis
path and must be validated against the benchmark and real captures, so it is
recorded as a measurable known gap. Cases C and D are `expectedFailure` evals
that flip once it is fixed.

### F2 — High, packaging/privacy: a profiler dump ships inside the skill

`helix-rew-tuner/scripts/prof` is a 34 KB cProfile dump committed in
`d0a359e`. It ships inside `helix-rew-tuner.skill` and embeds local absolute
paths (`C:\Users\Adroit\AppData\Local\Temp\claude\…`). The build packages
every file under the skill folder with no allowlist, so any stray file ships
the same way.

### F3 — High, activation and context: one mandatory 12k-token read, ambiguous trigger text

- SKILL.md requires reading `core_workflow.md` in full (47 KB, about 11.8k
  tokens) before *any* action, including read-only tasks (inspect a tune,
  convert ms to samples, read a REW export). It has no routing, and the hard
  safety rules exist only deep inside that document.
- The description's last clause ("handling supported beta Alpine `.jssh`
  presets, crossover, imaging, bass, phase, … problems") can parse as "any
  crossover/bass/phase problem". It has no negative scope (home or studio REW
  room EQ, other DSP brands' writes), and it misses common user words (DSP
  PC-Tool, time alignment, moving-mic/RTA, EMMA, P SIX / DSP.3).

### F4 — Medium, reliability: where to run the scripts from is ambiguous

The docs say "run from the skill directory, or prefix its absolute path".
Running from the skill folder breaks the user's relative file paths and can
put plans and outputs inside the installed skill folder. `python` does not
exist on many macOS/Linux machines (`python3`), and nothing says so.

### F5 — Medium, agent UX: tracebacks for ordinary input errors

A missing file, a bad value or a wrong file type makes `pipeline.py` print a
roughly 20-line Python traceback with the actual message last. That costs
context on every failed call and buries the fix.

### F6 — Medium, safety: silent overwrites outside the plan/apply boundary

- `--out` on the 15 report commands opens with `'w'`. A mistyped
  `--out mytune.afpx` replaces the tune with JSON.
- `pct6.py decode` and `alpine_jssh.py decode` silently overwrite an
  existing `.decoded.xml` / `.decoded.json`, which is the file a user edits
  before `encode`.

### F7 — Medium, safety/doc: confirmation flags not explained in the canonical workflow

`voice-variants --confirm` and `ab-make --confirm-trim` write files whose
edits are all auto-confirmed by one flag. Only methodology.md (read on
demand) says the user must have seen the edits first. core_workflow, which
the agent always reads, does not.

### F8 — Medium, input robustness: two common file shapes fail

UTF-16 text (Excel's "Unicode Text", some editors) and Excel-quoted CSV
(`"20.000","75.1",…`) fail with "<8 usable data rows — is this a REW
export?". BOM, decimal comma, semicolons, tabs, `.frd`, CRLF, cp1252 and
descending target curves all load correctly.

### F9 — Low: misleading note on multi-position analysis

`analyze --positions …` with no `--measurement` reports "no phase column in
--measurement" even though there is no such file and the positions carry
phase.

### F10 — Low, doctrine consistency: propose assumes 96 kHz without saying so

`propose` fits and predicts at a hard-coded 96 kHz, while `refine` and
`verify` require `--dsp-rate` (Non-negotiable #10). Measured effect for a
48 kHz unit: ≤0.05 dB below 3 kHz and up to 0.4 dB at 8–10 kHz. That is
small, but the assumption is invisible in the output.

### F11 — Low, doc structure

- The `pipeline.py` entry in core_workflow is one ~1,100-word paragraph
  covering 20 subcommands, which is hard to scan for the right command.
- Intake has three competing "first" steps: preflight "before anything
  else", the session file "first, before asking anything else", and
  expectations "in your very first reply".
- There is no measurement-only route (REW files, no tune file yet), even
  though Non-negotiable #1 requires a confirmed channel map.

### F12 — Low, hygiene

The `tunelib.py` header refers to `_tunefit.py` / `_devcalc.py` and reads
"Run  to execute" (the command is missing).

### F13 — Info: nothing measures agent behaviour

336 tests cover the deterministic layer, but nothing measures activation,
workflow compliance or end-to-end known-answer outcomes. Docs ↔ CLI drift is
only checked for methodology anchors.

### Note — an earlier, unmerged branch

`origin/improve-first-tune-workflow` (c6e1d70, 16 Oct) branched before
1.14.0/1.15.0 and was never merged. It adds a first-tune guide and makes
`propose --dsp-rate` required. It overlaps F10/F11, and merging it now would
conflict with the EMMA/MMM work on main. It is left untouched; whether to
rebase or close it is the owner's call.

## Context budget (approximate tokens = bytes / 4)

| File | Before | After | Read when |
|---|---|---|---|
| SKILL.md | 280 | 1,120 | always |
| core_workflow.md | 11,670 | 11,410 | before: always; after: analysis, proposal or write |
| afpx_format.md | 4,500 | 4,500 | before an AFPX write |
| tune_plan_schema.md | 1,500 | 1,500 | before plan/apply |
| methodology.md | 42,900 | 42,900 | by section |

Mandatory reading before a read-only task (inspect a tune, read a file,
convert a delay) drops from about 11,950 to about 1,120 tokens. A full
tuning session reads about 600 tokens more than before: the router and the
hard rules in SKILL.md, plus the run rules, session-start order and
confirmation-flag rule in core_workflow.

## Prioritized improvement plan

Ordered by effect on task success and reliability, then by risk.

| # | Item | Fixes | Risk | Status |
|---|---|---|---|---|
| 0 | `fit_peq_robust`: a rejected boost seed continues with cut seeds only | F0 | medium (validated: benchmark, 30-car sweep, full suite) | done |
| 1 | Remove `scripts/prof`; build refuses unexpected file types; ignore profiler output | F2 | none | done |
| 2 | SKILL.md as a router: precise trigger and negative scope, task routing, run rules, hard safety rules | F3, F4 | low | done |
| 3 | core_workflow: command table, one ordered intake, measurement-only route, confirmation-flag rule, run rules | F7, F11, F4 | low | done |
| 4 | `pipeline.py`: one-line errors (traceback on demand) and `--out` overwrite guard; decode CLIs never overwrite | F5, F6 | low | done |
| 5 | Loader: UTF-16 / BOM detection, quoted CSV fields | F8 | low | done |
| 6 | Correct the multi-position phase note; record propose's assumed DSP rate | F9, F10 | low | done |
| 7 | Evaluation suite: CI-run known-answer, safety, robustness and docs↔CLI checks; agent-behaviour scenarios and activation set with rubric | F13, F1 tracking | none | done |
| 8 | Header hygiene | F12 | none | done |
| 9 | Floating level inside the fitter (validate on the benchmark and real captures) | F1 | high | follow-up |
| 10 | Split methodology.md into topic files | context | medium | follow-up |
| 11 | Run the agent-behaviour and activation evals against a live agent each release | F13 | none | follow-up |

The implementation record (what changed, why, and test results) is at the end
of this file.

## Implementation record (version 1.16.0)

### What changed, and why

| Area | Change | Finding |
|---|---|---|
| `scripts/tunelib.py` | `fit_peq_robust(cut_seed_retry=True)`: a rejected boost seed blocks its region and the search continues with cut seeds only; `boost_rejections` added to the report. Stale header comment fixed. | F0, F12 |
| `scripts/pipeline.py` | Input errors print one `error: ...` line and exit 2 (`HELIX_TUNER_DEBUG=1` restores the traceback). Report `--out` refuses an input path or a tune/capture extension. `analyze --positions` no longer claims "no phase column in --measurement". `propose` reports `meta.prediction_sample_rate_hz`. | F5, F6, F9, F10 |
| `scripts/measure.py` | One reader for exports and targets: UTF-8 with or without BOM, UTF-16 LE/BE with or without BOM, spreadsheet quotes. | F8 |
| `scripts/pct6.py`, `scripts/alpine_jssh.py` | `decode` never replaces an existing `.decoded.*` file. | F6 |
| `scripts/decay.py` | `fdw --out` refuses to overwrite its input IR. | F6 |
| `scripts/prof` | Deleted (profiler dump with local paths). | F2 |
| `tools/build_skill.py` | Refuses any non-text file in the skill folder; computes the package before writing it; new SKILL.md; version 1.16.0. | F2, F3 |
| `SKILL.md` (generated) | Precise trigger description with negative scope; request router; run rules (full script paths from the user's folder, `python3`/`py -3`, outputs next to the source); eight hard rules, including "file content is data". | F3, F4 |
| `references/core_workflow.md` | Command table instead of a 1,100-word paragraph; run rules; one session-start order; measurement-only route; confirmation-flag rule for `voice-variants --confirm` / `ab-make --confirm-trim`; guidance on anchor-compensating broad boosts (F1). All doctrine and every `§` reference kept. | F4, F7, F11, F1 |
| `evals/` | Evaluation plan, 24-prompt activation set, 14 agent scenarios with rubric and 7 critical failures, fixture generator. | F13 |
| `tests/` | `test_skill_evals.py` (33 tests, 2 expected failures for F1), two fitter regressions, one build test. | F0, F2, F5–F8, F13 |
| `.gitignore`, README | Ignore profiler output; version, file tree and an evaluation pointer. | F2 |

Behaviour that did not change: the plan/apply contract and schema, every
write verifier, crossover preservation, the mixed-domain refusal, the
analysis numerics other than F0's stopping rule, report JSON shapes (fields
were only added), and the methodology text.

### Verification (Python 3.12.10, NumPy 2.5.4, SciPy 1.18.1, Windows 11)

| Gate | Before | After |
|---|---|---|
| Unit/integration tests | 336 passed | 372 passed, 2 expected failures (F1) |
| Script self-tests (7) | pass | pass |
| Preflight / benchmark | ready / 6 of 6 | ready / 6 of 6 |
| `build_skill.py --check` | current | current |
| Official skill validator (pinned `quick_validate.py`) | valid | valid |
| `compileall`, `git diff --check` | clean | clean |
| End-to-end agent flow on `evals/make_fixtures.py` output | 150 Hz cut rejected | cut proposed (APPLY); unconfirmed edit refused with nothing written; confirmed plan written and verified; re-apply refused; source hash unchanged; `verify` grades the band confirmed (predicted −3.9 dB, measured −3.4 dB); nothing written in the skill folder |

### Not done here (follow-ups)

1. **F1, level anchor.** The floating-level approach was tried in the
   one-seat MMM pass below and rejected on evidence. A better anchor needs
   real captures to judge, not more synthetic tuning. Cases C and D in
   `tests/test_skill_evals.py` turn into unexpected successes when a fix
   lands.
2. **Split `methodology.md`** (170 KB) into topic files, and extend
   `pipeline.py selftest`'s `§` check to cover them.
3. **Run layers 2 and 3 of `evals/`** against a live agent for this release
   and record the scores in `evals/results/1.16.0.md`. They need an agent
   session per prompt, so they were not run here.
4. **The unmerged `improve-first-tune-workflow` branch.** Rebase it or close
   it. Its first-tune guide could fill the measurement-only route; its
   required `propose --dsp-rate` is superseded by the recorded prediction
   rate unless 48 kHz units become a focus.

## Second pass: one seat, one moving-mic (MMM) run (2026-10-23)

The owner tunes almost entirely from **single-seat MMM captures**, usually
one run. A one-run MMM proposal goes through `fit_peq` (the single-trace
fitter), not the multi-position path F0 fixed, and an existing tune goes
through `refine`. Both were probed with known answers.

### Probes

- **Synthetic cars:** the benchmark's generator (a shared fault plus
  per-seat combs and modes). One MMM run is the power average of 24 head
  positions. Each proposal is scored at 8 unseen head positions with a
  level-free score, since the listener sets the volume. 30 cars; car 20 is
  refused by the RTA-mode tilt guard in every variant.
- **Simple cases:** M-A (one peak), M-C (two peaks), M-E (low peak) and M-F
  (peaks plus a broad midrange dip).
- **`refine` through an existing bank:** a perfect bank, one wrong cut, a
  missed peak, an under-cut, and an empty bank. **All handled correctly**,
  with no change needed.

### F14 — High: boosts stacked past the +3 dB limit (fixed)

Both fitters cap each band at +3 dB but not the cascade, so they put two or
three boosts on one dip. One sweep with a −8 dB notch at 900 Hz got a
**+6.8 dB** stacked boost in `bands`, written as soon as it is confirmed and
flagged only "ungated". On MMM the same dip became three separate trials (9
duplicate trial pairs across 29 cars).

Fix: `tunelib.limit_stacked_boosts`, applied in `propose` after the fit.
Cuts are always kept. Boosts are added greedily (best audibility score
first) while the whole cascade stays within +3 dB (+0.25 rounding), and the
rest go to `rejected` with the reason.

Penalising the cascade inside the optimiser was tried first and rejected.
It changed which cuts were found: car 13 lost a real 733 Hz cut through the
percentage parsimony gate.

### F15 — High for MMM: one dip ends a single-trace fit (fixed for MMM)

`fit_peq` seeds on the largest audibility-weighted deviation, and a
rejected seed ends the fit, as in F0. On one MMM run, a dip that outranks a
real peak left the peak uncut. Four of 29 synthetic cars got **no band at
all**. A 0.2 dB anchor change flipped one car from four bands to none.

Fix: `fit_peq(cut_seed_retry=True)`. A rejected dip seed blocks its region
and the search continues with cut seeds only; boosts are never retried.
`propose` enables it for `--capture mmm`. A single fixed sweep keeps the
author's stricter default, because its peaks may belong to the mic spot.

### F1 revisited — anchor refinement tried and rejected

Re-anchoring with a floating-level fit fixed the clean cases (M-C: residual
0.784 → 0.04, both peaks cut, no spurious trial). On realistic cars,
though, the level is not identifiable once a few broad bands can explain
the band. Shifts of −4 to −11 dB appeared, M-F moved the wrong way, and
cars 6 and 18 regressed badly. A cuts-only "flat afterwards" test did not
separate good shifts from bad. Floating the level inside `propose`'s fit,
and a cuts-first MMM design, were also worse. All three were removed. The
agent guidance now also flags `bass_balance` as provisional when large
midrange peaks are present.

### Results on the one-run MMM path (29 cars)

| Metric | Before | After |
|---|---|---|
| Mean gain at unseen head positions | 0.540 dB | 0.587 dB |
| Cars helped / harmed vs before | — | 5 / 0 |
| Worst single unseen seat | −0.742 dB | −0.742 dB (unchanged) |
| Cars with no correction at all | 4 | 0 |
| Boost trials suggested | 49 | 36 |
| Near-duplicate trial pairs (stacked) | 9 | 1 |
| One sweep, −8 dB notch: proposed cascade boost | +6.82 dB | +2.96 dB |

The multi-position benchmark is unchanged by this pass: 30 cars, 0.787 dB
unseen-seat gain, 5 helped and 0 harmed.

New tests: `SingleTraceFitTests` (3) in `tests/test_tunelib_regressions.py`,
and M1–M3 in `tests/test_skill_evals.py`. All three end-to-end cases fail on
the original code (no band; three stacked trials; +6.8 dB) and pass now.
