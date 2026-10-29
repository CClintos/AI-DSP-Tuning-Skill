# How it works — and why it is not just "EQ to a line"

*The long explanation behind the [README](../README.md): what gets measured, what a tune is scored on, MMM tuning, EMMA preparation, refining an existing tune and the restraint budget.*


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
it auto-aligns a broadband level offset using only frequencies the edit
leaves untouched (so a re-measure taken at a quieter volume that day doesn't
read as "the EQ failed"), compares octave-smoothed regions rather than raw bins
(so ordinary mic-position ripple doesn't either), and grades each changed
band `confirmed`, `diverged`, `reverted_recommended`, or `inconclusive`.
`confirmed` needs the re-measure to sit closer to the predicted change than to
no change, so an unchanged re-measure can never confirm an edit; a change
smaller than the measurement can resolve, or a region with low confidence,
stays `inconclusive`. Edited and removed filters are predicted relative to the
bank that was already measured, never as another cascade on top. `reverted_recommended` is treated as an instruction to
reconsider that band, not a suggestion.

### Tuning from moving-mic (MMM) RTA captures

If you measure with a moving mic and REW's RTA, pass `--capture mmm`: each
capture is treated as the spatial average it is, extra files as repeat runs
(which measure how repeatable your captures are), and phase-based checks are
switched off rather than run on data that has none. In their place:
- a full-system tilt that only a wrong RTA mode can produce (Spectrum mode, or
  white noise) is refused before it can tilt the tune;
- `--ambient` drops frequencies the cabin's background noise could be filling;
- `--cancel-check LEFT RIGHT BOTH` blocks boosts into dips that two halves
  create together (cancellation), found from magnitude alone;
- `mmm-compare` defaults to balanced bass selection: target balance against
  an unchanged measured midrange reference, with output and shape guards.
  A louder hump cannot win on output alone; repeat disagreement is measured
  between curves, and any winner needs a confirmation capture;
- repeatability retains separate bass/midrange/treble estimates and a local
  profile for filter verification, so quiet mids cannot certify noisy bass;
- `lr-match --target <curve>` trims the louder side and proposes cuts only
  when tone and matching both improve. It leaves unresolved dips for diagnosis
  instead of copying them onto the good side.

- with MMM, a band or edit smaller than your repeat-capture variation where it
  acts is not proposed, and an unchecked boost becomes a trial to verify;
- one dip can no longer end the search before a real peak is cut, and no fit
  stacks several boosts on one dip: expect at most one trial per dip;
- `--capture-profile` records your REW setup and checks it against REW's
  rules (pink noise in the RTA, sequence length = FFT length, separate clocks
  when the car plays the noise);
- `verify` tells you, filter by filter, whether a written change landed;
- `voice-variants` builds bass/treble shelf variants of a finished tune for a
  blind, level-matched listening test.

From 1.21.0, a single MMM capture set says more (and from 1.22.0, `capture-plan` says what to capture and `next` what the captures can run):
- `capture-audit` reads every capture's own header and `.mdat` record (RTA
  settings, mic, gain, input volume, time, calibrated levels) and flags short
  captures, mic-movement noise below 22 Hz, mic clipping, infrasound, mixed
  smoothing/resolution/mics, cancel-check triples played at different levels,
  unmuted drivers and HF interference -- then says what each file can feed;
- `--noise-floor <solos>` uses band-limited solos' stopbands as a noise floor
  measured while the mic moved (a static ambient capture misses that noise);
- `coherence` turns the cancel-check triple into summation coherence per band:
  where alignment can change the tone, and where only EQ or level can;
- `mmm-align` chooses a sub/midbass delay and polarity from four MMM captures
  (A, B, both, both with a known extra delay), within ~0.1 dB of the best in
  simulation, for confirmation and the normal phase-only plan;
- `stability` / `--peak-trace` read REW's peak trace ("Save both") as a bass
  stability map from one run;
- `xo-check` measures the crossover and PEQ your DSP actually applied from
  RAW/XO/EQ captures;
- `listening-level`, `road-noise` and `prefs` voice for the level you listen
  at (ISO 226), for road noise (a separate driving preset), and from what your
  blind A/Bs say you like;
- `frames` gives one run its own repeatability from a WAV recording or REW's
  per-block data, and `test-signal` / `signal-analyze` (experimental) add the
  skill's own periodic signals.

The capture checklist is in `references/methodology.md` (MMM-first tuning,
and Single-run MMM intelligence for the commands above).

### Preparing for an EMMA Sound Quality event

The skill reports in the judges' terms: `analyze` gives each of EMMA's four
tonal bands (sub-bass, mid-bass, midrange, high) against the target and the
spread between them; `emma-volume` checks the "6 dB louder" spectral-balance
pass, reporting an incorrect capture step separately from changed balance;
`noise-check` compares system off with system on playing silence; and
`imaging --bands emma` uses the 2026 SQ judgebook's five overlapping instrument
ranges, with position tracks 2-6 and focus tracks 7-11. These diagnostics do
not predict judging points. A capture that rises only 4 dB does not prove
the system cannot play 6 dB louder.
The methodology's "Preparing for EMMA judging" section summarises the rules
that matter for a tune (one judge, driver's seat, 80 dB cap, +6 dB pass).

For a close final MMM comparison, capture A1, B1, B2, A2 and give
`mmm-compare` both `--repeat A2.txt` and `--candidate-repeat trial=B2.txt`
(where `trial=B1.txt` is in `--captures`). Both candidate captures must
improve on both baseline captures, using one target anchor and the larger
repeat disagreement. A successful comparison still needs matched-level
listening. See the MMM-first section for a complete command.

### Improving a tune that already exists

After the first session the measurement already includes your filters, so
`pipeline.py refine` works on that bank directly — keep, relax, re-fit or
remove each filter, and only add one where something real is left — rather than
stacking new filters on top. Predictions are new minus old, so nothing is
counted twice. Changes are then judged by ear the fair way: `ab-make` writes
two blind copies (X and Y) with the louder one trimmed to match, and
`ab-result` reveals which you preferred and whether that beats chance.

Crossovers are still never written, but `probe` can now model a crossover
change (Linkwitz-Riley or Butterworth, from the current setting to a
candidate) at every junction, left/right pair and mic position it touches, so
it can recommend one for you to set in PC-Tool. `analyze` and `propose` also
report the low end's overall level against the target, because a bass region
that is wholly too hot or too light is a sub-level decision, not a job for EQ.

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
