# mmm.py -- decisions a single moving-mic (MMM) capture set can support that
# magnitude averages were assumed unable to make.
#
# An MMM capture is a power average over the head area: P = <|p|^2>. Two
# parts A and B playing together average to
#
#     P_AB = P_A + P_B + 2 Re(C),    C(f) = <a b*>   (the head-area cross-spectrum)
#
# and with B delayed by tau (and its polarity s = +-1, gain g):
#
#     P(tau) = P_A + g^2 P_B + 2 s g Re(C e^{j w tau}).
#
# So the captures the cancel check already makes (A, B, A+B) give Re(C), and
# ONE more capture at a known extra delay tau1 gives Im(C). With C, the
# head-area result of any delay, polarity or gain on either side is predicted
# -- the MMM equivalent of a timed-sweep probe, for users who only have MMM.
#
#   coherence    rho = Re(C)/sqrt(P_A P_B) per band from the A, B, A+B triple:
#                +1 adds coherently wherever the mic went, 0 adds as a power
#                sum (alignment cannot change the tone there), <0 cancels.
#   mmm-align    four captures -> predicted best delay/polarity (and gain) at
#                a junction, as a proposal for the normal confirmed phase plan.
#                Simulated on an image-source cabin: within ~0.1 dB of the best
#                achievable at an 80 Hz sub/midbass junction. Above a few
#                hundred Hz the field decorrelates across the head and the
#                method honestly reports little to gain.
#   stability    REW's peak trace minus its average, from ONE run: below
#                250 Hz it tracks how much a frequency moves across the head
#                (simulated r ~ 0.8; useless above 250 Hz).
#   xo-check     RAW -> XO -> EQ captures of one driver: the crossover and PEQ
#                the DSP actually applied, compared with the .afpx.
#   listening-level, road-noise
#                voicing for the level you listen at (ISO 226) and for road
#                noise -- taste options for a blind A/B, never corrections.
#   prefs        a paired-comparison model over logged blind A/Bs: your
#                preferred voicing, its uncertainty, and the next pair to test.
#
# Everything here reads captures and writes only its JSON report. Delays come
# out in ms (and in samples only at a --dsp-rate you confirm); applying one
# still goes through pipeline.py plan/apply with per-edit confirmation, and a
# phase change is never mixed with EQ.
import json
import math
import os
import re

import numpy as np

import capture_audit
import loudness
import measure
import tunelib

GRID = measure.common_grid(10.0, 24000.0, 96)


def _load(path, freqs=GRID):
    f, s, _p, _c = measure.load_text_export(path)
    return measure.resample_log(f, s, freqs), measure.support_mask(f, freqs)


def _p(db):
    return 10.0 ** (np.asarray(db, dtype=float) / 10.0)


def _db(p):
    return 10.0 * np.log10(np.maximum(p, 1e-30))


def _smooth_power(freqs, p, frac):
    if not frac:
        return p
    return _p(capture_audit.smooth_oct(freqs, _db(p), frac))


def _floor(paths, freqs, label='--floor'):
    """A noise floor from captures: band-limited solos contribute their
    stopbands (moving-mic floor); anything else (an ambient capture) counts
    whole. The highest wins per bin."""
    if not paths:
        return None
    caps = [capture_audit.load_capture(p) for p in paths]
    rows = []
    solos = [c for c in caps if c['passband']]
    if solos:
        fl = capture_audit.stopband_floor(freqs, solos)
        rows.append(fl['floor_db'])
    for c in caps:
        if not c['passband']:
            db = measure.resample_log(c['freqs'], c['db'], freqs)
            rows.append(np.where(measure.support_mask(c['freqs'], freqs), db, np.nan))
    stack = np.vstack(rows)
    with np.errstate(all='ignore'):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            return np.nanmax(stack, axis=0)


# ------------------------------------------------------------------ B1
def summation_coherence(freqs, pa_db, pb_db, pab_db, floor_db=None, centres=None,
                        max_gap_db=10.0, min_snr_db=10.0, band=None):
    """Per fractional-octave band: rho = (P_AB - P_A - P_B) / (2 sqrt(P_A P_B)).

    Reported only where the two parts are within max_gap_db of each other (a
    much quieter part cannot change the sum measurably) and, with a floor,
    every capture stands min_snr_db above it, and inside `band` (the parts'
    shared passband) when given. |rho| > 1.1 cannot happen for one playback
    level and noise-free data: it flags captures that do not share a level,
    or noise. Three noise-only captures read rho = -0.5 exactly (P_AB = P_A =
    P_B), which is why the passband and floor gates matter."""
    centres = capture_audit.THIRD_OCT if centres is None else centres
    la = capture_audit.band_levels(freqs, pa_db, centres)
    lb = capture_audit.band_levels(freqs, pb_db, centres)
    lab = capture_audit.band_levels(freqs, pab_db, centres)
    fl = None if floor_db is None else capture_audit.band_levels(
        freqs, np.where(np.isfinite(floor_db), floor_db, -200.0), centres)
    rows = []
    for i, c in enumerate(centres):
        if not np.isfinite([la[i], lb[i], lab[i]]).all():
            continue
        row = {'hz': round(float(c), 1), 'a_db': round(float(la[i]), 1), 'b_db': round(float(lb[i]), 1),
               'both_db': round(float(lab[i]), 1)}
        reason = None
        if band is not None and not band[0] <= c <= band[1]:
            reason = "outside the parts' shared passband"
        elif abs(la[i] - lb[i]) > max_gap_db:
            reason = 'parts %.0f dB apart' % abs(la[i] - lb[i])
        elif fl is not None and fl[i] > -150 and min(la[i], lb[i], lab[i]) - fl[i] < min_snr_db:
            reason = 'within %.0f dB of the noise floor' % min_snr_db
        if reason:
            row.update(rho=None, verdict='not_reported', why=reason)
        else:
            pa, pb, pab = _p(la[i]), _p(lb[i]), _p(lab[i])
            rho = (pab - pa - pb) / (2.0 * math.sqrt(pa * pb))
            row['rho'] = round(float(rho), 2)
            row['verdict'] = ('inconsistent' if abs(rho) > 1.1 else
                              'coherent' if rho >= 0.7 else
                              'cancelling' if rho <= -0.3 else
                              'power_sum' if abs(rho) < 0.3 else 'partial')
        rows.append(row)
    return rows


COHERENCE_MEANING = {
    'coherent': 'adds coherently across the head area: delay and polarity change the tone here',
    'partial': 'partly coherent: alignment has some tonal effect',
    'power_sum': 'adds as a power sum: alignment cannot change the tone here (it can still '
                 'change imaging); fix tone with EQ or level',
    'cancelling': 'cancels on average across the head area: a dip here is summation, not a '
                  'driver fault -- try polarity/delay before any EQ, and never boost it',
    'inconsistent': 'impossible for one playback level: the captures do not share a level, or '
                    'noise dominates',
}


def shared_passband(paths):
    """Where both parts of a triple play, from their names and levels (None
    when either part's passband cannot be told)."""
    bands = [capture_audit.load_capture(p)['passband'] for p in paths[:2]]
    if any(b is None for b in bands):
        return None
    lo, hi = max(b[0] for b in bands), min(b[1] for b in bands)
    return (lo, hi) if hi > lo else None


def triple_rows(paths, floor_paths=None, min_snr_db=10.0):
    loaded = [_load(p) for p in paths]
    live = np.logical_and.reduce([s for _d, s in loaded])
    dbs = [np.where(live, d, np.nan) for d, _s in loaded]
    floor = _floor(floor_paths, GRID)
    band = shared_passband(paths)
    return summation_coherence(GRID, *dbs, floor_db=floor, min_snr_db=min_snr_db, band=band),         floor, band


def coherence_cmd(args):
    rows, floor, band = triple_rows([args.a, args.b, args.together], args.floor, args.min_snr_db)
    counts = {}
    for r in rows:
        counts[r['verdict']] = counts.get(r['verdict'], 0) + 1
    notes = []
    if floor is None:
        notes.append('no --floor given: low bands may be noise-filled (pass the band-limited '
                     'solos or a moving ambient capture)')
    hdrs = [measure.read_export_header(p) for p in (args.a, args.b, args.together)]
    smooth = {('none' if h['unsmoothed'] else h['smoothing']) for h in hdrs}
    if len(smooth) > 1:
        notes.append('the three captures were exported with different smoothing (%s): rho is '
                     'not trustworthy until they match' % ', '.join(sorted(map(str, smooth))))
    return {'meta': {'a': args.a, 'b': args.b, 'together': args.together, 'floor': args.floor,
                     'shared_passband_hz': None if band is None else [round(x) for x in band]},
            'bands': rows, 'verdict_counts': counts, 'meaning': COHERENCE_MEANING, 'notes': notes}


# ------------------------------------------------------------------ B2
def cross_spectrum(freqs, pa, pb, pab, pab1, tau1_ms, min_sin=0.25):
    """C = <a b*> from P_A, P_B, P_AB and P_AB at B delayed by tau1 (linear
    powers). Returns (C, valid) -- valid is False where sin(w tau1) is too
    small for Im(C) to be read."""
    w1 = 2 * np.pi * freqs * tau1_ms / 1e3
    re0 = (pab - pa - pb) / 2.0
    re1 = (pab1 - pa - pb) / 2.0
    s = np.sin(w1)
    valid = np.abs(s) >= min_sin
    with np.errstate(divide='ignore', invalid='ignore'):
        im = np.where(valid, (re0 * np.cos(w1) - re1) / s, 0.0)
    return _clip_c(re0 + 1j * im, pa, pb), valid


def cross_spectrum_flip(freqs, pp, pm, pp1, pm1, tau1_ms, min_sin=0.25):
    """The same from A+B, A-B (B inverted) and both again with B delayed by
    tau1: no solos, and the flip cancels each path's own bias.
    Returns (C, P_A + P_B, valid)."""
    w1 = 2 * np.pi * freqs * tau1_ms / 1e3
    re0 = (pp - pm) / 4.0
    re1 = (pp1 - pm1) / 4.0
    papb = (pp + pm + pp1 + pm1) / 4.0
    s = np.sin(w1)
    valid = np.abs(s) >= min_sin
    with np.errstate(divide='ignore', invalid='ignore'):
        im = np.where(valid, (re0 * np.cos(w1) - re1) / s, 0.0)
    c = re0 + 1j * im
    mag = np.abs(c)
    lim = papb / 2.0                      # |C| <= sqrt(PA PB) <= (PA + PB)/2
    return np.where(mag > lim, c / np.maximum(mag, 1e-30) * lim, c), papb, valid


def _clip_c(c, pa, pb):
    lim = np.sqrt(np.maximum(pa * pb, 0.0))
    mag = np.abs(c)
    return np.where(mag > lim, c / np.maximum(mag, 1e-30) * lim, c)


def predict_power(freqs, pa, pb, c, delay_ms=0.0, invert=False, gain_db=0.0):
    """Head-area power with B delayed by delay_ms, optionally inverted and
    re-levelled by gain_db (A unchanged)."""
    g = 10.0 ** (gain_db / 20.0)
    s = -1.0 if invert else 1.0
    rot = np.exp(1j * 2 * np.pi * freqs * delay_ms / 1e3)
    return np.maximum(pa + g * g * pb + 2 * s * g * np.real(c * rot), 1e-30)


def alignment_table(freqs, pa, pb, c, band, valid, current_db, delays_ms, gains_db=(0.0,),
                    try_invert=True):
    """Every candidate's predicted band-mean level change against the current
    capture (dB, positive = more summation), and its worst bin."""
    sel = (freqs >= band[0]) & (freqs <= band[1]) & valid
    if np.count_nonzero(sel) < 4:
        raise ValueError('too few usable bins in %.0f-%.0f Hz: choose --tau1-ms near a quarter '
                         'period of the band centre' % band)
    rows = []
    for g in gains_db:
        for inv in ((False, True) if try_invert else (False,)):
            for d in delays_ms:
                p = predict_power(freqs, pa, pb, c, d, inv, g)
                change = _db(p[sel]) - current_db[sel]
                rows.append({'delay_ms': round(float(d), 3), 'invert': inv, 'gain_db': float(g),
                             'mean_change_db': float(np.mean(change)),
                             'worst_bin_change_db': float(np.min(change))})
    return rows, sel


def align4_cmd(args):
    band = tuple(args.band)
    tau1 = float(args.tau1_ms)
    if tau1 <= 0:
        raise ValueError('--tau1-ms must be the positive extra delay added to B for the delayed capture')
    centre = math.sqrt(band[0] * band[1])
    quarter = 1e3 / (4 * centre)
    notes = []
    if not 0.5 * quarter <= tau1 <= 1.5 * quarter:
        notes.append('tau1 %.2f ms is far from a quarter period at the band centre (%.2f ms): '
                     'part of the band cannot be read' % (tau1, quarter))
    flip = args.sum is not None
    paths = ([args.sum, args.diff, args.sum_delayed, args.diff_delayed] if flip else
             [args.a, args.b, args.together, args.together_delayed])
    if any(p is None for p in paths):
        raise ValueError('give either --a --b --together --together-delayed, or --sum --diff '
                         '--sum-delayed --diff-delayed')
    loaded = [_load(p) for p in paths]
    live = np.logical_and.reduce([s for _d, s in loaded])
    powers = [_smooth_power(GRID, _p(d), args.smooth) for d, _s in loaded]
    if flip:
        c, papb, valid = cross_spectrum_flip(GRID, *powers, tau1)
        pa = pb = papb / 2.0          # only P_A + P_B is known: gain trials need the solo form
        current = _db(powers[0])
        if any(g != 0 for g in args.gains_db):
            raise ValueError('gain trials need the solo captures (A and B separately); the flip '
                             'form only knows P_A + P_B')
    else:
        pa, pb, pab, pab1 = powers
        c, valid = cross_spectrum(GRID, pa, pb, pab, pab1, tau1)
        current = _db(pab)
    valid &= live
    span = args.max_delay_ms if args.max_delay_ms else min(10.0, 500.0 / band[0])
    delays = np.arange(-span, span + 1e-9, args.step_ms)
    rows, sel = alignment_table(GRID, pa, pb, c, band, valid, current, delays,
                                args.gains_db, not args.no_invert)
    best = max(rows, key=lambda r: r['mean_change_db'])
    worst = min(rows, key=lambda r: r['mean_change_db'])
    keep = next(r for r in rows if r['delay_ms'] == 0.0 and not r['invert'] and r['gain_db'] == 0.0)
    coh = float(np.median((np.abs(c) / np.sqrt(np.maximum(pa * pb, 1e-30)))[sel]))
    gain = best['mean_change_db'] - keep['mean_change_db']
    need = max(0.5, 2.0 * args.noise_db)
    if gain < need:
        verdict = 'keep_current'
        advice = ('the best candidate gains %.2f dB, below what one re-capture can confirm (%.2f dB): '
                  'keep the current setting' % (gain, need))
    else:
        verdict = 'candidate'
        advice = ('predicted %+.2f dB more summation across %.0f-%.0f Hz: confirm it with one '
                  'capture of the candidate against a repeat of the current setting (pipeline.py '
                  'mmm-compare --repeat ...) before planning it as a phase-only edit'
                  % (gain, band[0], band[1]))
    if coh < 0.5:
        notes.append('head-area coherence %.2f: the parts barely interact here, so alignment is an '
                     'imaging decision more than a tonal one' % coh)

    def show(r):
        d = r['delay_ms']
        out = {'delay_change_ms': d, 'invert_b': r['invert'], 'gain_change_db': r['gain_db'],
               'predicted_mean_change_db': round(r['mean_change_db'] - keep['mean_change_db'], 2),
               'predicted_worst_bin_db': round(r['worst_bin_change_db'], 2),
               'how': ('no delay change' if d == 0 else
                       'add %.3f ms to B (or remove it from A)' % d if d > 0 else
                       'add %.3f ms to A (or remove it from B)' % -d)}
        if args.dsp_rate:
            out['delay_change_samples'] = round(tunelib.ms_to_samples(abs(d), args.dsp_rate))
        return out
    ranked = sorted(rows, key=lambda r: -r['mean_change_db'])[:5]
    return {'meta': {'mode': 'flip' if flip else 'solo', 'files': paths, 'band_hz': list(band),
                     'tau1_ms': tau1, 'usable_bins': int(np.count_nonzero(sel)),
                     'smoothing_oct': (1.0 / args.smooth) if args.smooth else None,
                     'dsp_rate_hz': args.dsp_rate},
            'head_area_coherence': round(coh, 2),
            'swing_db': round(best['mean_change_db'] - worst['mean_change_db'], 2),
            'verdict': verdict, 'advice': advice, 'best': show(best), 'top': [show(r) for r in ranked],
            'notes': notes + ['a PREDICTION from magnitude averages: nothing is written; a delay goes '
                              'through plan/apply only after you see it in ms and samples at your '
                              'confirmed DSP rate, and never in the same plan as EQ',
                              'undo the temporary tau1 delay you set for the delayed capture']}


# ------------------------------------------------------------------ B3
def stability_weights(freqs, avg_db, peak_db, band=(20.0, 250.0), floor_w=0.25):
    """Confidence weights (1 = stable) from peak-minus-average of ONE run.

    Inside `band`, bins whose peak-minus-average sits high relative to the
    rest of the band move with head position. The scale is relative: the
    absolute gap grows with the number of averages. Outside the band the
    weight is 1 (the peak trace does not discriminate there)."""
    gap = capture_audit.smooth_oct(freqs, np.asarray(peak_db) - np.asarray(avg_db), 6.0) \
        if len(freqs) > 8 else np.asarray(peak_db) - np.asarray(avg_db)
    sel = (freqs >= band[0]) & (freqs <= band[1]) & np.isfinite(gap)
    w = np.ones_like(freqs, dtype=float)
    if np.count_nonzero(sel) < 8:
        return w, gap, None
    p25, p90 = np.percentile(gap[sel], [25, 90])
    scale = max(p90 - p25, 0.5)
    w[sel] = np.clip(1.0 - 0.75 * (gap[sel] - p25) / scale, floor_w, 1.0)
    return w, gap, (float(p25), float(p90))


def stability_cmd(args):
    avg, sa = _load(args.average)
    peak, sp = _load(args.peak)
    live = sa & sp
    if np.median((peak - avg)[live]) < -0.1:
        raise ValueError('--peak reads below --average: are the files swapped?')
    band = tuple(args.band)
    w, gap, ref = stability_weights(GRID, np.where(live, avg, np.nan), np.where(live, peak, np.nan), band)
    rows = []
    for c in capture_audit.THIRD_OCT:
        if c < band[0] / 1.12 or c > band[1] * 1.12:
            continue
        sel = live & (GRID >= c / 2 ** (1 / 6)) & (GRID < c * 2 ** (1 / 6))
        if not np.any(sel):
            continue
        wm = float(np.mean(w[sel]))
        rows.append({'hz': round(float(c), 1), 'peak_minus_average_db': round(float(np.mean(gap[sel])), 1),
                     'weight': round(wm, 2),
                     'reads': 'stable' if wm >= 0.8 else 'moves with head position' if wm <= 0.5 else 'mixed'})
    return {'meta': {'average': args.average, 'peak': args.peak, 'band_hz': list(band),
                     'reference_gap_db': None if ref is None else [round(x, 2) for x in ref]},
            'bands': rows,
            'notes': ['relative within this run: high peak-minus-average marks a frequency that '
                      'changes across the head area. EQ a stable modal peak with confidence; leave '
                      'a null that moves alone',
                      'above 250 Hz the peak trace does not track spatial spread (simulation r~0.1-0.2)',
                      'needs peak hold for the whole capture with no decay, and a quiet capture: a '
                      'door thump lifts the peak (run capture-audit)',
                      'pass the peak file as --peak-trace to propose/refine for the same weighting']}


def stability_conf(freqs, avg_path, peak_path, support):
    avg, sa = _load(avg_path, freqs)
    peak, sp = _load(peak_path, freqs)
    w, _gap, _ref = stability_weights(freqs, avg, peak)
    return np.where(support & sa & sp, w, 0.0)


# ------------------------------------------------------------------ B4
XO_SLOPES = {'LR': (12, 24, 36, 48), 'BW': (6, 12, 18, 24, 30, 36, 42, 48)}


def _section_db(freqs, kind, family, slope, hz, fs):
    return 20 * np.log10(np.maximum(np.abs(tunelib.crossover_H(freqs, kind, family, slope, hz, fs)), 1e-12))


def fit_crossover(freqs, transfer_db, kind, stated_hz, fs, live, search_oct=1.0):
    """Best corner per (family, slope) for one measured crossover section,
    best first. transfer_db is XO minus RAW, level-aligned in the passband;
    only bins the model puts above -30 dB are compared (deeper is noise)."""
    sel_base = live & np.isfinite(transfer_db)
    grid = stated_hz * 2.0 ** (np.arange(-24 * search_oct, 24 * search_oct + 1) / 24.0)
    out = []
    for family, slopes in XO_SLOPES.items():
        for slope in slopes:
            best = None
            for hz in grid:
                if not 0 < hz < fs / 2:
                    continue
                model = _section_db(freqs, kind, family, slope, hz, fs)
                sel = sel_base & (model > -30.0)
                if np.count_nonzero(sel) < 8:
                    continue
                rms = float(np.sqrt(np.mean((transfer_db[sel] - model[sel]) ** 2)))
                if best is None or rms < best['rms_db']:
                    best = {'family': family, 'slope_db_oct': slope, 'hz': float(hz), 'rms_db': rms}
            if best:
                out.append(best)
    return sorted(out, key=lambda r: r['rms_db'])


def minus6_hz(kind, family, slope, hz, fs):
    """Where a section is 6 dB down: comparable across families (a
    Butterworth corner is its -3 dB point, a Linkwitz-Riley corner -6 dB)."""
    f = hz * 2.0 ** (np.arange(-480, 481) / 240.0)
    f = f[f < fs / 2]
    db = _section_db(f, kind, family, int(slope), hz, fs)
    return float(f[int(np.argmin(np.abs(db + 6.0)))])


def _stated_section(text, what):
    try:
        hz, slope = (float(x) for x in text.split(','))
    except ValueError:
        raise ValueError('--%s takes HZ,SLOPE_DB_OCT (e.g. 270,24), got %r' % (what, text))
    return hz, slope


def _channel_from_args(args):
    """The channel's stated filters: from the .afpx, or --hp/--lp/--peq for a
    DSP this skill cannot read."""
    if args.afpx:
        import afpx
        chans = afpx.channels(afpx.decode(args.afpx))
        if args.channel is None or not 0 <= args.channel < len(chans):
            raise ValueError('--channel must be one of 0-%d for %s' % (len(chans) - 1, args.afpx))
        return chans[args.channel]
    if not (args.hp or args.lp):
        raise ValueError('give --afpx with --channel, or the stated crossover as --hp/--lp HZ,SLOPE')
    ch = {'hp_hz': None, 'lp_hz': None, 'hp_slope_db_oct': None, 'lp_slope_db_oct': None,
          'hp_char_idx': None, 'lp_char_idx': None, 'shelves': [], 'peqs': []}
    if args.hp:
        ch['hp_hz'], ch['hp_slope_db_oct'] = _stated_section(args.hp, 'hp')
    if args.lp:
        ch['lp_hz'], ch['lp_slope_db_oct'] = _stated_section(args.lp, 'lp')
    for band in args.peq or []:
        try:
            ch['peqs'].append(tuple(float(x) for x in band.split(',')))
        except ValueError:
            raise ValueError('--peq takes F,Q,G, got %r' % band)
    return ch


def xo_check_cmd(args):
    ch = _channel_from_args(args)
    fs = float(args.dsp_rate)
    freqs = measure.common_grid(15.0, min(20000.0, 0.45 * fs), 48)
    raw, sr = _load(args.raw, freqs)
    xo, sx = _load(args.xo, freqs)
    live = sr & sx
    transfer = xo - raw
    pass_lo = ch['hp_hz'] or 20.0
    pass_hi = ch['lp_hz'] or 20000.0
    interior = live & (freqs >= pass_lo * 2 ** 0.75) & (freqs <= pass_hi / 2 ** 0.75)
    notes = []
    if np.count_nonzero(interior) < 8:
        interior = live & (freqs >= pass_lo) & (freqs <= pass_hi)
        notes.append('narrow passband: the level offset was taken across the whole passband')
    offset = float(np.median(transfer[interior]))
    transfer = transfer - offset
    raw_peak = float(np.max(capture_audit.smooth_oct(freqs, raw)[live]))
    xo_ref = float(np.median(capture_audit.smooth_oct(freqs, xo)[interior]))
    # Bins the XO capture holds above its noise: in-car stopbands fill with
    # movement noise, which would read as "no attenuation".
    trusted = live & (raw >= raw_peak - 40.0) & (capture_audit.smooth_oct(freqs, xo) >= xo_ref - 30.0)
    floor = _floor(getattr(args, 'floor', None), freqs)
    if floor is not None:
        quiet = np.isfinite(floor)
        trusted &= ~quiet | (capture_audit.smooth_oct(freqs, xo) >= np.where(quiet, floor, -np.inf) + 10.0)
    else:
        notes.append("no --floor given: where movement noise fills the XO capture's stopband the "
                     "fit can misread a corner (pass the session's band-limited solos)")
    sections = []
    for kind, hz, slope, idx in (('hp', ch['hp_hz'], ch.get('hp_slope_db_oct'), ch.get('hp_char_idx')),
                                 ('lp', ch['lp_hz'], ch.get('lp_slope_db_oct'), ch.get('lp_char_idx'))):
        if not hz:
            continue
        side = trusted & ((freqs <= math.sqrt(pass_lo * pass_hi)) if kind == 'hp'
                          else (freqs >= math.sqrt(pass_lo * pass_hi)))
        fits = fit_crossover(freqs, transfer, kind, hz, fs, side) if np.count_nonzero(side) >= 12 else []
        row = {'section': kind, 'stated_hz': hz, 'stated_slope_db_oct': slope,
               'pc_tool_characteristic_index': idx}
        if not fits:
            row.update(verdict='noise_limited', why='too few bins above the noise to fit')
            sections.append(row)
            continue
        fit = fits[0]
        family = 'LR' if slope and int(slope) % 12 == 0 else 'BW'
        stated_db = _section_db(freqs, kind, family, int(slope), hz, fs) if slope else None
        same_slope = [r for r in fits if slope and r['slope_db_oct'] == int(slope)]
        other_family = [r for r in fits if r['slope_db_oct'] == fit['slope_db_oct']
                        and r['family'] != fit['family']]
        m6 = minus6_hz(kind, fit['family'], fit['slope_db_oct'], fit['hz'], fs)
        s6 = minus6_hz(kind, family, slope, hz, fs) if slope else hz
        err_oct = math.log2(m6 / s6)
        row.update(measured={'family': fit['family'], 'slope_db_oct': fit['slope_db_oct'],
                             'hz': round(fit['hz'], 1), 'minus_6db_hz': round(m6, 1),
                             'rms_error_db': round(fit['rms_db'], 2)},
                   stated_minus_6db_hz=round(s6, 1), corner_error_oct=round(err_oct, 3))
        transition = side & (stated_db > -12.0) & (stated_db < -3.0) if stated_db is not None else None
        if transition is not None and np.count_nonzero(transition) >= 4 and                 float(np.median(transfer[transition])) > -1.0:
            row['verdict'] = 'not_applied'
            row['why'] = ('no attenuation in the band where the stated filter is already 3-12 dB '
                          'down: the section is off, bypassed, or the captures were swapped')
        elif fit['rms_db'] > 2.0:
            row['verdict'] = 'shape_unclear'
        elif abs(err_oct) > 1.0 / 6.0 + 1.0 / 48.0:      # 1/6 octave plus the fit grid
            row['verdict'] = 'corner_differs'
        elif same_slope and fit['slope_db_oct'] != int(slope) and                 same_slope[0]['rms_db'] - fit['rms_db'] > 0.5:
            row['verdict'] = 'slope_differs'
        else:
            row['verdict'] = 'matches'
        if other_family and other_family[0]['rms_db'] - fit['rms_db'] < 0.3:
            row['family_note'] = ('Linkwitz-Riley and Butterworth fit about equally well here: the '
                                  'family is not identified by this capture')
        sections.append(row)
    out = {'meta': {'afpx': args.afpx, 'channel': args.channel, 'raw': args.raw, 'xo': args.xo,
                    'stated': {k: ch[k] for k in ('hp_hz', 'hp_slope_db_oct', 'lp_hz', 'lp_slope_db_oct')},
                    'dsp_rate_hz': fs, 'passband_level_change_db': round(offset, 2)},
           'crossover': sections, 'notes': notes + [
               'XO minus RAW cancels the cabin only when both captures followed the same seat, path '
               'and playback level; the passband offset above is removed before fitting',
               'this reads what the DSP applied; it never writes a crossover. If a section '
               'differs, set it by hand in PC-Tool']}
    if args.eq:
        eq, se = _load(args.eq, freqs)
        live_eq = live & se
        bands = [tuple(b) for b in ch['peqs']]
        pred = tunelib.cascade_db(freqs, bands, fs=fs)
        for kind, F, Q, G in ch.get('shelves') or []:
            pred = pred + (tunelib.low_shelf_db(freqs, F, Q, G, fs=fs) if 'low' in kind.lower()
                           else tunelib.high_shelf_db(freqs, F, Q, G, fs=fs))
        meas = eq - xo
        quiet = live_eq & (np.abs(pred) < 0.2) & trusted
        meas_off = float(np.median(meas[quiet])) if np.count_nonzero(quiet) >= 8 else float(np.median(meas[live_eq]))
        meas = tunelib.erb_smooth(freqs, meas - meas_off)
        acts = live_eq & trusted & (np.abs(pred) >= 0.5)
        if np.count_nonzero(acts) < 8:
            out['eq'] = {'verdict': 'nothing_to_check', 'why': 'the stated PEQ bank changes less than 0.5 dB'}
        else:
            resid = float(np.sqrt(np.mean((meas[acts] - pred[acts]) ** 2)))
            moved = float(np.sqrt(np.mean(meas[acts] ** 2)))
            stated = float(np.sqrt(np.mean(pred[acts] ** 2)))
            tol = max(1.0, 2.0 * args.noise_db)
            verdict = ('not_applied' if moved < 0.35 * stated else
                       'matches' if resid <= tol else 'differs')
            out['eq'] = {'eq_capture': args.eq, 'stated_rms_change_db': round(stated, 2),
                         'measured_rms_change_db': round(moved, 2),
                         'residual_rms_db': round(resid, 2), 'tolerance_db': round(tol, 2),
                         'verdict': verdict,
                         'advice': {'matches': 'the DSP applied the PEQ bank the file states',
                                    'differs': 'what changed is not what the file states: check the '
                                               'loaded setup, the channel, and that the captures '
                                               'followed the same path',
                                    'not_applied': 'the EQ capture shows almost none of the stated '
                                                   'change: was the EQ bypassed or another setup '
                                                   'loaded?'}[verdict]}
    return out


# ------------------------------------------------------------------ C1
def listening_phon(capture_path, offset_db=0.0):
    """(phon estimate, how): the capture's C-weighted level from its header,
    plus the listening-volume offset. A broadband level stands in for loudness
    level -- an approximation, said so in the report."""
    lv = measure.read_export_header(capture_path)['rew']['levels']
    for key, what in (('dbc', 'dB C'), ('unw_22_22k_db', 'dB 22-22k unweighted'), ('dba', 'dB A')):
        if lv.get(key) is not None:
            return lv[key] + offset_db, 'capture %.1f %s %+.1f dB volume offset' % (lv[key], what, offset_db)
    raise ValueError('%s carries no calibrated level note (REW RTA captures do): give '
                     '--listening-db instead' % capture_path)


def shelf_for(freqs, comp_db, fit_band=(30.0, 300.0), hz_choices=(80.0, 100.0, 125.0, 160.0),
              q=0.7, cap_db=6.0):
    """The low shelf (F, gain) that best matches a compensation curve over fit_band."""
    sel = (freqs >= fit_band[0]) & (freqs <= fit_band[1])
    best = None
    for hz in hz_choices:
        unit = tunelib.low_shelf_db(freqs, hz, q, 1.0)
        g = float(np.dot(unit[sel], comp_db[sel]) / max(np.dot(unit[sel], unit[sel]), 1e-9))
        g = float(np.clip(round(g * 4) / 4, -cap_db, cap_db))
        err = float(np.sqrt(np.mean((unit[sel] * g - comp_db[sel]) ** 2)))
        if best is None or err < best['fit_rms_db']:
            best = {'hz': hz, 'q': q, 'gain_db': g, 'fit_rms_db': round(err, 2)}
    return best


def listening_level_cmd(args):
    if args.listening_db is not None:
        phon, how = float(args.listening_db), 'stated listening level %.1f dB' % args.listening_db
    elif args.capture:
        phon, how = listening_phon(args.capture, args.volume_offset_db)
    else:
        raise ValueError('give --capture (with --volume-offset-db if you listen at another volume) '
                         'or --listening-db')
    ref = float(args.reference_phon)
    freqs = measure.common_grid(20.0, 12500.0, 24)
    comp = loudness.compensation_db(freqs, phon, ref)
    notes = []
    for p, name in ((phon, 'listening'), (ref, 'reference')):
        if not loudness.in_valid_range(p):
            notes.append('%s level %.0f phon is outside ISO 226\'s 20-90 phon range: extrapolated'
                         % (name, p))
    shelf = shelf_for(freqs, comp, cap_db=args.max_db)
    rows = [{'hz': round(float(c), 1), 'compensation_db': round(float(x), 1)}
            for c, x in zip(capture_audit.THIRD_OCT, loudness.compensation_db(capture_audit.THIRD_OCT, phon, ref))
            if c <= 12500]
    out = {'meta': {'listening_phon': round(phon, 1), 'how': how, 'reference_phon': ref,
                    'model': 'ISO 226:2003 equal-loudness contours, relative to 1 kHz'},
           'compensation': rows,
           'voicing_option': {'low_shelf': shelf,
                              'half_strength_db': round(shelf['gain_db'] / 2 * 4) / 4,
                              'propose_voice': 'bass=%g' % shelf['gain_db'],
                              'voice_variants': '--bass-db %g %g --bass-hz %g' % (
                                  round(shelf['gain_db'] / 2 * 4) / 4, shelf['gain_db'], shelf['hz'])},
           'emma_plus_6db': {'bass_shift_db': round(float(np.mean(
               loudness.compensation_db([40.0, 63.0, 100.0], phon + 6.0, phon))), 1),
               'meaning': 'how much heavier the bass sounds when the same tune plays 6 dB louder '
                          '(negative = the bass gains relative to 1 kHz)'},
           'notes': notes + [
               'a model of an average listener: offer the full and half-strength shelves as blind, '
               'level-matched A/B variants (voice-variants, ab-make) -- your ears decide',
               'reference %.0f phon is the level the target is assumed voiced at; change it with '
               '--reference-phon' % ref,
               'a broadband dB C level stands in for loudness level (phon): treat the result as '
               'about +-2 dB']}
    if args.capture:
        f, s, _p, _c = measure.load_text_export(args.capture)
        lows = capture_audit.band_levels(f, s + args.volume_offset_db, capture_audit.THIRD_OCT[:8])
        thr = loudness.threshold_db(capture_audit.THIRD_OCT[:8])
        out['below_threshold_hz'] = [round(float(c), 1) for c, x, t in
                                     zip(capture_audit.THIRD_OCT[:8], lows, thr) if np.isfinite(x) and x < t]
        if out['below_threshold_hz']:
            out['notes'].append('at this level the %s Hz third-octaves of the capture are below the '
                                'hearing threshold: bass decisions there are inaudible at this volume'
                                % '/'.join('%g' % x for x in out['below_threshold_hz']))
    return out


# ------------------------------------------------------------------ C2
def masking_loss_db(margin_db):
    """Approximate loudness lost by music `margin_db` above masking noise: the
    noise's share of the band power. 0 dB margin -> 3 dB, -10 dB -> 10.4 dB.
    A simplification of partial loudness, used only to rank bands."""
    return 10.0 * np.log10(1.0 + 10.0 ** (-np.asarray(margin_db, dtype=float) / 10.0))


def road_noise_cmd(args):
    fn, sn, _p, _c = measure.load_text_export(args.noise)
    fm, sm, _p, _c = measure.load_text_export(args.music)
    centres = capture_audit.THIRD_OCT[capture_audit.THIRD_OCT <= 10000]
    noise = capture_audit.band_levels(fn, sn, centres)
    music = capture_audit.band_levels(fm, sm + args.listening_offset_db, centres)
    margin = music - noise
    loss = np.where(np.isfinite(margin), masking_loss_db(margin), 0.0)
    loss = np.minimum(loss, 6.0)
    freqs = measure.common_grid(20.0, 10000.0, 24)
    loss_f = np.interp(np.log10(freqs), np.log10(centres), loss)
    lo_shelf = shelf_for(freqs, loss_f, fit_band=(25.0, 400.0), hz_choices=(100.0, 150.0, 200.0, 300.0),
                         cap_db=args.max_db)
    rows = [{'hz': round(float(c), 1), 'music_db': None if not np.isfinite(m) else round(float(m), 1),
             'road_noise_db': None if not np.isfinite(n) else round(float(n), 1),
             'margin_db': None if not np.isfinite(g) else round(float(g), 1),
             'masking_loss_db': round(float(x), 1)}
            for c, m, n, g, x in zip(centres, music, noise, margin, loss)]
    masked = [r['hz'] for r in rows if r['margin_db'] is not None and r['margin_db'] < 6.0]
    hdr = measure.read_export_header(args.noise)['rew']
    return {'meta': {'noise': args.noise, 'music': args.music,
                     'listening_offset_db': args.listening_offset_db,
                     'noise_dba': hdr['levels'].get('dba'),
                     'model': 'band power share (approximate partial loudness)'},
            'bands': rows, 'masked_bands_hz': masked,
            'driving_variant': {'low_shelf': lo_shelf,
                                'voice_variants': '--bass-db %g --bass-hz %g' % (lo_shelf['gain_db'], lo_shelf['hz'])},
            'notes': [
                'voicing, not correction: write it as a separate variant file for a second preset '
                '(voice-variants --confirm), never into the tune you voiced parked',
                'choose between the parked and driving presets by blind A/B ON THE ROAD, switched '
                'by a passenger or the DSP remote at a stop -- never by the driver while moving',
                'the road-noise capture must be made by a passenger holding the mic, system off, '
                'at your usual cruising speed and road surface',
                'levels above the hearing-safety limits are not a goal: this rebalances the bass '
                'the noise masks, it does not make the system louder overall']}


# ------------------------------------------------------------------ C3
KNOBS = ('bass', 'treble', 'presence')
_VARIANT_RE = re.compile(r'(bass|treble|presence)([+-]\d+(?:\.\d+)?)dB', re.I)


def knobs_for(path, manifest_cache=None, manual=None, base=None):
    """Voicing knob vector of a tune file: from a manual mapping, the
    voice_variants.json manifest beside it, its variant file name, or zero for
    the base tune. None if unknown."""
    norm = os.path.normcase(os.path.abspath(path))
    for key, vec in (manual or {}).items():
        if os.path.normcase(os.path.abspath(key)) == norm:
            return vec
    if base and os.path.normcase(os.path.abspath(base)) == norm:
        return {k: 0.0 for k in KNOBS}
    man = os.path.join(os.path.dirname(path), 'voice_variants.json')
    if os.path.isfile(man):
        cache = manifest_cache if manifest_cache is not None else {}
        if man not in cache:
            with open(man, encoding='utf-8') as fh:
                cache[man] = json.load(fh)
        for row in cache[man].get('variants', []):
            if os.path.normcase(os.path.abspath(row.get('file', ''))) == norm:
                return {k: float(row.get('knobs', {}).get(k, 0.0)) for k in KNOBS}
    m = _VARIANT_RE.search(os.path.basename(path))
    if m:
        vec = {k: 0.0 for k in KNOBS}
        vec[m.group(1).lower()] = float(m.group(2))
        return vec
    return None


def _trials(logs, manual, base):
    trials, skipped = [], []
    cache = {}
    for log_path in logs:
        with open(log_path, encoding='utf-8') as fh:
            entries = json.load(fh)
        for e in entries:
            src = e.get('sources') or {}
            reveal = e.get('reveal') or {}
            counts = e.get('counts') or {}
            if not ('A' in src and 'B' in src):
                skipped.append('entry without sources')
                continue
            ka, kb = (knobs_for(src[x], cache, manual, base) for x in ('A', 'B'))
            if ka is None or kb is None:
                skipped.append('%s vs %s: knob values unknown' % (os.path.basename(src['A']),
                                                                   os.path.basename(src['B'])))
                continue
            wins = {'A': 0, 'B': 0}
            for lab, n in counts.items():
                if lab in reveal:
                    wins[reveal[lab]] += int(n)
            if wins['A'] + wins['B'] == 0:
                continue
            trials.append((ka, kb, wins['A'], wins['B']))
    return trials, skipped


def fit_preferences(trials, knobs=KNOBS, prior_sd=1.0, n_draws=4000, seed=0):
    """Bradley-Terry with a concave quadratic utility per knob:
    u(x) = sum_k b_k x_k - c_k x_k^2,  P(A preferred) = logistic(u(A) - u(B)).
    MAP fit with Gaussian priors (b ~ N(0, prior_sd), c ~ N(0.15, 0.15),
    c >= 0.02), then a Laplace approximation for the uncertainty of each
    knob's preferred value b/(2c)."""
    from scipy import optimize
    active = [k for k in knobs if any(t[0][k] != t[1][k] for t in trials)]
    if not active:
        return None
    X = []
    for ka, kb, na, nb in trials:
        lin = [ka[k] - kb[k] for k in active]
        quad = [-(ka[k] ** 2 - kb[k] ** 2) for k in active]
        X.append((lin + quad, na, nb))
    m = len(active)
    mu = np.array([0.0] * m + [0.15] * m)
    sd = np.array([prior_sd] * m + [0.15] * m)

    def nlp(theta):
        total = np.sum(((theta - mu) / sd) ** 2) / 2.0
        for x, na, nb in X:
            z = float(np.dot(theta, x))
            total += na * np.logaddexp(0.0, -z) + nb * np.logaddexp(0.0, z)
        return total

    bounds = [(None, None)] * m + [(0.02, None)] * m
    res = optimize.minimize(nlp, mu, method='L-BFGS-B', bounds=bounds)
    theta = res.x
    H = np.diag(1.0 / sd ** 2)
    for x, na, nb in X:
        x = np.asarray(x)
        pz = 1.0 / (1.0 + math.exp(-float(np.dot(theta, x))))
        H += (na + nb) * pz * (1 - pz) * np.outer(x, x)
    cov = np.linalg.inv(H)
    rng = np.random.default_rng(seed)
    draws = rng.multivariate_normal(theta, cov, n_draws)
    out = {}
    for i, k in enumerate(active):
        b, c = draws[:, i], np.maximum(draws[:, m + i], 0.02)
        opt = np.clip(b / (2 * c), -6.0, 6.0)
        lo, med, hi = np.percentile(opt, [10, 50, 90])
        tested = sorted({t[0][k] for t in trials} | {t[1][k] for t in trials})
        out[k] = {'preferred_db': round(float(theta[i] / (2 * max(theta[m + i], 0.02))), 2),
                  'interval_80_db': [round(float(lo), 2), round(float(hi), 2)],
                  'median_db': round(float(med), 2), 'tested_db': tested}
    return out


def prefs_cmd(args):
    manual = {}
    for item in args.knobs or []:
        path, _, spec = item.partition('=')
        vec = {k: 0.0 for k in KNOBS}
        for part in filter(None, spec.split(',')):
            k, _, v = part.partition(':')
            if k.strip().lower() not in KNOBS:
                raise ValueError('--knobs knob must be one of %s (got %r)' % (', '.join(KNOBS), k))
            vec[k.strip().lower()] = float(v)
        manual[path] = vec
    trials, skipped = _trials(args.log, manual, args.base)
    if not trials:
        raise ValueError('no logged A/B has known knob values (%s). Run voice-variants, ab-make and '
                         'ab-result first, or map files with --knobs PATH=bass:1,treble:0'
                         % ('; '.join(skipped[:3]) or 'empty log'))
    fit = fit_preferences(trials)
    if fit is None:
        raise ValueError('every logged pair has the same knob values: nothing to learn from')
    decided = sum(t[2] + t[3] for t in trials)
    widest = max(fit, key=lambda k: fit[k]['interval_80_db'][1] - fit[k]['interval_80_db'][0])
    centre = fit[widest]['median_db']
    half = (fit[widest]['interval_80_db'][1] - fit[widest]['interval_80_db'][0]) / 2.0
    step = max(0.5, round(min(half, 3.0) * 4) / 4)
    pair = [round((centre - step) * 4) / 4, round((centre + step) * 4) / 4]
    return {'meta': {'logs': args.log, 'trials': len(trials), 'decided_choices': decided,
                     'skipped': skipped},
            'preferences': fit,
            'next_test': {'knob': widest, 'variants_db': pair,
                          'voice_variants': '--%s-db %g %g' % (widest, pair[0], pair[1]),
                          'why': 'the %s preference is the least certain (80%% interval %s dB)'
                                 % (widest, fit[widest]['interval_80_db'])},
            'notes': ['a model of your blind choices: preferred values outside the range you tested '
                      'are extrapolations -- test them before trusting them',
                      'fewer than about 20 decided choices give wide intervals; keep testing'
                      if decided < 20 else 'feed the preferred values into --voice on propose/refine '
                                           'as a taste layer on the target']}
