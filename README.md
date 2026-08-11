# AI DSP Tuning Skill

A measurement-driven tuning assistant for **Helix / Audiotec Fischer car-audio
DSPs** (P SIX, DSP.3, M-SIX, V-SIX, …). Works as an installable
[Claude](https://claude.ai) skill or, via `AGENTS.md`, with
[OpenAI Codex](https://openai.com/codex/) and other agents that read
repo-level `AGENTS.md` instructions.

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

**Claude (skill):** download [`helix-rew-tuner.skill`](helix-rew-tuner.skill)
and install it through Claude's skill flow (the file card shows **Save skill**
when your account allows skill creation). The `.skill` is self-contained — it
bundles the workflow, the Python analysis library, the reference docs, and the
default target curve. For Claude Code specifically, you can instead clone this
repo and copy `helix-rew-tuner/` into `~/.claude/skills/helix-rew-tuner/` — no
`.git` folder or repo-root files in that destination, just the skill folder's
contents.

`helix-rew-tuner.skill` is a deterministic zip of the `helix-rew-tuner/`
folder (`__pycache__` and bytecode excluded). After any edit under the skill,
regenerate the archive and generated Codex wrapper, then check parity:

```text
python tools/build_skill.py --write
python tools/build_skill.py --check
```

The writer uses stored (uncompressed) entries, sorted paths, fixed ZIP
timestamps, fixed file modes, and normalized text line endings, so identical
sources produce identical package bytes across supported runtimes. The check
mode is read-only and fails on stale generated instructions or metadata, stale
archive contents, or broken methodology anchors.

**Codex (or any `AGENTS.md`-reading agent):** clone this repo into (or
alongside) the project you're working in. The generated root `AGENTS.md` adapts
the canonical `references/core_workflow.md` doctrine to Codex's auto-loaded
instructions convention — no separate install step. It points into
`helix-rew-tuner/scripts/` and `helix-rew-tuner/references/` for the same
analysis code and docs used by the installable skill.

## Best way to run it

- **Surface: an agent with real local file access and code execution** — Claude
  Code (terminal, desktop app, IDE extension) or Codex (CLI/IDE), not a plain
  chat window. It reads your measurement and tune files off disk, runs its
  bundled Python, and writes the corrected tune back to a real location — all of
  which need a filesystem and a shell, not just a chat box. You *can* run the
  conversation in Claude.ai chat by uploading files, but you'll be copy-pasting
  and won't get a written `.afpx` back, so it's a weaker fit for the full loop.
- **Model: the strongest reasoning model your agent offers, for the tuning
  itself.** The judgment — classifying each problem, predicting how filters
  interact, catching a bad correction — is where model quality shows. A faster/
  cheaper model is fine for the mechanical steps (decoding a file, inspecting
  channels, changing one gain).
- **Reasoning budget: turn it up for the analysis and proposal steps** — extended
  thinking in Claude, high reasoning effort in Codex. The tool weighs several
  competing fixes per region and predicts the summed result before writing; the
  extra budget improves those calls. Not needed for routine inspection.

In short: **a code-capable agent + its strongest model + a high reasoning budget**
for real tuning sessions; a lighter model is fine for quick mechanical edits.

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

### On Claude

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

### On Codex

1. **Clone this repo** into, or as a sibling of, whatever directory Codex is
   working in — Codex auto-loads `AGENTS.md` for the directory tree it's running
   in, so there's no separate "install" step the way a Claude skill needs one.
   (If Codex is running somewhere unrelated to the repo, just reference the repo
   path in your prompt so it goes and reads `AGENTS.md` first.)
2. **Give it your files** — the REW export(s), the `.afpx`/`.pct6` tune, and a
   target curve if you have one (drop them in the working directory, or point
   Codex at their paths).
3. **Ask for it the same way you would with Claude:**

   > "Tune my Helix DSP — here's my REW measurement, my `.afpx`, and my target
   > curve."

4. Codex follows the identical seven-step workflow above — generated
   `AGENTS.md` and the installable `SKILL.md` both route to the canonical
   `references/core_workflow.md`, which calls into the same scripts and
   references. The only difference is which agent is driving; the analysis,
   restraint rules, and write/verify discipline don't change.

## What's in the box

```
helix-rew-tuner/
├── SKILL.md                          skill metadata + platform routing
├── requirements.txt                 minimum runtime dependencies
├── agents/openai.yaml               Codex skill catalogue metadata
├── scripts/
│   ├── tunelib.py                    verified DSP + acoustic-analysis core (self-tests)
│   ├── afpx.py                       decode / inspect / channel-detect / write-lint
│   ├── measure.py                    load REW exports & .mdat, validate axis, targets
│   ├── pipeline.py                   one deterministic analysis CLI -> one JSON report
│   ├── pct6.py                       BETA, personal-use-only .pct6 decode/encode
│   ├── alpine_jssh.py                BETA, personal-use-only Alpine .jssh decode/encode
│   ├── preflight.py                  read-only dependency and path readiness check
│   ├── benchmark.py                  deterministic optimizer regression benchmark
│   ├── decay.py                      decay / ringing analysis helpers
│   └── repeatability.py              repeat-capture drift and consistency helpers
├── references/
│   ├── afpx_format.md                the .afpx binary + filter-code spec
│   ├── pct6_format.md                the .pct6 container format + BETA caveats
│   ├── alpine_jssh_format.md         the Alpine .jssh container format + BETA caveats
│   ├── core_workflow.md              canonical workflow shared by agent wrappers
│   ├── methodology.md                how to decide what to fix (the doctrine)
│   ├── helix_hardware.md             filter modes, limits, model caveats
│   └── tune_plan_schema.md            versioned plan/apply JSON contract
└── assets/
    └── default_incar_target.txt      a sensible default target curve (override any time)

tools/
└── build_skill.py                    generated-wrapper/package drift check and writer

tests/
├── test_build_skill.py               build, metadata, anchor, and archive parity tests
├── test_pipeline_apply.py            deterministic tune plan/apply integration tests
├── test_preflight_and_benchmark.py   install and optimizer benchmark tests
└── test_tunelib_regressions.py       acoustic-analysis and optimizer regressions
```

Run the complete unit/integration suite with:

```text
python -m unittest discover -s tests -p "test_*.py" -v
```

The self-test-capable DSP/file scripts also run standalone without real
measurement or tune files:

```
python helix-rew-tuner/scripts/tunelib.py    # -> ALL TESTS PASSED
python helix-rew-tuner/scripts/afpx.py selftest
python helix-rew-tuner/scripts/pct6.py selftest
python helix-rew-tuner/scripts/alpine_jssh.py selftest
python helix-rew-tuner/scripts/pipeline.py selftest
```

Preflight, benchmark, and generated-package checks are separate executable
gates:

```text
python helix-rew-tuner/scripts/preflight.py --json
python helix-rew-tuner/scripts/benchmark.py --json
python tools/build_skill.py --check
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

## Beta: Alpine `.jssh` support - Thanks to Pascal BH!

`scripts/alpine_jssh.py` decodes/encodes Alpine DSP PC-Tool's `.jssh` preset
format (confirmed on a PXE-X121-12EV) — a **different vendor's** DSP entirely,
ported from a sibling project's independent reverse-engineering rather than
built here. Same confidence bar as `.pct6`, **personal/interoperability use
only:**

- **Confirmed valid JSON** under a position-dependent XOR (`byte_index % 256`,
  not a short repeating key) — genuinely reverse-engineered, not a guess: the
  source project verified it against six real captured presets, including one
  byte-for-byte match against Alpine's own output for an identical change.
- **Per-field confidence varies** — every getter/setter in `alpine_jssh.py`
  carries the same `CONFIRMED` / `assumed, not yet isolated` marker the source
  documented, field by field; some (channel gain, delay, mute, polarity) are
  byte-perfect confirmed, others (LPF filter type) are inferred from structural
  symmetry and flagged as such.
- **Not yet independently re-verified from this Python port against a real
  file** — run `alpine_jssh.roundtrip_identical()` against your own real
  `.jssh` before trusting a generated file on real hardware; that's the actual
  safety check, not the bundled synthetic selftest.
- Read [`references/alpine_jssh_format.md`](helix-rew-tuner/references/alpine_jssh_format.md)
  in full before touching a real `.jssh` file — it covers the full field table,
  the Q lookup table, and a noted open discrepancy between the UI-documented
  PEQ gain range and the wider range the byte format itself accepts.

## How it actually works — and why it's not just "EQ to a line"

A naive auto-EQ does one thing: measure a curve, subtract it from a target,
turn the difference into filters. That approach reliably makes a tune *worse*
in a car, for reasons that have nothing to do with filter quality:

- **A dip isn't always a magnitude problem.** Two drivers can be individually
  healthy and still cancel each other through a crossover or between left and
  right — boosting that "dip" doesn't fix the cancellation, it just burns
  headroom driving two signals further apart.
- **A null isn't always correctable.** A room mode or a reflection can look
  exactly like a driver problem on a single measurement, but chase the mic a
  few inches and it moves or vanishes — "fixing" it only helps that one exact
  seating position, and can hurt everywhere else.
- **Not every frequency region has reliable phase**, even when the magnitude
  trace looks clean — reflections dominate the fine structure of measured
  phase well before they visibly disturb SPL. Timing corrections built on bad
  phase data are worse than no correction.
- **Filters interact.** Fitting each band independently against the raw
  deviation and stacking them is how you get an overshoot nobody asked for the
  moment two bands sit within an octave of each other.
- **The target curve itself is a judgment call, not a fixed truth.** Matching
  a studio-flat curve exactly in a car reliably sounds bright and thin — the
  target has to be voiced for the room before it's worth chasing.

So before anything gets written, every region is put through a **classifier**
— tonal/driver-local, L/R level imbalance, phase cancellation, unstable
room/reflection null, or unreliable measurement — and only the first two ever
turn into an EQ move. The other three get a *different* kind of fix (timing,
gain, nothing) or get reported as non-correctable, on purpose.

### What actually gets measured, concretely

These aren't hand-wavy heuristics — they're specific, testable functions in
`scripts/tunelib.py`, each with a self-test:

- **`interference_audit`** — computes both the *incoherent power-sum* (the
  floor two drivers would hit if totally uncorrelated) and the *coherent
  voltage-sum* (the ceiling if perfectly in phase) from two solo measurements,
  then checks whether the real measured "together" trace falls *below* the
  power-sum floor. If it does, that's destructive interference — a phase
  problem, not a level problem — and boosting it is flagged as the wrong tool
  before a filter is ever proposed.
- **`crossover_confidence`** — bundles that interference check with phase
  reliability and prediction-confidence into one go/no-go verdict for a
  specific crossover band, so "is this crossover trustworthy to touch" is a
  single, repeatable call instead of eyeballing three separate plots.
- **`spatial_consistency`** — given three or more mic-position measurements,
  computes the per-frequency spread across positions and turns it into a
  continuous 0–1 confidence weight. A real driver/room feature stays roughly
  the same level everywhere; a comb-filtering artifact from one exact mic spot
  collapses a few inches away. Only what's *consistent* across positions gets
  full weight in the fix.
- **`phase_linearity_residual`** — fits a straight line (pure time delay) to
  the unwrapped phase in a band and reports the RMS residual in degrees.
  Real driver phase over its own passband is close to linear; reflections add
  wiggle on top. Below ~100° residual is trustworthy for timing decisions;
  above ~300–450° is reflection-dominated and gets rejected for anything
  phase-domain, no matter how clean the magnitude trace looks.
- **`excess_gd_mask`** — separates minimum-phase regions (flat excess group
  delay — EQ genuinely works here) from non-minimum-phase regions (excess-GD
  spikes, usually at sharp notches — EQ *cannot* fix these no matter how the
  filter is tuned; only phase/delay/polarity work can).
- **`inert_band_check`** — before trusting a proposed EQ band, checks whether
  the target driver is more than ~6 dB below whatever's dominating the summed
  response at that frequency. If so, the band is cosmetic — it changes that
  driver's own curve but the dominant driver swamps it in the sum, so it
  barely moves what you actually hear.
- **`reaches_target_after_boost`** — simulates a proposed boost capped at the
  hardware ceiling and checks whether the result actually reaches target. A
  boost that's maxed out and still falls short is the signature of a phase
  problem masquerading as a magnitude one — the fix isn't "more gain," it's
  going back to the interference audit.
- **`gating_warning`** — REW's windowed/gated measurements have a hard
  low-frequency trust floor set by the gate length; below it, the data is a
  reflection-of-a-reflection, not the driver. The tool computes that floor
  from the actual gate length used and refuses to trust anything below it.
- **`lr_match_report`** — a stereo center image (vocals, kick, anything panned
  center) is built from left and right summing coherently; wherever the two
  sides diverge in level, the image pulls toward the louder side *at that
  frequency* — audible as smear even when each channel looks fine on its own.
  This flags exactly where and how much the sides diverge in the
  image-critical band (~300 Hz–6 kHz), rather than just reporting an averaged
  L/R error that can hide a real, localized mismatch.

### What it scores a tune on

`tune_scorecard` is the single function every before/after and every
tune-vs-tune comparison runs through, so the math is identical every time
instead of being re-derived by hand each session:

- **`sum_rms_db`** — plain RMS deviation from target across the audible band.
- **`sum_wrms_img_db`** — the same, but weighted up in the 200 Hz–6 kHz
  imaging band, because errors there cost more perceptually than the same
  error at 30 Hz or 15 kHz.
- **`worst_dev_db`** — the single worst deviation in the 100 Hz–8 kHz range,
  so a tune that looks good on average but has one bad 3 dB notch can't hide
  behind a flattering aggregate.
- **`mid_balance_db` / `tweeter_balance_db`** (when L/R traces are supplied) —
  median and RMS left/right mismatch in the mid and tweeter imaging bands,
  the two frequency ranges where L/R error is most audible as image smear.

No single number is treated as "the score." A tune that improves
`sum_rms_db` while making `worst_dev_db` or an L/R balance metric worse is not
a win — the workflow's step 4 requires stating confidence *per claim*, not
one aggregate, precisely so a good average can't paper over one bad region.

### After the write: closing the loop instead of trusting the prediction

Everything above only produces a *prediction*. `predicted_vs_measured` is
what happens when the user comes back with a fresh, loaded-tune measurement:
it auto-aligns a broadband level offset using only the *untouched*
frequencies (so a re-measure taken at a quieter volume that day doesn't read
as "the EQ failed"), compares octave-smoothed regions rather than raw bins
(so ordinary mic-position ripple doesn't either), and grades each written
band `confirmed`, `diverged`, `reverted_recommended`, or `inconclusive` —
downgrading to `inconclusive` rather than forcing a verdict when confidence
is genuinely low. `reverted_recommended` is treated as an instruction to
reconsider that band, not a suggestion.

### The restraint budget

None of the above is used to justify writing *more* filters — it's used to
justify writing *fewer*, better-targeted ones. Overlapping candidate bands
are modelled jointly and the summed prediction is what's evaluated, never a
per-band gain-equals-deviation guess. Boosts are limited to protect headroom;
cuts are preferred. Left/right stays matched unless the data — not a guess —
proves the sides genuinely differ. When two candidate fixes score equally,
the one that changes less wins. That bias toward doing less is deliberate:
across real tuning sessions, the aggressive auto-EQ approach — more bands,
bigger moves, tighter curve-matching — consistently loses to the restrained
one on `tune_scorecard`'s whole-system metrics, not just on "sounds more
natural" intuition.

## License

No license is set yet — add one to state how others may reuse this.
