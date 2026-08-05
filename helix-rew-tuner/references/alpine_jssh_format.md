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

## Hardware limits — Alpine's, not Helix's

`ALPINE_LIMITS` in `alpine_jssh.py` carries the real numbers. **Never use
`tunelib.validate_peq_band` on an Alpine file** — that enforces Helix P SIX
(−15..+6 dB, Q 0.5–15). Use `alpine_jssh.validate_band` instead.

| | Alpine PXE-X121-12EV | Helix P SIX (for contrast) |
|---|---|---|
| PEQ freq | 20–20000 Hz | 20–20000 Hz |
| PEQ gain | **−12..+12 dB** | −15..+6 dB |
| PEQ Q | 0.404–28.852 (**writable: 0.498–7.588 only**) | 0.5–15 |
| Bands | 31 | 30 |

Two consequences that bite in practice:

- **`tunelib.fit_peq`'s defaults are Helix-shaped** (`g_lim=(-15,3)`,
  `q_lim=(0.5,8)`). Fitting for an Alpine without overriding them produces
  filters that are either illegal on the Alpine or unwritable by this
  module. Pass `q_lim=alpine_jssh.WRITABLE_Q_RANGE` and an Alpine `g_lim`.
- **Only 13 Q values are writable**, spanning 0.498–7.588 — narrower than
  Alpine's own UI range. A Q outside that span can't be written at all;
  `snap_q()` raises rather than silently writing something materially
  different.

### Resolved: the band-gain range discrepancy

The source project range-checked **band** gain as −60..+6 dB. That is the
**channel**-gain range (identical formula, checked identically a few
functions away) and appears to have been reused rather than independently
established — it's wrong for a band in both directions, forbidding a legal
+7..+12 dB boost while permitting −60 dB, far below anything Alpine's PEQ UI
accepts. `validate_band_gain_db()` here **deliberately deviates** and
enforces Alpine's documented ±12 dB. The stored encoding
(`round((dB+60)*10)`, two bytes LE) can physically hold a much wider span —
that's an encoding capability, not permission. If you obtain primary-source
evidence the band field genuinely accepts beyond ±12, widen
`ALPINE_LIMITS['peq_gain_db']` deliberately rather than loosening the check.

## Writing a computed filter set — Q snapping

A real optimizer returns **continuous** Q; this format accepts **13 discrete
values**. Exact-match-only writing therefore rejects almost every computed
filter, which would make the measure → fit → write pipeline unusable.

`write_peq_bands(obj, ch, bands, snap=True)` takes a `fit_peq`-shaped
`[(F, Q, G), ...]` list, validates every band against Alpine's limits
**before writing anything** (a partial write would leave the preset matching
neither the old tune nor the new one), snaps each Q to the nearest writable
value on a log scale, and clears trailing bands so a longer previous set
can't persist underneath the new one.

**Measured cost of snapping** across the practical range (Q 0.6–6.5, gains
to 6 dB): **worst case ~0.44 dB, typically ~0.2–0.3 dB** — below the "few
tenths of a dB is inaudible" bar used elsewhere in the methodology. That
makes snapping safe, but it is still a real deviation from what was
computed, so it is **never silent**: the return value reports
`worst_q_snap_ratio` and `snapped_count`. Quote those to the user rather
than claiming the requested Q applied exactly.

## Compatibility with the real Alpine software

A file that decodes cleanly and "looks right" as JSON is **not** the same as
a file Alpine will accept and apply. Three separate things have to hold, and
`preflight_real_file()` (CLI: `python alpine_jssh.py preflight <file>`) is
the gate that checks them. **Run it on a real preset and report its verdict
before trusting any generated file on hardware.**

### 1. Number-text preservation (why byte-identity is achievable at all)

`decode()` parses numbers into `_RawInt`/`_RawFloat`, which carry the
original source text; `encode()` emits that text verbatim for anything not
modified. Only values this module actually writes get re-serialized — and
every field it writes is an integer byte.

This sidesteps a genuine trap. There are two plausible "correct" serializer
rules and **they disagree**:

| source text | ported PowerShell writes | stdlib `json.dumps` writes |
|---|---|---|
| `1.0` | `1` | `1.0` |
| `0.1` | `0.10000000000000001` (G17) | `0.1` |

Reimplementing *either* rule silently rewrites part of a real file that
happens to use the other form — which breaks `roundtrip_identical()`, the
very check meant to catch real bugs, by making benign formatting noise
indistinguishable from corruption. Preserving the source text removes the
guesswork: an unmodified round-trip is now byte-identical **regardless of
how Alpine formats numbers**, verified in the selftest across `1.0`, `0.1`,
`1`, `1e3`, `100.0` and `-0.0`.

### 2. Values Alpine's UI can actually represent

Writing a value the UI can't express risks the stored byte and the on-screen
value disagreeing — a silent mismatch that makes a "verified" write
meaningless. Known entry resolutions:

| Field | Resolution | Enforced by |
|---|---|---|
| PEQ frequency | 1 Hz below 1 kHz; **10 Hz at/above** | `quantize_band_freq_hz()`, on by default in `write_peq_bands` |
| PEQ / channel gain | 0.1 dB | inherent in `round((dB+60)*10)` |
| Delay | 1/96 ms (~0.0104 ms) | inherent in `round(ms*96)` |
| PEQ Q | the 13 table codes only | `snap_q()` |

The frequency rule comes from the same author's separate, real-hardware-
tested Alpine entry tool ("values you can actually type into the Alpine").
Acoustic cost of quantizing is nil — 10 Hz at 2 kHz is 0.5%, well under a
hundredth of a semitone.

### 3. Alpine's limits, not Helix's

Covered in the table above — the recurring failure mode is reaching for
`tunelib.validate_peq_band` or leaving `fit_peq` on its Helix-shaped
defaults.

### What preflight cannot tell you

**Whether the hardware applied every value exactly.** Alpine accepting a
file is not proof the DSP honoured every field — the source project flags
this too. After loading a generated preset, read the values back through
Alpine's own UI before trusting them. That is the one remaining gap no
amount of file-level verification can close.

## Unresolved: the channel-gain field does not match the UI slider

On a real PXE-X121-12EV (2026-08-05), `get_channel_gain_db` read **−24.00 dB**
for CH11/CH12 while DSP PC-Tool's own Channel-settings `Gain` control for the
same channel displayed **9**. Both were read from the same preset in the same
session, so one of these is true: the field at 250–251 is not what the UI slider
writes, the slider uses a different scale/offset, or that control is a separate
parameter stored elsewhere in the block (offsets 264–295 are still unmapped).

**Do not write channel gain on this platform until this is resolved.** Every
other field in the table above was confirmed by diffing real files against known
PC-Tool actions; this one has a live contradiction against the UI and no
explanation. Band gain is unaffected — it uses the same encoding but was
confirmed independently and byte-perfectly.

Two related observations from the same unit, useful if you pick this up:
- The slider is **linear in dB and finely stepped**: measured acoustically at
  **1.03 dB per step** (slider 8 → 14 produced 6.16 dB over 25–80 Hz). So it
  behaves like a gain control; it just doesn't obviously map to the stored bytes.
- Some units expose a **2 Ω parallel mode** that merges CH11+CH12 into a single
  CH11 output. Where that's active, a solo capture of CH11 is the full output,
  not half — and CH12's stored settings may be ignored by the hardware. Worth
  asking the user rather than inferring from the file, which looks identical
  either way.

## The 13 writable Q values are narrower than the UI's own range

`get_band_q` returning `None` is not a bug and not rare — real presets are full
of Q codes outside the 13-entry table. On one real tune roughly 70% of stored
bands read back as `Q: None` (observed values from the UI included 1.714, 1.736,
1.955, 2.041, 2.560, 3.193, 4.966, 7.208 — none in the table). Frequency and
gain still decode correctly for those bands.

Two practical consequences:
- **You cannot faithfully rewrite a band whose Q isn't in the table.** Writing it
  back snaps the Q to a neighbour, silently changing a filter you meant to
  preserve. If the intent is to keep some bands and clear others, **edit only the
  bands you're changing** (`set_band_gain_db(obj, ch, band, 0.0)` on the ones to
  disable) rather than rebuilding the channel with `write_peq_bands`, which
  rewrites every band including the ones you wanted untouched.
- When reporting an existing tune to a user, say which bands' Q you could not
  read rather than presenting the readable subset as the whole picture.

## A trap worth knowing: zero bytes are not a neutral preset

Both gain fields encode as `stored = round((dB+60)*10)`, so a **zero** byte
pair decodes to **−60 dB, not 0 dB**. A zero-filled channel block therefore
reads back as every band cut to −60 dB. A genuinely flat/unused band stores
**600** (`0x0258`). This caught a fixture bug in this module's own selftest —
if you ever hand-build a block, build it through the setters, not from zeros.

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
