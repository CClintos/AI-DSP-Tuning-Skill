"""Bounded joint refinement of two measured existing banks; proposals only."""
import numpy as np
import judging
import measure
import tunelib


def refine_pair(f, runs, target, banks, support, band, fs, max_edits=4, ceilings=None, move_checks=None):
    if not np.isfinite(fs) or fs <= 0 or not 1 <= max_edits <= 8:
        raise ValueError('confirmed positive DSP rate and 1-8 edits required')
    sel = support & (f >= band[0]) & (f <= band[1])
    if np.count_nonzero(sel) < 8 or np.any(((f >= band[0]) & (f <= band[1])) & ~support):
        raise ValueError('both sides must cover the full refinement band')
    mean = [tunelib.mmm_power_pool(r) for r in runs]
    anchor = tunelib.validated_anchor_offset(f, (mean[0]+mean[1])/2, target, confidence=sel.astype(float))
    dev = [x-target-anchor for x in mean]
    old = [[tuple(b) for b in bank] for bank in banks]
    base_transfer = [tunelib.cascade_db(f, b, fs=fs) for b in old]
    profiles = [tunelib.capture_repeatability(f, r, band=band, support=sel) for r in runs]
    if any(p['level_spread_db'] > .75 for p in profiles):
        raise ValueError('MMM repeat levels differ by more than 0.75 dB; resolve playback level or mic coverage before joint refinement')
    margins = [max(.5, 2*p['noise_db']) for p in profiles]
    lr_sel = sel & (f >= 700) & (f <= 5000)
    if np.count_nonzero(lr_sel) < 8:
        raise ValueError('joint refinement needs common vocal-band support (700-5000 Hz)')

    def evaluate(pair):
        transfers = [tunelib.cascade_db(f, [b for b in pair[s] if b is not None], fs=fs)-base_transfer[s] for s in range(2)]
        after = [dev[s]+transfers[s] for s in range(2)]
        cards = [judging.scorecard(f, dev[s], after[s], sel, margins[s]) for s in range(2)]
        lr = float(np.sqrt(np.mean(tunelib.masked_erb_smooth(f, after[0]-after[1], lr_sel)[lr_sel]**2)))
        return transfers, cards, lr

    _, baseline, base_lr = evaluate(old)
    base_cost = np.mean([c['before']['total'] for c in baseline])
    current = [list(b) for b in old]
    edits, used = [], set()
    current_cost, current_lr = base_cost, base_lr
    ceilings = ceilings or [np.full(len(f), 3.), np.full(len(f), 3.)]

    def assess(pair):
        transfer, cards, lr = evaluate(pair)
        if lr > base_lr+.25 or any(c['verdict'] == 'regressed' for c in cards):
            return None
        for side in range(2):
            before_sm = tunelib.masked_erb_smooth(f, dev[side], sel)
            after_sm = tunelib.masked_erb_smooth(f, dev[side]+transfer[side], sel)
            dug = np.maximum(-after_sm, 0)-np.maximum(-before_sm, 0)
            if np.max(dug[sel]) > .5:
                return None
            if move_checks and move_checks[side]:
                for old_band, new_band in zip(old[side], pair[side]):
                    if old_band != new_band and move_checks[side](old_band, new_band):
                        return None
            if np.any(transfer[side] > ceilings[side]+.1):
                return None
            # Every independent pass must avoid a regional regression.
            for run in runs[side]:
                d = run-target-anchor
                if judging.scorecard(f, d, d+transfer[side], sel, margins[side])['verdict'] == 'regressed':
                    return None
        cost = float(np.mean([c['after']['total'] for c in cards]))
        return cost, lr, cards

    for _ in range(max_edits):
        options = []
        for side in range(2):
            choices = []
            for i, b in enumerate(current[side]):
                if b is None or (side, i) in used or not band[0] <= b[0] <= band[1]:
                    continue
                hz, q, gain = b
                candidates = [('remove', None), ('relax', (hz, q, round(gain*2)/4))]
                candidates += [('refit', (round(hz*2**shift, 1), round(q if qm == 1 else np.clip(q*qm, .5, 8), 2), round(g*4)/4))
                               for shift, qm, g in [(-1/6, 1, gain), (1/6, 1, gain),
                                                    (0, .75, gain), (0, 1.25, gain),
                                                    (0, 1, gain-.5), (0, 1, min(0, gain+.5))]]
                for action, new in candidates:
                    if new == b or (new and (not band[0] <= new[0] <= band[1] or not -15 <= new[2] <= 0)):
                        continue
                    pair = [list(x) for x in current]
                    pair[side][i] = new
                    # Physical feasibility precedes shortlisting; joint tonal guards follow.
                    transfer, cards, lr = evaluate(pair)
                    if np.any(transfer[side] > ceilings[side]+.1):
                        continue
                    if move_checks and move_checks[side] and move_checks[side](b, new):
                        continue
                    cost = float(np.mean([c['after']['total'] for c in cards]))
                    choices.append((cost, lr, side, i, action, b, new))
            options.append(sorted(choices, key=lambda x: x[:2])[:4])
        moves = [[c] for group in options for c in group]
        moves += [[a, b] for a in options[0] for b in options[1]]
        best = None
        for move in moves:
            if len(edits)+len(move) > max_edits:
                continue
            pair = [list(x) for x in current]
            for _, _, side, i, action, before, new in move:
                pair[side][i] = new
            result = assess(pair)
            if result is None:
                continue
            cost, lr, cards = result
            margin = max(margins)
            improves = current_cost-cost > margin or (current_lr-lr > margin and cost <= current_cost+.02)
            simpler = (all(c[4] == 'remove' for c in move) and cost <= min(current_cost, base_cost)+.02
                       and lr <= min(current_lr, base_lr)+.02)
            if not (improves or simpler):
                continue
            key = (cost, lr, sum(b is not None for bank in pair for b in bank))
            if best is None or key < best[0]:
                best = key, pair, move, result
        if best is None:
            break
        _, current, move, (current_cost, current_lr, _) = best
        for _, _, side, i, action, before, new in move:
            used.add((side, i))
            edits.append({'side': ('left', 'right')[side], 'index': i, 'action': action, 'old': before, 'new': new})
    _, cards, lr = evaluate(current)
    return {'banks': [[b for b in bank if b is not None] for bank in current], 'old_banks': old,
            'edits': edits, 'judging': cards, 'baseline_lr_mismatch_db': base_lr,
            'final_lr_mismatch_db': lr, 'decision_margins_db': margins,
            'target_anchor_db': anchor, 'unchanged': not edits,
            'prediction_sample_rate_hz': fs, 'predicted_not_measured': True}


def command(args):
    import afpx
    import audible
    import pipeline
    from types import SimpleNamespace
    if args.left_channel == args.right_channel:
        raise ValueError('left and right channels must differ')
    channels = afpx.channels(afpx.decode(args.afpx))
    selected = [args.left_channel, args.right_channel]
    if any(c < 0 or c >= len(channels) for c in selected):
        raise ValueError('selected channel does not exist')
    f = measure.common_grid(20, 20000, 96)
    live = np.ones(len(f), bool)
    runs = []
    pipeline._independent_capture_paths(args.left+args.right)
    for paths in (args.left, args.right):
        if len(paths) < 2:
            raise ValueError('stereo-refine needs two independent full MMM passes per side')
        raw, traces = {}, []
        for path in paths:
            axis, db, _, _ = measure.load_text_export(path)
            raw[path] = (axis, db)
            traces.append(measure.resample_log(axis, db, f))
            live &= measure.support_mask(axis, f)
        if len(raw) != len(paths) or tunelib.detect_duplicate_traces(raw):
            raise ValueError('duplicate stereo captures cannot count as independent runs')
        runs.append(traces)
    band = tuple(args.band)
    if not 60 <= band[0] < band[1] <= 16000:
        raise ValueError('stereo refinement band must lie within 60-16000 Hz')
    for c in selected:
        ch = channels[c]
        if band[0] < (ch['hp_hz'] or 0)*2**(1/3) or band[1] > (ch['lp_hz'] or 1e9)/2**(1/3):
            raise ValueError('refinement band must stay inside both selected channel passbands')
    entries = [pipeline._peq_bank(channels[c]) for c in selected]
    banks = [[(hz, q, g) for slot, hz, q, g in bank] for bank in entries]
    target = measure.load_target(pipeline.ASSETS_DEFAULT_TARGET if args.target == 'default' else args.target, f)
    limits = [audible.load_limits(p, f)[0] if p else np.full(len(f), 3.) for p in (args.left_limits, args.right_limits)]
    notes = []
    guards = pipeline.load_guards(args.afpx, notes)
    checks = [pipeline.guard_move_check(guards, [c], f, args.dsp_rate) for c in selected]
    result = refine_pair(f, runs, target, banks, live, band, args.dsp_rate, args.max_edits, limits, checks)
    guards = []
    for s, path in enumerate((args.left_junction_spec, args.right_junction_spec)):
        if path:
            import json
            with open(path, encoding='utf-8-sig') as fh:
                if json.load(fh).get('dsp_sample_rate_hz') != args.dsp_rate:
                    raise ValueError('junction spec DSP rate must match --dsp-rate')
        guards.append(audible.junction_guard(SimpleNamespace(junction_spec=path, dsp_rate=args.dsp_rate),
                      result['banks'][s], pipeline.probe, banks[s]))
    for e in result['edits']:
        s = 0 if e['side'] == 'left' else 1
        e['channel'] = selected[s]
        e['slot_index'] = entries[s][e['index']][0]
    result.update(source_afpx=args.afpx, channels=selected, junction_guards=guards,
                  apply_recommendation=('keep_current' if result['unchanged'] else
                    'hold_for_review' if any(g['status'] != 'assessed' for g in guards) else 'review_edits'),
                  notes=['Capture through these exact existing banks; left/right levels and mic coverage must match.',
                         'Unknown capture IDs require operator confirmation of separate full passes.',
                         'Load approved edits through plan/apply, then remeasure left, right and both; confirm mono vocals at matched level.'])
    return result
