# Tuning changes with an audible purpose

## Choose the correction path

- **An existing tune:** start with `refine`. Add `--partner other_side.txt` for
  target-supported L/R constraints, and `--limits quality-report.json` for
  measured clean-output limits from this driver, preset and playback level.
- **Shared front-system voicing plus different side faults:** use
  `stereo-propose`. It proposes a common bank plus limited side-specific cuts.
- **Bass handover:** use `bass-trials` with timed solos and an actual together
  measurement. It ranks small relative changes by tonal fit, not maximum output.
- **Final preference:** create small bass, presence or treble alternatives with
  `voice-variants`, capture their actual system responses, then use `voice-match`
  before a blind listening comparison.

All proposal/trial commands produce reviewable JSON and write no tune. Existing
plan/apply confirmation, original preservation and phase/EQ separation still apply.
None of these scores establishes an audible improvement without loaded-tune
measurements and matched-level listening.

## One reference through fitting and verification

`validated_anchor_offset` keeps the usual mid-band anchor unless independent
100-250 Hz and 4-10 kHz bands support a bounded correction. Each needs at least
24 trusted bins and a 10th-90th percentile spread no greater than 1.5 dB; their
levels must agree within 0.75 dB. Only an anchor discrepancy of 0.5-3 dB can be
corrected. These are conservative engineering guards, not a universal acoustic
model. If references disagree, are rolled off or unsupported, the old anchor is
retained. Broad bass/treble preference therefore cannot freely move the anchor.

This fixes the two known-answer cases (compensating boosts and a missed 500 Hz
cut). It also handles a mid-band over-cut when both references agree. A solo
whose judged band lies outside the session reference still anchors inside its
own passband. Pipeline refinement freezes that baseline anchor for every
candidate and the final judging report. The low-level `refine_bank` API retains
legacy shape-only behaviour unless `fixed_anchor=True` is selected.

Never interpret the nuisance reference as an actual output-gain adjustment.
Channel level remains a separate, measured decision. Apply any real gain change
explicitly and include it in subsequent system measurements.

## Joint L/R correction

```text
pipeline.py stereo-propose --left left1.txt left2.txt --right right1.txt right2.txt --target target.txt --out stereo.json
pipeline.py refine --afpx current.afpx --channels 0 --dsp-rate 96000 --positions left1.txt left2.txt --capture mmm --target target.txt --partner right.txt --limits left-quality.json --out left-refine.json
```

The rate and channel above are placeholders: use confirmed hardware values.
Capture both sides on the same level scale and with the same mic coverage.
Do not normalize one side independently. Each stereo output bank consists of
`common_bands` plus that side's `side_bands`; check available hardware slots.

A robust broadband level difference is first offered as an explicit attenuation
trim on the louder side. The target reference is then fixed for evaluating that
gain change and the remaining tonal corrections. A pure level offset should not
produce compensating PEQs. `lr-match` exposes raw and post-trim mismatch separately.
Common cuts address excess present on both sides. Side cuts must improve target
fit without increasing L/R mismatch materially or digging a new deficit greater
than 0.5 dB. A tonal/L/R score change inside the decision margin recommends `keep_current`.
Filter predictions declare their model sample rate; confirm it for the hardware.
Filters stay broad (Q <= 4) and do not boost a weak side to match an
excess, or cut a healthy side to copy a cancellation dip. `--partner` connects
matching to single/robust fitting and refinement; its post-fit guard vetoes an
L/R mismatch increase greater than 0.25 dB over 700 Hz-5 kHz. Small score changes
inside measured repeat variation remain unproven.

The paired magnitude mean is a per-side objective. It is NEVER the coherent
combined response. Remeasure each side and both together; use timed sweeps for
junction analysis and listen to mono vocals through normal head movements.
Existing filters are part of the measured baseline; use refine for edits or
removals rather than treating a residual stereo proposal as a replacement bank.

### Crossover-neighbour guard

Propose/refine also accept `--junction-spec junctions.json`. Use the existing
probe schema (`dsp_sample_rate_hz`, `drivers` or `positions`, `junctions`, optional
`pairs`) plus `apply_to`, a list of the driver names receiving this correction.
Paths resolve beside the spec. Each affected junction needs explicitly timed,
phase-valid data over its full one-octave neighbourhood on either side.

The guard evaluates the additional filter cascade, including the inverse of the
old bank for refinement. A rejected/tradeoff result at any supplied position
holds the proposal and withholds refinement plan edits. A common identical filter
on both neighbours should preserve alignment; a one-sided tonal correction can
change it. Missing neighbour evidence remains unknown. Include every junction
and L/R pair touched by the selected channels, then confirm the full system by
measurement. This guard does not authorise a phase or crossover write.

## Measured clean-output limits change the fit

Pass a `quality-check` report using `--limits` on propose, refine or bass-trials.
A measured compression band forbids additional gain there. Candidate fitting
penalizes the complete additional-gain transfer; final quantized banks are checked
again (0.1 dB tolerance). Removing an existing cut also raises output, so it is
subject to the same ceiling. Cuts elsewhere remain available.

For harmonic comparisons, quality manifests may add `distortion_reference`, with
the same `fundamental`, `harmonics` mapping and `noise` fields as `distortion`.
Use captures with the same calibration, mic position, routing and preset context.
Comparison requires fundamental levels matched within 1 dB over 90% of the band,
and at least 80% resolved harmonic coverage above the supplied noise floor. An
absolute harmonic rise exceeding 3 dB becomes a no-additional-boost region.
This is a conservative change detector, not a universal THD audibility threshold.
Unmatched levels and unresolved harmonics remain unknown; they do not prove stress.

Limits apply relative to the preset and playback level used for those captures.
They must belong to the driver/route being fitted. They are not driver power
ratings and do not certify amplifier, transient or higher-volume headroom.
Recreate the evidence after material preset, routing or listening-level changes.

## Sub/front trials

```text
pipeline.py bass-trials --sub sub.txt --front fronts.txt --together fronts_sub.txt --target target.txt --band 40 200 --delays-ms -0.5 0 0.5 --gains-db -1 0 1 --try-invert --out bass-trials.json
```

Solo sweeps must explicitly record a shared timing reference. The captures must
cover the requested band plus a 500-2000 Hz reference. Their predicted solo sum
must match the actual together capture within 1.5 dB RMS WITHOUT automatic level
alignment. Otherwise the search refuses to invent a precise recommendation.

A fixed baseline reference ranks target error, vetoes newly worsened local
features greater than 2 dB, and rejects a reference-band shift greater than
0.25 dB. A trial must improve the score by more than 0.25 dB to be offered.
These margins are engineering heuristics; no candidate is called measured proof.
Search is bounded to 100 candidates, relative +/-10 ms and +/-6 dB. Negative
relative delay is only feasible where the existing allocation permits it.

Confirm the specific trial before writing a delay or gain change. Polarity is
still a manual PC-Tool trial. Keep phase-domain and EQ-domain writes separate.
Capture fronts+sub again with repeated MMM and use `mmm-compare` for tonal
confirmation. This checks one bass junction; any additional junction touched
by a shared channel must also be checked with `probe`.

## Preference at matched loudness

`voice-variants` now also accepts `--presence-db -1 1 --presence-channels ...`
(default 2.2 kHz broad PEQ). It requires a free PEQ slot. Existing bass/treble
variants remain available. Avoid adding a preference filter just to improve a
technical score.

```text
pipeline.py voice-match --baseline current_system.txt --candidates warm=warm_system.txt clear=clear_system.txt --out level-matches.json
```

Measure the same broadband test signal, source gain and mic method for every
actual system preset, with common 40 Hz-16 kHz coverage. The returned measured
loudness change supplies `ab-make --loudness-db` and the attenuation of the louder
copy. This weighted-energy estimate still needs a listening check; it is not
program-specific loudness or a preference prediction. It replaces the assumption
that a shelf applied to selected channels changes the whole system identically.

Retain a variant only if the blind, matched-level preference repeats across
several familiar tracks at the volume the tune is intended for.

One MMM run can support a large provisional trial, but repeatability fields remain
null/`unverifiable` until independent repeats exist. A legacy assumed-noise option
in a comparison command does not turn missing repeat captures into measured certainty.
