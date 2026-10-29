# `tunelib.py` — functions for ad-hoc analysis

Use these only when no pipeline command covers the question, and say so.
Put `scripts/` on the path first: `sys.path.insert(0, r'<skill-dir>/scripts')`.

`tunelib.py` is the verified analysis and DSP core (self-test: `python
scripts/tunelib.py` → `ALL TESTS PASSED`). This table is a lookup, not the
rationale. Read the methodology section before using a function for the first
time in a session.

| Function(s) | For | Ref |
|---|---|---|
| `voice_target`, `measure_tilt` | voicing layer (tilt/bass/presence/air) | §Voicing |
| `fit_peq`, `fit_peq_robust` (+`mask`/`conf`/`null_boost_penalty`/`partner_target_db`) | single- or multi-position PEQ optimizer, restraint & L/R matching | §Restraint, §Imaging |
| `interference_audit` | real dip vs. destructive summation | §The interference audit |
| `crossover_confidence` | one band-limited crossover go/no-go | §The crossover action-ladder |
| `polarity_delay_search`, `estimate_delay_xcorr` | cross-checked delay search | §The crossover action-ladder |
| `delay_sweep`, `overlap_weighted_delay_gain` | in-band-only delay search (run alongside `polarity_delay_search` whenever either driver is band-limited — its damage-band safety net can hide a real gain there); maximin across multiple sessions; flags cycle-ambiguous results | §When `polarity_delay_search` says |
| `spatial_consistency`, `complex_vector_average` | multi-position averaging | §Multi-position variance |
| `phase_linearity_residual` | single-position phase reliability | §Quantify single-position phase reliability |
| `prediction_confidence` | do complex solos reproduce the measured pair sum? gates every phase decision (step 2) | §Quantify single-position phase reliability |
| `excess_gd_mask` | minimum-phase / EQ-ability classifier | §Minimum-phase |
| `excess_phase_fields` + `boost_gate_verdict` / `gate_boost_bands` | is a specific BOOST pushing gain into a cancellation? (ALLOW/WARN/BLOCK; specific, not sensitive — ALLOW proves nothing, and it needs UNSMOOTHED data) | §The boost gate |
| `lr_match_report` | L/R image-stability diagnostic | §Imaging |
| `source_level_audit`, `source_bandwidth_limits` | is the signal ENTERING the DSP level-independent? (cannot attribute to the source from an acoustic capture — see the docstring) | §Audit the source |
| `band_itd_ild`, `image_pull` | where the phantom image sits vs FREQUENCY (inter-channel model: ~1 ms or ~16 dB = full shift, cues trade); `smeared` means no single delay or trim fixes it | §Image position is frequency-dependent |
| `centre_steering` | centre the image at an off-centre seat: level-only vs far-side time lead + smaller trim, with the robustness trade | §Placing the phantom centre |
| `held_out_band_validation`, `eq_dig_depth` | leave-one-position-out check of a multi-position proposal: per band stability, held-out help and APPLY / REVIEW / DO NOT APPLY; dug depth = the new hole an EQ digs below target | §Multi-position variance |
| `delay_consensus` | one delay from four estimators with agreement, confidence, and a gross-timing guard (refuses when the energy arrives several periods away) | §Reading a junction |
| `probe_variants`, `chain_response` | what-if: candidate delay / polarity / Phase angle / all-pass / PEQ evaluated at EVERY junction it touches, before anything is written | §A channel hands over twice |
| `junction_phase_score`, `junction_sum_loss` | one crossover's phase alignment (both polarities, flip margin, lobe margin) and how far its sum falls short of coherent | §Reading a junction |
| `helix_phase_rotation`, `helix_phase_rotation_H`, `phase_control_check` | PC-Tool's channel Phase control: the Q=1 AP2 an angle builds at the channel's crossover, and a check that this unit builds it (two solo sweeps) | helix_hardware.md |
| `predicted_vs_measured` | predict → re-measure loop (step 7) | §Verification & honesty |
| `inert_band_check`, `reaches_target_after_boost` | sanity checks before trusting a band | §Two checks |
| `gating_frequency_limit`, `gating_warning` | gated-capture trust floor | §Sweep capture setup |
| `calibrate_solo_levels` | fix mismatched solo test levels | §Sweep capture setup |
| `anchor_sensitivity_report` | is a feature's magnitude an anchor artifact? | §Deviation analysis |
| `causal_ab_delta` | score a causal A/B — no target, no re-anchoring | §Deviation analysis |
| `mmm_overrides_fixed_point` | forbidden-inference guard (fixed-point can't beat MMM) | §Measurement method selection |
| `detect_duplicate_traces` | catch a re-exported file double-counted as a session | §Analysis traps |
| `historical_repeatability` | stable-near-zero ≠ unreliable, across sessions (NOT a universal SD floor — see its docstring) | §Analysis traps |
| `models_discriminable` | don't prefer the smaller residual unless the gap beats the data's own uncertainty | §Model-discrimination gate |
| *(decay/ringing + distortion axes — when EQ isn't the right tool)* | waterfall/spectrogram, THD | §Beyond magnitude |
| `tune_scorecard` (`_abs_rms_db` fields catch what a signed median can hide), `headroom_report` (clip_risk is PEQ-only — check the real output level, it's often a false alarm), `compression_check` | scoring, clip risk, level sanity | — |
| `hpf_excursion_risk` | driver excursion check (needs a supplied Fs) | — |
| `ms_to_samples`, `samples_to_ms` | sample-rate-aware delay conversion | — |
| `validate_peq_band` | hardware gain/Q limits | — |
| `allpass_fil_str`, `allpass1_fil_str`, `shelf_fil_str` | filter-XML writers | §Shelf cookbook, §All-pass cookbook |
