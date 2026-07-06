# Helix `.pct6` file format (BETA — read this before using)

> **BETA — much less proven than `.afpx`.** Personal/interoperability use on
> hardware you (or someone you're directly helping) own — not a general-purpose
> cracking tool, and not something to build a public service or wide
> redistribution on top of. Verified against real files on **PC-Tool 6.01.08
> only**. If you're on a different PC-Tool 6 version, verify decode actually
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
xml = pct6.decode('MyTune.pct6')   # -> XML string, same shape as afpx.decode()
pct6.encode(xml, 'Out.pct6')
```

**Password-protected `.pct6` saves use a different, unidentified scheme and are
NOT supported** — `decode()` will raise a clear error rather than silently
return garbage if it doesn't see plausible `<ATF ...>` XML come out.

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

## Don't commit real `.pct6` sample files to this repo

Decoded tune XML carries personal metadata (the original file path, which
includes a Windows username, has been seen embedded in the `FN=` attribute).
Use synthetic XML for tests (see `pct6.py selftest`), never a real user's tune
file.
