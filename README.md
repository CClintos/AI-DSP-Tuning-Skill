# Helix REW Auto-Tuner — a Claude skill

A measurement-driven tuning assistant for **Helix / Audiotec Fischer car-audio
DSPs** (P SIX, DSP.3, M-SIX, V-SIX, …), packaged as an installable
[Claude](https://claude.ai) skill.

You give Claude your REW measurements, your Helix `.afpx` tune file, and a target
curve. It decodes both formats, works out what's actually wrong (and — just as
importantly — what *shouldn't* be touched), writes a corrected `.afpx` within the
DSP's hardware limits, and verifies every change.

## What it does

**Reads your files.** Decodes REW measurements (`.mdat` or text export) and Helix
`.afpx` tunes, auto-detects which channel is which driver from the crossovers, and
loads any target curve you point it at.

**Analyses the measurement.** Compares your response to the target using ear-based
(perceptual) smoothing, and sorts each issue into a type — tonal, left/right level
imbalance, phase cancellation, room/reflection null, or unreliable data — so each one
gets the right kind of fix instead of a blanket EQ pass. An interference audit spots
where two speakers are cancelling, and a minimum-phase check flags dips that EQ can't
usefully correct.

**Corrects with the right tool.** Uses the full Helix filter set — parametric EQ,
low/high shelves, and all-pass (phase) filters — plus delay and polarity guidance for
crossover integration, in the order a good manual tuner works: timing first, EQ last.
Left/right corrections stay matched for a stable centre image, and filter interaction
and headroom are modelled so a stack of bands doesn't overshoot or clip the DSP.

**Writes safely and verifies.** Stays inside the DSP's hardware limits, leaves your
crossovers and delays untouched unless you ask, and decodes every file it writes back
to confirm only the intended changes landed.

**Keeps you honest.** Predictions from a single measurement aren't the final word —
it hands back a re-measure and listening checklist, because the loaded, re-measured
result is the real test.

## The tuning toolkit, in plain terms

A down-to-earth tour of what the tool actually reaches for, and when. None of these
are magic bullets — each has a job it's good at and a cost when misused, and the
skill tries to respect both.

**Parametric EQ — the workhorse.** A bell-shaped boost or cut at a chosen frequency
and width. Used mostly for *cuts*: taming a peak or a driver resonance. Cuts are
cheap and safe; boosts eat headroom and can push the DSP toward clipping, so the
tool prefers turning things down over up, and it models how neighbouring bands
overlap so a stack of filters doesn't quietly overshoot.

**Shelf filters — broad tone shaping.** A shelf lifts or drops *everything* above or
below a hinge frequency — a tone control done properly. A low shelf adds broad
bottom-end weight (a bigger, warmer bass without touching your crossover); a high
shelf handles the top octaves — most usefully a gentle high-shelf *cut* to take the
edge off a bright, hard-surfaced cabin. The honest limit: a shelf is for a broad
tilt, not a specific bump. If a problem starts and ends within a region, that's a
job for a bell — and the tool actually checks, numerically, whether a shelf can
reproduce the shape before it uses one.

**All-pass filters — the phase tool most people skip.** This is the interesting one.
An all-pass changes *nothing* about loudness — it makes nothing louder or quieter.
What it changes is *timing* (phase) around a chosen frequency. Why would you want
that? Because when two speakers play the same note — a midbass and a sub through a
crossover, or your left and right doors — they can arrive slightly out of step and
partly *cancel*, leaving a dip that no amount of EQ can fill (boost both and they
still cancel). An all-pass rotates one speaker's timing so they add together instead
of fighting, filling a null that would otherwise be permanent. The honest costs: it
adds a little group delay, and a one-sided all-pass can nudge the stereo image. So
the tool uses it sparingly — only when the measurements actually show two speakers
cancelling (not just any dip), keeps it as gentle as possible, and tells you to
confirm the centre image by ear with a mono vocal afterward.

**Delay & polarity — timing first.** Before reaching for an all-pass, the tool
checks the simpler timing fixes: flipping a speaker's polarity, or nudging its delay
by a fraction of a millisecond. These have no tonal side effects and often solve a
crossover problem outright, so they come first. It recommends them rather than
silently rewriting your time alignment.

### How it actually decides

**It listens like an ear, not a ruler.** Measurements are smoothed the way hearing
works — broadly down low (where the ear blends things together), more finely up high
— so it doesn't burn filters "fixing" wrinkles nobody can hear. A peak is treated as
more objectionable than an equal dip (it is), and the presence region where the ear
is most sensitive is weighted accordingly.

**It respects the whole car, not one mic spot.** With left/right and multi-position
measurements it can tell a stable problem from one that only exists at a single
point, and it keeps left/right corrections matched for a solid centre image unless
the data proves the two sides genuinely differ.

**It anchors level sensibly.** Rather than chasing an absolute loudness number, it
matches the *shape* of your target and lets overall level float — so dropping in a
different target curve just changes the voicing, not the whole tune.

**It stays inside the lines.** Every gain respects the DSP's real limits, your
crossovers and delays are left exactly as you set them unless you ask, and every
file it writes is decoded back and checked so you know only the intended changes
landed.

The through-line: a filter is something you should have to *justify*, not spray at a
graph. That restraint — plus using the *right kind* of filter for each problem — is
where the audible improvement really comes from.

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
