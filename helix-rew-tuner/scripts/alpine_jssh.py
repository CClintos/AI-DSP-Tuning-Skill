# alpine_jssh.py -- BETA. Decode/encode Alpine DSP PC-Tool ".jssh" preset
# files (confirmed on a PXE-X121-12EV). Read the caveats below first.
#
# STATUS: a Python port of a PowerShell implementation from a sibling project
# (an Alpine-specific tuning bridge) that reverse-engineered this format for
# personal interoperability with hardware the author owns -- this project did
# not perform that reverse-engineering itself, and inherits it at the same
# confidence level the source documented, field by field. Every reader and
# supported setter below carries the SAME "CONFIRMED" / "assumed, not yet
# isolated" marker the source gave it -- do not read a comment here as more
# certain than that. Crossover fields are inspect-only and have no setters.
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
# RUN preflight_real_file() ON A REAL PRESET BEFORE TRUSTING ANY WRITE, and
# report its verdict. "It decodes and the JSON looks right" is NOT the same
# bar as "Alpine will accept it". Nothing here silently guesses: decode()
# raises if the result isn't valid JSON, verify_write() raises if anything
# outside the expected fields changed, and preflight refuses a file whose
# channel blocks aren't the expected length.
#
# COMPATIBILITY WITH THE REAL ALPINE SOFTWARE -- the three things that make
# a file Alpine actually accepts, rather than one that merely parses:
#
#  1. NUMBER-TEXT PRESERVATION. decode() keeps each number's original source
#     text (_RawInt/_RawFloat) and encode() emits it verbatim for anything
#     not modified. This sidesteps a real trap: the ported PowerShell
#     serializer rewrites integral floats as integers (1.0 -> "1") and
#     non-integral ones as G17 (0.1 -> "0.10000000000000001"), while stdlib
#     json.dumps does neither -- so BOTH would silently rewrite parts of a
#     real file and break byte-identity, making a benign formatting
#     difference indistinguishable from a real content bug.
#
#  2. UI-REPRESENTABLE VALUES. Writing a number Alpine's own UI cannot
#     express risks the file and the screen disagreeing. PEQ frequencies are
#     quantized to Alpine's entry resolution (1 Hz below 1 kHz, 10 Hz at or
#     above -- see quantize_band_freq_hz); band gain is inherently on 0.1 dB
#     steps via its encoding, and delay on 1/96 ms steps via its own.
#
#  3. ALPINE'S LIMITS, NOT HELIX'S. See ALPINE_LIMITS/validate_band. Never
#     use tunelib.validate_peq_band on an Alpine file, and never leave
#     tunelib.fit_peq on its Helix-shaped defaults.
#
# STILL UNVERIFIED, and only a real file can close it: whether the hardware
# applies every written value exactly. Accepting a file is not proof the DSP
# honoured it -- read the values back through the Alpine UI after loading.
#
# CLI:
#   python alpine_jssh.py preflight <file.jssh>  # compatibility gate -- run this first
#   python alpine_jssh.py inspect <file.jssh>    # channel map + roles (step-1 intake)
#   python alpine_jssh.py decode <file.jssh>     # writes file.decoded.json
#   python alpine_jssh.py encode <file.json> <out.jssh>
#   python alpine_jssh.py selftest               # synthetic round-trip + field checks
import copy
import json
import sys
from pathlib import Path

import numpy as _np       # selftest only (fit_peq end-to-end check)

CHANNEL_BLOCK_LEN = 296       # confirmed length of one channel's value array
N_PEQ_BANDS = 31              # confirmed max PEQ bands per channel
PEQ_BAND_BYTES = 8            # confirmed per-band stride
CROSSOVER_BYTE_OFFSETS = frozenset(range(256, 264))

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

_FILTER_TYPE_NAME = {0: 'LR', 1: 'Butterworth', 2: 'Bessel'}

# Alpine PXE-X121-12EV hardware limits. These are ALPINE's, NOT Helix's --
# do NOT use tunelib.validate_peq_band here (that enforces Helix P SIX:
# -15..+6 dB, Q 0.5-15), and do NOT leave tunelib.fit_peq on its Helix-
# shaped defaults (g_lim=(-15,3), q_lim=(0.5,8)) when fitting for an Alpine.
# Use WRITABLE_Q_RANGE below as fit_peq's q_lim so the optimizer can't
# return a Q this module then has to refuse or snap far.
ALPINE_LIMITS = {
    'peq_freq_hz': (20, 20000),      # band frequency, per the source project
    'peq_gain_db': (-12.0, 12.0),    # Alpine UI's documented PEQ range
    'peq_q': (0.404, 28.852),        # Alpine UI's documented Q range
    'n_bands': N_PEQ_BANDS,
    'channel_gain_db': (-60.0, 6.0),
    'delay_ms': (0.0, 20.0),
}

# The Q values this module can actually WRITE -- narrower than Alpine's own
# 0.404-28.852 UI range, because the confirmed lookup table only spans these
# 13 points. Anything outside this span cannot be written at all (not even
# by snapping), so constrain the optimizer to it up front.
WRITABLE_Q_RANGE = (min(PEQ_Q_TABLE.values()), max(PEQ_Q_TABLE.values()))

# Off-conventions, per the source project's README: an Alpine HPF at 20 Hz
# and an LPF at 40000 Hz mean "filter off", not "a real 20 Hz/40 kHz corner".
# channels() maps these to None so role inference isn't fooled by them.
HPF_OFF_HZ = 20
LPF_OFF_HZ = 40000


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
    return json.loads(decode_bytes(path).decode('utf-8'),
                     parse_int=_RawInt, parse_float=_RawFloat)


class _RawInt(int):
    """An int that remembers exactly how it was written in the source file."""

    def __new__(cls, text):
        obj = int.__new__(cls, text)
        obj.raw = text
        return obj


class _RawFloat(float):
    """A float that remembers exactly how it was written in the source file."""

    def __new__(cls, text):
        obj = float.__new__(cls, text)
        obj.raw = text
        return obj


def _alpine_json(value):
    """Serialize back to Alpine's exact byte representation.

    The core trick is NUMBER-TEXT PRESERVATION, not reproducing Alpine's
    number formatting rules. decode() parses numbers into _RawInt/_RawFloat,
    which carry the original text; this emits that text verbatim for any
    value that was not modified. That makes an unmodified round-trip
    byte-identical **regardless of how Alpine chooses to format numbers** --
    no guessing required.

    That matters because guessing was demonstrably unsafe. The ported
    PowerShell serializer converts integral floats to integers (1.0 -> "1")
    and non-integral ones to G17 (0.1 -> "0.10000000000000001"); stdlib
    json.dumps does neither (repr(): "1.0" and "0.1"). Reimplementing either
    rule CHANGES a file that happens to contain the other form, silently
    breaking byte-identity -- which is exactly what roundtrip_identical()
    exists to detect, so a benign formatting difference would become
    indistinguishable from a real content bug. Preserving the source text
    sidesteps the entire question.

    Values this module WRITES are plain Python ints (all the byte fields
    are), which serialize unambiguously as JSON integers; only those change.

    String escaping matches the confirmed reference too: only " \\ \\n \\r \\t
    get short escapes, any other char below 0x20 becomes \\uXXXX, and
    everything else is emitted as literal UTF-8. (stdlib additionally emits
    \\b and \\f short escapes; those are vanishingly unlikely in a DSP preset
    but would be a divergence, so they are handled the reference way here.)"""
    if value is None:
        return 'null'
    if isinstance(value, bool):            # MUST precede int -- bool subclasses int
        return 'true' if value else 'false'
    raw = getattr(value, 'raw', None)      # untouched number -> emit source text verbatim
    if raw is not None:
        return raw
    if isinstance(value, str):
        out = ['"']
        for ch in value:
            if ch == '"':
                out.append('\\"')
            elif ch == '\\':
                out.append('\\\\')
            elif ch == '\n':
                out.append('\\n')
            elif ch == '\r':
                out.append('\\r')
            elif ch == '\t':
                out.append('\\t')
            elif ord(ch) < 0x20:
                out.append('\\u%04x' % ord(ch))
            else:
                out.append(ch)
        out.append('"')
        return ''.join(out)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return '%.17G' % value
    if isinstance(value, dict):
        return '{' + ','.join('%s:%s' % (_alpine_json(str(k)), _alpine_json(v))
                              for k, v in value.items()) + '}'
    if isinstance(value, (list, tuple)):
        return '[' + ','.join(_alpine_json(v) for v in value) + ']'
    raise TypeError('_alpine_json: unsupported type %s for value %r'
                    % (type(value).__name__, value))


def find_unverified_constructs(obj, path=''):
    """INFORMATIONAL scan for float values in a decoded preset.

    Not a blocker: because decode() preserves each number's source text
    (see _alpine_json), a float that is never modified round-trips
    byte-identically no matter how Alpine formats it. This exists to
    surface where floats live at all, since a float in a field this module
    might WRITE would be re-serialized from its numeric value rather than
    its source text -- and every field these setters touch is an integer
    byte, so that should never happen. If this reports a float inside
    data.output.output, treat it as a genuine surprise worth understanding
    before writing."""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.extend(find_unverified_constructs(v, '%s.%s' % (path, k)))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            found.extend(find_unverified_constructs(v, '%s[%d]' % (path, i)))
    elif isinstance(obj, float) and not isinstance(obj, bool):
        found.append({'path': path, 'value': float(obj),
                     'in_channel_data': path.startswith('.data.output.output'),
                     'reason': 'float value -- round-trips verbatim if untouched, but '
                               'would be reformatted if this module writes to it'})
    return found


def encode(obj, path):
    """Parsed Python object -> .jssh, using Alpine's own number/string
    formatting rules (see _alpine_json). NOT independently re-verified from
    this Python port against a real Alpine-produced file -- run
    preflight_real_file() on your own real preset before trusting a
    generated file on real hardware, exactly as the source project's own
    mandatory round-trip self-test required."""
    encode_bytes(_alpine_json(obj).encode('utf-8'), path)


def preflight_real_file(path):
    """THE compatibility gate. Run this on a REAL .jssh before trusting any
    generated file on real hardware, and report its verdict to the user.

    "It decodes and the JSON looks right" is NOT the same as "Alpine will
    accept it". This checks the things that actually differ between those
    two bars:
      1. does it decode at all (valid JSON under the position-XOR)?
      2. does an UNMODIFIED read+write reproduce the original file
         byte-for-byte? If not, this port's serializer disagrees with
         Alpine's somewhere, and every generated file inherits that
         disagreement.
      3. does it contain JSON constructs whose Alpine formatting nobody has
         verified (non-integral floats)?
      4. does it have the channel structure the field accessors assume?

    Returns a dict including 'verdict' -- 'safe_to_write' only when all
    checks pass. Anything else means: read the file fine, but do NOT write
    one back until the cause is understood."""
    result = {'path': str(path), 'decodes': False, 'byte_identical': False,
             'unverified_constructs': [], 'channel_count': None,
             'block_len_ok': None, 'verdict': 'do_not_write', 'reasons': []}
    try:
        obj = decode(path)
    except Exception as e:
        result['reasons'].append('does not decode: %s' % e)
        return result
    result['decodes'] = True

    rt = roundtrip_identical(path)
    result['byte_identical'] = rt['byte_identical']
    result['source_len'] = rt['source_len']
    result['output_len'] = rt['output_len']
    if not rt['byte_identical']:
        result['reasons'].append(
            'unmodified read+write is NOT byte-identical (%d -> %d bytes). This port\'s '
            'serializer disagrees with Alpine\'s somewhere; any generated file inherits '
            'that difference. Do not write until this is understood.'
            % (rt['source_len'], rt['output_len']))

    # Informational unless a float sits in the channel data this module
    # writes to -- an untouched float round-trips verbatim, but one inside a
    # byte block would be reformatted by a write and is a real surprise.
    result['unverified_constructs'] = find_unverified_constructs(obj)
    in_ch = [c for c in result['unverified_constructs'] if c['in_channel_data']]
    if in_ch:
        result['reasons'].append(
            '%d float(s) found INSIDE data.output.output (e.g. %s) -- the byte fields are '
            'expected to be integers; writing near these could reformat them.'
            % (len(in_ch), in_ch[0]['path']))

    try:
        blocks = obj['data']['output']['output']
        result['channel_count'] = len(blocks)
        bad = [i for i, b in enumerate(blocks) if len(b) != CHANNEL_BLOCK_LEN]
        result['block_len_ok'] = not bad
        if bad:
            result['reasons'].append(
                'channel block(s) %s are not %d values long -- the field offsets in this '
                'module assume that layout and would write to the wrong place.'
                % (bad, CHANNEL_BLOCK_LEN))
    except (KeyError, TypeError) as e:
        result['reasons'].append('missing expected data.output.output structure: %s' % e)
        result['block_len_ok'] = False

    if result['decodes'] and result['byte_identical'] and not result['reasons']:
        result['verdict'] = 'safe_to_write'
    return result


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
    setter here uses it rather than assuming a list is mutated by reference.
    Crossover offsets are read-only repository-wide and are rejected here so
    no higher-level or ad-hoc caller can bypass that policy."""
    if byte_offset in CROSSOVER_BYTE_OFFSETS:
        raise ValueError(
            'Alpine crossover byte offset %d is read-only; crossovers cannot '
            'be written or changed.' % byte_offset)
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


def get_channel_lpf_hz(obj, channel_index):
    """CONFIRMED against one real set value: bytes 260-261, little-endian,
    direct Hz."""
    block = channel_block(obj, channel_index)
    return block[260] + block[261] * 256


def _filter_type_name(code):
    return _FILTER_TYPE_NAME.get(code, 'Unknown(%d)' % code)


def get_channel_hpf_type(obj, channel_index):
    """CONFIRMED via two clean single-byte transitions: byte 258.
    0=LR, 1=Butterworth, 2=Bessel."""
    return _filter_type_name(channel_block(obj, channel_index)[258])


def get_channel_hpf_slope_db_per_oct(obj, channel_index):
    """CONFIRMED via two clean single-byte transitions: byte 259,
    stored = slopeIndex-1, dB/oct = (stored+1)*6 (0-7 -> 6-48 dB/oct)."""
    return (channel_block(obj, channel_index)[259] + 1) * 6


def get_channel_lpf_type(obj, channel_index):
    """NOT directly isolated for LPF specifically -- inferred from the clean
    structural parallel with HPF's confirmed byte 258. Treat with more
    caution than the confirmed fields in this module."""
    return _filter_type_name(channel_block(obj, channel_index)[262])


def get_channel_lpf_slope_db_per_oct(obj, channel_index):
    """CONFIRMED via two clean single-byte transitions: byte 263, same
    formula as HPF slope."""
    return (channel_block(obj, channel_index)[263] + 1) * 6


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
    """Enforces Alpine's DOCUMENTED PEQ band range, -12..+12 dB.

    DELIBERATE DEVIATION from the ported source, which range-checked band
    gain as -60..+6 dB. That figure is the CHANNEL-gain range (same formula,
    checked identically a few functions up) and appears to have been reused
    for bands rather than independently established -- it is wrong for a band
    in both directions: it forbids a legal +7..+12 dB boost while permitting
    -60 dB, far below anything Alpine's PEQ UI accepts. The stored encoding
    (round((dB+60)*10), two bytes LE) can physically hold a much wider span
    than either range; that is an encoding capability, not permission. If you
    have primary-source evidence the band field really does accept beyond
    +/-12, widen ALPINE_LIMITS['peq_gain_db'] deliberately rather than
    loosening this check."""
    glo, ghi = ALPINE_LIMITS['peq_gain_db']
    if not (glo <= gain_db <= ghi):
        raise ValueError('PEQ band gain %.2f dB is outside Alpine\'s documented %+.0f..%+.0f dB '
                         'range.' % (gain_db, glo, ghi))


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


def snap_q(q):
    """Nearest WRITABLE Q (a PEQ_Q_TABLE entry) to `q`, chosen on a log scale
    since Q is perceptually ratio-like. Returns (code, snapped_q, ratio_error)
    where ratio_error = snapped/requested (1.0 = exact hit).

    Why snapping is needed at all: any real optimizer (tunelib.fit_peq) returns
    CONTINUOUS Q, but only 13 discrete Q codes are confirmed for this format,
    so an exact-match-only writer rejects almost every computed filter and
    makes the whole measure -> fit -> write pipeline unusable. Measured cost of
    snapping across the practical Q range (0.6-6.5) at gains up to 6 dB: worst
    case ~0.44 dB, typically ~0.2-0.3 dB of magnitude error versus the
    requested filter -- below the "few tenths of a dB is inaudible" bar the
    methodology already uses elsewhere. That makes snapping SAFE, but it is
    still a real deviation from what was computed, so it is never silent:
    set_band_q(snap=True) returns the actual Q used, and write_peq_bands()
    reports the worst snap in the whole set.

    Raises ValueError if `q` is outside WRITABLE_Q_RANGE entirely -- that is
    not a snap, it's an unrepresentable value, and pretending otherwise would
    write a filter materially different from the one that was asked for."""
    lo, hi = WRITABLE_Q_RANGE
    if not (lo * 0.999 <= q <= hi * 1.001):
        raise ValueError('Q %.3f is outside the writable range %.3f-%.3f for this format '
                         '(only %d Q codes are confirmed). Constrain the optimizer with '
                         'q_lim=WRITABLE_Q_RANGE instead of snapping from outside it.'
                         % (q, lo, hi, len(PEQ_Q_TABLE)))
    import math
    code = min(PEQ_Q_TABLE, key=lambda c: abs(math.log(PEQ_Q_TABLE[c] / q)))
    snapped = PEQ_Q_TABLE[code]
    return code, snapped, snapped / q


def set_band_q(obj, channel_index, band, q, snap=False):
    """Write a band's Q. By default requires an exact table hit (within 0.01)
    and raises otherwise -- the conservative original behaviour. Pass
    snap=True to write the nearest writable Q instead; it RETURNS the Q
    actually written so the caller can report the deviation rather than
    silently assume the requested value landed."""
    if snap:
        code, snapped, _ratio = snap_q(q)
        set_channel_byte(obj, channel_index, _band_offset(band) + 4, code)
        return snapped
    matched = None
    for code, table_q in PEQ_Q_TABLE.items():
        if abs(table_q - q) < 0.01:
            matched = code
            break
    if matched is None:
        raise ValueError('Q value %.3f is not in the confirmed lookup table (known values: %s). '
                         'Pass snap=True to write the nearest writable Q instead (typically '
                         '<0.3 dB of error, worst case ~0.44 dB), or constrain your optimizer '
                         'to those values up front.'
                         % (q, ', '.join('%.3f' % v for v in sorted(PEQ_Q_TABLE.values()))))
    set_channel_byte(obj, channel_index, _band_offset(band) + 4, matched)
    return PEQ_Q_TABLE[matched]


def quantize_band_freq_hz(hz):
    """Snap a PEQ frequency to a value Alpine's UI can actually represent:
    1 Hz steps below 1000 Hz, 10 Hz steps at/above it.

    Source: the same author's separate, real-hardware-tested Alpine entry
    tool uses exactly this rule to produce "values you can actually type
    into the Alpine". Writing an unrepresentable frequency (e.g. 1997 Hz)
    into the FILE risks the file and the UI disagreeing -- Alpine may
    display or re-save a snapped value while the stored byte says otherwise,
    which is the kind of silent mismatch that makes a verified write
    meaningless. The acoustic cost of quantizing is nil: 10 Hz at 2 kHz is
    0.5%, well under a hundredth of a semitone."""
    hz = float(hz)
    return int(round(hz)) if hz < 1000 else int(round(hz / 10.0) * 10)


def validate_band(freq_hz, q, gain_db):
    """Enforce ALPINE's PEQ limits (not Helix's -- see ALPINE_LIMITS). Checks
    the DSP's own documented ranges, plus that Q is actually writable by this
    module. Raises ValueError. This is the Alpine equivalent of
    tunelib.validate_peq_band; do not use that one for an Alpine file."""
    flo, fhi = ALPINE_LIMITS['peq_freq_hz']
    glo, ghi = ALPINE_LIMITS['peq_gain_db']
    qlo, qhi = ALPINE_LIMITS['peq_q']
    if not (flo <= freq_hz <= fhi):
        raise ValueError('PEQ frequency %.1f Hz outside Alpine range %d-%d Hz.' % (freq_hz, flo, fhi))
    if not (glo <= gain_db <= ghi):
        raise ValueError('PEQ gain %.2f dB outside Alpine range %+.0f..%+.0f dB.' % (gain_db, glo, ghi))
    if not (qlo <= q <= qhi):
        raise ValueError('PEQ Q %.3f outside Alpine range %.3f-%.3f.' % (q, qlo, qhi))
    wlo, whi = WRITABLE_Q_RANGE
    if not (wlo * 0.999 <= q <= whi * 1.001):
        raise ValueError('PEQ Q %.3f is legal on the Alpine but NOT writable by this module '
                         '(only %.3f-%.3f is covered by the confirmed Q table).'
                         % (q, wlo, whi))
    return True


def write_peq_bands(obj, channel_index, bands, snap=True, clear_remaining=True,
                    quantize_freq=True):
    """Write a full computed filter set (the shape tunelib.fit_peq returns:
    a list of (F, Q, G)) into a channel, validating every band against
    ALPINE's limits first and reporting exactly what was written.

    This is the function that makes a measured -> fitted -> written workflow
    actually possible on this format, instead of hand-calling three setters
    per band and discovering mid-way that a Q is unwritable. Nothing is
    written unless EVERY band validates -- a partial write would leave the
    preset in a state matching neither the old tune nor the new one.

    clear_remaining zeroes the gain of every band after the ones supplied, so
    a previous, longer filter set can't leave stale bands active behind the
    new one (the same reason afpx's writers care about untouched slots).

    Returns {'written': [(F, Q_actual, G), ...], 'worst_q_snap_ratio': float,
    'snapped_count': int} -- report worst_q_snap_ratio to the user rather than
    claiming the requested Q was applied exactly."""
    if len(bands) > N_PEQ_BANDS:
        raise ValueError('%d bands requested but this format has only %d per channel.'
                         % (len(bands), N_PEQ_BANDS))
    prepared = []
    for F, Q, G in bands:
        q_target = Q
        if snap:
            _code, q_target, _ratio = snap_q(Q)     # raises if outside writable range
        f_target = quantize_band_freq_hz(F) if quantize_freq else int(round(F))
        validate_band(f_target, q_target, G)
        prepared.append((f_target, Q, q_target, G))

    written, worst_ratio, snapped = [], 1.0, 0
    for i, (F, Q_req, Q_use, G) in enumerate(prepared, start=1):
        set_band_frequency_hz(obj, channel_index, i, int(round(F)))
        set_band_gain_db(obj, channel_index, i, G)
        set_band_q(obj, channel_index, i, Q_use, snap=False)
        ratio = Q_use / Q_req
        if abs(ratio - 1.0) > 1e-6:
            snapped += 1
            if abs(ratio - 1.0) > abs(worst_ratio - 1.0):
                worst_ratio = ratio
        written.append((F, Q_use, G))
    if clear_remaining:
        for i in range(len(prepared) + 1, N_PEQ_BANDS + 1):
            set_band_gain_db(obj, channel_index, i, 0.0)
    return {'written': written, 'worst_q_snap_ratio': worst_ratio, 'snapped_count': snapped}


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
# Whole-file inspection -- the Alpine equivalent of afpx.channels(), and the
# reason it exists: the tuning workflow's FIRST step is confirming the channel
# map with the user ("nothing is assumed"), which needs a per-channel summary
# of crossovers/levels/delay/roles, not 40 individual getter calls.
def band_summary(obj, channel_index):
    """Every PEQ band on a channel: [{'band','freq_hz','gain_db','q','all_pass',
    'active'}]. 'active' = |gain| >= 0.05 dB (Alpine keeps all 31 band records
    present at all times, so a band is 'unused' by having no gain, not by being
    absent). 'q' is None if the stored Q code isn't in the confirmed table --
    that's a real unknown, not a zero."""
    out = []
    for b in range(1, N_PEQ_BANDS + 1):
        gain = get_band_gain_db(obj, channel_index, b)
        out.append({'band': b,
                   'freq_hz': get_band_frequency_hz(obj, channel_index, b),
                   'gain_db': round(gain, 2),
                   'q': get_band_q(obj, channel_index, b),
                   'all_pass': get_band_is_allpass(obj, channel_index, b),
                   'active': abs(gain) >= 0.05})
    return out


def channels(obj):
    """Per-channel summary with an INFERRED driver role, mirroring
    afpx.channels() so both formats present the same shape to the workflow.

    Role inference reuses afpx.infer_role (a pure crossover heuristic, not
    Helix-specific) and is explicitly a STARTING POINT for the user to
    confirm or correct -- never treated as truth, same as the .afpx path.
    Alpine's filter-off conventions (HPF 20 Hz / LPF 40000 Hz) are mapped to
    None before inference so an 'off' filter isn't misread as a real 20 Hz
    or 40 kHz corner."""
    try:
        from afpx import infer_role
    except ImportError:                                  # pragma: no cover
        def infer_role(hp, lp):
            return 'unknown (afpx.py not importable)'
    out = []
    for i in range(len(obj['data']['output']['output'])):
        hp = get_channel_hpf_hz(obj, i)
        lp = get_channel_lpf_hz(obj, i)
        hp_eff = None if hp <= HPF_OFF_HZ else hp
        lp_eff = None if lp >= LPF_OFF_HZ else lp
        bands = band_summary(obj, i)
        active = [b for b in bands if b['active']]
        out.append({
            'index': i,
            'channel_number': i + 1,
            'inferred_role': infer_role(hp_eff, lp_eff),
            'hp_hz': hp_eff, 'lp_hz': lp_eff,
            'hp_raw_hz': hp, 'lp_raw_hz': lp,
            'hp_type': get_channel_hpf_type(obj, i),
            'hp_slope_db_oct': get_channel_hpf_slope_db_per_oct(obj, i),
            'lp_type': get_channel_lpf_type(obj, i),
            'lp_slope_db_oct': get_channel_lpf_slope_db_per_oct(obj, i),
            'gain_db': round(get_channel_gain_db(obj, i), 2),
            'delay_ms': round(get_channel_delay_ms(obj, i), 3),
            'muted': get_channel_muted(obj, i),
            'inverted': get_channel_inverted(obj, i),
            'active_band_count': len(active),
            'free_band_count': N_PEQ_BANDS - len(active),
            'all_pass_bands': [b['band'] for b in bands if b['all_pass']],
            'bands': bands,
        })
    return out


def format_channels(chans):
    """Human-readable inspect output -- what the user actually confirms the
    channel map against."""
    lines = []
    for c in chans:
        xo = '%s-%s Hz' % ('off' if c['hp_hz'] is None else '%d' % c['hp_hz'],
                          'off' if c['lp_hz'] is None else '%d' % c['lp_hz'])
        flags = []
        if c['muted']:
            flags.append('MUTED')
        if c['inverted']:
            flags.append('INVERTED')
        if c['all_pass_bands']:
            flags.append('AP:%s' % ','.join(str(b) for b in c['all_pass_bands']))
        lines.append('CH%-3d %-18s %-16s %2d/%d bands  gain %+6.2f dB  delay %6.3f ms  %s'
                     % (c['channel_number'], c['inferred_role'], xo,
                        c['active_band_count'], N_PEQ_BANDS,
                        c['gain_db'], c['delay_ms'], ' '.join(flags)))
    return '\n'.join(lines)


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
    Confirm-AlpinePresetFileMatchesExpected enforces in the source project.
    Crossover offsets can never be declared expected: they are read-only."""
    import re
    requested_crossover_offsets = sorted(
        set(expected_byte_offsets) & CROSSOVER_BYTE_OFFSETS)
    if requested_crossover_offsets:
        raise ValueError(
            'Alpine crossover byte offset(s) %s cannot be authorized for a '
            'write; crossovers are read-only.'
            % ', '.join(str(offset) for offset in requested_crossover_offsets))
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
    """A schema-shaped, ACOUSTICALLY NEUTRAL object for the selftest -- NOT a
    real Alpine preset (no real one is bundled; see decode()'s docstring on
    why). Verifies the codec and field accessors are internally consistent,
    not that field offsets match a real PC-Tool version -- validate against a
    real file (roundtrip_identical()) before trusting a generated file on
    real hardware.

    IMPORTANT, and a real trap this fixture exists to avoid: an all-zero
    block is NOT a neutral preset. Both gain fields encode as
    stored=round((dB+60)*10), so a zero byte pair decodes to -60 dB, not
    0 dB -- a zero-filled fixture reads back as every band cut to -60 dB
    and every channel muted-by-gain. A genuinely flat/unused band stores
    600 (0x0258). This builds that true neutral state via supported setters,
    with crossover bytes seeded directly for read-only inspection, so tests
    measure real behaviour instead of an artefact of the fixture."""
    block = [0] * CHANNEL_BLOCK_LEN
    obj = {'data': {'output': {'output': [list(block) for _ in range(n_channels)]}},
          'data_info': {'data_upload_time': '2026-01-01T00:00:00'}}
    for i in range(n_channels):
        set_channel_gain_db(obj, i, 0.0)
        set_channel_delay_ms(obj, i, 0.0)
        set_channel_muted(obj, i, False)
        set_channel_inverted(obj, i, False)
        # Seed read-only crossover bytes directly in this synthetic fixture.
        # Production write helpers deliberately cannot touch offsets 256-263.
        channel = channel_block(obj, i)
        channel[256] = HPF_OFF_HZ & 0xFF
        channel[257] = (HPF_OFF_HZ >> 8) & 0xFF
        channel[258] = 0  # LR
        channel[259] = 3  # 24 dB/oct
        channel[260] = LPF_OFF_HZ & 0xFF
        channel[261] = (LPF_OFF_HZ >> 8) & 0xFF
        channel[262] = 0  # LR
        channel[263] = 3  # 24 dB/oct
        for b in range(1, N_PEQ_BANDS + 1):
            set_band_gain_db(obj, i, b, 0.0)        # flat = stored 600, not 0
            set_band_q(obj, i, b, 1.0, snap=True)
            set_band_is_allpass(obj, i, b, False)
    return obj


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

        # HPF/LPF are inspect-only. Seed captured-style bytes directly so the
        # getters remain covered without exposing a production write surface.
        xover = channel_block(obj, 0)
        xover[256], xover[257] = 4500 & 0xFF, (4500 >> 8) & 0xFF
        xover[258], xover[259] = 1, 3  # Butterworth, 24 dB/oct
        assert get_channel_hpf_hz(obj, 0) == 4500
        assert get_channel_hpf_type(obj, 0) == 'Butterworth'
        assert get_channel_hpf_slope_db_per_oct(obj, 0) == 24
        xover[260], xover[261] = 250 & 0xFF, (250 >> 8) & 0xFF
        xover[263] = 4
        assert get_channel_lpf_hz(obj, 0) == 250
        assert get_channel_lpf_slope_db_per_oct(obj, 0) == 30
        assert not any(name in globals() for name in (
            'set_channel_hpf_hz', 'set_channel_lpf_hz',
            'set_channel_hpf_type', 'set_channel_lpf_type',
            'set_channel_hpf_slope_db_per_oct',
            'set_channel_lpf_slope_db_per_oct'))
        for offset in CROSSOVER_BYTE_OFFSETS:
            try:
                set_channel_byte(obj, 0, offset, 0)
                raise AssertionError('crossover offset %d should be read-only' % offset)
            except ValueError:
                pass

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
        set_band_gain_db(changed, 0, 1, -3.0)
        out = Path('_alpine_jssh_selftest_out.jssh')
        encode(changed, out)
        res = verify_write(tmp, out, expected_channel_indices=[0], expected_byte_offsets=[2, 3])
        assert res['diff_count'] == 1, '0 to -3 dB should change only the low PEQ gain byte'
        sneaky = copy.deepcopy(base)
        set_band_gain_db(sneaky, 0, 1, -3.0)
        # An unexpected out-of-scope change. Flip whatever the CURRENT value
        # is rather than hardcoding one -- twice now this assertion silently
        # passed-by-not-testing because the value written happened to equal
        # the fixture's default, making the "change" a no-op that produced no
        # diff for verify_write to catch. Deriving it from the live value
        # makes the test independent of the fixture's defaults.
        set_channel_muted(sneaky, 1, not get_channel_muted(sneaky, 1))
        encode(sneaky, out)
        try:
            verify_write(tmp, out, expected_channel_indices=[0], expected_byte_offsets=[2, 3])
            raise AssertionError('verify_write should have caught the unexpected mute change')
        except ValueError:
            pass
        out.unlink(missing_ok=True)

        # ---- Q snapping: the fix that makes a computed filter set writable --
        code, snapped, ratio = snap_q(2.0)
        assert abs(snapped - 1.983) < 1e-6, 'Q 2.0 should snap to the 1.983 table entry'
        assert abs(ratio - 1.0) < 0.02, 'Q 2.0 -> 1.983 should be a <2%% change'
        try:
            snap_q(50.0)
            raise AssertionError('snap_q must refuse a Q outside the writable range')
        except ValueError:
            pass
        # exact-match mode must still refuse (conservative default preserved)
        try:
            set_band_q(obj, 0, 1, 2.0, snap=False)
            raise AssertionError('set_band_q(snap=False) must refuse a non-table Q')
        except ValueError:
            pass
        assert abs(set_band_q(obj, 0, 1, 2.0, snap=True) - 1.983) < 1e-6

        # ---- Alpine limits are ALPINE's, not Helix's ------------------------
        validate_band(1000.0, 1.5, 9.0)          # +9 dB is legal on Alpine...
        import tunelib as _T
        try:
            _T.validate_peq_band(1000.0, 1.5, 9.0)   # ...but NOT on Helix
            raise AssertionError('Helix validator should reject +9 dB')
        except ValueError:
            pass
        try:
            validate_band(1000.0, 1.5, 15.0)     # beyond Alpine's own +/-12
            raise AssertionError('validate_band should reject +15 dB')
        except ValueError:
            pass
        try:
            validate_band(1000.0, 20.0, 3.0)     # legal Alpine Q, NOT writable
            raise AssertionError('validate_band should reject an unwritable Q')
        except ValueError:
            pass

        # ---- end-to-end: a real fit_peq result must be writable -------------
        freqs = 24000.0 / (_T.LOGSTEP ** (1231 - _np.arange(1232)))
        dev = _T.peaking_db(freqs, 500.0, 2.0, 5.0) + _T.peaking_db(freqs, 2000.0, 1.0, 4.0)
        fitted, _rep = _T.fit_peq(freqs, dev, (100, 8000), n_bands_max=4,
                                 q_lim=WRITABLE_Q_RANGE, g_lim=(-12.0, 3.0))
        assert fitted, 'fit_peq returned no bands for a synthetic 2-peak deviation'
        target = _make_synthetic_preset()
        res = write_peq_bands(target, 0, fitted, snap=True)
        assert len(res['written']) == len(fitted), 'not every fitted band was written'
        for (F, Q, G) in res['written']:
            validate_band(F, Q, G)               # everything written is legal + writable
        assert abs(res['worst_q_snap_ratio'] - 1.0) < 0.25, \
            'Q snapping moved a band more than 25%% -- unexpectedly coarse'
        # read back what was written
        assert get_band_frequency_hz(target, 0, 1) == int(round(res['written'][0][0]))
        # bands beyond the written set were cleared, not left stale
        assert abs(get_band_gain_db(target, 0, N_PEQ_BANDS)) < 0.05, \
            'trailing bands should be cleared so a longer previous set cannot persist'

        # ---- channels(): the step-1 channel-map inspect ---------------------
        insp = _make_synthetic_preset(n_channels=2)
        insp0, insp1 = channel_block(insp, 0), channel_block(insp, 1)
        insp0[256], insp0[257] = 3150 & 0xFF, (3150 >> 8) & 0xFF
        insp1[260], insp1[261] = 80 & 0xFF, (80 >> 8) & 0xFF
        set_band_gain_db(insp, 0, 3, -2.0)
        chans = channels(insp)
        assert len(chans) == 2
        assert chans[0]['inferred_role'] == 'tweeter', \
            'HPF 3150 Hz should infer a tweeter, got %r' % chans[0]['inferred_role']
        assert chans[1]['inferred_role'] == 'sub', \
            'LPF 80 Hz should infer a sub, got %r' % chans[1]['inferred_role']
        assert chans[0]['lp_hz'] is None, 'LPF 40000 must read as off, not a real corner'
        assert chans[1]['hp_hz'] is None, 'HPF 20 must read as off, not a real corner'
        assert chans[0]['active_band_count'] == 1, 'exactly one band was given gain'
        assert chans[0]['free_band_count'] == N_PEQ_BANDS - 1
        assert format_channels(chans), 'format_channels produced no output'

        # ---- Alpine-exact serialization (the "will Alpine accept it" bar) ---
        # Integral floats must emit as integers the way Alpine writes them --
        # stdlib json.dumps would emit "1.0" here and silently break
        # byte-identity against a real Alpine-produced file.
        assert _alpine_json(1.0) == '1', 'integral float must serialize as an integer'
        assert _alpine_json(100.0) == '100'
        assert _alpine_json(True) == 'true' and _alpine_json(False) == 'false'
        assert _alpine_json(1) == '1', 'bool/int ordering bug (bool subclasses int)'
        assert _alpine_json(None) == 'null'
        assert _alpine_json({'a': [1, 2]}) == '{"a":[1,2]}', 'must be compact, no spaces'
        assert _alpine_json('café') == '"café"', 'non-ASCII must stay literal UTF-8'
        assert _alpine_json('a"b\\c\nd') == '"a\\"b\\\\c\\nd"'
        assert _alpine_json('\x08') == '"\\u0008"', 'control chars use \\uXXXX, not \\b'
        assert json.loads(_alpine_json({'x': [1, 2.5, 'y', None, True]})) == \
            {'x': [1, 2.5, 'y', None, True]}, 'output must still be valid, faithful JSON'

        # the float scanner locates floats and flags whether they sit in
        # channel byte data (the only place they'd actually be a problem)
        assert find_unverified_constructs({'a': {'b': 0.1}})[0]['path'] == '.a.b'
        assert find_unverified_constructs({'a': 1, 'c': 'x'}) == [], 'ints/strings are not floats'
        assert find_unverified_constructs(
            {'data': {'output': {'output': [[1.5]]}}})[0]['in_channel_data'] is True

        # ---- NUMBER-TEXT PRESERVATION: the real compatibility guarantee ----
        # An unmodified round-trip must be byte-identical no matter HOW Alpine
        # formats numbers -- covering both forms the two candidate serializer
        # rules disagree on (integral 1.0 and non-integral 0.1). Reimplementing
        # either rule would rewrite one of these and silently break byte-identity.
        _blk = json.dumps([0] * CHANNEL_BLOCK_LEN, separators=(',', ':'))
        for literal in ('1.0', '0.1', '1', '1e3', '100.0', '-0.0'):
            src = ('{"data":{"output":{"output":[%s]}},"data_info":{"v":%s}}'
                   % (_blk, literal))
            tp = Path('_alpine_jssh_numfmt.jssh')
            tp.write_bytes(_xor_by_position(src.encode('utf-8')))
            assert roundtrip_identical(tp)['byte_identical'], \
                'unmodified round-trip must preserve the literal %s exactly' % literal
            assert preflight_real_file(tp)['verdict'] == 'safe_to_write', \
                'a file containing %s should still pass preflight' % literal
            tp.unlink(missing_ok=True)
        # ...and a MODIFIED file must change only the intended bytes
        src = '{"data":{"output":{"output":[%s]}},"data_info":{"v":1.0}}' % json.dumps(
            [0] * CHANNEL_BLOCK_LEN, separators=(',', ':'))
        tp = Path('_alpine_jssh_numfmt.jssh')
        tp.write_bytes(_xor_by_position(src.encode('utf-8')))
        mod = decode(tp)
        set_band_gain_db(mod, 0, 1, -3.0)
        outp = Path('_alpine_jssh_numfmt_out.jssh')
        encode(mod, outp)
        verify_write(tp, outp, expected_channel_indices=[0], expected_byte_offsets=[2, 3])
        assert b'"v":1.0' in _xor_by_position(outp.read_bytes()), \
            'an untouched 1.0 elsewhere in the file must survive a write verbatim'
        tp.unlink(missing_ok=True); outp.unlink(missing_ok=True)

        # ---- frequency quantization to what Alpine can represent -----------
        assert quantize_band_freq_hz(1997) == 2000, '>=1kHz snaps to 10 Hz steps'
        assert quantize_band_freq_hz(1994) == 1990
        assert quantize_band_freq_hz(432.4) == 432, '<1kHz keeps 1 Hz steps'
        qb = _make_synthetic_preset()
        qres = write_peq_bands(qb, 0, [(1997.0, 1.0, -3.0)], snap=True)
        assert get_band_frequency_hz(qb, 0, 1) == 2000, \
            'write_peq_bands must store an Alpine-representable frequency'
        assert qres['written'][0][0] == 2000, 'reported freq must be what was stored'

        # ---- preflight gate on a well-formed synthetic file ----------------
        pf_path = Path('_alpine_jssh_preflight.jssh')
        encode(_make_synthetic_preset(n_channels=2), pf_path)
        pf = preflight_real_file(pf_path)
        assert pf['decodes'] and pf['byte_identical'], 'clean file must round-trip'
        assert pf['channel_count'] == 2 and pf['block_len_ok']
        assert pf['verdict'] == 'safe_to_write', 'clean file should pass preflight'
        # a float inside the channel byte data IS a real surprise and must block
        bad = '{"data":{"output":{"output":[[1.5%s]]}},"data_info":{}}' % (',0' * (CHANNEL_BLOCK_LEN - 1))
        pf_path.write_bytes(_xor_by_position(bad.encode('utf-8')))
        pf3 = preflight_real_file(pf_path)
        assert pf3['unverified_constructs'][0]['in_channel_data'] is True
        assert pf3['verdict'] == 'do_not_write', \
            'a float inside channel byte data must block the write verdict'
        # a malformed block length must also block (offsets would write blind)
        short = '{"data":{"output":{"output":[[0,1,2]]}},"data_info":{}}'
        pf_path.write_bytes(_xor_by_position(short.encode('utf-8')))
        pf4 = preflight_real_file(pf_path)
        assert pf4['block_len_ok'] is False and pf4['verdict'] == 'do_not_write', \
            'a wrong-length channel block must block the write verdict'
        pf_path.unlink(missing_ok=True)

        print('SELFTEST PASSED (synthetic schema only -- verify against a real .jssh file too: '
              'roundtrip_identical(real_file) should report byte_identical=True)')
    finally:
        tmp.unlink(missing_ok=True)


def _main():
    if len(sys.argv) < 2:
        print('usage: python alpine_jssh.py {preflight <file.jssh> | inspect <file.jssh> '
              '| decode <file.jssh> | encode <file.json> <out.jssh> | selftest}')
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == 'selftest':
        _selftest()
    elif cmd == 'preflight':
        r = preflight_real_file(sys.argv[2])
        print('decodes:          %s' % r['decodes'])
        print('byte-identical:   %s' % r['byte_identical'])
        print('channels:         %s (block length OK: %s)' % (r['channel_count'], r['block_len_ok']))
        print('unverified JSON:  %d construct(s)' % len(r['unverified_constructs']))
        print('VERDICT:          %s' % r['verdict'].upper())
        for reason in r['reasons']:
            print('  - %s' % reason)
        if r['verdict'] != 'safe_to_write':
            sys.exit(2)
    elif cmd == 'inspect':
        obj = decode(sys.argv[2])
        chans = channels(obj)
        print('%d channels in %s' % (len(chans), sys.argv[2]))
        print(format_channels(chans))
        print('\nRoles are INFERRED from crossovers -- confirm/correct them before tuning.')
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
