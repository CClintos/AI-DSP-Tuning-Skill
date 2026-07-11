# Helix / Audiotec Fischer DSP hardware notes

Reference for filter capabilities and limits. Verified against DSP PC-Tool 4 for
the P SIX DSP MK2; most applies across the Helix DSP line, but confirm limits for
the specific model when in doubt (they're in that model's PC-Tool).

## EQ / filter modes (PC-Tool 4)

Four per-band EQ modes: **Parametric**, **FineEQ**, **Allpass**, **Shelf**.

- **Parametric / FineEQ PEQ**: Q range **0.5–15**.
- **All-pass**: 1st order (90° at corner, no Q) or 2nd order (180° at corner).
  **Q range CORRECTED 2026-07-11**: earlier documentation here claimed a hard
  0.5–2 hardware ceiling — that was wrong. A real PC-Tool screenshot shows Q=9
  accepted and displayed (Band 14, 420 Hz, 2nd order). Don't tell a user a
  high-Q APF is illegal or will get clamped — it won't. High Q is often the
  *correct* choice for a narrow null: it confines the phase rotation to the
  target frequency instead of spilling a broad correction into neighbouring
  bands (a low-Q APF aimed at a narrow null can create a new, broader hole
  elsewhere as its own tradeoff). The real cost of high Q is **group delay /
  transient ringing**, not legality — evaluate that directly (`tunelib.
  group_delay_ms_from_H`, and for an L/R pair `interaural_group_delay_ms` —
  see methodology.md's All-pass cookbook) rather than treating Q itself as the
  risk metric. AF's own guidance that "Q above 1.5 is rarely used" is a style
  note about typical taste, not a hard limit.
- **Shelf**: first band (25 Hz) = low shelf, last band (20 kHz) = high shelf; the
  **Q (0.1–2) IS the slope** (no separate S parameter). Shown green in PC-Tool.

## Hardware gain ceiling

**+6 dB max boost, −15 dB max cut, per band** (applies even in Parametric mode).
`tunelib.validate_peq_band` enforces −15…+6 and Q 0.5–15.

- Stacking multiple bands at the **same** frequency is fine and even recommended for
  deep **cuts** (e.g. killing a resonance), but **never for boosts** — same-frequency
  boosts compound fast into digital clipping. Same-frequency cuts are unproblematic.
- PC-Tool's slider step is 0.25 dB — write gains as clean 0.25 multiples so they
  don't snap on next open.
- Always run `tunelib.headroom_report` on the final per-channel PEQ stack; if the
  cascade peak risks clipping, recommend an output-level trim.

## Crossovers

Butterworth / Bessel / Tschebyscheff / Linkwitz / Self-Define characteristics,
slopes up to −42 dB/oct (64-bit DSP units — internal sample rate varies by model,
see Delay & polarity below). **Leave crossovers alone unless the user explicitly
asks to change them** — a crossover change needs live re-measurement to validate
and is outside the safe auto-write path.

## Delay & polarity

Per-channel delay in samples. Delay writes are lower-risk than all-passes but
should still be **user-initiated for that specific change, every time**, not
auto-written from a search result, and always **verified by re-measure** after.
`afpx.write_delay_samples`/`afpx.verify_delay_write` make the write itself
safe and specific (touches only the one intended value, verified nothing else
moved) — they do not change *when* it's appropriate to write. See
`afpx_format.md` for the write-path details.

**Polarity is `CINV` on `<OC>` — confirmed by controlled diff, not `PM`/`P` on
the delay tag.** (This section previously said the mapping was unverified;
that was resolved and this note was stale — see `afpx_format.md` for the full
account.) `PM`/`P` don't reliably mean anything and should never be written.

**Sample rate is model-specific — never assume it.** The P SIX DSP MK2 runs at
96 kHz internally, so `delay_ms = samples / 96`. A different Helix model may run at
a different internal rate. Converting a delay computed for one rate into samples at
the wrong rate silently doubles (or halves) the real physical delay and wrecks
alignment — the error won't be obvious from the numbers alone. **Confirm the actual
internal sample rate for the specific unit (from PC-Tool, not assumed) before doing
any delay math**, and use `tunelib.ms_to_samples` / `samples_to_ms` with that
confirmed rate rather than hardcoding 96 kHz. Keep proposals anchored in physical
milliseconds first — that's the number that stays meaningful across models — and
convert to samples last.

## Driver excursion safety (optional — only with driver specs)

If the user provides a driver's resonant frequency (Fs), check any high-pass corner
against it with `tunelib.hpf_excursion_risk`: an HPF set at or below roughly 1.1×
Fs, especially at a steep slope (≥24 dB/oct), doesn't meaningfully restrain
mechanical excursion right at resonance — the electrical slope cuts drive but the
suspension is still least controlled there. This is advisory only (no Xmax/thermal
data needed) and should **never fire from an invented or assumed Fs** — only when
the user actually supplies one.

## Measurement setup gotchas (found during real tuning sessions)

**Digital Input Activation race condition.** If the DSP's input activation is set
to "Automatic via Signal Detection," the first chirp of an acoustic-timing-reference
measurement can get eaten mid-switchover — the input hasn't finished waking up yet
— producing nonsensical multi-second "delay" results that have nothing to do with
the actual acoustic path. **Fix: set input activation to Manual for the tuning
session**, or pre-warm the input with REW's "Check Levels" for a few seconds before
hitting Start, so the switchover has already happened before the reference chirp
plays.

**Rear-fill matrix routing.** Some installs route rear channels as a stereo-
difference matrix (e.g. Rear L = 0.5×FL − 0.5×FR) instead of a discrete feed. This
has real consequences the crossover-based channel-role inference can't see:
(a) it can't be exercised with mono or dual-mono test content — the difference
signal is literally zero, so a mono sweep/track will show nothing on that channel
even if it's working correctly; (b) it should be **excluded from front-stage tonal-
balance decisions**, since by design it only ever carries the stereo difference,
not a driver's own direct response. **Ask about rear-channel routing during
intake** — it's a routing question, separate from (and not detectable from) the
crossover-based role inference in `afpx.py`.

**Acoustic timing reference vs. XLR/hardware loopback — is it worth buying
loopback hardware?** A hardware loopback only changes *how* the timing reference is
established (electrical correlation instead of acoustic correlation via chirp) —
it changes nothing about the physics being measured, and it does **not** fix
clipping (gain-staging is a separate, orthogonal problem). Its real value is
workflow reliability across many repeated sessions (no chirp-detection failures to
troubleshoot), not incremental tuning accuracy over a clean acoustic-reference
measurement. Useful framing if a user asks whether dedicated measurement hardware
is worth buying: it buys convenience and reliability, not more accurate tuning
data.

**Digital vs. analog signal chain for measurement.** With acoustic timing
reference active, REW's per-sweep correlation absorbs any fixed bulk-latency
difference between playback paths — so a "lower latency" analog+ASIO signal chain
buys no real accuracy advantage over a digital one for tuning purposes. What
actually matters: **measure through the same signal chain used for real
listening**, and avoid switching the DSP's input source between measurement and
listening (this also ties directly into the Digital Input Activation race
condition above — switching the source can retrigger that same switchover delay).

## Other model notes

- Channel count varies by model (P SIX = 6 amplified + digital; DSP.3, M-SIX,
  V-SIX, etc. differ). Read the actual count from the `.afpx` (`afpx.py channels`),
  never assume.
- **Tone Control caveat**: if a connected Director/URC remote has Tone Control
  enabled, PC-Tool reserves band 2 on every channel for its bass/treble control.
  A reserved band 2 looks identical in the file to an unused one — it can't be
  detected from the `.afpx` alone. If band 2 seems stuck, ask the user to check the
  remote's Tone Control setting rather than assuming a bug.
- Internal processing is 64-bit / 96 kHz; a clean digital (optical/coax) source
  avoids an extra A/D stage but isn't required for tuning.
