# measure.py -- load measurements + target curve onto a common frequency grid.
#
# TWO input paths, both axis-explicit:
#   1) REW TEXT EXPORT: "Freq  SPL  Phase" columns. Export from REW with:
#      File > Export > Export measurement as text. An optional 4th column
#      (coherence, 0..1) is read if present -- REW's normal sweep export
#      doesn't provide one (that needs a dual-channel reference-vs-measured
#      capture a deconvolved sweep isn't), so this is forward-compatibility for
#      a different capture chain, not something to expect from a typical file.
#   2) REW .mdat, addressed as "file.mdat::Name" or "file.mdat::#3" (or a bare
#      file.mdat holding one measurement). mdat.py reads the Java object stream
#      by structure: the axis is the one REW states, and the values are the
#      UNSMOOTHED rawValues. The old byte scanner (which picked the mic cal
#      curve or a distortion array) is gone.
#
# Every loader below takes either form, and read_export_header reads the
# whole REW header: version, source (mic, gain, channel, input volume),
# format (RTA resolution, FFT, window, averages or the sweep), date, the
# level notes (Input RMS, dB A, dB C, 22-22k, >22k), smoothing and axis.
#
# CLI:
#   python measure.py textcols <export.txt | file.mdat::name>   # peek columns
#   python measure.py header <export.txt | file.mdat::name>     # parsed header, JSON
#   python measure.py mdat <file.mdat>                           # list its measurements
import datetime
import json
import math
import re
import sys

import numpy as np


_DECIMAL_COMMA = re.compile(r'-?\d+,\d+')


def _read_lines(path):
    """Lines of a text export, whichever Windows tool last saved it: UTF-8
    with or without a BOM, UTF-16 (Excel's "Unicode Text"; BOM or not), or a
    legacy code page. Undecodable bytes are replaced -- only header text,
    never a number, carries them in practice."""
    with open(path, 'rb') as fh:
        raw = fh.read()
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16', errors='replace').splitlines()
    head = raw[:400]
    if head[1::2].count(0) > len(head) // 4:
        return raw.decode('utf-16-le', errors='replace').splitlines()
    if head[0::2].count(0) > len(head) // 4:
        return raw.decode('utf-16-be', errors='replace').splitlines()
    return raw.decode('utf-8-sig', errors='replace').splitlines()


def _split_row(line):
    """Split one numeric row. Whitespace/semicolon-separated tokens written
    with a decimal comma ("20,508  72,3  -45,2", as REW writes in comma-decimal
    locales) are read as decimals; otherwise commas are field separators.
    Spreadsheet quoting ("20.000","72.3") is removed first."""
    line = line.replace('"', '')
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
    import mdat
    if mdat.is_spec(path):
        f, s, p = mdat.values(mdat.select(path))
        _check_freq_axis(f, path)
        return f, s, p, None
    f, s, p, coh = [], [], [], []
    for line in _read_lines(path):
        line = line.strip().lstrip('"')
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
    and REW's own text-export headers ("Smoothing: 1/48 octave").

    'rew' holds the rest of REW's header, parsed (parse_rew_header): every
    field is None when the header does not carry it. An .mdat measurement is
    read through the same text, so both sources give the same keys; the
    .mdat adds the mic serial and cal file, which a text export lacks."""
    import mdat
    if mdat.is_spec(path):
        lines = mdat.header_lines(mdat.select(path))
    else:
        lines = []
        for raw in _read_lines(path):
            line = raw.strip()
            if not line:
                continue
            if line[0] in '*#/' or line[0].isalpha():
                lines.append(line.lstrip('*#/ ').strip())
    out = {'timing_reference': None, 'timing_reference_text': None,
           'smoothing': None, 'unsmoothed': None, 'lines': lines,
           'rew': parse_rew_header(lines)}
    # REW's Format and Note lines describe the RTA's own settings ("..., no
    # smoothing and 31 averages") and a sweep's timing ("using a loopback as a
    # timing reference"), not the export: reading "smoothing and 31 averages"
    # there as the export's smoothing was a real misread. The explicit
    # "Smoothing:" line wins; the free-text search skips those lines.
    described = [ln for ln in lines if not re.match(r'(?i)(format|note|notes)\s*:', ln)]
    explicit = [ln for ln in described if re.match(r'(?i)smoothing\s*:', ln)]
    for line in explicit + [ln for ln in described if ln not in explicit]:
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
    if out['timing_reference'] is None and (out['rew']['format'] or {}).get('kind') == 'sweep':
        timing = out['rew']['format'].get('timing_reference')
        if timing:
            out['timing_reference'], out['timing_reference_text'] = True, timing
    return out


# ------------------------------------------------------------ REW header fields
_FMT_RTA = re.compile(r'(\d+)-point\s+1/(\d+)\s+octave\s+RTA', re.I)
_FMT_SPECTRUM = re.compile(r'(\d+)-point\s+(?:spectrum|FFT)', re.I)
_FMT_WINDOW = re.compile(r'using\s+(?:an?\s+)?(.+?)\s+window', re.I)
_FMT_SMOOTH = re.compile(r',\s*([^,]+?)\s+smoothing', re.I)
_FMT_AVG = re.compile(r'(\d+)\s+averages', re.I)
_FMT_SWEEP = re.compile(r'(\d+)k\s+Log\s+Swept\s+Sine(?:,\s*(\d+)\s+sweeps?)?(?:\s+at\s+(-?[\d.]+)\s*dBFS)?',
                        re.I)
_NUM = r'(-?\d+(?:\.\d+)?)'


def parse_rew_format(text):
    """REW's Format text -> {'kind': 'rta' | 'spectrum' | 'sweep' | None, ...}.

    RTA: fft_length, rta_fraction (N of 1/N octave), window, rta_smoothing,
    averages. Sweep: sweep_length, sweeps, level_dbfs, timing_reference
    ('loopback' | 'acoustic' | None). 'summary' is a short label."""
    text = ' '.join((text or '').split())
    out = {'kind': None, 'text': text or None, 'summary': None}
    if not text:
        return out
    m = _FMT_RTA.search(text)
    s = _FMT_SPECTRUM.search(text)
    w = _FMT_SWEEP.search(text)
    if m or s:
        out['kind'] = 'rta' if m else 'spectrum'
        out['fft_length'] = int((m or s).group(1))
        out['rta_fraction'] = int(m.group(2)) if m else None
        win = _FMT_WINDOW.search(text)
        out['window'] = win.group(1).strip() if win else None
        sm = _FMT_SMOOTH.search(text)
        smooth = sm.group(1).strip() if sm else None
        out['rta_smoothing'] = 'none' if smooth and smooth.lower() in ('no', 'none') else smooth
        avg = _FMT_AVG.search(text)
        out['averages'] = int(avg.group(1)) if avg else None
        out['summary'] = '%s %s%s, %s window, %s avg' % (
            '%dk' % (out['fft_length'] // 1024) if out['fft_length'] >= 1024 else out['fft_length'],
            'RTA 1/%d' % out['rta_fraction'] if m else 'spectrum',
            '' if not out['rta_smoothing'] or out['rta_smoothing'] == 'none' else
            ' (%s smoothed)' % out['rta_smoothing'],
            out['window'] or '?', out['averages'] if out['averages'] is not None else '?')
    elif w:
        out['kind'] = 'sweep'
        out['sweep_length'] = int(w.group(1)) * 1024
        out['sweeps'] = int(w.group(2)) if w.group(2) else None
        out['level_dbfs'] = float(w.group(3)) if w.group(3) else None
        low = text.lower()
        out['timing_reference'] = ('loopback' if 'loopback' in low and 'timing' in low else
                                   'acoustic' if 'acoustic' in low and 'timing' in low else None)
        out['summary'] = '%dk sweep x%s%s' % (int(w.group(1)), out['sweeps'] or '?',
                                             ', %s timing' % out['timing_reference']
                                             if out['timing_reference'] else '')
    return out


def _db_power(*levels):
    return sum(10.0 ** (x / 10.0) for x in levels if x is not None)


def parse_level_notes(text):
    """REW's RTA level notes -> dB values (None where absent).

    input_rms_db (whole input, unweighted, including below 22 Hz), dbc, dba,
    unw_22_22k_db, above_22k_db, and below_22_db derived from the power left
    over: Input RMS minus the 22 Hz-22 kHz and >22 kHz parts. In car MMM
    captures that remainder is mic handling, air movement or infrasound --
    never the speakers' music band. Units are REW's (dB SPL with a mic cal)."""
    text = ' '.join((text or '').split())
    pick = lambda pattern: (float(re.search(pattern, text, re.I).group(1))
                            if re.search(pattern, text, re.I) else None)
    out = {'input_rms_db': pick(r'Input RMS\s+' + _NUM + r'\s*dB'),
           'dbc': pick(_NUM + r'\s*dB\s*C\b'),
           'dba': pick(_NUM + r'\s*dB\s*A\b'),
           'unw_22_22k_db': pick(_NUM + r'\s*dB\s*22\s*-\s*22k'),
           'above_22k_db': pick(_NUM + r'\s*dB\s*>\s*22k'),
           'below_22_db': None}
    if out['input_rms_db'] is not None and out['unw_22_22k_db'] is not None:
        rest = _db_power(out['input_rms_db']) - _db_power(out['unw_22_22k_db'], out['above_22k_db'])
        floor = 10.0 ** ((out['input_rms_db'] - 30.0) / 10.0)   # below 30 dB down: not resolvable
        out['below_22_db'] = round(10.0 * math.log10(rest), 1) if rest > floor else None
    return out


def _split_top(text):
    """Split on commas outside parentheses."""
    parts, depth, cur = [], 0, ''
    for ch in text:
        depth += ch == '('
        depth -= ch == ')'
        if ch == ',' and depth == 0:
            parts.append(cur.strip())
            cur = ''
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def parse_source(text):
    """REW's Source text ("EXCL: Microphone (Umik-1  Gain: 18dB  ), MICROPHONE
    (Master Volume), L, volume: 0.950") -> device, mic_model, gain_db,
    channel, input_volume (None when REW has no control), exclusive."""
    text = ' '.join((text or '').split())
    out = {'text': text or None, 'device': None, 'mic_model': None, 'gain_db': None,
           'channel': None, 'input_volume': None, 'exclusive': None}
    if not text:
        return out
    out['exclusive'] = text.upper().startswith('EXCL:')
    body = re.sub(r'(?i)^excl:\s*', '', text)
    parts = _split_top(body)
    out['device'] = parts[0] if parts else None
    mic = re.search(r'umik[\s-]?(\d)', body, re.I)
    out['mic_model'] = 'UMIK-%s' % mic.group(1) if mic else None
    gain = re.search(r'gain:?\s*' + _NUM + r'\s*dB', body, re.I)
    out['gain_db'] = float(gain.group(1)) if gain else None
    for part in parts[1:]:
        if re.fullmatch(r'(?i)(l|r|left|right|\d+)', part):
            out['channel'] = part
    vol = re.search(r'volume:\s*' + _NUM, body, re.I)
    out['input_volume'] = float(vol.group(1)) if vol else None
    return out


def parse_rew_date(text):
    """REW's Dated text -> ISO time, or None (other locales are left unparsed)."""
    text = (text or '').strip()
    for fmt in ('%b %d, %Y, %I:%M:%S %p', '%b %d, %Y %I:%M:%S %p', '%Y-%m-%dT%H:%M:%S',
                '%d %b %Y, %H:%M:%S', '%d-%b-%Y %H:%M:%S'):
        try:
            return datetime.datetime.strptime(text.replace(' ', ' '), fmt).isoformat(timespec='seconds')
        except ValueError:
            continue
    return None


def parse_rew_header(lines):
    """Every REW header field the skill uses, from a text export's comment
    lines (or an .mdat's, via mdat.header_lines). Missing fields are None."""
    field = {}
    for line in lines:
        m = re.match(r'(?i)(measurement data .*?|source|format|dated|note|notes|measurement|'
                     r'smoothing|frequency step|start frequency|output|sample rate|mic)\s*:?\s*(.*)$',
                     line)
        if not m:
            continue
        key = m.group(1).lower()
        key = 'version' if key.startswith('measurement data') else key
        if key == 'version':
            v = re.search(r'REW\s+V?(\d+\.\d+(?:\.\d+)?(?:\s*beta\s*\d+)?)', line, re.I)
            field.setdefault('version', v.group(1) if v else None)
        else:
            field.setdefault('notes' if key == 'note' else key, m.group(2).strip())
    fmt = parse_rew_format(field.get('format'))
    notes = field.get('notes') or ''
    if fmt['kind'] is None and notes:
        fmt = parse_rew_format(notes)           # the Note line repeats the format
    mic = re.match(r'serial\s+(\S+),\s*cal\s+(.+)$', field.get('mic') or '')
    step = field.get('frequency step') or ''
    ppo = re.match(r'(\d+)\s*ppo', step, re.I)
    hz = re.match(_NUM + r'\s*Hz', step, re.I)
    start = re.match(_NUM, field.get('start frequency') or '')
    rate = re.match(_NUM, field.get('sample rate') or '')
    dated = field.get('dated')
    return {
        'version': field.get('version'),
        'source': parse_source(field.get('source')),
        'format': fmt,
        'date': (parse_rew_date(dated) or (dated if dated and re.match(r'\d{4}-\d\d-\d\dT', dated) else None)),
        'date_text': dated,
        'levels': parse_level_notes(notes),
        'measurement': field.get('measurement'),
        'smoothing': field.get('smoothing'),
        'ppo': int(ppo.group(1)) if ppo else None,
        'freq_step_hz': float(hz.group(1)) if hz and not ppo else None,
        'start_frequency_hz': float(start.group(1)) if start else None,
        'output': field.get('output'),
        'sample_rate_hz': float(rate.group(1)) if rate else None,
        'mic_serial': None if not mic or mic.group(1) == 'unknown' else mic.group(1),
        'mic_cal_file': None if not mic or mic.group(2) == 'unknown' else mic.group(2),
    }


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


def load_target(path, freqs):
    """Load a target curve (freq, level) text file, interpolate onto `freqs`.
    Level anchoring (matching overall loudness) is done by the caller."""
    f, s = [], []
    for line in _read_lines(path):
        line = line.strip().lstrip('"')
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
        print('usage: python measure.py {textcols|header|mdat} <file>'); sys.exit(1)
    cmd, path = sys.argv[1], sys.argv[2]
    try:
        if cmd == 'textcols':
            f, s, p, coh = load_text_export(path)
            print('%d points, %.1f-%.0f Hz, SPL %.1f..%.1f dB, phase: %s, coherence: %s'
                  % (len(f), f[0], f[-1], s.min(), s.max(),
                     'yes' if p is not None else 'no', 'yes' if coh is not None else 'no'))
        elif cmd == 'header':
            hdr = read_export_header(path)
            print(json.dumps({k: v for k, v in hdr.items() if k != 'lines'}, indent=2))
        elif cmd == 'mdat':
            import mdat
            sys.exit(mdat._main(['list', path]))
        else:
            print('unknown command %r' % cmd); sys.exit(1)
    except (ValueError, OSError) as exc:
        print('error: %s' % exc, file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    _main()
