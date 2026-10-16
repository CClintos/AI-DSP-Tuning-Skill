# Tools and reference lookup

Read the entries needed for the current stage. All script paths below are
relative to the skill directory, not this references folder. The canonical
sequence and write requirements live in [core_workflow.md](core_workflow.md).

## The scripts (in `scripts/`)

Run these with the user's files; they are the deterministic layer. Commands
below are written relative to the skill directory (the folder holding
`SKILL.md` and `requirements.txt`) — run them from there, or prefix the
skill directory's absolute path. For ad-hoc Python that imports them, put
`scripts/` on the path first: `sys.path.insert(0, r'<skill_dir>/scripts')`.

- **`preflight.py`** — read-only install check. Run `python scripts/preflight.py
  --json` before first use in a new environment; it reports Python, NumPy,
  SciPy, required skill paths, actionable failures, and overall readiness.
  Install declared dependencies with `python -m pip install -r requirements.txt`.
- **`benchmark.py`** — deterministic synthetic robust-fitting regression gate.
  Run `python scripts/benchmark.py --json`; any failed declared guard exits nonzero.
- **`tunelib.py`** — the verified analysis + DSP core (import it). Pure,
  deterministic, self-tested (`python scripts/tunelib.py` → `ALL TESTS PASSED`). This
  is a lookup table, not the rationale — each function's *why* and *when*
  lives in `references/methodology.md` (section noted below; read that
  before using a function you haven't used yet this session):

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
  | `tune_scorecard` (`_abs_rms_db` fields catch what a signed median can hide), `headroom_report` (pass confirmed `fs`; clip_risk is PEQ-only — check the real output level), `compression_check` | scoring, clip risk, level sanity | — |
  | `hpf_excursion_risk` | driver excursion check (needs a supplied Fs) | — |
  | `ms_to_samples`, `samples_to_ms` | sample-rate-aware delay conversion | — |
  | `validate_peq_band` | hardware gain/Q limits | — |
  | `allpass_fil_str`, `allpass1_fil_str`, `shelf_fil_str` | filter-XML writers | §Shelf cookbook, §All-pass cookbook |
- **`afpx.py`** — decode/inspect a `.afpx`, **auto-detect channel roles from
  crossovers**, and lint writes (`roundtrip_lint`). `python scripts/afpx.py inspect <file>`.
  Direct `afpx.py` write helpers are implementation/reference only; never call
  them as a user-facing file-output route.
  `channels()[ch]['slots']` gives every filter's stable `slot_index`/`fn`;
  the internal `write_filter_slot`/`verify_slot_write` pair edits an EXISTING filter by
  `(channel, slot)` — the only safe way to re-centre, relax or remove one,
  since matching by nearest frequency is ambiguous on real tunes (see
  `afpx_format.md`). Editing an existing band still needs the same measured
  justification and per-change confirmation as adding one.
  `read_output_levels`/`write_output_trim`/`verify_output_trim_write` handle
  per-channel **output level** (`<Vol>`, linear amplitude — read
  `afpx_format.md` for the fewer-Vol-tags-than-channels gotcha). Reading it is
  mandatory before reporting any `headroom_report` clip risk (that flag is
  PEQ-only and usually a false alarm once the existing trim is counted);
  its internal writer is attenuation-only by construction (≤0 dB, ≥−6 dB,
  relative to current). `python scripts/afpx.py selftest` self-tests these implementation
  primitives on synthetic XML; it does not replace the plan/apply boundary.
- **`measure.py`** — load REW text exports (robust) or `.mdat` (validate first),
  resample onto a common grid, load target curves.
- **`pipeline.py`** — one deterministic entry point for step 2-3's analysis
  instead of a bespoke `python -c` each session. `python scripts/pipeline.py analyze
  --measurement <export.txt> --target <file|default> [--positions ... |
  --solo-a/--solo-b/--together --pair-band LO HI | --gate-ms N | --afpx
  <file> | --voice tilt=X bass=Y presence=Z air=W]` → one JSON report: tilt,
  threshold-flagged deviation regions (not raw per-bin arrays), plus
  `spatial_consistency`/`interference_audit`/`crossover_confidence`/gating
  results for whichever inputs were given. When the measurement carries phase,
  the report also includes `boost_gate` — a per-dip ALLOW/WARN/BLOCK phase
  verdict for every `boost_needed` region, so a boost that would be pushing
  gain into a cancellation is flagged before it reaches a plan (`--trust-band
  LO HI` sets the driver's passband explicitly). Before quoting a verdict read
  methodology.md §The boost gate, which covers why ALLOW is not a certificate.
  Analysis writes nothing to a DSP file.
  `pipeline.py propose` (same inputs, plus required `--dsp-rate <Hz>` for the
  confirmed DSP internal rate) turns that analysis into a deterministic PEQ
  proposal — see step 4. Pass that rate as `fs` for ad-hoc filter fitting and
  prediction too; it is separate from REW's capture sample rate.
  Two further read-only commands share the same loader and conventions:
  `pipeline.py source-audit --at ref.txt=0 down6.txt=-6 ...` asks whether the
  signal ENTERING the DSP is level-independent (read §Audit the source, first —
  and note it will not attribute a finding to the source without `--electrical`),
  and `pipeline.py imaging --solo-l L.txt --solo-r R.txt [--near-side right|left]`
  reports where the image sits as a function of frequency — see §Image position
  is frequency-dependent, for how to read a `smeared` verdict — and, with
  `--near-side`, the options for centring it. `pipeline.py junction --lower A.txt
  --upper B.txt --crossover HZ [--direct-sound]` reads one crossover's phase
  score, sum loss and a four-estimator `delay_consensus` (§Reading a junction,).
  `pipeline.py probe --spec probe.json` evaluates candidate changes (delay,
  polarity, Phase angle, all-pass, PEQ) at every junction they touch and
  returns a verdict per candidate — ask it instead of estimating a change's
  effect (§A channel hands over twice,). Give it `pairs` (left/right drivers)
  and `positions` (2-3 head positions) and it only calls a change a
  `candidate` when no junction, no L/R balance and no position gets worse; it
  also models crossover what-ifs, advisory only (§Crossover what-ifs,).
  `pipeline.py refine` re-works the PEQ bank a tuned car was measured through
  instead of stacking new bands (§Refine the tune you have,), and `pipeline.py
  ab-make` / `ab-result` run a blind, loudness-matched listening comparison
  (§Judge by ear only at matched loudness,). For MMM data, `--capture mmm`
  plus `--ambient` and `--cancel-check` on analyze/propose/refine, and
  `pipeline.py mmm-compare` (default balanced: target balance against an
  unchanged measured reference, with output/shape guards) and `pipeline.py
  lr-match --target <curve>` (match only by correcting target-supported
  excess, never copying a dip onto the good side), support tonal decisions
  without inferring phase
  (§MMM-first tuning,). `--capture-profile` records and checks the REW setup;
  `pipeline.py verify` checks a written change against the re-captures, and
  `pipeline.py voice-variants` builds one-shelf voicing variants for a blind
  A/B. With 3+ positions, `propose` validates
  itself leave-one-position-out: each band carries APPLY / REVIEW / DO NOT
  APPLY, and DO NOT APPLY bands land in `rejected`. Label the positions with
  `--sittings` so each fold withholds a whole sitting (§Held-out by sitting,),
  and pass `--session-tune <afpx>` so the car's recorded guards apply
  (§Vehicle guards,); `refine` reads them from its `--afpx` sidecar. **Every AFPX write must use this same CLI:** first run `pipeline.py plan`
  and review `references/tune_plan_schema.md`, then populate the plan's
  `source_sha256`, distinct not-yet-existing `output_path`, edits, and
  per-edit `confirmations`; finally run `pipeline.py apply`. Apply exclusively
  creates a new output, re-decodes it, and returns the verification manifest.
  Keep phase-domain edits (delay, Phase control or T=19/20 APF) separate from
  EQ-domain edits (T=17 PEQ or T=3/4 shelves), with remeasurement between stages.
  Follow the core workflow's order: driver-local EQ, alignment, final tone.
  `pipeline.py session check|save` reads and records the intake sidecar (step
  1). `python scripts/pipeline.py selftest` self-tests analysis and
  documentation routing on synthetic fixtures.
- **`rew_api.py`** — READ-ONLY bridge to a running REW 5.40+ (Preferences → API;
  default `127.0.0.1:4735`). `python scripts/rew_api.py list` shows measurements
  with timing reference and SNR; `rew_api.py export "FL tweeter" --out fl_tw.txt`
  writes a text export every tool reads, and `--direct-sound` builds the
  8-cycle direct-sound response from REW's impulse response on the shared
  timing-reference axis — no manual exports, no WAV peak-alignment trap. It
  never triggers sweeps or changes anything in REW. Prefer it when REW is open.
- **`decay.py fdw <ir.txt> --out DRIVER_direct.txt`** — the DIRECT-SOUND
  response through an 8-cycle frequency-dependent window from the driver's
  arrival, written as a REW-style text export every other tool reads. Use it
  for imaging and junction TIMING decisions above ~500 Hz (the ear places a
  source on the first arrival); keep full-window / spatial-average data for
  tone. Prefer REW *text* IR exports — they carry the shared time base; a WAV
  does not. See §Two windows,
- **`decay.py reflections <ir.wav>`** — secondary arrivals from the impulse
  response: delay, level, path-length difference, and the comb each one must
  produce. `--dips 340 1020 ...` tests those predictions against the dips you
  actually measured, which is what turns an arrival into a diagnosis. A
  reflection is not an EQ problem — read §Reflections, before spending a filter
  on a dip you haven't explained.
- **`decay.py`** — waterfall/CSD decay analysis on an impulse-response `.wav`
  (REW "Export IR" or similar), for when a problem is ringing/decay-shaped
  rather than magnitude-shaped (see §Beyond magnitude, methodology.md).
  `python scripts/decay.py t20 <ir.wav>` (RT20-style decay time per band),
  `python scripts/decay.py csd <ir.wav>` (cumulative spectral decay slices),
  `python scripts/decay.py compare <a.wav> <b.wav>` (before/after). Self-contained CLI, no
  `tunelib`/`afpx` dependency.
- **`repeatability.py`** — build a same-sitting noise-floor from repeat
  sweeps and check a proposed deviation against it, when you need a real
  measured floor instead of `historical_repeatability`'s cross-session
  heuristic. `python scripts/repeatability.py floor <file> [<file> ...] [--json
  out.json]`, then `python scripts/repeatability.py check --floor <floor.json> --dev
  <hz:db> [...]`. Imports `measure.py` for loading.
- **`pct6.py`** — **BETA, personal-use only** — decode and source-bound encode
  `.pct6` (DSP PC-Tool 6, no-password saves only). `decode()` gives a byte-
  preserving (latin-1) text view safe to pass straight into `afpx.py`'s
  read/inspection functions. `decode_bytes()` gives raw bytes for read-only
  inspection. File creation is only through `write_preserving_crossovers`
  (or the source-requiring `encode` CLI), which compares every crossover at
  its original channel/slot and exclusively creates a new output. **Never decode with `errors='replace'` for anything
  that gets written back** — real files carry binary-ish attributes (e.g.
  `AV=`) that aren't reliably valid UTF-8, and `'replace'` silently
  corrupts them on re-encode. **Read `references/pct6_format.md` before
  using this on a real file** — the container key is version-fragile and
  unverified beyond PC-Tool 6.01.08/6.03.04.
- **`alpine_jssh.py`** — **BETA, personal-use only** support for the different-
  vendor Alpine `.jssh` format. Keep Alpine work in this skill, but read
  `references/alpine_jssh_format.md` in full before inspecting or changing a
  real preset; that reference owns the verified model scope, Alpine-specific
  limits, writable Q values, unsafe channel-gain caveat, edit-preservation
  rules, mandatory real-file preflight, and hardware read-back requirement.
  Alpine crossover fields are read-only: there are no HPF/LPF frequency, type,
  or slope setters, and its low-level writer/verifier refuse those byte offsets.

For anything not covered by a script, write short Python that imports these —
never hand-guess `.afpx`/`.pct6` bytes or filter codes.

## Reference files (read as needed)

- **`references/afpx_format.md`** — the exact `.afpx` binary + filter-code spec.
  Read before any write. (Verified on P SIX DSP MK2; see model caveat.)
- **`references/pct6_format.md`** — the `.pct6` container format, BETA caveats,
  and the version-fragility/no-password limitations. **Read this in full
  before touching a `.pct6` file** — it's held to a much lower confidence bar
  than `.afpx`.
- **`references/alpine_jssh_format.md`** — the Alpine `.jssh` container format,
  full field table with per-field confidence markers, the 13-point Q lookup
  table, and Alpine's hardware limits. **Read in full before touching a
  `.jssh` file.**
- **`references/methodology.md`** — how to decide what to fix: deviation analysis,
  the interference audit, the crossover action-ladder, shelf and all-pass
  cookbooks, imaging, and the restraint rules. Read before proposing edits.
  It's long — use its anchor-linked "Contents" section to jump to the part you
  need.
- **`references/helix_hardware.md`** — filter modes, hardware limits, model notes.
