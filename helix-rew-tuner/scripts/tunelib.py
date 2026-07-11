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
    (that's the definition of minimum phase)."""
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

def excess_gd_mask(freqs, spl_db, phase_deg, flat_ms=1.0, smooth_oct=1 / 6.0):
    """The EQ-ability classifier. Inputs: single-position REW text export WITH
    phase (freq, SPL, phase columns). Returns (excess_gd_ms, eqable_mask).
    REW doctrine: flat excess GD = minimum phase = EQ WORKS THERE; wild excess-GD
    swings (usually at sharp dips) = non-minimum-phase = EQ CANNOT FIX. `flat_ms`
    = how far excess GD may deviate from its local median and still count flat.
    Note: an overall time-of-flight offset only adds a CONSTANT GD slope, which the
    local-median comparison ignores by construction."""
    ph = np.unwrap(np.deg2rad(phase_deg))
    mp = minphase_from_mag(freqs, spl_db)
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
            null_boost_penalty=0.8, verbose=False):
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

    Returns (bands, report) - bands as [(F, Q, G), ...] rounded to hardware
    steps (0.25 dB gain), report dict with before/after scores.
    """
    from scipy.optimize import least_squares

    sel = (freqs >= fit_band[0]) & (freqs <= fit_band[1])
    if mask is not None:
        sel &= mask
    fsel = freqs[sel]
    w = audibility_weight(fsel)
    if conf is not None:
        w = w * np.clip(conf[sel], 0.0, 1.0)     # continuous confidence down-weight

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
        return np.concatenate([r, penalties(bands)])

    def score_of(params):
        bands = [(10 ** params[3 * i], params[3 * i + 1], params[3 * i + 2])
                 for i in range(len(params) // 3)]
        full = dev_db + cascade_db(freqs, bands)
        return audibility_score(freqs, full, band=fit_band, mask=mask, conf=conf)

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
        return score_of(params) + selection_tax_weight * tax + null_cost

    base_score = audibility_score(freqs, dev_db, band=fit_band, mask=mask, conf=conf)
    params = np.array([])
    lo_f, hi_f = np.log10(fit_band[0] * 1.02), np.log10(fit_band[1] * 0.98)
    cur_score = base_score
    cur_select_score = base_score

    for k in range(n_bands_max):
        # seed the next band at the biggest remaining weighted, smoothed bump
        bands_now = [(10 ** params[3 * i], params[3 * i + 1], params[3 * i + 2])
                     for i in range(len(params) // 3)]
        res_now = erb_smooth(freqs, dev_db + cascade_db(freqs, bands_now))
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
        new_score = score_of(fit.x)
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
        sum(([np.log10(F), Q, G] for F, Q, G in bands), []), dtype=float)) if bands else base_score
    return bands, {'score_before': round(base_score, 3),
                   'score_after': round(final, 3),
                   'selection_score_before': round(base_score, 3),
                   'selection_score_after': round(final_tax, 3),
                   'bands_used': len(bands)}

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
    check to the driver's passband. Returns a dict."""
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
    """Wide, confidence-weighted median target anchor with fallbacks."""
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
# 3d) POLARITY/DELAY SEARCH -- added 2026-07-03. Completes the doctrine ladder in
# code: polarity -> delay come BEFORE any APF (we had optimize_allpass but not
# the cheaper rungs below it, which was inconsistent). Same inputs (complex solo
# captures w/ shared time-zero) and the same gap-to-coherent-ceiling score as
# optimize_allpass, so results are directly comparable. Run THIS first; only if
# `residual_needs_apf` is True has an APF earned consideration.
def polarity_delay_search(freqs, driver_a, driver_b, band, max_delay_ms=1.5,
                          steps=121, damage_band=(60.0, 16000.0), damage_free_db=0.5):
    """Search polarity (binary, on B) x local delay (on B, +ve = B later) for the
    best summed response in `band`. Candidate finder, not a finalizer: apply the
    winning polarity/delay in PC-Tool (delay via the TA UI -- Python still never
    writes <T> tags), then re-measure the together trace to confirm.
    SIGN NOTE: delay_ms_B < 0 means B must arrive EARLIER, which hardware can't
    do -- apply +|delay| to the OTHER branch instead (keep its pair's internal
    offsets intact), exactly like the doc's negative-delay TA rule."""
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
    if 'FL High' in traces and 'FR High' in traces:
        b = erb_smooth(freqs, traces['FL High'] - traces['FR High'])
        s = (freqs >= tw_bal_band[0]) & (freqs <= tw_bal_band[1])
        out['tweeter_balance_db'] = round(float(np.median(b[s])), 2)
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
    use THIS as the real confidence number, not the raw pre-fit deviation)."""
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


    # ---- TEST27: voicing layer (voice_target + measure_tilt) --------------------
    base27 = np.zeros_like(freqs)
    # tilt round-trips through measure_tilt, and midrange pivot is preserved
    voiced27 = voice_target(freqs, base27, tilt_db_per_oct=-0.9)
    mt27 = measure_tilt(freqs, voiced27)
    i1k = int(np.argmin(np.abs(freqs - 1000)))
    print()
    print('TEST27 voicing: applied -0.9 dB/oct -> measured %.2f | 1kHz pivot level %.3f'
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

    print('\nALL TESTS PASSED')
