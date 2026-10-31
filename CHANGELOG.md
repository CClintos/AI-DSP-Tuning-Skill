# Changelog

Newest first. Version numbers match `metadata.version` in `helix-rew-tuner/SKILL.md`.

## 1.26.0

- Audit corrections: common-support verification, nuisance-level-consistent
  tonal judging, contiguous regional evidence, power-preserving MMM fit inputs,
  source-recording identity checks and regional crossover evidence eligibility.
- Joint refinement applies vehicle restrictions and local deficit guards,
  preserves Q during other parameter moves, and prunes physically infeasible
  candidates before shortlisting. Repeat-level spread above 0.75 dB is held.
- Listening logs reject report collisions, write atomically and deduplicate
  stable session IDs. Either-direction preference uses a two-sided exact test.
  Context-bound choices require hashed variant/baseline provenance; knob values
  record applied changes and next experiments stay close to the tested range.

- `stereo-refine` jointly evaluates remove/relax/refit moves on two existing
  PEQ banks against keeping the current tune. Selection and reporting share
  fixed-anchor judging, repeated-pass regression guards, L/R mismatch checks,
  clean-output ceilings and optional timed neighbour checks. Proposals only;
  measured audible improvement remains to be established in the car.
- `ab-result --context` records listener, baseline SHA-256, SPL and environment;
  `prefs --context` isolates those choices. Unselected mixed contexts fail.
- `stereo-propose` now power-pools MMM repeats, rejects known same-recording
  exports, and accepts the confirmed DSP rate for its filter model.

## 1.25.0

- **MMM evidence authority.** `frames` tags every export from a source recording
  with its SHA-256 capture ID and labels the half-path result as within-pass
  consistency. Repeatability-gated MMM comparisons reject two files from the
  same known recording; multi-pass MMM analysis does too.
- **Repeated-pass pooling.** Independent MMM passes are averaged in linear
  power while fixed-position spatial analysis retains its existing treatment.
- **Consistent measured candidate judgment.** `verify` and measured crossover
  review now include the same fixed-anchor scorecard as the candidate
  judging path, alongside their existing regional and timing guards.
- **Real-car validation route.** `corpus-check` replays hashed local before and
  after sessions, enforces independent recordings and held-out
  vehicle/listener groups, and reports objective and blind outcomes. No
  real-car corpus or revised universal weights are bundled.
- `capture-plan` specifies a repeatable small ear-centred MMM movement and
  makes the distinction between a full repeat pass and split halves explicit.

## 1.24.0

- **Listening sheet.** `assets/emma_listening_sheet.html` is the 280-point EMMA
  SQ scoresheet as an offline phone page, for your own listening or a judge's
  sheet copied in. `finish --heard` puts each lost point next to what the
  captures measured, with how far they explain it, and `next` picks up a
  sheet saved beside the captures.
- **`finish` uses the 2026 judge book's instruments** (electronic bass,
  electric guitar, banjo, vibraphone, triangle, over the ranges `imaging
  --bands emma` uses) instead of the 2024 book's flute and celesta, across the
  part of each range both sides play, up to 16 kHz. It also reports
  `emma_bands`.
- **`trust-check`**: after `capture-plan --goal validate`, decides whether
  `mmm-align`, the stability map, `frames` and the test signal are trusted,
  advisory or to be removed on this car, each against an independent
  measurement of the same thing.
- **`propose --dsp-rate`** models bands at the confirmed DSP rate (fitter,
  boost gate, held-out validation, vehicle guards); without it the report says
  96 kHz was assumed. `refine` now fits the filters it adds at the confirmed
  rate too (it fitted additions at 96 kHz).
- **Height and distance voicing knobs** in `voice-variants` (`--height-db`
  near 8 kHz, `--distance-db` near 4 kHz), learned by `prefs`.
- **First-tune guide**, `references/first_tune.md`, ported from the
  `improve-first-tune-workflow` branch and updated for `capture-plan`, `next`
  and `finish`.
- Fixed: octave smoothing carried a capture's empty low bins into every band
  above them, so `stability` read every band as stable for an export that
  starts above 10 Hz.
- First live agent evals: `evals/results/1.24.0.md` (activation recall 1.00,
  false triggers 0, no critical failures in 15 behaviour runs).

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
