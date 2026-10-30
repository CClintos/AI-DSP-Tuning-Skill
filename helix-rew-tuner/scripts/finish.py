# finish.py -- after the target curve: what still decides how the tune sounds.
#
# A target curve is a long-term average. Once the system sum sits on it,
# listeners and judges respond to other things (research: docs/research/
# 2026-10-29-beyond-the-target-curve.md in the repository):
#
#   tone     residual LOW-Q PEAKS about the broad fit. Peaks are far more
#            audible than equal dips (Buecklein 1981), and broad resonances are
#            audible at small amplitudes (Toole & Olive 1988). Dips are listed
#            to be left alone unless a cancel check explains them.
#   imaging  each EMMA instrument imaging in ONE place: the position (level,
#            and time when the captures carry phase) in third-octave slices of
#            the part of its range (2026 judge book, as `imaging --bands emma`)
#            both sides play; their mean (centre) and spread (focus). EMMA
#            scores an instrument heard in two places as zero; a range average
#            can be centred while the instrument is smeared.
#   height   overlapping passbands between driver pairs mounted at different
#            heights. Delay cannot move vertical images (no precedence effect
#            vertically, Wallis & Lee 2015) and vertically separated drivers
#            sharing 1-4 kHz scramble height cues; the high driver should own
#            everything from a few hundred Hz up.
#   sub      what gives a rear sub away: output above ~120 Hz (Theile 1992 and
#            later tests put detection at ~80-120 Hz) and harmonics against
#            Fielder & Benjamin's limits (H2 ~3%, H3 ~1%, higher ~0.3%) at the
#            level measured.
#   decay    bass ringing against Fazenda, Stephenson & Goldberg 2015
#            (music: 0.51 s at 63 Hz falling to 0.12 s at 250 Hz).
#   heard    with --heard, a listening sheet (assets/emma_listening_sheet.html,
#            the 280-point EMMA SQ sheet) read against all of the above by
#            scoresheet.py: each lost point next to what the captures show.
#
# It writes nothing. Each finding carries its evidence level and the command
# that acts on it; filters still go through propose/refine and plan/apply.
import math
import os

import numpy as np

import capture_audit
import measure
import tunelib

GRID = measure.common_grid(20.0, 20000.0, 96)
DEFAULT_TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'assets',
                              'default_incar_target.txt')
# The 2026 judge book's instruments and ranges (tracks 2-6), shared with imaging --bands emma.
EMMA_INSTRUMENTS = tuple((name, lo, hi) for name, (lo, hi)
                         in zip(tunelib.EMMA_IMAGING_INSTRUMENTS, tunelib.EMMA_IMAGING_BANDS))
MIN_COVER_OCT = 1.0           # the least of an instrument's range both sides must play
IMAGE_TOP_HZ = 16000.0        # as EMMA_BANDS: above this a moving-mic capture is mic- and noise-limited
PEAK_BAND = (150.0, 10000.0)
FULL_SCALE_DB = 16.0          # inter-channel level for a full image shift (tunelib.image_pull)
FB_LIMITS_PCT = {2: 3.0, 3: 1.0}
FB_HIGHER_PCT = 0.3
FAZENDA = ((32.0, 0.90), (63.0, 0.51), (250.0, 0.12))
DECAY_BANDS = (32, 40, 50, 63, 80, 100, 125, 160, 200, 250)
EVIDENCE = {
    'residual_peaks': 'strong: peaks are more audible than equal dips (Buecklein 1981); low-Q '
                      'resonances are audible at small amplitudes (Toole & Olive 1988)',
    'image_focus': 'strong: EMMA scores an instrument heard in more than one place as 0; '
                   '16-18 dB or 1-1.5 ms moves an image fully (Lee & Rumsey 2013, Sengpiel)',
    'height': 'strong: no vertical precedence effect and erratic height with overlapping vertical '
              'sources at 1-4 kHz (Wallis & Lee 2015); pitch-height effect',
    'sub_leakage': 'moderate: a sub is detected from about 80-120 Hz depending on placement '
                   '(Theile 1992 and later listening tests)',
    'sub_harmonics': 'moderate: Fielder & Benjamin 1988 pure-tone limits (conservative for music)',
    'decay': 'strong: Fazenda, Stephenson & Goldberg 2015 thresholds (music)',
    'smoothness': 'moderate in cars: Olive 2004 narrow-band deviation, built on loudspeakers',
}


def _smooth(freqs, db, frac):
    return capture_audit.smooth_oct(freqs, db, frac)


# ------------------------------------------------------------------ tone
def nbd(freqs, db, lo=100.0, hi=12000.0):
    """Mean absolute deviation inside half-octave bands (Olive's NBD)."""
    vals, c = [], lo * 2 ** 0.25
    while c * 2 ** 0.25 <= hi:
        sel = (freqs >= c / 2 ** 0.25) & (freqs < c * 2 ** 0.25)
        if np.count_nonzero(sel) >= 4:
            vals.append(float(np.mean(np.abs(db[sel] - np.mean(db[sel])))))
        c *= 2 ** 0.5
    return float(np.mean(vals)) if vals else None


def _q_from_width(width_oct):
    if width_oct <= 0:
        return None
    r = 2.0 ** width_oct
    return float(math.sqrt(r) / (r - 1.0))


def residual_peaks(freqs, dev_db, live=None, noise_db=0.3, band=PEAK_BAND, max_peaks=6, min_db=1.0):
    """Peaks of the 1/6-octave deviation from target about its own two-octave
    trend (the trend is tilt and level -- voicing's job), ranked by
    audibility: height, with broad (Q <= 10) ones first. A one-octave trend
    would absorb exactly the broad, most audible peaks."""
    live = np.ones_like(freqs, dtype=bool) if live is None else live
    res = _smooth(freqs, dev_db, 6.0) - _smooth(freqs, dev_db, 0.5)
    floor = max(min_db, 2.0 * noise_db)
    idx = np.flatnonzero(live & (freqs >= band[0]) & (freqs <= band[1]))
    peaks, dips = [], []
    for k in idx[1:-1]:
        if res[k] > res[k - 1] and res[k] >= res[k + 1] and res[k] >= floor:
            half = res[k] / 2.0
            lo = k
            while lo > 0 and res[lo] > half:
                lo -= 1
            hi = k
            while hi < len(freqs) - 1 and res[hi] > half:
                hi += 1
            width = float(np.log2(freqs[hi] / freqs[lo]))
            q = _q_from_width(width)
            span = max(width, 1.0 / 6.0)
            cut = -round(min(0.75 * res[k], 3.0) * 4) / 4
            peaks.append({'hz': round(float(freqs[k])), 'height_db': round(float(res[k]), 1),
                          'width_oct': round(width, 2), 'q': None if q is None else round(q, 1),
                          'suggested_cut': {'q': None if q is None else round(float(np.clip(q, 1.0, 6.0)), 1),
                                            'gain_db': cut},
                          'fit_band_hz': [round(float(freqs[k]) / 2 ** span), round(float(freqs[k]) * 2 ** span)]})
        if res[k] < res[k - 1] and res[k] <= res[k + 1] and res[k] <= -1.5:
            dips.append({'hz': round(float(freqs[k])), 'depth_db': round(float(res[k]), 1)})
    peaks.sort(key=lambda p: -(p['height_db'] * (1.0 if (p['q'] or 99) <= 10 else 0.6)))
    dips.sort(key=lambda d: d['depth_db'])
    return _merge(peaks, 'height_db')[:max_peaks], _merge(dips, 'depth_db')[:max_peaks]


def _merge(rows, key, within_oct=1.0 / 6.0):
    """One entry per feature: drop rows within within_oct of a stronger one."""
    kept = []
    for r in rows:                      # already strongest first
        if all(abs(math.log2(r['hz'] / k['hz'])) > within_oct for k in kept):
            kept.append(r)
    return kept


# ------------------------------------------------------------------ imaging
def _slices(lo, hi):
    """Third-octave slices of [lo, hi]."""
    n = max(1, int(round(3 * math.log2(hi / lo))))
    edges = lo * (hi / lo) ** (np.arange(n + 1) / n)
    return list(zip(edges[:-1], edges[1:]))


def image_balance(freqs, left_db, right_db, live, left_phase=None, right_phase=None, played=None):
    """Per EMMA instrument: the image position (pull, -1 full right .. +1 full
    left) in third-octave slices of the part of its range both sides play,
    from level and, with phase, time. Centre = mean pull; focus = spread of
    the slices (max - min), up to 16 kHz. A mono sub carries no left/right
    image, so an instrument's image comes from the L/R drivers that play it."""
    lsm, rsm = tunelib.erb_smooth(freqs, left_db), tunelib.erb_smooth(freqs, right_db)
    time_cue = left_phase is not None and right_phase is not None
    reach = live if played is None else played & live
    out = []
    for name, lo, hi in EMMA_INSTRUMENTS:
        cov = reach & (freqs >= lo) & (freqs <= min(hi, IMAGE_TOP_HZ))
        row = {'instrument': name, 'band_hz': [lo, hi]}
        span = (float(freqs[cov][0]), float(freqs[cov][-1])) if np.any(cov) else None
        if span is None or math.log2(span[1] / span[0]) < MIN_COVER_OCT:
            row.update(verdict='not_covered',
                       why=('the left/right captures play %s of this %d-%d Hz range: less than an '
                            'octave to judge its image by'
                            % ('none' if span is None else '%d-%d Hz' % span, lo, hi)))
            out.append(row)
            continue
        slices = _slices(*span)
        rows = tunelib.band_itd_ild(freqs, np.where(live, lsm, np.nan), np.where(live, rsm, np.nan),
                                    left_phase if time_cue else None, right_phase if time_cue else None,
                                    bands=slices, min_bins=6)
        pulled = tunelib.image_pull(rows, icld_full_scale_db=FULL_SCALE_DB)
        pulls = [b['pull'] for b in pulled['bands']]
        row.update(analysed_hz=[round(span[0]), round(span[1])], slices=len(slices))
        if len(pulls) < 2:
            row.update(verdict='insufficient_data', why='too few measured bins in the range')
            out.append(row)
            continue
        mean, spread = float(np.mean(pulls)), float(max(pulls) - min(pulls))
        worst = pulled['bands'][int(np.argmax([abs(p - mean) for p in pulls]))]
        centre = ('centred' if abs(mean) <= 0.0625 else
                  'slightly %s' % ('left' if mean > 0 else 'right') if abs(mean) <= 0.19 else
                  'pulled %s' % ('left' if mean > 0 else 'right'))
        focus = 'focused' if spread <= 0.25 else 'loose' if spread <= 0.5 else 'smeared'
        row.update(mean_pull=round(mean, 2), mean_pull_db=round(mean * FULL_SCALE_DB, 1),
                   spread=round(spread, 2), spread_db=round(spread * FULL_SCALE_DB, 1),
                   centre=centre, focus=focus,
                   widest_swing_hz=[round(worst['f_lo']), round(worst['f_hi'])],
                   time_cue_used=any(b['time_cue_used'] for b in pulled['bands']))
        out.append(row)
    return out, time_cue


IMAGING_ADVICE = {
    'smeared': 'heard in more than one place: find which side is hot at the widest swing '
               '(lr-match / stereo-propose for level, imaging for time) and correct that slice '
               'on that side only',
    'loose': 'the image widens across this band: listen for the instrument on EMMA tracks 2-6; '
             'if it sounds wide or doubled, correct the widest-swing slice on the hot side',
    'focused': None,
}


# ------------------------------------------------------------------ height
def passband_overlap(chans, low=None, high=None, min_hz=300.0):
    """Overlaps between driver pairs above min_hz. With --low/--high (the
    channels mounted low and high) an overlap of a low pair into a high pair's
    band is a stage-height finding; without them it is a question."""
    groups, seen = [], set()
    for c in chans:
        if not (c.get('hp_hz') or c.get('lp_hz')) or c['index'] in seen:
            continue
        members = sorted(set(c.get('pair_guess') or [c['index']]))
        seen.update(members)
        groups.append({'channels': members, 'role': c['inferred_role'],
                       'hp': c.get('hp_hz') or 20.0, 'lp': c.get('lp_hz') or 20000.0})
    low, high = set(low or []), set(high or [])
    out = []
    for i, a in enumerate(groups):
        for b in groups[i + 1:]:
            lo, hi = max(a['hp'], b['hp'], min_hz), min(a['lp'], b['lp'])
            if hi <= lo * 1.25:
                continue
            row = {'pairs': [a['channels'], b['channels']], 'roles': [a['role'], b['role']],
                   'overlap_hz': [round(lo), round(hi)], 'octaves': round(math.log2(hi / lo), 1)}
            a_low, b_low = bool(set(a['channels']) & low), bool(set(b['channels']) & low)
            a_high, b_high = bool(set(a['channels']) & high), bool(set(b['channels']) & high)
            if (a_low and b_high) or (b_low and a_high):
                lowpair = a if a_low else b
                highpair = b if a_low else a
                row['verdict'] = 'height_risk'
                row['advice'] = ('the low pair %s plays %d-%d Hz alongside the high pair %s: lower its '
                                 'low-pass towards %d Hz (model it with probe; set it by hand in PC-Tool)'
                                 % (lowpair['channels'], round(lo), round(hi), highpair['channels'],
                                    round(max(highpair['hp'], 300.0))))
            elif low or high:
                row['verdict'] = 'same_height'
            else:
                row['verdict'] = 'question'
                row['advice'] = ('are these pairs mounted at different heights? If so, the low one '
                                 'should stop where the high one starts (re-run with --low/--high)')
            out.append(row)
    return out


# ------------------------------------------------------------------ sub
def sub_stopband(freqs, db, live, floor=None, above_hz=120.0):
    band = capture_audit.passband(freqs, db, 'sub')
    if band is None:
        return {'verdict': 'insufficient_data', 'why': 'no sub passband found'}
    sm = _smooth(freqs, db, 3.0)
    pb = live & (freqs >= max(band[0], 25.0)) & (freqs <= min(band[1], 80.0))
    ref = float(np.median(sm[pb])) if np.count_nonzero(pb) >= 4 else float(np.max(sm[live]))
    sel = live & (freqs >= above_hz) & (freqs <= 500.0)
    if np.count_nonzero(sel) < 4:
        return {'verdict': 'insufficient_data', 'why': 'the capture does not reach %.0f Hz' % above_hz}
    k = int(np.flatnonzero(sel)[np.argmax(sm[sel])])
    rel = float(sm[k] - ref)
    out = {'passband_hz': [round(band[0]), round(band[1])], 'loudest_above_hz': round(float(freqs[k])),
           'level_above_rel_db': round(rel, 1)}
    if floor is not None and np.isfinite(floor[k]) and sm[k] - floor[k] < 10.0:
        out.update(verdict='noise_limited', why='the capture is within 10 dB of the noise floor there')
    elif rel > -20.0:
        out.update(verdict='leaking',
                   advice='the sub plays only %.0f dB down at %.0f Hz, where it can be located: a lower '
                          'or steeper low-pass (probe, then PC-Tool), and check for rattles there'
                          % (-rel, freqs[k]))
    else:
        out['verdict'] = 'clean'
    return out


def sub_harmonics(dist_freqs, harmonics, band=(20.0, 100.0)):
    """Harmonics against Fielder & Benjamin's limits, third-octave by third-octave."""
    centres = [c for c in capture_audit.THIRD_OCT if band[0] <= c <= band[1]]
    rows, worst = [], None
    for c in centres:
        i = int(np.argmin(np.abs(dist_freqs - c)))
        fund = float(harmonics['fundamental'][i])
        row = {'hz': round(float(c), 1), 'fundamental_db': round(fund, 1), 'harmonics_pct': {},
               'over_limit': []}
        for order in sorted(k for k in harmonics if k != 'fundamental'):
            pct = 100.0 * 10.0 ** ((float(harmonics[order][i]) - fund) / 20.0)
            row['harmonics_pct'][order] = round(pct, 2)
            limit = FB_LIMITS_PCT.get(order, FB_HIGHER_PCT)
            if pct > limit:
                row['over_limit'].append({'order': order, 'pct': round(pct, 2), 'limit_pct': limit,
                                          'lands_hz': round(order * float(c))})
                excess = pct / limit
                if worst is None or excess > worst[0]:
                    worst = (excess, order, float(c), pct, limit)
        rows.append(row)
    summary = None
    if worst:
        excess, order, c, pct, limit = worst
        summary = ('H%d reaches %.1f%% at %.0f Hz (limit about %.1f%%), landing at %.0f Hz%s'
                   % (order, pct, c, limit, order * c,
                      ' -- where bass can be located, a reason for a rear sub to be heard'
                      if order * c >= 100 else ''))
    return {'bands': rows, 'worst': summary, 'verdict': 'over_limit' if worst else 'within_limits'}


# ------------------------------------------------------------------ decay
def fazenda_threshold(hz):
    """Audible modal decay (s), log-log interpolated: music thresholds from
    63 Hz up, joined to the 0.9 s test-tone figure at 32 Hz below that."""
    xs, ys = zip(*FAZENDA)
    return float(10.0 ** np.interp(math.log10(hz), np.log10(xs), np.log10(ys)))


def decay_check(ir, fs, bands=DECAY_BANDS):
    """T60 (3x the -20 dB time of the band's Schroeder decay) per third-octave
    against the music thresholds. A band whose decay is no longer than the
    analysis filter's own is not resolvable (and such short decays are far
    under the thresholds anyway)."""
    import decay
    impulse = np.zeros(int(fs))
    impulse[int(0.1 * fs)] = 1.0
    rows = []
    for f0 in bands:
        meas = decay.decay_band(ir, fs, f0, drop=20.0, frac=3.0)
        own = decay.decay_band(impulse, fs, f0, drop=20.0, frac=3.0)
        thr = fazenda_threshold(f0)
        row = {'hz': f0, 'threshold_s': round(thr, 2), 't60_s': None, 'verdict': None}
        if meas['t_ms'] is None:
            row.update(verdict='unreliable', why=meas['reason'])
        else:
            t60 = 3.0 * meas['t_ms'] / 1000.0
            own_t60 = 3.0 * (own['t_ms'] or 0.0) / 1000.0
            row['t60_s'] = round(t60, 2)
            if t60 <= 1.5 * own_t60:
                row['verdict'] = 'not_resolvable'
                row['why'] = ('no longer than the analysis filter\'s own decay (%.2f s): shorter than '
                              'this band can show, so below the threshold' % own_t60)
            else:
                row['verdict'] = 'audible' if t60 > thr else 'inaudible'
        rows.append(row)
    audible = [r['hz'] for r in rows if r['verdict'] == 'audible']
    return {'bands': rows, 'audible_hz': audible,
            'advice': ('ringing above the audibility threshold at %s Hz: a cut on a minimum-phase '
                       'peak there also shortens its decay (check the boost gate first)'
                       % ', '.join(str(h) for h in audible)) if audible else None}


def _load_ir(spec):
    import mdat
    if mdat.is_spec(spec):
        m = mdat.select(spec)
        ir = (m.get('sweep') or {}).get('ir')
        if not ir:
            raise ValueError('%s has no impulse response (sweeps only)' % spec)
        return np.asarray(ir['samples'], dtype=float), float(ir['sample_rate_hz'])
    import decay
    return decay._load_any(spec)


# ------------------------------------------------------------------ report
LISTENING = [
    {'listen': 'tracks 2-6: at each of the five positions, every instrument (bass, guitar, banjo, '
               'vibraphone, triangle) in that one place',
     'if_wrong': 'an instrument off its position, or heard in two places (0 points for it)',
     'section': 'imaging'},
    {'listen': 'track 12: stage distance, width and height',
     'if_wrong': 'a close or narrow stage, or instruments low or moving in height with pitch',
     'section': 'height and imaging focus; the height and distance voicing variants'},
    {'listen': 'tracks 13-16: sub-bass, mid-bass, midrange and high, each clean and even',
     'if_wrong': 'a note or range louder than the rest, boom, harshness',
     'section': 'tone (residual peaks, emma_bands), sub and bass decay'},
    {'listen': 'track 16 at your volume, then about 6 dB louder',
     'if_wrong': 'the balance changes or the system strains', 'section': 'emma-volume'},
    {'listen': 'the silent track', 'if_wrong': 'hum, hiss or pops', 'section': 'noise-check'},
]
SHEET_NOTE = ('score the listening on assets/emma_listening_sheet.html (or copy a judge\'s sheet into '
              'it) and pass its export to finish --heard')


def _side(paths):
    rows, live = [], np.ones_like(GRID, dtype=bool)
    for p in paths:
        f, s, _ph, _c = measure.load_text_export(p)
        rows.append(measure.resample_log(f, s, GRID))
        live &= measure.support_mask(f, GRID)
    return 10.0 * np.log10(sum(10.0 ** (r / 10.0) for r in rows)), live


def finish_cmd(args):
    import mmm
    heard = getattr(args, 'heard', None)
    if not any((args.system, args.left, args.sub, args.ir, args.afpx, heard)):
        raise ValueError('give at least one of --system, --left/--right, --sub, --ir, --afpx or --heard')
    if bool(args.left) != bool(args.right):
        raise ValueError('--left and --right go together')
    sheet = None
    if heard:
        import scoresheet
        sheet = scoresheet.load(heard)          # checked before any capture is read
    floor = mmm._floor(args.floor, GRID) if args.floor else None
    report = {'meta': {k: getattr(args, k, None) for k in ('system', 'left', 'right', 'sub', 'ir', 'afpx',
                                                          'low', 'high', 'floor', 'target', 'heard')},
              'evidence': EVIDENCE, 'summary': [], 'listening_checklist': LISTENING,
              'listening_sheet': SHEET_NOTE}
    if args.system:
        f, s, _ph, _c = measure.load_text_export(args.system)
        db = measure.resample_log(f, s, GRID)
        live = measure.support_mask(f, GRID)
        if floor is not None:
            have = np.isfinite(floor)
            live &= ~have | (db >= np.where(have, floor, -np.inf) + 10.0)
        target = measure.load_target(DEFAULT_TARGET if args.target == 'default' else args.target, GRID)
        if args.voice:
            import pipeline
            target = tunelib.voice_target(GRID, target, **pipeline._parse_voice(args.voice))
        anchor = tunelib.target_anchor_offset(GRID, db, target, confidence=live.astype(float))
        dev = db - (target + anchor)
        peaks, dips = residual_peaks(GRID, dev, live, args.noise_db, max_peaks=args.max_peaks)
        ripple = nbd(GRID, _smooth(GRID, db, 24.0))
        report['tone'] = {'nbd_db': None if ripple is None else round(ripple, 2),
                          'residual_peaks': peaks, 'leave_alone_dips': dips,
                          'emma_bands': tunelib.emma_band_balance(GRID, dev, live),
                          'notes': ['peaks about a two-octave trend after the target is matched; a '
                                    'suggested cut is a starting point for propose/refine with '
                                    '--fit-band, which validate it -- never written from here',
                                    'dips are listed to leave alone unless --cancel-check or the boost '
                                    'gate shows they are fillable']}
        for p in peaks[:3]:
            report['summary'].append('peak %+.1f dB at %d Hz (Q about %s): cut about %.1f dB -- '
                                     'propose/refine --fit-band %d %d'
                                     % (p['height_db'], p['hz'], p['q'], p['suggested_cut']['gain_db'],
                                        p['fit_band_hz'][0], p['fit_band_hz'][1]))
    if args.left:
        ldb, llive = _side(args.left)
        rdb, rlive = _side(args.right)
        live = llive & rlive
        if floor is not None:
            have = np.isfinite(floor)
            live &= ~have | ((np.minimum(ldb, rdb) >= np.where(have, floor, -np.inf) + 10.0))
        lph = rph = None
        if len(args.left) == 1 and len(args.right) == 1:
            lc = measure.load_complex(args.left[0], GRID, require_phase=False)
            rc = measure.load_complex(args.right[0], GRID, require_phase=False)
            if lc['phase_deg'] is not None and rc['phase_deg'] is not None and \
                    measure.shared_timing_problem(lc, rc) is None:
                lph, rph = lc['phase_deg'], rc['phase_deg']
        played = np.zeros_like(GRID, dtype=bool)
        for path in list(args.left) + list(args.right):
            band = capture_audit.load_capture(path)['passband']
            played |= (GRID >= band[0]) & (GRID <= band[1]) if band else live
        bands, time_cue = image_balance(GRID, ldb, rdb, live, lph, rph, played)
        for b in bands:
            advice = IMAGING_ADVICE.get(b.get('focus'))
            if advice:
                b['advice'] = advice
                report['summary'].append('%s band %s (%.0f dB swing at %d-%d Hz): %s'
                                         % (b['instrument'], b['focus'], b['spread_db'],
                                            b['widest_swing_hz'][0], b['widest_swing_hz'][1], advice))
            elif b.get('centre', '').startswith('pulled'):
                report['summary'].append('%s band %s (%.1f dB): a level or time job for imaging / '
                                         'centre_steering' % (b['instrument'], b['centre'], b['mean_pull_db']))
        report['imaging'] = {'bands': bands, 'time_cue': time_cue,
                             'notes': ['pull: +1 is fully left, -1 fully right (16 dB or 1 ms is a full '
                                       'shift); focus is the spread of the band\'s third-octave slices',
                                       'level only: MMM captures carry no time cue -- timed sweeps of each '
                                       'side add it' if not time_cue else
                                       'level and time from the two timed captures']}
    if args.afpx:
        import afpx
        chans = afpx.channels(afpx.decode(args.afpx))
        over = passband_overlap(chans, args.low, args.high)
        report['height'] = {'overlaps': over,
                            'voicing_option': ('A/B a height variant: voice-variants --height-db 1 2 '
                                               '--height-channels <tweeter channels> (Blauert: a band '
                                               'near 8000 Hz reads "above"; weak evidence in cars, so '
                                               'blind A/B only)'),
                            'notes': ['channel pairs come from the tune\'s pair guess: confirm the map']}
        for o in over:
            if o['verdict'] in ('height_risk', 'question'):
                report['summary'].append('pairs %s and %s share %d-%d Hz: %s'
                                         % (o['pairs'][0], o['pairs'][1], o['overlap_hz'][0],
                                            o['overlap_hz'][1], o['advice']))
    if args.sub:
        f, s, _ph, _c = measure.load_text_export(args.sub)
        db = measure.resample_log(f, s, GRID)
        sub = {'stopband': sub_stopband(GRID, db, measure.support_mask(f, GRID), floor)}
        import mdat
        if mdat.is_spec(args.sub):
            m = mdat.select(args.sub)
            if m.get('harmonics') and m.get('noise_floor'):
                sub['harmonics'] = sub_harmonics(m['noise_floor'][0], m['harmonics'])
                sub['harmonics']['note'] = 'at the level of that sweep; distortion grows with level'
        if sub['stopband'].get('verdict') == 'leaking':
            report['summary'].append('sub: ' + sub['stopband']['advice'])
        if sub.get('harmonics', {}).get('worst'):
            report['summary'].append('sub: ' + sub['harmonics']['worst'])
        sub['timing'] = 'sub/midbass timing: mmm-align (MMM) or junction / bass-trials (timed sweeps)'
        report['sub'] = sub
    if args.ir:
        report['bass_decay'] = {}
        for spec in args.ir:
            ir, fs = _load_ir(spec)
            d = decay_check(ir, fs)
            report['bass_decay'][spec] = d
            if d['advice']:
                report['summary'].append('%s: %s' % (spec, d['advice']))
    report['voicing_options'] = [
        'bass and treble to taste: voice-variants + ab-make + prefs (preferred bass spans many dB '
        'between listeners)',
        'listening level: listening-level --capture <full-system capture>',
        'distance (taste, unproven): voice-variants --distance-db -1 -2 --distance-channels <mid and '
        'tweeter channels>',
    ]
    if sheet is not None:
        report['heard'] = scoresheet.explain(sheet[0], sheet[1], report)
        report['summary'] = ['heard: ' + p for p in report['heard']['priorities']] + report['summary']
    if not report['summary']:
        report['summary'].append('nothing above the thresholds in what was given')
    return report
