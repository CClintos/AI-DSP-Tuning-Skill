# Helix `.pct6` file format (BETA — read this before using)

> **BETA — much less proven than `.afpx`.** Personal/interoperability use on
> hardware you (or someone you're directly helping) own — not a general-purpose
> cracking tool, and not something to build a public service or wide
> redistribution on top of. Verified against real files on **PC-Tool 6.01.08 and
> 6.03.04**. If you're on a different PC-Tool 6 version, verify decode actually
> produces plausible `<ATF ...>` XML before trusting it — don't assume the key
> below still applies.

## What `.pct6` is

DSP PC-Tool 6's successor format to `.afpx` — adds the CONDUCTOR configuration
and supports more output channels (up to 22 seen, vs. 8 in `.afpx`), across a
wider device family (Helix DSP PRO, newer P SIX/M-SIX/V-EIGHT, BRAX NOX4,
MATCH DSP/PP-series). The **inner XML schema is the same** `<ATF ...><OC ...>
<Fil F=.. G=.. Q=.. T=.. I=.../></OC>...</ATF>` shape as `.afpx` — once
decoded, reuse `afpx.py`'s functions directly (`channel_blocks`, `filters`,
`attrs`, `channels`, `roundtrip_lint`, etc.). `pct6.py` only handles the outer
container; it doesn't reimplement any tune-XML parsing.

## Container format (no-password saves only)

`.pct6` = `XOR(whole_file, repeating_key=b"ATFV6")` → Qt `qCompress` format
(4-byte big-endian uncompressed-length header + standard zlib stream).

```python
import pct6
xml = pct6.decode('MyTune.pct6')   # -> byte-preserving text view, same shape as afpx.decode()
pct6.encode(xml, 'Out.pct6')
```

**Password-protected `.pct6` saves use a different, unidentified scheme and are
NOT supported** — `decode()` will raise a clear error rather than silently
return garbage if it doesn't see plausible `<ATF ...>` XML come out.

### The decoded content is XML-ish, but not reliably valid UTF-8 text

Real files carry attributes (e.g. `AV=`) with raw binary content. **Never
decode with `errors='replace'` if the result will be edited and written
back** — `'replace'` is lossy by design (it substitutes any invalid byte
sequence with U+FFFD), and re-encoding that substitution produces different
bytes than the original, silently corrupting whatever untouched data happened
to be in that field. This hasn't been reproduced as an actual corruption on
the files tested so far (their binary-looking attributes happened to already
be valid UTF-8) — that's luck on two samples, not a guarantee for every file,
version, or attribute this project hasn't seen yet.

`pct6.py` gives you two layers, matching how you're using the data:

- **`decode_bytes(path)` / `encode_bytes(bytes, path)`** — raw bytes, no text
  decoding at all. Use for read-only inspection or a verified round-trip
  check (`decode_bytes(original) == decode_bytes(reencoded)` after an
  edit-and-write-back — this is the real safety check, not just a file
  looking similar).
- **`decode(path)` / `encode(xml, path)`** — a byte-preserving **latin-1**
  text view, safe to hand to `afpx.py`'s regex-based functions. latin-1 maps
  every byte 0–255 to exactly one character 1:1 — no decode errors are
  possible and no information is lost, unlike `errors='replace'`. Always
  encode back with `encode()` (also latin-1) — mixing this with a
  utf-8-decoded string reintroduces the exact corruption this pair avoids.

**Don't parse this text with `xml.etree` or another strict XML parser
either** — the same non-strict binary content that survives regex parsing
will not survive that.

## Provenance — read this before trusting the key

The XOR key (`ATFV6`) and container structure were identified through
disassembly of the DSP PC-Tool 6 application, done independently for personal
interoperability with hardware the person doing it owns — **this project does
not perform or automate that kind of reverse engineering itself**, and the key
was only *verified empirically* here (real `.pct6` files decode to valid-
looking tune XML; round-trip decode→encode→decode reproduces the same content).

Treat the key as **version-fragile** — Audiotec Fischer could change the
container scheme in a future PC-Tool 6 release without notice, and this repo
has no way to detect that in advance. The one safeguard built in: `decode()`
checks the output actually starts with `<ATF` and raises instead of returning
plausible-looking noise if it doesn't. Always run a real decode and eyeball
the result before trusting a batch of edits on a PC-Tool version you haven't
tried before.

## Differences from `.afpx` worth knowing

- **More channels** (up to 22 seen) — `afpx.py`'s channel functions already
  handle an arbitrary count, no changes needed, but channel-role inference
  from crossovers matters even more here (more channels to keep straight).
- **`<OC>` block order does NOT necessarily match the Output A/B/C... tab
  order shown in PC-Tool.** VERIFIED 2026-07-07 on a real 22-channel file:
  **Output A** (confirmed via a matching delay value cross-checked against a
  screenshot) was `<OC>` index 12, not index 0. Don't assume file order == UI
  order — anchor at least one channel against a real screenshot value (a
  distinctive delay in ms, converted to samples, is a good anchor) before
  trusting the rest, then extend via the existing consecutive-same-role L/R
  pairing logic in `afpx.channels()`.
- **CORRECTION: the first 12 `<OC>` blocks are NOT "unused" — they're a
  separate "Virtual" channel layer, distinct from the "Outputs" tab.**
  VERIFIED 2026-07-07: PC-Tool 6 has a **"Virtual"** tab showing its own
  signal-flow diagram (`Input → Virtual channel → one or more physical
  Outputs`, e.g. one Virtual "Front L Full" channel feeding the physical
  High/Mid/Low Output channels for that side) with its own EQ, gain, and
  phase/delay controls. These Virtual channels live in `<OC>` indices 0–11 —
  they only *looked* unused in earlier files because that tune hadn't put any
  processing on them yet. Editing a Virtual channel's Fine EQ showed up as a
  real, non-zero `T=17` filter in one of these blocks. **Don't write off a
  low-index/no-crossover `<OC>` block as reserved/dead** — check whether it
  has real filter content before assuming that.
- **Editing one side of a stereo pair in PC-Tool can mirror to its partner
  automatically.** Observed: setting a low-shelf on one Front Low channel
  produced the identical filter on the paired channel too, even though only
  one side was touched in the UI. Worth keeping in mind when diffing — a
  change appearing on two channels doesn't necessarily mean both were
  deliberately edited.
- **Decoded XML is not always strictly well-formed** — one attribute (`AV=`)
  has been seen containing raw binary that would break a real XML parser.
  This is fine for `afpx.py`'s regex-based parsing (it never used
  `xml.etree`), but don't try to load `.pct6`-decoded XML with a strict parser.
- Filter type codes (`T=17` PEQ, `T=3`/`T=4` shelves, `T=19`/`T=20` all-pass)
  have been seen matching `.afpx`'s map in real decoded files so far, but this
  is **not independently export-diff-verified the way `.afpx`'s map is** —
  treat it as a working hypothesis to confirm with a controlled test (set a
  known filter in PC-Tool 6, save, decode, check the `T=` value matches
  expectation) before writing anything back for real.
- **Polarity and crossover-slope encoding are shared with `.afpx` and are now
  confirmed** — see `afpx_format.md`: `CINV` on `<OC>` is the real polarity
  flag (not the delay tag's `PM`/`P`, which was a false lead), and `G` on a
  crossover filter is the slope in dB/oct, where `G="0"` means the crossover
  isn't actually engaged even if a frequency is still stored. Both were
  confirmed by controlled diff on a real `.pct6` file.
- **Lowpass isn't always `T="15"`.** VERIFIED 2026-07-07: a Butterworth-
  characteristic lowpass was encoded as **`T="9"`**, not `T="15"` (`T="15"` has
  so far only been seen on Linkwitz-characteristic filters). The crossover
  type-code family likely varies **by characteristic** (Linkwitz, Butterworth,
  Bessel, Tschebyscheff, Self-Define), not just by LP-vs-HP direction — only
  `T=15` and `T=9` are confirmed as LP so far, and no Butterworth/Bessel/etc.
  HP code has been observed yet. `afpx.py` now checks both `T=15` and `T=9`
  for lowpass; treat this as an evolving map, not a complete one. If a
  channel's role won't classify and it has an unrecognized `T` code shaped
  like a crossover filter (F/G/Q present, G acting like a slope), that's worth
  investigating rather than assuming it's an unused slot.
- **Per-channel output level ("Channel Gain & Output Level" in PC-Tool) is
  NOT in the `<OC>` block at all** — it lives in separate `<Vol L="..."/>`
  tags elsewhere in the file, one linear-gain multiplier per channel
  (`dB = 20*log10(L)`). VERIFIED 2026-07-07 by controlled diff (two channels
  set to −3.50 dB and −4.50 dB in PC-Tool decoded to `L` values that convert
  back to exactly −3.50 and −4.50). On the one file checked (22 total
  channels, 10 active), the **last 10 `Vol` tags matched the 10 active output
  channels in order** (confirmed against 4 independent screenshot values with
  zero error) — but the **first 8 entries' meaning is not yet understood**
  (possibly the 12 input channels, only partially represented, or something
  else) and the "skip the first N" offset may not generalize to a
  differently-configured unit. Don't assume this indexing holds without
  re-confirming it on any other file.
- **There's a real routing matrix** (`<Route><R G0=".." ... G143=".." /></Route>`,
  a 12×12 grid for a 12-input unit) separate from the per-channel blocks —
  structure confirmed (mostly zero, non-zero entries cleanly share an index),
  but exact input/output semantics are **not yet confirmed** — that needs a
  controlled diff on the Signal Management (IO) tab, not done yet.
- **`FilBy` is a per-filter-section "Bypass" flag, independent of the slope
  stored in `G`** — see `afpx_format.md`, confirmed by controlled diff:
  toggling one filter section's header Bypass button flipped `FilBy` on both
  its HP and LP with everything else (including `G`) unchanged.
- **`MT` on `<OC>` is likely Mute, with inverted-from-naive logic** —
  `MT="1"` = **not** muted (the default seen on nearly every channel across
  every file this session), `MT="0"` = muted. Evidence: the one channel where
  `MT` changed at all (`1→0`) was exactly the channel a user reported muting,
  with nothing else different. Fairly confident, but only one clean data
  point — a second isolated mute test (start from `MT="1"`, mute, confirm it
  flips to `"0"` and back) would close this out completely.
- **The "Phase" (degrees) field next to delay-in-ms is still unexplained as
  a separate attribute.** A Virtual channel's delay tag changed
  `T="0"→"197"` samples (2.05 ms, matching a screenshot) when a user reported
  changing "phase to 95°" — but no distinct degrees-encoding attribute
  appeared anywhere in the diff. Working hypothesis, **not confirmed**: the
  on-screen "degrees" readout might just be a computed alternate *display* of
  the same single delay value (the way "Distance Mode" on the Time Alignment
  tab is cm for the same ms value), not a separately stored parameter. To
  test: on a channel at 0 ms, change only the degrees field to two different
  known values, save both, and check whether the resulting delay values
  convert back through a single consistent reference frequency.

## Don't commit real `.pct6` sample files to this repo

Decoded tune XML carries personal metadata (the original file path, which
includes a Windows username, has been seen embedded in the `FN=` attribute).
Use synthetic XML for tests (see `pct6.py selftest`), never a real user's tune
file.

If you have a real file locally, the one check worth running by hand before
trusting an edit-and-write-back workflow (can't be shipped in the repo's own
test suite, since it needs a real file):

```python
import pct6
orig = pct6.decode_bytes('MyTune.pct6')
pct6.encode(pct6.decode('MyTune.pct6'), 'roundtrip_check.pct6')
assert pct6.decode_bytes('roundtrip_check.pct6') == orig
```

Byte-identical `.pct6` *files* isn't required (the zlib compressor doesn't
guarantee that) — decoded-content equality is the real safety check.
