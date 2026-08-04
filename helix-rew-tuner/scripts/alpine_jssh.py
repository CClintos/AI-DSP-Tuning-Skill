# alpine_jssh.py -- BETA. Decode/encode Alpine DSP PC-Tool ".jssh" preset
# files (confirmed on a PXE-X121-12EV). Read the caveats below first.
#
# STATUS: a Python port of a PowerShell implementation from a sibling project
# (an Alpine-specific tuning bridge) that reverse-engineered this format for
# personal interoperability with hardware the author owns -- this project did
# not perform that reverse-engineering itself, and inherits it at the same
# confidence level the source documented, field by field. Every getter/setter
# below carries the SAME "CONFIRMED" / "assumed, not yet isolated" marker the
# source gave it -- do not read a comment here as more certain than that.
#
# THE CONTAINER FORMAT is well-verified: independently confirmed against six
# real captured presets (every one decodes to valid JSON) and, separately, a
# byte-for-byte match between a file this codec produced and what Alpine's
# own PC-Tool produced for the identical change. The PER-FIELD byte offsets
# below are confirmed only for the channels/values the source project
# actually tested -- channel-index-to-channel-number mapping beyond CH1/CH2
# is an ASSUMED sequential pattern, not directly confirmed for every channel.
#
# Container: JSON, XORed byte-for-byte against (byte index) MOD 256 -- NOT a
# short repeating key like .pct6's XOR_KEY. XOR is symmetric, so one function
# decodes and encodes.
#
# ALWAYS run verify_write() (or at minimum re-decode and eyeball the result)
# before trusting a generated file on real hardware -- this module refuses to
# silently guess: decode() raises if the result isn't valid JSON, and
# verify_write() raises if anything outside the expected fields changed.
#
# A NOTED OPEN DISCREPANCY, not resolved here: the source project's own
# README documents Alpine's PEQ gain UI as limited to -12..+12 dB, but the
# byte-level gain formula/range-check in this module (ported unchanged from
# the source) accepts -60..+6 dB, matching the *channel* gain field's
# documented range. Whether the *band* gain field genuinely shares that wider
# stored range or the UI simply never lets you type past +/-12 hasn't been
# independently re-verified -- validate_band_gain_db() enforces the wider
# range as ported; if you want the tighter UI-documented range enforced too,
# check for it explicitly at the call site rather than assuming this module
# does.
#
# CLI:
#   python alpine_jssh.py decode <file.jssh>     # writes file.decoded.json
#   python alpine_jssh.py encode <file.json> <out.jssh>
#   python alpine_jssh.py selftest               # synthetic round-trip + field checks
import copy
import json
import sys
from pathlib import Path

CHANNEL_BLOCK_LEN = 296       # confirmed length of one channel's value array
N_PEQ_BANDS = 31              # confirmed max PEQ bands per channel
PEQ_BAND_BYTES = 8            # confirmed per-band stride

# Confirmed 13 points from real single-byte-change captures (code -> Q).
# Deliberately a lookup table, not a formula -- code*Q drifts at both
# extremes of the range even though it sits close to ~134 through the
# middle. One point is deliberately excluded: a real test typing Q=0 (Alpine
# rounded it to 0.404, code 39) ALSO changed a second byte (offset+5, 0->1)
# that no other point in this table touches -- not understood, so left out
# of both read and write paths rather than risk an incomplete write.
PEQ_Q_TABLE = {14: 7.588, 20: 5.764, 31: 3.997, 42: 3.058, 53: 2.471,
               67: 1.983, 79: 1.700, 90: 1.500, 112: 1.200, 131: 1.023,
               134: 1.000, 187: 0.699, 250: 0.498}

_FILTER_TYPE_CODE = {'LR': 0, 'Butterworth': 1, 'Bessel': 2}
_FILTER_TYPE_NAME = {v: k for k, v in _FILTER_TYPE_CODE.items()}


def _xor_by_position(data):
    return bytes(b ^ (i % 256) for i, b in enumerate(data))


def decode_bytes(path):
    """.jssh -> raw JSON bytes (UTF-8), after the position-XOR unwrap. Raises
    ValueError if the result doesn't parse as JSON -- a corrupted file, or a
    format change this module hasn't seen."""
    raw = Path(path).read_bytes()
    decoded = _xor_by_position(raw)
    try:
        json.loads(decoded.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError('decoded content is not valid JSON -- this file may not be a '
                         '.jssh preset, or the container format has changed: %s' % e)
    return decoded


def encode_bytes(json_bytes, path):
    """Raw JSON bytes (UTF-8) -> .jssh. Pairs with decode_bytes() for a
    byte-exact round-trip IF the JSON bytes are unchanged; a re-SERIALIZED
    object is only byte-identical to Alpine's own output if encode()'s
    compact/non-ASCII-preserving formatting matches Alpine's serializer --
    see encode()'s docstring."""
    Path(path).write_bytes(_xor_by_position(json_bytes))


def decode(path):
    """.jssh -> parsed Python object (dict/list/etc, via json.loads). Unlike
    .pct6's XML-ish content, Alpine's .jssh is confirmed valid JSON, so this
    returns the parsed structure directly rather than a text view -- use
    ordinary dict/list access (see channel_block() etc. below) instead of
    regex parsing."""
    return json.loads(decode_bytes(path).decode('utf-8'))


def encode(obj, path):
    """Parsed Python object -> .jssh. Serializes with compact separators and
    ensure_ascii=False (non-ASCII left as real UTF-8, not \\u-escaped) --
    the source project independently confirmed this exact formatting
    reproduces Alpine's own serializer byte-for-byte for a real file, which
    is why this uses stdlib json.dumps with those settings rather than a
    hand-rolled serializer. NOT independently re-verified from this Python
    port against a real Alpine-produced file -- do that (byte-diff the
    output of an unmodified read+write against the original) before trusting
    a generated file on real hardware, same as the source project's own
    mandatory round-trip self-test required."""
    text = json.dumps(obj, separators=(',', ':'), ensure_ascii=False)
    encode_bytes(text.encode('utf-8'), path)


def roundtrip_identical(path):
    """Decode a real file, re-encode unchanged, decode again, and report
    whether the re-encoded bytes are byte-identical to the source. This is
    the real safety check before trusting encode() on a given file/PC-Tool
    version -- run it once per file you intend to edit, not just at
    selftest time. Returns dict with byte_identical/source_len/output_len."""
    obj = decode(path)
    tmp = Path(str(path) + '.roundtrip_tmp')
    try:
        encode(obj, tmp)
        source_raw = Path(path).read_bytes()
        output_raw = tmp.read_bytes()
        return {'byte_identical': source_raw == output_raw,
               'source_len': len(source_raw), 'output_len': len(output_raw)}
    finally:
        tmp.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Channel/field access -- confirmed 0-based: data['output']['output'][index]
# under the top-level object's 'data' key (i.e. obj['data']['output']
# ['output'][index]). channel_index_for() below maps channel NUMBER -> this
# index; confirmed CH1/CH2/CH3/CH5/CH7/CH11, assumed (not yet individually
# confirmed) for CH4/CH6/CH8/CH9.
def channel_index_for(channel_number):
    return channel_number - 1


def channel_block(obj, channel_index):
    return obj['data']['output']['output'][channel_index]


def set_channel_byte(obj, channel_index, byte_offset, value):
    """Writes one value into a channel's block, explicitly writing the whole
    block back into the parent object afterward -- ported deliberately from
    the source's own fix for a real bug where mutating the block in place
    did not reliably propagate back through Python's own list references
    either in some call patterns; this is the same read-modify-explicit-
    write-back shape as the confirmed-working PowerShell version, so every
    setter here uses it rather than assuming a list is mutated by reference."""
    block = obj['data']['output']['output'][channel_index]
    block[byte_offset] = int(value)
    obj['data']['output']['output'][channel_index] = block


# ---- channel-level fields --------------------------------------------------

def get_channel_gain_db(obj, channel_index):
    """CONFIRMED, byte-perfect: bytes 250-251, little-endian,
    stored = round((gainDb + 60) * 10)."""
    block = channel_block(obj, channel_index)
    stored = block[250] + block[251] * 256
    return (stored / 10.0) - 60.0


def validate_channel_gain_db(gain_db):
    if not (-60.0 <= gain_db <= 6.0):
        raise ValueError('Channel gain %.2f dB is outside Alpine\'s -60..+6 dB range.' % gain_db)


def set_channel_gain_db(obj, channel_index, gain_db):
    validate_channel_gain_db(gain_db)
    stored = round((gain_db + 60.0) * 10.0)
    set_channel_byte(obj, channel_index, 250, stored & 0xFF)
    set_channel_byte(obj, channel_index, 251, (stored >> 8) & 0xFF)


def get_channel_muted(obj, channel_index):
    """CONFIRMED: byte 248 (immediately after the 31 PEQ bands, which occupy
    0-247). 1 = unmuted/active, 0 = muted -- from a real muted/unmuted file
    pair differing by exactly this one byte."""
    return channel_block(obj, channel_index)[248] == 0


def set_channel_muted(obj, channel_index, muted):
    set_channel_byte(obj, channel_index, 248, 0 if muted else 1)


def get_channel_inverted(obj, channel_index):
    """CONFIRMED independently on two different channels: byte 249,
    0 = 0 degrees (normal), 1 = 180 degrees (inverted)."""
    return channel_block(obj, channel_index)[249] == 1


def set_channel_inverted(obj, channel_index, inverted):
    set_channel_byte(obj, channel_index, 249, 1 if inverted else 0)


def get_channel_delay_ms(obj, channel_index):
    """CONFIRMED with four exact matches across two channels including a
    0 ms reference point: bytes 252-253, little-endian, stored = round(ms*96)."""
    block = channel_block(obj, channel_index)
    stored = block[252] + block[253] * 256
    return stored / 96.0


def validate_channel_delay_ms(ms):
    if not (0.0 <= ms <= 20.0):
        raise ValueError('Delay %.3f ms is outside Alpine\'s 0-20 ms range.' % ms)


def set_channel_delay_ms(obj, channel_index, ms):
    validate_channel_delay_ms(ms)
    stored = round(ms * 96.0)
    set_channel_byte(obj, channel_index, 252, stored & 0xFF)
    set_channel_byte(obj, channel_index, 253, (stored >> 8) & 0xFF)


def get_channel_hpf_hz(obj, channel_index):
    """CONFIRMED, three-for-three exact match against real set values: bytes
    256-257, little-endian, direct Hz."""
    block = channel_block(obj, channel_index)
    return block[256] + block[257] * 256


def set_channel_hpf_hz(obj, channel_index, hz):
    if not (10 <= hz <= 20000):
        raise ValueError('HPF frequency %d Hz is outside a plausible 10-20000 Hz range.' % hz)
    set_channel_byte(obj, channel_index, 256, hz & 0xFF)
    set_channel_byte(obj, channel_index, 257, (hz >> 8) & 0xFF)


def get_channel_lpf_hz(obj, channel_index):
    """CONFIRMED against one real set value: bytes 260-261, little-endian,
    direct Hz."""
    block = channel_block(obj, channel_index)
    return block[260] + block[261] * 256


def set_channel_lpf_hz(obj, channel_index, hz):
    if not (10 <= hz <= 40000):
        raise ValueError('LPF frequency %d Hz is outside a plausible 10-40000 Hz range.' % hz)
    set_channel_byte(obj, channel_index, 260, hz & 0xFF)
    set_channel_byte(obj, channel_index, 261, (hz >> 8) & 0xFF)


def _filter_type_name(code):
    return _FILTER_TYPE_NAME.get(code, 'Unknown(%d)' % code)


def _filter_type_code(name):
    if name not in _FILTER_TYPE_CODE:
        raise ValueError("Unknown filter type name %r -- expected LR, Butterworth or Bessel." % name)
    return _FILTER_TYPE_CODE[name]


def get_channel_hpf_type(obj, channel_index):
    """CONFIRMED via two clean single-byte transitions: byte 258.
    0=LR, 1=Butterworth, 2=Bessel."""
    return _filter_type_name(channel_block(obj, channel_index)[258])


def set_channel_hpf_type(obj, channel_index, type_name):
    set_channel_byte(obj, channel_index, 258, _filter_type_code(type_name))


def get_channel_hpf_slope_db_per_oct(obj, channel_index):
    """CONFIRMED via two clean single-byte transitions: byte 259,
    stored = slopeIndex-1, dB/oct = (stored+1)*6 (0-7 -> 6-48 dB/oct)."""
    return (channel_block(obj, channel_index)[259] + 1) * 6


def set_channel_hpf_slope_db_per_oct(obj, channel_index, db_per_oct):
    if db_per_oct % 6 != 0 or not (6 <= db_per_oct <= 48):
        raise ValueError('HPF slope %d dB/octave must be a multiple of 6 between 6 and 48.' % db_per_oct)
    set_channel_byte(obj, channel_index, 259, (db_per_oct // 6) - 1)


def get_channel_lpf_type(obj, channel_index):
    """NOT directly isolated for LPF specifically -- inferred from the clean
    structural parallel with HPF's confirmed byte 258. Treat with more
    caution than the confirmed fields in this module."""
    return _filter_type_name(channel_block(obj, channel_index)[262])


def set_channel_lpf_type(obj, channel_index, type_name):
    set_channel_byte(obj, channel_index, 262, _filter_type_code(type_name))


def get_channel_lpf_slope_db_per_oct(obj, channel_index):
    """CONFIRMED via two clean single-byte transitions: byte 263, same
    formula as HPF slope."""
    return (channel_block(obj, channel_index)[263] + 1) * 6


def set_channel_lpf_slope_db_per_oct(obj, channel_index, db_per_oct):
    if db_per_oct % 6 != 0 or not (6 <= db_per_oct <= 48):
        raise ValueError('LPF slope %d dB/octave must be a multiple of 6 between 6 and 48.' % db_per_oct)
    set_channel_byte(obj, channel_index, 263, (db_per_oct // 6) - 1)


# ---- PEQ bands (1-31) -------------------------------------------------------

def _band_offset(band):
    if not (1 <= band <= N_PEQ_BANDS):
        raise ValueError('PEQ band %r is out of range (1-%d).' % (band, N_PEQ_BANDS))
    return (band - 1) * PEQ_BAND_BYTES


def get_band_frequency_hz(obj, channel_index, band):
    """CONFIRMED, byte-perfect: band N (1-31) starts at (N-1)*8 in the
    channel block; frequency is the first two bytes, little-endian, direct
    integer Hz (no scaling)."""
    off = _band_offset(band)
    block = channel_block(obj, channel_index)
    return block[off] + block[off + 1] * 256


def set_band_frequency_hz(obj, channel_index, band, hz):
    if not (20 <= hz <= 20000):
        raise ValueError('PEQ band frequency %d Hz is outside 20-20000 Hz.' % hz)
    off = _band_offset(band)
    set_channel_byte(obj, channel_index, off, hz & 0xFF)
    set_channel_byte(obj, channel_index, off + 1, (hz >> 8) & 0xFF)


def get_band_gain_db(obj, channel_index, band):
    """CONFIRMED with an exact match: bytes offset+2/+3, same
    stored=round((dB+60)*10) formula as channel gain."""
    off = _band_offset(band)
    block = channel_block(obj, channel_index)
    stored = block[off + 2] + block[off + 3] * 256
    return (stored / 10.0) - 60.0


def validate_band_gain_db(gain_db):
    # Ported unchanged from the source's own range check -- see the module
    # docstring's "noted open discrepancy" about this vs. the UI-documented
    # -12..+12 dB PEQ range.
    if not (-60.0 <= gain_db <= 6.0):
        raise ValueError('PEQ band gain %.2f dB is outside a plausible -60..+6 dB range.' % gain_db)


def set_band_gain_db(obj, channel_index, band, gain_db):
    validate_band_gain_db(gain_db)
    off = _band_offset(band)
    stored = round((gain_db + 60.0) * 10.0)
    set_channel_byte(obj, channel_index, off + 2, stored & 0xFF)
    set_channel_byte(obj, channel_index, off + 3, (stored >> 8) & 0xFF)


def get_band_q(obj, channel_index, band):
    """PARTIAL: returns None for a code not in PEQ_Q_TABLE rather than
    guessing via interpolation -- the source project explicitly kept this a
    lookup table because code*Q drifts at both range extremes."""
    off = _band_offset(band)
    code = channel_block(obj, channel_index)[off + 4]
    return PEQ_Q_TABLE.get(code)


def set_band_q(obj, channel_index, band, q):
    matched = None
    for code, table_q in PEQ_Q_TABLE.items():
        if abs(table_q - q) < 0.01:
            matched = code
            break
    if matched is None:
        raise ValueError('Q value %.3f is not yet in the known lookup table (known values: %s). '
                         'Setting an unlisted Q is not supported until more of the table is '
                         'confirmed.' % (q, ', '.join('%.3f' % v for v in sorted(PEQ_Q_TABLE.values()))))
    off = _band_offset(band)
    set_channel_byte(obj, channel_index, off + 4, matched)


def get_band_is_allpass(obj, channel_index, band):
    """CONFIRMED from two clean transitions: byte offset+7 (previously
    assumed unused padding, always 0) encodes filter mode --
    0 = normal PEQ, 3 = all-pass."""
    off = _band_offset(band)
    return channel_block(obj, channel_index)[off + 7] == 3


def set_band_is_allpass(obj, channel_index, band, all_pass):
    off = _band_offset(band)
    set_channel_byte(obj, channel_index, off + 7, 3 if all_pass else 0)


# --------------------------------------------------------------------------
# Generic diff + write verification -- the Python equivalent of the source
# project's Compare-AlpinePresetObjects / Confirm-AlpinePresetFileMatchesExpected.
# Use this the same way afpx.roundtrip_lint is used: after any write, verify
# NOTHING outside the intended fields moved, rather than trusting the writer.
def diff_objects(a, b, path=''):
    """Recursive deep diff between two decoded (dict/list/scalar) structures.
    Returns a list of {'path','old','new'} dicts, empty if identical."""
    diffs = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a.keys()) | set(b.keys())):
            diffs.extend(diff_objects(a.get(key), b.get(key), '%s.%s' % (path, key)))
        return diffs
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append({'path': path, 'old': 'length=%d' % len(a), 'new': 'length=%d' % len(b)})
            return diffs
        for i, (av, bv) in enumerate(zip(a, b)):
            diffs.extend(diff_objects(av, bv, '%s[%d]' % (path, i)))
        return diffs
    if a != b:
        diffs.append({'path': path, 'old': a, 'new': b})
    return diffs


def verify_write(source_path, out_path, expected_channel_indices, expected_byte_offsets,
                 ignore_paths=('.data_info.data_upload_time',)):
    """Re-decodes both the new file and the source fresh and diffs them.
    Every difference must be one of ignore_paths (e.g. a save timestamp) or
    fall at .data.output.output[i][b] with i in expected_channel_indices and
    b in expected_byte_offsets -- anything else raises rather than let an
    unverified file be trusted. This is the same discipline
    Confirm-AlpinePresetFileMatchesExpected enforces in the source project."""
    import re
    reloaded = decode(out_path)
    original_again = decode(source_path)
    diffs = diff_objects(original_again, reloaded)
    unexpected = []
    pat = re.compile(r'^\.data\.output\.output\[(\d+)\]\[(\d+)\]$')
    for d in diffs:
        if d['path'] in ignore_paths:
            continue
        m = pat.match(d['path'])
        if not m:
            unexpected.append(d)
            continue
        idx, byte = int(m.group(1)), int(m.group(2))
        if idx not in expected_channel_indices or byte not in expected_byte_offsets:
            unexpected.append(d)
    if unexpected:
        lines = ['%s: %r -> %r' % (d['path'], d['old'], d['new']) for d in unexpected[:5]]
        raise ValueError('Write verification failed: %d unexpected change(s) beyond what was '
                         'expected. %s' % (len(unexpected), '; '.join(lines)))
    return {'diff_count': len(diffs)}


# --------------------------------------------------------------------------
def _make_synthetic_preset(n_channels=3):
    """A minimal but schema-shaped object for the selftest -- NOT a real
    Alpine preset (no real one is bundled; see decode()'s docstring on why).
    Verifies the codec and field accessors are internally consistent, not
    that field offsets match a real PC-Tool version -- validate against a
    real file (roundtrip_identical()) before trusting a generated file on
    real hardware."""
    block = [0] * CHANNEL_BLOCK_LEN
    return {'data': {'output': {'output': [list(block) for _ in range(n_channels)]}},
           'data_info': {'data_upload_time': '2026-01-01T00:00:00'}}


def _selftest():
    obj = _make_synthetic_preset()
    tmp = Path('_alpine_jssh_selftest.jssh')
    try:
        # container round-trip
        encode(obj, tmp)
        back = decode(tmp)
        assert back == obj, 'decode/encode round-trip mismatch on synthetic preset'

        # channel gain
        set_channel_gain_db(obj, 0, -3.2)
        assert abs(get_channel_gain_db(obj, 0) - (-3.2)) < 0.05, 'channel gain round-trip failed'

        # mute / polarity
        set_channel_muted(obj, 0, True)
        assert get_channel_muted(obj, 0) is True, 'mute round-trip failed'
        set_channel_muted(obj, 0, False)
        assert get_channel_muted(obj, 0) is False, 'unmute round-trip failed'
        set_channel_inverted(obj, 0, True)
        assert get_channel_inverted(obj, 0) is True, 'polarity round-trip failed'

        # delay
        set_channel_delay_ms(obj, 0, 1.5)
        assert abs(get_channel_delay_ms(obj, 0) - 1.5) < 0.02, 'delay round-trip failed'
        try:
            set_channel_delay_ms(obj, 0, 25.0)
            raise AssertionError('delay validation should have rejected 25 ms')
        except ValueError:
            pass

        # HPF/LPF
        set_channel_hpf_hz(obj, 0, 4500)
        set_channel_hpf_type(obj, 0, 'Butterworth')
        set_channel_hpf_slope_db_per_oct(obj, 0, 24)
        assert get_channel_hpf_hz(obj, 0) == 4500
        assert get_channel_hpf_type(obj, 0) == 'Butterworth'
        assert get_channel_hpf_slope_db_per_oct(obj, 0) == 24
        set_channel_lpf_hz(obj, 0, 250)
        set_channel_lpf_slope_db_per_oct(obj, 0, 30)
        assert get_channel_lpf_hz(obj, 0) == 250
        assert get_channel_lpf_slope_db_per_oct(obj, 0) == 30

        # PEQ band
        set_band_frequency_hz(obj, 1, 5, 1200)
        set_band_gain_db(obj, 1, 5, -2.5)
        set_band_q(obj, 1, 5, 1.0)          # exact table hit (code 134)
        set_band_is_allpass(obj, 1, 5, True)
        assert get_band_frequency_hz(obj, 1, 5) == 1200
        assert abs(get_band_gain_db(obj, 1, 5) - (-2.5)) < 0.05
        assert get_band_q(obj, 1, 5) == 1.0
        assert get_band_is_allpass(obj, 1, 5) is True
        try:
            set_band_q(obj, 1, 5, 3.14159)
            raise AssertionError('unlisted Q should have been rejected')
        except ValueError:
            pass

        # verify_write: expected-fields-only write passes; an out-of-scope
        # change is caught
        base = _make_synthetic_preset()
        encode(base, tmp)
        changed = copy.deepcopy(base)
        set_channel_hpf_hz(changed, 0, 3000)
        out = Path('_alpine_jssh_selftest_out.jssh')
        encode(changed, out)
        res = verify_write(tmp, out, expected_channel_indices=[0], expected_byte_offsets=[256, 257])
        assert res['diff_count'] == 2, 'expected exactly 2 diffs (both HPF Hz bytes)'
        sneaky = copy.deepcopy(base)
        set_channel_hpf_hz(sneaky, 0, 3000)
        set_channel_muted(sneaky, 1, False)  # an unexpected out-of-scope change
                                             # (False, not True: the synthetic
                                             # block's byte 248 defaults to 0
                                             # (=muted), so muted=True is a
                                             # same-value no-op that wouldn't
                                             # actually produce a diff here)
        encode(sneaky, out)
        try:
            verify_write(tmp, out, expected_channel_indices=[0], expected_byte_offsets=[256, 257])
            raise AssertionError('verify_write should have caught the unexpected mute change')
        except ValueError:
            pass
        out.unlink(missing_ok=True)

        print('SELFTEST PASSED (synthetic schema only -- verify against a real .jssh file too: '
              'roundtrip_identical(real_file) should report byte_identical=True)')
    finally:
        tmp.unlink(missing_ok=True)


def _main():
    if len(sys.argv) < 2:
        print('usage: python alpine_jssh.py {decode <file.jssh> | encode <file.json> <out.jssh> | selftest}')
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == 'selftest':
        _selftest()
    elif cmd == 'decode':
        obj = decode(sys.argv[2])
        out = Path(sys.argv[2]).with_suffix('.decoded.json')
        out.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding='utf-8')
        print('decoded ->', out)
    elif cmd == 'encode':
        obj = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
        encode(obj, sys.argv[3])
        print('encoded ->', sys.argv[3])
    else:
        print('unknown command:', cmd)
        sys.exit(1)


if __name__ == '__main__':
    _main()
