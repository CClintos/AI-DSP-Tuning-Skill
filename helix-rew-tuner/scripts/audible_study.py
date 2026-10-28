"""Measured finalist comparisons for audible tuning decisions. Reports only."""
import json
import os

import numpy as np

import audible
import measure
import tunelib


F = measure.common_grid(20, 20000, 96)


def _path(base, name):
    if not isinstance(name, str) or not name:
        raise ValueError('study capture path must be nonempty')
    return os.path.abspath(os.path.join(base, name))


def _json(base, name):
    with open(_path(base, name), encoding='utf-8-sig') as fh:
        return json.load(fh)


def protect_output(spec, base, out):
    """A study report may never overwrite any nested manifest input."""
    if not out or not os.path.exists(out):
        return
    def visit(value):
        if isinstance(value, dict):
            for child in value.values():
                yield from visit(child)
        elif isinstance(value, list):
            for child in value:
                yield from visit(child)
        elif isinstance(value, str):
            yield value
    for value in visit(spec):
        path = os.path.join(base, value)
        if os.path.isfile(path) and os.path.samefile(path, out):
            raise ValueError('--out is a manifest input; refusing to overwrite it')


def _trace(base, name):
    axis, db, _phase, _coh = measure.load_text_export(_path(base, name))
    return measure.resample_log(axis, db, F), measure.support_mask(axis, F)


def _band(spec, default):
    lo, hi = map(float, spec.get('band_hz', default))
    if not np.isfinite([lo, hi]).all() or not 20 <= lo < hi <= 20000:
        raise ValueError('invalid study band_hz')
    return (lo, hi), (F >= lo) & (F <= hi)


def _common(*supports, band):
    if np.any(band & ~np.logical_and.reduce(supports)):
        raise ValueError('study captures must cover the whole comparison band')


def bass_area(spec, base):
    positions = spec.get('positions')
    if not isinstance(positions, list) or len(positions) < 2:
        raise ValueError('bass_area requires at least two positions in the same driver seat')
    from argparse import Namespace
    reports = []
    for pos in positions:
        if set(pos) != {'sub', 'front', 'together'}:
            raise ValueError('each bass_area position needs sub, front and together')
        args = Namespace(sub=_path(base, pos['sub']), front=_path(base, pos['front']),
                         together=_path(base, pos['together']),
                         target=(_path(base, spec['target']) if spec.get('target', 'default') != 'default' else 'default'),
                         band=spec.get('band_hz', [40, 200]),
                         delays_ms=spec.get('delays_ms', [-.5, 0, .5]),
                         gains_db=spec.get('gains_db', [-1, 0, 1]),
                         try_invert=bool(spec.get('try_invert', False)),
                         limits=_path(base, spec['limits']) if spec.get('limits') else None)
        reports.append(audible.bass_trials(args))
    ranked = []
    for i in range(len(reports[0]['trials'])):
        first = reports[0]['trials'][i]
        key = (first['delay_change_ms'], first['gain_change_db'], first['invert_sub'])
        rows = [next((r for r in report['trials'] if
                      (r['delay_change_ms'], r['gain_change_db'], r['invert_sub']) == key), None)
                for report in reports]
        if any(r is None for r in rows):
            raise ValueError('bass_area search grids differ between positions')
        ranked.append({'delay_change_ms': key[0], 'gain_change_db': key[1], 'invert_sub': key[2],
                       'worst_improvement_db': round(min(r['improvement_db'] for r in rows), 4),
                       'mean_improvement_db': round(float(np.mean([r['improvement_db'] for r in rows])), 4),
                       'rejection_reasons': sorted(set(reason for r in rows for reason in r['rejection_reasons']))})
    ranked.sort(key=lambda r: (-r['worst_improvement_db'], -r['mean_improvement_db']))
    viable = [r for r in ranked if not r['rejection_reasons'] and r['worst_improvement_db'] > .25]
    return {'status': 'trial' if viable else 'keep_current', 'candidate': viable[0] if viable else None,
            'positions': len(reports), 'model_rms_error_db': [r['model_rms_error_db'] for r in reports],
            'trials': ranked, 'note': 'Predictions require loaded-tune repeated MMM confirmation; points are within one driver seat.'}


def workload(spec, base):
    """Compare multitone residuals in explicitly unexcited frequency bins."""
    rows = []
    for item in spec.get('trials', []):
        name = item['name']
        bf, baseline, _p, _c = measure.load_text_export(_path(base, item['baseline']))
        cf, candidate, _p, _c = measure.load_text_export(_path(base, item['candidate']))
        band, sel = _band(item, (80, 10000))
        if len(bf) != len(cf) or not np.allclose(bf, cf, rtol=1e-6, atol=.01):
            raise ValueError('workload spectra require identical native frequency bins')
        bins = np.asarray(item['unexcited_hz'], float)
        if len(bins) < 8 or not np.isfinite(bins).all() or np.any((bins < band[0]) | (bins > band[1])):
            raise ValueError('workload needs at least eight valid unexcited_hz bins in band')
        idx = np.searchsorted(bf, bins).clip(1, len(bf)-1)
        idx -= np.abs(bf[idx-1]-bins) < np.abs(bf[idx]-bins)
        if np.unique(idx).size != len(idx):
            raise ValueError('unexcited_hz bins alias on analysis grid')
        if np.any(np.abs(bf[idx]-bins) > np.maximum(.05, bins*1e-5)):
            raise ValueError('unexcited_hz bins must exactly match native capture bins')
        # Derive the level match from separately captured output fundamentals.
        reference, rs = _trace(base, item['baseline_fundamental'])
        final, fs = _trace(base, item['candidate_fundamental'])
        output_band = (F >= max(100, band[0])) & (F <= min(1000, band[1]))
        if np.count_nonzero(output_band) < 8:
            raise ValueError('workload needs a 100-1000 Hz fundamental reference band')
        _common(rs, fs, band=output_band)
        ref_db = float(np.median((final-reference)[output_band]))
        if not np.isfinite(ref_db) or abs(ref_db) > 1:
            raise ValueError('workload outputs must be matched within 1 dB')
        delta = candidate[idx] - baseline[idx] - ref_db
        noise = float(item['noise_floor_db'])
        if not np.isfinite(noise):
            raise ValueError('workload noise_floor_db must be finite')
        resolved = np.minimum(candidate[idx], baseline[idx]) > noise + 10
        if resolved.mean() < .8:
            status = 'unknown'
        else:
            status = 'improved' if float(np.median(delta[resolved])) < -3 else ('regressed' if float(np.median(delta[resolved])) > 3 else 'within_margin')
        rows.append({'name': name, 'status': status, 'resolved_fraction': round(float(resolved.mean()), 3),
                     'median_residual_change_db': round(float(np.median(delta[resolved])), 3) if np.any(resolved) else None})
    return {'status': 'measured' if rows else 'unknown', 'trials': rows,
            'note': 'Use identical stimulus, spectrum, crest factor, source route and fixed mic; input bins must truly be unexcited. These are change detectors, not audibility thresholds.'}


def stability(spec, base):
    rows = []
    for item in spec.get('trials', []):
        cold, a = _trace(base, item['cold'])
        warm, b = _trace(base, item['warm'])
        recovery, c = _trace(base, item['recovered'])
        band, sel = _band(item, (40, 10000))
        _common(a, b, c, band=sel)
        w = warm[sel] - cold[sel]
        r = recovery[sel] - cold[sel]
        rows.append({'name': item['name'], 'band_hz': band,
                     'warm_median_change_db': round(float(np.median(w)), 3),
                     'warm_p10_change_db': round(float(np.percentile(w, 10)), 3),
                     'recovered_median_change_db': round(float(np.median(r)), 3),
                     'status': 'time_dependent_change' if np.median(w) < -.5 else 'within_margin'})
    return {'status': 'measured' if rows else 'unknown', 'trials': rows,
            'note': 'Capture at identical input, route and fixed mic after recorded playback durations. Acoustic drift alone does not identify thermal cause.'}


def crossover_review(spec, base, load=None, warm=None):
    target_name = spec.get('target', 'default')
    target_path = (os.path.join(os.path.dirname(__file__), '..', 'assets', 'default_incar_target.txt')
                   if target_name == 'default' else _path(base, target_name))
    target = measure.load_target(target_path, F)
    baseline, bs = _trace(base, spec['baseline'])
    band, sel = _band(spec, (80, 8000))
    _common(bs, band=sel)
    anchor = tunelib.validated_anchor_offset(F, baseline, target, confidence=bs.astype(float))
    before = tunelib.audibility_score(F, baseline-target-anchor, band=band, mask=sel)
    rows = []
    for item in spec.get('candidates', []):
        measured, support = _trace(base, item['measurement'])
        _common(bs, support, band=sel)
        probe = _json(base, item['probe_report'])
        named = item['variant']
        groups = probe.get('positions', [probe.get('variants', [])])
        verdicts = []
        for group in groups:
            row = next((r for r in group if r['name'] == named), None)
            if row is None:
                raise ValueError('crossover variant missing from probe position')
            verdicts.append(row['recommendation'])
        after = tunelib.audibility_score(F, measured-target-anchor, band=band, mask=sel)
        quality = _json(base, item['quality_report']) if item.get('quality_report') else None
        quality_state = quality.get('overall') if quality else 'unknown'
        if quality and quality.get('version') != 1:
            raise ValueError('crossover quality_report must be version 1')
        reasons = []
        if any(v in ('reject', 'tradeoff') for v in verdicts): reasons.append('probe rejects or trades off at a position')
        if quality_state == 'hold_for_review': reasons.append('measured output quality holds candidate')
        if quality is None or all(quality.get('evidence', {}).get(k, {}).get('status') == 'unknown'
                                  for k in ('compression', 'distortion')):
            reasons.append('clean-output evidence missing')
        for report, label in ((load, 'multitone'), (warm, 'warm-output')):
            if report is not None:
                match = next((r for r in report['trials'] if r['name'] == item['name']), None)
                if match is None or match['status'] in ('unknown', 'regressed', 'time_dependent_change'):
                    reasons.append(label + ' evidence missing or regressed')
        if before-after <= .25: reasons.append('measured tonal gain below decision margin')
        rows.append({'name': item['name'], 'variant': named, 'measured_tonal_gain_db': round(before-after, 3),
                     'probe_positions': len(groups), 'probe_verdicts': verdicts,
                     'quality_status': quality_state, 'rejection_reasons': reasons})
    rows.sort(key=lambda r: -r['measured_tonal_gain_db'])
    viable = [r for r in rows if not r['rejection_reasons']]
    return {'candidate': viable[0] if viable else None, 'trials': rows,
            'note': 'Requires manually loaded alternatives and system remeasurement; probe predictions alone cannot approve a crossover.'}


def stage_votes(spec):
    trials = spec.get('trials', [])
    if not trials:
        return {'status': 'unknown'}
    if len(trials) < 4 or len({x['track'] for x in trials}) < 2:
        return {'status': 'insufficient', 'reason': 'need four blinded matched-level trials on at least two tracks'}
    if any(abs(float(x['level_difference_db'])) > .5 or x['preferred'] not in ('baseline', 'candidate', 'tie') for x in trials):
        raise ValueError('stage trials need matched levels and baseline/candidate/tie preference')
    wins = sum(x['preferred'] == 'candidate' for x in trials)
    losses = sum(x['preferred'] == 'baseline' for x in trials)
    return {'status': 'candidate_preferred' if wins >= 3 and wins > losses else 'unresolved',
            'candidate_wins': wins, 'baseline_wins': losses, 'ties': len(trials)-wins-losses,
            'note': 'Listening preference is reported, not treated as a calibrated statistical significance test.'}


def volume_preferences(spec):
    rows = []
    for level in spec.get('levels', []):
        row = stage_votes(level)
        rows.append({'level': level['name'], **row})
    return {'levels': rows, 'status': 'measured_preference' if rows else 'unknown',
            'note': 'Use actual preset captures with voice-match at each listening level; do not derive a car EQ curve directly from equal-loudness contours.'}


def rattle_triage(spec):
    rows = []
    for item in spec.get('events', []):
        hz = float(item['excitation_hz'])
        if not 20 <= hz <= 20000 or not item.get('repeat_confirmed'):
            raise ValueError('rattle event needs valid excitation_hz and repeat_confirmed')
        rows.append({'excitation_hz': hz, 'location': item.get('suspected_location', 'unknown'),
                     'action': 'inspect physical source; compare before/after same-level recording and listening',
                     'status': 'repeatable_symptom'})
    return {'status': 'inspect' if rows else 'unknown', 'events': rows,
            'note': 'This triage records observed symptoms. It does not claim to implement specialised rub-and-buzz detection.'}


def study(spec, base):
    if not isinstance(spec, dict) or type(spec.get('version')) is not int or spec['version'] != 1:
        raise ValueError('audible-study requires version 1 manifest')
    names = {'bass_area', 'workload', 'stability', 'crossovers', 'stage', 'volume', 'rattles'}
    if set(spec) - {'version', *names}:
        raise ValueError('unknown audible-study section')
    evidence = {}
    if 'workload' in spec: evidence['workload'] = workload(spec['workload'], base)
    if 'stability' in spec: evidence['stability'] = stability(spec['stability'], base)
    if 'bass_area' in spec: evidence['bass_area'] = bass_area(spec['bass_area'], base)
    if 'crossovers' in spec:
        evidence['crossovers'] = crossover_review(spec['crossovers'], base,
                                                   evidence.get('workload'), evidence.get('stability'))
    if 'stage' in spec: evidence['stage'] = stage_votes(spec['stage'])
    if 'volume' in spec: evidence['volume'] = volume_preferences(spec['volume'])
    if 'rattles' in spec: evidence['rattles'] = rattle_triage(spec['rattles'])
    return {'version': 1, 'evidence': evidence,
            'note': 'Evidence is local to the measured car, route, level and capture method. Keep the current tune until a measured, matched-level improvement repeats.'}
