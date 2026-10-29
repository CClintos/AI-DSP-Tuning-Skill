# Real REW captures (regression fixtures)

REW's own output from one car, used by `tests/test_real_captures.py` so the
readers are tested against real files, not only against what we believe REW
writes.

- `2026-07-14/`: eight RTA text exports from one MMM session (REW 5.40 beta
  127, UMIK-1 at 18 dB gain, 64k FFT, 1/24 octave). Unchanged: they hold no
  file paths or names. The front-left tweeter was exported at 1/48 smoothing
  and the others with none, which is one of the things the tests check.
- `2026-07-04 front left tweeter.mdat`: one RTA measurement saved by REW. The
  only personal string, the Windows user name in the cal-file path, was
  replaced byte for byte (same length, so the Java object stream stays valid).

`.gitattributes` marks this folder `-text` so line endings are never rewritten.
