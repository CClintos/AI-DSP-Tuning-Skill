# pct6.py -- BETA. Decode/encode DSP PC-Tool 6 .pct6 tune files (Helix DSP PRO,
# newer Helix/Match/BRAX models). Read the caveats below before using this.
#
# STATUS: much less battle-tested than afpx.py. Verified against real files on
# PC-Tool 6.01.08 only, NO-PASSWORD saves only. Intended for personal/
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
# The inner XML is the SAME <ATF ...><OC ...><Fil .../></OC>...</ATF> schema
# as .afpx (see afpx_format.md) -- once decoded, reuse afpx.py's functions
# directly (channel_blocks, filters, attrs, channels, roundtrip_lint, etc.)
# rather than re-implementing parsing here. .pct6 can have more output
# channels than .afpx (up to 22 seen vs. 8) -- afpx.py's channel functions
# already handle an arbitrary channel count, no changes needed.
#
# Note: the decoded XML is not always strictly well-formed (one attribute has
# been seen containing raw binary) -- this is fine for afpx.py's regex-based
# parsing (it never used a strict XML parser), but don't try to load it with
# xml.etree or similar.
#
# CLI:
#   python pct6.py decode <file.pct6>              # writes file.decoded.xml
#   python pct6.py encode <file.xml> <out.pct6>
#   python pct6.py selftest                        # synthetic round-trip check
import sys
import zlib
from pathlib import Path

XOR_KEY = b'ATFV6'


def _xor_repeat(data, key):
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def decode(path):
    """.pct6 (no-password) -> XML string. Raises ValueError if the file
    doesn't decode to plausible tune XML (password-protected, or the format
    has changed on a newer PC-Tool version)."""
    raw = Path(path).read_bytes()
    unxored = _xor_repeat(raw, XOR_KEY)
    if len(unxored) < 4:
        raise ValueError('file too short to be a valid .pct6: %s' % path)
    declared = int.from_bytes(unxored[:4], 'big')
    xml_bytes = zlib.decompress(unxored[4:])
    if declared != len(xml_bytes):
        print('warning: declared length %d != decoded length %d -- verify this decode carefully'
              % (declared, len(xml_bytes)), file=sys.stderr)
    xml = xml_bytes.decode('utf-8', 'replace')
    if not xml.lstrip().startswith('<ATF'):
        raise ValueError('decoded content does not look like tune XML -- this file may be '
                         'password-protected, or the key/container has changed on this '
                         'PC-Tool version. Do not trust this output.')
    return xml


def encode(xml, path):
    """XML string -> .pct6 (no-password format only)."""
    payload = xml.encode('utf-8')
    packed = len(payload).to_bytes(4, 'big') + zlib.compress(payload, 9)
    Path(path).write_bytes(_xor_repeat(packed, XOR_KEY))


def _selftest():
    """Synthetic round-trip check -- no real .pct6 sample files are bundled
    with this repo (real tune files carry personal path/username metadata and
    shouldn't be committed), so this only verifies the codec is internally
    consistent, not that the key matches a real PC-Tool 6 file. Run
    `python pct6.py decode <your file>` against a real file to confirm that."""
    sample = '<ATF JPT="1" V="6.01.08"><OC><Fil T="17" F="110.00" Q="1.30" G="-4.00" FN="1"/></OC></ATF>'
    tmp = Path('_pct6_selftest.pct6')
    try:
        encode(sample, tmp)
        back = decode(tmp)
        assert back == sample, 'round-trip mismatch'
        print('SELFTEST PASSED (synthetic round-trip only -- verify against a real file too)')
    finally:
        tmp.unlink(missing_ok=True)


def _main():
    if len(sys.argv) < 2:
        print('usage: python pct6.py {decode <file.pct6> | encode <file.xml> <out.pct6> | selftest}')
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == 'selftest':
        _selftest()
    elif cmd == 'decode':
        xml = decode(sys.argv[2])
        out = Path(sys.argv[2]).with_suffix('.decoded.xml')
        out.write_text(xml, encoding='utf-8')
        print('decoded ->', out)
        print(xml[:200])
    elif cmd == 'encode':
        xml = Path(sys.argv[2]).read_text(encoding='utf-8')
        encode(xml, sys.argv[3])
        print('encoded ->', sys.argv[3])
    else:
        print('unknown command:', cmd)
        sys.exit(1)


if __name__ == '__main__':
    _main()
