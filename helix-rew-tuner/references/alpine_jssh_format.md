# Alpine `.jssh` preset format (BETA — read this before using)

> **BETA — ported from a sibling project, confirmed on a PXE-X121-12EV.**
> Personal/interoperability use on hardware you (or someone you're directly
> helping) own — not a general-purpose cracking tool, and not something to
> build a public service or wide redistribution on top of. Field-by-field
> confidence is inherited exactly as the source documented it — some fields
> are `CONFIRMED` from real captured-file diffs, others are an assumed
> structural pattern not yet individually isolated. Don't read a comment
> here as more certain than the source marked it.

## What `.jssh` is

DSP PC-Tool's preset file for Alpine's own DSP line (confirmed on a
PXE-X121-12EV; other Alpine PC-Tool DSPs are unverified but plausible given
the container is a straightforward JSON dump of the same kind of channel/PEQ
data every Alpine DSP tuning app exposes). Unlike `.afpx`/`.pct6`, there is
no XML involved at all — the decoded content is **confirmed valid JSON**.

## Container format

`.jssh` = `XOR(whole_file, key = byte_index mod 256)`. This is **not** a
short repeating key the way `.pct6` uses `b"ATFV6"` — every byte's key
depends on its own position in the file, cycling every 256 bytes. XOR is
symmetric, so the same operation decodes and encodes.

```python
import alpine_jssh
obj = alpine_jssh.decode('MyPreset.jssh')     # -> parsed Python dict/list
alpine_jssh.encode(obj, 'Out.jssh')
```

Unlike `.pct6`'s XML-ish content (which is not reliably valid UTF-8 and
needs a byte-preserving latin-1 view), Alpine's `.jssh` decodes to genuine
UTF-8 JSON — `decode()` returns the **parsed object directly**, not a text
view. Use ordinary dict/list access (`obj['data']['output']['output'][i]`,
or the field accessor functions below) rather than any text/regex parsing.

## Provenance — read this before trusting the field offsets

This container format and every per-field byte offset below were identified
by a **sibling project** (a PowerShell-based Alpine tuning bridge), through
reverse-engineering done independently for personal interoperability with
hardware its author owns — **this project did not perform that
reverse-engineering itself**, the same relationship this project has to the
`.pct6` key (see `pct6_format.md`'s own provenance section). It was only
**ported and re-verified structurally here**: the container round-trips
correctly against a synthetic schema (see `alpine_jssh.py`'s selftest), but
this Python port has **not yet been independently re-run against a real
Alpine-produced file** the way the source PowerShell was (six real captured
presets, one confirmed byte-for-byte match against Alpine's own output for
an identical change). **Run `alpine_jssh.roundtrip_identical()` against a
real file before trusting `encode()` output on real hardware** — that is
the actual safety check, not the synthetic selftest.

The source project's own verification discipline, inherited here:
- A **mandatory round-trip self-test**: decode a real file, re-encode
  unchanged, re-decode, and diff — must be byte-identical before any
  generated file is trusted.
- **Every write is diffed against the source and refused if anything outside
  the intended fields changed** (`alpine_jssh.verify_write`, the Python
  equivalent of the source's `Confirm-AlpinePresetFileMatchesExpected`) —
  the same "don't silently trust, verify and refuse" discipline
  `afpx.roundtrip_lint` uses for `.afpx`.

## Schema

Channels live at `obj['data']['output']['output'][channel_index]`, each a
flat list of **296 integers** (0–255, i.e. raw bytes represented as JSON
numbers). `channel_index_for(channel_number)` = `channel_number - 1` —
**confirmed for CH1/CH2/CH3/CH5/CH7/CH11**, assumed (not yet individually
confirmed) for CH4/CH6/CH8/CH9.

**Only offsets 0–263 are mapped.** Offsets 264–295 are unknown/unconfirmed —
every setter in `alpine_jssh.py` reads the existing block and writes back
only the one byte it changes, never fabricates a block, so those unmapped
bytes always ride through unchanged from whatever the source file had.

### PEQ bands (1–31), each 8 bytes at `(band-1)*8`

| Offset (within band) | Field | Encoding | Confidence |
|---|---|---|---|
| +0..1 | frequency | Hz, little-endian, direct int | CONFIRMED, byte-perfect |
| +2..3 | gain | `stored = round((dB+60)*10)`, LE | CONFIRMED, exact match |
| +4 | Q | lookup table (13 points, see below) | PARTIAL — table, not a formula |
| +5 | *(unclear)* | one anomalous observation at Q=0, not understood | **excluded** from read/write |
| +7 | filter mode | 0 = normal PEQ, 3 = all-pass | CONFIRMED, two clean transitions |

**Q lookup table** (code → Q): `14→7.588, 20→5.764, 31→3.997, 42→3.058,
53→2.471, 67→1.983, 79→1.700, 90→1.500, 112→1.200, 131→1.023, 134→1.000,
187→0.699, 250→0.498`. Deliberately kept as a table, not a formula — `code
* Q` sits close to ~134 through the middle of the range but drifts at both
extremes, and trusting an interpolated/extrapolated value there risks
writing a wrong Q to real hardware. `set_band_q()` raises for any Q not
within 0.01 of a table entry rather than guessing.

**The excluded byte+5 anomaly**: a real test that typed Q=0 (which Alpine
rounded to 0.404, code 39) *also* changed offset+5 from 0 to 1 — no other
captured point changes that byte at all. Not understood; left out of both
`get_band_q`/`set_band_q` on purpose rather than risk an incomplete write.

### Per-channel fields (fixed offsets, after the 31×8=248-byte band table)

| Offset | Field | Encoding | Confidence |
|---|---|---|---|
| 248 | mute | 1 = unmuted, 0 = muted | CONFIRMED (real muted/unmuted file pair) |
| 249 | polarity | 0 = 0°, 1 = 180° | CONFIRMED (two channels independently) |
| 250–251 | channel gain | `stored = round((dB+60)*10)`, LE | CONFIRMED, byte-perfect |
| 252–253 | delay | `stored = round(ms*96)`, LE | CONFIRMED, four exact matches |
| 256–257 | HPF Hz | direct int, LE | CONFIRMED, three-for-three |
| 258 | HPF type | 0=LR, 1=Butterworth, 2=Bessel | CONFIRMED, two clean transitions |
| 259 | HPF slope | `stored=idx-1`, dB/oct=`(stored+1)*6` | CONFIRMED, two clean transitions |
| 260–261 | LPF Hz | direct int, LE | CONFIRMED, one real set value |
| 262 | LPF type | same codes as HPF type | **inferred** from structural parallel, not independently isolated |
| 263 | LPF slope | same formula as HPF slope | CONFIRMED, two clean transitions |

## An open discrepancy — not resolved here

The source project's own README documents Alpine's **PEQ gain UI** as
limited to **−12..+12 dB**, but the byte-level formula/range-check for the
**PEQ band gain field** (same as the confirmed channel-gain range) accepts
**−60..+6 dB**. `alpine_jssh.validate_band_gain_db()` enforces the wider
range, ported unchanged from the source. Whether the stored field genuinely
supports that full range, or the UI simply never lets a user type past
±12 dB while the byte format has more headroom, hasn't been independently
re-verified. If you need the tighter UI-documented range enforced, check
for it explicitly at the call site — don't assume this module does.

## Differences from `.afpx`/`.pct6` worth knowing

- **Confirmed valid JSON**, not XML — no regex parsing needed, use normal
  dict/list access.
- **Position-dependent XOR key** (`i % 256`), not a short repeating key.
- **No XML filter-type-code system** (`T=17`/`T=3`/`T=19` etc.) — Alpine's
  PEQ bands are fixed 8-byte records at a fixed stride, addressed by band
  number, not by a variable filter-slot scheme.
- **Per-field confidence varies band to band** (see the tables above) —
  this format has more genuinely "assumed, not confirmed" fields than
  `.afpx`'s hardware-limit table, because it comes from diffing real
  captured files rather than an export-diff against known PC-Tool actions
  the way `.afpx`'s T-code map was verified.

## Don't commit real `.jssh` sample files to this repo

Same rule as `.afpx`/`.pct6` — a real preset may carry identifying/personal
data. Use the synthetic schema in `alpine_jssh.py`'s `_make_synthetic_preset`
for tests, never a real user's preset.
