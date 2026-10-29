# Tuning methodology — how to decide what to fix

This is the judgment layer. The scripts give you numbers; this tells you what they
mean and which action type each problem calls for. The overarching bias: **classify
before correcting, and prefer doing less.**

## Contents

- [Audit the source before correcting the system](#audit-the-source-before-correcting-the-system)
- [Measurement method selection — sweep vs Moving Mic (MMM)](#measurement-method-selection-sweep-vs-moving-mic-mmm)
- [Sweep capture setup](#sweep-capture-setup-before-you-have-data-to-analyze)
- [Beyond magnitude — decay and distortion](#beyond-magnitude-the-decay-time-domain-and-distortion-axes)
- [Deviation analysis](#deviation-analysis)
- [Analysis traps](#analysis-traps-conclusions-that-are-confidently-wrong-not-just-imprecise)
  - [Traps caught on an Alpine session](#traps-caught-on-an-alpine-pxe-x121-12ev-session-2026-08-05)
- [When the answer is physical, not electrical](#when-the-answer-is-physical-not-electrical)
- [Voicing](#voicing-the-most-audible-decision-and-its-about-the-target-not-the-filters)
- [Classify the problem](#classify-the-problem-the-core-skill)
  - [The interference audit](#the-interference-audit-magnitude-only-very-useful)
  - [Two checks before trusting a proposed EQ band](#two-checks-to-run-before-trusting-any-proposed-eq-band)
  - [Minimum-phase / EQ-ability](#minimum-phase-eq-ability)
  - [The boost gate](#the-boost-gate-the-same-doctrine-scored-and-asked-only-of-boosts)
  - [Single-position phase reliability](#quantify-single-position-phase-reliability-before-trusting-it)
  - [Multi-position variance](#multi-position-variance-eq-whats-common-ignore-what-moves)
- [Tune order](#tune-order-driver-local-eq-then-alignment-then-system-tone)
- [The crossover action-ladder](#the-crossover-action-ladder-cheapest-safest-first)
  - [A channel hands over twice](#a-channel-hands-over-twice)
  - [Reading a junction](#reading-a-junction-phase-score-sum-loss-and-which-window)
  - [Cut a shallow skirt onto the crossover](#cut-a-shallow-acoustic-skirt-down-onto-the-crossover-never-boost-one)
- [Shelf cookbook](#shelf-cookbook-broad-tonal-balance-only)
- [All-pass cookbook](#all-pass-cookbook-phase-only-use-sparingly)
- [Two windows: image from the direct sound, tone from the whole field](#two-windows-image-from-the-direct-sound-tone-from-the-whole-field)
- [Image position is frequency-dependent](#image-position-is-frequency-dependent-and-one-delay-cannot-fix-it)
- [Reflections: find the cause first](#reflections-find-the-cause-before-reaching-for-a-filter)
- [Imaging](#imaging)
  - [Placing the phantom centre](#placing-the-phantom-centre-level-or-time-and-level)
  - [The image outranks the crossover above ~300 Hz](#the-image-outranks-the-crossover-above-300-hz)
  - [Polarity belongs to the driver](#polarity-belongs-to-the-driver)
- [Restraint](#restraint-the-thing-that-beats-aggressive-auto-eq)
- [Verification and honesty](#verification-honesty)
- [REW IR-delay wrong-cycle trap](#rews-ir-delay-estimator-can-lock-onto-the-wrong-cycle-on-a-band-limited-driver)
- [Recovering L/R responses without solo captures](#recovering-per-channel-lr-responses-from-a-common-source-pair-without-solo-captures)
- [When `polarity_delay_search` finds no gain, run `delay_sweep`](#when-polarity_delay_search-says-nothing-to-gain-run-delay_sweep-and-how-this-was-actually-found)
- [Bracket every A/B write and use an untouched anchor](#bracket-every-ab-write-abba-and-anchor-on-a-band-the-write-structurally-cannot-touch)
- [Why a sum scorecard is blind to L/R imbalance](#a-whole-system-sum-scorecard-is-nearly-blind-to-a-channel-pair-lr-imbalance-the-math)
- [Extracting distortion/coherence from a REW `.mdat`](#extracting-distortioncoherence-from-a-rew-mdat-when-only-text-exports-were-expected)
- [Electrical-vs-measured decomposition](#electrical-vs-measured-decomposition-must-be-tune-matched-and-may-not-be-recoverable-at-all)
- [Width/Q from a plot](#widthq-from-a-plot-pick-one-definition-and-dont-switch-mid-analysis)
- [Clear the untouched-channel drift floor](#a-filters-benefit-must-clear-the-untouched-channel-drift-floor-not-just-be-positive)
- [Nearfield-vs-seat cancellation test](#nearfield-vs-seat-shape-comparison-as-a-cheap-cancellation-test)
- [Common-mode is a first-class objective](#common-mode-system-sum-vs-target-is-a-first-class-objective-not-a-fallback)
- [Fixed mic vs MMM](#fixed-mic-vs-mmm-is-a-second-orthogonal-authority-question-what-to-fix-vs-did-it-land)
- [Use the identical prediction and measurement operator](#prediction-and-measurement-must-go-through-the-identical-operator)
- [Model-discrimination gate](#model-discrimination-gate-a-smaller-residual-is-not-a-finding-by-itself)
- [Nearfield claim ceiling](#nearfield-has-a-claim-ceiling-source-local-not-exact-physical-cause)
- [Deep/narrow notch boost guardrail](#deepnarrow-notch-boost-guardrail-stable-does-not-mean-boostable)
- [Seat validation outranks nearfield aesthetics](#nearfield-aesthetics-do-not-override-a-seat-validated-filter)
- [Retraction discipline](#retraction-discipline-a-disproven-claim-invalidates-what-was-built-on-it)
- [Rear-fill / ambience measurement discipline](#rear-fill-ambience-channels-need-their-own-measurement-discipline)
- [Preparing for EMMA judging](#preparing-for-emma-sound-quality-judging)
- [MMM-first tuning](#mmm-first-tuning-the-short-path-for-tone-bass-level-and-lr-balance)
- [Single-run MMM intelligence](#single-run-mmm-intelligence-what-one-capture-set-can-still-tell-you)
  - [Capture audit](#capture-audit-read-what-every-capture-already-says)
  - [The moving-mic noise floor](#the-moving-mic-noise-floor)
  - [Summation coherence](#summation-coherence-from-the-cancel-check-triple)
  - [Four-capture MMM alignment](#four-capture-mmm-alignment)
  - [Bass stability from the peak trace](#bass-stability-from-the-peak-trace)
  - [What the DSP actually applied](#what-the-dsp-actually-applied-raw-xo-eq)
  - [Voicing for the listening level and the road](#voicing-for-the-listening-level-and-the-road)
  - [Learning the listener's voicing](#learning-the-listeners-voicing-from-blind-abs)
  - [Frame-level MMM](#frame-level-mmm-one-run-that-measures-its-own-repeatability)
  - [The skill's own test signals](#the-skills-own-test-signals-experimental)
- [Finishing touches after the curve](#finishing-touches-after-the-curve)
- [Refine the tune you have](#refine-the-tune-you-have-before-adding-to-it)
- [Matched-loudness blind A/B](#judge-by-ear-only-at-matched-loudness-blind)
- [Crossover what-ifs](#crossover-what-ifs-modelled-never-written)
- [Bass is a level decision first](#bass-is-a-level-decision-before-it-is-an-eq-decision)
- [Stopping is a valid outcome](#stopping-is-a-valid-and-often-correct-outcome)

## Audit the source before correcting the system

Every other section here assumes the signal arriving at the DSP is a clean,
level-independent copy of the recording. If it isn't — if the head unit applies
a loudness contour, dynamic bass, or compression — then a tune corrected at one
volume is **wrong at every other volume**, and nothing else in this skill can
see it, because everything else measures at a single level.

Capture the same sweep at three or more source volume settings and run
`pipeline.py source-audit --at ref.txt=0 down6.txt=-6 down12.txt=-12`. Each
trace is aligned to its own broadband level, so a pure volume change cancels
exactly and only a change of **shape** survives. Verdicts:

- **`clean`** — shape and level both track the control. Proceed normally.
- **`level_dependent_shape`** — the response changes shape with volume. Decide
  which volume the tune is *for* and say so, because it cannot be right at all
  of them.
- **`compression`** — measured level lags commanded level. Something in the
  chain is limiting.

**The confound, which matters more than the verdict.** An acoustic capture
cannot separate source processing from driver compression. A loudness contour
*adds* bass at low volume; a midbass running out of excursion *removes* bass at
high volume — relative to each other those are the same measurement. The
discriminator is where you capture, not what you compute: take the sweep
electrically at the DSP input and the drivers leave the path. The audit refuses
to name the source as the cause unless you pass `--electrical` to record that
you did.

Also check `bandwidth` in the report. A source already 6 dB down at 60 Hz sets
a ceiling no output EQ can lift, and boosting into it just burns headroom
against a wall.

## Measurement method selection — sweep vs Moving Mic (MMM)

**Not "one is better" — they answer different questions, and a full tune needs
both.** Established from a real project session (2026-07-14) that hit this
distinction the hard way, and independently reconfirmed the same day in a second
live session on the same tune (same conclusion, same ~8dB-cut-read-as-flat
failure signature) — see "Analysis traps" (below) for that session's other
findings. Sourced against the actual tuning-hardware vendors' own guidance, not
just general acoustics theory:
- miniDSP, "Microphone Techniques for Measurements in Car Cabins" and
  "Measurement Approaches in Car Cabins" (car-audio near-field guidance).
- Audiotec Fischer's own DSP Setup Guide — PC-Tool's built-in TuneEQ /
  TuneToTarget algorithms use a moving-mic-at-listening-position technique
  internally, not a fixed single point.

**Fixed-position sweep (log sine, ideally with an acoustic timing
reference)** is the only valid tool for anything phase-domain — delay,
polarity, crossover summation/interference audits, all-pass design (this
matches everything already established elsewhere in this file). Strong noise
rejection via deconvolution, fine spectral resolution. Its weakness: in a
car's near field, a single fixed mic point can show position-specific comb-
filtering/standing-wave structure that doesn't represent what's heard across
the volume a real head occupies. 2-3 fixed positions (centre/left-ear/
right-ear) mitigate this — confirms a feature is position-*stable*, which is
exactly what `spatial_consistency` (§Multi-position variance) is built to check — but a
handful of discrete points still isn't true spatial averaging.

**Moving Mic Method (MMM)** — mic physically swept around the head at the
listening position during capture, analyzed via RTA — **is the preferred
primary source for frequency-response/EQ decisions when both are
available**, including voicing-layer work (`voice_target`/`measure_tilt`).
It's the continuous, mechanically-averaged version of the same idea
`spatial_consistency` implements with discrete positions — both exist to stop
a single fixed point from being mistaken for what's actually heard. Two real
weaknesses to guard against, not reasons to avoid it:
1. **Magnitude only, no phase** — same rule as any other magnitude-only
   capture: never use it for delay/crossover/polarity/APF decisions.
2. **No noise rejection.** A sweep's deconvolution rejects steady background
   noise; plain RTA/MMM sums everything at each frequency, including it. A
   real dip in a band where cabin noise (engine/HVAC/road) has energy can
   read as falsely filled — **confirmed as a real, non-hypothetical failure
   on a live project**: a genuine ~8-13 dB electrical PEQ cut read as a flat,
   unremarkable response on an engine-running MMM capture, and was only
   caught because a later engine-off sweep of the same tune showed the true
   depth. **Capture MMM intended for EQ decisions with the engine off** (and
   as quiet a cabin as practical) — this is a capture-time discipline, not
   something fixable after the fact from the trace alone (the same reason
   `gating_warning` exists as a capture-time check rather than a post-hoc
   correction).

**Playback level must be controlled, not just anchored.** `target_anchor_offset`
and `calibrate_solo_levels` both assume shape is level-independent — measure
at any level, then anchor the overall level and compare shape. That
assumption breaks if the OS/driver audio path has a loudness-contour
enhancement active (e.g. Windows "Loudness Equalization") — those reshape
frequency response as a function of volume, so two captures at different
levels aren't simply level-shifted versions of each other anymore. Confirm
no such enhancement is active before trusting a shape comparison across
sessions taken at different volumes, and where practical, measure at the
level the user actually listens at — equal-loudness (Fletcher-Munson)
perception is itself level-dependent, so tonal balance judged at one SPL
doesn't necessarily hold at another.

**Default protocol:** sweeps (with acoustic timing reference) for all
delay/polarity/crossover/APF work — or, MMM-only, by comparing captures of
each candidate setting with `mmm-compare` (§MMM-first tuning). MMM — engine off, at or near the user's
real listening volume, confirmed no loudness-contour enhancement active — as
the primary dataset for PEQ/tonal/voicing decisions. Where both exist for
the same tune, a large disagreement between them in a given band is itself
diagnostic: check for ambient masking in the MMM capture and whether the
sweep-only feature is position-stable (2-3 positions) or a likely near-field
artifact, before trusting either one in isolation.

**A fixed-point coherent-sum prediction must never override an MMM magnitude
result — this is a hard rule, not a preference.** If a fixed-position model
predicts a tonal gain from a delay/APF change but the MMM A/B shows no
improvement (or a regression), **reject the tonal claim**, no matter how good
the fixed-point number looks. `tunelib.mmm_overrides_fixed_point(
fixed_point_predicted_db, mmm_measured_db)` encodes this so it isn't a
judgment call each time. The phase-domain finding can still be diagnostically
valid (e.g. for timing) — only the *tonal* claim is rejected. This specific
failure is worth watching for: a delay whose predicted improvement sits close
to a cycle-slip / period-ambiguity interval can look clearly beneficial at one
coherent point and simply not survive spatial averaging.

## Sweep capture setup (before you have data to analyze)

Bad capture produces confidently-wrong analysis no amount of downstream care can
fix. A few things to get right before trusting a measurement:

- **Frequency range per driver**: sweep roughly one octave below the driver's low
  crossover corner to one–two octaves above its high corner — not REW's full
  10 Hz–24 kHz default. A full-range sweep on a bandpassed midrange wastes
  resolution outside its passband and can make out-of-band noise look like signal.
- **Test level, not DSP gain, is the lever for clipping.** If a driver clips or
  audibly resonates during a sweep but is clean on pink noise or music, that's
  expected, not a fault — a sustained sweep tone holds energy at each frequency far
  longer than any transient content ever does, exciting mechanical resonances music
  never triggers. **Fix it by lowering REW's sweep level (dBFS)**, never by
  touching live DSP gain "just for the measurement" — a gain change there is a real
  tune edit, not a measurement setting, and it's easy to forget to revert.
- **Mismatched levels across solos are expected and fine — but must be corrected
  before joint magnitude analysis.** Solos are often necessarily captured at
  different test levels (e.g. a sub measured much quieter than the mids under an
  aggressive bass shelf, to keep the sweep clean). Phase is level-independent, so
  this never hurts polarity/delay/all-pass work. But `interference_audit`,
  `prediction_confidence`, and `tune_scorecard` are magnitude-based and will
  "detect" a fake gap or cancellation that's actually just a level mismatch between
  captures. Run `tunelib.calibrate_solo_levels` first to fit the real relative
  level, and treat its post-calibration residual — not the raw pre-fit deviation —
  as the actual confidence number.
- **Trust REW's own reported timing method before trusting the data.** REW's
  export header states which arrival-detection method was used for that
  measurement — "IR start time" (robust) vs. "estimated IR delay" (fragile). Treat
  the latter, and anything carrying a correlation warning, as **unusable for
  delay/time-alignment decisions** until it's re-measured cleanly.
- **If REW's "IR windows" (time-domain gating) is used to cut out room
  reflections, that choice has a hard low-frequency cost — know it before
  trusting the bass region.** Standard quasi-anechoic practice (from
  HolmImpulse's own documented gating limits, verified against their real
  example): a gate needs to contain **at least one full wavelength** of a
  frequency before that frequency's response means anything — cut the window
  short to exclude an early reflection and everything below
  `tunelib.gating_frequency_limit(gate_ms)` is not real data, just a windowing
  artifact. A 1 m reflection path difference (a ~2.9 ms gate) already puts the
  floor around 340 Hz — tight gating for reflection control and trustworthy
  deep bass are directly in tension. If a gated measurement's bass region
  looks reported below that floor, don't use it — pair the warning
  (`tunelib.gating_warning(gate_ms)` gives the ready-to-say sentence) with the
  actual remedy: an ungated capture, or a registered `complex_vector_average`
  across several mic positions (see below) for that range instead.

## Beyond magnitude — the decay (time-domain) and distortion axes

Magnitude-vs-frequency (sweep or RTA) answers "how loud is each frequency."
Two other axes answer questions it structurally cannot, and both are cheap to
capture once you already have sweeps. Reach for them when something has bugged
a listener that EQ passes never fully resolved — that's the tell it isn't a
tonal problem at all.

**Decay / CSD / waterfall / spectrogram — how long each frequency rings.** A
resonance that *rings* (a panel, a trim assembly, a loose rigid part on a
compliant mount, an underdamped driver or enclosure mode) shows as an extended
decay tail while the rest of the spectrum has already died away. Magnitude
alone cannot distinguish "this frequency is a bit hot" from "this frequency is
ringing," and the distinction changes the correct action: **EQ reduces a ring's
onset level but does not shorten its decay**, so a ringing resonance stays
smeared no matter how much you cut it. The fix for a ring is mechanical
(damping, re-seating, tightening the offending part), with EQ only reducing how
hard the system drives it.

**You do not need a dedicated capture for this if you already have a
phase-valid sweep text export.** REW text exports on a *linear* frequency grid
(check the header's `Frequency Step` — a sweep export is linear, e.g. ~0.37 Hz,
while an RTA export is log/ppo) carry magnitude and phase on FFT-native bin
spacing, so the impulse response can be reconstructed directly:
`H(f) = 10^(SPL/20) * exp(j*phase)` placed at bin `round(f/df)` of an
`rfft`-length array, then `irfft`. From there, a constant-Q gaussian bandpass in
the frequency domain plus an envelope gives per-frequency decay time.
`scripts/decay.py` implements this — `t20`/`csd`/`compare` subcommands work
directly from an IR `.wav` (e.g. REW's "Export IR"). Compare
the SAME frequency between the two sides (L vs R) rather than reading absolute
decay numbers — that controls for cabin modes and for the measurement chain,
and turns "is this ringing?" into a differential question with a clean control.
Note any all-pass filters loaded at capture time: an APF adds group delay and
can extend apparent decay near its centre frequency, so check whether a
confound biases the comparison toward or against the conclusion.

**The resonant-absorber signature — and why "where it rings" and "where you
hear it" are different frequencies.** A rigid mass on a compliant mount
attached to a panel behaves as a tuned mass absorber, and produces a
*three-part* signature that is easy to misread from magnitude alone:
- **At its resonance:** a magnitude **notch** (energy absorbed out of the
  panel's radiation) **and** a long **decay tail** (that stored energy released
  slowly). This is where the mechanical system actually resonates.
- **Just above resonance:** a magnitude **peak** with normal decay — the
  anti-resonance, where the panel radiates *loudest*.

A listener reports the frequency where it is **loudest** (the peak); decay
analysis finds where it is **stored** (the notch). Both observations are
correct and they sit tens of Hz apart. This matters twice: (1) EQ aimed at the
radiating peak does not reduce energy going *into* the resonator, and a
"compensating boost" placed at the notch can end up feeding the peak; (2) for
the physical hunt, exciting the part with a tone at the **resonance/notch**
frequency — not the peak — makes it vibrate hardest and easiest to localise by
touch. Give the listener that frequency, not the one they reported.

**Distortion (THD) — nonlinearity, a separate axis from level.** Useful for
three specific confirmations rather than as a routine sweep: (1) a THD rise at
or just below a high-pass corner is live confirmation of excursion stress,
where `hpf_excursion_risk` only gives a modelled estimate from a stated Fs;
(2) a THD rise toward the TOP of a driver's assigned band is direct evidence of
breakup rather than benign rolloff — exactly the evidence needed before
concluding "this driver is at its range limit, stop EQ'ing it" or before
weighing a crossover change; (3) a THD spike unrelated to any crossover corner
usually means amplifier clipping or a stressed driver at that frequency — worth
catching before EQ'ing around a "dip" that is really distortion-driven.

**Nearfield capture separates driver/enclosure problems from path/cabin
problems.** A mic placed very close to a driver is dominated by that driver's
direct output, largely excluding cabin reflections and inter-driver summation.
A feature present in BOTH the nearfield and the listening-position trace is in
the driver or its enclosure/door; a feature present only at the listening
position is a path/summation/cabin effect. This can reclassify a deviation
previously written off as "physical, not correctable" — worth doing before
permanently accepting a large dip as untreatable.

**Reverberant-room metrics (RT60, decay time, clarity/C50, EDT) do not transfer
to a car cabin.** They are defined for spaces large and reverberant enough to
develop a diffuse field; a car interior is far too small and too heavily damped
by trim, glass and upholstery for these to be well-conditioned or meaningful.
Don't force them onto the space — use the per-frequency L-vs-R decay comparison
above instead, which asks a narrower and answerable question.

## Deviation analysis

1. Interpolate the target onto the measurement grid, then **anchor the level** —
   match overall loudness by a robust median offset over a broad mid band (e.g.
   300–3000 Hz), not by aligning one point. `tunelib.target_anchor_offset` does a
   confidence-weighted version.
2. Smooth **perceptually**, not with a fixed fraction. `tunelib.erb_smooth` widens
   the window at low frequencies (where the ear integrates) and narrows it up high.
   This stops you "correcting" LF wiggles the ear never hears as separate.
3. Below the cabin's modal transition (~200–400 Hz), narrow peaks can be real and
   EQ-able. Above it, only broad trends are reliable — reflections dominate the fine
   structure and move with the mic.

**The anchoring trap — the most dangerous error in step 1, VERIFIED live
(2026-07-14).** When comparing several candidate tunes' before/after, never
re-anchor each version to its own median independently. If an edit changes energy
inside the anchor band itself (e.g. a low-mid cut), the anchor shifts, and the
*relative* deviation numbers move for reasons that have nothing to do with the
actual filter change — manufacturing a false "it went flat" result. A real case: a
re-anchored comparison showed a 600 Hz bump "corrected to +0.8 dB" when the true
change was only −1.1 dB (it stayed hot at +3.6 dB) — the anchor itself had silently
shifted between versions. **Hold ONE fixed anchor (the baseline's) across every
version being compared**, and always sanity-check against the raw, anchor-free
delta `after(f) − before(f)` at the frequencies that matter — that number is
anchor-independent and cannot be fooled this way. If a claimed deviation change is
bigger than the raw component delta can produce, the anchoring is wrong, not the
physics.

**The same trap re-appears when grading a re-measure, not just when comparing
candidates.** Scoring a before/after pair with a median anchor taken from a band
that a write actually touched will misattribute the anchor's own shift to every
OTHER frequency — including ones nothing was done to. A real case (2026-07-29):
grading a re-measure showed treble reading "worse" after a tune change that never
touched a single tweeter band — impossible on its face. Cause: the write cut two
bands sitting inside the 300–1000 Hz anchor window, so the anchor moved and every
untouched frequency inherited that shift. **When scoring a re-measure, align
levels using frequencies the write did NOT touch** (here, a clean 2–10 kHz region),
not the same fixed mid-band used for target-deviation anchoring — those are two
different jobs and can need two different anchor choices.

**For a causal A/B (did THIS specific change do what I think), use
`tunelib.causal_ab_delta(freqs, before, after)` instead of reconstructing this
by hand.** It's deliberately just `after − before`, no target and no anchor at
all — a causal A/B on the same measurement chain doesn't need one.
Independently anchoring "before" and "after" to a target before differencing
them is the exact anti-pattern above in a different outfit: it can absorb a
real common-mode change into each curve's own offset and hide it completely
(a real −1.5 dB common-mode cut compared this way reads as **0.00 dB** of
change — verified, see TEST39). `target_anchor_offset` still answers a
different, legitimate question (how close is this curve to target); don't use
it to answer "what changed."

**Before trusting a feature's magnitude enough to size a filter from it, check
whether the anchor choice itself is doing the work.** A real case: a 100 Hz
excess read as +2.5 dB using one defensible 300–1000 Hz anchor band — which
happened to contain both a cancellation null and a second, unrelated excess —
and +1.3 to +1.6 dB using seven other defensible anchors. The filter changed
from `100/Q2/−2` (which *worsened* whole-curve tracking) to `100/Q4/−1.5`
(which improved it) depending on which was trusted.
`tunelib.anchor_sensitivity_report(freqs, measured_db, target_db,
candidate_band)` runs several anchor bands (excluding the candidate feature
itself, to avoid the circularity of anchoring against the thing being judged)
and reports the range. `anchor_sensitive: True` means the conclusion depends
on an arbitrary choice — don't size a filter from it yet; find out why the
anchors disagree (usually a null or a second feature sitting inside one of
them) before trusting any single number.

## Analysis traps — conclusions that are confidently wrong, not just imprecise

Each of these produced a plausible, structured-looking answer that was wrong:
nothing about the output looked broken, only the number underneath it. The
sessions they came from are in the repository's `docs/case-notes.md`.

**A single-channel cut changes the L+R SUM by only about half its own value.**
−2 dB on one channel moves the power sum by about −1 dB. Never predict a
combined change equal to a one-sided gain. A one-sided excess cannot be
flattened in the sum without over-cutting that side: correct the imaging and
accept a partly reduced sum bump.

**Fix the SUM where the sum is wrong, not where one channel's solo dips.** The
other channel may fill the dip; boosting it builds a sum shoulder (+2 dB seen
at 1150-1300 Hz). Decide tone from the summed response; use solos for imaging
and imbalance only.

**Near a crossover the sum can wobble between sessions with no EQ cause —
coherence, not level.** A few millimetres of mic position is a real phase shift
there; the sum swung 3 dB at an untouched 1 kHz while every solo stayed put.
Act on a crossover-adjacent sum deviation only when it persists across
independent sessions.

**For L/R balance compare ABSOLUTE inter-channel level, never each side
normalized to its own reference.** Self-normalising can invert the difference.
`lr_match_report` uses raw FR−FL; use it rather than rebuilding the
comparison.

**Sub level couples to the low-mid correction.** After a low-mid cut the sub
needs less level. Model sub and mids together in the proposed state; the last
half dB is a by-ear voicing call.

**When two models disagree about deviation from target, arbitrate with an
anchor-independent SHAPE test.** Reference every value to a nearby in-band
frequency, `delta(f) − delta(f_ref)`, for the required change and for each
candidate's delivered change: every model must agree on those numbers.

**A tune comparison must score the FULL channel state.** Include output level
(`<Vol>`), not the PEQ set alone, and keep optimizer guardrail penalties apart
from acoustic error: guardrails from different systems are not comparable.

**Establish that a decoded field is LIVE before reasoning about its value.** A
file stores parameters the running configuration ignores (crossover `Q` is
leftover unless the characteristic is Self-define; the alignment lives in the
`<OC>` `HPi`/`LPi` index). Check the field against the software's own display;
treat an unverified field as unknown. A second-opinion model inherits your
framing and will refine a defect that does not exist.

**A measured null is not automatically the resonance the user reports.**
Confirm its frequency with independent physical evidence (does touching the
part move it? does road input alone excite it?) and, once that exists, trust it
over the measurement-only guess. A boost compensating a mislocated null once
fed the real resonance 35 Hz away.

**To synthesize "this defect fixed", remove only the positive excess over a
broad trend.** Smooth the same trace by about 1/2 octave, take raw minus trend,
and remove the positive part in the defect's band — not point-to-point
interpolation across it, which inherits nearby features. Bias any decision
built on a synthetic, unmeasured state towards removal or neutral, not new
boosts.

**Measure the capture method's own noise floor, then require every band to
clear it** (about 2-3 times). Two sessions with a known EQ delta give it: the
residual after subtracting the modelled delta and a broadband offset is the
repeatability (`capture_repeatability` and `repeatability.py` do this). MMM
floors worsen with frequency; a tilted residual means drift between
sessions, not noise.

**Don't let a few fixed positions overrule a moving-mic average for tonal
decisions** above a few hundred Hz: positions a head-width apart sample the
same comb, so their mean is not a spatial average. Prefer MMM and its own
measured repeatability; keep discrete positions for phase and crossover
stability.

**A score gap smaller than measurement repeatability is a tie, not a ranking.**
Say so, rather than presenting three-decimal scores as decisive.

**A low-SD near-zero mean is a strong, repeatable finding**, not an unreliable
one. Repeatability and effect size are different questions:
`tunelib.historical_repeatability(values)` returns `stable_near_zero`,
`stable_nonzero` or `unreliable` (the last driven only by SD).

**A re-exported or copied file can double-count as a second session.** Run
`tunelib.detect_duplicate_traces(traces)` before any cross-session statistic.

### Traps caught on an Alpine PXE-X121-12EV session (2026-08-05)

Root cause shared by all of these: **a summary statistic hid the shape of the
thing being summarised.**

**Band-averaging a deviation across a modal null reads as a LEVEL DEFICIT.**
A sub averaged −3.3 and −5.1 dB over two bands while it was +9.2 dB at 32 Hz
and +5.6 dB at 53 Hz between deep nulls: peaky, not short. Look point by point
inside any band before concluding "level": a deviation alternating sign by
more than a few dB is modal ripple, and its average means nothing. A level
error moves a whole region one way.

**Judge inherited EQ band by band against the RAW response**, never wholesale:
junk and real corrections sit in one list (3 of 11 sub bands were doing real
work). Prefer a capture of the channel with and without its EQ (`xo-check
--eq`) to any model of it.

**A CONSTANT offset across the band in `interference_audit` is a capture-level
mismatch, not interference.** Real summation combs; a pair measuring quieter
than either solo is impossible. Check the spread of `interference_db` first.

**Separate MMM captures are not reliably level-comparable** unless made at one
volume in one sitting (capture-audit checks a triple's playback level).

**Fractional-octave summaries misplace narrow features.** A 1/3-octave view put
a null at 1600 Hz (it was at 1908 Hz) and invented a 12.7 kHz dip. Notice with
fractional-octave views; locate with the full-resolution trace before placing a
mask or a filter.

**`fit_peq` returning zero bands on an obviously wrong channel means the mask
or fit band is wrong** (an unmasked deep null, or a crossover skirt in the
band). Fix the region and re-fit; never lower `improve_pct` or `min_gain` to
force an answer.

**Never include a crossover skirt in a fit band.** Fitting 22-80 Hz on a
channel low-passed at 60 Hz stacked four +4 dB bands at 76 Hz to undo the
low-pass. Several same-frequency bands in one output are the signature.

## When the answer is physical, not electrical

Some deviations are the install talking, not the tune. EQ can only change what
the driver is *asked* to produce; it cannot change what happens to that output
afterwards. Recognising these early stops a tuner burning filters, headroom and
sessions on something a mechanical fix resolves properly. Four failure modes
recur in door-mounted car installs, and they call for different remedies that
are easy to conflate.

**Damping, sealing, absorption and decoupling are four DIFFERENT jobs.** This is
the single most useful distinction, because "I've done sound deadening" usually
means only the first one:
- **Damping** (constrained-layer damping tiles on panels) — stops a panel
  *resonating*. Fixes ringing/buzzing panels. Does nothing for cancellation.
- **Sealing** (rigid block-off plates over the inner door skin's access holes)
  — stops the driver's rear output leaking round to the front. This is the fix
  for cancellation, and damping tiles alone do NOT achieve it: a partial cover
  leaks, and a leak defeats the seal.
- **Absorption** (open-cell/melamine foam, fibre mat behind the driver) —
  absorbs the rear wave inside the cavity so less of it returns.
- **Decoupling / gasketing** (closed-cell foam strips between driver or mounting
  ring and the door card; foam or rope where trim layers overlap) — seals the
  driver's front output to the card so it can't spill into the cavity, and stops
  trim pieces buzzing against each other.

**Broad midbass cancellation, typically somewhere in the ~300-800 Hz region, is
the classic signature of an acoustic short circuit** — the door acting as an
open baffle rather than an enclosure, because the inner skin's large service
holes let front and rear waves meet. Distinguishing features: it's broad rather
than a narrow notch, it appears in the driver's own solo (not only in a summed
trace), and it tends to appear at a similar frequency on BOTH doors because the
geometry is near-symmetric. Do not EQ-boost it — the energy is being cancelled,
not merely attenuated, so a boost costs headroom and excursion for very little
recovered output (`reaches_target_after_boost` will usually flag exactly this).
The remedy is sealing the inner skin and gasketing the driver to the door card.

**Before spending sealing/damping effort on a cancellation, confirm it
originates at the driver — measure nearfield.** A broad null at the seat can be
the acoustic short circuit above (real, in the door, sealing fixes it), or a
cabin-path effect entirely downstream of the driver (direct sound cancelling
against a reflection somewhere between the door and the seat) — and no door
treatment touches the second cause. The two are easy to conflate because both
produce a broad low-mid null at the seat. The test: measure the same driver
nearfield (mic 2-5 cm from the cone, EQ stripped from both traces) and compare
null depth to the at-seat depth. A real case (2026-07-31): a 9-11 dB null at
380-540 Hz at the seat measured only 2.6-3.3 dB nearfield on both channels —
the drivers were essentially clean, so the extra ~8 dB was accumulating
entirely in the cabin path. That closed off a sealing project that would not
have fixed it, and moved the deviation from "work queue" to "not correctable
from here, leave it" with a single pair of measurements instead of a guess.

**A single specular reflection produces a COMB, and that's testable.** If a
suspected reflection is the cause, the nulls fall at odd multiples of the first
(f, 3f, 5f...), because cancellation needs a path difference of an odd number of
half-wavelengths. Detrend the driver's raw response (remove the broad tilt with
a low-order polynomial fit in log-frequency), locate the nulls, and check the
ratios. If they ARE odd multiples, the implied extra path length is
`c / (2*f1)` — which physically identifies the reflector and tells you what to
treat. If they are NOT (real case: ratios came out 1.72, 2.30, 4.30 — no clean
odd pattern), a single reflection is ruled out and a broadband mechanism such as
the acoustic short circuit above is more likely. This is a cheap test that turns
"maybe it's a reflection" into a decided question.

**A resonant absorber (a rigid part on a compliant mount) is not the same as a
rattling panel, and the decay analysis distinguishes them** — see "Beyond
magnitude" above for the three-part notch/ring/peak signature and why the
frequency a listener reports differs from the frequency to excite when hunting
it by hand.

**Say plainly when a deviation is an install problem.** A tuner's job includes
reporting "this one is not correctable from the DSP, here is the physical
cause and the remedy" rather than spending filters to partially mask it. That
report is more valuable than a slightly flatter curve bought with headroom.

## Voicing — the most audible decision, and it's about the target, not the filters

Before correcting *toward* a target, get the target's overall **tilt** right,
because the broad tonal slope is the single most audible property of the whole
tune — more than any individual filter. Matching a curve precisely is not the
same as sounding good: a **studio-flat target reliably sounds bright and thin
in a car**, because near-field reflections and an off-axis seat rob perceived
warmth that a flat anechoic target never accounted for.

- **Measure where you are.** `tunelib.measure_tilt(freqs, system_sum_db)` fits
  the broadband dB/octave slope (heavily smoothed, audibility-weighted) and
  reads it against the typical good-in-car range — roughly **−0.8 to −1.0
  dB/oct** of downward tilt (a rule-of-thumb consensus, the ResoNix/Harman
  in-car target family sits here; not a hard law). Run it on the supplied
  target too — if the user handed you a flat/studio curve, that's worth saying
  out loud before you spend filters chasing it.
- **Voice by ear-language, not by curve-drawing.** `tunelib.voice_target`
  exposes four knobs that map to how people actually describe sound: **tilt**
  (warmer ↔ brighter), **bass shelf** (more ↔ less weight), **presence** (more
  forward ↔ laid back, ~3 kHz), **air** (more air ↔ tame the top). It returns a
  modified target; everything downstream is unchanged.
- **Keep voicing and correction conceptually separate.** Voicing shapes the
  *goal* (a taste choice — offer defaults, let the user pick). Correction is
  measurement-driven work *toward* that goal. Say which is which in the report
  so the user knows what's their preference vs. what the room forced.
- Voicing is broad by construction (tilt + gentle shelves + one wide presence
  bell) — it never introduces narrow, seat-specific, or high-Q moves, so it
  carries none of the robustness risk that aggressive corrective EQ does. This
  is the rare place where a boost (e.g. a bass-shelf lift) is both very audible
  and very safe.

## Classify the problem (the core skill)

For each region, decide the **type** before proposing a fix:

- **Driver-local tonal** — a peak/dip present in one driver's *solo* trace,
  independent of summation. → PEQ (usually a cut), or a shelf if it's a broad tilt.
- **L/R level imbalance** — one side broadly quieter. → gain, not EQ.
- **Phase cancellation** — solos are individually healthy, but their *sum* dips
  (below the incoherent power-sum). → polarity → delay → all-pass ladder. **Never a
  boost.**
- **Modal / reflection / spatial null** — a deep dip that appears in the solos too,
  moves across mic positions, or has wild excess group delay. → do **not** correct;
  boosting it wastes headroom and fixes nothing. Report it as non-correctable.
  If multiple position sweeps are available, `tunelib.spatial_consistency`
  (below) turns "moves across mic positions" from a judgment call into a
  per-frequency mask/conf you can hand straight to `fit_peq`.
- **Measurement invalid** — low prediction confidence, clock-drift artifacts, wrong
  axis. → request a re-measure; don't apply math to bad data.

### The interference audit (magnitude-only, very useful)

`tunelib.interference_audit(freqs, solo_a, solo_b, together)` compares the measured
"together" trace against the incoherent power-sum of the solos. If together sits
**below** the power-sum, the pair is **destructively interfering** — a phase
problem, not an EQ problem. This is how you tell a genuine cancellation from a
driver dip. Requires both solos + the measured pair.

### Two checks to run before trusting any proposed EQ band

**Is the band even audible, or is it cosmetic?** Before trusting a proposed (or
externally-supplied) EQ band, confirm the target driver actually has enough level
at that frequency to matter in the sum. `tunelib.inert_band_check(target_driver_db,
dominant_db)` flags a band as **inert** when the target driver sits ~6 dB or more
below whichever driver dominates the summed response there — a cut or boost on a
buried driver changes that driver's own curve but barely moves the audible result,
because the dominant driver's contribution swamps it.

**"Outside the passband" does NOT mean "contributes nothing" — check the
skirt.** A band centred beyond a channel's own crossover still has skirts that
reach back inside it, and dismissing such bands wholesale is as wrong as
trusting them. Evaluate the combined magnitude response of the out-of-band
bands *at frequencies inside the passband* and read the actual numbers. A real
case (2026-08-05): of seven out-of-band bands on a 400–4000 Hz channel, six
contributed under 0.05 dB anywhere in the passband — genuinely inert — while
the seventh (`4800 Hz Q4.966 −8.0 dB`, just above the 4 kHz corner) reached
**−1.95 dB at 4000 Hz**. Report the ones that do something and the ones that
don't as separate findings; "N bands lie outside the passband" is a lead, not a
conclusion.

**Does the boost actually reach target, or is the gap being papered over?** If a
large proposed boost still leaves the trace far short of the deficit at that
frequency, the boost isn't the fix — the shortfall is phase/destructive
interference eating the signal, and no amount of gain on one driver alone recovers
it (a coherent partner is still cancelling it there). `tunelib.
reaches_target_after_boost(current_db, target_db, proposed_boost_db)` simulates the
boost (capped at the hardware ceiling) and flags `likely_phase_problem` when the
result still falls short with the boost already maxed out. Run this alongside
`interference_audit` before accepting a claimed improvement — a boost that can't
reach target is wasted headroom, not a real fix.

### Minimum-phase / EQ-ability

Flat excess group delay ⇒ minimum-phase region ⇒ EQ works. Sharp excess-GD
excursions ⇒ non-minimum-phase ⇒ EQ won't generalize. `tunelib.excess_gd_mask`
flags regions to leave alone. Narrow high-frequency dips are almost never worth
correcting — they don't survive small mic movement.

### The boost gate — the same doctrine, scored, and asked only of boosts

`excess_gd_mask` answers "is this region minimum-phase" with a yes/no, against
an absolute group-delay threshold, and applies to cuts and boosts alike.
`tunelib.excess_phase_fields` + `boost_gate_verdict` ask a narrower and more
useful question: **would boosting *here*, with *this* filter, be pushing gain
into a cancellation?** Three things have to be true at once before it objects —
a deep local dip, a phase anomaly, and the filter actually delivering gain at
that frequency. Any one alone over-flags: cabin midrange is phase-rough almost
everywhere, and depth alone cannot tell a cancellation from a fillable shape
deficit. Verdicts are `ALLOW` / `WARN` / `BLOCK`; `pipeline.py analyze` reports
one per `boost_needed` deviation region under `boost_gate`.

**Cutting into a null is merely pointless; boosting into one wastes headroom
and cannot work** — that asymmetry is why this is boost-only.

Use it with three limits firmly in mind:

- **ALLOW is not a certificate.** On synthetic ground truth it misses most
  cancellations. It means "no phase objection found", nothing more — the
  interference audit, `reaches_target_after_boost`, `inert_band_check` and the
  headroom budget are what actually carry the decision.
- **WARN is an instruction to cross-check, not a verdict.** Shift the mic ~10 cm
  and re-measure: a real cancellation notch moves or fills, a driver/cabin shape
  deficit stays put.
- **It needs unsmoothed data.** The score is normalized by the measurement's own
  spread, so a 1/3-octave-smoothed export collapses the normalizer and makes
  everything read anomalous. The gate detects this and reports
  `low_confidence` rather than pretending — if you see it, re-export.

It is deliberately **specific rather than sensitive**: it objects rarely, so
that when it does the objection is usually real. A gate that flagged half of all
boosts would just be noise you learned to click through. Measured operating
characteristics, and the reasoning behind the thresholds, are in
`boost_gate_verdict`'s docstring — including why they are *not* the upstream
values this was ported from.

### Quantify single-position phase reliability before trusting it

A single fixed-position sweep can have excellent magnitude and still have garbage
phase above a few hundred Hz — reflections dominate the fine structure of the
phase curve long before they visibly wreck the magnitude curve. Don't guess; check.
Real driver phase is close to a straight line vs. frequency over its own passband
(dominated by acoustic path delay); reflections add wiggle on top of that line.
`tunelib.phase_linearity_residual(freqs, phase_deg, band)` fits that line and
returns the RMS residual in degrees — a concrete reliability score. From real
sessions: **≤~100° = trustworthy** for polarity/delay/APF decisions (seen on clean
midbass data); **~300–450°+ = reflection-dominated garbage** (seen on single-
position tweeter data) — don't use it for timing, no matter how clean the
magnitude trace looks.

**The fix, if reliability is poor: spatial averaging, done correctly.** A sweep
only takes a few seconds — don't move the mic mid-sweep. Instead take several
(3–7) discrete sweeps at slightly different fixed positions spanning head-width,
then average the **complex** spectra with `tunelib.complex_vector_average`, not a
magnitude-only average — **registered**: pass `freqs` (it estimates each
position's arrival against the first) or `delays_s` (e.g. REW's IR start times
on one timing reference). Moving the mic changes the flight time, so the
positions' phases only line up after that delay is removed; an unregistered
mean of one flat driver measured 5 cm apart invents a −9.5 dB dip at 1.67 kHz
and −17 dB at 2.5 kHz. Once registered, vector averaging cancels
position-specific comb-filtering while keeping what the positions share, and
the returned `coherence` shows where they still disagree. For tonal/EQ
decisions average magnitudes instead (`spatial_consistency`, MMM).

**Why this is trustworthy: it's the same discipline pro alignment tools require,
computed a different way because our data source is different.** Rational
Acoustics' Smaart gates every timing/EQ decision on a **coherence** trace —
a per-frequency measure of how much of the response is causally explained by
the reference signal, computed from a genuine dual-channel (reference vs.
measured) capture. That input isn't available here — a REW sweep export is a
single-channel deconvolved measurement, not a dual-channel transfer-function
capture, so there's no coherence trace to read. `phase_linearity_residual` and
`prediction_confidence` exist to serve the exact same purpose (know when NOT
to trust a region) from the data this project actually has access to. The
philosophy transfers even though the math doesn't. **If a measurement chain
ever does supply real per-frequency coherence** (not REW's normal sweep
export, but forward-compatibility is cheap), `measure.load_text_export` reads
an optional 4th column as coherence and returns it — usable directly as the
`conf` weight `fit_peq`/`prediction_confidence` already accept, at which point
you'd have the genuine Smaart-style signal instead of a proxy for it.

### Multi-position variance — "EQ what's common, ignore what moves"

`complex_vector_average` (above) is for CLEANING UP a phase-valid measurement.
`tunelib.spatial_consistency(freqs, position_traces, consistent_db=1.5)` is for
a different, earlier decision: **deciding what's even safe to correct**, and it
only needs plain SPL (dB) per position — no phase capture required, which makes
it far cheaper to gather than what `complex_vector_average` needs. Take 3–7
sweeps at slightly different fixed positions spanning head-width (same capture
discipline as above — don't move the mic mid-sweep), pass the list of SPL
curves in, and it returns a per-frequency `mask`/`conf` pair straight from the
across-position spread: low spread (holds at every position) = a real driver/
room feature, safe to correct; high spread (present at one spot, gone or
shifted a few inches away) = position-specific comb-filtering, the textbook
signature of the "Modal / reflection / spatial null" category above — feed it
straight into `fit_peq(freqs, dev_db, band, mask=sc['mask'], conf=sc['conf'])`
so the optimizer never spends a band on a dip that only exists at one seat
position.

**With 3+ positions, `pipeline.py propose` does this for you and then checks
itself.** The robust fitter (`fit_peq_robust`) works on the level-aligned
positions with that mask, and charges every position for any NEW hole a band
digs below target (`eq_dig_depth`) — masked bins included, because "don't chase
this" is not "free to dig here". Without that charge a peak that wandered a
quarter-octave between seats drew a −12.5 dB Q8 notch; with it, the same data
gets a gentle broad trim, and on synthetic cars scored at eight unseen
positions the gain rose 35–45 % while seats made worse fell about 70 %.
`held_out_band_validation` then refits with each position withheld in turn: a
band that does not come back (stability < 0.8) or does not help the withheld
position is `DO NOT APPLY`, in between is `REVIEW`. A single position cannot be
validated this way — say so rather than implying a check that did not run.

**A Moving Mic Method (MMM) capture is the continuous, mechanically-averaged
version of this same idea** — sweeping the mic around the head during
capture instead of comparing discrete fixed positions afterward. See
"Measurement method selection" for the fuller sweep-vs-MMM
picture, including why MMM is the *preferred* source for tonal/EQ decisions
when available, and the engine-noise-floor caveat that comes with it.

**This is also the honest, data-driven answer to "is this dip safe to boost,"
sharper than a single-position minimum-phase check alone can give.**
`excess_gd_mask` asks whether a dip's *phase behavior* looks minimum-phase at
one position — but a comb-filter null can look locally minimum-phase-ish from
a single vantage point and still be interference-driven; the single-position
math has no way to see that from one capture. Multiple positions do: a real
minimum-phase amplitude rolloff holds its shape as you move the mic; an
interference null's depth and center frequency both shift. Where the two
checks agree (min-phase AND spatially consistent), correcting it is on solid
ground. Where they disagree, or only one is available, treat the correction as
unproven and say so — don't let a passing `excess_gd_mask` alone green-light a
boost into what might still be a position-dependent cancellation.

## Tune order: driver-local EQ, then alignment, then system tone

A minimum-phase PEQ band changes phase with magnitude, so EQ placed on a
driver after its junction is aligned moves that alignment. The order that
does not undo itself (Resonalyze's manual makes the same argument):

1. **Driver-local EQ first** — corrections a driver's SOLO measurement (or
   its spatial average) justifies: its own resonances, a skirt brought down
   onto the crossover (below). Flattening a genuine minimum-phase resonance
   straightens that driver's phase too, which makes the next step easier.
   Keep bands broad near a crossover — many narrow bands near a sub/midbass
   junction turn the relative phase so fast that no single delay sums the
   pair over a useful bandwidth.
2. **Re-measure, then align** — polarity → delay → all-pass on the EQ'd
   drivers (the ladder below), top junction first. Re-align after any
   all-pass, which shifts group delay.
3. **System tone last** — broad shelves and bells away from the junctions,
   or applied to both drivers of a junction alike, so they do not disturb
   what step 2 settled.

This is not permission to EQ a summation problem: a dip that the solos do
not show is a phase problem and goes to the ladder, never to a boost. And it
does not relax the plan rule — phase-domain and EQ-domain writes still go in
separate plans with a re-measure between them; this only fixes which comes
first when both are needed.

## The crossover action-ladder (cheapest, safest first)

**Confidence is part of every recommendation.** A delay comes from
`delay_consensus` (junction score, magnitude search, cross-correlation, phase
slope): report the agreed value, how many estimators agree and the spread; a
`low` result or `timing_suspect` is "re-measure / check the timing
reference", never a number to write. An EQ band from `propose` with 3+
positions carries its held-out stability and action; present APPLY bands as
the proposal, REVIEW bands as questions, and say why DO NOT APPLY bands were
dropped.

**Start with `tunelib.crossover_confidence(freqs, solo_a, solo_b, together_db,
band)`, band-limited to just that crossover** (e.g. `(50.0, 120.0)` for sub/
midbass, `(1800.0, 4500.0)` for mid/tweeter) — not the whole trace. It bundles
`prediction_confidence`, `interference_audit`, and `phase_linearity_residual`
for that one region into a single `usable_for_crossover_decisions` verdict
plus a `destructive_interference_in_band` flag. If it comes back unusable,
stop and say so rather than running the ladder below on data that can't
support it — none of these steps are trustworthy on phase data the region
itself has already failed.

When `crossover_confidence` says the data is usable and two drivers don't sum
well through their crossover, test in this order and stop when the problem is
solved (a later, riskier tool must clearly beat the earlier one to be worth
it):

1. **Polarity** (free, binary).
2. **Delay** (cheap, no group-delay cost). `tunelib.polarity_delay_search` searches
   both together from complex solos. It also cross-checks itself against
   `tunelib.estimate_delay_xcorr` (a generalized cross-correlation estimate,
   `cross_check=True` by default) — a second, differently-computed delay
   estimate. **If `xcorr_agrees` is False, treat the delay result as
   untrustworthy regardless of how confident the grid search looks** — this
   is the situation the whole timing-chirp saga proved is real: per-frequency
   phase can be corrupted unevenly (clock drift) in a way a single method
   won't catch on its own, but two independently-computed estimates
   disagreeing will.
3. **All-pass** (adds group delay — only if polarity/delay leave a residual phase
   problem). `tunelib.optimize_allpass` searches F/Q against the summation.

Only after those, consider EQ — and only if the *solo* response justifies it.
`polarity_delay_search` returns `residual_needs_apf` to tell you whether step 3 is
even warranted. (EQ that the solo justifies is driver-local and belongs BEFORE
this ladder — see Tune order; EQ that only the sum "wants" is not EQ's job.)

### A channel hands over twice

A midrange meets the woofer below it and the tweeter above it. A delay,
polarity or all-pass that wins at one junction is carried to the other one
by the shared channel, and can spoil it. Before proposing any phase-domain
change to a channel with two neighbours, evaluate BOTH junctions with the
change applied, and say what the second one does. A delay applied to a
channel carries everything above it only if you move the whole stack — so
when the fix is "shift the midrange", ask whether the tweeter should move
with it.

### Reading a junction: phase score, sum loss, and which window

`python scripts/pipeline.py junction --lower MID.txt --upper TW.txt
--crossover 2500` (complex solos, one time base) reports two figures that
answer different questions:

- **`phase`** (`tunelib.junction_phase_score`) — Σw·cos(Δφ)/Σw with
  w = |lower|·|upper| over ±1 octave: 1 in phase, −1 inverted. One delay
  sweep of ±1.25 periods gives both polarities; a flip is recommended only
  when it beats the kept polarity by 0.05 (a real 80 Hz sub junction had its
  two best scores within 0.001 — that is a tie, not a flip). `lobe_margin`
  under ~0.05 means a whole-period hop cannot be ruled out; a best score
  under 0.5 means no delay is trustworthy (the drivers do not hold one phase
  relation across the band). `phase_at_fc_deg` is withheld when the bins
  around the corner disagree (a notch sits at the handover). Calibrated by
  Resonalyze on 20 junctions in 8 cars.
- **`sum_loss`** (`tunelib.junction_sum_loss`) — how far the complex sum
  falls short of perfect coherent addition, average and worst dip. It moves
  with the drivers' LEVEL ratio as much as with phase, so it never settles a
  phase question alone. A junction within ~3 dB with its score near its best
  is a working junction: leave it.

**Which window.** Above ~1 kHz the cabin decorrelates the two drivers' phase
in a full-window measurement — in Resonalyze's archive a correctly tuned
tweeter junction could not score above ~0.69 through the full window, but
reached ~0.93 through an 8-cycle frequency-dependent window. For junction
TIMING above ~500 Hz, build direct-sound responses with
`python scripts/decay.py fdw IR.txt --out DRIVER_direct.txt` from REW text
IR exports (they carry the shared time base) and pass `--direct-sound`. Below
~500 Hz the two windows agree (median 5°), so ordinary exports are fine.

### Cut a shallow acoustic skirt down onto the crossover (never boost one)

The crossover the user set is electrical; the drivers sum ACOUSTICALLY, and
a driver whose own output falls slower than the filter leaves a wider,
lumpier overlap than the crossover was chosen for. Treat the crossover's
ideal acoustic slope as part of that driver's target outside its passband:
where the measured skirt sits ABOVE that slope, a cut that brings it down is
a legitimate driver-local correction (step 1 of Tune order) and improves
summation — Resonalyze measured junction sum loss 0.37 → 0.30 dB on average
and worst dip 2.0 → 1.6 dB across seven car tunes doing exactly this. Never
boost a skirt: that undoes the crossover and spends the driver's excursion
where the neighbour is already playing at full level. Crossovers themselves
are still never written.


**A found delay can now be written directly** (`afpx.write_delay_samples`,
verified by `afpx.verify_delay_write`) instead of only ever being a
recommendation for the user to enter in PC-Tool by hand. This does not lower
the bar for *when* to write one: present the specific found delay (in both ms
and samples, at the unit's confirmed sample rate — never assumed) and get
explicit confirmation for that number before writing, exactly as for any
other write. The write itself is safe and verified; the decision to make it
still isn't automatic.

**Never combine a phase-domain write (polarity/delay/APF) with a PEQ write
in the same crossover-adjacent region in the same pass.** A PEQ band's
predicted effect is computed against the *currently measured* summed
response. Once a phase fix actually changes how the two drivers sum through
that crossover, the summed curve there changes too — a PEQ that was fit to
the pre-fix curve is now validated against data that no longer describes the
system. This is exactly why the ladder above is ordered polarity → delay →
all-pass → *only then* EQ: it isn't just "cheapest fix first," it's "don't
let a later step's math go stale out from under an earlier one still being
decided." If a phase write is happening this turn for a crossover region,
either leave that region's PEQ proposal for a later turn (after a
re-measure — `predicted_vs_measured` is the tool for confirming the phase
fix actually landed before trusting anything built on top of it), or say
explicitly that the PEQ prediction there is provisional pending that
re-measure. Don't write both against the same stale prediction and report
them as equally confident — they aren't.

## Shelf cookbook (broad tonal balance only)

Shelves are for **broad tilts anchored at a spectrum end**, never a local feature.
The hinge frequency `F` is the parameter that matters; everything past it moves to
the plateau.

- **Low shelf**: ~60–80 Hz hinge = sub weight; ~100–150 Hz = whole-bottom warmth.
- **High shelf**: ~8–10 kHz = "air"; ~3–5 kHz = broad brightness/de-harsh. A gentle
  high-shelf **cut** (−1 to −3 dB) is the classic fix for a bright, reflective cabin.
- Keep shelf Q low (0.1–0.7) for a smooth knee; Q > 1 adds a resonant bump.
- **Decide shelf vs bell numerically**: `tunelib.fit_shelf_to_curve` — if a single
  shelf can't reproduce the target shape within ~0.75 dB, it's a bell, keep the PEQ.
- **The reverse case — no shelf filters available at all**: this doesn't come up
  for Helix (it has real shelf types, T=3/T=4), but if you're ever helping with a
  DSP whose parametric EQ offers only peaking bands, `tunelib.fit_peaking_to_shelf`
  approximates a low/high shelf with N peaking filters over the channel's actual
  passband. Pass that DSP's real Q/gain limits — don't default to Helix's. It
  returns plain F/Q/G numbers only; it does not know or assume anything about that
  DSP's file format, so hardware-validate and enter/write them through whatever
  that specific unit actually supports.
- **Judging someone else's shelf emulation: check the Q values first.** A shelf
  is a plateau; peaking filters only build one if their skirts overlap, which
  needs **low Q (~0.5–0.7)** and placement *inside* the passband. Bands at
  Q 1.7–7.2 sitting outside the crossover cannot make a shelf no matter how many
  there are — each is a narrow bump on a signal the crossover is already
  attenuating. A real case (2026-08-05): seven such bands, offered as a
  "high shelf / low shelf emulation", summed to a **skirt** rising to −1.95 dB
  only in the last half-octave before the crossover, and under 0.05 dB
  everywhere else. The intent was sound (that DSP has no native shelf type);
  the execution could not work. Diagnose it by evaluating the bands' combined
  response inside the passband and comparing it to what an actual shelf would
  do — flat past the hinge — rather than by counting bands.

## All-pass cookbook (phase only — use sparingly)

An all-pass has flat magnitude; it only changes how two branches sum. Earn it only
when the defect is phase (a summation null), never a magnitude bump.

- **F** = the null / phase-crossing frequency. **Q** = how sharp the correction is
  confined around F. Q is **not capped at ~2** (see helix_hardware.md — that was a
  documentation error, corrected 2026-07-11); PC-Tool accepts at least Q=9. Don't
  default to low Q out of a mistaken belief that higher is illegal — a low-Q APF
  aimed at a narrow null spills its rotation into a wider band and can create a
  *new* hole in territory that was previously clean, which is its own real cost.
  Use whichever Q actually confines the fix to the null without damaging the
  surrounding response — check both narrow and broad candidates against the
  measured summation, don't assume the lower one is automatically safer.
- 1st-order (T=19, no Q) for gentle broad correction; 2nd-order (T=20) for more/
  more-local rotation.
- **The channel Phase control is a third option that costs no EQ slot**: one
  Q=1 2nd-order all-pass whose lag at that channel's crossover equals the
  dialled angle (5.625° steps; `tunelib.helix_phase_rotation`, written as a
  `phase_rotation` plan edit). Its centre is tied to the crossover and its Q is
  fixed at 1, so it suits rotating a driver's phase AT its own handover (a
  junction whose best score wants a rotation no delay gives) or a broad
  one-sided L/R correction near that corner — not a narrow null elsewhere,
  which still wants a free T=20 with its own F and Q. Score candidates with
  `junction_phase_score` on the rotated response before proposing one.
- The **invert** flag (`I="1"`) flips rotation direction: if the null gets *worse*
  at every F/Q, invert and re-sweep.
- **The real cost of any APF is group delay, and the real imaging-risk metric is
  INTERAURAL group delay — not per-filter Q, and not "how many sides have a
  filter."** `tunelib.group_delay_ms_from_H` gives one filter's own group delay;
  `tunelib.interaural_group_delay_ms(freqs, H_left, H_right)` gives the L−R
  *difference* vs frequency, which is what actually predicts image smearing.
  **A split-side configuration (a different APF on each of L and R) is NOT
  automatically gentler on imaging than stacking correction on one side alone —
  it can be worse.** Confirmed from a real case: a high-Q APF on each side at two
  different frequencies (Q4.7 on one side, Q8 on the other) produced a peak
  interaural group delay of ~17 ms, versus ~7 ms for a single lower-Q APF placed
  on one side only — because opposite-side high-Q filters maximize the L−R phase
  *difference* right at the correction frequency, even though each individual
  filter looks modest in isolation. **Always compute `interaural_group_delay_ms`
  for the actual proposed L+R combination before judging it "safe" from Q or
  filter count alone.**
- Put a one-sided APF on the **subordinate** (weaker/farther) side when only one
  side needs it, keep it below ~1 kHz for one-sided use, and **verify centre image
  with a mono vocal** after — plus, for anything with meaningful interaural GD, a
  mono bass line through the correction frequency, listening for a note that
  smears or pulls sideways rather than staying anchored with the rest of the line.
- Symmetric APF (identical F/Q on both L and R) is summation-only and image-safe —
  zero interaural group delay by construction, since both branches get the same
  filter. This is different from a *split* configuration, which deliberately uses
  **different** F/Q per side and does carry real interaural GD risk (above).
- **A symmetric APF cannot fix an L+R cancellation.** The commonest reason for an
  all-pass in a car is a lower-midrange/midbass null where the LEFT and RIGHT
  drivers cancel at the off-centre seat (path-length difference). That null lives
  in the L−R relative phase, and an identical filter on both sides leaves the L−R
  relation exactly as it was. Only a one-sided (unilateral) APF changes it.
  **Real case (2026-07-09):** a unilateral 420 Hz Q0.7 APF on one front mid had
  cleared two L+R nulls; mirroring the same APF onto the other mid "for symmetry"
  zeroed the L↔R rotation and brought both back — the System Sum fell 17.5 dB at
  401 Hz and 22 dB at 173 Hz, the nulls position-stable at all three mic positions.
  Removing the mirrored copy restored the fix. Forum practice converges on the
  same remedy (a 2nd-order APF around 150–300 Hz on one side's midrange in many
  cars); find the actual F/Q from the measured L and R solos with
  `optimize_allpass`, check `interaural_group_delay_ms`, and verify with a mono
  bass line and vocal.

## Two windows: image from the direct sound, tone from the whole field

The ear places a source on the FIRST arrival (the precedence effect) and
judges tone on the whole field, reflections included. So the two kinds of
decision want two different views of the same driver:

- **Imaging and timing** — L/R arrival, junction delay and polarity above
  ~500 Hz, centre placement — from a **direct-sound** response: a
  frequency-dependent window of about 8 cycles from the driver's arrival
  (`decay.py fdw`). At 2 kHz that is 4 ms, so the earliest reflections are
  still inside; it is a short window, not an anechoic one.
- **Tonal balance and EQ** — from the full window, and better still from a
  spatial average (MMM or several positions), which no window improves on.

Never compare a figure from one window with a figure from the other, and
never average them. A disagreement between them is a hypothesis, not a
verdict: a deep direct-sound dip under a shallow full-window one suggests a
timing or polarity fault the cabin's later energy fills in; the reverse
suggests interference particular to that mic position.

## Image position is frequency-dependent, and one delay cannot fix it

The standard car-audio move is one delay per side, set from path length. That
is a single number for a mechanism that is not single:

- What the seat receives from the two loudspeakers differs by an
  **inter-channel time difference** (ICTD) and an **inter-channel level
  difference** (ICLD), each of which can change from band to band — a
  reflection, a crossover region or a driver's directivity moves one band
  and not its neighbours.
- A phantom image between two loudspeakers moves fully to one speaker at
  roughly **1 ms** of ICTD or **15–17 dB** of ICLD (Lee & Rumsey 2013), and
  the two cues **trade**: a time lead can be cancelled by a level cut. These
  are inter-CHANNEL figures, not interaural ones — 650 µs (the largest
  difference between two ears) moves a phantom image only about two thirds
  of the way. And level is not a treble-only cue here: at low frequency a
  level difference between the speakers is exactly what produces a time
  difference at the ears (Blumlein).

So an image can sit centred at 2 kHz and pull left at 250 Hz. That is audible,
extremely common, and invisible to both magnitude-vs-target and L/R level
matching — the two things a conventional tune actually checks.

`pipeline.py imaging --solo-l L.txt --solo-r R.txt` reports it. ITD is **fitted,
not differentiated**: the unwrapped phase difference is regressed against
angular frequency per band and the slope taken as the arrival-time difference,
which is far more robust than a pointwise group delay. Each band reports a
`pull` from −1 (hard right) to +1 (hard left) — pull = ICLD/16 dB + ICTD/1 ms,
clipped — with the cue that contributes more named. Sign: `itd_us` is positive
when the LEFT side arrives first, using REW's phase convention (a channel
arriving τ late has phase −360·f·τ). Releases before 1.9.0 had this sign
reversed, so an imaging or centre-steering result from an older version that
involved a non-zero measured time difference should be re-run, not reused.

Read the **`verdict`** first:

- **`stable`** — image holds position across frequency.
- **`pulled`** — consistently off-centre. This *is* the case a delay or level
  trim addresses; fix it the normal way.
- **`smeared`** — bands disagree with each other. **No single delay value can
  fix this**, and adding one will improve some bands while making others worse.
  The causes worth checking are inter-driver alignment within a side, a
  crossover region where the two drivers arrive at different times, and
  reflections (below).

Sign convention is positive = pulls left, throughout.

Honest limits. This is not a calibrated localization model — real
localization uses the listener's own head, pinnae and small head movements, none
of which a microphone at the seat has; read it as an ordering, not degrees of
arc. Time panning is weak for continuous tones with a high fundamental, where
level panning stays robust. An ICTD whose phase-difference regression fits
poorly is **discarded rather than blended**, because a phase difference that
isn't behaving like a delay is not an arrival-time cue. When phase is missing
entirely the time cue is withdrawn and any arrival difference between the sides
is simply absent from the prediction. Use direct-sound exports (Two windows)
for the time cue whenever you have them.

## Reflections: find the cause before reaching for a filter

A frequency response says a dip exists. It cannot say why. The impulse response
can: `decay.py reflections ir.wav` lists secondary arrivals with their delay,
level, and the **path-length difference** that delay implies.

The step that turns a hypothesis into a diagnosis is the comb prediction. A
reflection at delay *t* must produce its first cancellation at 1/(2*t*) and
repeat every 1/*t*. Pass the measured dip frequencies with `--dips 340 1020
1700` and each arrival is tested against them. An arrival that explains nothing
measured is not the cause of the problem in front of you, however real it is —
and a dip explained by no arrival needs a different explanation entirely
(driver, cabin mode, or summation between drivers).

Two disciplines carried over from the rest of `decay.py`:

- **Path difference is geometry, not a diagnosis.** The tool reports centimetres.
  Which panel sits at that distance is your call, and naming a surface from
  arithmetic alone would be a guess wearing a number.
- **`null_depth_db` bounds what the arrival can explain.** A −20 dB reflection
  cannot produce a 15 dB hole. When a measured dip is far deeper than the
  arrival allows, the arrival is at most part of the story.

The payoff is mostly negative, in the best sense: a reflection is not an EQ
problem, so identifying one stops a filter being spent where no filter can work
and points at aiming, absorption or an enclosure change instead.

## Imaging

**Level is a poor proxy for distance — timing is the definitive one.** It is
tempting to infer "which speaker is nearer the measured seat" from which side
measures louder, and it is unreliable, because measured level is confounded by
at least three things at once: the channels' own gain settings (measurements
taken through a tune include them — subtract them before comparing), driver
aiming/directivity (in a car the *far* tweeter often fires more on-axis across
the cabin and can measure louder than the near one), and driver-to-driver
variation. A real case (2026-08-05): raw measured level said "right is nearer"
on two pairs and "left is nearer" on the other two, while arrival time said
"right is farther" consistently on all four. **When level and timing disagree
about geometry, timing wins.** Level asymmetry is still worth reporting — as an
imaging problem to solve — just never as evidence of which speaker is closer.

**Was the tune's own delay active during the capture? Test it, don't assume —
sign-coherence across pairs settles it.** Arrival times measured through a DSP
that is already applying delay are not acoustic flight times, and the two
interpretations lead to opposite conclusions about seat and wiring. Compute the
L/R arrival difference for every driver pair under both hypotheses (raw
arrivals, and arrivals minus the preset's stored delays). **One microphone
cannot be in two places: the correct hypothesis gives the same side farther on
every pair.** In a real case, "delays bypassed" gave right-farther by 31–74 cm
on all four pairs while "delays active" gave left-farther by 3–7 cm on two
pairs and right-farther by 23–35 cm on the other two — incoherent, therefore
wrong. A further sanity check on the surviving hypothesis: the L/R differences
should track mounting geometry, growing as drivers sit further outboard
(dash mids 32 cm < sail tweeters 44 cm < rears 48 cm < door midbass 74 cm is
what a real driver's-seat capture looks like).

**Within-pair L/R timing is immune to crossover group delay — cross-driver
timing is not.** Both channels of a driver pair pass through identical
crossovers, so any group delay they add cancels in the L-vs-R *difference*.
That makes the L/R split usable even from captures taken with crossovers
bypassed or with a protective filter in place, which is often the only data
available. The same capture tells you nothing reliable about tweeter-vs-midbass
alignment, where the crossovers' group delay is precisely what you'd be
measuring. **A safe partial correction follows from this: fix each pair's L/R
split while preserving that pair's MEAN delay**, which leaves every
cross-driver relationship exactly where it was and changes only the thing the
data supports.

**Low-frequency arrival estimates inflate — cross-check before writing one.**
A driver's own rolloff plus cabin effects push REW's delay estimate long at LF;
in one case a door midbass roughly 0.7 m away reported 2.80 m and 3.54 m paths.
A physically impossible distance is the cheap tell. Run `estimate_delay_xcorr`
as an independent check and compare: agreement to a few hundredths of a ms with
`reliable` set is writable; a 2.5 ms disagreement with `confidence_ratio` near 1
is not, and no amount of wanting the number changes that.

The near/dominant speaker (louder, closer to the measured seat) anchors
localization. Broad level-match the two sides in the image band (~500 Hz–8 kHz,
weighted 700 Hz–5 kHz) — `tune_scorecard` reports L/R balance. A system sum cannot
reveal L/R imbalance, so per-side work needs solo measurements.

**Where, not just how much.** `tune_scorecard`/`perceptual_score`'s stereo term
give one scalar for the whole band — useful as a headline number, useless for
deciding what to fix. `lr_match_report(freqs, left, right, band, flag_db)`
(Smaart discipline: interchannel mismatch is more audible than absolute-curve
error, since a center image is built from L and R summing coherently — wherever
they diverge in level at a frequency, the image pulls toward the louder side
*at that frequency*, heard as smear/wander even when each channel individually
reads close to target) gives the actual regions: extent, peak mismatch in dB,
and which side is louder. Read-only — it tells you where to look, not what to
do about it.

**Closing a flagged gap** usually means fixing the worse channel directly
(preferred — it also improves that channel's own accuracy). When that's not
possible — the "worse" side's deviation is a masked null, non-min-phase, or
otherwise un-EQ-able — `fit_peq`'s `partner_target_db`/`partner_weight` can
instead pull the *better* channel toward matching the compromised one, trading
a bit of that channel's own tonal accuracy for a stable image. This is a real
trade, not a free win: it competes against `fit_peq`'s existing boost tax by
design, so `partner_weight` around 1.0 often isn't enough to win when the
needed move is a boost — that resistance is intentional, not a bug, since a
boost that only helps matching and does nothing for the channel's own target
accuracy should have to earn its place. Raise the weight (2–4+) once you've
actually decided the image-stability payoff is worth it for that specific
region; don't reach for it as a default.

### Placing the phantom centre: level, or time and level

At an off-centre seat the near side arrives earlier and louder, and the image
collapses toward that door. Equal-arrival time alignment removes the time part;
what is left is a level and directivity question. Two established ways to
centre it, which trade against each other (`tunelib.centre_steering`, or
`pipeline.py imaging ... --near-side right|left`):

- **Level only** — leave the alignment at equal arrival and attenuate the near
  side until the image centres. Typically 5–8 dB in a car. Costs near-side
  headroom and can tilt that side's tone.
- **Time and level** — also let the FAR side arrive slightly early (0.2–0.3 ms
  is a reasonable start in a sedan), so part of the steering comes from time;
  the near side then needs roughly half the cut (2–4 dB) for the same image.

Neither is "correct" — present both with their numbers and let the user choose
by ear with a mono vocal. Two cautions to state with the time option:
inter-channel time changes about 0.29 ms per 10 cm of head movement while
level barely moves, so a time-made centre is narrower in space; and past about
±0.3 ms the image becomes less certain. `centre_steering` therefore recommends
the largest lead not past 0.3 ms whose trim fits, and returns every option.
These are stage decisions — never write a gain that equalizes the sides
without a measured level delta behind it, and never as a side effect of EQ.

### The image outranks the crossover above ~300 Hz

When a junction's delay search and the L/R image disagree, decide by band.
Above ~300 Hz the arrival relationship between a driver's left and right
instance IS the image: keep each pair's L/R arrival where the chosen centre
needs it (equal, or the chosen far-side lead) and fit the junctions around
that, rather than letting a junction delay drag one side's driver off its
twin. Below ~300 Hz arrival carries little localization: there the junction
summation decides, and the L/R split only has to stay on the right lobe.
For DELAYS, align from the TOP junction down: the tweeter junction needs
hundredths of a millisecond, the sub junction tolerates about one, and a delay
moves a channel at every frequency, so anchoring on the top puts the error
where the ear forgives it (Resonalyze's auto-alignment archive). For the
channel PHASE controls the manufacturer advises the opposite order —
sub↔woofer, woofer↔mid, mid↔tweeter — and for them that is right: each
control acts at its own channel's lower crossover, so a higher one barely
disturbs a junction already set below it. Delays first, then phase controls
bottom-up, then re-check every junction.

### Polarity belongs to the driver

A driver's left and right instances share one polarity. A proposal that
inverts the left midrange but not the right one is not a tune, it is a wiring
question — check the physical connection before writing anything. Settle a
pair's polarity at the junction where it is clearest and carry it to the
twin; at a low junction where the two polarities score within ~0.05, keep the
current one.

**A cheap, high-confidence signal for when a one-sided cut is the right move (not
just legal): scan for frequencies where the whole-system deviation-from-target
AND the raw L/R imbalance both flag the SAME side as hot at the SAME frequency.**
When they align, a single cut on that one channel fixes both problems in one
move — the tonal excess and the imaging error were the same root cause, not two
separate ones needing separate fixes. This is a stronger, more specific case than
the general "fix the worse channel" rule above: it's not just permission to touch
one side, it's a positive search — look across the band for spots where sum-error
and imbalance-direction agree, and treat those as the free wins to take first,
before spending budget on anything symmetric in the same region.

## Restraint (the thing that beats aggressive auto-EQ)

- Model candidate edits jointly and predict the summed result — bands within an
  octave interact; never set gain = −deviation per band.
- Peaks cost more than dips. Don't fill narrow dips. Don't chase single-point RTA
  combing.
- Fewer, broader, lower-Q filters that improve the whole-system `tune_scorecard`
  beat many narrow fixes that flatter one trace. Empirically, "aggressive" tunes
  that push bigger moves tend to *lose* on robust, whole-system scoring.
- Every edit needs a reason tied to the data. If you can't say why, don't write it.
- **A masked null needs an active guard, not just exclusion.** `fit_peq`'s
  `mask` parameter excludes null/non-min-phase/low-confidence bins from the
  fit error — but that's passive: a band aimed at a legitimate nearby feature
  can still spill real boost into a masked bin as a side effect, since nothing
  was watching that region. `null_boost_penalty` (on by default) actively
  penalizes any positive gain the candidate cascade produces inside masked-out
  bins, closing that loophole instead of just declining to reward it.
- **A deviation must survive more than one session before it's actionable, not
  just clear the noise floor once.** The noise-floor ratio filters measurement
  jitter within a session but not run-to-run coherence/setup variance across
  sessions (see the crossover coherence-wobble trap above). When independent
  same-target captures exist, require a deviation to hold sign and rough
  magnitude across all of them before writing a fix; drop anything that swings
  sign or vanishes on a repeat, however large it looked in isolation. A real
  case (2026-07-31): scanning one session flagged sixteen deviations by
  noise-floor ratio alone; requiring 3-session persistence collapsed that to
  four real ones — two of the discarded flags (68 Hz, 4000 Hz) swung 2-3 dB
  session to session despite no EQ touching them in between.
- **A gain predicted by optimizing coherent complex summation at ONE fixed mic
  point is not evidence the change helps in the car — the objective itself is
  the flaw, not the candidate filter/delay.** A phase-only edit (all-pass,
  delay) cannot create acoustic energy; it only moves WHERE constructive and
  destructive summation land in space. Selecting an fc/Q or a delay value by
  maximizing predicted summation at a handful of points will reliably find
  *something* that looks robust — even agreeing in sign across several points,
  even across several sessions — precisely because summation peaks/nulls are
  large and spatially structured. That structure is exactly what a spatially-
  averaged (MMM) measurement integrates away. A real case (2026-08-08): an
  all-pass was selected because 4 independent complex-summation datasets
  across 3 mic positions all agreed in sign on the predicted gain (+0.3 to
  +1.5 dB in the target band) — and it measured the OPPOSITE sign by MMM after
  writing it (−0.65 dB), degrading a broad ~2000–8000 Hz span the fixed-point
  prediction never flagged. The same session independently killed a whole-side
  delay proposal by the identical mechanism (it improved the centre-mic
  prediction while simultaneously worsening BOTH ear-position predictions in
  the source data itself — the failure was visible before ever measuring), and
  a channel-level trim (a fixed-point sweep said +1.56 dB; two separate MMM
  sessions on the same channels said +0.51 dB and +1.09 dB). **If a
  phase-domain change is meant to survive in the car, select AND validate it
  against spatially-averaged data from the start — fixed-point agreement
  across positions or sessions is not a substitute, no matter how internally
  consistent it looks.** The one delay refinement that DID hold up under MMM
  in that same project worked because, at those frequencies (40–140 Hz,
  wavelength 2.4–8.6 m), a single point genuinely represents the whole cabin —
  the fixed-point technique isn't wrong in general, it just stops being valid
  somewhere in the low hundreds of Hz, well below where crossovers and imaging
  decisions usually live.

## Verification & honesty

Predictions from magnitude (RTA/MMM) data don't capture phase outcomes. Always end
by telling the user which claims are *predicted* vs *measured*, and give a specific
re-measure + listening checklist — the loaded-and-re-measured result is the only
real proof.

**When that re-measure actually comes back, use it — don't just eyeball the new
plot.** `tunelib.predicted_vs_measured(freqs, before_db, remeasured_after_db,
bands)` grades every written band against the fresh measurement instead of
trusting the one-shot prediction forever. The reason this needs its own
function rather than a plain subtraction: two real measurement runs never
match exactly, even with nothing wrong — a different playback level, a mic
that landed slightly differently, more road/engine noise that day. A naive
diff can't tell "the correction failed" apart from "I played it 2dB quieter
this time," and would produce false verdicts either direction. So it doesn't
diff raw curves — it estimates a broadband level offset only where the
predicted change is ~0 dB (so the alignment step can't quietly absorb the very
change being tested, skirts included), compares octave-smoothed regions around
each changed band's center (so ordinary mic-position comb ripple doesn't read
as failure), and drops to `'inconclusive'` wherever confidence in that region
is low or the change is smaller than the measurement can resolve, rather than
forcing a verdict either way. `'confirmed'` means the re-measure is closer to
the predicted change than to no change at all — before 1.9.0 a fixed 2 dB
tolerance let an untouched re-measure "confirm" any cut smaller than 2 dB.
Pass `old_bands` when filters were edited or removed, so the prediction is the
new bank relative to the old one rather than another cascade on top. Treat a `'reverted_recommended'` result the
same as a `interference_audit`/`reaches_target_after_boost` finding pre-write
— it means the predicted change didn't actually show up, which is usually
the same "phase/interference is eating this" signature, just caught after
the fact instead of before. Pull or reconsider that band rather than leaving
it in the file on the strength of a prediction that turned out wrong.

**Extend the same skepticism to a candidate you didn't produce yourself.** This
applies "re-decode fresh, don't trust memory" (see SKILL.md's non-negotiables) to
external candidates too: when another AI, an optimizer, or an earlier session hands
you a candidate `.afpx` with a self-reported score, check what measurement files
and baseline tune it actually used to compute that score — file dates catch a stale
comparison fast. A score computed against data that's since changed is meaningless
even if it's internally consistent and the math checks out. **Always reproduce the
claimed score yourself against the current session's data** before accepting it.

**A check that cannot fail is not evidence — confirm the negative case before
trusting the positive one.** A verification step that returns the right answer by
construction (a parse that silently defaults to zero, a regex that matches nothing
and leaves a variable unset, a diff against an empty baseline) will report success
whether or not the thing being checked is actually true. A real case (2026-08-01):
asked to confirm a car's two rear channels received sign-inverted signal from a
routing matrix, a first pass regex failed to parse the matrix's `G<N>="..."`
coefficients, every value silently read as the float default `0.0`, and the
equality test `ch5 == -1 * ch4` passed — because `0.0 == -1 * 0.0` is true
regardless of what the real matrix contains. The printed "verified: True" was
correct-looking output for a test that could not have failed. Caught only because
the user pushed back from firsthand knowledge (their polarity control reads
"normal" on both channels — true, and a *different* field from the matrix sign
being checked). The fix isn't a cleverer parser; it's a habit: before trusting an
assertion's result, ask whether that assertion could have printed the same output
if the underlying data were garbage, empty, or all-zero, and add an explicit guard
for that (e.g. assert the parsed set is non-empty / not all-zero) alongside the
real check. This is the same root failure as the stale-decoded-field trap above
(Q on a bypassed crossover) — a value looked meaningful and wasn't — but here the
uninspected thing is the *verification code itself*, not the data.

## REW's IR-delay estimator can lock onto the wrong cycle on a band-limited driver

On a steeply high-passed driver (a tweeter above its corner) REW's estimated IR
delay can jump between values about `1 / f_passband` apart on identical repeats:
7.02 and 6.58 ms in one 8-repeat test, a 0.44 ms gap matching 1/2278 Hz, each
cluster repeatable to microseconds. **Decisive test:** fit a delay to the phase
difference `unwrap(angle(B/A))` between one capture from each cluster over a
band both cover: it reads about 0 ms when only the estimator jumped. Never trust
one reported REW delay for a band-limited driver; use repeats or the exported
complex data (`delay_consensus` checks for this).

## Recovering per-channel L/R responses from a common-source pair, without solo captures

If one channel's polarity can be toggled, `N = L + R` and `V = L − R` captured
on a shared time base give both channels exactly, for any linear system:

```
L = (N + V) / 2
R = (N − V) / 2
```

Validate against an independent solo of that channel where one exists (0.01-0.26
dB median error in one project), and **outside the recovered channel's
passband too**: the captures' shared noise does not cancel, and a recovered sub
once read nearly as loud as the mids at 6-19 kHz.

## When `polarity_delay_search` says "nothing to gain," run `delay_sweep` (and how this was actually found)

`polarity_delay_search` can report `improvement_pct: 0.0` while a real in-band
gain exists. Its default `damage_band=(60, 16000)` penalises any delay that
worsens the full-range sum, and a band-limited driver's capture is noise floor
across most of that span, so the safety term swamps the in-band gain.

**Run `delay_sweep` (or `overlap_weighted_delay_gain`) alongside it whenever
either driver is band-limited.** It scores coherent-versus-power-sum gain
inside `band` only, weighted by `min(|a|,|b|)**2`; `datasets=[...]` from other
sessions returns the maximin-robust delay; and it flags `ambiguous` when a
near-equal second maximum sits over half a wavelength away (a cycle slip).
Narrowing `damage_band` to the driver's real passband (20-200 Hz for a sub) also
fixes `polarity_delay_search`.

**Rule:** a candidate-finder's "nothing here" — especially exactly 0.0 — means
its score did not move, not that the acoustics are optimal. (Found 2026-08-08 by
an independent recomputation: a 0.1-0.7 dB gain, later confirmed by an in-car
A/B.)

## Bracket every A/B write A→B→B→A, and anchor on a band the write structurally cannot touch

A two-state comparison spanning more than a couple of minutes can drift
(playback level, auto-gain, a connection) by more than the effect measured.

**Bracket:** capture A, B, B, A, not A, B. If the two Bs agree and the two As do
not, the session drifted (one A/B rose +2.7 dB over four minutes).

**Anchor on a band the write cannot touch.** A delay or all-pass is magnitude-
flat on its own channel, so the edited channel's solo must be magnitude-
identical before and after, and any band that channel does not dominate is a
drift anchor: re-reference every capture to its own level there before
comparing. That recovered 0.07-0.11 dB repeatability and a real 0.2-0.6 dB gain
from the drifting A/B above.

## A whole-system "sum" scorecard is nearly blind to a channel-pair L/R imbalance — the math

Two decorrelated, equal-nominal-level sources with a total imbalance of `D` dB
between them (one at `+D/2`, the other at `−D/2` relative to balanced) produce
an incoherent power-sum only THIS much different from the balanced pair's sum:

| imbalance between the two channels | change in their SUMMED level |
|---|---|
| 1 dB | 0.03 dB |
| 2 dB | 0.11 dB |
| 2.45 dB | 0.17 dB |
| 3 dB | 0.25 dB |
| 5 dB | 0.68 dB |
| 10 dB | 2.40 dB |

`ΔdB = 10·log10[(10^((D/2)/10) + 10^((−D/2)/10)) / 2]`, verified numerically.

A 2–3 dB L/R channel imbalance — clearly audible, clearly worth a level trim —
moves a system-sum scorecard by roughly a TENTH of a dB. Any scoring/QA loop
that only ever looks at a system sum (or any other coherent multi-driver mix)
is structurally unable to see this class of error: the sum isn't wrong, the
energy really is all there, it's just distributed unevenly between two
sources the sum can no longer tell apart. **If per-channel L/R balance
matters (it usually does for imaging), it has to be checked from per-channel
solo measurements — an excellent system-sum score is evidence of aggregate
tonal correctness, not of balance.**

## Extracting distortion/coherence from a REW `.mdat` when only text exports were expected

REW's SPL & Phase text export carries magnitude and phase only. A `.mdat` —
REW's Java object stream (magic `\xac\xed\x00\x05`, then "REW Measurement
Data File V2") — carries everything per measurement, and `scripts/mdat.py`
reads it **by structure**: one `roomeqwizard.MeasData` object per
measurement, each stating its own axis (`startFreq`, `logStep` or `freqStep`,
`dataLength`), its unsmoothed `rawValues`, the RTA settings and level notes,
the mic serial and cal curve, and for sweeps the impulse response, timing
reference and delay, SNR, the fundamental and harmonics (`distortionData.harmData`:
its second array is the fundamental, then H2 up) and a
per-frequency noise floor. Address a measurement as `file.mdat::Name` or
`file.mdat::#3` anywhere a capture path is taken.

**Never pick float arrays out of the bytes by pattern.** The byte scanner
this replaced took whichever large array came first: on an RTA file the
615-point mic calibration curve, on a sweep file a 956-point distortion array
on an axis 21% wrong — and its one-third-octave axis check passed both. The
field meanings come from real files (REW 5.31.3 and 5.40 beta 127, Windows
and macOS), not REW documentation: `mdat.py` refuses a file whose stated axis
does not end where REW says (`endFreq`), and the user's own `.mdat` files hold
local paths (cal files, user names) — scrub them before sharing one.

**Listening-position THD from RTA/MMM-style captures is frequently an
artifact, not driver stress — two specific traps:**
1. **Below a crossover.** A driver's fundamental is attenuated by its own
   high-pass at a given frequency, but a harmonic 1–2 octaves up can land
   comfortably inside the driver's passband at full gain — dividing a
   suppressed fundamental by an unsuppressed harmonic reports huge "THD"
   (17–20% observed) that has nothing to do with the driver actually
   distorting.
2. **In a cabin null.** The same division problem happens spatially: a
   driver measured at a frequency where the room/cabin has a deep magnitude
   null shows inflated THD at that frequency even with a perfectly linear
   driver, because only the fundamental — not the harmonic, elsewhere in the
   spectrum — is being suppressed by the null.

Both traps distort magnitude only, not distortion measured **nearfield**, or
measured **only inside the driver's own passband, away from crossover
corners**. Restrict any real driver-stress conclusion to those conditions.
## Electrical-vs-measured decomposition must be tune-matched, and may not be recoverable at all

When splitting a measured L/R (or any) difference into "DSP-electrical" (computed
from a `.afpx`'s PEQ chain) vs "non-DSP residual" (measured minus electrical), the
electrical transfer function and the measured trace **must come from the same tune
state**. A real case (2026-08-09): a script subtracted one tune file's electrical
L/R transfer from an **8-session historical mean** measurement, spanning five weeks
and multiple different tune states. The arithmetic was internally consistent and
produced plausible-looking numbers (e.g. "DSP explains only 5-9% of the imbalance",
"non-DSP residual +14 dB") — but it was invalid, because five of the eight sessions
predated every tune file that still existed on disk. There was no way to redo the
decomposition correctly from the available corpus; the finding had to be withdrawn
outright, not merely corrected. This is the same "apples to oranges" class of error
as averaging deviation across different tune states elsewhere in this file, but it's
easy to miss specifically in decomposition scripts because the electrical subtraction
happens as one clean vectorized step and nothing about the code makes the mismatch
visible. **Before trusting a decomposition's "non-DSP residual" number, check that
each measurement session has a surviving `.afpx` (or documented no-EQ state) from
the same date**, and if it doesn't, decompose only single-session measurements
against their own tune, and don't average residuals across tune states you couldn't
individually decompose.

## Width/Q from a plot: pick one definition and don't switch mid-analysis

Two different scripts in the same project, over the same feature, produced two
different octave-widths — 0.09 octave (implying Q~16, beyond the hardware's Q15
ceiling) vs 0.13-0.15 octave (implying Q~10, well within range) — because one
script measured "band where the mean stays within 1.5 dB of the extreme" and the
other measured the standard −3 dB / half-amplitude width. Both numbers were
computed correctly from real data; they just answer different questions, and only
the −3 dB definition maps onto PEQ Q the way `fc/Q` filter design assumes. The
"1.5 dB of the extreme" version is *narrower by construction* whenever the feature
isn't a clean symmetric notch (real notches never are), so it will systematically
suggest more extreme Q than the filter you'd actually design. **Always use −3 dB
(half-amplitude) width for any Q estimate that will inform an actual filter choice**,
and if a different width metric is used for some other purpose (e.g. characterizing
how "narrow" a feature looks for a stability/robustness argument), label it
explicitly as such so it never gets read as a Q recommendation.

## A filter's benefit must clear the untouched-channel drift floor, not just be positive

A single unbracketed before/after A/B will always show *some* movement on the
channel that wasn't touched — session-level drift (mic reseat, playback level,
cabin conditions). A real case (2026-08-09): an 8 kHz filter's benefit, measured
at auditory (ERB) bandwidth over its intended 4-14 kHz range, was +0.17 dB — while
the same session's untouched control channel drifted a median 0.13 dB with a
0.96 dB 10-90 percentile spread. The filter's electrical behavior was independently
confirmed correct (the touched channel moved almost exactly what the PEQ predicts),
so this isn't a case for reverting it — but the *size of the win* is not
distinguishable from ordinary drift, and should not be cited as evidence this class
of correction is worth pursuing further. **Before reporting a filter's dB benefit
from a single A/B, compute the same before/after metric on an untouched control
channel from the same session and report both numbers side by side** — see also
`predicted_vs_measured`'s untouched-frequency alignment, which exists for the same
reason. A benefit smaller than the control drift is "keep, benign, unproven" — not
"materially improved."

## Nearfield-vs-seat shape comparison as a cheap cancellation test

The established test for "is this a cabin null, not a driver/level issue" has been
nearfield-absent-at-seat-present (documented above re: the 400-500 Hz seat null).
The same test works directly on an **L/R difference trace**, not just on a single
channel's response, and is cheap if a nearfield L/R pair already exists from an
unrelated session: mean-remove each of the seat-difference and nearfield-difference
traces over a shared reference band (to cancel the arbitrary mic-distance level
offset between the two capture types), then compare shape. A real case
(2026-08-09): a 12.5 dB seat-only L/R swing across 140-200 Hz (a null signature by
its narrowness and depth alone) was confirmed non-actionable this way — the 140 Hz
and 200 Hz components were largely or fully absent nearfield, while only the 160 Hz
component partially survived. This closed a question that would otherwise have
needed a dedicated physical/mechanical measurement session. Caveat: this is
supporting evidence, not proof, when the nearfield and seat captures are from
different sessions/distances with no matched-distance control — treat a clean
absence as license to *not* spend measurement time on physical investigation, not
as certainty.

## Common-mode (System Sum vs target) is a first-class objective, not a fallback

During long work on one axis (L/R balance, one band, one pair), periodically
re-score System Sum against the target from scratch: a +2.5 dB excess at 100 Hz,
SD 0.2 dB across four sessions, once sat unnoticed for weeks. Common-mode
corrections (one filter on both sides of a pair) can never undo L/R work.

**But a System Sum deficit is not automatically common-mode.** Inspect the
contributors first: a stable −5 dB at 7 kHz was entirely one tweeter (its
nearfield −5.05 dB, the other +0.09 dB). Only a deficit both sides share is a
common-mode filter candidate. See "Nearfield claim ceiling" and "Deep/narrow
notch boost guardrail" below for a source-local cause.

## Fixed mic vs MMM is a second, orthogonal authority question — "what to fix" vs "did it land"

**MMM answers "what should be fixed?"**: tonal balance, L/R spectral balance,
System Sum against target — anything inherently spatial.

**A fixed mic answers "did a known DSP change land?"** With the mic untouched,
`A = R·S` and `B = R·H·S`, so `B/A = H` exactly: the cabin cancels, and what
matters is repeatability, not spatial averaging.

**Rule:** verify a write with a fixed mic (tripod, untouched, ideally A→B→B→A)
against the exact predicted transfer. Never infer a routing, tool or DSP fault
from an MMM result unless the effect is far above MMM's *measured* variance in
that band; otherwise label it "unresolved". (An MMM A/B once suggested 19% of a
−1.5 dB cut landed and prompted an invented PC-Tool fault; a fixed mic measured
−1.53 dB.)

## Prediction and measurement must go through the identical operator

Run a predicted transfer through the same smoothing, baseline fit or scoring
operator as the measurement before comparing them. The error goes either way:
a 100 Hz Q4 −1.5 dB filter looked 51% delivered against its raw depth and 69%
(inside the repeat spread) against its ERB-smoothed prediction; an 8 kHz Q12
−3 dB filter called "shallower than predicted" in fact exceeded its
1/3-octave-smoothed prediction. The risk is largest when the filter is as
narrow as the operator (ERB below about 200 Hz, any 1/N-octave smoothing for
high-Q filters). `erb_smooth()` and the 1/N smoothers work on synthetic curves
too; see `models_discriminable()` for comparing residuals on one basis.

## Model-discrimination gate — a smaller residual is not a finding by itself

Choosing between two competing explanations (which channel got a filter, which
topology fits the data, which mechanism caused a deficit) by picking whichever has
the lower fit residual is only valid if the two residuals differ by more than the
uncertainty of the data used to compute them.

**Real case (2026-08-10):** an MMM-derived comparison scored "mids+subs" at
0.46 dB rms and "mids-only" at 0.30 dB rms, and the lower number was reported as
"mids-only fits better." The measurement's own low-frequency path noise that
session was ~0.8–0.95 dB — larger than either residual, let alone their 0.16 dB
gap. The conclusion was unsupportable from the data used to reach it, and it
became load-bearing for a wrong implementation diagnosis (see the fixed-mic
section above).

**Rule, and helper:** before preferring the model with the smaller residual, call
`tunelib.models_discriminable(residual_a_db, residual_b_db, uncertainty_db)`. It
returns `not_discriminable` unless the gap between the two residuals exceeds the
supplied uncertainty (by a configurable margin, default 1×) — in which case the
correct statement is "these models cannot be told apart from this dataset," not a
preference for the smaller number. The `uncertainty_db` argument must be the
measured variance for the *same* band/metric/protocol used to compute both
residuals, not a number borrowed from a different measurement (see
`historical_repeatability`'s docstring on the same point).

## Nearfield has a claim ceiling: source-local, not exact physical cause

Nearfield-vs-seat comparison (see "Nearfield-vs-seat shape comparison" above) is
excellent for answering *whether* a feature originates at the driver or is created
between the driver and the seat. It does **not**, by itself, identify *which*
physical mechanism at the driver is responsible.

**Real case (2026-08-10):** a left tweeter showed deep notches at 4.6 and 7.2 kHz,
confirmed present in its own nearfield capture and absent on the right tweeter.
That is solid evidence of "left tweeter, physical" — but driver aim, mounting,
grille diffraction, a cavity resonance, and unit-to-unit manufacturing variation
are all consistent with the same nearfield signature, and nothing in a magnitude-only
nearfield capture distinguishes between them.

**Rule:** the supportable claim from a present-nearfield, absent-on-the-other-side
result is "this has a confirmed source-local component; the exact physical cause
is unresolved" — not a specific mechanism (aiming, defective unit, etc.) unless
something further (a driver swap, a mounting change with a re-measure, physical
inspection) actually isolates it.

## Deep/narrow notch boost guardrail — stable does not mean boostable

A notch that is deep, narrow, and highly repeatable is *more* suspicious as a
boost target, not less — those are exactly the properties of a directivity null,
installation cavity resonance, or driver radiation limit, none of which respond
usefully to electrical boost.

**Real case (2026-08-10):** the 7.2 kHz System Sum deficit above (−5.32 dB,
SD 0.11 dB, ratio 48 — by every repeatability rule in this file, about as
trustworthy a number as this project ever produced) was one step from a proposed
`7400 Hz / Q7 / +6 dB` common-mode correction before nearfield data showed it was
a single driver's own radiation response, not a target/tonal deficit. Boosting a
driver by 6 dB at a frequency where it measures 5–11 dB down *at the driver itself*
would have driven it harder exactly where it isn't radiating toward the listener —
distortion and heat, not output.

**Rule:** before proposing a boost at a deep/narrow feature, however clean the
repeatability statistics look, check (in order): is it present nearfield (source-
local, not cabin)? is it present on both sides (physical asymmetry, not systemic)?
does the target/reference curve actually call for output there, or is the "deficit"
relative to a smooth target that was never validated at that resolution? A feature
passing every repeatability test is a reason to trust the *measurement*, not a
license to skip the mechanism check before writing a filter.

## Nearfield aesthetics do not override a seat-validated filter

Once a filter has been validated by an actual seat A/B (predicted vs measured
agreement, controls checked), a *later* nearfield capture that makes the filter's
centre frequency look visually mis-centred relative to the driver's raw acoustic
shape is not grounds to re-fit it.

**Real case (2026-08-10):** an FL tweeter `7100/Q1.6/−3` cut, previously validated
by a seat MMM A/B that measured the predicted change to 0.19 dB rms, was checked
against the same driver's nearfield acoustic shape (EQ chain subtracted). The
filter's deepest cut landed where the driver was nearfield-quieter than the other
side by 2.2 dB — on paper, a better-centred filter would sit 1–1.5 kHz lower. It
was **not** refit: the seat is the authority for a balance decision the nearfield
capture cannot make (nearfield isn't what's heard), the existing filter had actual
outcome evidence behind it, and no new seat-level test existed to re-validate a
change. The observation was recorded for if the driver's physical aim is ever
changed, at which point the whole HF EQ region should be refit from fresh seat
measurements rather than patched from nearfield reasoning alone.

**Rule:** nearfield data can explain mechanism and flag a filter as *worth
re-examining after further seat testing*. It cannot, by itself, justify changing
a filter that has direct seat-level outcome evidence behind it.

## Retraction discipline: a disproven claim invalidates what was built on it

When a stronger measurement disproves an earlier conclusion, the earlier
conclusion must be explicitly withdrawn — and so must anything reasoned from it,
even findings that felt independent at the time.

**Real case (2026-08-10):** "the sub channels never received the filter" (from
MMM, see above) was the direct basis for "mids-only fits the System Sum better
than mids+subs" (see the model-discrimination section) and for the PC-Tool
clamping hypothesis (see the fixed-mic section). When the fixed-mic test and the
PC-Tool screenshot disproved the first claim, all three had to be retracted
together — not just the original one, quietly leaving the derived claims to stand
on their own. A retraction message should say explicitly which downstream claims
are being withdrawn along with the source claim, not just correct the immediate
number.

**Practical check:** before citing a prior finding in this project (this session's
or an earlier one's), ask whether it depended on something that has since been
re-measured or re-analyzed. If yes, re-verify the dependency before reusing the
conclusion — don't assume a claim is still good just because nobody has revisited
it.

## Rear-fill / ambience channels need their own measurement discipline

**A diagnostic stimulus is not the listening level.** A differential test
signal loud enough for SNR on an ambience channel plays it far louder than
music does. Shape and L/R matching from such a capture remain valid (each
channel normalised to its own in-band level); absolute rear-to-front level and
audibility conclusions do not.

**A channel can have an objective matching problem with no target.** Twin rear
drivers sharing a two-lobe response, with one side correcting both lobes and the
other one, gave a +3.9 dB R−L gap at 1140 Hz; adding the missing filter to one
side closed it to +0.1 dB. General pattern for any one-sided correction: change
one side, leave the other, and use the unchanged side's movement in the same
sitting as the uncertainty floor. A common elevation both sides share afterwards
is voicing, not matching — decide it at normal listening level.

**Rear-fill timing and level.** Rear fill should arrive BEHIND the front stage,
not with it: on top of the delay that makes the nearer rear speakers co-arrive,
roughly 10–20 ms later lets the rears add space while the precedence effect keeps
the image on the dashboard (use ~0 ms only when second-row listeners matter
more). Set its level by ear at normal listening level, not from a diagnostic
capture: start 6–12 dB under the front, raise it until it becomes audible as a
separate source, then back off 2–3 dB. Time a rear or centre against the ONE
front driver that plays most of the 1–4 kHz voice band (usually the midrange),
not against the summed front stage — a band-limited arrival of a sum is the
arrival of whichever driver plays earliest in that band.

## Preparing for EMMA Sound Quality judging

Checked against the [2026 competition manual and SQ judgebook](https://www.emmanet.info/competition/rules/)
on 21 October 2026. The SQ judgebook's body identifies Edition 2026 despite
stale PDF title/index metadata. Confirm which edition and recordings the event
uses. What the rules mean for a tune, and which command answers each item:

- **One judge, in the driver's seat.** Judging is "single seat": all scoring
  comes from the judge in the driver's seat (the right-hand seat in a
  right-hand-drive car), who may not move or re-adjust the seat. Tune that
  seat, with the seat where you will present it. Judges' heads are not your
  height: run the MMM a little higher and lower than your own head.
- **You suggest the volume; the cap is 80 dB** (unweighted, slow, on pink
  noise). Capture at the volume you will suggest.
- **Then the judge turns it up about 6 dB.** "Overall spectral balance at
  higher volume" is a full 30-point item in the 2026 matrix, and a system that
  cannot play 6 dB louder loses 12 points. Capture the same MMM at your volume
  and about 6 dB up (2-3 head-unit steps; check with an SPL meter), then
  `pipeline.py emma-volume --normal N.txt --loud L.txt`: it reports whether the
  capture reached +6 dB and which analysis band rises less or more. A
  `step_not_demonstrated` verdict does not prove the system cannot reach it:
  the knob increment may simply be wrong. An acoustic pair cannot distinguish
  compression, processing and capture variation; repeat a suspect result.
  `incomplete_coverage` cannot pass the full-band check. The rulebook's
  gain-structure hint applies: the head unit
  should use most of its range before an amplifier clips.
- **Tonal accuracy is four bands of 30 points**: sub-bass 10-60 Hz, mid-bass
  60-200 Hz, midrange 200 Hz-3 kHz, high 3 kHz up. Judges score the quality
  inside each band there, and the RELATIVE level of the bands under spectral
  balance; big differences between bands score lower than an average would
  suggest. `analyze` reports `emma_bands`: each band's level against the
  target (`median_db`, what spectral balance hears), its peaks and holes
  about its own level (`roughness_db`, a response-shape diagnostic), and the
  spread between bands. These are target-relative engineering summaries,
  not predicted judging points: MMM does not measure attack, distortion,
  stage depth or listening pleasure. A mistake around a crossover costs both bands either
  side of it, so junction work pays twice.
- **Imaging positions and focus (25 + 25)** in the 2026 SQ judgebook use
  electronic bass (20-500 Hz), electric guitar (60-1200 Hz), banjo
  (160-5500 Hz), vibraphone (200-5000 Hz), and triangle (2-20 kHz).
  Position uses tracks 2-6; focus uses tracks 7-11. `pipeline.py imaging
  --bands emma` summarises these overlapping instrument ranges, from
  left-only and right-only captures. Also inspect the default frequency
  bands: a broad average can hide opposing errors within one instrument's
  range. MMM supplies level cues only; establish position and focus by
  listening to the event's technical tracks. No output predicts points.
- **System noise costs up to 6 points**: hum, hiss, pops, anything not on the
  recording, judged on the zero-bit track (engine off unless the head judge
  announces otherwise for every car). Capture an RTA with the system off and
  one with it on playing silence at your volume, then `pipeline.py
  noise-check --off OFF.txt --on ON.txt`. Listen separately for turn-on pops
  and noise while changing volume or track.
- **The car is judged "ready for driving"**: windows, trunk and sunroof
  closed, no curtains or window covers. Capture that way.
- **Channel check**: tracks 2 and 3 verify left and right; a reversal gives
  you five minutes to fix it, once.
- The 2026 recording has new tonal tracks (the 2026 Tuning judge book names
  13 "Ocean Drive", 14 "One Fine Day", 15 "Coming Back to You", with track 16
  for spectral balance); listen to them on your own system before the event.

## MMM-first tuning: the short path for tone, bass level and L/R balance

When the user tunes from moving-mic RTA averages (MMM), each capture is
already a spatial average: do not ask for 3+ discrete positions, and pass
`--capture mmm` to `analyze`, `propose` and `refine` so the tools read it that
way. Extra `--positions` files are then REPEAT RUNS of the same tune, not
seats. **One run of each capture is the normal path** — every command works
from it: filters stay broad (Q <= 4), comparisons and verification use an
assumed resolution (0.25-0.3 dB), and nothing is rejected for repeatability.
A repeat run is optional: it replaces the assumption with a measured,
frequency-by-frequency repeatability, which then also screens out changes
too small to confirm. The one place a single extra capture pays most is a
close bass-setting comparison: repeat the baseline setting once (`--repeat`).
For one driver's seat, repeat the same compact movement around that driver's
normal head area. Keep the seat, mic aim, signal, playback volume and capture
duration consistent; a larger movement on the second run changes the sampled
listening area. Two runs are an uncertainty estimate, not statistical proof.
MMM has no phase, so delay, polarity, Phase angle and crossover phase are
chosen by comparing captures, never from one trace.

**Capture set (engine off, one session, nothing changed in between):**
REW RTA in a 1/N-octave mode (1/48 octave), never Spectrum mode; pink
periodic noise with its length matched to the FFT length; unlimited averages,
about 30 s per capture while moving the mic slowly through the head space of
the judged seat (ear to ear, forehead to headrest); the same mic calibration
file and the same mic aim every time; normal listening volume, nothing
touched between captures.

| Capture | What it unlocks |
|---|---|
| Full system (a second run optional) | tonal deviation; a second run adds local repeatability (`capture.repeatability`) |
| Left side only, right side only, both | `lr-match`, and `--cancel-check LEFT RIGHT BOTH` |
| Sub only, front midbasses only, sub + midbasses | bass level (`bass_balance`) and `--cancel-check SUB MIDS SUB+MIDS` |
| Ambient (generator off) | `--ambient`: bins under 10 dB SNR are excluded |
| Full system at each candidate bass delay / polarity / Phase | `mmm-compare` checks the handover against an unchanged measured midrange reference |

**Record the setup once, as a capture profile** (`--capture-profile
profile.json` on analyze/propose/refine/verify), e.g.:

```json
{"analyzer": "rta 1/48", "noise": "pink periodic", "fft_length": 65536,
 "sequence_length": 65536, "sample_rate_hz": 48000, "playback": "file",
 "test_file_sample_rate_hz": 48000, "test_file_fft_length": 65536,
 "window": "hann", "averaging": "forever", "rms_level_dbfs": -12,
 "mic_cal": "90deg", "mic_aim": "up", "seat": "driver", "engine": "off"}
```

It is checked against REW's signal-generator rules: pink noise with the RTA
and white with the Spectrum analyser; the periodic sequence length equal to
the FFT length; a test file made at REW's sample rate and FFT length; peaks
clip above about -6 dBFS RMS (periodic) or -12 dBFS (random). A rule broken
refuses the session. `playback: "file"` — pink noise played by the car's own
source while the laptop records — is a separate clock, which REW says needs
windowing and averaging/overlap set for it with periodic noise; the profile
flags that. Every report carries the profile id, so captures from different
setups are not compared by accident.

**What the tools now enforce for MMM:**
- *RTA mode.* A full-system tilt steeper than -2.5 dB/oct or rising faster
  than +1.5 dB/oct is refused by `propose`/`refine` (noted by `analyze`):
  Spectrum mode shows pink noise falling ~3 dB/oct and white noise in an
  octave RTA rises ~3 dB/oct, and voicing toward the target would tilt the
  tune the opposite way. With a valid capture profile recorded the refusal
  becomes a check-the-car note; otherwise `--accept-tilt` only if it really is
  the car. A single-driver capture is never refused: `refine` on a channel
  with a crossover inside 120 Hz–10 kHz, or `propose` with a narrow
  `--fit-band`, only notes that the check belongs on the full-system capture
  (a midbass solo low-passed at 2.6 kHz reads about −5 dB/oct on a correctly
  set RTA).
- *EQ policy.* With `--capture mmm`, every proposed band (propose) and every
  edit (refine) must change the response by more than the repeat-capture
  variation where it acts — max(0.5 dB, 2 x the local repeatability) — or it
  is not proposed: a re-capture could not confirm it. With a single run,
  filters are kept broad (Q <= 4) because nothing yet shows a narrow feature is
  real. A boost with no cancellation evidence (no phase, no `--cancel-check`)
  goes to `needs_trial` in propose and is not proposed by refine: write one
  alone, re-capture, and keep it only if `verify` confirms it.
- *One dip does not end the search.* The fitter tries the largest
  audibility-weighted deviation first. On an MMM capture, a dip whose boost
  fails the gate now blocks its region and the fit moves on to the peaks; it
  used to stop there, so a dip outranking a real peak left the peak uncut. On
  synthetic one-run cars this gave every car a correction and helped seats
  the fit never saw, with none worse.
- *No stacked boosts.* Any fit (sweep or MMM) could put two or three boosts
  on one dip (+7 dB into a narrow notch from one sweep). The whole cascade
  now stays within the +3 dB boost limit, and the extra boosts are listed in
  `rejected` with that reason. Expect at most one trial per dip.
- *Noise.* An RTA adds the background in, so a dip can read as filled.
  `--ambient` excludes every bin less than `--min-snr-db` (10) above it.
- *Cancellation without phase.* Where two halves measured together sum below
  the power sum of the halves alone, the dip is destructive summation; with
  `--cancel-check` a boost into it is BLOCKed (a dip both halves already have
  is not, and may be filled). The three captures must share one playback level.
- *Repeatability.* Two or more runs give bass, midrange and treble summaries
  plus a frequency profile in `capture.repeatability`. Pass that whole object
  to `predicted_vs_measured(..., repeatability=profile)` after re-capture:
  each changed filter is judged against uncertainty in its own region.
  Missing coverage is inconclusive. `verification_noise_db` remains a
  conservative scalar fallback; a quiet midrange must not certify noisy bass.
- *L/R protection.* `lr-match --target <curve>` (default: the supplied in-car
  target) proposes a cut only where the louder side also exceeds the target,
  matching improves, and target error improves without a new deficit. Both
  sides share one fixed target anchor after any proposed trim. A healthy side
  is not cut to copy the other side's dip. `unresolved_regions` need diagnosis
  and listening, not forced matching. A proposed trim is still a listening
  decision; broad response differences can resemble a level offset.
- *Bass selection.* `mmm-compare` defaults to `--objective balanced`: judge
  target error in the handover relative to `--reference-band 300 3000`, with
  guards against worse shape, new holes/humps and significant output loss.
  Use full-system captures so that reference contains real, unchanged output;
  never use a sub-only stopband or ambient noise as the reference. For another
  comparison band, explicitly select an unchanged reference outside it. If
  none is measured, balanced/level cannot choose a winner; `--objective shape`
  can compare band shape only and cannot establish bass-to-midrange balance.
  `--objective level` remains available but must pass the tonal guards too.
  More output alone does not prove better sound or correct phase.

**After every write: `verify`.** `pipeline.py verify --report <refine or
propose JSON> --before <the captures it came from> --after <re-captures>
--dsp-rate 96000` judges each changed filter against the repeatability of
both the before and after runs in its own region, reports the target error
before and after, and says per band: keep (confirmed), rethink (the change did
not show up), re-capture (partly landed), or settle by blind A/B
(inconclusive). `--bands F,Q,G ... --old-bands ...` when only some of a
report's edits were written.

**Voicing last, by ear.** Once the corrections are verified, `pipeline.py
voice-variants --afpx tuned.afpx --out-dir v --bass-channels <sub+midbass>
--treble-channels <tweeters> --bass-db -1 1 --treble-db -1 1` builds one-shelf
variants (low shelf on the bass channels, high shelf on the tweeters, in their
end shelf slots; an existing shelf's gain is adjusted instead). It shows the
edits first and writes only with `--confirm`. Compare each variant against the
current tune with its `ab_make` line — blind, level-matched, at normal volume —
and keep only a repeatable preference; then record the voiced target for the
next session. A variant that measures further from the curve but is preferred
blind is a voicing choice, and the right one.

**Order.** Check the tilt and voicing (§Voicing,) → set the bass LEVEL
(`bass_balance`; a trim or sub amp gain, not bells) → choose the sub/midbass
setting with `mmm-compare --objective balanced --repeat <baseline-repeat>`
over the handover band, using the chosen target and unchanged reference →
match L/R with `lr-match --target <same-target>` (only target-supported cuts) →
`refine` (or `propose` on a channel with no PEQ yet) with
`--capture mmm --cancel-check ...` → blind, loudness-matched A/B (§Judge by ear
only at matched loudness,) → re-capture and `pipeline.py verify` with the
same capture set → `voice-variants` blind A/B last. `mmm-compare` measures repeat disagreement
from the difference BETWEEN the repeat curves, not the difference of their
target-error scores (two different curves can have equal scores). It keeps
the current setting unless a candidate clears twice that RMS disagreement,
the engineering floors of 0.25 dB (level) / 0.1 dB (shape or target error),
and the tonal guards. These thresholds are not universal audibility limits.
Every winner is provisional: repeat the winning setting with the same path
and source level, rerun the comparison, and confirm by listening before
keeping it. MMM supports tonal decisions; it cannot prove arrival time,
phase alignment or image position. After changing the handover, recheck bass
level before further EQ.

**For a close final touch-up, capture A1 → B1 → B2 → A2.** A is the retained
baseline and B is one candidate. Keep the target, playback level, mic path
and all other settings fixed. Return to A for the last capture to expose
drift. Feed both repeats to the comparison, for example for a bass handover:

```bash
python scripts/pipeline.py mmm-compare --captures current=A1.txt trial=B1.txt --baseline current --repeat A2.txt --candidate-repeat trial=B2.txt --band 40 160 --reference-band 300 3000 --target target.txt
```

Choose the trial/reference bands for the actual change: the reference must
be measured, unchanged, and outside the trial. The command keeps the
original baseline's target anchor, checks both candidate runs against both
baseline runs, uses the worse repeat disagreement to set the candidate's
resolution, and applies tonal guards to every comparison. The reported
`improvement_vs_baseline` is the smallest improvement across these pairs.
An identical re-export cannot count as an independent repeat. A
`repeat_supported` result still needs matched-level listening; four captures
are not a statistical confidence interval or proof that a judge will prefer
the change. If results disagree, retain A and investigate. This is optional
confirmation for small changes, not a new prerequisite for ordinary MMM.

## Single-run MMM intelligence: what one capture set can still tell you

An MMM capture is a power average over the head area, so it was treated as
able to say only "the average level per band". It says more. Its header
records how it was captured; its stopbands record the noise the moving mic
made; three captures the cancel check already asks for hold the head-area
cross term; REW's peak trace holds the spread; and a recording of the pass
holds every block. The commands below read those. None of them writes a tune.

### Capture audit: read what every capture already says

Run `pipeline.py capture-audit --captures <files or a whole .mdat>` before
analysing an MMM set. REW writes into every export and `.mdat`: the RTA
resolution, FFT length, window and number of averages; the mic, its gain
setting, input channel and input volume; the capture time; and calibrated
levels (Input RMS, dB A, dB C, 22 Hz-22 kHz unweighted, above 22 kHz). The
audit turns those into checks per capture and across the set:

- **Settings.** Same mic serial and cal file, RTA resolution, FFT, window and
  export smoothing across anything compared. A set that mixes them is
  compared like with like or re-exported; smoothing one file of a cancel-check
  triple changes its cancellation map. (Real set: one tweeter exported at
  1/48 among eight unsmoothed files.)
- **Length.** First FFT plus one hop per further average, at REW's overlap
  for that FFT (87.5% at 64k): 32 averages is under 7 s. Under about 20 s the
  pass has not covered the head area evenly.
- **Movement noise.** Input RMS minus the 22 Hz-22 kHz and >22 kHz parts is the
  energy below 22 Hz. In an MMM capture it is mic handling, cable and air
  movement, and its tail fills the lowest bass bands. As loud as the signal
  is a problem; then the bass of that capture is not evidence.
- **Mic headroom.** Input RMS plus pink noise's ~12 dB crest against the
  mic's clip point (forum-reported for the UMIK-1: about 115 dB SPL at 18 dB
  gain, 121 dB at 12 dB). A sub at 108 dB SPL RMS clips the mic's peaks.
- **Infrasound.** A sub capture with as much energy below 22 Hz as in band is
  reproducing infrasound: check for a subsonic high-pass.
- **Playback level in a triple.** The "both" capture sits near the power sum
  of its halves in dB A (dB C too, unless movement noise dominates it).
  Otherwise the volume moved and the triple is not a cancellation map.
- **Stopbands.** Two octaves past a solo's passband edge the capture should
  be floor. Within 20 dB of the passband there means another driver still
  playing (below a high-pass) or rattle, distortion or interference (above a
  low-pass). A low-passed solo whose level rises towards 20 kHz, or sits well
  above the set's other low-passed solos there, carries interference or
  system noise in the chain.
- **Order and sittings** from the capture times (a gap over 20 minutes starts
  a new sitting).

The report ends with a table of what each file can feed (tone EQ above a
measured noise limit, bass decisions, comparisons, the cancel check, absolute
SPL) and why. `analyze`, `propose` and `refine` record the same automatic
capture profile (`capture.auto_profile`) and add a note when the captures
they were given differ in any of those settings; only what the files cannot
say is left to ask: the noise type, mic aim, engine state, seat and path.

### The moving-mic noise floor

A static ambient capture measures the cabin with the mic still. Handling and
air noise exist only while the mic moves, so they are missing from it. A
band-limited solo's stopband is measured during real movement: the tweeter
solo two octaves below its high-pass is the moving-mic floor for the bass.
Pass the session's solos as `--noise-floor` (analyze, propose, refine; also
`coherence --floor` and `xo-check --floor`). The highest floor per frequency
gates the data, combined with `--ambient` when both are given. When two
twins' floors differ by many dB (11-14 dB at 20-100 Hz between two tweeter
solos of one real set), a left/right difference there is noise, not the
speakers: the audit says so.

### Summation coherence from the cancel-check triple

From A, B and A+B at one playback level,

    rho(f) = (P_AB - P_A - P_B) / (2 sqrt(P_A P_B))

is the head-area average of the cosine of their phase difference (`pipeline.py
coherence`; `analyze` adds it to each `--cancel-check`). Near +1 the parts add
coherently wherever the mic went: delay and polarity change the tone there.
Near 0 they add as a power sum: alignment cannot change the tone (it can
still move the image), so the tonal fix is EQ or level. Below 0 they cancel
on average: polarity or delay before any EQ, and never a boost. It is
reported only where the parts are within 10 dB of each other and, with a
floor, 10 dB above it; |rho| above 1.1 is impossible at one level and marks
captures that do not share a level, or noise.

### Four-capture MMM alignment

With B delayed by tau, `P(tau) = P_A + P_B + 2 Re(C e^{j w tau})`, where
`C = <a b*>` is the head-area cross-spectrum. The triple gives Re(C); one
more capture with a known extra delay tau1 on B gives Im(C). With C,
`pipeline.py mmm-align` predicts the head-area result of every delay, polarity
and (with solos) gain on B, and ranks them.

1. Capture A alone, B alone, both, and both again with tau1 added to B's
   delay in PC-Tool (a quarter period at the band centre: about 3 ms for an
   80 Hz junction). Undo tau1 afterwards. The flip form needs no solos: both,
   both with B inverted, and those two again with tau1 (`--sum --diff
   --sum-delayed --diff-delayed`).
2. `mmm-align ... --tau1-ms 3 --band 50 130 [--dsp-rate HZ]` gives the best
   change, how much it gains over the current setting, the worst bin, and
   the head-area coherence.
3. A `candidate` must be confirmed by one capture of it against a repeat of
   the current setting (`mmm-compare --repeat`) before it is planned, and then
   it goes through the normal phase-only plan: the user sees it in ms and in
   samples at the confirmed rate, and no EQ joins it.

Simulated on an image-source cabin (10 random cabins, each capture on its own
random path, 0.15 dB RTA noise): at an 80 Hz sub/midbass junction the best
setting was worth about 2.1 dB in the handover band and the four captures
landed within 0.07 dB of it on average (flip form 0.05 dB). Above a few
hundred Hz the field decorrelates across the head (coherence about 0.3 for
L/R mono at 300-1200 Hz, 0.2 at a 2.5 kHz mid/tweeter junction) and the
method honestly finds little to gain: alignment there is an imaging decision,
judged by ear and by timed sweeps, not a tonal one. Real-car confirmation is
still to come.

### Bass stability from the peak trace

REW's RTA keeps a peak trace, and "Save both" saves it beside the average.
From one run, peak minus average per frequency tracks how much that frequency
changes across the head area below 250 Hz (simulated r about 0.8 against the
true spread, 0.7 against run-to-run change; about 0.1-0.2 above 250 Hz, so it
is not used there). `pipeline.py stability --average AVG --peak PEAK` maps
it; `--peak-trace PEAK` on a single-run `propose` or `refine` uses it as the
confidence weight, so a stable modal peak can be cut with confidence and a
null that moves with the head is left alone. The scale is relative within the
run (the gap grows with the number of averages). Set peak hold to hold for the
whole capture with no decay, and audit the capture first: a door thump lifts
the peak.

### What the DSP actually applied: RAW, XO, EQ

Captures of one driver at one seat, path and level with its crossover and EQ
bypassed (RAW), crossover on (XO) and both on (EQ) cancel the cabin in their
differences: XO minus RAW is the crossover the DSP applied, EQ minus XO the
PEQ. `pipeline.py xo-check --raw --xo [--eq] --afpx T --channel N --dsp-rate
HZ` fits each section (Linkwitz-Riley or Butterworth, slope, corner) and
compares it with the tune (or with `--hp/--lp/--peq` for a DSP this skill
cannot read). Corners are compared at their -6 dB points, because a
Butterworth corner is its -3 dB point and a Linkwitz-Riley corner -6 dB. A
section showing no attenuation where the stated filter is already 3-12 dB
down is `not_applied`. Pass `--floor`: movement noise in an XO capture's
stopband otherwise reads as a shallower slope. The report records the
PC-Tool characteristic index beside the measured family, which is how the
unverified HPi/LPi codes get confirmed. It never writes a crossover; a
section that differs is set by hand in PC-Tool.

### Voicing for the listening level and the road

**Listening level.** The ear loses bass faster than midrange as the level
drops. `pipeline.py listening-level --capture SYSTEM [--volume-offset-db X]`
takes the capture's calibrated dB C (or `--listening-db`) as the loudness
level and returns the ISO 226:2003 contour difference against the level the
target is assumed voiced at (`--reference-phon`, default 83), the low shelf
that matches it, and its half-strength version. It also lists the
third-octaves the capture itself played below the hearing threshold: one real
full-system capture at 64 dBA put 20-31.5 Hz below it, so bass decisions
from it covered sound nobody heard. The shelf is a taste option for a blind,
level-matched A/B (`voice-variants`, `ab-make`), never a correction. Measure
near the listening level too: it also beats the movement noise.

**Road noise.** A capture at the seat while cruising, system off, **mic held
by a passenger**, is the masking spectrum. Bands where music at the listening
level sits near or under it lose loudness. `pipeline.py road-noise --noise
ROAD --music SYSTEM` estimates the loss per band from the noise's share of
the band power (a simplification of partial loudness) and fits a broad low
shelf, capped at +4 dB. Write it with `voice-variants` as a separate file for
a second preset and choose between the presets blind, on the road, switched
by a passenger or the DSP remote at a stop — never by the driver while
moving. It rebalances what the noise masks; it is not a reason to play louder.

### Learning the listener's voicing from blind A/Bs

`voice-variants --confirm` records each variant's knob values in
`voice_variants.json`; `ab-result` logs each blind choice. `pipeline.py prefs
--log ab_log.json --base TUNE` fits a paired-comparison (Bradley-Terry)
model with a concave quadratic preference per knob (bass, treble, presence)
and returns the preferred value with an 80% interval, and the next variant
pair to test (around the least certain knob). Values outside the tested range
are extrapolations; fewer than about 20 decided choices give wide intervals.
The preferred values feed `--voice` as the taste layer on the target.

### Frame-level MMM: one run that measures its own repeatability

REW shows the mean of a capture's FFT blocks and discards them. Kept, the
blocks of one run give the spread across the path, split-half repeatability
(first half of the path against the second), a robust mean without handling
bumps, the peak trace and the capture length. Two read-only sources:

- a WAV recording of the mic during the pass, from any recorder:
  `pipeline.py frames --wav PASS.wav --cal MIC_CAL.txt --out-dir D` (REW's RTA
  can process the same WAV with Open WAV as a cross-check of the average);
- REW itself: `rew_api.py rta-frames --seconds 30 --out frames.json` with RTA
  averaging set to None polls the captured data by GET (each new sample count
  is one block; no subscription is registered), then `frames --api-frames`.

It writes mean, robust, peak and half-path text exports. `--positions HALF1
HALF2 --capture mmm` then turns on the repeatability-gated paths from one
capture: verify thresholds, `mmm-compare` resolution, Q above the single-run
cap where the response is stable. Each half covers half the path, so the
figure is conservative by about sqrt(2). Without `--spl-offset-db` levels are
dBFS; the mic cal file's response correction is applied, its sensitivity not.

### The skill's own test signals (experimental)

`pipeline.py test-signal --kind ... --wav-out SIG.wav` writes a periodic
signal with a known spectrum and a silent lead-in; play it from the car's
USB source and record the mic through the whole file; `signal-analyze --wav
REC.wav --spec SIG.wav.json` corrects the clock difference between player and
recorder (to a fraction of a ppm in simulation), takes each period as one
rectangular-window FFT, and reads every tone as a complex transfer value.

- `multitone-empty` leaves every third bin empty: the empty bins measure
  noise plus intermodulation at the playback level during the capture, and
  the lead-in measures the noise alone with the same movement. In simulation,
  1% cubic distortion lifted the empty bins 23-36 dB over the floor.
- `lr-interleaved` puts left and right on alternate bins: one capture gives
  both sides, their level difference per band, and the L+R sum predicted with
  phase at the same positions (within 0.1 dB of the true comb in simulation).
- Coherent averaging gives each band's field coherence across the path.

Limits: mic motion Doppler-shifts tones into neighbouring bins, a quarter bin
near 210 Hz at 0.3 m/s; above `doppler_limit_hz` empty-bin readings are
reported as leakage, never as distortion. Everything here is checked in
simulation only, and none of it replaces a timed sweep for delays.

## Finishing touches after the curve

A target curve is a long-term average. Once the system sum sits on it, what
listeners and judges respond to is imaging, the last broad peaks, how the bass
joins the stage, and taste. `pipeline.py finish` reports each of these from the
captures it is given and writes nothing; every finding names its fix and its
evidence level.

- **Cut residual broad peaks, not dips.** A peak is detected where an equal dip
  goes unnoticed (Bücklein 1981), and low-Q resonances are audible at small
  amplitudes (Toole & Olive 1988). `finish` lists peaks of the 1/6-octave
  deviation above its two-octave trend, each with a fit band for `propose` or
  `refine`, which validate the cut. Dips stay listed to leave alone until the
  cancel check or the boost gate says they can be filled.
- **One instrument, one place.** EMMA scores an instrument heard in two places
  as zero. `finish` finds the image position (pull: +1 fully left, −1 fully
  right; 16 dB or 1 ms is a full shift) in third-octave slices of each EMMA
  instrument band: the mean is the centre, and the spread is the focus (up to
  0.25 focused, up to 0.5 loose, above that smeared). A band can be centred on
  average while its instrument is smeared. MMM gives the level cue only; timed
  sweeps add time. Correct the hot side at the widest-swing slice only
  (`stereo-propose`, `lr-match`), then confirm by ear.
- **Keep the two sides phase-symmetric.** A low-frequency phase difference
  between the sides moves the image (Møller et al. 2007: from about 30-35 µs);
  the same phase on both sides is much less audible. A one-sided all-pass or
  delay in the imaging band is an image decision, never a tonal one.
- **Height is set by the crossover, not delay.** There is no precedence effect
  in the vertical plane, and vertically separated drivers sharing the 1-4 kHz
  octaves make height erratic (Wallis & Lee 2015). Low frequencies image near
  ear height wherever the speaker is; high ones near the speaker that plays
  them. So the high-mounted driver should own everything from a few hundred
  hertz up: `finish --afpx --low <door channels> --high <dash/pillar channels>`
  flags the overlap, `probe` models a new low-pass, and the user sets it in
  PC-Tool. A broad +1-2 dB near 8 kHz (the band heard "above") is a blind A/B
  height variant, not a correction.
- **Focus or spaciousness, chosen on purpose.** Reflections (windshield, side
  windows, a glass roof) and decorrelation widen and brighten the sound but
  blur the image; absorption focuses it (Kaplanis et al. 2017). Competition
  scoring rewards focus.
- **Keep the sub hidden.** A sub is detected from about 80-120 Hz depending on
  placement. What gives it away is output above that, rattles and harmonics:
  `finish --sub` checks output above 120 Hz, and a `.mdat` sweep adds the
  harmonics against Fielder & Benjamin's pure-tone limits (H2 about 3%, H3 about
  1%, higher about 0.3%, at the level measured). Its timing is `mmm-align`,
  `junction` or `bass-trials`.
- **Bass ringing rarely limits a car, but check it when sweeps exist.**
  Fazenda, Stephenson & Goldberg 2015 put the audible modal decay with music at
  0.51 s at 63 Hz falling to 0.12 s at 250 Hz; `finish --ir` compares each
  third-octave against it, and calls a band whose decay is no longer than the
  analysis filter's own unresolvable (and far under the limit).
- **Voice to the listener.** Preferred bass and treble differ by many dB between
  listeners (trained listeners choose less of both), so the last tonal word
  belongs to a blind, level-matched A/B (`voice-variants`, `ab-make`, `prefs`,
  `listening-level`).

## Refine the tune you have before adding to it

After the first session, every measurement is taken THROUGH a tune that
already has filters in it. `propose` fits new bands to whatever the system now
does, so run on a tuned car it can only stack more filters on top: it cannot
see that an old cut is now digging a hole, and each extra band near a
crossover moves phase that was aligned earlier.

`pipeline.py refine --afpx tune.afpx --channels N [N...] --dsp-rate 96000
--positions ... --target ...` starts from the bank the measurement was taken
through. For every PEQ inside the channel's passband (kept 1/3 octave inside
its crossovers) it tries removing it, halving it, and re-fitting it in place;
where free slots and a real residual both exist it may add one band. Every
prediction is the measurement + cascade(new bank) - cascade(old bank), so a
measured filter is never applied twice. The low-level API can re-anchor in
level so removing a cut in the anchor band is not mistaken for a broadband
error. A move is kept only when it improves the mean score across positions
without the worst position getting worse; removal wins near-ties, because a
filter that is not earning its place is a cost. An empty edit list means the
current bank already earns its place — that is the result, say so.

**Level is anchored inside the judged band, never at 300–3000 Hz.** A single
driver's solo is mostly stopband, and the session's 300–3000 Hz anchor lies
wholly outside a tweeter (above it) and a sub (below it). Anchored there, the
whole passband reads as one big level error and the fitter "fixes" loudness
with bells: on a real car a tweeter solo scored 14.7 dB and a sub 35.8 dB
before any edit, and the proposals were −15 dB cuts at Q0.5. Refine now
anchors each candidate inside the band it judges, so it corrects shape only;
the channel's level stays a separate decision (output trim, level matching).
A sub channel (low-passed below 250 Hz) is judged from 20 Hz rather than the
general 60 Hz floor — from 60 Hz an 80 Hz low-pass leaves a 60–64 Hz sliver.
`propose` does the same when an explicit `--fit-band` misses the 300–3000 Hz
anchor; it decides from the band you give, not from the trace, because an
in-car solo's stopband is often filled with road noise louder than the driver
(measured: 50 dB at 25 Hz on a tweeter solo playing 38 dB in its passband).

Several channels are refined together only when they carry the SAME bank (a
left/right pair measured together); unequal banks need their own solo
measurements. Its `plan_edits` address existing slots (`G: 0` for a removal),
`comparison` gives the loudness change for the listening test, and
`verify_with` is what `predicted_vs_measured` needs after the re-measure.

## Held-out by sitting, not by position

Leave-one-position-out asks whether a band helps a mic spot it was not fitted
on. Positions captured in the same sitting share the seat position, the mic,
the cabin temperature and that day's noise, so withholding one of them leaves
its siblings in the fit and the check flatters the proposal. Across sittings
on a real car, tone below 300 Hz moved by up to 0.9 dB with nothing in the
tune changed. Label every `--positions` file with `propose --sittings` (one
label per file, e.g. `8aug 8aug 10aug 10aug 12aug`) and each fold withholds a
whole sitting and scores the mean over its positions. Three distinct sittings
are needed; with fewer, `propose` fits jointly and says no band carries a
held-out check. When judging edits by hand, score each sitting separately and
keep only what helps every sitting — a band that helps the mean but hurts the
latest sitting is fitted to the past car, not this one.

## Vehicle guards: what this car taught, enforced every time

Some facts about a car are learned once, from evidence no single measurement
shows, and must hold for every later proposal. Record them as `guards` in the
session sidecar (`session save`); `refine` reads them from the `--afpx`
sidecar and `propose` from `--session-tune` (with `--channels` to pick
channel-specific zones). They describe the car, not the file, so they stay in
force after a tune edit.

```json
{"guards": {"max_boost_q": 3.0, "no_boost": [
  {"lo_hz": 380, "hi_hz": 540, "channels": [2, 3],
   "reason": "seated-listener body-reflection null: MMM shows it, a fixed mic reads it as a fixable dip"},
  {"lo_hz": 4400, "hi_hz": 4900, "channels": [0], "reason": "FL tweeter physical notch"}]}}
```

A guard blocks a BOOST whose own response rises more than 0.25 dB anywhere in
a zone on a listed channel (`channels: null` = every channel), and any boost
above `max_boost_q`. A new or deepened cut is never blocked. `refine` also
judges every edit to an EXISTING filter by its net transfer (new minus old):
relaxing, re-centring, narrowing or removing a cut can lift a zone as surely
as a boost, and narrowing a kept boost can pass the Q cap. On a real car a
tweeter-cut refit that was *deeper* still lifted that tweeter's physical
4.4–4.9 kHz notch by 0.45 dB; it is refused now. Blocked bands land in `propose`'s `rejected` with the guard's
reason; `refine` drops the move and names it in `notes`. Every zone needs a
reason — the physical fact it protects — so a later session can tell a guard
from a habit. Add one only from evidence: an MMM-vs-fixed-mic disagreement, a
null that moves with the head, a notch present in every sitting.

## Judge by ear only at matched loudness, blind

A louder version of the same tune wins a quick comparison even when it is
worse, and most good corrections are cuts — so an unmatched A/B tends to reject
exactly the changes that helped. Knowing which version is playing biases the
choice the same way. Both are cheap to remove:

1. Take the predicted loudness change from `refine` (`comparison`) or
   `propose` (`prediction.loudness_change_db`) — positive means the candidate
   is louder.
2. `pipeline.py ab-make --a current.afpx --b candidate.afpx --loudness-db X
   --out-dir ab1` writes `X.afpx` and `Y.afpx` in random order and trims the
   louder one on every channel through the normal verified apply path
   (comparison copies only; the originals are untouched). It refuses until the
   user has seen the trim and you pass `--confirm-trim`.
3. The user loads X, Y, Y, X (and repeats) at their normal volume on two or
   three short familiar clips, noting a preference per pair — ideally with
   someone else loading the files.
4. `pipeline.py ab-result --key ab1/.ab_key.json --choices ...` reveals which
   was which, gives the chance probability, and appends to `ab1/ab_log.json`.

Six or more decided choices are needed before a preference means anything. A
candidate that measures better but is not preferred blind is not kept on the
strength of the measurement; one that is preferred blind but measures worse
at the other positions is a voicing question, not a correction.

## Crossover what-ifs: modelled, never written

This skill never writes a crossover, but a poorly placed corner or slope is one
of the most audible faults in an active system, and saying nothing about it
leaves the biggest lever unused. The exports were measured through the
current crossover, so a candidate is modelled like any other change:
multiply by H_new / H_old. `probe` takes it as a change on a driver:

```json
{"crossover": [{"kind": "hp",
                "from": {"family": "LR", "slope_db_oct": 24, "hz": 3500},
                "to":   {"family": "LR", "slope_db_oct": 24, "hz": 2800}}]}
```

`from` must be what PC-Tool shows for that channel — read it from the UI, not
inferred from the file (only one characteristic index is confirmed). Linkwitz-
Riley and Butterworth are modelled; Bessel and Self-define are refused because
their Helix normalization is unverified. Below the old corner the export is
mostly stopband, so the lift is capped at 12 dB and reported as
`crossover_lift_db`: above ~6 dB the prediction is a direction, not a number.
Judge a crossover candidate at BOTH of each driver's junctions, with `pairs`
for left/right balance and `positions` for 2-3 head positions — a better
handover on one side only moves the image (`tradeoff`), and one that helps at
one spot only is not an improvement. Lowering a high-pass raises that
driver's excursion; check it (`hpf_excursion_risk`) before the user tries it at
volume. A candidate the user likes is set by hand in PC-Tool, then re-measured
and compared blind like any other change.

## Bass is a level decision before it is an EQ decision

The sub-to-front balance is one of the most audible properties of a car tune,
and when the whole 25-80 Hz region sits above or below the anchored target it
is a LEVEL question: bells fitted to a region-wide offset spend filters and
phase on what one gain change does better. `analyze` and `propose` report
`bass_balance` (median anchored deviation per bass band and a verdict) and say
so in the notes. Output trims only cut, so a light low end is raised with the
sub amplifier's gain (or by lowering every other channel equally) — after
confirming at the sub/midbass junction that the deficit is not a cancellation.
`propose`'s default fit band starts at 60 Hz; a deviation below it is now
named in the notes instead of passing silently — fit the sub region on the sub
measurement with `--fit-band` if it is shape, not level.

When a sub/midbass change is probed, give the probe both front junctions it
touches (sub–left woofer and sub–right woofer), the woofer–tweeter junctions
the woofers also own, `pairs` for left/right, and `positions`: a change that
improves the bass handover but moves the vocal image or helps at one head
position only is not the improvement it looks like.

## Stopping is a valid, and often correct, outcome

A converged tune does not owe you another filter just because a scan still shows
non-zero deviations. By the end of a long project, remaining "candidates" are
often sign-alternating fine structure, source-local physical features unsuitable
for boost (see above), crossover-region interference without clean magnitude
authority, or changes smaller than the measurement's own repeatability — none of
which are actionable, however real they are.

**Real case (2026-08-10):** after a full-spectrum common-mode scan turned up seven
candidate regions, six were closed on inspection (cabin cancellation, physical
driver notches, or no stable feature) and the seventh (100 Hz) had already been
addressed. The correct output was not "propose the eighth filter" — it was **"no
further DSP change is justified from current evidence; the remaining open item is
a listening decision, and one item is physical, not DSP."** A tuning session that
converges to "stop" has succeeded; treat refusing an unsupported filter as an
equally good outcome as finding a good one, and say so explicitly rather than
manufacturing a marginal candidate to have something to propose.

## Evidence-constrained audible tuning

For the current pipeline reference model, stereo proposals, measured clean-output
limits, bass trial selection and actual-system voicing matches, read
`audible_tuning.md`. Pipeline refinement now uses `fixed_anchor=True`: the baseline
passband reference is held through every candidate and final judgement. The low-level
legacy shape-only option is not the pipeline default.
