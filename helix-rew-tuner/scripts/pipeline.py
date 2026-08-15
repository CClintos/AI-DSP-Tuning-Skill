# pipeline.py -- one deterministic entry point for the analysis layer.
#
# Every session up to now hand-wrote bespoke `python -c` snippets to load
# exports, resample, compute deviation, and run the audits. It worked, but
# it was re-derived slightly differently every time (different thresholds,
# different region-finding logic, easy to skip a check by accident without
# noticing) and each invocation cost tokens the same handful of numbers
# doesn't need to repay every session.
#
# `analyze` is reporting-only. `plan` creates a reviewable JSON draft, while
# `apply` is the explicit, fail-closed write boundary for a confirmed plan.
# Judgment (what to actually DO about a flagged region) still lives in
# methodology.md and the conversation; this module keeps both the analysis
# numbers and approved writes deterministic by delegating to the independently
# tested tunelib.py/measure.py/afpx.py functions.
#
# python pipeline.py analyze --measurement <export.txt> --target <target.txt|default> [options]
# python pipeline.py plan --source <input.afpx> --output <new.afpx> --out <plan.json>
# python pipeline.py apply --plan <plan.json>
#   --measurement FILE           REW text export (system sum or primary trace)
#   --positions FILE [FILE...]   2+ position sweeps -> spatial_consistency
#                                 (first one doubles as --measurement if that
#                                 flag is omitted)
#   --target FILE | default      target curve, or the skill's default in-car curve
#   --voice tilt=X bass=Y presence=Z air=W   voice_target knobs applied to target
#   --solo-a FILE --solo-b FILE --together FILE [--pair-band LO HI]
#                                 one interference_audit pass (+ crossover_confidence
#                                 if solo files carry phase and --pair-band is given)
#   --gate-ms N                   only if you KNOW the capture was time-gated --
#                                 REW's text export doesn't carry this, so it's
#                                 never inferred
#   --afpx FILE                   read-only context (model, channel map) in the
#                                 report -- never written to
#   --dev-flag-db N (default 2.0) deviation-region flagging threshold
#   --out FILE                    write JSON here instead of stdout
import argparse
import hashlib
import json
import math
import os
import sys
import tempfile

import numpy as np

import afpx
import measure
import tunelib

ASSETS_DEFAULT_TARGET = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'assets', 'default_incar_target.txt')


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def validate_plan(plan, source_path, source_bytes=None):
    """Validate and normalize an AFPX tune plan without writing files."""
    if not isinstance(plan, dict):
        raise ValueError('plan must be a JSON object')
    required = {'version', 'source_path', 'source_sha256', 'format',
                'output_path', 'edits', 'confirmations'}
    missing = required - set(plan)
    extra = set(plan) - required
    if missing:
        raise ValueError('plan is missing required field(s): %s' % sorted(missing))
    if extra:
        raise ValueError('plan has unknown field(s): %s' % sorted(extra))
    if type(plan['version']) is not int or plan['version'] != 1:
        raise ValueError('unsupported plan version %r (expected 1)' % plan['version'])
    if plan['format'] != 'afpx':
        raise ValueError('unsupported format %r (only afpx is writable)' % plan['format'])
    if not isinstance(plan['source_path'], str) or not plan['source_path']:
        raise ValueError('source_path must be a non-empty string')
    if not isinstance(plan['output_path'], str) or not plan['output_path']:
        raise ValueError('output_path must be a non-empty string')
    if not isinstance(plan['edits'], list) or not plan['edits']:
        raise ValueError('edits must be a non-empty list')
    if not isinstance(plan['confirmations'], dict):
        raise ValueError('confirmations must be an object keyed by edit id')

    source_path = os.path.abspath(os.fspath(source_path))
    plan_source = os.path.abspath(plan['source_path'])
    if os.path.normcase(os.path.realpath(plan_source)) != os.path.normcase(
            os.path.realpath(source_path)):
        raise ValueError('plan source_path does not match supplied source path')
    if not os.path.isfile(source_path):
        raise ValueError('source_path is not a file: %s' % source_path)
    if os.path.splitext(source_path)[1].lower() != '.afpx':
        raise ValueError('format afpx requires a .afpx source_path')

    supplied_hash = plan['source_sha256']
    if (not isinstance(supplied_hash, str) or len(supplied_hash) != 64 or
            any(ch not in '0123456789abcdefABCDEF' for ch in supplied_hash)):
        raise ValueError('source_sha256 must be 64 hexadecimal characters')
    if source_bytes is None:
        with open(source_path, 'rb') as fh:
            source_bytes = fh.read()
    else:
        source_bytes = bytes(source_bytes)
    actual_hash = _sha256_bytes(source_bytes)
    if supplied_hash.lower() != actual_hash:
        raise ValueError('source_sha256 does not match source file')

    output_path = os.path.abspath(plan['output_path'])
    if os.path.splitext(output_path)[1].lower() != '.afpx':
        raise ValueError('format afpx requires a .afpx output_path')
    if os.path.normcase(os.path.realpath(output_path)) == os.path.normcase(
            os.path.realpath(source_path)):
        raise ValueError('output_path must be different from source path')
    if os.path.exists(output_path):
        raise ValueError('output_path already exists; refusing to overwrite: %s' % output_path)

    source_xml = afpx.decode_bytes(source_bytes, source_path)
    confirmations = plan['confirmations']
    normalized_edits = []
    edit_ids = set()
    target_keys = set()
    phase_edit_ids = set()
    eq_edit_ids = set()
    working_xml = source_xml

    def integer_field(edit, key):
        value = edit.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError('%s: %s must be an integer' % (edit.get('id'), key))
        return value

    def numeric_field(edit, key):
        value = edit.get(key)
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                not math.isfinite(value)):
            raise ValueError('%s: %s must be a finite JSON number' %
                             (edit.get('id'), key))
        return float(value)

    for raw_edit in plan['edits']:
        if not isinstance(raw_edit, dict):
            raise ValueError('every edit must be an object')
        edit_id = raw_edit.get('id')
        if not isinstance(edit_id, str) or not edit_id:
            raise ValueError('every edit requires a non-empty string id')
        if edit_id in edit_ids:
            raise ValueError('duplicate edit id: %s' % edit_id)
        edit_ids.add(edit_id)
        kind = raw_edit.get('kind')
        if kind not in {'filter_slot', 'delay_samples', 'output_trim'}:
            raise ValueError('%s: unsupported edit kind %r; crossover and polarity '
                             'writes are not supported' % (edit_id, kind))

        allowed = {
            'filter_slot': {'id', 'kind', 'channel', 'slot', 'F', 'Q', 'G', 'type_code'},
            'delay_samples': {'id', 'kind', 'channel', 'samples'},
            'output_trim': {'id', 'kind', 'channel', 'trim_db'},
        }[kind]
        unknown = set(raw_edit) - allowed
        if unknown:
            raise ValueError('%s: unknown field(s): %s' % (edit_id, sorted(unknown)))

        channel = integer_field(raw_edit, 'channel')
        normalized_edit = {'id': edit_id, 'kind': kind, 'channel': channel}
        if kind == 'filter_slot':
            slot = integer_field(raw_edit, 'slot')
            if not any(key in raw_edit for key in ('F', 'Q', 'G', 'type_code')):
                raise ValueError('%s: filter_slot edit has nothing to change' % edit_id)
            key = (kind, channel, slot)
            if key in target_keys:
                raise ValueError('%s: duplicate filter target ch%d slot%d' %
                                 (edit_id, channel, slot))
            target_keys.add(key)
            try:
                old_tag = afpx.filters(afpx.channel_blocks(working_xml)[channel])[slot]
            except (IndexError, TypeError):
                raise ValueError('%s: channel or slot is out of range' % edit_id)
            old_attrs = afpx.attrs(old_tag)
            old_type = old_attrs.get('T')
            if ('type_code' in raw_edit and
                    (not isinstance(raw_edit['type_code'], str) or
                     not raw_edit['type_code'])):
                raise ValueError('%s: type_code must be a non-empty string' % edit_id)
            target_type = str(raw_edit.get('type_code', old_type))
            if target_type in afpx.CROSSOVER_TYPES:
                raise ValueError('%s: crossover edit requested; refusing' % edit_id)
            if target_type not in {'1', '17', '3', '4', '19', '20'}:
                raise ValueError('%s: unsupported filter type_code %r' %
                                 (edit_id, target_type))
            if target_type == '3' and old_attrs.get('dF') != '25':
                raise ValueError('%s: low shelf requires the dF 25 end slot' % edit_id)
            if target_type == '4' and old_attrs.get('dF') != '20000':
                raise ValueError('%s: high shelf requires the dF 20000 end slot' % edit_id)
            kwargs = {}
            for field in ('F', 'Q', 'G'):
                if field in raw_edit:
                    kwargs[field] = numeric_field(raw_edit, field)
                    normalized_edit[field] = kwargs[field]
            if 'type_code' in raw_edit:
                kwargs['type_code'] = target_type
                normalized_edit['type_code'] = target_type
            candidate_xml = afpx.write_filter_slot(
                working_xml, channel, slot, **kwargs)
            if candidate_xml == working_xml:
                raise ValueError('%s is a no-op; requested slot values already match'
                                 % edit_id)
            working_xml = candidate_xml
            normalized_edit['slot'] = slot
            domain_types = {old_type, target_type}
            if domain_types & {'19', '20'}:
                phase_edit_ids.add(edit_id)
            if domain_types & {'3', '4', '17'}:
                eq_edit_ids.add(edit_id)
        elif kind == 'delay_samples':
            samples = integer_field(raw_edit, 'samples')
            key = (kind, channel)
            if key in target_keys:
                raise ValueError('%s: duplicate delay target ch%d' % (edit_id, channel))
            target_keys.add(key)
            delay_tags = afpx.delay_tags(working_xml)
            if 0 <= channel < len(delay_tags):
                existing = afpx.attrs(delay_tags[channel]).get('T')
                try:
                    existing_samples = int(existing, 10)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        '%s: existing delay T=%r must be an integer'
                        % (edit_id, existing)
                    ) from exc
                if existing_samples == samples:
                    raise ValueError('%s is a no-op; requested delay already matches'
                                     % edit_id)
            candidate_xml = afpx.write_delay_samples(working_xml, channel, samples)
            if candidate_xml == working_xml:
                raise ValueError('%s is a no-op; requested delay already matches'
                                 % edit_id)
            working_xml = candidate_xml
            normalized_edit['samples'] = samples
            phase_edit_ids.add(edit_id)
        else:
            if 'trim_db' not in raw_edit:
                raise ValueError('%s: trim_db is required' % edit_id)
            trim_db = numeric_field(raw_edit, 'trim_db')
            key = (kind, channel)
            if key in target_keys:
                raise ValueError('%s: duplicate output trim target ch%d' % (edit_id, channel))
            target_keys.add(key)
            if trim_db == 0.0:
                raise ValueError('%s is a no-op; zero dB output trim changes nothing'
                                 % edit_id)
            candidate_xml = afpx.write_output_trim(working_xml, {channel: trim_db})
            if candidate_xml == working_xml:
                raise ValueError('%s is a no-op; requested output trim changes nothing'
                                 % edit_id)
            working_xml = candidate_xml
            normalized_edit['trim_db'] = trim_db
        if confirmations.get(edit_id) is not True:
            raise ValueError('%s requires explicit per-change confirmation' % edit_id)
        normalized_edits.append(normalized_edit)

    unknown_confirmations = set(confirmations) - edit_ids
    if unknown_confirmations:
        raise ValueError('confirmations reference unknown edit id(s): %s' %
                         sorted(unknown_confirmations))
    if any(type(value) is not bool for value in confirmations.values()):
        raise ValueError('confirmation values must be JSON booleans')
    if phase_edit_ids and eq_edit_ids:
        raise ValueError(
            'phase-domain and EQ-domain edits (including delay and filter edits '
            'on the same channel) cannot share one plan; apply the '
            'phase change, remeasure, then create a fresh EQ plan (phase=%s, EQ=%s)'
            % (sorted(phase_edit_ids), sorted(eq_edit_ids)))

    return {
        'version': 1,
        'source_path': source_path,
        'source_sha256': actual_hash,
        'format': 'afpx',
        'output_path': output_path,
        'edits': normalized_edits,
        'confirmations': dict(confirmations),
    }


def _slot_expect(edit):
    expect = {}
    if 'F' in edit:
        expect['F'] = '%.2f' % edit['F']
    if 'Q' in edit:
        expect['Q'] = '%g' % edit['Q']
    if 'G' in edit:
        expect['G'] = '%g' % edit['G']
    if 'type_code' in edit:
        expect['T'] = edit['type_code']
    return expect


def _apply_edits(source_xml, edits):
    working_xml = source_xml
    results = []
    for edit in edits:
        before = working_xml
        if edit['kind'] == 'filter_slot':
            kwargs = {key: edit[key] for key in ('F', 'Q', 'G', 'type_code')
                      if key in edit}
            working_xml = afpx.write_filter_slot(
                before, edit['channel'], edit['slot'], **kwargs)
            result = afpx.verify_slot_write(
                before, working_xml, edit['channel'], edit['slot'], _slot_expect(edit))
        elif edit['kind'] == 'delay_samples':
            working_xml = afpx.write_delay_samples(
                before, edit['channel'], edit['samples'])
            result = afpx.verify_delay_write(
                before, working_xml, edit['channel'], edit['samples'])
        elif edit['kind'] == 'output_trim':
            trims = {edit['channel']: edit['trim_db']}
            working_xml = afpx.write_output_trim(before, trims)
            result = afpx.verify_output_trim_write(before, working_xml, trims)
        else:
            raise ValueError('application is not implemented for edit kind %r' % edit['kind'])
        if not result['pass']:
            raise ValueError('%s verification failed: %s' %
                             (edit['id'], '; '.join(result['errors'])))
        results.append({'id': edit['id'], 'kind': edit['kind'], 'result': result})
    return working_xml, results


def apply_plan(plan_path):
    """Apply a validated plan to a new AFPX and return its verification manifest."""
    plan_path = os.path.abspath(os.fspath(plan_path))
    with open(plan_path, encoding='utf-8') as fh:
        plan = json.load(fh)
    plan_dir = os.path.dirname(plan_path)
    for key in ('source_path', 'output_path'):
        if isinstance(plan.get(key), str) and not os.path.isabs(plan[key]):
            plan[key] = os.path.join(plan_dir, plan[key])
    source_path = plan.get('source_path') if isinstance(plan, dict) else None
    if not isinstance(source_path, str) or not source_path:
        raise ValueError('source_path must be a non-empty string')
    if not os.path.isfile(source_path):
        raise ValueError('source_path is not a file: %s' % source_path)
    with open(source_path, 'rb') as fh:
        source_bytes = fh.read()
    normalized = validate_plan(plan, source_path, source_bytes=source_bytes)
    source_xml = afpx.decode_bytes(source_bytes, normalized['source_path'])
    intended_xml, _ = _apply_edits(source_xml, normalized['edits'])

    output_dir = os.path.dirname(normalized['output_path']) or os.curdir
    temp_path = None
    try:
        fd, temp_path = tempfile.mkstemp(prefix='.tune-plan-', suffix='.afpx', dir=output_dir)
        os.close(fd)
        afpx._encode_unchecked(intended_xml, temp_path)
        emitted_xml = afpx.decode(temp_path)
        replayed_xml, edit_results = _apply_edits(source_xml, normalized['edits'])
        if replayed_xml != emitted_xml:
            raise ValueError('encoded output did not decode to the verified edit result')
        filter_count = sum(1 for edit in normalized['edits']
                           if edit['kind'] == 'filter_slot')
        lint = afpx.roundtrip_lint(
            source_xml, emitted_xml, expect_changed=filter_count,
            allow_delay=any(edit['kind'] == 'delay_samples'
                            for edit in normalized['edits']))
        if not lint['pass']:
            raise ValueError('roundtrip_lint failed: %s' % '; '.join(lint['errors']))
        if _sha256_file(normalized['source_path']) != normalized['source_sha256']:
            raise ValueError('source file changed after plan validation; refusing output')
        afpx.write_preserving_crossovers(
            normalized['source_path'], emitted_xml, normalized['output_path'])
    finally:
        if temp_path is not None and os.path.exists(temp_path):
            os.unlink(temp_path)

    return {
        'plan_version': normalized['version'],
        'format': normalized['format'],
        'source_path': normalized['source_path'],
        'output_path': normalized['output_path'],
        'source_sha256': normalized['source_sha256'],
        'output_sha256': _sha256_file(normalized['output_path']),
        'normalized_edits': normalized['edits'],
        'verification': {'edits': edit_results, 'roundtrip_lint': lint},
        'predicted_not_measured': True,
    }


def create_plan(source_path, output_path):
    """Create an empty version-1 AFPX plan for review and editing."""
    source_path = os.path.abspath(os.fspath(source_path))
    output_path = os.path.abspath(os.fspath(output_path))
    if not os.path.isfile(source_path):
        raise ValueError('source is not a file: %s' % source_path)
    if os.path.splitext(source_path)[1].lower() != '.afpx':
        raise ValueError('plan currently supports .afpx sources only')
    if os.path.splitext(output_path)[1].lower() != '.afpx':
        raise ValueError('output must use the .afpx extension')
    if os.path.normcase(os.path.realpath(source_path)) == os.path.normcase(
            os.path.realpath(output_path)):
        raise ValueError('output must be different from source')
    return {
        'version': 1,
        'source_path': source_path,
        'source_sha256': _sha256_file(source_path),
        'format': 'afpx',
        'output_path': output_path,
        'edits': [],
        'confirmations': {},
    }


def _find_regions(freqs, y, flag_db, smooth_oct=1.0 / 6.0):
    """Generic contiguous-region finder -- same smooth/flag/collapse-to-runs
    pattern tunelib.lr_match_report already uses, kept local (not imported)
    so nothing here can regress an already-tested tunelib function."""
    sm = tunelib.octave_smooth_log(freqs, y, smooth_oct)
    flagged = np.abs(sm) >= flag_db
    regions = []
    in_run, start = False, 0
    for i in range(len(freqs)):
        if flagged[i] and not in_run:
            start, in_run = i, True
        if in_run and (not flagged[i] or i == len(freqs) - 1):
            end = i if flagged[i] else i - 1
            seg = slice(start, end + 1)
            j = start + int(np.argmax(np.abs(sm[seg])))
            regions.append({'f_lo': round(float(freqs[start]), 1),
                            'f_hi': round(float(freqs[end]), 1),
                            'peak_hz': round(float(freqs[j]), 1),
                            'peak_db': round(float(sm[j]), 2),
                            'direction': 'boost_needed' if sm[j] < 0 else 'cut_needed'})
            in_run = False
    return regions


def _trust_band(freqs, spl_db, down_db=20.0, smooth_oct=1.0 / 3.0, inset_oct=1.0 / 3.0):
    """The band this trace actually produces output in, as (lo, hi).

    Bounds where the boost gate measures its robust spread. Two things this has
    to avoid, both of which quietly corrupt that statistic:
      - a STOPBAND is mostly noise, and letting it in inflates the normalizer,
        which makes the gate permissive everywhere;
      - the AXIS EDGES carry extraction artifacts, because the cepstral
        minimum-phase step clamps the magnitude flat past the ends of the
        measured range and the smoothing pads there. Those show up as
        high-S outliers on data that is perfectly minimum-phase (measured:
        max S 8.1 in the top octave of a fixture whose true excess phase is
        zero), and they were the whole reason a full-axis band needed a
        blocking threshold ~50 % higher than a per-driver one.
    So: widest contiguous run within `down_db` of the smoothed peak, then inset
    by `inset_oct` at each end."""
    sm = tunelib.octave_smooth_log(freqs, spl_db, smooth_oct)
    live = sm >= (np.max(sm) - down_db)
    best, start = None, None
    for i, on in enumerate(live):
        if on and start is None:
            start = i
        if start is not None and (not on or i == len(live) - 1):
            end = i if on else i - 1
            if best is None or (end - start) > (best[1] - best[0]):
                best = (start, end)
            start = None
    lo, hi = ((float(freqs[0]), float(freqs[-1])) if best is None
              else (float(freqs[best[0]]), float(freqs[best[1]])))
    lo = max(lo, float(freqs[0]) * 2 ** inset_oct)
    hi = min(hi, float(freqs[-1]) / 2 ** inset_oct)
    if hi <= lo:                      # degenerate/narrow trace -- don't inset
        return ((float(freqs[0]), float(freqs[-1])) if best is None
                else (float(freqs[best[0]]), float(freqs[best[1]])))
    return lo, hi


_VOICE_KEYS = {'tilt': 'tilt_db_per_oct', 'bass': 'bass_shelf_db',
              'presence': 'presence_db', 'air': 'air_db'}


def _parse_voice(pairs):
    knobs = {}
    for p in pairs or []:
        if '=' not in p:
            raise ValueError('--voice expects key=value pairs, e.g. tilt=-0.5 (got %r)' % p)
        k, v = p.split('=', 1)
        if k not in _VOICE_KEYS:
            raise ValueError('unknown voice knob %r -- choose from %s' % (k, sorted(_VOICE_KEYS)))
        knobs[_VOICE_KEYS[k]] = float(v)
    return knobs


def analyze(args):
    freqs = measure.common_grid(20.0, 20000.0, 96)
    report = {}
    notes = []

    positions_db = []
    for p in (args.positions or []):
        f, s, _ph, _coh = measure.load_text_export(p)
        positions_db.append(measure.resample_log(f, s, freqs))

    measurement_phase = meas_axis = None
    if args.measurement:
        f, s, ph, _coh = measure.load_text_export(args.measurement)
        primary_db = measure.resample_log(f, s, freqs)
        measurement_phase, meas_axis = ph, f
    elif positions_db:
        primary_db = positions_db[0]
    else:
        raise ValueError('need --measurement or --positions')

    target_path = ASSETS_DEFAULT_TARGET if args.target == 'default' else args.target
    target_db = measure.load_target(target_path, freqs)

    voice_knobs = _parse_voice(args.voice)
    if voice_knobs:
        target_db = tunelib.voice_target(freqs, target_db, **voice_knobs)
        report['voicing_applied'] = voice_knobs

    anchor = tunelib.target_anchor_offset(freqs, primary_db, target_db)
    dev_db = primary_db - (target_db + anchor)

    report['meta'] = {
        'measurement_file': args.measurement,
        'positions_used': len(positions_db),
        'target_file': ('assets/default_incar_target.txt' if args.target == 'default' else args.target),
        'anchor_offset_db': round(float(anchor), 2),
        'phase_available': measurement_phase is not None,
    }
    if measurement_phase is None:
        notes.append('no phase column in --measurement -- minimum-phase/delay '
                     'decisions are unavailable from this file alone')

    report['tilt'] = {'measured': tunelib.measure_tilt(freqs, primary_db),
                      'target': tunelib.measure_tilt(freqs, target_db)}
    report['deviation_regions'] = _find_regions(freqs, dev_db, args.dev_flag_db)

    # Phase objection per dip a boost would target. Answers the one question
    # the deviation list cannot: is this dip a shape deficit EQ can fill, or a
    # cancellation that will eat the gain? Advisory by design -- see
    # tunelib.boost_gate_verdict on why this informs the proposal table rather
    # than silently dropping bands.
    boost_regions = [r for r in report['deviation_regions']
                     if r['direction'] == 'boost_needed']
    if measurement_phase is None:
        pass                      # already noted above; needs phase
    elif not boost_regions:
        notes.append('boost gate not run -- no dip regions deep enough to flag '
                     '(nothing here tempts a boost)')
    else:
        trust = tuple(args.trust_band) if args.trust_band else _trust_band(freqs, primary_db)
        try:
            fields = tunelib.excess_phase_fields(
                freqs,
                primary_db,
                measure.resample_log(
                    meas_axis,
                    np.rad2deg(np.unwrap(np.deg2rad(measurement_phase))),
                    freqs),
                trust_band=trust)
        except ValueError as exc:
            notes.append('boost gate skipped: %s' % exc)
        else:
            rows = []
            for r in boost_regions:
                width = max(r['f_hi'] - r['f_lo'], 1e-6)
                q = float(np.clip(r['peak_hz'] / width, 0.5, 8.0))
                v = tunelib.boost_gate_verdict(fields, r['peak_hz'], q)
                v.update({'region_hz': [r['f_lo'], r['f_hi']],
                          'peak_hz': r['peak_hz'], 'assumed_q': round(q, 2),
                          'deficit_db': r['peak_db']})
                rows.append(v)
            report['boost_gate'] = {
                'trust_band_hz': [round(float(trust[0]), 1), round(float(trust[1]), 1)],
                'trust_band_source': 'explicit' if args.trust_band else 'derived (-20 dB from peak)',
                'low_confidence': bool(fields['mad_floored']),
                'regions': rows,
                'counts': {v: sum(1 for r in rows if r['verdict'] == v)
                           for v in ('ALLOW', 'WARN', 'BLOCK')},
            }
            if fields['mad_floored']:
                notes.append('boost gate ran on a trace too smooth to support it '
                             '(MAD floored) -- re-export WITHOUT smoothing before '
                             'trusting any verdict below')

    if len(positions_db) >= 3:
        sc = tunelib.spatial_consistency(freqs, positions_db)
        report['spatial_consistency'] = {
            'positions_used': len(positions_db),
            'mean_confidence': round(float(np.mean(sc['conf'])), 2),
            'low_confidence_regions': _find_regions(freqs, sc['spread_db'], args.dev_flag_db),
        }
    elif positions_db:
        notes.append('%d position(s) given -- need >=3 for spatial_consistency '
                     '(fewer positions cannot tell a real dip from a '
                     'position-specific null)' % len(positions_db))

    if args.solo_a and args.solo_b and args.together:
        fa, sa, pa, _ = measure.load_text_export(args.solo_a)
        fb, sb, pb, _ = measure.load_text_export(args.solo_b)
        ft, st, _pt, _ = measure.load_text_export(args.together)
        solo_a_db = measure.resample_log(fa, sa, freqs)
        solo_b_db = measure.resample_log(fb, sb, freqs)
        together_db = measure.resample_log(ft, st, freqs)
        _psum, _csum, interf_db, flagged = tunelib.interference_audit(
            freqs, solo_a_db, solo_b_db, together_db)
        report['interference'] = {
            'flagged_regions': _find_regions(
                freqs, np.where(flagged, interf_db, 0.0), args.dev_flag_db)
        }
        if args.pair_band:
            lo, hi = args.pair_band
            if pa is not None and pb is not None:
                solo_a_c = (10 ** (solo_a_db / 20.0) *
                           np.exp(1j * np.deg2rad(measure.resample_log(fa, pa, freqs))))
                solo_b_c = (10 ** (solo_b_db / 20.0) *
                           np.exp(1j * np.deg2rad(measure.resample_log(fb, pb, freqs))))
                report['crossover_confidence'] = tunelib.crossover_confidence(
                    freqs, solo_a_c, solo_b_c, together_db, (lo, hi))
            else:
                notes.append('--pair-band given but --solo-a/--solo-b have no phase '
                             'column -- crossover_confidence needs phase, ran '
                             'interference_audit only')
    elif args.solo_a or args.solo_b or args.together:
        notes.append('interference audit needs all three of --solo-a, --solo-b, '
                     'and --together -- skipped, only some were given')

    if args.gate_ms:
        report['gating'] = {'gate_ms': args.gate_ms,
                            'trust_floor_hz': round(tunelib.gating_frequency_limit(args.gate_ms), 1),
                            'warning': tunelib.gating_warning(args.gate_ms)}

    if args.afpx:
        xml = afpx.decode(args.afpx)
        report['afpx'] = {'path': args.afpx, 'channels': afpx.channels(xml)}

    report['notes'] = notes
    return report


def check_doc_refs(core_path=None, methodology_path=None):
    """Validate canonical workflow section names and methodology anchors.

    This exists because line-number references kept going stale: another
    session edits methodology.md, every heading shifts, and core workflow silently
    points at the wrong place. It broke three times before being replaced with
    section names, which survive insertions. This check makes the remaining
    drift (a renamed or deleted heading) fail loudly instead of being
    rediscovered by accident. Returns a list of problems; empty means OK."""
    here = os.path.dirname(os.path.abspath(__file__))
    core = (os.fspath(core_path) if core_path is not None else
            os.path.join(here, '..', 'references', 'core_workflow.md'))
    meth = (os.fspath(methodology_path) if methodology_path is not None else
            os.path.join(here, '..', 'references', 'methodology.md'))
    if not (os.path.isfile(core) and os.path.isfile(meth)):
        return ['references/core_workflow.md or references/methodology.md not found']
    import re as _re
    with open(meth, encoding='utf-8') as fh:
        headings = [ln.lstrip('#').strip() for ln in fh if ln.startswith('#')]
    with open(core, encoding='utf-8') as fh:
        core_text = fh.read()
    refs = sorted(set(_re.findall(r'§([^|,\n]+)', core_text)))
    linked_anchors = sorted(set(_re.findall(
        r'\]\((?:[^)\s]*/)?methodology\.md#([^)]+)\)', core_text,
        flags=_re.IGNORECASE)))

    def anchor(heading):
        value = _re.sub(r'[`*_]', '', heading.strip().lower())
        value = _re.sub(r'[^\w\- ]', '', value)
        return _re.sub(r'[ \t]+', '-', value)

    anchors = {anchor(heading) for heading in headings}
    problems = []
    for ref in refs:
        ref = ref.strip()
        if not any(h.lower().startswith(ref.lower()) for h in headings):
            problems.append('core_workflow.md references "§%s" but no such heading in '
                            'methodology.md' % ref)
    for linked_anchor in linked_anchors:
        if linked_anchor.lower() not in anchors:
            problems.append('core_workflow.md has unresolved methodology.md anchor #%s'
                            % linked_anchor)
    return problems


def _selftest():
    """Self-contained self-test -- no real REW/afpx files needed, matching
    afpx.py's/pct6.py's selftest convention. Builds synthetic fixtures on
    measure.common_grid (the same grid analyze() uses internally, so
    resampling is a clean pass-through) and drives analyze() directly with a
    hand-built argparse.Namespace, exactly like the CLI would populate one."""
    import tempfile

    freqs = measure.common_grid(20.0, 20000.0, 96)

    with tempfile.TemporaryDirectory() as d:
        def save(name, *cols):
            path = os.path.join(d, name)
            np.savetxt(path, np.column_stack(cols), fmt='%.4f')
            return path

        spl = 78.0 + tunelib.peaking_db(freqs, 300.0, 2.0, -6.0)   # real, fillable dip
        phase = np.zeros_like(freqs)
        # The measurement gets the dip's TRUE minimum phase plus ordinary
        # measurement noise, so the fixture is physically coherent: a
        # minimum-phase dip is by definition fillable, which is what the boost
        # gate must conclude below. Noise matters -- a noiseless trace collapses
        # the gate's MAD normalizer (see tunelib.excess_phase_fields).
        meas_phase = (np.rad2deg(tunelib.minphase_from_mag(freqs, spl))
                      + np.random.RandomState(3).normal(0, 0.2, len(freqs)))
        meas_path = save('measurement.txt', freqs, spl, meas_phase)
        target_path = save('target.txt', freqs, 76.0 * np.ones_like(freqs))

        rng = np.random.RandomState(7)
        pos_paths = [save('pos_%d.txt' % i,
                          freqs, spl + tunelib.peaking_db(freqs, nc, 8.0, -8.0) +
                          rng.normal(0, 0.15, len(freqs)), phase)
                    for i, nc in enumerate((380.0, 415.0, 450.0))]  # wandering null

        tau = 1.0 / (2 * 415.0)
        A = np.ones_like(freqs) * 10 ** (50 / 20.0)
        Bc = 10 ** (50 / 20.0) * np.exp(-1j * 2 * np.pi * freqs * tau)
        solo_a_path = save('solo_a.txt', freqs, 20 * np.log10(A), np.zeros_like(freqs))
        solo_b_path = save('solo_b.txt', freqs, 20 * np.log10(np.abs(Bc)), np.rad2deg(np.angle(Bc)))
        together_path = save('together.txt', freqs, 20 * np.log10(np.abs(A + Bc)))

        xml = ('<ATF><OC ON="0" CINV="0"><Fil T="1"/></OC>'
              '<OC ON="1" CINV="1"><Fil T="17" F="100" G="-2" Q="1"/></OC></ATF>'
              '<T PM="1" P="0" T="0"/><T PM="2" P="0" T="91"/>')
        afpx_path = os.path.join(d, 'test.afpx')
        afpx._encode_unchecked(xml, afpx_path)

        args = argparse.Namespace(
            measurement=meas_path, positions=pos_paths, target=target_path,
            voice=['tilt=-0.5'], solo_a=solo_a_path, solo_b=solo_b_path,
            together=together_path, pair_band=[200.0, 800.0], gate_ms=2.9,
            afpx=afpx_path, dev_flag_db=2.0, trust_band=None, out=None)
        report = analyze(args)

        assert report['voicing_applied'] == {'tilt_db_per_oct': -0.5}
        assert abs(report['meta']['anchor_offset_db'] - 2.0) < 1.0, \
            'should roughly recover the injected +2dB level offset'
        assert abs(report['tilt']['target']['tilt_db_per_oct'] - (-0.5)) < 0.2
        assert any(200.0 <= r['peak_hz'] <= 400.0 and r['direction'] == 'boost_needed'
                  for r in report['deviation_regions']), \
            'the real -6dB dip @300Hz should be flagged as a boost-needed region'
        assert report['spatial_consistency']['low_confidence_regions'], \
            'the wandering (position-dependent) null should be flagged low-confidence'
        assert not any(280.0 <= r['peak_hz'] <= 320.0
                       for r in report['spatial_consistency']['low_confidence_regions']), \
            'the real dip must NOT be flagged low-confidence -- it holds across positions'
        assert report['interference']['flagged_regions'], \
            'the 415Hz antiphase construction should trip interference_audit'
        assert report['crossover_confidence']['destructive_interference_in_band']
        assert abs(report['gating']['trust_floor_hz'] - 344.8) < 1.0
        assert len(report['afpx']['channels']) == 2
        assert report['afpx']['channels'][1]['polarity'] == 'inverted'
        # The 300 Hz dip is minimum-phase by construction, so the boost gate
        # must NOT object to filling it -- a BLOCK here would mean the gate is
        # rejecting exactly the case EQ is for.
        bg = report['boost_gate']
        assert not bg['low_confidence'], \
            'fixture carries measurement noise; MAD should not have floored: %r' % bg
        dip_rows = [r for r in bg['regions'] if 200.0 <= r['peak_hz'] <= 400.0]
        assert dip_rows, 'the 300Hz dip should have reached the boost gate: %r' % bg
        assert all(r['verdict'] == 'ALLOW' for r in dip_rows), \
            'a minimum-phase dip must not be gated: %r' % dip_rows
        assert bg['trust_band_source'].startswith('derived')
        assert report['notes'] == [], 'a fully-specified run should have no skip notes: %r' % report['notes']
        print('pipeline selftest: analyze() wiring OK (voicing, level anchor, '
             'deviation regions, spatial_consistency, interference_audit, '
             'crossover_confidence, gating, boost_gate, afpx read-through)')

        try:
            analyze(argparse.Namespace(measurement=None, positions=None, target=target_path,
                                       voice=None, solo_a=None, solo_b=None, together=None,
                                       pair_band=None, gate_ms=None, afpx=None,
                                       dev_flag_db=2.0, trust_band=None, out=None))
            raise AssertionError('missing --measurement/--positions should have raised')
        except ValueError:
            pass
        print('pipeline selftest: missing measurement/positions correctly raises')

        try:
            _parse_voice(['foo=1'])
            raise AssertionError('unknown voice knob should have raised')
        except ValueError:
            pass
        print('pipeline selftest: unknown voice knob correctly raises')

    doc_problems = check_doc_refs()
    assert not doc_problems, 'stale doc cross-references:\n  ' + '\n  '.join(doc_problems)
    print('pipeline selftest: core_workflow.md section refs and anchors resolve OK')

    print('\nALL PIPELINE SELFTESTS PASSED')


def main():
    ap = argparse.ArgumentParser(description='Deterministic analysis report for a tuning session.')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('selftest', help='run the self-contained synthetic-fixture self-test')

    pl = sub.add_parser('plan', help='create a versioned AFPX tune-plan draft')
    pl.add_argument('--source', required=True, help='source .afpx tune')
    pl.add_argument('--output', required=True, help='new .afpx output path')
    pl.add_argument('--out', help='write the JSON plan here instead of stdout')

    app = sub.add_parser('apply', help='validate and apply a tune plan')
    app.add_argument('--plan', required=True, help='version-1 JSON tune plan')

    an = sub.add_parser('analyze', help='load measurement(s) + target, emit one JSON report')
    an.add_argument('--measurement')
    an.add_argument('--positions', nargs='+')
    an.add_argument('--target', required=True, help='target curve file, or "default"')
    an.add_argument('--voice', nargs='+', help='e.g. tilt=-0.5 bass=2 presence=1 air=0')
    an.add_argument('--solo-a')
    an.add_argument('--solo-b')
    an.add_argument('--together')
    an.add_argument('--pair-band', nargs=2, type=float, metavar=('LO_HZ', 'HI_HZ'))
    an.add_argument('--gate-ms', type=float)
    an.add_argument('--trust-band', nargs=2, type=float, metavar=('LO_HZ', 'HI_HZ'),
                    help='band this driver actually produces output in, for the '
                         'boost gate; default derived as -20 dB from the peak')
    an.add_argument('--afpx')
    an.add_argument('--dev-flag-db', type=float, default=2.0)
    an.add_argument('--out')

    args = ap.parse_args()
    if args.cmd == 'selftest':
        _selftest()
    elif args.cmd == 'plan':
        draft = create_plan(args.source, args.output)
        text = json.dumps(draft, indent=2)
        if args.out:
            with open(args.out, 'x', encoding='utf-8') as fh:
                fh.write(text)
            print('wrote %s' % args.out)
        else:
            print(text)
    elif args.cmd == 'apply':
        print(json.dumps(apply_plan(args.plan), indent=2))
    elif args.cmd == 'analyze':
        report = analyze(args)
        text = json.dumps(report, indent=2)
        if args.out:
            open(args.out, 'w').write(text)
            print('wrote %s' % args.out)
        else:
            print(text)


if __name__ == '__main__':
    main()
