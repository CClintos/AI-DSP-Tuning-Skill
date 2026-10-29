# Changelog

Newest first. Version numbers match `metadata.version` in `helix-rew-tuner/SKILL.md`.

## 1.23.0

`pipeline.py finish`: what still decides the sound once the system sum is on
the target, from published psychoacoustics and the EMMA judging rules
(`docs/research/2026-10-29-beyond-the-target-curve.md`). It lists residual
broad peaks to cut (not dips), checks that each EMMA instrument band images in
one place (centre and focus, from level and, with timed sweeps, time), flags
overlapping passbands between drivers mounted at different heights, checks
the sub for leakage above 120 Hz and harmonics against Fielder & Benjamin's
limits, and compares bass decay with Fazenda et al.'s audibility thresholds.
`next` suggests it. Also fixed: the `.mdat` reader labelled REW's distortion
arrays off by one (the second array is the fundamental).

## 1.22.0

Leaner where an agent reads, and two commands that prevent bad captures and
wrong tool choices. `capture-plan` turns the tune and the session goals into the
named capture list, REW settings, averages for the capture length, the mic's
level ceiling, the T1 delay for `mmm-align` and a RAW/XO/EQ sequence that never
removes a tweeter's or midrange's high-pass. `next` audits whatever was captured
and prints the commands that apply, with their arguments. `xo-check` gains
`--section` and a PEQ-only mode. `core_workflow.md` lost 14% (the tunelib
function table moved to `references/tunelib_api.md`, step 7 now routes through
`verify`, duplicated beta-format text went) while gaining a decision table by
what was captured; `methodology.md` lost 15% by condensing ten case-study
sections to their rules (the full stories are in `docs/case-notes.md`). Real REW
files from one car are now regression fixtures (`tests/fixtures/real`), and a
doctrine test fails if trimming ever drops a hard rule. The README's long
explanation, development notes and version history moved to
`docs/how-it-works.md`, `docs/development.md` and this file.

## 1.21.0

Version 1.21.0 reads everything a single MMM capture carries. `.mdat` files
are read by structure (the old byte scanner picked the mic calibration curve on
RTA files and a distortion array on an axis 21% wrong on sweep files); the
whole REW header is parsed (and REW's Format line is no longer misread as the
export's smoothing); `capture-audit`, the moving-mic noise floor, summation
coherence, four-capture alignment, peak-trace stability, the RAW/XO/EQ
crossover check, listening-level and road-noise voicing, learned preferences,
frame-level statistics, read-only REW RTA endpoints and experimental test
signals are new. See "Single-run MMM intelligence" in
`helix-rew-tuner/references/methodology.md`.

## 1.20.0

Version 1.20.0 fixes four things found re-running the skill on a real car:
`bass-trials` now scores each trial against its own unchanged model (before,
model error made even the zero-change trial fail and every trial was rejected);
the RTA-mode tilt guard no longer refuses single-driver MMM captures; vehicle
guards veto any `refine` edit whose net transfer lifts a protected zone or
narrows a boost past the Q cap; and the `quality-check` message now lists every
accepted evidence group, headroom included.

## 1.19.0

Version 1.19.0 adds `audible-study`, a measured finalist review covering acoustic
crossover choices, multitone workload, sustained output, bass across the driver's
head area, stage/volume preference trials and physical noise triage. See
`helix-rew-tuner/references/audible_tuning.md` for its manifest and limits.

## 1.18.0

Version 1.18.0 corrects the two known level-anchor cases and holds one reference
through refinement and judging. `--partner` and `--limits` connect L/R and measured
compression/distortion evidence to filter choices. `stereo-propose` builds shared
and side-specific cuts; `bass-trials` checks small sub gain/delay/polarity trials
against the actual measured sum; `voice-match` calculates blind A/B trims from
actual candidate system captures. Voicing variants include a broad presence option.
See [audible tuning](helix-rew-tuner/references/audible_tuning.md) for commands,
capture requirements and what counts as a confirmed improvement.
