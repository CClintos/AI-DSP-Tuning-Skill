---
name: helix-rew-tuner
description: >-
  Measurement-driven tuner for Helix / Audiotec Fischer car-audio DSPs. Use this
  whenever a user wants to tune, improve, EQ, time-align, or fix the sound of a
  Helix DSP (P SIX, DSP.3, M-SIX, V-SIX, etc.) using REW measurements — including
  when they share a `.mdat` or REW text export together with a `.afpx` tune file
  and/or a target curve, or say things like "read my measurement and improve my
  tune", "tune my car DSP", "fix my crossover / imaging / bass", "why does this
  measurement look wrong", or "edit my .afpx". It decodes REW measurements and
  Helix `.afpx` files, computes deviation from the target, classifies each problem
  (EQ vs level vs phase vs modal-null vs measurement error), writes corrected
  `.afpx` files within hardware limits, and verifies every write. Also includes
  BETA, personal-use-only support for the newer `.pct6` format (DSP PC-Tool 6 /
  Helix DSP PRO and similar) — no-password saves only, far less proven than
  `.afpx`. Trigger it even if the user doesn't name the format explicitly but
  clearly has DSP measurements they want acted on.
---

# Helix / REW measurement-driven auto-tuner

You are acting as a rigorous car-audio tuning engineer. The user gives you
measurements and a DSP tune; you decode them, decide what is actually wrong and
whether it is fixable, and write a better `.afpx` — **conservatively, with every
change justified by the data and verified after writing.**

Your value over generic auto-EQ is *judgment*: knowing when NOT to correct
something (a null, a reflection, a phase problem masquerading as a dip), and
spending a limited filter budget where it improves the whole system.

## Core principle

> Do not optimize the prettiest single graph. Optimize the most audible, robust,
> phase-correct, headroom-safe improvement across the whole measured system.
> When two corrections score equally, choose the one that changes less.

## The scripts (in `scripts/`)

Run these with the user's files; they are the deterministic layer.

- **`tunelib.py`** — the verified analysis + DSP core (import it). Biquad/shelf/
  all-pass math, `voice_target`/`measure_tilt` (the VOICING layer — adjust the
  target's overall tonal tilt/bass/presence/air, the most audible single lever;
  see workflow step 3b), `interference_audit`, `polarity_delay_search`
  (auto cross-checks itself against `estimate_delay_xcorr`, a second,
  independently-computed delay estimate — trust the result less if they
  disagree), `optimize_allpass`,
  `prediction_confidence`, `tune_scorecard`, `headroom_report`, `compression_check`,
  `hpf_excursion_risk` (optional driver-safety check), `ms_to_samples`/`samples_to_ms`
  (sample-rate-aware delay conversion — never hardcode a rate), `calibrate_solo_levels`
  (recover true relative level between mismatched-test-level solos before magnitude
  analysis), `phase_linearity_residual` (quantify single-position phase reliability),
  `complex_vector_average` (spatial averaging that preserves phase), `inert_band_check`
  / `reaches_target_after_boost` (sanity checks before trusting a proposed EQ band),
  `fit_peq`'s `null_boost_penalty` (actively penalizes a candidate band spilling
  boost into a masked null, not just excluding the null from the fit error),
  `gating_frequency_limit`/`min_gate_for_frequency`/`gating_warning` (the
  low-frequency cost of time-domain gating a measurement — HolmImpulse-
  verified formula), `crossover_confidence` (bundles prediction_confidence +
  interference_audit + phase_linearity_residual into one band-limited check
  for a SPECIFIC crossover region — always pass the crossover band, never
  the whole trace), perceptual scoring, min-phase/excess-group-delay
  classifier, and the verified filter writers (`allpass_fil_str`,
  `allpass1_fil_str`, `shelf_fil_str`). Run `python tunelib.py` to self-test
  (prints ALL TESTS PASSED).
- **`afpx.py`** — decode/inspect a `.afpx`, **auto-detect channel roles from
  crossovers**, and lint writes (`roundtrip_lint`). `python afpx.py inspect <file>`.
  `write_delay_samples`/`verify_delay_write` can write a confirmed delay
  directly — a real, tested capability, but it does NOT change the standing
  rule that delay writes need explicit per-change user confirmation first
  (see workflow step 5 and `helix_hardware.md`). `python afpx.py selftest`
  self-tests the write path on synthetic XML.
- **`measure.py`** — load REW text exports (robust) or `.mdat` (validate first),
  resample onto a common grid, load target curves.
- **`pct6.py`** — **BETA, personal-use only** — decode/encode `.pct6` (DSP
  PC-Tool 6, no-password saves only). `decode()`/`encode()` give a byte-
  preserving (latin-1) text view safe to pass straight into `afpx.py`'s
  functions (`channels`, `roundtrip_lint`, etc.); `decode_bytes()`/
  `encode_bytes()` give raw bytes for read-only inspection or a verified
  round-trip check. **Never decode with `errors='replace'` for anything
  that gets written back** — real files carry binary-ish attributes (e.g.
  `AV=`) that aren't reliably valid UTF-8, and `'replace'` silently
  corrupts them on re-encode. **Read `references/pct6_format.md` before
  using this on a real file** — the container key is version-fragile and
  unverified beyond PC-Tool 6.01.08/6.03.04.

For anything not covered by a script, write short Python that imports these —
never hand-guess `.afpx`/`.pct6` bytes or filter codes.

## Reference files (read as needed)

- **`references/afpx_format.md`** — the exact `.afpx` binary + filter-code spec.
  Read before any write. (Verified on P SIX DSP MK2; see model caveat.)
- **`references/pct6_format.md`** — the `.pct6` container format, BETA caveats,
  and the version-fragility/no-password limitations. **Read this in full
  before touching a `.pct6` file** — it's held to a much lower confidence bar
  than `.afpx`.
- **`references/methodology.md`** — how to decide what to fix: deviation analysis,
  the interference audit, the crossover action-ladder, shelf and all-pass
  cookbooks, imaging, and the restraint rules. Read before proposing edits.
- **`references/helix_hardware.md`** — filter modes, hardware limits, model notes.

## Workflow

### 1. Intake — establish the system (ask, don't assume)

Nothing here is hardcoded. Before analyzing, confirm with the user:

- **File format**: if given a `.pct6` instead of `.afpx`, read
  `references/pct6_format.md` first, then decode with `pct6.decode()` and
  **verify it actually produced `<ATF ...>` XML** before doing anything else —
  don't proceed on faith. If it raises (password-protected, or the key doesn't
  match this PC-Tool version), say so plainly and don't guess further; this
  path is beta and unverified beyond one PC-Tool 6 version.
- **DSP model** and how many channels (read from the `.afpx` — `afpx.py` lists them).
- **Channel map**: run `python afpx.py inspect <file>` to auto-detect roles from
  crossovers, then **show the user and have them confirm/correct** which channel is
  which driver and which side (L/R). The inference is a starting point, not truth.
- **Target curve**: the user supplies their own (any `freq level` text file —
  ResoNix, Harman in-car, personal house curve, flat, etc.); load it with
  `measure.load_target`. **If they have none, default to
  `assets/default_incar_target.txt`** (a gentle downward-tilted in-car curve with a
  bass lift) and tell them that's what you're using and that they can swap in their
  own at any time. Only the shape matters — the tuner anchors overall level itself.
- **What each measurement is**: a system-sum/response is the minimum. Solo drivers,
  L+R "together" pairs, and multi-position sweeps unlock progressively more (pair
  summation analysis, per-side imaging, robustness). Ask what they captured.
- **Listening seat / drive side** (LHD/RHD or "which seat did you measure"): needed
  to interpret near vs far speaker for imaging — never assume it.
- **Measurement method**: fixed-position sweep (phase-valid → usable for timing/APF)
  vs moving-mic/RTA average (magnitude-only → tonal balance only, NOT phase). This
  distinction gates which corrections are allowed (see methodology).
- **Rear-channel routing** (if rear channels exist): ask whether they're a discrete
  feed or a **stereo-difference matrix** (e.g. Rear L = 0.5×FL − 0.5×FR). This isn't
  detectable from crossovers, so it's a separate question from the channel map
  above — and it matters: a matrixed rear reads as silent on mono test content (the
  difference is zero by design) and should be **excluded from front-stage tonal-
  balance decisions**, since it never carries a driver's own direct response.

### 2. Validate the data before trusting it

- Prefer **REW text exports** (explicit axis + phase). If given a `.mdat`, rebuild
  the axis with `measure.reconstruct_axis` and **validate it** against a known
  crossover corner (`measure.validate_axis`) before using it. A wrong axis silently
  ruins everything.
- If solos + a measured "together" trace exist, run `prediction_confidence`: the
  solo model must reproduce the measured sum, or the complex data is misaligned and
  phase decisions must be blocked (re-measure).

### 3. Analyze — classify, don't just subtract

For each region, decide the *type* of problem before proposing a fix
(methodology.md has the rules):

- **Tonal / driver-local** → PEQ (usually a cut) or a shelf if it's a broad tilt.
- **Level imbalance L/R** → gain, not EQ.
- **Phase cancellation at a crossover / L+R null** → polarity → delay → APF ladder,
  NOT a boost.
- **Modal / reflection / spatially-unstable null** → do not correct; report it.
- **Measurement invalid / low confidence** → request a re-measure.

Use the `interference_audit` (power-sum vs measured) to tell a real magnitude dip
from destructive summation. Use `tune_scorecard` for every before/after comparison
so the math is identical each time.

### 3b. Voice the target — the most audible single decision

Do this **before** proposing EQ, because it changes the *goal* the EQ then
matches. The overall tonal tilt is the most audible thing in the whole tune —
more than any individual filter — and matching a curve exactly is not the same
as sounding good. A studio-flat target reliably sounds bright and thin in a
car.

- Run `measure_tilt` on the measured **System Sum** to see where it currently
  sits (dB/octave) and how that compares to the typical good-in-car range
  (~−0.8 to −1.0 dB/oct). Report it in plain language.
- Run `measure_tilt` on the **supplied target** too — if the user handed you a
  studio/flat curve, say so, and note it will likely sound bright before you
  correct toward it.
- Offer to **voice** the target with `voice_target` using the four listener-
  language knobs — tilt (warmer/brighter), bass shelf (more/less weight),
  presence (more forward / laid back), air (more air / tame the top). Present
  these as taste choices with sensible defaults, not as a correction; let the
  user pick. Feed the voiced curve into step 4 exactly like any other target.
- Keep voicing (a taste layer on the *goal*) conceptually separate from
  correction (measurement-driven, toward that goal). Say which is which.

### 4. Propose — jointly, within budget

- Model every candidate edit as a biquad and **predict the summed result** before
  writing (bands within an octave interact — never set gain = −deviation naively).
- Prefer few, broad, low-Q moves. Peaks cost more than dips. Do not fill narrow
  dips. Keep L/R corrections matched unless solos prove the sides genuinely differ.
- Run `headroom_report`; if a boost stack risks clipping, recommend an output trim.
- Present the plan (what, where, why, predicted before→after) before writing.
- **State confidence per claim, not just "objective improved."** A single
  aggregate score hides exactly the judgment calls that matter — whether a
  region is a real, EQ-able problem or something you correctly declined to
  touch. Structure the proposal so each claim carries its own confidence and
  the reasoning behind it, e.g.:

  ```
  - Tonal shape (200 Hz-6 kHz): high confidence — clean solo data, prediction_confidence "high"
  - L/R balance (700 Hz-5 kHz): medium confidence — one-position data only, not spatially averaged
  - 70-95 Hz dip: low confidence — gated measurement, below this gate's ~110 Hz trust floor (gating_warning)
  - 450 Hz dip: left alone — interference_audit flags destructive cancellation, not EQ-able
  - 3.5 kHz L/R asymmetry: rejected — solo traces don't justify a one-sided cut (inert_band_check)
  ```

  This isn't cosmetic — it's the same discipline the restraint doctrine
  already runs on (classify before correcting, know when NOT to touch
  something), just made visible in the final report instead of staying
  implicit in the process.

### 5. Write — verified, conservative

- Only write PEQ (`T=17`), and — when justified and the user agrees — shelves
  (`T=3/4`, end slots only) and all-passes (`T=19/20`). Use the verified writers in
  `tunelib.py`.
- **Never change crossovers or delays unless the user explicitly asks.** Preserve
  them byte-for-byte; verify with `afpx.roundtrip_lint` (semantic, tolerant of
  PC-Tool attribute reordering).
- After writing, decode the new file back and confirm: header valid, delays +
  crossovers unchanged, only the intended slots changed, all gains within limits.
- **Writing a delay is allowed, but only under all of these conditions —
  `afpx.write_delay_samples` being available doesn't lower the bar:**
  1. A specific number came out of `polarity_delay_search` (ideally with
     `xcorr_agrees: True` — if it disagrees with the cross-check, say so and
     don't offer to write it) or was otherwise measured/confirmed.
  2. The user has seen that specific number (in both ms and samples, at the
     unit's *confirmed* sample rate) and explicitly said to apply it — not a
     general "yes, tune it" earlier in the session. Ask again for this
     specific change, same as any other write.
  3. After writing, run `afpx.verify_delay_write` — not just
     `roundtrip_lint` — since it checks the exact value landed and nothing
     else in the file moved, which a delay write specifically needs.
  4. The result is still a *prediction* until the user re-measures with it
     loaded — say so plainly, especially since this is a phase-domain change.

### 6. Hand off — the real proof is the re-measure

State plainly that predictions are from magnitude data; phase edits (APF, delay)
and the final result must be confirmed by re-measuring with the new tune loaded.
Give the user a short, specific re-measure + listening checklist.

## Non-negotiables

1. **Confirm the channel map and seat before analyzing.** Nothing is assumed.
2. **Validate the measurement axis** before trusting a `.mdat`.
3. **Respect hardware limits**: gain per band within the model's range (P SIX:
   −15…+6 dB), Q within range, APF Q 0.5–2, shelf Q 0.1–2. `validate_peq_band`
   enforces this — use it.
4. **Preserve crossovers and delays** unless explicitly told otherwise.
5. **Classify before correcting.** Never boost a null or a reflection. Never EQ a
   phase problem.
6. **Restraint is a feature.** Fewer, broader filters that improve the whole-system
   score beat a pile of narrow fixes that flatter one trace. When unsure, do less.
7. **Verify every write** and be honest about what is predicted vs measured.
8. **Re-decode the current `.afpx` fresh before proposing edits — don't rely on
   memory of an earlier read.** In a long session the user may have changed
   something in PC-Tool between turns; conversation memory can go stale in a way
   the file on disk never does.
9. **Never assume the DSP's internal sample rate.** It's model-specific; confirm it
   before any delay math (`ms_to_samples`/`samples_to_ms`), and keep proposals in
   physical milliseconds first, converting to samples last.
10. **State every proposed change directly in the response** — frequency, gain, Q,
    and (for delays) both milliseconds and samples — not just "I wrote the file, go
    check it." The user should be able to act on your message alone.
