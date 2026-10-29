# Case notes

The full, original write-ups behind rules in `helix-rew-tuner/references/methodology.md`, kept for the history: the
dated sessions, the numbers and how each problem was found. The methodology
keeps the rule and its reason; this file is not shipped in the skill package.

## Analysis traps — conclusions that are confidently wrong, not just imprecise

Five more failure modes caught live (2026-07-14) alongside the anchoring trap
above. Each produced a plausible, structured-looking answer that was still wrong —
that's what makes this class of error dangerous: nothing about the *output* looks
broken, only the number underneath it.

**A single-channel cut changes the L+R SUM by only about half its own value.**
Cutting one mid channel by −2 dB drops the summed pair by roughly −1 dB, not −2 —
the other, unchanged channel still contributes to the power sum
(`10*log10(10**(La/10)+10**(Lb/10))`). Never predict a combined-response change
equal to a one-sided filter's own gain. This is also why a one-sided excess (one
channel hot at some frequency) can't be fully flattened in the sum without
over-cutting that channel and wrecking L/R balance — the honest trade is to correct
imaging and accept a partially-reduced sum bump, not chase the sum to zero with an
asymmetric cut.

**Fix the SUM where the sum is wrong, not where a single channel's solo dips.** A
per-channel solo can dip at a frequency where the *summed* response is already
flat, because the other channel fills it. "Fixing" that solo's dip with a boost
then pushes the SUM into a shoulder peak it didn't have before. A real case:
lifting one channel at 1150–1300 Hz (where that channel's own solo dipped) created
+2 dB sum shoulders, because the sum there was already flat — the dip was real but
irrelevant to what's actually heard. Decide tonal corrections from the summed
response; use a per-channel solo only for imaging/imbalance calls, never as the
thing you're flattening.

**Near a crossover, the summed response can wobble session-to-session with no
EQ cause — that's coherence, not level.** Where two channels sum with a
phase relationship sensitive to mic position (a few mm move is a real phase
shift around 800 Hz-1 kHz), the SUM can swing several dB between otherwise
identical repeat measurements while each channel's own solo stays put. A real
case (2026-07-31): confirmed −1.2 dB per-channel solo cuts near 800 Hz produced
only a −0.35 dB sum change, and an untouched neighbor band (1000 Hz) swung
−3 dB between two same-evening sessions with no filter written anywhere near
it. Don't treat a sum deviation in a crossover-adjacent band as actionable from
a single MMM pass — require it to persist across independent sessions (see
Restraint) before writing a fix; a coherence wobble won't repeat, a real
deviation will.

**For L/R balance, compare ABSOLUTE inter-channel level — never each side
self-normalized against its own reference.** Normalizing each channel to its own
target/baseline before comparing "how scooped is each side" can hide or invert the
real difference — this is a distinct trap from the signed-median blind spot
`tune_scorecard`'s `_abs_rms_db` fields catch (Verification & honesty, below); this
one is about which TWO things you're differencing, not how you summarize the
difference. A real case: an own-reference-normalized comparison said one side
needed MORE presence lift; the absolute FR−FL difference showed that side was
already the louder one at 1 kHz, so the proposed lift would have pushed the image
further off-center, not fixed it. `lr_match_report` (Imaging, below) already does
this correctly — raw FR−FL, not two independently-normalized shapes — use it
rather than reconstructing the comparison by hand.

**Sub level couples to the low-mid correction — don't set it from the sub solo in
isolation.** The sub's needed gain depends on the mid/low-mid level it sums against
at the crossover. After cutting a low-mid excess, the sub needs LESS boost to stay
balanced than it did before that cut. Two otherwise-careful analyses of the same
tune disagreed by 1.5 dB on sub gain purely because one measured relative to the
mids before the low-mid cut and one after — both were internally consistent, only
one matched the tune actually being proposed. Model sub and mids together against
the same proposed state, and treat the final half-a-dB or so as a by-ear voicing
call, not a number precise enough to compute past that point.

**When two models disagree about deviation-from-target, arbitrate with an
anchor-independent SHAPE test.** Absolute deviation numbers depend on each model's
normalization/anchor choice, so two internally-correct models can report
contradictory deviations indefinitely. Local shape cannot: reference every value
to a nearby in-band frequency — `delta(f) − delta(f_ref)`, e.g. f_ref = 1300 Hz
for a presence-region dispute — for BOTH the required target delta and each
candidate tune's delivered change. Any model must agree on those numbers, so the
disagreement collapses to checkable arithmetic. A real case (2026-07-17): two
analyses deadlocked over a Harman re-voicing ("your file overshoots +2.9 dB" vs
"yours delivers zero of the required rise") until the shape test showed one file
delivered +4.1 of a required +5.8 dB local rise and the other +0.0 — resolved in
one round, and the overshoot claim traced to a different effective target anchor,
not a real acoustic difference.

**A tune comparison must score the FULL channel state — including output level
(Vol) — not the PEQ set alone.** A file with baked level trims is acoustically
different from one without, even with identical filters; a scorer that reads only
PEQ misjudges headroom, sub/front balance, and target fit. A real cross-audit got
its verdict exactly backwards this way — it ignored `<Vol>` tags and so missed
−1 dB front trims that were the point of the file. Related: keep optimizer
*guardrail* penalties separate from *acoustic* error when comparing candidates
from different systems — a guardrail term can dominate the composite and invert
the acoustic verdict, and different systems' guardrails are not comparable
(one system's guardrail scored 10 of a 17-point total in that same audit).

**Establish that a decoded field is LIVE before reasoning about its value.** A
DSP file stores parameters that the running configuration ignores — leftovers
from whatever the slot was previously set to. Reading such a field and
interpreting its number produces a fully-formed, confident, wrong conclusion,
because nothing about the value itself looks stale. A real case (2026-08-01):
crossover `Fil` tags carried Q=0.7 on the front mids, Q=0.5 on the sub lowpass
and Q=1 on the rears, which "clearly" showed the rears were a different alignment
with a resonant shoulder at the corner. PC-Tool showed all eight channels as
Linkwitz-Riley −24 dB/Oct. The alignment is held in the `<OC>`-level `HPi`/`LPi`
index (identical on every channel); the `Q` only becomes live under a
"Self-define" characteristic. The invented defect survived three consecutive
analyses — an initial read, a second opinion from a different model that accepted
the premise and elaborated on it, and a "verification" pass — because each one
reasoned about *the number* and none asked whether the field was wired to
anything. One glance at the device UI settled it in seconds. Before building an
argument on a decoded value: check whether the software's own display agrees,
prefer a field you have confirmed against that display, and treat an unverified
field as unknown rather than as data. Note this compounds badly with
cross-model review — a second opinion inherits your framing and will confidently
refine a defect that does not exist.

**A magnitude null found in measurement data is not automatically the same
physical thing as a resonance/rattle the user reports by ear or by hand.** Both
can be real, narrow, and centered near the same rough region without being the
same phenomenon — one can be an absorption dip (energy leaving via a mechanically
damped panel) and the other a genuine resonant peak (energy being added by a
vibrating mass), a few tens of Hz apart. Building a correction around the
measured null without confirming its frequency against the user's own independent
evidence (can they reproduce/shift it by touching a specific component? does it
occur without the audio system driving it at all, e.g. from road input alone?)
risks aiming at the wrong target. A real case: a −4 dB EQ cut was built around a
notch found at ~155 Hz; the user later pinned the actual resonance, by manually
manipulating the suspect part, at ~190 Hz — and the tune's *compensating boost*
for the (mistaken) null had been landing almost exactly on the real resonance the
whole time, feeding it. Once independent physical evidence exists, trust it over
the measurement-only guess and re-derive from the confirmed frequency.

**Synthesizing a "what if this physical defect were fixed" response: use
excess-over-broad-trend, not point-to-point interpolation across the feature.**
When modeling a hypothetical future measurement (a resonance eliminated, a
rattle fixed) from today's data, a naive fix — interpolate a smooth curve
between two reference points flanking the defect — is fragile if either
reference point is itself inside another nearby feature (a null, a second
resonance edge); the interpolation inherits that contamination and over- or
under-estimates the effect. More robust: take the raw trace, compute a heavily
smoothed (~1/2-octave) version of the SAME trace as the local "trend," define
excess as raw-minus-trend, and remove only the POSITIVE part of that excess in
the defect's band — since a resonance is fundamentally added energy on top of
the driver's own baseline, not a re-definition of what the baseline is. A real
case: the interpolation-across-two-points method put a resonance's contribution
at 3–4 dB; redone with the excess-over-broad-trend method (same underlying
data) it was 1.6–2.4 dB — enough to flip the right correction from "remove the
existing compensating cut" to "remove it, and the case for adding a small boost
on top is much weaker than it first looked." Bias any decision built on a
synthetic (not yet re-measured) state toward removal/neutral over new boosts —
the smaller the assumed effect, the less a boost's benefit clears the bar of
being worth a write with no confirming measurement behind it yet.

**Measure the capture method's OWN noise floor, then require every band to
clear it.** "Is this deviation real?" has no answer in the abstract — it depends
on how repeatable the measurement is at that frequency, which is a property of
the method, the rig, and the frequency, not a constant. It is directly
measurable whenever two sessions exist with a *known* EQ delta between them
(even a tune change, as long as the change is known): subtract the modelled EQ
delta from the measured difference, remove a broadband offset using a region the
change didn't touch, and whatever residual is left IS the session-to-session
repeatability. Then require a proposed correction to exceed that residual by a
comfortable factor (~2-3x) before spending a filter on it. A real case: MMM
repeatability measured this way came out ~0.1 dB at 400-500 Hz, 0.6-1.0 dB at
700-1400 Hz, 1.0-1.6 dB above 1400 Hz for the midbasses, and 0.23-0.46 dB across
the band for the tweeters — so a 2 dB correction at 1250 Hz was well supported
while a 1.5 dB one at 630 Hz was marginal, a distinction invisible without the
measurement. Expect the floor to WORSEN with frequency for moving-mic captures
(the mic path is never traced identically twice, and path variation matters more
as wavelength shrinks), and watch for a systematic tilt in the residual rather
than random scatter — that indicates level/path drift between sessions, not
noise.

**Don't let a handful of discrete fixed positions overrule a moving-mic average
for tonal decisions.** `spatial_consistency` on 2-3 fixed sweep positions is the
right tool for deciding whether a *phase/crossover* feature is stable, but it is
the WEAKER instrument for tonal calls above a few hundred Hz, and it can flag a
perfectly sound MMM-derived correction as "position-variable." The reason is
sampling density: positions spaced a head-width apart are close enough to sit in
the SAME near-field comb nulls, so their mean is not the spatial average an MMM
capture produces — it is three samples of a comb pattern. A real case: a
3-position mean disagreed with MMM by up to 16 dB above 800 Hz, and flagged two
one-sided cuts as low-confidence (0.05-0.07) — yet MMM's own measured
repeatability at those exact frequencies was +/-0.24-0.56 dB, i.e. the
corrections were supported by 4-8x margin. When the two disagree for a tonal
decision, prefer MMM and use its own repeatability (above) as the noise floor;
reserve the discrete-position spread for what it's actually good at.

**A score gap smaller than measurement repeatability is a tie, not a ranking.**
Two candidates differing by a few tenths of a dB in the summed response, built from
a single MMM run each, are within the run-to-run measurement noise of that capture
method — the "winner" won't survive a re-measure and the gap isn't real signal.
Report a difference that small as a tie and say why, rather than optimizing past
the noise floor or presenting three-decimal scores as if they were decisive. Same
discipline `predicted_vs_measured`'s `consistent_db` tolerance already applies to
the predict-vs-remeasure comparison — crude and directional on purpose, not a
precision instrument.

**A low-SD near-zero mean is a strong, repeatable finding — not a weak or
unreliable one.** `|mean|/SD` is a tempting trust gate across repeated
sessions and a real anti-pattern: a band reading mean=+0.1 dB, SD=0.2 dB
across several independent sessions is *very* stable and nearly balanced,
but a `|mean|/SD`-style gate reads its small mean as low "signal" and can
exclude it from scoring as unreliable — exactly backwards. Repeatability
(how much values scatter session to session) and effect size (how far from
zero the mean is) are different questions; `tunelib.historical_repeatability
(values)` answers them separately and returns `'stable_near_zero'`,
`'stable_nonzero'`, or `'unreliable'` — the last one driven only by SD, never
by a small mean.

**A re-exported or copy-pasted measurement file can silently double-count as
a second independent session**, inflating N and deflating the apparent
spread of a "historical" feature. Before computing any cross-session
repeatability or sign-count, run `tunelib.detect_duplicate_traces(traces)` —
it hashes/compares each trace and groups byte-identical or near-identical
(floating-point round-trip tolerance) captures, which must be counted once,
not once per filename or date.

### Traps caught on an Alpine PXE-X121-12EV session (2026-08-05)

Six more, all from one session, all of which produced confident wrong answers
before being caught. Grouped because they share a root cause: **a summary
statistic hid the shape of the thing being summarised.**

**Band-averaging a deviation across a modal null reads as a LEVEL DEFICIT.**
The most expensive error of that session. A subwoofer's deviation averaged over
25–40 Hz and 40–63 Hz came out −3.3 and −5.1 dB, which reads unambiguously as
"this sub is 5 dB short — raise the gain, and the existing cuts are why it's
short." Point-by-point, the same response was **+9.2 dB at 32 Hz and +5.6 dB at
53 Hz** with deep nulls at 28 and 44 Hz dragging the averages down. The sub was
never short on level; it was peaky, and the inherited filters sitting on those
peaks were doing exactly the right job. Acting on the averaged read meant
proposing to delete filters that were *improving* in-band RMS by 1.2 dB.
**Before concluding "level" from any band-averaged deviation, look at the
point-by-point deviation inside that band.** If it alternates sign by more than
a few dB, it is modal ripple and the average is meaningless — averaging across
a null is arithmetic, not acoustics. Level errors move a whole region the same
direction; ripple does not.

**Judging inherited EQ: check every band against the RAW response before
removing it.** Corollary of the above, and the mechanism that made it costly. A
tune carrying obvious junk (bands outside their own channel's passband,
duplicated bands, +6/−11 dB pairs a few Hz apart) invites the conclusion that
the whole set is junk. It usually isn't: the junk and the real corrections sit
in the same list. Reconstruct the raw (pre-EQ) response — either measured with
EQ bypassed, or by mathematically removing the known filters — and check each
band against it individually. In that session 3 of 11 sub bands were doing real
work on real modal peaks and 8 were inert; a blanket clear got the 8 right and
the 3 badly wrong. **Where the user has captured the same channel both with and
without its EQ, use that instead of any model — it is the only comparison free
of your own filter arithmetic.**

**A CONSTANT offset across the whole band in `interference_audit` is a level
mismatch between captures, not interference.** Real destructive summation is
frequency-dependent — it combs, swinging several dB across an octave. A flat
−6 dB (std 0.36 dB across 3.3 octaves) is a capture-level difference, and the
giveaway is arithmetic: the "pair" trace measuring *quieter than either solo
alone* is physically impossible for any summation. Check the spread of
`interference_db` before interpreting its sign; a low standard deviation across
a wide band invalidates the audit rather than reporting a problem.

**Separate MMM captures are not reliably level-comparable.** MMM level depends
on traverse path, speed and volume, so two MMM runs of different drivers can
differ by several dB for no acoustic reason. This breaks anything that compares
absolute levels *across* captures — `interference_audit` above all, which needs
solos and their pair on a common scale. Comparisons *within* a single capture,
and shape comparisons after level-normalising, remain valid. Plan for it at
capture time: if solos and pairs are both wanted, capture them at the same
master volume in one sitting.

**Fractional-octave summaries misplace narrow features — locate at full
resolution before placing a mask or a filter.** A 1/3-octave view put a
midrange null at "1600 Hz" and invented a dip at "12.7 kHz". At full resolution
the null was at **1908 Hz** and the 12.7 kHz dip did not exist — it was the
1/3-octave bin smearing in the rolloff above 13 kHz. Both errors then propagated:
the mask went in the wrong place, and `fit_peq` was handed a fit region still
containing a −12 dB null it could not fix. **Use fractional-octave views to
notice that something is there; use the full-resolution trace to decide where
it is.**

**`fit_peq` returning ZERO bands on an obviously-wrong channel means your mask
or fit band is wrong — not that the thresholds need loosening.** Twice in one
session. Once because an unmasked −12 dB null dominated the error so no cut
could clear the improvement gate; once because the fit band included the
crossover skirt. The parsimony gate is doing its job in both cases. The correct
response is to fix the region you handed it, then re-fit. **Never respond by
lowering `improve_pct` or `min_gain` to force an answer out** — that converts a
diagnosable input error into filters nobody can justify.

**Never include a crossover skirt in a fit band.** Given 22–80 Hz on a channel
low-passed at 60 Hz, `fit_peq` (boosts allowed) returned **four identical +4 dB
bands stacked at 76 Hz** — 16 dB of boost trying to undo the low-pass, because
the skirt reads as deviation-from-target like anything else. Fit only over the
range where that driver is the dominant contributor, well inside its own
passband. An output that stacks multiple same-frequency bands is the signature
of this error and should never be written.

## REW's IR-delay estimator can lock onto the wrong cycle on a band-limited driver

On a driver with a steep high-pass (a tweeter above its crossover corner, in
particular), REW's "estimated IR delay" figure can jump between two (or more)
discrete values roughly `1 / f_passband_centre` apart between otherwise-
identical repeat captures. Nothing physically moved; only the estimator's
cycle-lock did.

**Signature, confirmed by an 8-repeat controlled test (nothing touched between
captures):** the reported delay clustered on exactly two values —
`7.017, 7.018, 7.019, 6.579, 6.574, 6.579, 7.019, 7.018` ms — a 0.439 ms gap,
matching `1/2278 Hz` almost exactly, sitting inside that tweeter's crossover
region. Within either cluster the spread was 1–5 µs (real repeatability);
across the two clusters it looked like a 0.44 ms "timing failure."

**How to tell the estimator from a real timing problem — this is the decisive
test, not eyeballing the impulse plot.** Fit a delay to the PHASE DIFFERENCE
between one capture from each cluster (linear regression of
`unwrap(angle(B/A))` vs. frequency, over a band where both captures have real
energy). On the same 8-repeat set this returned an implied delay of
`0.0000 ms` (residual ~18°) between a "6.58 ms" capture and a "7.02 ms"
capture — the underlying phase-valid data was unaffected the whole time; only
the single scalar REW reports in the header/sidebar was jumping.

**Practical rule:** never trust a single reported REW delay number for a
band-limited driver, especially a tweeter above its own crossover corner.
Either (a) take multiple repeats and check for a small-integer-multiple-of-a-
cycle relationship between clustered values before drawing any conclusion, or
(b) skip the reported number entirely and work from the exported complex data
(phase-slope delay, or the algebraic recovery below) instead.

## Recovering per-channel L/R responses from a common-source pair, without solo captures

If the DSP allows toggling one channel's polarity, two captures — `N = L + R`
(normal) and `V = L − R` (one channel inverted) — algebraically recover BOTH
individual channel responses with no solo measurements at all:

```
L = (N + V) / 2
R = (N − V) / 2
```

This holds exactly for any linear system, as long as N and V share a common
time reference (so they're complex-comparable) and nothing else changed
between the two captures.

**Always validate the recovery before trusting it downstream** — reconstruct
L (or R) and compare it against an independently, directly measured solo of
that same channel, if one exists anywhere in the project (a different
session, a different day — fine, as long as that channel's crossover/EQ
hasn't changed since). A real case: this technique validated to 0.01–0.26 dB
median error against independent solos across four separate recovered-channel
vs. independent-solo comparisons in one project, which is what made every
subsequent phase and level conclusion drawn from the recovered channels
trustworthy rather than assumed.

Useful when solo captures weren't taken, when re-measuring solos would cost
too much session time, or — as in the imbalance case below — as a
cross-check that builds multi-session confidence in a finding alongside
directly-measured solos.

**Validate OUTSIDE the recovered channel's expected passband too, not just
inside it.** A recovered low-passed driver (a sub, from an N/V decomposition)
can carry substantial spurious energy far above its real crossover — the two
source captures' shared noise floor doesn't fully cancel in the subtraction,
and dividing by 2 can still leave a "signal" within a few dB of whatever
else you're comparing it against. On a real project this showed up as a
recovered sub reading nearly as loud as the mids at 6–19 kHz, a decade above
its LR24 low-pass — obviously not real, but only obvious once someone
printed the level there. See the next section for the real downstream damage
this specific artifact can do to a candidate-finder function that isn't
expecting it.

## When `polarity_delay_search` says "nothing to gain," run `delay_sweep` (and how this was actually found)

**Real case (2026-08-08).** `polarity_delay_search` on a sub/mids pair,
target band 40–140 Hz, reported `delay_ms_B: 0.0, improvement_pct: 0.0`. That
was taken at face value — "sub timing is already optimal, nothing to gain" —
and told to the user as such. **This was wrong, and it wasn't caught by
re-examining the tool. An independent second opinion (a different AI, given
the same measurement files) computed its own delay sweep from scratch using a
different scoring method — direct coherent-summation gain, weighted toward
frequencies where BOTH drivers actually overlap in level, checked for a
"maximin-robust" optimum across two separately-captured sessions — and
proposed a specific non-zero delay with the reasoning laid out.** Reproducing
that computation confirmed a real, small (0.1–0.7 dB depending on band and
weighting), reproducible gain that `polarity_delay_search` had missed, and it
went on to be confirmed by an actual A/B measurement in the car.

**`tunelib.delay_sweep` / `overlap_weighted_delay_gain` package that exact
method** (added after this happened, so it's a one-line call next time
instead of needing a second opinion to surface it):
`delay_sweep(freqs, driver_a, driver_b, band, datasets=[...])` scores every
candidate delay by coherent-sum-vs-power-sum gain inside `band` ONLY — no
cross-band safety term at all — weighted by `min(|a|,|b|)**2` so frequencies
where one driver dominates and the other is negligible don't dilute a real
in-band gain toward zero. Pass other independently-captured `(freqs, a, b)`
tuples via `datasets=` for the maximin-across-sessions check: it returns the
delay whose WORST-case gain across every dataset is highest, so a delay that
only helps one session doesn't get recommended. It also flags `ambiguous`
when a near-equal second local maximum sits more than half a wavelength away
from the best one — the same cycle-slip signature documented above for REW's
own delay estimator, now checked automatically instead of by eye.

**Only after this was fixed did it become worth asking WHY the original tool
missed it** — that's a separate, useful diagnosis, not the discovery itself.
`polarity_delay_search`'s default `damage_band=(60, 16000)` Hz penalizes any
candidate delay that makes the ORIGINAL full-range sum worse anywhere across
that whole span — a sensible safety net for a genuine full-range vs.
full-range comparison (mid vs. tweeter), but most of that span is pure
measurement noise floor, not signal, for a low-passed driver like a sub.
Splitting the function's own score into its two summed terms confirmed this
directly: the in-band `gap` component *did* fall substantially moving away
from 0 ms, but the full-range `damage` term swung by roughly 4x more over the
same move, swamping it. Traced to source: at 6–19 kHz the sub input carried
energy within a few dB of the mids' own level — pure noise floor, confirmed
on both a directly-measured sub solo and an independently N/V-recovered one
(see the decomposition section above), so it's a property of any band-limited
driver's capture, not specific to the decomposition technique. Narrowing
`damage_band` to the sub's real electrical passband (20–200 Hz) recovered a
sensible, non-zero answer from `polarity_delay_search` too, in reasonable
agreement with `delay_sweep`'s result on the same data.

**Rule: don't accept a candidate-finder's "nothing here" verdict —
especially `improvement_pct` landing suspiciously exactly at 0.0 — as
evidence the acoustics are already optimal. It's evidence the SCORE didn't
move, and a score can fail to move for reasons that have nothing to do with
the acoustics.** Run `delay_sweep` alongside `polarity_delay_search` whenever
either driver is band-limited (a sub, in particular), and treat a flat 0.0%
from the latter as a prompt to check the former, not as a closed question.

## Bracket every A/B write A→B→B→A, and anchor on a band the write structurally cannot touch

Any two-state comparison (tune A vs. tune B) that spans more than a couple of
minutes is vulnerable to session-level drift — playback level creeping,
auto-gain re-engaging, a physical connection changing — large enough to dwarf
the effect being measured. Two defenses, used together:

**Bracket, don't just A→B.** Capture order `A, B, B, A` (or `A1, A2 … B1,
B2 … A3`), not just `A, B`. If the two `B` captures agree, and the closing `A`
disagrees with the opening `A` by more than that, the session drifted — caught
DURING the session instead of discovered afterward. A real case (2026-08-08):
a delay-write A/B test showed a monotonic +2.7 dB broadband level rise across
~4 minutes (`A1 → A2 +2.6 dB`; a control solo capture the write couldn't
possibly touch also drifted +0.85 dB, flat across frequency — pure gain
drift, not a response change), caught immediately by comparing the two
nominally-identical control captures.

**Anchor on a band the specific write is physically incapable of altering,
then re-derive the result relative to that anchor.** A pure delay or a pure
all-pass filter is magnitude-flat by construction on the channel it's applied
to — it changes phase only, never that channel's own SPL at any frequency.
That gives two free, zero-cost checks for any delay/APF write:
- The edited channel's own solo capture, before vs. after, must be
  magnitude-identical. If it isn't, something in the measurement chain moved
  — not the filter.
- Any frequency band where the edited channel doesn't dominate the trace
  (below its own crossover corner, or a different channel's passband
  entirely) is a valid drift anchor: re-reference every capture in the
  session to its OWN level in that band before comparing anything else.

Applied to the +2.7 dB drift above: anchoring every capture on 300–2000 Hz (a
band the sub-delay write couldn't reach — the sub is low-passed well below
it) collapsed the drift and recovered clean 0.07–0.11 dB repeatability,
revealing a small (~0.2–0.6 dB) real, repeatable, correctly-signed gain that
the raw numbers had made look unusable.

## Common-mode (System Sum vs target) is a first-class objective, not a fallback

It's easy for a tuning session to drift into scoring only L/R differential error,
because that's usually where the interesting/actionable findings show up early and
because most of the diagnostic tooling here (`tune_scorecard`, delay/EQ candidate
search) is framed around per-channel or per-pair comparisons. But the tonal-target
objective (System Sum vs the reference curve) is an equally valid, independent axis,
and a long L/R-focused investigation can leave it completely unscored for weeks
while genuinely large, genuinely repeatable common-mode errors sit untouched. A real
case (2026-08-09): after an entire multi-week campaign optimizing 4-14 kHz L/R
balance down to parity with the rest of the spectrum, scoring System Sum vs target
for the first time turned up a **+2.5 dB excess at 100 Hz with SD 0.2 dB across
four sessions spanning three different tune states** — more repeatable than any L/R
feature found in the whole project, sitting in a region nobody had looked at because
all recent attention was on the region that had, ironically, already been leveled.
Common-mode corrections are lower-risk than differential ones (identical filter on
both channels of a pair leaves R−L mathematically unchanged, so they can never
undo differential work), which makes neglecting this axis doubly wasteful. **When a
tuning investigation has been running on one axis (L/R, a single band, a single
driver pair) for several sessions, periodically re-score the other axis (System
Sum vs target) from scratch** rather than assuming it was already covered earlier
in the project.

**Caveat added 2026-08-10, from the very next thing that went wrong with this
advice: a System Sum deficit is not automatically evidence of a common-mode
cause.** A stable ~5 dB System Sum shortfall around 7 kHz (SD 0.11 dB across three
sessions — by the standard above, an extremely trustworthy number) was one step
from becoming a common-mode boost proposal (`+6 dB`, high Q, on both tweeters).
Nearfield captures on both tweeters showed the deficit was **entirely one driver**:
present in the left tweeter's own nearfield response (−5.05 dB, matching the seat's
−5.09 dB to 0.04 dB) and **absent in the right's** (+0.09 dB). The total-sum number
was real and repeatable; the mechanism it implied was wrong. **Before labeling any
System Sum deficit "common-mode," inspect the contributors** (L and R separately,
or the relevant driver pair) to confirm they actually share the deficit. A total
that's low can be low because both sides are low equally, or because one side is
very low and the other is fine — only the first case is a common-mode filter
candidate. See also "Nearfield claim ceiling" and "Deep/narrow notch boost
guardrail" below, which cover what to do once contributor inspection finds a
source-local cause instead.

## Fixed mic vs MMM is a second, orthogonal authority question — "what to fix" vs "did it land"

The existing "Measurement method selection" section (sweep vs MMM) answers *which
method is authoritative for a given research question*, but it doesn't cover a
distinction that caused a real, fully-formed wrong conclusion: **MMM and a fixed
mic answer different questions, and using MMM for the wrong one produces confident,
specific, wrong answers — not just noisy ones.**

**MMM answers "what should be fixed?"** — tonal balance, L/R spectral balance,
System Sum vs target: anything where the listening objective is inherently spatial.

**A fixed mic answers "did a known DSP change actually land?"** A filter is an
electrical fact that applies identically at every point in the cabin, so verifying
it needs *repeatability*, not spatial averaging. If the acoustic path is `R(f)`
and the pre-change source response is `S(f)`, then `A = R·S`; if the change adds a
known transfer `H`, then `B = R·H·S`, so with the mic and everything else
unchanged, `B/A = H` exactly — the room response and any unchanged crossover
cancel in the ratio. MMM's spatial averaging doesn't get you anything extra for
this question and costs you the one thing you need, which is a low noise floor.

**Real case (2026-08-10), the full failure chain:** a `100 Hz / Q4 / −1.5 dB`
band was added to a sub channel low-passed at 80 Hz. An MMM solo A/B suggested the
sub delivered only ~19% of the intended cut. That was treated as a real finding,
which led to inventing a mechanism ("PC-Tool silently clamps/rejects a PEQ whose
centre lies outside the channel's own passband") to explain it. **Both halves were
wrong.** A PC-Tool screenshot showed the band present and enabled. A fixed-mic
A/B (mic on a tripod, untouched between captures) measured **−1.53 dB against
−1.50 dB predicted, 95% delivered, with an untouched control band at +0.02 dB** —
the implementation was correct the entire time. The MMM result was noise: the
project's own measured low-frequency MMM path variance that day was ~0.8–0.95 dB,
comparable to the 1.5 dB effect being measured.

**Rule:** for "did the write land?", use a fixed mic (tripod, untouched between
captures, ideally A→B→B→A), compare the whole measured B−A transfer against the
exact predicted transfer, and do not infer a routing/tool/DSP fault from an MMM
result unless the effect is far above MMM's *measured* (not assumed) variance for
that band. If a fixed-mic check is unavailable, label the finding "unresolved,"
not "the filter didn't land."

## Prediction and measurement must go through the identical operator

Comparing a raw filter transfer to a *processed* (smoothed, baseline-fit,
prominence-scored) measurement is not apples-to-apples, and the direction of the
resulting error is not obvious in advance.

**Real case 1 (2026-08-10):** a `100 Hz / Q4.0 / −1.5 dB` filter's raw centre
depth is −1.50 dB. Comparing that raw number to an ERB-smoothed measured change
made the measurement look like it delivered only 51% of the filter (measured
−0.58 dB vs "predicted" −1.15 dB, itself already a robust-regression operator
applied only to the raw filter). Running the *filter* through the *same* ERB
smoothing before comparing gives −0.84 dB predicted — the measurement then lands
at 69% with the residual gap inside the pair-to-pair repeat spread. The 51%
number implied a real, physically impossible anomaly (a uniform electrical cut
cannot be diluted by spatial averaging — if a filter attenuates by 1.5 dB at every
point, the power average over any set of points also drops by 1.5 dB); the 69%
number showed there was nothing to explain.

**Real case 2, same day, opposite direction:** an `8000 Hz / Q12 / −3 dB` filter's
measured effect at 8 kHz (−1.87 dB) was compared to its raw −3.00 dB prediction and
described as "shallower than predicted, consistent with 1/3-octave smoothing" —
directionally reasonable-sounding, but never actually computed. Running the
predicted transfer through the same 1/3-octave smoothing gives −1.20 dB — the
measurement in fact *exceeded* the (correctly processed) prediction. The hand-wave
had the right instinct and the wrong sign.

**Rule:** whenever a predicted transfer will be compared to a measurement that has
been smoothed, baseline-fit, or scored by any custom operator, run the *predicted*
transfer through the *identical* operator before comparing. This risk is largest
exactly where it's easiest to overlook: when the filter's own bandwidth is
comparable to or narrower than the operator's effective bandwidth (ERB widens
in absolute Hz at low frequency, so even Q3–5 filters below ~200 Hz are affected;
narrow high-Q HF filters like `Q12` are affected by any octave-fraction smoothing).
`erb_smooth()` and any 1/N-octave smoother in this toolkit apply equally to a
synthetic filter-response curve as to a measured one — use them on both sides of
a comparison, never one side only. See `models_discriminable()` for the related
rule about comparing residuals computed on inconsistent bases.

## Rear-fill / ambience channels need their own measurement discipline

Rear-fill (or any channel deliberately fed a differential/ambience signal rather
than full programme content) breaks two assumptions the rest of this methodology
otherwise takes for granted.

**The test stimulus is not representative of normal listening level.** An
antiphase or differential test WAV used to get usable SNR out of a low-level
ambience channel can be far louder, at that channel, than the channel ever plays
during normal music. **Real case (2026-08-10):** rear channels were deliberately
driven hard for measurement; the user flagged unprompted that this did not
represent normal playback level. Shape and L/R-matching conclusions from such a
capture remain valid (each channel normalized to its own in-band mean cancels the
level); absolute rear-to-front level or "how audible are the rears" conclusions
do not, and must not be drawn from a diagnostic-level capture.

**A channel can have an objective matching problem with no declared target.**
Rear fill usually has no tonal target curve (the front-stage/system target isn't
the right reference for an ambience channel), but that doesn't mean nothing is
measurable. **Real case, same session:** both rear drivers shared the same raw
two-lobe response (~1130 Hz and ~1550 Hz peaks). The left channel had a filter
correcting both lobes; the right had only one, leaving a structural, asymmetric
gap that showed up as the single largest rear L/R error (+3.9 dB at 1140 Hz).
Adding the missing filter to the right channel only, and verifying with the
**untouched left channel as a same-sitting control**, closed the gap (R−L at
1140 Hz: +3.9 → +0.1 dB; untouched-channel control drift: 0.34 dB). This is a
useful general pattern for any one-sided correction, not just rears: change one
side, leave the other alone, and use the unchanged side's movement as the
uncertainty floor for the same session — cheaper and more direct than borrowing
a floor from elsewhere.

**What matching does not settle:** after the two channels were matched, both still
carried the same ~4 dB *common* elevation across that region. That is a voicing
question (rear ambience is deliberately not full-range-flat and has no declared
target), not a matching one, and — per the diagnostic-level caveat above — the
capture used to find the matching gap is not the right basis for a common-mode
voicing decision either. Leave common rear voicing to normal-level listening
unless a specific target philosophy is declared for the rear channels.

**Rear-fill timing and level.** Rear fill should arrive BEHIND the front stage,
not with it: on top of the delay that makes the nearer rear speakers co-arrive,
roughly 10–20 ms later lets the rears add space while the precedence effect keeps
the image on the dashboard (use ~0 ms only when second-row listeners matter
more). Set its level by ear at normal listening level, not from a diagnostic
capture: start 6–12 dB under the front, raise it until it becomes audible as a
separate source, then back off 2–3 dB. Time a rear or centre against the ONE
front driver that plays most of the 1–4 kHz voice band (usually the midrange),
not against the summed front stage — a band-limited arrival of a sum is the
arrival of whichever driver plays earliest in that band.
