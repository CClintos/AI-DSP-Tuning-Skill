# tunelib.py -- verified DSP + acoustic-analysis core for the Helix/REW auto-tuner skill.
# Pure functions (no file paths, no hardware I/O). Run  to execute
# the full synthetic self-test suite (should print ALL TESTS PASSED).
# Encodings verified on a Helix P SIX DSP MK2; other Helix models: round-trip-verify first.
# _tunefit.py — joint PEQ optimizer + minimum-phase classifier + audibility score.
# Companion to _devcalc.py (which stays the measurement/deviation workhorse).
# Added 2026-07-02 (Fable max pass). Everything here is self-tested by `python _tunefit.py`.
#
# WHY THIS EXISTS (the gap vs TuneEQ / REW's own EQ window):
#  - TuneEQ and REW fit bands GREEDILY, one at a time, to raw magnitude error.
#    Greedy = each band ignores how its skirts change the next band's problem.
#    fit_peq() fits all bands JOINTLY (scipy least_squares over the full cascade).
#  - Neither weights the error by audibility. audibility_score() ERB-smooths the
#    residual and weights by where the ear is sensitive, so the optimizer spends
#    its band budget where it is HEARD, not where the plot looks worst.
#  - Neither checks EQ-ability physics. REW's own doctrine (minimumphase.html):
#    "Anywhere the excess group delay plot is flat is a minimum phase region"
#    -> correctable. Sharp dips with wild excess-GD swings are non-minimum-phase
#    -> EQ cannot fix them. excess_gd_mask() computes that classifier from a
#    single-position export WITH PHASE (REW text export, 3 columns).

import numpy as np

FS = 96000.0                     # Helix internal rate (verified, P SIX MK2 manual)
LOGSTEP = 2 ** (1 / 96.0)        # REW 96 PPO

# --------------------------------------------------------------------------
# biquad + cascade (same RBJ math _devcalc.py uses, vector over freq axis)
def peaking_db(freqs, f0, Q, gain_db, fs=FS):
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / fs
    al = np.sin(w0) / (2 * Q)
    b0, b1, b2 = 1 + al * A, -2 * np.cos(w0), 1 - al * A
    a0, a1, a2 = 1 + al / A, -2 * np.cos(w0), 1 - al / A
    w = 2 * np.pi * freqs / fs
    z1, z2 = np.exp(-1j * w), np.exp(-2j * w)
    H = (b0 + b1 * z1 + b2 * z2) / (a0 + a1 * z1 + a2 * z2)
    return 20 * np.log10(np.abs(H))

def cascade_db(freqs, bands):
    out = np.zeros_like(freqs, dtype=float)
    for F, Q, G in bands:
        out += peaking_db(freqs, F, Q, G)
    return out

# --------------------------------------------------------------------------
# 1) MINIMUM-PHASE EXTRACTION + EXCESS GROUP DELAY  (REW doctrine, computable)
def minphase_from_mag(freqs, mag_db, n_fft=2 ** 16, fs=48000.0):
    """Min-phase (radians, on `freqs`) implied by a magnitude curve.
    Real-cepstrum method: resample |H| to a linear grid, fold the cepstrum,
    read back the phase. Standard DSP; assumes the magnitude IS the whole story
    (that's the definition of minimum phase).

    `fs` here is the MEASUREMENT sample rate, NOT the DSP's internal rate
    (module-level FS = 96 kHz). These are genuinely different quantities and
    the difference is deliberate: the analysis grid only has to span the
    measured axis, and a standard REW export tops out at 24 kHz = Nyquist for
    48 kHz. Do NOT "fix" this to FS -- that would extrapolate magnitude across
    24-48 kHz where no measurement exists.

    Raises if the axis extends past fs/2. Without that check the trailing
    np.interp silently CLAMPS above Nyquist and returns flat phase there,
    which excess_gd_mask would then read as a perfectly minimum-phase (i.e.
    "safe to EQ") region built on data that doesn't exist -- a silently wrong
    answer rather than a loud failure."""
    f_max = float(np.max(freqs))
    if f_max > fs / 2.0:
        raise ValueError(
            'measurement axis reaches %.0f Hz but fs=%.0f gives Nyquist %.0f Hz -- '
            'pass the MEASUREMENT sample rate explicitly (fs=2*f_max or higher). '
            'Note fs here is the measurement rate, not the DSP internal rate.'
            % (f_max, fs, fs / 2.0))
    lin_f = np.linspace(0, fs / 2, n_fft // 2 + 1)
    lo, hi = freqs.min(), freqs.max()
    lin_db = np.interp(np.clip(lin_f, lo, hi), freqs, mag_db)  # clamp ends flat
    log_mag = lin_db / 8.685889638             # dB -> ln|H|
    full = np.concatenate([log_mag, log_mag[-2:0:-1]])          # even spectrum
    cep = np.fft.ifft(full).real
    n = len(full)
    fold = np.zeros(n)
    fold[0] = cep[0]
    fold[1:n // 2] = 2 * cep[1:n // 2]
    fold[n // 2] = cep[n // 2]
    mp_full = np.fft.fft(fold)
    mp_phase_lin = np.imag(mp_full[:n_fft // 2 + 1])            # radians (min phase)
    return np.interp(freqs, lin_f, mp_phase_lin)

def excess_gd_mask(freqs, spl_db, phase_deg, flat_ms=1.0, smooth_oct=1 / 6.0,
                   measurement_fs=None):
    """The EQ-ability classifier. Inputs: single-position REW text export WITH
    phase (freq, SPL, phase columns). Returns (excess_gd_ms, eqable_mask).
    REW doctrine: flat excess GD = minimum phase = EQ WORKS THERE; wild excess-GD
    swings (usually at sharp dips) = non-minimum-phase = EQ CANNOT FIX. `flat_ms`
    = how far excess GD may deviate from its local median and still count flat.
    Note: an overall time-of-flight offset only adds a CONSTANT GD slope, which the
    local-median comparison ignores by construction.

    `measurement_fs` is the MEASUREMENT sample rate (not the DSP's FS). Left
    None it defaults to whatever comfortably spans the supplied axis, so an
    export reaching past 24 kHz no longer silently produces flat (fake
    minimum-phase) values above Nyquist -- see minphase_from_mag."""
    if measurement_fs is None:
        measurement_fs = max(48000.0, 2.2 * float(np.max(freqs)))
    ph = np.unwrap(np.deg2rad(phase_deg))
    mp = minphase_from_mag(freqs, spl_db, fs=measurement_fs)
    ex = ph - mp
    w = 2 * np.pi * freqs
    gd = -np.gradient(ex, w) * 1000.0            # excess group delay, ms
    # local median baseline (removes constant offset + slow trend)
    nb = max(3, int(round((1.0 / np.log10(LOGSTEP)) * np.log10(2 ** smooth_oct))))
    if nb % 2 == 0: nb += 1
    half = nb // 2
    base = np.array([np.median(gd[max(0, i - half):min(len(gd), i + half + 1)])
                     for i in range(len(gd))])
    wob = np.abs(gd - base)
    # wobble itself smoothed a touch so single-bin spikes don't flip the mask
    wob = np.convolve(wob, np.ones(5) / 5, mode='same')
    return gd, (wob <= flat_ms)

# --------------------------------------------------------------------------
# 2) AUDIBILITY-WEIGHTED SCORE (ERB smoothing + sensitivity weighting)
def erb_hz(fc):
    return 24.7 * (4.37 * fc / 1000.0 + 1.0)

def erb_smooth(freqs, y):
    dlog = np.log(LOGSTEP)
    out = np.empty_like(y)
    for i in range(len(y)):
        hb = max(1, int(round(np.log(1 + 0.5 * erb_hz(freqs[i]) / freqs[i]) / dlog)))
        out[i] = np.mean(y[max(0, i - hb):min(len(y), i + hb + 1)])
    return out

def audibility_weight(freqs):
    """Simple sensitivity weighting, PROVISIONAL (Toole/Olive tables still not
    primary-sourced): full weight 200 Hz-6 kHz (vocals/timbre/imaging band the
    ear is fussiest about + competition midrange), tapering to 0.5 by 40 Hz and
    0.4 by 16 kHz. Shapes priority only - it does not silence anything."""
    w = np.ones_like(freqs)
    lo = freqs < 200
    w[lo] = 0.5 + 0.5 * (np.log2(freqs[lo] / 40.0) / np.log2(200.0 / 40.0))
    hi = freqs > 6000
    w[hi] = 1.0 - 0.6 * (np.log2(freqs[hi] / 6000.0) / np.log2(16000.0 / 6000.0))
    return np.clip(w, 0.3, 1.0)

def audibility_score(freqs, dev_db, band=(60.0, 16000.0), mask=None, conf=None):
    """One number for 'how audibly wrong is this curve' (lower = better).
    ERB-smooth first (what the ear integrates), weight by sensitivity, RMS.
    `conf` is an optional 0..1 per-bin confidence array. Use it for spatial
    consistency / phase-validity weighting so uncertain bins cannot dominate
    the score or the parsimony gate."""
    sm = erb_smooth(freqs, dev_db)
    sel = (freqs >= band[0]) & (freqs <= band[1])
    if mask is not None:
        sel &= mask
    if not np.any(sel):
        return float('inf')
    w = audibility_weight(freqs)[sel]
    if conf is not None:
        w = w * np.clip(conf[sel], 0.0, 1.0)
    den = np.sum(w ** 2)
    if den <= 1e-12:
        return float('inf')
    return float(np.sqrt(np.sum((sm[sel] * w) ** 2) / den))

# --------------------------------------------------------------------------
# 3) JOINT PEQ FIT (the TuneEQ-beater)
def fit_peq(freqs, dev_db, fit_band, n_bands_max=5, mask=None, conf=None,
            g_lim=(-15.0, 3.0), q_lim=(0.5, 8.0), min_gain=1.0,
            improve_pct=6.0, boost_penalty=0.5, hf_q_penalty=0.4,
            hf_q_knee=4.0, transition_hz=1000.0, selection_tax_weight=0.25,
            null_boost_penalty=0.8, partner_target_db=None, partner_weight=0.0,
            partner_band=(700.0, 5000.0), verbose=False):
    """Jointly fit up to n_bands_max peaking bands so that dev+EQ -> 0 over
    fit_band, minimizing the ERB/audibility-weighted residual.

    Discipline built in (this is where it beats a raw curve-fitter):
      - mask=False bins are EXCLUDED from the error (nulls / non-min-phase /
        volatile comb regions never attract a filter);
      - conf (optional 0..1 per-freq confidence, e.g. from spatial_consistency)
        CONTINUOUSLY down-weights uncertain bins instead of a hard mask edge --
        the solver still "sees" them a little, but won't spend a band on a
        low-confidence wiggle;
      - "FILTER TAX" (beats TuneEQ's fill-every-hole habit): each proposed band
        pays a penalty for being a BOOST (boost_penalty x G) and for being a
        NARROW filter above the transition (hf_q_penalty x (Q-knee) when
        F>transition_hz) -- so the optimizer only boosts / goes high-Q-up-high
        when the audible payoff clearly outweighs the tax;
      - boosts capped at g_lim[1] (+3 default), cuts at -15 (hardware);
      - Q capped at 8 (craft ceiling), 0.5 floor (hardware);
      - PARSIMONY: bands are added one at a time and each must improve the
        weighted score by >= improve_pct %, else it is discarded and fitting
        stops -- no chasing sub-dB residuals with extra bands (TuneEQ trap);
      - selection_tax_weight adds a smaller version of the filter tax to the
        parsimony gate. The full tax still shapes fitting, but the gate should
        not reject a clearly useful cut just because it has moderate Q;
      - NULL-BOOST GUARD: mask=False bins are excluded from the fit error, but
        that alone is passive -- a band aimed at a nearby legitimate feature
        can still spill real gain into a masked null as a side effect, and
        the fitter would never notice. The selection gate now actively
        penalizes any positive (boost) contribution the candidate cascade
        makes inside masked-out bins (null_boost_penalty x mean boost there),
        closing that loophole instead of just declining to reward it;
      - bands with fitted |G| < min_gain dB are dropped at the end.
      - PARTNER MATCH (image stability, Smaart discipline: interchannel
        mismatch is more audible than absolute-curve error): pass
        partner_target_db = the OTHER channel's already-fitted post-EQ curve
        (dev_db + cascade_db(freqs, other_bands)) and partner_weight > 0 to
        additionally pull THIS channel's corrected curve toward matching it
        within partner_band (default 700 Hz-5 kHz, the image-critical range
        lr_match_report also uses). This can justify a band purely to close
        an L/R gap even when it barely moves this channel's own distance to
        target -- both the fit and the parsimony gate are partner-aware so
        such a band isn't rejected as "no improvement." See lr_match_report
        for the read-only diagnostic that tells you whether this is needed.

        IMPORTANT ASYMMETRY: closing a gap by matching the WORSE side means
        pulling the better-matching channel away from target on purpose --
        trading absolute tonal accuracy for image stability. That's often
        the right trade (imaging is more audible than a small absolute
        error), but it's a real trade, not a free win, so it isn't free in
        the math either: partner_weight competes against the existing boost
        tax (boost_penalty/selection_tax_weight), which correctly resists a
        boost that helps nothing but matching. A weight around 1.0 may not
        be enough to win that fight if the needed move is a boost -- raise
        it (2-4+) once you've decided the image-stability payoff is worth
        it; don't just crank it by default. Prefer improving the worse
        channel directly when that's possible instead of degrading the
        better one to match it.

    Returns (bands, report) - bands as [(F, Q, G), ...] rounded to hardware
    steps (0.25 dB gain), report dict with before/after scores (plus
    partner_mismatch_before/after when partner matching is active).
    """
    from scipy.optimize import least_squares

    sel = (freqs >= fit_band[0]) & (freqs <= fit_band[1])
    if mask is not None:
        sel &= mask
    fsel = freqs[sel]
    w = audibility_weight(fsel)
    if conf is not None:
        w = w * np.clip(conf[sel], 0.0, 1.0)     # continuous confidence down-weight

    psel = pw = ptarget = None
    if partner_target_db is not None and partner_weight > 0:
        psel = ((freqs >= max(fit_band[0], partner_band[0])) &
                (freqs <= min(fit_band[1], partner_band[1])))
        if mask is not None:
            psel = psel & mask
        if np.any(psel):
            pw = audibility_weight(freqs[psel])
            ptarget = np.asarray(partner_target_db, dtype=float)[psel]
        else:
            psel = None

    def partner_mismatch(bands):
        if psel is None:
            return 0.0
        own = dev_db[psel] + cascade_db(freqs[psel], bands)
        return float(wrms(np.abs(own - ptarget), pw))

    def penalties(bands):
        # CONSTANT length (2 terms/band) so least_squares' finite-diff Jacobian
        # never sees the vector change size when a band's F is perturbed.
        p = []
        for F, Q, G in bands:
            p.append(boost_penalty * max(0.0, G))                    # boost tax
            hf = 1.0 / (1.0 + np.exp(-(np.log2(F / transition_hz)) * 6.0))  # smooth gate ~transition
            p.append(hf_q_penalty * hf * max(0.0, Q - hf_q_knee))    # narrow-HF tax
        return np.array(p) if p else np.zeros(0)

    def resid(params):
        bands = [(10 ** params[3 * i], params[3 * i + 1], params[3 * i + 2])
                 for i in range(len(params) // 3)]
        r = (dev_db[sel] + cascade_db(fsel, bands)) * w
        parts = [r, penalties(bands)]
        if psel is not None:
            own_p = dev_db[psel] + cascade_db(freqs[psel], bands)
            parts.append(partner_weight * pw * (own_p - ptarget))
        return np.concatenate(parts)

    def score_of(params):
        bands = [(10 ** params[3 * i], params[3 * i + 1], params[3 * i + 2])
                 for i in range(len(params) // 3)]
        full = dev_db + cascade_db(freqs, bands)
        return audibility_score(freqs, full, band=fit_band, mask=mask, conf=conf)

    def combined_score_of(params):
        """score_of plus the partner-match penalty, when active. This (not
        score_of) is what drives band-count decisions -- a band that only
        closes an L/R gap should count as progress even if it barely moves
        this channel's own distance to target. score_of/audibility_score
        stay pure for the reported 'score_after' (still means distance-to-
        target, not distance-to-partner)."""
        bands = [(10 ** params[3 * i], params[3 * i + 1], params[3 * i + 2])
                 for i in range(len(params) // 3)]
        return score_of(params) + partner_weight * partner_mismatch(bands)

    def selection_score_of(params):
        """Score used by the parsimony gate.
        Raw audibility score decides whether the curve improved; the tax decides
        whether a boost / narrow-HF filter earned the right to exist; the
        null-boost guard decides whether it's quietly spilling gain into a
        masked-out region (a null/non-min-phase/low-confidence bin) it was
        never supposed to touch."""
        bands = [(10 ** params[3 * i], params[3 * i + 1], params[3 * i + 2])
                 for i in range(len(params) // 3)]
        p = penalties(bands)
        tax = float(np.sqrt(np.mean(p ** 2))) if len(p) else 0.0
        null_cost = 0.0
        if mask is not None and null_boost_penalty > 0:
            excluded = ~mask
            if np.any(excluded):
                spill = cascade_db(freqs, bands)[excluded]
                null_cost = null_boost_penalty * float(np.mean(np.maximum(spill, 0.0)))
        return combined_score_of(params) + selection_tax_weight * tax + null_cost

    base_score = audibility_score(freqs, dev_db, band=fit_band, mask=mask, conf=conf)
    base_partner = partner_mismatch([])
    base_combined = base_score + partner_weight * base_partner
    params = np.array([])
    lo_f, hi_f = np.log10(fit_band[0] * 1.02), np.log10(fit_band[1] * 0.98)
    cur_score = base_combined
    cur_select_score = base_combined

    for k in range(n_bands_max):
        # seed the next band at the biggest remaining weighted, smoothed bump.
        # Blends in partner mismatch (when active) so a channel that's
        # already flat vs target but diverging from its partner still gets a
        # seed frequency, instead of the empty-residual break below firing
        # before partner matching ever gets a chance.
        bands_now = [(10 ** params[3 * i], params[3 * i + 1], params[3 * i + 2])
                     for i in range(len(params) // 3)]
        raw_now = dev_db + cascade_db(freqs, bands_now)
        seed_basis = raw_now.copy()
        if psel is not None:
            seed_basis[psel] = raw_now[psel] + partner_weight * (raw_now[psel] - ptarget)
        res_now = erb_smooth(freqs, seed_basis)
        res_w = np.where(sel, np.abs(res_now) * audibility_weight(freqs), 0)
        if conf is not None:
            res_w *= np.clip(conf, 0.0, 1.0)
        i0 = int(np.argmax(res_w))
        if res_w[i0] <= 0:
            break
        seed_F, seed_G = freqs[i0], float(np.clip(-res_now[i0], g_lim[0], g_lim[1]))
        trial = np.concatenate([params, [np.log10(seed_F), 1.5, seed_G]])
        nb = len(trial) // 3
        lb = np.tile([lo_f, q_lim[0], g_lim[0]], nb)
        ub = np.tile([hi_f, q_lim[1], g_lim[1]], nb)
        fit = least_squares(resid, np.clip(trial, lb, ub), bounds=(lb, ub),
                            method='trf', max_nfev=400)
        new_score = combined_score_of(fit.x)
        new_select_score = selection_score_of(fit.x)
        raw_gain_pct = 100.0 * (cur_score - new_score) / max(cur_score, 1e-9)
        select_gain_pct = 100.0 * (cur_select_score - new_select_score) / max(cur_select_score, 1e-9)
        if verbose:
            print('  band %d: score %.3f -> %.3f (%.1f%%) | selection %.3f -> %.3f (%.1f%%)' %
                  (nb, cur_score, new_score, raw_gain_pct, cur_select_score, new_select_score, select_gain_pct))
        if raw_gain_pct < improve_pct or select_gain_pct < improve_pct:
            break                                    # parsimony gate
        params, cur_score, cur_select_score = fit.x, new_score, new_select_score

    bands = []
    for i in range(len(params) // 3):
        F = round(float(10 ** params[3 * i]), 1)
        Q = round(float(params[3 * i + 1]), 2)
        G = round(float(params[3 * i + 2]) * 4) / 4.0       # 0.25 dB steps
        if abs(G) >= min_gain:
            bands.append((F, Q, G))
    final = audibility_score(freqs, dev_db + cascade_db(freqs, bands),
                             band=fit_band, mask=mask, conf=conf)
    final_tax = selection_score_of(np.array(
        sum(([np.log10(F), Q, G] for F, Q, G in bands), []), dtype=float))
    report = {'score_before': round(base_score, 3),
              'score_after': round(final, 3),
              'selection_score_before': round(base_score, 3),
              'selection_score_after': round(final_tax, 3),
              'bands_used': len(bands)}
    if psel is not None:
        report['partner_mismatch_before'] = round(base_partner, 3)
        report['partner_mismatch_after'] = round(partner_mismatch(bands), 3)
    return bands, report

# --------------------------------------------------------------------------
# 3c) INTERFERENCE / SUMMATION AUDIT — added 2026-07-03 (Fable pass).
# Detects L/R (or any driver-pair) destructive interference from THREE PLAIN
# MAGNITUDE captures at one fixed mic spot: solo_a, solo_b, and the pair
# playing together. NO acoustic timing reference / phase capture needed —
# this is the cheap alternative to a full phase-valid measurement for simply
# DETECTING a cancellation (though fine-tuning an APF's F/Q still benefits
# from live sweeping by ear/RTA, §3 "manual APF protocol").
# This is how the ~415 Hz mid-pair null was finally explained: each mid solo
# was healthy there, but the "MidBass Together" trace read ~3 dB BELOW even
# the incoherent sum -- proof the two sides are partially cancelling, not a
# modal/boundary null. That reclassified it from "leave forever" to
# "all-pass candidate."
def interference_audit(freqs, solo_a_db, solo_b_db, together_db, flag_db=2.0,
                       smooth_oct=1 / 12.0):
    """psum = incoherent (power) sum: the floor you'd get if A and B were
    totally uncorrelated. csum = fully coherent (voltage) sum: the ceiling if
    perfectly in phase. If `together` reads BELOW psum, the pair is destructively
    interfering at that frequency (a phase-relative problem, not a level or
    EQ-able magnitude problem). Returns (psum_db, csum_db, interference_db,
    flagged_mask). interference_db = together - psum; large negative = bad."""
    psum = 10 * np.log10(10 ** (solo_a_db / 10.0) + 10 ** (solo_b_db / 10.0))
    csum = 20 * np.log10(10 ** (solo_a_db / 20.0) + 10 ** (solo_b_db / 20.0))
    interference_db = together_db - psum
    flag_basis = octave_smooth_log(freqs, interference_db, smooth_oct) if smooth_oct else interference_db
    return psum, csum, interference_db, (flag_basis < -flag_db)

# --------------------------------------------------------------------------
# CROSSOVER-SPECIFIC CONFIDENCE -- bundles existing band-aware checks into one
# report for a SPECIFIC crossover region (e.g. sub/midbass 50-120Hz, mid/
# tweeter 1.8-4.5kHz) instead of inspecting a whole trace. No new math -- this
# composes prediction_confidence, interference_audit, and
# phase_linearity_residual, which were all already band-parameterized, so the
# same result was always obtainable by hand. This just makes it one call
# instead of three, so a crossover check is consistent every time it's run.
def crossover_confidence(freqs, solo_a, solo_b, together_db, band):
    """solo_a/solo_b: COMPLEX solo responses (magnitude+phase) for the two
    drivers either side of this crossover. together_db: measured together
    SPL. band: the crossover region only, e.g. (50.0, 120.0) -- do not pass
    the whole trace, that defeats the point."""
    pconf = prediction_confidence(freqs, solo_a, solo_b, together_db, band)
    sel = (freqs >= band[0]) & (freqs <= band[1])
    a_db = 20 * np.log10(np.abs(solo_a) + 1e-12)
    b_db = 20 * np.log10(np.abs(solo_b) + 1e-12)
    _, _, _, flagged = interference_audit(freqs, a_db, b_db, together_db)
    cancelling = bool(np.any(flagged[sel]))
    ph_a = phase_linearity_residual(freqs, np.rad2deg(np.angle(solo_a)), band)
    ph_b = phase_linearity_residual(freqs, np.rad2deg(np.angle(solo_b)), band)
    both_phase_ok = ph_a['trustworthy_for_timing'] and ph_b['trustworthy_for_timing']
    usable = pconf['usable_for_phase_decisions'] and both_phase_ok
    return {'band': band, 'prediction_confidence': pconf,
            'destructive_interference_in_band': cancelling,
            'phase_reliability_a': ph_a, 'phase_reliability_b': ph_b,
            'usable_for_crossover_decisions': usable}

# --------------------------------------------------------------------------
# L/R IMAGE-STABILITY REPORT -- Smaart practice: interchannel mismatch is more
# audible than absolute-curve error, because a center image (vocals, kick,
# anything panned center) is built from L and R summing coherently. Wherever
# the two sides diverge in level, the image pulls toward the louder side AT
# THAT FREQUENCY -- heard as smear/wander even when each channel individually
# looks close to target. perceptual_score()'s 'stereo' term already scores
# this as one scalar; this exposes WHERE and BY HOW MUCH so a fix can be
# targeted instead of guessed at. Read-only diagnostic -- see fit_peq's
# partner_target_db/partner_weight below for the matching bias itself.
def lr_match_report(freqs, left_db, right_db, band=(300.0, 6000.0), flag_db=1.5):
    """left_db/right_db: any two curves on the same freq grid (raw measured,
    or post-EQ-predicted dev+cascade) -- whichever comparison you want a
    verdict on. band: image-critical range to judge (vocals/timbre); default
    matches perceptual_score's stereo term. flag_db: per-ERB-band mismatch
    that counts as audible (~1.5 dB is a reasonable "you'd notice" floor).

    Returns per-region flags (extent, peak mismatch, louder side) plus an
    overall wrms mismatch score. Does not decide anything -- surfaces it."""
    freqs = np.asarray(freqs, dtype=float)
    diff = erb_smooth(freqs, np.asarray(left_db, dtype=float) - np.asarray(right_db, dtype=float))
    sel = (freqs >= band[0]) & (freqs <= band[1])
    flagged = sel & (np.abs(diff) >= flag_db)

    regions = []
    in_run = False
    start = 0
    for i in range(len(freqs)):
        if flagged[i] and not in_run:
            start, in_run = i, True
        if in_run and (not flagged[i] or i == len(freqs) - 1):
            end = i if flagged[i] else i - 1
            seg = slice(start, end + 1)
            j = start + int(np.argmax(np.abs(diff[seg])))
            regions.append({'f_lo': round(float(freqs[start]), 1),
                            'f_hi': round(float(freqs[end]), 1),
                            'peak_hz': round(float(freqs[j]), 1),
                            'peak_delta_db': round(float(diff[j]), 2),
                            'louder_side': 'left' if diff[j] > 0 else 'right'})
            in_run = False

    w = band_weight(freqs, band[0], band[1])
    overall_db = wrms(np.abs(diff)[sel], w[sel]) if np.any(sel) else 0.0
    return {'regions': regions, 'overall_mismatch_db': round(float(overall_db), 2),
            'stable': len(regions) == 0}

# --------------------------------------------------------------------------
# SPECIAL-FILTER XML WRITERS -- encodings VERIFIED by controlled export-diffs.
# COMPLETE T-code map (as of 2026-07-03 "Test .afpx" diff, which CORRECTED the
# earlier "T=20 = shelf" inference):
#   T=1  free slot          T=17 parametric EQ
#   T=15 LP xover           T=16 HP xover
#   T=3  LOW SHELF   (band 1 / dF=25 only;  G!=0 active)   [VERIFIED 2026-07-03]
#   T=4  HIGH SHELF  (band 30 / dF=20000 only; G!=0 active)[VERIFIED 2026-07-03]
#   T=19 1st-order ALL-PASS (G=0, Q written as 1 placeholder; MIDDLE slots OK)
#        [CONFIRMED 2026-07-03: PC-Tool screenshot, Band 20 middle slot,
#         "Q: N/A for 1st order", "1. Order" active]
#   T=20 2nd-order ALL-PASS (G=0, Q meaningful)              [VERIFIED 2026-07-02]
#        Q range CORRECTED 2026-07-11: earlier "0.5-2 hardware ceiling" claim was
#        WRONG -- PC-Tool screenshot shows Q=9 accepted and displayed (Band 14,
#        420 Hz, 2nd order). Not yet export-diff round-trip verified above Q=2,
#        but do NOT block or warn a user off high Q as "illegal" -- it isn't.
#        High Q is often the CORRECT choice for a narrow null: it confines the
#        phase rotation to the target frequency and avoids the collateral
#        cancellation a broad (low-Q) APF creates in neighbouring bands. The
#        real cost of high Q is GROUP DELAY / transient ringing, not legality --
#        see interaural_group_delay_ms() below and methodology.md's All-pass
#        cookbook.
# The I attribute (present on EVERY <Fil>) = the INVERT flag, 0/1 -- VERIFIED
# 2026-07-03 by export-diff: pressing 'invert' on the T=19 APF flipped exactly
# I="0" -> I="1" and nothing else in the whole file. (It was previously
# misread as an 'index'.) All writers take invert=True to set it.
# Notes: middle-slot APFs are real (T=19 seen at dF=2000) -> APFs do NOT compete
# with shelves for the end slots. Old tunes' parked T=20 bands were parked
# ALL-PASSES, not shelves (their odd Q>2 values = stale XML from prior PEQ use).
# Switching band 1/30 to a shelf CONSUMES whatever PEQ lived in that slot --
# relocate ("defrag") the squatter PEQ to a free middle slot FIRST.
def allpass_fil_str(F, Q, FN, dF='20000', invert=False):
    """2nd-order all-pass (T=20). G always "0" -- that's what makes it an APF.
    Middle slots allowed (verified via the T=19 sighting + AF docs), but default
    stays the end slot for consistency with the verified example.

    Q range: PC-Tool accepts at least up to 9 (screenshot-verified 2026-07-11,
    corrects the earlier wrong "0.5-2 hardware ceiling" claim). This writer
    does not cap Q -- only checks it's a sane positive number -- because a
    hard ceiling here would silently block a legitimate high-Q correction.
    The real tradeoff of high Q is group delay / ringing, which the CALLER
    should evaluate with group_delay_ms_from_H / interaural_group_delay_ms,
    not a magnitude/legality check on Q itself."""
    assert Q > 0.0, 'APF Q must be positive'
    return '<Fil G="0" FN="%s" F="%.2f" T="20" I="%s" dF="%s" Q="%s"/>' % (FN, F, '1' if invert else '0', dF, Q)

def allpass1_fil_str(F, FN, dF, invert=False):
    """1st-order all-pass (T=19, -90 deg at corner, no Q -- written as 1).
    CONFIRMED 1st-order (PC-Tool screenshot: Q shows "N/A for 1st order" with
    "1. Order" active on this exact band). Middle slots verified fine."""
    return '<Fil Q="1" G="0" F="%.2f" FN="%s" I="%s" T="19" dF="%s"/>' % (F, FN, '1' if invert else '0', dF)

def shelf_fil_str(kind, F, Q, G, FN, invert=False):
    """Low shelf (T=3, band 1/dF=25) or high shelf (T=4, band 30/dF=20000).
    VERIFIED encodings from the 2026-07-03 export: LS -2.25@4980.25 Q1 -> T=3;
    HS +0.25@5400 Q0.5 -> T=4. Q 0.1-2 IS the slope (no separate S param).
    G in 0.25 dB steps, within [-15,+6]."""
    assert kind in ('low', 'high')
    assert 0.1 <= Q <= 2.0, 'shelf Q must be 0.1-2 (AF spec)'
    assert -15.0 <= G <= 6.0, 'shelf gain out of Helix range'
    T, dF = ('3', '25') if kind == 'low' else ('4', '20000')
    return '<Fil Q="%s" G="%s" F="%.2f" FN="%s" I="%s" T="%s" dF="%s"/>' % (Q, G, F, FN, '1' if invert else '0', T, dF)

def fil_attrs(tag):
    import re as _re
    return dict(_re.findall(r'([A-Za-z]+)="([^"]*)"', tag))

def delays_semantically_equal(xml_a, xml_b):
    """PC-Tool round-trips REORDER attributes inside <T .../> tags (verified
    2026-07-03: PM= T= P= became T= P= PM=, same values). So for any file that
    passed through PC-Tool, compare delay tags as attr DICTS, not bytes. For
    our own Python writes the byte check is still fine (we never reorder)."""
    import re as _re
    ta = [fil_attrs(t) for t in _re.findall(r'<T [^>]*/>', xml_a)]
    tb = [fil_attrs(t) for t in _re.findall(r'<T [^>]*/>', xml_b)]
    return ta == tb

# --------------------------------------------------------------------------
# 4) HEADROOM REPORT (mandatory output on every tune — clipping guard)
def headroom_report(freqs, bands, xover_lo=None, xover_hi=None):
    """Given a channel's full PEQ set, report the worst-case positive gain the
    EQ cascade produces (that's what eats digital headroom / clips). Every tune
    must print this per channel. `xover_*` optionally bounds the summed-boost
    check to the driver's passband. Returns a dict.

    IMPORTANT -- `clip_risk` here sees ONLY the PEQ stage, so it is often a
    FALSE ALARM on a well-set-up tune. It does not know the channel's OUTPUT
    TRIM, which usually already offsets the boost. VERIFIED on a real file
    (2026-07-14): a mid channel flagged clip_risk=True for a +2.7 dB cascade
    peak while its output level sat at -2.75 dB, so net at the DAC was ~0 dB
    and nothing was actually clipping. **Before reporting a clip risk to the
    user, read the channel's actual output level (`afpx.read_output_levels`)
    and compare** -- report the NET figure, not the PEQ-only one. If a real
    net risk remains, `recommended_trim_db` is the number to apply, via
    `afpx.write_output_trim` (attenuation-only by construction) under the same
    confirm-then-verify rule as any other write."""
    g = cascade_db(freqs, bands)
    sel = np.ones_like(freqs, dtype=bool)
    if xover_lo is not None: sel &= freqs >= xover_lo
    if xover_hi is not None: sel &= freqs <= xover_hi
    peak_gain = float(np.max(g[sel])) if np.any(sel) else 0.0
    fpk = float(freqs[sel][np.argmax(g[sel])]) if np.any(sel) else 0.0
    largest_boost = max([G for _, _, G in bands], default=0.0)
    return {'peak_cascade_gain_db': round(peak_gain, 2),
            'peak_gain_freq': round(fpk, 0),
            'largest_single_boost_db': round(largest_boost, 2),
            'clip_risk': peak_gain > 0.0,
            'recommended_trim_db': round(-peak_gain, 2) if peak_gain > 0 else 0.0}

# ==========================================================================
# SELF-TESTS + REAL-DATA VALIDATION

def weighted_median(values, weights=None):
    values = np.asarray(values, dtype=float)
    if weights is None:
        return float(np.median(values))
    weights = np.asarray(weights, dtype=float)
    ok = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not np.any(ok):
        return float(np.median(values[np.isfinite(values)]))
    values, weights = values[ok], weights[ok]
    order = np.argsort(values)
    values, weights = values[order], weights[order]
    cdf = np.cumsum(weights)
    return float(values[np.searchsorted(cdf, 0.5 * cdf[-1])])

def target_anchor_offset(freqs, measured_db, target_db, confidence=None,
                         anchor_bands=((300.0, 3000.0), (120.0, 1000.0), (1000.0, 6000.0)),
                         min_bins=12):
    """Wide, confidence-weighted median target anchor with fallbacks.

    Assumes SHAPE is level-independent -- anchor the overall level, then
    compare shape. That assumption breaks if the playback chain has a
    loudness-contour enhancement active (e.g. Windows "Loudness
    Equalization"): those reshape frequency response as a function of
    volume, so two captures at different levels aren't just level-shifted
    versions of each other anymore. Confirm no such enhancement is active
    before anchoring across measurements taken at different playback
    levels (see methodology.md's "Measurement method selection" section)."""
    freqs = np.asarray(freqs, dtype=float)
    dev = np.asarray(measured_db, dtype=float) - np.asarray(target_db, dtype=float)
    if confidence is None:
        confidence = np.ones_like(freqs)
    confidence = np.clip(np.asarray(confidence, dtype=float), 0.0, 1.0)
    for lo, hi in anchor_bands:
        sel = (freqs >= lo) & (freqs <= hi) & (confidence > 0.3) & np.isfinite(dev)
        if np.count_nonzero(sel) >= min_bins:
            return weighted_median(dev[sel], confidence[sel])
    sel = np.isfinite(dev)
    return weighted_median(dev[sel], confidence[sel])

# --------------------------------------------------------------------------
# VOICING -- the single most audible tuning layer (overall tonal balance),
# expressed as the four knobs people actually voice by rather than as
# individual filters. voice_target() shapes the GOAL; the measurement-driven
# EQ engine (fit_peq) still does the correcting, so voicing composes cleanly
# with everything downstream -- you voice the target, then match to it.
# measure_tilt() is the diagnostic half: where the measured (or target) curve
# actually sits, in plain language, so you can decide which way to nudge.
def voice_target(freqs, base_target_db, tilt_db_per_oct=0.0,
                 bass_shelf_db=0.0, bass_shelf_hz=100.0,
                 presence_db=0.0, presence_hz=3000.0, presence_width_oct=0.8,
                 air_db=0.0, air_hz=9000.0, pivot_hz=1000.0, shelf_slope=1.4):
    """Apply broad VOICING adjustments on top of a base target curve. Returns a
    new target array; feed it to fit_peq exactly like any other target. All
    knobs default to 0 (= base curve unchanged). This shapes the target only --
    it does NOT add filters directly; the EQ engine still corrects the
    measurement toward this voiced goal.

    Knobs (mapped to how listeners actually describe sound):
      tilt_db_per_oct : overall slope, pivoting at pivot_hz (~1 kHz, so the
                        midrange level is preserved). NEGATIVE = warmer (highs
                        quieter relative to mids). See measure_tilt for the
                        typical good-in-car range; a studio-flat (~0) target
                        tends to sound bright/thin in a cabin.
      bass_shelf_db   : low-shelf lift/cut below bass_shelf_hz. "More weight."
      presence_db     : gentle broad bell at presence_hz (~3 kHz), width in
                        octaves. "More forward" (+) / "more laid back" (-).
      air_db          : high-shelf above air_hz (~9 kHz). "More air" / tame top.
    """
    f = np.asarray(freqs, float)
    out = np.asarray(base_target_db, float).copy()
    out = out + tilt_db_per_oct * np.log2(f / pivot_hz)
    if bass_shelf_db:
        out = out + bass_shelf_db * 0.5 * (1.0 - np.tanh(np.log2(f / bass_shelf_hz) * shelf_slope))
    if air_db:
        out = out + air_db * 0.5 * (1.0 + np.tanh(np.log2(f / air_hz) * shelf_slope))
    if presence_db:
        out = out + presence_db * np.exp(-0.5 * (np.log2(f / presence_hz) / presence_width_oct) ** 2)
    return out


def measure_tilt(freqs, spl_db, band=(120.0, 10000.0), good_lo=-1.0, good_hi=-0.8):
    """Fit the broadband tonal TILT (dB/octave) of a curve -- the macro voicing
    metric. Heavily smooths first (so resonances don't skew the slope), then
    does an audibility-weighted linear fit of level vs log2(freq) over `band`.

    Returns the slope plus a plain-language read against the typical good-in-car
    range. Rule-of-thumb consensus (NOT gospel -- bounds are tunable): a car
    wants roughly -0.8..-1.0 dB/oct of downward tilt, more than a studio,
    because near-field reflections and an off-axis seat otherwise leave it
    sounding bright and thin. Use this on the measured System Sum to see where
    you are, and on a candidate voiced target to see where you're aiming."""
    f = np.asarray(freqs, float)
    y = erb_smooth(f, np.asarray(spl_db, float))
    sel = (f >= band[0]) & (f <= band[1])
    if np.count_nonzero(sel) < 4:
        raise ValueError('band does not overlap enough of the axis')
    x = np.log2(f[sel])
    w = audibility_weight(f[sel])
    W = np.sum(w)
    xm, ym = np.sum(w * x) / W, np.sum(w * y[sel]) / W
    var = np.sum(w * (x - xm) ** 2)
    slope = float(np.sum(w * (x - xm) * (y[sel] - ym)) / var) if var > 1e-12 else 0.0
    if slope > good_hi:
        read = 'brighter/thinner than typical in-car -- consider MORE downward tilt (more negative)'
    elif slope < good_lo:
        read = 'darker/duller than typical in-car -- consider LESS downward tilt'
    else:
        read = 'within the typical good in-car tilt range'
    return {'tilt_db_per_oct': round(slope, 2),
            'good_incar_range': (good_lo, good_hi), 'read': read}

def allpass_H(freqs, f0, Q=0.7, order=2, fs=FS):
    """Digital all-pass response used by Helix-style filters.
    order=2 is the verified AFPX-writeable APF. order=1 is kept for modelling
    and live experiments, but do not write it unless the target hardware export
    has been verified."""
    w0 = 2 * np.pi * f0 / fs
    w = 2 * np.pi * freqs / fs
    z1 = np.exp(-1j * w)
    if order == 1:
        t = np.tan(w0 / 2.0)
        a = (t - 1.0) / (t + 1.0)
        return (a + z1) / (1.0 + a * z1)
    if order != 2:
        raise ValueError('order must be 1 or 2')
    al = np.sin(w0) / (2.0 * Q)
    b0, b1, b2 = 1.0 - al, -2.0 * np.cos(w0), 1.0 + al
    a0, a1, a2 = 1.0 + al, -2.0 * np.cos(w0), 1.0 - al
    z2 = np.exp(-2j * w)
    return (b0 + b1 * z1 + b2 * z2) / (a0 + a1 * z1 + a2 * z2)

def allpass_H_inv(freqs, f0, Q=0.7, order=2, fs=FS):
    """PC-Tool's Allpass 'invert' button, simulated: multiplying an all-pass by
    -1 is still an all-pass (|H|=1) but with 180 deg added at ALL frequencies.
    Mathematically identical to (channel polarity flip) + (normal APF) -- just
    applied inside the EQ block, so the TA/polarity page stays untouched.
    USE WHEN: live-dialing an APF and the trough DEEPENS for every F/Q you try
    -- the rotation direction is wrong; invert flips the branch relationship.
    XML encoding VERIFIED 2026-07-03: the I attribute (I="1" = inverted) --
    the export-diff showed exactly I 0->1 and nothing else."""
    return -allpass_H(freqs, f0, Q, order, fs)

def group_delay_ms_from_H(freqs, H):
    ph = np.unwrap(np.angle(H))
    w = 2 * np.pi * freqs
    return -np.gradient(ph, w) * 1000.0

def interaural_group_delay_ms(freqs, H_left=None, H_right=None):
    """The imaging-risk metric for a proposed L/R APF pair -- added 2026-07-11
    after a real split-side candidate (APF on FL AND a different APF on FR)
    turned out to have a LARGER interaural group-delay spike (~17 ms) than a
    single APF on one side alone (~7 ms), despite each individual filter
    looking gentler in isolation. Per-filter group_delay_ms_from_H does not
    catch this -- it only sees one branch at a time. Pass None for a branch
    with no added filter (treated as flat/unity). Returns the L-R DIFFERENCE
    in group delay vs frequency (ms); its peak magnitude near the correction
    frequency/frequencies is what predicts image smearing risk -- compare
    candidates on THIS number, not on individual filter Q. A split-side
    (one APF per side) is not automatically gentler than stacking multiple
    APFs on one side -- check both shapes with this function before assuming."""
    HL = H_left if H_left is not None else np.ones_like(freqs, dtype=complex)
    HR = H_right if H_right is not None else np.ones_like(freqs, dtype=complex)
    ph_L = np.unwrap(np.angle(HL))
    ph_R = np.unwrap(np.angle(HR))
    w = 2 * np.pi * freqs
    gd_L = -np.gradient(ph_L, w) * 1000.0
    gd_R = -np.gradient(ph_R, w) * 1000.0
    return gd_L - gd_R

def optimize_allpass(freqs, driver_a, driver_b, search_band, apply_to='A',
                     order=2, f_steps=96, q_steps=24, q_lim=(0.5, 8.0),
                     damage_band=(60.0, 16000.0), damage_free_db=0.5,
                     damage_penalty=1.0, gd_penalty=0.0, max_gd_ms=2.0):
    """Grid-search a 2nd-order APF for a driver-pair sum.

    Inputs are complex solo-driver responses with shared time zero. The score is
    the weighted gap from the coherent-sum ceiling inside `search_band`, plus a
    penalty for making other audible regions worse than the no-APF sum.

    q_lim defaults to (0.5, 8.0) -- widened 2026-07-11, high Q is legal (see
    helix_hardware.md) and often the right answer for a narrow null.

    This searches ONE branch (mid<->tweeter or sub<->mid) in isolation. If you
    are choosing a filter for the LEFT side and a separate filter for the RIGHT
    side of the same crossover (a "split" configuration, different F/Q per
    side), running this twice independently does NOT tell you the imaging cost
    of the combined result -- the L-R difference is a property of the pair, not
    of either filter alone. After picking candidates for both sides, run
    `interaural_group_delay_ms(freqs, H_left, H_right)` on the actual combined
    pair before treating it as safe; a split configuration is not automatically
    gentler than concentrating correction on one side (see methodology.md).

    This is a candidate finder, not a blind finalizer: verify the chosen APF by
    re-measuring the acoustic sum after loading it.
    """
    sel = (freqs >= search_band[0]) & (freqs <= search_band[1])
    dmg_sel = (freqs >= damage_band[0]) & (freqs <= damage_band[1])
    if not np.any(sel):
        raise ValueError('search_band does not overlap the frequency axis')

    sum0 = 20 * np.log10(np.abs(driver_a + driver_b) + 1e-12)
    coherent = 20 * np.log10(np.abs(driver_a) + np.abs(driver_b) + 1e-12)

    def wrms(y, m):
        w = audibility_weight(freqs[m])
        den = np.sum(w ** 2)
        return float(np.sqrt(np.sum((y[m] * w) ** 2) / den)) if den > 1e-12 else float('inf')

    base_gap = np.maximum(coherent - sum0, 0.0)
    base_score = wrms(base_gap, sel)
    f_grid = np.geomspace(search_band[0], search_band[1], f_steps)
    q_grid = np.linspace(q_lim[0], q_lim[1], q_steps)

    best = None
    for F in f_grid:
        for Q in q_grid:
            H = allpass_H(freqs, F, Q, order=order)
            if apply_to.upper() == 'A':
                sdb = 20 * np.log10(np.abs(driver_a * H + driver_b) + 1e-12)
            elif apply_to.upper() == 'B':
                sdb = 20 * np.log10(np.abs(driver_a + driver_b * H) + 1e-12)
            else:
                raise ValueError("apply_to must be 'A' or 'B'")
            gap = np.maximum(coherent - sdb, 0.0)
            damage = np.maximum(sum0 - sdb - damage_free_db, 0.0)
            gd = group_delay_ms_from_H(freqs, H)
            gd_excess = max(0.0, float(np.max(gd[sel])) - max_gd_ms)
            score = wrms(gap, sel) + damage_penalty * wrms(damage, dmg_sel) + gd_penalty * gd_excess
            if best is None or score < best['selection_score_after']:
                iF = int(np.argmin(np.abs(freqs - F)))
                best = {'F': round(float(F), 1),
                        'Q': round(float(Q), 2),
                        'order': int(order),
                        'apply_to': apply_to.upper(),
                        'score_before': round(base_score, 3),
                        'selection_score_after': round(float(score), 3),
                        'gap_score_after': round(wrms(gap, sel), 3),
                        'lift_at_F_db': round(float(sdb[iF] - sum0[iF]), 2),
                        'worst_damage_db': round(float(np.max(np.maximum(sum0[dmg_sel] - sdb[dmg_sel], 0.0))), 2),
                        'max_apf_gd_ms_in_band': round(float(np.max(gd[sel])), 3)}

    best['improvement_pct'] = round(100.0 * (base_score - best['gap_score_after']) / max(base_score, 1e-9), 1)
    return best

def loudness_weight(freqs):
    """Car-tuning priority weight.

    Keeps the old broad sensitivity idea but adds explicit upper-mid risk:
    presence errors around 2-5 kHz are costly, LF broad errors still matter,
    and the top octave gets less authority because off-axis/seat variance is
    usually high in cars.
    """
    freqs = np.asarray(freqs, dtype=float)
    w = audibility_weight(freqs)
    presence = np.exp(-0.5 * (np.log2(freqs / 3200.0) / 0.65) ** 2)
    midbass = 0.25 * np.exp(-0.5 * (np.log2(freqs / 120.0) / 0.9) ** 2)
    w = w * (1.0 + 0.45 * presence + midbass)
    w[freqs > 12000.0] *= 0.75
    return np.clip(w, 0.25, 1.8)

def band_weight(freqs, lo, hi, floor=0.0, edge_oct=0.5):
    """Soft rectangular band weight with octave-tapered edges."""
    freqs = np.asarray(freqs, dtype=float)
    w = np.ones_like(freqs)
    below = freqs < lo
    above = freqs > hi
    w[below] = np.clip(1.0 - np.log2(lo / freqs[below]) / edge_oct, floor, 1.0)
    w[above] = np.clip(1.0 - np.log2(freqs[above] / hi) / edge_oct, floor, 1.0)
    return np.clip(w, floor, 1.0)

def wrms(values, weights=None):
    values = np.asarray(values, dtype=float)
    if weights is None:
        weights = np.ones_like(values)
    weights = np.asarray(weights, dtype=float)
    ok = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not np.any(ok):
        return float('inf')
    den = np.sum(weights[ok] ** 2)
    return float(np.sqrt(np.sum((values[ok] * weights[ok]) ** 2) / den))

def local_peak_q_proxy(freqs, local_db, min_prom_db=0.5):
    """Approximate how narrow/prominent positive local excess is.

    This is not a literal acoustic Q measurement; it is a cheap resonance-risk
    proxy for scoring. Broad tonal errors should be handled by normal ERB score,
    while narrow upper-mid peaks deserve extra caution.
    """
    freqs = np.asarray(freqs, dtype=float)
    local_db = np.asarray(local_db, dtype=float)
    q = np.ones_like(local_db)
    pos = np.maximum(local_db, 0.0)
    n = len(freqs)
    for i in range(1, n - 1):
        if pos[i] < min_prom_db or pos[i] < pos[i - 1] or pos[i] < pos[i + 1]:
            continue
        half = pos[i] * 0.5
        l = i
        r = i
        while l > 0 and pos[l] > half:
            l -= 1
        while r < n - 1 and pos[r] > half:
            r += 1
        bw_oct = max(np.log2(freqs[r] / freqs[l]), 1 / 24.0)
        q[i] = np.clip(1.0 / bw_oct, 0.5, 12.0)
    return q

def masking_relief(freqs, smoothed_db):
    """Small down-weight for errors sitting near much louder broad energy.

    This is intentionally conservative. It prevents the perceptual score from
    overreacting to small ripples on top of dominant bass/midbass energy, but it
    never hides a real error completely.
    """
    smoothed_db = np.asarray(smoothed_db, dtype=float)
    broad = octave_smooth_log(freqs, smoothed_db, 1.0)
    relief = np.where(broad > smoothed_db + 3.0, 0.72, 1.0)
    return np.clip(relief, 0.65, 1.0)

def perceptual_score(freqs, dev_db, left_db=None, right_db=None, band=(60.0, 16000.0),
                     mask=None, conf=None):
    """Composite score for car-audio tuning decisions.

    It keeps broad tonal error, but separately penalizes narrow upper-mid peaks
    and L/R mismatch in the image-critical band. Dips cost less than peaks so
    the app remains biased against filling nulls.
    """
    freqs = np.asarray(freqs, dtype=float)
    dev_db = np.asarray(dev_db, dtype=float)
    sel = (freqs >= band[0]) & (freqs <= band[1])
    if mask is not None:
        sel &= np.asarray(mask, dtype=bool)
    if not np.any(sel):
        return {'total': float('inf'), 'tonal': float('inf'),
                'resonance': float('inf'), 'stereo': 0.0}
    c = np.ones_like(freqs, dtype=float) if conf is None else np.clip(np.asarray(conf, dtype=float), 0.0, 1.0)
    sm = erb_smooth(freqs, dev_db)
    W = loudness_weight(freqs) * c
    peak_term = np.maximum(sm, 0.0)
    dip_term = 0.6 * np.maximum(-sm, 0.0)
    tonal = wrms((peak_term + dip_term)[sel] * masking_relief(freqs[sel], sm[sel]), W[sel])

    local = dev_db - sm
    q_proxy = local_peak_q_proxy(freqs, local)
    resonance_weight = band_weight(freqs, 1500.0, 6000.0, floor=0.05) * c
    resonance_term = np.maximum(local, 0.0) * np.clip(q_proxy / 1.8, 0.8, 3.0)
    resonance = wrms(resonance_term[sel], resonance_weight[sel])

    stereo = 0.0
    if left_db is not None and right_db is not None:
        lr = erb_smooth(freqs, np.asarray(left_db, dtype=float) - np.asarray(right_db, dtype=float))
        stereo_weight = band_weight(freqs, 700.0, 5000.0, floor=0.0) * c
        stereo = wrms(np.abs(lr[sel]), stereo_weight[sel])

    total = tonal + 1.2 * resonance + 0.8 * stereo
    return {'total': round(float(total), 4),
            'tonal': round(float(tonal), 4),
            'resonance': round(float(resonance), 4),
            'stereo': round(float(stereo), 4)}

def smooth_bool_mask(mask, oct_frac=1 / 12.0, threshold=0.5):
    y = np.asarray(mask, dtype=float)
    w = max(1, int(round((1.0 / np.log10(LOGSTEP)) * np.log10(2 ** oct_frac))))
    sm = np.convolve(y, np.ones(w) / w, mode='same')
    return sm >= threshold


def octave_smooth_log(freqs, y, oct_frac):
    w = max(1, int(round((1.0 / np.log10(LOGSTEP)) * np.log10(2 ** oct_frac))))
    return np.convolve(y, np.ones(w) / w, mode='same')


# --------------------------------------------------------------------------
# ROBUST DELAY ESTIMATE (generalized cross-correlation) -- added to make TA
# usable even when per-frequency phase confidence is shaky (the exact failure
# mode a USB-mic timing-chirp capture can produce: clock drift corrupts phase
# unevenly across frequency). A coherent-sum grid search is sensitive to
# whichever bins happen to be weighted heavily; cross-correlation instead asks
# "where does the BULK of the two spectra's energy line up in time" -- a
# single global operation less swayed by a few bad bins. It does NOT fix
# already-corrupted phase data (garbage in, garbage out, same as any method
# using the same input) -- what it buys is a SECOND, differently-computed
# estimate to cross-check the grid search against; large disagreement between
# the two is itself a useful "don't trust this" signal, in the same spirit as
# the coherence-gating discussed in methodology.md.
def estimate_delay_xcorr(freqs, driver_a, driver_b, band, max_delay_ms=5.0, n_uniform=8192):
    """Sign convention MATCHES polarity_delay_search's delay_ms_B (verified by
    round-trip test): the returned delay is the correction to apply to
    driver_b (via B*exp(-1j*2*pi*f*d_ms/1000)) to align it with driver_a.

    Method: resample the complex spectra onto a UNIFORM linear frequency grid
    (freqs is normally log-spaced -- IFFT needs linear spacing or the lag axis
    is meaningless), interpolating real/imaginary parts separately (not
    magnitude/phase, which risks unwrap artifacts at interpolation
    boundaries), then IFFT the windowed cross-spectrum to get correlation vs.
    lag and take the peak within +/-max_delay_ms.

    Returns delay_ms and a confidence ratio (peak height / median sidelobe
    height -- large means a sharp, trustworthy peak; near 1 means no real
    peak, don't trust this estimate)."""
    lo, hi = band
    if not (freqs[0] <= lo and hi <= freqs[-1]):
        raise ValueError('band must be within the measured frequency range')
    f_lin = np.linspace(lo, hi, n_uniform)
    Ar = np.interp(f_lin, freqs, driver_a.real); Ai = np.interp(f_lin, freqs, driver_a.imag)
    Br = np.interp(f_lin, freqs, driver_b.real); Bi = np.interp(f_lin, freqs, driver_b.imag)
    Au, Bu = Ar + 1j * Ai, Br + 1j * Bi
    win = np.hanning(n_uniform)
    cross = (Au * np.conj(Bu)) * win
    n_fft = 4 * n_uniform
    corr = np.fft.fftshift(np.fft.ifft(cross, n=n_fft))
    df = f_lin[1] - f_lin[0]
    fs_equiv = df * n_fft
    lags_ms = (np.arange(n_fft) - n_fft // 2) / fs_equiv * 1000.0
    sel = np.abs(lags_ms) <= max_delay_ms
    if not np.any(sel):
        raise ValueError('max_delay_ms is smaller than the lag-axis resolution -- increase n_uniform')
    mag = np.abs(corr)
    i0 = int(np.argmax(mag[sel]))
    peak_lag = float(lags_ms[sel][i0])
    peak_val = float(mag[sel][i0])
    sidelobe = float(np.median(mag[sel]))
    confidence = peak_val / (sidelobe + 1e-12)
    return {'delay_ms': round(peak_lag, 3), 'confidence_ratio': round(confidence, 1),
            'reliable': bool(confidence > 10.0)}


# --------------------------------------------------------------------------
# 3d) POLARITY/DELAY SEARCH -- added 2026-07-03. Completes the doctrine ladder in
# code: polarity -> delay come BEFORE any APF (we had optimize_allpass but not
# the cheaper rungs below it, which was inconsistent). Same inputs (complex solo
# captures w/ shared time-zero) and the same gap-to-coherent-ceiling score as
# optimize_allpass, so results are directly comparable. Run THIS first; only if
# `residual_needs_apf` is True has an APF earned consideration.
def polarity_delay_search(freqs, driver_a, driver_b, band, max_delay_ms=1.5,
                          steps=121, damage_band=(60.0, 16000.0), damage_free_db=0.5,
                          cross_check=True):
    """Search polarity (binary, on B) x local delay (on B, +ve = B later) for the
    best summed response in `band`. Candidate finder, not a finalizer: apply the
    winning polarity/delay via PC-Tool or afpx.write_delay_samples (verified,
    user-confirmed writes only -- see helix_hardware.md), then re-measure the
    together trace to confirm.
    SIGN NOTE: delay_ms_B < 0 means B must arrive EARLIER, which hardware can't
    do -- apply +|delay| to the OTHER branch instead (keep its pair's internal
    offsets intact), exactly like the doc's negative-delay TA rule.

    cross_check=True (default) also runs estimate_delay_xcorr as an
    independent second opinion and reports agreement -- large disagreement
    between the grid search and the cross-correlation estimate means the
    phase data likely isn't trustworthy enough to act on, even if the grid
    search itself looks confident."""
    sel = (freqs >= band[0]) & (freqs <= band[1])
    dmg = (freqs >= damage_band[0]) & (freqs <= damage_band[1])
    if not np.any(sel):
        raise ValueError('band does not overlap the frequency axis')
    coh = 20 * np.log10(np.abs(driver_a) + np.abs(driver_b) + 1e-12)
    sum0 = 20 * np.log10(np.abs(driver_a + driver_b) + 1e-12)

    def wr(y, m):
        w = audibility_weight(freqs[m])
        den = np.sum(w ** 2)
        return float(np.sqrt(np.sum((y[m] * w) ** 2) / den)) if den > 1e-12 else float('inf')

    # NOTE (2026-07-03): the R&D brief proposed a gain-trim rung below polarity.
    # REJECTED after a failing self-test proved it ill-posed here: this score is
    # gap-to-coherent-ceiling with the ceiling fixed from the INPUT solos, so a
    # level change on B can push the sum past the ceiling and game the metric.
    # Level mismatch is diagnosed by tune_scorecard's balance metrics instead.
    base = wr(np.maximum(coh - sum0, 0.0), sel)
    best = None
    for pol in (False, True):
        s = -1.0 if pol else 1.0
        for d_ms in np.linspace(-max_delay_ms, max_delay_ms, steps):
            B2 = s * driver_b * np.exp(-1j * 2 * np.pi * freqs * d_ms / 1000.0)
            sdb = 20 * np.log10(np.abs(driver_a + B2) + 1e-12)
            gap = np.maximum(coh - sdb, 0.0)
            damage = np.maximum(sum0 - sdb - damage_free_db, 0.0)
            score = wr(gap, sel) + wr(damage, dmg)
            if best is None or score < best['score_after']:
                best = {'polarity_flip_B': pol, 'delay_ms_B': round(float(d_ms), 3),
                        'score_before': round(base, 3), 'score_after': round(score, 3)}
    best['improvement_pct'] = round(100.0 * (base - best['score_after']) / max(base, 1e-9), 1)
    # if polarity+delay left >25% of the original gap, an APF search is justified next
    best['residual_needs_apf'] = bool(best['score_after'] > 0.25 * base)
    if cross_check:
        try:
            xc = estimate_delay_xcorr(freqs, driver_a, driver_b, band, max_delay_ms=max_delay_ms)
            best['xcorr_delay_ms'] = xc['delay_ms']
            best['xcorr_confidence_ratio'] = xc['confidence_ratio']
            agree_ms = abs(best['delay_ms_B'] - xc['delay_ms'])
            best['xcorr_agreement_ms'] = round(agree_ms, 3)
            best['xcorr_agrees'] = bool(xc['reliable'] and agree_ms <= 0.15)
        except ValueError:
            best['xcorr_delay_ms'] = None
            best['xcorr_agrees'] = None
    return best

# --------------------------------------------------------------------------
# 3e) TWO-LEVEL COMPRESSION GATE -- added 2026-07-03. Makes the "high-SPL
# linearity check" numeric. Sweep the same thing twice, `level_delta_db` apart
# electrically; where the measured rise falls short, the driver/region is
# compressing (thermal/excursion/resonance). NEVER boost a compressing region --
# re-crossover or reduce its workload instead. NOTE: per REW's docs, log-sweep
# distortion data is noise-floor-limited at HF (stepped-sine is the trustworthy
# method) -- treat sweep-derived HF distortion/compression evidence as lower
# confidence.
def compression_check(low_db, high_db, level_delta_db, warn_db=0.75):
    """Returns (compression_db_per_bin, flagged_mask). compression = expected
    rise minus measured rise; > warn_db (default 0.75) = compressing, veto boosts."""
    comp = level_delta_db - (np.asarray(high_db, float) - np.asarray(low_db, float))
    return comp, comp > warn_db



# --------------------------------------------------------------------------
# 3f) SHELF SIMULATION -- RBJ low/high shelf (Q form), matching the Helix shelf
# parameterization (Q 0.1-2 IS the slope control; hinge freq in 1 Hz steps;
# band 1 = low-shelf-capable, band 30 = high-shelf-capable). The active-shelf
# XML encoding is T=3 (low) / T=4 (high) with G!=0 -- export-diff-VERIFIED (see
# shelf_fil_str below and afpx_format.md). T=20 is the 2nd-order ALL-PASS, not
# a shelf -- an earlier, now-corrected note here said otherwise; don't trust
# any surviving reference to "T=20 shelf" elsewhere as anything but stale.
def low_shelf_db(freqs, f0, Q, gain_db, fs=FS):
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / fs
    cw, al = np.cos(w0), np.sin(w0) / (2 * Q)
    sA = 2 * np.sqrt(A) * al
    b0 = A * ((A + 1) - (A - 1) * cw + sA)
    b1 = 2 * A * ((A - 1) - (A + 1) * cw)
    b2 = A * ((A + 1) - (A - 1) * cw - sA)
    a0 = (A + 1) + (A - 1) * cw + sA
    a1 = -2 * ((A - 1) + (A + 1) * cw)
    a2 = (A + 1) + (A - 1) * cw - sA
    w = 2 * np.pi * freqs / fs
    z1, z2 = np.exp(-1j * w), np.exp(-2j * w)
    H = (b0 + b1 * z1 + b2 * z2) / (a0 + a1 * z1 + a2 * z2)
    return 20 * np.log10(np.abs(H))

def high_shelf_db(freqs, f0, Q, gain_db, fs=FS):
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * f0 / fs
    cw, al = np.cos(w0), np.sin(w0) / (2 * Q)
    sA = 2 * np.sqrt(A) * al
    b0 = A * ((A + 1) + (A - 1) * cw + sA)
    b1 = -2 * A * ((A - 1) + (A + 1) * cw)
    b2 = A * ((A + 1) + (A - 1) * cw - sA)
    a0 = (A + 1) - (A - 1) * cw + sA
    a1 = 2 * ((A - 1) - (A + 1) * cw)
    a2 = (A + 1) - (A - 1) * cw - sA
    w = 2 * np.pi * freqs / fs
    z1, z2 = np.exp(-1j * w), np.exp(-2j * w)
    H = (b0 + b1 * z1 + b2 * z2) / (a0 + a1 * z1 + a2 * z2)
    return 20 * np.log10(np.abs(H))

def fit_shelf_to_curve(freqs, target_curve_db, kind, band, q_lim=(0.1, 2.0)):
    """Grid-fit one shelf to replicate `target_curve_db` (e.g. a stack of broad
    PEQs being considered for consolidation) over `band`. Returns (F, Q, G,
    max_abs_err_in_band). Use to decide IF a shelf faithfully replaces the
    stack -- if max_err > ~0.75 dB where it matters, keep the PEQs."""
    fn = low_shelf_db if kind == 'low' else high_shelf_db
    sel = (freqs >= band[0]) & (freqs <= band[1])
    gains = np.arange(-6.0, 6.01, 0.25)
    best = None
    for F in np.geomspace(band[0], band[1], 40):
        for Q in np.linspace(q_lim[0], q_lim[1], 20):
            for G in gains:
                if abs(G) < 0.5: continue
                err = float(np.max(np.abs(fn(freqs, F, Q, G)[sel] - target_curve_db[sel])))
                if best is None or err < best[3]:
                    best = (round(float(F), 1), round(float(Q), 2), float(G), round(err, 2))
    return best

# --------------------------------------------------------------------------
# PEAKING-ONLY APPROXIMATION OF A SHELF -- the mirror of fit_shelf_to_curve.
# Not a Helix need (Helix's PEQ has real shelf filters, T=3/T=4) -- this is
# for the OTHER direction: a target DSP whose parametric EQ offers only
# peaking (bell) bands, no shelf type at all. Inspired by reviewing a sibling
# tool built for a specific Alpine head unit that solved exactly this problem
# for its own PEQ -- generalized here to any target DSP's real Q/gain limits
# via q_lim/gain_limit rather than assuming one unit's numbers. This produces
# ONLY F/Q/G numbers; it does not read, write, or assume anything about a
# target DSP's file format or software -- how those numbers get into the
# unit (manual entry, a vendor app, etc.) is entirely up to the caller.
def fit_peaking_to_shelf(shelves, n_bands, fit_band, q_lim=(0.5, 15.0),
                         gain_limit=None, fs=FS, grid=300, drop_below_db=0.05,
                         seed=0):
    """Fit `n_bands` peaking filters to approximate one or more shelves, for
    a DSP whose PEQ has no shelf filter type.

    shelves: list of (kind, F, Q, G) with kind in {'low','high'} -- same
    convention as low_shelf_db/high_shelf_db/fit_shelf_to_curve.
    fit_band: (lo_hz, hi_hz) -- the CHANNEL's actual passband (e.g. a
    tweeter's crossover range), not the whole audio band. A fit generated
    for one channel's passband is not valid for a different channel --
    regenerate per channel from that channel's own crossover points.
    q_lim: the TARGET DSP's real peaking-Q range -- pass the actual unit's
    hardware limits, not Helix's; e.g. (0.404, 6.0) is a deliberately
    conservative ceiling used for one real unit's gentle-shelf case in the
    sibling tool this was generalized from, not a universal default.
    gain_limit: |gain| cap per peaking band. None (default) picks
    max(4.0, 1.4 * the largest shelf gain) so the optimizer can't hide error
    behind a big near-cancelling pair; pass the DSP's real ceiling explicitly
    if you have it.
    drop_below_db: filters that fit at or below this |gain| are dropped
    after fitting (a peaking filter at ~0 dB does nothing but occupies a
    band) -- the returned rms/max_err_db are recomputed on the survivors so
    the reported match quality stays honest.

    Returns (bands, report). bands = [(F, Q, G), ...] sorted by frequency,
    F/Q/G plain floats -- NOT rounded to any specific DSP's entry precision
    and NOT hardware-validated (that varies by unit; call the target DSP's
    own limits check, e.g. validate_peq_band for Helix, before writing or
    entering these). report = {'rms_db', 'max_err_db', 'dropped'} describing
    fit quality; anything under a few tenths of a dB is inaudible."""
    from scipy.optimize import differential_evolution

    lo_hz, hi_hz = fit_band
    f = np.geomspace(lo_hz, hi_hz, grid)
    target = np.zeros_like(f)
    max_shelf = 0.0
    for kind, F, Q, G in shelves:
        if kind not in ('low', 'high'):
            raise ValueError("shelf kind must be 'low' or 'high', got %r" % (kind,))
        max_shelf = max(max_shelf, abs(G))
        fn = low_shelf_db if kind == 'low' else high_shelf_db
        target += fn(f, F, Q, G, fs=fs)

    gb = gain_limit if gain_limit is not None else max(4.0, 1.4 * max_shelf)
    q_min, q_max = q_lim
    bounds = [(np.log10(lo_hz), np.log10(hi_hz)), (-gb, gb), (q_min, q_max)] * n_bands
    reg = 1.5e-3   # ridge on peaking gains: among equally-good fits, prefer the
                   # smaller-gain (well-conditioned) one over a fragile large
                   # near-cancelling pair that happens to score the same RMS

    def model_of(p):
        m = np.zeros_like(f)
        for i in range(n_bands):
            m += peaking_db(f, 10 ** p[3 * i], p[3 * i + 2], p[3 * i + 1], fs=fs)
        return m

    def obj(p):
        rms = float(np.sqrt(np.mean((model_of(p) - target) ** 2)))
        gains = p[1::3]
        return rms + reg * float(np.mean(gains ** 2))

    res = differential_evolution(obj, bounds, seed=seed, tol=1e-10,
                                 maxiter=300, popsize=20, polish=True)

    filters = sorted(
        [(round(float(10 ** res.x[3 * i]), 1), round(float(res.x[3 * i + 2]), 3),
          round(float(res.x[3 * i + 1]), 2)) for i in range(n_bands)],
        key=lambda b: b[0])
    filters = [(F, Q, G) for F, Q, G in filters if abs(G) > drop_below_db]
    dropped = n_bands - len(filters)

    model = np.zeros_like(f)
    for F, Q, G in filters:
        model += peaking_db(f, F, Q, G, fs=fs)
    err = model - target
    report = {'rms_db': round(float(np.sqrt(np.mean(err ** 2))), 3),
             'max_err_db': round(float(np.max(np.abs(err))), 3),
             'dropped': dropped}
    return filters, report



# --------------------------------------------------------------------------
# 3g) PREDICTION-CONFIDENCE GATE -- adopted 2026-07-03 from the R&D brief (its
# best idea). Before trusting any phase-sensitive search (polarity_delay_search,
# optimize_allpass), prove the model can predict the CURRENT measured together
# trace from the solo captures. If it can't, the complex data is misaligned
# (clock drift, moved mic, wrong time-zero) and phase decisions are blocked.
def prediction_confidence(freqs, driver_a, driver_b, measured_together_db, band):
    """Complex solos A,B (shared time-zero) + the measured pair-together SPL.
    Returns dict with rms error (after removing a level bias) and a gate:
    usable_for_phase_decisions True only if the solo model reproduces the
    measured sum within ~2.5 dB rms in-band."""
    sel = (freqs >= band[0]) & (freqs <= band[1])
    if not np.any(sel):
        raise ValueError('band does not overlap axis')
    pred = 20 * np.log10(np.abs(driver_a + driver_b) + 1e-12)
    err = pred[sel] - np.asarray(measured_together_db, float)[sel]
    bias = float(np.median(err))
    resid = err - bias
    rms = float(np.sqrt(np.mean(resid ** 2)))
    return {'rms_err_db': round(rms, 2), 'level_bias_db': round(bias, 2),
            'usable_for_phase_decisions': bool(rms <= 2.5),
            'grade': 'high' if rms <= 2.0 else ('medium' if rms <= 4.0 else 'low')}

# --------------------------------------------------------------------------
# 3h) TUNE SCORECARD -- one canonical scoring function so every tune comparison
# uses identical math (yesterday's v5/v6/v7/aggressive benchmark was hand-rolled
# three times; this ends that). Named components, not one opaque number.
#
# The *_balance_db fields below are a SIGNED MEDIAN -- a deliberate choice for
# "which side is broadly louder," but it has a real blind spot: an L/R
# difference that OSCILLATES sign across the band (comb-filtering, a driver
# that's ahead in one sub-band and behind in another) can median out near
# zero while the actual mismatch is large everywhere, just not consistently
# in one direction. The matching *_balance_abs_rms_db field doesn't have that
# blind spot -- it's the RMS of the same signed-difference curve, so opposite-
# sign errors add instead of cancelling. Read both: signed median tells you
# the DIRECTION (if any) worth a broad gain nudge, abs-RMS tells you the true
# MAGNITUDE of the mismatch regardless of direction. (lr_match_report goes
# further still -- per-frequency regions instead of one number for the whole
# band -- use it when you need to know WHERE, not just how much.)
def tune_scorecard(freqs, traces, target_db,
                   img_band=(200.0, 6000.0), mid_bal_band=(200.0, 2000.0),
                   tw_bal_band=(2800.0, 16000.0), inband=(60.0, 16000.0)):
    """traces: dict with 'System Sum' and optionally 'FL Low','FR Low',
    'FL High','FR High' (predicted or measured SPL on `freqs`). Returns the
    named metrics used for every tune-vs-tune decision."""
    dev = erb_smooth(freqs, traces['System Sum'] - target_db)
    inb = (freqs >= inband[0]) & (freqs <= inband[1])
    w = np.ones_like(freqs); w[(freqs >= img_band[0]) & (freqs <= img_band[1])] = 1.8
    out = {'sum_rms_db': round(float(np.sqrt(np.mean(dev[inb] ** 2))), 2),
           'sum_wrms_img_db': round(float(np.sqrt(np.sum((dev[inb] * w[inb]) ** 2) / np.sum(w[inb] ** 2))), 2),
           'worst_dev_db': round(float(np.max(np.abs(dev[(freqs >= 100) & (freqs <= 8000)]))), 1)}
    if 'FL Low' in traces and 'FR Low' in traces:
        b = erb_smooth(freqs, traces['FL Low'] - traces['FR Low'])
        s = (freqs >= mid_bal_band[0]) & (freqs <= mid_bal_band[1])
        out['mid_balance_db'] = round(float(np.median(b[s])), 2)
        out['mid_balance_abs_rms_db'] = round(float(np.sqrt(np.mean(b[s] ** 2))), 2)
    if 'FL High' in traces and 'FR High' in traces:
        b = erb_smooth(freqs, traces['FL High'] - traces['FR High'])
        s = (freqs >= tw_bal_band[0]) & (freqs <= tw_bal_band[1])
        out['tweeter_balance_db'] = round(float(np.median(b[s])), 2)
        out['tweeter_balance_abs_rms_db'] = round(float(np.sqrt(np.mean(b[s] ** 2))), 2)
    return out



def validate_peq_band(F, Q, G):
    """Enforce Helix hardware limits before writing a PEQ. Raises ValueError.
    P SIX DSP MK2: gain -15..+6 dB, Q 0.5..15, F within 20..20000 Hz."""
    F, Q, G = float(F), float(Q), float(G)
    if not (20.0 <= F <= 20000.0):
        raise ValueError('PEQ frequency out of range: %.2f Hz' % F)
    if not (0.5 <= Q <= 15.0):
        raise ValueError('PEQ Q out of range (0.5-15): %.3f' % Q)
    if not (-15.0 <= G <= 6.0):
        raise ValueError('PEQ gain out of Helix range (-15..+6): %.2f dB' % G)
    return True



# --------------------------------------------------------------------------
# SAMPLE-RATE-AWARE DELAY CONVERSION -- added after reviewing a sibling project
# (ayukhno/autosound-tuning-skill) that flagged a real, easy-to-make mistake:
# a delay computed for one DSP's internal sample rate, entered into a DSP
# running at a DIFFERENT rate, silently doubles (or halves) the real physical
# delay. P SIX DSP MK2 runs at 96 kHz -- but this skill supports other Helix
# models too, and their internal rate is NOT guaranteed to match. ALWAYS confirm
# the actual sample rate (from PC-Tool's device info, not assumed) before
# converting. Physical milliseconds are the hardware-independent reference --
# keep proposals in ms first, convert last, and show both.
def ms_to_samples(delay_ms, sample_rate_hz):
    """Physical delay (ms) -> DSP delay register value (samples) at the DSP's
    ACTUAL internal rate. Never assume 96 kHz -- confirm the model's rate."""
    return delay_ms * sample_rate_hz / 1000.0

def samples_to_ms(samples, sample_rate_hz):
    """Inverse of ms_to_samples -- read a delay register back into physical ms
    (the number that stays meaningful across different DSP models)."""
    return samples * 1000.0 / sample_rate_hz

# --------------------------------------------------------------------------
# DRIVER EXCURSION SAFETY CHECK (optional -- needs the driver's Fs) -- added
# after reviewing a sibling project's presweep safety gate. Rule of thumb from
# car-audio driver-protection practice: a high-pass set too close to (or below)
# a driver's own resonant frequency, especially at a steep electrical slope,
# doesn't remove the mechanical excursion risk AT resonance -- the driver can
# still move further than intended right where it's least controlled. This is
# advisory only (no Xmax/power data needed) and should only fire if the user
# actually supplies Fs -- never invent a driver spec.
def hpf_excursion_risk(hpf_hz, slope_db_oct, driver_fs_hz, safe_ratio=1.1):
    """Returns dict: risk=True if hpf_hz sits at/below safe_ratio * driver_fs_hz
    while the slope is steep (>=24 dB/oct, i.e. 4th-order+). Gentler slopes
    (12-18 dB/oct) are more forgiving because they still let some mechanical
    rolloff assist below the corner -- only flagged if hpf_hz < driver_fs_hz
    outright for those. This is a heuristic advisory, not a hard limit."""
    ratio = hpf_hz / float(driver_fs_hz)
    if slope_db_oct >= 24.0:
        risk = ratio < safe_ratio
    else:
        risk = ratio < 1.0
    return {'hpf_hz': hpf_hz, 'driver_fs_hz': driver_fs_hz, 'slope_db_oct': slope_db_oct,
            'ratio': round(ratio, 2), 'excursion_risk': bool(risk),
            'note': ('HPF is close to/below Fs at a steep slope -- confirm the driver can '
                     'handle unrestrained excursion near resonance before using this crossover'
                     if risk else 'HPF sits comfortably above Fs for this slope')}



# --------------------------------------------------------------------------
# SOLO-LEVEL CALIBRATION -- added after a real-session finding: solos are often
# necessarily captured at different test levels (e.g. a sub measured much
# quieter than the mids under an aggressive bass shelf, to avoid clipping).
# Phase is level-independent, so this never hurts timing work (polarity_delay_
# search, optimize_allpass) -- but any MAGNITUDE-based joint check
# (interference_audit, prediction_confidence, tune_scorecard) needs the real
# relative level recovered first, or it will "detect" a fake cancellation/gap
# that's actually just a test-level mismatch.
def calibrate_solo_levels(freqs, solo_db, together_db, band):
    """Fit a scalar dB offset to solo_db so that its incoherent contribution best
    explains together_db over `band` (least-squares on a log scale). Returns the
    fitted offset (add to solo_db) and the residual rms (post-calibration --
    use THIS as the real confidence number, not the raw pre-fit deviation).

    Same level-independent-shape assumption as target_anchor_offset -- see
    that function's docstring for the loudness-contour caveat if solo and
    together were captured at meaningfully different playback levels."""
    sel = (freqs >= band[0]) & (freqs <= band[1])
    if not np.any(sel):
        raise ValueError('band does not overlap axis')
    diff = together_db[sel] - solo_db[sel]
    offset = float(np.median(diff))
    resid = together_db[sel] - (solo_db[sel] + offset)
    return {'level_offset_db': round(offset, 2),
            'residual_rms_db': round(float(np.sqrt(np.mean(resid ** 2))), 2)}

# --------------------------------------------------------------------------
# PHASE RELIABILITY SCORE -- a single fixed-position sweep can have excellent
# magnitude data but garbage phase above a few hundred Hz, because reflections
# dominate the fine structure while the ear (and REW's own averaging) still
# reports something. Quantify it instead of guessing: real driver phase is
# close to a straight line vs frequency over its own passband (it's dominated
# by acoustic path delay); reflections add high-frequency wiggle on top.
def gating_frequency_limit(gate_ms):
    """Minimum trustworthy frequency for a time-gated (windowed) measurement of
    the given gate length -- adopted from HolmImpulse's quasi-anechoic gating
    practice, verified against its own documented example (a 1 m reflection
    path difference -> ~2.91 ms gate -> "cannot trust below ~344 Hz"; this
    formula predicts 343 Hz, matching within normal speed-of-sound rounding).
    You need at least one full wavelength of a frequency to fit inside the
    reflection-free window before that frequency's response is meaningful --
    below this limit, the window cut off the waveform before a cycle
    completed, and the reported magnitude/phase there is not real data.
    Relevant to REW's own "IR windows" gating feature (or HolmImpulse), NOT to
    a REW text export that's already been captured -- this is a measurement-
    setup-time check (choose your window length knowing its low-frequency
    cost), complementary to phase_linearity_residual (a post-hoc diagnostic on
    data you already have)."""
    return 1000.0 / gate_ms


def min_gate_for_frequency(freq_hz):
    """Inverse of gating_frequency_limit: the minimum gate length (ms) needed
    to trust a measurement down to freq_hz."""
    return 1000.0 / freq_hz


def gating_warning(gate_ms):
    """A ready-to-say sentence for a gated measurement's low-frequency limit --
    pair with the actual remedy (spatially-averaged / ungated capture via
    complex_vector_average), not just the caveat."""
    f_min = gating_frequency_limit(gate_ms)
    return ('Do not trust this gated response below ~%.0f Hz (gate length %.1f ms). '
            'Low-frequency work should use an ungated or spatially-averaged '
            'measurement instead.' % (f_min, gate_ms))


def phase_linearity_residual(freqs, phase_deg, band):
    """RMS residual (degrees) of unwrapped phase vs frequency after removing the
    best-fit straight line (i.e. removing pure delay) over `band`. Rule of thumb
    from real sessions: <=~100 deg = trustworthy for timing decisions; >~300-450
    deg = reflection-dominated, do not use for polarity/delay/APF work."""
    sel = (freqs >= band[0]) & (freqs <= band[1])
    if np.sum(sel) < 3:
        raise ValueError('band does not overlap enough of the axis')
    ph = np.unwrap(np.deg2rad(phase_deg[sel]))
    ph = np.rad2deg(ph)
    f = freqs[sel]
    slope, intercept = np.polyfit(f, ph, 1)
    resid = ph - (slope * f + intercept)
    rms = float(np.sqrt(np.mean(resid ** 2)))
    return {'rms_residual_deg': round(rms, 1),
            'trustworthy_for_timing': bool(rms <= 100.0),
            'grade': ('trustworthy' if rms <= 100.0 else
                     'marginal' if rms <= 300.0 else 'reflection-dominated (do not use)')}

# --------------------------------------------------------------------------
# COMPLEX (VECTOR) AVERAGING ACROSS MIC POSITIONS -- a sweep only takes a few
# seconds, so don't move the mic mid-sweep. Instead take several (3-7) discrete
# sweeps at slightly different fixed positions spanning head-width, then vector-
# average the COMPLEX spectra (not magnitude-only). This cancels position-
# specific comb-filtering (which differs per position) while preserving the
# real driver phase (which is common to all of them) -- a magnitude-only
# average would keep the comb-filtering artifacts baked into the average level.
def complex_vector_average(complex_traces):
    """complex_traces: list of complex ndarrays on the SAME frequency grid (one
    per mic position). Returns the vector-averaged complex response -- take
    20*log10(abs(.)) for magnitude, angle(.) for phase."""
    if len(complex_traces) < 2:
        raise ValueError('need >=2 position traces to average')
    stack = np.stack(complex_traces, axis=0)
    return np.mean(stack, axis=0)

# --------------------------------------------------------------------------
# SPATIAL CONSISTENCY MASK -- the core Smaart discipline this skill was
# missing: measure several (3-7) mic positions spanning the listening area,
# then only correct what's COMMON across them. A dip that's at the mic spot
# but gone (or moved) a few inches away is position-specific interference
# (comb-filtering between direct sound and a nearby reflection, e.g. dash/
# door/opposite-side arrival) -- EQing it makes that one spot better and
# everywhere else worse. A dip that holds at every position is a real
# driver/room feature and is safe to correct. This is the honest,
# measurement-driven answer to "is this dip safe to boost" that a single-
# position phase/min-phase check can't fully give (see fit_peq's docstring
# and methodology.md -- excess_gd_mask can call a comb-filter null locally
# minimum-phase-ish from one position and still be wrong about whether it's
# interference, because it never sees a second position to compare against).
# fit_peq's mask/conf parameters were built for exactly this kind of input --
# this is what finally sources them from real spatial data instead of a
# single-position guess.
def spatial_consistency(freqs, position_traces, consistent_db=1.5,
                        min_positions=3, smooth_oct=1.0 / 12.0):
    """position_traces: list of >=min_positions arrays on the SAME freq grid,
    one per mic position -- either complex (magnitude+phase, reduced to
    magnitude here) or plain SPL in dB (fine, and usually all that's
    practical to capture per position -- phase-valid capture at multiple
    positions is a much bigger ask than just moving the mic). Judges
    MAGNITUDE consistency only; phase at an arbitrary position isn't a
    meaningful thing to average the way "is this dip here or not" is.

    consistent_db: how much across-position spread still counts as "the same
    feature" (~1.5 dB is a reasonable floor -- normal measurement/positioning
    noise is smaller than that; a real interference null is usually much
    larger, often 6+ dB at one spot and near-zero a few inches away).

    Returns mean_db (across-position average), spread_db (per-frequency
    across-position std, lightly octave-smoothed so single-bin position-grid
    jitter doesn't flip the mask), mask (bool, True = consistent enough to
    trust a correction there), conf (continuous 0..1, 1 at spread=0 tapering
    to 0 by 2x consistent_db -- feed directly into fit_peq's conf=).

    Use: sc = spatial_consistency(freqs, [pos1, pos2, pos3])
         fit_peq(freqs, dev_db, band, mask=sc['mask'], conf=sc['conf'])"""
    if len(position_traces) < min_positions:
        raise ValueError('need >= %d position traces (got %d) -- a single '
                         'position cannot tell a real dip from a position-'
                         'specific null' % (min_positions, len(position_traces)))
    freqs = np.asarray(freqs, dtype=float)
    db_traces = []
    for t in position_traces:
        t = np.asarray(t)
        db_traces.append(20 * np.log10(np.abs(t)) if np.iscomplexobj(t) else t.astype(float))
    stack = np.stack(db_traces, axis=0)
    mean_db = np.mean(stack, axis=0)
    spread_raw = np.std(stack, axis=0, ddof=0)
    spread_db = octave_smooth_log(freqs, spread_raw, smooth_oct)
    mask = spread_db <= consistent_db
    conf = np.clip(1.0 - spread_db / (2.0 * consistent_db), 0.0, 1.0)
    return {'mean_db': mean_db, 'spread_db': spread_db,
            'mask': mask, 'conf': conf}

# --------------------------------------------------------------------------
# PREDICTED vs MEASURED -- closes the predict -> re-measure loop. Everything
# above this point in the file only ever runs FORWARD (measure -> propose ->
# write -> "now go re-measure"); nothing consumed that re-measure. This does,
# but deliberately NOT as a raw curve subtraction -- a bare before/after diff
# gets swamped by exactly the confounds a real re-measure carries (different
# playback level, mic position drift, a noisier capture that day). Three
# guards, each reusing a discipline already built for the same underlying
# problem elsewhere in this file, rather than inventing a fourth:
#   1. LEVEL ALIGNMENT: a pure volume-knob difference between runs is a
#      broadband, frequency-flat offset, not signal -- estimated ONLY from
#      untouched regions (so it can't absorb the very change under test) via
#      the same wide-anchor weighted-median trick target_anchor_offset uses.
#   2. SMOOTHING: compares octave-smoothed regional averages, not raw bins --
#      mic position drift shows up as narrow comb ripple, the same kind of
#      noise spatial_consistency already treats as not-signal.
#   3. CONFIDENCE GATING: low conf (e.g. from spatial_consistency or
#      prediction_confidence on the NEW measurement) in a band's region
#      reads as 'inconclusive', not a false confirm or false revert.
def predicted_vs_measured(freqs, before_db, remeasured_after_db, bands,
                          conf=None, region_oct=0.3, consistent_db=2.0,
                          min_predicted_db=0.5):
    """freqs, before_db: the ORIGINAL pre-write measurement (what the
    correction was actually proposed against). remeasured_after_db: the new
    measurement taken after loading the write. bands: the (F, Q, G) list
    that was ACTUALLY written -- not a separately-tracked prediction, so this
    can't drift out of sync with what's really in the file; predicted_after
    is computed as before_db + cascade_db(freqs, bands). conf: optional 0..1
    per-freq confidence on the NEW measurement (spatial_consistency's 'conf'
    if you have multi-position re-measures, prediction_confidence otherwise).

    region_oct: +/- octaves around each band's F judged as "this band's
    region" -- deliberately NOT derived from Q; the question is whether the
    local shape near F tracked prediction, not a precise filter-theory
    bandwidth. consistent_db: tolerance below which actual is considered to
    have tracked predicted -- widen it if your re-measure discipline is
    looser (single position, different day, hand-held mic) than a tight
    tolerance would assume; this is a crude directional check, not a
    precision instrument. min_predicted_db: bands whose own predicted local
    change is smaller than this can't meaningfully fail the check (nothing
    to track) and always grade 'confirmed'.

    Returns {'level_offset_db': ..., 'bands': [...]} -- level_offset_db is
    the broadband correction actually applied before comparing (report it;
    a large value usually just means "quieter/louder playback that day," not
    a tuning result). Each band entry carries predicted_change_db,
    actual_change_db, error_db, confidence, and verdict in {'confirmed',
    'diverged', 'reverted_recommended', 'inconclusive'}. 'reverted_recommended'
    is the actionable one -- actual moved the wrong way or barely moved at
    all despite a real predicted change, the same signature
    reaches_target_after_boost already treats as "phase is eating this, not
    an EQ problem" -- reconsider or remove that band rather than trusting
    the original one-shot prediction forever."""
    freqs = np.asarray(freqs, dtype=float)
    before_db = np.asarray(before_db, dtype=float)
    remeasured_after_db = np.asarray(remeasured_after_db, dtype=float)
    predicted_after_db = before_db + cascade_db(freqs, bands)

    touched = np.zeros_like(freqs, dtype=bool)
    for F, Q, G in bands:
        touched |= (freqs >= F / 2 ** region_oct) & (freqs <= F * 2 ** region_oct)
    untouched = ~touched

    if np.count_nonzero(untouched) >= 12:
        level_offset_db = target_anchor_offset(
            freqs[untouched], remeasured_after_db[untouched],
            predicted_after_db[untouched],
            confidence=(conf[untouched] if conf is not None else None))
    else:
        level_offset_db = 0.0    # too much of the spectrum touched to anchor safely
    aligned_after_db = remeasured_after_db - level_offset_db

    pred_delta = erb_smooth(freqs, predicted_after_db - before_db)
    act_delta = erb_smooth(freqs, aligned_after_db - before_db)

    reports = []
    for F, Q, G in bands:
        region = (freqs >= F / 2 ** region_oct) & (freqs <= F * 2 ** region_oct)
        if not np.any(region):
            continue
        w = audibility_weight(freqs[region])
        predicted_change = float(np.average(pred_delta[region], weights=w))
        actual_change = float(np.average(act_delta[region], weights=w))
        error = actual_change - predicted_change
        region_conf = float(np.mean(conf[region])) if conf is not None else 1.0

        if region_conf < 0.3:
            verdict = 'inconclusive'
        elif abs(predicted_change) < min_predicted_db or abs(error) <= consistent_db:
            verdict = 'confirmed'
        elif (np.sign(actual_change) != np.sign(predicted_change)
              or abs(actual_change) < 0.3 * abs(predicted_change)):
            verdict = 'reverted_recommended'
        else:
            verdict = 'diverged'

        reports.append({'F': F, 'Q': Q, 'G': G,
                        'predicted_change_db': round(predicted_change, 2),
                        'actual_change_db': round(actual_change, 2),
                        'error_db': round(error, 2),
                        'confidence': round(region_conf, 2),
                        'verdict': verdict})

    return {'level_offset_db': round(float(level_offset_db), 2), 'bands': reports}

# --------------------------------------------------------------------------
# "INERT BAND" CHECK -- before trusting a proposed (or externally-supplied) EQ
# band, confirm the target driver actually has enough LEVEL at that frequency
# to matter in the sum. A cut/boost on a driver that's already >~6 dB below
# whichever driver dominates the summed response at that frequency is
# essentially cosmetic -- it changes that driver's own curve but barely moves
# the audible result, because the dominant driver's contribution swamps it.
def inert_band_check(target_driver_db, dominant_db, threshold_db=6.0):
    """Returns dict: inert=True if target_driver_db sits threshold_db or more
    below dominant_db at the frequency in question -- the band is cosmetic,
    not corrective, and shouldn't be trusted as a real fix for that frequency."""
    gap = dominant_db - target_driver_db
    return {'gap_db': round(float(gap), 2), 'inert': bool(gap >= threshold_db),
            'note': ('target driver is buried -- this band barely affects the sum'
                     if gap >= threshold_db else 'target driver has enough level to matter here')}

# --------------------------------------------------------------------------
# "DOES IT ACTUALLY REACH TARGET" CHECK -- pair with interference_audit. If a
# large proposed boost STILL leaves the trace far short of the deficit at that
# frequency, the boost isn't the fix -- the problem is phase/destructive
# interference eating the signal, and no amount of gain on one driver alone
# recovers it (a coherent partner is still cancelling it). Confirms wasted
# headroom vs a real correctable magnitude shortfall.
def reaches_target_after_boost(current_db, target_db, proposed_boost_db, max_boost_db=6.0):
    """Simulates applying proposed_boost_db (capped at hardware max_boost_db) and
    checks whether the result actually reaches target_db. still_short_db > 0
    with a boost already at/near the hardware ceiling is the signature of a
    phase problem masquerading as a magnitude one -- don't keep boosting."""
    applied = min(float(proposed_boost_db), float(max_boost_db))
    after = current_db + applied
    short = target_db - after
    return {'boost_applied_db': round(applied, 2), 'result_db': round(after, 2),
            'still_short_db': round(float(short), 2),
            'likely_phase_problem': bool(short > 1.5 and applied >= max_boost_db - 0.25)}


if __name__ == '__main__':
    import struct

    freqs = 24000.0 / (LOGSTEP ** (1231 - np.arange(1232)))

    # ---- TEST 1: excess-GD classifier on a synthetic known system ----------
    # Build: one minimum-phase peak (EQ-able) + one reflection notch
    # (delayed copy summed -> NON-minimum-phase around the notch).
    w = 2 * np.pi * freqs
    Hpk = 10 ** (peaking_db(freqs, 300.0, 2.0, +6.0) / 20.0) \
        * np.exp(1j * np.deg2rad(0))                        # magnitude only...
    # give the peak its true min phase:
    ph_pk = minphase_from_mag(freqs, peaking_db(freqs, 300.0, 2.0, +6.0))
    Hpk = 10 ** (peaking_db(freqs, 300.0, 2.0, +6.0) / 20.0) * np.exp(1j * ph_pk)
    # DSP subtlety the classifier must honor: a reflection WEAKER than the
    # direct (a<1) makes a comb that is still MINIMUM phase (zeros inside the
    # unit circle) -> technically EQ-able. Only a DOMINANT reflection (a>1)
    # flips the notch non-minimum-phase -> un-EQ-able. Test both.
    tau = 1.0 / (2 * 1200.0)                                # antiphase at 1.2 kHz
    H_weak = Hpk * (1.0 + 0.8 * np.exp(-1j * w * tau))      # min-phase comb
    H_dom  = Hpk * (0.8 + 1.0 * np.exp(-1j * w * tau))      # dominant reflection
    i_pk = int(np.argmin(np.abs(freqs - 300)))
    near = (freqs > 1200 / 2 ** (1 / 12.)) & (freqs < 1200 * 2 ** (1 / 12.))
    print('TEST1 excess-GD classifier:')
    for nm, H, expect_nt in [('weak refl (min-phase)', H_weak, True),
                             ('dominant refl (non-min-phase)', H_dom, False)]:
        spl = 20 * np.log10(np.abs(H))
        ph = np.rad2deg(np.angle(H))
        gd, mask = excess_gd_mask(freqs, spl, ph, flat_ms=0.15)
        nt_ok = bool(np.all(mask[near])) if expect_nt else bool(np.any(~mask[near]))
        print('  %-30s peak@300 eqable=%s (exp True) | notch@1.2k %s' %
              (nm, mask[i_pk], 'stays eqable (exp)' if expect_nt else
               ('flagged un-EQ-able (exp)' if nt_ok else 'NOT flagged (FAIL)')))
        assert mask[i_pk] and nt_ok, 'excess-GD classifier failed on ' + nm

    # ---- TEST 2: optimizer recovers a known correction ---------------------
    dev = peaking_db(freqs, 500.0, 2.0, 5.0) + peaking_db(freqs, 2000.0, 1.0, 4.0)
    bands, rep = fit_peq(freqs, dev, (100, 8000), n_bands_max=4)
    print('TEST2 optimizer on synthetic (+5@500 Q2, +4@2k Q1):')
    for b in bands: print('   fit: F=%-7.1f Q=%-5.2f G=%+.2f' % b)
    print('   score %.3f -> %.3f with %d bands' % (rep['score_before'], rep['score_after'], rep['bands_used']))
    assert rep['score_after'] < 0.35 * rep['score_before'] and rep['bands_used'] <= 3


    # ---- TEST 3: filter tax discourages boosts + narrow-HF filters ---------
    # A dip that COULD be filled with a boost: without tax the fit may boost;
    # with a strong tax it should prefer to leave it (fewer/no boost bands).
    devd = -peaking_db(freqs, 3000.0, 6.0, 5.0)     # a narrow -5 dip at 3 kHz (HF)
    b_notax, _ = fit_peq(freqs, devd, (300, 8000), n_bands_max=3,
                         boost_penalty=0.0, hf_q_penalty=0.0)
    b_tax, _ = fit_peq(freqs, devd, (300, 8000), n_bands_max=3,
                       boost_penalty=1.5, hf_q_penalty=1.5)
    boosts_notax = sum(1 for _, _, G in b_notax if G > 0)
    boosts_tax = sum(1 for _, _, G in b_tax if G > 0)
    print('\nTEST3 filter tax on a narrow +HF dip (fill temptation):')
    print('  no tax  -> %d band(s), boosts=%d: %s' % (len(b_notax), boosts_notax, b_notax))
    print('  w/ tax  -> %d band(s), boosts=%d: %s' % (len(b_tax), boosts_tax, b_tax))
    assert boosts_tax <= boosts_notax, 'filter tax did not reduce boosts'

    # ---- TEST 4: headroom report ------------------------------------------
    hr = headroom_report(freqs, [(120.0, 1.0, 4.0), (1000.0, 2.0, -3.0), (110.0, 1.5, 3.0)])
    print('\nTEST4 headroom report:', hr)
    assert hr['clip_risk'] and hr['recommended_trim_db'] < 0, 'headroom report wrong'

    # ---- TEST 5: interference audit (synthetic + real "Measurements.mdat") --
    tau = 1.0 / (2 * 415.0)                       # antiphase at 415 Hz
    w = 2 * np.pi * freqs
    A = np.ones_like(freqs, dtype=complex) * 10 ** (50 / 20.0)     # solo A, 50dB
    B = 10 ** (50 / 20.0) * np.exp(-1j * w * tau)                  # solo B, delayed
    together_complex = 20 * np.log10(np.abs(A + B))                # true coherent sum
    solo_a_db = 20 * np.log10(np.abs(A)); solo_b_db = 20 * np.log10(np.abs(B))
    psum, csum, interf, flag = interference_audit(freqs, solo_a_db, solo_b_db, together_complex)
    i415 = int(np.argmin(np.abs(freqs - 415)))
    i830 = int(np.argmin(np.abs(freqs - 830)))    # back in phase an octave up (2*tau cycle)
    print('\nTEST5 interference audit (synthetic antiphase @415Hz):')
    print('  @415Hz  psum=%.1f csum=%.1f together=%.1f interf=%+.1f flagged=%s (expect True)'
          % (psum[i415], csum[i415], together_complex[i415], interf[i415], flag[i415]))
    print('  @830Hz  interf=%+.1f flagged=%s' % (interf[i830], flag[i830]))
    assert flag[i415], 'interference audit missed a known cancellation'

    # ---- TEST 6: all-pass XML matches the VERIFIED real export exactly -----
    xml = allpass_fil_str(430.0, 0.7, FN='229')
    expect = '<Fil G="0" FN="229" F="430.00" T="20" I="0" dF="20000" Q="0.7"/>'
    print('\nTEST6 allpass_fil_str:', xml)
    assert xml == expect, 'allpass XML does not match the verified real export'


    # ---- TEST9: polarity/delay search (the rungs BELOW the APF) -------------
    w = 2 * np.pi * freqs
    A9 = np.ones_like(freqs, dtype=complex)
    B9 = -np.ones_like(freqs, dtype=complex)          # pure polarity inversion
    r1 = polarity_delay_search(freqs, A9, B9, (200, 2000))
    print()
    print('TEST9 polarity/delay search:')
    print('  inverted pair  -> flip=%s delay=%.2fms improve=%.0f%% needs_apf=%s'
          % (r1['polarity_flip_B'], r1['delay_ms_B'], r1['improvement_pct'], r1['residual_needs_apf']))
    assert r1['polarity_flip_B'] and abs(r1['delay_ms_B']) < 0.05 and not r1['residual_needs_apf']
    B9b = np.exp(-1j * w * 0.0004) * np.ones_like(freqs, dtype=complex)   # 0.4 ms late
    r2 = polarity_delay_search(freqs, A9, B9b, (500, 2000))
    print('  0.4ms-late B   -> flip=%s delay=%.2fms improve=%.0f%% needs_apf=%s'
          % (r2['polarity_flip_B'], r2['delay_ms_B'], r2['improvement_pct'], r2['residual_needs_apf']))
    # B was LATE, so the fix is NEGATIVE delay on B (advance). Hardware can't
    # advance: translate a negative delay_ms_B into "+delay on the OTHER branch"
    # (the doc's negative-delay rule).
    assert (not r2['polarity_flip_B']) and abs(r2['delay_ms_B'] + 0.4) < 0.05
    # frequency-LOCALIZED rotation (APF-shaped problem): polarity/delay cannot
    # fully fix it -> the search must hand off to the APF stage
    B9c = -(allpass_H(freqs, 415.0, 0.7) ** 2) * np.ones_like(freqs, dtype=complex)
    r3 = polarity_delay_search(freqs, A9, B9c, (250, 700))
    print('  local rotation -> improve=%.0f%% needs_apf=%s (expect True)'
          % (r3['improvement_pct'], r3['residual_needs_apf']))
    assert r3['residual_needs_apf'], 'should have handed off to APF search'

    # ---- TEST10: two-level compression gate ---------------------------------
    low10 = np.zeros_like(freqs)
    high10 = low10 + 10.0                              # perfectly linear +10 dB
    hot10 = (freqs > 2000) & (freqs < 4000)
    high10[hot10] -= 2.0                               # 2 dB compression in a band
    comp10, flag10 = compression_check(low10, high10, 10.0)
    print()
    print('TEST10 compression gate: flagged=%d bins, all inside 2-4k: %s'
          % (int(flag10.sum()), bool(np.all(flag10 == hot10))))
    assert np.all(flag10[hot10]) and not np.any(flag10[~hot10])


    # ---- TEST11: shelf shapes ------------------------------------------------
    ls = low_shelf_db(freqs, 200.0, 0.7, -6.0)
    hs = high_shelf_db(freqs, 5000.0, 0.7, -3.0)
    i20 = int(np.argmin(np.abs(freqs - 20))); i200 = int(np.argmin(np.abs(freqs - 200)))
    i20k = int(np.argmin(np.abs(freqs - 20000))); i5k = int(np.argmin(np.abs(freqs - 5000)))
    print()
    print('TEST11 shelves: LS(-6@200) 20Hz=%.1f 200Hz=%.1f 20kHz=%.1f | HS(-3@5k) 20Hz=%.1f 5kHz=%.1f 20kHz=%.1f'
          % (ls[i20], ls[i200], ls[i20k], hs[i20], hs[i5k], hs[i20k]))
    assert abs(ls[i20] + 6) < 0.3 and abs(ls[i200] + 3) < 0.5 and abs(ls[i20k]) < 0.3
    assert abs(hs[i20]) < 0.3 and abs(hs[i5k] + 1.5) < 0.5 and abs(hs[i20k] + 3) < 0.4

    # ---- TEST12: special-filter writers vs REAL export lines (semantic) -----
    real_ls = '<Fil Q="1" G="-2.25" F="4980.25" FN="0" I="0" T="3" dF="25"/>'
    real_hs = '<Fil Q="0.5" G="0.25" F="5400.00" FN="29" I="0" T="4" dF="20000"/>'
    real_a1 = '<Fil Q="1" G="0" F="2000.00" FN="19" I="0" T="19" dF="2000"/>'
    real_a1i = '<Fil Q="1" G="0" F="2000.00" FN="19" I="1" T="19" dF="2000"/>'
    mine_ls = shelf_fil_str('low', 4980.25, 1, -2.25, FN='0')
    mine_hs = shelf_fil_str('high', 5400.0, 0.5, 0.25, FN='29')
    mine_a1 = allpass1_fil_str(2000.0, FN='19', dF='2000')
    mine_a1i = allpass1_fil_str(2000.0, FN='19', dF='2000', invert=True)
    def _semeq(a, b):
        da, db = fil_attrs(a), fil_attrs(b)
        # numeric-normalize
        for d_ in (da, db):
            for k in ('F', 'Q', 'G'):
                d_[k] = float(d_[k])
        return da == db
    print()
    print('TEST12 special writers: LS match=%s HS match=%s APF1 match=%s'
          % (_semeq(mine_ls, real_ls), _semeq(mine_hs, real_hs), _semeq(mine_a1, real_a1)))
    assert _semeq(mine_ls, real_ls) and _semeq(mine_hs, real_hs) and _semeq(mine_a1, real_a1)
    assert _semeq(mine_a1i, real_a1i), 'inverted APF1 string mismatch vs real export'
    print('TEST12c invert flag: I="1" writer matches the real inverted export')
    # delay semantic comparison tolerates PC-Tool attr reordering
    xa = '<OC><T PM="4" T="223" P="0"/></OC>'
    xb = '<OC><T T="223" P="0" PM="4"/></OC>'
    xc = '<OC><T T="224" P="0" PM="4"/></OC>'
    assert delays_semantically_equal(xa, xb) and not delays_semantically_equal(xa, xc)
    print('TEST12b delay semantic-equality: reorder tolerated, value change caught')


    # ---- TEST13: APF invert = the opposite-direction tool -------------------
    # invert multiplies the APF by -1: same rotation, plus 180 deg EVERYWHERE.
    #  - healthy (in-phase) pair + normal 2nd-order APF at f0 -> NULL at f0
    #  - ANTIPHASE pair + normal APF at f0 -> FIXED at f0 (the 430 Hz use-case)
    #  - antiphase pair + INVERTED APF -> still null at f0 (wrong direction
    #    locally) but FIXED far from f0 (acts as a broadband polarity flip)
    # So: if live-dialing makes the target dip worse at every F/Q, hit invert --
    # the needed rotation is on the other side of the circle.
    A13 = np.ones_like(freqs, dtype=complex)
    i415 = int(np.argmin(np.abs(freqs - 415)))
    i5k  = int(np.argmin(np.abs(freqs - 5000)))
    def sdb13(x): return 20*np.log10(np.abs(x) + 1e-12)
    healthy = sdb13(A13 + A13)[i415]
    Hn, Hi = allpass_H(freqs,415,0.7), allpass_H_inv(freqs,415,0.7)
    n_on_healthy   = sdb13(A13*Hn + A13)[i415]
    n_on_antiphase = sdb13(A13*Hn - A13)[i415]
    i_on_anti_f0   = sdb13(A13*Hi - A13)[i415]
    i_on_anti_5k   = sdb13(A13*Hi - A13)[i5k]
    print()
    print('TEST13 APF invert: healthy=%.1f | norm-on-healthy@f0=%.1f (null) | '
          'norm-on-anti@f0=%.1f (fixed) | inv-on-anti@f0=%.1f (null) @5k=%.1f (fixed)'
          % (healthy, n_on_healthy, n_on_antiphase, i_on_anti_f0, i_on_anti_5k))
    assert n_on_healthy < healthy - 30
    assert abs(n_on_antiphase - healthy) < 0.1
    assert i_on_anti_f0 < healthy - 30
    assert abs(i_on_anti_5k - healthy) < 0.5
    assert np.allclose(np.abs(Hi), 1.0)


    tgt_like = 60.0 + 0.0 * freqs
    # ---- TEST14: prediction-confidence gate ----------------------------------
    A14 = np.ones_like(freqs, dtype=complex)
    B14 = np.exp(-1j * 2 * np.pi * freqs * 0.0002) * 0.8   # coherent pair, known sum
    true_together = 20 * np.log10(np.abs(A14 + B14)) + 3.0  # +3 dB level bias (mic cal)
    r14 = prediction_confidence(freqs, A14, B14, true_together, (200, 2000))
    # now corrupt the model: pretend B was captured with a wrong time-zero
    B14bad = B14 * np.exp(-1j * 2 * np.pi * freqs * 0.004)
    r14b = prediction_confidence(freqs, A14, B14bad, true_together, (200, 2000))
    print()
    print('TEST14 prediction gate: good rms=%.2f (%s, bias %+.1f) | corrupted rms=%.2f (%s)'
          % (r14['rms_err_db'], r14['grade'], r14['level_bias_db'], r14b['rms_err_db'], r14b['grade']))
    assert r14['usable_for_phase_decisions'] and abs(r14['level_bias_db'] + 3.0) < 0.2
    assert not r14b['usable_for_phase_decisions']

    # ---- TEST15: scorecard + gain rung ---------------------------------------
    tr15 = {'System Sum': tgt_like + 2.0 * np.sin(np.log(freqs)),
            'FL Low': tgt_like - 3.0, 'FR Low': tgt_like + 0.0,
            'FL High': tgt_like + 1.0, 'FR High': tgt_like - 1.0}
    sc = tune_scorecard(freqs, tr15, tgt_like)
    print('TEST15 scorecard:', sc)
    assert abs(sc['mid_balance_db'] + 3.0) < 0.1 and abs(sc['tweeter_balance_db'] - 2.0) < 0.1
    assert sc['sum_rms_db'] > 0
    # a constant offset: signed median and abs-RMS must agree (same magnitude)
    assert abs(sc['mid_balance_abs_rms_db'] - 3.0) < 0.1
    assert abs(sc['tweeter_balance_abs_rms_db'] - 2.0) < 0.1

    # signed-median blind spot: an L/R difference that ALTERNATES sign across
    # the band medians out near zero while still being a real, large mismatch
    # everywhere -- abs-RMS must catch what the median misses.
    osc15 = 4.0 * np.sign(np.sin(2 * np.pi * np.log2(freqs / 200.0) * 1.5))
    tr15b = {'System Sum': tgt_like, 'FL Low': tgt_like + osc15, 'FR Low': tgt_like}
    sc15b = tune_scorecard(freqs, tr15b, tgt_like)
    print('TEST15b oscillating L/R (median blind spot):', sc15b)
    assert abs(sc15b['mid_balance_db']) < 0.5, 'median should read near-zero here (the blind spot)'
    assert sc15b['mid_balance_abs_rms_db'] > 2.5, 'abs-RMS must reveal the real mismatch the median hid'


    # ---- TEST17: sample-rate-aware delay conversion --------------------------
    s96 = ms_to_samples(6.52, 96000.0)
    s48 = ms_to_samples(6.52, 48000.0)
    print()
    print('TEST17 delay conversion: 6.52ms @ 96kHz=%.0f samples | @48kHz=%.0f samples (must NOT match)'
          % (s96, s48))
    assert abs(s96 - 626) < 1 and abs(s48 - 313) < 1
    assert abs(samples_to_ms(s96, 96000.0) - 6.52) < 1e-6
    # the exact failure mode this guards against: entering a 96kHz sample count
    # into a 48kHz DSP without reconversion doubles the real physical delay
    wrong_ms = samples_to_ms(s96, 48000.0)
    assert abs(wrong_ms - 13.04) < 0.01, 'sanity check on the double-delay failure mode itself'

    # ---- TEST18: driver excursion safety check -------------------------------
    safe = hpf_excursion_risk(80.0, 24.0, driver_fs_hz=32.0)
    risky = hpf_excursion_risk(35.0, 24.0, driver_fs_hz=32.0)
    gentle_ok = hpf_excursion_risk(30.0, 12.0, driver_fs_hz=25.0)
    gentle_risky = hpf_excursion_risk(20.0, 12.0, driver_fs_hz=25.0)
    print('TEST18 excursion check: 80Hz/24dB on Fs=32Hz -> risk=%s | 35Hz/24dB on Fs=32Hz -> risk=%s'
          % (safe['excursion_risk'], risky['excursion_risk']))
    assert not safe['excursion_risk'] and risky['excursion_risk']
    assert not gentle_ok['excursion_risk'] and gentle_risky['excursion_risk']


    # ---- TEST19: solo-level calibration ---------------------------------------
    A19 = np.full_like(freqs, 70.0)              # solo captured 8dB quieter than
    together19 = np.full_like(freqs, 70.0) + 8.0  # its true contribution to "together"
    cal = calibrate_solo_levels(freqs, A19, together19, (200, 2000))
    print()
    print('TEST19 solo-level calibration: offset=%.1fdB (expect +8) residual=%.2f'
          % (cal['level_offset_db'], cal['residual_rms_db']))
    assert abs(cal['level_offset_db'] - 8.0) < 0.1 and cal['residual_rms_db'] < 0.1

    # ---- TEST20: phase reliability score ---------------------------------------
    f20 = freqs[(freqs >= 300) & (freqs <= 3000)]
    clean_phase = -0.02 * f20                                    # pure delay, dead straight
    noisy_phase = clean_phase + 200.0 * np.sin(f20 / 60.0)         # reflection wiggle
    ph_clean_full = np.interp(freqs, f20, clean_phase)
    ph_noisy_full = np.interp(freqs, f20, noisy_phase)
    r_clean = phase_linearity_residual(freqs, ph_clean_full, (300, 3000))
    r_noisy = phase_linearity_residual(freqs, ph_noisy_full, (300, 3000))
    print('TEST20 phase reliability: clean=%.1fdeg (%s) | noisy=%.1fdeg (%s)'
          % (r_clean['rms_residual_deg'], r_clean['grade'],
             r_noisy['rms_residual_deg'], r_noisy['grade']))
    assert r_clean['trustworthy_for_timing'] and not r_noisy['trustworthy_for_timing']

    # ---- TEST21: complex vector averaging --------------------------------------
    base = np.ones_like(freqs, dtype=complex)
    comb1 = base * (1 + 0.3 * np.exp(1j * freqs / 200.0))   # position-specific comb
    comb2 = base * (1 + 0.3 * np.exp(1j * (freqs / 200.0 + 2.1)))
    comb3 = base * (1 + 0.3 * np.exp(1j * (freqs / 200.0 + 4.2)))
    avg = complex_vector_average([comb1, comb2, comb3])
    print('TEST21 vector avg: mean |avg-base| = %.3f (expect << 0.3, combing cancels)'
          % np.mean(np.abs(avg - base)))
    assert np.mean(np.abs(avg - base)) < 0.15

    # ---- TEST22: inert band check ----------------------------------------------
    buried = inert_band_check(target_driver_db=60.0, dominant_db=75.0)
    audible = inert_band_check(target_driver_db=72.0, dominant_db=75.0)
    print('TEST22 inert band: buried(15dB down)=%s | audible(3dB down)=%s'
          % (buried['inert'], audible['inert']))
    assert buried['inert'] and not audible['inert']

    # ---- TEST23: reaches-target-after-boost ------------------------------------
    r_ok = reaches_target_after_boost(current_db=70.0, target_db=74.0, proposed_boost_db=4.0)
    r_phase = reaches_target_after_boost(current_db=60.0, target_db=74.0, proposed_boost_db=6.0)
    print('TEST23 reaches target: ok-case short=%.1f (flag=%s) | phase-case short=%.1f (flag=%s)'
          % (r_ok['still_short_db'], r_ok['likely_phase_problem'],
             r_phase['still_short_db'], r_phase['likely_phase_problem']))
    assert not r_ok['likely_phase_problem'] and r_phase['likely_phase_problem']


    # ---- TEST24: null-boost guard on fit_peq ------------------------------------
    A24 = -peaking_db(freqs, 500.0, 1.2, 6.0)        # dip wanting a broad correction
    mask24 = ~((freqs >= 600.0) & (freqs <= 900.0))   # adjacent masked null

    def null_spill(bands):
        casc = cascade_db(freqs, bands)
        region = (freqs >= 600.0) & (freqs <= 900.0)
        return float(np.max(casc[region])) if len(bands) else 0.0

    bands_off, _ = fit_peq(freqs, A24, (200, 2000), n_bands_max=3, mask=mask24,
                          null_boost_penalty=0.0)
    bands_on, _ = fit_peq(freqs, A24, (200, 2000), n_bands_max=3, mask=mask24,
                         null_boost_penalty=3.0)
    spill_off, spill_on = null_spill(bands_off), null_spill(bands_on)
    print()
    print('TEST24 null-boost guard: spill OFF=%.2fdB (%d bands) | spill ON=%.2fdB (%d bands)'
          % (spill_off, len(bands_off), spill_on, len(bands_on)))
    assert spill_off > 2.0, 'setup check: guard-off case should actually spill into the null'
    assert spill_on < spill_off, 'null-boost guard did not reduce spillover into the masked region'


    # ---- TEST25: gating-frequency-limit (HolmImpulse-verified formula) ---------
    # HolmImpulse's own documented example: a ~1m reflection path difference
    # (~2.91ms gate) gives "cannot trust below ~344 Hz". Verify our formula
    # against that real-world reference point, not just internal consistency.
    gate_ms25 = 1000.0 / 343.0   # the gate length implied by a 343 Hz limit
    f_min25 = gating_frequency_limit(gate_ms25)
    print()
    print('TEST25 gating limit: gate=%.2fms -> f_min=%.1fHz (HolmImpulse doc: ~344Hz for ~1m path)'
          % (gate_ms25, f_min25))
    assert abs(f_min25 - 343.0) < 0.5
    assert abs(min_gate_for_frequency(f_min25) - gate_ms25) < 1e-9, 'inverse function mismatch'
    # sanity: a shorter gate (closer reflection) raises the trustworthy floor
    assert gating_frequency_limit(1.0) > gating_frequency_limit(3.0)


    # ---- TEST26: crossover_confidence bundles the band-limited checks correctly
    A26 = np.ones_like(freqs, dtype=complex) * 10 ** (75 / 20)
    B26_healthy = np.exp(-1j * 2 * np.pi * freqs * 0.0003) * 10 ** (75 / 20)
    together_healthy = 20 * np.log10(np.abs(A26 + B26_healthy) + 1e-12)
    r_healthy = crossover_confidence(freqs, A26, B26_healthy, together_healthy, (50.0, 120.0))

    B26_bad = -A26   # antiphase everywhere -> real cancellation in-band
    together_bad = 20 * np.log10(np.abs(A26 + B26_bad) + 1e-12)
    r_bad = crossover_confidence(freqs, A26, B26_bad, together_bad, (50.0, 120.0))

    print()
    print('TEST26 crossover_confidence: healthy usable=%s cancelling=%s | bad usable=%s cancelling=%s'
          % (r_healthy['usable_for_crossover_decisions'], r_healthy['destructive_interference_in_band'],
             r_bad['usable_for_crossover_decisions'], r_bad['destructive_interference_in_band']))
    assert r_healthy['usable_for_crossover_decisions'] and not r_healthy['destructive_interference_in_band']
    assert r_bad['destructive_interference_in_band']

    # ---- TEST27: interaural_group_delay_ms -- split-side (one APF per side, at
    # DIFFERENT frequencies) must show a LARGER peak interaural GD than a single
    # APF on one side alone. This is the real-session finding that motivated the
    # function: don't assume "one APF per side" is automatically gentler on
    # imaging than stacking on one side, just because each filter looks modest.
    H_split_L = allpass_H(freqs, 173.4, 4.7)
    H_split_R = allpass_H(freqs, 402.8, 8.0)
    igd_split = interaural_group_delay_ms(freqs, H_split_L, H_split_R)

    H_single_L = allpass_H(freqs, 174.0, 2.0)
    igd_single = interaural_group_delay_ms(freqs, H_single_L, None)

    peak_split = float(np.max(np.abs(igd_split)))
    peak_single = float(np.max(np.abs(igd_single)))
    print('TEST27 interaural_group_delay_ms: split-side peak=%.1fms  single-side peak=%.1fms'
          % (peak_split, peak_single))
    assert peak_split > peak_single, 'split-side should show larger interaural GD in this scenario'
    # a branch with nothing added must contribute exactly zero group delay
    zero_gd = interaural_group_delay_ms(freqs, None, None)
    assert np.allclose(zero_gd, 0.0)


    # ---- TEST30: voicing layer (voice_target + measure_tilt) --------------------
    base27 = np.zeros_like(freqs)
    # tilt round-trips through measure_tilt, and midrange pivot is preserved
    voiced27 = voice_target(freqs, base27, tilt_db_per_oct=-0.9)
    mt27 = measure_tilt(freqs, voiced27)
    i1k = int(np.argmin(np.abs(freqs - 1000)))
    print()
    print('TEST30 voicing: applied -0.9 dB/oct -> measured %.2f | 1kHz pivot level %.3f'
          % (mt27['tilt_db_per_oct'], voiced27[i1k]))
    assert abs(mt27['tilt_db_per_oct'] - (-0.9)) < 0.1, 'tilt did not round-trip'
    assert abs(voiced27[i1k]) < 0.05, 'tilt pivot did not preserve midrange level'
    # a flat target correctly reads as too bright for a car (the feature's point)
    assert measure_tilt(freqs, base27)['tilt_db_per_oct'] > -0.8
    # bass shelf lifts LF, leaves the midrange alone
    bs27 = voice_target(freqs, base27, bass_shelf_db=3.0, bass_shelf_hz=100.0)
    i50 = int(np.argmin(np.abs(freqs - 50)))
    assert bs27[i50] > 2.0 and abs(bs27[i1k]) < 0.1, 'bass shelf shape wrong'
    # presence bell is local to its center
    pr27 = voice_target(freqs, base27, presence_db=2.0, presence_hz=3000.0)
    i3k = int(np.argmin(np.abs(freqs - 3000))); i300 = int(np.argmin(np.abs(freqs - 300)))
    assert abs(pr27[i3k] - 2.0) < 0.05 and abs(pr27[i300]) < 0.2, 'presence bell not local'


    # ---- TEST31: estimate_delay_xcorr recovers a known delay, matches search sign
    A28 = np.ones_like(freqs, dtype=complex) * 10 ** (75 / 20)
    B28 = np.exp(-1j * 2 * np.pi * freqs * 0.73 / 1000.0) * 10 ** (75 / 20)
    xc28 = estimate_delay_xcorr(freqs, A28, B28, (200.0, 8000.0), max_delay_ms=2.0)
    print()
    print('TEST31 xcorr: recovered=%.3fms (injected -0.73ms correction) conf=%.1f reliable=%s'
          % (xc28['delay_ms'], xc28['confidence_ratio'], xc28['reliable']))
    assert abs(xc28['delay_ms'] - (-0.73)) < 0.02, 'xcorr delay estimate off'
    assert xc28['reliable']
    # sign convention matches polarity_delay_search: applying xcorr's own delay_ms
    # via the SAME correction formula must land on the coherent ceiling
    B28_corrected = B28 * np.exp(-1j * 2 * np.pi * freqs * xc28['delay_ms'] / 1000.0)
    # sub-100us residual error (well under one 96kHz sample) shows as small ripple
    # right at the top of the band -- check a representative range at a tolerance
    # that reflects real-world usefulness, not idealized zero-error precision.
    check_band = (freqs >= 200) & (freqs <= 6000)
    corrected_db = 20 * np.log10(np.abs(A28 + B28_corrected)[check_band] + 1e-12)
    ceiling_db = 20 * np.log10(np.abs(A28)[check_band] + np.abs(B28)[check_band] + 1e-12)
    assert np.allclose(corrected_db, ceiling_db, atol=0.1), 'xcorr sign convention mismatch'

    # noisy/random phase (simulated bad capture) must read as unreliable, not confident-wrong
    rng28 = np.random.RandomState(0)
    B28_noisy = np.exp(1j * rng28.uniform(-np.pi, np.pi, len(freqs))) * 10 ** (75 / 20)
    xc28_noisy = estimate_delay_xcorr(freqs, A28, B28_noisy, (200.0, 8000.0), max_delay_ms=2.0)
    print('TEST28 xcorr on garbage phase: conf=%.1f reliable=%s (must be False)'
          % (xc28_noisy['confidence_ratio'], xc28_noisy['reliable']))
    assert not xc28_noisy['reliable']

    # ---- TEST32: polarity_delay_search's cross-check agrees on clean data ------
    r29 = polarity_delay_search(freqs, A28, B28, (200.0, 8000.0), max_delay_ms=2.0)
    print('TEST32 cross-check: grid=%.3fms xcorr=%.3fms agrees=%s'
          % (r29['delay_ms_B'], r29['xcorr_delay_ms'], r29['xcorr_agrees']))
    assert r29['xcorr_agrees']
    assert abs(r29['delay_ms_B'] - r29['xcorr_delay_ms']) < 0.05

    # ---- TEST33: lr_match_report flags a real L/R gap, clears on a match --------
    left33 = peaking_db(freqs, 1500.0, 2.0, 3.0)      # left channel +3dB bump @1.5k
    right33 = np.zeros_like(freqs)
    rep33 = lr_match_report(freqs, left33, right33, band=(300.0, 6000.0), flag_db=1.5)
    print('\nTEST33 lr_match_report (left +3dB@1.5k vs flat right):')
    print('  regions:', rep33['regions'], '| overall=%.2f dB | stable=%s' %
          (rep33['overall_mismatch_db'], rep33['stable']))
    assert not rep33['stable'] and len(rep33['regions']) >= 1
    r0 = rep33['regions'][0]
    assert abs(r0['peak_hz'] - 1500.0) < 1500.0 * 0.15
    assert r0['louder_side'] == 'left' and r0['peak_delta_db'] > 1.5

    rep33b = lr_match_report(freqs, left33, left33, band=(300.0, 6000.0), flag_db=1.5)
    assert rep33b['stable'] and rep33b['overall_mismatch_db'] < 0.05
    print('  identical L/R -> stable=%s overall=%.3f dB (exp ~0)' %
          (rep33b['stable'], rep33b['overall_mismatch_db']))

    # ---- TEST34: fit_peq partner matching -- closes an L/R gap that this
    # channel's own distance-to-target alone would never justify a band for ------
    partner34 = peaking_db(freqs, 1500.0, 2.0, 3.0)   # "left" ended up +3dB@1.5k
    dev_r34 = np.zeros_like(freqs)                     # "right" already matches target
    bands_off34, rep_off34 = fit_peq(freqs, dev_r34, (200.0, 6000.0), n_bands_max=3)
    print('\nTEST34 partner match: without partner_weight, right stays untouched:', bands_off34)
    assert len(bands_off34) == 0, 'right should not touch an already-flat curve on its own'

    # partner_weight=1.0 is deliberately NOT enough here -- the existing boost
    # tax (boost_penalty/selection_tax_weight) correctly resists a boost that
    # only helps partner-matching and does nothing for this channel's own
    # target accuracy. That resistance is a feature, not a bug: matching a
    # partner isn't free, and the caller must weight it high enough to say
    # "the image-stability payoff is worth it here."
    bands_on34, rep_on34 = fit_peq(freqs, dev_r34, (200.0, 6000.0), n_bands_max=3,
                                   partner_target_db=partner34, partner_weight=3.0,
                                   partner_band=(700.0, 5000.0))
    print('TEST34 partner match: with partner_weight=3, right gets:', bands_on34)
    print('  partner mismatch %.3f -> %.3f' %
          (rep_on34['partner_mismatch_before'], rep_on34['partner_mismatch_after']))
    assert len(bands_on34) >= 1, 'partner matching should justify a band here'
    assert rep_on34['partner_mismatch_after'] < 0.5 * rep_on34['partner_mismatch_before']

    right_corrected34 = dev_r34 + cascade_db(freqs, bands_on34)
    rep34_after = lr_match_report(freqs, partner34, right_corrected34, band=(300.0, 6000.0))
    print('  lr_match_report after partner match: stable=%s overall=%.2f dB' %
          (rep34_after['stable'], rep34_after['overall_mismatch_db']))
    assert rep34_after['overall_mismatch_db'] < 1.0, 'partner match should close most of the L/R gap'

    # ---- TEST35: spatial_consistency separates a real dip from a comb-filter
    # null that just happens to sit under the mic at one position ---------------
    real_dip35 = peaking_db(freqs, 300.0, 2.0, -6.0)      # holds at every position
    rng35 = np.random.RandomState(1)
    null_centers35 = [380.0, 415.0, 450.0, 415.0]         # wanders position to position
    positions35 = []
    for nc in null_centers35:
        noise = rng35.normal(0, 0.2, size=freqs.shape)
        positions35.append(real_dip35 + peaking_db(freqs, nc, 8.0, -8.0) + noise)
    sc35 = spatial_consistency(freqs, positions35, consistent_db=1.5, min_positions=3)
    i300_35 = int(np.argmin(np.abs(freqs - 300.0)))
    i415_35 = int(np.argmin(np.abs(freqs - 415.0)))
    print('\nTEST35 spatial_consistency: real dip@300Hz spread=%.2fdB mask=%s conf=%.2f | '
          'wandering null@415Hz spread=%.2fdB mask=%s conf=%.2f' %
          (sc35['spread_db'][i300_35], sc35['mask'][i300_35], sc35['conf'][i300_35],
           sc35['spread_db'][i415_35], sc35['mask'][i415_35], sc35['conf'][i415_35]))
    assert sc35['mask'][i300_35] and sc35['conf'][i300_35] > 0.7, \
        'real, position-invariant dip should stay trusted'
    assert not sc35['mask'][i415_35] and sc35['conf'][i415_35] < 0.5, \
        'position-varying null should be excluded/down-weighted'

    # too few positions must refuse outright rather than silently trust a
    # single-position measurement it cannot actually validate
    try:
        spatial_consistency(freqs, positions35[:2], min_positions=3)
        raise AssertionError('spatial_consistency accepted too few positions')
    except ValueError:
        pass
    print('  <3 positions correctly rejected')

    # ---- TEST36: predicted_vs_measured closes the predict -> re-measure loop,
    # correctly tolerating a broadband level offset (different playback volume)
    # rather than mistaking it for a tuning result -------------------------------
    rng36 = np.random.RandomState(3)

    # a real, fillable dip: corrected, re-measured 1.5dB quieter + small noise
    before36a = peaking_db(freqs, 300.0, 2.0, -6.0)
    band36a = [(300.0, 2.0, 6.0)]
    after36a = (before36a + cascade_db(freqs, band36a) - 1.5 +
               rng36.normal(0, 0.3, len(freqs)))

    # an interference null 'corrected' with a boost that never lands
    # acoustically (measured stays ~unchanged despite the predicted lift)
    before36b = peaking_db(freqs, 415.0, 6.0, -8.0)
    band36b = [(415.0, 6.0, 5.0)]
    after36b = before36b - 1.5 + rng36.normal(0, 0.3, len(freqs))

    r36a = predicted_vs_measured(freqs, before36a, after36a, band36a)
    r36b = predicted_vs_measured(freqs, before36b, after36b, band36b)
    print('\nTEST36 predicted_vs_measured:')
    print('  real dip, -1.5dB quieter re-measure:', r36a['level_offset_db'], r36a['bands'])
    print('  interference null, boost never lands:', r36b['level_offset_db'], r36b['bands'])
    assert abs(r36a['level_offset_db'] - (-1.5)) < 0.3, 'should recover the injected level offset'
    assert r36a['bands'][0]['verdict'] == 'confirmed', \
        'a real correction should be confirmed despite the level offset, not flagged'
    assert r36b['bands'][0]['verdict'] == 'reverted_recommended', \
        'a boost that never landed acoustically should be flagged for reconsideration'

    # low confidence in the region must override to inconclusive even when the
    # numbers alone would otherwise say "confirmed"
    conf36 = np.full_like(freqs, 0.05)
    r36c = predicted_vs_measured(freqs, before36a, after36a, band36a, conf=conf36)
    assert r36c['bands'][0]['verdict'] == 'inconclusive'
    print('  low-confidence region correctly overridden to inconclusive')

    # ---- TEST37: minphase Nyquist guard (silent-wrong-answer prevention) ----
    # Before 2026-07-31 an axis reaching past the assumed Nyquist was silently
    # CLAMPED to flat phase, which excess_gd_mask reads as "perfectly
    # minimum-phase" = safe to EQ, on data that doesn't exist. Fail loudly.
    f37 = np.geomspace(20.0, 40000.0, 800)
    mag37 = peaking_db(f37, 1000.0, 2.0, 6.0)
    try:
        minphase_from_mag(f37, mag37)          # default fs=48k -> Nyquist 24k
        raise AssertionError('minphase_from_mag must reject an axis above Nyquist')
    except ValueError as e:
        assert 'Nyquist' in str(e)
    mp37 = minphase_from_mag(f37, mag37, fs=2.2 * 40000.0)
    above37 = f37 > 24000.0
    assert not np.allclose(mp37[above37], 0.0), 'above-Nyquist phase must be real, not flat'
    gd37, mask37 = excess_gd_mask(f37, mag37, np.rad2deg(mp37))
    assert mask37.all(), 'a pure minimum-phase input must classify as fully EQ-able'
    print('\nTEST37 minphase Nyquist guard: rejects over-range axis, auto-rate '
          'handles 40 kHz export, min-phase input still classifies EQ-able')

    # ---- TEST38: fit_peaking_to_shelf recovers a known LS+HS pair -------------
    # Same reference case (values and tolerances) the sibling Alpine tool this
    # was generalized from used for its own headless self-check -- confirms
    # the ported math + scipy-DE optimizer reproduce that result.
    shelves38 = [('high', 10000.0, 0.71, 3.28), ('low', 8644.0, 0.71, -4.78)]
    bands38, rep38 = fit_peaking_to_shelf(
        shelves38, 4, (3000.0, 20000.0), q_lim=(0.404, 6.0), fs=96000.0, seed=3)
    print('\nTEST38 fit_peaking_to_shelf (HS 10000/0.71/+3.28 + LS 8644/0.71/-4.78, '
          '4 PK, 3k-20k, 96 kHz):')
    for F, Q, G in bands38:
        print('   PK  %6.0f Hz   %+.2f dB   Q %.3f' % (F, G, Q))
    print('   rms=%.3f dB  max=%.3f dB  dropped=%d' %
          (rep38['rms_db'], rep38['max_err_db'], rep38['dropped']))
    assert rep38['rms_db'] < 0.05, 'fit_peaking_to_shelf RMS too high'
    assert rep38['max_err_db'] < 0.20, 'fit_peaking_to_shelf max error too high'

    print('\nALL TESTS PASSED')
