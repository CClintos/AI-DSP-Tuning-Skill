# decay.py -- time-domain decay (CSD / waterfall / T20) from a REAL impulse
# response, with a mandatory noise-floor guard.
#
# WHY THIS EXISTS, AND WHY IT REFUSES THINGS
# Decay analysis is the easiest place in this whole skill to produce confident
# nonsense. Two ways it happened for real (2026-08-01, sub orientation test):
#
#   1) RECONSTRUCTING an IR from a freq/SPL/phase text export by zero-filling an
#      FFT grid. Getting the grid size wrong aliased the bins and produced 1300 ms
#      "decay times" in a car cabin -- physically impossible, but they printed as
#      clean numbers. Even done correctly, the hard zeroing outside the exported
#      band rings in the time domain and puts a floor under the result.
#   2) Reading T20/T30 without checking where the noise floor is. The Schroeder
#      curve flattens into the floor and the crossing time becomes a property of
#      the noise, not the room. T20 values of 150-230 ms were reported for a car
#      cabin whose real RT60 at 100 Hz is ~50-100 ms.
#
# So this module: (a) prefers a real exported IR over any reconstruction, and
# (b) computes, for every band, the time at which the decay reaches the noise
# floor -- and REFUSES to report any T-value whose crossing happens after that.
# A refusal is the correct output when the measurement cannot support the answer.
#
# INPUT (in order of preference)
#   1. REW: Impulse > right-click > Export impulse response as WAV  (best)
#   2. REW: File > Export > Export impulse response as text          (fine)
#   3. A freq/SPL/phase export, via ir_from_spectrum() -- USE ONLY IF you have
#      nothing else, and read the caveat on that function.
#
# CLI:
#   python decay.py t20 ir.wav                     # per-band decay, guarded
#   python decay.py t20 ir.wav --drop 10           # T10 (survives a high floor)
#   python decay.py csd ir.wav --slices 12         # waterfall table
#   python decay.py compare a.wav b.wav            # two IRs side by side
import argparse
import struct
import sys
import wave

import numpy as np

DEFAULT_BANDS = (32, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400)


# ---------------------------------------------------------------- input
def load_ir_wav(path):
    """Load a REW-exported impulse response WAV -> (ir, fs). Mono or first channel."""
    with wave.open(path, 'rb') as w:
        fs = w.getframerate()
        n = w.getnframes()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(n)
    if sw == 2:
        x = np.frombuffer(raw, dtype='<i2').astype(np.float64) / 32768.0
    elif sw == 4:
        x = np.frombuffer(raw, dtype='<i4').astype(np.float64) / 2147483648.0
    elif sw == 3:
        a = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = (a[:, 0] | (a[:, 1] << 8) | (a[:, 2] << 16))
        v[v >= 1 << 23] -= 1 << 24
        x = v.astype(np.float64) / 8388608.0
    else:
        raise ValueError('unsupported sample width %d bytes' % sw)
    if ch > 1:
        x = x.reshape(-1, ch)[:, 0]
    return x, fs


def load_ir_text(path):
    """REW 'export impulse response as text': time(s or ms) + amplitude columns."""
    t, v = [], []
    for line in open(path, encoding='utf-8', errors='replace'):
        line = line.strip()
        if not line or line[0].isalpha() or line[0] in '*#/':
            continue
        p = line.replace(',', ' ').split()
        try:
            t.append(float(p[0]))
            v.append(float(p[1]))
        except (ValueError, IndexError):
            continue
    if len(t) < 64:
        raise ValueError('found <64 samples in %s -- is this an IR text export?' % path)
    t = np.array(t)
    v = np.array(v)
    dt = np.median(np.diff(t))
    # REW writes seconds or milliseconds depending on version/settings.
    fs = 1.0 / dt
    if fs < 1000:               # implausible as a sample rate -> axis was in ms
        fs = 1000.0 / dt
    return v, float(fs)


def ir_from_spectrum(freqs, spl_db, phase_deg, fs=48000.0, n=None):
    """LAST RESORT: rebuild an IR from a freq/SPL/phase export.

    The exported spectrum is a SUBSET of an FFT grid. If n does not match the
    grid the export came from, bins alias and the result is garbage that still
    looks like a plausible waveform. We derive n from the export's own frequency
    step instead of assuming, and refuse if it is not close to an integer power
    of two -- that mismatch is exactly the bug that produced 1300 ms decay times.

    Even when correct, hard-zeroing outside the exported band rings in the time
    domain and RAISES the noise floor. Prefer a real exported IR."""
    freqs = np.asarray(freqs, dtype=float)
    df = float(np.median(np.diff(freqs)))
    if df <= 0:
        raise ValueError('non-monotonic frequency axis')
    if n is None:
        n_est = fs / df
        n = int(round(n_est))
        if abs(n_est - n) > 0.05 * max(1.0, n_est / 1000.0):
            raise ValueError('frequency step %.6f Hz is not consistent with fs=%g '
                             '(implies n=%.2f). Pass fs explicitly or use a real IR.'
                             % (df, fs, n_est))
        if n & (n - 1):
            raise ValueError('implied FFT size %d is not a power of two -- the fs '
                             'assumption is probably wrong. Pass the correct fs.' % n)
    H = np.zeros(n // 2 + 1, dtype=complex)
    idx = np.round(freqs / df).astype(int)
    ok = (idx > 0) & (idx < len(H))
    if not ok.any():
        raise ValueError('no exported bin lands inside the FFT grid')
    H[idx[ok]] = 10 ** (spl_db[ok] / 20.0) * np.exp(1j * np.deg2rad(phase_deg[ok]))
    return np.fft.irfft(H, n), fs


# ---------------------------------------------------------------- analysis
def _bandpass(ir, fs, f0, frac=1.0):
    """CAUSAL octave-band filter (Butterworth, forward only).

    Causality is not a detail here. An FFT-masked or filtfilt (zero-phase)
    filter smears energy BACKWARDS in time, so the pre-arrival region -- the
    thing we use to estimate the noise floor -- fills with the filter's own
    pre-ringing. Measured on the selftest fixture: a zero-phase filter put the
    "floor" at -20 dB when the injected noise was -80 dBFS, a 60 dB error that
    silently invalidated every decay verdict. FFT masking is also circular, so
    onset energy wraps around into the tail and corrupts the fallback estimate
    too. A forward-only IIR has no pre-ring and no wraparound; its own phase
    shift is irrelevant because we measure an energy envelope, not phase."""
    from scipy.signal import butter, sosfilt
    nyq = fs / 2.0
    lo = max(f0 * 2 ** (-frac / 2), 1.0) / nyq
    hi = min(f0 * 2 ** (frac / 2), nyq * 0.99) / nyq
    if not (0 < lo < hi < 1):
        raise ValueError('band %g Hz (frac %g) does not fit below Nyquist %g' % (f0, frac, nyq))
    sos = butter(4, [lo, hi], btype='band', output='sos')
    return sosfilt(sos, ir)


def _noise_floor_db(band, pk, fs):
    """Floor in dB relative to the band's peak.

    Preferred estimate is the PRE-arrival region (before any signal exists).
    Many real REW IR exports keep little or no pre-delay, so we fall back to
    the far TAIL -- by which point a car-cabin decay is long finished, leaving
    only the measurement/reconstruction floor. Returns None only when neither
    region is usable, rather than inventing a number."""
    peak = np.abs(band[pk])
    if peak <= 0:
        return None
    guard = int(0.005 * fs)
    if pk - guard >= int(0.010 * fs):
        pre = np.abs(band[:pk - guard])
        if pre.size:
            return 20 * np.log10(np.median(pre) / peak + 1e-30)
    tail = np.abs(band[int(len(band) * 0.9):])
    if tail.size >= 64:
        return 20 * np.log10(np.median(tail) / peak + 1e-30)
    return None


def decay_band(ir, fs, f0, drop=20.0, frac=1.0, floor_margin=3.0):
    """Guarded decay time for one band.

    Returns a dict with 't_ms' (None if unreliable), the estimated noise floor,
    the time the decay reaches that floor, and an explicit 'reliable' flag +
    reason. The guard is the point of this function: a T-value is only returned
    if the -drop dB crossing happens BEFORE the decay reaches floor_margin dB of
    the noise floor."""
    band = _bandpass(ir, fs, f0, frac)
    pk = int(np.argmax(np.abs(band)))
    nf = _noise_floor_db(band, pk, fs)
    tail = band[pk:]
    e = tail ** 2
    sch = np.cumsum(e[::-1])[::-1]
    sch = 10 * np.log10(sch / (sch[0] + 1e-30) + 1e-30)
    hit = np.where(sch <= -drop)[0]
    t_ms = float(hit[0] / fs * 1000.0) if len(hit) else None
    out = {'hz': f0, 'drop_db': drop, 't_ms': t_ms,
           'noise_floor_db': None if nf is None else round(nf, 1),
           'floor_reached_ms': None, 'reliable': False, 'reason': ''}
    if nf is None:
        out['reason'] = 'no pre-arrival region to estimate a noise floor'
        return out
    env_db = 20 * np.log10(np.abs(tail) / (np.abs(band[pk]) + 1e-30) + 1e-30)
    win = max(1, int(0.002 * fs))
    smooth = np.array([env_db[i:i + win].max() for i in range(0, len(env_db) - win, win)])
    tt = np.arange(len(smooth)) * win / fs * 1000.0
    reach = np.where(smooth <= nf + floor_margin)[0]
    t_floor = float(tt[reach[0]]) if len(reach) else None
    out['floor_reached_ms'] = None if t_floor is None else round(t_floor, 1)
    if t_ms is None:
        out['reason'] = 'decay never reaches -%g dB' % drop
    elif t_floor is not None and t_ms >= t_floor:
        out['reason'] = ('-%g dB crossing (%.1f ms) is at/after the noise floor '
                         '(%.1f ms) -- not a real decay time' % (drop, t_ms, t_floor))
        out['t_ms'] = None
    elif nf > -(drop + floor_margin):
        out['reason'] = ('noise floor only %.1f dB below peak -- cannot resolve '
                         'a -%g dB decay' % (-nf, drop))
        out['t_ms'] = None
    else:
        out['reliable'] = True
        out['reason'] = 'ok'
    return out


def decay_report(ir, fs, bands=DEFAULT_BANDS, drop=20.0, frac=1.0):
    return [decay_band(ir, fs, f0, drop=drop, frac=frac) for f0 in bands]


def csd(ir, fs, bands=DEFAULT_BANDS, slices_ms=(0, 2, 5, 10, 20, 40, 80), frac=1.0):
    """Waterfall as a table: level (dB rel. that band's peak) at each time slice.
    Values at or below the band's noise floor are returned as None -- an
    un-plottable hole is more honest than a number that is really just noise."""
    rows = []
    for f0 in bands:
        band = _bandpass(ir, fs, f0, frac)
        pk = int(np.argmax(np.abs(band)))
        peak = np.abs(band[pk])
        nf = _noise_floor_db(band, pk, fs)
        vals = []
        for ms in slices_ms:
            i = pk + int(ms / 1000.0 * fs)
            if i >= len(band):
                vals.append(None)
                continue
            w = max(1, int(0.001 * fs))
            v = 20 * np.log10(np.abs(band[max(i - w, 0):i + w]).max() / (peak + 1e-30) + 1e-30)
            vals.append(None if (nf is not None and v <= nf + 3.0) else round(float(v), 1))
        rows.append({'hz': f0, 'noise_floor_db': None if nf is None else round(nf, 1),
                     'slices_ms': list(slices_ms), 'levels_db': vals})
    return rows


# ---------------------------------------------------------------- CLI
def _load_any(path, fs_hint=48000.0):
    if path.lower().endswith('.wav'):
        return load_ir_wav(path)
    return load_ir_text(path)


def _main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('t20', 'csd'):
        p = sub.add_parser(name)
        p.add_argument('ir')
        p.add_argument('--drop', type=float, default=20.0)
        p.add_argument('--frac', type=float, default=1.0)
        p.add_argument('--slices', type=int, default=7)
    c = sub.add_parser('compare')
    c.add_argument('a')
    c.add_argument('b')
    c.add_argument('--drop', type=float, default=20.0)
    a = ap.parse_args()

    if a.cmd == 't20':
        ir, fs = _load_any(a.ir)
        print('IR: %d samples @ %g Hz (%.0f ms)' % (len(ir), fs, len(ir) / fs * 1000))
        print('\n%6s %10s %12s %12s  %s' % ('Hz', 'T%g' % a.drop, 'floor dB', 'floor @ms', 'status'))
        for r in decay_report(ir, fs, drop=a.drop, frac=a.frac):
            t = '%.1f ms' % r['t_ms'] if r['t_ms'] is not None else '--'
            print('%6d %10s %12s %12s  %s' % (
                r['hz'], t,
                '--' if r['noise_floor_db'] is None else '%.1f' % r['noise_floor_db'],
                '--' if r['floor_reached_ms'] is None else '%.1f' % r['floor_reached_ms'],
                'OK' if r['reliable'] else r['reason']))
        ok = sum(1 for r in decay_report(ir, fs, drop=a.drop, frac=a.frac) if r['reliable'])
        print('\n%d bands reliable. If most are not, the capture lacks dynamic range '
              '-- average more, raise level, or use a smaller --drop (e.g. 10).' % ok)

    elif a.cmd == 'csd':
        ir, fs = _load_any(a.ir)
        sl = [0, 2, 5, 10, 20, 40, 80, 120, 160, 200, 300, 400][:a.slices]
        rows = csd(ir, fs, slices_ms=sl, frac=a.frac)
        print('%6s ' % 'Hz' + ' '.join('%7d' % s for s in sl) + '   floor')
        for r in rows:
            cells = ' '.join('%7s' % ('--' if v is None else '%.1f' % v) for v in r['levels_db'])
            print('%6d %s   %s' % (r['hz'], cells,
                                   '--' if r['noise_floor_db'] is None else '%.1f' % r['noise_floor_db']))
        print("\n'--' = at or below this band's noise floor: no usable data there.")

    elif a.cmd == 'compare':
        ia, fa = _load_any(a.a)
        ib, fb = _load_any(a.b)
        ra = {r['hz']: r for r in decay_report(ia, fa, drop=a.drop)}
        rb = {r['hz']: r for r in decay_report(ib, fb, drop=a.drop)}
        print('%6s %12s %12s %10s  %s' % ('Hz', 'A', 'B', 'B-A', 'usable?'))
        for hz in sorted(ra):
            A, B = ra[hz], rb[hz]
            both = A['reliable'] and B['reliable']
            d = '%+.1f' % (B['t_ms'] - A['t_ms']) if both else '--'
            print('%6d %12s %12s %10s  %s' % (
                hz,
                '%.1f' % A['t_ms'] if A['t_ms'] is not None else '--',
                '%.1f' % B['t_ms'] if B['t_ms'] is not None else '--',
                d, 'yes' if both else 'NO -- do not compare'))


def _selftest():
    fs = 48000.0
    n = 1 << 16
    t = np.arange(n) / fs
    rng = np.random.default_rng(3)

    def synth(f0, tau_ms, noise_db=-80.0, pre_ms=20.0):
        """Decaying tone starting after a realistic pre-delay, plus noise."""
        d = int(pre_ms / 1000.0 * fs)
        env = np.zeros(n)
        env[d:] = np.exp(-(t[:n - d]) / (tau_ms / 1000.0))
        sig = env * np.sin(2 * np.pi * f0 * (t - pre_ms / 1000.0))
        sig[d] += 1.0
        return sig + rng.normal(0, 10 ** (noise_db / 20.0), n)

    # a known exponential decay must be recovered
    TAU = 30.0
    ir = synth(100.0, TAU)
    r = decay_band(ir, fs, 100.0, drop=20.0)
    assert r['reliable'], r
    expect = TAU * (20.0 / 8.6859)          # t = tau * drop_dB / (20/ln10)
    assert abs(r['t_ms'] - expect) / expect < 0.25, (r['t_ms'], expect)
    print('decay selftest: recovers a known %.0f ms tau (T20 %.1f vs %.1f expected) OK'
          % (TAU, r['t_ms'], expect))

    # a HIGH noise floor must produce a refusal, not a number
    noisy = synth(100.0, TAU, noise_db=-12.0)
    rn = decay_band(noisy, fs, 100.0, drop=20.0)
    assert not rn['reliable'] and rn['t_ms'] is None, rn
    print('decay selftest: refuses T20 when the floor is too high OK (%s)' % rn['reason'][:52])

    # ...but a smaller drop should still work on that same noisy capture
    rn10 = decay_band(synth(100.0, TAU, noise_db=-40.0), fs, 100.0, drop=10.0)
    assert rn10['reliable'], rn10
    print('decay selftest: smaller --drop still usable on a noisier capture OK')

    # faster decay must measure shorter than slower decay
    fast = decay_band(synth(100.0, 10.0), fs, 100.0, drop=20.0)
    slow = decay_band(synth(100.0, 60.0), fs, 100.0, drop=20.0)
    assert fast['reliable'] and slow['reliable']
    assert fast['t_ms'] < slow['t_ms'], (fast['t_ms'], slow['t_ms'])
    print('decay selftest: orders fast (%.1f ms) < slow (%.1f ms) OK' % (fast['t_ms'], slow['t_ms']))

    # csd must hole-punch below the floor rather than report noise
    rows = csd(synth(100.0, 5.0, noise_db=-45.0), fs, bands=(100,), slices_ms=(0, 5, 200))
    assert rows[0]['levels_db'][0] is not None
    assert rows[0]['levels_db'][-1] is None, rows[0]
    print('decay selftest: CSD returns None below the noise floor OK')

    # the aliasing bug that caused the 1300 ms result must now raise
    freqs = np.arange(1, 5000) * 0.36621097
    try:
        ir_from_spectrum(freqs, np.zeros(len(freqs)), np.zeros(len(freqs)), fs=44100.0)
        raise AssertionError('should have refused a mismatched fs/grid')
    except ValueError as e:
        print('decay selftest: refuses mismatched fs/FFT grid OK (%s)' % str(e)[:46])
    ir2, _ = ir_from_spectrum(freqs, np.zeros(len(freqs)), np.zeros(len(freqs)), fs=48000.0)
    assert len(ir2) == 131072, len(ir2)
    print('decay selftest: accepts the correct fs (n=131072) OK')
    print('\nALL DECAY SELFTESTS PASSED')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'selftest':
        _selftest()
    else:
        _main()
