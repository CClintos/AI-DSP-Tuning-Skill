# Tuning methodology — how to decide what to fix

This is the judgment layer. The scripts give you numbers; this tells you what they
mean and which action type each problem calls for. The overarching bias: **classify
before correcting, and prefer doing less.**

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

### Minimum-phase / EQ-ability

Flat excess group delay ⇒ minimum-phase region ⇒ EQ works. Sharp excess-GD
excursions ⇒ non-minimum-phase ⇒ EQ won't generalize. `tunelib.excess_gd_mask`
flags regions to leave alone. Narrow high-frequency dips are almost never worth
correcting — they don't survive small mic movement.

## The crossover action-ladder (cheapest, safest first)

When two drivers don't sum well through their crossover, test in this order and
stop when the problem is solved (a later, riskier tool must clearly beat the
earlier one to be worth it):

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

- **F** = the null / phase-crossing frequency. **Q** = how sharp: 0.5 broad, 2 tight
  at F. Use the **lowest Q that fills the null** — higher Q rings more on transients.
- 1st-order (T=19, no Q) for gentle broad correction; 2nd-order (T=20) for more/
  more-local rotation.
- The **invert** flag (`I="1"`) flips rotation direction: if the null gets *worse*
  at every F/Q, invert and re-sweep.
- **Imaging cost is real and often unavoidable**: fixing an L↔R null needs a one-
  sided APF, which injects interaural group-delay mismatch (can be ~1 ms spread over
  a wide band). Put it on the **subordinate** (weaker/farther) side, keep it below
  ~1 kHz for one-sided use, and **verify centre image with a mono vocal** after.
- Symmetric APF (same branch on both L and R) is summation-only and image-safe.

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

## Verification & honesty

Predictions from magnitude (RTA/MMM) data don't capture phase outcomes. Always end
by telling the user which claims are *predicted* vs *measured*, and give a specific
re-measure + listening checklist — the loaded-and-re-measured result is the only
real proof.
