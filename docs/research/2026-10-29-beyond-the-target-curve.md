# Beyond the target curve: what makes a car tune sound good (2026-10-29)

Question: once the system sum sits on the target curve, what else decides
whether a tune sounds good, and which of those things can the skill measure or
help with? Research from published psychoacoustics, a car-cabin perception
study, the EMMA judging rules, and tests on real captures from this repo's
fixtures and the 15 July 2026 session.

Evidence strength is marked on every claim: **strong** (peer-reviewed and
consistent across studies), **moderate** (one study, or a secondary summary of
the paper), **weak** (practice and forum consensus, not tested).

## 1. The short answer

A target curve is a long-term average. What listeners and judges actually
respond to, once the average is right, is:

1. **How each instrument images**: in one place, the right size, at the right
   height. In EMMA's 2024 judge book this is 100 of 310 listening points
   (positions 25, focus 25, distance 15, width 15, height 15, room 5).
2. **Narrow, low-Q peaks left over after the broad fit.** Peaks are far more
   audible than dips of the same size, and broad (low-Q) resonances are audible
   at very small amplitudes.
3. **Bass that arrives with the front stage**: the sub not localising,
   sub/midbass timing, and distortion at the levels actually played.
4. **The listener's own taste in bass and treble.** It varies by more than
   anything EQ corrects: 17 dB of preferred bass level across one panel.
5. **The trade between focus and spaciousness.** Reflections and decorrelation
   widen and brighten the sound but blur the image, and the reverse.

Modal ringing, the usual "tight bass" explanation in rooms, is rarely the limit
in a car: the 15 July sweeps stayed under the published audibility limits at
every resolvable band.

## 2. What the judges and the research measure

**EMMA SQ judge book, 2024 edition** (strong, as a description of what is
scored):

- **Positions (25):** five evenly spaced positions, left, left-centre, centre,
  right-centre and right. Each is tested with five instruments, each in its own
  band: electronic bass 40-100 Hz, electric guitar 100-250 Hz, flute
  250 Hz-1 kHz, celesta 1-2 kHz, triangle 2-4 kHz (and up past 20 kHz).
  "When a tone can be heard in multiple places score 0 points for that
  instrument." The note's attack decides its position.
- **Focus (25):** the right size for each instrument relative to the others:
  electric bass big, guitar smaller, flute smaller again, celesta and triangle
  smallest. Size is not loudness.
- **Stage height (15):** every instrument at eye level, stable from left to
  right, fixed and moving instruments alike. One point off for each instrument
  that leaves eye level anywhere.
- **Distance (15), width (15), room information (1-5):** where the stage
  starts, how far it spreads, and how big a room the recording feels like.
- **Tonal accuracy (4 × 30), spectral balance (30, and 30 again at about
  +6 dB), listening pleasure (30).** The tonal notes name phase problems
  explicitly: an instrument that moves forward or back with frequency, and a
  drum heard from the sub and the midbass at slightly different times.

**Kaplanis et al. 2017, car cabin perception** (Bang & Olufsen with Aalto, KU
Leuven and Aalborg; strong for one car). Expert assessors described 12 cabin
conditions on six dimensions: **bass, ambience, transparency, width and
envelopment, brightness, and image focus.** A reflective glass roof raised
width, envelopment, brightness and transparency but reduced focus (comb
filtering from the extra early reflections). Added absorption made the sound
less ambient, wide and bright but more focused. The windshield and the side
windows mattered, and so did how they interacted. An EQ change that raised width
and brightness also cost image focus.

**Toole 2015 (JAES review)** (strong):

- Three experimentally derived car targets (Olive & Welti 2009, Clark 2001,
  Binelli & Farina 2008) and five luxury cars all boost the bass against road
  noise, and agree closely through the midrange.
- No single target curve satisfies every listener, which argues for easy bass
  and treble controls.
- Untrained listeners chose more bass and more treble than trained ones. In
  the Harman study behind this (Olive, Welti & McMullin 2013; figures from
  secondary summaries, so moderate) the gap was about 1-2 dB of bass and 2-3 dB
  of treble, and preferred bass spanned 17 dB across the panel.

## 3. Tone after the curve

- **Peaks matter more than dips** (strong; Bücklein 1981). A peak is detected
  where an equal dip goes unnoticed, so the final EQ touches are cuts on
  residual peaks. Filling dips adds little, and filling a cancellation adds
  nothing.
- **Broad resonances are the audible ones** (strong; Toole & Olive 1988). The
  detection threshold rises with Q, about 3 dB per doubling of Q. On pink noise,
  low-Q resonances are detectable at fractions of a dB; on continuous music,
  low-Q (below about 10) resonances are the more audible kind, and high-Q ones
  show mainly on transients.
- **Smoothness predicts preference** (moderate for cars). Olive's loudspeaker
  model (2004, 70 loudspeakers in 19 tests) rates a speaker by the smoothness of
  its response and its narrow-band deviation (NBD, the average ripple inside
  half-octave bands), plus bass extension. It was built on anechoic and room
  data, not cars, so in a car it is a ripple measure, not a score.

**On the 14 July captures** (before the final tune was written, so this shows
the method, not a verdict on the current tune): NBD 1.4 dB on the system sum.
Residual peaks above a one-octave trend after level-anchoring to the default
target: **622 Hz +4.1 dB (Q≈7)**, a **1.24-1.45 kHz cluster +1.6 to +2.4 dB
(Q≈4)**, 5.75 kHz +2.3 dB (Q≈5), 315 Hz +2 dB. The deepest dips (437 Hz −7 dB,
1 kHz, 2.3 kHz, 4.7 kHz) are the ones to leave alone until the cancel check
explains them.

## 4. Imaging and focus

- **Panning numbers** (strong). Between two loudspeakers, about 16-18 dB of
  level or 1-1.5 ms of time moves the image fully to one side, and the two
  trade (Sengpiel's curves, Lee & Rumsey 2013; the skill's `image_pull` uses
  16 dB and 1 ms). One dB is therefore about 6% of a half-stage, and 0.1 ms
  about 7-10%.
- **One instrument, one place.** EMMA zeroes an instrument heard in two
  places. Physically that happens when the left/right balance changes
  *within* the instrument's band: the image is then at a different place at
  different frequencies of the same note. The band average can be centred
  while the instrument is smeared.
- **Phase is heard mainly as an image shift** (strong for the one-sided case;
  Møller et al. 2007). An all-pass inserted in one ear's path only moved the
  image once its low-frequency delay difference passed about 30-35 µs, and
  high-Q sections also rang. Applied equally to both sides, phase is much less
  audible (moderate). So keep left/right filters symmetric in phase: a one-sided
  all-pass or delay in the imaging band is an image decision, not a tonal one.
- **Focus versus width** (strong). Lower inter-channel coherence widens the
  image (apparent source width) until it splits in two (Gribben & Lee 2017 and
  others). In a car, early reflections do the same (Kaplanis 2017). Competition
  focus and everyday spaciousness pull in opposite directions; pick on purpose.

**On the 14 July L/R solos** (level only; MMM has no phase), at ERB resolution
in EMMA's bands:

| Instrument band | Mean L−R | 10th to 90th percentile | Widest swing |
|---|---|---|---|
| Guitar 100-250 Hz | +1.5 dB | −2.1 to +7.6 dB | 149 Hz |
| Flute 250 Hz-1 kHz | −1.3 dB | −4.8 to +3.2 dB | 818 Hz |
| Celesta 1-2 kHz | −0.2 dB | −1.8 to +1.7 dB | — tight |
| Triangle 2-4 kHz | +0.3 dB | −2.2 to +4.0 dB | 3.8 kHz |

The centre holds on average in every band. Focus is the risk: the guitar leans
left around 150 Hz, and the flute and triangle swing about ±4 dB around 820 Hz
and 3.8 kHz. Timed sweeps through `pipeline.py imaging --bands emma` add the
time cue that MMM cannot.

## 5. Stage height

- **Pitch-height effect** (strong; Pratt, Roffler & Butler, Cabrera & Tilley,
  Wallis & Lee 2015). Higher frequencies are heard higher. Low-frequency images
  sit near ear height whatever the speaker height; high-frequency images sit
  near the speaker that plays them.
- **Delay cannot move height** (strong; Wallis & Lee 2015). No precedence
  effect was found in the vertical plane, so a delay does not lift the stage.
  Height comes from spectral cues and from which driver plays which band.
- **Overlap scrambles height** (strong). With vertically separated speakers
  playing the same band, localisation in the 1-4 kHz octaves became erratic,
  attributed to comb filtering of the spectral cues.
- **Directional bands** (moderate; Blauert, with individual variation). A
  third-octave band near 8 kHz is heard "above", near 1 kHz "behind", and near
  500 Hz and 4 kHz "in front", wherever the speaker is.

What follows for a tune: the driver mounted high (dash or pillar) should own
everything from a few hundred hertz up, and the low door driver should not
overlap it there. **The 14 July tune has channels 2/3 (80-2600 Hz) and 4/5
(300-2600 Hz) playing the same 300-2600 Hz**: three octaves of overlap. If one
pair sits in the doors and the other on the dash or pillars, that is a likely
cause of a low or unstable stage, and moving the door pair's low-pass down
(towards 300-500 Hz) is the experiment to try. This needs your channel map
confirmed first. A small, broad lift near 8 kHz is a height *variant* to A/B,
not a correction (weak evidence in cars).

## 6. Distance, depth and room

- **Distance cues are level, direct-to-reverberant ratio and spectrum**
  (strong; Kolarik et al. 2016). Spectral cues are only relative. No study found
  supports the "presence dip pushes the stage back" practice: treat it as a
  taste variant.
- In a car, ambience and width come from reflections and from rear fill
  (methodology §Rear-fill: 10-20 ms behind the front, 6-12 dB under it).
  Absorption buys focus at the cost of ambience (Kaplanis 2017).

## 7. Bass quality

- **Modal ringing** (strong; Fazenda, Stephenson & Goldberg 2015). With music,
  a mode's decay is audible above about 0.51 s at 63 Hz, falling to 0.12 s at
  250 Hz; with test tones, from about 0.9 s at 32 Hz to 0.17 s at 200 Hz. **On
  the 15 July sweeps** every resolvable band was under the limit: sub 0.21-0.24 s
  at 63-125 Hz, midbasses 0.09-0.13 s. The right midbass at 250 Hz sat right at
  it (0.13 s against 0.12 s). Below about 50 Hz a third-octave filter rings for
  as long as the decay itself, but the limits there are far above that.
- **Sub localisation** (moderate). In controlled tests a sub went undetected up
  to about 80-120 Hz, depending on placement and listener (Theile 1992 and
  later tests). What gives a rear sub away is content above that: the low-pass
  skirt, rattles, and harmonics.
- **Distortion** (moderate; pure-tone criteria). Fielder & Benjamin 1988: H2
  below about 3%, H3 below about 1%, higher harmonics at or below 0.1-0.3% are
  inaudible. Geddes & Lee 2003: THD itself correlates poorly with what is heard,
  and higher orders count more. **On the 15 July sub sweep** at about 100 dB
  SPL: H2 1.4-2.5% (fine) but H3 up to 1.6% at 50-80 Hz, landing at
  150-240 Hz, where bass localises. That is a plausible reason for a sub to
  drift rearward when played loud, and it is worth checking at the volume
  actually used.
- **Timing** (moderate). A group-delay threshold of about 2.5 ms at 100 Hz,
  roughly doubling in reverberant conditions (Fielder & Benjamin). EMMA names
  the sub/midbass time difference directly; the skill's `junction`,
  `bass-trials` and `mmm-align` cover it.

## 8. The touches, ranked

| # | Touch | Evidence | How to check it with the skill |
|---|---|---|---|
| 1 | Make each instrument band image in one place: fix L/R balance swings *inside* the 100 Hz-4 kHz bands, side-specific cuts only where one side is hot | strong | `imaging --bands emma` (sweeps), `lr-match`, `stereo-propose`; the per-band spread above is not yet a command |
| 2 | Cut residual low-Q peaks after the broad fit; leave dips | strong | `propose`/`refine`; a residual-peak list is not yet a command |
| 3 | Give the high-mounted driver everything above a few hundred Hz; avoid overlapping vertically separated drivers | strong | channel map + `probe` crossover what-ifs; an overlap check is not yet a command |
| 4 | Keep the sub hidden: steep low-pass ≤ 80 Hz, nothing above 120 Hz, H3 under ~1% at your volume, aligned with the midbass | moderate | `capture-audit` (stopbands), `mmm-align`, `bass-trials`, `.mdat` harmonics |
| 5 | Keep L/R filters phase-symmetric in the imaging band | strong | `probe` pairs; one-sided all-pass is an image decision |
| 6 | Voice bass and treble to the listener by blind A/B | strong | `voice-variants`, `ab-make`, `prefs`, `listening-level` |
| 7 | Choose focus or spaciousness deliberately (absorption, rear-fill level and delay) | strong | listening; rear-fill doctrine |
| 8 | Height variant: broad +1-2 dB near 8 kHz | weak | `voice-variants` A/B only |
| 9 | Check bass decay when sweeps exist | strong limits, rarely limiting in cars | `decay.py t20` against the limits above |

## 9. What the skill could add

- **A finishing report**, built in 1.23.0 as `pipeline.py finish`, from whatever exists:
  the residual low-Q peaks after the fit, ranked by audibility (height and Q);
  the per-EMMA-band image balance and its spread (MMM level, or sweep level and
  time); passband overlaps between vertically separated drivers (from the tune
  and the confirmed channel map); sub checks (stopband content above 120 Hz,
  harmonics against Fielder & Benjamin, timing); and bass decay against
  Fazenda's limits. Each item names its evidence level and the command that
  fixes it.
- **A listening checklist** keyed to EMMA's tracks: what each failure sounds
  like, which measurement confirms it, and which command addresses it.
- **Two voicing variants for A/B**: a height variant (8 kHz) and a
  presence-dip "distance" variant, both labelled taste options.

## 10. Fixed while researching

The 1.21.0 `.mdat` reader labelled REW's distortion arrays one or two places
off: the second `harmData` array is the fundamental (it matches the
measurement's own SPL on every file checked), then H2 and up. `mdat.py` now
returns `fundamental`, 2, 3 and so on, and leaves the unidentified first array
out.

## Sources

- EMMA Sound Quality Judge Book, Edition 2024: <https://www.emmanet.info/wp-content/uploads/2024/03/EMMASQJudgebook24.pdf>
- Kaplanis, Bech, Tervo, Pätynen, Lokki, van Waterschoot, Jensen, "Perceptual aspects of reproduced sound in car cabin acoustics", JASA 141(3), 2017: <https://lirias.kuleuven.be/retrieve/489014>
- Toole, "The Measurement and Calibration of Sound Reproducing Systems", JAES 63(7/8), 2015: <https://www.linkwitzlab.com/Toole-Room%20calibration.pdf>
- Olive, Welti, McMullin, "Listener Preferences for In-Room Loudspeaker and Headphone Target Responses", AES 135, 2013: <https://aes2.org/publications/elibrary-page/?id=17042>
- Olive, "A Multiple Regression Model for Predicting Loudspeaker Preference" (Harman patent US 8,311,232 and AES 2004): <https://patents.google.com/patent/US8311232>
- Toole & Olive, "The Modification of Timbre by Resonances", AES 1988: <https://aes2.org/publications/elibrary-page/?id=5163>
- Bücklein, "The Audibility of Frequency Response Irregularities", JAES 1981: <https://aes2.org/publications/elibrary-page/?id=10291>
- Wallis & Lee, "The effect of interchannel time difference on localisation in vertical stereophony", AES 2015: <https://eprints.hud.ac.uk/25888/>
- Lee, ICSA 2015 paper on vertical localisation and the pitch-height effect: <https://eprints.hud.ac.uk/25887/>
- Blauert's directional bands (DAGA 2014 summary): <https://pub.dega-akustik.de/DAGA_2014/data/articles/000035.pdf>
- Sengpiel, localisation curves for level and time panning: <https://sengpielaudio.com/calculator-localisationcurves.htm>
- Møller, Minnaar, Olesen, Christensen, Plogsties, "On the audibility of all-pass phase in electroacoustical transfer functions", JAES 55(3), 2007: <https://vbn.aau.dk/files/227876517/2007_M_ller_et_al_AES_Journal.pdf>
- Gribben & Lee, horizontal and vertical decorrelation and image width, Applied Sciences 2017: <https://eprints.hud.ac.uk/id/eprint/33959/>
- Kolarik, Moore, Zahorik, Cirstea, Pardhan, "Auditory distance perception in humans", 2016: <https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4744263/>
- Fazenda, Stephenson, Goldberg, "Perceptual thresholds for the effects of room modes as a function of modal decay", JASA 2015: <https://eprints.hud.ac.uk/id/eprint/24317/>
- Theile, subwoofer concept listening tests, AES preprint 3335, 1992: <https://hauptmikrofon.de/theile/1992-3_Subwoofer-concep_92.AES-Preprint3335.pdf>
- Fielder & Benjamin, "Subwoofer Performance for Accurate Reproduction of Music", JAES 1988 (summary): <https://stereophile.com/content/science-subwoofing-page-3>
- Geddes & Lee, "Auditory Perception of Nonlinear Distortion", AES 2003: <https://aes2.org/publications/elibrary-page/?id=12465>
