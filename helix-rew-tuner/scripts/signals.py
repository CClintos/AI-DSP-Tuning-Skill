# signals.py -- EXPERIMENTAL: the skill's own test signals, and what a
# recording of them measures that pink noise in REW's RTA cannot.
#
# Each signal is periodic in one FFT length (65536 samples at 48 kHz by
# default) with a known spectrum, preceded by silence:
#   pink-periodic    every bin, pink weighting: a known-excitation RTA source.
#   multitone-empty  pink tones with every Nth bin left EMPTY: the empty bins
#                    measure noise plus intermodulation at the real playback
#                    level during every capture. The lead-in silence measures
#                    the noise alone, with the same mic movement.
#   lr-interleaved   left on bins 1 mod 3, right on bins 2 mod 3, 0 mod 3
#                    empty: one moving capture gives left, right, their level
#                    difference per band, and the L+R sum predicted with phase
#                    at the same positions.
#
# Play the WAV from the car's own source (USB) while recording the mic (any
# recorder; the analysis corrects the clock difference between the two).
# Analysis per period: the recording is resampled onto the player's clock,
# each period is one rectangular-window FFT, and every tone gives a complex
# transfer value. Coherent averaging of those values across the path shows how
# much of each band's field is common to the whole head area.
#
# LIMITS (why this is experimental):
#   - Mic motion Doppler-shifts tones into neighbouring bins: at 0.3 m/s the
#     shift is f * 0.3/343, a quarter of a bin (0.73 Hz) near 210 Hz and a
#     whole bin near 840 Hz. Empty-bin readings above `doppler_limit_hz` are
#     leakage, not noise; they are reported as such, never as distortion.
#   - The L/R phase interpolation assumes the two arrivals are within a few ms;
#     it is checked in simulation only, not yet against a real car.
#   - Nothing here replaces a timed sweep for delays.
import json
import math
import os

import numpy as np

import frames
import measure

KINDS = ('pink-periodic', 'multitone-empty', 'lr-interleaved')
GEN_VERSION = 1
SPEED_OF_SOUND = 343.0


def _plan(kind, rate, fft, lo, hi, empty_every):
    k = np.arange(1, fft // 2)
    f = k * rate / fft
    band = (f >= lo) & (f <= hi)
    if kind == 'pink-periodic':
        left = right = band
    elif kind == 'multitone-empty':
        left = right = band & (k % empty_every != 0)
    elif kind == 'lr-interleaved':
        left, right = band & (k % 3 == 1), band & (k % 3 == 2)
    else:
        raise ValueError('kind must be one of %s' % ', '.join(KINDS))
    return k, f, left, right


def source_spectra(spec):
    """Complex one-period spectra (rfft scale) of the left and right channels."""
    kind, rate, fft = spec['kind'], spec['sample_rate_hz'], spec['fft_length']
    k, f, left, right = _plan(kind, rate, fft, spec['lo_hz'], spec['hi_hz'], spec['empty_every'])
    rng = np.random.default_rng(spec['seed'])
    phase = rng.uniform(0, 2 * np.pi, len(k))
    amp = 1.0 / np.sqrt(f)
    out = []
    for mask in (left, right):
        X = np.zeros(fft // 2 + 1, complex)
        X[k[mask]] = amp[mask] * np.exp(1j * phase[mask])
        out.append(X)
    if kind == 'lr-interleaved':
        return out[0], out[1]
    return out[0], out[0].copy()


def make(kind, rate=48000, fft=65536, seconds=45.0, level_dbfs=-15.0, seed=1, lo=15.0,
         hi=20000.0, empty_every=3, lead_in_s=3.0):
    """(samples [n, 2], spec). level_dbfs is each channel's RMS re full scale."""
    spec = {'format': 'helix-rew-tuner-signal-v%d' % GEN_VERSION, 'kind': kind,
            'sample_rate_hz': int(rate), 'fft_length': int(fft), 'seed': int(seed),
            'lo_hz': float(lo), 'hi_hz': float(hi), 'empty_every': int(empty_every),
            'lead_in_s': float(lead_in_s), 'level_dbfs': float(level_dbfs)}
    XL, XR = source_spectra(spec)
    periods = []
    for X in (XL, XR):
        x = np.fft.irfft(X, fft)
        # dBFS re a full-scale sine, whose RMS is 1/sqrt(2). The same scale
        # factor multiplies every tone, so it cancels out of relative results.
        x = x / np.sqrt(np.mean(x ** 2)) * 10 ** (level_dbfs / 20.0) / math.sqrt(2)
        periods.append(x)
    spec['scale'] = [float(np.sqrt(np.mean(p ** 2)) / np.sqrt(np.mean(np.fft.irfft(X, fft) ** 2)))
                     for p, X in zip(periods, (XL, XR))]
    peak = max(np.max(np.abs(p)) for p in periods)
    if peak >= 0.89:
        raise ValueError('level %.1f dBFS RMS puts peaks at %.1f dBFS: lower --level-dbfs'
                         % (level_dbfs, 20 * math.log10(peak)))
    n_per = int(math.ceil(seconds * rate / fft))
    body = np.stack([np.tile(p, n_per) for p in periods], axis=1)
    lead = np.zeros((int(lead_in_s * rate), 2))
    tail = np.zeros((int(0.5 * rate), 2))
    spec['periods'] = n_per
    spec['peak_dbfs'] = round(20 * math.log10(peak), 2)
    return np.concatenate([lead, body, tail]), spec


def make_cmd(args):
    x, spec = make(args.kind, args.rate, args.fft, args.seconds, args.level_dbfs, args.seed,
                   args.lo, args.hi, args.empty_every, args.lead_in)
    if os.path.exists(args.wav_out) or os.path.exists(args.wav_out + '.json'):
        raise ValueError('%s (or its .json) already exists -- choose a new name' % args.wav_out)
    if os.path.splitext(args.wav_out)[1].lower() != '.wav':
        raise ValueError('--wav-out must end in .wav')
    frames.write_wav(args.wav_out, x, args.rate, 24)
    with open(args.wav_out + '.json', 'x', encoding='utf-8') as fh:
        json.dump(spec, fh, indent=2)
    return {'wav': args.wav_out, 'spec': args.wav_out + '.json', 'signal': spec,
            'play': ['copy the WAV to the car\'s USB source and play it at your normal level '
                     '(check peaks stay clean: %.1f dBFS)' % spec['peak_dbfs'],
                     'record the mic for the whole file, starting before it plays, while moving '
                     'the mic around the head as for any MMM capture',
                     'then: pipeline.py signal-analyze --wav <recording> --spec %s.json' % args.wav_out]}


# ------------------------------------------------------------------ analysis
def _envelope_start(x, rate, floor_s):
    """Index where the test signal starts: energy 20 dB over the lead-in."""
    win = int(0.05 * rate)
    e = np.convolve(x ** 2, np.ones(win) / win, mode='same')
    quiet = np.median(e[:max(win, int(floor_s * rate))]) + 1e-20
    above = np.flatnonzero(e > quiet * 100.0)
    if not above.size:
        raise ValueError('no test signal found above the lead-in noise')
    return int(above[0])


def clock_ratio(seg, period, max_ppm=500.0):
    """Recorded samples per source period / period, from the autocorrelation
    peak near one period (parabolic refinement)."""
    span = int(math.ceil(period * max_ppm * 1e-6)) + 2
    lags = np.arange(period - span, period + span + 1)
    n = len(seg) - lags[-1]
    if n < period:
        raise ValueError('recording too short to measure the clock (needs 2+ periods)')
    a = seg[:n]
    r = np.array([np.dot(a, seg[L:L + n]) for L in lags])
    i = int(np.argmax(r))
    if 0 < i < len(r) - 1:
        y0, y1, y2 = r[i - 1], r[i], r[i + 1]
        den = y0 - 2 * y1 + y2
        frac = 0.5 * (y0 - y2) / den if den else 0.0
    else:
        frac = 0.0
    return (lags[i] + frac) / period


_KERNEL = {}


def _kernel(taps, beta, phases=1024):
    """Kaiser-windowed sinc sampled at `phases`+1 fractional offsets."""
    key = (taps, beta, phases)
    if key not in _KERNEL:
        half = taps // 2
        m = np.arange(-half + 1, half + 1)
        d = (np.arange(phases + 1) / phases)[:, None] - m[None, :]
        w = np.i0(beta * np.sqrt(np.clip(1 - (d / half) ** 2, 0, 1))) / np.i0(beta)
        _KERNEL[key] = np.sinc(d) * w
    return _KERNEL[key]


def _resample(seg, ratio, period, n_periods, taps=128, beta=10.0, phases=1024):
    """seg read at fractional positions n * ratio (n = 0 .. n_periods*period-1)
    with a Kaiser-windowed sinc: exact in time, so no whole-sample rounding of
    the clock ratio (half a sample over the segment leaks every tone at HF)."""
    n_out = n_periods * period
    half = taps // 2
    need = int(math.ceil((n_out - 1) * ratio)) + half + 1
    if need > len(seg):
        raise ValueError('recording too short for %d periods' % n_periods)
    x = np.concatenate([np.zeros(half), seg[:need + half]])
    m = np.arange(-half + 1, half + 1)
    table = _kernel(taps, beta, phases)
    out = np.empty(n_out)
    for s in range(0, n_out, 16384):
        t = np.arange(s, min(s + 16384, n_out)) * ratio
        i0 = np.floor(t).astype(np.int64)
        pos = (t - i0) * phases
        p0 = np.minimum(pos.astype(np.int64), phases - 1)
        a = (pos - p0)[:, None]
        h = table[p0] * (1 - a) + table[p0 + 1] * a
        out[s:s + len(t)] = np.einsum('ij,ij->i', x[(i0 + half)[:, None] + m[None, :]], h)
    return out


def _refine_ratio(blocks, f, mask, rate, period):
    """Residual clock error from the phase drift of low tones across periods."""
    sel = mask & (f >= 20) & (f <= 2000)
    if np.count_nonzero(sel) < 8 or blocks.shape[0] < 4:
        return 0.0
    ph = np.unwrap(np.angle(blocks[:, sel]), axis=0)
    b = np.arange(blocks.shape[0]) - (blocks.shape[0] - 1) / 2.0
    slope = (b @ (ph - ph.mean(axis=0))) / (b @ b)          # rad per period, per tone
    k = f[sel] * period / rate
    # a period too long by eps (fraction) delays tone k by 2*pi*k*eps per period
    return float(-np.sum(slope * k) / np.sum(k * k) / (2 * np.pi))


def transfer_blocks(x, rate, spec):
    """Per-period complex transfer at every excited bin, after clock correction.
    Returns dict with freqs, H_L/H_R [periods, bins] (NaN where not excited),
    raw power spectra, the silence-floor spectrum and the clock ratio."""
    period = spec['fft_length']
    if abs(rate - spec['sample_rate_hz']) > 1:
        raise ValueError('recording at %g Hz, signal made at %d Hz: record at the signal rate'
                         % (rate, spec['sample_rate_hz']))
    start = _envelope_start(x, rate, max(0.5, spec['lead_in_s'] - 0.5))
    lead = x[:max(0, start - int(0.2 * rate))]
    seg = x[start + period // 4:]
    ratio = clock_ratio(seg, period)
    n_periods = int(len(seg) / (period * ratio)) - 1
    if n_periods < 6:
        raise ValueError('only %d whole periods recorded: record the whole file' % n_periods)
    XL, XR = source_spectra(spec)
    scale = spec.get('scale') or [1.0, 1.0]
    XL, XR = XL * scale[0], XR * scale[1]
    f = np.fft.rfftfreq(period, 1.0 / rate)
    excited = (np.abs(XL) > 0) | (np.abs(XR) > 0)
    y = _resample(seg, ratio, period, n_periods)
    B = np.fft.rfft(y.reshape(n_periods, period), axis=1)
    for _ in range(4):
        eps = _refine_ratio(B[1:-1] / np.where(excited, XL + XR, 1.0), f, excited, rate, period)
        if abs(eps) < 2e-9:
            break
        ratio *= 1.0 + eps
        y = _resample(seg, ratio, period, n_periods)
        B = np.fft.rfft(y.reshape(n_periods, period), axis=1)
    B = B[1:-1]                               # resampling edge periods
    floor = None
    if len(lead) >= period:
        nf = len(lead) // period
        F = np.fft.rfft(lead[:nf * period].reshape(nf, period), axis=1)
        floor = np.mean(np.abs(F) ** 2, axis=0)
    out = {'freqs': f, 'power': np.abs(B) ** 2, 'floor_power': floor,
           'clock_ratio': ratio, 'clock_ppm': (ratio - 1.0) * 1e6, 'periods': B.shape[0]}
    with np.errstate(divide='ignore', invalid='ignore'):
        out['H_L'] = np.where(np.abs(XL) > 0, B / np.where(np.abs(XL) > 0, XL, 1.0), np.nan)
        out['H_R'] = np.where(np.abs(XR) > 0, B / np.where(np.abs(XR) > 0, XR, 1.0), np.nan)
    if spec['kind'] != 'lr-interleaved':
        out['H_R'] = None
    out['mask_L'], out['mask_R'] = np.abs(XL) > 0, np.abs(XR) > 0
    out['empty'] = ~excited & (f >= spec['lo_hz']) & (f <= spec['hi_hz'])
    return out


def _bulk_delay(H, f, rate, period):
    """Per period, the delay (s) of the strongest arrival in the combined
    transfer -- removed before interpolating phase between bins."""
    Hz = np.where(np.isfinite(H), H, 0.0)
    ir = np.fft.irfft(Hz, period, axis=1)
    return np.argmax(np.abs(ir), axis=1) / rate


def _interp_complex(f_from, H_from, f_to):
    return np.interp(f_to, f_from, H_from.real) + 1j * np.interp(f_to, f_from, H_from.imag)


def analyze(x, rate, spec, hand_speed=0.3, frac=6):
    tb = transfer_blocks(x, rate, spec)
    f = tb['freqs']
    bin_hz = rate / spec['fft_length']
    doppler_limit = 0.25 * bin_hz * SPEED_OF_SOUND / hand_speed
    centres = measure.common_grid(max(20.0, spec['lo_hz']), min(spec['hi_hz'], 0.45 * rate), frac)
    P = tb['power']
    rows = []
    hl, hr = tb['H_L'], tb['H_R']
    pred_sum = None
    if hr is not None:
        both = np.where(np.isfinite(hl), hl, 0) + np.where(np.isfinite(hr), hr, 0)
        d = _bulk_delay(both, f, rate, spec['fft_length'])
        rot = np.exp(2j * np.pi * f[None, :] * d[:, None])
        mL, mR = tb['mask_L'], tb['mask_R']
        HLc, HRc = hl[:, mL] * rot[:, mL], hr[:, mR] * rot[:, mR]
        HR_at_L = np.vstack([_interp_complex(f[mR], HRc[b], f[mL]) for b in range(HRc.shape[0])])
        pred_sum = np.abs(HLc + HR_at_L) ** 2
    for c in centres:
        sel = (f >= c / 2 ** (0.5 / frac)) & (f < c * 2 ** (0.5 / frac))
        row = {'hz': round(float(c), 1)}
        tones_l = sel & tb['mask_L']
        if np.count_nonzero(tones_l) < 2:
            continue
        HL = hl[:, tones_l]
        pl = np.mean(np.abs(HL) ** 2)
        row['left_db'] = round(10 * math.log10(pl), 2)
        row['left_field_coherence'] = round(float(np.mean(np.abs(np.mean(HL, axis=0)) ** 2)
                                                  / np.mean(np.abs(HL) ** 2)), 2)
        if hr is not None:
            tones_r = sel & tb['mask_R']
            if np.count_nonzero(tones_r) >= 2:
                pr = np.mean(np.abs(hr[:, tones_r]) ** 2)
                row['right_db'] = round(10 * math.log10(pr), 2)
                row['ild_db'] = round(row['left_db'] - row['right_db'], 2)
                ps = float(np.mean(pred_sum[:, sel[tb['mask_L']]]))
                row['predicted_sum_db'] = round(10 * math.log10(ps), 2)
                row['rho'] = round((ps - pl - pr) / (2 * math.sqrt(pl * pr)), 2)
        empty = sel & tb['empty']
        tones = sel & (tb['mask_L'] | tb['mask_R'])
        if np.count_nonzero(empty) >= 2:
            pe = float(np.mean(P[:, empty]))
            pt = float(np.mean(P[:, tones]))
            row['tone_to_empty_db'] = round(10 * math.log10(pt / pe), 1)
            if tb['floor_power'] is not None:
                fl = float(np.mean(tb['floor_power'][empty]))
                row['empty_over_silence_db'] = round(10 * math.log10(pe / fl), 1)
            row['empty_bins'] = 'leakage (Doppler)' if c > doppler_limit else 'noise + distortion'
        rows.append(row)
    return {'clock_ppm': round(tb['clock_ppm'], 2), 'periods': tb['periods'],
            'doppler_limit_hz': round(doppler_limit), 'bands': rows, 'blocks': tb}


def analyze_cmd(args):
    with open(args.spec, encoding='utf-8') as fh:
        spec = json.load(fh)
    if not str(spec.get('format', '')).startswith('helix-rew-tuner-signal-v'):
        raise ValueError('%s is not a signal description written by signals.py' % args.spec)
    x, rate = frames.read_wav(args.wav)
    ch = args.channel if args.channel is not None else 0
    if not 0 <= ch < x.shape[1]:
        raise ValueError('%s has %d channel(s)' % (args.wav, x.shape[1]))
    res = analyze(x[:, ch], rate, spec, args.hand_speed)
    res.pop('blocks')
    notes = ['EXPERIMENTAL: checked in simulation only. Empty-bin readings above %d Hz are mic-motion '
             'leakage at %.1f m/s, not distortion' % (res['doppler_limit_hz'], args.hand_speed),
             'field coherence near 1 means the whole head area shares one response in that band '
             '(a fixed-point sweep would represent it); near 0 it does not',
             'levels are relative to the digital source, not SPL']
    if abs(res['clock_ppm']) > 200:
        notes.append('clock difference %.0f ppm is unusually large: check both sample rates' % res['clock_ppm'])
    res['notes'] = notes
    res['meta'] = {'wav': args.wav, 'spec': args.spec, 'kind': spec['kind'], 'channel': ch}
    return res
