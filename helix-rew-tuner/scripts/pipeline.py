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
# python pipeline.py propose --measurement <export.txt> | --positions A B C ... --target <file|default>
# python pipeline.py refine --afpx <tune.afpx> --channels N [N...] --dsp-rate HZ --measurement|--positions ... --target ...
# python pipeline.py ab-make --a <A.afpx> --b <B.afpx> --loudness-db X --out-dir <dir> [--confirm-trim]
# python pipeline.py ab-result --key <dir>/.ab_key.json --choices X Y Y X ...
# python pipeline.py mmm-compare --captures now=a.txt d05=b.txt ... --band LO HI [--repeat now2.txt]
# python pipeline.py lr-match --left L.txt --right R.txt [--band 300 6000]
# python pipeline.py verify --report refine.json --before B1 B2 --after A1 A2 --dsp-rate HZ
# python pipeline.py voice-variants --afpx T --out-dir D --bass-channels .. --bass-db -1 1 [--confirm]
# python pipeline.py emma-volume --normal judge.txt --loud judge_plus6.txt
# python pipeline.py noise-check --off system_off.txt --on zero_bit.txt
#   analyze/propose/refine also take: --capture mmm (each --positions file is a
#   repeat MMM run, not a seat), --ambient noise.txt, --cancel-check A B BOTH,
#   --accept-tilt
# python pipeline.py session check --tune <file>  |  session save --tune <file> --answers <json>
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
#                                 never inferred. Bins below the gate's trust
#                                 floor are dropped from analysis AND from
#                                 propose's fit band (both commands take it)
#   --afpx FILE                   read-only context (model, channel map) in the
#                                 report -- never written to
#   --dev-flag-db N (default 2.0) deviation-region flagging threshold
#   --out FILE                    write JSON here instead of stdout
import argparse
import hashlib
import json
import math
import os
import random
import shutil
import sys
import tempfile

import numpy as np

import afpx
import measure
import tunelib
import judging
import audible

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
        if kind not in {'filter_slot', 'delay_samples', 'output_trim', 'phase_rotation'}:
            raise ValueError('%s: unsupported edit kind %r; crossover and polarity '
                             'writes are not supported' % (edit_id, kind))

        allowed = {
            'filter_slot': {'id', 'kind', 'channel', 'slot', 'F', 'Q', 'G', 'type_code'},
            'delay_samples': {'id', 'kind', 'channel', 'samples'},
            'output_trim': {'id', 'kind', 'channel', 'trim_db'},
            'phase_rotation': {'id', 'kind', 'channel', 'degrees'},
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
        elif kind == 'phase_rotation':
            if 'degrees' not in raw_edit:
                raise ValueError('%s: degrees is required' % edit_id)
            degrees = numeric_field(raw_edit, 'degrees')
            key = (kind, channel)
            if key in target_keys:
                raise ValueError('%s: duplicate phase target ch%d' % (edit_id, channel))
            target_keys.add(key)
            tags = afpx.delay_tags(working_xml)
            if not 0 <= channel < len(tags):
                raise ValueError('%s: channel is out of range' % edit_id)
            try:
                current = float(afpx.attrs(tags[channel]).get('P'))
            except (TypeError, ValueError):
                raise ValueError('%s: channel has no readable P= phase attribute' % edit_id)
            if abs(current - degrees) < 1e-9:
                raise ValueError('%s is a no-op; requested phase already matches' % edit_id)
            working_xml = afpx.write_phase_rotation(working_xml, channel, degrees)
            normalized_edit['degrees'] = degrees
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
        elif edit['kind'] == 'phase_rotation':
            working_xml = afpx.write_phase_rotation(
                before, edit['channel'], edit['degrees'])
            result = afpx.verify_phase_write(
                before, working_xml, edit['channel'], edit['degrees'])
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
                            for edit in normalized['edits']),
            allow_phase=any(edit['kind'] == 'phase_rotation'
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


# ------------------------------------------------------------ intake session sidecar
# core_workflow.md step 1: a small record of confirmed intake answers kept next
# to the tune as <tune>.tuner_session.json, bound to the tune's SHA-256 so a
# PC-Tool edit between sessions is detected instead of trusted.
SESSION_FIELDS = ('dsp_model', 'sample_rate_hz', 'channel_map', 'listening_seat',
                  'drive_side', 'rear_channel_routing', 'target_curve_path', 'voicing',
                  'guards')
# Answers read or inferred from the tune file's own bytes; stale once it changes.
SESSION_FILE_DERIVED = ('dsp_model', 'sample_rate_hz', 'channel_map')


def session_path(tune_path):
    return os.fspath(tune_path) + '.tuner_session.json'


def session_check(tune_path):
    """Report the sidecar for `tune_path`: absent, hash-matching, or stale."""
    tune_path = os.fspath(tune_path)
    if not os.path.isfile(tune_path):
        raise ValueError('tune file not found: %s' % tune_path)
    path = session_path(tune_path)
    current = _sha256_file(tune_path)
    report = {'session_path': path, 'exists': os.path.isfile(path),
              'current_sha256': current, 'hash_matches': None,
              'answers': None, 'stale_fields': []}
    if not report['exists']:
        report['guidance'] = 'no prior session: run intake, then session save'
        return report
    try:
        with open(path, encoding='utf-8') as fh:
            stored = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ValueError('cannot read session file %s: %s' % (path, exc)) from exc
    if not isinstance(stored, dict):
        raise ValueError('session file %s is not a JSON object' % path)
    report['hash_matches'] = stored.get('afpx_sha256') == current
    report['answers'] = {k: stored.get(k) for k in SESSION_FIELDS}
    if report['hash_matches']:
        report['guidance'] = ('tune unchanged since recorded: present these answers '
                              'back for a quick "still correct?"')
    else:
        report['stale_fields'] = list(SESSION_FILE_DERIVED)
        report['guidance'] = ('tune file changed since recorded: tell the user, re-run '
                              'afpx.py inspect, and treat stale_fields as unconfirmed; '
                              'offer the other answers back for confirmation')
    return report


def session_save(tune_path, answers):
    """Write the sidecar from confirmed intake answers. Never touches the tune."""
    tune_path = os.fspath(tune_path)
    if not os.path.isfile(tune_path):
        raise ValueError('tune file not found: %s' % tune_path)
    if not isinstance(answers, dict):
        raise ValueError('answers must be a JSON object')
    if 'afpx_sha256' in answers:
        raise ValueError('afpx_sha256 is computed from the tune file; do not supply it')
    unknown = sorted(set(answers) - set(SESSION_FIELDS))
    if unknown:
        raise ValueError('unknown session field(s): %s (allowed: %s)'
                         % (unknown, ', '.join(SESSION_FIELDS)))
    if answers.get('guards') is not None:
        _validate_guards(answers['guards'])
    record = {k: answers.get(k) for k in SESSION_FIELDS}
    record['afpx_sha256'] = _sha256_file(tune_path)
    path = session_path(tune_path)
    fd, tmp = tempfile.mkstemp(prefix='.tuner-session-', suffix='.json',
                               dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(record, fh, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


# Vehicle guards: physical facts about THIS car that no single measurement
# shows, learned once and enforced on every later proposal. Stored in the
# session sidecar because they belong to the car, not to one tune file -- they
# stay valid when the tune changes. Example from a real car: boosting 380-540
# Hz on the mids fills a seated-listener body-reflection null that only an
# MMM shows (a fixed mic reads it as a fixable dip), and the left tweeter has
# two physical notches that EQ cannot raise.
GUARD_TOLERANCE_DB = 0.25        # a boost's skirt may touch a zone by this much


def _validate_guards(guards):
    if not isinstance(guards, dict):
        raise ValueError('guards must be a JSON object: {"no_boost": [...], "max_boost_q": N}')
    unknown = sorted(set(guards) - {'no_boost', 'max_boost_q'})
    if unknown:
        raise ValueError('unknown guard key(s): %s (allowed: no_boost, max_boost_q)' % unknown)
    q = guards.get('max_boost_q')
    if q is not None and not (isinstance(q, (int, float)) and q > 0):
        raise ValueError('max_boost_q must be a positive number')
    zones = guards.get('no_boost') or []
    if not isinstance(zones, list):
        raise ValueError('no_boost must be a list of zones')
    for z in zones:
        if not isinstance(z, dict) or set(z) - {'lo_hz', 'hi_hz', 'channels', 'reason'}:
            raise ValueError('a no_boost zone is {lo_hz, hi_hz, channels, reason}: %r' % (z,))
        lo, hi = z.get('lo_hz'), z.get('hi_hz')
        if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and 0 < lo < hi):
            raise ValueError('no_boost zone needs 0 < lo_hz < hi_hz: %r' % (z,))
        ch = z.get('channels')
        if ch is not None and not (isinstance(ch, list) and ch
                                   and all(isinstance(c, int) and c >= 0 for c in ch)):
            raise ValueError('no_boost channels must be null (every channel) or a list of '
                             'channel indexes: %r' % (z,))
        if not isinstance(z.get('reason'), str) or not z['reason'].strip():
            raise ValueError('every no_boost zone needs a reason -- the physical fact it '
                             'protects: %r' % (z,))
    return guards


def load_guards(tune_path, notes):
    """The sidecar's vehicle guards for `tune_path`, or None."""
    path = session_path(tune_path)
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as fh:
        stored = json.load(fh)
    guards = stored.get('guards') if isinstance(stored, dict) else None
    if not guards:
        return None
    _validate_guards(guards)
    if stored.get('afpx_sha256') != _sha256_file(tune_path):
        notes.append('vehicle guards applied from a session file recorded for an earlier '
                     'version of this tune: they describe the car, not the file, so they '
                     'still hold -- re-confirm them if the car changed')
    return guards


def guard_check(guards, channels=None, freqs=None):
    """(F, Q, G) -> None, or the reason a BOOST breaks a vehicle guard.

    A zone applies when its channels are null, the caller names no channels,
    or the two share one. Cuts are never blocked: relaxing or deepening a cut
    cannot fill a null."""
    if not guards:
        return None
    f = measure.common_grid(20.0, 20000.0, 96) if freqs is None else np.asarray(freqs)
    qmax = guards.get('max_boost_q')
    zones = [z for z in guards.get('no_boost') or []
             if z.get('channels') is None or channels is None
             or set(z['channels']) & set(channels)]

    def check(F, Q, G):
        if G <= 0:
            return None
        if qmax is not None and Q > qmax + 1e-9:
            return 'boost Q %.2f exceeds the max_boost_q %g set for this car' % (Q, qmax)
        rise = tunelib.peaking_db(f, F, Q, G)
        for z in zones:
            sel = (f >= z['lo_hz']) & (f <= z['hi_hz'])
            if np.any(sel) and float(np.max(rise[sel])) > GUARD_TOLERANCE_DB:
                return ('raises %.0f-%.0f Hz by %.1f dB: %s'
                        % (z['lo_hz'], z['hi_hz'], float(np.max(rise[sel])), z['reason']))
        return None
    return check


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


def _load_session(args, freqs):
    """Load measurement/positions/target the same way for analyze and propose.

    Tonal deviation comes from the level-aligned mean when two or more
    positions exist -- EQ what is common, not what one mic spot happened to
    see (methodology.md §Multi-position variance). The phase-bearing
    --measurement, when given, stays the trace for phase-based checks.

    Evidence rules enforced here rather than left to the instructions:
      - only MEASURED bins count: `support` is the intersection of every
        trace's measured range (and the gate's trust floor, with --gate-ms);
        anchoring and fitting are confined to it;
      - an identical trace given twice is ONE position, not two: duplicates
        are dropped before they can inflate confidence."""
    notes = []
    profile = _load_capture_profile(args, notes)
    support = np.ones_like(freqs, dtype=bool)
    raw_positions, positions_db, kept_index = {}, [], []
    for i, p in enumerate(args.positions or []):
        f, s, _ph, _coh = measure.load_text_export(p)
        raw_positions[p if p not in raw_positions else '%s (#%d)' % (p, i + 1)] = (f, s)
    duplicates = tunelib.detect_duplicate_traces(raw_positions) if raw_positions else []
    dropped = {label for grp in duplicates for label in grp[1:]}
    for grp in duplicates:
        notes.append('positions %s are the SAME capture -- counted once; a repeated file '
                     'is not a second mic position' % ', '.join(grp))
    for i, (p, (f, s)) in enumerate(raw_positions.items()):
        if p in dropped:
            continue
        kept_index.append(i)
        positions_db.append(measure.resample_log(f, s, freqs))
        support &= measure.support_mask(f, freqs)

    capture = getattr(args, 'capture', None) or 'sweep'
    measurement_phase = meas_axis = None
    measurement_header = None
    if args.measurement:
        f, s, ph, _coh = measure.load_text_export(args.measurement)
        primary_db = measure.resample_log(f, s, freqs)
        measurement_phase, meas_axis = ph, f
        measurement_header = measure.read_export_header(args.measurement)
        support &= measure.support_mask(f, freqs)
        if capture == 'mmm' and ph is not None:
            notes.append('phase column ignored: a moving-mic RTA average has no meaningful '
                         'phase, so nothing phase-based is run on it')
            measurement_phase = None
    elif positions_db:
        primary_db = positions_db[0]
    else:
        raise ValueError('need --measurement or --positions')

    ambient = None
    if getattr(args, 'ambient', None):
        fa, sa, _pa, _ca = measure.load_text_export(args.ambient)
        amb_db = measure.resample_log(fa, sa, freqs)
        raw = positions_db + ([primary_db] if args.measurement else [])
        ok, snr = tunelib.snr_support(np.min(np.vstack(raw), axis=0), amb_db,
                                      getattr(args, 'min_snr_db', 10.0))
        ok &= measure.support_mask(fa, freqs)
        lost = _mask_runs(freqs, support & ~ok)
        live = support & ok
        ambient = {'file': args.ambient, 'min_snr_db': getattr(args, 'min_snr_db', 10.0),
                   'excluded_hz': lost,
                   'median_snr_db': round(float(np.median(snr[live])), 1) if np.any(live) else None}
        if lost:
            notes.append('excluded where the capture is less than %.0f dB above the ambient '
                         'capture (an RTA adds the noise in, so a dip there can be noise-filled): '
                         '%s' % (ambient['min_snr_db'], ', '.join(lost)))
        support &= ok

    if not np.all(support) and np.any(support):
        covered = freqs[support]
        notes.append('analysis confined to the measured range %.0f-%.0f Hz -- the '
                     'traces hold no data outside it' % (covered[0], covered[-1]))
    gate_ms = getattr(args, 'gate_ms', None)
    gate_floor = None
    if gate_ms:
        gate_floor = tunelib.gating_frequency_limit(gate_ms)
        support &= freqs >= gate_floor
    if not np.any(support):
        raise ValueError('no frequency is covered by every trace (and the gate floor) -- '
                         'nothing measured to analyse')

    target_path = ASSETS_DEFAULT_TARGET if args.target == 'default' else args.target
    target_db = measure.load_target(target_path, freqs)
    voice_knobs = _parse_voice(args.voice)
    if voice_knobs:
        target_db = tunelib.voice_target(freqs, target_db, **voice_knobs)

    sc = aligned = None
    repeatability = None
    if len(positions_db) >= 2:
        sc = tunelib.spatial_consistency(freqs, positions_db, min_positions=2)
        aligned = np.vstack(positions_db) - np.asarray(sc['level_offsets_db'])[:, None]
        basis_db = sc['mean_db']
        source = ('mean of %d MMM runs' if capture == 'mmm' else
                  'mean of %d positions') % len(positions_db)
        if capture == 'mmm':
            repeatability = tunelib.capture_repeatability(freqs, positions_db, support=support)
    else:
        basis_db = primary_db
        source = 'MMM average (one run)' if capture == 'mmm' else 'single position'
    # Two positions cannot separate a real dip from a seat-specific null, so
    # only three or more earn a mask/confidence.
    authority = sc if len(positions_db) >= 3 else None
    conf = authority['conf'] * support if authority else None
    mask = authority['mask'] & support if authority else (None if np.all(support) else support)
    anchor_conf = conf if conf is not None else support.astype(float)
    anchor = tunelib.target_anchor_offset(freqs, basis_db, target_db, confidence=anchor_conf)
    validated = tunelib.validated_anchor_offset(freqs, basis_db, target_db, confidence=anchor_conf)
    if validated != anchor:
        notes.append('mid-band anchor adjusted %+.2f dB: independent low/high reference bands agree' % (validated - anchor))
        anchor = validated
    return {
        'positions_db': positions_db, 'kept_index': kept_index, 'primary_db': primary_db,
        'measurement_phase': measurement_phase, 'meas_axis': meas_axis,
        'measurement_header': measurement_header,
        'target_db': target_db, 'voice_knobs': voice_knobs,
        'basis_db': basis_db, 'deviation_source': source, 'aligned': aligned,
        'mask': mask, 'conf': conf, 'support': support, 'gate_floor_hz': gate_floor,
        'duplicates': duplicates, 'notes': notes,
        'anchor': anchor, 'dev_db': basis_db - (target_db + anchor),
        'capture': capture, 'repeatability': repeatability, 'ambient': ambient,
        'profile': profile,
    }


def _load_capture_profile(args, notes):
    """The REW setup the captures were made with, checked against REW's rules.
    A problem refuses the session; warnings become notes."""
    path = getattr(args, 'capture_profile', None)
    if not path:
        return None
    with open(path, encoding='utf-8') as fh:
        raw = json.load(fh)
    chk = tunelib.check_capture_profile(raw)
    if chk['problems']:
        raise ValueError('capture profile %s: %s' % (path, '; '.join(chk['problems'])))
    notes.extend('capture profile: %s' % w for w in chk['warnings'])
    return {'file': path, 'id': chk['profile_id'], 'warnings': chk['warnings']}


def _mask_runs(freqs, mask):
    """Contiguous True runs of `mask` as 'LO-HI Hz' strings."""
    runs, start = [], None
    for i, on in enumerate(mask):
        if on and start is None:
            start = i
        if start is not None and (not on or i == len(mask) - 1):
            end = i if on else i - 1
            runs.append('%.0f-%.0f Hz' % (freqs[start], freqs[end]))
            start = None
    return runs


def _rta_tilt(freqs, sess, notes, refuse, accept=False):
    """MMM only: catch an RTA in the wrong mode before it tilts the tune.
    refuse=True for a full-system proposal; analyze only notes it (it may be
    looking at a solo)."""
    if sess['capture'] != 'mmm':
        return None
    live = sess['support']
    tilt = tunelib.measure_tilt(freqs[live], sess['basis_db'][live])['tilt_db_per_oct']
    problem = tunelib.rta_tilt_check(tilt)
    recorded = sess.get('profile') is not None
    if problem and refuse and not accept and not recorded:
        raise ValueError(problem + ' (record the setup with --capture-profile, or pass '
                         '--accept-tilt only if this really is the car)')
    if problem and recorded:
        notes.append(problem + ' -- but the recorded capture profile says the RTA setup was '
                     'right: confirm the car really is this far off before voicing')
    elif problem:
        notes.append(problem + ('' if refuse else ' -- if this is a full-system capture'))
    return {'tilt_db_per_oct': tilt, 'problem': problem}


def _cancel_checks(args, freqs):
    """Magnitude-only cancellation maps from (part A, part B, both together)
    captures at one playback level: where the pair measures BELOW the power
    sum of its halves, the dip is destructive summation and no boost fills it."""
    checks = []
    for files in getattr(args, 'cancel_check', None) or []:
        traces, live = [], np.ones_like(freqs, dtype=bool)
        for path in files:
            f, s, _ph, _c = measure.load_text_export(path)
            traces.append(measure.resample_log(f, s, freqs))
            live &= measure.support_mask(f, freqs)
        _ps, _cs, interf, flagged = tunelib.interference_audit(freqs, *traces)
        flagged = flagged & live
        checks.append({'files': list(files), 'flagged': flagged,
                       'cancellation_hz': _mask_runs(freqs, flagged)})
    return checks


def _cancel_verdict(freqs, checks, F, Q):
    order = {'ALLOW': 0, 'WARN': 1, 'BLOCK': 2}
    verdict = 'ALLOW'
    for c in checks:
        v = tunelib.cancellation_boost_verdict(freqs, c['flagged'], F, Q)
        verdict = max(verdict, v, key=order.get)
    return verdict


def _capture_report(sess, tilt):
    public = tunelib.public_repeatability(sess['repeatability'])
    return {'method': sess['capture'],
            'runs': len(sess['positions_db']) or 1,
            'repeatability': public,
            'verification_noise_db': (public or {}).get('noise_db'),
            'rta_tilt': tilt, 'ambient': sess['ambient'],
            'profile': sess.get('profile')}


MMM_SINGLE_RUN_Q_MAX = 4.0


SESSION_ANCHOR_BAND = (300.0, 3000.0)    # tunelib.target_anchor_offset's first choice


def _band_anchor(freqs, sess, band):
    """The level anchor taken inside `band` instead of the session default."""
    conf = sess['conf'] if sess['conf'] is not None else sess['support'].astype(float)
    return tunelib.target_anchor_offset(freqs, sess['basis_db'], sess['target_db'],
                                        confidence=conf, anchor_bands=(tuple(band),))


def _outside_anchor(band, min_cover=0.8):
    """True when `band` holds too little of the session anchor band for that
    anchor to stand for it -- a fit confined to one driver's passband (a
    tweeter above it, a sub below it). Decided from the band the user gave,
    not from the trace: an in-car solo's stopband is often filled with road
    noise louder than the driver itself (measured: 50 dB at 25 Hz on a
    tweeter solo playing 38 dB), so the trace cannot be trusted to say where
    the driver plays."""
    a_lo, a_hi = SESSION_ANCHOR_BAND
    inside = max(0.0, np.log2(min(band[1], a_hi) / max(band[0], a_lo)))
    return inside < min_cover * np.log2(a_hi / a_lo)


def _bass_note(balance):
    """The low end as a whole off target is a level decision, said plainly."""
    v, db = balance['verdict'], balance['sub_region_db']
    if v == 'bass_heavy':
        return ('25-80 Hz sits %+.1f dB above the anchored target as a whole: that is a sub/'
                'midbass LEVEL question before it is an EQ one -- lower the sub channel '
                '(output trim) or the sub amplifier gain, then re-measure before fitting '
                'bells to what is left' % db)
    if v == 'bass_light':
        return ('25-80 Hz sits %+.1f dB below the anchored target as a whole: a LEVEL '
                'question first. Trims here only cut, so raise the sub amplifier gain (or '
                'lower every other channel equally) rather than boosting with bells -- and '
                'confirm the deficit is not a sub/midbass cancellation (junction) first' % db)
    return None


def _smoothing_note(sess):
    """A boost-gate verdict on a smoothed export needs saying so."""
    hdr = sess.get('measurement_header') or {}
    if hdr.get('unsmoothed') is False:
        return ('--measurement header says it was smoothed (%s) -- the boost gate reads '
                'phase anomalies best on an UNSMOOTHED export (REW File > Export, no '
                'smoothing); the REW API cannot supply one' % hdr['smoothing'])
    return None


def _phase_fields(args, freqs, sess):
    chk = measure.phase_step_check(sess['meas_axis'], sess['measurement_phase'])
    trust = tuple(args.trust_band) if args.trust_band else _trust_band(freqs, sess['primary_db'])
    covered = freqs[sess['support']]
    hi = float(covered[-1]) if chk['ok'] else min(float(covered[-1]), chk['first_bad_hz'])
    trust = (max(trust[0], float(covered[0])), min(trust[1], hi))
    if trust[1] <= trust[0]:
        raise ValueError('no band left where the phase is measured and unwraps reliably')
    fields = tunelib.excess_phase_fields(
        freqs,
        sess['primary_db'],
        measure.resample_phase(sess['meas_axis'], sess['measurement_phase'], freqs),
        trust_band=trust)
    return trust, fields


def analyze(args):
    freqs = measure.common_grid(20.0, 20000.0, 96)
    report = {}
    notes = []

    sess = _load_session(args, freqs)
    notes.extend(sess['notes'])
    positions_db = sess['positions_db']
    measurement_phase, target_db = sess['measurement_phase'], sess['target_db']
    anchor, dev_db = sess['anchor'], sess['dev_db']
    support = sess['support']
    report['judging'] = judging.scorecard(freqs, dev_db, dev_db, support)
    report['judging']['unassessed'] = ['distortion', 'compression', 'imaging', 'decay', 'headroom', 'listening']
    if sess['voice_knobs']:
        report['voicing_applied'] = sess['voice_knobs']

    tilt = _rta_tilt(freqs, sess, notes, refuse=False)
    report['capture'] = _capture_report(sess, tilt)
    cancel = _cancel_checks(args, freqs)
    if cancel:
        report['cancellation'] = [{'files': c['files'], 'cancellation_hz': c['cancellation_hz']}
                                  for c in cancel]
    report['meta'] = {
        'measurement_file': args.measurement,
        'positions_used': len(positions_db),
        'deviation_source': sess['deviation_source'],
        'target_file': ('assets/default_incar_target.txt' if args.target == 'default' else args.target),
        'anchor_offset_db': round(float(anchor), 2),
        'phase_available': measurement_phase is not None,
        'measured_range_hz': [round(float(freqs[support][0]), 1),
                              round(float(freqs[support][-1]), 1)],
        'duplicate_positions': sess['duplicates'],
        'measurement_smoothing': (sess['measurement_header'] or {}).get('smoothing'),
    }
    if measurement_phase is None and sess['capture'] != 'mmm':
        if args.measurement:
            notes.append('no phase column in --measurement -- minimum-phase/delay '
                         'decisions are unavailable from this file alone')
        else:
            notes.append('--positions are used for magnitude only: give one fixed-position '
                         'export with phase as --measurement for the boost gate and other '
                         'phase-based checks')

    report['tilt'] = {'measured': tunelib.measure_tilt(freqs, sess['basis_db']),
                      'target': tunelib.measure_tilt(freqs, target_db)}
    report['bass_balance'] = tunelib.bass_balance(freqs, dev_db, support)
    report['emma_bands'] = tunelib.emma_band_balance(freqs, dev_db, support)
    note = _bass_note(report['bass_balance'])
    if note:
        notes.append(note)
    report['deviation_regions'] = _find_regions(freqs, np.where(support, dev_db, 0.0),
                                                args.dev_flag_db)

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
        try:
            trust, fields = _phase_fields(args, freqs, sess)
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
            elif _smoothing_note(sess):
                notes.append(_smoothing_note(sess))

    if len(positions_db) >= 3:
        sc = tunelib.spatial_consistency(freqs, positions_db)
        report['spatial_consistency'] = {
            'positions_used': len(positions_db),
            'mean_confidence': round(float(np.mean(sc['conf'])), 2),
            'low_confidence_regions': _find_regions(freqs, sc['spread_db'], args.dev_flag_db),
        }
    elif positions_db and sess['capture'] != 'mmm':
        notes.append('%d position(s) given -- need >=3 for spatial_consistency '
                     '(fewer positions cannot tell a real dip from a '
                     'position-specific null)' % len(positions_db))

    if args.solo_a and args.solo_b and args.together:
        solo_a = measure.load_complex(args.solo_a, freqs, require_phase=False)
        solo_b = measure.load_complex(args.solo_b, freqs, require_phase=False)
        together = measure.load_complex(args.together, freqs, require_phase=False)
        pair_support = solo_a['support'] & solo_b['support'] & together['support']
        _psum, _csum, interf_db, flagged = tunelib.interference_audit(
            freqs, solo_a['db'], solo_b['db'], together['db'])
        report['interference'] = {
            'flagged_regions': _find_regions(
                freqs, np.where(flagged & pair_support, interf_db, 0.0), args.dev_flag_db)
        }
        if args.pair_band:
            lo, hi = args.pair_band
            if solo_a['complex'] is not None and solo_b['complex'] is not None:
                refusal = (measure.shared_timing_problem(solo_a, solo_b)
                           or measure.unwrap_problem(solo_a, solo_b, band=(lo, hi)))
                if refusal:
                    notes.append('crossover_confidence skipped: %s' % refusal)
                else:
                    report['crossover_confidence'] = tunelib.crossover_confidence(
                        freqs, solo_a['complex'], solo_b['complex'], together['db'], (lo, hi))
                    unstated = measure.timing_unstated(solo_a, solo_b)
                    if unstated:
                        notes.append(_unstated_note(unstated))
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
                            'warning': tunelib.gating_warning(args.gate_ms),
                            'applied': 'bins below the trust floor are excluded from this report'}

    if args.afpx:
        xml = afpx.decode(args.afpx)
        report['afpx'] = {'path': args.afpx, 'channels': afpx.channels(xml)}

    report['notes'] = notes
    return report


def _sitting_groups(args, sess, notes):
    """One sitting label per kept position (--sittings), or None.

    Held-out validation then withholds a whole sitting per fold
    (tunelib.held_out_band_validation `groups`)."""
    labels = getattr(args, 'sittings', None)
    if not labels:
        if len(sess['positions_db']) >= 3:
            notes.append('held-out validation withheld one POSITION at a time: positions from '
                         'the same sitting share its seat, mic and noise, so label them with '
                         '--sittings for a check that has to survive a whole new sitting')
        return None
    if len(labels) != len(args.positions or []):
        raise ValueError('--sittings needs one label per --positions file (%d given for %d)'
                         % (len(labels), len(args.positions or [])))
    groups = [labels[i] for i in sess['kept_index']]
    if len(set(groups)) < 3:
        notes.append('only %d sitting(s): held-out validation needs 3+ sittings, so it was '
                     'not run -- these positions agree with each other, not with another day'
                     % len(set(groups)))
    return groups


PROPOSE_FIT_BAND = (60.0, 12000.0)


def propose(args):
    """Deterministic EQ proposal: fit, gate boosts, predict. Writes nothing.

    One entry point instead of re-deriving the fitter call each session, so
    the same data always gets the same proposal. The judgment calls stay
    with the agent and the user: every band still needs a stated reason,
    per-edit confirmation, and pipeline.py plan/apply to be written."""
    freqs = measure.common_grid(20.0, 20000.0, 96)
    notes = []
    sess = _load_session(args, freqs)
    notes.extend(sess['notes'])
    band = tuple(args.fit_band) if args.fit_band else PROPOSE_FIT_BAND
    covered = freqs[sess['support']]
    clipped = (max(band[0], float(covered[0])), min(band[1], float(covered[-1])))
    if clipped != band:
        if clipped[1] <= clipped[0]:
            raise ValueError('fit band %g-%g Hz lies wholly outside the measured/trusted range '
                             '%.0f-%.0f Hz' % (band[0], band[1], covered[0], covered[-1]))
        notes.append('fit band narrowed from %g-%g Hz to %.0f-%.0f Hz: only measured%s bins '
                     'may be corrected' % (band[0], band[1], clipped[0], clipped[1],
                                           ', gate-trusted' if sess['gate_floor_hz'] else ''))
        band = clipped
    solo_band = bool(args.fit_band) and _outside_anchor(band)
    if solo_band:
        # Fitting one driver's passband: the 300-3000 Hz anchor sits in its
        # stopband and would read the whole passband as one level error.
        anchor = _band_anchor(freqs, sess, band)
        notes.append('fit band lies outside the %.0f-%.0f Hz session anchor: level anchored '
                     'inside %.0f-%.0f Hz instead (%+.1f dB) -- shape, not loudness, is judged '
                     'here; set the channel level separately' % (SESSION_ANCHOR_BAND + band
                                                                 + (anchor - sess['anchor'],)))
        sess['anchor'] = anchor
        sess['dev_db'] = sess['basis_db'] - (sess['target_db'] + anchor)
    mask, conf, dev_db = sess['mask'], sess['conf'], sess['dev_db']
    evidence_kw, evidence = audible.fitting_evidence(args, freqs, sess)
    partner_db = evidence.pop('partner_db', None)

    tilt = None
    if not solo_band:
        tilt = _rta_tilt(freqs, sess, notes, refuse=True,
                         accept=getattr(args, 'accept_tilt', False))
    mmm = sess['capture'] == 'mmm'
    unit = 'run' if mmm else 'position'
    qkw = {}
    if mmm and sess['repeatability'] is None:
        qkw = {'q_lim': (0.5, MMM_SINGLE_RUN_Q_MAX)}
        notes.append('one MMM run: filters are kept broad (Q <= %g) -- a narrower feature '
                     'needs a repeat run to show it is real' % MMM_SINGLE_RUN_Q_MAX)
    qkw.update(evidence_kw)
    held_out = None
    band_validation = {}
    groups = _sitting_groups(args, sess, notes)
    if sess['aligned'] is not None and sess['aligned'].shape[0] >= 3 and (
            groups is None or len(set(groups)) >= 3):
        deviations = sess['aligned'] - (sess['target_db'] + sess['anchor'])
        # Leave-one-position-out: the proposal must help positions it was not
        # fitted on (tunelib.held_out_band_validation). Its final fit IS the
        # proposal, so validation and proposal cannot drift apart.
        held_out = tunelib.held_out_band_validation(
            freqs, deviations, band, mask=mask, conf=conf,
            fitter_kwargs=dict({'n_bands_max': args.max_bands}, **qkw), groups=groups)
        bands = [(r['f_hz'], r['q'], r['gain_db']) for r in held_out['bands']]
        band_validation = {(r['f_hz'], r['q'], r['gain_db']): r for r in held_out['bands']}
        fit_report = {'held_out_verdict': held_out['verdict'],
                      'median_held_out_gain_db': held_out['median_held_out_gain_db'],
                      'worst_held_out_gain_db': held_out['worst_held_out_gain_db']}
        if held_out['verdict'] == 'not_validated':
            notes.append('held-out validation FAILED: refitted without each %s in '
                         'turn, the proposal did not reliably help the %s left out -- '
                         'treat every band as unconfirmed until more %ss agree'
                         % (unit, unit, unit))
    elif sess['aligned'] is not None:
        deviations = sess['aligned'] - (sess['target_db'] + sess['anchor'])
        bands, fit_report = tunelib.fit_peq_robust(
            freqs, deviations, band, n_bands_max=args.max_bands,
            mask=mask, conf=conf, fit_smoothed=True, **qkw)
        if groups is None and mmm:
            notes.append('two MMM runs: fitted jointly; their repeatability (%.2f dB) is the '
                         'resolution any re-measure must beat' % sess['repeatability']['noise_db'])
        elif groups is None:
            notes.append('two positions: fitted jointly, but held-out validation needs 3+ '
                         'positions, so no band carries a generalisation check')
    else:
        deviations = None
        bands, fit_report = tunelib.fit_peq(
            freqs, dev_db, band, n_bands_max=args.max_bands, mask=mask, fit_smoothed=True,
            cut_seed_retry=mmm, **qkw)
        if mmm:
            notes.append('one MMM run: already a spatial average, so the fit is not chasing '
                         'one mic spot -- capture the same tune a second time to measure '
                         'repeatability, which verification and mmm-compare need')
        else:
            notes.append('single position: the fit cannot tell a real feature from '
                         'a seat-specific one, and held-out validation needs 3+ '
                         'positions -- capture them (or MMM) before trusting narrow bands')
    bands, stacked = tunelib.limit_stacked_boosts(freqs, bands, band=band, dev_db=dev_db)
    bands, limited = audible.enforce_ceiling(freqs, bands, evidence_kw.get('boost_ceiling_db'))

    gate = {}
    has_boost = any(g > 0 for _f, _q, g in bands)
    if sess['measurement_phase'] is not None and has_boost:
        try:
            _trust, fields = _phase_fields(args, freqs, sess)
            rows, _summary = tunelib.gate_boost_bands(fields, bands)
            gate = {(r['f_hz'], r['q'], r['gain_db']): r['verdict'] for r in rows}
            if fields['mad_floored']:
                notes.append('boost gate ran on a trace too smooth to support it -- '
                             're-export WITHOUT smoothing before trusting it')
            elif _smoothing_note(sess):
                notes.append(_smoothing_note(sess))
        except ValueError as exc:
            notes.append('boost gate skipped: %s' % exc)
    elif has_boost and _cancel_checks(args, freqs):
        cancel = _cancel_checks(args, freqs)
        for F, Q, G in bands:
            if G > 0:
                gate[(float(F), float(Q), float(G))] = _cancel_verdict(freqs, cancel, F, Q)
        notes.append('no phase: boosts were checked against %d measured pair(s) instead -- '
                     'a boost into a dip the pair creates together (measured sum below the '
                     'power sum of its halves) is BLOCKed' % len(cancel))
    elif has_boost and mmm:
        notes.append('boosts are UNGATED: an MMM capture has no phase. Give --cancel-check '
                     'LEFT RIGHT BOTH (and SUB MIDS SUB+MIDS), captured at one playback level, '
                     'to check them for cancellation from magnitude alone')
    elif has_boost:
        notes.append('boosts are UNGATED: no phase column in --measurement, so the '
                     'boost gate could not check them for cancellation '
                     '(methodology.md §The boost gate)')

    gcheck = None
    if args.session_tune:
        gcheck = guard_check(load_guards(args.session_tune, notes), args.channels, freqs)
        if gcheck is None:
            notes.append('no vehicle guards recorded in the session file for %s'
                         % args.session_tune)
    kept, rejected, needs_trial = [], [], []
    for F, Q, G in bands:
        tunelib.validate_peq_band(F, Q, G)
        verdict = gate.get((float(F), float(Q), float(G)))
        row = {'f_hz': F, 'q': Q, 'gain_db': G,
               'kind': 'boost' if G > 0 else 'cut', 'boost_gate': verdict}
        validation = band_validation.get((F, Q, G))
        if validation:
            for key in ('confidence', 'action', 'stability', 'held_out_help',
                        'median_held_out_gain_db', 'worst_held_out_dig_db'):
                row[key] = validation[key]
            if validation['action'] == 'DO NOT APPLY':
                row['reason'] = ('held-out validation: refitted without each position in '
                                 'turn, this band did not reliably come back or did not help '
                                 'the position left out -- it is fitted to particular seats')
                rejected.append(row)
                continue
        why = gcheck(F, Q, G) if gcheck else None
        if why:
            row['reason'] = 'vehicle guard: %s' % why
            rejected.append(row)
            continue
        if verdict == 'BLOCK':
            row['reason'] = ('boost gate BLOCK: the dip is a cancellation (phase-anomalous, or '
                             'the pair sums below its power sum); gain would be eaten')
            rejected.append(row)
            continue
        if verdict == 'WARN':
            row['caution'] = 're-measure with the mic moved ~10 cm before proposing this boost'
        if mmm:
            support_v = tunelib.mmm_change_support(
                freqs, tunelib.peaking_db(freqs, F, Q, G), tunelib.peq_region(F, Q),
                sess['repeatability'])
            row['repeatability'] = support_v
            if support_v['status'] == 'below_repeatability':
                row['reason'] = ('smaller than the repeat-capture variation where it acts '
                                 '(%.2f vs %.2f dB): a re-capture could not confirm it'
                                 % (support_v['local_change_db'],
                                    support_v['local_resolution_db']))
                rejected.append(row)
                continue
            if G > 0 and verdict is None:
                row['reason'] = ('boost with no cancellation evidence (no phase, no '
                                 '--cancel-check): write it ALONE, re-capture, and keep it '
                                 'only if pipeline.py verify confirms it')
                needs_trial.append(row)
                continue
        kept.append(row)
    for F, Q, G in stacked:
        rejected.append({'f_hz': F, 'q': Q, 'gain_db': G, 'kind': 'boost', 'boost_gate': None,
                         'reason': 'stacks on another boost past the +3 dB boost limit: the fit '
                                   'was filling one dip with several bands'})
    for F, Q, G in limited:
        rejected.append({'f_hz': F, 'q': Q, 'gain_db': G, 'reason': 'exceeds measured additional-gain ceiling'})
    final = [(r['f_hz'], r['q'], r['gain_db']) for r in kept]

    eq = tunelib.cascade_db(freqs, final)
    smoothed_before = tunelib.erb_smooth(freqs, dev_db)
    smoothed_after = tunelib.erb_smooth(freqs, dev_db + eq)
    for row in kept:
        i = int(np.argmin(np.abs(freqs - row['f_hz'])))
        row['predicted_deviation_db'] = {'before': round(float(smoothed_before[i]), 2),
                                         'after': round(float(smoothed_after[i]), 2)}
    prediction = {
        'score_before_db': round(tunelib.audibility_score(
            freqs, dev_db, band=band, mask=mask, conf=conf), 3),
        'score_after_db': round(tunelib.audibility_score(
            freqs, dev_db + eq, band=band, mask=mask, conf=conf), 3),
        'max_cascade_boost_db': round(float(np.max(eq)), 2) if final else 0.0,
    }
    if deviations is not None:
        prediction['position_scores_before_db'] = [
            round(tunelib.audibility_score(freqs, d, band=band), 3) for d in deviations]
        prediction['position_scores_after_db'] = [
            round(tunelib.audibility_score(freqs, d + eq, band=band), 3) for d in deviations]
    if not final:
        notes.append('no band earned its place: nothing here is both fixable and '
                     'worth a filter -- stopping is a valid outcome')
    support = sess['support']
    # A band-limited solo's region below the fit band is its stopband, not a
    # deviation; and its low end says nothing about the system's bass balance.
    below = [] if solo_band else _find_regions(
        freqs, np.where(support & (freqs < band[0]), dev_db, 0.0), 2.0)
    if below:
        notes.append('deviation below the fit band (%s) was NOT considered -- for the sub '
                     'region run propose again with --fit-band on the sub measurement, or treat '
                     'it as a level question (bass_balance)'
                     % ', '.join('%.0f-%.0f Hz %+.1f dB' % (r['f_lo'], r['f_hi'], r['peak_db'])
                                 for r in below))
    balance = None if solo_band else tunelib.bass_balance(freqs, dev_db, support)
    note = _bass_note(balance) if balance else None
    if note:
        notes.append(note)
    if final:
        prediction['loudness_change_db'] = round(tunelib.loudness_change_db(
            freqs[support], sess['basis_db'][support], (sess['basis_db'] + eq)[support]), 2)

    margin = max(0.5, 2 * (sess['repeatability'] or {}).get('noise_db', 0.0))
    judgement = judging.scorecard(freqs, dev_db, dev_db + eq,
                                 sess['support'] & (freqs >= band[0]) & (freqs <= band[1]), margin)
    if partner_db is not None:
        judgement['partner_balance'] = audible.partner_guard(freqs, dev_db, partner_db, eq, sess['support'])
        if judgement['partner_balance']['status'] == 'regressed':
            judgement['verdict'] = 'regressed'
    judgement['junction_guard'] = audible.junction_guard(args, final, probe)
    if judgement['junction_guard']['status'] == 'hold_for_review':
        judgement['verdict'] = 'regressed'
    judgement['evidence'] = evidence
    judgement['predicted_not_measured'] = True
    judgement['additional_peq_peak_gain_db'] = round(float(np.max(eq)), 3)
    judgement['headroom_status'] = 'unknown: full existing chain, routing and levels required'
    judgement['apply_recommendation'] = ('hold_for_review' if judgement['verdict'] == 'regressed' else 'review_bands')
    if judgement['verdict'] == 'regressed':
        notes.append('judging regression veto: hold this proposal; a regional or score-component loss exceeds the margin')
    return {
        'judging': judgement,
        'meta': {'measurement_file': args.measurement,
                 'positions_used': len(sess['positions_db']),
                 'sittings_used': None if groups is None else len(set(groups)),
                 'deviation_source': sess['deviation_source'],
                 'fit_band_hz': list(band),
                 'capture': _capture_report(sess, tilt),
                 'gate_floor_hz': (round(sess['gate_floor_hz'], 1)
                                   if sess['gate_floor_hz'] else None),
                 'duplicate_positions': sess['duplicates'],
                 'anchor_offset_db': round(float(sess['anchor']), 2),
                 'voicing_applied': sess['voice_knobs'] or None,
                 # Bands are modelled at this rate. On a 48 kHz unit a band above
                 # ~6 kHz lands up to ~0.4 dB differently; refine takes --dsp-rate.
                 'prediction_sample_rate_hz': tunelib.FS},
        'tilt': {'measured': tunelib.measure_tilt(freqs, sess['basis_db']),
                 'target': tunelib.measure_tilt(freqs, sess['target_db'])},
        'proposal': {'bands': kept, 'rejected': rejected, 'needs_trial': needs_trial},
        'bass_balance': balance,
        'held_out_validation': None if held_out is None else {
            'verdict': held_out['verdict'], 'folds': held_out['folds'],
            'median_held_out_gain_db': held_out['median_held_out_gain_db'],
            'worst_held_out_gain_db': held_out['worst_held_out_gain_db']},
        'prediction': prediction,
        'fitter': {k: v for k, v in fit_report.items()
                   if isinstance(v, (int, float, bool, str))},
        'notes': notes,
        'predicted_not_measured': True,
        'next_step': ('present each band with its reason and predicted before/after; '
                      'write only user-confirmed bands via pipeline.py plan/apply, '
                      'then re-measure'),
    }


def source_audit(args):
    """Is the signal ENTERING the DSP level-independent? (roadmap item 01)

    Everything else in this skill assumes it is. Nothing else can check."""
    freqs = measure.common_grid(20.0, 20000.0, 96)
    traces, levels, notes = [], [], []
    for spec in args.at:
        path, _, lvl = spec.partition('=')
        if not lvl:
            raise ValueError('--at wants PATH=DB (the volume setting in dB '
                             'relative to your reference), got %r' % spec)
        f, s, _ph, _c = measure.load_text_export(path)
        traces.append(measure.resample_log(f, s, freqs))
        levels.append(float(lvl))

    audit = tunelib.source_level_audit(freqs, traces, levels,
                                       electrical=bool(args.electrical))
    report = {'meta': {'traces': len(traces), 'commanded_db': levels,
                       'capture': 'electrical' if args.electrical else 'acoustic'},
              'verdict': audit['verdict'],
              'attribution': audit['attribution'],
              'steps': [], 'notes': list(audit['notes'])}
    for step, spec in zip(audit['steps'], args.at):
        row = {k: step[k] for k in
               ('index', 'measured_db', 'tracking_error_db', 'max_shape_db', 'verdict')}
        row['file'] = spec.split('=')[0]
        row['shape_regions'] = _find_regions(freqs, step['shape_delta_db'],
                                             args.shape_flag_db)
        report['steps'].append(row)

    ref = traces[audit['reference_index']]
    report['bandwidth'] = tunelib.source_bandwidth_limits(freqs, ref)
    if report['bandwidth']['low_hz']:
        notes.append('source is already down 6 dB by %.0f Hz -- output EQ cannot '
                     'recover what the source does not send'
                     % report['bandwidth']['low_hz'])
    report['notes'].extend(notes)
    return report


def imaging(args):
    """Where does the image sit, as a function of frequency? (roadmap item 04)"""
    freqs = measure.common_grid(20.0, 20000.0, 96)
    left = measure.load_complex(args.solo_l, freqs, require_phase=False)
    right = measure.load_complex(args.solo_r, freqs, require_phase=False)
    support = left['support'] & right['support']
    if not np.any(support):
        raise ValueError('the two solo exports share no measured frequency range')
    # Bands outside the shared measured range must not be read; band_itd_ild
    # skips any band left with too few finite bins.
    left_db = np.where(support, left['db'], np.nan)
    right_db = np.where(support, right['db'], np.nan)

    notes = []
    lp = rp = None
    if left['phase_deg'] is not None and right['phase_deg'] is not None:
        refusal = measure.shared_timing_problem(left, right)
        if refusal:
            notes.append('TIME cue dropped: %s. Only level differences were used.' % refusal)
        else:
            phase_ok = support & left['phase_support'] & right['phase_support']
            lp = np.where(phase_ok, left['phase_deg'], np.nan)
            rp = np.where(phase_ok, right['phase_deg'], np.nan)
            if not np.all(phase_ok[support]):
                notes.append('TIME cue limited to %.0f Hz and below: %s'
                             % (freqs[phase_ok][-1] if np.any(phase_ok) else 0.0,
                                measure.unwrap_problem(left, right)))
            unstated = measure.timing_unstated(left, right)
            if unstated:
                notes.append(_unstated_note(unstated))
    else:
        notes.append('no phase column in one or both solo exports -- the TIME cue '
                     'is unavailable, so only level differences were used. Any '
                     'arrival-time difference between the sides is missing from '
                     'this prediction')

    emma = getattr(args, 'bands', 'default') == 'emma'
    rows = (tunelib.band_itd_ild(freqs, left_db, right_db, lp, rp,
                                 bands=tunelib.EMMA_IMAGING_BANDS) if emma
            else tunelib.band_itd_ild(freqs, left_db, right_db, lp, rp))
    pull = tunelib.image_pull(rows)
    if pull['verdict'] == 'smeared':
        notes.append('image position disagrees across frequency -- one delay or trim '
                     'cannot fix this; see methodology.md §Image position is '
                     'frequency-dependent')
    elif pull['verdict'] == 'pulled':
        notes.append('image sits consistently off-centre -- this IS the case a '
                     'delay or level trim addresses (see centre_steering)')
    report = {'meta': {'solo_l': args.solo_l, 'solo_r': args.solo_r,
                       'phase_available': lp is not None,
                       'convention': 'positive = image pulls LEFT (left leads or is louder)',
                       'model': 'inter-channel: ~1 ms or ~16 dB = full shift, cues trade'},
              'verdict': pull['verdict'],
              'spread': pull['spread'], 'mean_pull': pull['mean_pull'],
              'bands': pull['bands'], 'notes': notes}
    if emma:
        instruments = dict(zip(tunelib.EMMA_IMAGING_BANDS, tunelib.EMMA_IMAGING_INSTRUMENTS))
        for band in report['bands']:
            band['instrument'] = instruments[(band['f_lo'], band['f_hi'])]
        report['meta']['emma_edition'] = 2026
        notes.append('instrument ranges follow the 2026 SQ judgebook: position tracks 2-6, '
                     'focus tracks 7-11. These overlapping ranges are diagnostic summaries, '
                     'not isolated test bands or predictions of judging points. A broad-band '
                     'average can hide opposing pulls: also inspect the default frequency '
                     'bands and listen to the actual tracks. MMM supplies level cues only.')
    near_side = getattr(args, 'near_side', None)
    if near_side:
        report['centre_steering'] = tunelib.centre_steering(rows, near_side)
    return report


def _unstated_note(paths):
    return ('%s: the header does not say whether a timing reference was used -- the '
            'time-based result is only valid if every capture shared one (REW timing '
            'reference, or the rew_api.py export which records it)' % ', '.join(paths))


def _complex_exports(paths, freqs):
    """Load phase-bearing exports for relative-phase work, refusing captures
    that cannot share a time base. Returns (loaded items, notes); each
    caller then checks its own band with measure.unwrap_problem."""
    loaded = [measure.load_complex(path, freqs) for path in paths]
    refusal = measure.shared_timing_problem(*loaded)
    if refusal:
        raise ValueError(refusal)
    notes = []
    unstated = measure.timing_unstated(*loaded)
    if unstated:
        notes.append(_unstated_note(unstated))
    return loaded, notes


def probe(args):
    """What would these candidate changes do, at every junction they touch?
    Reads complex exports named in a JSON spec; writes nothing."""
    with open(args.spec, encoding='utf-8') as fh:
        spec = json.load(fh)
    if not isinstance(spec, dict):
        raise ValueError('probe spec must be a JSON object')
    unknown = set(spec) - {'dsp_sample_rate_hz', 'drivers', 'positions', 'junctions',
                           'pairs', 'variants', 'notes'}
    if unknown:
        raise ValueError('probe spec has unknown field(s): %s' % sorted(unknown))
    if ('drivers' in spec) == ('positions' in spec):
        raise ValueError('probe spec needs exactly one of "drivers" (one mic position) or '
                         '"positions" (a list of driver maps, one per mic position)')
    fs = spec.get('dsp_sample_rate_hz')
    if not isinstance(fs, (int, float)) or fs <= 0:
        raise ValueError('dsp_sample_rate_hz is required -- the CONFIRMED internal rate, '
                         'never assumed (it decides how every filter is realized)')
    base_dir = os.path.dirname(os.path.abspath(args.spec))
    freqs = measure.common_grid(20.0, 20000.0, 96)
    position_maps = spec['positions'] if 'positions' in spec else [spec['drivers']]
    if not isinstance(position_maps, list) or not position_maps:
        raise ValueError('"positions" must be a non-empty list of driver maps')
    junctions = [(j['lower'], j['upper'], float(j['crossover_hz']))
                 for j in spec.get('junctions') or []]
    pairs = [tuple(pair) for pair in spec.get('pairs') or []]
    if any(len(pair) != 2 for pair in pairs):
        raise ValueError('"pairs" entries are [left_driver, right_driver]')
    variants = spec.get('variants') or []
    notes, per_position, driver_names = [], [], None
    for k, pmap in enumerate(position_maps):
        names, paths = [], []
        for name, path in (pmap or {}).items():
            names.append(name)
            paths.append(path if os.path.isabs(path) else os.path.join(base_dir, path))
        loaded, pnotes = _complex_exports(paths, freqs) if paths else ([], [])
        notes.extend(n for n in pnotes if n not in notes)
        by_name = dict(zip(names, loaded))
        drivers = {name: item['complex'] for name, item in by_name.items()}
        if len(drivers) < 2:
            raise ValueError('probe needs at least two drivers on one time base')
        if driver_names is None:
            driver_names = sorted(drivers)
        elif sorted(drivers) != driver_names:
            raise ValueError('position %d names different drivers than position 0' % k)
        for lo, up, fc in junctions:
            involved = [by_name[n] for n in (lo, up) if n in by_name]
            refusal = measure.unwrap_problem(*involved, band=(fc / 2.0, fc * 2.0))
            if refusal:
                raise ValueError(refusal)
        per_position.append(tunelib.probe_variants(freqs, drivers, junctions, variants,
                                                   fs=float(fs), pairs=pairs))
    if any('crossover' in change for v in variants for change in v.get('changes', {}).values()):
        notes.append('crossover changes are ADVISORY: this skill never writes crossovers. A '
                     'candidate you like is set by hand in PC-Tool, then re-measured; '
                     'crossover_lift_db above ~6 dB means the prediction leans on stopband '
                     'data below the measured corner -- treat it as a direction, not a number. '
                     'Lowering a high-pass raises that driver\'s excursion: check it before '
                     'trying it at volume (hpf_excursion_risk)')
    report = {'meta': {'spec': args.spec, 'dsp_sample_rate_hz': fs,
                       'drivers': driver_names, 'positions': len(per_position),
                       'junctions': [j[0] + '-' + j[1] for j in junctions],
                       'pairs': ['%s/%s' % pair for pair in pairs],
                       'convention': 'delay_ms positive = later; changes are added on top of '
                                     'the tune the exports were measured through'},
              'variants': per_position[0],
              'notes': notes,
              'predicted_not_measured': True,
              'note': ('a probe ranks candidates; the chosen one still goes through a plan '
                       '(per-edit confirmation) and a re-measure')}
    if len(per_position) > 1:
        report['positions'] = per_position
        report['robust'] = tunelib.aggregate_probe_positions(per_position)
    elif len(per_position) == 1 and variants:
        notes.append('one mic position only: a handover change can help here and hurt a few '
                     'centimetres away -- give "positions" (2-3 head positions) before '
                     'treating a candidate as an improvement')
    return report


REFINE_END_SLOTS = ('25', '32', '20000')
REFINE_SUB_LP_HZ = 250.0        # a channel low-passed below this is a sub channel
REFINE_SUB_FLOOR_HZ = 20.0


def _peq_bank(summary):
    """[(slot_index, F, Q, G)] of the channel's active, un-bypassed PEQ bells."""
    return [(sl['slot_index'], sl['F'], sl['Q'], sl['G']) for sl in summary['slots']
            if sl['type_code'] == '17' and not sl['bypassed'] and sl['G']]


def refine(args):
    """Refine the PEQ bank the measurement was taken through (writes nothing).

    The current tune is the starting point: every filter is kept, relaxed,
    re-fitted in place or removed, and a filter is added only where free
    slots and a real residual both exist. Predictions are dev +
    cascade(new) - cascade(old), so a measured filter is never counted twice.
    Several channels can be refined together only when they carry the SAME
    bank -- a shared measurement cannot justify unequal edits."""
    freqs = measure.common_grid(20.0, 20000.0, 96)
    notes = []
    if not args.dsp_rate or args.dsp_rate <= 0:
        raise ValueError('--dsp-rate is required: the CONFIRMED internal rate, never assumed')
    fs = float(args.dsp_rate)
    sess = _load_session(args, freqs)
    notes.extend(sess['notes'])
    xml = afpx.decode(args.afpx)
    chans = afpx.channels(xml)
    for c in args.channels:
        if not 0 <= c < len(chans):
            raise ValueError('channel %d does not exist (0..%d)' % (c, len(chans) - 1))
    banks = {c: _peq_bank(chans[c]) for c in args.channels}
    ref = sorted((F, Q, G) for _s, F, Q, G in banks[args.channels[0]])
    for c in args.channels[1:]:
        if sorted((F, Q, G) for _s, F, Q, G in banks[c]) != ref:
            raise ValueError('channels %d and %d carry different PEQ banks -- one shared '
                             'measurement cannot justify unequal edits; refine each channel '
                             'from its own solo measurement' % (args.channels[0], c))
    order = {c: sorted(banks[c], key=lambda b: (b[1], b[2], b[3])) for c in args.channels}
    old_bank = [(F, Q, G) for _s, F, Q, G in order[args.channels[0]]]
    free = {c: [sl['slot_index'] for sl in chans[c]['slots']
                if sl['free'] and sl['dF'] not in REFINE_END_SLOTS] for c in args.channels}
    retained = sorted({'%s %.0f Hz' % (sl['type'], sl['F'] or 0) for c in args.channels
                       for sl in chans[c]['slots'] if sl['active']
                       and sl['type_code'] not in ('17',) and sl['type_code'] not in afpx.CROSSOVER_TYPES})
    if retained:
        notes.append('non-PEQ filters are kept as they are and not re-evaluated: %s'
                     % ', '.join(retained))

    covered = freqs[sess['support']]
    hp = max((chans[c]['hp_hz'] or 0.0) for c in args.channels)
    lp = min((chans[c]['lp_hz'] or 1e9) for c in args.channels)
    if args.fit_band:
        band = tuple(args.fit_band)
    elif lp < REFINE_SUB_LP_HZ:
        # A sub channel lives below the general 60 Hz floor; judging it from
        # there leaves a sliver of passband (60-64 Hz behind an 80 Hz low-pass).
        band = (REFINE_SUB_FLOOR_HZ, PROPOSE_FIT_BAND[1])
    else:
        band = PROPOSE_FIT_BAND
    band = (max(band[0], float(covered[0]), hp * 2 ** (1 / 3.0)),
            min(band[1], float(covered[-1]), lp / 2 ** (1 / 3.0)))
    if band[1] <= band[0]:
        raise ValueError('no frequency range is inside both the measurement and the channel '
                         'passband (kept 1/3 octave inside the crossovers)')
    if np.log2(band[1] / band[0]) < 1.0:
        notes.append('judged band %.0f-%.0f Hz is under an octave -- too little passband for a '
                     'bank decision; widen it with --fit-band if the driver plays wider'
                     % band)

    tilt = None
    if not _outside_anchor(band):
        tilt = _rta_tilt(freqs, sess, notes, refuse=True,
                         accept=getattr(args, 'accept_tilt', False))
    # Level is anchored inside the judged band, never the session's 300-3000 Hz
    # default: that lies in a tweeter's or a sub's stopband (tunelib.refine_bank).
    anchor = _band_anchor(freqs, sess, band) if _outside_anchor(band) else sess['anchor']
    if abs(anchor - sess['anchor']) > 1.0:
        notes.append('level anchored inside the judged band (%+.1f dB vs the %.0f-%.0f Hz '
                     'session anchor) -- this solo is band-limited' % (
                         anchor - sess['anchor'], 300, 3000))
    sess['anchor'] = anchor
    sess['dev_db'] = sess['basis_db'] - (sess['target_db'] + anchor)
    evidence_kw, evidence = audible.fitting_evidence(args, freqs, sess)
    partner_db = evidence.pop('partner_db', None)
    if sess['aligned'] is not None:
        devs = list(sess['aligned'] - (sess['target_db'] + anchor))
    else:
        devs = [sess['basis_db'] - (sess['target_db'] + anchor)]
        if sess['capture'] == 'mmm':
            notes.append('one MMM run: a spatial average already -- capture the same tune again '
                         'to measure repeatability before trusting a small change')
        else:
            notes.append('single position: refining against one mic spot -- capture 3+ '
                         'positions before trusting a re-fit or an added band')

    boost_check = None
    if sess['measurement_phase'] is not None:
        try:
            _trust, fields = _phase_fields(args, freqs, sess)

            def boost_check(F, Q, G):
                rows, _summary = tunelib.gate_boost_bands(fields, [(F, Q, G)])
                return rows[0]['verdict']
        except ValueError as exc:
            notes.append('boost gate unavailable: %s' % exc)
    cancel = _cancel_checks(args, freqs)
    if boost_check is None and cancel:
        def boost_check(F, Q, G):
            return _cancel_verdict(freqs, cancel, F, Q)
        notes.append('no phase: candidate boosts are checked for cancellation against %d '
                     'measured pair(s)' % len(cancel))
    mmm = sess['capture'] == 'mmm'
    if mmm and boost_check is None:
        def boost_check(F, Q, G):
            return 'BLOCK'
        notes.append('MMM with no --cancel-check: raised or added boosts are not proposed -- '
                     'give --cancel-check evidence, or trial one boost alone and verify it')
    local_check = None
    if mmm:
        prof = sess['repeatability']

        def local_check(action, old, new):
            olds = [tuple(old)] if old is not None else []
            news = [tuple(new)] if new is not None else []
            T = (tunelib.cascade_db(freqs, news, fs=fs) - tunelib.cascade_db(freqs, olds, fs=fs))
            spans = [tunelib.peq_region(b[0], b[1]) for b in olds + news]
            region = (min(lo for lo, _hi in spans), max(hi for _lo, hi in spans))
            v = tunelib.mmm_change_support(freqs, T, region, prof)
            if v['status'] == 'below_repeatability':
                return ('change %.2f dB is inside the repeat-capture variation (%.2f dB) '
                        'where it acts' % (v['local_change_db'], v['local_resolution_db']))
            return None

    gcheck = guard_check(load_guards(args.afpx, notes), args.channels, freqs)
    guard_blocks = {}
    if gcheck:
        phase_check = boost_check

        def boost_check(F, Q, G):
            why = gcheck(F, Q, G)
            if why:
                guard_blocks.setdefault(why, (F, Q, G))
                return 'BLOCK'
            return phase_check(F, Q, G) if phase_check else 'UNCHECKED'

    result = tunelib.refine_bank(
        freqs, devs, old_bank, band, mask=sess['mask'], conf=sess['conf'], fs=fs,
        max_edits=args.max_edits, free_slots=min(len(v) for v in free.values()),
        boost_check=boost_check, local_check=local_check, fixed_anchor=True, **evidence_kw,
        q_lim=((0.5, MMM_SINGLE_RUN_Q_MAX) if mmm and sess['repeatability'] is None
               else (0.5, 8.0)))
    if result['vetoed']:
        notes.append('%d candidate edit(s) were smaller than the repeat-capture variation where '
                     'they act and were not proposed' % len(result['vetoed']))
    if mmm and sess['repeatability'] is None:
        notes.append('one MMM run: edits are kept broad (Q <= %g) and none can be checked '
                     'against repeatability -- capture the tune twice' % MMM_SINGLE_RUN_Q_MAX)
    for why, (F, Q, G) in list(guard_blocks.items())[:3]:
        notes.append('vehicle guard blocked a candidate boost (%.0f Hz Q%.2f %+.2f dB): %s'
                     % (F, Q, G, why))
    if len(guard_blocks) > 3:
        notes.append('vehicle guards blocked %d more candidate boosts' % (len(guard_blocks) - 3))

    edits, plan_edits = [], []
    next_free = {c: list(free[c]) for c in args.channels}
    for k, e in enumerate(result['edits']):
        slots = {}
        for c in args.channels:
            slot = next_free[c].pop(0) if e['index'] is None else order[c][e['index']][0]
            slots[c] = slot
            edit = {'id': 'refine-%d-ch%d-s%d' % (k + 1, c, slot), 'kind': 'filter_slot',
                    'channel': c, 'slot': slot}
            if e['action'] == 'remove':
                edit['G'] = 0.0
            else:
                F, Q, G = e['new']
                edit.update({'F': F, 'Q': Q, 'G': G})
                if e['action'] == 'add':
                    edit['type_code'] = '17'
            plan_edits.append(edit)
        row = dict(e)
        row['slots'] = {str(c): s for c, s in slots.items()}
        if e['boost_gate'] == 'UNCHECKED':
            row['caution'] = 'boost not phase-checked: no phase in --measurement'
        edits.append(row)

    support = sess['support']
    old_db = tunelib.cascade_db(freqs, old_bank, fs=fs)
    transfer = tunelib.cascade_db(freqs, [tuple(b) for b in result['bank']], fs=fs) - old_db
    comparison = None
    if edits:
        loud = tunelib.loudness_change_db(freqs[support], sess['basis_db'][support],
                                          (sess['basis_db'] + transfer)[support])
        comparison = {'loudness_change_db': round(loud, 2),
                      'louder_version': 'refined' if loud > 0 else 'current',
                      'match_trim_db': round(-abs(loud), 2),
                      'how': ('compare by ear only at matched loudness: pipeline.py ab-make '
                              '--loudness-db %.2f applies this trim to the louder copy' % loud)}
    else:
        notes.append('the current bank already earns its place -- no edit beats it at the '
                     'measured positions. Leaving it alone is the result')
    margin = max(0.5, 2 * (sess['repeatability'] or {}).get('noise_db', 0.0))
    judgement = judging.scorecard(freqs, sess['dev_db'], sess['dev_db'] + transfer,
                                 support & (freqs >= band[0]) & (freqs <= band[1]), margin)
    if partner_db is not None:
        judgement['partner_balance'] = audible.partner_guard(freqs, sess['dev_db'], partner_db, transfer, support)
        if judgement['partner_balance']['status'] == 'regressed':
            judgement['verdict'] = 'regressed'
    judgement['junction_guard'] = audible.junction_guard(args, [tuple(b) for b in result['bank']], probe, old_bands=old_bank)
    if judgement['junction_guard']['status'] == 'hold_for_review':
        judgement['verdict'] = 'regressed'
    judgement['evidence'] = evidence
    judgement['predicted_not_measured'] = True
    judgement['headroom_status'] = 'unknown: full chain and routing required'
    judgement['apply_recommendation'] = ('hold_for_review' if judgement['verdict'] == 'regressed' else 'review_edits')
    if judgement['verdict'] == 'regressed':
        notes.append('judging regression veto: hold this refinement for review')
        plan_edits = []
    return {
        'judging': judgement,
        'meta': {'afpx': args.afpx, 'channels': args.channels, 'dsp_sample_rate_hz': fs,
                 'judged_band_hz': [round(band[0], 1), round(band[1], 1)],
                 'positions_used': len(sess['positions_db']) or 1,
                 'deviation_source': sess['deviation_source']},
        'current_bank': [{'F': F, 'Q': Q, 'G': G,
                          'slots': {str(c): order[c][i][0] for c in args.channels}}
                         for i, (F, Q, G) in enumerate(old_bank)],
        'baseline': result['baseline'], 'refined': result['final'],
        'edits': edits, 'plan_edits': plan_edits,
        'comparison': comparison,
        'verify_with': {'bands': result['bank'], 'old_bands': result['old_bank'],
                        'noise_db': (tunelib.public_repeatability(sess['repeatability'])
                                     or {}).get('noise_db'),
                        'note': ('after writing, re-capture the same way and run pipeline.py '
                                 'verify --report <this file> --before <these captures> '
                                 '--after <the re-captures>')},
        'capture': _capture_report(sess, tilt),
        'notes': notes,
        'predicted_not_measured': True,
        'next_step': ('present each edit (what, slot, why, predicted change), copy only the '
                      'confirmed ones into a plan with confirmations, apply, then compare the '
                      'two tunes level-matched by ear (ab-make) and re-measure'),
    }


AB_LABELS = ('X', 'Y')


def ab_make(args):
    """Two blind, loudness-matched copies of tunes A and B for a listening test.

    The louder one is trimmed by |loudness_db| on every channel through the
    normal verified plan/apply path (output_trim, attenuation only); the
    other is copied byte-for-byte. Which file is which is written only to the
    key file, so the listener can load X and Y without knowing."""
    a, b = os.path.abspath(args.a), os.path.abspath(args.b)
    for path in (a, b):
        if not os.path.isfile(path):
            raise ValueError('not a file: %s' % path)
    loud = float(args.loudness_db)
    if abs(loud) > 6.0:
        raise ValueError('|loudness_db| %.2f exceeds the 6 dB trim floor -- the two versions '
                         'differ too much in level to match by trimming' % abs(loud))
    trim = -abs(loud) if abs(loud) >= 0.1 else 0.0
    louder = b if loud > 0 else a
    if trim and not args.confirm_trim:
        raise ValueError('matching needs a %.2f dB output trim on every channel of the louder '
                         'copy (comparison copy only; the originals are untouched). Show the '
                         'user that number and re-run with --confirm-trim once they agree' % trim)
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    key_path = os.path.join(out_dir, '.ab_key.json')
    targets = {lab: os.path.join(out_dir, '%s.afpx' % lab) for lab in AB_LABELS}
    for path in list(targets.values()) + [key_path]:
        if os.path.exists(path):
            raise ValueError('%s already exists -- use a fresh --out-dir' % path)
    rng = random.Random(args.seed) if args.seed is not None else random.SystemRandom()
    sources = [a, b]
    rng.shuffle(sources)
    key = {'version': 1, 'loudness_db': loud, 'trim_db': trim, 'labels': {}}
    for lab, src in zip(AB_LABELS, sources):
        dst = targets[lab]
        applied = 0.0
        if src == louder and trim:
            xml = afpx.decode(src)
            chans = sorted(afpx.read_output_levels(xml))
            if not chans:
                raise ValueError('%s has no channel output levels to trim' % src)
            with tempfile.TemporaryDirectory() as tmp:
                plan = create_plan(src, dst)
                plan['edits'] = [{'id': 'ab-match-ch%d' % c, 'kind': 'output_trim',
                                  'channel': c, 'trim_db': trim} for c in chans]
                plan['confirmations'] = {e['id']: True for e in plan['edits']}
                plan_path = os.path.join(tmp, 'ab_plan.json')
                with open(plan_path, 'w', encoding='utf-8') as fh:
                    json.dump(plan, fh)
                apply_plan(plan_path)
            applied = trim
        else:
            with open(src, 'rb') as fh_in, open(dst, 'xb') as fh_out:
                shutil.copyfileobj(fh_in, fh_out)
        key['labels'][lab] = {'source': src, 'is': 'A' if src == a else 'B',
                              'trim_db': applied, 'sha256': _sha256_file(dst)}
    with open(key_path, 'x', encoding='utf-8') as fh:
        json.dump(key, fh, indent=2)
    return {
        'files': targets,
        'key': key_path,
        'level_matched_by_db': trim,
        'protocol': [
            'Do not open %s until the test is done.' % os.path.basename(key_path),
            'Same seat, same normal listening volume, same 2-3 short clips you know well '
            '(a centred vocal, something with bass and kick, something bright).',
            'Load X and Y in the order X, Y, Y, X (then repeat), about 20 seconds each; if '
            'someone else can load them for you, even better.',
            'For each pair write which you prefer (X, Y, or same), then run pipeline.py '
            'ab-result --key %s --choices ...' % key_path,
            'At least 6 choices: fewer cannot tell a real preference from chance.',
        ],
    }


def _binomial_tail(k, n):
    """P(at least k of n) for a fair coin."""
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2.0 ** n if n else 1.0


def ab_result(args):
    """Score a blind A/B, reveal which label was which, and log it."""
    with open(args.key, encoding='utf-8') as fh:
        key = json.load(fh)
    choices = [c.strip().upper() for c in args.choices]
    bad = [c for c in choices if c not in AB_LABELS + ('SAME',)]
    if bad:
        raise ValueError('choices must be X, Y or same; got %s' % bad)
    counts = {lab: choices.count(lab) for lab in AB_LABELS}
    n = counts['X'] + counts['Y']
    top = max(AB_LABELS, key=lambda lab: counts[lab])
    p = _binomial_tail(counts[top], n) if n else 1.0
    winner = key['labels'][top]['is'] if n and counts['X'] != counts['Y'] else None
    if winner and p < 0.1:
        verdict = '%s preferred (%d of %d, chance would do this %.0f%% of the time)' % (
            winner, counts[top], n, 100 * p)
    else:
        verdict = 'no reliable preference (%d of %d)' % (counts[top], n)
    entry = {'choices': choices, 'counts': counts, 'p_chance': round(p, 3),
             'verdict': verdict, 'preferred': winner if p < 0.1 else None,
             'reveal': {lab: key['labels'][lab]['is'] for lab in AB_LABELS},
             'sources': {key['labels'][lab]['is']: key['labels'][lab]['source']
                         for lab in AB_LABELS},
             'loudness_matched_db': key.get('trim_db'), 'note': args.note}
    log_path = os.path.join(os.path.dirname(os.path.abspath(args.key)), 'ab_log.json')
    log = []
    if os.path.exists(log_path):
        with open(log_path, encoding='utf-8') as fh:
            log = json.load(fh)
    log.append(entry)
    with open(log_path, 'w', encoding='utf-8') as fh:
        json.dump(log, fh, indent=2)
    entry['log'] = log_path
    if n < 6:
        entry['caution'] = 'fewer than 6 decided choices -- treat any preference as provisional'
    return entry


VERIFY_ADVICE = {
    'confirmed': 'keep: the change landed as predicted',
    'diverged': 'partly landed: re-capture, then refine from the new state',
    'reverted_recommended': ('the change did not show up: remove or rethink this band '
                             '(refine on the new captures)'),
    'inconclusive': ('not resolvable by measurement here: keep it only if the blind, '
                     'loudness-matched A/B prefers it'),
}


def _verify_bands(args):
    """(bands, old_bands) from --bands/--old-bands or a refine/propose report."""
    def triples(specs):
        out = []
        for spec in specs:
            parts = spec.split(',')
            if len(parts) != 3:
                raise ValueError('a band is F,Q,G -- got %r' % spec)
            out.append(tuple(float(x) for x in parts))
        return out
    bands = old = None
    if args.report:
        with open(args.report, encoding='utf-8') as fh:
            report = json.load(fh)
        if 'verify_with' in report:
            bands = [tuple(b) for b in report['verify_with']['bands']]
            old = [tuple(b) for b in report['verify_with']['old_bands']]
        elif 'proposal' in report:
            bands = [(b['f_hz'], b['q'], b['gain_db']) for b in report['proposal']['bands']]
            old = []
        else:
            raise ValueError('%s is neither a refine nor a propose report' % args.report)
    if args.bands:
        bands = triples(args.bands)
        old = triples(args.old_bands or [])
    if bands is None:
        raise ValueError('give --report (refine/propose output) or --bands F,Q,G ...')
    return bands, old


def verify(args):
    """Did the written change land? Before vs after captures, judged per changed
    filter against the repeatability where that filter acts (writes nothing)."""
    freqs = measure.common_grid(20.0, 20000.0, 96)
    if not args.dsp_rate or args.dsp_rate <= 0:
        raise ValueError('--dsp-rate is required: the CONFIRMED internal rate')
    notes = []
    profile = _load_capture_profile(args, notes)

    def load(paths):
        runs, live = [], np.ones_like(freqs, dtype=bool)
        for path in paths:
            f, s, _ph, _c = measure.load_text_export(path)
            runs.append(measure.resample_log(f, s, freqs))
            live &= measure.support_mask(f, freqs)
        return runs, live

    before, lb = load(args.before)
    after, la = load(args.after)
    live = lb & la

    def mean_of(runs):
        if len(runs) >= 2:
            return tunelib.spatial_consistency(freqs, runs, min_positions=2)['mean_db']
        return runs[0]

    b_db, a_db = mean_of(before), mean_of(after)
    prof = None
    if len(before) >= 2:
        prof = tunelib.capture_repeatability(freqs, before, support=live)
    if len(after) >= 2:
        prof = tunelib.combine_repeatability(
            prof, tunelib.capture_repeatability(freqs, after, support=live))
    if prof is None:
        notes.append('one capture each side: resolution ASSUMED from --noise-db %.2f dB -- '
                     'capture before and after twice to measure it' % args.noise_db)
    bands, old = _verify_bands(args)
    result = tunelib.predicted_vs_measured(freqs, b_db, a_db, bands, old_bands=old,
                                           repeatability=prof, noise_db=args.noise_db,
                                           fs=float(args.dsp_rate))
    for row in result['bands']:
        row['advice'] = VERIFY_ADVICE.get(row['verdict'])
    target_path = ASSETS_DEFAULT_TARGET if args.target == 'default' else args.target
    target = measure.load_target(target_path, freqs)
    covered = freqs[live]
    band = (max(60.0, float(covered[0])), min(12000.0, float(covered[-1])))

    def target_error(x):
        anchor = tunelib.target_anchor_offset(freqs, x, target, confidence=live.astype(float))
        return tunelib.audibility_score(freqs, x - target - anchor, band=band, mask=live)

    te_b, te_a = target_error(b_db), target_error(a_db)
    counts = {v: sum(1 for r in result['bands'] if r['verdict'] == v)
              for v in tunelib.VERIFY_VERDICTS}
    return {'meta': {'before': args.before, 'after': args.after, 'report': args.report,
                     'dsp_sample_rate_hz': args.dsp_rate, 'profile': profile},
            'repeatability': tunelib.public_repeatability(prof),
            'level_offset_db': result['level_offset_db'],
            'trace_changed': result['trace_changed'],
            'target_error_db': {'before': round(te_b, 3), 'after': round(te_a, 3),
                                'change': round(te_a - te_b, 3)},
            'counts': counts, 'bands': result['bands'],
            'notes': notes + result['notes'],
            'next_step': ('keep confirmed bands; act on reverted ones; settle inconclusive '
                          'ones by the blind A/B (ab-make with the measured level offset)')}


def voice_variants(args):
    """Shelf-only voicing variants of a finished tune, for a blind A/B.

    Each variant changes ONE thing -- a low shelf on the bass channels or a
    high shelf on the tweeter channels -- in the channel's end shelf slot,
    through the verified plan/apply path. Without --confirm it only shows the
    edits. Voicing is a preference decision: compare the variants blind and
    level-matched (ab-make with the predicted loudness change), never by
    which one measures closer to a curve."""
    xml = afpx.decode(args.afpx)
    chans = afpx.channels(xml)
    variants = [('bass', d) for d in (args.bass_db or [])] + \
               [('treble', d) for d in (args.treble_db or [])] + \
               [('presence', d) for d in (getattr(args, 'presence_db', None) or [])]
    if not variants:
        raise ValueError('give --bass-db and/or --treble-db values, e.g. --bass-db -1 1')
    freqs = measure.common_grid(20.0, 20000.0, 96)
    program = measure.load_target(ASSETS_DEFAULT_TARGET, freqs)
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for kind, delta in variants:
        step = round(float(delta) * 4.0) / 4.0
        if step == 0.0:
            raise ValueError('%s variant %+g dB rounds to 0 at the 0.25 dB shelf step' % (kind, delta))
        channels = (args.bass_channels if kind == 'bass' else
                    getattr(args, 'presence_channels', None) if kind == 'presence' else args.treble_channels)
        if not channels:
            raise ValueError('--%s-channels is required for a %s variant' % (kind, kind))
        end, code = ('25', '3') if kind == 'bass' else ('presence', '17') if kind == 'presence' else ('20000', '4')
        hz = args.bass_hz if kind == 'bass' else args.presence_hz if kind == 'presence' else args.treble_hz
        edits, curve_spec = [], None
        for c in channels:
            if not 0 <= c < len(chans):
                raise ValueError('channel %d does not exist' % c)
            slot = next((sl for sl in chans[c]['slots'] if (sl['free'] and sl['dF'] not in ('25', '20000') if kind == 'presence' else sl['dF'] == end)), None)
            if slot is None:
                raise ValueError('channel %d has no %s shelf slot (dF=%s)' % (c, kind, end))
            edit = {'id': 'voice-%s%+.2f-ch%d' % (kind, step, c), 'kind': 'filter_slot',
                    'channel': c, 'slot': slot['slot_index']}
            if slot['type_code'] == code and slot['G']:
                G = float(np.clip(slot['G'] + step, -15.0, 6.0))
                edit['G'] = G
                spec = (slot['F'], slot['Q'], G - slot['G'])
            elif slot['free'] or slot['type_code'] == code:
                edit.update({'type_code': code, 'F': float(hz), 'Q': float(args.q), 'G': step})
                spec = (float(hz), float(args.q), step)
            else:
                raise ValueError('channel %d %s slot holds a %s filter' % (c, kind, slot['type']))
            curve_spec = curve_spec or spec
            edits.append(edit)
        F, Q, G = curve_spec
        shelf = (tunelib.low_shelf_db(freqs, F, Q, G) if kind == 'bass' else
                 tunelib.peaking_db(freqs, F, Q, G) if kind == 'presence' else
                 tunelib.high_shelf_db(freqs, F, Q, G))
        loud = tunelib.loudness_change_db(freqs, program, program + shelf)
        name = '%s%+.2fdB' % (kind, step)
        path = os.path.join(out_dir, name + '.afpx')
        row = {'variant': name, 'file': path, 'edits': edits,
               'loudness_status': 'provisional: use voice-match on actual candidate system captures',
               'predicted_loudness_change_db': round(loud, 2),
               'ab_make': ('pipeline.py ab-make --a %s --b %s --loudness-db %.2f --out-dir '
                           '<dir> --confirm-trim' % (args.afpx, path, loud))}
        if args.confirm:
            if os.path.exists(path):
                raise ValueError('%s already exists -- use a fresh --out-dir' % path)
            with tempfile.TemporaryDirectory() as tmp:
                plan = create_plan(args.afpx, path)
                plan['edits'] = edits
                plan['confirmations'] = {e['id']: True for e in edits}
                plan_path = os.path.join(tmp, 'voice_plan.json')
                with open(plan_path, 'w', encoding='utf-8') as fh:
                    json.dump(plan, fh)
                row['manifest_output_sha256'] = apply_plan(plan_path)['output_sha256']
        rows.append(row)
    return {'meta': {'afpx': args.afpx, 'out_dir': out_dir, 'written': bool(args.confirm)},
            'variants': rows,
            'notes': ['each variant changes one shelf; the original tune is untouched',
                      'compare each against the current tune blind and level-matched '
                      '(its ab_make line), at your normal volume, on familiar tracks',
                      'predicted loudness assumes the shelf reaches the whole system -- '
                      'confirm the match by ear'] +
                     ([] if args.confirm else ['dry run: show the user these edits, then '
                                               're-run with --confirm to write the files'])}


def _load_pair(a_path, b_path, freqs):
    fa, sa, _p, _c = measure.load_text_export(a_path)
    fb, sb, _p, _c = measure.load_text_export(b_path)
    live = measure.support_mask(fa, freqs) & measure.support_mask(fb, freqs)
    return measure.resample_log(fa, sa, freqs), measure.resample_log(fb, sb, freqs), live


def emma_volume(args):
    """EMMA's higher-volume spectral balance check from two captures (writes nothing)."""
    freqs = measure.common_grid(20.0, 20000.0, 96)
    normal, loud, live = _load_pair(args.normal, args.loud, freqs)
    result = tunelib.emma_volume_check(freqs, normal, loud, step_db=args.step_db, support=live)
    result['meta'] = {'normal': args.normal, 'loud': args.loud}
    result['notes'].append('capture both with the same signal, mic path and everything else; '
                           'only the head-unit volume changes (about 2-3 steps for 6 dB -- '
                           'check with an SPL meter on pink noise)')
    return result


def noise_check(args):
    """What the system adds to the quiet cabin: system off vs on with silence."""
    freqs = measure.common_grid(20.0, 20000.0, 96)
    off, on, live = _load_pair(args.off, args.on, freqs)
    result = tunelib.system_noise_check(freqs, off, on, support=live)
    result['meta'] = {'off': args.off, 'on': args.on}
    result['notes'] = ['capture both at the judging seat with the same RTA settings and no '
                       'generator; "on" plays digital silence (the zero-bit track) at the '
                       'volume you will suggest',
                       'hum points at grounding or the source; hiss at amplifier gain set too '
                       'high for the source level; also listen for turn-on pops and noise while '
                       'changing volume or track -- EMMA deducts for those too']
    return result


def _labelled(specs, what):
    out = {}
    for spec in specs:
        label, sep, path = spec.partition('=')
        if not sep or not label or not path:
            raise ValueError('%s wants LABEL=PATH, got %r' % (what, spec))
        if label in out:
            raise ValueError('duplicate label %r' % label)
        out[label] = path
    return out


def mmm_compare(args):
    """Which setting is better, from magnitude captures alone (writes nothing).

    Capture the same MMM path at each candidate setting -- a sub delay, sub
    polarity, a Phase angle, a trim -- and rank them over one band. Nothing
    wins unless it beats the baseline by more than the measured repeatability
    (--repeat: a second capture of the baseline setting)."""
    freqs = measure.common_grid(20.0, 20000.0, 96)
    files = _labelled(args.captures, '--captures')
    if len(files) < 2:
        raise ValueError('mmm-compare needs at least two captures')
    captures, live = {}, np.ones_like(freqs, dtype=bool)
    for label, path in files.items():
        f, s, _ph, _c = measure.load_text_export(path)
        captures[label] = measure.resample_log(f, s, freqs)
        live &= measure.support_mask(f, freqs)
    repeat = None
    if args.repeat:
        f, s, _ph, _c = measure.load_text_export(args.repeat)
        repeat = measure.resample_log(f, s, freqs)
        live &= measure.support_mask(f, freqs)
    baseline = args.baseline or next(iter(files))
    repeat_files = _labelled(getattr(args, 'candidate_repeat', None) or [], '--candidate-repeat')
    candidate_repeats = {}
    for label, path in repeat_files.items():
        if label == baseline or label not in files:
            raise ValueError('--candidate-repeat must name a non-baseline label in --captures')
        f, s, _ph, _c = measure.load_text_export(path)
        candidate_repeats[label] = measure.resample_log(f, s, freqs)
        live &= measure.support_mask(f, freqs)
    notes = []
    if args.ambient:
        f, s, _ph, _c = measure.load_text_export(args.ambient)
        all_runs = list(captures.values()) + list(candidate_repeats.values())
        if repeat is not None:
            all_runs.append(repeat)
        ok, _snr = tunelib.snr_support(np.min(np.vstack(all_runs), axis=0),
                                       measure.resample_log(f, s, freqs), args.min_snr_db)
        ok &= measure.support_mask(f, freqs)
        lost = _mask_runs(freqs, live & ~ok)
        if lost:
            notes.append('excluded below %.0f dB SNR: %s' % (args.min_snr_db, ', '.join(lost)))
        live &= ok
    target_path = ASSETS_DEFAULT_TARGET if args.target == 'default' else args.target
    target_db = measure.load_target(target_path, freqs)
    result = tunelib.compare_captures(freqs, captures, target_db, tuple(args.band), baseline,
                                      repeat_db=repeat, noise_db=args.noise_db,
                                      objective=args.objective, support=live,
                                      reference_band=tuple(args.reference_band),
                                      candidate_repeats=candidate_repeats)
    if args.objective == 'level':
        notes.append('level ranking assumes every capture used the same playback volume and '
                     'gain: change only the setting under test between captures')
    notes.append('a choice is a provisional tonal improvement, not proof of phase or image '
                 'position; repeat it at the same source level and confirm by listening '
                 'before keeping it; write any change through its own plan')
    result['files'] = files
    result['repeat_files'] = {'baseline': args.repeat, 'candidates': repeat_files}
    result['notes'] = notes
    return result


def lr_match(args):
    """Left/right tonal match from two half-system captures (writes nothing).

    Left side only and right side only, same MMM path and playback level:
    reports a trim and cuts only where matching AND target error improve."""
    freqs = measure.common_grid(20.0, 20000.0, 96)
    fl, sl, _p, _c = measure.load_text_export(args.left)
    fr, sr, _p, _c = measure.load_text_export(args.right)
    left = measure.resample_log(fl, sl, freqs)
    right = measure.resample_log(fr, sr, freqs)
    live = measure.support_mask(fl, freqs) & measure.support_mask(fr, freqs)
    covered = freqs[live]
    if len(covered) < 8:
        raise ValueError('L/R captures have insufficient common measured coverage')
    band = (max(args.band[0], float(covered[0])), min(args.band[1], float(covered[-1])))
    target_path = ASSETS_DEFAULT_TARGET if args.target == 'default' else args.target
    target = measure.load_target(target_path, freqs)
    result = tunelib.lr_match_cuts(freqs[live], left[live], right[live], band=band,
                                   flag_db=args.flag_db, target_db=target[live])
    notes = result['notes'] + ['captures must share one MMM path and playback level; the trim goes on every '
             'channel of the louder side (output_trim, attenuation only), each cut on the '
             'driver of that side that plays its frequency',
             'image balance is a listening decision too: confirm with a centred mono vocal, '
             'and re-capture both halves after writing']
    result.update({'meta': {'left': args.left, 'right': args.right, 'target': str(target_path),
                            'band_hz': [round(band[0], 1), round(band[1], 1)]},
                   'notes': notes, 'predicted_not_measured': True})
    return result


def junction(args):
    """Phase score + sum loss for one crossover pair (methodology.md
    §The crossover action-ladder). Read-only; writes nothing."""
    freqs = measure.common_grid(20.0, 20000.0, 96)
    loaded, notes = _complex_exports([args.lower, args.upper], freqs)
    fc = float(args.crossover)
    band = (fc / 2.0, fc * 2.0)
    refusal = measure.unwrap_problem(*loaded, band=band)
    if refusal:
        raise ValueError(refusal)
    lower, upper = loaded[0]['complex'], loaded[1]['complex']
    phase = tunelib.junction_phase_score(freqs, lower, upper, fc)
    if phase is None:
        notes.append('fewer than 8 usable bins around the crossover -- no read-out')
    else:
        if not phase['alignable']:
            notes.append('best score below 0.5: the two drivers do not hold one phase '
                         'relation across the band -- no delay is trustworthy here')
        if phase['lobe_margin'] == phase['lobe_margin'] and phase['lobe_margin'] < 0.05:
            notes.append('lobe margin under 0.05: a whole-period hop cannot be ruled out')
        if phase['polarity_ambiguous']:
            notes.append('polarity is ambiguous here (within 0.05) -- keep the current one')
        if fc >= 1000.0 and not args.direct_sound:
            notes.append('above ~1 kHz full-window phase is decorrelated by the cabin; '
                         'repeat with direct-sound exports (decay.py fdw) and pass '
                         '--direct-sound before trusting a delay here')
    return {'meta': {'lower': args.lower, 'upper': args.upper, 'crossover_hz': fc,
                     'window': 'direct-sound (FDW)' if args.direct_sound else 'as exported',
                     'convention': 'extra delay/polarity apply to the LOWER channel'},
            'phase': phase,
            'delay_consensus': tunelib.delay_consensus(freqs, lower, upper, fc),
            'sum_loss': tunelib.junction_sum_loss(freqs, lower, upper, band),
            'notes': notes,
            'reminder': ('a channel hands over twice: re-check its OTHER junction with '
                         'any delay/polarity you carry to it')}


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
            # every capture states its timing reference, as rew_api.py writes it
            np.savetxt(path, np.column_stack(cols), fmt='%.4f',
                       header='timing reference: Acoustic', comments='* ')
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

        # ---- source-audit wiring: a head unit with a loudness contour -------
        base = 80.0 + tunelib.peaking_db(freqs, 900.0, 1.2, -3.0)
        cmd_levels = [0.0, -6.0, -12.0]
        contour_paths = []
        for c in cmd_levels:
            trace = base + c + (abs(c) / 12.0) * tunelib.low_shelf_db(freqs, 120.0, 0.7, 6.0)
            contour_paths.append('%s=%g' % (save('src_%g.txt' % abs(c), freqs, trace,
                                                 np.zeros_like(freqs)), c))
        sa = source_audit(argparse.Namespace(at=contour_paths, electrical=False,
                                             shape_flag_db=1.0, out=None))
        assert sa['verdict'] == 'level_dependent_shape', sa
        assert sa['attribution'] == 'source_or_driver_compression', sa
        worst = max(sa['steps'], key=lambda s: s['max_shape_db'])
        assert any(r['peak_hz'] < 300.0 for r in worst['shape_regions']), \
            'the bass contour should be localised in the bass: %r' % worst['shape_regions']
        assert any('CANNOT ATTRIBUTE' in n for n in sa['notes']), sa['notes']
        print('pipeline selftest: source-audit catches a loudness contour and '
              'refuses to attribute it from an acoustic capture')

        # a clean source must come back clean, with no invented findings
        clean_paths = ['%s=%g' % (save('clean_%g.txt' % abs(c), freqs, base + c,
                                       np.zeros_like(freqs)), c) for c in cmd_levels]
        sc = source_audit(argparse.Namespace(at=clean_paths, electrical=True,
                                            shape_flag_db=1.0, out=None))
        assert sc['verdict'] == 'clean', sc
        print('pipeline selftest: source-audit reports a clean source as clean')

        # ---- imaging wiring: opposing cues across the duplex region ---------
        lead_s = 300e-6
        l_db = 80.0 * np.ones_like(freqs)
        r_db = 80.0 + tunelib.high_shelf_db(freqs, 2000.0, 0.7, 6.0)
        l_ph = np.zeros_like(freqs)
        r_ph = (-360.0 * freqs * lead_s + 180.0) % 360.0 - 180.0   # right late, wrapped
        im = imaging(argparse.Namespace(
            solo_l=save('img_l.txt', freqs, l_db, l_ph),
            solo_r=save('img_r.txt', freqs, r_db, r_ph), out=None))
        assert im['meta']['phase_available'], im['meta']
        assert im['verdict'] == 'smeared', im
        lo_band = [b for b in im['bands'] if b['f_hi'] <= 400][0]
        hi_band = [b for b in im['bands'] if b['f_lo'] >= 5000][0]
        assert lo_band['side'] == 'left' and hi_band['side'] == 'right', (lo_band, hi_band)
        print('pipeline selftest: imaging reports left-at-LF / right-at-HF from '
              'opposing time and level cues (spread %.2f)' % im['spread'])

        # without phase the time cue must be withdrawn, not guessed
        im2 = imaging(argparse.Namespace(
            solo_l=save('img_l2.txt', freqs, l_db),
            solo_r=save('img_r2.txt', freqs, r_db), out=None))
        assert not im2['meta']['phase_available']
        assert any('TIME cue is unavailable' in n for n in im2['notes']), im2['notes']
        print('pipeline selftest: imaging withdraws the time cue when phase is absent')

    doc_problems = check_doc_refs()
    assert not doc_problems, 'stale doc cross-references:\n  ' + '\n  '.join(doc_problems)
    print('pipeline selftest: core_workflow.md section refs and anchors resolve OK')

    print('\nALL PIPELINE SELFTESTS PASSED')


def _capture_args(parser):
    parser.add_argument('--capture', choices=('sweep', 'mmm'), default='sweep',
                        help='mmm: a moving-mic RTA average -- each --positions file is a '
                             'repeat run of the same tune, not a seat')
    parser.add_argument('--ambient', help='RTA capture with the generator off (same settings)')
    parser.add_argument('--min-snr-db', type=float, default=10.0)
    parser.add_argument('--cancel-check', nargs=3, action='append',
                        metavar=('PART_A', 'PART_B', 'BOTH'),
                        help='two halves and both together at one playback level (e.g. left, '
                             'right, both): boosts into their cancellation are blocked')
    parser.add_argument('--accept-tilt', action='store_true',
                        help='proceed although the MMM tilt looks like a wrong RTA mode')
    parser.add_argument('--capture-profile', metavar='JSON',
                        help='the recorded REW setup (analyzer, noise, FFT, playback route, '
                             'mic cal/aim ...), checked against REW\'s rules')


def main():
    ap = argparse.ArgumentParser(description='Deterministic analysis report for a tuning session.')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('selftest', help='run the self-contained synthetic-fixture self-test')

    qc = sub.add_parser('quality-check', help='evidence-aware tone, compression and distortion judging')
    qc.add_argument('--spec', required=True, help='version-1 quality manifest; paths relative to this file')
    qc.add_argument('--out', help='write JSON report')

    sp = sub.add_parser('stereo-propose', help='shared voicing and limited side-specific cuts, judged together')
    sp.add_argument('--left', nargs='+', required=True)
    sp.add_argument('--right', nargs='+', required=True)
    sp.add_argument('--target', default='default')
    sp.add_argument('--band', nargs=2, type=float, default=(300, 6000))
    sp.add_argument('--max-bands', type=int, default=3)
    sp.add_argument('--out')

    bt = sub.add_parser('bass-trials', help='predict sub gain/delay/polarity trials, validated against the actual sum')
    bt.add_argument('--sub', required=True)
    bt.add_argument('--front', required=True)
    bt.add_argument('--together', required=True)
    bt.add_argument('--target', default='default')
    bt.add_argument('--band', nargs=2, type=float, default=(40, 200))
    bt.add_argument('--delays-ms', nargs='+', type=float, default=(-0.5, 0, 0.5))
    bt.add_argument('--gains-db', nargs='+', type=float, default=(-1, 0, 1))
    bt.add_argument('--try-invert', action='store_true')
    bt.add_argument('--limits')
    bt.add_argument('--out')

    vm = sub.add_parser('voice-match', help='estimate blind A/B level trims from actual measured system responses')
    vm.add_argument('--baseline', required=True)
    vm.add_argument('--candidates', nargs='+', required=True, metavar='LABEL=PATH')
    vm.add_argument('--out')

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

    _capture_args(an)

    pr = sub.add_parser('propose',
                        help='deterministic PEQ proposal from the same inputs (writes nothing)')
    pr.add_argument('--measurement')
    pr.add_argument('--positions', nargs='+')
    pr.add_argument('--sittings', nargs='+', metavar='LABEL',
                    help='one sitting label per --positions file (e.g. 8aug 8aug 10aug): '
                         'held-out validation then withholds a whole sitting at a time')
    pr.add_argument('--target', required=True, help='target curve file, or "default"')
    pr.add_argument('--session-tune', metavar='AFPX',
                    help='enforce the vehicle guards recorded in the session file of this tune')
    pr.add_argument('--channels', nargs='+', type=int,
                    help='channel(s) this proposal is for: selects channel-specific guards')
    pr.add_argument('--voice', nargs='+', help='e.g. tilt=-0.5 bass=2 presence=1 air=0')
    pr.add_argument('--fit-band', nargs=2, type=float, metavar=('LO_HZ', 'HI_HZ'),
                    help='band to correct (default %g-%g Hz)' % PROPOSE_FIT_BAND)
    pr.add_argument('--max-bands', type=int, default=5)
    pr.add_argument('--trust-band', nargs=2, type=float, metavar=('LO_HZ', 'HI_HZ'))
    pr.add_argument('--gate-ms', type=float,
                    help='the capture was time-gated: never fit below its trust floor')
    pr.add_argument('--out')
    pr.add_argument('--junction-spec', help='timed neighbour probe spec plus apply_to; veto tonal edits that worsen a supplied junction')
    pr.add_argument('--partner', help='other side capture on the SAME level scale; constrain target-supported L/R matching')
    pr.add_argument('--limits', help='quality-check report from this driver/preset/level; constrain additional gain')
    _capture_args(pr)

    rf = sub.add_parser('refine',
                        help='keep / relax / re-fit / remove / add on the existing PEQ bank '
                             '(writes nothing)')
    rf.add_argument('--afpx', required=True, help='the tune the measurement was taken through')
    rf.add_argument('--channels', nargs='+', type=int, required=True,
                    help='channel index(es) the measurement covers; several only if they '
                         'carry the same PEQ bank')
    rf.add_argument('--dsp-rate', type=float, required=True,
                    help='the CONFIRMED DSP sample rate in Hz (P SIX DSP MK2: 96000)')
    rf.add_argument('--measurement')
    rf.add_argument('--positions', nargs='+')
    rf.add_argument('--target', required=True, help='target curve file, or "default"')
    rf.add_argument('--voice', nargs='+')
    rf.add_argument('--fit-band', nargs=2, type=float, metavar=('LO_HZ', 'HI_HZ'))
    rf.add_argument('--trust-band', nargs=2, type=float, metavar=('LO_HZ', 'HI_HZ'))
    rf.add_argument('--gate-ms', type=float)
    rf.add_argument('--max-edits', type=int, default=4)
    rf.add_argument('--out')
    rf.add_argument('--junction-spec', help='timed neighbour probe spec plus apply_to; veto tonal edits that worsen a supplied junction')
    rf.add_argument('--partner', help='other side capture on the SAME level scale; constrain target-supported L/R matching')
    rf.add_argument('--limits', help='quality-check report from this driver/preset/level; constrain additional gain')
    _capture_args(rf)

    mc = sub.add_parser('mmm-compare',
                        help='rank magnitude captures of different settings over one band')
    mc.add_argument('--captures', nargs='+', required=True, metavar='LABEL=PATH')
    mc.add_argument('--baseline', help='label of the current setting (default: the first)')
    mc.add_argument('--repeat', help='a second capture of the baseline setting')
    mc.add_argument('--candidate-repeat', nargs='+', metavar='LABEL=PATH',
                    help='independent second capture of a candidate; compare both runs '
                         'against both baseline runs with the same target anchor')
    mc.add_argument('--band', nargs=2, type=float, required=True, metavar=('LO_HZ', 'HI_HZ'))
    mc.add_argument('--target', default='default')
    mc.add_argument('--objective', choices=('balanced', 'shape', 'level'), default='balanced',
                    help='balanced: target balance with output guard; shape: band shape only; '
                         'level: output with tonal guards')
    mc.add_argument('--reference-band', nargs=2, type=float, default=(300.0, 3000.0),
                    metavar=('LO_HZ', 'HI_HZ'),
                    help='unchanged measured band outside trial band (default 300-3000 Hz)')
    mc.add_argument('--noise-db', type=float,
                    help='repeatability when no --repeat was captured (default 0.25)')
    mc.add_argument('--ambient')
    mc.add_argument('--min-snr-db', type=float, default=10.0)
    mc.add_argument('--out')

    vf = sub.add_parser('verify', help='did a written change land? before vs after captures')
    vf.add_argument('--before', nargs='+', required=True, help='captures the change was made from')
    vf.add_argument('--after', nargs='+', required=True, help='re-captures with the new tune')
    vf.add_argument('--report', help='the refine or propose JSON the change came from')
    vf.add_argument('--bands', nargs='+', metavar='F,Q,G', help='bands actually written')
    vf.add_argument('--old-bands', nargs='+', metavar='F,Q,G', help='bands they replaced')
    vf.add_argument('--dsp-rate', type=float, required=True)
    vf.add_argument('--target', default='default')
    vf.add_argument('--noise-db', type=float, default=0.3,
                    help='resolution when before/after were each captured once')
    vf.add_argument('--capture-profile', metavar='JSON')
    vf.add_argument('--out')

    vv = sub.add_parser('voice-variants', help='single-filter voicing variants for a blind A/B')
    vv.add_argument('--afpx', required=True)
    vv.add_argument('--out-dir', required=True)
    vv.add_argument('--bass-channels', nargs='+', type=int)
    vv.add_argument('--treble-channels', nargs='+', type=int)
    vv.add_argument('--bass-db', nargs='+', type=float, help='e.g. -1 1')
    vv.add_argument('--treble-db', nargs='+', type=float, help='e.g. -1 1')
    vv.add_argument('--presence-db', nargs='+', type=float)
    vv.add_argument('--presence-channels', nargs='+', type=int)
    vv.add_argument('--presence-hz', type=float, default=2200.0)
    vv.add_argument('--bass-hz', type=float, default=120.0)
    vv.add_argument('--treble-hz', type=float, default=6000.0)
    vv.add_argument('--q', type=float, default=0.7)
    vv.add_argument('--confirm', action='store_true', help='write the variant files')
    vv.add_argument('--out')

    ev = sub.add_parser('emma-volume', help='does the balance hold 6 dB louder? (EMMA)')
    ev.add_argument('--normal', required=True, help='capture at the volume you will suggest')
    ev.add_argument('--loud', required=True, help='same capture about 6 dB louder')
    ev.add_argument('--step-db', type=float, default=6.0)
    ev.add_argument('--out')

    nc = sub.add_parser('noise-check', help='system noise: system off vs on playing silence')
    nc.add_argument('--off', required=True, help='RTA with the audio system off')
    nc.add_argument('--on', required=True, help='RTA with the system on, playing silence')
    nc.add_argument('--out')

    lm = sub.add_parser('lr-match', help='left/right tonal match from half-system captures')
    lm.add_argument('--left', required=True, help='left side only')
    lm.add_argument('--right', required=True, help='right side only')
    lm.add_argument('--target', default='default', help='desired tonal curve, or default')
    lm.add_argument('--band', nargs=2, type=float, default=(300.0, 6000.0),
                    metavar=('LO_HZ', 'HI_HZ'))
    lm.add_argument('--flag-db', type=float, default=1.5)
    lm.add_argument('--out')

    abm = sub.add_parser('ab-make', help='blind, loudness-matched copies of two tunes')
    abm.add_argument('--a', required=True, help='current tune')
    abm.add_argument('--b', required=True, help='candidate tune')
    abm.add_argument('--loudness-db', required=True, type=float,
                     help='B relative to A (refine/propose report it); positive = B louder')
    abm.add_argument('--out-dir', required=True)
    abm.add_argument('--confirm-trim', action='store_true',
                     help='the user agreed to the matching trim on the comparison copy')
    abm.add_argument('--seed', type=int, help='fixed shuffle, for tests only')
    abm.add_argument('--out')

    abr = sub.add_parser('ab-result', help='score a blind A/B and reveal which was which')
    abr.add_argument('--key', required=True)
    abr.add_argument('--choices', nargs='+', required=True, help='X, Y or same per pair')
    abr.add_argument('--note')
    abr.add_argument('--out')

    sa = sub.add_parser('source-audit',
                        help='is the signal entering the DSP level-independent?')
    sa.add_argument('--at', nargs='+', required=True, metavar='PATH=DB',
                    help='the same sweep at several SOURCE volumes, e.g. '
                         'ref.txt=0 down6.txt=-6 down12.txt=-12')
    sa.add_argument('--electrical', action='store_true',
                    help='captured at the DSP input, not acoustically -- only '
                         'then can a finding be attributed to the source rather '
                         'than to driver compression')
    sa.add_argument('--shape-flag-db', type=float, default=1.0)
    sa.add_argument('--out')

    im = sub.add_parser('imaging',
                        help='predicted image position vs frequency from solo L/R')
    im.add_argument('--solo-l', required=True)
    im.add_argument('--solo-r', required=True)
    im.add_argument('--bands', choices=('default', 'emma'), default='default',
                    help='emma: the five instrument bands of the EMMA imaging tracks')
    im.add_argument('--near-side', choices=('left', 'right'),
                    help='the side nearer the listener (right = RHD driver seat): '
                         'adds centre-steering options')
    im.add_argument('--out')

    pb = sub.add_parser('probe', help='evaluate candidate changes at every junction (writes nothing)')
    pb.add_argument('--spec', required=True, help='JSON: dsp_sample_rate_hz, drivers, junctions, variants')
    pb.add_argument('--out')

    jn = sub.add_parser('junction', help='phase score and sum loss for one crossover pair')
    jn.add_argument('--lower', required=True, help='lower driver export (with phase)')
    jn.add_argument('--upper', required=True, help='upper driver export (with phase)')
    jn.add_argument('--crossover', required=True, type=float, help='crossover frequency, Hz')
    jn.add_argument('--direct-sound', action='store_true',
                    help='the exports are direct-sound (decay.py fdw) responses')
    jn.add_argument('--out')

    se = sub.add_parser('session', help='read or record the intake session sidecar')
    se_sub = se.add_subparsers(dest='session_cmd', required=True)
    se_check = se_sub.add_parser('check', help='compare the sidecar against the tune hash')
    se_check.add_argument('--tune', required=True)
    se_save = se_sub.add_parser('save', help='record confirmed intake answers')
    se_save.add_argument('--tune', required=True)
    se_save.add_argument('--answers', required=True,
                         help='JSON object with any of: ' + ', '.join(SESSION_FIELDS))

    args = ap.parse_args()
    try:
        _dispatch(args)
    except (ValueError, OSError) as exc:
        # An input problem, not a bug: one line an agent can act on instead of
        # a traceback that buries it. HELIX_TUNER_DEBUG=1 shows the traceback.
        if os.environ.get('HELIX_TUNER_DEBUG'):
            raise
        print('error: %s' % exc, file=sys.stderr)
        sys.exit(2)


# Reports are JSON. A mistyped --out must never replace a tune, a capture, or
# one of the command's own inputs: plan/apply is the only route that writes tunes.
_PROTECTED_OUT_SUFFIXES = ('.afpx', '.pct6', '.jssh', '.mdat', '.wav')


def _arg_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _arg_strings(item)


def _check_report_out(args):
    out = getattr(args, 'out', None)
    if not out:
        return
    if os.path.splitext(out)[1].lower() in _PROTECTED_OUT_SUFFIXES:
        raise ValueError('--out %s looks like a tune or capture file; reports are JSON, '
                         'so choose a new .json path' % out)
    if not os.path.exists(out):
        return
    for name, value in vars(args).items():
        if name == 'out':
            continue
        for text in _arg_strings(value):
            for path in {text, text.partition('=')[2]}:
                if path and os.path.exists(path) and os.path.samefile(path, out):
                    raise ValueError('--out %s is one of this command\'s inputs; '
                                     'refusing to overwrite it' % out)


def _dispatch(args):
    if args.cmd == 'selftest':
        _selftest()
    elif args.cmd == 'quality-check':
        _check_report_out(args)
        with open(args.spec, encoding='utf-8-sig') as fh:
            spec = json.load(fh)
        report = judging.load_spec(spec, os.path.dirname(os.path.abspath(args.spec)))
        if args.out:
            for source in report['input_files']:
                if os.path.exists(args.out) and os.path.samefile(source, args.out):
                    raise ValueError('--out is a manifest input; refusing to overwrite it')
            with open(args.out, 'w', encoding='utf-8') as fh:
                json.dump(report, fh, indent=2, allow_nan=False)
            print('wrote %s' % args.out)
        else:
            print(json.dumps(report, indent=2, allow_nan=False))
    elif args.cmd == 'session':
        if args.session_cmd == 'check':
            print(json.dumps(session_check(args.tune), indent=2))
        else:
            with open(args.answers, encoding='utf-8') as fh:
                answers = json.load(fh)
            print('wrote %s' % session_save(args.tune, answers))
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
    elif args.cmd in ('analyze', 'propose', 'source-audit', 'imaging', 'junction', 'probe',
                      'refine', 'ab-make', 'ab-result', 'mmm-compare', 'lr-match',
                      'verify', 'voice-variants', 'emma-volume', 'noise-check', 'bass-trials', 'voice-match', 'stereo-propose'):
        _check_report_out(args)
        report = {'analyze': analyze, 'propose': propose, 'source-audit': source_audit,
                  'imaging': imaging, 'junction': junction, 'probe': probe,
                  'refine': refine, 'ab-make': ab_make,
                  'ab-result': ab_result, 'mmm-compare': mmm_compare,
                  'lr-match': lr_match, 'verify': verify,
                  'voice-variants': voice_variants, 'emma-volume': emma_volume,
                  'noise-check': noise_check, 'bass-trials': audible.bass_trials,
                  'voice-match': audible.measured_voice_match, 'stereo-propose': audible.stereo_propose}[args.cmd](args)
        text = json.dumps(report, indent=2)
        if args.out:
            with open(args.out, 'w', encoding='utf-8') as fh:
                fh.write(text)
            print('wrote %s' % args.out)
        else:
            print(text)


if __name__ == '__main__':
    main()
