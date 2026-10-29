# rew_api.py -- READ-ONLY bridge to a running Room EQ Wizard (REW 5.40+) over
# its local HTTP API, so measurements come straight from REW instead of being
# exported one file at a time.
#
# Why this exists: manual exports are where data quietly goes wrong. A WAV
# impulse-response export with a peak-referenced window puts every driver's
# peak at the same sample and silently destroys the relative timing the
# junction and imaging tools depend on; a text export can carry the wrong
# smoothing; and every extra click is a reason to measure fewer positions.
# The API returns each measurement's frequency response with phase and its
# impulse response with the start time on the shared timing-reference axis.
#
# Strictly read-only: only GET requests. It never triggers a sweep (which
# would play test signals through the car, and needs REW Pro), never edits or
# deletes a measurement, and never switches on REW's "blocking" mode (that
# setting persists in REW across restarts).
#
# Wire format (documented and verified live against REW 5.40 by the MIT
# projects alex-vyverman/OptiMIMO and brandon-fryslie/room-eq-wizard-mcp):
#   GET /measurements                  -> object keyed by 1-based index
#   GET /measurements/{id}/frequency-response?ppo=96&smoothing=1/48
#                                      -> startFreq + ppo|freqStep, base64 arrays
#   GET /measurements/{id}/impulse-response?normalised=false
#                                      -> startTime, sampleRate, base64 samples
#   arrays are base64 of BIG-endian float32; REW writes bare NaN/Infinity.
# REW's frequency-response endpoint has no unsmoothed log-spaced form ('None'
# silently becomes 1/48), so 1/48 is requested explicitly and recorded.
#
# Enable the API in REW: Preferences -> API (or start REW with -api); default
# address http://127.0.0.1:4735.
#
# RTA and metadata reads (GET only, documented in REW's API help; the exact
# JSON field names of the RTA structures are not documented, so they are
# looked up defensively and the raw objects are kept in the output):
#   GET /rta/configuration             mode, FFT, window, overlap, averaging
#   GET /rta/status, /rta/levels       running state; nanosecond timestamp and the
#                                      running sample count (exact capture length)
#   GET /rta/captured-data, /rta/captured-peak-data
#                                      the RTA average and its peak trace
#   GET /measurements/{id}             notes, cal paths, offsets
#   GET /measurements/{id}/distortion  harmonic distortion table
#   GET /eq/house-curve                path of REW's house curve (usable as --target)
# `rta-frames` polls captured-data with RTA averaging set to None, so each new
# sample count is one block: per-block data from GETs, with no subscription
# (a subscription would register a callback in REW, which this bridge never does).
#
# CLI:
#   python rew_api.py list
#   python rew_api.py export "FL tweeter" --out fl_tw.txt
#   python rew_api.py export "FL tweeter" --out fl_tw_direct.txt --direct-sound
#   python rew_api.py rta-config | rta-status | house-curve | info "FL tweeter"
#   python rew_api.py rta-capture --out avg.txt [--peak-out peak.txt]
#   python rew_api.py rta-frames --seconds 30 --out frames.json
#   python rew_api.py distortion "FL tweeter" --out fl_tw_dist.json
import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

DEFAULT_URL = 'http://127.0.0.1:4735'


class RewError(Exception):
    """A REW API failure, worded for the user."""


def decode_floats(encoded):
    raw = base64.b64decode(encoded)
    if len(raw) % 4:
        raise RewError('REW float array is %d bytes, not a multiple of 4 -- corrupt data'
                       % len(raw))
    return np.frombuffer(raw, dtype='>f4').astype(np.float64)


def _parse_rew_json(text):
    # REW writes Java's NaN/Infinity as bare tokens; strings are skipped whole.
    cleaned = re.sub(r'"(?:[^"\\]|\\.)*"|(-?Infinity|NaN)',
                     lambda m: 'null' if m.group(1) else m.group(0), text)
    return json.loads(cleaned)


class RewClient:
    def __init__(self, base_url=DEFAULT_URL, timeout=15.0):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    def _get(self, path, query=None):
        url = self.base_url + path
        if query:
            url += '?' + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        request = urllib.request.Request(url, headers={'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                text = response.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            body = exc.read().decode('utf-8', 'replace')
            raise RewError('REW API GET %s -> HTTP %d %s' % (path, exc.code, body[:200])) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise RewError('cannot reach the REW API at %s (%s). Open REW and enable the '
                           'API: Preferences -> API, or start REW with -api.'
                           % (self.base_url, exc)) from exc
        try:
            return _parse_rew_json(text)
        except ValueError as exc:
            raise RewError('REW returned something that is not JSON for %s' % path) from exc

    def list_measurements(self):
        data = self._get('/measurements')
        if not isinstance(data, dict):
            raise RewError('unexpected /measurements response (expected an object)')
        items = []
        for index, summary in data.items():
            if not isinstance(summary, dict) or not summary.get('uuid'):
                continue
            items.append({'index': int(index), 'uuid': str(summary['uuid']),
                          'title': str(summary.get('title', 'Measurement %s' % index)),
                          'sample_rate': summary.get('sampleRate'),
                          'timing_reference': summary.get('timingReference'),
                          'signal_to_noise_db': summary.get('signalToNoisedB'),
                          'start_freq': summary.get('startFreq'),
                          'end_freq': summary.get('endFreq')})
        return sorted(items, key=lambda m: m['index'])

    def resolve(self, ref):
        """A measurement by exact title, 1-based index, or uuid."""
        items = self.list_measurements()
        ref = str(ref)
        for m in items:
            if ref in (m['uuid'], m['title']) or (ref.isdigit() and int(ref) == m['index']):
                return m
        raise RewError('no measurement %r in REW (have: %s)'
                       % (ref, ', '.join(m['title'] for m in items) or 'none'))

    def frequency_response(self, ref, ppo=96, smoothing='1/48'):
        m = self.resolve(ref)
        d = self._get('/measurements/%s/frequency-response' % urllib.parse.quote(m['uuid'], safe=''),
                      {'ppo': ppo, 'smoothing': smoothing})
        if not isinstance(d, dict) or 'magnitude' not in d:
            raise RewError('%r has no frequency response (%s)' % (m['title'], d))
        spl = decode_floats(d['magnitude'])
        n = len(spl)
        if d.get('ppo'):
            f = float(d['startFreq']) * 2 ** (np.arange(n) / float(d['ppo']))
        elif d.get('freqStep'):
            f = float(d['startFreq']) + np.arange(n) * float(d['freqStep'])
        else:
            raise RewError('frequency response for %r has neither ppo nor freqStep' % m['title'])
        phase = decode_floats(d['phase']) if d.get('phase') else None
        return f, spl, phase, {'title': m['title'], 'uuid': m['uuid'],
                               'smoothing': d.get('smoothing', smoothing), 'unit': d.get('unit'),
                               'timing_reference': m.get('timing_reference'),
                               'signal_to_noise_db': m.get('signal_to_noise_db')}

    def impulse_response(self, ref):
        m = self.resolve(ref)
        d = self._get('/measurements/%s/impulse-response' % urllib.parse.quote(m['uuid'], safe=''),
                      {'normalised': 'false'})
        if not isinstance(d, dict) or not isinstance(d.get('data'), str):
            raise RewError('%r has no impulse response (REW: %s)'
                           % (m['title'], (d or {}).get('message') if isinstance(d, dict) else d))
        samples = decode_floats(d['data'])
        fs = d.get('sampleRate') or (1.0 / d['sampleInterval'] if d.get('sampleInterval') else None)
        if not fs:
            raise RewError('REW did not report a sample rate for %r' % m['title'])
        return samples, float(fs), float(d.get('startTime') or 0.0), {
            'title': m['title'], 'uuid': m['uuid'],
            'timing_reference': d.get('timingReference', m.get('timing_reference')),
            'signal_to_noise_db': m.get('signal_to_noise_db')}


def _pick(d, *names):
    """First present key among `names`, case-insensitively (REW's RTA field
    names are not documented)."""
    if not isinstance(d, dict):
        return None
    low = {str(k).lower(): v for k, v in d.items()}
    for n in names:
        if n.lower() in low and low[n.lower()] is not None:
            return low[n.lower()]
    return None


def response_arrays(d, what):
    """(freqs, magnitude) of a REW FrequencyResponse object."""
    if not isinstance(d, dict) or not isinstance(_pick(d, 'magnitude'), str):
        raise RewError('%s returned no frequency response -- is the RTA running and has it '
                       'captured data? (%s)' % (what, str(d)[:160]))
    mag = decode_floats(_pick(d, 'magnitude'))
    start = _pick(d, 'startFreq')
    ppo, step = _pick(d, 'ppo'), _pick(d, 'freqStep')
    if start is None or not (ppo or step):
        raise RewError('%s has no startFreq with ppo or freqStep' % what)
    n = np.arange(len(mag))
    f = float(start) * 2 ** (n / float(ppo)) if ppo else float(start) + n * float(step)
    return f, mag


def find_setting(obj, fragment):
    """(key path, value) pairs whose key contains `fragment`, anywhere in obj."""
    out = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                p = '%s.%s' % (path, k) if path else str(k)
                if fragment.lower() in str(k).lower() and not isinstance(v, (dict, list)):
                    out.append((p, v))
                walk(v, p)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, '%s[%d]' % (path, i))
    walk(obj, '')
    return out


class RtaReader:
    """GET-only reads of REW's RTA and measurement metadata."""

    def __init__(self, client):
        self.c = client

    def configuration(self):
        return self.c._get('/rta/configuration')

    def status(self):
        return self.c._get('/rta/status')

    def levels(self, unit=None):
        return self.c._get('/rta/levels', {'unit': unit})

    def captured(self, peak=False, unit=None):
        path = '/rta/captured-peak-data' if peak else '/rta/captured-data'
        d = self.c._get(path, {'unit': unit})
        f, mag = response_arrays(d, path)
        return f, mag, {'timestamp_ns': _pick(d, 'timestamp', 'timeStamp', 'timestampNs'),
                        'sample_count': _pick(d, 'sampleCount', 'samples', 'count'),
                        'smoothing': _pick(d, 'smoothing'), 'unit': _pick(d, 'unit') or unit or 'SPL'}

    def measurement(self, ref):
        m = self.c.resolve(ref)
        return self.c._get('/measurements/%s' % urllib.parse.quote(m['uuid'], safe=''))

    def distortion(self, ref, ppo=None, unit=None):
        m = self.c.resolve(ref)
        return self.c._get('/measurements/%s/distortion' % urllib.parse.quote(m['uuid'], safe=''),
                           {'ppo': ppo, 'unit': unit})

    def house_curve(self):
        return self.c._get('/eq/house-curve')


def poll_frames(reader, seconds, interval=0.1, sleep=None, clock=None):
    """Successive captured-data snapshots with distinct sample counts. With RTA
    averaging set to None each one is a single block."""
    import time
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    frames, last, f0 = [], None, None
    end = clock() + seconds
    while clock() < end:
        f, mag, meta = reader.captured()
        key = meta['sample_count'] if meta['sample_count'] is not None else meta['timestamp_ns']
        if key is None or key != last:
            if f0 is None:
                f0 = f
            if len(f) == len(f0):
                frames.append({'sample_count': meta['sample_count'], 'timestamp_ns': meta['timestamp_ns'],
                               'db': [round(float(x), 3) for x in mag]})
            last = key
        sleep(interval)
    return f0, frames


def _refuse_existing(path):
    if os.path.exists(path):
        raise RewError('%s already exists -- choose a new file name' % path)


def _write_text(path, f, spl, phase, header_lines):
    with open(path, 'w', encoding='utf-8') as fh:
        for line in header_lines:
            fh.write('* %s\n' % line)
        fh.write('* Freq(Hz) SPL(dB) Phase(degrees)\n')
        for i in range(len(f)):
            if phase is None:
                fh.write('%.4f %.4f\n' % (f[i], spl[i]))
            else:
                fh.write('%.4f %.4f %.4f\n' % (f[i], spl[i], phase[i]))


def _main(argv=None):
    ap = argparse.ArgumentParser(description='Read-only REW HTTP API bridge.')
    ap.add_argument('--url', default=DEFAULT_URL)
    sub = ap.add_subparsers(dest='cmd', required=True)
    ls = sub.add_parser('list', help='measurements loaded in REW')
    ls.add_argument('--json', action='store_true')
    ex = sub.add_parser('export', help='write one measurement as a REW-style text export')
    ex.add_argument('measurement', help='exact title, 1-based index, or uuid')
    ex.add_argument('--out', required=True)
    ex.add_argument('--smoothing', default='1/48')
    ex.add_argument('--direct-sound', action='store_true',
                    help='frequency-dependent window from the IR (decay.fdw_response)')
    ex.add_argument('--cycles', type=float, default=8.0)
    for name, why in (('rta-config', 'the RTA setup (FFT, window, overlap, averaging)'),
                      ('rta-status', 'whether the RTA is enabled and running'),
                      ('house-curve', 'the house curve file REW is using')):
        sub.add_parser(name, help=why)
    inf = sub.add_parser('info', help="one measurement's notes, cal paths and offsets")
    inf.add_argument('measurement')
    rc = sub.add_parser('rta-capture', help='the RTA average (and peak) as text exports')
    rc.add_argument('--out', required=True)
    rc.add_argument('--peak-out')
    rf = sub.add_parser('rta-frames', help='per-block RTA data by polling (averaging None)')
    rf.add_argument('--seconds', type=float, default=30.0)
    rf.add_argument('--interval', type=float, default=0.1)
    rf.add_argument('--sample-rate', type=float, help='the RTA input rate, for capture length')
    rf.add_argument('--out', required=True)
    di = sub.add_parser('distortion', help="a measurement's distortion table as JSON")
    di.add_argument('measurement')
    di.add_argument('--out', required=True)
    di.add_argument('--ppo', type=int)
    a = ap.parse_args(argv)
    client = RewClient(a.url)
    rta = RtaReader(client)
    try:
        if a.cmd in ('rta-config', 'rta-status', 'house-curve', 'info'):
            data = {'rta-config': rta.configuration, 'rta-status': rta.status,
                    'house-curve': rta.house_curve}.get(a.cmd)
            print(json.dumps(data() if data else rta.measurement(a.measurement), indent=2))
            return 0
        if a.cmd == 'distortion':
            _refuse_existing(a.out)
            table = rta.distortion(a.measurement, a.ppo)
            with open(a.out, 'x', encoding='utf-8') as fh:
                json.dump(table, fh, indent=2)
            print('wrote %s' % a.out)
            return 0
        if a.cmd == 'rta-capture':
            config = rta.configuration()
            for out, peak in ((a.out, False), (a.peak_out, True)):
                if not out:
                    continue
                _refuse_existing(out)
                f, mag, meta = rta.captured(peak)
                header = ['REW API RTA %s (GET /rta/captured-%sdata)' % (
                              'peak' if peak else 'average', 'peak-' if peak else ''),
                          'Smoothing: %s' % (meta['smoothing'] or 'None'),
                          'unit %s, sample count %s, timestamp %s ns' % (
                              meta['unit'], meta['sample_count'], meta['timestamp_ns'])]
                for key, value in (find_setting(config, 'averag') + find_setting(config, 'overlap')
                                   + find_setting(config, 'fft') + find_setting(config, 'window')):
                    header.append('rta %s: %s' % (key, value))
                _write_text(out, f, mag, None, header)
                print('wrote %s (%d points)' % (out, len(f)))
            return 0
        if a.cmd == 'rta-frames':
            _refuse_existing(a.out)
            averaging = find_setting(rta.configuration(), 'averag')
            f, frames = poll_frames(rta, a.seconds, a.interval)
            if f is None:
                raise RewError('the RTA returned no data: start it in REW first')
            doc = {'format': 'rew-rta-frames-v1', 'freqs': [float(x) for x in f], 'frames': frames,
                   'averaging': averaging, 'sample_rate_hz': a.sample_rate, 'unit': 'SPL'}
            with open(a.out, 'x', encoding='utf-8') as fh:
                json.dump(doc, fh)
            print('wrote %s (%d frames)' % (a.out, len(frames)))
            if not any('none' in str(v).lower() for _k, v in averaging):
                print('note: RTA averaging does not read as None (%s): these frames are running '
                      'averages, not single blocks' % (averaging or 'not reported'))
            return 0
        if a.cmd == 'list':
            items = client.list_measurements()
            if a.json:
                print(json.dumps(items, indent=2))
            else:
                for m in items:
                    print('%3d  %-40s  ref=%-10s SNR=%s' % (
                        m['index'], m['title'], m['timing_reference'] or '-',
                        '-' if m['signal_to_noise_db'] is None else '%.1f dB' % m['signal_to_noise_db']))
                if any(not m['timing_reference'] for m in items):
                    print('\nnote: measurements without a timing reference have no shared time '
                          'base -- fine for tone, NOT for delays, junctions or imaging.')
            return 0
        if a.direct_sound:
            import decay
            samples, fs, start, meta = client.impulse_response(a.measurement)
            f = 20.0 * 2 ** (np.arange(int(round(np.log2(20000.0 / 20.0) * 96)) + 1) / 96.0)
            f = f[f < fs / 2]
            spl, phase = decay.fdw_response(samples, fs, f, cycles=a.cycles, t0_s=start)
            header = ['REW API direct-sound export: %s (%s)' % (meta['title'], meta['uuid']),
                      '%g-cycle frequency-dependent window from the arrival; phase on the '
                      'timing-reference axis (start %.6f s)' % (a.cycles, start),
                      'timing reference: %s' % (meta['timing_reference'] or 'NONE -- no shared time base')]
        else:
            f, spl, phase, meta = client.frequency_response(a.measurement, smoothing=a.smoothing)
            header = ['REW API export: %s (%s)' % (meta['title'], meta['uuid']),
                      'smoothing %s, unit %s' % (meta['smoothing'], meta['unit']),
                      'timing reference: %s' % (meta['timing_reference'] or 'NONE -- no shared time base')]
        if meta.get('signal_to_noise_db') is not None:
            header.append('signal to noise: %.1f dB' % meta['signal_to_noise_db'])
        _write_text(a.out, f, spl, phase, header)
        print('wrote %s (%d points)' % (a.out, len(f)))
        return 0
    except RewError as exc:
        print('ERROR: %s' % exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(_main())
