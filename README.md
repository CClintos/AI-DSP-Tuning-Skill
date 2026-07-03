# Helix REW Auto-Tuner — a Claude skill

A measurement-driven tuning assistant for **Helix / Audiotec Fischer car-audio
DSPs** (P SIX, DSP.3, M-SIX, V-SIX, …), packaged as an installable
[Claude](https://claude.ai) skill.

You give Claude your REW measurements, your Helix `.afpx` tune file, and a target
curve. It decodes both formats, works out what's actually wrong (and — just as
importantly — what *shouldn't* be touched), writes a corrected `.afpx` within the
DSP's hardware limits, and verifies every change.

Its edge over generic auto-EQ is **judgment**: it classifies each problem (tonal
vs level vs phase vs modal-null vs bad-measurement) before correcting, spends a
limited filter budget where it improves the whole system, and refuses to "fix"
things that measurement can't fix (reflections, nulls, phase problems dressed up
as dips).

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
