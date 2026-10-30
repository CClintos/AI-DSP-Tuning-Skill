# scoresheet.py -- an EMMA sound-quality listening sheet, read against the
# measurements.
#
# The sheet is the 280-point EMMA SQ scoresheet (imaging 25 on tracks 2-6,
# sound stage 45 on track 12, tonal accuracy 4 x 30 on tracks 13-16, overall
# spectral balance 2 x 30 on track 16, listening pleasure 30, and up to -6 each
# for system noise and visibility). assets/emma_listening_sheet.html fills it in
# on a phone and exports the JSON read here; a judge's paper sheet can be
# copied into the same page.
#
# `finish --heard` puts each lost point next to what the captures given to
# finish measured in that region and the command that acts on it. A listening
# sheet is evidence about the sound, not about its cause: an item the
# measurements do not explain is reported as not explained, never forced onto
# a filter. Comments and event names are the listener's words: quoted, never
# acted on.
import json
import math
import os

import tunelib

FORMAT = 'emma-listening-sheet'
POSITIONS = ('left', 'left-centre', 'centre', 'right-centre', 'right')
INSTRUMENTS = ('bass', 'guitar', 'banjo', 'vibraphone', 'triangle')
# the sheet's short names for the 2026 judge book's instruments (finish/imaging bands)
BAND_NAME = dict(zip(INSTRUMENTS, tunelib.EMMA_IMAGING_INSTRUMENTS))
ITEMS = (('stage', 'distance', 15), ('stage', 'width', 15), ('stage', 'height', 15),
         ('tonal', 'sub_bass', 30), ('tonal', 'mid_bass', 30), ('tonal', 'midrange', 30),
         ('tonal', 'high', 30), ('balance', 'normal', 30), ('balance', 'louder', 30),
         ('pleasure', None, 30))
DEDUCTIONS = ('system_noise', 'visibility')
TOTAL_MAX = 280
HEARD = {
    'distance': ('too close', 'too far', 'vague'),
    'width': ('narrow', 'too wide', 'holes'),
    'height': ('low', 'high', 'varies with pitch', 'unstable'),
    'tonal': ('too much', 'too little', 'boomy', 'uneven', 'muddy', 'thin', 'harsh', 'bright',
              'dull', 'sibilant', 'distorted', 'rattle'),
    'normal': ('bass heavy', 'bass light', 'mids forward', 'mids recessed', 'bright', 'dull'),
    'louder': ('harsh', 'compressed', 'distorted', 'boomy', 'rattle', 'bass heavy', 'bass light',
               'bright', 'dull'),
    'pleasure': ('naturalness', 'harmony & musicality', 'atmosphere & emotion', 'clarity',
                 'effortless sound', 'dynamics & energy', 'distinction & separation',
                 'body of voice & air', 'transparency', 'details'),
}
LABEL = {'distance': 'sound stage: distance', 'width': 'sound stage: width',
         'height': 'sound stage: height', 'sub_bass': 'tonal accuracy: sub-bass',
         'mid_bass': 'tonal accuracy: mid-bass', 'midrange': 'tonal accuracy: midrange',
         'high': 'tonal accuracy: high frequency', 'normal': 'spectral balance: normal volume',
         'louder': 'spectral balance: about 6 dB louder', 'pleasure': 'listening pleasure'}
MORE = {'too much', 'boomy', 'muddy', 'harsh', 'bright', 'sibilant'}
LESS = {'too little', 'thin', 'dull'}
QUOTE_MAX = 300


def _quote(text):
    text = ' '.join(str(text).split())
    return text if len(text) <= QUOTE_MAX else text[:QUOTE_MAX - 3] + '...'


def _points(value, lo, hi, where):
    if value is None or value == '':
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('%s: points must be a number (got %r)' % (where, value))
    if not lo <= value <= hi:
        raise ValueError('%s: %g is outside %g..%g' % (where, value, lo, hi))
    return float(value)


def _words(values, known, where, notes):
    out = []
    for w in values or []:
        w = str(w).strip().lower()
        if not w:
            continue
        if w not in known:
            notes.append('%s: "%s" is not one of the sheet\'s words; kept as a comment'
                         % (where, _quote(w)))
        out.append(w)
    return out


def load(path):
    """Read and check a listening sheet; returns (sheet, notes)."""
    if os.path.getsize(path) > 1_000_000:
        raise ValueError('%s is too large to be a listening sheet' % path)
    with open(path, encoding='utf-8-sig') as fh:
        try:
            raw = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError('%s is not JSON: %s' % (path, exc))
    return parse(raw)


def is_sheet(path):
    try:
        if os.path.getsize(path) > 1_000_000:
            return False
        with open(path, encoding='utf-8-sig') as fh:
            raw = json.load(fh)
        return isinstance(raw, dict) and raw.get('format') == FORMAT
    except (OSError, ValueError):
        return False


def parse(raw):
    if not isinstance(raw, dict) or raw.get('format') != FORMAT:
        raise ValueError('not a listening sheet: expected "format": "%s" (export it from '
                         'assets/emma_listening_sheet.html)' % FORMAT)
    if raw.get('version') != 1:
        raise ValueError('listening sheet version %r is not supported (1 is)' % raw.get('version'))
    notes = []
    sheet = {'source': raw.get('source') if raw.get('source') in ('judge', 'self') else None,
             'quoted': {k: _quote(raw[k]) for k in ('event', 'date', 'listener', 'notes')
                        if raw.get(k)},
             'imaging': {}, 'items': {}, 'deductions': {}}
    img = raw.get('imaging') or {}
    cells = img.get('cells') or {}
    entered = img.get('points') or {}
    for pos in POSITIONS:
        row = cells.get(pos) or {}
        heard = {}
        for ins in INSTRUMENTS:
            v = row.get(ins)
            if v in (None, '', '?'):
                continue
            v = str(v).strip().lower()
            if v not in POSITIONS + ('two places',):
                raise ValueError('imaging %s/%s: "%s" is not a position' % (pos, ins, _quote(v)))
            heard[ins] = v
        given = _points(entered.get(pos), 0, 5, 'imaging %s' % pos)
        counted = (sum(1 for v in heard.values() if v == pos) if len(heard) == len(INSTRUMENTS)
                   else None)
        if given is not None and counted is not None and given != counted:
            notes.append('imaging %s: the entered %g points differ from the %d instruments marked in '
                         'place; the entered points are used' % (pos, given, counted))
        sheet['imaging'][pos] = {'heard': heard, 'points': given if given is not None else counted}
    for group, key, mx in ITEMS:
        node = raw.get(group) or {}
        node = node if key is None else (node.get(key) or {})
        if not isinstance(node, dict):
            raise ValueError('%s: expected an object' % (key or group))
        name = key or group
        known = HEARD['tonal'] if group == 'tonal' else HEARD.get(name, ())
        words = _words(node.get('lacking') if name == 'pleasure' else node.get('heard'), known,
                       LABEL[name], notes)
        sheet['items'][name] = {'points': _points(node.get('points'), 0, mx, LABEL[name]), 'max': mx,
                                'heard': words,
                                'comment': _quote(node['comment']) if node.get('comment') else None}
    for key in DEDUCTIONS:
        sheet['deductions'][key] = _points((raw.get('deductions') or {}).get(key), -6, 0, key) or 0.0
    total = score(sheet)
    if raw.get('total') not in (None, '') and total['points'] is not None \
            and abs(float(raw['total']) - total['points']) > 0.01:
        notes.append('the sheet says %s points; its items add up to %g'
                     % (_quote(raw['total']), total['points']))
    return sheet, notes


def score(sheet):
    """Points over the items that were scored, deductions included."""
    pts, scored_max, missing = 0.0, 0.0, []
    for pos, row in sheet['imaging'].items():
        if row['points'] is None:
            missing.append('imaging %s' % pos)
        else:
            pts, scored_max = pts + row['points'], scored_max + 5
    for name, item in sheet['items'].items():
        if item['points'] is None:
            missing.append(LABEL[name])
        else:
            pts, scored_max = pts + item['points'], scored_max + item['max']
    pts += sum(sheet['deductions'].values())
    return {'points': round(pts, 1) if scored_max else None, 'max': TOTAL_MAX,
            'scored_max': scored_max, 'not_scored': missing}


# ------------------------------------------------------------------ explain
def _band(report, name):
    for b in ((report.get('tone') or {}).get('emma_bands') or {}).get('bands', []):
        if b['band'] == name and b['median_db'] is not None:
            return b
    return None


def _peaks(report, lo, hi):
    return [p for p in (report.get('tone') or {}).get('residual_peaks', []) if lo <= p['hz'] <= hi]


def _decay(report, lo, hi):
    out = []
    for spec, d in (report.get('bass_decay') or {}).items():
        out += ['%s rings %.2f s at %d Hz (audible above %.2f s)'
                % (os.path.basename(spec), b['t60_s'], b['hz'], b['threshold_s'])
                for b in d['bands'] if b['verdict'] == 'audible' and lo <= b['hz'] <= hi]
    return out


def _tonal(name, item, report):
    lo, hi = next((b[1], b[2]) for b in tunelib.EMMA_BANDS if b[0] == name)
    heard = set(item['heard'])
    band, peaks = _band(report, name), _peaks(report, lo, hi)
    measured, nxt = [], []
    if band:
        measured.append('the band sits %+.1f dB against the target; peaks and holes inside it %.1f dB '
                        'RMS' % (band['median_db'], band['roughness_db']))
    measured += ['residual peak %+.1f dB at %d Hz (Q about %s)' % (p['height_db'], p['hz'], p['q'])
                 for p in peaks]
    rings = _decay(report, lo, hi)
    measured += rings
    sub = report.get('sub') or {}
    if name in ('sub_bass', 'mid_bass') and (sub.get('harmonics') or {}).get('worst'):
        measured.append('sub: ' + sub['harmonics']['worst'])
    if not report.get('tone'):
        return measured, 'no system capture given: nothing to check this against', \
            ['finish --system <full-system capture>  (capture-plan --goal tone)'], 'no_capture'
    med = band['median_db'] if band else 0.0
    if heard & MORE and med > 1.0:
        likely = 'the band measures %+.1f dB hot: a level decision before any filter' % med
        nxt.append('analyze --target <yours>: bass_balance and emma_bands' if name in ('sub_bass', 'mid_bass')
                   else 'refine / propose over %d-%d Hz' % (lo, hi))
        conf = 'measured'
    elif heard & MORE and peaks:
        p = peaks[0]
        likely = 'a residual peak at %d Hz rather than the band level' % p['hz']
        nxt.append('refine / propose --fit-band %d %d' % tuple(p['fit_band_hz']))
        conf = 'measured'
    elif 'boomy' in heard and rings:
        likely = 'bass ringing above the audibility threshold'
        nxt.append('a cut on the ringing peak (check the boost gate first), then finish --ir again')
        conf = 'measured'
    elif heard & LESS and med < -1.0:
        likely = ('the band measures %.1f dB low: check it is not a cancellation before any boost or '
                  'level change' % -med)
        nxt.append('coherence / --cancel-check, and mmm-align or junction at the sub/midbass junction'
                   if name in ('sub_bass', 'mid_bass') else
                   'coherence on the L/R triple, then refine / propose')
        conf = 'measured'
    elif heard & {'distorted', 'rattle'}:
        likely = 'a level-dependent problem a tonal capture cannot show'
        nxt.append('quality-check (compression, distortion) and a slow sine sweep by ear for rattles')
        conf = 'not_explained'
    elif 'uneven' in heard and (peaks or (band and band['roughness_db'] > 1.5)):
        likely = 'peaks and holes inside the band'
        nxt.append('refine / propose over %d-%d Hz; leave narrow dips alone' % (lo, hi))
        conf = 'measured'
    elif band and abs(med) > 1.5:
        likely = 'the band measures %+.1f dB against the target' % med
        nxt.append('voice the target or set the level, then A/B it blind (voice-variants, ab-make)')
        conf = 'consistent'
    elif peaks:
        likely = 'the largest residual peak in the band (%d Hz)' % peaks[0]['hz']
        nxt.append('refine / propose --fit-band %d %d' % tuple(peaks[0]['fit_band_hz']))
        conf = 'consistent'
    else:
        likely = ('not explained by these captures: the band is on target. Tonal accuracy also hears '
                  'attack, decay and distortion, which an MMM capture does not show; a voicing '
                  'difference from the judge is possible too')
        nxt.append('voice-variants + ab-make + prefs for taste; sweeps with finish --ir for decay')
        conf = 'not_explained'
    return measured, likely, nxt, conf


def _stage(name, item, report):
    heard = set(item['heard'])
    measured, nxt = [], []
    over = [o for o in (report.get('height') or {}).get('overlaps', [])
            if o['verdict'] in ('height_risk', 'question')]
    measured += ['pairs %s and %s share %d-%d Hz (%s)' % (o['pairs'][0], o['pairs'][1],
                                                          o['overlap_hz'][0], o['overlap_hz'][1],
                                                          o['verdict']) for o in over]
    mid, high = _band(report, 'midrange'), _band(report, 'high')
    imaging = (report.get('imaging') or {}).get('bands', [])
    loose = [b['instrument'] for b in imaging if b.get('focus') in ('loose', 'smeared')]
    if name == 'height':
        if over:
            likely = ('drivers at different heights share the same band: delay cannot fix height, '
                      'the crossover can (the high driver should own everything from a few hundred '
                      'hertz up)')
            nxt += ['probe a lower low-pass on the low pair, set it by hand in PC-Tool',
                    'voice-variants --height-db 1 2 --height-channels <tweeters> for a blind A/B']
            conf = 'measured' if any(o['verdict'] == 'height_risk' for o in over) else 'consistent'
        elif report.get('height') is None:
            likely = 'no tune given: the height check needs the crossovers'
            nxt.append('finish --afpx <tune> --low <door channels> --high <dash/pillar channels>')
            conf = 'no_capture'
        else:
            likely = 'no overlapping passbands found: try the height voicing variant blind'
            nxt.append('voice-variants --height-db 1 2 --height-channels <tweeters>')
            conf = 'not_explained'
    elif name == 'distance':
        measured += ['%s %+.1f dB against the target' % (b['band'], b['median_db'])
                     for b in (mid, high) if b]
        presence = _peaks(report, 1500.0, 6000.0)
        measured += ['residual peak %+.1f dB at %d Hz' % (p['height_db'], p['hz']) for p in presence]
        if 'too close' in heard or not heard:
            likely = ('an upper-midrange peak or door drivers playing high bring the stage close; the '
                      '"presence dip" that pushes it back is a taste variant, not a correction')
            nxt += ['refine / propose --fit-band %d %d' % tuple(presence[0]['fit_band_hz'])] if presence else []
            nxt.append('voice-variants --distance-db -1 -2 --distance-channels <mid and tweeter '
                       'channels> for a blind A/B')
        else:
            likely = ('a vague or distant stage usually comes with a smeared image (%s)'
                      % (', '.join(loose) or 'none measured'))
            nxt.append('fix the smeared instrument bands first (finish imaging section), then '
                       'voice-variants --distance-db 1 for a blind A/B')
        conf = 'consistent' if (presence or over or loose) else 'not_explained'
    else:
        measured += ['%s image %s' % (b['instrument'], b['focus']) for b in imaging
                     if b.get('focus') in ('loose', 'smeared')]
        likely = ('width comes from the outermost speakers and the side reflections: first check the '
                  'far-left and far-right positions on tracks 2-6. A narrow stage with good positions '
                  'is a focus-against-spaciousness choice (Kaplanis et al. 2017)')
        nxt.append('imaging --solo-l --solo-r (timed sweeps) for the extremes; rear fill per '
                   'methodology if the car has it')
        conf = 'consistent' if loose else 'not_explained'
    return measured, likely, nxt, conf


def _balance(name, item, report):
    heard = set(item['heard'])
    eb = (report.get('tone') or {}).get('emma_bands')
    measured, nxt = [], []
    if eb and eb.get('verdict'):
        measured.append('band levels: %s (%s)' % (
            ', '.join('%s %+.1f' % (b['band'], b['median_db']) for b in eb['bands']
                      if b['median_db'] is not None), eb['verdict']))
    if name == 'normal':
        if eb and eb.get('spread_db') is not None and eb['spread_db'] > 2.0:
            likely = 'the bands sit unevenly against the target (%s)' % eb['verdict']
            conf = 'measured'
        elif heard:
            likely = ('the balance measures even against the target, so this is the target itself: '
                      'voice it (bass shelf, tilt) and A/B blind')
            conf = 'consistent'
        else:
            likely = 'not explained by the captures given'
            conf = 'not_explained' if eb else 'no_capture'
        nxt.append('voice the target (core workflow step 3b), then voice-variants + ab-make + prefs')
        return measured, likely, nxt, conf
    nxt.append('emma-volume --normal <capture at your volume> --loud <the same about 6 dB up>')
    if heard & {'harsh', 'compressed', 'distorted', 'rattle'}:
        sub = report.get('sub') or {}
        if (sub.get('harmonics') or {}).get('worst'):
            measured.append('sub: ' + sub['harmonics']['worst'])
        likely = 'something runs out of headroom or distorts when turned up'
        nxt.append('quality-check (compression, distortion, headroom) at the louder volume')
        conf = 'consistent' if measured else 'not_explained'
    elif heard & {'boomy', 'bass heavy'}:
        likely = ('bass grows faster than the rest as level rises (equal-loudness contours): a '
                  'level-dependent voicing choice')
        nxt.append('listening-level --capture <full system> for the options')
        conf = 'consistent'
    else:
        likely = 'compare the louder capture with the normal one band by band'
        conf = 'no_capture'
    return measured, likely, nxt, conf


PLEASURE = {
    'clarity': 'residual midrange peaks and image focus',
    'details': 'residual high-frequency peaks and image focus',
    'transparency': 'residual peaks and bass decay',
    'distinction & separation': 'image focus per instrument and overlapping passbands (height)',
    'body of voice & air': 'the 150-400 Hz level (body) and the top octave (air) against the target',
    'dynamics & energy': 'headroom and compression at the volume played (emma-volume, quality-check)',
    'effortless sound': 'headroom and distortion when turned up (emma-volume, quality-check)',
    'naturalness': 'the overall balance and the target itself',
    'harmony & musicality': 'the overall balance and the target itself',
    'atmosphere & emotion': 'stage size and ambience: focus against spaciousness',
}


def _pleasure(item, report):
    lacking = [w for w in item['heard'] if w in PLEASURE]
    measured = ['%s: look at %s' % (w, PLEASURE[w]) for w in lacking]
    likely = ('listening pleasure follows the other items: fix the measured ones first'
              if lacking else 'no reasons ticked')
    return measured, likely, ['the items above, highest lost points first'], 'consistent' if lacking else 'not_explained'


def _imaging(sheet, report):
    bands = {b['instrument']: b for b in (report.get('imaging') or {}).get('bands', [])}
    rows = []
    for pos in POSITIONS:
        row = sheet['imaging'][pos]
        if row['points'] is None:
            continue
        wrong = {ins: v for ins, v in row['heard'].items() if v != pos}
        if row['points'] >= 5 and not wrong:
            continue
        targets = list(wrong) or [ins for ins in INSTRUMENTS
                                  if bands.get(BAND_NAME[ins], {}).get('focus') in ('loose', 'smeared')
                                  or str(bands.get(BAND_NAME[ins], {}).get('centre', '')).startswith('pulled')]
        measured = []
        for ins in targets:
            b = bands.get(BAND_NAME[ins])
            if b and b.get('focus'):
                measured.append('%s band (%d-%d Hz): %s, %s; widest swing %d-%d Hz'
                                % (BAND_NAME[ins], b['band_hz'][0], b['band_hz'][1], b['centre'],
                                   b['focus'], b['widest_swing_hz'][0], b['widest_swing_hz'][1]))
            elif b:
                measured.append('%s band: %s' % (BAND_NAME[ins], b.get('verdict')))
        heard = ['%s heard %s' % (ins, v) for ins, v in wrong.items()]
        if not bands:
            likely, conf = 'no left/right captures given', 'no_capture'
            nxt = ['finish --left <left solos> --right <right solos>  (capture-plan --goal lr)']
        elif pos == 'centre' and measured:
            likely = ('at the centre both sides play equally, so a band pulled or smeared between the '
                      'sides moves it: correct the hot side at the widest swing')
            nxt = ['lr-match / stereo-propose for level; imaging --near-side for the time option']
            conf = 'measured'
        elif pos == 'centre':
            likely = ('the level balance measures centred: the time cue is the next suspect, which '
                      'MMM cannot show')
            nxt = ['timed sweeps of each side, then imaging --bands emma --near-side <side>']
            conf = 'not_explained'
        elif pos in ('left', 'right'):
            likely = ('a hard-panned instrument should come from one side only: the other side or a '
                      'reflection is pulling it in; rarely a level problem')
            nxt = ['listen with the other side muted; decay.py reflections on that side\'s impulse']
            conf = 'consistent' if measured else 'not_explained'
        else:
            likely = ('half-left and half-right positions depend on the time difference between the '
                      'sides at this seat; the nearer side wins for half-panned sounds')
            nxt = ['timed sweeps, then imaging --bands emma --near-side <side>']
            conf = 'consistent' if measured else 'not_explained'
        rows.append({'item': 'imaging: %s position' % pos, 'points': row['points'], 'max': 5,
                     'lost': 5 - row['points'], 'heard': heard, 'comment': None,
                     'measured': measured, 'likely': likely, 'next': nxt, 'confidence': conf})
    return rows


def explain(sheet, notes, report):
    """Each scored item with lost points, against what the report measured."""
    items = _imaging(sheet, report)
    for name, item in sheet['items'].items():
        if item['points'] is None or (item['points'] >= item['max'] and not item['heard']):
            continue
        if name in ('sub_bass', 'mid_bass', 'midrange', 'high'):
            measured, likely, nxt, conf = _tonal(name, item, report)
        elif name in ('distance', 'width', 'height'):
            measured, likely, nxt, conf = _stage(name, item, report)
        elif name in ('normal', 'louder'):
            measured, likely, nxt, conf = _balance(name, item, report)
        else:
            measured, likely, nxt, conf = _pleasure(item, report)
        items.append({'item': LABEL[name], 'points': item['points'], 'max': item['max'],
                      'lost': round(item['max'] - item['points'], 1), 'heard': item['heard'],
                      'comment': item['comment'], 'measured': measured, 'likely': likely,
                      'next': nxt, 'confidence': conf})
    for key, val in sheet['deductions'].items():
        if val < 0:
            items.append({'item': key.replace('_', ' '), 'points': val, 'max': 0, 'lost': -val,
                          'heard': [], 'comment': None, 'measured': [],
                          'likely': ('hum, hiss or pops on the zero-bit track' if key == 'system_noise'
                                     else 'equipment visible from the seat: not a tuning matter'),
                          'next': (['noise-check --off <system off> --on <on, playing silence>']
                                   if key == 'system_noise' else []),
                          'confidence': 'not_explained'})
    items.sort(key=lambda r: -r['lost'])
    rank = {'measured': 0, 'consistent': 1, 'not_explained': 2, 'no_capture': 3}
    priorities = sorted((r for r in items if r['lost'] > 0 and r['item'] != LABEL['pleasure']),
                        key=lambda r: (rank[r['confidence']], -r['lost']))[:5]
    return {'source': sheet['source'], 'quoted': sheet['quoted'], 'total': score(sheet),
            'items': items,
            'priorities': ['%s (-%g): %s -> %s' % (r['item'], r['lost'], r['likely'],
                                                    r['next'][0] if r['next'] else 'listen again')
                           for r in priorities],
            'notes': notes + [
                'confidence: measured = the captures show the cause; consistent = they fit it; '
                'not_explained = they do not show it; no_capture = nothing given to check it',
                'a judge scores one seat at the suggested volume: tune and capture that seat there',
                'comments and names are the listener\'s words, quoted as data']}
