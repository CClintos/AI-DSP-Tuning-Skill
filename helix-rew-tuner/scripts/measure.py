# measure.py -- load measurements + target curve onto a common frequency grid.
#
# TWO input paths, in order of robustness:
#   1) REW TEXT EXPORT (recommended): "Freq  SPL  Phase" columns. Axis is explicit
#      and unambiguous, phase is available for real crossover/APF work. Export from
#      REW with: File > Export > Export measurement as text.
#   2) REW .mdat (convenience, MUST be validated): the binary carries float32 SPL
#      arrays but the frequency axis is reconstructed by assumption (log-spaced,
#      anchored at the top). ALWAYS validate the reconstructed axis against a known
#      feature (a crossover corner you know) before trusting it.
#
# CLI:
#   python measure.py textcols <export.txt>          # peek columns
#   python measure.py mdat <file.mdat>               # list SPL arrays found + axis guess
import struct
import sys

import numpy as np


def load_text_export(path):
    """REW text export -> (freqs, spl_db, phase_deg or None). Whitespace or comma
    separated; skips headers/comment lines. This is the robust, axis-explicit path."""
    f, s, p = [], [], []
    for line in open(path, encoding='utf-8', errors='replace'):
        line = line.strip()
        if not line or line[0].isalpha() or line[0] in '*#/':
            continue
        parts = line.replace(',', ' ').split()
        try:
            f.append(float(parts[0]))
            s.append(float(parts[1]))
            p.append(float(parts[2]) if len(parts) > 2 else np.nan)
        except (ValueError, IndexError):
            continue
    if len(f) < 8:
        raise ValueError('found <8 usable data rows in %s -- is this a REW text export?' % path)
    f, s, p = np.array(f), np.array(s), np.array(p)
    return f, s, (p if np.isfinite(p).any() else None)


def resample_log(freqs_src, y_src, freqs_dst):
    """Interpolate onto a target grid in log-frequency (correct for audio)."""
    return np.interp(np.log10(freqs_dst), np.log10(freqs_src), y_src)


def common_grid(lo=20.0, hi=20000.0, ppo=48):
    """A clean log grid (points-per-octave). Use to align multiple traces."""
    n = int(round(np.log2(hi / lo) * ppo)) + 1
    return lo * 2 ** (np.arange(n) / ppo)


# ------------------------------------------------------------ .mdat (validated fallback)
def mdat_spl_arrays(path, min_len=256):
    """Extract float32 SPL arrays from a REW .mdat (Java-serialized). Returns list
    of (offset, length, array). The frequency AXIS is NOT in here reliably -- you
    must reconstruct and validate it (see reconstruct_axis)."""
    data = open(path, 'rb').read()
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
    for line in open(path, encoding='utf-8', errors='replace'):
        line = line.strip()
        if not line or line[0].isalpha() or line[0] in '*#/':
            continue
        parts = line.replace(',', ' ').split()
        try:
            f.append(float(parts[0])); s.append(float(parts[1]))
        except (ValueError, IndexError):
            continue
    if len(f) < 2:
        raise ValueError('target curve needs >=2 (freq, level) rows: %s' % path)
    return np.interp(np.log10(freqs), np.log10(np.array(f)), np.array(s))


def _main():
    if len(sys.argv) < 3:
        print('usage: python measure.py {textcols|mdat} <file>'); sys.exit(1)
    cmd, path = sys.argv[1], sys.argv[2]
    if cmd == 'textcols':
        f, s, p = load_text_export(path)
        print('%d points, %.1f-%.0f Hz, SPL %.1f..%.1f dB, phase: %s'
              % (len(f), f[0], f[-1], s.min(), s.max(), 'yes' if p is not None else 'no'))
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
