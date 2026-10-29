# mdat.py -- read REW .mdat files by structure, not by guessing.
#
# An .mdat is a Java Object Serialization Stream: a header string ("REW
# Measurement Data File V2"), the REW version, the file notes, then one
# roomeqwizard.MeasData object per measurement. Each MeasData states its own
# frequency axis (startFreq + logStep or freqStep, dataLength), so nothing is
# reconstructed. The byte scanner this replaces picked whichever float array
# came first: on an RTA file that was the mic calibration curve, on a sweep
# file a distortion array on an axis 21% wrong.
#
# What each measurement carries (field names as REW writes them; meanings are
# read from the names and values of real files, REW does not document them):
#   shortDesc, sourceFileDate      name, capture time (ms since epoch)
#   splValues / rawValues          as displayed (smoothed by octaveFrac) / unsmoothed
#   phaseValues                    sweeps only
#   sourceFileFormat, measNotes    "65536-point 1/24 octave RTA using Hann window, ...
#                                  and 31 averages" and the Input RMS / A / C notes
#   meterCal                       mic serial, cal file name, sensitivity, cal curve
#   sourceFileName, outputName     input device/gain/channel/volume, playback device
#   irData, distortionData         sweeps: impulse response, timing reference and
#                                  delay, SNR, harmonics, noise floor
#
# Security: the stream is DATA. This reader only builds Python values from it;
# nothing in the file can run code, and array sizes are checked against the
# bytes actually present before anything is allocated.
#
# A measurement is addressed as  file.mdat::Name  or  file.mdat::#3  (1-based,
# REW's own order). Every loader in measure.py accepts that form, so one
# .mdat can stand in for a folder of text exports.
#
# CLI:
#   python mdat.py list <file.mdat> [--json]
#   python mdat.py export "<file.mdat>::<name>" --out name.txt [--smoothed]
#   python mdat.py export-all <file.mdat> --out-dir DIR
import argparse
import datetime
import json
import os
import re
import struct
import sys

import numpy as np

MAGIC = 0xACED
TC_NULL, TC_REFERENCE, TC_CLASSDESC, TC_OBJECT, TC_STRING, TC_ARRAY = 0x70, 0x71, 0x72, 0x73, 0x74, 0x75
TC_CLASS, TC_BLOCKDATA, TC_ENDBLOCKDATA, TC_RESET, TC_BLOCKDATALONG = 0x76, 0x77, 0x78, 0x79, 0x7A
TC_LONGSTRING, TC_PROXYCLASSDESC, TC_ENUM = 0x7C, 0x7D, 0x7E
BASE_HANDLE = 0x7E0000
SC_WRITE_METHOD, SC_EXTERNALIZABLE = 0x01, 0x04
REW_HEADER = 'REW Measurement Data File'
MEAS_CLASS = 'roomeqwizard.MeasData'
_PRIM = {'F': ('>f4', 4), 'D': ('>f8', 8), 'I': ('>i4', 4), 'J': ('>i8', 8),
         'S': ('>i2', 2), 'B': ('>i1', 1), 'Z': ('>u1', 1), 'C': ('>u2', 2)}
_SCALAR = {'F': ('>f', 4), 'D': ('>d', 8), 'I': ('>i', 4), 'J': ('>q', 8),
           'S': ('>h', 2), 'B': ('>b', 1)}
_MAX_DEPTH = 200


class MdatError(ValueError):
    """The file is not an .mdat this reader understands -- worded for the user."""


class _ClassDesc:
    __slots__ = ('name', 'flags', 'fields', 'superdesc')

    def __init__(self, name, flags, fields, superdesc):
        self.name, self.flags, self.fields, self.superdesc = name, flags, fields, superdesc


class JObject:
    """One deserialized Java object: its class name and fields by name."""
    __slots__ = ('name', 'fields', 'annotations')

    def __init__(self, name):
        self.name = name
        self.fields = {}
        self.annotations = []

    def get(self, field, default=None):
        value = self.fields.get(field, default)
        # java.lang.Double / Integer / Boolean ... unbox to the plain value
        if isinstance(value, JObject) and value.name.startswith('java.lang.') and 'value' in value.fields:
            return value.fields['value']
        return value


class JEnum:
    __slots__ = ('name', 'constant')

    def __init__(self, name, constant):
        self.name, self.constant = name, constant


class _Block(bytes):
    pass


class _Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0
        self.handles = []
        self.depth = 0

    def _need(self, n):
        if n < 0 or self.p + n > len(self.d):
            raise MdatError('the file ends inside a record (truncated or not an .mdat)')

    def u1(self):
        self._need(1)
        v = self.d[self.p]
        self.p += 1
        return v

    def unpack(self, fmt, size):
        self._need(size)
        v = struct.unpack_from(fmt, self.d, self.p)[0]
        self.p += size
        return v

    def raw(self, n):
        self._need(n)
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def utf(self):
        return self.raw(self.unpack('>H', 2)).decode('utf-8', 'replace')

    def handle(self, obj):
        self.handles.append(obj)
        return len(self.handles) - 1

    def ref(self):
        h = self.unpack('>i', 4) - BASE_HANDLE
        if not 0 <= h < len(self.handles):
            raise MdatError('bad back-reference in the stream')
        return self.handles[h]

    def stream(self):
        if self.unpack('>H', 2) != MAGIC or self.unpack('>H', 2) != 5:
            raise MdatError('not a Java serialization stream, so not a REW .mdat')
        items = []
        while self.p < len(self.d):
            items.append(self.content())
        return items

    def content(self):
        self._need(1)
        tc = self.d[self.p]
        if tc == TC_BLOCKDATA:
            self.p += 1
            return _Block(self.raw(self.u1()))
        if tc == TC_BLOCKDATALONG:
            self.p += 1
            return _Block(self.raw(self.unpack('>i', 4)))
        if tc == TC_RESET:
            self.p += 1
            self.handles = []
            return None
        return self.obj()

    def obj(self):
        self.depth += 1
        if self.depth > _MAX_DEPTH:
            raise MdatError('object nesting too deep -- not a REW .mdat')
        try:
            return self._obj()
        finally:
            self.depth -= 1

    def _obj(self):
        tc = self.u1()
        if tc == TC_NULL:
            return None
        if tc == TC_REFERENCE:
            return self.ref()
        if tc == TC_STRING:
            s = self.utf()
            self.handle(s)
            return s
        if tc == TC_LONGSTRING:
            s = self.raw(self.unpack('>q', 8)).decode('utf-8', 'replace')
            self.handle(s)
            return s
        if tc in (TC_CLASSDESC, TC_PROXYCLASSDESC):
            self.p -= 1
            return self.classdesc()
        if tc == TC_CLASS:
            cd = self.classdesc()
            self.handle(cd)
            return cd
        if tc == TC_ARRAY:
            return self.array()
        if tc == TC_ENUM:
            cd = self.classdesc()
            h = self.handle(None)
            e = JEnum(cd.name if cd else None, self.obj())
            self.handles[h] = e
            return e
        if tc == TC_OBJECT:
            return self.newobject()
        raise MdatError('unknown record 0x%02x at byte %d -- not a REW .mdat' % (tc, self.p - 1))

    def classdesc(self):
        tc = self.u1()
        if tc == TC_NULL:
            return None
        if tc == TC_REFERENCE:
            return self.ref()
        if tc == TC_PROXYCLASSDESC:
            h = self.handle(None)
            for _ in range(self.unpack('>i', 4)):
                self.utf()
            self.annotations()
            cd = _ClassDesc('proxy', 0, [], self.classdesc())
            self.handles[h] = cd
            return cd
        if tc != TC_CLASSDESC:
            raise MdatError('expected a class description at byte %d' % (self.p - 1))
        name = self.utf()
        self.raw(8)                                   # serialVersionUID
        h = self.handle(None)
        flags = self.u1()
        fields = []
        for _ in range(self.unpack('>H', 2)):
            kind = chr(self.u1())
            fname = self.utf()
            if kind in 'L[':
                self.obj()                            # field class name
            fields.append((kind, fname))
        self.annotations()
        cd = _ClassDesc(name, flags, fields, self.classdesc())
        self.handles[h] = cd
        return cd

    def annotations(self):
        items = []
        while True:
            self._need(1)
            if self.d[self.p] == TC_ENDBLOCKDATA:
                self.p += 1
                return items
            items.append(self.content())

    def array(self):
        cd = self.classdesc()
        h = self.handle(None)
        n = self.unpack('>i', 4)
        kind = cd.name[1] if cd and len(cd.name) > 1 else 'L'
        if kind in _PRIM:
            dtype, size = _PRIM[kind]
            arr = np.frombuffer(self.raw(n * size), dtype=dtype).astype(
                np.float64 if kind in 'FD' else np.int64)
        else:
            self._need(n)                             # at least one byte per element
            arr = [self.obj() for _ in range(n)]
        self.handles[h] = arr
        return arr

    def prim(self, kind):
        if kind == 'Z':
            return bool(self.u1())
        if kind == 'C':
            return chr(self.unpack('>H', 2))
        fmt, size = _SCALAR[kind]
        return self.unpack(fmt, size)

    def newobject(self):
        cd = self.classdesc()
        if cd is None:
            raise MdatError('object without a class description')
        o = JObject(cd.name)
        self.handle(o)
        chain = []
        while cd is not None:
            chain.append(cd)
            cd = cd.superdesc
        for c in reversed(chain):
            if c.flags & SC_EXTERNALIZABLE:
                o.annotations.extend(self.annotations())
                continue
            for kind, fname in c.fields:
                o.fields[fname] = self.obj() if kind in 'L[' else self.prim(kind)
            if c.flags & SC_WRITE_METHOD:
                o.annotations.extend(self.annotations())
        return o


# ------------------------------------------------------------------ measurements
def _num(o, key):
    v = o.get(key) if isinstance(o, JObject) else None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _text(o, key):
    v = o.get(key) if isinstance(o, JObject) else None
    return v if isinstance(v, str) else None


def _arr(o, key):
    v = o.get(key) if isinstance(o, JObject) else None
    return v if isinstance(v, np.ndarray) and v.size else None


def _axis(m, n):
    """REW's own axis for an n-point array of MeasData m."""
    start = _num(m, 'startFreq')
    if start is None or start <= 0:
        raise MdatError('measurement %r has no start frequency' % _text(m, 'shortDesc'))
    if m.get('isLogSpaced'):
        step = _num(m, 'logStep')
        ppo = _num(m, 'ppo')
        if not step and ppo:
            step = 2.0 ** (1.0 / ppo)
        if not step or step <= 1.0:
            raise MdatError('measurement %r is log-spaced but states no step' % _text(m, 'shortDesc'))
        return start * step ** np.arange(n)
    step = _num(m, 'freqStep')
    if not step or step <= 0:
        raise MdatError('measurement %r states neither a log step nor a frequency step'
                        % _text(m, 'shortDesc'))
    return start + step * np.arange(n)


def smoothing_text(octave_frac):
    """REW's octaveFrac as text: 0 is none, N is 1/N octave."""
    if not octave_frac:
        return 'None'
    if octave_frac > 0:
        return '1/%g octave' % octave_frac
    return 'REW smoothing code %g' % octave_frac


def _version(m):
    major, minor = m.get('rewVersion'), m.get('rewSubVersion')
    if not isinstance(major, int) or not isinstance(minor, int):
        return None
    tail = _text(m, 'versionSt') or ''
    return '%d.%02d%s' % (major, minor, tail if tail.startswith('.') else (' ' + tail.strip() if tail.strip() else ''))


def _date(ms):
    if not isinstance(ms, (int, float)) or ms <= 0:
        return None
    return datetime.datetime.fromtimestamp(ms / 1000.0).isoformat(timespec='seconds')


def _harmonics(dist):
    harm = dist.get('harmData') if isinstance(dist, JObject) else None
    if not isinstance(harm, list):
        return None
    out = {}
    for i, a in enumerate(harm):
        if isinstance(a, np.ndarray) and a.size:
            out[i + 2] = a
    return out or None


def _measurement(m, index):
    name = _text(m, 'shortDesc') or 'Measurement %d' % index
    spl = _arr(m, 'splValues')
    if spl is None:
        raise MdatError('measurement %r carries no SPL data' % name)
    n = len(spl)
    length = m.get('dataLength')
    if isinstance(length, int) and length != n:
        raise MdatError('measurement %r states %d points but holds %d -- this REW version '
                        'stores data differently; export it as text instead' % (name, length, n))
    freqs = _axis(m, n)
    end = _num(m, 'endFreq')
    if end and abs(freqs[-1] / end - 1.0) > 0.005:
        raise MdatError('measurement %r: the stated axis ends at %.0f Hz but REW says %.0f Hz -- '
                        'not trusting it; export it as text instead' % (name, freqs[-1], end))
    raw = _arr(m, 'rawValues')
    phase = _arr(m, 'phaseValues')
    cal = m.get('meterCal')
    mic = None
    if isinstance(cal, JObject):
        serial = cal.get('serialNum')
        mic = {'serial': str(serial) if isinstance(serial, int) and serial > 0 else None,
               'cal_file': _text(cal, 'sourceName') or None,
               'sensitivity_db': _num(cal, 'sensitivitydB'),
               'cal_freqs': _arr(cal, 'freqArray'), 'cal_gain_db': _arr(cal, 'gainArray')}
    ir, dist = m.get('irData'), m.get('distortionData')
    sweep = None
    if isinstance(ir, JObject):
        samples = ir.get('ir')
        sweep = {'timing_reference_used': ir.get('usedTimingRef'),
                 'delay_ms': None if _num(ir, 'measurementDelay') is None
                 else 1e3 * _num(ir, 'measurementDelay'),
                 'snr_db': _num(ir, 'signalToNoisedB'),
                 'signal_to_distortion_db': _num(ir, 'signalToDistdB'),
                 'ir': None}
        if isinstance(samples, JObject) and _arr(samples, 'data') is not None and _num(samples, 'T'):
            sweep['ir'] = {'samples': _arr(samples, 'data'), 'sample_rate_hz': 1.0 / _num(samples, 'T'),
                           'start_time_s': _num(samples, 'startTime') or 0.0}
    noise_floor = None
    if isinstance(dist, JObject) and _arr(dist, 'noiseFloorSPL') is not None:
        nf = _arr(dist, 'noiseFloorSPL')
        df = _arr(dist, 'freqs')
        if df is not None and len(df) == len(nf):
            noise_floor = (df, nf)
    rta = bool(m.get('isFromRTA'))
    return {
        'index': index, 'name': name, 'kind': 'rta' if rta else ('sweep' if sweep else 'other'),
        'timestamp_ms': m.get('sourceFileDate'), 'date': _date(m.get('sourceFileDate')),
        'freqs': freqs, 'spl': spl, 'raw': raw if raw is not None and len(raw) == n else None,
        'ppo': (int(round(1.0 / np.log2(freqs[1] / freqs[0]))) if m.get('isLogSpaced') and n > 1
                else None),
        'phase': phase if phase is not None and len(phase) == n else None,
        'smoothing': smoothing_text(_num(m, 'octaveFrac')),
        'rta_octave_frac': _num(m, 'rtaOctaveFrac'),
        'format': (_text(m, 'sourceFileFormat') or '').strip(),
        'notes': (_text(m, 'measNotes') or '').strip(),
        'source': _text(m, 'sourceFileName'), 'output': _text(m, 'outputName'),
        'sample_rate_hz': _num(m, 'sampleRate'), 'rew_version': _version(m),
        'valid_range_hz': (_num(m, 'validStartFreq'), _num(m, 'validEndFreq')),
        'level_adjusted': m.get('rtaLevelAdjustApplied'),
        'mic': mic, 'sweep': sweep, 'noise_floor': noise_floor,
        'harmonics': _harmonics(dist),
    }


_CACHE = {}


def load(path):
    """Every measurement in an .mdat, in REW's order (index is 1-based)."""
    path = os.path.abspath(path)
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    if key in _CACHE:
        return _CACHE[key]
    with open(path, 'rb') as fh:
        data = fh.read()
    try:
        items = _Reader(data).stream()
    except (struct.error, IndexError, UnicodeError) as exc:
        raise MdatError('%s is not a readable REW .mdat (%s)' % (path, exc)) from exc
    if not items or not isinstance(items[0], str) or not items[0].startswith(REW_HEADER):
        raise MdatError('%s does not start with "%s" -- not a REW measurement file' % (path, REW_HEADER))
    measurements = [_measurement(o, i + 1) for i, o in enumerate(
        x for x in items if isinstance(x, JObject) and x.name == MEAS_CLASS)]
    if not measurements:
        raise MdatError('%s holds no measurements' % path)
    file_notes = next((x[len('Notes:'):] for x in items[1:4]
                       if isinstance(x, str) and x.startswith('Notes:')), None)
    for meas in measurements:
        meas['file'] = path
        meas['file_notes'] = file_notes
    _CACHE.clear()
    _CACHE[key] = measurements
    return measurements


def is_spec(text):
    """True when `text` names an .mdat (whole file or file::selector)."""
    text = str(text)
    return '::' in text or text.lower().endswith('.mdat')


def split_spec(text):
    path, sep, selector = str(text).partition('::')
    return path, (selector if sep else None)


def select(spec):
    """The one measurement `spec` names: file.mdat::Name, file.mdat::#N, or a
    file.mdat holding exactly one measurement."""
    path, selector = split_spec(spec)
    items = load(path)
    if selector is None:
        if len(items) == 1:
            return items[0]
        raise MdatError('%s holds %d measurements -- name one as "%s::<name>" or "%s::#<n>" '
                        '(%s)' % (path, len(items), path, path, '; '.join(
                            '#%d %s' % (m['index'], m['name']) for m in items)))
    if re.fullmatch(r'#\d+', selector):
        n = int(selector[1:])
        for m in items:
            if m['index'] == n:
                return m
        raise MdatError('%s has no measurement #%d (it has %d)' % (path, n, len(items)))
    hits = [m for m in items if m['name'] == selector] or \
           [m for m in items if m['name'].strip().lower() == selector.strip().lower()]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise MdatError('%s has %d measurements named %r -- use "::#<n>" (%s)' % (
            path, len(hits), selector, ', '.join('#%d' % m['index'] for m in hits)))
    raise MdatError('%s has no measurement named %r (have: %s)' % (
        path, selector, '; '.join(m['name'] for m in items)))


def values(meas, smoothed=False):
    """(freqs, spl_db, phase_deg or None) inside REW's valid range: unsmoothed
    rawValues unless smoothed=True (or the file has none). The skill smooths
    for itself, and the boost gate needs unsmoothed data."""
    f = meas['freqs']
    spl = meas['spl'] if smoothed or meas['raw'] is None else meas['raw']
    lo, hi = meas['valid_range_hz']
    keep = np.isfinite(spl) & (f > 0)
    if lo:
        keep &= f >= lo * (1 - 1e-6)
    if hi:
        keep &= f <= hi * (1 + 1e-6)
    phase = meas['phase']
    if phase is not None:
        keep &= np.isfinite(phase)
    if np.count_nonzero(keep) < 8:
        raise MdatError('measurement %r has fewer than 8 valid points' % meas['name'])
    return f[keep], spl[keep], (phase[keep] if phase is not None else None)


def header_lines(meas, smoothed=False):
    """REW-style text-export header lines for one measurement, so that
    measure.read_export_header reads an .mdat exactly as it reads a text export."""
    lines = ['Measurement data from %s via mdat.py (REW %s)' % (
        os.path.basename(meas.get('file') or '.mdat'), meas['rew_version'] or 'version unknown')]
    if meas['source']:
        lines.append('Source: %s' % meas['source'])
    if meas['format']:
        lines.append('Format: %s' % ' '.join(meas['format'].split()))
    if meas['date']:
        lines.append('Dated: %s' % meas['date'])
    if meas['notes']:
        lines.append('Note: %s' % ' '.join(meas['notes'].split()))
    lines.append('Measurement: %s' % meas['name'])
    lines.append('Smoothing: %s' % (meas['smoothing'] if smoothed or meas['raw'] is None else 'None'))
    if meas['ppo']:
        lines.append('Frequency Step: %d ppo' % meas['ppo'])
    lines.append('Start Frequency: %.7g Hz' % values(meas, smoothed)[0][0])
    if meas['output']:
        lines.append('Output: %s' % meas['output'])
    if meas['sample_rate_hz']:
        lines.append('Sample rate: %g Hz' % meas['sample_rate_hz'])
    mic = meas['mic'] or {}
    if mic.get('serial') or mic.get('cal_file'):
        lines.append('Mic: serial %s, cal %s' % (mic.get('serial') or 'unknown',
                                                  mic.get('cal_file') or 'unknown'))
    if meas['sweep'] is not None:
        used = meas['sweep']['timing_reference_used']
        lines.append('timing reference: %s' % ('used' if used else 'NONE -- no shared time base'
                                               if used is False else 'unknown'))
    return lines


def write_text(meas, out, smoothed=False):
    f, spl, phase = values(meas, smoothed)
    with open(out, 'x', encoding='utf-8') as fh:
        for line in header_lines(meas, smoothed):
            fh.write('* %s\n' % line)
        fh.write('* Freq(Hz) SPL(dB)%s\n' % (' Phase(degrees)' if phase is not None else ''))
        for i in range(len(f)):
            if phase is None:
                fh.write('%.6f %.4f\n' % (f[i], spl[i]))
            else:
                fh.write('%.6f %.4f %.4f\n' % (f[i], spl[i], phase[i]))
    return len(f)


def _safe_name(name):
    return re.sub(r'[^\w.+-]+', '_', name).strip('_') or 'measurement'


def summary(meas):
    """JSON-safe one-measurement summary (no arrays)."""
    import measure
    f, _s, phase = values(meas)
    mic = meas['mic'] or {}
    return {'index': meas['index'], 'name': meas['name'], 'kind': meas['kind'], 'date': meas['date'],
            'points': len(f), 'range_hz': [round(float(f[0]), 2), round(float(f[-1]), 1)],
            'phase': phase is not None, 'smoothing_as_saved': meas['smoothing'],
            'format': measure.parse_rew_format(meas['format']),
            'levels': measure.parse_level_notes(meas['notes']),
            'source': measure.parse_source(meas['source']), 'output': meas['output'],
            'mic_serial': mic.get('serial'), 'mic_cal_file': mic.get('cal_file'),
            'sample_rate_hz': meas['sample_rate_hz'], 'rew_version': meas['rew_version'],
            'sweep': None if meas['sweep'] is None else {
                k: v for k, v in meas['sweep'].items() if k != 'ir'}}


def _main(argv=None):
    ap = argparse.ArgumentParser(description='Read REW .mdat files (read-only).')
    sub = ap.add_subparsers(dest='cmd', required=True)
    ls = sub.add_parser('list', help='every measurement: name, kind, time, settings, levels')
    ls.add_argument('file')
    ls.add_argument('--json', action='store_true')
    ex = sub.add_parser('export', help='write one measurement as a REW-style text export')
    ex.add_argument('spec', help='"file.mdat::name" or "file.mdat::#n"')
    ex.add_argument('--out', required=True)
    ex.add_argument('--smoothed', action='store_true', help='the displayed (smoothed) values')
    ea = sub.add_parser('export-all', help='one text export per measurement')
    ea.add_argument('file')
    ea.add_argument('--out-dir', required=True)
    ea.add_argument('--smoothed', action='store_true')
    a = ap.parse_args(argv)
    try:
        if a.cmd == 'list':
            rows = [summary(m) for m in load(a.file)]
            if a.json:
                print(json.dumps(rows, indent=2))
            else:
                for r in rows:
                    lv, fm = r['levels'], r['format']
                    print('#%-3d %-19s %-6s %-30s %s  mic %s  %s' % (
                        r['index'], r['date'] or '-', r['kind'], r['name'][:30],
                        fm.get('summary') or '-', r['mic_serial'] or '-',
                        ('%.1f dBA' % lv['dba']) if lv.get('dba') is not None else ''))
            return 0
        if a.cmd == 'export':
            if os.path.splitext(a.out)[1].lower() in ('.mdat', '.afpx', '.pct6', '.jssh', '.wav'):
                raise MdatError('--out must be a new text file, not %s' % a.out)
            n = write_text(select(a.spec), a.out, a.smoothed)
            print('wrote %s (%d points)' % (a.out, n))
            return 0
        os.makedirs(a.out_dir, exist_ok=True)
        for m in load(a.file):
            out = os.path.join(a.out_dir, '%02d_%s.txt' % (m['index'], _safe_name(m['name'])))
            n = write_text(m, out, a.smoothed)
            print('wrote %s (%d points)' % (out, n))
        return 0
    except (MdatError, OSError) as exc:
        print('error: %s' % exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(_main())
