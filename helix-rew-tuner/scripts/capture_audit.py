# capture_audit.py -- what a set of MMM/RTA captures can and cannot support,
# read from the captures themselves before any analysis trusts them.
#
# REW writes a capture-quality record into every export and .mdat (RTA
# resolution, FFT, window, averages, mic and gain, input volume, time, and
# calibrated levels including the energy below 22 Hz and above 22 kHz). The
# analysis commands used to read none of it. On one real set that hid:
# mic-movement noise below 22 Hz louder than a tweeter solo's own passband,
# noise floors 11-14 dB apart between twin captures, one file exported
# smoothed among unsmoothed ones, two different mics and two RTA resolutions
# across sessions, sub captures loud enough to clip the mic, and a rising
# 12-24 kHz artefact in low-passed solos.
#
# Three things live here:
#   auto_profile(...)    the capture profile built from the headers, so nobody
#                        has to hand-write one (only mic aim, noise type, engine
#                        and seat are left to ask)
#   audit(...)           per-capture and whole-set checks, and a table of
#                        which analyses each file can feed and why
#   stopband_floor(...)  the moving-mic noise floor read from band-limited
#                        solos' stopbands -- measured during real movement,
#                        unlike a static ambient capture
#
# Everything here reads; nothing is written except the JSON report.
import math
import os
import re

import numpy as np

import measure

# REW's RTA overlaps successive FFTs by this much (its RTA help: "50% for 16k,
# 75% for 32k, 87.5% for 64k and 93.75% for 128k"); "Max overlap" can lower it.
REW_OVERLAP = {16384: 0.5, 32768: 0.75, 65536: 0.875, 131072: 0.9375}
MIN_CAPTURE_S = 20.0
SITTING_GAP_MIN = 20.0
PINK_CREST_DB = 12.0           # peak over RMS for pink noise, near enough
# Peak SPL where the mic's ADC clips, by model and gain setting. Forum-reported
# for the UMIK-1 (miniDSP does not publish it per gain version): treat as
# approximate.
MIC_CLIP_DB_SPL = {('UMIK-1', 18.0): 115.0, ('UMIK-1', 12.0): 121.0}
ROLE_SEARCH_HZ = {'tweeter': (1500.0, 20000.0), 'mid': (150.0, 8000.0),
                  'midbass': (40.0, 1200.0), 'sub': (15.0, 150.0),
                  'full': (20.0, 20000.0), 'rear': (60.0, 20000.0)}
FLOOR_GUARD_OCT = 2.0          # a stopband this far past the passband edge is floor
NOISE_LF_HZ = 100.0            # below this, stopband energy is handling/air, not leakage
NOISE_LF_MOVING_HZ = 300.0     # ... and below this when the capture shows movement noise
HF_RISE_DB = 15.0              # a low-passed solo rising this much from 10 to 17-21 kHz
HF_SET_EXCESS_DB = 10.0        # ... or this far above the set's other low-passed solos up there


# ------------------------------------------------------------------ helpers
def role_from_name(name):
    """{'driver', 'side', 'stage', 'ambient'} guessed from a capture name
    ("LF Mid RAW", "Front Left Tweeter", "Both Mids", "System Sum"). A guess
    for grouping and search ranges -- the user's labels win."""
    low = ' %s ' % re.sub(r'[_\-./]+', ' ', (name or '').lower())
    has = lambda *words: any(re.search(r'\b%s\b' % w, low) for w in words)
    ambient = has('ambient', 'noise', 'silence', 'floor', 'background', 'off')
    if has('sub', 'subwoofer', 'subs'):
        driver = 'sub'
    elif has('midbass', 'mid bass', 'midbasses', 'woofer', 'woofers', 'mb', 'door', 'low', 'lows'):
        driver = 'midbass'
    elif has('tweeter', 'tweeters', 'tweet', 'tw', 'high', 'highs', 'hi'):
        driver = 'tweeter'
    elif has('mid', 'mids', 'midrange', 'mr'):
        driver = 'mid'
    elif has('rear', 'rears'):
        driver = 'rear'
    elif has('system', 'sum', 'full', 'stage', 'all', 'front'):
        driver = 'full'
    else:
        driver = None
    if has('both', 'pair', 'together', 'l r', 'lr', 'stereo') or driver == 'full' and not has(
            'left', 'right', 'lf', 'rf', 'fl', 'fr', 'l', 'r'):
        side = 'both'
    elif has('left', 'lf', 'fl', 'l', 'lh', 'rl'):
        side = 'left'
    elif has('right', 'rf', 'fr', 'r', 'rh', 'rr'):
        side = 'right'
    else:
        side = None
    stage = next((s.upper() for s in ('raw', 'xo', 'eq') if has(s)), None)
    return {'driver': driver, 'side': side, 'stage': stage, 'ambient': bool(ambient)}


def band_levels(freqs, db, centres, half_oct=1.0 / 6.0):
    """Power-average level (dB) in fractional-octave bands; NaN where empty."""
    p = 10.0 ** (np.asarray(db, dtype=float) / 10.0)
    out = []
    for c in centres:
        sel = (freqs >= c / 2 ** half_oct) & (freqs < c * 2 ** half_oct)
        out.append(10.0 * np.log10(np.mean(p[sel])) if np.any(sel) else np.nan)
    return np.array(out)


THIRD_OCT = 1000.0 * 2.0 ** (np.arange(-17, 14) / 3.0)      # 20 Hz .. 20 kHz


def smooth_oct(freqs, db, frac=3.0):
    """Power average over a 1/frac-octave window centred on every bin."""
    p = 10.0 ** (np.asarray(db, dtype=float) / 10.0)
    lf = np.log2(freqs)
    c = np.concatenate([[0.0], np.cumsum(p)])
    lo = np.searchsorted(lf, lf - 0.5 / frac)
    hi = np.searchsorted(lf, lf + 0.5 / frac, side='right')
    return 10.0 * np.log10((c[hi] - c[lo]) / np.maximum(hi - lo, 1))


def passband(freqs, db, driver=None, drop_db=20.0):
    """(lo, hi) Hz where a solo plays: the run around its loudest 1/3-octave
    region (searched inside the driver's usual range when known, because an
    in-car tweeter solo's handling noise below 40 Hz can be as loud as the
    tweeter) that stays within drop_db of that peak. None if nothing stands out."""
    sm = smooth_oct(freqs, db, 3.0)
    lo_s, hi_s = ROLE_SEARCH_HZ.get(driver, (40.0, 16000.0))
    search = (freqs >= max(lo_s, freqs[0])) & (freqs <= min(hi_s, freqs[-1]))
    if np.count_nonzero(search) < 4:
        return None
    idx = np.flatnonzero(search)
    peak = idx[int(np.argmax(sm[idx]))]
    level = sm[peak]
    live = sm >= level - drop_db
    lo = peak
    while lo > 0 and live[lo - 1] and freqs[lo - 1] >= lo_s / 2:
        lo -= 1
    hi = peak
    while hi < len(freqs) - 1 and live[hi + 1] and freqs[hi + 1] <= hi_s * 2:
        hi += 1
    return float(freqs[lo]), float(freqs[hi])


def capture_length_s(fmt, sample_rate_hz=None, overlap=None):
    """(seconds, assumptions) of an RTA capture from its averages: the first
    FFT needs fft samples, each further average one hop."""
    if not fmt or fmt.get('kind') not in ('rta', 'spectrum') or not fmt.get('averages'):
        return None, []
    fft, avg = fmt['fft_length'], fmt['averages']
    notes = []
    fs = sample_rate_hz
    if not fs:
        fs = 48000.0
        notes.append('sample rate not recorded: 48 kHz assumed')
    if overlap is None:
        overlap = REW_OVERLAP.get(fft, 0.5)
        notes.append('REW\'s maximum overlap for a %d-point FFT (%.2f%%) assumed: a lower '
                     '"Max overlap" setting made the capture longer' % (fft, 100 * overlap))
    hop = fft * (1.0 - overlap)
    return (fft + (avg - 1) * hop) / fs, notes


def _power_sum_db(*levels):
    return 10.0 * math.log10(sum(10.0 ** (x / 10.0) for x in levels))


def iso226_threshold_db(freqs):
    """ISO 226:2003 threshold of hearing (dB SPL), log-interpolated."""
    import loudness
    return loudness.threshold_db(freqs)


# ------------------------------------------------------------------ records
def load_capture(path, label=None, band=None):
    """One capture: data on its own axis plus its parsed header and role."""
    f, s, _p, _c = measure.load_text_export(path)
    hdr = measure.read_export_header(path)
    rew = hdr['rew']
    name = label or rew.get('measurement') or os.path.splitext(os.path.basename(
        measure_name(path)))[0]
    role = role_from_name(name)
    # A RAW capture plays the driver with its crossover bypassed: full range,
    # so its name says nothing about where it stops.
    if band is None and role['driver'] and role['driver'] not in ('full', 'rear')             and not role['ambient'] and role['stage'] != 'RAW':
        band = passband(f, s, role['driver'])
    return {'path': path, 'name': name, 'freqs': f, 'db': s, 'header': hdr, 'rew': rew,
            'role': role, 'passband': band}


def measure_name(path):
    import mdat
    if mdat.is_spec(path):
        return mdat.select(path)['name']
    return path


def expand(paths):
    """Paths, with a bare multi-measurement .mdat expanded to every measurement."""
    import mdat
    out = []
    for p in paths:
        base, sel = mdat.split_spec(p)
        if sel is None and base.lower().endswith('.mdat'):
            out.extend('%s::#%d' % (base, m['index']) for m in mdat.load(base))
        else:
            out.append(p)
    return out


# ------------------------------------------------------------------ profile
SETTING_KEYS = ('rew_version', 'mic_serial', 'mic_cal_file', 'mic_model', 'mic_gain_db',
                'input_volume', 'rta', 'fft_length', 'window', 'export_smoothing',
                'sample_rate_hz', 'playback')


def settings(cap):
    rew = cap['rew']
    fmt, src = rew['format'] or {}, rew['source'] or {}
    out = rew.get('output') or ''
    playback = None
    if out:
        playback = ('car source / separate clock' if 'not selected' in out.lower()
                    or 'no output' in out.lower() else 'REW generator: %s' % out.split(',')[0])
    smooth = cap['header'].get('smoothing')
    return {'rew_version': rew.get('version'), 'mic_serial': rew.get('mic_serial'),
            'mic_cal_file': rew.get('mic_cal_file'), 'mic_model': src.get('mic_model'),
            'mic_gain_db': src.get('gain_db'), 'input_volume': src.get('input_volume'),
            'rta': ('1/%d' % fmt['rta_fraction'] if fmt.get('rta_fraction') else fmt.get('kind')),
            'fft_length': fmt.get('fft_length'), 'window': fmt.get('window'),
            'export_smoothing': ('none' if cap['header'].get('unsmoothed') else smooth),
            'sample_rate_hz': rew.get('sample_rate_hz'), 'playback': playback}


def auto_profile(caps):
    """The capture profile the headers already state, the fields that differ
    between captures, and what is left to ask (files cannot say it)."""
    rows = [settings(c) for c in caps]
    profile, differs = {}, {}
    for key in SETTING_KEYS:
        vals = {}
        for c, row in zip(caps, rows):
            if row[key] is not None:
                vals.setdefault(str(row[key]), []).append(c['name'])
        if len(vals) == 1:
            profile[key] = next(iter(vals))
        elif len(vals) > 1:
            differs[key] = vals
    cal = (profile.get('mic_cal_file') or '').lower()
    if '90' in cal:
        profile['mic_cal'] = '90deg'
    elif cal and ('0deg' in cal or '_0' in cal):
        profile['mic_cal'] = '0deg'
    ask = [k for k, why in (('noise', 'which test signal (pink periodic / pink random)'),
                            ('mic_aim', 'where the mic pointed'),
                            ('engine', 'engine off?'), ('seat', 'which seat'),
                            ('mic_path', 'the path the mic was moved along'))
           if k not in profile]
    if 'mic_cal' not in profile:
        ask.append('mic_cal')
    return {'stated_by_files': profile, 'differs': differs, 'ask_user': ask}


# ------------------------------------------------------------------ floor
def stopband_mask(freqs, band, guard_oct=FLOOR_GUARD_OCT):
    lo, hi = band
    return (freqs < lo / 2 ** guard_oct) | (freqs > hi * 2 ** guard_oct)


def stopband_floor(freqs, caps, guard_oct=FLOOR_GUARD_OCT):
    """The moving-mic noise floor on `freqs` from band-limited solos.

    Where a solo is guard_oct beyond its own passband edge, what the mic
    records is the cabin and the mic's own movement, not that driver. Returns
    {'floor_db' (the highest solo floor per bin -- conservative for a noise
    gate; NaN where no solo covers it), 'median_db', 'spread_db' (highest
    minus lowest, where two or more solos cover a bin), 'sources'}."""
    rows, names = [], []
    for c in caps:
        if not c.get('passband'):
            continue
        db = measure.resample_log(c['freqs'], c['db'], freqs)
        live = measure.support_mask(c['freqs'], freqs) & stopband_mask(freqs, c['passband'], guard_oct)
        rows.append(np.where(live, db, np.nan))
        names.append(c['name'])
    if not rows:
        return None
    stack = np.vstack(rows)
    with np.errstate(all='ignore'):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            hi, lo = np.nanmax(stack, axis=0), np.nanmin(stack, axis=0)
            med = np.nanmedian(stack, axis=0)
    count = np.sum(np.isfinite(stack), axis=0)
    return {'floor_db': hi, 'median_db': med,
            'spread_db': np.where(count >= 2, hi - lo, np.nan),
            'count': count, 'sources': names}


def floor_report(freqs, floor):
    """JSON-safe third-octave summary of a stopband floor."""
    if floor is None:
        return None
    out = []
    for c in THIRD_OCT:
        sel = (freqs >= c / 2 ** (1 / 6)) & (freqs < c * 2 ** (1 / 6)) & np.isfinite(floor['floor_db'])
        if not np.any(sel):
            continue
        spread = floor['spread_db'][sel]
        out.append({'hz': round(float(c), 1),
                    'floor_db': round(float(10 * np.log10(np.mean(10 ** (floor['floor_db'][sel] / 10)))), 1),
                    'spread_db': (round(float(np.nanmax(spread)), 1)
                                  if np.isfinite(spread).any() else None)})
    return {'sources': floor['sources'], 'third_octaves': out}


# ------------------------------------------------------------------ checks
def _flag(level, code, text):
    return {'level': level, 'code': code, 'text': text}


def check_capture(cap, overlap=None, min_length_s=MIN_CAPTURE_S):
    """Flags for one capture, and per-analysis usability."""
    rew, f, db = cap['rew'], cap['freqs'], cap['db']
    fmt, lv, src = rew['format'] or {}, rew['levels'] or {}, rew['source'] or {}
    role, band = cap['role'], cap['passband']
    flags = []
    length, assumptions = capture_length_s(fmt, rew.get('sample_rate_hz'), overlap)
    if length is not None and length < min_length_s:
        flags.append(_flag('warn', 'short_capture',
                           'about %.0f s of averaging (%d averages): an MMM pass needs about '
                           '%.0f s or more to cover the head area evenly' % (
                               length, fmt['averages'], min_length_s)))
    if fmt.get('kind') == 'spectrum':
        flags.append(_flag('problem', 'spectrum_mode',
                           'captured in Spectrum mode: pink noise reads 3 dB/oct falling -- use the '
                           'RTA (1/N octave) mode'))
    if fmt.get('kind') == 'rta' and fmt.get('rta_smoothing') not in (None, 'none'):
        flags.append(_flag('warn', 'rta_smoothing',
                           'the RTA itself smoothed the capture (%s): nothing can unsmooth it'
                           % fmt['rta_smoothing']))
    below, inband = lv.get('below_22_db'), lv.get('unw_22_22k_db')
    if below is not None and inband is not None:
        if role['driver'] == 'sub' and not role['ambient'] and below >= inband - 3.0:
            flags.append(_flag('warn', 'infrasound',
                               'as much energy below 22 Hz (%.1f dB) as in band (%.1f dB) on a sub '
                               'capture: the sub is reproducing infrasound -- check for a subsonic '
                               'high-pass; it frees headroom and cuts excursion' % (below, inband)))
        elif below >= inband - 6.0:
            flags.append(_flag('problem', 'handling_noise',
                               '%.1f dB below 22 Hz against %.1f dB in band: mic movement, handling or '
                               'air noise as loud as the signal. Its tail fills the bass: keep the '
                               'cable still, move the mic slowly, close vents and windows' % (below, inband)))
        elif below >= inband - 15.0:
            flags.append(_flag('warn', 'handling_noise',
                               '%.1f dB below 22 Hz against %.1f dB in band: movement noise that can '
                               'reach the lowest bass bands' % (below, inband)))
    rms = lv.get('input_rms_db')
    clip = MIC_CLIP_DB_SPL.get((src.get('mic_model'), src.get('gain_db')))
    if rms is not None and clip is not None:
        peak = rms + PINK_CREST_DB
        if peak >= clip:
            flags.append(_flag('problem' if peak >= clip + 3 else 'warn', 'mic_clip_risk',
                               'Input RMS %.1f dB SPL: noise peaks near %.0f dB reach the %s (%g dB gain) '
                               'clip point of about %.0f dB SPL -- lower the playback level by %.0f dB '
                               'and re-capture' % (rms, peak, src['mic_model'], src['gain_db'], clip,
                                                   math.ceil(peak - clip + 3))))
    vol = src.get('input_volume')
    if vol is not None and abs(vol - 1.0) > 1e-3:
        flags.append(_flag('info', 'input_volume',
                           'input volume %.3f: a UMIK cal file assumes 100%%, so absolute SPL reads '
                           '%.1f dB low (relative comparisons at the same volume are fine)'
                           % (vol, -20 * math.log10(vol))))
    above = lv.get('above_22k_db')
    if above is not None and above > 45.0:
        flags.append(_flag('warn', 'ultrasonic',
                           '%.1f dB above 22 kHz: ultrasonic content or interference in the chain' % above))
    if band is not None:
        lo, hi = band
        pb = (f >= lo) & (f <= hi)
        pass_db = float(np.median(smooth_oct(f, db)[pb])) if np.any(pb) else None
        sm = smooth_oct(f, db, 3.0)
        if hi < 6000.0 and f[-1] > 20000.0 and pass_db is not None:
            # A UMIK's cal correction lifts its own noise floor towards 20 kHz by
            # several dB, so a modest rise is normal; the set-level check in
            # audit() compares low-passed solos with each other as well.
            top = float(np.mean(sm[(f >= 17000) & (f <= 21000)]))
            mid = float(np.mean(sm[(f >= 9000) & (f <= 11000)]))
            cap['hf_top_db'] = top
            if top - mid > HF_RISE_DB:
                flags.append(_flag('warn', 'hf_artefact',
                                   'level RISES from %.0f dB at 10 kHz to %.0f dB at 17-21 kHz on a '
                                   'driver that plays only to %.0f Hz: interference or system noise '
                                   'in the chain (or mic clipping on a loud capture)' % (mid, top, hi)))
        if pass_db is not None:
            moving = any(fl['code'] == 'handling_noise' for fl in flags)
            far = stopband_mask(f, band) & (f >= (NOISE_LF_MOVING_HZ if moving else NOISE_LF_HZ))                 & (f <= 12000.0)
            if np.any(far):
                worst = int(np.flatnonzero(far)[np.argmax(sm[far])])
                gap = pass_db - sm[worst]
                if gap < 20.0:
                    where = 'above its low-pass' if f[worst] > hi else 'below its high-pass'
                    why = ('rattle, distortion, interference, or another driver still playing'
                           if f[worst] > hi else 'another driver still playing (mute check)')
                    flags.append(_flag('warn', 'stopband_excess',
                                       'only %.0f dB below its passband at %.0f Hz, two octaves %s: %s'
                                       % (gap, f[worst], where, why)))
    if role['driver'] == 'full' and not role['ambient']:
        thr = iso226_threshold_db(THIRD_OCT[:5])
        lows = band_levels(f, db, THIRD_OCT[:5])
        inaudible = [round(float(c), 1) for c, x, t in zip(THIRD_OCT[:5], lows, thr)
                     if np.isfinite(x) and x < t]
        if inaudible:
            flags.append(_flag('info', 'below_hearing_threshold',
                               'at this playback level the %s Hz third-octaves sit below the '
                               'ISO 226 hearing threshold: if this is your listening level, '
                               'that bass is inaudible (see listening-level); for measuring, a '
                               'louder capture also beats the movement noise'
                               % '/'.join('%g' % c for c in inaudible)))
    return flags, length, assumptions


def _sittings(caps):
    dated = [(c['rew'].get('date'), i) for i, c in enumerate(caps)]
    if any(d is None for d, _ in dated):
        return None
    import datetime
    order = sorted(dated)
    groups, label, last = {}, 1, None
    for d, i in order:
        t = datetime.datetime.fromisoformat(d)
        if last is not None and (t - last).total_seconds() > SITTING_GAP_MIN * 60:
            label += 1
        groups[i] = label
        last = t
    return [{'name': caps[i]['name'], 'date': d, 'sitting': groups[i]} for d, i in order]


_SIDE_WORDS = {'left', 'right', 'both', 'l', 'r', 'lf', 'rf', 'fl', 'fr', 'lh', 'rh', 'rl', 'rr',
               'pair', 'together', 'stereo', 'lr', 'front'}


def _name_tokens(name):
    return {t for t in re.split(r'[^a-z0-9]+', (name or '').lower()) if t} - _SIDE_WORDS


def find_triples(caps):
    """(A, B, BOTH) index triples: a left and a right capture of one driver
    group with the 'both' capture that belongs to them. Name-based, so it is a
    suggestion: when several 'both' captures could match (a "Front Both" and
    a "System Sum"), the one sharing the most name words with the halves wins,
    and each pair of halves is used once."""
    out, used = [], set()
    groups = {}
    for i, x in enumerate(caps):
        r = x['role']
        if r['ambient'] or r['side'] not in ('left', 'right', 'both'):
            continue
        groups.setdefault((r['driver'], r['stage']), {'left': [], 'right': [], 'both': []})[r['side']].append(i)
    for (_driver, _stage), g in groups.items():
        if len(g['left']) != 1 or len(g['right']) != 1 or not g['both']:
            continue
        a, b = g['left'][0], g['right'][0]
        halves = _name_tokens(caps[a]['name']) | _name_tokens(caps[b]['name'])
        best = max(g['both'], key=lambda k: (len(_name_tokens(caps[k]['name']) & halves),
                                            -len(_name_tokens(caps[k]['name']) - halves)))
        if (a, b) not in used:
            out.append((a, b, best))
            used.add((a, b))
    return out


def triple_levels(caps, triple, tol_db=1.0):
    """Was the playback level held across a cancel-check triple? The 'both'
    capture should sit near the power sum of its halves (in dBA, where the
    music band adds incoherently, and dBC)."""
    a, b, both = (caps[i] for i in triple)
    out = {'files': [a['name'], b['name'], both['name']], 'checks': []}
    noisy = any(x.get('handling_noise') for x in (a, b, both))
    # dB C passes the sub-22 Hz movement noise almost unweighted, so it only
    # checks the playback level when none of the three captures carries it.
    for key in ('dba',) if noisy else ('dba', 'dbc'):
        la, lb, lab = (x['rew']['levels'].get(key) for x in (a, b, both))
        if None in (la, lb, lab):
            continue
        pred = _power_sum_db(la, lb)
        diff = lab - pred
        out['checks'].append({'weighting': key, 'halves_db': [la, lb], 'both_db': lab,
                              'power_sum_db': round(pred, 1), 'difference_db': round(diff, 1),
                              'consistent': bool(-tol_db - 0.5 <= diff <= tol_db + 2.0)})
    out['consistent'] = all(c['consistent'] for c in out['checks']) if out['checks'] else None
    return out


def audit(paths, labels=None, bands=None, overlap=None, triples=None, min_length_s=MIN_CAPTURE_S):
    """The capture-audit report for `paths` (text exports, file.mdat::name,
    or whole .mdat files). bands: {name: (lo, hi)} passbands for solos the
    name does not identify; triples: explicit [(A, B, BOTH) names]."""
    paths = expand(paths)
    caps = []
    for i, p in enumerate(paths):
        label = labels[i] if labels and i < len(labels) else None
        cap = load_capture(p, label)
        if bands and cap['name'] in bands:
            cap['passband'] = tuple(bands[cap['name']])
        caps.append(cap)
    freqs = measure.common_grid(20.0, 20000.0, 48)
    profile = auto_profile(caps)
    floor = stopband_floor(freqs, caps)
    rows = []
    for cap in caps:
        flags, length, assumptions = check_capture(cap, overlap, min_length_s)
        cap['handling_noise'] = any(fl['code'] == 'handling_noise' for fl in flags)
        rows.append({'name': cap['name'], 'file': cap['path'], 'date': cap['rew'].get('date'),
                     'role': cap['role'],
                     'passband_hz': [round(x) for x in cap['passband']] if cap['passband'] else None,
                     'settings': settings(cap), 'levels': cap['rew']['levels'],
                     'capture_length_s': None if length is None else round(length, 1),
                     'length_assumptions': assumptions, 'flags': flags})
    tops = [c['hf_top_db'] for c in caps if c.get('hf_top_db') is not None]
    if len(tops) >= 3:
        ref = float(np.median(tops))
        for cap, row in zip(caps, rows):
            top = cap.get('hf_top_db')
            if top is not None and top > ref + HF_SET_EXCESS_DB and not any(
                    fl['code'] == 'hf_artefact' for fl in row['flags']):
                row['flags'].append(_flag('warn', 'hf_artefact',
                                          '%.0f dB at 17-21 kHz, %.0f dB above the other low-passed solos '
                                          'in this set, on a driver that plays only to %.0f Hz: '
                                          'interference or system noise in the chain (or mic clipping '
                                          'on a loud capture)' % (top, top - ref, cap['passband'][1])))
    for cap, row in zip(caps, rows):
        row['noise_limited_below_hz'] = _noise_limited_below(freqs, cap, floor)
    by_name = {c['name']: i for i, c in enumerate(caps)}
    tri = []
    for t in triples or []:
        missing = [n for n in t if n not in by_name]
        if missing:
            raise ValueError('triple names not among the captures: %s' % ', '.join(missing))
        tri.append(tuple(by_name[n] for n in t))
    tri = tri or find_triples(caps)
    triple_rows = [triple_levels(caps, t) for t in tri]
    for t, row in zip(tri, triple_rows):
        smooth = {settings(caps[i])['export_smoothing'] for i in t}
        if len(smooth) > 1:
            row['smoothing_mismatch'] = sorted(str(s) for s in smooth)
            row['consistent'] = False
    twins = _twin_floors(freqs, caps)
    set_flags = []
    for key, vals in profile['differs'].items():
        set_flags.append(_flag('problem' if key in ('rta', 'export_smoothing', 'mic_serial',
                                                    'mic_cal_file', 'fft_length') else 'warn',
                               'mixed_%s' % key,
                               'captures differ in %s: %s' % (key, '; '.join(
                                   '%s (%s)' % (v, ', '.join(n[:3]) + ('...' if len(n) > 3 else ''))
                                   for v, n in vals.items()))))
    for row in triple_rows:
        if row['consistent'] is False:
            set_flags.append(_flag('problem', 'triple_level',
                                   'cancel-check set %s does not hold one playback level or one '
                                   'export setting: its cancellation map is not evidence' % ' / '.join(row['files'])))
    for t in twins:
        if t['max_difference_db'] >= 6.0:
            set_flags.append(_flag('warn', 'twin_floor_mismatch',
                                   '%s and %s: moving-mic floors differ by up to %.0f dB at %s Hz -- '
                                   'a left/right difference there can be noise, not the speakers'
                                   % (t['a'], t['b'], t['max_difference_db'], t['where_hz'])))
    usable = [_usable(cap, row, profile, triple_rows) for cap, row in zip(caps, rows)]
    for row, use in zip(rows, usable):
        row['usable_for'] = use
    return {'captures': rows, 'set': {'profile': profile, 'flags': set_flags,
                                      'sittings': _sittings(caps), 'triples': triple_rows,
                                      'twin_floors': twins,
                                      'moving_floor': floor_report(freqs, floor)},
            'table': [_table_line(r) for r in rows]}


def _twin_floors(freqs, caps):
    """Left/right solos of one driver group: how far apart their stopband
    floors sit (the same noise should read the same)."""
    out = []
    for i, a in enumerate(caps):
        for b in caps[i + 1:]:
            ra, rb = a['role'], b['role']
            if not (a['passband'] and b['passband'] and ra['driver'] and ra['driver'] == rb['driver']
                    and {ra['side'], rb['side']} == {'left', 'right'} and ra['stage'] == rb['stage']):
                continue
            fa = stopband_floor(freqs, [a])['floor_db']
            fb = stopband_floor(freqs, [b])['floor_db']
            both = np.isfinite(fa) & np.isfinite(fb)
            if np.count_nonzero(both) < 8:
                continue
            d = np.abs(smooth_oct(freqs[both], fa[both]) - smooth_oct(freqs[both], fb[both]))
            k = int(np.argmax(d))
            out.append({'a': a['name'], 'b': b['name'], 'max_difference_db': round(float(d[k]), 1),
                        'where_hz': round(float(freqs[both][k]))})
    return out


def _noise_limited_below(freqs, cap, floor, margin_db=10.0, top_hz=500.0):
    """Highest frequency under top_hz where this capture is less than
    margin_db above the set's moving-mic floor (other solos' stopbands), or
    None when the floor does not reach this capture's range."""
    if floor is None:
        return None
    db = smooth_oct(freqs, measure.resample_log(cap['freqs'], cap['db'], freqs), 6.0)
    fl = floor['floor_db']
    sel = np.isfinite(fl) & (freqs <= top_hz) & measure.support_mask(cap['freqs'], freqs)
    if cap['passband']:
        sel &= (freqs >= cap['passband'][0]) & (freqs <= cap['passband'][1])
    low = sel & (db - fl < margin_db)
    return round(float(freqs[low].max())) if np.any(low) else None


def _usable(cap, row, profile, triples):
    """Per analysis: True, or the reason it is not (or only partly) usable."""
    codes = {f['code']: f for f in row['flags']}
    problems = [f['code'] for f in row['flags'] if f['level'] == 'problem']
    use = {}
    limit = row.get('noise_limited_below_hz')
    if not problems:
        use['tone_eq'] = True if not limit else 'above %d Hz (noise-limited below)' % limit
    elif set(problems) == {'handling_noise'}:
        use['tone_eq'] = 'above %d Hz only: movement noise below' % max(limit or 0, 100)
    else:
        use['tone_eq'] = 'no: %s' % ', '.join(problems)
    bass_block = [c for c in ('handling_noise', 'mic_clip_risk', 'infrasound') if c in codes]
    use['bass_decisions'] = True if not bass_block else 'no: %s' % ', '.join(bass_block)
    mixed = [k for k in ('rta', 'export_smoothing', 'mic_serial', 'fft_length') if k in profile['differs']]
    use['comparisons'] = True if not mixed else 'only within matching settings: %s differ' % ', '.join(mixed)
    in_triple = [t for t in triples if cap['name'] in t['files']]
    if in_triple:
        use['cancel_check'] = True if all(t['consistent'] is not False for t in in_triple) else \
            'no: the triple\'s level or smoothing does not match'
    vol = cap['rew']['source'].get('input_volume')
    use['absolute_spl'] = True if vol is None or abs(vol - 1.0) < 1e-3 else \
        'offset: input volume %.3f (cal assumes 1.000)' % vol
    return use


def _table_line(row):
    flags = ', '.join('%s%s' % ('!' if f['level'] == 'problem' else '', f['code']) for f in row['flags'])
    lv = row['levels'] or {}
    return '%-26s %-19s %5s s  %5s dBA  %s' % (
        row['name'][:26], row['date'] or '-',
        '-' if row['capture_length_s'] is None else '%.0f' % row['capture_length_s'],
        '-' if lv.get('dba') is None else '%.1f' % lv['dba'], flags or 'ok')


def cli(args):
    bands = {}
    for item in args.band or []:
        name, _, rng = item.rpartition('=')
        try:
            lo, hi = (float(x) for x in rng.split(','))
        except ValueError:
            raise ValueError('--band takes NAME=LO,HI (got %r)' % item)
        bands[name] = (lo, hi)
    return audit(args.captures, labels=args.labels, bands=bands, overlap=args.overlap,
                 triples=[tuple(t) for t in args.triple or []], min_length_s=args.min_length_s)
