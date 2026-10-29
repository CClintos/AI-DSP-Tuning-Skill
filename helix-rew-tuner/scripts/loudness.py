# loudness.py -- ISO 226:2003 equal-loudness contours, and what they say
# about voicing at the level you actually listen at.
#
# The ear loses bass faster than midrange as the level drops: a balance that
# sounds right at 85 phon sounds thin at 65. A target curve is voiced at some
# level; played quieter, its bass reads lighter by the difference between the
# two contours (relative to 1 kHz). This module computes that difference. It
# is a MODEL of an average listener, used only to propose a voicing option for
# a blind A/B -- never a correction, and never a reason to boost on its own.
#
# Table: ISO 226:2003, Table 1 (frequency, alpha_f, L_U, T_f), 20 Hz-12.5 kHz.
# Valid 20-90 phon (to 80 phon above 4 kHz); outside that range the contour is
# extrapolated and labelled so.
import numpy as np

ISO_F = np.array([20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630,
                  800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500],
                 dtype=float)
ISO_AF = np.array([0.532, 0.506, 0.480, 0.455, 0.432, 0.409, 0.387, 0.367, 0.349, 0.330, 0.315,
                   0.301, 0.288, 0.276, 0.267, 0.259, 0.253, 0.250, 0.246, 0.244, 0.243, 0.243,
                   0.243, 0.242, 0.242, 0.245, 0.254, 0.271, 0.301])
ISO_LU = np.array([-31.6, -27.2, -23.0, -19.1, -15.9, -13.0, -10.3, -8.1, -6.2, -4.5, -3.1, -2.0,
                   -1.1, -0.4, 0.0, 0.3, 0.5, 0.0, -2.7, -4.1, -1.0, 1.7, 2.5, 1.2, -2.1, -7.1,
                   -11.2, -10.7, -3.1])
ISO_TF = np.array([78.5, 68.7, 59.5, 51.1, 44.0, 37.5, 31.5, 26.5, 22.1, 17.9, 14.4, 11.4, 8.6,
                   6.2, 4.4, 3.0, 2.2, 2.4, 3.5, 1.7, -1.3, -4.2, -6.0, -5.4, -1.5, 6.0, 12.6,
                   13.9, 12.3])
VALID_PHON = (20.0, 90.0)


def contour_table(phon):
    """SPL (dB) of the `phon` equal-loudness contour at the 29 ISO frequencies."""
    phon = float(phon)
    af = 4.47e-3 * (10.0 ** (0.025 * phon) - 1.15) + \
        (0.4 * 10.0 ** ((ISO_TF + ISO_LU) / 10.0 - 9.0)) ** ISO_AF
    return 10.0 / ISO_AF * np.log10(af) - ISO_LU + 94.0


def _interp(freqs, values):
    f = np.clip(np.asarray(freqs, dtype=float), ISO_F[0], ISO_F[-1])
    return np.interp(np.log10(f), np.log10(ISO_F), values)


def contour_db(freqs, phon):
    """The contour on any grid, log-interpolated and held flat past 20 Hz / 12.5 kHz."""
    return _interp(freqs, contour_table(phon))


def threshold_db(freqs):
    """Threshold of hearing (T_f), dB SPL."""
    return _interp(freqs, ISO_TF)


def compensation_db(freqs, listening_phon, reference_phon):
    """How much louder each frequency must be, relative to 1 kHz, for a
    balance voiced at reference_phon to sound the same at listening_phon.
    Positive in the bass when listening quieter than the reference."""
    lis = contour_table(listening_phon) - listening_phon
    ref = contour_table(reference_phon) - reference_phon
    return _interp(freqs, lis - ref)


def in_valid_range(phon):
    return VALID_PHON[0] <= float(phon) <= VALID_PHON[1]
