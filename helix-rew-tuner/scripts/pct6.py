# pct6.py -- BETA. Decode/encode DSP PC-Tool 6 .pct6 tune files (Helix DSP PRO,
# newer Helix/Match/BRAX models). Read the caveats below before using this.
#
# STATUS: much less battle-tested than afpx.py. Verified against real files on
# PC-Tool 6.01.08 and 6.03.04, NO-PASSWORD saves only. Intended for personal/
# interoperability use on hardware you (or someone you're helping) actually
# own -- not a general-purpose cracking tool, and not guaranteed to keep
# working on a future PC-Tool version.
#
# THE KEY BELOW IS VERSION-FRAGILE. It was identified through disassembly of
# the PC-Tool 6 application (done independently, for personal interoperability
# -- not something this project performs or automates) and only verified
# empirically here: decoding real .pct6 files produces valid-looking <ATF ...>
# tune XML. It could silently stop matching on a future PC-Tool 6 release.
# ALWAYS check that decode() actually produces <ATF ...> XML before trusting
# the result on a file from a PC-Tool version you haven't tried before --
# don't assume last year's key still applies.
#
# PASSWORD-PROTECTED saves use a different (unidentified) scheme and are NOT
# handled here -- decode() will raise on them rather than silently return
# garbage.
#
# Container: XOR(whole_file, repeating_key=b"ATFV6") -> Qt qCompress format
# (4-byte big-endian uncompressed-length header + standard zlib stream).
#
# The inner content is XML-ish -- SAME <ATF ...><OC ...><Fil .../></OC>...
# </ATF> schema as .afpx (see afpx_format.md) -- but it is NOT reliably valid
# UTF-8 text. Real files carry attributes (e.g. AV=) with raw binary content.
# DO NOT decode with `errors='replace'` if the result will ever be re-encoded
# and written back -- 'replace' is lossy by design (it substitutes invalid
# byte sequences with U+FFFD), and re-encoding that substitution produces
# DIFFERENT bytes than the original, silently corrupting whatever untouched
# data happened to sit in that field. This has NOT been reproduced as an
# actual corruption on the two real files tested so far (their binary-looking
# attributes happened to already be valid UTF-8) -- that is luck, not a
# guarantee, and the failure mode is real for any file/version/attribute this
# project hasn't seen yet. Use decode() (latin-1 round-trip, below) for any
# candidate text; only write it with write_preserving_crossovers(), bound to
# the original source. Use decode_bytes() only
# for read-only inspection where you don't need string operations.
#
# Once decoded, reuse afpx.py's functions directly (channel_blocks, filters,
# attrs, channels, roundtrip_lint, etc.) rather than re-implementing parsing
# here -- they're regex-based (never used a strict XML parser), and the
# latin-1 text view below is safe to feed them: every byte maps to exactly
# one character 1:1, so the ASCII structural parts (tags, attribute names,
# quotes) parse identically either way, and any binary-ish attribute content
# just rides along unchanged instead of being silently substituted. Do NOT
# parse this text with xml.etree or another strict XML parser -- the same
# non-strict content that survives regex parsing will not survive that.
#
# .pct6 can have more output channels than .afpx (up to 22 seen) -- afpx.py's
# channel functions already handle an arbitrary channel count, no changes
# needed. Note: channel-index-to-Output-letter mappings (e.g. "decoded ch12 =
# Output A" on one real tune) are TUNE-SPECIFIC findings from a controlled
# diff against that one file's own screenshots -- they are not a universal
# .pct6 rule and must never be hardcoded here. If a project wants to record a
# confirmed mapping for a specific tune/install, keep it in a separate,
# optional config (e.g. a small JSON file) outside this module, not in code.
#
# CLI:
#   python pct6.py decode <file.pct6>              # writes file.decoded.xml (raw bytes)
#   python pct6.py encode <file.xml> <out.pct6>     # reads file.xml as raw bytes
#   python pct6.py selftest                        # synthetic round-trip check
import sys
import zlib
from pathlib import Path

import afpx

XOR_KEY = b'ATFV6'


def _xor_repeat(data, key):
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def decode_bytes(path):
    """.pct6 (no-password) -> raw inner XML-ish bytes, after XOR + zlib/
    qCompress unwrap. No text decoding at all -- use this for read-only
    inspection or byte-exact round-trip comparison. Raises ValueError if the
    result doesn't look like tune XML
    (password-protected, or the key/container has changed on this PC-Tool
    version)."""
    raw = Path(path).read_bytes()
    unxored = _xor_repeat(raw, XOR_KEY)
    if len(unxored) < 4:
        raise ValueError('file too short to be a valid .pct6: %s' % path)
    declared = int.from_bytes(unxored[:4], 'big')
    xml_bytes = zlib.decompress(unxored[4:])
    if declared != len(xml_bytes):
        print('warning: declared length %d != decoded length %d -- verify this decode carefully'
              % (declared, len(xml_bytes)), file=sys.stderr)
    if not xml_bytes.lstrip().startswith(b'<ATF'):
        raise ValueError('decoded content does not look like tune XML -- this file may be '
                         'password-protected, or the key/container has changed on this '
                         'PC-Tool version. Do not trust this output.')
    return xml_bytes


def _encode_bytes_unchecked(xml_bytes, path, exclusive=False):
    """Internal raw container codec; it performs no tune-safety checks."""
    packed = len(xml_bytes).to_bytes(4, 'big') + zlib.compress(xml_bytes, 9)
    mode = 'xb' if exclusive else 'wb'
    with open(path, mode) as fh:
        fh.write(_xor_repeat(packed, XOR_KEY))


def decode(path):
    """.pct6 (no-password) -> a byte-preserving TEXT view (latin-1), safe to
    hand to afpx.py's regex-based functions. latin-1 maps every byte 0-255 to
    exactly one character 1:1 -- no decode errors are possible and no bytes
    are lost, unlike `errors='replace'`. Encode this same string back with
    write_preserving_crossovers() to create a safe new output."""
    return decode_bytes(path).decode('latin-1')


def write_preserving_crossovers(source_path, xml, output_path):
    """Create a new PCT6 only if all source crossover slots are unchanged."""
    source_xml = decode(source_path)
    if afpx.semantic_xover_key(source_xml) != afpx.semantic_xover_key(xml):
        raise ValueError(
            'crossover state or channel/slot identity changed; refusing PCT6 output')
    _encode_bytes_unchecked(xml.encode('latin-1'), output_path, exclusive=True)


def _selftest():
    """Synthetic round-trip check -- no real .pct6 sample files are bundled
    with this repo (real tune files carry personal path/username metadata and
    shouldn't be committed), so this only verifies the codec is internally
    consistent, not that the key matches a real PC-Tool 6 file. Against a real
    file, also check: decode_bytes(original) == decode_bytes(reencoded) --
    that's the real safety check (byte-identical .pct6 output is a nice-to-
    have if the compressor is deterministic, but decoded-content equality is
    what actually matters)."""
    sample = b'<ATF JPT="1" V="6.01.08"><OC><Fil T="17" F="110.00" Q="1.30" G="-4.00" FN="1"/></OC></ATF>'
    tmp = Path('_pct6_selftest.pct6')
    try:
        # bytes-level round-trip
        _encode_bytes_unchecked(sample, tmp)
        back_bytes = decode_bytes(tmp)
        assert back_bytes == sample, 'raw PCT6 codec round-trip mismatch'

        # latin-1 text-view round-trip, including a non-ASCII byte to prove
        # nothing gets substituted the way utf-8/replace would
        sample_binary = sample[:-6] + bytes([0x93, 0xC1, 0xFE]) + sample[-6:]
        _encode_bytes_unchecked(sample_binary, tmp)
        text = decode(tmp)
        assert text.encode('latin-1') == sample_binary, 'latin-1 text view lost information'
        _encode_bytes_unchecked(text.encode('latin-1'), tmp)
        assert decode_bytes(tmp) == sample_binary, 'decode/raw-codec round-trip mismatch'

        print('SELFTEST PASSED (synthetic round-trip only -- verify against a real file too:'
              ' decode_bytes(original) == decode_bytes(reencoded))')
    finally:
        tmp.unlink(missing_ok=True)


def _main():
    if len(sys.argv) < 2:
        print('usage: python pct6.py {decode <file.pct6> | encode '
              '<source.pct6> <file.xml> <out.pct6> | selftest}')
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == 'selftest':
        _selftest()
    elif cmd == 'decode':
        xml_bytes = decode_bytes(sys.argv[2])
        out = Path(sys.argv[2]).with_suffix('.decoded.xml')
        out.write_bytes(xml_bytes)
        print('decoded ->', out)
        print(repr(xml_bytes[:200]))
    elif cmd == 'encode':
        if len(sys.argv) != 5:
            raise ValueError('encode requires source.pct6, candidate.xml, and new output.pct6')
        xml = Path(sys.argv[3]).read_bytes().decode('latin-1')
        write_preserving_crossovers(sys.argv[2], xml, sys.argv[4])
        print('encoded ->', sys.argv[4])
    else:
        print('unknown command:', cmd)
        sys.exit(1)


if __name__ == '__main__':
    _main()
