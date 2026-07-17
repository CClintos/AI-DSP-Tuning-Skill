# Tuning methodology — how to decide what to fix

This is the judgment layer. The scripts give you numbers; this tells you what they
mean and which action type each problem calls for. The overarching bias: **classify
before correcting, and prefer doing less.**

## Contents (line numbers, for offset reads — this file is long; jump straight
to the section you need instead of reading it whole)

- Measurement method selection — sweep vs Moving Mic (MMM) — line 28
- Sweep capture setup — line 100
- Deviation analysis — line 147
- Analysis traps (anchoring, sum-vs-solo, imaging, sub coupling, ties) — line 175
- Voicing — the most audible decision — line 235
- Classify the problem (the core skill) — line 266
  - The interference audit — line 285
  - Two checks before trusting a proposed EQ band — line 293
  - Minimum-phase / EQ-ability — line 314
  - Quantify single-position phase reliability — line 321
  - Multi-position variance ("EQ what's common, ignore what moves") — line 361
- The crossover action-ladder — line 399
- Shelf cookbook — line 460
- All-pass cookbook — line 473
- Imaging — line 516
- Restraint — line 548
- Verification & honesty — line 566

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
exactly what `spatial_consistency` (line 212) is built to check — but a
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

**A score gap smaller than measurement repeatability is a tie, not a ranking.**
Two candidates differing by a few tenths of a dB in the summed response, built from
a single MMM run each, are within the run-to-run measurement noise of that capture
method — the "winner" won't survive a re-measure and the gap isn't real signal.
Report a difference that small as a tie and say why, rather than optimizing past
the noise floor or presenting three-decimal scores as if they were decisive. Same
discipline `predicted_vs_measured`'s `consistent_db` tolerance already applies to
the predict-vs-remeasure comparison — crude and directional on purpose, not a
precision instrument.

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
"Measurement method selection" (line 27) for the fuller sweep-vs-MMM
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
