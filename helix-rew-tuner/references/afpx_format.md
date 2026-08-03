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

### `Q` on a crossover filter is usually NOT live — VERIFIED 2026-08-01

The crossover **characteristic/alignment** is held in the `<OC>`-level `HPi` /
`LPi` index, **not** in the `Fil` tag's `Q`. On a file whose PC-Tool display was
checked directly, all 8 active channels read *Linkwitz-Riley −24 dB/Oct* while
their stored `Q` values were 0.7 (front mids), 0.5 (sub lowpass) and 1 (rears) —
`HPi="31"` / `LPi="30"` on every one of them. The differing Q values were
leftover state from prior settings, and a bypassed filter (`lpBy="1"`) still
carried a `Q`, confirming the field persists while inactive.

The stored `Q` becomes live only when Characteristic is set to **"Self-define"**,
which per the same PC-Tool screenshot also **forces Slope to −12 dB/Oct (greyed
out)**. So LR24-with-custom-Q is not available: choosing Self-define trades the
24 dB/oct slope for a 2nd-order filter whose knee Q you control. Q above ~0.8
puts a genuine gain peak just under the corner (Q=1.2 → +2.4 dB, Q=1.5 →
+4.0 dB), so Self-define is a real tool but a real risk.

Known mapping so far: `HPi="31"` / `LPi="30"` == LR24. **Other values are
unidentified** — treat them as unknown rather than inferring.

`afpx.channel_summary` therefore reports `hp_char_idx` / `lp_char_idx` as
authoritative and names the Q fields `hp_q_stored_not_live` /
`lp_q_stored_not_live` so the value cannot be mistaken for an operating
parameter. `Q` stays in `CROSSOVER_FIELDS` for change detection — a Q edit still
matters under Self-define. See methodology §Analysis traps for the general rule
(establish a decoded field is live before reasoning about its value); the same
failure mode is documented for `T=19` all-pass Q below.

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

## Filter identity is (channel_index, slot_index) — never frequency

`channels()[ch]['slots']` lists every filter slot with its positional
`slot_index`, stored `fn`, type, F/Q/G, `bypassed` and `free` flags.
`peqs`/`shelves`/`all_passes` remain plain `(F,Q,G)`-style tuples for
`cascade_db`/`headroom_report`, but they carry **no identity** — so they can
say *what* a channel is doing, never *which* filter to edit.

**Address an existing filter by slot, never by nearest frequency.** Real tunes
put bands close enough that proximity matching is ambiguous: one 16-band
channel had five pairs within 10% of each other (129.4/136.9, 258.3/277.0,
621.8/650.0, 1015.9/1115.0, 1236.6/1300.0). A "move the 97 Hz band to 100 Hz"
expressed as *find the band nearest 97* can retune the wrong one, or leave the
original and create a duplicate at the new frequency. Slot order is also **not**
frequency order — on that same channel the 258.3 Hz and 277.0 Hz bands live at
slots 12 and 0.

`write_filter_slot(xml, channel_index, slot_index, F=/Q=/G=/type_code=)` edits
one slot in place: only the attributes you pass change, `FN`/`dF`/`I`/`FilBy`
stay byte-identical, and no other slot moves. `type_code='1'` frees a slot
(removal without deleting it, preserving slot count). It **refuses to touch a
crossover** unless `allow_crossover=True`, so a mis-indexed edit can't silently
retune one. PEQ edits are checked against hardware limits. Verify with
`verify_slot_write`, which confirms the intended attributes landed, nothing
else on that tag moved, every other slot in every channel is unchanged, and
delays didn't shift.

This is the mechanism for expressing an edit precisely — not permission to make
one. Relaxing, re-centring or removing an existing filter still needs measured
justification and the same per-change confirmation as any other write.

## Crossover protection is enforced from ONE place — don't re-list codes

`afpx.CROSSOVER_TYPES` = `{'9','15','16'}` and `afpx.CROSSOVER_FIELDS`
(`T,F,Q,G,dF,FilBy`) are the single source of truth. Everything that detects,
protects, or infers a crossover uses them.

**Why this is a rule and not a style preference — four real detection gaps
found 2026-07-31, all four caused by knowledge being documented here but
re-typed as local literals in the guard:**
- `semantic_xover_key` protected only `T=15/16`, so a **`T="9"` low-pass
  frequency or slope change passed `roundtrip_lint` silently** — even though
  `channel_summary` had correctly read `T=9` as a low-pass since 2026-07-07.
- It also omitted `FilBy`, so **switching a crossover OFF entirely** (bypass,
  with F/Q/G untouched) linted as `{'pass': True, 'slots_changed': 0}`. On a
  tweeter that's a driver-damage scenario, not a tonal one.
- The slot-change counter used a nested `zip()`, which truncates to the
  shorter list: a **deleted filter slot or an entire deleted channel** counted
  as zero changes and passed.
- The slot signature omitted `FilBy`, so **bypassing an ordinary PEQ** was
  invisible too.

All four now fail closed, with a regression test each in `afpx.py selftest`,
plus a no-false-positive test proving a legitimate single-PEQ gain edit still
passes. The lesson generalises: **a verified format finding isn't real until
some guard enforces it** — when adding a new type code or state field here,
add it to the constants above, not to one call site.

## Output level (`<Vol>`) — VERIFIED 2026-07-14

`<Vol T="15" L="0.7286181745132278" i="0"/>`, **one per channel, inside that
channel's `<OC>` block.** `L` is **LINEAR amplitude**, so `dB = 20*log10(L)`
(`L="1.0"` = unity/0 dB). Verified by reading real files: `L="0.7286…"` =
−2.75 dB matched the channel's PC-Tool output trim.

**GOTCHA — there are FEWER `<Vol>` tags than channels.** Unused/empty output
channels have **no `<Vol>` tag at all** (a real 10-channel file had them only on
ch0–ch7; ch8/ch9 had none). So **the Nth `<Vol>` tag in the file is NOT
channel N** — a positional index silently writes to the wrong channel.
`afpx.read_output_levels` / `write_output_trim` / `verify_output_trim_write` map
each tag to its containing `<OC>` block and key by channel index (same
convention as `channels()`); the selftest deliberately includes a
missing-`<Vol>` channel so a regression to positional indexing fails loudly.

**Why this matters beyond writes:** `tunelib.headroom_report`'s `clip_risk`
only sees the PEQ stage and is frequently a **false alarm** — the channel's
output trim usually already offsets the boost. Verified real case: a +2.7 dB
PEQ cascade peak on a channel sitting at −2.75 dB output = ~0 dB net, not
clipping. **Always read the actual output level before reporting a clip risk.**

**Writing a trim** (`afpx.write_output_trim`) is **attenuation-only by
construction** — values must be ≤ 0 dB and ≥ −6 dB (configurable floor), and
the trim is *relative* to the existing level, so it composes with a trim the
user already set rather than replacing it. That structural guarantee (it cannot
raise level, so it cannot create a clipping risk) makes it safer than the delay
write, but it is still an audible change to the user's tune: same standing rule
— user-initiated, explicitly confirmed for that specific change, and verified
after with `verify_output_trim_write` (which checks the exact resulting dB,
that level went *down*, that other channels' `<Vol>` tags are byte-identical,
and that nothing outside `<Vol>` moved).

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
