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
| `19` | **1st-order all-pass** (`G=0`, no real Q — PC-Tool shows "N/A for 1st order") | any slot incl. middle |
| `20` | **2nd-order all-pass** (`G=0`, Q meaningful) | any slot |

Notes that have burned people:
- **`Q` on a `T=19` (1st-order all-pass) can hold a stale, non-functional
  value.** VERIFIED 2026-07-07 by cross-checking decoded XML against a real
  screenshot: a `T=19` band showed `Q="4"` in the file, but PC-Tool displayed
  **"Q: N/A for 1st order"** — the number is very likely left over from when
  that same band was previously a 2nd-order all-pass (where Q is meaningful),
  and PC-Tool doesn't clear it when you switch orders. **Never treat `Q` on a
  `T=19` filter as real data** — the type code alone tells you Q doesn't apply.
- On `T=15`/`T=16` crossover filters, **`G` encodes the SLOPE in dB/oct, not
  gain** — VERIFIED 2026-07-07 by controlled diff (`F="6000.00" G="-12"` matched
  a real screenshot's "-12 dB/Oct"). **`G="0"` means the crossover is NOT
  engaged**, even though `F=` still holds a stored frequency value — a reader
  must check `G!=0` before trusting the frequency for anything (role inference
  included). `afpx.py`'s `channel_summary()` does this now; it previously
  trusted any stored frequency regardless of whether the slope was actually on.
- **`G!=0` alone is not enough to call a crossover "engaged" — also check
  `FilBy`.** VERIFIED 2026-07-07 by a second controlled diff: toggling a
  filter section's own **"Bypass"** button (in its header, separate from the
  Slope dropdown) flipped `FilBy="0"→"1"` on both the HP and LP of the same
  channel with `G`, `F`, and every other value completely unchanged. So
  **`FilBy="1"` means that filter section is bypassed via its header button,
  independent of whatever slope is stored in `G`.** A filter can hold a real,
  non-zero slope and still be bypassed — `afpx.py` now requires both `G!=0`
  *and* `FilBy!="1"` before treating a crossover as actually engaged. This
  also resolves an earlier-unexplained inconsistency (a channel's HP and LP
  showing different `FilBy` while both looked "active" by `G` alone) — they
  likely just had different bypass states that weren't being checked.
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

**Writing a delay is now a real, verified capability — `afpx.write_delay_samples`
/ `afpx.verify_delay_write`.** This does NOT change the standing rule: delay
writes are **user-initiated and explicitly confirmed for that specific change,
every time — never applied automatically from a `polarity_delay_search` or
`estimate_delay_xcorr` result.** Those functions are candidate finders; a
found delay becomes a write only after the user has seen the specific number
and said to apply it. `write_delay_samples` touches only the one channel's `T=`
value — `PM`/`P` are left byte-identical (they aren't confirmed to mean
anything, see below, so nothing should touch them). `verify_delay_write` is
deliberately stronger than the generic `roundtrip_lint(allow_delay=True)`: it
confirms the exact new value landed, every other channel's delay tag is
untouched, and every `<OC>` block is unchanged — not just "something delay-
related changed." Always run it after a delay write, and always follow with a
re-measure — a predicted-good delay is still a prediction until confirmed.

**Polarity is `CINV` on the `<OC>` tag — VERIFIED 2026-07-07 by controlled diff**
(on a `.pct6` file, same `<OC>` schema as `.afpx`): flipping polarity for one
channel in PC-Tool changed exactly one thing, `CINV="1"` → `CINV="0"`, and nothing
else meaningful. `CINV="1"` = inverted, `CINV="0"` = normal.

This closes out a long-standing false lead: it was previously claimed that the
delay tag's `PM` (`PM="1"` normal / `PM="4"` inverted) controlled polarity — that
was never confirmed, and the same controlled diff proved it wrong: `PM` and `P`
on the delay tag **stayed completely identical** across a real, confirmed polarity
flip. Whatever `PM`/`P` encode (a real-world case showed `PM="4"` displayed as
*Normal* — plausibly some delay-entry display-unit mode, still not confirmed),
it isn't polarity. `afpx.channels()` now reports `polarity` from `CINV` (trust
this) and keeps the delay tag's `PM`/`P` only as raw, uninterpreted context under
`polarity_delay_tag_raw`.

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
