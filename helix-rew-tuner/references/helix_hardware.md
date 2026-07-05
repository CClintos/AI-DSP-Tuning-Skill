# Helix / Audiotec Fischer DSP hardware notes

Reference for filter capabilities and limits. Verified against DSP PC-Tool 4 for
the P SIX DSP MK2; most applies across the Helix DSP line, but confirm limits for
the specific model when in doubt (they're in that model's PC-Tool).

## EQ / filter modes (PC-Tool 4)

Four per-band EQ modes: **Parametric**, **FineEQ**, **Allpass**, **Shelf**.

- **Parametric / FineEQ PEQ**: Q range **0.5–15**.
- **All-pass**: 1st order (90° at corner, no Q) or 2nd order (180° at corner);
  Q range **0.5–2**. Prefer low Q — abrupt narrow phase shifts are more audible and
  high-Q all-passes ring on transients.
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

Per-channel delay in samples and polarity (`PM=1` normal / `PM=4` inverted). Delay
writes are lower-risk than all-passes but should still be **user-initiated**, not
auto-written, and verified by re-measure.

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
