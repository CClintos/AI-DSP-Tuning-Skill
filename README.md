# AI DSP Tuning Skill

[![Validate](https://github.com/CClintos/AI-DSP-Tuning-Skill/actions/workflows/validate.yml/badge.svg)](https://github.com/CClintos/AI-DSP-Tuning-Skill/actions/workflows/validate.yml)

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
a good manual tuner works: driver-local EQ the solos justify, re-measure, then
timing (delay, polarity, all-pass) on the corrected drivers, then broad system tone —
EQ moves phase, so timing is rechecked if a later unequal EQ change touches it. A
cross-correlation delay estimate
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
crossovers untouched unconditionally, and decodes every file it writes back to
confirm only the intended changes landed. A delay can be written directly once
you've confirmed a specific number — never automatically — and that write is
verified too.

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
- **A dip is not automatically a thing to fill** — before proposing a boost, it
  checks whether the dip is a shape deficit EQ can actually correct or a
  cancellation that will simply eat the gain, and says which. It's deliberately
  cautious about objecting, so an objection is worth reading rather than clicking
  through — and it tells you when your measurement is too smoothed to support the
  question being asked at all.
- **Within limits, verified** — every gain respects the DSP's hardware limits,
  crossovers are never written or changed, delays require confirmation of the
  specific value, and every written file is decoded back and checked.

## What you need

- A **Helix / Audiotec Fischer DSP** and its `.afpx` tune file (from DSP PC-Tool).
  Newer `.pct6` files (DSP PC-Tool 6) have basic beta support — see below.
- **REW** ([Room EQ Wizard](https://www.roomeqwizard.com/)) measurements — a text
  export (`Freq  SPL  Phase`) or the `.mdat` itself (`session.mdat::Front L Tweeter`),
  which the skill reads by structure, axis and all.
- A **target curve** (`frequency  level` text file). One is bundled as a default;
  bring your own (ResoNix, Harman in-car, a house curve, flat) any time.
- **Python 3.10+ with NumPy and SciPy** on whatever machine/container your agent
  runs its shell tool in (`pip install -r helix-rew-tuner/requirements.txt`) —
  the skill executes real Python locally, it doesn't just describe the analysis.
  If you're not sure your environment is ready, run
  `python helix-rew-tuner/scripts/preflight.py --json` first; it checks the
  Python version, both dependencies, and file layout without touching any
  tune or measurement file.

## Install

`SKILL.md`'s frontmatter carries a `metadata.version` field (currently
`1.24.0`) so you can tell whether an already-installed copy is current — open
your installed `SKILL.md` and compare its version against this repo's; if
it's older, redownload/re-copy per below. There's no auto-update; this skill
has no persistent connection back to GitHub once installed.

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

**If you tune by moving mic (MMM):** before a session, ask for a capture plan
(`pipeline.py capture-plan --goal tone lr bass --afpx yourtune.afpx`): the exact
captures to make and how to name them, the REW settings, how many averages make
each capture long enough, the level your mic can take, and the safety limits.
Once the tune sits on the target, `pipeline.py finish` lists what still
decides the sound: the last broad peaks, whether each instrument images in one
place, stage height and the sub. Score a listening session, or copy a judge's
sheet, on `helix-rew-tuner/assets/emma_listening_sheet.html` (the 280-point
EMMA sheet, offline on a phone) and `finish --heard` reads it against the
captures. Afterwards, point the agent at the files or the session `.mdat`
(`pipeline.py next --captures <folder>`): it audits them and runs what they
support. Short captures, mic-handling noise and mixed settings were the commonest
problems in real sessions, and the plan prevents them.

## Exporting your measurements from REW

You can hand over the `.mdat` itself: the skill reads it by structure (REW's own
frequency axis, the unsmoothed values, the mic, the RTA settings and the
calibrated levels) and takes `session.mdat::LF Mid XO` or `session.mdat::#3`
anywhere it takes a file. A `.mdat` contains local paths (your user name, cal
file locations), so check before sharing one publicly. Text exports work
just as well, and getting all your measurements out as text is one step:

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

Expect a few short confirmations, not one big auto-apply. Your original tune
file is never modified — every write creates a new, separate output file, so
there's nothing to undo in PC-Tool if a proposal doesn't work out — and each
proposed edit is confirmed individually before it's written. A basic tune is
normally a handful of quick yes/no exchanges as you go.

### On Claude

Once installed, just tell Claude something like:

> "Tune my Helix DSP — here's my REW measurement, my `.afpx`, and my target curve."

Claude will:

1. Inspect the `.afpx` and **auto-detect** which channel is which driver (from the
   crossovers) — then ask you to confirm.
2. Validate the measurement data.
3. Offer to voice the target (tilt/bass/presence/air) before proposing anything —
   the goal, not the correction, comes first.
4. Classify each problem region and propose a conservative, budgeted set of edits
   (starting from the deterministic `pipeline.py propose`, which averages multiple
   mic positions and gates boosts), showing predicted before → after with a
   confidence level per claim.
5. Write a verified `.afpx` only through `pipeline.py plan` followed by
   `pipeline.py apply`, always preserving crossovers and requiring a specific
   confirmation for every edit.
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

Every AFPX file write uses the versioned
[`tune_plan_schema.md`](helix-rew-tuner/references/tune_plan_schema.md): the
plan binds `source_sha256`, a distinct not-yet-existing `output_path`, all
edits, and per-edit `confirmations`. `pipeline.py apply` exclusively creates
the output and prints a verification manifest with hashes, normalized edits,
and decoded write checks. Direct `afpx.py` write helpers are implementation/reference only.
A phase-domain plan (delay or T=19/20 APF) is
applied and remeasured before a new plan can contain EQ-domain PEQ or shelves.

## What's in the box

```
helix-rew-tuner/
├── SKILL.md                          skill metadata + platform routing
├── requirements.txt                 minimum runtime dependencies
├── agents/openai.yaml               Codex skill catalogue metadata
├── scripts/
│   ├── tunelib.py                    verified DSP + acoustic-analysis core (self-tests)
│   ├── afpx.py                       decode / inspect / internal write verification
│   ├── measure.py                    load REW exports & .mdat, full REW header, targets
│   ├── mdat.py                       read REW .mdat files by structure (Java object stream)
│   ├── capture_audit.py              capture audit, automatic capture profile, moving-mic floor
│   ├── mmm.py                        coherence, four-capture alignment, peak stability,
│   │                                 crossover check, listening-level/road voicing, preferences
│   ├── loudness.py                   ISO 226:2003 equal-loudness contours
│   ├── frames.py                     per-block MMM statistics from a WAV or REW frames
│   ├── signals.py                    EXPERIMENTAL test signals and their analysis
│   ├── pipeline.py                   analysis, EQ proposal, and required AFPX plan/apply boundary
│   ├── pct6.py                       BETA source-bound .pct6 decode/encode
│   ├── alpine_jssh.py                BETA source-bound Alpine .jssh decode/encode
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
```

Build tools, evaluations, audits, the test suite and the release gate are described in [docs/development.md](docs/development.md).

## Safety & scope

- **Your original tune file is never modified.** Every write creates a new,
  separate output file — `pipeline.py apply` refuses to overwrite an existing
  path — so your source `.afpx`/`.pct6`/`.jssh` is exactly as it was if you
  don't like a proposal; there's nothing to undo in PC-Tool.
- **Every proposed edit is confirmed individually before it's written** —
  nothing is ever applied in bulk from one "yes, tune it." Expect a handful of
  short confirmations for a basic tune, not one big automatic apply.
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
- **Verified against real no-password files on PC-Tool 6.01.08 and 6.03.04.**
  This is limited container evidence, not a promise for every device or future
  build. The container key is version-fragile — Audiotec Fischer could change it in a future release
  without notice. Always check that a decode actually produces plausible
  `<ATF ...>` XML before trusting it on a PC-Tool version you haven't tried.
- The only file-producing helper/CLI is source-bound: it compares the complete
  crossover state at each original channel/slot and exclusively creates a new
  output. Raw unchecked container encoders are internal only.
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
- **Per-field confidence varies** — every reader and supported setter in
  `alpine_jssh.py` carries the same `CONFIRMED` / `assumed, not yet isolated`
  marker the source documented, field by field. HPF/LPF frequency, type, and
  slope remain readable for inspection but are unconditionally read-only;
  delay and PEQ retain their verified write paths.
- Alpine output is source-bound too: the helper/CLI compares all crossover
  bytes at their original channel and exclusively creates a distinct output;
  there is no public raw encoder bypass.
- **Not yet independently re-verified from this Python port against a real
  file** — run `alpine_jssh.roundtrip_identical()` against your own real
  `.jssh` before trusting a generated file on real hardware; that's the actual
  safety check, not the bundled synthetic selftest.
- Read [`references/alpine_jssh_format.md`](helix-rew-tuner/references/alpine_jssh_format.md)
  in full before touching a real `.jssh` file — it covers the full field table,
  the Q lookup table, and a noted open discrepancy between the UI-documented
  PEQ gain range and the wider range the byte format itself accepts.

## How it works

The full explanation — what gets measured, what a tune is scored on, tuning from moving-mic captures, EMMA preparation, refining an existing tune and why restraint wins — is in [docs/how-it-works.md](docs/how-it-works.md). The doctrine the agent follows is in [`references/methodology.md`](helix-rew-tuner/references/methodology.md).

## Credits

The excess-phase **boost gate** (`tunelib.excess_phase_fields` /
`boost_gate_verdict`) is a port of the method in
[`ayukhno/autosound-tuning-skill`](https://github.com/ayukhno/autosound-tuning-skill)'s
MIT-licensed `rew_tool/eq_gate.py` — the three-way conjunction (dip depth **and**
phase anomaly **and** filter weight), the sliding-RMS statistic that catches both
lobes of a bipolar excess-group-delay swing, and the graded ALLOW/WARN/BLOCK
verdicts are theirs. Their write-up of *why* a depth-only null guard is a
regression saved re-learning it the expensive way.

The port is not a copy: excess phase is derived cepstrally here rather than read
from REW's native excess-phase trace, the score is normalized in cycles rather
than seconds (measured: normalizing seconds tilts it ~80× across the audio band
on a fixture with no phase anomaly in it at all), and the thresholds were
re-derived on synthetic ground truth for this path. Details and measured
operating characteristics are in `boost_gate_verdict`'s docstring.

Several imaging and junction methods come from
[`DIMOSUS/Resonalyze`](https://github.com/DIMOSUS/Resonalyze) (MIT): the model of
the Audiotec-Fischer channel **Phase** control (one Q=1 all-pass at the channel's
crossover, measured there on a DSP ULTRA S), the junction phase score with its
flip and lobe margins, the 8-cycle direct-sound window for timing decisions, the
cut-only "crossover in the target" skirt correction, the asymmetric EQ objective
tested as `fit_peq(objective='asymmetric')`, and the stereo-staging rules (image
outranks the junction above ~300 Hz, polarity belongs to the driver, rear-fill
timing, time-and-level centre placement). The phantom-image model follows Lee &
Rumsey (2013) and De Sena et al. (2020). The research record, with what was
adopted and what is still open, is in
[`docs/research/2026-10-01-imaging-and-resonalyze.md`](docs/research/2026-10-01-imaging-and-resonalyze.md).

## License

[MIT](LICENSE).

## Evidence-aware measurement judging

`pipeline.py quality-check --spec quality.json --out quality-report.json` compares
fresh repeated captures with one fixed target anchor, reports per-band compression
and noise-qualified harmonic distortion, checks L/R magnitude regressions, and
estimates spectral headroom from a supplied full-chain transfer. Missing evidence
stays unknown; regional losses veto average-score wins. Analyze, propose and refine
also expose tonal judging scorecards. See
[measurement judging](helix-rew-tuner/references/measurement_judging.md) for the
manifest, capture protocol, decision margins and limitations.

## Changes

What each version changed is in [CHANGELOG.md](CHANGELOG.md).
