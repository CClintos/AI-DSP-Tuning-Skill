# planner.py -- before and after an MMM session: what to capture, and what
# the captures you have can now run.
#
#   capture-plan  From the tune (optional) and the goals, the exact capture
#                 list with names capture-audit recognises, the REW settings,
#                 the averages that make each capture long enough, the level
#                 window between the movement noise and the mic's clip point,
#                 the extra delay for mmm-align at each bass junction, and the
#                 RAW/XO/EQ sequence for xo-check -- with the safety limits
#                 (a tweeter never plays without its high-pass).
#   next          From whatever was captured (files, folders, a whole .mdat),
#                 the audit's verdict and the commands that apply, with their
#                 arguments filled in.
#
# Both only read. Every real session reviewed had captures of 5-11 s, mic
# movement noise as loud as the signal, mixed smoothing or resolution, or a
# clipping mic: problems capture-audit can only report afterwards. The plan
# prevents them; `next` stops the wrong tool being picked for the data.
import glob
import math
import os
import re
import shlex

import capture_audit

GOALS = ('tone', 'lr', 'bass', 'xo', 'stability', 'repeat', 'frames', 'validate')
CREST_DB = capture_audit.PINK_CREST_DB
HEADROOM_DB = 3.0


def _q(path):
    """A path as one shell word, for the command lines printed."""
    return shlex.quote(path) if os.name != 'nt' else ('"%s"' % path if re.search(r'[\s&()]', path) else path)


def averages_for(seconds, fft, sample_rate, overlap=None):
    """RTA averages that cover `seconds` at REW's overlap for this FFT."""
    overlap = capture_audit.REW_OVERLAP.get(fft, 0.5) if overlap is None else overlap
    hop = fft * (1.0 - overlap)
    return max(1, int(math.ceil((seconds * sample_rate - fft) / hop)) + 1)


def mic_ceiling_db(mic_model, gain_db):
    clip = capture_audit.MIC_CLIP_DB_SPL.get((mic_model, gain_db))
    return None if clip is None else clip - CREST_DB - HEADROOM_DB


def _junctions(chans):
    """(lower role, upper role, crossover Hz) for the bass junction(s) the
    tune states: where a sub's low-pass meets the midbasses' high-pass."""
    subs = [c for c in chans if c['inferred_role'] == 'sub' and c.get('lp_hz')]
    mids = [c for c in chans if c['inferred_role'] in ('midbass', 'midbass/mid', 'woofer')
            and c.get('hp_hz')]
    out = []
    if subs and mids:
        lp = subs[0]['lp_hz']
        hp = min(c['hp_hz'] for c in mids)
        out.append({'lower': 'sub', 'upper': 'midbass', 'hz': round(math.sqrt(lp * hp), 1),
                    'sub_channels': [c['index'] for c in subs],
                    'midbass_channels': [c['index'] for c in mids]})
    return out


def _cap(name, what, how=None, goal=None, peak=False):
    row = {'name': name, 'what': what}
    if how:
        row['how'] = how
    if goal:
        row['for'] = goal
    if peak:
        row['save'] = 'Save both (average and peak)'
    return row


def plan(goals, chans=None, sample_rate=48000, fft=65536, seconds=25.0, mic_model='UMIK-1',
         mic_gain_db=18.0, dsp_rate=None, junction_hz=None):
    goals = list(GOALS) if 'all' in goals else list(dict.fromkeys(goals))
    unknown = [g for g in goals if g not in GOALS]
    if unknown:
        raise ValueError('unknown goal(s) %s (choose from %s, or all)' % (unknown, ', '.join(GOALS)))
    avg = averages_for(seconds, fft, sample_rate)
    ceiling = mic_ceiling_db(mic_model, mic_gain_db)
    settings = {
        'rta': 'RTA mode 1/48 octave (never Spectrum mode)',
        'fft_length': fft, 'window': 'Hann (the car plays the noise on its own clock)',
        'averaging': 'Forever, Stop at %d averages (about %.0f s at REW\'s %.2f%% overlap for %d '
                     'points)' % (avg, seconds, 100 * capture_audit.REW_OVERLAP.get(fft, 0.5), fft),
        'max_overlap': 'leave at its maximum: a lower setting lengthens every capture',
        'smoothing': 'export and save every capture with NO smoothing; never mix smoothing in a set',
        'input_volume': '1.00 (the mic cal file assumes 100%)',
        'mic': 'one mic and one cal file for the whole session (the 90 degree file, mic pointing up)',
        'test_signal': 'pink periodic noise from the car source at the RTA FFT length (or '
                       '`pipeline.py test-signal --kind pink-periodic`), same volume for every capture',
        'peak': 'Peak hold at its maximum and Peak decay 0 dB/s, so "Save both" keeps the whole '
                'capture\'s peak',
        'engine': 'engine off, doors and windows closed, fan off',
        'movement': 'use the same small path around the judged seat head area each pass: '
                    'left ear, centre, right ear and normal fore-aft extent; spend similar time '
                    'in each part, move slowly, and hold the cable still',
        'repeat_provenance': 'a fresh full pass is an independent repeat; two halves exported '
                             'from one recording only describe within-pass consistency',
    }
    levels = {
        'full_system': 'near your normal listening level (about 75-85 dB C): it beats the movement '
                       'noise and is the level the tune is heard at',
        'solos': 'the same volume setting as the full system -- never touch the volume between '
                 'captures of a set',
    }
    if ceiling is not None:
        levels['mic_ceiling'] = ('keep Input RMS below %.0f dB SPL: the %s at %g dB gain clips peaks '
                                 'near %.0f dB SPL' % (ceiling, mic_model, mic_gain_db,
                                                       ceiling + CREST_DB + HEADROOM_DB))
    caps, steps, safety = [], [], []
    juncs = _junctions(chans) if chans else []
    if junction_hz:
        juncs = [{'lower': 'sub', 'upper': 'midbass', 'hz': float(junction_hz),
                  'sub_channels': None, 'midbass_channels': None}]
    if 'tone' in goals or 'validate' in goals:
        caps.append(_cap('System Sum', 'everything playing', goal='tone', peak='stability' in goals))
        caps.append(_cap('Ambient moving', 'generator OFF, the same mic movement and duration',
                         goal='noise floor'))
    if 'lr' in goals:
        caps += [_cap('Front L', 'left front channels only (sub off)', goal='lr'),
                 _cap('Front R', 'right front channels only (sub off)', goal='lr'),
                 _cap('Front Both', 'both front sides (sub off)', goal='lr')]
    if 'bass' in goals or 'validate' in goals:
        caps += [_cap('Sub', 'sub only', goal='bass'),
                 _cap('Midbass Both', 'both midbasses only', goal='bass'),
                 _cap('Sub Midbass Both', 'sub and both midbasses together', goal='bass')]
        for j in juncs or [{'hz': 80.0, 'midbass_channels': None}]:
            tau1 = round(250.0 / j['hz'], 2)          # a quarter period at the junction
            where = ('channels %s' % ', '.join(str(c) for c in j['midbass_channels'])
                     if j.get('midbass_channels') else 'both midbass channels')
            how = ('in PC-Tool add %.2f ms to the delay of %s, capture, then set it back' % (tau1, where))
            if dsp_rate:
                how += ' (%.2f ms = %d samples at %g Hz)' % (tau1, round(tau1 * dsp_rate / 1e3), dsp_rate)
            caps.append(_cap('Sub Midbass Both T1 %.2fms' % tau1, 'sub and midbasses, midbass delayed '
                             'by %.2f ms' % tau1, how, goal='bass'))
            steps.append('mmm-align: pipeline.py mmm-align --a "Sub" --b "Midbass Both" --together '
                         '"Sub Midbass Both" --together-delayed "Sub Midbass Both T1 %.2fms" '
                         '--tau1-ms %.2f --band %.0f %.0f' % (tau1, tau1, j['hz'] / 1.6, j['hz'] * 1.6))
        safety.append('undo the temporary T1 delay before anything else: the tune file must not keep it')
    if 'stability' in goals and not any(c.get('save') for c in caps):
        caps.append(_cap('System Sum', 'everything playing', goal='stability', peak=True))
    if 'repeat' in goals:
        caps.append(_cap('System Sum 2', 'a second full-system run, same path and duration',
                         goal='repeatability'))
    if 'frames' in goals:
        steps.append('record the mic as a 48 kHz WAV for the whole System Sum pass (any recorder), then '
                     'pipeline.py frames --wav "System Sum.wav" --cal <mic cal file> --out-dir frames')
    if 'xo' in goals:
        rows = []
        for c in (chans or []):
            role = c['inferred_role']
            if not (c.get('hp_hz') or c.get('lp_hz')) or role.startswith('wide'):
                continue
            label = 'ch%d %s' % (c['index'], role.split('/')[0])
            if role == 'tweeter' or (c.get('hp_hz') and c['hp_hz'] >= 1000):
                rows += [_cap('%s XO' % label, 'crossover on, PEQ bypassed', goal='xo'),
                         _cap('%s EQ' % label, 'crossover and PEQ on', goal='xo')]
                steps.append('xo-check (PEQ only): pipeline.py xo-check --xo "%s XO" --eq "%s EQ" '
                             '--afpx <tune> --channel %d --dsp-rate <confirmed rate>' % (label, label, c['index']))
                continue
            section = 'lp' if c.get('lp_hz') else None
            if section:
                rows += [_cap('%s RAW' % label, 'LOW-PASS bypassed, high-pass kept, PEQ bypassed',
                              goal='xo'),
                         _cap('%s XO' % label, 'crossover on, PEQ bypassed', goal='xo'),
                         _cap('%s EQ' % label, 'crossover and PEQ on', goal='xo')]
                steps.append('xo-check: pipeline.py xo-check --raw "%s RAW" --xo "%s XO" --eq "%s EQ" '
                             '--section lp --afpx <tune> --channel %d --dsp-rate <confirmed rate>'
                             % (label, label, label, c['index']))
        if not chans:
            rows.append(_cap('<driver> RAW / XO / EQ', 'per driver: low-pass bypassed (high-pass kept), '
                             'crossover on, crossover and PEQ on', goal='xo'))
        caps += rows
        safety += ['never bypass a tweeter\'s or a midrange\'s high-pass: check those drivers\' PEQ '
                   'only (XO and EQ captures)',
                   'a RAW capture is played at the set\'s volume or lower; stop at any distress sound',
                   'set every bypassed section back before the next capture, and check the tune in '
                   'PC-Tool matches the file at the end']
    if 'validate' in goals:
        caps += [_cap('Sub sweep', 'timed sweep at the head centre, sub only, loopback or acoustic '
                      'timing reference', goal='validate'),
                 _cap('Midbass sweep', 'same, both midbasses', goal='validate'),
                 _cap('Sub Midbass sweep', 'same, together', goal='validate'),
                 _cap('System Sum run 1', 'MMM full system with Save both', goal='validate', peak=True),
                 _cap('System Sum run 2', 'a second identical run with Save both', goal='validate', peak=True)]
        fc = juncs[0]['hz'] if juncs else 80.0
        steps += ['junction: pipeline.py junction --lower "Sub sweep" --upper "Midbass sweep" '
                  '--crossover %.0f --out junction.json (and the mmm-align step above with --out '
                  'align.json)' % fc,
                  'record a WAV of run 1 for frames (frames --wav ... --out-dir frames)',
                  'decide: pipeline.py trust-check --align align.json --junction junction.json '
                  '--average "System Sum run 1" --peak "System Sum run 1 peak" --repeat "System Sum '
                  'run 2" --frames-mean <frames mean file> -- trusted, advisory or remove for each '
                  'simulation-checked tool']
    names = [c['name'] for c in caps]
    triples = []
    if all(n in names for n in ('Front L', 'Front R', 'Front Both')):
        triples.append(['Front L', 'Front R', 'Front Both'])
    if all(n in names for n in ('Sub', 'Midbass Both', 'Sub Midbass Both')):
        triples.append(['Sub', 'Midbass Both', 'Sub Midbass Both'])
    audit = 'pipeline.py capture-audit --captures <the exported files or the session .mdat>'
    for t in triples:
        audit += ' --triple "%s" "%s" "%s"' % tuple(t)
    return {'goals': goals, 'rew_settings': settings, 'levels': levels,
            'capture_seconds': seconds, 'averages': avg,
            'captures': caps, 'cancel_check_sets': triples, 'safety': safety,
            'after': [audit, 'pipeline.py next --captures <the same files>'] + steps,
            'junctions': juncs,
            'notes': ['name each capture exactly as listed: the audit and `next` read the names',
                      'nothing here changes the tune; delays and bypasses are set by hand in '
                      'PC-Tool and set back']}


def capture_plan_cmd(args):
    chans = None
    if args.afpx:
        import afpx
        chans = afpx.channels(afpx.decode(args.afpx))
    return plan(args.goal, chans, args.sample_rate, args.fft, args.seconds, args.mic,
                args.mic_gain_db, args.dsp_rate, args.junction_hz)


# ------------------------------------------------------------------ next
_PEAK = re.compile(r'\bpeak\b', re.I)
_T1 = re.compile(r'\bT1\s*([\d.]+)\s*ms\b', re.I)
_ROAD = re.compile(r'\b(road|driving|cruise|cruising)\b', re.I)
_CH = re.compile(r'\bch(\d+)\b', re.I)


def _expand_inputs(paths):
    import scoresheet
    out, wavs, logs, sheets = [], [], [], []
    for p in paths:
        if os.path.isdir(p):
            for q in sorted(glob.glob(os.path.join(p, '*'))):
                low = q.lower()
                if low.endswith(('.txt', '.mdat')):
                    out.append(q)
                elif low.endswith('.wav'):
                    wavs.append(q)
                elif os.path.basename(low) == 'ab_log.json':
                    logs.append(q)
                elif low.endswith('.json') and scoresheet.is_sheet(q):
                    sheets.append(q)
        elif p.lower().endswith('.wav'):
            wavs.append(p)
        elif os.path.basename(p).lower() == 'ab_log.json':
            logs.append(p)
        elif p.lower().endswith('.json') and scoresheet.is_sheet(p):
            sheets.append(p)
        else:
            out.append(p)
    return out, wavs, logs, sheets


def _spec_by_name(caps):
    """Readable paths: file.mdat::Name when the name is unique in that file."""
    import mdat
    names = {}
    for c in caps:
        base, sel = mdat.split_spec(c['path'])
        names.setdefault(base, []).append(c['name'])
    out = {}
    for c in caps:
        base, sel = mdat.split_spec(c['path'])
        if sel is not None and names[base].count(c['name']) == 1:
            out[c['path']] = '%s::%s' % (base, c['name'])
        else:
            out[c['path']] = c['path']
    return out


def next_steps(paths, afpx_path=None, target='default'):
    files, wavs, logs, sheets = _expand_inputs(paths)
    if not files and not wavs and not logs and not sheets:
        raise ValueError('no captures found in %s' % ', '.join(paths))
    report = capture_audit.audit(files) if files else {'captures': [], 'set': {'flags': [], 'triples': []},
                                                       'table': []}
    caps = [capture_audit.load_capture(p) for p in capture_audit.expand(files)] if files else []
    show = _spec_by_name(caps)
    rows = report['captures']
    by_name = {c['name']: (c, r) for c, r in zip(caps, rows)}
    run, blocked, missing, info = [], [], [], []

    def add(cmd, why):
        run.append({'command': 'pipeline.py ' + cmd, 'why': why})

    def p(cap):
        return _q(show[cap['path']])
    rta = [c for c in caps if (c['rew']['format'] or {}).get('kind') in ('rta', None)]
    sweeps = [c for c in caps if (c['rew']['format'] or {}).get('kind') == 'sweep']
    peaks = [c for c in rta if _PEAK.search(c['name'])]
    plain = [c for c in rta if c not in peaks]
    ambient = [c for c in plain if c['role']['ambient'] and not _ROAD.search(c['name'])]
    road = [c for c in plain if _ROAD.search(c['name'])]
    solos = [c for c in plain if c['passband'] and not c['role']['ambient']]
    full = [c for c in plain if c['role']['driver'] == 'full' and c['role']['side'] in ('both', None)
            and not c['role']['ambient'] and not _ROAD.search(c['name'])]
    # "System Sum" over "Front Stage": the whole system, sub included, is the tonal reference
    full.sort(key=lambda c: (not re.search(r'\b(system|sum|full|all)\b', c['name'], re.I), c['name']))
    problems = {r['name']: [f['code'] for f in r['flags'] if f['level'] == 'problem'] for r in rows}

    floor_args = (' --noise-floor ' + ' '.join(p(c) for c in solos)) if solos else ''
    amb_arg = (' --ambient ' + p(ambient[0])) if ambient else ''
    triple_rows = [t for t in report['set']['triples'] if t.get('consistent') is not False]
    bad_triples = [t for t in report['set']['triples'] if t.get('consistent') is False]
    for t in bad_triples:
        blocked.append({'what': 'cancel check %s' % ' / '.join(t['files']),
                        'why': 'its captures do not share one playback level or export setting'})
    cancel = ''.join(' --cancel-check %s' % ' '.join(p(by_name[n][0]) for n in t['files'])
                     for t in triple_rows)
    if full:
        base = full[0]
        repeats = [c for c in full if re.sub(r'\s*(run\s*)?\d+$', '', c['name'].lower()) ==
                   re.sub(r'\s*(run\s*)?\d+$', '', base['name'].lower())]
        source = ('--positions %s' % ' '.join(p(c) for c in repeats)) if len(repeats) >= 2 \
            else '--measurement %s' % p(base)
        peak = next((c for c in peaks if re.sub(_PEAK, '', c['name']).strip().lower()
                     == base['name'].strip().lower()), None)
        peak_arg = (' --peak-trace %s' % p(peak)) if peak and len(repeats) < 2 else ''
        if problems.get(base['name']):
            blocked.append({'what': 'trusting %s for bass' % base['name'],
                            'why': ', '.join(problems[base['name']])})
        common = '%s --target %s --capture mmm%s%s%s%s' % (source, target, amb_arg, floor_args, cancel, peak_arg)
        add('analyze ' + common, 'tone, bass balance and the cancellation map of the full system')
        add('propose ' + common, 'a PEQ proposal from the same evidence (writes nothing)')
        if afpx_path:
            add('refine --afpx %s --channels <channels> --dsp-rate <confirmed rate> %s'
                % (_q(afpx_path), common), 'when the capture was made through a tune that already has PEQ')
        add('listening-level --capture %s' % p(base), 'the ISO 226 voicing option for your listening level')
        if road:
            add('road-noise --noise %s --music %s' % (p(road[0]), p(base)),
                'a driving-preset voicing option from the road-noise capture')
        if peak:
            add('stability --average %s --peak %s' % (p(base), p(peak)), 'which bass moves with your head')
        elif len(repeats) < 2:
            missing.append('a peak trace of the full system ("Save both") or a second run: '
                           'bass stability and measured repeatability')
    else:
        missing.append('a full-system capture ("System Sum")')
    for t in triple_rows:
        a, b, both = (by_name[n][0] for n in t['files'])
        floor = (' --floor ' + ' '.join(p(c) for c in solos if c not in (a, b, both))) if solos else ''
        add('coherence --a %s --b %s --together %s%s' % (p(a), p(b), p(both), floor),
            'where alignment can change the tone between these two, and where only EQ can')
        if a['role']['driver'] in ('full', None, 'mid', 'tweeter', 'midbass') and a['role']['side'] == 'left':
            add('lr-match --left %s --right %s --target %s' % (p(a), p(b), target),
                'left/right tonal match from the two halves')
    t1 = [c for c in plain if _T1.search(c['name'])]
    for d in t1:
        base_name = _T1.sub('', d['name']).strip()
        together = by_name.get(base_name, (None,))[0]
        sub = next((c for c in plain if c['role']['driver'] == 'sub' and c['role']['side'] in (None, 'both')
                    and c is not together and not _T1.search(c['name']) and c['role']['stage'] is None), None)
        mb = next((c for c in plain if c['role']['driver'] == 'midbass' and c is not together
                   and not _T1.search(c['name'])), None)
        tau = float(_T1.search(d['name']).group(1))
        if together and sub and mb:
            hz = 250.0 / tau
            add('mmm-align --a %s --b %s --together %s --together-delayed %s --tau1-ms %g --band %.0f %.0f'
                % (p(sub), p(mb), p(together), p(d), tau, hz / 1.6, hz * 1.6),
                'sub/midbass delay and polarity from the four captures (a prediction to confirm)')
        else:
            blocked.append({'what': 'mmm-align with %s' % d['name'],
                            'why': 'needs "Sub", "Midbass Both" and "%s" captures as well' % base_name})
    stages = {}
    for c in plain:
        r = c['role']
        if r['stage']:
            ch = _CH.search(c['name'])
            key = ('ch', int(ch.group(1))) if ch else (r['driver'] or '', r['side'] or '')
            stages.setdefault(key, {})[r['stage']] = c
    for key, st in sorted(stages.items(), key=lambda kv: str(kv[0])):
        planned = key[0] == 'ch'          # capture-plan names: RAW keeps the high-pass
        label = 'channel %d' % key[1] if planned else ('%s %s' % (key[1], key[0] or 'driver')).strip()
        if 'XO' in st and ('RAW' in st or 'EQ' in st):
            cmd = 'xo-check --xo %s' % p(st['XO'])
            if 'RAW' in st:
                cmd = 'xo-check --raw %s --xo %s' % (p(st['RAW']), p(st['XO']))
                if planned:
                    cmd += ' --section lp'
            if 'EQ' in st:
                cmd += ' --eq %s' % p(st['EQ'])
            if afpx_path:
                cmd += ' --afpx %s --channel %s' % (_q(afpx_path), key[1] if planned else '<channel>')
            else:
                cmd += ' --hp HZ,SLOPE [--lp HZ,SLOPE]'
            cmd += ' --dsp-rate <confirmed rate>'
            if solos:
                cmd += ' --floor ' + ' '.join(p(c) for c in solos[:4])
            add(cmd, 'the crossover and PEQ the DSP actually applied on %s' % label)
    if sweeps:
        by_driver = {}
        for c in sweeps:
            by_driver.setdefault(c['role']['driver'], {})[c['role']['side']] = c
        for driver, sides in sorted(by_driver.items(), key=lambda kv: str(kv[0])):
            if 'left' in sides and 'right' in sides:
                add('imaging --solo-l %s --solo-r %s' % (p(sides['left']), p(sides['right'])),
                    'where the %s image sits against frequency (timed sweeps carry phase)'
                    % (driver or 'L/R'))
        info.append('timed sweeps found (%s): junction, probe and bass-trials take them for delays '
                    'and polarity -- they need the crossover and a pair of drivers, so confirm which '
                    'pair first' % ', '.join(c['name'] for c in sweeps[:8]))
    for w in wavs:
        add('frames --wav %s --out-dir frames' % _q(w),
            'per-block statistics of that pass: its own repeatability, robust mean and peak trace')
    for lg in logs:
        add('prefs --log %s' % _q(lg), 'your voicing preference from the logged blind A/Bs')
    # finishing touches after the curve, from whatever this set holds
    lefts = [c for c in solos if c['role']['side'] == 'left' and c['role']['stage'] in (None, 'EQ')]
    rights = [c for c in solos if c['role']['side'] == 'right' and c['role']['stage'] in (None, 'EQ')]
    sub_solo = next((c for c in plain if c['role']['driver'] == 'sub' and c['role']['side'] in (None, 'both')
                     and c['role']['stage'] in (None, 'EQ') and not _T1.search(c['name'])), None)
    bass_irs = [c for c in sweeps if c['role']['driver'] in ('sub', 'midbass')][:4]
    parts = []
    if full:
        parts.append('--system %s' % p(full[0]))
    if lefts and rights:
        parts.append('--left %s --right %s' % (' '.join(p(c) for c in lefts), ' '.join(p(c) for c in rights)))
    if sub_solo:
        parts.append('--sub %s' % p(sub_solo))
    if bass_irs:
        parts.append('--ir %s' % ' '.join(p(c) for c in bass_irs))
    if afpx_path:
        parts.append('--afpx %s' % _q(afpx_path))
    if sheets:
        parts.append('--heard %s' % _q(sheets[-1]))
    if parts:
        floor_part = (' --floor ' + ' '.join(p(c) for c in solos)) if solos else ''
        add('finish %s%s' % (' '.join(parts), floor_part),
            'after the curve: residual low-Q peaks, each instrument band imaging in one place, '
            'height overlaps, the sub and bass decay' +
            ('; and each lost point on the listening sheet against them' if sheets else ''))
    if not triple_rows:
        missing.append('a cancel-check set (left, right, both): summation coherence and boost evidence')
    if not ambient and not solos:
        missing.append('a moving ambient capture or band-limited solos: the noise floor')
    return {'audit': {'table': report['table'],
                      'problems': [f['text'] for f in report['set']['flags'] if f['level'] == 'problem'] +
                                  ['%s: %s' % (n, ', '.join(c)) for n, c in problems.items() if c]},
            'run': run, 'info': info, 'blocked': blocked,
            'missing': missing + (['run `pipeline.py capture-plan` for a capture list that unlocks the '
                                   'rest'] if missing else []),
            'notes': ['commands are suggestions from the file names and headers: confirm the drivers, '
                      'channels and seat with the user first',
                      'nothing is written by any of them except voice-variants/ab-make with their '
                      'confirmation flags and plan/apply']}


def next_cmd(args):
    return next_steps(args.captures, args.afpx, args.target)
