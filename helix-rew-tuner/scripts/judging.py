"""Evidence-aware judging; magnitude alone never certifies timing or clean output."""
import os

import numpy as np

import measure
import tunelib

BANDS = (('sub', 20, 80), ('midbass', 80, 250), ('low_mid', 250, 1000),
         ('presence', 1000, 4000), ('treble', 4000, 16000))


def positive(value, name, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('%s must be a finite number' % name)
    if not np.isfinite(value) or (value < 0 if allow_zero else value <= 0):
        raise ValueError('%s must be %s' % (name, 'nonnegative' if allow_zero else 'positive'))
    return float(value)


def vectors(freqs, *traces):
    f = np.asarray(freqs, float)
    if f.ndim != 1 or len(f) < 8 or not np.isfinite(f).all() or np.any(f <= 0) or np.any(np.diff(f) <= 0):
        raise ValueError('frequency axis must have 8+ finite, positive, increasing bins')
    arrays = [np.asarray(t, float) for t in traces]
    if any(t.shape != f.shape or not np.isfinite(t).all() for t in arrays):
        raise ValueError('traces must be finite arrays matching the frequency axis')
    return f, arrays


def regions(freqs, support):
    live = np.asarray(support, bool)
    if live.shape != freqs.shape:
        raise ValueError('support must match the frequency axis')
    for name, lo, hi in BANDS:
        sel = live & (freqs >= lo) & (freqs < hi)
        # Partial bands cannot certify a whole band.
        covered = (np.count_nonzero(sel) >= 8 and freqs[live].min() <= lo * 1.01
                   and freqs[live].max() >= hi / 1.01) if np.any(live) else False
        yield name, lo, hi, sel, covered


def scorecard(freqs, before_dev, after_dev, support, tolerance_db=0.5):
    """One anchor, separate tonal/peak scores and a per-band regression veto.

    The threshold is a decision margin, not a statistical confidence interval.
    Actual distortion, headroom and imaging require independent evidence.
    """
    f, (before, after) = vectors(freqs, before_dev, after_dev)
    tolerance = positive(tolerance_db, 'tolerance_db', allow_zero=True)
    rows = []
    for name, lo, hi, sel, covered in regions(f, support):
        row = {'name': name, 'band_hz': [lo, hi], 'status': 'unknown'}
        if covered:
            b = tunelib.audibility_score(f, before, band=(lo, hi), mask=sel)
            a = tunelib.audibility_score(f, after, band=(lo, hi), mask=sel)
            row.update(before_db=round(b, 4), after_db=round(a, 4),
                       improvement_db=round(b - a, 4),
                       status='regressed' if a - b > tolerance else 'within_margin')
        rows.append(row)
    live = np.asarray(support, bool) & (f >= 20) & (f <= 16000)
    if np.count_nonzero(live) < 8:
        raise ValueError('not enough measured bins for judging')
    b = tunelib.perceptual_score(f, before, band=(20, 16000), mask=live)
    a = tunelib.perceptual_score(f, after, band=(20, 16000), mask=live)
    regression = any(r['status'] == 'regressed' for r in rows)
    # A narrow-peak improvement must not hide a broad tonal regression, or vice versa.
    component_regression = [k for k in ('tonal', 'resonance') if a[k] - b[k] > tolerance]
    gain = b['total'] - a['total']
    return {'verdict': ('regressed' if regression or component_regression else
                        'improved' if gain > tolerance else 'tie'),
            'margin_db': tolerance, 'before': b, 'after': a,
            'component_regressions': component_regression, 'bands': rows,
            'tie_action': 'keep the existing tune, or the simpler candidate',
            'scope': 'tonal magnitude only; scores are heuristics, not listening probabilities'}


def compression(freqs, low_db, high_db, step_db, support, tolerance_db=0.75):
    f, (low, high) = vectors(freqs, low_db, high_db)
    step = positive(step_db, 'commanded step_db')
    tolerance = positive(tolerance_db, 'compression tolerance_db')
    # Never align levels: doing so would remove broadband compression.
    error = high - low - step
    rows = []
    for name, lo, hi, sel, covered in regions(f, support):
        row = {'name': name, 'band_hz': [lo, hi], 'status': 'unknown'}
        if covered:
            shortfall = np.maximum(-error[sel], 0)
            p90 = float(np.percentile(shortfall, 90))
            expansion = float(np.percentile(np.maximum(error[sel], 0), 90))
            row.update(median_tracking_error_db=round(float(np.median(error[sel])), 3),
                       p90_shortfall_db=round(p90, 3), p90_excess_db=round(expansion, 3),
                       status=('compression' if p90 > tolerance else
                               'level_dependent_gain' if expansion > tolerance else 'tracks'))
        rows.append(row)
    return {'commanded_step_db': step, 'tolerance_db': tolerance, 'bands': rows,
            'attribution': 'system-level only; isolate source, amplifier and driver before naming a cause'}


def distortion(freqs, fundamental_db, harmonics_db, noise_db, support, min_snr_db=10):
    """Absolute harmonic SPL and ratios; never infer a universal audibility pass.

    All traces use stimulus frequency as x axis (REW distortion graph), not
    the harmonic's acoustic frequency. Inputs must share absolute calibration.
    """
    if not harmonics_db or any(k not in ('h2', 'h3', 'h4', 'h5', 'h6', 'h7', 'h8', 'h9')
                               for k in harmonics_db):
        raise ValueError('harmonics must contain named h2..h9 traces')
    keys = sorted(harmonics_db)
    f, arrays = vectors(freqs, fundamental_db, *[harmonics_db[k] for k in keys], noise_db)
    fundamental, noise = arrays[0], arrays[-1]
    snr = positive(min_snr_db, 'min_snr_db')
    rows = []
    for name, lo, hi, sel, covered in regions(f, support):
        row = {'name': name, 'band_hz': [lo, hi], 'status': 'unknown'}
        if covered:
            valid = sel & (fundamental - noise >= snr)
            row['fundamental_resolved_fraction'] = round(float(np.mean(valid[sel])), 3)
            row['harmonics'] = {}
            for k, harmonic in zip(keys, arrays[1:-1]):
                resolved = valid & (harmonic - noise >= snr)
                # Unresolved harmonics are not zero distortion.
                row['harmonics'][k] = {
                    'resolved_fraction': round(float(np.mean(resolved[sel])), 3),
                    'max_absolute_db': round(float(np.max(harmonic[resolved])), 3) if np.any(resolved) else None,
                    'max_percent': round(float(np.max(100 * 10 ** ((harmonic[resolved] - fundamental[resolved]) / 20))), 3) if np.any(resolved) else None}
            row['status'] = 'measured' if np.all(valid[sel]) else 'noise_limited'
        rows.append(row)
    return {'bands': rows, 'audibility_verdict': 'not_assessed',
            'notes': ['Ratios can rise in fundamental nulls; inspect absolute harmonic levels.',
                      'Noise is assessed on the supplied distortion-graph stimulus-frequency axis.',
                      'Supplied harmonics are reported individually; incomplete harmonics are not labelled THD.']}


def load_spec(spec, base_dir):
    """Quality-check manifest; referenced files resolve beside the manifest."""
    allowed = {'version', 'baseline', 'candidate', 'target', 'level_steps', 'distortion',
               'margin_db', 'compression_tolerance_db', 'stereo', 'headroom'}
    if not isinstance(spec, dict) or set(spec) - allowed or type(spec.get('version')) is not int or spec.get('version') != 1:
        raise ValueError('quality spec requires version 1 and documented fields only')
    f = measure.common_grid(20, 20000, 96)
    inputs = []

    def trace(path):
        if not isinstance(path, str) or not path:
            raise ValueError('capture path must be a nonempty string')
        path = os.path.abspath(os.path.join(base_dir, path))
        axis, db, _phase, _coh = measure.load_text_export(path)
        inputs.append(path)
        return measure.resample_log(axis, db, f), measure.support_mask(axis, f)

    def runs(paths):
        if not isinstance(paths, list) or not paths:
            raise ValueError('baseline and candidate must be nonempty lists of capture paths')
        loaded = [trace(p) for p in paths]
        raw = {str(i): (f, db) for i, (db, _live) in enumerate(loaded)}
        if tunelib.detect_duplicate_traces(raw):
            raise ValueError('duplicate captures cannot count as independent repeats')
        return np.vstack([x[0] for x in loaded]), np.logical_and.reduce([x[1] for x in loaded])

    report = {'version': 1, 'evidence': {k: {'status': 'unknown'} for k in
              ('tone', 'compression', 'distortion', 'imaging', 'decay', 'headroom', 'listening')},
              'overall': 'incomplete', 'notes': ['Missing evidence never counts as a pass.']}
    evidence = report['evidence']
    if any(k in spec for k in ('baseline', 'candidate', 'target')):
        if not all(k in spec for k in ('baseline', 'candidate', 'target')):
            raise ValueError('tone judging needs baseline, candidate and target together')
        before, bs = runs(spec['baseline'])
        after, ass = runs(spec['candidate'])
        target_path = spec['target']
        if not isinstance(target_path, str) or not target_path:
            raise ValueError('target must be a nonempty path or default')
        target_path = (os.path.join(os.path.dirname(__file__), '..', 'assets', 'default_incar_target.txt')
                       if target_path == 'default' else os.path.join(base_dir, target_path))
        # Target support is explicit too: no flat extrapolation earns authority.
        tf = []
        for line in measure._read_lines(target_path):
            parts = measure._split_row(line.strip())
            try:
                tf.append(float(parts[0]))
            except (ValueError, IndexError):
                continue
        target = measure.load_target(target_path, f)
        tf = np.sort(tf)
        inputs.append(os.path.abspath(target_path))
        live = bs & ass & measure.support_mask(tf, f)
        if np.count_nonzero(live) < 8:
            raise ValueError('captures and target have no shared measured band')
        anchor = tunelib.target_anchor_offset(f, before.mean(axis=0), target, confidence=live.astype(float))
        margin = positive(spec.get('margin_db', 0.5), 'margin_db')
        repeated = len(before) >= 2 and len(after) >= 2
        if repeated:
            for capture in (before, after):
                profile = tunelib.capture_repeatability(f, capture, support=live)
                margin = max(margin, 2 * profile['noise_db'], profile['level_spread_db'])
        result = scorecard(f, before.mean(axis=0) - target - anchor,
                           after.mean(axis=0) - target - anchor, live, margin)
        if result['verdict'] == 'improved' and not repeated:
            result['verdict'] = 'unconfirmed'
        evidence['tone'] = {'status': result['verdict'], 'scorecard': result,
                            'independent_repeats': repeated, 'anchor_db': round(float(anchor), 3)}
        report['notes'].append('Tone comparison requires matched playback levels, preset and capture method; no candidate level alignment is applied.')
    if 'level_steps' in spec:
        steps = spec['level_steps']
        if not isinstance(steps, list) or len(steps) < 2:
            raise ValueError('level_steps needs 2+ fixed-mic captures with path and level_db')
        loaded = []
        for s in steps:
            if not isinstance(s, dict) or set(s) != {'path', 'level_db'}:
                raise ValueError('each level step needs only path and level_db')
            level = s['level_db']
            if isinstance(level, bool) or not isinstance(level, (int, float)) or not np.isfinite(level):
                raise ValueError('level_db must be finite')
            db, live = trace(s['path'])
            loaded.append((float(level), db, live))
        loaded.sort(key=lambda x: x[0])
        if len({x[0] for x in loaded}) != len(loaded):
            raise ValueError('level_steps must have distinct commanded levels')
        ref_level, ref, ref_live = loaded[0]
        reports = [compression(f, ref, db, level - ref_level, ref_live & live,
                               spec.get('compression_tolerance_db', 0.75)) for level, db, live in loaded[1:]]
        evidence['compression'] = {'status': 'measured', 'steps': reports}
    if 'distortion' in spec:
        d = spec['distortion']
        if not isinstance(d, dict) or set(d) != {'fundamental', 'harmonics', 'noise'} or not isinstance(d['harmonics'], dict):
            raise ValueError('distortion requires fundamental, harmonics mapping and noise paths')
        fundamental, live = trace(d['fundamental'])
        noise, ns = trace(d['noise'])
        harmonics = {}
        for key, path in d['harmonics'].items():
            harmonics[key], hs = trace(path)
            live &= hs
        evidence['distortion'] = {'status': 'measured', 'report': distortion(f, fundamental, harmonics, noise, live & ns)}
    if 'stereo' in spec:
        st = spec['stereo']
        if not isinstance(st, dict) or set(st) != {'before_left', 'before_right', 'after_left', 'after_right'}:
            raise ValueError('stereo needs before_left, before_right, after_left, after_right paths')
        loaded = [trace(st[k]) for k in ('before_left', 'before_right', 'after_left', 'after_right')]
        live = np.logical_and.reduce([s for _db, s in loaded])
        left, right, new_left, new_right = [db for db, _s in loaded]
        rows = []
        for name, lo, hi, sel, covered in regions(f, live):
            row = {'name': name, 'band_hz': [lo, hi], 'status': 'unknown'}
            if covered:
                b = float(np.sqrt(np.mean(tunelib.masked_erb_smooth(f, left - right, sel)[sel] ** 2)))
                a = float(np.sqrt(np.mean(tunelib.masked_erb_smooth(f, new_left - new_right, sel)[sel] ** 2)))
                row.update(before_mismatch_db=round(b, 3), after_mismatch_db=round(a, 3),
                           status='regressed' if a - b > positive(spec.get('margin_db', 0.5), 'margin_db') else 'within_margin')
            rows.append(row)
        evidence['imaging'] = {'status': 'magnitude_only', 'bands': rows,
                               'timing_and_head_movement': 'unknown',
                               'note': 'L/R magnitude mismatch is a risk indicator, not a binaural image prediction; captures require a common level scale.'}
    if 'headroom' in spec:
        hr = spec['headroom']
        if not isinstance(hr, dict) or set(hr) != {'transfer', 'input_peak_dbfs'}:
            raise ValueError('headroom needs full-chain transfer path and input_peak_dbfs')
        peak = hr['input_peak_dbfs']
        if isinstance(peak, bool) or not isinstance(peak, (int, float)) or not np.isfinite(peak) or peak > 0:
            raise ValueError('input_peak_dbfs must be finite and <= 0')
        transfer, live = trace(hr['transfer'])
        gain = float(np.max(transfer[live]))
        evidence['headroom'] = {'status': 'modelled', 'peak_transfer_gain_db': round(gain, 3),
                                'estimated_output_peak_dbfs': round(peak + gain, 3),
                                'spectral_margin_db': round(-peak - gain, 3),
                                'internal_clipping': 'unknown',
                                'note': 'Transfer must be full-chain gain in dB, including routing and trims, not acoustic SPL. This spectral estimate cannot certify transient peaks, internal stages or amplifier limits.'}
    if not inputs:
        raise ValueError('quality spec must contain tone, level_steps or distortion evidence')
    regressions = (evidence['tone']['status'] == 'regressed'
                   or any(b['status'] == 'regressed' for b in evidence['imaging'].get('bands', []))
                   or any(b['status'] in ('compression', 'level_dependent_gain') for step in evidence['compression'].get('steps', []) for b in step['bands'])
                   or evidence['headroom'].get('spectral_margin_db', 0) < 0)
    if regressions:
        report['overall'] = 'hold_for_review'
    report['input_files'] = sorted(set(inputs))
    return report
