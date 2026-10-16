---
name: helix-rew-tuner
description: >-
  Use when preparing measurements, diagnosing, tuning, or verifying Helix /
  Audiotec Fischer car-audio DSP systems; editing or validating `.afpx` or beta
  `.pct6` tune files; or handling supported beta Alpine `.jssh` presets,
  crossover, imaging, bass, phase, level, target-curve, or measurement-quality
  problems.
metadata:
  version: "1.14.0"
---

# Helix / REW measurement-driven auto-tuner

Use this skill for supported Helix, Audiotec Fischer, and beta Alpine car-audio
DSP work, from preparing a first measurement to refining a measured tune.

Before analyzing data, proposing changes, or writing a tune, read
`references/core_workflow.md` in full and follow it as the canonical workflow.
Paths in that workflow are relative to this skill directory. Read each routed
format or methodology reference before its first required operation.

For a new installation or a user without measurements, follow
`references/first_tune.md` for foundation checks, REW setup and the first capture
set. The workflow comes before the optional catalogue in
`references/tool_reference.md`; load only the entries needed for the current step.

Alpine `.jssh` support remains part of this skill. Treat it as beta and follow
the format-specific preflight, writable-limit, Q-snap, preservation, and
hardware read-back requirements in `references/alpine_jssh_format.md`.
