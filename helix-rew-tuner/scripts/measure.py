# measure.py -- load measurements + target curve onto a common frequency grid.
#
# TWO input paths, in order of robustness:
#   1) REW TEXT EXPORT (recommended): "Freq  SPL  Phase" columns. Axis is explicit
#      and unambiguous, phase is available for real crossover/APF work. Export from
#      REW with: File > Export > Export measurement as text. An optional 4th
#      column (coherence, 0..1) is read if present -- REW's normal sweep export
#      doesn't provide one (that needs a dual-channel reference-vs-measured
#      capture a deconvolved sweep isn't), so this is forward-compatibility for
#      a different capture chain, not something to expect from a typical file.
#   2) REW .mdat (convenience, MUST be validated): the binary carries float32 SPL
#      arrays but the frequency axis is reconstructed by assumption (log-spaced,
#      anchored at the top). ALWAYS validate the reconstructed axis against a known
#      feature (a crossover corner you know) before trusting it.
#
# CLI:
#   python measure.py textcols <export.txt>          # peek columns
#   python measure.py mdat <file.mdat>               # list SPL arrays found + axis guess
import re
import struct
import sys

import numpy as np


_DECIMAL_COMMA = re.compile(r'-?\d+,\d+')


def _split_row(line):
    """Split one numeric row. Whitespace/semicolon-separated tokens written
    with a decimal comma ("20,508  72,3  -45,2", as REW writes in comma-decimal
    locales) are read as decimals; otherwise commas are field separators."""
    tokens = [t for t in re.split(r'[\s;]+', line) if t]
    if (len(tokens) >= 2 and '.' not in line
            and any(_DECIMAL_COMMA.fullmatch(t) for t in tokens)):
        return [t.replace(',', '.') for t in tokens]
    return line.replace(',', ' ').split()


def load_text_export(path):
    """REW text export -> (freqs, spl_db, phase_deg or None, coherence or None).
    Whitespace or comma separated; skips headers/comment lines. This is the
    robust, axis-explicit path.

    Standard REW sweep exports are freq/SPL/phase (3 columns) -- coherence is
    NOT a column REW's sweep-based text export provides (coherence needs a
    genuine dual-channel reference-vs-measured capture, which a deconvolved
    sweep isn't). This loader optionally reads a 4th numeric column as
    coherence (0..1) if present, for forward-compatibility with a different
    capture chain that does provide it -- it's simply None if the file only
    has 3 columns, which is the normal case. When coherence IS available,
    it's a natural `conf` weight for prediction_confidence/fit_peq -- the
    Smaart-style trust signal this project's usual REW-only pipeline can't
    otherwise compute (see methodology.md)."""
    f, s, p, coh = [], [], [], []
    with open(path, encoding='utf-8', errors='replace') as fh:
        lines = fh.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line[0].isalpha() or line[0] in '*#/':
            continue
        parts = _split_row(line)
        try:
            f.append(float(parts[0]))
            s.append(float(parts[1]))
            p.append(float(parts[2]) if len(parts) > 2 else np.nan)
            coh.append(float(parts[3]) if len(parts) > 3 else np.nan)
        except (ValueError, IndexError):
            continue
    if len(f) < 8:
        raise ValueError('found <8 usable data rows in %s -- is this a REW text export?' % path)
    f, s, p, coh = np.array(f), np.array(s), np.array(p), np.array(coh)
    _check_freq_axis(f, path)
    if not np.isfinite(s).all():
        raise ValueError('non-finite SPL value in %s' % path)
    # A column is all-or-nothing: a phase column with holes would be
    # interpolated straight across them and read as real phase.
    for name, col in (('phase', p), ('coherence', coh)):
        if np.isfinite(col).any() and not np.isfinite(col).all():
            raise ValueError('%s column is incomplete in %s (%d of %d rows missing) -- '
                             're-export the whole measurement'
                             % (name, path, int(np.count_nonzero(~np.isfinite(col))), len(col)))
    return f, s, (p if np.isfinite(p).any() else None), (coh if np.isfinite(coh).any() else None)


_TIMING_RE = re.compile(r'timing\s*ref(?:erence)?\s*[:=]?\s*(.+)', re.I)
_SMOOTHING_RE = re.compile(r'smooth(?:ing|ed)?\s*[:=]?\s*([^,;]+)', re.I)
_NO_VALUE = ('none', 'no', 'off', 'n/a', '-', 'false')


def read_export_header(path):
    """What the export's comment header says about how it was captured.

    The numeric rows say nothing about whether two captures share a time
    base or how much they were smoothed, and both decide what the data may
    be used for. Returns {'timing_reference': True | False | None,
    'timing_reference_text', 'smoothing', 'unsmoothed': True | False | None,
    'lines'}. None means the header does not say -- unknown, not absent.

    Reads this skill's rew_api.py headers ("timing reference: Acoustic",
    "timing reference: NONE -- no shared time base", "smoothing 1/48, ...")
    and REW's own text-export headers ("Smoothing: 1/48 octave")."""
    lines = []
    with open(path, encoding='utf-8', errors='replace') as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if line[0] in '*#/' or line[0].isalpha():
                lines.append(line.lstrip('*#/ ').strip())
    out = {'timing_reference': None, 'timing_reference_text': None,
           'smoothing': None, 'unsmoothed': None, 'lines': lines}
    for line in lines:
        m = _TIMING_RE.search(line)
        if m and out['timing_reference'] is None:
            text = m.group(1).strip()
            out['timing_reference_text'] = text
            first = re.split(r'[\s,;(]+', text.lower(), maxsplit=1)[0]
            out['timing_reference'] = first not in _NO_VALUE
            continue
        m = _SMOOTHING_RE.search(line)
        if m and out['smoothing'] is None and 'freq(hz)' not in line.lower():
            text = m.group(1).strip()
            out['smoothing'] = text
            out['unsmoothed'] = text.lower().split()[0] in _NO_VALUE if text else None
    return out


def support_mask(freqs_src, freqs_dst, edge_tol=1e-6):
    """True where freqs_dst lies inside the measured range of freqs_src.

    resample_log (np.interp) holds the end values flat past either end, so a
    200 Hz-2 kHz capture looks like data at 20 Hz and 20 kHz. Anything that
    anchors, fits or scores must use this mask to stay on measured bins."""
    freqs_src = np.asarray(freqs_src, dtype=float)
    freqs_dst = np.asarray(freqs_dst, dtype=float)
    lo, hi = freqs_src[0] * (1 - edge_tol), freqs_src[-1] * (1 + edge_tol)
    return (freqs_dst >= lo) & (freqs_dst <= hi)


def phase_step_check(freqs_src, phase_deg, max_median_step_deg=90.0, run=8):
    """Can this phase trace be unwrapped unambiguously?

    np.unwrap assumes the true change between neighbouring bins is under
    180 degrees. A late arrival on a coarse grid breaks that silently (a 5 ms
    delay advances 180 degrees every 100 Hz, so a 1/48-octave grid fails
    above ~7 kHz). That failure is SUSTAINED: every step from some frequency
    up is large. An isolated near-180 degree jump is different -- it is what
    a deep cancellation null really does, and the boost gate needs to see it.
    So a trace fails only where the median of `run` consecutive steps
    exceeds max_median_step_deg. Returns {'ok', 'worst_step_deg',
    'first_bad_hz'}."""
    ph = np.unwrap(np.deg2rad(np.asarray(phase_deg, dtype=float)))
    steps = np.abs(np.rad2deg(np.diff(ph)))
    out = {'ok': True, 'worst_step_deg': round(float(steps.max()), 1) if steps.size else 0.0,
           'first_bad_hz': None}
    if steps.size < run:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(steps, run)
    bad = np.nonzero(np.median(windows, axis=1) > max_median_step_deg)[0]
    if bad.size:
        out['ok'] = False
        out['first_bad_hz'] = round(float(freqs_src[bad[0] + 1]), 1)
    return out


def resample_phase(freqs_src, phase_deg, freqs_dst):
    """Unwrap first, then interpolate in log-frequency; returns unwrapped
    degrees. Interpolating wrapped phase puts the midpoint of +179 and -179
    at 0 instead of 180 -- every phase path must come through here."""
    unwrapped = np.rad2deg(np.unwrap(np.deg2rad(np.asarray(phase_deg, dtype=float))))
    return resample_log(freqs_src, unwrapped, freqs_dst)


def load_complex(path, freqs_dst, require_phase=True):
    """One loader for every phase-bearing analysis.

    Returns {'db', 'phase_deg' (unwrapped, or None), 'complex' (or None),
    'support' (measured-range mask on freqs_dst), 'phase_support' (bins
    whose phase is measured AND below any unwrap failure), 'phase_limit_hz'
    (where unwrapping stops being reliable, or None), 'header'
    (read_export_header), 'phase_check' (phase_step_check, or None),
    'path'}. With require_phase, a missing phase column raises.

    An unwrap failure only corrupts bins ABOVE it (unwrapping accumulates
    upward), so a trace is not rejected outright: a 3.5 ms flight time on
    REW's 96-PPO API grid goes ambiguous near 10 kHz, which says nothing
    about a 3 kHz junction. Each analysis checks its own band against
    phase_limit_hz instead."""
    f, s, ph, _coh = load_text_export(path)
    if ph is None and require_phase:
        raise ValueError('%s has no phase column -- this analysis needs complex data' % path)
    db = resample_log(f, s, freqs_dst)
    out = {'path': path, 'db': db, 'phase_deg': None, 'complex': None,
           'support': support_mask(f, freqs_dst), 'header': read_export_header(path),
           'phase_check': None, 'phase_limit_hz': None,
           'phase_support': np.zeros_like(freqs_dst, dtype=bool)}
    if ph is not None:
        chk = phase_step_check(f, ph)
        out['phase_check'] = chk
        out['phase_deg'] = resample_phase(f, ph, freqs_dst)
        out['complex'] = 10 ** (db / 20.0) * np.exp(1j * np.deg2rad(out['phase_deg']))
        out['phase_support'] = out['support'].copy()
        if not chk['ok']:
            out['phase_limit_hz'] = chk['first_bad_hz']
            out['phase_support'] &= np.asarray(freqs_dst) < chk['first_bad_hz']
    return out


def shared_timing_problem(*loaded):
    """Why these captures may NOT be compared in phase, or None if nothing
    says they can't. A phase column is not proof of a shared time base:
    REW only puts separate captures on one time axis when each used the
    same timing reference. An explicit 'none' in any header refuses relative
    phase work; a header that does not say is left to the operator."""
    for item in loaded:
        if item['header']['timing_reference'] is False:
            return ('%s says it has no timing reference (%s) -- its phase is not on a '
                    'shared time base, so delays, junction phase and imaging time cues '
                    'cannot be read from it' % (item['path'], item['header']['timing_reference_text']))
    return None


def timing_unstated(*loaded):
    """Paths whose header does not say whether a timing reference was used."""
    return [item['path'] for item in loaded if item['header']['timing_reference'] is None]


def unwrap_problem(*loaded, band=None):
    """Why phase cannot be trusted across `band` (lo, hi) -- the first trace
    whose unwrap limit falls inside it, as a message -- or None. Without a
    band, any unwrap limit at all is reported."""
    for item in loaded:
        limit = item.get('phase_limit_hz')
        if limit is not None and (band is None or limit < band[1]):
            return ('%s: phase moves too far between neighbouring points from %.0f Hz to unwrap '
                    'reliably%s (export at a finer resolution, or remove the bulk delay first)'
                    % (item['path'], limit,
                       '' if band is None else ', inside the %.0f-%.0f Hz band this needs'
                       % (band[0], band[1])))
    return None


def _check_freq_axis(f, path):
    """np.interp and every log-frequency step assume a positive, strictly
    increasing axis; anything else resamples to plausible-looking garbage
    instead of failing. A decimal-comma export ("20,508  72,3") is the usual
    cause: the comma splits each number, so the axis repeats values."""
    if not np.isfinite(f).all() or (f <= 0).any():
        raise ValueError('frequency column must be finite and positive in %s' % path)
    if (np.diff(f) <= 0).any():
        raise ValueError('frequency column is not strictly increasing in %s -- a '
                         'decimal-comma export? Re-export from REW with "." as the '
                         'decimal separator' % path)


def resample_log(freqs_src, y_src, freqs_dst):
    """Interpolate onto a target grid in log-frequency (correct for audio).
    Magnitude only: outside the measured range the end values are held
    flat (see support_mask), and phase must go through resample_phase."""
    return np.interp(np.log10(freqs_dst), np.log10(freqs_src), y_src)


def common_grid(lo=20.0, hi=20000.0, ppo=96):
    """A clean log grid (points-per-octave). Use to align multiple traces.
    96 PPO matches REW's default and pipeline.py's analysis grid."""
    n = int(round(np.log2(hi / lo) * ppo)) + 1
    return lo * 2 ** (np.arange(n) / ppo)


# ------------------------------------------------------------ .mdat (validated fallback)
def mdat_spl_arrays(path, min_len=256):
    """Extract float32 SPL arrays from a REW .mdat (Java-serialized). Returns list
    of (offset, length, array). The frequency AXIS is NOT in here reliably -- you
    must reconstruct and validate it (see reconstruct_axis)."""
    with open(path, 'rb') as fh:
        data = fh.read()
    out, i = [], 0
    while True:
        j = data.find(b'\x75\x71\x00\x7e', i)
        if j < 0:
            break
        p = j + 6
        n = struct.unpack('>I', data[p:p + 4])[0]
        body = p + 4
        if 0 < n < 5_000_000 and body + 4 * n <= len(data):
            a = np.frombuffer(data[body:body + 4 * n], dtype='>f4')
            with np.errstate(invalid='ignore'):
                if n >= min_len and np.isfinite(a).all():
                    out.append((j, n, a.astype(float)))
        i = j + 2
    return out


def reconstruct_axis(n, ppo=96, top_hz=24000.0):
    """Rebuild the likely log axis for an n-point REW magnitude array. ppo and
    top_hz depend on the user's REW FFT/PPO settings -- these are the common
    defaults. VALIDATE with validate_axis before trusting."""
    step = 2 ** (1.0 / ppo)
    return top_hz / (step ** (n - 1 - np.arange(n)))


def validate_axis(freqs, spl, known_feature_hz, expect):
    """Confirm a reconstructed axis by checking a feature you already know.
    `expect` in {'rolloff_above','rolloff_below','peak_near','dip_near'}.
    Returns (ok, message)."""
    at = lambda x: int(np.argmin(np.abs(freqs - x)))
    fi = at(known_feature_hz)
    if expect == 'rolloff_above':
        ok = spl[at(known_feature_hz)] - spl[at(known_feature_hz * 2)] > 8
    elif expect == 'rolloff_below':
        ok = spl[at(known_feature_hz)] - spl[at(known_feature_hz / 2)] > 8
    elif expect in ('peak_near', 'dip_near'):
        w = (freqs > known_feature_hz / 1.3) & (freqs < known_feature_hz * 1.3)
        idx = np.argmax(spl[w]) if expect == 'peak_near' else np.argmin(spl[w])
        found = freqs[w][idx]
        ok = abs(np.log2(found / known_feature_hz)) < 1 / 3.0
    else:
        return False, 'unknown expectation'
    return bool(ok), ('axis OK at %g Hz' % known_feature_hz if ok
                      else 'axis FAILED near %g Hz -- adjust ppo/top_hz or use text export' % known_feature_hz)


def load_target(path, freqs):
    """Load a target curve (freq, level) text file, interpolate onto `freqs`.
    Level anchoring (matching overall loudness) is done by the caller."""
    f, s = [], []
    with open(path, encoding='utf-8', errors='replace') as fh:
        lines = fh.read().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line[0].isalpha() or line[0] in '*#/':
            continue
        parts = _split_row(line)
        try:
            f.append(float(parts[0])); s.append(float(parts[1]))
        except (ValueError, IndexError):
            continue
    if len(f) < 2:
        raise ValueError('target curve needs >=2 (freq, level) rows: %s' % path)
    f, s = np.array(f), np.array(s)
    order = np.argsort(f, kind='stable')   # hand-made curves are often high-to-low
    f, s = f[order], s[order]
    if (np.diff(f) == 0).any():
        raise ValueError('target curve has duplicate frequencies: %s' % path)
    _check_freq_axis(f, path)
    if not np.isfinite(s).all():
        raise ValueError('non-finite level value in target curve %s' % path)
    return np.interp(np.log10(freqs), np.log10(f), s)


def _main():
    if len(sys.argv) < 3:
        print('usage: python measure.py {textcols|mdat} <file>'); sys.exit(1)
    cmd, path = sys.argv[1], sys.argv[2]
    if cmd == 'textcols':
        f, s, p, coh = load_text_export(path)
        print('%d points, %.1f-%.0f Hz, SPL %.1f..%.1f dB, phase: %s, coherence: %s'
              % (len(f), f[0], f[-1], s.min(), s.max(),
                 'yes' if p is not None else 'no', 'yes' if coh is not None else 'no'))
    elif cmd == 'mdat':
        arrs = mdat_spl_arrays(path)
        spl = [(j, n, a) for j, n, a in arrs if 0 < a.max() < 130 and a.min() > -60]
        print('%d SPL-like arrays found (lengths: %s)'
              % (len(spl), sorted(set(n for _, n, _ in spl))))
        if spl:
            n = spl[0][1]
            ax = reconstruct_axis(n)
            print('reconstructed axis for n=%d (ppo=96, top=24k): %.1f-%.0f Hz' % (n, ax[0], ax[-1]))
            print('NOTE: validate this axis with a known crossover corner before trusting it.')


if __name__ == '__main__':
    _main()
