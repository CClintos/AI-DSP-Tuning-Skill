# Your first tune

Use this guide when the DSP is newly installed or nothing has been measured yet.
Work through one stage at a time with the assistant. A useful tonal tune comes
from moving-mic captures alone; timed sweeps add alignment later. Existing
measurement and tune files go straight to [core workflow intake](core_workflow.md).

## 1. Make the installation ready to measure

Tell the assistant the DSP model, speaker models, which outputs drive which
speakers, the source and how it connects, and the listening seat. Say whether
the speakers use passive crossovers or individual DSP outputs. If any of these
are unknown, establish them before playing test signals.

In PC-Tool, following the DSP, amplifier and speaker manufacturers' setup
guidance:

1. Save the current setup as a baseline `.afpx` (or a supported `.pct6`). With
   no tune file yet, save the installed configuration first: the skill works
   from that file and never invents a blank hardware setup.
2. Check input-to-output routing and set protective high- and low-pass filters
   suited to each driver. Keep passive protection in place. Never bypass a
   filter to get a wider measurement, and never take crossover frequencies from
   a generic example.
3. At low level, identify one output at a time with a signal inside its
   protected passband. Confirm physical left/right and driver identity: labels
   and inferred roles are not proof. Restore the intended routing.
4. Centre balance and fader, and turn off tone controls, loudness and playback
   enhancements. Note any factory processing that cannot be turned off; a later
   [source audit](methodology.md#audit-the-source-before-correcting-the-system)
   checks level dependence, and until then the source is unverified.
5. Set input sensitivity and amplifier gain with the manufacturers' procedure
   through this source path: find the source's clean volume limit with their
   clipping or distortion check, then set the DSP input and amplifier gains by
   their indicators. Record the clean limit and the measurement volume. Never
   set gain by ear or from a target curve; an acoustic mic cannot prove
   electrical headroom.
6. Save the result as a **new baseline file** and keep the original. Every
   first capture must match this new baseline.

**Ready when:** every output is identified, protection and routing are
confirmed, the system plays cleanly, and the saved file matches what is being
measured. The skill never writes crossovers: initial crossover setup, and any
crossover or polarity change it later recommends, are manual PC-Tool steps.
[Audiotec Fischer's setup guide](https://www.audiotec-fischer.de/media/pdf/d3/47/70/ATF_Sound_Tuning_Magazine-DSP_Setup_Guide_Vol1_web.pdf)
covers routing and preparation; your equipment's manuals set its limits and
gain procedure.

## 2. Connect REW and the USB mic

1. In REW's audio preferences, select the **actual USB mic and its input**, not
   the default device, and the output that feeds the car. Check that the test
   signal takes the intended listening path. REW's sample rate is a property of
   the sound devices, not the DSP's internal rate.
2. Load the manufacturer's calibration file for that mic's serial number and
   orientation (the 90-degree file for an upward-facing mic, when provided).
   Keep aim and calibration the same throughout, with the capsule at about ear
   height.
3. Start quietly and run REW's **Check Levels**. Confirm a useful input level
   with no input or output overload. Turn off mic monitoring and OS audio
   enhancements (Windows Loudness Equalization, for example).

If the mic clips or a driver sounds distressed, **stop, lower the test signal
and capture again**. Never change DSP gain just to get through a capture. Keep
every capture of a set at the same playback and recording settings.

REW's help covers [device selection](https://www.roomeqwizard.com/help/help_en-GB/html/soundcard.html),
[mic orientation](https://www.roomeqwizard.com/help/help_en-GB/html/gettingstarted.html)
and [SPL calibration](https://www.roomeqwizard.com/help/help_en-GB/html/inputcal.html).
**Ready when:** the correct, calibrated mic records the intended speaker path
cleanly and the settings are noted.

## 3. Choose the first measurement task

| Start | What it can establish | Capture |
|---|---|---|
| **Tone, bass level and L/R balance** | Broad tonal corrections, bass level and alignment choices compared by tone, L/R tonal match | Moving-mic (MMM) RTA captures, stage 4 |
| **Full tune including timing and phase** | Driver responses, crossover summation and alignment, image position, plus tone | MMM for tone **and** fixed sweeps with a shared timing reference, stage 5 |

MMM carries no phase. Comparing MMM captures of different delay or polarity
settings shows which sounds better tonally (`mmm-align` predicts it from four
captures); it cannot measure an arrival time or locate the image. Use timed
sweeps for those. When both exist, MMM is the primary tonal data. See
[measurement method selection](methodology.md#measurement-method-selection-sweep-vs-moving-mic-mmm).

## 4. Capture a moving-mic baseline

Ask the assistant for the plan first: `pipeline.py capture-plan --goal tone lr
bass` (add `--afpx <tune>` once a tune file exists). It prints the capture
names, the REW settings (RTA 1/48 octave, pink periodic noise at the FFT
length, averages for the capture length), your mic's level ceiling and the
order. The usual set:

| Set | Names `capture-plan` uses | Purpose |
|---|---|---|
| **Minimum start** | `System Sum`, `Ambient moving` (generator off) | System tone, and the noise floor every finding is checked against |
| Add for L/R balance | `Front L`, `Front R`, `Front Both` (sub off) | Compare the sides and find cancellation between them |
| Add for bass | `Sub`, `Midbass Both`, `Sub Midbass Both`, and one with a known temporary midbass delay | Bass level against cancellation, and the sub/midbass alignment `mmm-align` predicts |

Park with the engine, fan and HVAC off, doors and windows closed. Mute
rear-fill channels for a front-stage tune and note it. Move the mic slowly
through the head space of the seat being tuned (ear to ear, forehead to
headrest) for the whole capture; reset averaging for each capture and never
touch the volume within a set. Undo any temporary delay the plan asks for
before anything else.

One run of each is the normal path; a repeat helps resolve small changes. A
system capture alone cannot justify a driver's own EQ or a timing change. The
[MMM checklist](methodology.md#mmm-first-tuning-the-short-path-for-tone-bass-level-and-lr-balance)
has the details.

Then hand the files, a folder or the whole `.mdat` to `pipeline.py next
--captures <them>`. It audits each capture from its own header (length,
movement noise, mic clipping, smoothing, mixed settings, triples played at
different levels) and lists the commands that apply, with arguments filled in.

**Ready when:** each capture is named, the tune loaded during it is known, the
audit shows no problem that blocks it, and the ambient capture exists.

## 5. Add fixed sweeps for timing and phase

Keep the mic still at the listening position for a whole comparison set. With
a USB mic, choose REW's **acoustic timing reference**: a fixed reference output
on a speaker that reproduces the high-frequency timing chirp (never a sub), the
same reference speaker, routing and offset for every related capture. Keep the
reference chirp playing when other outputs are muted for solos. If the routing
cannot separate the chirp from the measured driver, sort out a reference path
with the assistant first. Keep all protective filters on.

With separate USB-input and playback clocks, use REW's **Adjust clock with
acoustic ref**. Never shift impulse peaks by hand to manufacture a common time
base. A missing reference, correlation warning, clipping or clock problem
means capture again. See REW's [timing-reference instructions](https://www.roomeqwizard.com/help/help_en-GB/html/makingmeasurements.html)
and the [sweep capture checks](methodology.md#sweep-capture-setup-before-you-have-data-to-analyze).

| Set | Suggested names | Supports |
|---|---|---|
| **Minimum for one crossover** | `FL Mid Sweep`, `FL Tweeter Sweep`, `FL Mid+Tweeter Sweep` | That pair's summation and alignment |
| Full front stage | Every driver solo, each adjacent crossover pair per side, the L/R pairs, `System Sweep` | Every junction and the stereo image |

Export text with frequency, SPL and phase (or keep the `.mdat`). **Ready
when:** the timing reference succeeded on every trace and the solos predict
the measured pair sum. Until then, phase edits stay unsupported.

## 6. Tune, re-measure, finish

Give the assistant the saved tune, the captures, the channel map, the seat and
your notes. Confirm the DSP's internal sample rate from its model documentation
before any filter modelling or delay conversion; REW's capture rate is not a
substitute. Use the bundled target unless you have one, and choose its broad
balance before any EQ is fitted.

Follow [the tune order](methodology.md#tune-order-driver-local-eq-then-alignment-then-system-tone):
driver-local faults the solos justify first, re-measure, alignment where the
data supports it, then system tone. A cancellation that only appears in a sum
gets the polarity, delay, all-pass ladder, never an EQ boost. Every written
edit is confirmed by you first and verified after writing; apply any
recommended polarity or crossover change yourself in PC-Tool, save, and
re-measure before the next prediction.

After each written change, capture the same set again with the new tune loaded:
`pipeline.py verify` checks each change landed as predicted. Once the system
sum sits on the target, `pipeline.py finish` lists what still decides the
sound: the last broad peaks, whether each instrument images in one place, stage
height and the hidden sub ([finishing touches](methodology.md#finishing-touches-after-the-curve)).

Then listen. The EMMA listening sheet (`assets/emma_listening_sheet.html`, open
it in any browser, phone included) follows the 280-point scoresheet: score your
own listening, or copy a judge's sheet into it, and export the JSON. `finish
--heard <that file>` puts each lost point next to the measurement that explains
it and the command that addresses it.

**A first pass is complete when:** the loaded tune is saved, re-measures
confirm the changes within their resolution, and blind, level-matched listening
supports keeping them (`ab-make`). Note what is unresolved, and stop when the
remaining differences do not justify another edit. A smoother graph alone is
not the finish line.
