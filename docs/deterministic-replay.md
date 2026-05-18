# Deterministic Replay Architecture

WDIF replay exists to answer one question:

```text
Can the same trace evidence reproduce the same RCA result later?
```

Replay is not just trace storage. A valid replay must preserve the span tree, diagnostic output, ranking order, configuration, normalization assumptions, dependency provenance, and integrity hashes.

## Snapshot Flow

```text
trace file
  -> parse and normalize spans
  -> run deterministic heuristics
  -> rank diagnostics
  -> attach causal propagation metadata
  -> build determinism manifest
  -> hash snapshot payload
  -> write .wdif evidence snapshot
```

The replay path reads the `.wdif` file, validates integrity, reconstructs spans from snapshot form, reruns RCA, and compares the new output with the original snapshot output.

## Replay Contract

A replay is considered trustworthy only when:

- `snapshot_hash_valid` is `true`,
- `determinism_manifest_valid` is `true`,
- `matches_original` is `true`,
- `diagnostic_diff.changed_count` is `0`.

If any of these fields fail, the snapshot is still useful as evidence, but it is no longer proof of deterministic RCA equality.

## Determinism Manifest

The manifest captures the inputs that can affect RCA reproducibility:

- schema version,
- Python and platform versions,
- tokenizer dependency versions,
- config hash,
- span tree hash,
- diagnostics hash,
- normalization hash,
- ranking hash.

This makes replay correctness stricter than "same spans." WDIF treats replay correctness as "same evidence plus same RCA semantics."

## Failure Modes

- A changed snapshot hash means the evidence file was modified.
- A changed manifest means the replay environment or RCA assumptions drifted.
- A changed diagnostic diff means the engine no longer reproduces the original finding set.
- A changed ranking hash means the same findings may now be prioritized differently.

## Verification

Replay behavior is covered by `tests/test_replay.py`, including:

- snapshot creation and replay equality,
- tamper detection,
- manifest drift detection,
- snapshot diffing,
- CLI round trips for `snapshot`, `replay`, and `diff`.
