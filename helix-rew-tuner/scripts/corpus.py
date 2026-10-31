"""Replay real, local before/after sessions without publishing private captures."""
import hashlib
import json
import os

import numpy as np

import judging
import measure
import tunelib


def _load(base, item, grid):
    path = os.path.abspath(os.path.join(base, item['file']))
    if not os.path.isfile(path):
        raise ValueError('missing corpus capture: %s' % path)
    digest = _hash_file(path)
    if digest != item['sha256']:
        raise ValueError('corpus capture hash changed: %s' % path)
    f, db, _phase, _coh = measure.load_text_export(path)
    import pipeline
    return measure.resample_log(f, db, grid), measure.support_mask(f, grid), (digest, pipeline._capture_id(path))


def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def replay(spec, base):
    if not isinstance(spec, dict) or spec.get('version') != 1 or not isinstance(spec.get('sessions'), list):
        raise ValueError('corpus index needs version 1 and sessions list')
    grid = measure.common_grid(20, 20000, 96)
    rows, ids, splits = [], set(), {}
    for case in spec['sessions']:
        sid = case['session_id']
        if sid in ids:
            raise ValueError('duplicate corpus session_id')
        ids.add(sid)
        group = case['vehicle_id'] + '/' + case['listener_id']
        split = case.get('split', 'development')
        if split not in ('development', 'held_out'):
            raise ValueError('corpus split must be development or held_out')
        if group in splits and splits[group] != split:
            raise ValueError('vehicle/listener group leaks across corpus splits')
        splits[group] = split
        loaded = {key: [_load(base, item, grid) for item in case[key]]
                  for key in ('before', 'after')}
        if not loaded['before'] or not loaded['after']:
            raise ValueError('corpus session needs before and after captures')
        identities = [item[2] for group_items in loaded.values() for item in group_items]
        capture_ids = [x[1] for x in identities if x[1]]
        hashes = [x[0] for x in identities]
        if len(capture_ids) != len(set(capture_ids)) or len(hashes) != len(set(hashes)):
            raise ValueError('one corpus recording was counted more than once')
        live = np.logical_and.reduce([item[1] for g in loaded.values() for item in g])
        if np.count_nonzero(live) < 8:
            raise ValueError('corpus before/after have insufficient common support')
        def aggregate(items):
            traces = [item[0] for item in items]
            return tunelib.mmm_power_pool(traces) if len(traces) > 1 else traces[0]
        before, after = aggregate(loaded['before']), aggregate(loaded['after'])
        target_path = os.path.abspath(os.path.join(base, case['target']))
        if not os.path.isfile(target_path) or _hash_file(target_path) != case.get('target_sha256'):
            raise ValueError('corpus target is missing or its hash changed: %s' % target_path)
        target = measure.load_target(target_path, grid)
        anchor = tunelib.validated_anchor_offset(grid, before, target, confidence=live.astype(float))
        score = judging.scorecard(grid, before-target-anchor, after-target-anchor, live)
        trials = case.get('blind_trials', [])
        if any(t.get('preferred') not in ('before', 'after', 'tie') or
               not isinstance(t.get('track'), str) or not t['track'] for t in trials):
            raise ValueError('blind_trials need track and before/after/tie preference')
        after_wins = sum(t['preferred'] == 'after' for t in trials)
        before_wins = sum(t['preferred'] == 'before' for t in trials)
        preference = ('after' if after_wins > before_wins else
                      'before' if before_wins > after_wins else 'tie')
        objective = 'after' if score['verdict'] == 'improved' else ('before' if score['verdict'] == 'regressed' else 'tie')
        rows.append({'session_id': sid, 'split': split, 'objective_version': 'judging.scorecard.v1',
                     'verdict': score['verdict'], 'score_change_db': round(score['after']['total']-score['before']['total'], 4),
                     'blind_preference': preference if trials else 'unknown',
                     'objective_blind_agreement': objective == preference if trials else None,
                     'blind_after_wins': after_wins,
                     'blind_before_wins': before_wins,
                     'blind_ties': sum(t['preferred'] == 'tie' for t in trials),
                     'blind_trials': len(trials)})
    return {'version': 1, 'sessions': rows,
            'by_split': {split: {'sessions': sum(r['split'] == split for r in rows),
                                 'agreement': sum(r['split'] == split and r['objective_blind_agreement'] is True for r in rows),
                                 'disagreement': sum(r['split'] == split and r['objective_blind_agreement'] is False for r in rows)}
                         for split in ('development', 'held_out')},
            'note': 'One vehicle/listener is one evaluation group; trials and tracks are repeated observations, not independent listeners.'}
