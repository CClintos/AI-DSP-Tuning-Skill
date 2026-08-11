# Tune plan schema version 1

The tune-plan path is the deterministic write boundary for Helix `.afpx` files.
It never modifies the source or overwrites an existing output. `pipeline.py
apply` validates the complete plan and source hash before creating a temporary
file, decodes and verifies that file, and only then exclusively creates the
requested new output path.

## Required top-level fields

Version 1 is a JSON object with exactly these fields:

| Field | Type | Meaning |
|---|---|---|
| `version` | integer | Must be `1`. |
| `source_path` | string | Source `.afpx`; relative paths in a saved plan are resolved from the plan file's directory. |
| `source_sha256` | string | Lower- or upper-case 64-digit SHA-256 of the source bytes. Apply refuses a stale hash. |
| `format` | string | Must be `"afpx"`. `.pct6` and Alpine writes are not enabled by this schema. |
| `output_path` | string | A different, not-yet-existing `.afpx` path. |
| `edits` | array | One or more edit objects described below. |
| `confirmations` | object | Edit ID to JSON boolean. Protected edits require their own value to be exactly `true`. |

Unknown fields, edit kinds, duplicate edit IDs, duplicate targets, empty edit
lists, nonexistent slots/channels, and unsupported filter types are refused.
Every edit must change its in-memory input; no-op filter-slot, delay, and output
trim requests are refused during validation before a file is staged.
Crossover and polarity edits are not part of version 1 and are always refused.

## Edit objects

Every edit has a unique non-empty string `id`, a `kind`, and a zero-based
integer `channel`.

### Filter slot

```json
{
  "id": "peq-front-left-1",
  "kind": "filter_slot",
  "channel": 0,
  "slot": 7,
  "type_code": "17",
  "F": 315.0,
  "Q": 1.2,
  "G": -2.5
}
```

At least one of `type_code`, `F`, `Q`, or `G` is required. Omitted attributes
remain unchanged. Supported type codes are free/off (`1`), PEQ (`17`), low and
high shelf (`3`, `4`), and first- and second-order all-pass (`19`, `20`).
Crossovers (`9`, `15`, `16`) cannot be targeted or created. PEQ values must be
within 20-20000 Hz, Q 0.5-15, and gain -15 to +6 dB. Low/high shelves are
limited to the existing `dF=25`/`dF=20000` end slots, Q 0.1-2, gain -15 to +6
dB, and 0.25 dB gain steps. A first-order all-pass (`19`) accepts no Q edit; its
stored Q is non-functional and gain must be 0 dB. A second-order all-pass (`20`)
requires positive Q (there is deliberately no invented upper cap) and 0 dB
gain. All writable active filters require a 20-20000 Hz frequency. Editing or
creating a shelf or all-pass is protected and requires
`confirmations[edit.id] = true`.

### Delay in samples

```json
{
  "id": "delay-front-left",
  "kind": "delay_samples",
  "channel": 0,
  "samples": 96
}
```

`samples` is an exact non-negative integer. The value must already have been
derived at the DSP's confirmed sample rate and shown to the user. Every delay
edit is protected and requires its own `true` confirmation. Version 1 refuses
a delay and a filter-slot edit on the same channel in one plan, avoiding a
phase change combined with a PEQ prediction based on the old summed response.

### Relative output trim

```json
{
  "id": "trim-front-left",
  "kind": "output_trim",
  "channel": 0,
  "trim_db": -1.5
}
```

`trim_db` is relative to the current channel output level and must be between
-6 and 0 dB. It can only attenuate. The channel must already contain a `<Vol>`
tag. Every trim edit is protected and requires its own `true` confirmation.

## Example plan and commands

Create an empty, source-hashed draft:

```powershell
python helix-rew-tuner/scripts/pipeline.py plan `
  --source .\baseline.afpx `
  --output .\baseline-planned.afpx `
  --out .\tune-plan.json
```

After adding reviewed edits and per-change confirmations, apply it:

```powershell
python helix-rew-tuner/scripts/pipeline.py apply --plan .\tune-plan.json
```

Apply reads one immutable source-byte snapshot. The plan hash is checked against
that snapshot, and both validation and application decode those exact bytes.
Immediately before exclusive output creation, apply also re-hashes the current
source path and refuses if it changed during validation/application; this final
check is a mutation guard and never becomes the apply input. Exclusive creation
also refuses an output path that appears after validation instead of replacing it.
Apply prints a JSON manifest with source/output hashes, normalized edits, each
matching writer verification, `roundtrip_lint`, and
`"predicted_not_measured": true`. Loading the output into the DSP and
re-measuring remains the proof of the acoustic result.
