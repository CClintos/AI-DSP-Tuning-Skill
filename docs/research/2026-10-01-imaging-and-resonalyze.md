# Imaging and sound-quality research, 2026-10-01

What was compared, what changed in the skill, and what is still open. The
skill's methodology is the judgment layer; this file is the paper trail for
the parts of it that came from outside.

## Sources

- **Resonalyze** — <https://github.com/DIMOSUS/Resonalyze> (MIT, © dimosus).
  An open-source Windows tuner for car audio: per-driver measurements on one
  loopback time base, a virtual DSP that simulates every channel's chain and
  sums the drivers as phasors, stereo-aware auto delay, an EQ fitter, and an
  assistant bridge. Read: README, MANUAL.md, docs/agent/AGENT_GUIDE.md,
  docs/tech/{dsp-helix-phase-control, junction-phase-and-group-placement,
  auto-alignment (stereo cascade), eq-auto-tuner, spatial-average}.md, and
  dsp/PhaseRotationControl.cs.
- **Lee & Rumsey (2013)**, "Level and time panning of phantom images for
  musical sources", JAES 61(12) — full phantom shift at about 17 dB ICLD or
  about 1 ms ICTD; level panning robust for all sources, time panning weak for
  continuous sources with a high fundamental.
- **De Sena et al. (2020)**, "Localization uncertainty in time-amplitude
  stereophonic reproduction", IEEE/ACM TASLP 28, arXiv:1907.11425 — ~15 dB /
  ~1 ms for a full shift; off-centre, relative level barely changes while
  relative time changes ~0.29 ms per 10 cm (60° layout); ±0.3 ms is a
  higher-uncertainty zone.
- Car-audio practice (diymobileaudio.com all-pass threads; Audiofrog "Time
  Alignment Part 1") — one-sided 2nd-order all-pass on a midrange for the
  driver-seat L/R midbass cancellation.
- The user's own sessions (2026-07-09) — mirroring a unilateral 420 Hz APF
  onto the other side brought back two L+R nulls.

## Gaps found, and what changed

| Gap | Change |
| --- | --- |
| `image_pull` scaled inter-CHANNEL differences with INTERAURAL constants (650 µs, 12 dB) and a duplex crossover that made level a treble-only cue | Inter-channel trading model: pull = ICLD/16 dB + ICTD/1 ms; level effective at all frequencies (Blumlein) |
| No method for placing the phantom centre at an off-centre seat | `centre_steering`: level-only vs far-side time lead + smaller trim, with the robustness trade; `pipeline.py imaging --near-side` |
| Imaging/junction timing judged on full-window phase | `decay.py fdw` direct-sound (8-cycle FDW) response; methodology "Two windows" |
| No junction read-out beyond pairwise delay search | `junction_phase_score` (both polarities in one sweep, 0.05 flip margin, lobe margin, 0.5 alignable floor) and `junction_sum_loss`; `pipeline.py junction` |
| Helix channel Phase control unknown to the skill | `helix_phase_rotation(_H)` model (Q=1 AP2 at the configured crossover, 5.625° grid, 3/16·fs corner cap); recommend-only; controlled-diff protocol for the `.afpx` storage |
| Ladder read "phase first, EQ only after" — applied to a whole tune this undoes alignment | Tune order: driver-local EQ → re-measure → align → system tone |
| Shared channels changed at one junction without checking the other | "A channel hands over twice" |
| Symmetric APF called image-safe without saying it cannot fix an L+R null | All-pass cookbook rule with the 2026-07-09 case |
| No rules for L/R pairs vs junctions, polarity symmetry, rear-fill timing | "Image outranks the crossover above ~300 Hz", top-down alignment, "Polarity belongs to the driver", rear fill 10–20 ms behind at −6..−12 dB |
| EQ never brought a shallow acoustic skirt onto the crossover | Methodology: cut-only skirt correction (Resonalyze: sum loss 0.37 → 0.30 dB, worst dip 2.0 → 1.6 dB over 7 car tunes) |
| EQ objective charged pre-existing depth | `fit_peq(objective='asymmetric', boost_mode='allowed'|'refill'|'off')`, opt-in, tested below |

## EQ objective, held-out test

Synthetic cars: a real fault shared by every seat plus per-seat reflection
combs and cabin modes; fit from one position or the mean of three; scored on
eight unseen positions (60 cars per row).

| Fit from | Objective | Real fault removed | Peak energy removed | Boost | Symmetric unseen gain | Unseen seats worse |
| --- | --- | --- | --- | --- | --- | --- |
| 1 position | symmetric (smoothed) | 0.556 dB | 0.954 | 0.90 dB | 0.509 | 0.73 / 8 |
| 1 position | asymmetric | 0.626 | 1.295 | 0.15 | 0.485 | 1.02 |
| 1 position | asymmetric + refill | 0.411 | 1.814 | 0.30 | 0.613 | 1.65 |
| mean of 3 | symmetric (smoothed) | 0.600 | 1.436 | 2.14 | 0.966 | 0.25 |
| mean of 3 | asymmetric | 0.750 | 1.533 | 0.80 | 0.847 | 0.42 |
| mean of 3 | asymmetric + refill | 0.609 | 1.886 | 0.45 | 0.888 | 0.67 |

Mixed: the asymmetric objective corrects more of what is really wrong, takes
peaks down harder and spends far less headroom, but leaves dips and harms a
few more unseen seats. Kept opt-in, not a default.

## Still open

- **A whole-system virtual sum.** Resonalyze simulates every channel's full
  chain and evaluates every junction and both sides at once. The skill now has
  the per-junction pieces; a side-level simulator that carries one change
  through every junction it touches is the next structural step.
- **Where `.afpx` stores the Phase control**, and whether the P SIX MK2 exposes
  it — needs one controlled diff from the user's PC-Tool.
- **Hybrid sum** (spatial-average magnitude with point phase, summed as
  phasors) for predicting the averaged result of a junction change.
- **Headphone audition** of a predicted tune (convolving music with each
  side's summed response) — useful for judging stage before driving.
