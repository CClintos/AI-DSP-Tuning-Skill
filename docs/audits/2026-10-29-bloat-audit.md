# Bloat audit: what to cut, what to add (1.21.0, 29 Oct 2026)

Question: is `helix-rew-tuner` too bloated, what can be removed without losing
anything, and what would actually help the tune?

**Verdict: the code is not bloated; the documentation and the command surface
are.** Almost all the code is used. The weight that costs something is the
text an agent must read every session, the third of `methodology.md` that
nothing routes to, and 34 commands with overlapping purposes. The 1.21.0
release added to this: 11 commands (9 table rows) and about 4,400 tokens of documentation.

## 1. What was measured

| Item | Size | Who pays |
|---|---|---|
| Shipped package (`helix-rew-tuner.skill`) | 1.28 MB, ~320k tokens if all read | nobody reads it all |
| `SKILL.md` | 4.6 KB, ~1.2k tokens | every request |
| `core_workflow.md` | 50.9 KB, ~12.7k tokens | every tuning request, in full |
| `methodology.md` | 185 KB, ~46k tokens, 72 sections | by section |
| Typical MMM session reading | SKILL + core + MMM-first + single-run sections ≈ 20k tokens | every MMM session |
| Scripts | 22 files, ~990 KB | run, not read |
| Self-test code inside scripts | 99 KB (tunelib alone 54 KB, 888 lines) | package size only |
| `README.md` | 783 lines | humans only (not shipped) |

`core_workflow.md` by section (tokens): command table 1.9k, intake 1.85k,
tunelib function table 1.35k, step 4 1.1k, step 5 1.1k, other scripts 1.0k,
non-negotiables 0.6k, the rest 3.8k.

## 2. Code: not bloated

A call-graph pass from every CLI entry point (test blocks excluded):

| Module | Reached from a command | Only via the documented ad-hoc API | Unused |
|---|---|---|---|
| tunelib | 3,769 lines | 756 | 27 |
| pipeline | 2,837 | — | 43 (doc-ref checker, test only) |
| afpx, measure, mdat, mmm, capture_audit, audible, judging, rew_api, frames, signals | 100% | — | 0 |
| alpine_jssh (beta, contributed) | 450 | 258 | 47 |
| decay | 477 | — | 32 |

Truly unused: about 110 lines (`decay.ir_from_spectrum`, `tunelib.s_at`,
`allpass_H_inv`, `min_gate_for_frequency`, `fil_attrs`,
`loudness.contour_db`, `alpine_jssh.diff_objects` and five unexposed Alpine
setters). Every command is tested except `source-audit` at the CLI (its
function is tested) and `signal-analyze` (its analysis is tested directly).
The self-test code in the scripts (8% of the package) is run by CI and is
the per-environment sanity check, so it earns its place.

## 3. Documentation: the real bloat

**`methodology.md`.** 49.9 KB of its 173 KB of sections (29%) is referenced
from nowhere outside the file: an agent reaches it only through the
contents list. The largest unrouted or weakly routed sections are dated
session stories whose rule is one or two sentences:

| Section | Size | What it is |
|---|---|---|
| Analysis traps (incl. the Alpine session subsection) | 19.7 KB | "caught live (2026-07-14)" case studies |
| When the answer is physical, not electrical | 4.8 KB | install advice (orphan) |
| `polarity_delay_search` says nothing to gain … (and how this was actually found) | 4.0 KB | the story of a second opinion |
| Rear-fill measurement discipline | 3.3 KB | "Real case (2026-08-10)" |
| Common-mode is a first-class objective | 2.9 KB | "A real case (2026-08-09)" |
| 14 further orphans of 1-2.5 KB | ~25 KB | each a rule plus its history |

Many of those rules are already enforced in code (held-out by sitting,
model discrimination, the deep-notch boost guardrail, the identical-operator
rule), so the prose is rationale, not instruction. The contents list itself
is 6.4 KB (1.6k tokens) and is read every time the file is opened.

**`core_workflow.md`.** Necessary routing, but it carries material that is
needed rarely or already lives elsewhere:
- the tunelib function table (5.4 KB) serves ad-hoc analysis "only for
  something no command covers";
- the `.pct6` and Alpine paragraphs under "Other scripts" repeat their own
  format references, which SKILL.md already routes to;
- the intake step explains the session sidecar at length (~2 KB);
- the 11 non-negotiables restate SKILL.md's 8 hard rules (each hard rule
  appears 2-3 times across the two files; keeping one copy for read-only
  tasks in SKILL.md is deliberate);
- the nine 1.21.0 rows are long.

**Repo-only (humans, not agents).** `docs/superpowers/` holds three executed
August plan/spec files (21 KB); `tools/compare_audible_proposals.py` is a
one-off comparison pinned to commit `1712a3a`; the README's version history
sits in a section called "Audible tuning paths", and its 230-line "How it
actually works" essay repeats the methodology.

## 4. Command surface

34 user-facing commands; `analyze`, `propose` and `refine` take 21-23 flags
each. They cluster by goal, and within a cluster the right tool depends on
what was captured:

| Goal | Commands |
|---|---|
| Bass alignment | `bass-trials` (timed solos), `mmm-align` (MMM), `mmm-compare` (captured candidates), `probe`, `junction` |
| L/R | `lr-match`, `stereo-propose`, `coherence`, `imaging` |
| Blind A/B | `voice-variants`, `voice-match`, `ab-make`, `ab-result`, `prefs` |
| Capture quality | `capture-audit`, `noise-check`, `--ambient` / `--noise-floor` |
| Voicing | `--voice`, `voice-variants`, `listening-level`, `road-noise` |
| Judging | `quality-check`, `audible-study`, analyze's judging block |

The risk is not size but choice: an agent picking the wrong tool for the data
it has. Merging commands in code would be churn; a per-goal decision table and
a command that reads the files and names the applicable tools (A2 below)
remove the choice instead.

The weakest-justified commands are 1.21.0's own `test-signal` and
`signal-analyze`: experimental, simulation-checked only, and in the main
command table.

## 5. Recommended cuts (no rule or capability lost)

| # | Cut | Saves | Risk |
|---|---|---|---|
| C1 | `core_workflow.md`: move the tunelib table to `references/tunelib_api.md` (read on demand); cut the `.pct6`/Alpine paragraphs to one routing line each; shorten the sidecar text; drop non-negotiables that only restate SKILL.md; tighten the 1.21.0 rows | ~12 KB, ~3k tokens per session (−24%) | low; check with the activation and scenario evals |
| C2 | `methodology.md`: rewrite each case study as rule + one-line reason, move the stories to `docs/case-notes.md` (not shipped); flatten the contents list | ~60-75 KB (−35-45%), ~1-2k tokens per section read | medium: section names must survive (`check_doc_refs`), one section per edit |
| C3 | Take `test-signal` / `signal-analyze` out of the core command table (keep the code and the methodology note) until a real-car check | ~200 tokens, one fewer wrong turn | none |
| C4 | Delete the ~110 unused lines | small | none |
| C5 | Repo-only: delete `docs/superpowers/` and `tools/compare_audible_proposals.py`; move README version history to `CHANGELOG.md`; cut the README essay to a link | humans only | none |

Not recommended: moving self-tests out of the scripts (CI and the
environment check use them), or merging overlapping commands in code.

## 6. Additions that would actually improve the tune

Ranked by expected effect on the end result, from what the real captures
showed.

**A1. `capture-plan`: fix the weakest link before it happens.** Every real
session reviewed had captures of 5-11 s, movement noise as loud as the signal,
mixed smoothing, mixed RTA resolution, or a clipping mic, and the audit can
only report that afterwards. A command that, from the `.afpx` and the goal,
prints the exact capture list with names `capture-audit` recognises, the REW
settings (1/48, FFT, window, peak hold with no decay, "Save both"), the
averages needed for 20 s at REW's overlap, a level window between the
movement floor and the mic's clip point, the τ1 for `mmm-align` from the
tune's crossover, and the RAW/XO/EQ sequence for `xo-check`. Low effort; it
improves every analysis downstream.

**A2. `next`: one command that reads the files and names what can run.**
Given a folder or `.mdat` (and optionally the tune), it runs the audit,
groups the captures (triples, twins, RAW/XO/EQ, peak traces, sweeps vs RTA)
and prints the applicable commands with their exact arguments. That lets
`core_workflow.md` shrink further and stops tool-choice mistakes.

**A3. Real-capture regression fixtures.** Synthetic tests (423 of them in
1.20.0) missed two real-file bugs: the `.mdat` reader, and the header parser
reading REW's Format line ("…no smoothing and 31 averages") as the export
smoothing, so every real RTA export read as smoothed. A small set of real
exports, scrubbed and shared with the owner's consent, would have caught
both. The 14 July text exports carry no file paths.

**A4. One validation evening.** `mmm-align`, the peak-trace stability map,
`frames` and the test signals are simulation-checked only. A fixed protocol
(timed sweeps plus the four MMM captures at one junction, two runs with peak
traces, one WAV-recorded pass) decides whether each is trusted, kept as
advisory, or removed. Until then they stay labelled.

**A5. Run the agent evals live before trimming (earlier audit, F13).** The
activation and scenario sets exist but have never run against a live agent.
Running them before and after C1/C2 shows the cuts did not change behaviour.

Still open from the 2026-10-22 audit: F1, the level-anchor bias (three
fixes tried and rejected). It is the main known correctness gap, but needs a
design, not a trim.

## 7. Suggested order

1. C3, C4, C5 and A1 (low risk, immediate).
2. A5 baseline, then C1, then A5 again.
3. A2, which makes more of C1 possible.
4. C2, section by section.
5. A3 when the owner agrees which captures may be published; A4 at the
   next car session.

## 8. Implementation record (1.22.0, same day)

Two findings above were wrong and were corrected before acting on them:

- **Dead code.** The ~110 "unused" lines are not dead: `s_at`, `fil_attrs`,
  `allpass_H_inv`, `min_gate_for_frequency` and `decay.ir_from_spectrum` are
  used by other helpers or by the self-tests, and `alpine_jssh.diff_objects`
  is a post-write verification helper. C4 was dropped; the code has no real
  dead weight.
- **Non-negotiables.** They cannot be cut back to what SKILL.md lacks:
  `AGENTS.md`, which Codex reads, is generated from `core_workflow.md` alone,
  so every hard rule must stay there too. A test now enforces it.

| Item | Done | Result |
|---|---|---|
| C1 core_workflow | tunelib table to `references/tunelib_api.md`; beta-format paragraphs to one line; sidecar text halved; step 7 routed through `verify` (it used to send agents to ad-hoc `tunelib` calls); my 1.21.0 rows shortened; a decision table by what was captured and two new rows added | 50.9 → 43.8 KB (−14%), ~1.8k fewer tokens per session with the additions included |
| C2 methodology | ten case-study sections condensed to rule + reason, headings unchanged; full originals in `docs/case-notes.md` (not shipped) | 184 → 158 KB (−15%). Less than the 35-45% estimated: the remaining long sections are doctrine, not stories |
| C3 | `test-signal` / `signal-analyze` out of the core command table | experimental tools stay documented in methodology only |
| C5 | `docs/superpowers/` and `tools/compare_audible_proposals.py` deleted; README essay → `docs/how-it-works.md`, developer notes → `docs/development.md` (test list now generated from the files; the old one was missing several), version notes → `CHANGELOG.md` | README 783 → 460 lines |
| A1 | `pipeline.py capture-plan` | tested against a synthetic tune; on the real 14 July tune it plans 140 averages for 25 s, a 100 dB SPL mic ceiling and a 3.12 ms T1 on the midbass channels, and keeps every tweeter and midrange high-pass |
| A2 | `pipeline.py next` | on the real 14 July set every command it printed ran; on the 15 July `.mdat` it routes the RAW/XO/EQ captures to `xo-check` and the sweeps to `imaging`; a test runs every printed command |
| A3 | `tests/fixtures/real/` (eight 14 July exports, unchanged; one `.mdat`, the Windows user name in a cal path replaced byte for byte) and `tests/test_real_captures.py` | pins the smoothing read, the header fields, the `.mdat` axis, the audit's findings and the coherence results; 1.20.0 fails the smoothing test |
| A5 (substitute) | `DoctrinePreservationTests`: every hard rule in core_workflow, every condensed rule in methodology, every story in the case notes | the live-agent evals still need a live run |
| — | `xo-check --section` and a PEQ-only mode (no RAW, as a tweeter needs); `capture-audit` pairs L/R halves with the right "both" capture | — |

Not done: A4 (needs a car) and live-agent evals (need fresh agent sessions).
