# Tuning methodology — how to decide what to fix

This is the judgment layer. The scripts give you numbers; this tells you what they
mean and which action type each problem calls for. The overarching bias: **classify
before correcting, and prefer doing less.**

## Contents (line numbers, for offset reads — this file is long; jump straight
to the section you need instead of reading it whole)

- Measurement method selection — sweep vs Moving Mic (MMM) — line 47
- Sweep capture setup — line 131
- Beyond magnitude — decay (time-domain) and distortion axes — line 178
- Deviation analysis — line 258
- Analysis traps (anchoring, causal A/B, anchor sensitivity, sum-vs-solo,
  coherence wobble, stale decoded fields, imaging, sub coupling, ties,
  stable-near-zero, duplicates) — line 325
  - Traps from the Alpine session: null-averaging read as level, judging
    inherited EQ, flat interference offsets, MMM level comparability,
    fractional-octave smearing, zero-band fits, crossover skirts — line 536
- When the answer is physical, not electrical — line 615
- Voicing — the most audible decision — line 689
- Classify the problem (the core skill) — line 720
  - The interference audit — line 739
  - Two checks before trusting a proposed EQ band (+ out-of-band skirts) — line 747
  - Minimum-phase / EQ-ability — line 780
  - Quantify single-position phase reliability — line 787
  - Multi-position variance — line 827
- The crossover action-ladder — line 865
- Shelf cookbook (incl. judging a shelf emulation) — line 926
- All-pass cookbook — line 959
- Imaging (incl. level-vs-timing for geometry, within-pair delay) — line 1002
- Restraint (incl. why fixed-point summation optima don't survive MMM) — line 1093
- Verification & honesty — line 1151
- REW's IR-delay estimator locking onto the wrong cycle on a band-limited driver — line 1209
- Recovering per-channel L/R responses from an N=L+R / V=L−R pair, no solos needed — line 1240
- When `polarity_delay_search` says "nothing to gain," run `delay_sweep` (and how this was actually found) — line 1282
- Bracket every A/B write A→B→B→A, and anchor on a band the write can't touch — line 1340
- Why a system-sum scorecard is nearly blind to L/R channel imbalance (with the math) — line 1376
- Extracting distortion/coherence from a REW `.mdat`, and listening-position THD traps — line 1403
- Electrical-vs-measured decomposition must be tune-matched, and may not be
  recoverable at all — line 1441
- Width/Q from a plot: pick one definition and don't switch mid-analysis — line 1463
- A filter's benefit must clear the untouched-channel drift floor, not just be positive — line 1480
- Nearfield-vs-seat shape comparison as a cheap cancellation test — line 1498
- Common-mode (System Sum vs target) is a first-class objective, not a fallback — line 1517

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
delay/polarity/crossover/APF work. MMM — engine off, at or near the user's
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
  actual remedy: an ungated capture, or `complex_vector_average` across
  several mic positions (see below) for that range instead.

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
the frequency domain plus an envelope gives per-frequency decay time. Compare
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

Five more failure modes caught live (2026-07-14) alongside the anchoring trap
above. Each produced a plausible, structured-looking answer that was still wrong —
that's what makes this class of error dangerous: nothing about the *output* looks
broken, only the number underneath it.

**A single-channel cut changes the L+R SUM by only about half its own value.**
Cutting one mid channel by −2 dB drops the summed pair by roughly −1 dB, not −2 —
the other, unchanged channel still contributes to the power sum
(`10*log10(10**(La/10)+10**(Lb/10))`). Never predict a combined-response change
equal to a one-sided filter's own gain. This is also why a one-sided excess (one
channel hot at some frequency) can't be fully flattened in the sum without
over-cutting that channel and wrecking L/R balance — the honest trade is to correct
imaging and accept a partially-reduced sum bump, not chase the sum to zero with an
asymmetric cut.

**Fix the SUM where the sum is wrong, not where a single channel's solo dips.** A
per-channel solo can dip at a frequency where the *summed* response is already
flat, because the other channel fills it. "Fixing" that solo's dip with a boost
then pushes the SUM into a shoulder peak it didn't have before. A real case:
lifting one channel at 1150–1300 Hz (where that channel's own solo dipped) created
+2 dB sum shoulders, because the sum there was already flat — the dip was real but
irrelevant to what's actually heard. Decide tonal corrections from the summed
response; use a per-channel solo only for imaging/imbalance calls, never as the
thing you're flattening.

**Near a crossover, the summed response can wobble session-to-session with no
EQ cause — that's coherence, not level.** Where two channels sum with a
phase relationship sensitive to mic position (a few mm move is a real phase
shift around 800 Hz-1 kHz), the SUM can swing several dB between otherwise
identical repeat measurements while each channel's own solo stays put. A real
case (2026-07-31): confirmed −1.2 dB per-channel solo cuts near 800 Hz produced
only a −0.35 dB sum change, and an untouched neighbor band (1000 Hz) swung
−3 dB between two same-evening sessions with no filter written anywhere near
it. Don't treat a sum deviation in a crossover-adjacent band as actionable from
a single MMM pass — require it to persist across independent sessions (see
Restraint) before writing a fix; a coherence wobble won't repeat, a real
deviation will.

**For L/R balance, compare ABSOLUTE inter-channel level — never each side
self-normalized against its own reference.** Normalizing each channel to its own
target/baseline before comparing "how scooped is each side" can hide or invert the
real difference — this is a distinct trap from the signed-median blind spot
`tune_scorecard`'s `_abs_rms_db` fields catch (Verification & honesty, below); this
one is about which TWO things you're differencing, not how you summarize the
difference. A real case: an own-reference-normalized comparison said one side
needed MORE presence lift; the absolute FR−FL difference showed that side was
already the louder one at 1 kHz, so the proposed lift would have pushed the image
further off-center, not fixed it. `lr_match_report` (Imaging, below) already does
this correctly — raw FR−FL, not two independently-normalized shapes — use it
rather than reconstructing the comparison by hand.

**Sub level couples to the low-mid correction — don't set it from the sub solo in
isolation.** The sub's needed gain depends on the mid/low-mid level it sums against
at the crossover. After cutting a low-mid excess, the sub needs LESS boost to stay
balanced than it did before that cut. Two otherwise-careful analyses of the same
tune disagreed by 1.5 dB on sub gain purely because one measured relative to the
mids before the low-mid cut and one after — both were internally consistent, only
one matched the tune actually being proposed. Model sub and mids together against
the same proposed state, and treat the final half-a-dB or so as a by-ear voicing
call, not a number precise enough to compute past that point.

**When two models disagree about deviation-from-target, arbitrate with an
anchor-independent SHAPE test.** Absolute deviation numbers depend on each model's
normalization/anchor choice, so two internally-correct models can report
contradictory deviations indefinitely. Local shape cannot: reference every value
to a nearby in-band frequency — `delta(f) − delta(f_ref)`, e.g. f_ref = 1300 Hz
for a presence-region dispute — for BOTH the required target delta and each
candidate tune's delivered change. Any model must agree on those numbers, so the
disagreement collapses to checkable arithmetic. A real case (2026-07-17): two
analyses deadlocked over a Harman re-voicing ("your file overshoots +2.9 dB" vs
"yours delivers zero of the required rise") until the shape test showed one file
delivered +4.1 of a required +5.8 dB local rise and the other +0.0 — resolved in
one round, and the overshoot claim traced to a different effective target anchor,
not a real acoustic difference.

**A tune comparison must score the FULL channel state — including output level
(Vol) — not the PEQ set alone.** A file with baked level trims is acoustically
different from one without, even with identical filters; a scorer that reads only
PEQ misjudges headroom, sub/front balance, and target fit. A real cross-audit got
its verdict exactly backwards this way — it ignored `<Vol>` tags and so missed
−1 dB front trims that were the point of the file. Related: keep optimizer
*guardrail* penalties separate from *acoustic* error when comparing candidates
from different systems — a guardrail term can dominate the composite and invert
the acoustic verdict, and different systems' guardrails are not comparable
(one system's guardrail scored 10 of a 17-point total in that same audit).

**Establish that a decoded field is LIVE before reasoning about its value.** A
DSP file stores parameters that the running configuration ignores — leftovers
from whatever the slot was previously set to. Reading such a field and
interpreting its number produces a fully-formed, confident, wrong conclusion,
because nothing about the value itself looks stale. A real case (2026-08-01):
crossover `Fil` tags carried Q=0.7 on the front mids, Q=0.5 on the sub lowpass
and Q=1 on the rears, which "clearly" showed the rears were a different alignment
with a resonant shoulder at the corner. PC-Tool showed all eight channels as
Linkwitz-Riley −24 dB/Oct. The alignment is held in the `<OC>`-level `HPi`/`LPi`
index (identical on every channel); the `Q` only becomes live under a
"Self-define" characteristic. The invented defect survived three consecutive
analyses — an initial read, a second opinion from a different model that accepted
the premise and elaborated on it, and a "verification" pass — because each one
reasoned about *the number* and none asked whether the field was wired to
anything. One glance at the device UI settled it in seconds. Before building an
argument on a decoded value: check whether the software's own display agrees,
prefer a field you have confirmed against that display, and treat an unverified
field as unknown rather than as data. Note this compounds badly with
cross-model review — a second opinion inherits your framing and will confidently
refine a defect that does not exist.

**A magnitude null found in measurement data is not automatically the same
physical thing as a resonance/rattle the user reports by ear or by hand.** Both
can be real, narrow, and centered near the same rough region without being the
same phenomenon — one can be an absorption dip (energy leaving via a mechanically
damped panel) and the other a genuine resonant peak (energy being added by a
vibrating mass), a few tens of Hz apart. Building a correction around the
measured null without confirming its frequency against the user's own independent
evidence (can they reproduce/shift it by touching a specific component? does it
occur without the audio system driving it at all, e.g. from road input alone?)
risks aiming at the wrong target. A real case: a −4 dB EQ cut was built around a
notch found at ~155 Hz; the user later pinned the actual resonance, by manually
manipulating the suspect part, at ~190 Hz — and the tune's *compensating boost*
for the (mistaken) null had been landing almost exactly on the real resonance the
whole time, feeding it. Once independent physical evidence exists, trust it over
the measurement-only guess and re-derive from the confirmed frequency.

**Synthesizing a "what if this physical defect were fixed" response: use
excess-over-broad-trend, not point-to-point interpolation across the feature.**
When modeling a hypothetical future measurement (a resonance eliminated, a
rattle fixed) from today's data, a naive fix — interpolate a smooth curve
between two reference points flanking the defect — is fragile if either
reference point is itself inside another nearby feature (a null, a second
resonance edge); the interpolation inherits that contamination and over- or
under-estimates the effect. More robust: take the raw trace, compute a heavily
smoothed (~1/2-octave) version of the SAME trace as the local "trend," define
excess as raw-minus-trend, and remove only the POSITIVE part of that excess in
the defect's band — since a resonance is fundamentally added energy on top of
the driver's own baseline, not a re-definition of what the baseline is. A real
case: the interpolation-across-two-points method put a resonance's contribution
at 3–4 dB; redone with the excess-over-broad-trend method (same underlying
data) it was 1.6–2.4 dB — enough to flip the right correction from "remove the
existing compensating cut" to "remove it, and the case for adding a small boost
on top is much weaker than it first looked." Bias any decision built on a
synthetic (not yet re-measured) state toward removal/neutral over new boosts —
the smaller the assumed effect, the less a boost's benefit clears the bar of
being worth a write with no confirming measurement behind it yet.

**Measure the capture method's OWN noise floor, then require every band to
clear it.** "Is this deviation real?" has no answer in the abstract — it depends
on how repeatable the measurement is at that frequency, which is a property of
the method, the rig, and the frequency, not a constant. It is directly
measurable whenever two sessions exist with a *known* EQ delta between them
(even a tune change, as long as the change is known): subtract the modelled EQ
delta from the measured difference, remove a broadband offset using a region the
change didn't touch, and whatever residual is left IS the session-to-session
repeatability. Then require a proposed correction to exceed that residual by a
comfortable factor (~2-3x) before spending a filter on it. A real case: MMM
repeatability measured this way came out ~0.1 dB at 400-500 Hz, 0.6-1.0 dB at
700-1400 Hz, 1.0-1.6 dB above 1400 Hz for the midbasses, and 0.23-0.46 dB across
the band for the tweeters — so a 2 dB correction at 1250 Hz was well supported
while a 1.5 dB one at 630 Hz was marginal, a distinction invisible without the
measurement. Expect the floor to WORSEN with frequency for moving-mic captures
(the mic path is never traced identically twice, and path variation matters more
as wavelength shrinks), and watch for a systematic tilt in the residual rather
than random scatter — that indicates level/path drift between sessions, not
noise.

**Don't let a handful of discrete fixed positions overrule a moving-mic average
for tonal decisions.** `spatial_consistency` on 2-3 fixed sweep positions is the
right tool for deciding whether a *phase/crossover* feature is stable, but it is
the WEAKER instrument for tonal calls above a few hundred Hz, and it can flag a
perfectly sound MMM-derived correction as "position-variable." The reason is
sampling density: positions spaced a head-width apart are close enough to sit in
the SAME near-field comb nulls, so their mean is not the spatial average an MMM
capture produces — it is three samples of a comb pattern. A real case: a
3-position mean disagreed with MMM by up to 16 dB above 800 Hz, and flagged two
one-sided cuts as low-confidence (0.05-0.07) — yet MMM's own measured
repeatability at those exact frequencies was +/-0.24-0.56 dB, i.e. the
corrections were supported by 4-8x margin. When the two disagree for a tonal
decision, prefer MMM and use its own repeatability (above) as the noise floor;
reserve the discrete-position spread for what it's actually good at.

**A score gap smaller than measurement repeatability is a tie, not a ranking.**
Two candidates differing by a few tenths of a dB in the summed response, built from
a single MMM run each, are within the run-to-run measurement noise of that capture
method — the "winner" won't survive a re-measure and the gap isn't real signal.
Report a difference that small as a tie and say why, rather than optimizing past
the noise floor or presenting three-decimal scores as if they were decisive. Same
discipline `predicted_vs_measured`'s `consistent_db` tolerance already applies to
the predict-vs-remeasure comparison — crude and directional on purpose, not a
precision instrument.

**A low-SD near-zero mean is a strong, repeatable finding — not a weak or
unreliable one.** `|mean|/SD` is a tempting trust gate across repeated
sessions and a real anti-pattern: a band reading mean=+0.1 dB, SD=0.2 dB
across several independent sessions is *very* stable and nearly balanced,
but a `|mean|/SD`-style gate reads its small mean as low "signal" and can
exclude it from scoring as unreliable — exactly backwards. Repeatability
(how much values scatter session to session) and effect size (how far from
zero the mean is) are different questions; `tunelib.historical_repeatability
(values)` answers them separately and returns `'stable_near_zero'`,
`'stable_nonzero'`, or `'unreliable'` — the last one driven only by SD, never
by a small mean.

**A re-exported or copy-pasted measurement file can silently double-count as
a second independent session**, inflating N and deflating the apparent
spread of a "historical" feature. Before computing any cross-session
repeatability or sign-count, run `tunelib.detect_duplicate_traces(traces)` —
it hashes/compares each trace and groups byte-identical or near-identical
(floating-point round-trip tolerance) captures, which must be counted once,
not once per filename or date.

### Traps caught on an Alpine PXE-X121-12EV session (2026-08-05)

Six more, all from one session, all of which produced confident wrong answers
before being caught. Grouped because they share a root cause: **a summary
statistic hid the shape of the thing being summarised.**

**Band-averaging a deviation across a modal null reads as a LEVEL DEFICIT.**
The most expensive error of that session. A subwoofer's deviation averaged over
25–40 Hz and 40–63 Hz came out −3.3 and −5.1 dB, which reads unambiguously as
"this sub is 5 dB short — raise the gain, and the existing cuts are why it's
short." Point-by-point, the same response was **+9.2 dB at 32 Hz and +5.6 dB at
53 Hz** with deep nulls at 28 and 44 Hz dragging the averages down. The sub was
never short on level; it was peaky, and the inherited filters sitting on those
peaks were doing exactly the right job. Acting on the averaged read meant
proposing to delete filters that were *improving* in-band RMS by 1.2 dB.
**Before concluding "level" from any band-averaged deviation, look at the
point-by-point deviation inside that band.** If it alternates sign by more than
a few dB, it is modal ripple and the average is meaningless — averaging across
a null is arithmetic, not acoustics. Level errors move a whole region the same
direction; ripple does not.

**Judging inherited EQ: check every band against the RAW response before
removing it.** Corollary of the above, and the mechanism that made it costly. A
tune carrying obvious junk (bands outside their own channel's passband,
duplicated bands, +6/−11 dB pairs a few Hz apart) invites the conclusion that
the whole set is junk. It usually isn't: the junk and the real corrections sit
in the same list. Reconstruct the raw (pre-EQ) response — either measured with
EQ bypassed, or by mathematically removing the known filters — and check each
band against it individually. In that session 3 of 11 sub bands were doing real
work on real modal peaks and 8 were inert; a blanket clear got the 8 right and
the 3 badly wrong. **Where the user has captured the same channel both with and
without its EQ, use that instead of any model — it is the only comparison free
of your own filter arithmetic.**

**A CONSTANT offset across the whole band in `interference_audit` is a level
mismatch between captures, not interference.** Real destructive summation is
frequency-dependent — it combs, swinging several dB across an octave. A flat
−6 dB (std 0.36 dB across 3.3 octaves) is a capture-level difference, and the
giveaway is arithmetic: the "pair" trace measuring *quieter than either solo
alone* is physically impossible for any summation. Check the spread of
`interference_db` before interpreting its sign; a low standard deviation across
a wide band invalidates the audit rather than reporting a problem.

**Separate MMM captures are not reliably level-comparable.** MMM level depends
on traverse path, speed and volume, so two MMM runs of different drivers can
differ by several dB for no acoustic reason. This breaks anything that compares
absolute levels *across* captures — `interference_audit` above all, which needs
solos and their pair on a common scale. Comparisons *within* a single capture,
and shape comparisons after level-normalising, remain valid. Plan for it at
capture time: if solos and pairs are both wanted, capture them at the same
master volume in one sitting.

**Fractional-octave summaries misplace narrow features — locate at full
resolution before placing a mask or a filter.** A 1/3-octave view put a
midrange null at "1600 Hz" and invented a dip at "12.7 kHz". At full resolution
the null was at **1908 Hz** and the 12.7 kHz dip did not exist — it was the
1/3-octave bin smearing in the rolloff above 13 kHz. Both errors then propagated:
the mask went in the wrong place, and `fit_peq` was handed a fit region still
containing a −12 dB null it could not fix. **Use fractional-octave views to
notice that something is there; use the full-resolution trace to decide where
it is.**

**`fit_peq` returning ZERO bands on an obviously-wrong channel means your mask
or fit band is wrong — not that the thresholds need loosening.** Twice in one
session. Once because an unmasked −12 dB null dominated the error so no cut
could clear the improvement gate; once because the fit band included the
crossover skirt. The parsimony gate is doing its job in both cases. The correct
response is to fix the region you handed it, then re-fit. **Never respond by
lowering `improve_pct` or `min_gain` to force an answer out** — that converts a
diagnosable input error into filters nobody can justify.

**Never include a crossover skirt in a fit band.** Given 22–80 Hz on a channel
low-passed at 60 Hz, `fit_peq` (boosts allowed) returned **four identical +4 dB
bands stacked at 76 Hz** — 16 dB of boost trying to undo the low-pass, because
the skirt reads as deviation-from-target like anything else. Fit only over the
range where that driver is the dominant contributor, well inside its own
passband. An output that stacks multiple same-frequency bands is the signature
of this error and should never be written.

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
magnitude-only average. Vector averaging cancels position-specific comb-filtering
(which differs per position) while preserving the real driver phase (which is
common to all of them); a magnitude-only average would just bake the comb-
filtering artifacts into the averaged level instead of cancelling them.

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

## The crossover action-ladder (cheapest, safest first)

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
even warranted.

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
diff raw curves — it estimates a broadband level offset from the *untouched*
frequencies only (so the alignment step can't quietly absorb the very change
being tested), compares octave-smoothed regions around each band's center
(so ordinary mic-position comb ripple doesn't read as failure), and drops to
`'inconclusive'` wherever confidence in that region is low rather than
forcing a verdict either way. Treat a `'reverted_recommended'` result the
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

On a driver with a steep high-pass (a tweeter above its crossover corner, in
particular), REW's "estimated IR delay" figure can jump between two (or more)
discrete values roughly `1 / f_passband_centre` apart between otherwise-
identical repeat captures. Nothing physically moved; only the estimator's
cycle-lock did.

**Signature, confirmed by an 8-repeat controlled test (nothing touched between
captures):** the reported delay clustered on exactly two values —
`7.017, 7.018, 7.019, 6.579, 6.574, 6.579, 7.019, 7.018` ms — a 0.439 ms gap,
matching `1/2278 Hz` almost exactly, sitting inside that tweeter's crossover
region. Within either cluster the spread was 1–5 µs (real repeatability);
across the two clusters it looked like a 0.44 ms "timing failure."

**How to tell the estimator from a real timing problem — this is the decisive
test, not eyeballing the impulse plot.** Fit a delay to the PHASE DIFFERENCE
between one capture from each cluster (linear regression of
`unwrap(angle(B/A))` vs. frequency, over a band where both captures have real
energy). On the same 8-repeat set this returned an implied delay of
`0.0000 ms` (residual ~18°) between a "6.58 ms" capture and a "7.02 ms"
capture — the underlying phase-valid data was unaffected the whole time; only
the single scalar REW reports in the header/sidebar was jumping.

**Practical rule:** never trust a single reported REW delay number for a
band-limited driver, especially a tweeter above its own crossover corner.
Either (a) take multiple repeats and check for a small-integer-multiple-of-a-
cycle relationship between clustered values before drawing any conclusion, or
(b) skip the reported number entirely and work from the exported complex data
(phase-slope delay, or the algebraic recovery below) instead.

## Recovering per-channel L/R responses from a common-source pair, without solo captures

If the DSP allows toggling one channel's polarity, two captures — `N = L + R`
(normal) and `V = L − R` (one channel inverted) — algebraically recover BOTH
individual channel responses with no solo measurements at all:

```
L = (N + V) / 2
R = (N − V) / 2
```

This holds exactly for any linear system, as long as N and V share a common
time reference (so they're complex-comparable) and nothing else changed
between the two captures.

**Always validate the recovery before trusting it downstream** — reconstruct
L (or R) and compare it against an independently, directly measured solo of
that same channel, if one exists anywhere in the project (a different
session, a different day — fine, as long as that channel's crossover/EQ
hasn't changed since). A real case: this technique validated to 0.01–0.26 dB
median error against independent solos across four separate recovered-channel
vs. independent-solo comparisons in one project, which is what made every
subsequent phase and level conclusion drawn from the recovered channels
trustworthy rather than assumed.

Useful when solo captures weren't taken, when re-measuring solos would cost
too much session time, or — as in the imbalance case below — as a
cross-check that builds multi-session confidence in a finding alongside
directly-measured solos.

**Validate OUTSIDE the recovered channel's expected passband too, not just
inside it.** A recovered low-passed driver (a sub, from an N/V decomposition)
can carry substantial spurious energy far above its real crossover — the two
source captures' shared noise floor doesn't fully cancel in the subtraction,
and dividing by 2 can still leave a "signal" within a few dB of whatever
else you're comparing it against. On a real project this showed up as a
recovered sub reading nearly as loud as the mids at 6–19 kHz, a decade above
its LR24 low-pass — obviously not real, but only obvious once someone
printed the level there. See the next section for the real downstream damage
this specific artifact can do to a candidate-finder function that isn't
expecting it.

## When `polarity_delay_search` says "nothing to gain," run `delay_sweep` (and how this was actually found)

**Real case (2026-08-08).** `polarity_delay_search` on a sub/mids pair,
target band 40–140 Hz, reported `delay_ms_B: 0.0, improvement_pct: 0.0`. That
was taken at face value — "sub timing is already optimal, nothing to gain" —
and told to the user as such. **This was wrong, and it wasn't caught by
re-examining the tool. An independent second opinion (a different AI, given
the same measurement files) computed its own delay sweep from scratch using a
different scoring method — direct coherent-summation gain, weighted toward
frequencies where BOTH drivers actually overlap in level, checked for a
"maximin-robust" optimum across two separately-captured sessions — and
proposed a specific non-zero delay with the reasoning laid out.** Reproducing
that computation confirmed a real, small (0.1–0.7 dB depending on band and
weighting), reproducible gain that `polarity_delay_search` had missed, and it
went on to be confirmed by an actual A/B measurement in the car.

**`tunelib.delay_sweep` / `overlap_weighted_delay_gain` package that exact
method** (added after this happened, so it's a one-line call next time
instead of needing a second opinion to surface it):
`delay_sweep(freqs, driver_a, driver_b, band, datasets=[...])` scores every
candidate delay by coherent-sum-vs-power-sum gain inside `band` ONLY — no
cross-band safety term at all — weighted by `min(|a|,|b|)**2` so frequencies
where one driver dominates and the other is negligible don't dilute a real
in-band gain toward zero. Pass other independently-captured `(freqs, a, b)`
tuples via `datasets=` for the maximin-across-sessions check: it returns the
delay whose WORST-case gain across every dataset is highest, so a delay that
only helps one session doesn't get recommended. It also flags `ambiguous`
when a near-equal second local maximum sits more than half a wavelength away
from the best one — the same cycle-slip signature documented above for REW's
own delay estimator, now checked automatically instead of by eye.

**Only after this was fixed did it become worth asking WHY the original tool
missed it** — that's a separate, useful diagnosis, not the discovery itself.
`polarity_delay_search`'s default `damage_band=(60, 16000)` Hz penalizes any
candidate delay that makes the ORIGINAL full-range sum worse anywhere across
that whole span — a sensible safety net for a genuine full-range vs.
full-range comparison (mid vs. tweeter), but most of that span is pure
measurement noise floor, not signal, for a low-passed driver like a sub.
Splitting the function's own score into its two summed terms confirmed this
directly: the in-band `gap` component *did* fall substantially moving away
from 0 ms, but the full-range `damage` term swung by roughly 4x more over the
same move, swamping it. Traced to source: at 6–19 kHz the sub input carried
energy within a few dB of the mids' own level — pure noise floor, confirmed
on both a directly-measured sub solo and an independently N/V-recovered one
(see the decomposition section above), so it's a property of any band-limited
driver's capture, not specific to the decomposition technique. Narrowing
`damage_band` to the sub's real electrical passband (20–200 Hz) recovered a
sensible, non-zero answer from `polarity_delay_search` too, in reasonable
agreement with `delay_sweep`'s result on the same data.

**Rule: don't accept a candidate-finder's "nothing here" verdict —
especially `improvement_pct` landing suspiciously exactly at 0.0 — as
evidence the acoustics are already optimal. It's evidence the SCORE didn't
move, and a score can fail to move for reasons that have nothing to do with
the acoustics.** Run `delay_sweep` alongside `polarity_delay_search` whenever
either driver is band-limited (a sub, in particular), and treat a flat 0.0%
from the latter as a prompt to check the former, not as a closed question.

## Bracket every A/B write A→B→B→A, and anchor on a band the write structurally cannot touch

Any two-state comparison (tune A vs. tune B) that spans more than a couple of
minutes is vulnerable to session-level drift — playback level creeping,
auto-gain re-engaging, a physical connection changing — large enough to dwarf
the effect being measured. Two defenses, used together:

**Bracket, don't just A→B.** Capture order `A, B, B, A` (or `A1, A2 … B1,
B2 … A3`), not just `A, B`. If the two `B` captures agree, and the closing `A`
disagrees with the opening `A` by more than that, the session drifted — caught
DURING the session instead of discovered afterward. A real case (2026-08-08):
a delay-write A/B test showed a monotonic +2.7 dB broadband level rise across
~4 minutes (`A1 → A2 +2.6 dB`; a control solo capture the write couldn't
possibly touch also drifted +0.85 dB, flat across frequency — pure gain
drift, not a response change), caught immediately by comparing the two
nominally-identical control captures.

**Anchor on a band the specific write is physically incapable of altering,
then re-derive the result relative to that anchor.** A pure delay or a pure
all-pass filter is magnitude-flat by construction on the channel it's applied
to — it changes phase only, never that channel's own SPL at any frequency.
That gives two free, zero-cost checks for any delay/APF write:
- The edited channel's own solo capture, before vs. after, must be
  magnitude-identical. If it isn't, something in the measurement chain moved
  — not the filter.
- Any frequency band where the edited channel doesn't dominate the trace
  (below its own crossover corner, or a different channel's passband
  entirely) is a valid drift anchor: re-reference every capture in the
  session to its OWN level in that band before comparing anything else.

Applied to the +2.7 dB drift above: anchoring every capture on 300–2000 Hz (a
band the sub-delay write couldn't reach — the sub is low-passed well below
it) collapsed the drift and recovered clean 0.07–0.11 dB repeatability,
revealing a small (~0.2–0.6 dB) real, repeatable, correctly-signed gain that
the raw numbers had made look unusable.

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

REW's SPL & Phase text export (what `measure.py` parses) carries magnitude and
phase only. If a distortion, coherence, or raw-IR question comes up and only
text exports exist, the answer may already be sitting in a `.mdat` the user
also has — REW's binary Java-serialized measurement file (magic bytes
`\xac\xed\x00\x05` + "REW Measurement Data File V2") carries all of that, per
measurement, that the text export drops.

Rough layout, observed directly on a real file (not from REW documentation —
treat as version/config-dependent and validate before trusting it on a
different REW version): distortion is stored as one `1053`-point float32
block per measurement = an explicit ascending frequency axis (`10 → ~19900`
Hz), followed by ~10 more `1053`-point blocks = the fundamental and
successive harmonics, in descending mean-level order (fundamental strongest).
**Blocks for different measurements are NOT necessarily in the file in the
same order the captures were taken** — match a block to its measurement by
correlating its fundamental trace against that measurement's already-known
SPL curve (from a paired text export, if one exists), not by position in the
file.

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

It's easy for a tuning session to drift into scoring only L/R differential error,
because that's usually where the interesting/actionable findings show up early and
because most of the diagnostic tooling here (`tune_scorecard`, delay/EQ candidate
search) is framed around per-channel or per-pair comparisons. But the tonal-target
objective (System Sum vs the reference curve) is an equally valid, independent axis,
and a long L/R-focused investigation can leave it completely unscored for weeks
while genuinely large, genuinely repeatable common-mode errors sit untouched. A real
case (2026-08-09): after an entire multi-week campaign optimizing 4-14 kHz L/R
balance down to parity with the rest of the spectrum, scoring System Sum vs target
for the first time turned up a **+2.5 dB excess at 100 Hz with SD 0.2 dB across
four sessions spanning three different tune states** — more repeatable than any L/R
feature found in the whole project, sitting in a region nobody had looked at because
all recent attention was on the region that had, ironically, already been leveled.
Common-mode corrections are lower-risk than differential ones (identical filter on
both channels of a pair leaves R−L mathematically unchanged, so they can never
undo differential work), which makes neglecting this axis doubly wasteful. **When a
tuning investigation has been running on one axis (L/R, a single band, a single
driver pair) for several sessions, periodically re-score the other axis (System
Sum vs target) from scratch** rather than assuming it was already covered earlier
in the project.
