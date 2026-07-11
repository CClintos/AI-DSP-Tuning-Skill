# Tuning methodology — how to decide what to fix

This is the judgment layer. The scripts give you numbers; this tells you what they
mean and which action type each problem calls for. The overarching bias: **classify
before correcting, and prefer doing less.**

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
   both together from complex solos.
3. **All-pass** (adds group delay — only if polarity/delay leave a residual phase
   problem). `tunelib.optimize_allpass` searches F/Q against the summation.

Only after those, consider EQ — and only if the *solo* response justifies it.
`polarity_delay_search` returns `residual_needs_apf` to tell you whether step 3 is
even warranted.

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

**Extend the same skepticism to a candidate you didn't produce yourself.** This
applies "re-decode fresh, don't trust memory" (see SKILL.md's non-negotiables) to
external candidates too: when another AI, an optimizer, or an earlier session hands
you a candidate `.afpx` with a self-reported score, check what measurement files
and baseline tune it actually used to compute that score — file dates catch a stale
comparison fast. A score computed against data that's since changed is meaningless
even if it's internally consistent and the math checks out. **Always reproduce the
claimed score yourself against the current session's data** before accepting it.
