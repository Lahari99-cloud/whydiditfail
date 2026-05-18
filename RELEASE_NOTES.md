# Release Notes

## v0.1.0: Deterministic Replay Foundation

This release establishes WDIF as deterministic causal diagnostics infrastructure for production AI traces.

### Highlights

- Deterministic `.wdif` evidence snapshots.
- SHA-256 snapshot integrity validation.
- Determinism manifests for config, normalization, ranking, span tree, and diagnostics.
- Replay verification with original-vs-replay RCA equality checks.
- Snapshot diffing for regression analysis.
- Causal propagation metadata for upstream/downstream failure chains.
- Bounded ingestion, dead-letter queues, tokenizer routing, and policy-aware exit codes.
- OpenInference and OpenTelemetry example fixtures.

### Release Validation

Recommended release checks:

```bash
python -m pytest -q
python -m compileall wdif tests
wdif snapshot examples/openinference_trace.json --output reports/openinference_trace.wdif --json
wdif replay reports/openinference_trace.wdif --json
wdif diff reports/openinference_trace.wdif reports/openinference_trace.wdif --json
```

Expected replay invariants:

```json
{
  "matches_original": true,
  "snapshot_hash_valid": true,
  "determinism_manifest_valid": true,
  "diagnostic_diff": {
    "changed_count": 0
  }
}
```
