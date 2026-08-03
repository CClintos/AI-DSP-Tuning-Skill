# repeatability.py -- measure the session's OWN noise floor from repeat captures,
# instead of carrying a remembered per-band number from a previous session.
#
# WHY THIS EXISTS
# Every "is this deviation real?" decision in this skill compares a deviation
# against a noise floor. Those floors were previously estimated once (e.g. "about
# 0.4 dB below 600 Hz") and then reused across sessions, rigs and drivers. That is
# wrong in both directions: it makes small-but-real findings look unactionable on a
# good rig, and lets measurement scatter look actionable on a noisy one. The floor
# is a property of THIS rig on THIS day at THIS mic path -- it should be measured,
# not remembered.
#
# HOW TO CAPTURE THE INPUT
# Capture the SAME thing N times (>=3, 5 is better) changing NOTHING between runs:
# same tune, same volume, same channels unmuted, same mic technique. For MMM,
# re-walk the same path each time -- the path variation IS part of the floor you
# want to characterise. Do NOT touch the DSP, the source, or the mic mount.
#
# WHAT IT RETURNS
# A per-frequency standard deviation across the repeats, summarised per band.
# Use ~2.5x the local sigma as the "act on this" threshold (see methodology
# section "Restraint"): a deviation below that is indistinguishable from what
# this rig produces measuring the same unchanged system twice.
#
# CLI:
#   python repeatability.py floor a.txt b.txt c.txt [...]      # print the floor
#   python repeatability.py floor *.txt --json out.json        # save for reuse
#   python repeatability.py check dev.txt --floor out.json     # screen deviations
import argparse
import json
import sys

import numpy as np

import measure

# Default reporting bands. Deliberately coarse: a per-frequency sigma is noisy
# with only a handful of repeats, so report it aggregated, and let callers
# interpolate. Chosen to match where measurement behaviour actually changes
# (modal region, midrange, the short-wavelength region where mic position bites).
DEFAULT_BANDS = ((20, 60), (60, 120), (120, 300), (300, 600),
                 (600, 1400), (1400, 3000), (3000, 8000), (8000, 20000))


def load_repeats(paths, grid=None, ppo=48):
    """Load N repeat captures onto one common log grid.

    Returns (grid, matrix) where matrix is (n_repeats, n_freqs) of SPL dB.
    Raises if fewer than 2 usable files -- a 'floor' from one capture is
    not a floor, it is a single number with no spread, and silently
    returning zeros would be worse than failing."""
    if len(paths) < 2:
        raise ValueError('need >=2 repeat captures to measure a floor, got %d' % len(paths))
    loaded = []
    for p in paths:
        f, s, _, _ = measure.load_text_export(p)
        loaded.append((f, s))
    if grid is None:
        lo = max(f.min() for f, _ in loaded)
        hi = min(f.max() for f, _ in loaded)
        grid = measure.common_grid(max(lo, 20.0), min(hi, 20000.0), ppo)
    mat = np.vstack([measure.resample_log(f, s, grid) for f, s in loaded])
    return grid, mat


def level_align(mat, grid, lo=300.0, hi=3000.0):
    """Remove whole-capture level drift before measuring scatter.

    A repeat set can differ by a fraction of a dB of overall gain (source
    volume drift, a slightly different mic height). That is a real effect but
    it is NOT the frequency-dependent floor we are trying to measure -- left
    in, it inflates sigma uniformly at every frequency and hides the actual
    shape. Align on a broad mid band, then measure what is left."""
    m = (grid >= lo) & (grid <= hi)
    if m.sum() < 4:
        m = slice(None)
    offs = np.array([np.median(row[m]) for row in mat])
    return mat - offs[:, None], offs - offs.mean()


def measure_floor(paths, bands=DEFAULT_BANDS, ppo=48, align=True):
    """Per-frequency and per-band 1-sigma repeatability of this rig, right now."""
    grid, mat = load_repeats(paths, ppo=ppo)
    drift = np.zeros(len(mat))
    if align:
        mat, drift = level_align(mat, grid)
    # ddof=1: sample standard deviation. With 3-5 repeats the difference from
    # the population form is not negligible and understating sigma is the
    # dangerous direction -- it makes noise look actionable.
    sigma = mat.std(axis=0, ddof=1)
    out = {
        'n_repeats': int(mat.shape[0]),
        'files': list(paths),
        'level_drift_db': [round(float(d), 3) for d in drift],
        'bands': [],
    }
    for lo, hi in bands:
        m = (grid >= lo) & (grid < hi)
        if m.sum() == 0:
            continue
        out['bands'].append({
            'lo_hz': lo, 'hi_hz': hi,
            'sigma_db': round(float(np.median(sigma[m])), 3),
            'sigma_p90_db': round(float(np.percentile(sigma[m], 90)), 3),
            'worst_db': round(float(sigma[m].max()), 3),
            'worst_at_hz': round(float(grid[m][np.argmax(sigma[m])]), 1),
        })
    out['_grid'] = grid.tolist()
    out['_sigma'] = sigma.tolist()
    return out


def floor_at(floor, freqs):
    """Interpolate a measured floor onto arbitrary frequencies (log domain)."""
    g = np.asarray(floor['_grid'])
    s = np.asarray(floor['_sigma'])
    return np.interp(np.log2(np.asarray(freqs, dtype=float)), np.log2(g), s)


def screen(deviations, floor, factor=2.5):
    """Screen (freq, deviation_db) pairs against the MEASURED floor.

    factor=2.5 mirrors the threshold used elsewhere in this skill. Returns a
    verdict per entry rather than silently filtering, so a caller can see what
    was rejected and why -- a dropped finding should be visible, not invisible."""
    freqs = np.array([f for f, _ in deviations], dtype=float)
    devs = np.array([d for _, d in deviations], dtype=float)
    sig = floor_at(floor, freqs)
    rows = []
    for f, d, s in zip(freqs, devs, sig):
        ratio = abs(d) / s if s > 0 else np.inf
        rows.append({
            'hz': float(f), 'deviation_db': float(d), 'floor_db': round(float(s), 3),
            'ratio': round(float(ratio), 2),
            'verdict': 'ACTIONABLE' if ratio >= factor else ('marginal' if ratio >= 1.5 else 'noise'),
        })
    return rows


# ---------------------------------------------------------------- CLI
def _main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    f = sub.add_parser('floor', help='measure the floor from repeat captures')
    f.add_argument('files', nargs='+')
    f.add_argument('--json', help='write the floor to this path for reuse')
    f.add_argument('--ppo', type=int, default=48)
    f.add_argument('--no-align', action='store_true')
    c = sub.add_parser('check', help='screen deviations against a saved floor')
    c.add_argument('--floor', required=True)
    c.add_argument('--dev', nargs='+', required=True, metavar='HZ:DB')
    c.add_argument('--factor', type=float, default=2.5)
    a = ap.parse_args()

    if a.cmd == 'floor':
        fl = measure_floor(a.files, ppo=a.ppo, align=not a.no_align)
        print('repeats: %d' % fl['n_repeats'])
        print('level drift between captures (dB): %s' %
              ', '.join('%+.2f' % d for d in fl['level_drift_db']))
        print('\n%-16s %9s %9s %9s' % ('band', 'sigma', 'p90', 'worst'))
        for b in fl['bands']:
            print('%5.0f-%-10.0f %9.3f %9.3f %9.3f  (worst @ %.0f Hz)' %
                  (b['lo_hz'], b['hi_hz'], b['sigma_db'], b['sigma_p90_db'],
                   b['worst_db'], b['worst_at_hz']))
        print('\nact on a deviation only above ~2.5x sigma for its band.')
        if a.json:
            json.dump(fl, open(a.json, 'w'))
            print('wrote %s' % a.json)

    elif a.cmd == 'check':
        fl = json.load(open(a.floor))
        devs = []
        for d in a.dev:
            hz, db = d.split(':')
            devs.append((float(hz), float(db)))
        for r in screen(devs, fl, a.factor):
            print('%8.0f Hz  dev %+6.2f  floor %.2f  ratio %5.2f  %s' %
                  (r['hz'], r['deviation_db'], r['floor_db'], r['ratio'], r['verdict']))


def _selftest():
    """Synthetic: a known noise level must be recovered, and a known signal
    must survive screening while a sub-floor one must not."""
    import tempfile
    import os
    rng = np.random.default_rng(0)
    freqs = measure.common_grid(20, 20000, 48)
    base = 80 - 6 * np.log2(freqs / 100)
    NOISE = 0.30
    paths = []
    d = tempfile.mkdtemp()
    for i in range(5):
        s = base + rng.normal(0, NOISE, len(freqs))
        p = os.path.join(d, 'r%d.txt' % i)
        with open(p, 'w') as fh:
            fh.write('* synthetic\n')
            for a_, b_ in zip(freqs, s):
                fh.write('%.4f %.4f 0.0\n' % (a_, b_))
        paths.append(p)
    fl = measure_floor(paths)
    assert fl['n_repeats'] == 5
    mids = [b['sigma_db'] for b in fl['bands'] if 120 <= b['lo_hz'] <= 3000]
    got = float(np.median(mids))
    assert abs(got - NOISE) < 0.08, 'recovered sigma %.3f vs injected %.3f' % (got, NOISE)
    print('repeatability selftest: recovers injected sigma (%.3f vs %.3f) OK' % (got, NOISE))

    rows = screen([(1000, 2.0), (1000, 0.2)], fl)
    assert rows[0]['verdict'] == 'ACTIONABLE', rows[0]
    assert rows[1]['verdict'] == 'noise', rows[1]
    print('repeatability selftest: screening keeps real / rejects sub-floor OK')

    try:
        measure_floor(paths[:1])
        raise AssertionError('should have refused a single capture')
    except ValueError:
        print('repeatability selftest: refuses <2 captures OK')

    # a pure level offset between captures must NOT inflate the floor
    shifted = []
    for i, p in enumerate(paths):
        q = p.replace('.txt', '_shift.txt')
        lines = [l for l in open(p) if not l.startswith('*')]
        with open(q, 'w') as fh:
            fh.write('* synthetic\n')
            for l in lines:
                a_, b_, c_ = l.split()
                fh.write('%s %.4f %s\n' % (a_, float(b_) + i * 0.5, c_))
        shifted.append(q)
    fl2 = measure_floor(shifted)
    mids2 = float(np.median([b['sigma_db'] for b in fl2['bands'] if 120 <= b['lo_hz'] <= 3000]))
    assert abs(mids2 - NOISE) < 0.08, 'level drift leaked into floor: %.3f' % mids2
    print('repeatability selftest: level drift removed, not counted as floor OK')
    print('\nALL REPEATABILITY SELFTESTS PASSED')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'selftest':
        _selftest()
    else:
        _main()
