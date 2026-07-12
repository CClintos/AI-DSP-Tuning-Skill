# pipeline.py -- one deterministic entry point for the analysis layer.
#
# Every session up to now hand-wrote bespoke `python -c` snippets to load
# exports, resample, compute deviation, and run the audits. It worked, but
# it was re-derived slightly differently every time (different thresholds,
# different region-finding logic, easy to skip a check by accident without
# noticing) and each invocation cost tokens the same handful of numbers
# doesn't need to repay every session.
#
# This is a REPORTING layer only -- it decides and writes nothing to any DSP
# file. Judgment (what to actually DO about a flagged region) still lives in
# methodology.md and the conversation; this just makes the numbers behind
# that judgment identical and cheap to produce every time, with zero
# duplicated math -- everything here is a thin, deterministic wrapper around
# tunelib.py/measure.py/afpx.py functions that are already independently
# tested by their own self-tests.
#
# python pipeline.py analyze --measurement <export.txt> --target <target.txt|default> [options]
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
import json
import os
import sys

import numpy as np

import afpx
import measure
import tunelib

ASSETS_DEFAULT_TARGET = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'assets', 'default_incar_target.txt')


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

    measurement_phase = None
    if args.measurement:
        f, s, ph, _coh = measure.load_text_export(args.measurement)
        primary_db = measure.resample_log(f, s, freqs)
        measurement_phase = ph
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
        meas_path = save('measurement.txt', freqs, spl, phase)
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
        afpx.encode(xml, afpx_path)

        args = argparse.Namespace(
            measurement=meas_path, positions=pos_paths, target=target_path,
            voice=['tilt=-0.5'], solo_a=solo_a_path, solo_b=solo_b_path,
            together=together_path, pair_band=[200.0, 800.0], gate_ms=2.9,
            afpx=afpx_path, dev_flag_db=2.0, out=None)
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
        assert report['notes'] == [], 'a fully-specified run should have no skip notes: %r' % report['notes']
        print('pipeline selftest: analyze() wiring OK (voicing, level anchor, '
             'deviation regions, spatial_consistency, interference_audit, '
             'crossover_confidence, gating, afpx read-through)')

        try:
            analyze(argparse.Namespace(measurement=None, positions=None, target=target_path,
                                       voice=None, solo_a=None, solo_b=None, together=None,
                                       pair_band=None, gate_ms=None, afpx=None,
                                       dev_flag_db=2.0, out=None))
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

    print('\nALL PIPELINE SELFTESTS PASSED')


def main():
    ap = argparse.ArgumentParser(description='Deterministic analysis report for a tuning session.')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sub.add_parser('selftest', help='run the self-contained synthetic-fixture self-test')

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
    an.add_argument('--afpx')
    an.add_argument('--dev-flag-db', type=float, default=2.0)
    an.add_argument('--out')

    args = ap.parse_args()
    if args.cmd == 'selftest':
        _selftest()
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
