# trust.py -- one validation evening decides how far to trust the
# simulation-checked MMM tools.
#
# mmm-align, the peak-trace stability map, frames and the interleaved test
# signal were built and checked in simulation (docs/audits/2026-10-29-bloat-
# audit.md, A4). `capture-plan --goal validate` lists one car evening that
# measures each of them a second, independent way:
#
#   mmm-align     its best sub/midbass delay and polarity from four MMM
#                 captures, against `junction` on timed sweeps of the same
#                 junction (+ delay on the midbass equals - delay on the sub)
#   stability     run 1's peak-minus-average map below 250 Hz, against how far
#                 two identical runs actually disagree, band by band
#   frames        the WAV recording's mean, against REW's own average of that
#                 run (same pass, two analysers)
#   test signals  the interleaved signal's left/right level difference from one
#                 pass, against separate Front L and Front R captures
#
# Each comes back trusted, advisory or remove (or not_run / inconclusive).
# One evening is one car: "trusted" is a first real-car confirmation to
# record, not a proof for every car. It reads files and writes nothing.
import json

import numpy as np

import capture_audit
import mmm

GRID = mmm.GRID


def _smooth(db, frac=6.0):
    return capture_audit.smooth_oct(GRID, db, frac)


def _rank(x):
    order = np.argsort(x, kind='mergesort')
    r = np.empty(len(x))
    r[order] = np.arange(len(x))
    for v in np.unique(x):                       # average ties
        r[x == v] = np.mean(r[x == v])
    return r


def spearman(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if len(a) < 3 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return None
    return float(np.corrcoef(_rank(a), _rank(b))[0, 1])


def _report(path, want):
    with open(path, encoding='utf-8-sig') as fh:
        try:
            r = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError('%s is not JSON: %s' % (path, exc))
    if not isinstance(r, dict) or not all(k in r for k in want):
        raise ValueError('%s is not a %s report (missing %s): save it with that command\'s --out'
                         % (path, '/'.join(want), ', '.join(k for k in want if k not in r)))
    return r


# ------------------------------------------------------------------ mmm-align
def align_check(align, junction):
    """mmm-align (A = sub, B = midbass) against junction (lower = sub)."""
    best = align['best']
    dc = junction['delay_consensus'] or {}
    fc = float(dc.get('crossover_hz') or junction['meta']['crossover_hz'])
    period = 1000.0 / fc
    out = {'crossover_hz': fc, 'period_ms': round(period, 2),
           'mmm_align': {'midbass_delay_change_ms': best['delay_change_ms'],
                         'invert_midbass': best['invert_b'], 'verdict': align['verdict']},
           'junction': {'sub_delay_change_ms': dc.get('extra_delay_lower_ms'),
                        'invert': dc.get('invert'), 'confidence': dc.get('confidence')}}
    lo, hi = align['meta']['band_hz']
    if not lo <= fc <= hi:
        out.update(verdict='not_run', why='the junction (%.0f Hz) is outside the band mmm-align '
                                          'searched (%.0f-%.0f Hz): run both on the same junction'
                                          % (fc, lo, hi))
        return out
    if dc.get('extra_delay_lower_ms') is None or dc.get('confidence') == 'low':
        out.update(verdict='not_run', why='the timed sweeps give no confident delay at this junction '
                                          '(junction confidence low): capture them again')
        return out
    reference = -float(dc['extra_delay_lower_ms'])      # the same change, made on the midbass
    error = abs(float(best['delay_change_ms']) - reference)
    same_polarity = bool(best['invert_b']) == bool(dc.get('invert'))
    out.update(midbass_delay_from_sweeps_ms=round(reference, 3), error_ms=round(error, 3),
               error_periods=round(error / period, 3), same_polarity=same_polarity)
    if same_polarity and error <= period / 8:
        out.update(verdict='trusted', why='within an eighth of a period (%.2f ms) of the timed sweeps'
                                          % (period / 8))
    elif same_polarity and error <= period / 4:
        out.update(verdict='advisory', why='within a quarter period: right direction, confirm each '
                                           'candidate with an mmm-compare capture')
    else:
        out.update(verdict='remove', why=('opposite polarity to the timed sweeps' if not same_polarity
                                          else 'more than a quarter period from the timed sweeps'))
    return out


# ------------------------------------------------------------------ stability
def stability_check(average, peak, repeat, band=(20.0, 250.0)):
    """Does the peak-trace map mark the bands that really move between runs?"""
    a, sa = mmm._load(average)
    p, sp = mmm._load(peak)
    b, sb = mmm._load(repeat)
    live = sa & sp & sb
    if np.median((p - a)[live]) < -0.1:
        raise ValueError('--peak reads below --average: are the files swapped?')
    ref = live & (GRID >= 100.0) & (GRID <= 5000.0)
    if np.count_nonzero(ref) < 8:
        raise ValueError('the runs share too little of 100-5000 Hz to level-match them')
    diff = np.abs(_smooth(a) - _smooth(b) - float(np.median((a - b)[ref])))
    w, _gap, _ref = mmm.stability_weights(GRID, np.where(live, a, np.nan), np.where(live, p, np.nan), band)
    rows = []
    for c in capture_audit.THIRD_OCT:
        if c < band[0] or c > band[1]:
            continue
        sel = live & (GRID >= c / 2 ** (1 / 6)) & (GRID < c * 2 ** (1 / 6))
        if np.count_nonzero(sel) < 3:
            continue
        rows.append({'hz': round(float(c), 1), 'weight': round(float(np.mean(w[sel])), 2),
                     'run_to_run_db': round(float(np.mean(diff[sel])), 2)})
    out = {'bands': rows}
    if len(rows) < 6:
        out.update(verdict='not_run', why='fewer than six third-octave bands below 250 Hz in all three files')
        return out
    inst = [1.0 - r['weight'] for r in rows]
    spread = [r['run_to_run_db'] for r in rows]
    rho = spearman(inst, spread)
    moving = [r['run_to_run_db'] for r in rows if r['weight'] <= 0.5]
    steady = [r['run_to_run_db'] for r in rows if r['weight'] >= 0.8]
    out.update(rank_correlation=None if rho is None else round(rho, 2),
               moving_bands_mean_db=round(float(np.mean(moving)), 2) if moving else None,
               stable_bands_mean_db=round(float(np.mean(steady)), 2) if steady else None,
               largest_run_to_run_db=round(max(spread), 2))
    if max(spread) < 0.3 or rho is None:
        out.update(verdict='inconclusive', why='the two runs agree within 0.3 dB everywhere (or the map '
                                               'is flat): nothing here to rank')
    elif rho >= 0.5 and (not moving or not steady or np.mean(moving) >= 1.5 * np.mean(steady)):
        out.update(verdict='trusted', why='the bands the peak trace marks as moving are the ones two '
                                          'runs disagree on (rank correlation %.2f)' % rho)
    elif rho >= 0.2:
        out.update(verdict='advisory', why='a weak match (rank correlation %.2f): use it as a hint, '
                                           'not a weight' % rho)
    else:
        out.update(verdict='remove', why='the peak trace does not predict where two runs disagree '
                                         '(rank correlation %.2f)' % rho)
    return out


# ------------------------------------------------------------------ frames
def _agreement(a, sa, b, sb, lo=50.0, hi=10000.0):
    live = sa & sb
    ref = live & (GRID >= 100.0) & (GRID <= 5000.0)
    if np.count_nonzero(ref) < 8:
        raise ValueError('the two traces share too little of 100-5000 Hz to compare')
    d = _smooth(a) - _smooth(b) - float(np.median((a - b)[ref]))
    sel = live & (GRID >= lo) & (GRID <= hi)
    return float(np.sqrt(np.mean(d[sel] ** 2))), float(np.max(np.abs(d[sel]))), \
        float(GRID[sel][int(np.argmax(np.abs(d[sel])))])


def frames_check(frames_mean, average):
    a, sa = mmm._load(frames_mean)
    b, sb = mmm._load(average)
    rms, worst, at = _agreement(a, sa, b, sb)
    out = {'rms_db': round(rms, 2), 'worst_db': round(worst, 2), 'worst_hz': round(at)}
    if rms <= 0.5 and worst <= 1.5:
        out.update(verdict='trusted', why='the WAV analysis matches REW\'s own average of the same pass')
    elif rms <= 1.0 and worst <= 3.0:
        out.update(verdict='advisory', why='close, with a %.1f dB difference at %d Hz: check the mic '
                                           'calibration file passed to frames' % (worst, at))
    else:
        out.update(verdict='remove', why='the WAV analysis and REW disagree by %.1f dB RMS on the same '
                                         'pass' % rms)
    return out


# ------------------------------------------------------------------ test signals
def signal_check(signal, front_l, front_r):
    rows = [r for r in signal.get('bands', []) if 'ild_db' in r and 100.0 <= r['hz'] <= 10000.0]
    if len(rows) < 6:
        return {'verdict': 'not_run', 'why': 'the signal report has no left/right difference between '
                                             '100 Hz and 10 kHz: analyse an lr-interleaved pass'}
    l, sl = mmm._load(front_l)
    r, sr = mmm._load(front_r)
    ild = _smooth(l) - _smooth(r)
    live = sl & sr
    d = []
    for row in rows:
        k = int(np.argmin(np.abs(GRID - row['hz'])))
        if live[k]:
            d.append(row['ild_db'] - float(ild[k]))
    if len(d) < 6:
        return {'verdict': 'not_run', 'why': 'the Front L/R captures do not cover the signal\'s bands'}
    d = np.asarray(d)
    rms, mean = float(np.sqrt(np.mean(d ** 2))), float(np.mean(d))
    out = {'bands_compared': len(d), 'rms_db': round(rms, 2), 'mean_offset_db': round(mean, 2)}
    if rms <= 1.0:
        out.update(verdict='trusted', why='one interleaved pass gives the same left/right balance as two '
                                          'separate captures')
    elif rms <= 2.0:
        out.update(verdict='advisory', why='within 2 dB RMS of the separate captures')
    else:
        out.update(verdict='remove', why='%.1f dB RMS from the separate captures' % rms)
    if abs(mean) > 1.0:
        out['note'] = ('a %.1f dB constant offset: were Front L and Front R played at the same volume?'
                       % mean)
    return out


# ------------------------------------------------------------------ command
def trust_cmd(args):
    tools = {}
    if bool(args.align) != bool(args.junction):
        raise ValueError('--align and --junction go together')
    if args.align:
        tools['mmm-align'] = align_check(_report(args.align, ('best', 'verdict', 'meta')),
                                         _report(args.junction, ('delay_consensus', 'meta')))
    if args.peak or args.repeat:
        if not (args.average and args.peak and args.repeat):
            raise ValueError('the stability check needs --average, --peak and --repeat')
        tools['stability'] = stability_check(args.average, args.peak, args.repeat)
    if args.frames_mean:
        if not args.average:
            raise ValueError('the frames check needs --average (REW\'s average of the same pass)')
        tools['frames'] = frames_check(args.frames_mean, args.average)
    if args.signal:
        if not (args.front_l and args.front_r):
            raise ValueError('the test-signal check needs --front-l and --front-r')
        tools['test-signals'] = signal_check(_report(args.signal, ('bands', 'meta')),
                                             args.front_l, args.front_r)
    if not tools:
        raise ValueError('give at least one check: --align/--junction, --average/--peak/--repeat, '
                         '--frames-mean/--average, or --signal/--front-l/--front-r')
    for name in ('mmm-align', 'stability', 'frames', 'test-signals'):
        tools.setdefault(name, {'verdict': 'not_run', 'why': 'no inputs given for this check'})
    summary = ['%s: %s -- %s' % (k, v['verdict'], v['why']) for k, v in tools.items()]
    return {'tools': tools, 'summary': summary,
            'notes': ['trusted: keep using it, and drop its "simulation only" label once a second car '
                      'agrees; advisory: keep it as a hint beside the established tool; remove: stop '
                      'relying on it until it is fixed',
                      'one evening is one car and one seat: record the result in docs/case-notes.md',
                      'mmm-align is compared with the timed sweeps, which stay the reference for '
                      'delay and polarity whatever this says']}
