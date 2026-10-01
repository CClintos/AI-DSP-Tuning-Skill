# Research-note ideas, evaluated 2026-10-02

Source: the user's "ClaudeDSPTuner GitHub research & improvement ideas" note.
All eleven referenced repositories exist. Code read: OptiMIMO (MIT),
audio-calibration-mcp (MIT), room-eq-wizard-mcp (MIT), autoeq room-EQ quality
crates (no licence: ideas only), Resonalyze (earlier).

| Idea | Outcome |
| --- | --- |
| Held-out validation + per-recommendation confidence | `held_out_band_validation`; `propose` gates bands APPLY / REVIEW / DO NOT APPLY (audio-calibration-mcp train/withheld gate, autoeq held-out seats) |
| Probe engine | `probe_variants` + `pipeline.py probe` |
| Delay confidence | `delay_consensus` (4 estimators + gross-timing guard, research case 005) |
| Direct REW access | `rew_api.py`, read-only (wire format from OptiMIMO / room-eq-wizard-mcp, verified live there; stub-tested here) |
| Regression cases 001-006 | `tests/test_calibration_cases.py`; case 006 found a real fault (below) |
| Single weighted score | not adopted: per-claim confidence is more honest |
| Anchored target | FIR-matrix concept; the skill already keeps natural geometry |
| Universal DSP model | not adopted: analysis is already format-independent |
| FIR | not applicable to the P SIX MK2 |

## Fault found by case 006, and the fix

A peak that wanders +/-1/4 octave between positions made `fit_peq_robust`
cut -12.5 dB Q8: masked (position-inconsistent) bins were free to dig, and a
band-wide RMS read a peak-for-hole trade as an improvement. Fix: dug depth
(`eq_dig_depth`, Resonalyze's falloff) charged inside the objective at every
in-band bin (`dig_weight=1`), with a median-position 6 dB backstop. Synthetic
cars, 40 per row, scored at 8 unseen positions (old -> new):

| Fit positions | Unseen gain dB | Unseen seats worse /8 | Deepest new hole dB |
| --- | --- | --- | --- |
| 3 | 0.567 -> 0.767 | 1.43 -> 0.35 | 7.64 -> 4.45 |
| 3 + wandering peak | 0.688 -> 0.821 | 1.57 -> 0.75 | 7.60 -> 5.83 |
| 4 | 0.525 -> 0.756 | 1.62 -> 0.40 | 6.05 -> 4.53 |
| 4 + wandering peak | 0.585 -> 0.816 | 1.55 -> 0.55 | 6.89 -> 5.15 |

A hard 3 dB per-position veto was tried first and rejected: per-seat combs
are broad, so it vetoed every legitimate cut (benchmark gain 0.53 -> 0).
