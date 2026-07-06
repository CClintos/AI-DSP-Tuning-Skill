# Helix `.afpx` file format (verified spec)

Read this before writing any `.afpx`. All filter writers in `scripts/tunelib.py`
already implement these encodings correctly — prefer them over hand-building tags.

> **Model caveat:** every encoding below was verified by controlled export-diff on
> a **Helix P SIX DSP MK2** (DSP PC-Tool 4). Other Helix models are very likely the
> same but are NOT independently verified — for a different model, do one controlled
> round-trip (write a known change, load in PC-Tool, re-export, diff) before trusting
> writes. The decode/inspect path is safe on any model.

## Container

`.afpx` = **4-byte big-endian uint32 header (= uncompressed XML length) + zlib-
compressed XML.** The header is the length, not a magic number, and MUST be
recomputed on re-encode.

```python
xml = zlib.decompress(open(f, 'rb').read()[4:])                       # decode
out = struct.pack('>I', len(xml)) + zlib.compress(xml, 9)             # encode
```

XML shape: `<ATF ...><OC ...> <Fil .../> ... </OC> ... </ATF>`. One `<OC>` per
output channel, ~30 filter slots each.

## `<Fil>` attributes

- `F` = real centre frequency in Hz (float, e.g. `"110.00"`).
- `dF` = **cosmetic ISO slot label** (e.g. `"125"`); can differ from `F`. A naive
  `F="..."` regex grabs the `F=` inside `dF=` — anchor with `(?<![A-Za-z])F=`.
- `G` = gain dB, `Q` = Q, `FN` = filter id (keep unique), `T` = type (below).
- `I` = **invert flag (0/1)** — NOT an index. `I="1"` flips the filter's polarity
  (used by the all-pass "invert" button).

## Filter type codes (`T=`) — complete verified map

| T | Meaning | Slot restriction |
|---|---------|------------------|
| `1` | free / off slot (`G="0"`) | any |
| `17` | **Parametric EQ** — the normal band; obeys PC-Tool AutoSort | any (use middle slots) |
| `15` / `16` | LP / HP crossover — **do not touch** unless asked | fixed |
| `3` | **Low shelf** (active when `G≠0`) | band 1 / `dF="25"` only |
| `4` | **High shelf** (active when `G≠0`) | band 30 / `dF="20000"` only |
| `19` | **1st-order all-pass** (`G=0`, no Q → written `Q="1"`) | any slot incl. middle |
| `20` | **2nd-order all-pass** (`G=0`, Q meaningful) | any slot |

Notes that have burned people:
- Shelf and all-pass do **not** share a code. (An earlier guess that `T=20` was a
  shelf was wrong — it is the 2nd-order all-pass.)
- **Switching band 1 or band 30 into shelf mode consumes whatever filter was in
  that slot.** If a PEQ is squatting there, relocate it to a free middle slot first.
- All-passes can live in **middle** slots, so they never compete with shelves for
  the two end slots.
- **Only write `T="17"` for ordinary EQ.** Never place a shelf/all-pass code in an
  arbitrary slot — those pin to fixed slots and don't AutoSort.

## Delay / polarity

`<T T="samples" PM="..." P="..." .../>` per channel, with delay in samples at the
DSP's internal sample rate (model-specific — see `helix_hardware.md`, don't assume
96 kHz). **Preserve this tag unless the user asks to change timing.**

**Polarity attribute mapping is UNVERIFIED — do not trust it.** It was previously
claimed that `PM="1"` = normal / `PM="4"` = inverted polarity. A real-world
counterexample has since surfaced: a sub channel with `PM="4"` that PC-Tool
displayed as **Normal**, while `P="0"` was present on every channel checked
regardless of the `PM` value. The likely (not yet confirmed) read is that `P` is
the real polarity flag and `PM` encodes something else — possibly a delay-entry
display-unit mode. **Before trusting either attribute for a polarity read or
write, do a controlled export-diff**: toggle polarity for one channel in PC-Tool,
export, and diff against the unchanged file to see exactly which attribute (or
combination) actually flips. Until that's done, `afpx.channels()` reports the raw
`PM`/`P` values rather than an interpreted normal/inverted label.

## Round-trip gotcha (important for verification)

PC-Tool **reorders attributes inside a tag** when it saves (e.g. `<T PM= T= P=/>`
comes back as `<T T= P= PM=/>`, same values). So when verifying that a PC-Tool-
saved file preserved delays/crossovers, compare **semantically** (parse attrs to a
dict/sorted-tuple), not byte-wise. `afpx.roundtrip_lint` and
`tunelib.delays_semantically_equal` already do this.

## Writing safely

1. Convert a free slot (`T="1"`) to a PEQ by setting `T="17"` and its `F/Q/G`
   (keep `dF`, give a unique `FN`), or use `tunelib` writers for shelf/APF.
2. Validate every PEQ with `tunelib.validate_peq_band(F, Q, G)`.
3. Re-encode, decode back, and run `afpx.roundtrip_lint(old, new, expect_changed=N)`.
4. Confirm delays + crossovers unchanged and only the intended slots differ.
