# Your first tune

Use this guide when the DSP is newly installed or you have no measurements yet.
Work through one stage at a time with the assistant. You can begin with a useful
tonal tune from moving-mic captures, then add timed sweeps for alignment. Existing
measurement and tune files go straight to [core workflow intake](core_workflow.md).

## 1. Make the installation ready to measure

Tell the assistant the DSP model, speaker models, which outputs drive which
speakers, source/playback connection, and listening seat. Include whether the
speakers use passive crossovers or individual DSP outputs. If these are unknown,
establish them before playing test signals.

In PC-Tool, using the DSP, amplifier and speaker manufacturers' setup guidance:

1. Save the current setup as a baseline `.afpx` or supported `.pct6`. If you have
   no tune file, save/export the actual installed configuration first; the skill
   works from that file rather than inventing a blank hardware setup.
2. Check input-to-output routing and set protective high/low-pass filters
   appropriate to each driver. Keep passive protection in place. Do not bypass
   filters to obtain a wider measurement or choose crossover frequencies from a
   generic example.
3. At low playback level, identify one output/speaker at a time using a signal
   within its protected passband. Confirm physical left/right and driver identity;
   labels and inferred roles alone are not proof. Restore the intended routing.
4. Centre source balance/fader and disable optional tone controls, loudness and
   playback enhancements. Record any factory processing that cannot be disabled.
   A later [source audit](methodology.md#audit-the-source-before-correcting-the-system)
   checks level dependence; without it, the source remains unverified.
5. Complete the manufacturer's input-sensitivity and amplifier/output-gain setup
   through that configured source path.
   Establish the source's clean volume limit using the specified clipping or
   distortion check, then set DSP input sensitivity and amplifier gain using
   their documented indicators/test procedure. Record the clean limit and chosen
   measurement volume. Do not guess gain positions or use a target curve to
   determine amplifier gain; an acoustic mic alone cannot prove electrical headroom.
6. Save the resulting configuration as a **new baseline file** after these setup
   changes. Keep the original save; all first captures must match the new baseline.

**Ready when:** every output is identified, protection and routing are confirmed,
the system plays cleanly, and the saved file matches the configuration being
measured. If any of those checks fail, resolve them before measuring or EQ.
The skill preserves crossovers in written files; initial crossover setup and any
later recommended crossover/polarity changes are manual PC-Tool steps.
[Audiotec Fischer's setup guide](https://www.audiotec-fischer.de/media/pdf/d3/47/70/ATF_Sound_Tuning_Magazine-DSP_Setup_Guide_Vol1_web.pdf)
provides routing and preparation background; use your particular equipment's
manuals for its limits and gain procedure.

## 2. Connect REW and the USB mic

1. In REW's audio preferences, select the **actual USB mic and its input**;
   do not leave them as the default device. Select the actual output feeding the
   car, and confirm that the test signal follows the intended listening path.
   Record the REW sample rate supported by the devices; this is separate from the
   DSP's internal sample rate.
2. Load the manufacturer's calibration file for that microphone/serial number
   and its orientation. For an upward-facing mic, use the matching 90-degree file
   when provided. Keep aim and calibration consistent, with the capsule around
   normal ear height. A USB-mic calibration containing recognised sensitivity
   data supplies SPL calibration; otherwise follow REW's SPL calibration process
   before relying on absolute SPL.
3. Begin quietly and run REW's **Check Levels** for the intended measurement
   range. Confirm useful input signal without input/output overload. Turn off
   microphone monitoring and optional OS audio enhancements.

If the mic clips or a driver sounds distressed, **stop, lower the test signal and
re-capture**. Do not change DSP gain just to get through a sweep. If the microphone
input itself needs adjustment, use its manufacturer's procedure and record it.
Keep comparable captures at the same playback and recording settings; if a solo
must be quieter, label its test level so the assistant can account for it.

See REW's [device selection](https://www.roomeqwizard.com/help/help_en-GB/html/soundcard.html),
[mic orientation](https://www.roomeqwizard.com/help/help_en-GB/html/gettingstarted.html)
and [SPL calibration](https://www.roomeqwizard.com/help/help_en-GB/html/inputcal.html)
instructions. **Ready when:** the correct calibrated mic records the intended
speaker path cleanly and the settings have been noted.

## 3. Choose the first measurement task

| Start | What it can establish | Capture next |
|---|---|---|
| **Basic tone, bass level and L/R balance** | Broad tonal corrections and measured comparisons of settings | Moving-mic RTA captures below |
| **Full tune including timing and phase** | Driver response, crossover summation and alignment, plus tonal balance | MMM for tone **and** fixed sweeps with a shared timing reference |

MMM contains no phase. Comparing MMM captures of different bass delay/polarity
settings can show which gives a better tonal outcome; it cannot establish an
arrival time, prove phase alignment or locate the stereo image. Use timed sweeps
for those claims. If both methods are available, use MMM as the primary tonal
dataset. See [measurement method selection](methodology.md#measurement-method-selection-sweep-vs-moving-mic-mmm).

## 4. Capture a moving-mic baseline

Park with the engine and HVAC off, in a quiet setting. For a front-stage tune,
mute rear-fill/ambience channels and record that choice. Use REW's **RTA in
1/48-octave mode**, pink periodic noise with sequence length matching the FFT,
and unlimited averaging. Move the mic slowly around the normal head area
(ear to ear, forehead to headrest) for about 30 seconds per capture. Reset
averaging for each new capture. Keep the same path, aim, duration, source volume
and signal level throughout; measure at a clean, comfortable listening level.
Use the RTA's **Save current** button and name the resulting measurement; save the
average rather than the peak trace. See [REW's RTA controls](https://www.roomeqwizard.com/help/help_en-GB/html/spectrum.html).

| Set | Suggested names | Purpose |
|---|---|---|
| **Minimum start** | `System MMM`, `Ambient MMM` (generator off) | Broad system tone assessment and a background-noise check |
| Add for L/R balance | `Front L MMM`, `Front R MMM`, `Front LR MMM` (sub off for all three) | Compare the sides and detect cancellation in their combination |
| Add for bass integration | `Sub MMM`, `Midbasses MMM`, `Sub+Midbasses MMM` (other drivers off) | Separate a bass level problem from destructive summation |
| Add for driver EQ | Named individual driver captures, e.g. `FL Midbass MMM` | Justify channel-specific correction |

One run of each is the normal path. Repeats are optional and help resolve small
changes. A minimum system capture cannot justify individual-driver EQ or a timing
change. For comparing candidate bass settings, also capture the **full system**
at each setting so the unchanged midrange provides a level reference.
The [MMM checklist](methodology.md#mmm-first-tuning-the-short-path-for-tone-bass-level-and-lr-balance)
has the capture profile and detailed settings, including separate playback clocks.

**Ready when:** each trace is named, the active speakers and tune are known,
captures are free of clipping, and the ambient trace is available. The assistant
excludes noise-dominated regions rather than treating them as useful response.

## 5. Add fixed sweeps for timing and phase

Keep the mic stationary at the listening position for an entire comparison set.
With a USB mic, select REW's **acoustic timing reference** in the measurement
dialog. Choose a fixed reference output feeding a speaker capable of reproducing
the high-frequency timing chirp; a subwoofer is unsuitable. Use the **same
reference speaker, routing and timing offset** for all related captures.

Arrange playback so the reference chirp reaches that speaker while the measurement
sweep reaches only the driver or pair being measured. Keep the reference path
available when muting other outputs for solos; do not mute its chirp along with
the unwanted measurement speakers. If the current routing cannot separate these
signals, establish a supported reference path with the assistant before proceeding.
Keep all protective filters active.

Use single sweeps and a suitable range for the protected driver/pair. With separate
USB-input/playback clocks, use REW's **Adjust clock with acoustic ref** option.
Do not use
independently shifted IR peaks or delay estimates to manufacture a common time
reference. Preserve REW's recorded timing and phase. A missing reference,
correlation warning, clipping or clock problem means re-capture before alignment.
See [REW's timing-reference instructions](https://www.roomeqwizard.com/help/help_en-GB/html/makingmeasurements.html)
and [sweep capture checks](methodology.md#sweep-capture-setup-before-you-have-data-to-analyze).

| Set | Suggested names | What it supports |
|---|---|---|
| **Minimum for one crossover** | `FL Mid Sweep`, `FL Tweeter Sweep`, `FL Mid+Tweeter Sweep` | Test that pair's measured summation and alignment |
| Full front stage | Every driver solo, every adjacent crossover pair on each side, relevant L/R pairs, and `System Sweep` | Evaluate all affected junctions and stereo relationships |

Use the same level and fixed mic position within each set. Label any necessary
test-level difference. Additional complete sets at nearby left-ear/right-ear
positions check robustness; each position needs its own consistently referenced
set. If sweeps are also the only tonal data, aim for three positions before EQ.

**Ready when:** the timing reference succeeded on each trace and the assistant
confirms that the solos predict the measured pair sum. Until then, phase edits
remain unsupported. Keep the REW `.mdat` and export text with frequency, SPL and
phase, preserving the timing metadata.

## 6. Tune, re-measure, then finish

Give the assistant the saved tune, named captures, channel map, seat and setup
notes. Confirm the DSP's internal sample rate from its model documentation before
filter modelling or delay conversion; the REW capture rate is not a substitute.
Use the bundled target unless you already have one. Choose its broad tonal balance
before fitting EQ.

Follow [the tune order](methodology.md#tune-order-driver-local-eq-then-alignment-then-system-tone):
correct driver-local faults the solos justify, re-measure, align the corrected
drivers where the data supports it, then make final system-tone adjustments.
For a cancellation that only appears in a sum, use the polarity → delay → all-pass
ladder rather than filling it with EQ. A basic MMM-only session makes supported
tonal/level changes and leaves timing claims open.

Each written edit is confirmed and verified. Apply any proposed polarity or
crossover change manually in PC-Tool, save the resulting tune and re-measure
before the next prediction. Re-capture the same baseline set after loading the
new tune; compare it at matched listening loudness with familiar music.

**A first pass is complete when:** the loaded configuration is saved, measurements
confirm the intended changes within their resolution, and listening supports
keeping them. Note unresolved limitations and stop when the remaining differences
do not justify another edit. A smoother graph alone is not the finish condition.
