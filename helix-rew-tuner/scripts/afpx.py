# afpx.py -- generic Helix .afpx read / inspect / channel-detect / write / lint.
# No hardcoded channel map: driver roles are INFERRED from each channel's own
# crossover corners, then confirmed by the user. Works for any Helix DSP channel
# count. Encodings verified on P SIX DSP MK2 -- for other models, run a controlled
# round-trip (write, load in PC-Tool, export, diff) before trusting writes.
#
# CLI:
#   python afpx.py inspect  <file.afpx>            # channel roles + filters + free slots
#   python afpx.py channels <file.afpx> --json     # machine-readable channel map
import argparse
import json
import re
import struct
import sys
import zlib


# ---------------------------------------------------------------- codec
def decode(path):
    raw = open(path, 'rb').read()
    if len(raw) < 5:
        raise ValueError('file too short to be a valid .afpx: %s' % path)
    declared = struct.unpack('>I', raw[:4])[0]
    xml = zlib.decompress(raw[4:]).decode('utf-8', 'replace')
    if declared != len(xml.encode('utf-8')):
        print('warning: header length %d != decoded length %d' % (declared, len(xml.encode('utf-8'))),
              file=sys.stderr)
    return xml


def encode(xml, path):
    payload = xml.encode('utf-8')
    open(path, 'wb').write(struct.pack('>I', len(payload)) + zlib.compress(payload, 9))


# ---------------------------------------------------------------- parsing
def attrs(tag):
    return dict(re.findall(r'([A-Za-z]+)="([^"]*)"', tag))


def channel_blocks(xml):
    return re.findall(r'<OC\b.*?</OC>', xml, re.S)


def filters(block):
    return re.findall(r'<Fil\b[^>]*/?>', block)


# Filter type codes (verified P SIX MK2). See references/afpx_format.md.
TYPE = {'1': 'free', '17': 'PEQ', '15': 'LP', '16': 'HP',
        '3': 'low_shelf', '4': 'high_shelf', '19': 'allpass1', '20': 'allpass2'}


def channel_summary(block):
    """Everything known about one output channel, incl. an INFERRED driver role."""
    fils = [attrs(f) for f in filters(block)]
    active = [a for a in fils if a.get('T') != '1']
    hp = next((a for a in fils if a.get('T') == '16'), None)
    # Lowpass isn't always T=15 -- VERIFIED 2026-07-07: a Butterworth-characteristic
    # lowpass on a real file was encoded as T=9, not T=15 (T=15 has so far only been
    # seen on Linkwitz-characteristic filters). The crossover type code family
    # appears to vary by characteristic (Linkwitz/Butterworth/Bessel/etc.), not
    # just by LP-vs-HP -- treat T=15/T=9 as the LP codes confirmed so far, not
    # necessarily the complete set. If a channel's role won't classify and it has
    # an unrecognized T code with a plausible crossover-like F/G/Q shape, that's
    # worth investigating rather than assuming it's just an unused/PEQ slot.
    lp = next((a for a in fils if a.get('T') in ('15', '9')), None)
    # On crossover filters, `G` encodes the SLOPE (dB/oct), not gain -- VERIFIED
    # 2026-07-07 by controlled diff: F="1000.00" G="0" matched a real screenshot
    # showing that LP's Slope as OFF, while F="6000.00" G="-12" matched "-12 dB/Oct"
    # on the HP of the same channel. G=="0" means the crossover is NOT actually
    # engaged -- its frequency must be ignored for role inference, even though the
    # frequency value is still present in the file.
    #
    # G!=0 is NOT sufficient to call a crossover "engaged", though -- VERIFIED
    # 2026-07-07 by a second controlled diff: toggling a filter section's own
    # "Bypass" button (in its header, separate from the Slope dropdown) flipped
    # FilBy 0->1 on BOTH the HP and LP of the same channel with G, F, and every
    # other value completely unchanged. So FilBy="1" means that filter section
    # is bypassed via its own header button, independent of what slope is
    # stored in G. A filter can hold a real slope value and still be bypassed.
    hp_engaged = hp is not None and float(hp.get('G', 0)) != 0 and hp.get('FilBy') != '1'
    lp_engaged = lp is not None and float(lp.get('G', 0)) != 0 and lp.get('FilBy') != '1'
    hp_f = float(hp['F']) if hp_engaged else None
    lp_f = float(lp['F']) if lp_engaged else None
    role = infer_role(hp_f, lp_f)
    peqs = [(float(a['F']), float(a['Q']), float(a['G']))
            for a in fils if a.get('T') == '17' and float(a.get('G', 0)) != 0]
    # Q on a T=19 (1st-order all-pass) is not real data -- VERIFIED 2026-07-07:
    # PC-Tool shows "Q: N/A for 1st order" even when the file stores a nonzero
    # Q (likely left over from when the band was a 2nd-order all-pass). Report
    # None rather than a number that looks meaningful but isn't.
    apfs = [(TYPE[a['T']], float(a['F']), None if a['T'] == '19' else float(a.get('Q', 0)))
            for a in fils if a.get('T') in ('19', '20')]
    shelves = [(TYPE[a['T']], float(a['F']), float(a['Q']), float(a['G']))
               for a in fils if a.get('T') in ('3', '4') and float(a.get('G', 0)) != 0]
    free_mid = sum(1 for a in fils if a.get('T') == '1' and a.get('dF') not in ('25', '32', '20000'))
    oc = attrs(re.match(r'<OC\b[^>]*>', block).group(0))
    # Polarity: CINV on the <OC> tag -- VERIFIED 2026-07-07 by controlled diff
    # (flipping polarity in PC-Tool flipped CINV 1->0 and changed nothing else
    # meaningful; the delay tag's PM/P attributes did NOT move). Trust CINV, not
    # PM -- see afpx_format.md for the full account of why PM was a false lead.
    polarity = None
    if 'CINV' in oc:
        polarity = 'inverted' if oc.get('CINV') == '1' else 'normal'
    return {
        'hp_hz': hp_f, 'lp_hz': lp_f, 'inferred_role': role,
        'active_filter_count': len(active),
        'peqs': peqs, 'all_passes': apfs, 'shelves': shelves,
        'free_middle_slots': free_mid,
        'low_shelf_slot_free': any(a.get('T') == '1' and a.get('dF') == '25' for a in fils),
        'high_shelf_slot_free': any(a.get('T') == '1' and a.get('dF') == '20000' for a in fils),
        'polarity': polarity, 'cinv_raw': oc.get('CINV'),
        'delay_samples': oc.get('__delay__'),  # filled in by channels()
    }


def infer_role(hp_hz, lp_hz):
    """Classify a driver from its crossover band. Heuristic -- the user confirms.
    Order matters: check the specific bands before the catch-all 'wide'."""
    if lp_hz is not None and lp_hz <= 120:
        return 'sub'
    if hp_hz is not None and hp_hz >= 1500:
        return 'tweeter'
    if hp_hz is not None and hp_hz <= 250 and lp_hz is not None and lp_hz <= 4000:
        return 'midbass/mid'
    if hp_hz is not None and 250 < hp_hz < 1500:
        return 'midrange'
    if (hp_hz is None or hp_hz <= 60) and (lp_hz is None or lp_hz >= 6000):
        return 'wide/full-range?'
    return 'unknown (confirm manually)'


def delay_tags(xml):
    return re.findall(r'<T [^>]*/?>', xml)


def channels(xml):
    """List every channel with inferred role, filters, delay, free slots.
    Also guesses L/R pairing from adjacent same-role channels."""
    blocks = channel_blocks(xml)
    delays = [attrs(t) for t in delay_tags(xml)]
    out = []
    for i, b in enumerate(blocks):
        s = channel_summary(b)
        if i < len(delays):
            s['delay_samples'] = delays[i].get('T')
            # Polarity comes from CINV on <OC> (set in channel_summary) -- VERIFIED
            # 2026-07-07, see afpx_format.md. The delay tag's PM/P attributes are
            # kept here only as raw context; they do NOT reliably encode polarity
            # (confirmed: PM/P stayed identical across a real polarity flip).
            s['polarity_delay_tag_raw'] = {'PM': delays[i].get('PM'), 'P': delays[i].get('P')}
        s['index'] = i
        out.append(s)
    # pair guess: consecutive equal-role channels are likely L/R
    for i in range(0, len(out) - 1, 2):
        if out[i]['inferred_role'] == out[i + 1]['inferred_role']:
            out[i]['pair_guess'] = out[i + 1]['pair_guess'] = (i, i + 1)
    return out


# ---------------------------------------------------------------- lint
def semantic_delay_key(xml):
    """Order-independent -- PC-Tool reorders attributes inside <T> tags on save."""
    return [tuple(sorted(attrs(t).items())) for t in delay_tags(xml)]


def semantic_xover_key(xml):
    keep = ('T', 'F', 'Q', 'G', 'dF')
    return sorted(tuple((k, attrs(f).get(k)) for k in keep)
                  for f in filters(xml) if attrs(f).get('T') in ('15', '16'))


# ---------------------------------------------------------------- delay write
# WRITE_DELAY_SAMPLES is a real, verified capability -- but this does NOT
# change the project's standing rule (helix_hardware.md, SKILL.md): delay
# writes are USER-INITIATED and EXPLICITLY CONFIRMED only, never applied
# automatically from an analysis result. This function makes the write
# possible and safe (touches only the one intended T= value; verify_
# delay_write proves nothing else moved); it does not authorize when to call
# it. Only writes the T= (samples) attribute -- never PM/P, which are NOT
# confirmed to mean polarity (see afpx_format.md) and are left untouched.
def write_delay_samples(xml, channel_index, samples):
    """Write ONLY the T= (delay, in samples) attribute on the delay tag for
    channel_index -- every other attribute on that tag (PM, P, ...) stays
    byte-identical, and every other channel's delay tag is untouched.
    channel_index is position-matched to channel_blocks()/channels() order,
    the same convention already used for reading. samples must be a
    non-negative integer (the DSP's actual internal rate determines what
    physical delay that represents -- convert with tunelib.ms_to_samples
    using the CONFIRMED rate for this unit, never assume 96 kHz)."""
    samples = int(round(samples))
    if samples < 0:
        raise ValueError('delay samples must be non-negative: %d' % samples)
    matches = list(re.finditer(r'<T [^>]*/?>', xml))
    if channel_index < 0 or channel_index >= len(matches):
        raise ValueError('channel_index %d out of range (%d delay tags found)'
                         % (channel_index, len(matches)))
    m = matches[channel_index]
    old_tag = m.group(0)
    if not re.search(r'(?<![A-Za-z])T="[^"]*"', old_tag):
        raise ValueError('could not find a T= attribute in tag: %s' % old_tag)
    new_tag = re.sub(r'(?<![A-Za-z])T="[^"]*"', 'T="%d"' % samples, old_tag, count=1)
    return xml[:m.start()] + new_tag + xml[m.end():]


def verify_delay_write(old_xml, new_xml, channel_index, expected_samples):
    """Strong, SPECIFIC verification for a delay write -- deliberately stronger
    than roundtrip_lint(allow_delay=True), which only checks THAT delay tags
    changed, not WHAT changed or whether anything else moved too. Confirms:
      - channel_index's new T is exactly expected_samples;
      - channel_index's other delay-tag attributes (PM, P, ...) are BYTE-
        IDENTICAL to before -- only T should have moved;
      - every OTHER channel's delay tag is completely unchanged;
      - every <OC> block's content (filters, CINV/polarity, etc.) is
        completely unchanged -- confirms the write really touched nothing
        else in the whole file.
    Returns {'pass': bool, 'errors': [...]}."""
    old_delays = [attrs(t) for t in delay_tags(old_xml)]
    new_delays = [attrs(t) for t in delay_tags(new_xml)]
    errors = []
    if len(old_delays) != len(new_delays):
        return {'pass': False,
                'errors': ['delay tag count changed (%d -> %d)' % (len(old_delays), len(new_delays))]}
    expected_str = str(int(round(expected_samples)))
    for i, (o, n) in enumerate(zip(old_delays, new_delays)):
        if i == channel_index:
            if n.get('T') != expected_str:
                errors.append('ch%d: T is %r, expected %r' % (i, n.get('T'), expected_str))
            other_old = {k: v for k, v in o.items() if k != 'T'}
            other_new = {k: v for k, v in n.items() if k != 'T'}
            if other_old != other_new:
                errors.append('ch%d: attributes other than T changed (old=%r new=%r)'
                              % (i, other_old, other_new))
        elif o != n:
            errors.append('ch%d: delay tag changed unexpectedly (old=%r new=%r)' % (i, o, n))
    old_blocks, new_blocks = channel_blocks(old_xml), channel_blocks(new_xml)
    if len(old_blocks) != len(new_blocks):
        errors.append('channel count changed unexpectedly')
    else:
        for i, (ob, nb) in enumerate(zip(old_blocks, new_blocks)):
            if ob != nb:
                errors.append('ch%d: <OC> block content changed unexpectedly '
                              '(only the delay tag should differ)' % i)
    return {'pass': not errors, 'errors': errors}


# ---------------------------------------------------------------- output trim
# tunelib.headroom_report already COMPUTES recommended_trim_db when a boost
# stack risks clipping -- but until now there was no way to APPLY it, so the
# recommendation just sat in a report and the user had to find the output
# level control in PC-Tool by hand. This closes that loop.
#
# The output level lives in a <Vol L="..."/> tag inside each <OC> block, where
# L is LINEAR amplitude (dB = 20*log10(L)) -- VERIFIED 2026-07-14 by reading
# real files: a mid channel at L="0.7286181745132278" = -2.75 dB matched its
# PC-Tool output trim, and that trim was exactly what offset a +2.7 dB PEQ
# cascade peak (which is why headroom_report's clip_risk on that channel was
# a false alarm -- it only sees the PEQ stage, not the output trim).
#
# GOTCHA THAT WOULD SILENTLY CORRUPT A WRITE: there are FEWER <Vol> tags than
# channels -- unused/empty output channels have no <Vol> tag at all (a real
# 10-channel file had Vol in ch0-ch7 only). So the Nth <Vol> tag in the file
# is NOT channel N. These functions map each Vol tag to its containing <OC>
# block and index by CHANNEL, matching channels()/channel_blocks() order like
# every other function here. Never index Vol tags positionally.
#
# SAFETY BY CONSTRUCTION, not just by convention: trim_db must be <= 0 and
# >= min_trim_db (default -6). This can only ever ATTENUATE. Unlike the delay
# write (which is gated by user confirmation but could be given a bad number),
# a trim write is structurally incapable of raising output level or pushing a
# channel further into clipping. It still follows the same standing rule --
# user-initiated, explicitly confirmed for that specific change, verified
# after -- because it IS an audible level change to their tune.
def _vol_spans(xml):
    """[(channel_index, match)] for every <Vol> tag, mapped to the <OC> block
    it lives inside. Channels with no <Vol> tag are simply absent."""
    out = []
    for i, m in enumerate(re.finditer(r'<OC\b.*?</OC>', xml, re.S)):
        block, base = m.group(0), m.start()
        v = re.search(r'<Vol\b[^>]*/?>', block)
        if v:
            out.append((i, base + v.start(), base + v.end(), v.group(0)))
    return out


def read_output_levels(xml):
    """{channel_index: {'L': float, 'db': float, 'tag': str}} for channels that
    have a <Vol> tag. dB = 20*log10(L); L=1.0 is unity (0 dB)."""
    import math
    out = {}
    for ci, s, e, tag in _vol_spans(xml):
        a = attrs(tag)
        if 'L' not in a:
            continue
        L = float(a['L'])
        out[ci] = {'L': L, 'db': (20.0 * math.log10(L) if L > 0 else float('-inf')),
                   'tag': tag}
    return out


def write_output_trim(xml, trims_db, min_trim_db=-6.0):
    """Apply protective output attenuation. trims_db: {channel_index: dB},
    every value <= 0 (attenuation only) and >= min_trim_db. The trim is
    RELATIVE to the channel's existing level -- new_L = old_L * 10**(dB/20) --
    so it composes with whatever trim the user already had rather than
    replacing it. Only the L= attribute moves; T=/i= and every other tag in
    the file stay byte-identical. Returns the new XML.

    Use tunelib.headroom_report(...)['recommended_trim_db'] to source the
    number, but read the channel's CURRENT level first (read_output_levels)
    and tell the user both the current and resulting dB -- an existing trim
    may already cover the risk (see the false-alarm note above)."""
    if not trims_db:
        raise ValueError('trims_db is empty -- nothing to write')
    spans = {ci: (s, e, tag) for ci, s, e, tag in _vol_spans(xml)}
    for ci, db in sorted(trims_db.items()):
        if db > 0:
            raise ValueError('ch%d: trim must be <= 0 dB (attenuation only), got %+.2f'
                             % (ci, db))
        if db < min_trim_db:
            raise ValueError('ch%d: trim %+.2f dB exceeds the %+.1f dB safety floor'
                             % (ci, db, min_trim_db))
        if ci not in spans:
            raise ValueError('ch%d has no <Vol> tag (unused channel?) -- channels '
                             'with a Vol tag: %s' % (ci, sorted(spans)))
    # apply right-to-left so earlier offsets stay valid
    new_xml = xml
    for ci in sorted(trims_db, key=lambda c: spans[c][0], reverse=True):
        s, e, tag = spans[ci]
        a = attrs(tag)
        if 'L' not in a:
            raise ValueError('ch%d: <Vol> tag has no L= attribute: %s' % (ci, tag))
        new_L = float(a['L']) * (10.0 ** (trims_db[ci] / 20.0))
        new_tag = re.sub(r'(?<![A-Za-z])L="[^"]*"', 'L="%r"' % new_L, tag, count=1)
        new_xml = new_xml[:s] + new_tag + new_xml[e:]
    return new_xml


def verify_output_trim_write(old_xml, new_xml, trims_db, tol_db=0.01):
    """Strong verification for a trim write. Confirms:
      - each trimmed channel's new level is old + trim_db (within tol_db);
      - the change is ATTENUATION (new level strictly <= old, per channel);
      - every other channel's <Vol> tag is BYTE-IDENTICAL;
      - the trimmed tags' other attributes (T=, i=) are unchanged;
      - delays are semantically equal and every <OC> block differs ONLY by
        its <Vol> tag (so no filter/polarity/crossover moved).
    Returns {'pass': bool, 'errors': [...]}."""
    errors = []
    old_lv, new_lv = read_output_levels(old_xml), read_output_levels(new_xml)
    if sorted(old_lv) != sorted(new_lv):
        return {'pass': False, 'errors': ['set of channels with a <Vol> tag changed '
                                          '(%s -> %s)' % (sorted(old_lv), sorted(new_lv))]}
    for ci in sorted(old_lv):
        o, n = old_lv[ci], new_lv[ci]
        if ci in trims_db:
            want = o['db'] + trims_db[ci]
            if abs(n['db'] - want) > tol_db:
                errors.append('ch%d: level is %+.3f dB, expected %+.3f dB'
                              % (ci, n['db'], want))
            if n['L'] > o['L'] + 1e-12:
                errors.append('ch%d: level INCREASED (%.4f -> %.4f) -- trim must only '
                              'attenuate' % (ci, o['L'], n['L']))
            oa = {k: v for k, v in attrs(o['tag']).items() if k != 'L'}
            na = {k: v for k, v in attrs(n['tag']).items() if k != 'L'}
            if oa != na:
                errors.append('ch%d: <Vol> attributes other than L changed (%r -> %r)'
                              % (ci, oa, na))
        elif o['tag'] != n['tag']:
            errors.append('ch%d: untrimmed channel\'s <Vol> tag changed (%s -> %s)'
                          % (ci, o['tag'], n['tag']))
    if semantic_delay_key(old_xml) != semantic_delay_key(new_xml):
        errors.append('delays changed -- a trim write must not touch timing')
    ob, nb = channel_blocks(old_xml), channel_blocks(new_xml)
    if len(ob) != len(nb):
        errors.append('channel count changed')
    else:
        strip = lambda b: re.sub(r'<Vol\b[^>]*/?>', '<Vol/>', b)
        for i, (a, b) in enumerate(zip(ob, nb)):
            if strip(a) != strip(b):
                errors.append('ch%d: <OC> content other than <Vol> changed' % i)
    return {'pass': not errors, 'errors': errors}


def roundtrip_lint(old_xml, new_xml, expect_changed=None,
                   allow_delay=False, allow_xover=False):
    """Verify a write: delays + crossovers preserved (semantically), header
    valid on re-encode, and only the intended slots changed. Returns a dict."""
    errors = []
    if not allow_delay and semantic_delay_key(old_xml) != semantic_delay_key(new_xml):
        errors.append('delay tags changed')
    if not allow_xover and semantic_xover_key(old_xml) != semantic_xover_key(new_xml):
        errors.append('crossover filters changed')
    # count changed PEQ/shelf/APF slots (FN-insensitive)
    def sig(xml):
        out = []
        for b in channel_blocks(xml):
            out.append([tuple((k, attrs(f).get(k)) for k in ('T', 'F', 'Q', 'G', 'dF', 'I'))
                        for f in filters(b)])
        return out
    so, sn = sig(old_xml), sig(new_xml)
    changed = sum(1 for co, cn in zip(so, sn) for a, b in zip(co, cn) if a != b)
    if expect_changed is not None and changed != expect_changed:
        errors.append('changed %d slots, expected %d' % (changed, expect_changed))
    return {'pass': not errors, 'errors': errors, 'slots_changed': changed}


# ---------------------------------------------------------------- CLI
def _fmt_ch(c):
    xo = '%s-%s Hz' % (('%.0f' % c['hp_hz']) if c['hp_hz'] else 'DC',
                       ('%.0f' % c['lp_hz']) if c['lp_hz'] else 'open')
    line = ('ch%d  %-16s  band %-14s  %d active' %
            (c['index'], c['inferred_role'], xo, c['active_filter_count']))
    extra = []
    if c.get('all_passes'):
        extra.append('APF ' + ','.join('%s@%.0f' % (t, f) for t, f, q in c['all_passes']))
    if c.get('shelves'):
        extra.append('shelf ' + ','.join('%s@%.0f' % (t, f) for t, f, q, g in c['shelves']))
    extra.append('%d free mid slots' % c['free_middle_slots'])
    return line + '   [' + ' | '.join(extra) + ']'


def _selftest():
    """Synthetic-XML self-test for write_delay_samples/verify_delay_write --
    the write path with real hardware-timing consequences, so it gets a real
    test, not just manual scratch verification. No real .afpx sample files
    needed or used."""
    xml = ('<ATF><OC ON="0" CINV="0"><Fil T="1"/></OC>'
           '<OC ON="1" CINV="1"><Fil T="17" F="100" G="-2" Q="1"/></OC></ATF>'
           '<T PM="1" P="0" T="0"/><T PM="2" P="0" T="91"/>')

    new_xml = write_delay_samples(xml, 1, 216)
    v = verify_delay_write(xml, new_xml, 1, 216)
    assert v['pass'], 'positive case should pass: %r' % v['errors']
    assert delay_tags(new_xml)[0] == delay_tags(xml)[0], 'untouched channel must be byte-identical'
    print('afpx selftest: positive write+verify OK')

    same_xml = write_delay_samples(xml, 0, 0)
    v2 = verify_delay_write(xml, same_xml, 0, 0)
    assert v2['pass'], 'same-value write should still pass: %r' % v2['errors']
    print('afpx selftest: same-value edge case OK')

    corrupted = new_xml.replace('CINV="0"', 'CINV="1"')
    v3 = verify_delay_write(xml, corrupted, 1, 216)
    assert not v3['pass'], 'must catch an unrelated OC change'
    print('afpx selftest: unrelated-corruption detection OK')

    tampered = new_xml.replace('PM="2"', 'PM="9"')
    v4 = verify_delay_write(xml, tampered, 1, 216)
    assert not v4['pass'], 'must catch PM/P being disturbed on the written tag'
    print('afpx selftest: PM/P-disturbed detection OK')

    try:
        write_delay_samples(xml, 99, 100)
        raise AssertionError('out-of-range channel_index should have raised')
    except ValueError:
        pass
    print('afpx selftest: out-of-range channel_index correctly raises')

    # ---- output trim -------------------------------------------------------
    # NOTE ch1 deliberately has NO <Vol> tag, and ch2 does -- this reproduces
    # the real-file gotcha (fewer Vol tags than channels, so the Nth Vol tag
    # is NOT channel N). If the mapping were positional, the ch2 write below
    # would silently land on ch1's tag and the byte-identical check would fail.
    vxml = ('<ATF>'
            '<OC ON="0" CINV="0"><Vol T="15" L="0.5" i="0"/><Fil T="1"/></OC>'
            '<OC ON="1" CINV="0"><Fil T="17" F="100" G="-2" Q="1"/></OC>'
            '<OC ON="2" CINV="0"><Vol T="15" L="1.0" i="0"/><Fil T="1"/></OC>'
            '</ATF><T PM="1" P="0" T="0"/><T PM="1" P="0" T="5"/><T PM="1" P="0" T="9"/>')

    lv = read_output_levels(vxml)
    assert sorted(lv) == [0, 2], 'Vol tags must map to channels 0 and 2, got %s' % sorted(lv)
    assert abs(lv[0]['db'] - (-6.0206)) < 0.01 and abs(lv[2]['db'] - 0.0) < 1e-9
    print('afpx selftest: read_output_levels maps Vol->channel (skips ch1, no Vol) OK')

    t = write_output_trim(vxml, {2: -3.0})
    v = verify_output_trim_write(vxml, t, {2: -3.0})
    assert v['pass'], 'positive trim case should pass: %r' % v['errors']
    assert abs(read_output_levels(t)[2]['db'] - (-3.0)) < 0.01
    assert read_output_levels(t)[0]['tag'] == lv[0]['tag'], 'ch0 Vol must be byte-identical'
    print('afpx selftest: trim write on the correct channel + verify OK')

    # relative composition: trimming an already-trimmed channel stacks
    t2 = write_output_trim(vxml, {0: -2.0})
    assert abs(read_output_levels(t2)[0]['db'] - (-8.0206)) < 0.01, 'trim must be relative'
    assert verify_output_trim_write(vxml, t2, {0: -2.0})['pass']
    print('afpx selftest: trim is relative to existing level OK')

    for bad, why in [({2: +1.0}, 'positive gain'), ({2: -99.0}, 'below safety floor'),
                     ({1: -3.0}, 'channel with no Vol tag'), ({}, 'empty dict')]:
        try:
            write_output_trim(vxml, bad)
            raise AssertionError('%s should have raised' % why)
        except ValueError:
            pass
    print('afpx selftest: rejects boost / over-floor / no-Vol-channel / empty OK')

    # a boost smuggled past the writer must still be caught by verification.
    # Derive the written L from the file rather than hardcoding it -- a stale
    # literal here would silently make this a no-op test that always passes.
    trimmed = write_output_trim(vxml, {2: -3.0})
    written_L = attrs(read_output_levels(trimmed)[2]['tag'])['L']
    sneaky = trimmed.replace('L="%s"' % written_L, 'L="2.0"')
    assert sneaky != trimmed, 'sneaky-edit fixture failed to apply'
    assert not verify_output_trim_write(vxml, sneaky, {2: -3.0})['pass'], \
        'verification must catch a level INCREASE'
    # and an unrelated filter change must be caught too
    tampered = write_output_trim(vxml, {2: -3.0}).replace('G="-2"', 'G="-5"')
    assert not verify_output_trim_write(vxml, tampered, {2: -3.0})['pass'], \
        'verification must catch an unrelated filter change'
    print('afpx selftest: verification catches level increase + unrelated edits OK')

    print('\nALL AFPX SELFTESTS PASSED')


def main():
    ap = argparse.ArgumentParser(description='Inspect / analyze a Helix .afpx file.')
    ap.add_argument('cmd', choices=['inspect', 'channels', 'selftest'])
    ap.add_argument('file', nargs='?')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'selftest':
        _selftest()
        return
    xml = decode(a.file)
    chans = channels(xml)
    if a.json:
        print(json.dumps(chans, indent=2))
        return
    print('%d output channels. Inferred driver roles (CONFIRM these with the user):\n' % len(chans))
    for c in chans:
        print(_fmt_ch(c))
    print('\nDelays present:', len(delay_tags(xml)),
          '| Reminder: roles are inferred from crossover corners -- verify against the actual install.')


if __name__ == '__main__':
    main()
