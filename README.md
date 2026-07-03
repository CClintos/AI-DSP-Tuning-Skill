# Helix REW Auto-Tuner — a Claude skill

A measurement-driven tuning assistant for **Helix / Audiotec Fischer car-audio
DSPs** (P SIX, DSP.3, M-SIX, V-SIX, …), packaged as an installable
[Claude](https://claude.ai) skill.

You give Claude your REW measurements, your Helix `.afpx` tune file, and a target
curve. It decodes both formats, works out what's actually wrong (and — just as
importantly — what *shouldn't* be touched), writes a corrected `.afpx` within the
DSP's hardware limits, and verifies every change.

## Why this can do better than trace-matching auto-EQ

Most auto-EQ (including REW's own, and DSP "target match" tools) does one thing:
look at a single magnitude curve and add filters to flatten it toward the target.
That's useful, but it's blind to *why* the curve looks the way it does — so it
happily boosts things that can't be boosted and flattens one microphone position
at the expense of the rest of the car. This skill is built around the opposite
idea: **understand the problem before touching it, and change as little as
possible.** Concretely, it does things trace-matching can't:

- **Classifies every problem before correcting it.** A dip in the response can be
  a driver resonance (EQ it), a level imbalance between left and right (change gain,
  not EQ), a phase cancellation where two speakers fight at a crossover (fix timing,
  not EQ), or a room/reflection null (leave it alone — boosting wastes headroom and
  fixes nothing). Auto-EQ treats all four the same and gets three of them wrong.
- **Detects destructive summation with an interference audit.** Given left, right,
  and combined measurements, it compares the real combined result against the
  power-sum of the two sides. If the combination sits *below* that floor, the
  speakers are cancelling — a phase problem an EQ boost can only paper over. It flags
  these instead of fighting them.
- **Knows which dips are even fixable.** Using minimum-phase / excess-group-delay
  analysis, it separates dips that EQ can genuinely correct from dips that will just
  move or reappear when you shift the mic an inch. Narrow high-frequency dips almost
  never survive real listening — it won't chase them.
- **Fixes crossovers with the right tool, in the right order.** For driver
  integration it tries polarity, then delay, then an all-pass filter (phase-only)
  *before* resorting to EQ — the order a good manual tuner uses, because EQ can't fix
  a timing problem.
- **Handles phase and imaging deliberately.** All-pass filters are used only when a
  summation null actually justifies them, with awareness of the group-delay and
  stereo-image cost — and it verifies centre image with a mono-vocal check rather
  than trusting the graph.
- **Models filter interaction and headroom.** It predicts the *combined* result of
  all filters (bands within an octave overlap and add — naively setting each gain to
  the deviation overshoots), and tracks how much boost stacks up so it can warn
  before you clip the DSP.
- **Scores perceptually, and prizes restraint.** It weights errors by audibility
  (the ear cares more about a peak than an equal dip, and more about the presence
  region than deep bass), and optimizes the *whole* measured system rather than
  flattering one trace. In head-to-head tests, tunes that pushed bigger, more
  aggressive corrections consistently *lost* to fewer, broader, better-placed ones.
- **Refuses to guess, and verifies everything.** It never fabricates `.afpx` bytes,
  never exceeds the DSP's hardware limits, never touches your crossovers or delays
  unless you ask, and decodes every file it writes back to confirm only the intended
  changes landed.

None of this is magic, and it isn't a replacement for a re-measurement: the honest
final word is always "load it, measure again, and listen." But compared to
one-curve auto-EQ, it makes far better decisions about *what deserves a filter at
all* — which is where most of the audible difference actually comes from.

## What you need

- A **Helix / Audiotec Fischer DSP** and its `.afpx` tune file (from DSP PC-Tool).
- **REW** ([Room EQ Wizard](https://www.roomeqwizard.com/)) measurements — a text
  export (`Freq  SPL  Phase`) is preferred; `.mdat` also works (with axis validation).
- A **target curve** (`frequency  level` text file). One is bundled as a default;
  bring your own (ResoNix, Harman in-car, a house curve, flat) any time.

## Install

Download [`helix-rew-tuner.skill`](helix-rew-tuner.skill) and install it through
Claude's skill flow (the file card shows **Save skill** when your account allows
skill creation). The `.skill` is self-contained — it bundles the workflow, the
Python analysis library, the reference docs, and the default target curve.

## Use

Once installed, just tell Claude something like:

> "Tune my Helix DSP — here's my REW measurement, my `.afpx`, and my target curve."

Claude will:

1. Inspect the `.afpx` and **auto-detect** which channel is which driver (from the
   crossovers) — then ask you to confirm.
2. Validate the measurement data.
3. Classify each problem region and propose a conservative, budgeted set of edits,
   showing predicted before → after.
4. Write a verified `.afpx` (preserving your crossovers and delays untouched).
5. Give you a re-measure + listening checklist — because the loaded, re-measured
   result is the only real proof.

## What's in the box

```
helix-rew-tuner/
├── SKILL.md                          the workflow Claude follows
├── scripts/
│   ├── tunelib.py                    verified DSP + acoustic-analysis core (self-tests)
│   ├── afpx.py                       decode / inspect / channel-detect / write-lint
│   └── measure.py                    load REW exports & .mdat, validate axis, targets
├── references/
│   ├── afpx_format.md                the .afpx binary + filter-code spec
│   ├── methodology.md                how to decide what to fix (the doctrine)
│   └── helix_hardware.md             filter modes, limits, model caveats
└── assets/
    └── default_incar_target.txt      a sensible default target curve (override any time)
```

Run the core library's self-tests with `python helix-rew-tuner/scripts/tunelib.py`
(prints `ALL TESTS PASSED`).

## Safety & scope

- **Crossovers and delays are never changed** unless you explicitly ask.
- All EQ is written within Helix hardware limits (P SIX: −15…+6 dB, Q 0.5–15, etc.),
  and every write is decoded back and linted to confirm only the intended slots moved.
- Predictions from magnitude (RTA/MMM) measurements don't capture phase outcomes;
  all-pass and delay work must be confirmed by re-measuring with the tune loaded.

## Model caveat

The `.afpx` format details are **verified on a Helix P SIX DSP MK2** (DSP PC-Tool 4).
Other Helix models are very likely identical but are not independently verified — for
a different model, do one controlled round-trip (write a known change, load in
PC-Tool, re-export, diff) before trusting writes. Reading/inspecting is safe on any
model.

## License

No license is set yet — add one to state how others may reuse this.
