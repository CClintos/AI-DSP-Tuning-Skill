"""Connect measured evidence to correction choices and measured listening trials."""
import json
import os

import numpy as np

import measure
import tunelib


def load_limits(path, freqs):
    with open(path, encoding='utf-8-sig') as fh:
        report = json.load(fh)
    if not isinstance(report, dict) or type(report.get('version')) is not int or report.get('version') != 1 or not isinstance(report.get('evidence'), dict):
        raise ValueError('--limits requires a version-1 quality-check report')
    ceiling = np.full(len(freqs), 3.0)
    blocked = []
    evidence = report['evidence']
    for step in evidence.get('compression', {}).get('steps', []):
        for row in step.get('bands', []):
            if row.get('status') == 'compression':
                blocked.append({'band_hz': row['band_hz'], 'reason': 'measured compression'})
    for row in evidence.get('distortion', {}).get('comparison', []):
        if row.get('status') == 'harmonic_regression':
            blocked.append({'band_hz': row['band_hz'], 'reason': 'absolute harmonics rose at matched fundamental level'})
    for row in blocked:
        lo, hi = map(float, row['band_hz'])
        if not np.isfinite([lo, hi]).all() or not 0 < lo < hi:
            raise ValueError('invalid measured limit band')
        # Guard filter skirts too: capacity is restricted throughout each band.
        ceiling[(freqs >= lo) & (freqs <= hi)] = 0.0
    return ceiling, blocked


def fitting_evidence(args, freqs, sess):
    kw, report = {}, {'limits': [], 'partner': None}
    if getattr(args, 'limits', None):
        cap, blocked = load_limits(args.limits, freqs)
        kw['boost_ceiling_db'] = cap
        report['limits'] = blocked
        report['limits_file'] = os.path.abspath(args.limits)
        sess['notes'].append('measured limits apply to ADDITIONAL gain through this capture preset; driver, routing and playback level must match the supplied evidence')
    if getattr(args, 'partner', None):
        axis, db, _p, _c = measure.load_text_export(args.partner)
        partner_support = measure.support_mask(axis, freqs)
        if np.any(sess['support'] & ~partner_support):
            raise ValueError('--partner must cover the measurement range; export both sides over the same range')
        other = measure.resample_log(axis, db, freqs) - sess['target_db'] - sess['anchor']
        own = sess['dev_db']
        # Only close target-supported excess. Neither fill the weak side to
        # match an excess nor copy a cancellation dip onto a healthy side.
        desired = np.where(own > 0, np.minimum(own, np.maximum(other, 0)), own)
        kw.update(partner_target_db=desired, partner_weight=1.0)
        report['partner'] = os.path.abspath(args.partner)
        report['partner_db'] = other
    return kw, report


def enforce_ceiling(freqs, bands, ceiling):
    kept = list(bands)
    rejected = []
    if ceiling is None:
        return kept, rejected
    while np.any(tunelib.cascade_db(freqs, kept) > ceiling + 0.1):
        indices = [i for i, b in enumerate(kept) if b[2] > 0]
        if not indices:
            break
        excess = tunelib.cascade_db(freqs, kept) - ceiling
        idx = max(indices, key=lambda i: float(np.max(np.where(excess > 0.1, tunelib.cascade_db(freqs, [kept[i]]), 0))))
        rejected.append(kept.pop(idx))
    return kept, rejected


def partner_guard(freqs, own, other, transfer, support):
    sel = np.asarray(support, bool) & (freqs >= 700) & (freqs <= 5000)
    if np.count_nonzero(sel) < 8:
        return {'status': 'unknown'}
    before = tunelib.masked_erb_smooth(freqs, own - other, sel)[sel]
    after = tunelib.masked_erb_smooth(freqs, own + transfer - other, sel)[sel]
    b, a = float(np.sqrt(np.mean(before ** 2))), float(np.sqrt(np.mean(after ** 2)))
    return {'before_mismatch_db': round(b, 3), 'after_mismatch_db': round(a, 3),
            'status': 'regressed' if a > b + 0.25 else 'within_margin'}


def measured_voice_match(args):
    f = measure.common_grid(20, 20000, 96)
    axis, db, _p, _c = measure.load_text_export(args.baseline)
    baseline = measure.resample_log(axis, db, f)
    bs = measure.support_mask(axis, f)
    rows = []
    labels = set()
    for entry in args.candidates:
        label, sep, path = entry.partition('=')
        if not sep or not label or not path or label in labels:
            raise ValueError('--candidates requires unique LABEL=PATH entries')
        labels.add(label)
        axis, db, _p, _c = measure.load_text_export(path)
        live = bs & measure.support_mask(axis, f)
        band = (40, 16000)
        required = (f >= band[0]) & (f <= band[1])
        if np.any(required & ~live):
            raise ValueError('measured loudness matching needs common 40 Hz-16 kHz coverage')
        candidate = measure.resample_log(axis, db, f)
        change = tunelib.loudness_change_db(f, baseline, candidate, band=band)
        rows.append({'label': label, 'file': path, 'measured_loudness_change_db': round(change, 3),
                     'louder': 'candidate' if change >= 0 else 'baseline',
                     'attenuate_louder_db': round(-abs(change), 3)})
    return {'baseline': args.baseline, 'variants': rows,
            'method': 'audibility-weighted energy estimate from actual system captures',
            'notes': ['Capture the same broadband test signal with unchanged source gain and mic method.',
                      'Use the measured change with ab-make --loudness-db, then verify the listening match.',
                      'This estimates a level match; only blind listening establishes preference.']}


def bass_trials(args):
    f = measure.common_grid(20, 20000, 96)
    files = [args.sub, args.front, args.together]
    loaded = [measure.load_complex(p, f, require_phase=(i < 2)) for i, p in enumerate(files)]
    for item in loaded[:2]:
        if item['header']['timing_reference'] is not True:
            raise ValueError('bass trials require explicitly timed solo sweeps on a common reference')
    references = [str(item['header']['timing_reference_text']).strip().lower() for item in loaded[:2]]
    if references[0] != references[1]:
        raise ValueError('bass solo headers name different timing references')
    refusal = measure.shared_timing_problem(*loaded[:2]) or measure.unwrap_problem(*loaded[:2], band=(float(args.band[0]), 2000))
    if refusal:
        raise ValueError(refusal)
    live = np.logical_and.reduce([x['support'] for x in loaded])
    band = tuple(args.band)
    if not 20 <= band[0] < band[1] <= 500:
        raise ValueError('bass trial band must be between 20 and 500 Hz')
    sel = (f >= band[0]) & (f <= band[1])
    ref = (f >= 500) & (f <= 2000)
    if np.any((sel | ref) & ~live):
        raise ValueError('bass trials require common measured coverage across trial band and 500-2000 Hz reference')
    sub, front = loaded[0]['complex'], loaded[1]['complex']
    measured = loaded[2]['db']
    predicted = 20 * np.log10(np.maximum(np.abs(sub + front), 1e-12))
    rms = float(np.sqrt(np.mean((predicted[sel] - measured[sel]) ** 2)))
    if rms > 1.5:
        raise ValueError('solo sum differs from measured together by %.2f dB RMS; fix capture/time/level consistency before searching' % rms)
    target_path = args.target
    if target_path == 'default':
        target_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'default_incar_target.txt')
    target = measure.load_target(target_path, f)
    anchor = float(np.median((measured - target)[ref]))
    measured_before = tunelib.audibility_score(f, measured - target - anchor, band=band, mask=sel)
    # Every trial is compared with the model's OWN unchanged prediction, never
    # with the measured capture: otherwise the model error (allowed up to 1.5 dB
    # RMS) is counted as part of every change, and the zero-change trial itself
    # fails the reference-band and local-regression guards.
    before = tunelib.audibility_score(f, predicted - target - anchor, band=band, mask=sel)
    ceiling, limits = (load_limits(args.limits, f) if args.limits else (None, []))
    delays, gains = list(args.delays_ms), list(args.gains_db)
    if not delays or not gains or len(delays) * len(gains) * (2 if args.try_invert else 1) > 100:
        raise ValueError('give a nonempty search with at most 100 candidates')
    if not np.isfinite(delays + gains).all() or max(map(abs, delays)) > 10 or max(map(abs, gains)) > 6:
        raise ValueError('bass trials are limited to +/-10 ms and +/-6 dB relative changes')
    rows = []
    base_error = np.abs(tunelib.masked_erb_smooth(f, predicted - target - anchor, sel))
    for delay in delays:
        for gain in gains:
            for invert in ([False, True] if args.try_invert else [False]):
                changed = sub * 10 ** (gain / 20) * np.exp(-2j * np.pi * f * delay / 1000) * (-1 if invert else 1)
                db = 20 * np.log10(np.maximum(np.abs(front + changed), 1e-12))
                after = tunelib.audibility_score(f, db - target - anchor, band=band, mask=sel)
                error = np.abs(tunelib.masked_erb_smooth(f, db - target - anchor, sel))
                veto = []
                if np.max((error - base_error)[sel]) > 2:
                    veto.append('new local tonal regression exceeds 2 dB')
                if ceiling is not None and np.any(gain > ceiling[sel] + 0.1):
                    veto.append('gain exceeds measured clean-output limit')
                if abs(float(np.median((db - predicted)[ref]))) > 0.25:
                    veto.append('reference band changed; bass-only assumption is invalid')
                rows.append({'delay_change_ms': float(delay), 'gain_change_db': float(gain),
                             'invert_sub': invert, 'score_db': round(after, 4),
                             'improvement_db': round(before - after, 4), 'rejection_reasons': veto})
    rows.sort(key=lambda x: x['score_db'])
    candidates = [r for r in rows if not r['rejection_reasons'] and r['improvement_db'] > 0.25]
    return {'predicted_not_measured': True, 'baseline_score_db': round(before, 4),
            'measured_baseline_score_db': round(measured_before, 4),
            'model_rms_error_db': round(rms, 3), 'band_hz': list(band), 'limits': limits,
            'candidate': candidates[0] if candidates else None, 'trials': rows,
            'next_step': 'Confirm the specific delay/gain trial, load it separately, then measure fronts+sub with repeated MMM and compare via mmm-compare; polarity remains a manual PC-Tool trial.',
            'notes': ['Trials are scored against the unchanged model prediction (baseline_score_db), '
                      'so model error is not counted as part of any change.',
                      'Relative delay can only be applied if the existing delay allocation permits it.',
                      'Single-point predictions are trial directions, never proof of tonal improvement.']}


def stereo_propose(args):
    """Shared target-supported cuts plus side corrections, evaluated together.

    The two side magnitudes are never treated as a coherent system sum.
    Existing filters remain part of the measured baseline; this proposes
    additional cuts only and does not allocate or write hardware slots.
    """
    f = measure.common_grid(20, 20000, 96)
    band = tuple(map(float, args.band))
    if not 60 <= band[0] < band[1] <= 16000 or not 1 <= args.max_bands <= 5:
        raise ValueError('stereo-propose needs a 60-16000 Hz band and 1-5 bands per stage')
    live = np.ones(len(f), bool)
    sides, repeat = {}, {}
    for side, paths in (('left', args.left), ('right', args.right)):
        traces = []
        raw = {}
        for i, path in enumerate(paths):
            axis, db, _p, _c = measure.load_text_export(path)
            raw[str(i)] = (axis, db)
            traces.append(measure.resample_log(axis, db, f))
            live &= measure.support_mask(axis, f)
        if tunelib.detect_duplicate_traces(raw):
            raise ValueError('duplicate stereo captures cannot count as independent runs')
        # Preserve the cross-side level scale; no independent side normalization.
        sides[side] = np.mean(traces, axis=0)
        repeat[side] = traces
    sel = (f >= band[0]) & (f <= band[1])
    if np.any(sel & ~live):
        raise ValueError('both stereo sides must cover the complete requested band')
    target_path = (os.path.join(os.path.dirname(__file__), '..', 'assets', 'default_incar_target.txt')
                   if args.target == 'default' else args.target)
    target = measure.load_target(target_path, f)
    raw_sides = {side: curve.copy() for side, curve in sides.items()}
    level_diagnostic = tunelib.lr_match_cuts(f, sides['left'], sides['right'], band=band)
    trim = level_diagnostic['trim']
    if trim:
        sides[trim['side']] = sides[trim['side']] + trim['trim_db']
    # Choose the baseline reference once after the explicit proposed gain
    # alignment. This is an actual output trim, never an invisible EQ anchor.
    anchor = tunelib.validated_anchor_offset(f, (sides['left'] + sides['right']) / 2, target, confidence=live.astype(float))
    dev = {s: curve - target - anchor for s, curve in sides.items()}
    original_dev = {s: curve - target - anchor for s, curve in raw_sides.items()}
    common_excess = np.minimum(np.maximum(dev['left'], 0), np.maximum(dev['right'], 0))
    common, _ = tunelib.fit_peq(f, common_excess, band, n_bands_max=args.max_bands,
                               g_lim=(-6, 0), q_lim=(.5, 4), fit_smoothed=True, cut_seed_retry=True)
    shared = np.zeros(len(f))
    kept_common = []
    for b in common:
        proposed = shared + tunelib.cascade_db(f, [b])
        if all(np.max((np.maximum(-tunelib.masked_erb_smooth(f, d + proposed, sel), 0)
                          - np.maximum(-tunelib.masked_erb_smooth(f, d, sel), 0))[sel]) <= .5 for d in dev.values()):
            kept_common.append(b)
            shared = proposed
    current = {s: d + shared for s, d in dev.items()}
    banks = {'left': [], 'right': []}
    for side, other in (('left', 'right'), ('right', 'left')):
        excess = np.minimum(np.maximum(current[side], 0), np.maximum(current[side] - current[other], 0))
        bands, _ = tunelib.fit_peq(f, excess, band, n_bands_max=args.max_bands,
                                  g_lim=(-6, 0), q_lim=(.5, 4), fit_smoothed=True, cut_seed_retry=True)
        for b in bands:
            transfer = tunelib.cascade_db(f, [b])
            before = tunelib.audibility_score(f, current[side], band=band, mask=sel)
            after = tunelib.audibility_score(f, current[side] + transfer, band=band, mask=sel)
            guard = partner_guard(f, current[side], current[other], transfer, sel)
            dug = np.maximum(-tunelib.masked_erb_smooth(f, current[side] + transfer, sel), 0) - np.maximum(-tunelib.masked_erb_smooth(f, current[side], sel), 0)
            if after < before and guard['status'] != 'regressed' and np.max(dug[sel]) <= .5:
                current[side] += transfer
                banks[side].append(b)
    before_gap = tunelib.masked_erb_smooth(f, original_dev['left'] - original_dev['right'], sel)[sel]
    after_gap = tunelib.masked_erb_smooth(f, current['left'] - current['right'], sel)[sel]
    margin = .5
    repeated = all(len(x) >= 2 for x in repeat.values())
    if repeated:
        for runs in repeat.values():
            profile = tunelib.capture_repeatability(f, runs, band=band, support=live)
            margin = max(margin, 2 * profile['noise_db'], profile['level_spread_db'])
    import judging
    judge = judging.scorecard(f, (original_dev['left'] + original_dev['right']) / 2,
                              (current['left'] + current['right']) / 2, sel, margin)
    b_gap, a_gap = float(np.sqrt(np.mean(before_gap ** 2))), float(np.sqrt(np.mean(after_gap ** 2)))
    if a_gap > b_gap + .25:
        judge['verdict'] = 'regressed'
    worthwhile = judge['verdict'] == 'improved' or b_gap - a_gap > margin
    return {'predicted_not_measured': True, 'prediction_sample_rate_hz': tunelib.FS,
            'target_anchor_db': round(anchor, 3),
            'level_trim': trim, 'common_bands': kept_common, 'side_bands': banks,
            'judging': judge, 'before_lr_mismatch_db': round(b_gap, 3),
            'after_lr_mismatch_db': round(a_gap, 3), 'independent_repeats': repeated,
            'apply_recommendation': ('hold_for_review' if judge['verdict'] == 'regressed' else
                                     'review_bands' if worthwhile else 'keep_current'),
            'notes': ['Level trim is a separate proposed gain change; confirm its level scale and repeat it before keeping it.',
                      'Each side bank is common_bands plus its side_bands; review free slots before planning a write.',
                      'Keep the same capture level and mic coverage on both sides; no independent side anchoring is applied.',
                      'The paired magnitude mean is a per-side tonal objective, not a predicted coherent system sum.',
                      'Remeasure left, right and both together, then check mono vocals and normal head movements.',
                      'For existing filters needing removal/refit use refine --partner first.']}


def junction_guard(args, bands, run_probe, old_bands=()):
    """Check a tonal transfer at every supplied junction it touches."""
    path = getattr(args, 'junction_spec', None)
    if not path:
        return {'status': 'unknown', 'reason': 'no timed neighbour captures supplied'}
    with open(path, encoding='utf-8-sig') as fh:
        spec = json.load(fh)
    allowed = {'dsp_sample_rate_hz', 'drivers', 'positions', 'junctions', 'pairs', 'apply_to', 'notes'}
    if not isinstance(spec, dict) or set(spec) - allowed:
        raise ValueError('junction spec needs documented probe fields plus apply_to')
    names = spec.pop('apply_to', None)
    if not isinstance(names, list) or not names or len(set(names)) != len(names) or not all(isinstance(x, str) for x in names):
        raise ValueError('junction spec apply_to must name the affected driver(s)')
    positions = spec.get('positions') if 'positions' in spec else [spec.get('drivers')]
    if not isinstance(positions, list) or not positions:
        raise ValueError('junction spec needs drivers or positions')
    f = measure.common_grid(20, 20000, 96)
    base = os.path.dirname(os.path.abspath(path))
    junctions = spec.get('junctions') or []
    touched = [j for j in junctions if j.get('lower') in names or j.get('upper') in names]
    if not touched:
        raise ValueError('junction spec does not describe a junction touched by apply_to')
    for pmap in positions:
        if not isinstance(pmap, dict) or not set(names) <= set(pmap):
            raise ValueError('junction position is missing an affected driver')
        loaded = {}
        for driver, source in pmap.items():
            if not isinstance(source, str):
                raise ValueError('junction driver paths must be strings')
            pmap[driver] = os.path.abspath(os.path.join(base, source))
            loaded[driver] = measure.load_complex(pmap[driver], f)
            if loaded[driver]['header']['timing_reference'] is not True:
                raise ValueError('junction guard requires explicitly timed neighbour sweeps')
        for j in touched:
            if j.get('lower') not in loaded or j.get('upper') not in loaded:
                raise ValueError('junction is missing its lower or upper driver')
            fc = float(j['crossover_hz'])
            if not np.isfinite(fc) or fc <= 0:
                raise ValueError('junction crossover_hz must be finite and positive')
            region = (f >= fc / 2) & (f <= fc * 2)
            for driver in (j['lower'], j['upper']):
                if np.count_nonzero(region) < 8 or np.any(region & ~loaded[driver]['phase_support']):
                    raise ValueError('junction guard needs measured, phase-valid support across the complete junction band')
    transfer = list(bands) + [(F, Q, -G) for F, Q, G in old_bands]
    spec['variants'] = [{'name': 'tonal-edit', 'changes': {name: {'peq': transfer} for name in names}}]
    import argparse
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        candidate = os.path.join(tmp, 'probe.json')
        with open(candidate, 'w', encoding='utf-8') as fh:
            json.dump(spec, fh)
        report = run_probe(argparse.Namespace(spec=candidate))
    report['meta']['spec'] = os.path.abspath(path)
    positions = report.get('positions', [report['variants']])
    recommendations = [next(row['recommendation'] for row in rows if row['name'] == 'tonal-edit') for rows in positions]
    veto = any(r in ('reject', 'tradeoff') for r in recommendations)
    return {'status': 'hold_for_review' if veto else 'assessed',
            'positions': len(positions), 'probe': report,
            'scope': 'supplied timed junctions only; confirm the whole-system result with MMM'}
