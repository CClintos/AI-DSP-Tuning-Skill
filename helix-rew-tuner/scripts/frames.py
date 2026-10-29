# frames.py -- one MMM run that measures its own repeatability.
#
# REW's RTA shows the power mean of every FFT block in a capture and throws
# the blocks away. Kept, the blocks of ONE moving-mic run also give:
#   - the spread across the path (how much each frequency moves);
#   - split-half repeatability: the first half of the path against the
#     second, a measured resolution in place of the assumed 0.25-0.3 dB;
#   - a robust mean that drops handling bumps and passing cars;
#   - REW's own peak-hold trace (max over blocks) for the stability map;
#   - coverage: blocks used, seconds, fraction kept.
#
# Two sources of blocks, both read-only:
#   1) a WAV recording of the mic made during the MMM pass (any recorder, 48 kHz
#      is typical). The RTA is computed here: 1/N-octave band power per block,
#      the mic cal file applied. REW's RTA can process the same WAV (Open WAV)
#      as a cross-check of the average.
#   2) frames polled from a running REW with `rew_api.py rta-frames` (RTA
#      averaging set to None, so each poll is one block) -- GET requests only.
#
# Outputs are REW-style text exports every command reads: mean, robust mean,
# peak, and the two halves. Pass the halves as `--positions half1 half2
# --capture mmm` and the repeatability-gated features (verify thresholds,
# mmm-compare resolution, narrower Q where stable) switch on from one run.
# Each half covers half the path, so its repeatability overstates the full
# capture's by about sqrt(2): conservative, never optimistic.
#
# Absolute level: without --spl-offset-db the output is dBFS (re a full-scale
# sine). The UMIK cal file's response correction is applied when given; its
# sensitivity is not (REW's mapping for it is not documented here).
#
# CLI (through pipeline.py frames):
#   pipeline.py frames --wav pass.wav --cal 7160281_90deg.txt --out-dir D [--fft 65536]
#   pipeline.py frames --api-frames frames.json --out-dir D
import json
import math
import os
import struct

import numpy as np

import measure

REW_OVERLAP = {16384: 0.5, 32768: 0.75, 65536: 0.875, 131072: 0.9375}
BUMP_DB = 6.0            # a block this much above the median low-band energy is a bump


# ------------------------------------------------------------------ WAV
def read_wav(path):
    """(samples float64 [n, channels] in -1..1, sample_rate). PCM 16/24/32-bit
    and IEEE float 32/64, plain or WAVE_FORMAT_EXTENSIBLE."""
    with open(path, 'rb') as fh:
        data = fh.read()
    if data[:4] not in (b'RIFF', b'RF64') or data[8:12] != b'WAVE':
        raise ValueError('%s is not a WAV file' % path)
    pos, fmt, raw = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack('<I', data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b'fmt ':
            fmt = body
        elif cid == b'data':
            raw = body if size != 0xFFFFFFFF else data[pos + 8:]
        pos += 8 + size + (size & 1)
    if fmt is None or raw is None:
        raise ValueError('%s has no fmt/data chunk' % path)
    tag, channels, rate = struct.unpack('<HHI', fmt[:8])
    bits = struct.unpack('<H', fmt[14:16])[0]
    if tag == 0xFFFE and len(fmt) >= 26:
        tag = struct.unpack('<H', fmt[24:26])[0]
    width = bits // 8
    n = len(raw) // (width * channels)
    raw = raw[:n * width * channels]
    if tag == 3 and bits in (32, 64):
        x = np.frombuffer(raw, dtype='<f%d' % width).astype(np.float64)
    elif tag == 1 and bits == 16:
        x = np.frombuffer(raw, dtype='<i2') / 32768.0
    elif tag == 1 and bits == 24:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = np.where(v >= 1 << 23, v - (1 << 24), v) / float(1 << 23)
    elif tag == 1 and bits == 32:
        x = np.frombuffer(raw, dtype='<i4') / 2147483648.0
    else:
        raise ValueError('%s: unsupported WAV encoding (format %d, %d-bit)' % (path, tag, bits))
    return x.reshape(-1, channels), float(rate)


def write_wav(path, x, rate, bits=24):
    """Write float samples (-1..1, [n] or [n, ch]) as PCM; refuses to overwrite."""
    x = np.atleast_2d(np.asarray(x, dtype=float).T).T
    if x.ndim == 1:
        x = x[:, None]
    n, ch = x.shape
    if np.max(np.abs(x)) >= 1.0:
        raise ValueError('samples reach full scale: lower the level')
    if bits == 16:
        payload = np.round(x * 32767).astype('<i2').tobytes()
    elif bits == 24:
        v = np.round(x * ((1 << 23) - 1)).astype(np.int32).reshape(-1)
        b = np.empty((v.size, 3), dtype=np.uint8)
        b[:, 0], b[:, 1], b[:, 2] = v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF
        payload = b.tobytes()
    else:
        raise ValueError('bits must be 16 or 24')
    width = bits // 8
    hdr = b'RIFF' + struct.pack('<I', 36 + len(payload)) + b'WAVE' + b'fmt ' + struct.pack(
        '<IHHIIHH', 16, 1, ch, int(rate), int(rate) * ch * width, ch * width, bits)
    with open(path, 'xb') as fh:
        fh.write(hdr + b'data' + struct.pack('<I', len(payload)) + payload)


# ------------------------------------------------------------------ cal file
def load_cal(path):
    """Mic cal file -> (freqs, dB). Header lines (e.g. "Sens Factor =-1.761dB,
    SERNO: 7160281") are skipped."""
    f, d = [], []
    with open(path, encoding='utf-8-sig', errors='replace') as fh:
        for line in fh:
            parts = line.replace(',', ' ').replace('\t', ' ').split()
            try:
                a, b = float(parts[0]), float(parts[1])
            except (ValueError, IndexError):
                continue
            if a > 0:
                f.append(a)
                d.append(b)
    if len(f) < 4:
        raise ValueError('%s does not look like a mic calibration file' % path)
    order = np.argsort(f)
    return np.asarray(f)[order], np.asarray(d)[order]


# ------------------------------------------------------------------ blocks
def block_spectra(x, rate, fft=65536, overlap=None, window='hann'):
    """(bin_freqs, mean-square power per bin per block [blocks, bins]).
    Normalised so a band's bins sum to that band's mean-square level."""
    x = np.asarray(x, dtype=float)
    if x.ndim > 1:
        x = x.mean(axis=1) if x.shape[1] > 1 else x[:, 0]
    if overlap is None:
        overlap = REW_OVERLAP.get(fft, 0.5)
    hop = max(1, int(round(fft * (1.0 - overlap))))
    if len(x) < fft:
        raise ValueError('recording (%d samples) is shorter than one %d-point FFT' % (len(x), fft))
    w = np.hanning(fft) if window == 'hann' else np.ones(fft)
    scale = 2.0 / (fft * np.sum(w ** 2))
    starts = range(0, len(x) - fft + 1, hop)
    out = np.empty((len(starts), fft // 2 + 1))
    for i, s in enumerate(starts):
        spec = np.fft.rfft(x[s:s + fft] * w)
        out[i] = np.abs(spec) ** 2 * scale
    out[:, 0] /= 2.0
    return np.fft.rfftfreq(fft, 1.0 / rate), out, hop


def fractional_bands(bin_freqs, power, frac=48, ppo=96, lo=10.0, hi=None):
    """Sum bins into 1/frac-octave bands centred on a ppo-per-octave grid."""
    hi = hi or bin_freqs[-1] / 2 ** (0.5 / frac)
    centres = measure.common_grid(lo, hi, ppo)
    edges_lo = np.searchsorted(bin_freqs, centres / 2 ** (0.5 / frac))
    edges_hi = np.searchsorted(bin_freqs, centres * 2 ** (0.5 / frac))
    keep = edges_hi > edges_lo
    c = np.concatenate([np.zeros((power.shape[0], 1)), np.cumsum(power, axis=1)], axis=1)
    bands = c[:, edges_hi[keep]] - c[:, edges_lo[keep]]
    return centres[keep], bands


def frames_from_wav(path, fft=65536, overlap=None, frac=48, cal=None, spl_offset_db=None,
                    channel=None):
    x, rate = read_wav(path)
    if channel is not None:
        if not 0 <= channel < x.shape[1]:
            raise ValueError('%s has %d channel(s)' % (path, x.shape[1]))
        x = x[:, channel:channel + 1]
    clipped = float(np.mean(np.abs(x) >= 0.999))
    bf, p, hop = block_spectra(x, rate, fft, overlap)
    freqs, bands = fractional_bands(bf, p, frac)
    db = 10.0 * np.log10(np.maximum(bands, 1e-30) / 0.5)      # dBFS re full-scale sine
    if cal is not None:
        cf, cd = load_cal(cal)
        db = db - np.interp(np.log10(freqs), np.log10(cf), cd)
    unit = 'dBFS'
    if spl_offset_db is not None:
        db = db + spl_offset_db
        unit = 'dB SPL (offset %+.2f dB)' % spl_offset_db
    meta = {'source': 'wav', 'file': path, 'sample_rate_hz': rate, 'fft_length': fft,
            'hop': hop, 'block_seconds': hop / rate, 'unit': unit, 'rta_fraction': frac,
            'cal_file': cal, 'clipped_fraction': clipped,
            'seconds': len(x) / rate}
    return freqs, db, meta


def frames_from_api(path):
    """Frames polled from REW (rew_api.py rta-frames): one dB array per block."""
    with open(path, encoding='utf-8') as fh:
        d = json.load(fh)
    if d.get('format') != 'rew-rta-frames-v1':
        raise ValueError('%s is not an rta-frames file from rew_api.py' % path)
    freqs = np.asarray(d['freqs'], dtype=float)
    frames = [fr for fr in d['frames'] if len(fr['db']) == len(freqs)]
    if len(frames) < 4:
        raise ValueError('%s holds %d usable frames; at least 4 are needed' % (path, len(frames)))
    db = np.array([fr['db'] for fr in frames], dtype=float)
    counts = [fr.get('sample_count') for fr in frames]
    span = None
    if counts[0] is not None and counts[-1] is not None and d.get('sample_rate_hz'):
        span = (counts[-1] - counts[0]) / float(d['sample_rate_hz'])
    return freqs, db, {'source': 'rew-api', 'file': path, 'unit': d.get('unit', 'SPL'),
                       'seconds': span, 'averaging': d.get('averaging'),
                       'sample_rate_hz': d.get('sample_rate_hz')}


# ------------------------------------------------------------------ analysis
def _mean_db(db, rows=None):
    p = 10.0 ** (db / 10.0) if rows is None else 10.0 ** (db[rows] / 10.0)
    return 10.0 * np.log10(np.mean(p, axis=0))


def analyze_frames(freqs, db, bump_db=BUMP_DB, low_band=(20.0, 120.0)):
    """Statistics of one capture's blocks (rows of db, dB per band)."""
    n = db.shape[0]
    if n < 4:
        raise ValueError('need at least 4 blocks')
    low = (freqs >= low_band[0]) & (freqs <= low_band[1])
    energy = 10 * np.log10(np.mean(10 ** (db[:, low] / 10), axis=1)) if np.any(low) else np.zeros(n)
    broad = 10 * np.log10(np.mean(10 ** (db / 10), axis=1))
    med_e, med_b = np.median(energy), np.median(broad)
    bumps = (energy > med_e + bump_db) | (broad > med_b + bump_db)
    keep = ~bumps
    if np.count_nonzero(keep) < max(4, n // 2):
        keep = np.ones(n, dtype=bool)          # too many "bumps": the capture is just uneven
        bumps[:] = False
    half = n // 2
    first, second = np.arange(half), np.arange(half, n)
    first, second = first[keep[first]], second[keep[second]]
    if len(first) < 2 or len(second) < 2:
        raise ValueError('too few clean blocks in one half of the capture to compare halves')
    return {
        'mean_db': _mean_db(db), 'robust_db': _mean_db(db, keep),
        'peak_db': np.max(db, axis=0),
        'spread_db': np.std(db[keep], axis=0, ddof=1),
        'half1_db': _mean_db(db, first), 'half2_db': _mean_db(db, second),
        'blocks': n, 'kept': int(np.count_nonzero(keep)),
        'bump_blocks': [int(i) for i in np.flatnonzero(bumps)],
    }


def _write(path, freqs, db, lines):
    with open(path, 'x', encoding='utf-8') as fh:
        for line in lines:
            fh.write('* %s\n' % line)
        fh.write('* Freq(Hz) SPL(dB)\n')
        for f, s in zip(freqs, db):
            fh.write('%.6f %.4f\n' % (f, s))


def run(args):
    import tunelib
    if bool(args.wav) == bool(args.api_frames):
        raise ValueError('give one of --wav or --api-frames')
    if args.wav:
        freqs, db, meta = frames_from_wav(args.wav, args.fft, args.overlap, args.rta_fraction,
                                          args.cal, args.spl_offset_db, args.channel)
    else:
        freqs, db, meta = frames_from_api(args.api_frames)
    stats = analyze_frames(freqs, db)
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    stem = args.name or os.path.splitext(os.path.basename(args.wav or args.api_frames))[0]
    files = {}
    head = ['Measurement data from frames.py (%s, %d blocks)' % (meta['source'], stats['blocks']),
            'Format: %d-point 1/%d octave RTA using Hann window, no smoothing and %d averages'
            % (meta.get('fft_length') or 0, meta.get('rta_fraction') or 48, stats['blocks']),
            'Smoothing: None', 'unit: %s' % meta['unit']]
    for key, label in (('mean_db', 'mean'), ('robust_db', 'robust'), ('peak_db', 'peak'),
                       ('half1_db', 'half1'), ('half2_db', 'half2')):
        path = os.path.join(out_dir, '%s_%s.txt' % (stem, label))
        _write(path, freqs, stats[key], head + ['Measurement: %s %s' % (stem, label)])
        files[label] = path
    live = (freqs >= 20.0) & (freqs <= min(20000.0, freqs[-1]))
    rep = tunelib.capture_repeatability(freqs, [stats['half1_db'], stats['half2_db']], support=live)
    public = tunelib.public_repeatability(rep)
    spread = stats['spread_db']
    bands = []
    for name, lo, hi in (('bass', 20, 250), ('midrange', 250, 4000), ('treble', 4000, 16000)):
        sel = live & (freqs >= lo) & (freqs <= hi)
        if np.any(sel):
            bands.append({'name': name, 'median_spread_db': round(float(np.median(spread[sel])), 2)})
    notes = []
    secs = meta.get('seconds')
    if secs is not None and secs < 20:
        notes.append('only %.0f s of capture: an MMM pass needs about 20 s or more' % secs)
    if meta.get('clipped_fraction'):
        notes.append('%.3f%% of samples at full scale: the recording clipped -- lower the input '
                     'gain or the playback level' % (100 * meta['clipped_fraction']))
    if stats['bump_blocks']:
        notes.append('%d block(s) dropped from the robust mean as handling bumps or passing noise '
                     '(more than %.0f dB above the median energy)' % (len(stats['bump_blocks']), BUMP_DB))
    robust_vs_mean = float(np.max(np.abs((stats['robust_db'] - stats['mean_db'])[live])))
    if robust_vs_mean > 0.5:
        notes.append('the robust mean differs from the plain mean by up to %.1f dB: use the robust '
                     'file' % robust_vs_mean)
    return {'meta': dict(meta, blocks=stats['blocks'], kept=stats['kept']),
            'files': files, 'split_half_repeatability': public,
            'path_spread': bands,
            'use': ['--measurement %s --capture mmm  (one run, robust mean)' % files['robust'],
                    '--positions %s %s --capture mmm  (repeatability from this one run; '
                    'conservative by about sqrt(2))' % (files['half1'], files['half2']),
                    '--peak-trace %s  (bass stability map, with the mean file)' % files['peak']],
            'notes': notes}
