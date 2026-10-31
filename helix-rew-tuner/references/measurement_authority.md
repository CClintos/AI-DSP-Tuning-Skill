# MMM measurement authority and real-car replay

## What a capture can establish

`frames` exports a full-pass mean, a robust mean, a peak trace and two halves.
All exports from the same WAV or REW API recording carry the same SHA-256
`capture_id`. The halves test coverage and drift **within one pass**. They are
not separate repeat measurements. Run the whole moving-mic path again to
estimate pass-to-pass repeatability. `mmm-compare --repeat` and
`--candidate-repeat`, and multi-position MMM analysis, reject matching known
capture IDs. `verify --capture mmm` also pools repeated full passes in power.
Legacy files without an ID are allowed but their provenance must
be checked by the operator.

For two or more independent MMM passes, the session reference is the equal-pass
mean in **linear power**, converted back to dB. This retains absolute level.
Fixed microphone positions and nearby head-area measurements keep their
spatial consistency treatment; they are not pooled as repeated MMM passes.
Keep playback level, volume, source and microphone path controlled across
the passes. Preserve each original capture.

Candidate reports use the same fixed pre-change target anchor and
`judging.scorecard` before and after where a measured comparison is available.
Regional guards still apply. This score is an objective heuristic, not a
demonstrated listening preference. A small score change beneath repeatability
does not establish a better sound.

## Replay private real-car sessions

`python scripts/pipeline.py corpus-check --spec corpus.json --out report.json`
reads a local JSON index and its captures; it does not upload them. Relative
capture and target paths are resolved beside the index. Each capture's SHA-256
must match the index. Use complete, independent before and after passes and
matched-level blind listening trials. Keep private recordings outside the
distributed skill archive.

```json
{
  "version": 1,
  "sessions": [
    {
      "session_id": "car-a-2026-11-01-eq-01",
      "vehicle_id": "car-a",
      "listener_id": "listener-a",
      "split": "development",
      "target": "target.txt",
      "target_sha256": "64 lowercase hex characters",
      "before": [{"file": "before-pass-1.txt", "sha256": "64 lowercase hex characters"}],
      "after": [{"file": "after-pass-1.txt", "sha256": "64 lowercase hex characters"}],
      "blind_trials": [
        {"track": "track-a", "preferred": "after"}
      ]
    }
  ]
}
```

Use real hashes in place of the placeholders. Repeated captures can be added
to either list. The same file hash cannot appear twice in one session, even
under different names. All sessions for one vehicle/listener pair must stay
in one split. Reserve `held_out` pairs before changing weights or thresholds;
do not tune on their outcomes. Report objective and blind outcomes by
vehicle/listener, since tracks and repeated trials are not independent people.
The repository currently contains no real-car preference corpus. Thus no new
universal scoring weights or audible-gain claim is justified yet.
