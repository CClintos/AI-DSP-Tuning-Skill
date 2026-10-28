# Measurement quality and judging

Use `pipeline.py quality-check --spec quality.json --out quality-report.json`
for a measurement-based assessment of a candidate tune. Paths inside the manifest
resolve relative to the manifest, including when the command is run elsewhere.
This command produces a report; it does not write a tune.

Start with only the evidence available. Omitted dimensions stay `unknown`.

```json
{
  "version": 1,
  "baseline": ["current_mmm_1.txt", "current_mmm_2.txt", "current_mmm_3.txt"],
  "candidate": ["trial_mmm_1.txt", "trial_mmm_2.txt", "trial_mmm_3.txt"],
  "target": "target.txt",
  "margin_db": 0.5,
  "level_steps": [
    {"path": "driver_normal.txt", "level_db": 0},
    {"path": "driver_plus3.txt", "level_db": 3},
    {"path": "driver_plus6.txt", "level_db": 6}
  ],
  "compression_tolerance_db": 0.75,
  "distortion": {
    "fundamental": "fundamental.txt",
    "harmonics": {"h2": "h2.txt", "h3": "h3.txt"},
    "noise": "distortion_noise.txt"
  },
  "stereo": {
    "before_left": "current_left.txt",
    "before_right": "current_right.txt",
    "after_left": "trial_left.txt",
    "after_right": "trial_right.txt"
  },
  "headroom": {"transfer": "full_chain_gain.txt", "input_peak_dbfs": -6}
}
```

All groups are optional, but at least one must be provided. Tone comparison
requires baseline, candidate and target together. A target may also be `default`.
Unknown fields, invalid numerical values and duplicate repeat captures are rejected.
The report cannot overwrite a capture, target, manifest or tune input.

## Tone and regression rules

Capture fresh before/after MMM repeats over the same listening volume with the
same mic calibration, orientation, playback level, path, duration and settings.
Use the existing capture-profile and ambient checks on analyze/propose/refine.
Do not mix fixed positions and MMM repeats in the tone manifest. Keep engine/HVAC
off and reset averaging between captures. Level-match listening comparisons too.

The target anchor is calculated from the baseline once and held for the candidate.
Raw playback levels are retained: independently re-anchoring each tune could hide
changes. Repeat uncertainty uses the existing frequency-dependent repeatability
helper; the decision margin conservatively takes the worst regional uncertainty
from either tune (twice its reported noise, or measured run level spread), with
`margin_db` as a minimum. This is a small-sample decision rule, not a confidence
interval or a calibrated listening probability. Two captures per tune are the
minimum for `improved`; three or more are preferable. A single-run apparent win
is `unconfirmed`. Fresh verification should be separate from captures used to fit.

The report separates broad tonal error and narrow-peak risk. Each fully supported
bass/mid/treble band also gets a score. A regional or component regression beyond
the margin vetoes an average improvement. Differences within the margin are a tie:
keep the current tune, or choose the candidate with fewer filters and less boost.
Partial bands remain unknown and are not certified using extrapolated endpoints.

Analyze now exposes a baseline judging scorecard. Propose and refine expose a
predicted before/after scorecard. A regression sets `apply_recommendation` to
`hold_for_review`; refine withholds its ready-to-copy `plan_edits`. Do not write a
proposal marked hold: revise it or capture evidence explaining the disagreement.
Predictions never replace a loaded-tune verification or matched-level listening.

## Clean output and distortion

Level-step captures use a FIXED, untouched microphone, unchanged gains and DSP,
and known playback steps. The comparison preserves absolute levels: a 6 dB input
increase producing 4 dB output is a 2 dB shortfall. Reports show median tracking
error and the 90th-percentile shortfall/excess in each fully measured band.
The default 0.75 dB threshold is configurable. Compression is a system finding;
source, amplifier and driver need isolation before naming the cause. Use
`source-audit --electrical` for source attribution when that evidence exists.

For distortion, supply separate two-column frequency/absolute-dB traces exported
from REW's distortion graph. The x axis must be STIMULUS frequency for every trace,
including harmonics and noise. These are not ordinary SPL/phase export columns.
All traces require the same absolute calibration and capture level. Noise must be
appropriate for the supplied harmonic traces; do not substitute a mismatched RTA
noise spectrum. Harmonics/fundamental need 10 dB separation from their supplied
noise floor to be reported as resolved. Unresolved values are null, not zero.
Absolute harmonic levels are reported alongside ratios so a fundamental null
cannot masquerade as increased harmonic output. No universal THD pass is inferred;
incomplete harmonic sets are never labelled total THD. Compare drivers and levels
before considering driver-bandwidth or boost changes.

Stereo captures need a common level scale and consistent spatial coverage.
The report measures L/R spectral mismatch without independent level alignment.
This is only an imaging-risk indicator: use `imaging`, timing-reference sweeps,
mono vocals and small head movements to judge the actual image. Do not sacrifice
image stability to improve one full-system frequency-response score.

Headroom input is a full-chain transfer in dB, including routing, summing and
trims, plus a known input peak in dBFS. It is NOT acoustic SPL. The spectral margin
is an estimate; transient overshoot, earlier internal stages and amplifier limits
remain unassessed. PEQ-only positive gain is not proof of clipping. The ordinary
proposal reports explicitly leave full-chain headroom unknown.

## Evidence that remains separate

Use existing `decay.py csd`, `t20`, `compare` and `reflections` commands with fixed-mic
IR exports for ringing/reflection investigation. Match analysis settings and check
noise support. Avoid a generic cabin RT60 target. Mechanical ringing requires
physical investigation; EQ may change excitation and observed decay, but cannot
be assumed to repair the underlying mechanical cause.

The quality report deliberately keeps decay, full image stability and listening
unknown: magnitude files cannot establish them. `overall` remains `incomplete`
when no veto is found, or `hold_for_review` for tonal/stereo regression, level
tracking problems or negative modelled headroom. It never awards an all-round pass
from a subset of measurements.
