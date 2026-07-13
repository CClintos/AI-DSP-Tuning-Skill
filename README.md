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

**Voices the target first — the most audible single decision.** Overall tonal tilt
matters more than any individual filter, and matching a curve exactly isn't the same
as sounding good (a studio-flat target reliably sounds bright and thin in a car). It
measures where your system and your target curve currently sit, tilt-wise, against the
typical good-in-car range, then offers to voice the target — warmer/brighter, more/less
bass weight, more/less presence, more/less air — in listener language, before any EQ
is proposed. Voicing is a taste layer on the goal; the correction that follows is still
fully measurement-driven.

**Corrects with the right tool.** Uses the full Helix filter set — parametric EQ,
low/high shelves, and all-pass (phase) filters — plus delay and polarity, in the order
a good manual tuner works: timing first, EQ last. A cross-correlation delay estimate
double-checks the usual phase-based search (and flags disagreement as a "don't trust
this" signal instead of picking one). Left/right corrections stay matched by default;
where they need to genuinely differ, it can flag exactly where and how much the two
sides diverge in the imaging band, and target closing that gap directly.

**Separates real problems from where-you-put-the-mic.** If you give it a few
measurements from different positions around the seat instead of just one, it tells
real driver/room features (present everywhere) apart from position-specific
comb-filtering (gone or shifted a few inches away) — the difference between something
worth correcting and something that would only make one exact spot sound better. A
Moving Mic Method (MMM/RTA) capture — mic swept around the head during the
measurement — is the continuous version of the same idea, and is the **preferred**
source for tonal/EQ decisions when you have it (fixed sweeps stay the only valid tool
for anything phase-domain). The one thing to get right when capturing it: **engine
off** — RTA has no noise rejection the way a sweep's deconvolution does, so a real dip
can otherwise read as falsely filled by cabin noise.

**Writes safely and verifies.** Stays inside the DSP's hardware limits, leaves your
crossovers and delays untouched unless you ask, and decodes every file it writes back
to confirm only the intended changes landed. A delay can be written directly once
you've confirmed a specific number — never automatically — and that write is verified
too.

**Keeps you honest, both before and after.** Predictions from a single measurement
aren't the final word — it hands back a re-measure and listening checklist targeting
exactly what's still unproven. And when that re-measure comes back, it's not just
eyeballed: each written band gets checked against what actually happened, correctly
tolerating an ordinary run-to-run difference (playback level, mic position) rather than
mistaking it for the correction failing.

## The tuning toolkit

The full Helix filter set, each used for what it's good at:

- **Parametric EQ** — mostly cuts, for peaks and driver resonances. Overlapping
  bands are modelled together so a stack doesn't overshoot, and boosts are limited to
  protect headroom.
- **Shelf filters** — broad tonal shaping: a low shelf for bottom-end weight, a high
  shelf (usually a gentle cut) to take the edge off a bright cabin. It checks
  numerically whether a shelf fits the shape before choosing one over a bell.
- **All-pass filters** — phase alignment where two drivers cancel through a crossover
  or between left and right. Applied only where the measurement shows real
  cancellation, kept gentle, with a mono-vocal image check flagged for afterward.
- **Delay & polarity** — tried before an all-pass, since they fix timing with no
  tonal cost. A found delay can be written directly once you've seen the specific
  number and confirmed it — never applied automatically from a search result — and
  the write is verified to have changed only that one value.

### How it decides

- **Perceptual weighting** — ear-based smoothing (broad at low frequencies, finer up
  high), peaks weighted over dips, the presence region prioritised.
- **Whole car, not one mic** — left/right and multi-position measurements (fixed or
  swept/MMM) separate stable problems from single-point artefacts; left/right stays
  matched unless the data shows the sides genuinely differ.
- **Timing before tone, and never both at once on the same guess** — a phase fix
  (polarity/delay/all-pass) and an EQ band in the same crossover-adjacent region are
  never proposed together against the same unconfirmed data: the EQ prediction goes
  stale the moment the phase fix changes what it was measured against, so one waits
  for a re-measure before the other is trusted.
- **Shape-anchored level** — it matches the shape of your target and lets overall
  level float, so swapping in a different curve changes the voicing, not the tune.
- **Within limits, verified** — every gain respects the DSP's hardware limits,
  crossovers and delays are left as you set them unless you ask, and every written
  file is decoded back and checked.

## What you need

- A **Helix / Audiotec Fischer DSP** and its `.afpx` tune file (from DSP PC-Tool).
  Newer `.pct6` files (DSP PC-Tool 6) have basic beta support — see below.
- **REW** ([Room EQ Wizard](https://www.roomeqwizard.com/)) measurements — a text
  export (`Freq  SPL  Phase`) is preferred; `.mdat` also works (with axis validation).
- A **target curve** (`frequency  level` text file). One is bundled as a default;
  bring your own (ResoNix, Harman in-car, a house curve, flat) any time.

## Install

Download [`helix-rew-tuner.skill`](helix-rew-tuner.skill) and install it through
Claude's skill flow (the file card shows **Save skill** when your account allows
skill creation). The `.skill` is self-contained — it bundles the workflow, the
Python analysis library, the reference docs, and the default target curve.

## Best way to run it

- **Surface: Claude Code** (terminal, desktop app, or IDE extension). The skill
  reads your measurement and tune files off disk, runs its bundled Python, and writes
  the corrected `.afpx` back to a real location — all of which need local file access
  and code execution. You *can* run the conversation in Claude.ai chat by uploading
  files, but you'll be copy-pasting and won't get a written `.afpx` back, so it's a
  weaker fit for the full loop.
- **Model: an Opus-class (strongest available) model for the tuning itself.** The
  judgment — classifying each problem, predicting how filters interact, catching a
  bad correction — is where model quality shows. A faster model like Sonnet is fine
  for the mechanical steps (decoding a file, inspecting channels, changing one gain).
- **Thinking: extended thinking on for the analysis and proposal steps.** The tool
  weighs several competing fixes per region and predicts the summed result before
  writing; the extra budget improves those calls. Not needed for routine inspection.

In short: **Claude Code + an Opus-class model + extended thinking** for real tuning
sessions; a lighter model is fine for quick mechanical edits.

## Exporting your measurements from REW

Text export is preferred over `.mdat` — the frequency axis is explicit rather than
reconstructed, and phase comes along with it (which the phase/crossover analysis
needs). Getting all your measurements out as text is one step:

1. Take your measurements in REW and give them clear names as you go (e.g. `Front L
   High`, `Front R High`, `Front L Low`, `Front R Low`, `Sub`, `System Sum`,
   `Tweeters Together`, `Mid Bass Together`) — the names carry over into the exported
   filenames, and the skill uses them to work out what each trace is.
2. **File → Export → Export All.** This exports every measurement in your list to
   text files in one go, using each measurement's name as the filename — no need to
   select and export them one at a time.
3. Upload the exported measurement files to Claude along with your `.afpx` and
   target curve.

(If your REW build doesn't show "Export All", `File → Export → Export measurement as
text` does the same thing one measurement at a time — select a measurement, export,
repeat.)

## Use

Once installed, just tell Claude something like:

> "Tune my Helix DSP — here's my REW measurement, my `.afpx`, and my target curve."

Claude will:

1. Inspect the `.afpx` and **auto-detect** which channel is which driver (from the
   crossovers) — then ask you to confirm.
2. Validate the measurement data.
3. Offer to voice the target (tilt/bass/presence/air) before proposing anything —
   the goal, not the correction, comes first.
4. Classify each problem region and propose a conservative, budgeted set of edits,
   showing predicted before → after with a confidence level per claim.
5. Write a verified `.afpx` (preserving your crossovers and delays untouched).
6. Give you a re-measure + listening checklist targeting exactly what's still
   unproven — because the loaded, re-measured result is the only real proof.
7. When that re-measure comes back, check each written band against it instead of
   just eyeballing the new plot, and flag anything that didn't land as predicted.

## What's in the box

```
helix-rew-tuner/
├── SKILL.md                          the workflow Claude follows
├── scripts/
│   ├── tunelib.py                    verified DSP + acoustic-analysis core (self-tests)
│   ├── afpx.py                       decode / inspect / channel-detect / write-lint
│   ├── measure.py                    load REW exports & .mdat, validate axis, targets
│   ├── pipeline.py                   one deterministic analysis CLI -> one JSON report
│   └── pct6.py                       BETA, personal-use-only .pct6 decode/encode
├── references/
│   ├── afpx_format.md                the .afpx binary + filter-code spec
│   ├── pct6_format.md                the .pct6 container format + BETA caveats
│   ├── methodology.md                how to decide what to fix (the doctrine)
│   └── helix_hardware.md             filter modes, limits, model caveats
└── assets/
    └── default_incar_target.txt      a sensible default target curve (override any time)
```

Every script self-tests standalone, no real measurement/tune files needed:

```
python helix-rew-tuner/scripts/tunelib.py    # -> ALL TESTS PASSED
python helix-rew-tuner/scripts/afpx.py selftest
python helix-rew-tuner/scripts/pct6.py selftest
python helix-rew-tuner/scripts/pipeline.py selftest
```

## Safety & scope

- **Crossovers are never changed**, and a delay is written only after you've seen the
  specific number and explicitly confirmed that one change — never automatically from
  a search result.
- All EQ is written within Helix hardware limits (P SIX: −15…+6 dB, Q 0.5–15, etc.),
  and every write is decoded back and linted to confirm only the intended slots moved.
- Magnitude-only measurements (RTA/MMM) are the **preferred** source for tonal/EQ
  decisions — capture with the engine off, since RTA has no noise rejection — but
  can't capture phase outcomes; all-pass and delay work still needs a fixed,
  phase-valid sweep, and must be confirmed by re-measuring with the tune loaded.

## Model caveat

The `.afpx` format details are **verified on a Helix P SIX DSP MK2** (DSP PC-Tool 4).
Other Helix models are very likely identical but are not independently verified — for
a different model, do one controlled round-trip (write a known change, load in
PC-Tool, re-export, diff) before trusting writes. Reading/inspecting is safe on any
model.

## Beta: `.pct6` support (DSP PC-Tool 6 / Helix DSP PRO)

DSP PC-Tool 6 introduced a newer `.pct6` save format (adds the CONDUCTOR
configuration, more output channels). Basic decode/encode support exists in
`scripts/pct6.py`, but it's held to a **much lower confidence bar** than
`.afpx` — **personal/interoperability use only, not a general-purpose
cracking tool:**

- **No-password saves only.** Password-protected `.pct6` files use a different,
  unidentified scheme and aren't supported — the decoder raises a clear error
  rather than returning garbage if it doesn't see valid tune XML come out.
- **Verified against real files on PC-Tool 6.01.08 only.** The container key is
  version-fragile — Audiotec Fischer could change it in a future release
  without notice. Always check that a decode actually produces plausible
  `<ATF ...>` XML before trusting it on a PC-Tool version you haven't tried.
- Read [`references/pct6_format.md`](helix-rew-tuner/references/pct6_format.md)
  in full before touching a real `.pct6` file — it covers the container format,
  provenance, and what's different from `.afpx` (more channels, less-verified
  filter-type mapping, non-strictly-well-formed XML).

## License

No license is set yet — add one to state how others may reuse this.
