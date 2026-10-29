# Development

Everything outside the shipped `helix-rew-tuner/` folder: build tools, evaluations, audits, tests and the release gate. The skill itself is described in the [README](../README.md).

```
tools/
└── build_skill.py                    generated-wrapper/package drift check and writer

evals/
├── README.md                         three-layer evaluation plan and pass bars
├── activation.json                   should / should-not trigger prompts
├── scenarios.json                    agent-behaviour scenarios, rubric, critical failures
└── make_fixtures.py                  synthetic tune + REW fixtures for the scenarios

docs/audits/                          dated skill audits and what each one changed

tests/                                one file per area; each file's docstring says what it covers
├── test_audible.py
├── test_audible_study.py
├── test_build_skill.py
├── test_calibration_cases.py
├── test_capture_intelligence.py
├── test_codec_and_loader_integrity.py
├── test_delay_consensus.py
├── test_emma_prep.py
├── test_held_out_validation.py
├── test_imaging_phase_and_windows.py
├── test_judging.py
├── test_mmm_capability.py
├── test_mmm_capture.py
├── test_mmm_confirmation.py
├── test_mmm_decisions.py
├── test_phase_control_write.py
├── test_pipeline_apply.py
├── test_preflight_and_benchmark.py
├── test_probe.py
├── test_propose.py
├── test_refine_ab_crossover.py
├── test_registered_average_and_excursion.py
├── test_review_fixes.py
├── test_rew_api.py
├── test_session_file.py
├── test_skill_evals.py
├── test_source_and_imaging.py
├── test_timing_and_evidence.py
├── test_tunelib_regressions.py
└── test_vehicle_rules.py
```

Run the complete unit/integration suite with:

```text
python -m unittest discover -s tests -p "test_*.py" -v
```

The self-test-capable DSP/file scripts also run standalone without real
measurement or tune files:

```
python helix-rew-tuner/scripts/tunelib.py    # -> ALL TESTS PASSED
python helix-rew-tuner/scripts/afpx.py selftest
python helix-rew-tuner/scripts/pct6.py selftest
python helix-rew-tuner/scripts/alpine_jssh.py selftest
python helix-rew-tuner/scripts/pipeline.py selftest
python helix-rew-tuner/scripts/decay.py selftest
python helix-rew-tuner/scripts/repeatability.py selftest
```

Preflight, benchmark, and generated-package checks are separate executable
gates:

```text
python helix-rew-tuner/scripts/preflight.py --json
python helix-rew-tuner/scripts/benchmark.py --json
python tools/build_skill.py --check
```

GitHub Actions runs this full release gate on Windows and Linux with Python
3.10 and 3.13 for every push and pull request. It also compiles all Python
sources, runs the official skill validator, and rejects generated-package or
whitespace drift.

The unit suite includes the deterministic layer of the skill evaluation
(`tests/test_skill_evals.py`). The activation and agent-behaviour layers need
a live agent and are run before a release; [`evals/README.md`](../evals/README.md)
explains the scenarios, the rubric and the pass bars. Two known-answer cases
are marked as expected failures until the fitter floats the target level (see
[`docs/audits/2026-10-22-skill-audit.md`](../docs/audits/2026-10-22-skill-audit.md),
finding F1).
